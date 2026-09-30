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

    def __post_init__(self) -> None:
        if not LAYER_URL_RE.match(self.layer_url):
            raise ValueError(f"{self.source_id}: layer_url must be https://.../FeatureServer|MapServer/<n>")
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

    def county_value(self, county: str) -> str:
        return self.county_values.get(county, county)

    def out_fields(self) -> list[str]:
        names = {self.id_field, *self.field_map.values()}
        if self.county_field:
            names.add(self.county_field)
        if self.value_year_field:
            names.add(self.value_year_field)
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
    urls = []
    for i in range(0, len(ids), cfg.batch_size):
        chunk = ids[i:i + cfg.batch_size]
        where = f"{cfg.id_field} IN ({','.join(_sql_str(x) for x in chunk)})"
        if cfg.county_field:
            where = f"{cfg.county_field} = {_sql_str(cfg.county_value(county))} AND ({where})"
        params = {"where": where, "outFields": ",".join(cfg.out_fields()), "returnGeometry": "true" if cfg.centroid else "false",
                  "outSR": "4326", "f": "json"}
        urls.append(cfg.layer_url + "/query?" + urlencode(params))
    return urls


def index_features(cfg: ParcelSourceConfig, features: Iterable[dict]) -> dict[tuple[str, str], list[dict]]:
    """(layer county value or '', normalized id) -> features. More than one
    feature per key is kept so the match can call it ambiguous."""
    idx: dict[tuple[str, str], list[dict]] = {}
    for ft in features:
        attrs = ft.get("attributes") or {}
        key = normalize_id(attrs.get(cfg.id_field), cfg.id_rule)
        if key is None:
            continue
        county = str(attrs.get(cfg.county_field) or "").strip().upper() if cfg.county_field else ""
        idx.setdefault((county, key), []).append(ft)
    return idx


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
        key = normalize_id(r.get("parcel"), cfg.id_rule)
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
            "matched_id_field": cfg.id_field, "matched_parcel_id": match.key, "id_rule": cfg.id_rule,
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
