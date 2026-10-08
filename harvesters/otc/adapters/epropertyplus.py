"""ePropertyPlus public-portal adapter (Tennessee onboarding, 2026-10-08).

ePropertyPlus is the land-management system several land banks publish
their inventory through. Each tenant serves its own public portal, and the
portal's own code reads the published inventory from

    <portal>/landmgmtpub/remote/public/property/getPublishedProperties?page=<n>&limit=<k>

which answers ``{"success": true, "size": <total>, "rows": [...]}``.
Structure evidence (value-free, `job=evidence`, `evidence_scope=tn_shelby`,
runs 37855584514 / 37855783595 / 37856005485 / 37856189946 / 37856396525) is described in
docs/tennessee-survey.md.

The adapter is configuration-driven: an `EppConfig` names the portal, the
county, and which of the portal's own fields say a row is offered. It does
not fetch - a caller injects `fetch_json(url) -> dict` - and its result is
exactly one of

  COMPLETE  every page read, at least one row carries the configured offered status
  EMPTY     every page read, no row carries it (the portal's own statement)
  FAILED    transport error, success=false, a malformed page, a missing
            required field, a page cap hit, or fewer rows than the portal's own
            `size` - nothing read is trusted, never a partial zero

Free text (`comments`) and the portal's thumbnail URLs are never mapped.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable
from urllib.parse import urlencode

from ..model import AmountKind, InventoryType, OtcRecord, PurchaseUrlKind, SourceAuthority

__all__ = ["EppConfig", "EppResult", "fetch_all", "page_url", "parse_rows"]

LIST_PATH = "/landmgmtpub/remote/public/property/getPublishedProperties"
REQUIRED = ("parcelNumber", "currentStatus", "available")
NO_VALUE = frozenset({"", "NA", "N/A", "TBD", "NONE"})


@dataclass(frozen=True)
class EppConfig:
    source_id: str
    state: str
    county: str
    portal: str                                   # https://<tenant>.epropertyplus.com
    list_url: str                                 # the public page a person opens
    offered: tuple[tuple[str, str], ...]          # every (field, value) must hold for a row to be offered
    id_pattern: str
    inventory_type: InventoryType | None = InventoryType.POST_SALE
    record_source: str = "laft"
    source_authority: SourceAuthority = SourceAuthority.GOVERNMENT_DIRECT
    amount_field: str | None = None
    amount_kind: AmountKind = AmountKind.NOT_PUBLISHED
    amount_label: str = ""
    purchase_url: str | None = None
    purchase_url_kind: PurchaseUrlKind | None = None
    page_limit: int = 500
    max_pages: int = 100
    columns_verified: bool = False
    notes: str = ""


@dataclass
class EppResult:
    outcome: str                                  # COMPLETE | EMPTY | FAILED
    records: list[OtcRecord] = field(default_factory=list)
    error_category: str | None = None
    error_detail: str | None = None
    size: int | None = None
    rows_read: int = 0
    excluded_status: int = 0
    rejected_ids: int = 0
    duplicates: int = 0


def page_url(cfg: EppConfig, page: int) -> str:
    return f"{cfg.portal}{LIST_PATH}?{urlencode({'page': page, 'limit': cfg.page_limit})}"


def _text(v: Any) -> str | None:
    if v is None:
        return None
    s = re.sub(r"\s+", " ", str(v)).strip()
    return s or None


def _positive(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f > 0 else None


def _offered(row: dict, cfg: EppConfig) -> bool:
    return all((_text(row.get(f)) or "").upper() == v.upper() for f, v in cfg.offered)


def parse_rows(cfg: EppConfig, rows: list[dict], *, retrieved_at: datetime) -> tuple[list[OtcRecord], dict]:
    """Rows of the portal's list -> offered records, plus counts."""
    counts = {"excluded_status": 0, "rejected_ids": 0, "duplicates": 0}
    seen: set[str] = set()
    out: list[OtcRecord] = []
    for row in rows:
        if not _offered(row, cfg):
            counts["excluded_status"] += 1
            continue
        pid = _text(row.get("parcelNumber"))
        if not pid or not re.fullmatch(cfg.id_pattern, pid):
            counts["rejected_ids"] += 1
            continue
        if pid in seen:
            counts["duplicates"] += 1
            continue
        seen.add(pid)
        amount = _positive(row.get(cfg.amount_field)) if cfg.amount_field else None
        kind = cfg.amount_kind if amount is not None else AmountKind.NOT_PUBLISHED
        coords = {}
        try:
            lat, lng = float(row.get("latitude")), float(row.get("longitude"))
            if -90 <= lat <= 90 and -180 <= lng <= 180 and (lat, lng) != (0.0, 0.0):
                coords = {"latitude": lat, "longitude": lng}
        except (TypeError, ValueError):
            pass
        land_use = _text(row.get("propertyClass"))
        prov = {
            "adapter": "epropertyplus",
            "portal": cfg.portal,
            "list_endpoint": LIST_PATH,
            "portal_property_id": row.get("id"),
            "offered_rule": " and ".join(f"{f} = {v!r}" for f, v in cfg.offered),
            "amount": (f"field {cfg.amount_field!r} ({cfg.amount_label}) = {kind.value}" if amount is not None
                       else "no amount on the row"),
        }
        if coords:
            prov["coordinates"] = "the portal's own latitude / longitude for the parcel"
        out.append(OtcRecord(
            state=cfg.state, county=cfg.county, case_no=pid,
            source_id=cfg.source_id, source_authority=cfg.source_authority,
            inventory_type=cfg.inventory_type, retrieved_at=retrieved_at,
            parcel=pid,
            address=_text(row.get("propertyAddress1")),
            amount=amount, amount_kind=kind,
            list_url=cfg.list_url, purchase_url=cfg.purchase_url, purchase_url_kind=cfg.purchase_url_kind,
            provenance=prov, record_source=cfg.record_source,
            land_use=None if (land_use or "").upper() in NO_VALUE else land_use,
            assessed=_positive(row.get("currentAssessment")),
            tax_year=_text(row.get("assessmentYear")),
            source_status_text=_text(row.get("currentStatus")),
            **coords,
        ))
    return out, counts


