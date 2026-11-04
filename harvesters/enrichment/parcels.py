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

import math
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable
from urllib.parse import urlencode

__all__ = ["ID_RULES", "ParcelSourceConfig", "MatchResult", "Coverage", "normalize_id", "enrichment_allowed",
           "query_urls", "socrata_features", "index_features", "match_rows", "plan_update", "polygon_centroid", "polygon_area_sqft",
           "LAYER_URL_RE", "DERIVED_AREA_NOTE"]

LAYER_URL_RE = re.compile(r"^https://[^?#\s]+/(FeatureServer|MapServer)/\d+$")
# A Socrata (SODA) dataset resource: https://<host>/resource/<4x4>.json
SODA_URL_RE = re.compile(r"^https://[^/?#\s]+/resource/[a-z0-9]{4}-[a-z0-9]{4}\.json$")
# "county_file": one published file per county (a zipped shapefile); the
# runner reads its attribute table and keeps only the requested identifiers.
TRANSPORTS = ("arcgis", "socrata", "county_file")
# A county file URL: https only, with a {fips} placeholder for the county.
FILE_TEMPLATE_RE = re.compile(r"^https://[^?#\s]+\{fips\}[^?#\s]*\.zip$")

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
    # A Texas appraisal district's REAL-PROPERTY account: digits, optionally
    # written with the district's 'R' (real property) prefix, leading zeros
    # dropped. Any other shape - another prefix ('N' mineral interest, 'P'
    # personal property), a separator, a second letter - is not a real-
    # property account and yields no identifier, so it can never meet a
    # parcel polygon through the bare number (TX enrichment, 2026-10-28:
    # Waller's PBFCM list carries both 'R' parcels and 'N' mineral leases).
    "r_account": lambda v: (lambda m: m.group(1).lstrip("0") if m else "")(re.fullmatch(r"R?(\d+)", v.strip().upper())),
}

