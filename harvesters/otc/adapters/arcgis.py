"""Generic ArcGIS FeatureServer / MapServer layer adapter.

Several state-level tax-land publishers the 50-state audit found expose
their inventory as an ArcGIS REST layer (a `/FeatureServer/<n>` or
`/MapServer/<n>` endpoint answering `/query`). This adapter turns one such
layer into `OtcRecord`s. It is configuration-driven and state-agnostic: a
layer is an `ArcGisLayerConfig` naming the endpoint, the attribute that is
the source's own identifier, and which attributes hold which fields -
never a state- or source-specific parser. No layer is configured here.

It does NOT fetch. A caller injects a `fetch_json(url) -> dict` callable
(so this module has no HTTP dependency - a test enforces that) and gets
back an `ArcGisResult` whose `outcome` is exactly one of

  COMPLETE  every page was read; at least one feature parsed
  EMPTY     every page was read; the layer returned zero features for the
            configured `where` - the layer's own statement, not an error
  FAILED    transport error, an ArcGIS error payload, a malformed
            response, a page cap hit, or an identifier the layer did not
            provide - NOTHING read from that fetch is trusted as an
            inventory; the caller gets no records, never a partial zero

Unavailable is never mistaken for empty. Pagination is deterministic
(ordered by the identifier, offset/count paging, stopped by the
`exceededTransferLimit` flag the service sets) and capped so a service
that keeps saying "more" cannot run forever.

Running this against a live source additionally requires (a) a
`columns_verified=True` configuration, which only exists after a human has
fetched the layer and read its fields, and (b) a `gate.evaluate_source()`
decision of allowed=True for the source. Neither exists for any source.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

from ...governance import states
from ..model import AmountKind, InventoryType, OtcRecord, PurchaseUrlKind, SourceAuthority

__all__ = ["ArcGisError", "ArcGisFieldMap", "ArcGisLayerConfig", "ArcGisResult", "PageResult",
           "fetch_all", "parse_page", "query_params", "query_url"]

LAYER_URL_RE = re.compile(r"^https://[^?#]+/(FeatureServer|MapServer)/\d+$")


class ArcGisError(Exception):
    """A response that cannot be read as a layer page. `category` is one of
    the scripts/laft_status.py error categories."""

    def __init__(self, category: str, detail: str) -> None:
        super().__init__(f"{category}: {detail}")
        self.category = category
        self.detail = detail


@dataclass(frozen=True)
class ArcGisFieldMap:
    """Layer attribute name -> record field. Only `case_no` (the source's
    own identifier) is required; the rest are read when named."""
    case_no: str
    parcel: str | None = None
    address: str | None = None
    legal_desc: str | None = None
    amount: str | None = None
    status: str | None = None
    # Six-state sprint: property facts the layer itself publishes on the
    # row (never computed, never joined from elsewhere).
    owner_name: str | None = None
    acreage: str | None = None
    land_use: str | None = None
    taxable_value: str | None = None
    assessed: str | None = None
    market: str | None = None
    tax_year: str | None = None
    latitude: str | None = None
    longitude: str | None = None
    sold_flag: str | None = None         # the layer's own "has been sold" flag attribute, when it publishes one

    def named(self) -> dict[str, str]:
        return {k: v for k, v in vars(self).items() if v}


@dataclass(frozen=True)
class ArcGisLayerConfig:
    source_id: str
    state: str
    source_authority: SourceAuthority
    inventory_type: InventoryType | None
    layer_url: str                       # https://host/.../FeatureServer/3  (no /query)
    fields: ArcGisFieldMap
    # Exactly one of: a fixed county (a county-level publisher) or the
    # attribute that names the county per feature (a statewide publisher).
    county: str | None = None
    county_field: str | None = None
    amount_kind: AmountKind = AmountKind.NOT_PUBLISHED   # what the amount attribute IS, from the layer's field alias
    where: str = "1=1"
    page_size: int = 1000
    max_pages: int = 100
    list_url: str | None = None          # the human-facing page the layer backs, if any
    purchase_url: str | None = None
    purchase_url_kind: PurchaseUrlKind | None = None
    columns_verified: bool = False       # True only after a human read the live layer's fields
    notes: str = ""
    record_source: str = "laft"          # "laft" (AVAILABLE) | "certificate" | "auction" (six-state sprint)

    def __post_init__(self) -> None:
        if not LAYER_URL_RE.match(self.layer_url):
            raise ValueError(f"layer_url must be https://.../FeatureServer/<n> or /MapServer/<n>: {self.layer_url!r}")
        problems = states.state_problems(self.state)
        if problems:
            raise ValueError("; ".join(problems))
        if (self.county is None) == (self.county_field is None):
            raise ValueError("exactly one of county / county_field is required")
        if not self.fields.case_no:
            raise ValueError("fields.case_no (the layer's identifier attribute) is required")
        if self.page_size <= 0 or self.max_pages <= 0:
            raise ValueError("page_size and max_pages must be positive")
        if not self.where.strip():
            raise ValueError("where must not be blank (use 1=1 for the whole layer)")
        if (self.purchase_url is None) != (self.purchase_url_kind is None):
            raise ValueError("purchase_url and purchase_url_kind go together")


@dataclass
class PageResult:
    records: list[OtcRecord]
    exceeded_transfer_limit: bool
    feature_count: int
    object_id_field: str | None


@dataclass
class ArcGisResult:
    outcome: str                               # COMPLETE | EMPTY | FAILED
    records: list[OtcRecord] = field(default_factory=list)
    pages: int = 0
    error_category: str | None = None
    error_detail: str | None = None

    @property
    def ok(self) -> bool:
        return self.outcome in ("COMPLETE", "EMPTY")


def _out_fields(cfg: ArcGisLayerConfig) -> list[str]:
    names = list(cfg.fields.named().values())
    if cfg.county_field:
        names.append(cfg.county_field)
    seen: list[str] = []
    for n in names:
        if n not in seen:
            seen.append(n)
    return seen


def query_params(cfg: ArcGisLayerConfig, offset: int = 0) -> dict[str, str]:
    """The `/query` parameters for one page. Ordered by the identifier so
    offset paging is deterministic across pages; no geometry (this is an
    inventory list, not a map)."""
    return {
        "f": "json",
        "where": cfg.where,
        "outFields": ",".join(_out_fields(cfg)),
        "returnGeometry": "false",
        "orderByFields": cfg.fields.case_no,
        "resultOffset": str(offset),
        "resultRecordCount": str(cfg.page_size),
    }


def _quote(value: str) -> str:
    """RFC 3986 percent-encoding of everything but unreserved characters.
    Local so this package keeps its no-HTTP-imports rule (urllib included)."""
    return "".join(c if (c.isascii() and c.isalnum()) or c in "-._~" else
                   "".join(f"%{b:02X}" for b in c.encode("utf-8")) for c in value)


def query_url(cfg: ArcGisLayerConfig, offset: int = 0) -> str:
    return f"{cfg.layer_url}/query?" + "&".join(f"{k}={_quote(v)}" for k, v in query_params(cfg, offset).items())


def _amount(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value) if value >= 0 else None
    cleaned = re.sub(r"[^0-9.]", "", str(value))
    if not re.match(r"^\d+(\.\d+)?$", cleaned):
        return None
    return float(cleaned)


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _positive(value: Any) -> float | None:
    """A published figure > 0, else None (0 / blank = not published)."""
    try:
        n = _amount(value)
    except (ValueError, TypeError):
        return None
    return n if n is not None and n > 0 else None


SOLD_YES = {"Y", "YES", "TRUE", "T", "1", "SOLD"}


def _sold(attrs: dict, fm: ArcGisFieldMap) -> dict:
    """The layer's own sold flag: 'yes' -> a published 'sold' outcome with the
    source's wording; anything else says nothing (never inferred)."""
    if not fm.sold_flag:
        return {}
    raw = _text(attrs.get(fm.sold_flag))
    if raw and raw.strip().upper() in SOLD_YES:
        return {"published_outcome": "sold", "source_status_text": f"{fm.sold_flag}: {raw}"}
    return {}


