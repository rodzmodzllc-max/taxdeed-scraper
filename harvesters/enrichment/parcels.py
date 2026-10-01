"""Statewide parcel / assessment enrichment - the reusable "FDOR equivalent".

Florida's enricher (scripts/enrich_property_details.py) is one state's
bespoke code. This module is the state-agnostic version the six-state
expansion runs on: a state's statewide parcel / CAMA layer is DATA (a
`ParcelSourceConfig`), and the pipeline around it - query, deterministic
match, field mapping, provenance, safe update, coverage - exists once.

Rules (each pinned by tests/python/test_enrichment_factory.py):

  * MATCH ONLY ON AN AUTHORITATIVE IDENTIFIER. A property row is matched by
    (county, normalized parcel/account id) where the id is the layer's own
    identifier attribute, normalized by a named, deterministic rule
    (`ID_RULES`). Owner name, mailing address, situs address and location
    are never used to attach data. No match -> the fields stay unavailable
    and the reason is recorded; two or more features for one key ->
    AMBIGUOUS, nothing written.
  * A SOURCE MUST BE CLEARED TO BE USED. `enrichment_allowed()` refuses a
    configuration whose columns were not verified against the live layer
    or whose publication decision is not APPROVED (the registry's own
    vocabulary). A technically working layer with unclear reuse terms is
    gated, never used.
  * FIELD-LEVEL PROVENANCE. Every written column gets a field_provenance
    entry (source 'statewide_parcel', source_id, dataset, layer URL, the
    matched identifier, the value year, the licence). Writes go through
    scripts/field_provenance.py's precedence rule: a blank column may be
    filled, a provenanced value of equal or higher rank is never replaced.
  * NOTHING IS DERIVED THAT THE SOURCE DOES NOT PUBLISH. A value field the
    layer does not carry stays NULL; a centroid is computed only from the
    parcel's own polygon geometry; zero / blank / sentinel values are not
    written.

The module does no I/O: callers inject `fetch_json(url) -> dict` (the
runner is scripts/enrich_statewide_parcels.py).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable
from urllib.parse import urlencode

__all__ = ["ID_RULES", "ParcelSourceConfig", "MatchResult", "Coverage", "normalize_id", "enrichment_allowed",
           "query_urls", "index_features", "match_rows", "plan_update", "polygon_centroid", "LAYER_URL_RE"]

LAYER_URL_RE = re.compile(r"^https://[^?#\s]+/(FeatureServer|MapServer)/\d+$")
# A Socrata (SODA) dataset resource: https://<host>/resource/<4x4>.json
SODA_URL_RE = re.compile(r"^https://[^/?#\s]+/resource/[a-z0-9]{4}-[a-z0-9]{4}\.json$")
TRANSPORTS = ("arcgis", "socrata")

# Deterministic identifier normalizations. Each is a pure function of the
# string; none guesses, pads or re-derives an identifier.
ID_RULES: dict[str, Callable[[str], str]] = {
    # as published, trimmed and upper-cased
    "exact": lambda v: v.strip().upper(),
    # separators removed (spaces, dashes, dots, slashes, underscores) - the
    # same characters, in the same order
    "alnum": lambda v: re.sub(r"[^0-9A-Za-z]", "", v).upper(),
    # digits only (for purely numeric account numbers written with separators)
    "digits": lambda v: re.sub(r"\D", "", v),
    # a NUMERIC identifier: digits only, leading zeros dropped. For a source
    # that stores the id as a number (a Socrata "number" column loses the
    # leading zeros the published form carries); applied to both sides.
    "numeric": lambda v: re.sub(r"\D", "", v).lstrip("0"),
}

# Columns this pipeline may write, and their type. Anything else in a field
# map is a configuration error.
COLUMN_TYPES = {
    "owner_name": "text", "address": "text", "legal_desc": "text", "land_use": "text", "prop_type": "text",
    "assessed": "num", "market": "num", "land_value": "num", "improvement_value": "num", "taxable_value": "num",
    "acreage": "num", "year_built": "int", "living_area": "int", "value_year": "int", "homestead": "bool",
}
SENTINEL_TEXT = {"", "N/A", "NA", "NONE", "NULL", "UNKNOWN", "0"}
APPROVED_PUBLICATION = {"APPROVED", "APPROVED_GRANDFATHERED"}


@dataclass(frozen=True)
class ParcelSourceConfig:
    source_id: str                      # "nc_onemap_parcels"
    state: str
    agency: str                         # the owning agency, as it names itself
    dataset: str                        # the dataset's own title
    landing_url: str                    # the human-facing dataset page
    layer_url: str                      # https://.../FeatureServer/<n>
    id_field: str                       # the layer attribute that IS the parcel/account id
    id_rule: str                        # ID_RULES key, applied to BOTH sides
    field_map: dict[str, str]           # properties column -> layer attribute
    licence: str                        # licence / terms, as the source states them
    publication_status: str             # registry vocabulary: APPROVED / APPROVED_GRANDFATHERED / UNREVIEWED / RESTRICTED / BLOCKED
    county_field: str | None = None     # the attribute naming the county (statewide layer)
    county_values: dict[str, str] = field(default_factory=dict)  # our county name -> the layer's county value, when they differ
    value_year_field: str | None = None
    centroid: bool = False              # compute latitude/longitude from the matched parcel polygon
    columns_verified: bool = False      # True only once the live layer's fields were read (evidence run)
    batch_size: int = 50
    notes: str = ""
    # The properties column holding the identifier this layer is keyed on.
    # "parcel" for most states; Texas rows carry the appraisal-district
    # ACCOUNT in case_no (texas_harvester.TexasSaleRow.account_number).
    row_id_column: str = "parcel"
    # Other layer attributes that hold the SAME kind of identifier (a CAD's
    # property id vs its geographic id). A row matches only when its key
    # resolves to exactly one feature across all of them; one key hitting two
    # different features (through two attributes) is AMBIGUOUS.
    alt_id_fields: tuple = ()
    # "arcgis" (FeatureServer/MapServer query) or "socrata" (SODA resource).
    transport: str = "arcgis"
    # A multi-year source (a tax roll with one record per tax year): among the
    # records for one identifier keep only those with the greatest value of
    # this field; two DIFFERENT records still tied there are AMBIGUOUS.
    latest_field: str | None = None
    # How identifiers are written in the query: "string" (quoted) or
    # "number" (a numeric column - the normalized key, unquoted).
    id_query: str = "string"
    # County scope (all-sources engine, 2026-10-01): empty = the layer covers
    # every county of its state; otherwise only these counties (a county
    # appraisal / assessor layer). Several scoped layers may serve one state.
    counties: tuple = ()

    def __post_init__(self) -> None:
        if self.transport not in TRANSPORTS:
            raise ValueError(f"{self.source_id}: unknown transport {self.transport!r}")
        if self.transport == "arcgis" and not LAYER_URL_RE.match(self.layer_url):
            raise ValueError(f"{self.source_id}: layer_url must be https://.../FeatureServer|MapServer/<n>")
        if self.transport == "socrata" and not SODA_URL_RE.match(self.layer_url):
            raise ValueError(f"{self.source_id}: a socrata source's layer_url must be https://<host>/resource/<id>.json")
        if self.transport == "socrata" and self.centroid:
            raise ValueError(f"{self.source_id}: a centroid needs polygon geometry (arcgis transport)")
        if self.id_query not in ("string", "number"):
            raise ValueError(f"{self.source_id}: id_query must be string or number")
        if self.id_rule not in ID_RULES:
            raise ValueError(f"{self.source_id}: unknown id_rule {self.id_rule!r}")
        unknown = set(self.field_map) - set(COLUMN_TYPES)
        if unknown:
            raise ValueError(f"{self.source_id}: field_map names unknown column(s) {sorted(unknown)}")
        forbidden = {"owner_name", "address"} & {c for c, a in self.field_map.items() if a == self.id_field}
        if forbidden:
            raise ValueError(f"{self.source_id}: the identifier attribute cannot also fill {sorted(forbidden)}")
        if not self.id_field:
            raise ValueError(f"{self.source_id}: id_field required")
        if self.row_id_column not in ("parcel", "case_no", "certificate_no"):
            raise ValueError(f"{self.source_id}: row_id_column must be parcel, case_no or certificate_no")
        overlap = {"owner_name", "address"} & {c for c, a in self.field_map.items() if a in self.alt_id_fields}
        if overlap:
            raise ValueError(f"{self.source_id}: an identifier attribute cannot also fill {sorted(overlap)}")

    def covers(self, county: str) -> bool:
        return not self.counties or county in self.counties

    def county_value(self, county: str) -> str:
        return self.county_values.get(county, county)

    def id_fields(self) -> tuple:
        return (self.id_field, *self.alt_id_fields)

    def out_fields(self) -> list[str]:
        names = {*self.id_fields(), *self.field_map.values()}
        if self.county_field:
            names.add(self.county_field)
        if self.value_year_field:
            names.add(self.value_year_field)
        if self.latest_field:
            names.add(self.latest_field)
        return sorted(names)


def normalize_id(value: Any, rule: str) -> str | None:
    """The deterministic key for one identifier, or None when there is no
    usable identifier (blank, or no digit at all - a parcel id without a
    digit is a label, not an identifier)."""
    if value is None:
        return None
    s = str(value).strip()
    if not s or not re.search(r"\d", s):
        return None
    key = ID_RULES[rule](s)
    return key or None


def enrichment_allowed(cfg: ParcelSourceConfig) -> tuple[bool, str]:
    if not cfg.columns_verified:
        return False, "layer columns not verified against the live source"
    if cfg.publication_status not in APPROVED_PUBLICATION:
        return False, f"publication status {cfg.publication_status} - reuse not cleared"
    return True, "verified columns, approved publication"


def _sql_str(v: str) -> str:
    return "'" + v.replace("'", "''") + "'"


def query_urls(cfg: ParcelSourceConfig, county: str, raw_ids: Iterable[str]) -> list[str]:
    """ArcGIS /query URLs asking for exactly these identifiers (as the
    property rows carry them - the layer's own spelling is matched after
    normalization on both sides). Batched; county-scoped when the layer is
    statewide."""
    ids = sorted({str(i).strip() for i in raw_ids if str(i or "").strip()})
    if cfg.id_query == "number":
        ids = sorted({k for k in (normalize_id(i, cfg.id_rule) for i in ids) if k and k.isdigit()}, key=int)
    urls = []
    for i in range(0, len(ids), cfg.batch_size):
        chunk = ids[i:i + cfg.batch_size]
        in_list = ",".join(x if cfg.id_query == "number" else _sql_str(x) for x in chunk)
        if cfg.transport == "socrata":
            where = " OR ".join(f"{f} in({in_list})" for f in cfg.id_fields())
            urls.append(cfg.layer_url + "?" + urlencode({"$where": where, "$select": ",".join(cfg.out_fields()), "$limit": 5000}))
            continue
        where = " OR ".join(f"{f} IN ({in_list})" for f in cfg.id_fields())
        where = f"({where})" if len(cfg.id_fields()) > 1 else where
        if cfg.county_field:
            # Case-insensitive on the county NAME only (layers spell it "Morgan" or
            # "MORGAN"); the identifier stays an exact IN list.
            where = f"UPPER({cfg.county_field}) = {_sql_str(cfg.county_value(county).upper())} AND ({where})"
        params = {"where": where, "outFields": ",".join(cfg.out_fields()), "returnGeometry": "true" if cfg.centroid else "false",
                  "outSR": "4326", "f": "json"}
        urls.append(cfg.layer_url + "/query?" + urlencode(params))
    return urls


def index_features(cfg: ParcelSourceConfig, features: Iterable[dict]) -> dict[tuple[str, str], list[dict]]:
    """(layer county value or '', normalized id) -> features. More than one
    feature per key is kept so the match can call it ambiguous."""
    idx: dict[tuple[str, str], list[dict]] = {}
    seen: dict[tuple[str, str], set] = {}
    for ident, ft in enumerate(features):
        attrs = ft.get("attributes") or {}
        county = str(attrs.get(cfg.county_field) or "").strip().upper() if cfg.county_field else ""
        # One feature (its position in the response) reached through two of
        # its own identifier attributes is still ONE candidate; two different
        # features always stay two, even with identical attribute values.
        for f in cfg.id_fields():
            key = normalize_id(attrs.get(f), cfg.id_rule)
            if key is None or ident in seen.setdefault((county, key), set()):
                continue
            seen[(county, key)].add(ident)
            idx.setdefault((county, key), []).append({**ft, "_matched_field": f})
    if cfg.latest_field:
        for k, fts in idx.items():
            years = [_latest_value(ft, cfg.latest_field) for ft in fts]
            known = [y for y in years if y is not None]
            if len(fts) > 1 and known:
                top = max(known)
                idx[k] = [ft for ft, y in zip(fts, years) if y == top]
    return idx


def _latest_value(ft: dict, field_name: str):
    """The record's numeric value of the latest-selection field (a tax year),
    or None when it is blank or not a number - a record without a year never
    wins over one that has it."""
    v = (ft.get("attributes") or {}).get(field_name)
    try:
        return float(str(v).strip())
    except (TypeError, ValueError):
        return None


@dataclass
class MatchResult:
    row_id: str
    status: str                         # MATCHED | UNMATCHED | AMBIGUOUS | NO_IDENTIFIER
    feature: dict | None = None
    key: str | None = None
    reason: str = ""


def match_rows(cfg: ParcelSourceConfig, rows: Iterable[dict], index: dict[tuple[str, str], list[dict]]) -> list[MatchResult]:
    out = []
    for r in rows:
        key = normalize_id(r.get(cfg.row_id_column), cfg.id_rule)
        if key is None:
            out.append(MatchResult(r["id"], "NO_IDENTIFIER", reason="row carries no parcel/account identifier with a digit"))
            continue
        county = cfg.county_value(r.get("county") or "").strip().upper() if cfg.county_field else ""
        hits = index.get((county, key), [])
        if len(hits) == 1:
            out.append(MatchResult(r["id"], "MATCHED", hits[0], key))
        elif not hits:
            out.append(MatchResult(r["id"], "UNMATCHED", key=key, reason=f"no {cfg.id_field} equal to the row's identifier ({cfg.id_rule}) in {r.get('county')}"))
        else:
            out.append(MatchResult(r["id"], "AMBIGUOUS", key=key, reason=f"{len(hits)} features share the identifier - nothing attached"))
    return out


def _coerce(column: str, value: Any):
    kind = COLUMN_TYPES[column]
    if value is None:
        return None
    if kind == "text":
        s = re.sub(r"\s+", " ", str(value)).strip()
        return None if s.upper() in SENTINEL_TEXT else s
    if kind in ("num", "int"):
        try:
            n = float(str(value).replace(",", "").replace("$", "").strip())
        except ValueError:
            return None
        if n <= 0:
            return None                  # zero / negative = not published, never a real value
        return int(round(n)) if kind == "int" else round(n, 4)
    if kind == "bool":
        s = str(value).strip().upper()
        if s in ("Y", "YES", "TRUE", "1", "T"):
            return True
        if s in ("N", "NO", "FALSE", "0", "F"):
            return False
        return None
    return None


def polygon_centroid(geometry: dict | None) -> tuple[float, float] | None:
    """Area-weighted centroid (lat, lng) of an Esri JSON polygon in WGS84 -
    the parcel's own geometry, never a geocode. None when there is none."""
    rings = (geometry or {}).get("rings") or []
    a_sum = cx = cy = 0.0
    for ring in rings:
        if len(ring) < 3:
            continue
        for (x0, y0, *_), (x1, y1, *_) in zip(ring, ring[1:] + ring[:1]):
            cross = x0 * y1 - x1 * y0
            a_sum += cross
            cx += (x0 + x1) * cross
            cy += (y0 + y1) * cross
    if abs(a_sum) < 1e-18:
        return None
    lng, lat = cx / (3 * a_sum), cy / (3 * a_sum)
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        return None
    return round(lat, 7), round(lng, 7)