# Columns this pipeline may write, and their type. Anything else in a field
# map is a configuration error.
COLUMN_TYPES = {
    "owner_name": "text", "address": "text", "legal_desc": "text", "land_use": "text", "prop_type": "text",
    "assessed": "num", "market": "num", "land_value": "num", "improvement_value": "num", "taxable_value": "num",
    "acreage": "num", "year_built": "int", "living_area": "int", "value_year": "int", "homestead": "bool",
    "lot_sqft": "int",
}
# The provenance wording of a lot area computed from the matched parcel's own
# polygon (thin-fields sprint, 2026-10-27). The app shows it as "Derived by our
# system - <this>", so a reader never takes it for the deed / assessed area.
DERIVED_AREA_NOTE = ("area of the matched parcel polygon, computed by us (spherical approximation, within about half a "
                     "percent); a GIS area, not the deed or assessed lot size")
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
    # With latest_field: records older than this value are never candidates
    # (a parcel that left the roll years ago must not be enriched from its
    # last historic record).
    latest_min: float | None = None
    # How identifiers are written in the query: "string" (quoted) or
    # "number" (a numeric column - the normalized key, unquoted).
    id_query: str = "string"
    # County scope (all-sources engine, 2026-10-01): empty = the layer covers
    # every county of its state; otherwise only these counties (a county
    # appraisal / assessor layer). Several scoped layers may serve one state.
    counties: tuple = ()
    # Conditional columns (enrichment sprint, 2026-10-01): column ->
    # (attribute, condition attribute, accepted condition values). The value
    # is written ONLY when the source's own condition attribute says it means
    # that column - e.g. a tax roll's `units` is acreage only on records whose
    # `unit_type` is ACREAGE (it counts lots or improvements otherwise).
    conditional_map: dict = field(default_factory=dict)
    # column -> source values that mean "not classified" for that column
    # (e.g. a land-use code NOT DETERMINED): treated as no value, never stored.
    no_value: dict = field(default_factory=dict)
    # Raw attributes copied verbatim into each provenance entry, so the
    # source's own classification travels with a normalized/derived column.
    provenance_attrs: tuple = ()
    # Multi-year roll, column by column (sprint 2026-10-01): column -> earliest
    # acceptable year. When the latest record leaves that column blank (the
    # EBR roll stopped publishing STRUCTURE USE after tax year 2023), the value
    # comes from the most recent year that DOES publish it, no older than this
    # floor - one distinct value in that year or nothing - and its provenance
    # names that year. Only for an identifier that already matched exactly.
    column_year_floor: dict = field(default_factory=dict)
    # county_file transport (TX enrichment 2026-10-27): the per-county file URL
    # template ({fips}), each covered county's FIPS code, and - because each
    # county's appraisal district fills a different identifier attribute - the
    # identifier attribute(s) and rule MEASURED for that county:
    # county -> ((attribute, ...), id_rule). A county without an entry is not
    # covered (never matched on a guessed attribute).
    file_url_template: str = ""
    county_fips: dict = field(default_factory=dict)
    county_id: dict = field(default_factory=dict)
    # Only blank columns are ever written. A column a listing sync also writes
    # is never mapped at all; this keeps a later sync and this source from
    # taking turns overwriting each other.
    fill_blank_only: bool = False
    # Only rows of these sources (properties.source_id, else harvester_source)
    # are matched - the sources whose row_id_column IS this layer's identifier
    # (Texas: the vendor listings carry the appraisal-district account in
    # case_no; a county list's case_no may be something else). Empty = every row.
    row_source_ids: tuple = ()

    def takes_row(self, row: dict) -> bool:
        return not self.row_source_ids or (row.get("source_id") or row.get("harvester_source") or "") in self.row_source_ids
    # Thin-states sprint (2026-10-27). column -> regular expressions (matched
    # at the start of the upper-cased value) that mean "not published" for
    # that column - e.g. a county layer writing "0 UNKNOWN <city>" as the
    # situs of a parcel with no street address. Such a value is never stored.
    no_value_patterns: dict = field(default_factory=dict)
    # column -> ((attribute, prefix), ...): a TEXT column the source publishes
    # in parts (house number, direction, street name, type, unit). The parts
    # are joined with single spaces in the source's own order, a blank part
    # is skipped, a part's prefix (e.g. "#" before a unit number) is written
    # only with that part. Nothing is added that the parts do not say; no
    # part means no value, and a blank FIRST part (the house number) means no
    # value at all. Only for text columns.
    composite_map: dict = field(default_factory=dict)
    # Thin-fields sprint (2026-10-27). For a layer that publishes the parcel
    # POLYGON but no defined area attribute: write lot_sqft as the area of the
    # matched parcel's own polygon, provenance-labelled as derived
    # (DERIVED_AREA_NOTE). Never replaces a value any source published (the
    # shared precedence rule: equal rank never overwrites, a blank only).
    derived_lot_area: bool = False
    # socrata transport: the dataset column holding the parcel geometry
    # (GeoJSON), read only for derived_lot_area and / or centroid.
    geometry_field: str | None = None

    def __post_init__(self) -> None:
        if self.transport not in TRANSPORTS:
            raise ValueError(f"{self.source_id}: unknown transport {self.transport!r}")
        if self.transport == "arcgis" and not LAYER_URL_RE.match(self.layer_url):
            raise ValueError(f"{self.source_id}: layer_url must be https://.../FeatureServer|MapServer/<n>")
        if self.transport == "socrata" and not SODA_URL_RE.match(self.layer_url):
            raise ValueError(f"{self.source_id}: a socrata source's layer_url must be https://<host>/resource/<id>.json")
        if self.transport == "county_file":
            if not FILE_TEMPLATE_RE.match(self.file_url_template):
                raise ValueError(f"{self.source_id}: a county_file source needs an https .zip file_url_template with {{fips}}")
            if not self.county_id or set(self.county_id) != set(self.counties):
                raise ValueError(f"{self.source_id}: a county_file source's counties must be exactly the counties with a measured identifier rule")
            missing = set(self.counties) - set(self.county_fips)
            if missing:
                raise ValueError(f"{self.source_id}: no FIPS code for {sorted(missing)}")
            for c, (fields_, rule) in self.county_id.items():
                if not fields_ or rule not in ID_RULES:
                    raise ValueError(f"{self.source_id}: bad identifier rule for {c}")
        if self.transport == "socrata" and self.centroid and not self.geometry_field:
            raise ValueError(f"{self.source_id}: a socrata centroid needs the parcel polygon column (geometry_field)")
        if self.derived_lot_area and not (self.transport == "arcgis" or (self.transport == "socrata" and self.geometry_field)):
            raise ValueError(f"{self.source_id}: a derived lot area needs the parcel polygon (arcgis, or socrata with geometry_field)")
        if self.geometry_field and not (self.transport == "socrata" and (self.derived_lot_area or self.centroid)):
            raise ValueError(f"{self.source_id}: geometry_field is read only for a socrata derived lot area or centroid")
        if self.derived_lot_area and ("lot_sqft" in self.field_map or "lot_sqft" in self.conditional_map):
            raise ValueError(f"{self.source_id}: lot_sqft is either published (mapped) or derived, never both")
        if self.id_query not in ("string", "number", "normalized"):
            raise ValueError(f"{self.source_id}: id_query must be string, number or normalized")
        if self.id_rule not in ID_RULES:
            raise ValueError(f"{self.source_id}: unknown id_rule {self.id_rule!r}")
        bad_cond = set(self.conditional_map) & set(self.field_map)
        if bad_cond:
            raise ValueError(f"{self.source_id}: column(s) {sorted(bad_cond)} are both mapped and conditional")
        clash = set(self.composite_map) & (set(self.field_map) | set(self.conditional_map))
        if clash:
            raise ValueError(f"{self.source_id}: column(s) {sorted(clash)} are both composite and mapped")
        for column, parts in self.composite_map.items():
            if COLUMN_TYPES.get(column) != "text":
                raise ValueError(f"{self.source_id}: composite column {column!r} must be a text column")
            if not parts or any(not (isinstance(p, tuple) and len(p) == 2 and p[0]) for p in parts):
                raise ValueError(f"{self.source_id}: composite column {column!r} needs ((attribute, prefix), ...)")
            if self.id_field in {a for a, _ in parts} and column in ("owner_name", "address"):
                raise ValueError(f"{self.source_id}: the identifier attribute cannot also fill {column}")
        for column, pats in self.no_value_patterns.items():
            if column not in COLUMN_TYPES or not pats:
                raise ValueError(f"{self.source_id}: no_value_patterns names {column!r} without patterns")
            for p in pats:
                re.compile(p)
        unknown = (set(self.field_map) | set(self.conditional_map) | set(self.composite_map)) - set(COLUMN_TYPES)
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

    def id_fields(self, county: str | None = None) -> tuple:
        if county is not None and county in self.county_id:
            return tuple(self.county_id[county][0])
        return (self.id_field, *self.alt_id_fields)

    def id_rule_for(self, county: str | None = None) -> str:
        if county is not None and county in self.county_id:
            return self.county_id[county][1]
        return self.id_rule

    def file_url(self, county: str) -> str:
        return self.file_url_template.format(fips=self.county_fips[county])

    def written_columns(self) -> frozenset:
        """Every properties column this layer can write."""
        cols = set(self.field_map) | set(self.conditional_map) | set(self.composite_map)
        if self.value_year_field:
            cols.add("value_year")
        if self.centroid:
            cols.update(("latitude", "longitude"))
        if self.derived_lot_area:
            cols.add("lot_sqft")
        return frozenset(cols)

    def out_fields(self) -> list[str]:
        names = {*self.id_fields(), *self.field_map.values(), *self.provenance_attrs}
        for fields_, _rule in self.county_id.values():
            names.update(fields_)
        for parts in self.composite_map.values():
            names.update(a for a, _ in parts)
        for attr, cond, _vals in self.conditional_map.values():
            names.update((attr, cond))
        if self.county_field:
            names.add(self.county_field)
        if self.value_year_field:
            names.add(self.value_year_field)
        if self.latest_field:
            names.add(self.latest_field)
        if self.geometry_field:
            names.add(self.geometry_field)
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


