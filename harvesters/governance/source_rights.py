"""Source rights: one view over the permission engine for every use of a
source's data, the reconciliation of the 2026-10-12 disposition register
against the code, and the customer-safe provenance contract (2026-10-16).

This module never grants anything. Every answer comes from
`permissions.authorize()` (data/source_permissions.csv), evaluated per
county and per dataset; the register (data/audit/source_register_2026-10-12.csv)
is an audit baseline, never an authorization.

Three parts:

1. `rights_profile(source_id, state, county, dataset)` - the decision for
   each USE of a source's data: ingest (fetch + parse), persist (store),
   refresh (fetch + parse + store, all three), customer display, commercial
   use (display on DOCUMENTED permission only - an interim allowance is never
   commercial permission), export / redistribution, enrichment, link,
   parcel geometry (no module grants it: denied), imagery (the imagery
   registry's terms) and the attribution text the record carries. Every
   composite use is allowed only when EVERY operation in it is allowed, so a
   condition unmet on one operation fails the whole use.

2. `reconcile()` - maps each register row to the code source ids
   (data/audit/register_code_map.csv), evaluates the permission engine at
   each county of the row's scope, and reports every operation the code
   allows beyond the register's decision (its "ceiling"), every register row
   with no code source, and every code source with no register row.

3. The customer contract: `customer_source_notice()` (attribution and a
   fixed, customer-safe basis label - never a reviewer, a reason, an
   evidence reference, a contact or correspondence) and
   `field_provenance_view(row, field)` (source, origin, the row's own
   timestamps, freshness and a value status from a fixed vocabulary). A
   timestamp is reported only when the row carries it; nothing is inferred
   from the current time; an unknown value is never a zero.

Standard library only.
"""
from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from . import permissions as P

REPO = Path(__file__).resolve().parents[2]
REGISTER_CSV = REPO / "data" / "audit" / "source_register_2026-10-12.csv"
CODE_MAP_CSV = REPO / "data" / "audit" / "register_code_map.csv"
REGISTRY_CSV = REPO / "data" / "county_source_registry.csv"

# --- 1. composite uses ------------------------------------------------------

COMPOSITE_USES: dict[str, tuple[str, ...]] = {
    "ingest": ("fetch", "parse"),
    "persist": ("store",),
    "refresh": ("fetch", "parse", "store"),
    "customer_display": ("display",),
    "commercial_use": ("display",),      # plus: DOCUMENTED basis on every operation
    "export": ("redistribute",),
    "enrich": ("enrich",),
    "link": ("link",),
}
DOCUMENTED_ONLY_USES = frozenset({"commercial_use", "export"})


@dataclass(frozen=True)
class UseDecision:
    use: str
    allowed: bool
    basis: str                # DOCUMENTED | INTERIM | LINK_ONLY | DENIED
    reason_code: str
    operations: tuple[str, ...] = ()
    conditions: tuple[str, ...] = ()

    def as_dict(self) -> dict:
        return {"use": self.use, "allowed": self.allowed, "basis": self.basis, "reason_code": self.reason_code,
                "operations": list(self.operations), "conditions": list(self.conditions)}


def _use(perms: P.Permissions, use: str, source_id, state, county, dataset, today) -> UseDecision:
    ops = COMPOSITE_USES[use]
    decisions = [perms.authorize(source_id, op, state=state, county=county, dataset=dataset, today=today) for op in ops]
    conds = tuple(sorted({c for d in decisions for c in d.conditions}))
    for d in decisions:
        if not d.allowed:
            return UseDecision(use, False, "DENIED", d.reason_code, ops, conds)
    bases = {d.basis for d in decisions}
    basis = "DOCUMENTED" if bases == {"DOCUMENTED"} else "LINK_ONLY" if bases == {"LINK_ONLY"} else "INTERIM"
    if use in DOCUMENTED_ONLY_USES and basis != "DOCUMENTED":
        return UseDecision(use, False, "DENIED", "NEEDS_DOCUMENTED_PERMISSION", ops, conds)
    return UseDecision(use, True, basis, "ALLOWED_" + basis, ops, conds)


