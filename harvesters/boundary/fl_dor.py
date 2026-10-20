"""Florida DOR Property Tax Oversight county parcel shapefiles: the reader and
the identifier rules the Parcel Shapefiles Readme documents (reviewed by the
product owner on 2026-10-20; data/source_approvals.csv records the caveats
and how each is handled).

What is read
* Boundary geometry from a county's PIN shapefile, with exactly one
  attribute decoded: PARCELNO (and CO_NO, when the file carries it, only to
  check the file is the county it was given as). Every other DBF column is
  skipped unread. A PAR file (assessment attributes on the same polygons) is
  refused unless the caller explicitly allows its geometry; its attributes
  are never decoded either way.
* PARCELNO must be a DBF character field. A numeric field would have lost
  leading zeros, which is the formatting problem the Readme warns about for
  CSV copies, so such a file is refused instead of being joined.
* A separate condominium file (Miami-Dade, St. Johns) is never ingested as a
  parcel boundary.

How a property is joined (no reformatting anywhere)
* The key on our side is the exact NAL PARCEL_ID already VALIDATED for the
  record: the `matched_parcel_id` recorded in `field_provenance` when the
  record matched the statewide tax-roll layer exactly
  (scripts/enrich_property_details.py). A record without one, or with two
  different ones, is not joined: our listing's own parcel spelling is never
  reformatted into a guess.
* The key on the file's side is PARCELNO exactly as the DBF stores it (only
  the DBF's right-padding removed).
* They match only when the strings are equal. Before any match is used, the
  read checks that the file's identifier shapes include the shapes of the
  validated ids for that county (`format_check`); otherwise the county's
  join is reported NOT VALIDATED and nothing is attached.

Records never attached to a parcel polygon
* DOR use code 04 (condominium): a unit has no polygon of its own; the parcel
  polygon is the common land. In Miami-Dade and St. Johns the condominium
  records live in a separate file, so they are reported as such.
* DOR use code 94 (right-of-way): road / utility corridors, conservatively
  never attached.

Features never attached to a property
* No PARCELNO (rights-of-way, water, unparcelled areas, a redacted
  identifier): kept out, counted.
* Several features with one PARCELNO (stacked / phantom polygons) and one
  geometry shared by several PARCELNOs (multi-parcel polygons): see
  harvesters/boundary/plan.py.

Standard library only.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import projection, shapefile
from .projection import UnsupportedProjection
from .shapefile import ShapefileError

IDENTIFIER_FIELD = "PARCELNO"
COUNTY_FIELD = "CO_NO"
VARIANTS = ("PIN", "PAR")
CONDO_USE_CODES = frozenset({"04"})
RIGHT_OF_WAY_USE_CODES = frozenset({"94"})
CONDO_SEPARATE_FILE_COUNTIES = frozenset({"Miami-Dade", "St. Johns"})
NAL_PROVENANCE_SOURCE = "fdor_nal"

# Standard FL DOR county numbering, 11-77 (the same table as
# scripts/enrich_property_details.py COUNTY_CODES; a test pins them equal).
COUNTY_CODES = {
    "Alachua": 11, "Baker": 12, "Bay": 13, "Bradford": 14, "Brevard": 15,
    "Broward": 16, "Calhoun": 17, "Charlotte": 18, "Citrus": 19, "Clay": 20,
    "Collier": 21, "Columbia": 22, "Miami-Dade": 23, "DeSoto": 24, "Dixie": 25,
    "Duval": 26, "Escambia": 27, "Flagler": 28, "Franklin": 29, "Gadsden": 30,
    "Gilchrist": 31, "Glades": 32, "Gulf": 33, "Hamilton": 34, "Hardee": 35,
    "Hendry": 36, "Hernando": 37, "Highlands": 38, "Hillsborough": 39,
    "Holmes": 40, "Indian River": 41, "Jackson": 42, "Jefferson": 43,
    "Lafayette": 44, "Lake": 45, "Lee": 46, "Leon": 47, "Levy": 48,
    "Liberty": 49, "Madison": 50, "Manatee": 51, "Marion": 52, "Martin": 53,
    "Monroe": 54, "Nassau": 55, "Okaloosa": 56, "Okeechobee": 57,
    "Orange": 58, "Osceola": 59, "Palm Beach": 60, "Pasco": 61,
    "Pinellas": 62, "Polk": 63, "Putnam": 64, "St. Johns": 65,
    "St. Lucie": 66, "Santa Rosa": 67, "Sarasota": 68, "Seminole": 69,
    "Sumter": 70, "Suwannee": 71, "Taylor": 72, "Union": 73, "Volusia": 74,
    "Wakulla": 75, "Walton": 76, "Washington": 77,
}


def exact_key(value) -> str:
    """The join key: the identifier exactly as written, minus trailing
    padding. Leading zeros, inner spaces, dashes, dots and case are kept."""
    if value is None:
        return ""
    return str(value).rstrip(" \x00")


def identifier_shape(value) -> str:
    """Value-free shape of an identifier (digit runs -> d<n>, letter runs ->
    A<n>, separators kept), the same notation enrich_property_details.py
    prints."""
    text = exact_key(value)
    return re.sub(r"\d+|[A-Za-z]+", lambda m: ("d" if m.group(0)[0].isdigit() else "A") + str(len(m.group(0))),
                  text) or "(blank)"


# --- our side ---------------------------------------------------------------

def nal_parcel_id(row: dict) -> tuple[str | None, str]:
    """(the validated NAL PARCEL_ID, '') or (None, reason)."""
    prov = row.get("field_provenance") or {}
    if isinstance(prov, str):
        import json  # noqa: PLC0415
        try:
            prov = json.loads(prov)
        except ValueError:
            prov = {}
    ids = {exact_key(e.get("matched_parcel_id")) for e in prov.values()
           if isinstance(e, dict) and e.get("source") == NAL_PROVENANCE_SOURCE and exact_key(e.get("matched_parcel_id"))}
    if not ids:
        return None, "NO_VALIDATED_NAL_ID"
    if len(ids) > 1:
        return None, "CONFLICTING_NAL_IDS"
    return next(iter(ids)), ""


def record_exclusion(row: dict, county: str) -> str:
    """Why a record is never attached to a parcel polygon, or ''."""
    use = exact_key(row.get("dor_use_code")).strip()
    if use in CONDO_USE_CODES:
        return "CONDO_UNIT_SEPARATE_FILE" if county in CONDO_SEPARATE_FILE_COUNTIES else "CONDO_UNIT"
    if use in RIGHT_OF_WAY_USE_CODES:
        return "RIGHT_OF_WAY"
    return ""


def prepare_records(rows: list[dict], county: str) -> tuple[list[dict], dict]:
    """The records that may be joined (each with `nal_parcel_id`) and the
    counts of the ones that may not, by reason."""
    eligible, counts = [], {}
    for row in rows:
        reason = record_exclusion(row, county)
        key = None
        if not reason:
            key, reason = nal_parcel_id(row)
        if reason:
            counts[reason] = counts.get(reason, 0) + 1
            continue
        eligible.append(dict(row, nal_parcel_id=key))
    return eligible, counts


# --- the file's side ----------------------------------------------------------

@dataclass
class CountyRead:
    status: str                         # COMPLETE | FAILED | REFUSED
    county: str
    reason: str = ""
    dataset: str = ""
    dataset_date: str | None = None     # the DBF's own last-update date
    crs: str = ""
    features: list[dict] = field(default_factory=list)
    counts: dict = field(default_factory=dict)


def read_county(path, county: str, *, variant: str = "PIN", allow_par_geometry: bool = False) -> CountyRead:
    """Read one county's DOR parcel shapefile into GeoJSON features carrying
    PARCELNO and a feature id. Never raises: a problem is a FAILED or REFUSED
    read, which the refresh treats as 'write nothing'."""
    if county not in COUNTY_CODES:
        return CountyRead("REFUSED", county, "UNKNOWN_COUNTY")
    variant = (variant or "").upper()
    if variant not in VARIANTS:
        return CountyRead("REFUSED", county, "UNKNOWN_VARIANT")
    if variant == "PAR" and not allow_par_geometry:
        return CountyRead("REFUSED", county, "PAR_FILE_NOT_ALLOWED")
    name = str(path).lower()
    if "condo" in name:
        return CountyRead("REFUSED", county, "CONDOMINIUM_FILE_NOT_INGESTED")
    try:
        shp = shapefile.read(path, wanted_fields=(IDENTIFIER_FIELD, COUNTY_FIELD),
                             wanted_char_fields=(IDENTIFIER_FIELD,))
        crs = projection.parse_prj(shp.prj)
    except (ShapefileError, UnsupportedProjection, OSError) as exc:
        return CountyRead("FAILED", county, type(exc).__name__ + ": " + str(exc))
    expected = COUNTY_CODES[county]
    out = CountyRead("COMPLETE", county, dataset=f"DOR PTO {variant} parcel shapefile {shp.name}",
                     dataset_date=shp.dbf_date.isoformat() if shp.dbf_date else None, crs=crs.kind)
    counts: dict = {}
    for i, (rec, rings) in enumerate(zip(shp.records, shp.shapes)):
        co = rec.get(COUNTY_FIELD, "")
        if co.strip():
            try:
                co_no = int(float(co))
            except ValueError:
                co_no = None
            if co_no != expected:
                return CountyRead("FAILED", county, f"WRONG_COUNTY: CO_NO {co.strip()} is not {expected}")
        key = exact_key(rec.get(IDENTIFIER_FIELD))
        if not key.strip():
            counts["NO_PARCELNO"] = counts.get("NO_PARCELNO", 0) + 1
            continue
        if rings is None:
            counts["NULL_SHAPE"] = counts.get("NULL_SHAPE", 0) + 1
            continue
        parts = shapefile.rings_to_multipolygon(rings)
        if parts is None:
            counts["INVALID_RINGS"] = counts.get("INVALID_RINGS", 0) + 1
            continue
        try:
            coords = [[[list(projection.to_lonlat(crs, x, y)) for x, y in ring] for ring in poly] for poly in parts]
        except (ValueError, ZeroDivisionError, OverflowError):
            counts["PROJECTION_FAILED"] = counts.get("PROJECTION_FAILED", 0) + 1
            continue
        out.features.append({"type": "Feature",
                             "properties": {IDENTIFIER_FIELD: key, "FEATURE_ID": f"{shp.name}#{i + 1}"},
                             "geometry": {"type": "MultiPolygon", "coordinates": coords}})
    out.counts = counts
    return out


def format_check(records: list[dict], features: list[dict]) -> tuple[bool, str]:
    """Whether the file's PARCELNO format is the format of the validated ids.
    True when at least one validated id's shape occurs among the file's
    identifier shapes; a county whose shapes never overlap is NOT VALIDATED
    and nothing is attached. Value-free: shapes only."""
    ours = {identifier_shape(r.get("nal_parcel_id")) for r in records if r.get("nal_parcel_id")}
    theirs = {identifier_shape(f["properties"].get(IDENTIFIER_FIELD)) for f in features}
    if not ours:
        return False, "NO_VALIDATED_IDS"
    if not theirs:
        return False, "NO_IDENTIFIED_FEATURES"
    if not ours & theirs:
        return False, "FORMAT_MISMATCH: validated ids " + ",".join(sorted(ours)) + " vs file " + ",".join(sorted(theirs)[:5])
    return True, ""
