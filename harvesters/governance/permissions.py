"""Per-operation source permission: one fail-closed decision every
collection, storage, enrichment and display entry point asks before acting.

Why this exists (source-register audit, 2026-10-12). Before this module the
project answered one question per source - "is its publication / legal
status in the allowed set?" - and several real entry points asked nothing at
all (the Florida PowerShell harvesters and syncs, the nine Florida LAFT
harvesters, the enrichment scripts). A source being reachable, publicly
posted, previously harvested or marked APPROVED in a config is not a grant.
This module makes the grant explicit, per operation, dated and expiring.

The record: data/source_permissions.csv, one row per
(source_id, dataset, jurisdiction, operation). Columns are documented in
docs/source-permissions.md and validated by `validate()` below.

The decision, `authorize()`, never raises and returns a `PermissionDecision`
(machine-readable: `as_dict()`). It ALLOWS only when exactly one applicable
record:
  * is in effect today (effective_on <= today <= expires_on), and
  * is APPROVED / APPROVED_WITH_CONDITIONS on DOCUMENTED evidence
    (a published licence or written permission) -> basis DOCUMENTED, or
  * is LEGAL_REVIEW_REQUIRED / OWNER_PERMISSION_REQUIRED / UNKNOWN carrying an
    explicit, dated, expiring INTERIM allowance (internal risk acceptance or
    grandfathered production practice, with who recorded it) -> basis INTERIM,
  * and every condition it names is satisfied (conditions are evaluated HERE,
    by named checkers over repository records, never asserted by a caller);
  * LINK_ONLY allows the `link` operation and nothing else.
Everything else DENIES with a reason code: missing record, unknown source,
wrong jurisdiction / dataset / operation, expired, not yet effective,
conflicting records, BLOCKED, RESTRICTED, unmet or unknown condition, or an
invalid / unreadable configuration (which denies EVERY operation).

An INTERIM allowance is never reported, stored or treated as permission:
`basis` stays INTERIM and `documented` is False. Validation refuses an
APPROVED row on internal-acceptance evidence, so an internal decision cannot
be upgraded to documented permission by editing a status word.

Hard blocks: the vendors in county_source_registry.BLOCKED_SOURCE_IDS
(tx_pbfcm, tx_mvba, tx_govease, tx_ctsa) are denied in code whatever the
file says, and a file that records anything but BLOCKED for one of them is
INVALID (so every operation is denied until the file is corrected). Lifting
one of these blocks therefore needs a reviewed code change, a record change
and a test change together - never a data edit alone.

Out of scope here: parcel POLYGON storage / display, which has its own
permission matrix (harvesters/boundary/permissions.py, PR #144). Nothing in
this module grants a geometry operation.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Callable, Iterable

REPO = Path(__file__).resolve().parents[2]
PERMISSIONS_CSV = REPO / "data" / "source_permissions.csv"

# The operations a record can name. Each maps to the AuthorizationScope
# dimension(s) of harvesters/governance/authorization.py that a written
# provider authorization would have to grant (docs/source-permissions.md).
OPERATIONS = (
    "discover",         # read a page only to learn what exists (value-free capture)
    "fetch",            # automated retrieval of the source's records
    "fetch_via_proxy",  # retrieval routed through a third-party proxy after a block
    "parse",            # normalize the retrieved records
    "store",            # write records to the product database
    "enrich",           # attach values from this source to records of another
    "display",          # show this source's records / values to customers
    "redistribute",     # export, API, resale or any re-publication outside the app
    "link",             # link to the source's own published page, copying nothing
)
OPERATION_SCOPE_DIMENSIONS = {
    "discover": ("automated_access",),
    "fetch": ("automated_access",),
    "fetch_via_proxy": ("automated_access",),
    "parse": ("normalization",),
    "store": ("storage",),
    "enrich": ("derived_data",),
    "display": ("customer_display",),
    "redistribute": ("customer_export", "api_redistribution"),
    "link": (),
}

STATUSES = (
    "APPROVED", "APPROVED_WITH_CONDITIONS", "LINK_ONLY", "LEGAL_REVIEW_REQUIRED",
    "OWNER_PERMISSION_REQUIRED", "RESTRICTED", "BLOCKED", "UNKNOWN",
)
DOCUMENTED_STATUSES = frozenset({"APPROVED", "APPROVED_WITH_CONDITIONS"})
OPEN_STATUSES = frozenset({"LEGAL_REVIEW_REQUIRED", "OWNER_PERMISSION_REQUIRED", "UNKNOWN"})

EVIDENCE_TYPES = (
    "PUBLISHED_LICENSE",         # the publisher's own licence / terms grant the use
    "WRITTEN_PERMISSION",        # a written grant from the data owner (must match authorization.py)
    "INTERNAL_RISK_ACCEPTANCE",  # the product owner accepted the risk; NOT a grant
    "GRANDFATHERED_PRACTICE",    # in production before review; NOT a grant
    "PROHIBITION_FOUND",         # the source's own terms prohibit the use
    "TECHNICAL_SIGNAL_ONLY",     # e.g. robots.txt; neither a grant nor a legal finding
    "TERMS_SILENT",              # terms read; neither grant nor prohibition
    "NO_EVIDENCE",               # nothing read
)
DOCUMENTED_EVIDENCE = frozenset({"PUBLISHED_LICENSE", "WRITTEN_PERMISSION"})
INTERIM_EVIDENCE = frozenset({"INTERNAL_RISK_ACCEPTANCE", "GRANDFATHERED_PRACTICE"})
# An interim allowance (grandfathered practice or an internal risk
# acceptance) is a stopgap, never a grant: it may run at most this many days
# from its effective date. Every interim record on file runs to 2027-04-12,
# 210 days after the earliest effective date (2026-09-14). A longer one is a
# configuration error, which denies every source - it can never silently
# extend an allowance. Renewing one needs a new, dated record.
INTERIM_MAX_DAYS = 210
# Operations that route around a control the source itself applied (an HTTP
# 403, an IP block, a disclaimer or login wall). An interim allowance - a
# grandfathered practice or an internal risk acceptance - can never allow
# one: only a published licence or a written grant from the data owner that
# covers automated access can (2026-10-16, source-rights enforcement).
CIRCUMVENTION_OPERATIONS = frozenset({"fetch_via_proxy"})

COLUMNS = (
    "source_id", "provider", "dataset", "publisher", "jurisdiction", "operation", "status",
    "evidence_type", "evidence_ref", "evidence_date", "reviewer", "effective_on", "expires_on",
    "conditions", "attribution", "last_verified_on", "reason",
)

# Lifting one of these needs a code change (here AND in county_source_registry)
# plus a record change plus a test change. A data edit alone invalidates the file.
try:
    from .county_source_registry import BLOCKED_SOURCE_IDS as _BLOCKED
except Exception:  # noqa: BLE001 - a broken import must not open the gate
    _BLOCKED = frozenset({"tx_pbfcm", "tx_mvba", "tx_govease", "tx_ctsa"})
HARD_BLOCKED_SOURCE_IDS = frozenset(_BLOCKED) | {"tx_pbfcm", "tx_mvba", "tx_govease", "tx_ctsa"}


class PermissionConfigError(ValueError):
    """The permission file is missing, unreadable or invalid."""


@dataclass(frozen=True)
class PermissionRecord:
    source_id: str
    provider: str
    dataset: str
    publisher: str
    jurisdiction: str
    operation: str
    status: str
    evidence_type: str
    evidence_ref: str
    evidence_date: str
    reviewer: str
    effective_on: str
    expires_on: str
    conditions: tuple[str, ...]
    attribution: str
    last_verified_on: str
    reason: str
    line: int = 0

    @property
    def state(self) -> str:
        return self.jurisdiction.split(":", 1)[0]

    @property
    def county(self) -> str | None:
        return self.jurisdiction.split(":", 1)[1] if ":" in self.jurisdiction else None

    @property
    def may_allow(self) -> bool:
        """Could this record ever allow? (Used by validation.)"""
        return (self.status in DOCUMENTED_STATUSES or self.status == "LINK_ONLY"
                or (self.status in OPEN_STATUSES and self.evidence_type in INTERIM_EVIDENCE))


@dataclass(frozen=True)
class PermissionDecision:
    source_id: str
    operation: str
    state: str
    county: str | None
    dataset: str | None
    allowed: bool
    basis: str            # DOCUMENTED | INTERIM | LINK_ONLY | DENIED
    reason_code: str
    reason: str
    status: str = ""
    evidence_type: str = ""
    evidence_ref: str = ""
    expires_on: str = ""
    record_line: int = 0
    conditions: tuple[str, ...] = ()

    @property
    def documented(self) -> bool:
        """True only for a published licence or written permission - never
        for an internal risk acceptance or grandfathered practice."""
        return self.allowed and self.basis == "DOCUMENTED"

    def as_dict(self) -> dict:
        return {k: (list(v) if isinstance(v, tuple) else v) for k, v in self.__dict__.items()} | {"documented": self.documented}


# --- loading and validation --------------------------------------------------

def _d(value: str, what: str, line: int, problems: list[str]) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        problems.append(f"line {line}: {what} {value!r} is not an ISO date")
        return None


def parse(text_rows: Iterable[dict]) -> list[PermissionRecord]:
    out = []
    for i, r in enumerate(text_rows, start=2):
        missing = [c for c in COLUMNS if c not in r]
        if missing:
            raise PermissionConfigError(f"line {i}: missing column(s) {missing}")
        out.append(PermissionRecord(
            **{c: (r[c] or "").strip() for c in COLUMNS if c != "conditions"},
            conditions=tuple(c.strip() for c in (r["conditions"] or "").split("|") if c.strip()),
            line=i))
    return out


def validate(records: list[PermissionRecord]) -> list[str]:
    """Every problem with the record set; an empty list means valid."""
    problems: list[str] = []
    if not records:
        problems.append("no permission records")
    for r in records:
        L = r.line
        if not r.source_id or not r.jurisdiction or not r.operation:
            problems.append(f"line {L}: source_id, jurisdiction and operation are required")
        if r.operation not in OPERATIONS:
            problems.append(f"line {L}: unknown operation {r.operation!r}")
        if r.status not in STATUSES:
            problems.append(f"line {L}: unknown status {r.status!r}")
        if r.evidence_type not in EVIDENCE_TYPES:
            problems.append(f"line {L}: unknown evidence_type {r.evidence_type!r}")
        if not r.dataset:
            problems.append(f"line {L}: dataset is required ('*' for every dataset of the source)")
        if not r.reason:
            problems.append(f"line {L}: reason is required")
        st = r.state
        if not (st == "US" or (len(st) == 2 and st.isupper())):
            problems.append(f"line {L}: jurisdiction {r.jurisdiction!r} must be US, XX or XX:County")
        eff = _d(r.effective_on, "effective_on", L, problems)
        exp = _d(r.expires_on, "expires_on", L, problems)
        ev = _d(r.evidence_date, "evidence_date", L, problems)
        _d(r.last_verified_on, "last_verified_on", L, problems)
        if eff and exp and exp <= eff:
            problems.append(f"line {L}: expires_on must be after effective_on")
        # A record that could allow must be fully dated, sourced and attributed.
        if r.may_allow:
            for col in ("evidence_ref", "evidence_date", "reviewer", "effective_on", "expires_on"):
                if not getattr(r, col):
                    problems.append(f"line {L}: {r.status} on {r.evidence_type} needs {col}")
            if ev and eff and ev > eff:
                problems.append(f"line {L}: evidence_date is after effective_on")
        # Documented status needs documented evidence: internal acceptance or
        # grandfathering can never be recorded as APPROVED.
        if r.status in DOCUMENTED_STATUSES and r.evidence_type not in DOCUMENTED_EVIDENCE:
            problems.append(f"line {L}: {r.status} requires PUBLISHED_LICENSE or WRITTEN_PERMISSION evidence, "
                            f"not {r.evidence_type} (internal acceptance is never documented permission)")
        if (r.status in OPEN_STATUSES and r.evidence_type in INTERIM_EVIDENCE and eff and exp
                and (exp - eff).days > INTERIM_MAX_DAYS):
            problems.append(f"line {L}: interim allowance ({r.evidence_type}) runs {(exp - eff).days} days; "
                            f"the limit is {INTERIM_MAX_DAYS} - record a dated renewal instead")
        if r.status in OPEN_STATUSES and r.evidence_type in DOCUMENTED_EVIDENCE:
            problems.append(f"line {L}: documented evidence on an open status {r.status} - record the decision instead")
        if r.status == "LINK_ONLY" and r.operation != "link":
            problems.append(f"line {L}: LINK_ONLY applies to the link operation only")
        if r.status == "APPROVED_WITH_CONDITIONS" and not r.conditions:
            problems.append(f"line {L}: APPROVED_WITH_CONDITIONS needs at least one condition")
        for c in r.conditions:
            if c not in CONDITION_CHECKERS:
                problems.append(f"line {L}: unknown condition {c!r}")
        if r.source_id in HARD_BLOCKED_SOURCE_IDS and r.status != "BLOCKED":
            problems.append(f"line {L}: {r.source_id} is hard-blocked in code; only BLOCKED may be recorded")
        if r.evidence_type == "WRITTEN_PERMISSION":
            problems.extend(_written_permission_problems(r))
    return problems


def _written_permission_problems(r: PermissionRecord) -> list[str]:
    """A WRITTEN_PERMISSION row must agree with authorization.py: the
    provider authorization for the source must be granted and cover the
    operation's scope dimension(s)."""
    try:
        from . import authorization as A  # noqa: PLC0415
    except Exception as exc:  # noqa: BLE001
        return [f"line {r.line}: cannot check WRITTEN_PERMISSION against authorization.py ({type(exc).__name__})"]
    recs = [a for a in dict(getattr(A, "PROVIDER_AUTHORIZATIONS", {})).values() if a.source_id == r.source_id]
    if not recs:
        return [f"line {r.line}: WRITTEN_PERMISSION recorded but authorization.py holds no record for {r.source_id}"]
    for a in recs:
        if a.authorization_status not in A.AUTHORIZATION_GRANTED_STATUSES:
            continue
        if all(getattr(a.scope, dim).authorized for dim in OPERATION_SCOPE_DIMENSIONS[r.operation]):
            return []
    return [f"line {r.line}: WRITTEN_PERMISSION for {r.source_id}/{r.operation} contradicts authorization.py "
            f"(no granted authorization covers it)"]