def _imagery_use(source_id: str) -> UseDecision:
    try:
        from harvesters import imagery as IM  # noqa: PLC0415
        src = IM.SOURCES.get(source_id)
    except Exception:  # noqa: BLE001 - no registry, no imagery
        src = None
    if not src:
        return UseDecision("imagery", False, "DENIED", "NOT_AN_IMAGERY_SOURCE")
    terms = src.get("terms_status", "")
    if terms == "APPROVED":
        return UseDecision("imagery", True, "DOCUMENTED", "IMAGERY_TERMS_APPROVED")
    if terms == "PROVIDER_DISPLAY":
        return UseDecision("imagery", True, "LINK_ONLY", "IMAGERY_PROVIDER_DISPLAY_ONLY")
    return UseDecision("imagery", False, "DENIED", "IMAGERY_TERMS_" + (terms or "UNKNOWN"))


def rights_profile(source_id: str, *, state: str, county: str | None = None, dataset: str | None = None,
                   today: date | None = None, perms: P.Permissions | None = None) -> dict:
    """Every use of one source's data at one place, fail closed."""
    perms = perms or P.default()
    today = today or date.today()
    uses = {u: _use(perms, u, source_id, state, county, dataset, today).as_dict() for u in COMPOSITE_USES}
    # No module grants parcel polygons (storage or display): a centroid point
    # reaches a record only through an `enrich` permission on the
    # parcel_centroid dataset. Geometry is therefore always denied here.
    uses["geometry"] = UseDecision("geometry", False, "DENIED", "NO_GEOMETRY_PERMISSION").as_dict()
    uses["imagery"] = _imagery_use(source_id).as_dict()
    disp = perms.authorize(source_id, "display", state=state, county=county, dataset=dataset, today=today)
    rec = _record_for(perms, disp)
    return {"source_id": source_id, "state": state, "county": county, "dataset": dataset, "uses": uses,
            "attribution": (rec.attribution if rec and disp.allowed else "")}


def _record_for(perms: P.Permissions, decision: P.PermissionDecision) -> P.PermissionRecord | None:
    if not decision.record_line:
        return None
    for r in perms.records:
        if r.line == decision.record_line:
            return r
    return None


# --- 3. the customer contract -----------------------------------------------

# The only basis wording a customer ever sees. Internal evidence types,
# reviewers, reasons, references, contacts and correspondence never leave
# the permission records.
CUSTOMER_BASIS_LABELS = {
    "DOCUMENTED": "Published under the source's licence or written permission",
    "INTERIM": "Public record shown as published by the source",
    "LINK_ONLY": "Link to the source's own page only",
    "DENIED": "Not shown",
}
CUSTOMER_CONDITION_LABELS = {
    "attribution_text_recorded": "Attribution required",
    "dated_list_only": "Dated list - not a statement of current availability",
    "excluded_from_paid_tier": "Not part of paid plans",
}
INTERNAL_KEYS = frozenset({"reviewer", "reason", "evidence_ref", "evidence_type", "evidence_date", "record_line",
                           "status", "contact_decision_maker", "outreach_status", "remaining_questions",
                           "legal_status", "recommended_next_action", "governance_reason", "next_action"})


def customer_source_notice(source_id: str, *, state: str, county: str | None = None, dataset: str | None = None,
                           today: date | None = None, perms: P.Permissions | None = None) -> dict:
    """What a customer may be told about a source. Nothing internal."""
    perms = perms or P.default()
    d = perms.authorize(source_id, "display", state=state, county=county, dataset=dataset, today=today)
    if not d.allowed:
        link = perms.authorize(source_id, "link", state=state, county=county, dataset=dataset, today=today)
        basis = "LINK_ONLY" if link.allowed else "DENIED"
        return {"source_id": source_id, "shown": False, "basis": CUSTOMER_BASIS_LABELS[basis],
                "attribution": "", "conditions": []}
    rec = _record_for(perms, d)
    return {"source_id": source_id, "shown": True, "basis": CUSTOMER_BASIS_LABELS[d.basis],
            "attribution": rec.attribution if rec else "",
            "conditions": [CUSTOMER_CONDITION_LABELS.get(c, "Use conditions apply") for c in d.conditions]}