def _governance_permissions():
    try:
        from ..governance import permissions as PERM  # noqa: PLC0415
    except ImportError:  # imported as top-level `enrichment` (harvesters/ on sys.path)
        from governance import permissions as PERM  # noqa: PLC0415
    return PERM


def recorded_permission(cfg: ParcelSourceConfig) -> tuple[bool, str]:
    """The source's recorded fetch AND enrich permission
    (data/source_permissions.csv, harvesters/governance/permissions.py).
    Fail closed: an error loading governance is a refusal."""
    try:
        PERM = _governance_permissions()
    except Exception as exc:  # noqa: BLE001
        return False, f"permission check unavailable ({type(exc).__name__})"
    for op in ("fetch", "enrich"):
        d = PERM.authorize(cfg.source_id, op, state=cfg.state)
        if not d.allowed:
            return False, f"no recorded {op} permission [{d.reason_code}]"
    return True, ""


# The permission check enrichment_allowed() applies. A module attribute so a
# test exercising the matching mechanics on a FIXTURE layer can stand it in;
# the real check is covered by tests/python/test_source_permissions.py.
PERMISSION_CHECK = recorded_permission


def enrichment_allowed(cfg: ParcelSourceConfig) -> tuple[bool, str]:
    if not cfg.columns_verified:
        return False, "layer columns not verified against the live source"
    if cfg.publication_status not in APPROVED_PUBLICATION:
        return False, f"publication status {cfg.publication_status} - reuse not cleared"
    ok, why = PERMISSION_CHECK(cfg)
    if not ok:
        return False, why
    return True, "verified columns, approved publication, recorded permission"