def load(path: Path | None = None) -> list[PermissionRecord]:
    """Read and validate; raise PermissionConfigError on any problem."""
    p = Path(path) if path else PERMISSIONS_CSV
    try:
        with p.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            header = tuple(reader.fieldnames or ())
            if header != COLUMNS:
                raise PermissionConfigError(f"{p.name}: header {header} != {COLUMNS}")
            records = parse(reader)
    except PermissionConfigError:
        raise
    except Exception as exc:  # noqa: BLE001 - unreadable is invalid
        raise PermissionConfigError(f"cannot read {p}: {type(exc).__name__}: {exc}") from exc
    problems = validate(records)
    if problems:
        raise PermissionConfigError("; ".join(problems[:20]) + (f" (+{len(problems) - 20} more)" if len(problems) > 20 else ""))
    return records


# --- conditions: evaluated here, over repository records, never asserted ------

def _paid_beta_sources() -> set[str]:
    path = REPO / "data" / "paid_beta_sources.csv"
    with path.open(newline="", encoding="utf-8") as f:
        return {r["source_id"] for r in csv.DictReader(f) if (r.get("paid_beta") or "").strip().lower() == "yes"}


def _registry_restrictions(source_id: str) -> list[str]:
    path = REPO / "data" / "county_source_registry.csv"
    with path.open(newline="", encoding="utf-8") as f:
        return [r.get("restrictions") or "" for r in csv.DictReader(f) if r.get("source_id") == source_id]