VALUE_STATUSES = ("CONFIRMED_SOURCE", "ESTIMATED_BY_SOURCE", "DERIVED_BY_TAXACQ", "UNVERIFIED",
                  "NOT_PUBLISHED", "NOT_TRACKED")
VALUE_STATUS_LABELS = {
    "CONFIRMED_SOURCE": "As published by the source",
    "ESTIMATED_BY_SOURCE": "Estimate published by the source",
    "DERIVED_BY_TAXACQ": "Derived by TAXACQ",
    "UNVERIFIED": "Not verified",
    "NOT_PUBLISHED": "Not published by the source",
    "NOT_TRACKED": "Not tracked",
}
FRESHNESS_STATES = ("CURRENT", "STALE", "UNVERIFIED", "WITHDRAWN", "NOT_TRACKED")

# Fields the product tracks for a record. A field outside this map is
# NOT_TRACKED - never "none found" and never zero. The value says which
# columns hold it; the first non-blank wins.
TRACKED_FIELDS: dict[str, tuple[str, ...]] = {
    "case_no": ("case_no",), "parcel": ("parcel",), "address": ("address",), "county": ("county",),
    "sale_date": ("sale_date",), "amount": ("purchase_amount", "min_bid", "bid"),
    "status": ("status",), "source_url": ("url_auction", "purchase_url", "source_url"),
    "assessed": ("assessed",), "market": ("market",), "land_use": ("land_use",), "acreage": ("acreage",),
    "latitude": ("latitude",), "longitude": ("longitude",), "flood_zone": ("flood_zone",),
    "legal_desc": ("legal_desc",), "certificate_no": ("certificate_no",),
}
# Facts the product never infers (they appear only as a source-published
# result through the outcome / inventory-status writers): a sold, redeemed or
# winning state, a price paid, ownership, title, parcel-boundary accuracy or
# a return. They are NOT_TRACKED on the record itself.
NEVER_INFERRED = ("sold", "redeemed", "winner", "winning_bid", "price_paid", "owner", "title", "boundary",
                  "boundary_accuracy", "return", "roi")
# Fields whose value is the row's own source list column (no enrichment).
LIST_FIELDS = frozenset({"case_no", "parcel", "address", "county", "sale_date", "amount", "status", "source_url",
                         "legal_desc", "certificate_no"})
# Provenance sources that compute a value rather than read it.
DERIVED_PROVENANCE = frozenset({"census_geocoder"})
DERIVED_PROVENANCE_DATASETS = frozenset({"parcel_centroid"})
ESTIMATE_AMOUNT_KINDS = frozenset({"ESTIMATED_PURCHASE_PRICE", "ESTIMATE"})
# A legacy amount sentinel: `bid` = 0 with no amount kind means "not published".
LEDGER_OF_SOURCE = {"auction": "AUCTIONS", "laft": "AVAILABLE", "certificate": "LIENS_CERTIFICATES"}
CLOSED_STATUSES = frozenset({"closed", "gone", "expired", "delisted", "withdrawn"})


def _blank(v) -> bool:
    return v is None or (isinstance(v, str) and not v.strip())


def _parse_ts(v) -> datetime | None:
    if _blank(v):
        return None
    try:
        s = str(v).replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _source_id_of(row: dict) -> str:
    return str(row.get("source_id") or row.get("harvester_source") or "")


def _provenance(row: dict) -> dict:
    fp = row.get("field_provenance")
    if isinstance(fp, str):
        try:
            fp = json.loads(fp)
        except ValueError:
            fp = None
    return fp if isinstance(fp, dict) else {}


def field_value(row: dict, fld: str):
    for col in TRACKED_FIELDS.get(fld, ()):
        v = row.get(col)
        if not _blank(v):
            return col, v
    return None, None


