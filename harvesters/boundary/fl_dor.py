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

The shapefile itself is read by harvesters/boundary/shapefile.py (pyshp, and
pyproj for the reprojection to WGS84).
"""
from __future__ import annotations

import math
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from . import shapefile

IDENTIFIER_FIELD = "PARCELNO"
COUNTY_FIELD = "CO_NO"
VARIANTS = ("PIN", "PAR")
CONDO_USE_CODES = frozenset({"04"})
RIGHT_OF_WAY_USE_CODES = frozenset({"94"})
CONDO_SEPARATE_FILE_COUNTIES = frozenset({"Miami-Dade", "St. Johns"})
NAL_PROVENANCE_SOURCE = "fdor_nal"
# Florida's extent (harvesters/enrichment/geocode.py STATE_BOUNDS): lat min/max, lon min/max.
FLORIDA_BOUNDS = (24.0, 31.5, -88.0, -79.5)
# How far a matched polygon may lie from the record's own stored point before
# the match is refused: catches a wrong polygon, tolerates an address geocode.
LOCATION_TOLERANCE_M = 1000.0

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


# How a record was joined (stored in parcel_boundaries.match_method):
# * EXACT_PARCEL_ID - the record's validated NAL PARCEL_ID equals PARCELNO;
# * PARCEL_NUMBER_LOCATION_CONFIRMED - the listing's own parcel number with
#   separators removed (case ignored, every digit and leading zero kept) equals
#   exactly one PARCELNO value in the county file, AND the record's own stored
#   point lies inside that polygon. Chosen by the product owner on 2026-10-22
#   for Florida Available records, most of which carry no validated NAL id.
METHOD_VALIDATED = "EXACT_PARCEL_ID"
METHOD_LISTING = "PARCEL_NUMBER_LOCATION_CONFIRMED"
LISTING_KEY_MIN, LISTING_KEY_MAX = 4, 40


def separators_removed(value) -> str:
    """The listing-join key: letters and digits only, upper case. Leading
    zeros and every digit are kept; only separators (dashes, spaces, dots,
    slashes) and case are ignored."""
    return re.sub(r"[^A-Za-z0-9]", "", "" if value is None else str(value)).upper()


def _point(row: dict) -> tuple[float, float] | None:
    try:
        lat, lon = float(row.get("latitude")), float(row.get("longitude"))
    except (TypeError, ValueError):
        return None
    return (lon, lat) if math.isfinite(lat) and math.isfinite(lon) else None


def prepare_records(rows: list[dict], county: str, *, listing_join: bool = False) -> tuple[list[dict], dict]:
    """The records that may be joined and the counts of the ones that may not,
    by reason. A record with a validated NAL id joins on it (join_key set).
    With listing_join, a record without one may join on its listing parcel
    (listing_key set; join_key is resolved against the file later and the
    record must carry its own point, which has to fall inside the polygon)."""
    eligible, counts = [], {}
    for row in rows:
        reason = record_exclusion(row, county)
        key = None
        if not reason:
            key, reason = nal_parcel_id(row)
        if key:
            eligible.append(dict(row, nal_parcel_id=key, join_key=key, join_method=METHOD_VALIDATED))
            continue
        if listing_join and reason == "NO_VALIDATED_NAL_ID":
            lk = separators_removed(row.get("parcel"))
            if not (LISTING_KEY_MIN <= len(lk) <= LISTING_KEY_MAX and any(ch.isdigit() for ch in lk)):
                reason = "NO_USABLE_LISTING_PARCEL"
            elif _point(row) is None:
                reason = "NO_RECORD_POINT"
            else:
                eligible.append(dict(row, listing_key=lk, join_key=None, join_method=METHOD_LISTING))
                continue
        counts[reason] = counts.get(reason, 0) + 1
    return eligible, counts


def resolve_listing_keys(records: list[dict], features: list[dict]) -> tuple[list[dict], dict]:
    """Give each listing-joined record the file's own PARCELNO spelling, when
    exactly one PARCELNO value in the file has the same separators-removed
    form. None -> LISTING_UNMATCHED; several -> LISTING_FORMAT_AMBIGUOUS."""
    spellings: dict = {}
    for f in features:
        raw = f["properties"].get(IDENTIFIER_FIELD)
        spellings.setdefault(separators_removed(raw), set()).add(raw)
    out, counts = [], {}
    for r in records:
        if r.get("join_method") != METHOD_LISTING:
            out.append(r)
            continue
        raws = spellings.get(r["listing_key"], set())
        if len(raws) == 1:
            out.append(dict(r, join_key=next(iter(raws))))
            continue
        why = "LISTING_UNMATCHED" if not raws else "LISTING_FORMAT_AMBIGUOUS"
        counts[why] = counts.get(why, 0) + 1
    return out, counts


def point_in_multipolygon(lon: float, lat: float, geom) -> bool:
    """Even-odd test over every ring of a GeoJSON MultiPolygon."""
    inside = False
    for poly in geom.get("coordinates") or []:
        for ring in poly:
            for (x1, y1), (x2, y2) in zip(ring, ring[1:]):
                if (y1 > lat) != (y2 > lat) and lon < (x2 - x1) * (lat - y1) / (y2 - y1) + x1:
                    inside = not inside
    return inside


def confirm_listing_points(records: list[dict], features: list[dict]) -> tuple[list[dict], dict]:
    """A listing-joined record is kept only when its own stored point lies
    inside the polygon carrying its PARCELNO (LOCATION_CONFIRMED_INSIDE);
    otherwise it is not joined (LOCATION_NOT_INSIDE)."""
    geoms: dict = {}
    for f in features:
        geoms.setdefault(f["properties"].get(IDENTIFIER_FIELD), []).append(f["geometry"])
    out, counts = [], {}
    for r in records:
        if r.get("join_method") != METHOD_LISTING:
            out.append(r)
            continue
        lon, lat = _point(r)
        if any(point_in_multipolygon(lon, lat, g) for g in geoms.get(r["join_key"], [])):
            counts["LOCATION_CONFIRMED_INSIDE"] = counts.get("LOCATION_CONFIRMED_INSIDE", 0) + 1
            out.append(r)
        else:
            counts["LOCATION_NOT_INSIDE"] = counts.get("LOCATION_NOT_INSIDE", 0) + 1
    return out, counts


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
    identifier_shapes: set = field(default_factory=set)   # every PARCELNO shape in the file (value-free)
    duplicate_keys: set = field(default_factory=set)      # in-scope PARCELNO values on more than one record


def read_county(path, county: str, *, variant: str = "PIN", allow_par_geometry: bool = False,
                keys=None, listing_keys=None) -> CountyRead:
    """Read one county's DOR parcel shapefile (.shp with its siblings, or the
    county .zip) into GeoJSON features carrying PARCELNO and FID. Never
    raises: a problem is a FAILED or REFUSED read, which the refresh treats
    as 'write nothing'.

    keys: the exact identifiers that can be joined (the county's validated NAL
    ids). When given, only features carrying one of them are reprojected and
    kept (a county holds hundreds of thousands of polygons); every feature with
    one of them is kept, so stacked polygons stay AMBIGUOUS, and a kept polygon
    whose geometry the file also publishes under another PARCELNO is dropped
    (MULTI_PARCEL_GEOMETRY). The identifier format is still taken from the
    whole file."""
    if county not in COUNTY_CODES:
        return CountyRead("REFUSED", county, "UNKNOWN_COUNTY")
    variant = (variant or "").upper()
    if variant not in VARIANTS:
        return CountyRead("REFUSED", county, "UNKNOWN_VARIANT")
    if variant == "PAR" and not allow_par_geometry:
        return CountyRead("REFUSED", county, "PAR_FILE_NOT_ALLOWED")
    if "condo" in Path(str(path)).name.lower():
        return CountyRead("REFUSED", county, "CONDOMINIUM_FILE_NOT_INGESTED")
    with tempfile.TemporaryDirectory() as td:
        try:
            shp = Path(path)
            if shp.suffix.lower() == ".zip":
                shp = shapefile.extract_zip(shp, td)
            return _read_shp(shp, county, variant, keys, listing_keys)
        except (shapefile.UnsupportedProjection, shapefile.UnsupportedFormat, RuntimeError, OSError) as exc:
            return CountyRead("FAILED", county, type(exc).__name__ + ": " + str(exc))
        except Exception as exc:  # noqa: BLE001 - a malformed file (pyshp raises its own types) is a failed read
            return CountyRead("FAILED", county, "MALFORMED_FILE: " + type(exc).__name__)


def _read_shp(shp: Path, county: str, variant: str, keys=None, listing_keys=None) -> CountyRead:
    expected = COUNTY_CODES[county]
    out = CountyRead("COMPLETE", county, dataset=f"DOR PTO {variant} parcel shapefile {shp.stem}",
                     dataset_date=shapefile.dbf_date(shp), crs="projected")
    counts: dict = {}
    keep = None
    if keys is not None or listing_keys is not None:
        exact, listing = set(keys or ()), set(listing_keys or ())
        keep = (lambda props: exact_key(props.get(IDENTIFIER_FIELD)) in exact
                or separators_removed(props.get(IDENTIFIER_FIELD)) in listing)
    keys_by_raw: dict = {}
    # Records per in-scope PARCELNO, counted before any record is dropped
    # (malformed, empty, out of state, shared geometry): a duplicate must stay
    # visible however its other record fares. One record = one count, however
    # many parts its shape has.
    records_per_key: dict = {}
    for f in shapefile.read_pin_features(shp, keep=keep):
        props = f["properties"]
        co = props.get(COUNTY_FIELD, "")
        if co.strip():
            try:
                co_no = int(float(co))
            except ValueError:
                co_no = None
            if co_no != expected:
                return CountyRead("FAILED", county, f"WRONG_COUNTY: CO_NO {co.strip()} is not {expected}")
        key = exact_key(props.get(IDENTIFIER_FIELD))
        if not key.strip():
            counts["NO_PARCELNO"] = counts.get("NO_PARCELNO", 0) + 1
            continue
        out.identifier_shapes.add(identifier_shape(key))
        if keep is None or keep(props):
            records_per_key[key] = records_per_key.get(key, 0) + 1
        if f.get("malformed"):
            counts["MALFORMED_SHAPE"] = counts.get("MALFORMED_SHAPE", 0) + 1
            if keep is not None:
                keys_by_raw.setdefault(f["raw_sha"], set()).add(key)
            continue
        if keep is not None:
            keys_by_raw.setdefault(f["raw_sha"], set()).add(key)
        if f.get("skipped"):
            counts["NOT_IN_SCOPE"] = counts.get("NOT_IN_SCOPE", 0) + 1
            continue
        if f["geometry"] is None:
            counts["NULL_SHAPE"] = counts.get("NULL_SHAPE", 0) + 1
            continue
        box = geometry_bbox(f["geometry"])
        if box is None or not _inside_florida(box):
            counts["OUT_OF_STATE"] = counts.get("OUT_OF_STATE", 0) + 1
            continue
        feat = {"type": "Feature", "properties": {IDENTIFIER_FIELD: key, "FID": props["FID"]},
                "geometry": f["geometry"]}
        if keep is not None:
            feat["_raw_sha"] = f["raw_sha"]
        out.features.append(feat)
    if keep is not None:
        kept = []
        for feat in out.features:
            if len(keys_by_raw.get(feat.pop("_raw_sha"), ())) > 1:
                counts["MULTI_PARCEL_GEOMETRY"] = counts.get("MULTI_PARCEL_GEOMETRY", 0) + 1
                continue
            kept.append(feat)
        out.features = kept
    out.duplicate_keys = {k for k, n in records_per_key.items() if n > 1}
    if out.duplicate_keys:
        counts["DUPLICATE_IDENTIFIER_KEYS"] = len(out.duplicate_keys)
    out.counts = counts
    return out


def reject_duplicate_keys(records: list[dict], duplicate_keys) -> tuple[list[dict], dict]:
    """A record whose file identifier (join_key) is carried by more than one
    record of the county file is not joined (AMBIGUOUS_DUPLICATE_IDENTIFIER):
    nothing in the file says the separate records are one parcel, and neither
    distance nor which of them happens to be readable may choose between
    them. Applies to every join method."""
    out, counts = [], {}
    for r in records:
        if r.get("join_key") in duplicate_keys:
            counts["AMBIGUOUS_DUPLICATE_IDENTIFIER"] = counts.get("AMBIGUOUS_DUPLICATE_IDENTIFIER", 0) + 1
            continue
        out.append(r)
    return out, counts


def geometry_bbox(geom) -> tuple[float, float, float, float] | None:
    """(min lon, min lat, max lon, max lat) of a GeoJSON MultiPolygon, or None."""
    try:
        pts = [pt for poly in geom["coordinates"] for ring in poly for pt in ring]
        lons, lats = [float(p[0]) for p in pts], [float(p[1]) for p in pts]
    except (TypeError, KeyError, ValueError, IndexError):
        return None
    if not pts:
        return None
    return min(lons), min(lats), max(lons), max(lats)


def _inside_florida(box) -> bool:
    lat0, lat1, lon0, lon1 = FLORIDA_BOUNDS
    return lon0 <= box[0] and box[2] <= lon1 and lat0 <= box[1] and box[3] <= lat1


def _metres_outside(box, lon: float, lat: float) -> float:
    """Distance from a point to a lon/lat box, in metres (0 inside)."""
    dlon = max(box[0] - lon, 0.0, lon - box[2])
    dlat = max(box[1] - lat, 0.0, lat - box[3])
    return math.hypot(dlon * 111320.0 * math.cos(math.radians(lat)), dlat * 110540.0)


def location_check(records: list[dict], features: list[dict], *, tolerance_m: float = LOCATION_TOLERANCE_M
                   ) -> tuple[list[dict], dict]:
    """Drop a polygon that lies far from where the joined record itself says it
    is. The identifier match is the identity; this is a second, independent
    check so a wrong polygon is never attached silently. A record with stored
    coordinates more than `tolerance_m` from the polygon's extent loses that
    polygon (LOCATION_MISMATCH: the record stays unmatched). A record without
    coordinates is not checked and is counted (NO_RECORD_COORDINATES).

    Distance never resolves ambiguity: an identifier carried by more than one
    feature (separate shapefile records - nothing in the file says they are
    one parcel) keeps every one of its polygons here, however far, so the plan
    rejects the record as AMBIGUOUS instead of attaching whichever polygon
    happens to be near (DUPLICATE_IDENTIFIER). One record whose shape has
    several parts is ONE feature (a MultiPolygon) and is not affected."""
    occurrences: dict = {}
    for f in features:
        key = f["properties"].get(IDENTIFIER_FIELD)
        occurrences[key] = occurrences.get(key, 0) + 1
    points: dict = {}
    for r in records:
        try:
            lat, lon = float(r.get("latitude")), float(r.get("longitude"))
        except (TypeError, ValueError):
            continue
        if math.isfinite(lat) and math.isfinite(lon):
            points.setdefault(r.get("nal_parcel_id"), []).append((lon, lat))
    records = [r for r in records if r.get("join_method", METHOD_VALIDATED) == METHOD_VALIDATED]
    keys = {r.get("nal_parcel_id") for r in records}
    kept, counts = [], {}
    for f in features:
        key = f["properties"].get(IDENTIFIER_FIELD)
        if key not in keys:
            kept.append(f)
            continue
        if occurrences[key] > 1:
            counts["DUPLICATE_IDENTIFIER"] = counts.get("DUPLICATE_IDENTIFIER", 0) + 1
            kept.append(f)
            continue
        pts = points.get(key)
        if not pts:
            counts["NO_RECORD_COORDINATES"] = counts.get("NO_RECORD_COORDINATES", 0) + 1
            kept.append(f)
            continue
        box = geometry_bbox(f["geometry"])
        if box is None or any(_metres_outside(box, lon, lat) > tolerance_m for lon, lat in pts):
            counts["LOCATION_MISMATCH"] = counts.get("LOCATION_MISMATCH", 0) + 1
            continue
        counts["LOCATION_CONFIRMED"] = counts.get("LOCATION_CONFIRMED", 0) + 1
        kept.append(f)
    return kept, counts


def format_check(records: list[dict], features: list[dict], file_shapes=None) -> tuple[bool, str]:
    """Whether the file's PARCELNO format is the format of the validated ids.
    True when at least one validated id's shape occurs among the file's
    identifier shapes; a county whose shapes never overlap is NOT VALIDATED
    and nothing is attached. Value-free: shapes only."""
    ours = {identifier_shape(r.get("nal_parcel_id")) for r in records if r.get("nal_parcel_id")}
    theirs = set(file_shapes) if file_shapes else {identifier_shape(f["properties"].get(IDENTIFIER_FIELD))
                                                   for f in features}
    if not ours:
        return False, "NO_VALIDATED_IDS"
    if not theirs:
        return False, "NO_IDENTIFIED_FEATURES"
    if not ours & theirs:
        return False, "FORMAT_MISMATCH: validated ids " + ",".join(sorted(ours)) + " vs file " + ",".join(sorted(theirs)[:5])
    return True, ""
