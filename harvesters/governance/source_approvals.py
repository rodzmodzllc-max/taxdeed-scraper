"""Source-approval register for parcel sources approved on written or published
terms (2026-10-20), plus the refresh and geometry rules those approvals need.

data/source_approvals.csv holds one row per approved source: the exact dataset
scope and what is excluded, the basis, the evidence and what is NOT on file,
the permitted activities, the conditions and attribution, the source's
EXPECTED refresh cadence and TAXACQ's ACTUAL last successful refresh. The two
are separate columns and never derived from each other.

This file does not grant anything by itself. Every operation is still decided
by permissions.authorize() against data/source_permissions.csv; the conditions
those records name (technical_readme_reviewed, attribution_terms_recorded) are
evaluated here, over this file, so a missing Readme review or a missing
disclaimer denies the operation (fail closed).

Also here, as pure functions with no I/O:

* apply_refresh(): a refresh outcome updates `last_successful_refresh` only for
  a COMPLETE read (or an EMPTY read with the source's own empty signal);
  FAILED / INCOMPLETE / SOURCE_UNAVAILABLE / STALE never do, and the expected
  cadence window never stands in for a refresh.
* match_geometries(): deterministic exact-identifier association of parcel
  features to property records. No match is reported as UNMATCHED and two or
  more features for one identifier (stacked polygons, condominium units) as
  AMBIGUOUS - neither is ever associated.
* simplify_ring(): Douglas-Peucker simplification that keeps a ring closed and
  never returns fewer than four positions or a zero-area ring.
* plan_geometry_refresh(): one geometry per (source_id, property_id); a
  failed or partial read changes nothing and nothing is ever deleted because
  it is missing from a read.

Standard library only.
"""
from __future__ import annotations

import csv
import math
import re
from dataclasses import dataclass, replace
from datetime import date, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
APPROVALS_CSV = REPO / "data" / "source_approvals.csv"

COLUMNS = (
    "source_id", "provider", "dataset_scope", "excluded_scope", "status", "basis", "license_name", "license_url",
    "evidence_ref", "evidence_sender", "evidence_received_on", "evidence_supplied_on", "evidence_limitation",
    "permitted_activities", "conditions", "credit", "change_notice", "disclaimer", "disclaimer_url", "metadata_url",
    "landing_urls", "expected_refresh_cadence", "last_successful_refresh", "technical_readme_url",
    "technical_readme_reviewed_on", "technical_caveats", "reviewer", "decided_on",
)
STATUSES = ("APPROVED_WITH_CONDITIONS", "APPROVED")
BASES = ("WRITTEN_PERMISSION", "PUBLISHED_LICENSE")
# The register states TAXACQ's own last successful refresh. NEVER = no
# successful refresh has happened (no ingestion path ran); UNKNOWN = it cannot
# be verified; otherwise an ISO timestamp of a COMPLETE read.
REFRESH_SENTINELS = ("NEVER", "UNKNOWN")
NOT_YET_READ = "NOT YET READ"


class ApprovalConfigError(ValueError):
    """The approval register is missing, unreadable or invalid."""


@dataclass(frozen=True)
class Approval:
    source_id: str
    provider: str
    dataset_scope: str
    excluded_scope: str
    status: str
    basis: str
    license_name: str
    license_url: str
    evidence_ref: str
    evidence_sender: str
    evidence_received_on: str
    evidence_supplied_on: str
    evidence_limitation: str
    permitted_activities: tuple[str, ...]
    conditions: str
    credit: str
    change_notice: str
    disclaimer: str
    disclaimer_url: str
    metadata_url: str
    landing_urls: tuple[str, ...]
    expected_refresh_cadence: str
    last_successful_refresh: str
    technical_readme_url: str
    technical_readme_reviewed_on: str
    technical_caveats: str
    reviewer: str
    decided_on: str

    @property
    def readme_reviewed(self) -> bool:
        """True only when a review date is recorded AND the caveats are the
        document's own (not the placeholder that says it was not read)."""
        return (bool(self.technical_readme_reviewed_on) and bool(self.technical_caveats.strip())
                and not self.technical_caveats.startswith(NOT_YET_READ))

    @property
    def attribution_complete(self) -> bool:
        """Credit, change notice, a disclaimer (text or https page) and an https
        metadata page - plus an https licence link when the basis is a
        published licence."""
        if not (self.credit.strip() and self.change_notice.strip()):
            return False
        if not (self.disclaimer.strip() or _https(self.disclaimer_url)):
            return False
        if not _https(self.metadata_url):
            return False
        if self.basis == "PUBLISHED_LICENSE" and not _https(self.license_url):
            return False
        return True


def _https(url: str) -> bool:
    return bool(re.match(r"^https://[^\s/]+\.[^\s/]+", url or ""))


def _split(value: str) -> tuple[str, ...]:
    return tuple(p.strip() for p in (value or "").split("|") if p.strip())


def _is_date(value: str) -> bool:
    try:
        date.fromisoformat(value)
        return True
    except ValueError:
        return False


def _is_timestamp(value: str) -> bool:
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        return True
    except ValueError:
        return False


