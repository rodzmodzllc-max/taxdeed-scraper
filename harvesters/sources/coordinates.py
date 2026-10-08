"""Authoritative property coordinates: method, geometry, matching, replacement.

This is the one rule for where a property's latitude / longitude came from
and whether another coordinate may replace it. ``public/app.js``
``coordinateProvenance()`` mirrors ``coordinate_provenance()``, and
``tests/python/fixtures/coordinate_cases.json`` pins both.

Methods, strongest first:

- ``PARCEL_GIS``: an official county / state parcel layer, matched on the
  parcel identifier.
- ``TAX_ROLL``: an official tax-roll / cadastral layer (FDOR NAL), matched on
  the parcel identifier.
- ``LAND_BANK_GIS``: the land bank's own GIS layer for its inventory.
- ``OFFICIAL_ADDRESS``: a location the source list itself publishes for the
  record.
- ``OTHER_REVIEWED``: a government-published location whose derivation the
  source does not state.
- ``VENDOR_LISTING``: coordinates in a vendor / counsel listing. Never
  authoritative.
- ``DETERMINISTIC_GEOCODE``: a public address geocoded by the US Census
  Bureau Geocoder, accepted only when state, county and house number agree.
  Never parcel-authoritative.
- ``UNRECORDED``: coordinates on file whose origin was not recorded.

Geometry is what the point stands for: ``POINT`` (a point the source
published), ``PARCEL_CENTROID`` (the area-weighted centroid of the matched
parcel polygon, not the buildable portion or a structure), or
``PARCEL_GEOMETRY`` (the polygon itself, not stored today).

Matching is deterministic: one feature for one identifier (parcel id,
account number, state parcel number, GIS identifier), or an address that
agrees on state, county and house number. A fuzzy, partial or "nearby"
match never produces a coordinate. Replacement only goes UP the method
ranking, and an authoritative coordinate is never replaced by a
non-authoritative one.
"""
from __future__ import annotations

import re

METHODS = ("PARCEL_GIS", "TAX_ROLL", "LAND_BANK_GIS", "OFFICIAL_ADDRESS", "OTHER_REVIEWED",
           "VENDOR_LISTING", "DETERMINISTIC_GEOCODE", "UNRECORDED")
METHOD_RANK = {"PARCEL_GIS": 6, "TAX_ROLL": 5, "LAND_BANK_GIS": 5, "OFFICIAL_ADDRESS": 4, "OTHER_REVIEWED": 3,
               "VENDOR_LISTING": 2, "DETERMINISTIC_GEOCODE": 1, "UNRECORDED": 0}
AUTHORITATIVE = frozenset({"PARCEL_GIS", "TAX_ROLL", "LAND_BANK_GIS", "OFFICIAL_ADDRESS", "OTHER_REVIEWED"})
GEOMETRIES = ("POINT", "PARCEL_CENTROID", "PARCEL_GEOMETRY")
METHOD_LABELS = {
    "PARCEL_GIS": "Official parcel GIS layer",
    "TAX_ROLL": "Official tax-roll parcel layer",
    "LAND_BANK_GIS": "Land bank GIS layer",
    "OFFICIAL_ADDRESS": "Location published by the source list",
    "OTHER_REVIEWED": "Government-published location",
    "VENDOR_LISTING": "Vendor listing (not an official parcel location)",
    "DETERMINISTIC_GEOCODE": "Address geocode (US Census Bureau) - not a parcel location",
    "UNRECORDED": "Origin not recorded",
}
GEOMETRY_LABELS = {"POINT": "Point", "PARCEL_CENTROID": "Parcel centroid", "PARCEL_GEOMETRY": "Parcel boundary"}
STRONG_MATCH_KINDS = ("parcel_id", "account_number", "state_parcel_number", "gis_identifier")
ADDRESS_MATCH_KIND = "address_state_county_house_number"

# What each AVAILABLE source's OWN coordinates are, from its adapter
# configuration (harvesters/otc/adapters/expansion.py, la.py):
SOURCE_COORDINATES = {
    "la_ebr_adjudicated": ("OFFICIAL_ADDRESS", "POINT", "the parish open-data list's own location column"),
    "mi_detroit_landbank_lots": ("LAND_BANK_GIS", "POINT", "the DLBA layer's own latitude / longitude attributes"),
    "mi_detroit_landbank_programs": ("LAND_BANK_GIS", "POINT", "the DLBA layer's own latitude / longitude attributes"),
    "mn_ramsey_tax_forfeit": ("PARCEL_GIS", "POINT", "the county tax-forfeited land layer's own point for the parcel"),
    "tn_shelby_landbank": ("LAND_BANK_GIS", "POINT", "the Shelby County Land Bank portal's own latitude / longitude"),
}
# field_provenance.latitude.source -> method / geometry, for enriched rows.
PROVENANCE_COORDINATES = {
    "fdor_nal": ("TAX_ROLL", "PARCEL_CENTROID"),
    "statewide_parcel": ("PARCEL_GIS", "PARCEL_CENTROID"),
    "county_gis": ("PARCEL_GIS", "PARCEL_CENTROID"),
    "vendor_listing": ("VENDOR_LISTING", "POINT"),
    "census_geocoder": ("DETERMINISTIC_GEOCODE", "POINT"),
}


def _num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None