def value_status(row: dict, fld: str) -> str:
    """One status from VALUE_STATUSES for one field of one record."""
    if fld not in TRACKED_FIELDS or fld in NEVER_INFERRED:
        return "NOT_TRACKED"
    col, v = field_value(row, fld)
    if fld == "amount":
        kind = str(row.get("purchase_amount_kind") or "")
        if col == "bid" and _num(v) == 0 and not kind:
            return "NOT_PUBLISHED"          # the legacy 0 sentinel is never a figure
        if col is None:
            return "NOT_PUBLISHED"
        if kind in ESTIMATE_AMOUNT_KINDS or str(row.get("bid_kind") or "") in ESTIMATE_AMOUNT_KINDS:
            return "ESTIMATED_BY_SOURCE"
    if col is None:
        return "NOT_PUBLISHED"
    entry = _provenance(row).get(col) or _provenance(row).get(fld)
    if isinstance(entry, dict):
        if entry.get("source") in DERIVED_PROVENANCE or entry.get("dataset") in DERIVED_PROVENANCE_DATASETS:
            return "DERIVED_BY_TAXACQ"
        return "CONFIRMED_SOURCE" if _parse_ts(row.get("last_seen_at")) or entry.get("recorded_at") else "UNVERIFIED"
    if fld in LIST_FIELDS and _source_id_of(row) and _parse_ts(row.get("last_seen_at")):
        return "CONFIRMED_SOURCE"
    return "UNVERIFIED"


def _num(v):
    try:
        return float(str(v).replace(",", "").replace("$", ""))
    except (TypeError, ValueError):
        return None


def freshness(row: dict, now: datetime) -> str:
    status = str(row.get("status") or "").lower()
    if status in CLOSED_STATUSES or not _blank(row.get("delisted_at")):
        return "WITHDRAWN"
    seen = _parse_ts(row.get("last_seen_at"))
    if seen is None:
        return "UNVERIFIED"
    ledger = LEDGER_OF_SOURCE.get(str(row.get("source") or ""), "AVAILABLE")
    try:
        from .publication_state import FRESHNESS_DAYS  # noqa: PLC0415
        days = FRESHNESS_DAYS[ledger]
    except Exception:  # noqa: BLE001
        days = 7
    return "STALE" if now - seen > timedelta(days=days) else "CURRENT"


# The provenance categories some writers record without a source_id, and the
# permission source each one names (county_gis is per county).
PROVENANCE_SOURCE_IDS = {"fdor_nal": "fl_fdor_cadastral", "census_geocoder": "census_geocoder"}
COUNTY_GIS_SOURCE_IDS = {("FL", "Santa Rosa"): "fl_santa_rosa_parcels", ("FL", "Flagler"): "fl_palm_coast_flagler_parcels"}
COORDINATE_FIELDS = frozenset({"latitude", "longitude"})


def enrichment_source_id(row: dict, entry: dict) -> str | None:
    """The permission source behind an enrichment provenance entry, or None
    for a list value / an entry that names no source."""
    if entry.get("source_id") and entry.get("source") not in ("county_list", "vendor_listing", "hand_research"):
        return str(entry["source_id"])
    src = entry.get("source")
    if src == "county_gis":
        return COUNTY_GIS_SOURCE_IDS.get((str(row.get("state") or ""), str(row.get("county") or "")))
    return PROVENANCE_SOURCE_IDS.get(src)


def enrichment_decision(row: dict, fld: str, entry: dict, *, perms: P.Permissions,
                        today: date | None) -> P.PermissionDecision | None:
    """The `enrich` decision of the source that attached this value, or None
    for a value the record's own source published."""
    sid = enrichment_source_id(row, entry)
    if sid is None:
        return None
    dataset = None
    if sid == "fl_fdor_cadastral":
        dataset = "parcel_centroid" if fld in COORDINATE_FIELDS else "parcel_attributes"
    return perms.authorize(sid, "enrich", state=str(row.get("state") or ""), county=row.get("county") or None,
                           dataset=dataset, today=today)


