"""Authoritative geocoding: which source may give a record its coordinates,
what a lookup's outcome means, and whether a coordinate may be written.

The rules (docs/enrichment-geocoding.md):

* Coordinates come only from an official parcel / tax-roll layer, matched on
  the record's own parcel or account identifier, ONE feature per identifier
  (harvesters.sources.coordinates.accept_match). No address matching, no
  fuzzy or partial match, no nearest feature, no other property's point.
* The point is the matched parcel polygon's centroid (PARCEL_CENTROID), and
  is refused when it falls outside the record's state (a projection error or
  a swapped x / y), so a bad answer is a PARSER_FAILURE, never a pin.
* A coordinate is written only when it is strictly stronger than what is
  stored (coordinates.should_replace): a record with no coordinates takes
  any authoritative one; an authoritative coordinate is never replaced by a
  weaker one; a stored coordinate with no recorded origin is replaced ONLY
  when the operator asks for upgrades (allow_upgrade) - the provenance rule
  treats an unrecorded value as government-rank, so replacing one is an
  explicit, separately counted decision.
* A source whose reuse is not cleared (publication not APPROVED) or whose
  columns were never read live is never queried.

Standard library only; network I/O is injected by scripts/geocode_authoritative.py.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from harvesters.enrichment import parcels as P
from harvesters.enrichment.sources import all_sources
from harvesters.sources import coordinates as C

FDOR_LAYER_URL = ("https://services9.arcgis.com/Gh9awoU677aKree0/arcgis/rest/services/"
                  "Florida_Statewide_Cadastral/FeatureServer/0")


@dataclass(frozen=True)
class CoordinateSource:
    source_id: str
    state: str
    method: str                 # coordinates.METHODS
    geometry: str               # coordinates.GEOMETRIES
    provenance_source: str      # scripts/field_provenance.RANK key
    agency: str
    dataset: str
    layer_url: str
    landing_url: str
    publication_status: str
    verified: bool              # the layer's fields were read live
    identifier_column: str = "parcel"
    counties: tuple = ()        # () = every county of the state
    parcel_cfg: object = None   # harvesters.enrichment.parcels.ParcelSourceConfig for ArcGIS layers
    lookup_kind: str = "parcel_layer"   # parcel_layer | fdor | santa_rosa (FL lookups reuse enrich_property_details)

    def covers(self, state: str, county: str) -> bool:
        return state == self.state and (not self.counties or county in self.counties)

    def usable(self) -> tuple[bool, str]:
        if self.publication_status not in P.APPROVED_PUBLICATION:
            return False, "SOURCE_NOT_APPROVED"
        if not self.verified:
            return False, "SOURCE_UNVERIFIED"
        return True, ""


FDOR_SOURCE = CoordinateSource(
    source_id="fl_fdor_cadastral", state="FL", method="TAX_ROLL", geometry="PARCEL_CENTROID",
    provenance_source="fdor_nal", agency="Florida Department of Revenue",
    dataset="Florida Statewide Cadastral (FDOR NAL parcel layer)", layer_url=FDOR_LAYER_URL,
    landing_url="https://floridarevenue.com/property/Pages/DataPortal.aspx",
    publication_status="APPROVED", verified=True, lookup_kind="fdor",
)

# Santa Rosa's own parcel layer: FDOR never matches this county's numbering,
# and the enricher already reads this layer (enrich_property_details
# lookup_santa_rosa_gis), whose PAR_NUM equals the stored parcel and which
# returns the polygon centroid. Flagler's county layer returns no centroid,
# so it is NOT a coordinate source.
SANTA_ROSA_SOURCE = CoordinateSource(
    source_id="fl_santa_rosa_parcels", state="FL", method="PARCEL_GIS", geometry="PARCEL_CENTROID",
    provenance_source="county_gis", agency="Santa Rosa County (ParcelsOpenData)",
    dataset="ParcelsOpenData", landing_url="https://www.santarosa.fl.gov/",
    layer_url="https://services.arcgis.com/Eg4L1xEv2R3abuQd/arcgis/rest/services/ParcelsOpenData/FeatureServer/0",
    publication_status="APPROVED", verified=True, counties=("Santa Rosa",), lookup_kind="santa_rosa",
)


def _parcel_layer_sources() -> list[CoordinateSource]:
    out = []
    for cfg in all_sources():
        if not cfg.centroid:
            continue
        out.append(CoordinateSource(
            source_id=cfg.source_id, state=cfg.state, method="PARCEL_GIS", geometry="PARCEL_CENTROID",
            provenance_source="statewide_parcel", agency=cfg.agency, dataset=cfg.dataset, layer_url=cfg.layer_url,
            landing_url=cfg.landing_url, publication_status=cfg.publication_status, verified=cfg.columns_verified,
            identifier_column=cfg.row_id_column, counties=tuple(cfg.counties), parcel_cfg=cfg))
    return out


def coordinate_sources() -> list[CoordinateSource]:
    """Every configured coordinate source, FDOR first. County-scoped layers
    come before a state's statewide one, so the more local source is tried
    first when both cover a county."""
    srcs = [FDOR_SOURCE, SANTA_ROSA_SOURCE, *_parcel_layer_sources()]
    return sorted(srcs, key=lambda s: (s.state, 0 if s.counties else 1, s.source_id))


def sources_for(state: str, county: str) -> list[CoordinateSource]:
    return [s for s in coordinate_sources() if s.covers(state, county)]


# --- state bounds: a point outside its record's state is never written ------
# (min_lat, max_lat, min_lng, max_lng), generous by ~0.5 degree.
STATE_BOUNDS = {
    "FL": (24.0, 31.5, -88.0, -79.5), "TX": (25.5, 37.0, -107.0, -93.0), "LA": (28.5, 33.5, -94.5, -88.5),
    "MI": (41.2, 48.8, -90.9, -82.0), "WY": (40.5, 45.5, -111.5, -103.5), "SC": (31.8, 35.7, -83.9, -78.0),
    "CO": (36.5, 41.5, -109.6, -101.5), "WI": (42.0, 47.5, -93.2, -86.2), "MO": (35.5, 41.1, -96.3, -88.6),
    "OK": (33.3, 37.5, -103.5, -94.0), "PA": (39.2, 42.8, -81.0, -74.2), "MN": (43.0, 49.8, -97.7, -89.0),
    "UT": (36.5, 42.5, -114.5, -108.5), "AL": (30.0, 35.5, -88.9, -84.4), "AR": (32.5, 37.0, -95.0, -89.2),
    "AZ": (31.0, 37.5, -115.0, -108.5), "WV": (37.0, 40.7, -83.2, -77.2),
}


def in_state(lat: float, lng: float, state: str) -> bool:
    b = STATE_BOUNDS.get(state)
    if b is None:
        return False
    return b[0] <= lat <= b[1] and b[2] <= lng <= b[3]


# --- planning ---------------------------------------------------------------
PLAN_CLASSES = ("MISSING", "UPGRADE", "UPGRADE_NOT_REQUESTED", "ALREADY_AUTHORITATIVE",
                "NO_IDENTIFIER", "NO_SOURCE", "SOURCE_NOT_APPROVED", "SOURCE_UNVERIFIED")
LOOKUP_CLASSES = ("MISSING", "UPGRADE")


def _identifier(row: dict, src: CoordinateSource) -> str | None:
    v = row.get(src.identifier_column)
    if v is None or not str(v).strip():
        return None
    s = str(v).strip()
    return s if any(ch.isdigit() for ch in s) and len(s) <= 40 else None


def plan_row(row: dict, *, allow_upgrade: bool = False) -> tuple[str, CoordinateSource | None]:
    """(plan class, the source to query or None). Never touches the network."""
    state, county = str(row.get("state") or ""), str(row.get("county") or "")
    existing = C.coordinate_provenance(row)["method"]
    candidates = sources_for(state, county)
    if not candidates:
        return ("ALREADY_AUTHORITATIVE" if existing in C.AUTHORITATIVE else "NO_SOURCE"), None
    reasons = []
    for src in candidates:
        ok, why = src.usable()
        if not ok:
            reasons.append(why)
            continue
        if existing != "NONE" and not C.should_replace(existing, src.method):
            return "ALREADY_AUTHORITATIVE", src
        if _identifier(row, src) is None:
            reasons.append("NO_IDENTIFIER")
            continue
        if existing == "NONE":
            return "MISSING", src
        return ("UPGRADE" if allow_upgrade else "UPGRADE_NOT_REQUESTED"), src
    if existing in C.AUTHORITATIVE:
        return "ALREADY_AUTHORITATIVE", None
    for why in ("NO_IDENTIFIER", "SOURCE_UNVERIFIED", "SOURCE_NOT_APPROVED"):
        if why in reasons:
            return why, None
    return "NO_SOURCE", None


# --- lookup outcomes ----------------------------------------------------------
OUTCOMES = ("MATCHED", "NO_MATCH", "AMBIGUOUS", "SOURCE_UNAVAILABLE", "PARSER_FAILURE", "NO_IDENTIFIER")


@dataclass
class Lookup:
    status: str                       # OUTCOMES
    lat: float | None = None
    lng: float | None = None
    matched_identifier: str = ""
    matched_field: str = ""
    reason: str = ""


def classify_point(lat, lng, state: str, *, matched_identifier: str = "", matched_field: str = "") -> Lookup:
    """A single matched feature's point -> MATCHED, or PARSER_FAILURE when it
    is missing, not a number, or outside the record's state."""
    try:
        la, ln = float(lat), float(lng)
    except (TypeError, ValueError):
        return Lookup("PARSER_FAILURE", reason="the matched feature carried no usable point")
    if la != la or ln != ln or not in_state(la, ln, state):
        return Lookup("PARSER_FAILURE", reason="the matched point is outside the record's state")
    return Lookup("MATCHED", la, ln, matched_identifier, matched_field)