def _coords(attrs: dict, fm: ArcGisFieldMap) -> dict:
    """Latitude/longitude only when the layer publishes both, in range."""
    if not (fm.latitude and fm.longitude):
        return {}
    try:
        lat, lng = float(attrs.get(fm.latitude)), float(attrs.get(fm.longitude))
    except (TypeError, ValueError):
        return {}
    if -90 <= lat <= 90 and -180 <= lng <= 180 and (lat, lng) != (0.0, 0.0):
        return {"latitude": lat, "longitude": lng}
    return {}


def parse_page(cfg: ArcGisLayerConfig, payload: Any, *, retrieved_at: datetime, offset: int = 0) -> PageResult:
    """One `/query` response -> records. Raises ArcGisError for an error
    payload or a shape that is not a layer page - a caller must treat that
    as FAILED, never as zero rows."""
    if not isinstance(payload, dict):
        raise ArcGisError("PARSE_FORMAT_CHANGE", f"response is {type(payload).__name__}, not a JSON object")
    if "error" in payload:
        err = payload.get("error")
        code = err.get("code") if isinstance(err, dict) else None
        msg = err.get("message") if isinstance(err, dict) else str(err)
        raise ArcGisError("SOURCE_ERROR", f"ArcGIS error {code}: {msg}")
    features = payload.get("features")
    if not isinstance(features, list):
        raise ArcGisError("PARSE_FORMAT_CHANGE", "no `features` list in response")
    object_id_field = _text(payload.get("objectIdFieldName"))
    fm = cfg.fields
    records: list[OtcRecord] = []
    for i, feat in enumerate(features):
        attrs = feat.get("attributes") if isinstance(feat, dict) else None
        if not isinstance(attrs, dict):
            raise ArcGisError("PARSE_FORMAT_CHANGE", f"feature {offset + i} has no attributes object")
        case_no = _text(attrs.get(fm.case_no))
        if case_no is None:
            # The identifier IS the identity. A feature without one cannot
            # be a deterministic record; the whole fetch is untrusted.
            raise ArcGisError("PARSE_FORMAT_CHANGE", f"feature {offset + i} has no {fm.case_no!r} value")
        if cfg.county is not None:
            county = cfg.county
        else:
            county = _text(attrs.get(cfg.county_field))
            if county is None:
                raise ArcGisError("PARSE_FORMAT_CHANGE", f"feature {offset + i} has no {cfg.county_field!r} value")
        amount = _amount(attrs.get(fm.amount)) if fm.amount else None
        kind = cfg.amount_kind if amount is not None else AmountKind.NOT_PUBLISHED
        if amount is not None and kind is AmountKind.NOT_PUBLISHED:
            # A configured layer that names an amount attribute must say
            # what it is; an unlabelled figure is not silently kept.
            kind = AmountKind.PUBLISHED_AMOUNT_KIND_UNSPECIFIED
        present = {f: True for f, attr in fm.named().items() if _text(attrs.get(attr)) is not None}
        prov = {
            "adapter": "arcgis",
            "layer_url": cfg.layer_url,
            "query_where": cfg.where,
            "id_field": fm.case_no,
            "object_id_field": object_id_field,
            "object_id": attrs.get(object_id_field) if object_id_field else None,
            "attributes": present,
            "amount": (f"attribute {fm.amount!r} = {kind.value}" if amount is not None else "no amount attribute value"),
        }
        records.append(OtcRecord(
            state=cfg.state, county=county, case_no=case_no,
            source_id=cfg.source_id, source_authority=cfg.source_authority,
            inventory_type=cfg.inventory_type, retrieved_at=retrieved_at,
            parcel=_text(attrs.get(fm.parcel)) if fm.parcel else None,
            address=_text(attrs.get(fm.address)) if fm.address else None,
            legal_desc=_text(attrs.get(fm.legal_desc)) if fm.legal_desc else None,
            amount=amount, amount_kind=kind,
            list_url=cfg.list_url, document_url=None,
            purchase_url=cfg.purchase_url, purchase_url_kind=cfg.purchase_url_kind,
            provenance=prov,
            record_source=cfg.record_source,
            owner_name=_text(attrs.get(fm.owner_name)) if fm.owner_name else None,
            acreage=_positive(attrs.get(fm.acreage)) if fm.acreage else None,
            land_use=_text(attrs.get(fm.land_use)) if fm.land_use else None,
            taxable_value=_positive(attrs.get(fm.taxable_value)) if fm.taxable_value else None,
            assessed=_positive(attrs.get(fm.assessed)) if fm.assessed else None,
            market=_positive(attrs.get(fm.market)) if fm.market else None,
            tax_year=_text(attrs.get(fm.tax_year)) if fm.tax_year else None,
            **_coords(attrs, fm),
            **({"source_status_text": _text(attrs.get(fm.status))} if fm.status and not _sold(attrs, fm) else {}),
            **_sold(attrs, fm),
        ))
    return PageResult(records=records, exceeded_transfer_limit=bool(payload.get("exceededTransferLimit")),
                      feature_count=len(features), object_id_field=object_id_field)