def parse(rows) -> list[Approval]:
    out = []
    for r in rows:
        kw = {c: (r.get(c) or "").strip() for c in COLUMNS}
        kw["permitted_activities"] = _split(kw["permitted_activities"])
        kw["landing_urls"] = _split(kw["landing_urls"])
        out.append(Approval(**kw))
    return out


def validate(approvals: list[Approval]) -> list[str]:
    problems: list[str] = []
    seen: set[str] = set()
    for a in approvals:
        sid = a.source_id or "(blank)"
        if not a.source_id:
            problems.append("a row has no source_id")
        if a.source_id in seen:
            problems.append(f"{sid}: duplicate row")
        seen.add(a.source_id)
        if a.status not in STATUSES:
            problems.append(f"{sid}: status {a.status!r} not in {STATUSES}")
        if a.basis not in BASES:
            problems.append(f"{sid}: basis {a.basis!r} not in {BASES}")
        for col in ("dataset_scope", "excluded_scope", "evidence_ref", "evidence_limitation", "conditions",
                    "expected_refresh_cadence", "reviewer"):
            if not getattr(a, col):
                problems.append(f"{sid}: {col} is required")
        if not a.permitted_activities:
            problems.append(f"{sid}: permitted_activities is required")
        if not a.landing_urls or not all(_https(u) for u in a.landing_urls):
            problems.append(f"{sid}: landing_urls must be https pages")
        for col in ("evidence_received_on", "evidence_supplied_on", "technical_readme_reviewed_on", "decided_on"):
            v = getattr(a, col)
            if v and not _is_date(v):
                problems.append(f"{sid}: {col} {v!r} is not an ISO date")
        if not a.decided_on:
            problems.append(f"{sid}: decided_on is required")
        if a.basis == "PUBLISHED_LICENSE" and not _https(a.license_url):
            problems.append(f"{sid}: a published-licence basis needs an https licence_url")
        # The actual refresh is a fact of a TAXACQ read, never of the cadence.
        lsr = a.last_successful_refresh
        if lsr not in REFRESH_SENTINELS and not _is_timestamp(lsr):
            problems.append(f"{sid}: last_successful_refresh must be NEVER, UNKNOWN or a timestamp, not {lsr!r}")
        # A Readme review date without the document's own caveats is not a review.
        if a.technical_readme_reviewed_on and (not a.technical_caveats or a.technical_caveats.startswith(NOT_YET_READ)):
            problems.append(f"{sid}: technical_readme_reviewed_on is set but the caveats were not recorded from the document")
        if a.technical_readme_url and not _https(a.technical_readme_url):
            problems.append(f"{sid}: technical_readme_url must be https")
        # Evidence never invented: a received date is recorded only with a stated sender.
        if a.evidence_received_on and not a.evidence_sender:
            problems.append(f"{sid}: a received date needs the sender")
    return problems


def load(path: Path | None = None) -> dict[str, Approval]:
    p = Path(path) if path else APPROVALS_CSV
    try:
        with p.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            if tuple(reader.fieldnames or ()) != COLUMNS:
                raise ApprovalConfigError(f"{p.name}: header {tuple(reader.fieldnames or ())} != {COLUMNS}")
            approvals = parse(reader)
    except ApprovalConfigError:
        raise
    except Exception as exc:  # noqa: BLE001 - unreadable is invalid
        raise ApprovalConfigError(f"cannot read {p}: {type(exc).__name__}: {exc}") from exc
    problems = validate(approvals)
    if problems:
        raise ApprovalConfigError("; ".join(problems))
    return {a.source_id: a for a in approvals}


def get(source_id: str) -> Approval | None:
    """The approval row, or None (also when the register is invalid: the
    conditions that read it then fail closed)."""
    try:
        return load().get(source_id)
    except ApprovalConfigError:
        return None


# --- refresh tracking --------------------------------------------------------

REFRESH_SUCCESS = frozenset({"COMPLETE"})


@dataclass(frozen=True)
class RefreshState:
    expected_cadence: str
    last_successful_refresh: str          # NEVER | UNKNOWN | ISO timestamp
    last_attempt_at: str = ""
    last_attempt_status: str = ""
    consecutive_failures: int = 0


def apply_refresh(state: RefreshState, *, status: str, at: str, empty_signal: bool = False) -> RefreshState:
    """The state after one read. Only a COMPLETE read, or an EMPTY read that
    carries the source's own empty signal, advances last_successful_refresh.
    Anything else records the attempt and leaves the last success alone."""
    status = (status or "").upper()
    succeeded = status in REFRESH_SUCCESS or (status == "EMPTY" and empty_signal)
    if succeeded:
        return replace(state, last_successful_refresh=at, last_attempt_at=at, last_attempt_status=status,
                       consecutive_failures=0)
    return replace(state, last_attempt_at=at, last_attempt_status=status or "UNKNOWN",
                   consecutive_failures=state.consecutive_failures + 1)


# --- geometry: deterministic association, simplification, refresh plan -------

@dataclass(frozen=True)
class GeometryMatch:
    property_id: object
    key: str
    outcome: str            # MATCHED | UNMATCHED | AMBIGUOUS | NO_IDENTIFIER
    feature: dict | None = None