def from_feature_count(features: list, state: str, *, point_of, matched_identifier: str = "",
                       matched_field: str = "") -> Lookup:
    """The deterministic rule for a feature list: exactly one feature is a
    match (its point checked), none is NO_MATCH, more than one is AMBIGUOUS.
    `point_of(feature)` returns (lat, lng) or None."""
    if not features:
        return Lookup("NO_MATCH")
    if not C.accept_match("parcel_id", len(features)):
        return Lookup("AMBIGUOUS", reason=f"{len(features)} features share the identifier - nothing attached")
    pt = point_of(features[0])
    if not pt:
        return Lookup("PARSER_FAILURE", reason="the matched feature carried no usable geometry")
    return classify_point(pt[0], pt[1], state, matched_identifier=matched_identifier, matched_field=matched_field)


def lookup_parcel_layer(src: CoordinateSource, rows: list[dict], fetch_json) -> dict[str, Lookup]:
    """Batch lookup against one ArcGIS parcel layer (row id -> Lookup).
    A failed / error query marks every row of the county SOURCE_UNAVAILABLE."""
    cfg = src.parcel_cfg
    out: dict[str, Lookup] = {}
    by_county: dict[str, list[dict]] = {}
    for r in rows:
        by_county.setdefault(str(r.get("county") or ""), []).append(r)
    for county, crow in sorted(by_county.items()):
        features, failed, parse_fail = [], False, False
        for url in P.query_urls(cfg, county, [r.get(cfg.row_id_column) for r in crow]):
            try:
                data = fetch_json(url)
            except ValueError:
                parse_fail = True
                break
            except Exception:  # noqa: BLE001 - transport / HTTP failure
                failed = True
                break
            if not isinstance(data, dict) or "error" in data or not isinstance(data.get("features"), list):
                failed = True
                break
            features += data["features"]
        if failed or parse_fail:
            status = "PARSER_FAILURE" if parse_fail else "SOURCE_UNAVAILABLE"
            out.update({r["id"]: Lookup(status, reason="the layer query failed") for r in crow})
            continue
        idx = P.index_features(cfg, features)
        for m in P.match_rows(cfg, crow, idx):
            if m.status == "NO_IDENTIFIER":
                out[m.row_id] = Lookup("NO_IDENTIFIER", reason=m.reason)
            elif m.status == "UNMATCHED":
                out[m.row_id] = Lookup("NO_MATCH", reason=m.reason)
            elif m.status == "AMBIGUOUS":
                out[m.row_id] = Lookup("AMBIGUOUS", reason=m.reason)
            else:
                pt = P.polygon_centroid(m.feature.get("geometry"))
                state = cfg.state
                out[m.row_id] = (classify_point(pt[0], pt[1], state, matched_identifier=m.key or "",
                                                matched_field=m.feature.get("_matched_field") or cfg.id_field)
                                 if pt else Lookup("PARSER_FAILURE", reason="the matched parcel carried no polygon"))
    return out