def enrichment_permitted(row: dict, fld: str, entry: dict, *, perms: P.Permissions, today: date | None) -> bool:
    """A value attached by another source is shown only while that source's
    `enrich` permission holds for this record's state and county (a provider
    approval for one county or dataset never covers another)."""
    d = enrichment_decision(row, fld, entry, perms=perms, today=today)
    return d is None or d.allowed


def field_provenance_view(row: dict, fld: str, *, now: datetime, perms: P.Permissions | None = None,
                          today: date | None = None) -> dict:
    """The customer-visible provenance of one field: source, origin, the
    row's own timestamps and a status. Timestamps the row does not carry
    are None, never filled from the clock; a field whose source may not be
    displayed is WITHDRAWN with no value."""
    vs = value_status(row, fld)
    col, v = field_value(row, fld)
    entry = _provenance(row).get(col or fld)
    entry = entry if isinstance(entry, dict) else {}
    sid = _source_id_of(row)
    state = str(row.get("state") or "")
    notice = customer_source_notice(sid, state=state, county=row.get("county") or None,
                                    perms=perms, today=today) if sid and state else None
    fresh = "NOT_TRACKED" if vs == "NOT_TRACKED" else freshness(row, now)
    shown = bool(notice and notice["shown"])
    attribution = (notice or {}).get("attribution") or ""
    enr = enrichment_decision(row, fld, entry, perms=perms or P.default(), today=today) if entry else None
    if enr is not None:
        if not enr.allowed:
            shown = False
        else:
            rec = _record_for(perms or P.default(), enr)
            attribution = rec.attribution if rec else ""      # the attaching source's attribution, not the list's
    if not shown and vs != "NOT_TRACKED":
        fresh = "WITHDRAWN"
    origin = None
    if vs == "DERIVED_BY_TAXACQ":
        origin = "DERIVED_BY_TAXACQ"
    elif vs in ("CONFIRMED_SOURCE", "ESTIMATED_BY_SOURCE", "UNVERIFIED") and col is not None:
        origin = "SOURCE_REPORTED"
    return {
        "field": fld,
        "value": (v if shown and vs not in ("NOT_PUBLISHED", "NOT_TRACKED") else None),
        "value_status": vs,
        "value_status_label": VALUE_STATUS_LABELS[vs],
        "source_id": sid or None,
        "provenance_source": entry.get("source"),
        "source_url": row.get("url_auction") or row.get("source_url") or None,
        "origin": origin,
        "retrieved_at": entry.get("recorded_at") or None,
        "effective_at": row.get("list_as_of") or row.get("source_published_at") or None,
        "last_verified_at": row.get("last_seen_at") or None,
        "freshness": fresh,
        "attribution": attribution if shown else "",
        "conditions": (notice or {}).get("conditions") or [],
    }


# --- public disclosure ------------------------------------------------------

FORBIDDEN_PUBLIC_PATTERNS = (
    (re.compile(r'"(reviewer|evidence_ref|contact_decision_maker|outreach_status|remaining_questions|legal_status)"\s*:'),
     "internal permission / register key"),
    (re.compile(r"INTERNAL_RISK_ACCEPTANCE|GRANDFATHERED_PRACTICE|PROHIBITION_FOUND|TECHNICAL_SIGNAL_ONLY"),
     "internal permission evidence type"),
    (re.compile(r"source_permissions\.csv|source_register_2026|counsel[- ]packet|privileged", re.I),
     "reference to internal legal records"),
    (re.compile(r"\bsb_secret_[A-Za-z0-9_]+|service_role\s*[:=]\s*\"ey|SCRAPERAPI_KEY\s*[:=]"),
     "credential"),
)


def public_disclosure_problems(text: str) -> list[str]:
    return [f"{label}: {m.group(0)[:60]}" for rx, label in FORBIDDEN_PUBLIC_PATTERNS for m in [rx.search(text)] if m]