def fetch_all(cfg: EppConfig, fetch_json: Callable[[str], Any], *, retrieved_at: datetime) -> EppResult:
    """Read every page; any failure on any page makes the whole result
    FAILED with no records (a partial inventory would close rows the portal
    still lists)."""
    rows: list[dict] = []
    size = None
    for page in range(1, cfg.max_pages + 1):
        try:
            payload = fetch_json(page_url(cfg, page))
        except Exception as exc:  # noqa: BLE001 - transport is FAILED, never zero
            status = getattr(getattr(exc, "response", None), "status_code", None)
            return EppResult("FAILED", error_category="TRANSPORT_CONNECTION",
                             error_detail=f"page {page}: {type(exc).__name__}" + (f" HTTP {status}" if status else ""))
        if not isinstance(payload, dict) or payload.get("success") is not True or not isinstance(payload.get("rows"), list):
            return EppResult("FAILED", error_category="PARSE_FORMAT_CHANGE", error_detail=f"page {page}: not a success page")
        if not isinstance(payload.get("size"), int):
            return EppResult("FAILED", error_category="PARSE_FORMAT_CHANGE", error_detail=f"page {page}: no total size")
        size = payload["size"]
        batch = payload["rows"]
        if batch and any(k not in batch[0] for k in REQUIRED):
            missing = [k for k in REQUIRED if k not in batch[0]]
            return EppResult("FAILED", error_category="PARSE_FORMAT_CHANGE", error_detail=f"missing field(s) {missing}")
        rows += batch
        if not batch or len(rows) >= size:
            break
    else:
        return EppResult("FAILED", error_category="PARSE_FORMAT_CHANGE", error_detail=f"page cap {cfg.max_pages} hit", size=size)
    if size is None or len(rows) < size:
        return EppResult("FAILED", error_category="PARSE_FORMAT_CHANGE", size=size, rows_read=len(rows),
                         error_detail=f"read {len(rows)} of {size} rows")
    records, counts = parse_rows(cfg, rows, retrieved_at=retrieved_at)
    res = EppResult("COMPLETE" if records else "EMPTY", records=records, size=size, rows_read=len(rows), **counts)
    if not records and counts["rejected_ids"]:
        # Offered rows exist but none carries a valid identifier: a format change, never "empty".
        res.outcome, res.error_category, res.error_detail = "FAILED", "PARSE_FORMAT_CHANGE", "no offered row with a valid parcel id"
    return res