# --- the write decision ---------------------------------------------------------
def provenance_entry(src: CoordinateSource, lk: Lookup, recorded_at: str) -> dict:
    """The field_provenance entry for latitude / longitude: source, the
    layer read, the read date, the matching method and the coordinate type."""
    return {
        "source": src.provenance_source, "recorded_at": recorded_at,
        "method": src.method, "geometry": src.geometry,
        "match": "parcel_id", "matched_identifier": lk.matched_identifier,
        "matched_field": lk.matched_field or None,
        "source_id": src.source_id, "agency": src.agency, "dataset": src.dataset,
        "layer_url": src.layer_url, "landing_url": src.landing_url,
        "derived": "centroid of the one parcel polygon whose identifier equals this record's",
        "pipeline": "geocode_authoritative",
    }


def decide(row: dict, src: CoordinateSource, lk: Lookup, *, allow_upgrade: bool, recorded_at: str):
    """('write', fields) or ('skip', reason)."""
    if lk.status != "MATCHED":
        return "skip", lk.status
    existing = C.coordinate_provenance(row)["method"]
    if existing != "NONE":
        if not C.should_replace(existing, src.method):
            return "skip", "STRONGER_OR_EQUAL_EXISTING"
        if not allow_upgrade:
            return "skip", "UPGRADE_NOT_REQUESTED"
    entry = {k: v for k, v in provenance_entry(src, lk, recorded_at).items() if v not in (None, "")}
    fp = dict(row.get("field_provenance") or {}) if isinstance(row.get("field_provenance"), dict) else {}
    fp["latitude"] = entry
    fp["longitude"] = entry
    return "write", {"latitude": round(lk.lat, 7), "longitude": round(lk.lng, 7), "field_provenance": fp}