def _sql_str(v: str) -> str:
    return "'" + v.replace("'", "''") + "'"


def query_urls(cfg: ParcelSourceConfig, county: str, raw_ids: Iterable[str]) -> list[str]:
    """ArcGIS /query URLs asking for exactly these identifiers (as the
    property rows carry them - the layer's own spelling is matched after
    normalization on both sides). Batched; county-scoped when the layer is
    statewide."""
    ids = sorted({str(i).strip() for i in raw_ids if str(i or "").strip()})
    if cfg.transport == "county_file":
        # One file per county; the identifiers are filtered while it is read.
        return [cfg.file_url(county)] if ids and county in cfg.county_id else []
    if cfg.id_query == "number":
        ids = sorted({k for k in (normalize_id(i, cfg.id_rule) for i in ids) if k and k.isdigit()}, key=int)
    elif cfg.id_query == "normalized":
        # The layer stores the identifier in its normalized spelling (e.g. a
        # PIN written without its dashes): ask for exactly that string.
        ids = sorted({k for k in (normalize_id(i, cfg.id_rule) for i in ids) if k})
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
        params = {"where": where, "outFields": ",".join(cfg.out_fields()),
                  "returnGeometry": "true" if (cfg.centroid or cfg.derived_lot_area) else "false",
                  "outSR": "4326", "f": "json"}
        urls.append(cfg.layer_url + "/query?" + urlencode(params))
    return urls


def socrata_features(cfg: ParcelSourceConfig, records) -> list[dict]:
    """A SODA answer (a list of records) as ArcGIS-shaped features: the
    attributes without the geometry column, the geometry (GeoJSON) beside
    them. None / anything but a list is a failed read - the caller decides."""
    gf = cfg.geometry_field
    return [{"attributes": {k: v for k, v in rec.items() if k != gf}, **({"geometry": rec.get(gf)} if gf else {})}
            for rec in records if isinstance(rec, dict)]