def has_coordinates(row: dict) -> bool:
    lat, lng = _num(row.get("latitude")), _num(row.get("longitude"))
    return lat is not None and lng is not None and -90 <= lat <= 90 and -180 <= lng <= 180 and not (lat == 0 and lng == 0)


def coordinate_provenance(row: dict) -> dict:
    """{method, geometry, authoritative, label, geometry_label, source, matched_identifier}.
    method 'NONE' when the row has no usable coordinates."""
    if not has_coordinates(row):
        return {"method": "NONE", "geometry": "", "authoritative": False, "label": "No authoritative coordinates available",
                "geometry_label": "", "source": "", "matched_identifier": ""}
    fp = row.get("field_provenance") if isinstance(row.get("field_provenance"), dict) else {}
    entry = fp.get("latitude") if isinstance(fp.get("latitude"), dict) else {}
    src = entry.get("source") or ""
    method, geometry = "UNRECORDED", "POINT"
    if src in PROVENANCE_COORDINATES:
        method, geometry = PROVENANCE_COORDINATES[src]
        if entry.get("method") in METHODS:      # an entry may name its method explicitly
            method = entry["method"]
        if entry.get("geometry") in GEOMETRIES:
            geometry = entry["geometry"]
    elif src == "county_list" or not src:
        sid = row.get("source_id") or row.get("harvester_source") or ""
        if sid in SOURCE_COORDINATES:
            method, geometry, _ = SOURCE_COORDINATES[sid]
        elif src == "county_list":
            method, geometry = "OTHER_REVIEWED", "POINT"
    return {"method": method, "geometry": geometry, "authoritative": method in AUTHORITATIVE,
            "label": METHOD_LABELS[method], "geometry_label": GEOMETRY_LABELS.get(geometry, ""),
            "source": src, "matched_identifier": entry.get("matched_identifier") or entry.get("matched_on") or ""}


def accept_match(kind: str, matched_features: int, *, address_agrees: bool = False) -> bool:
    """Whether one candidate match may produce a coordinate. Exactly one
    feature, matched on a strong identifier, or an address that agrees on
    state, county AND house number. Anything else - several features, a
    fuzzy or partial address, a nearest-feature search - is refused."""
    if matched_features != 1:
        return False
    if kind in STRONG_MATCH_KINDS:
        return True
    if kind == ADDRESS_MATCH_KIND:
        return address_agrees
    return False


def should_replace(existing_method: str, new_method: str) -> bool:
    """A new coordinate replaces an existing one only when its method is
    strictly stronger, and never authoritative -> non-authoritative."""
    if new_method not in METHOD_RANK:
        return False
    if existing_method in ("NONE", "", None):
        return True
    if existing_method in AUTHORITATIVE and new_method not in AUTHORITATIVE:
        return False
    return METHOD_RANK[new_method] > METHOD_RANK.get(existing_method, 0)


# --- geocode validation (scripts/geocode_properties.py) --------------------

def _norm(text) -> str:
    t = re.sub(r"[^a-z0-9 ]", " ", str(text or "").lower().replace("saint ", "st "))
    return re.sub(r"\s+", " ", t).strip()


def county_matches(county: str, census_counties: list[dict]) -> bool:
    """Our county name against the Census response's county geographies.
    An independent city is named '<X> City' here and 'X city' by the Census
    (St. Louis City vs St. Louis County share the base name 'St. Louis', so
    the full NAME decides); a county matches on its BASENAME."""
    ours = _norm(county)
    city = ours.endswith(" city")
    for entry in census_counties or []:
        name = _norm(entry.get("NAME"))
        base = _norm(entry.get("BASENAME")) or re.sub(r" (county|parish|city)$", "", name)
        if city:
            if name == ours:
                return True
        elif base == ours and not name.endswith(" city"):
            return True
    return False


_HOUSE = re.compile(r"^\s*(\d+)\b")


def address_agrees(input_address: str, matched_address: str) -> bool:
    """The Census matched address must carry the SAME house number as the
    input and share its first street-name word. A different number, or no
    number on either side, is not a deterministic match."""
    a, b = _HOUSE.match(str(input_address or "")), _HOUSE.match(str(matched_address or ""))
    if not a or not b or a.group(1) != b.group(1):
        return False
    skip = {"n", "s", "e", "w", "ne", "nw", "se", "sw", "north", "south", "east", "west"}
    words_in = [w for w in _norm(input_address[a.end():]).split() if w not in skip]
    words_m = set(_norm(matched_address[b.end():]).split())
    return bool(words_in) and words_in[0] in words_m


def geocode_provenance_entry(matched_identifier: str, recorded_at: str | None = None) -> dict:
    """The field_provenance entry a Census geocode writes for latitude / longitude."""
    entry = {"source": "census_geocoder", "method": "DETERMINISTIC_GEOCODE", "geometry": "POINT",
             "match": ADDRESS_MATCH_KIND, "evidence": "US Census Bureau Geocoder one-line address match; state, county "
             "and house number agree with the row - an address location, not a parcel location"}
    if matched_identifier:
        entry["matched_identifier"] = matched_identifier
    if recorded_at:
        entry["recorded_at"] = recorded_at
    return entry


def coverage(rows) -> dict:
    """Counts by method for a population (operational report; no values)."""
    out = {m: 0 for m in METHODS}
    out["NONE"] = 0
    for r in rows:
        out[coordinate_provenance(r)["method"]] += 1
    return out