def _cond_excluded_from_paid_tier(rec: PermissionRecord) -> bool:
    return rec.source_id not in _paid_beta_sources()


def _cond_dated_list_only(rec: PermissionRecord) -> bool:
    texts = _registry_restrictions(rec.source_id)
    return bool(texts) and all("dated list" in t.lower() for t in texts)


def _cond_attribution_text_recorded(rec: PermissionRecord) -> bool:
    return bool(rec.attribution.strip())


CONDITION_CHECKERS: dict[str, Callable[[PermissionRecord], bool]] = {
    # The source is not in the paid tier (data/paid_beta_sources.csv).
    "excluded_from_paid_tier": _cond_excluded_from_paid_tier,
    # The registry records the owner's dated-list-only decision for the source.
    "dated_list_only": _cond_dated_list_only,
    # The attribution text the licence requires is recorded on the permission.
    "attribution_text_recorded": _cond_attribution_text_recorded,
}


# --- the decision -------------------------------------------------------------

def _deny(source_id, operation, state, county, dataset, code, reason, rec: PermissionRecord | None = None) -> PermissionDecision:
    return PermissionDecision(
        source_id=source_id or "", operation=operation or "", state=state or "", county=county, dataset=dataset,
        allowed=False, basis="DENIED", reason_code=code, reason=reason,
        status=rec.status if rec else "", evidence_type=rec.evidence_type if rec else "",
        evidence_ref=rec.evidence_ref if rec else "", expires_on=rec.expires_on if rec else "",
        record_line=rec.line if rec else 0, conditions=rec.conditions if rec else ())