def match_geometries(records: list[dict], features: list[dict], *, record_key: str, feature_key: str,
                     normalize=lambda v: re.sub(r"\s+", "", str(v or "")).upper()) -> list[GeometryMatch]:
    """Associate each property record with exactly one feature on a documented
    identifier. A record with no identifier, no feature, or several features
    for the identifier is reported and never associated."""
    index: dict[str, list[dict]] = {}
    for f in features:
        k = normalize((f.get("attributes") or f).get(feature_key))
        if k:
            index.setdefault(k, []).append(f)
    out = []
    for r in records:
        k = normalize(r.get(record_key))
        if not k:
            out.append(GeometryMatch(r.get("id"), "", "NO_IDENTIFIER"))
            continue
        hits = index.get(k, [])
        if not hits:
            out.append(GeometryMatch(r.get("id"), k, "UNMATCHED"))
        elif len(hits) > 1:
            out.append(GeometryMatch(r.get("id"), k, "AMBIGUOUS"))
        else:
            out.append(GeometryMatch(r.get("id"), k, "MATCHED", hits[0]))
    return out


def unmatched_features(features: list[dict], records: list[dict], *, record_key: str, feature_key: str,
                       normalize=lambda v: re.sub(r"\s+", "", str(v or "")).upper()) -> int:
    """How many features no record claims (reported, never attached anywhere)."""
    keys = {normalize(r.get(record_key)) for r in records}
    return sum(1 for f in features if normalize((f.get("attributes") or f).get(feature_key)) not in keys)


def _perp(p, a, b) -> float:
    (x, y), (x1, y1), (x2, y2) = p, a, b
    dx, dy = x2 - x1, y2 - y1
    if dx == 0 and dy == 0:
        return math.hypot(x - x1, y - y1)
    return abs(dy * x - dx * y + x2 * y1 - y2 * x1) / math.hypot(dx, dy)


def _dp(points, tol):
    if len(points) < 3:
        return list(points)
    idx, dmax = 0, -1.0
    for i in range(1, len(points) - 1):
        d = _perp(points[i], points[0], points[-1])
        if d > dmax:
            idx, dmax = i, d
    if dmax > tol:
        return _dp(points[: idx + 1], tol)[:-1] + _dp(points[idx:], tol)
    return [points[0], points[-1]]


def _area(ring) -> float:
    return sum(ring[i][0] * ring[i + 1][1] - ring[i + 1][0] * ring[i][1] for i in range(len(ring) - 1)) / 2


def simplify_ring(ring: list[list[float]], tolerance: float) -> list[list[float]]:
    """A simplified closed ring. Falls back to the original ring when
    simplification would leave fewer than four positions or no area."""
    if len(ring) < 4 or ring[0] != ring[-1]:
        raise ValueError("a ring must be closed and have at least four positions")
    # Split the closed ring at the point farthest from the start so the
    # endpoints of both halves are fixed.
    far = max(range(1, len(ring) - 1), key=lambda i: math.hypot(ring[i][0] - ring[0][0], ring[i][1] - ring[0][1]))
    out = _dp(ring[: far + 1], tolerance)[:-1] + _dp(ring[far:], tolerance)
    if out[0] != out[-1]:
        out.append(out[0])
    if len(out) < 4 or _area(out) == 0:
        return [list(p) for p in ring]
    return [list(p) for p in out]


def plan_geometry_refresh(stored: dict, matches: list[GeometryMatch], *, source_id: str, read_status: str,
                          observed_at: str) -> dict:
    """What a refresh would do. `stored` maps property_id -> the current row for
    THIS source (one per property). A read that is not COMPLETE changes
    nothing; a record missing from a COMPLETE read keeps its geometry and is
    reported, never deleted; a property never gets a second geometry row."""
    plan = {"source_id": source_id, "insert": [], "replace": [], "unchanged": [], "kept_not_in_read": [],
            "unmatched": [], "ambiguous": [], "deleted": [], "skipped_read_not_complete": False}
    if (read_status or "").upper() != "COMPLETE":
        plan["skipped_read_not_complete"] = True
        return plan
    seen = set()
    for m in matches:
        if m.outcome == "UNMATCHED" or m.outcome == "NO_IDENTIFIER":
            plan["unmatched"].append(m.property_id)
            continue
        if m.outcome == "AMBIGUOUS":
            plan["ambiguous"].append(m.property_id)
            continue
        if m.property_id in seen:
            continue
        seen.add(m.property_id)
        geom = (m.feature or {}).get("geometry")
        row = stored.get(m.property_id)
        if row is None:
            plan["insert"].append({"property_id": m.property_id, "source_id": source_id, "geometry": geom,
                                   "source_observed_at": observed_at})
        elif row.get("geometry") == geom:
            plan["unchanged"].append(m.property_id)
        else:
            plan["replace"].append({"property_id": m.property_id, "source_id": source_id, "geometry": geom,
                                    "source_observed_at": observed_at})
    plan["kept_not_in_read"] = sorted((pid for pid in stored if pid not in seen), key=str)
    return plan