def fetch_all(cfg: ArcGisLayerConfig, fetch_json: Callable[[str], Any], *, retrieved_at: datetime) -> ArcGisResult:
    """Read every page of the layer through `fetch_json(url)`. Any failure
    on any page makes the whole result FAILED with no records: a partial
    inventory would let the lifecycle close rows the layer still lists."""
    records: list[OtcRecord] = []
    offset = 0
    pages = 0
    while True:
        if pages >= cfg.max_pages:
            return ArcGisResult("FAILED", pages=pages, error_category="PARSE_TRUNCATED",
                                error_detail=f"layer still reported more features after {pages} pages of {cfg.page_size}")
        url = query_url(cfg, offset)
        try:
            payload = fetch_json(url)
        except Exception as exc:  # noqa: BLE001 - any transport failure is FAILED, never zero
            return ArcGisResult("FAILED", pages=pages, error_category="TRANSPORT", error_detail=f"{type(exc).__name__}: {exc}")
        try:
            page = parse_page(cfg, payload, retrieved_at=retrieved_at, offset=offset)
        except ArcGisError as exc:
            return ArcGisResult("FAILED", pages=pages, error_category=exc.category, error_detail=exc.detail)
        pages += 1
        records.extend(page.records)
        if not page.exceeded_transfer_limit or page.feature_count == 0:
            break
        offset += page.feature_count
    seen: set[tuple[str, str]] = set()
    for r in records:
        key = (r.county, r.case_no)
        if key in seen:
            return ArcGisResult("FAILED", pages=pages, error_category="PARSE_FORMAT_CHANGE",
                                error_detail=f"identifier {r.case_no!r} in {r.county} appeared twice across pages - paging is not stable")
        seen.add(key)
    return ArcGisResult("COMPLETE" if records else "EMPTY", records=records, pages=pages)