def index_features(cfg: ParcelSourceConfig, features: Iterable[dict], county: str | None = None) -> dict[tuple[str, str], list[dict]]:
    """(layer county value or '', normalized id) -> features. More than one
    feature per key is kept so the match can call it ambiguous. `county`
    selects a county_file source's measured identifier attribute(s) and rule."""
    id_fields, rule = cfg.id_fields(county), cfg.id_rule_for(county)
    idx: dict[tuple[str, str], list[dict]] = {}
    seen: dict[tuple[str, str], set] = {}
    for ident, ft in enumerate(features):
        attrs = ft.get("attributes") or {}
        county = str(attrs.get(cfg.county_field) or "").strip().upper() if cfg.county_field else ""
        # One feature (its position in the response) reached through two of
        # its own identifier attributes is still ONE candidate; two different
        # features always stay two, even with identical attribute values.
        for f in id_fields:
            key = normalize_id(attrs.get(f), rule)
            if key is None or ident in seen.setdefault((county, key), set()):
                continue
            seen[(county, key)].add(ident)
            idx.setdefault((county, key), []).append({**ft, "_matched_field": f})
    if cfg.latest_field and cfg.column_year_floor:
        for k, fts in idx.items():
            hist = list(fts)
            for ft in fts:
                ft["_history"] = hist
    if cfg.latest_field and cfg.latest_min is not None:
        for k in list(idx):
            idx[k] = [ft for ft in idx[k] if (_latest_value(ft, cfg.latest_field) or 0) >= cfg.latest_min]
            if not idx[k]:
                del idx[k]
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
        county_key = r.get("county") if cfg.county_id else None
        rule = cfg.id_rule_for(county_key)
        key = normalize_id(r.get(cfg.row_id_column), rule)
        if key is None:
            out.append(MatchResult(r["id"], "NO_IDENTIFIER", reason="row carries no parcel/account identifier with a digit"))
            continue
        county = cfg.county_value(r.get("county") or "").strip().upper() if cfg.county_field else ""
        hits = index.get((county, key), [])
        if len(hits) == 1:
            out.append(MatchResult(r["id"], "MATCHED", hits[0], key))
        elif not hits:
            out.append(MatchResult(r["id"], "UNMATCHED", key=key, reason=f"no {'/'.join(cfg.id_fields(county_key))} equal to the row's identifier ({rule}) in {r.get('county')}"))
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
        if column == "year_built" and not 1700 <= n <= 2100:
            return None                  # not a year (e.g. several years run together: "1990,2005")
        return int(round(n)) if kind == "int" else round(n, 4)
    if kind == "bool":
        s = str(value).strip().upper()
        if s in ("Y", "YES", "TRUE", "1", "T"):
            return True
        if s in ("N", "NO", "FALSE", "0", "F"):
            return False
        return None
    return None


def _ring_moments(ring) -> tuple[float, float, float]:
    """(2 x signed area, x moment, y moment) of one ring (shoelace)."""
    pts = [(float(p[0]), float(p[1])) for p in ring if isinstance(p, (list, tuple)) and len(p) >= 2]
    a = mx = my = 0.0
    if len(pts) < 3:
        return a, mx, my
    for (x0, y0), (x1, y1) in zip(pts, pts[1:] + pts[:1]):
        cross = x0 * y1 - x1 * y0
        a += cross
        mx += (x0 + x1) * cross
        my += (y0 + y1) * cross
    return a, mx, my