def _applicable(records, source_id, operation, state, county, dataset) -> list[PermissionRecord]:
    """The most specific matching records: county rows of that county beat
    state rows, which beat US rows. Dataset '*' matches any dataset; a named
    dataset matches only itself (a caller that names none matches only '*')."""
    def ds_ok(r):
        return r.dataset == "*" or (dataset is not None and r.dataset == dataset)
    cands = [r for r in records if r.source_id == source_id and r.operation == operation and ds_ok(r)]
    for tier in (
        [r for r in cands if county and r.state == state and r.county == county],
        [r for r in cands if r.state == state and r.county is None],
        [r for r in cands if r.state == "US"],
    ):
        if tier:
            return tier
    return []


class Permissions:
    """A loaded, validated permission set. `authorize()` never raises."""

    def __init__(self, records: list[PermissionRecord] | None = None, *, error: str | None = None,
                 checkers: dict[str, Callable[[PermissionRecord], bool]] | None = None):
        self.records = records or []
        self.error = error
        self.checkers = dict(CONDITION_CHECKERS if checkers is None else checkers)

    @classmethod
    def from_file(cls, path: Path | None = None, **kw) -> "Permissions":
        try:
            return cls(load(path), **kw)
        except PermissionConfigError as exc:
            return cls([], error=str(exc), **kw)

    def source_ids(self) -> set[str]:
        return {r.source_id for r in self.records}

    def authorize(self, source_id: str | None, operation: str, *, state: str | None, county: str | None = None,
                  dataset: str | None = None, today: date | None = None) -> PermissionDecision:
        args = (source_id, operation, state, county, dataset)
        try:
            return self._authorize(*args, today=today or date.today())
        except Exception as exc:  # noqa: BLE001 - an unexpected error is a denial
            return _deny(*args, "EVALUATION_ERROR", f"{type(exc).__name__}: {exc}")

    def _authorize(self, source_id, operation, state, county, dataset, *, today: date) -> PermissionDecision:
        args = (source_id, operation, state, county, dataset)
        if self.error is not None:
            return _deny(*args, "CONFIG_INVALID", f"permission configuration unavailable or invalid: {self.error}")
        if not source_id:
            return _deny(*args, "NO_SOURCE", "no source_id given")
        if operation not in OPERATIONS:
            return _deny(*args, "UNKNOWN_OPERATION", f"{operation!r} is not a defined operation")
        if not state:
            return _deny(*args, "NO_JURISDICTION", "no state given")
        if source_id in HARD_BLOCKED_SOURCE_IDS:
            return _deny(*args, "HARD_BLOCKED", f"{source_id} is a hard-blocked vendor (county_source_registry.BLOCKED_SOURCE_IDS)")
        if source_id not in self.source_ids():
            return _deny(*args, "UNKNOWN_SOURCE", f"{source_id} has no permission record - missing is never permission")
        recs = _applicable(self.records, *args)
        if not recs:
            return _deny(*args, "NO_RECORD", f"no {operation} record for {source_id} in {state}{':' + county if county else ''}"
                                             f"{' dataset ' + dataset if dataset else ''}")
        if len(recs) > 1:
            return _deny(*args, "CONFLICT", f"{len(recs)} records apply (lines {', '.join(str(r.line) for r in recs)}) - "
                                            f"conflicting or duplicate records never allow", recs[0])
        rec = recs[0]
        eff = date.fromisoformat(rec.effective_on) if rec.effective_on else None
        exp = date.fromisoformat(rec.expires_on) if rec.expires_on else None
        if rec.status == "BLOCKED":
            return _deny(*args, "BLOCKED", rec.reason, rec)
        if rec.status == "RESTRICTED":
            return _deny(*args, "RESTRICTED", rec.reason, rec)
        if rec.status == "LINK_ONLY" and operation != "link":
            return _deny(*args, "LINK_ONLY", "link-only source: no copy, store or display", rec)
        if not rec.may_allow:
            return _deny(*args, "NOT_PERMITTED", f"{rec.status} on {rec.evidence_type}: {rec.reason}", rec)
        if eff is None or today < eff:
            return _deny(*args, "NOT_YET_EFFECTIVE", f"effective {rec.effective_on or 'never'}; today {today}", rec)
        if exp is None or today > exp:
            return _deny(*args, "EXPIRED", f"expired {rec.expires_on or '(no expiry recorded)'}; review and re-record", rec)
        for cond in rec.conditions:
            check = self.checkers.get(cond)
            if check is None:
                return _deny(*args, "UNKNOWN_CONDITION", f"condition {cond!r} has no checker", rec)
            try:
                ok = bool(check(rec))
            except Exception as exc:  # noqa: BLE001
                return _deny(*args, "CONDITION_UNCHECKABLE", f"condition {cond!r}: {type(exc).__name__}", rec)
            if not ok:
                return _deny(*args, "CONDITION_UNMET", f"condition {cond!r} is not satisfied", rec)
        basis = "LINK_ONLY" if rec.status == "LINK_ONLY" else "DOCUMENTED" if rec.status in DOCUMENTED_STATUSES else "INTERIM"
        if operation in CIRCUMVENTION_OPERATIONS and basis != "DOCUMENTED":
            return _deny(*args, "CIRCUMVENTION_NEEDS_DOCUMENTED",
                         f"{operation} routes around a control the source applied; an interim allowance "
                         f"({rec.evidence_type}) never permits that - only documented permission can", rec)
        code = {"LINK_ONLY": "ALLOWED_LINK_ONLY", "DOCUMENTED": "ALLOWED_DOCUMENTED", "INTERIM": "ALLOWED_INTERIM"}[basis]
        why = rec.reason if basis != "INTERIM" else f"INTERIM ({rec.evidence_type}, not a grant): {rec.reason}"
        return PermissionDecision(
            source_id=source_id, operation=operation, state=state, county=county, dataset=dataset, allowed=True,
            basis=basis, reason_code=code, reason=why, status=rec.status, evidence_type=rec.evidence_type,
            evidence_ref=rec.evidence_ref, expires_on=rec.expires_on, record_line=rec.line, conditions=rec.conditions)

    def due_for_review(self, within_days: int, today: date | None = None) -> list[PermissionRecord]:
        today = today or date.today()
        out = []
        for r in self.records:
            if r.may_allow and r.expires_on:
                left = (date.fromisoformat(r.expires_on) - today).days
                if left <= within_days:
                    out.append(r)
        return out


_DEFAULT: Permissions | None = None


def default() -> Permissions:
    """The repository's permission set, loaded once per process."""
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = Permissions.from_file()
    return _DEFAULT


def reset_default() -> None:
    global _DEFAULT
    _DEFAULT = None


def authorize(source_id, operation, *, state, county=None, dataset=None, today=None) -> PermissionDecision:
    return default().authorize(source_id, operation, state=state, county=county, dataset=dataset, today=today)


def require(source_id, operation, *, state, county=None, dataset=None, label: str = "") -> PermissionDecision:
    """authorize() and raise PermissionDenied when not allowed - for entry
    points that must stop before any request or write."""
    d = authorize(source_id, operation, state=state, county=county, dataset=dataset)
    if not d.allowed:
        raise PermissionDenied(d, label)
    return d


class PermissionDenied(RuntimeError):
    def __init__(self, decision: PermissionDecision, label: str = ""):
        self.decision = decision
        super().__init__(f"{label + ': ' if label else ''}{decision.source_id} {decision.operation} "
                         f"denied [{decision.reason_code}] {decision.reason}")