# --- run accounting ---------------------------------------------------------------
@dataclass
class Report:
    mode: str
    allow_upgrade: bool = False
    rows_read: int = 0
    plan: dict = field(default_factory=dict)          # PLAN_CLASSES -> count
    by_rule: dict = field(default_factory=dict)       # P1..P7 -> candidates
    by_source: dict = field(default_factory=dict)     # source_id -> candidates
    candidates: int = 0
    looked_up: int = 0
    matched: int = 0
    no_match: int = 0
    ambiguous: int = 0
    source_unavailable: int = 0
    parser_failure: int = 0
    no_identifier: int = 0
    would_write: int = 0
    written: int = 0
    skipped: dict = field(default_factory=dict)       # reason -> count
    write_errors: int = 0

    def add_outcome(self, status: str) -> None:
        attr = {"MATCHED": "matched", "NO_MATCH": "no_match", "AMBIGUOUS": "ambiguous",
                "SOURCE_UNAVAILABLE": "source_unavailable", "PARSER_FAILURE": "parser_failure",
                "NO_IDENTIFIER": "no_identifier"}[status]
        setattr(self, attr, getattr(self, attr) + 1)

    def skip(self, reason: str) -> None:
        self.skipped[reason] = self.skipped.get(reason, 0) + 1

    def as_dict(self) -> dict:
        d = dict(self.__dict__)
        for k in ("plan", "by_rule", "by_source", "skipped"):
            d[k] = dict(sorted(d[k].items()))
        return d