# --- 2. register reconciliation ---------------------------------------------

# The most a register decision allows. An operation the code allows beyond
# this is a discrepancy. `fetch_via_proxy` and `redistribute` are never in a
# ceiling: neither is allowed by any register decision.
CEILINGS: dict[str, frozenset[str]] = {
    "ENABLED": frozenset({"discover", "fetch", "parse", "store", "enrich", "display", "link"}),
    "MANUAL_ONLY": frozenset({"discover", "fetch", "parse", "store", "enrich", "display", "link"}),
    "ADMIN_ONLY": frozenset({"discover", "fetch", "parse", "store", "enrich", "link"}),
    "LINKS_ONLY": frozenset({"discover", "link"}),
    "DISABLED": frozenset({"discover", "link"}),
    "GATED": frozenset({"discover", "link"}),
    "NOT_NEEDED": frozenset({"discover", "link"}),
    "DO_NOT_ADD": frozenset({"link"}),
    "BLOCKED": frozenset(),
    "DECISION_REQUIRED": frozenset(),
    "CLIENT_SIDE": frozenset(),
}
MATCH_TYPES = ("EXACT", "RENAMED", "SPLIT_OF", "AGGREGATE_OF", "OPERATION_OF", "NO_CODE_SOURCE",
               "NO_PERMISSION_RECORD", "CLIENT_SIDE")
CHECK_OPERATIONS = tuple(op for op in P.OPERATIONS if op != "discover")  # discovery has its own guard


@dataclass
class Finding:
    register_id: str
    kind: str          # EXCEEDS_CEILING | NO_CODE_SOURCE | NO_PERMISSION_RECORD | ACTIVE_WITHOUT_RECORD | UNREGISTERED_CODE_SOURCE
    source_id: str = ""
    places: list[str] = field(default_factory=list)
    operations: list[str] = field(default_factory=list)
    detail: str = ""

    def as_dict(self) -> dict:
        return {"register_id": self.register_id, "kind": self.kind, "source_id": self.source_id,
                "places": self.places, "operations": self.operations, "detail": self.detail}