def polygon_centroid(geometry: dict | None) -> tuple[float, float] | None:
    """Area-weighted centroid (lat, lng) of a WGS84 parcel polygon - the
    parcel's own geometry, never a geocode. Accepts an Esri JSON polygon
    ({"rings": ...}) or a GeoJSON Polygon / MultiPolygon (a Socrata
    dataset's geometry column). None when there is none.

    Esri rings keep their published orientation (outer clockwise, holes
    counter-clockwise), so the signed sums already subtract the holes. A
    GeoJSON polygon is normalised per part - its first ring counts as area,
    every later ring (a hole) as negative area - so a dataset that does not
    enforce the right-hand rule still yields the right centroid."""
    geometry = geometry if isinstance(geometry, dict) else {}
    a_sum = cx = cy = 0.0
    if geometry.get("rings"):
        for ring in geometry["rings"]:
            a, mx, my = _ring_moments(ring)
            a_sum, cx, cy = a_sum + a, cx + mx, cy + my
    else:
        kind, coords = geometry.get("type"), geometry.get("coordinates") or []
        polys = [coords] if kind == "Polygon" else coords if kind == "MultiPolygon" else []
        for poly in polys:
            if not isinstance(poly, list):
                continue
            for i, ring in enumerate(poly):
                if not isinstance(ring, list):
                    continue
                a, mx, my = _ring_moments(ring)
                sign = (1.0 if a >= 0 else -1.0) * (1.0 if i == 0 else -1.0)
                a_sum, cx, cy = a_sum + sign * a, cx + sign * mx, cy + sign * my
    if abs(a_sum) < 1e-18:
        return None
    lng, lat = cx / (3 * a_sum), cy / (3 * a_sum)
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        return None
    return round(lat, 7), round(lng, 7)


def _rings(geometry) -> list:
    """Polygon rings as lists of (lng, lat) from an Esri JSON polygon
    ({"rings": ...}) or a GeoJSON Polygon / MultiPolygon. [] when neither."""
    if not isinstance(geometry, dict):
        return []
    if geometry.get("rings"):
        return [r for r in geometry["rings"] if isinstance(r, list)]
    kind, coords = geometry.get("type"), geometry.get("coordinates") or []
    if kind == "Polygon":
        return [r for r in coords if isinstance(r, list)]
    if kind == "MultiPolygon":
        return [r for poly in coords if isinstance(poly, list) for r in poly if isinstance(r, list)]
    return []


# Authalic radius of the WGS 84 ellipsoid: a sphere of the same surface area.
_AUTHALIC_R_M = 6371007.181
_SQFT_PER_M2 = 10.763910417


def _signed_ring_area_m2(ring) -> float:
    pts = [(float(p[0]), float(p[1])) for p in ring if isinstance(p, (list, tuple)) and len(p) >= 2]
    if len(pts) < 3:
        return 0.0
    s = 0.0
    for (x0, y0), (x1, y1) in zip(pts, pts[1:] + pts[:1]):
        s += math.radians(x1 - x0) * (2 + math.sin(math.radians(y0)) + math.sin(math.radians(y1)))
    return s * _AUTHALIC_R_M ** 2 / 2.0


def polygon_area_sqft(geometry) -> int | None:
    """Area of a WGS 84 polygon in square feet (spherical excess on the
    authalic sphere; holes subtract). In one polygon the outer ring and its
    holes run in opposite directions (Esri: outer clockwise; GeoJSON: outer
    counter-clockwise), so the absolute sum of the signed ring areas is its
    area; a GeoJSON MultiPolygon is summed part by part. An Esri polygon with
    several outer rings is summed the same way (all its outer rings share one
    direction). None for no / degenerate geometry."""
    if isinstance(geometry, dict) and geometry.get("type") == "MultiPolygon":
        total = sum(abs(sum(_signed_ring_area_m2(r) for r in poly if isinstance(r, list)))
                    for poly in geometry.get("coordinates") or [] if isinstance(poly, list))
    else:
        rings = _rings(geometry)
        if not rings:
            return None
        total = abs(sum(_signed_ring_area_m2(r) for r in rings))
    sqft = total * _SQFT_PER_M2
    return int(round(sqft)) if sqft >= 1 else None


def _is_no_value(cfg: ParcelSourceConfig, column: str, value) -> bool:
    text = str(value).strip().upper()
    if text in {str(v).upper() for v in cfg.no_value.get(column, ())}:
        return True
    return any(re.match(p, text) for p in cfg.no_value_patterns.get(column, ()))