def plan_update(cfg: ParcelSourceConfig, row: dict, match: MatchResult, *, recorded_at: str) -> tuple[dict, dict]:
    """(fields to write, provenance entries) for one MATCHED row. Only
    blank columns (or columns whose stored value has no stronger
    provenance) are written - the caller runs field_provenance's filter on
    the result. Never called for an unmatched row."""
    if match.status != "MATCHED" or match.feature is None:
        return {}, {}
    attrs = match.feature.get("attributes") or {}
    year = _coerce("value_year", attrs.get(cfg.value_year_field)) if cfg.value_year_field else None
    fields: dict = {}
    for column, attr in cfg.field_map.items():
        v = _coerce(column, attrs.get(attr))
        if v is not None:
            fields[column] = v
    if year is not None and "value_year" not in fields and any(c in fields for c in ("assessed", "market", "land_value", "improvement_value", "taxable_value")):
        fields["value_year"] = year
    if cfg.centroid:
        c = polygon_centroid(match.feature.get("geometry"))
        if c:
            fields["latitude"], fields["longitude"] = c
    meta = {"source_id": cfg.source_id, "dataset": cfg.dataset, "agency": cfg.agency, "layer_url": cfg.layer_url,
            "matched_id_field": match.feature.get("_matched_field") or cfg.id_field, "matched_row_column": cfg.row_id_column,
            "matched_parcel_id": match.key, "id_rule": cfg.id_rule,
            "licence": cfg.licence, "value_year": year, "recorded_at": recorded_at}
    prov = {}
    for column in fields:
        entry = {"source": "statewide_parcel", **{k: v for k, v in meta.items() if v is not None}}
        if column in ("latitude", "longitude"):
            entry["derived"] = "area-weighted centroid of the matched parcel polygon"
        prov[column] = entry
    return fields, prov


@dataclass
class Coverage:
    """Counts with their denominators - never a bare percentage."""
    rows_considered: int = 0
    matched: int = 0
    unmatched: int = 0
    ambiguous: int = 0
    no_identifier: int = 0
    failed_queries: int = 0
    rows_written: int = 0
    fields_written: dict[str, int] = field(default_factory=dict)

    def add(self, m: MatchResult) -> None:
        self.rows_considered += 1
        attr = {"MATCHED": "matched", "UNMATCHED": "unmatched", "AMBIGUOUS": "ambiguous", "NO_IDENTIFIER": "no_identifier"}[m.status]
        setattr(self, attr, getattr(self, attr) + 1)

    def as_dict(self) -> dict:
        return {"rows_considered": self.rows_considered, "matched": self.matched, "unmatched": self.unmatched,
                "ambiguous": self.ambiguous, "no_identifier": self.no_identifier, "failed_queries": self.failed_queries,
                "rows_written": self.rows_written, "fields_written": dict(sorted(self.fields_written.items()))}