def _read(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _registry_places(rows: list[dict]) -> dict[str, list[tuple[str, str]]]:
    out: dict[str, list[tuple[str, str]]] = {}
    for r in rows:
        out.setdefault(r["source_id"], []).append((r["state"], r["county"]))
    return out


def scope_places(scope: str, source_ids: list[str], registry: dict[str, list[tuple[str, str]]],
                 perms: P.Permissions) -> list[tuple[str, str | None]]:
    """The (state, county) points a map row's scope covers."""
    kind, _, arg = scope.partition(":")
    listed = [c.strip() for c in arg.split(";") if c.strip()]
    places: set[tuple[str, str | None]] = set()
    for sid in source_ids:
        reg = registry.get(sid, [])
        if kind == "registry":
            places |= {(s, c) for s, c in reg}
        elif kind == "registry_except":
            places |= {(s, c) for s, c in reg if c not in listed}
        elif kind == "counties":
            st = reg[0][0] if reg else next((r.state for r in perms.records if r.source_id == sid), "")
            places |= {(st, c) for c in listed}
        elif kind == "state":
            places.add((arg, None))
        if kind in ("registry", "registry_except") and not reg:
            places |= {(r.state, r.county) for r in perms.records if r.source_id == sid and r.state != "US"}
    return sorted(places, key=lambda p: (p[0], p[1] or ""))


def allowed_operations(perms: P.Permissions, source_id: str, state: str, county: str | None,
                       datasets: list[str], today: date, operations: tuple[str, ...] = CHECK_OPERATIONS) -> dict[str, str]:
    """operation -> basis for every operation allowed at one place (any dataset)."""
    out: dict[str, str] = {}
    for ds in datasets:
        for op in operations:
            d = perms.authorize(source_id, op, state=state, county=county,
                                dataset=None if ds == "*" else ds, today=today)
            if d.allowed and op not in out:
                out[op] = d.basis
    return out


def reconcile(*, today: date | None = None, perms: P.Permissions | None = None,
              register: list[dict] | None = None, code_map: list[dict] | None = None,
              registry_rows: list[dict] | None = None) -> dict:
    perms = perms or P.default()
    today = today or date.today()
    register = register if register is not None else _read(REGISTER_CSV)
    code_map = code_map if code_map is not None else _read(CODE_MAP_CSV)
    registry = _registry_places(registry_rows if registry_rows is not None else _read(REGISTRY_CSV))
    by_id = {r["register_id"]: r for r in code_map}
    perm_ids = perms.source_ids()
    rows, findings = [], []
    for reg in register:
        rid = reg["source_id"]
        m = by_id.get(rid)
        if m is None:
            findings.append(Finding(rid, "NOT_MAPPED", detail="register row has no code-map row"))
            continue
        sids = [s for s in m["code_source_ids"].split(";") if s]
        datasets = [d for d in (m["dataset"] or "*").split(";") if d]
        ceiling = CEILINGS[m["decision_class"]]
        ops = tuple(o for o in (m.get("operations") or "").split(";") if o) or CHECK_OPERATIONS
        active = reg["implementation_status"].upper().startswith("ACTIVE")
        entry = {"register_id": rid, "provider": reg["provider_owner"], "coverage": reg["coverage"],
                 "data_types": reg["data_categories"], "implementation_status": reg["implementation_status"],
                 "legal_status": reg["legal_status"], "decision": reg["enablement_decision"],
                 "decision_class": m["decision_class"], "match_type": m["match_type"], "code_source_ids": sids,
                 "scope": m["scope"], "places": [], "allowed": {}, "findings": []}
        if not sids:
            kind = "CLIENT_SIDE_NO_RECORD" if m["match_type"] == "CLIENT_SIDE" else (
                "NO_PERMISSION_RECORD" if m["match_type"] == "NO_PERMISSION_RECORD" else "NO_CODE_SOURCE")
            if active or m["match_type"] in ("CLIENT_SIDE", "NO_PERMISSION_RECORD"):
                f = Finding(rid, kind, detail=m["note"])
                findings.append(f)
                entry["findings"].append(f.as_dict())
            rows.append(entry)
            continue
        for sid in sids:
            if sid not in perm_ids and sid not in P.HARD_BLOCKED_SOURCE_IDS:
                f = Finding(rid, "NO_PERMISSION_RECORD", sid, detail="code source has no permission record")
                findings.append(f)
                entry["findings"].append(f.as_dict())
        over: dict[tuple[str, tuple[str, ...]], list[str]] = {}
        for sid in sids:
            for st, county in scope_places(m["scope"], [sid], registry, perms):
                allowed = allowed_operations(perms, sid, st, county, datasets, today, ops)
                place = f"{st}:{county}" if county else st
                entry["places"].append(place)
                for op, basis in allowed.items():
                    entry["allowed"].setdefault(f"{sid}:{op}", set()).add(basis)
                extra = tuple(sorted(op for op in allowed if op not in ceiling))
                if extra:
                    over.setdefault((sid, extra), []).append(place)
        for (sid, extra), places in sorted(over.items()):
            f = Finding(rid, "EXCEEDS_CEILING", sid, sorted(places), list(extra),
                        f"register decision {m['decision_class']} allows at most {sorted(ceiling) or 'nothing'}")
            findings.append(f)
            entry["findings"].append(f.as_dict())
        entry["allowed"] = {k: sorted(v) for k, v in sorted(entry["allowed"].items())}
        entry["places"] = sorted(set(entry["places"]))
        rows.append(entry)
    mapped = {s for r in code_map for s in r["code_source_ids"].split(";") if s}
    for sid in sorted(perm_ids - mapped):
        findings.append(Finding("", "UNREGISTERED_CODE_SOURCE", sid, detail="permission records exist but no register row maps to it"))
    return {"generated_for": today.isoformat(), "rows": rows, "findings": [f.as_dict() for f in findings]}