def composite_value(column: str, parts, attrs: dict):
    """A text column published in parts, joined as the source orders them
    (blank parts skipped, a prefix only beside its own part), or None. The
    FIRST part is required: a street name without its house number is not a
    situs address, so a record missing it yields no value at all."""
    out = []
    for i, (attr, prefix) in enumerate(parts):
        v = _coerce(column, attrs.get(attr))
        if v is None and i == 0:
            return None
        if v is not None:
            out.append(f"{prefix}{v}" if prefix else v)
    return " ".join(out) or None


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
        if v is not None and not _is_no_value(cfg, column, v):
            fields[column] = v
    for column, (attr, cond, accepted) in cfg.conditional_map.items():
        if str(attrs.get(cond) or "").strip().upper() not in {str(a).upper() for a in accepted}:
            continue
        v = _coerce(column, attrs.get(attr))
        if v is not None and not _is_no_value(cfg, column, v):
            fields[column] = v
    for column, parts in cfg.composite_map.items():
        v = composite_value(column, parts, attrs)
        if v is not None and not _is_no_value(cfg, column, v):
            fields[column] = v
    column_years: dict = {}
    for column, floor in cfg.column_year_floor.items():
        if column in fields:
            continue
        attr = cfg.field_map.get(column)
        hist = match.feature.get("_history") or []
        by_year: dict = {}
        for ft in hist:
            y = _latest_value(ft, cfg.latest_field)
            v = _coerce(column, (ft.get("attributes") or {}).get(attr)) if attr else None
            if y is not None and y >= floor and v is not None and not _is_no_value(cfg, column, v):
                by_year.setdefault(y, set()).add(v)
        if by_year:
            y = max(by_year)
            if len(by_year[y]) == 1:
                fields[column] = next(iter(by_year[y]))
                column_years[column] = int(y)
    if year is not None and "value_year" not in fields and any(c in fields for c in ("assessed", "market", "land_value", "improvement_value", "taxable_value")):
        fields["value_year"] = year
    if cfg.centroid:
        c = polygon_centroid(match.feature.get("geometry"))
        if c:
            fields["latitude"], fields["longitude"] = c
    if cfg.derived_lot_area and "lot_sqft" not in fields:
        area = polygon_area_sqft(match.feature.get("geometry"))
        if area:
            fields["lot_sqft"] = area
    county_key = row.get("county") if cfg.county_id else None
    layer = cfg.file_url(county_key) if cfg.transport == "county_file" and county_key in cfg.county_fips else cfg.layer_url
    meta = {"source_id": cfg.source_id, "dataset": cfg.dataset, "agency": cfg.agency, "layer_url": layer,
            "matched_id_field": match.feature.get("_matched_field") or cfg.id_field, "matched_row_column": cfg.row_id_column,
            "matched_parcel_id": match.key, "id_rule": cfg.id_rule_for(county_key),
            "licence": cfg.licence, "value_year": year, "recorded_at": recorded_at}
    if cfg.latest_field and attrs.get(cfg.latest_field) not in (None, ""):
        meta["record_of"] = f"{cfg.latest_field}={attrs.get(cfg.latest_field)} (latest published)"
    raw = {a: attrs.get(a) for a in cfg.provenance_attrs if attrs.get(a) not in (None, "")}
    if raw:
        meta["source_attributes"] = raw
    prov = {}
    for column in fields:
        entry = {"source": "statewide_parcel", **{k: v for k, v in meta.items() if v is not None}}
        if column in column_years:
            entry["record_of"] = (f"{cfg.latest_field}={column_years[column]} (the most recent year publishing this column; "
                                  f"later years leave it blank)")
        if column in ("latitude", "longitude"):
            entry["derived"] = "area-weighted centroid of the matched parcel polygon"
        if column == "lot_sqft" and cfg.derived_lot_area:
            entry["derived"] = DERIVED_AREA_NOTE
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
