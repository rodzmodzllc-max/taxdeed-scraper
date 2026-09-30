"""Source-level customer-publication gate for the AVAILABLE ledger (2026-09-30).

A row may be harvested, stored and enriched internally while its SOURCE is
not approved for customer publication. The decision is taken once per
source (a registry row), never per property, and a government website is
never treated as automatic commercial permission: publication is an
explicit registry value, validated against the source's governance state.

Seven things the gate tells apart, for one source:

  1. harvestable              a production-verified source with a named
                              harvester and a URL (the registry's own rule)
  2. establishes_availability the source feeds the AVAILABLE ledger with a
                              stated inventory type (it is a list of
                              purchasable / applicable inventory, not a sale
                              calendar)
  3. purchase_info            what the source publishes for buying:
                              "property" (a per-property action link is
                              established by an enabled rule), "instructions"
                              (a source-level process / application page),
                              "none"
  4. governance_ok            governance_status is APPROVED or
                              APPROVED_GRANDFATHERED (terms reviewed or
                              grandfathered production practice)
  5. publication APPROVED*    the registry says the source may be shown to
                              customers (APPROVED after a review;
                              APPROVED_GRANDFATHERED = already served to
                              customers before this gate existed, carried
                              forward - no separate review record)
  6. UNREVIEWED / RESTRICTED  not publishable: no review yet, or reviewed
                              and restricted (the `restrictions` column says
                              why)
  7. BLOCKED                  a blocked vendor; feeds no ledger

`customer_publishable` is true only for 5. The frontend withholds every
AVAILABLE row whose stored `publication_status` (migration 022, propagated
from the source by scripts/publication_gate.py) is not APPROVED*; a row
with no stored value (written before the column existed, or a source the
registry cannot name) keeps today's behaviour and is counted as
"unclassified" so the gap is measurable rather than hidden.

Nothing here decides a legal question. The values are registry data,
reviewed and committed; this module validates and applies them.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Iterable

PUBLICATION_STATUSES = ("APPROVED", "APPROVED_GRANDFATHERED", "UNREVIEWED", "RESTRICTED", "BLOCKED")
PUBLISHABLE_STATUSES = frozenset({"APPROVED", "APPROVED_GRANDFATHERED"})
DEFAULT_PUBLICATION = "UNREVIEWED"
STALE_DAYS = 14   # an AVAILABLE row not read from its source for this long is "stale" in the measurement


@dataclass(frozen=True)
class PublicationDecision:
    state: str
    county: str
    source_id: str
    ledgers: frozenset[str]
    harvestable: bool
    establishes_availability: bool
    purchase_info: str              # property | instructions | none
    governance_ok: bool
    publication: str                # PUBLICATION_STATUSES
    restrictions: str
    reasons: tuple[str, ...] = field(default_factory=tuple)

    @property
    def customer_publishable(self) -> bool:
        return self.publication in PUBLISHABLE_STATUSES

    def as_dict(self) -> dict:
        return {"state": self.state, "county": self.county, "source_id": self.source_id, "ledgers": sorted(self.ledgers),
                "harvestable": self.harvestable, "establishes_availability": self.establishes_availability,
                "purchase_info": self.purchase_info, "governance_ok": self.governance_ok, "publication": self.publication,
                "customer_publishable": self.customer_publishable, "restrictions": self.restrictions or None,
                "reasons": list(self.reasons)}


def effective_publication(row) -> str:
    """The publication status a registry row carries, with the two
    non-negotiable overrides: a blocked vendor is BLOCKED and a source under
    legal review is at most RESTRICTED, whatever the column says. Blank =
    UNREVIEWED."""
    from .county_source_registry import BLOCKED_SOURCE_IDS
    value = (getattr(row, "publication_status", "") or "").strip() or DEFAULT_PUBLICATION
    if row.source_id in BLOCKED_SOURCE_IDS or row.governance_status == "BLOCKED":
        return "BLOCKED"
    if row.governance_status == "LEGAL_REVIEW_REQUIRED" and value in PUBLISHABLE_STATUSES:
        return "RESTRICTED"
    return value


def publication_problems(row) -> list[str]:
    """Validation of the registry's publication columns for one row."""
    from .county_source_registry import BLOCKED_SOURCE_IDS, RUNNABLE_GOVERNANCE
    problems: list[str] = []
    raw = (getattr(row, "publication_status", "") or "").strip()
    value = raw or DEFAULT_PUBLICATION
    if value not in PUBLICATION_STATUSES:
        return [f"publication_status {raw!r}"]
    restrictions = (getattr(row, "restrictions", "") or "").strip()
    blocked = row.source_id in BLOCKED_SOURCE_IDS or row.governance_status == "BLOCKED"
    if blocked and value != "BLOCKED":
        problems.append("a blocked vendor's publication_status must be BLOCKED")
    if value == "BLOCKED" and not blocked:
        problems.append("publication_status BLOCKED on a source that is not a blocked vendor")
    if value in PUBLISHABLE_STATUSES:
        if row.governance_status not in RUNNABLE_GOVERNANCE:
            problems.append(f"publication_status {value} requires governance APPROVED or APPROVED_GRANDFATHERED, not {row.governance_status!r} "
                            "(a government website is not commercial permission)")
        if not row.is_production:
            problems.append(f"publication_status {value} on a source that is not PRODUCTION_VERIFIED")
    if value == "RESTRICTED" and not restrictions:
        problems.append("publication_status RESTRICTED must say why (restrictions)")
    if row.governance_status == "LEGAL_REVIEW_REQUIRED" and value in PUBLISHABLE_STATUSES:
        problems.append("a source under LEGAL_REVIEW_REQUIRED cannot be published")
    return problems


def decide(row, *, property_rule_enabled: bool = False) -> PublicationDecision:
    """The full decision for one registry row. `property_rule_enabled` says
    whether an enabled purchase-link rule (data/laft_purchase_link_rules.csv)
    establishes per-property links for this source - the registry itself
    only knows source-level paths."""
    from .county_source_registry import AVAILABLE_INVENTORY_TYPES
    reasons: list[str] = []
    harvestable = bool(row.is_production and row.harvester and row.canonical_url)
    if not harvestable:
        reasons.append("not harvestable: " + ("not PRODUCTION_VERIFIED" if not row.is_production else "no harvester or URL"))
    ledgers = row.ledger_set
    establishes = "AVAILABLE" in ledgers and (row.inventory_type in AVAILABLE_INVENTORY_TYPES or row.state == "TX")
    if "AVAILABLE" in ledgers and not establishes:
        reasons.append("feeds AVAILABLE without a stated inventory type")
    if property_rule_enabled:
        purchase_info = "property"
    elif row.purchase_url and row.purchase_url_kind:
        purchase_info = "property" if row.purchase_url_kind in ("online_purchase", "offer_form", "bid_form") else "instructions"
    else:
        purchase_info = "none"
        if "AVAILABLE" in ledgers:
            reasons.append("no purchase or application path published at source level")
    from .county_source_registry import RUNNABLE_GOVERNANCE
    governance_ok = row.governance_status in RUNNABLE_GOVERNANCE
    if not governance_ok:
        reasons.append(f"governance {row.governance_status}")
    publication = effective_publication(row)
    if publication not in PUBLISHABLE_STATUSES:
        reasons.append(f"publication {publication}")
    return PublicationDecision(state=row.state, county=row.county, source_id=row.source_id, ledgers=frozenset(ledgers),
                               harvestable=harvestable, establishes_availability=establishes, purchase_info=purchase_info,
                               governance_ok=governance_ok, publication=publication,
                               restrictions=(getattr(row, "restrictions", "") or "").strip(), reasons=tuple(reasons))


def decisions_by_source(rows, *, property_rule_sources: frozenset[str] = frozenset()) -> dict[str, PublicationDecision]:
    """One decision per source_id. A source with several county rows must
    agree on publication (the generator guarantees it; a disagreement is
    reported as the strictest value so a county can never be published by
    accident)."""
    order = {s: i for i, s in enumerate(("BLOCKED", "RESTRICTED", "UNREVIEWED", "APPROVED_GRANDFATHERED", "APPROVED"))}
    out: dict[str, PublicationDecision] = {}
    for r in rows:
        if not r.source_id:
            continue
        d = decide(r, property_rule_enabled=r.source_id in property_rule_sources)
        prev = out.get(r.source_id)
        if prev is None or order[d.publication] < order[prev.publication]:
            out[r.source_id] = d
    return out


def source_id_of(row: dict) -> str | None:
    """The registry source id a properties row belongs to: its own
    `source_id` (written by the LAFT lifecycle) first, then the harvester's
    tag. `fl_realauction_<county>` tags collapse to `fl_realauction`; an
    unknown tag is None - never guessed into a source."""
    sid = str(row.get("source_id") or "").strip()
    if sid:
        return sid
    tag = str(row.get("harvester_source") or "").strip()
    if not tag:
        return None
    if tag.startswith("fl_realauction_"):
        return "fl_realauction"
    return tag


def row_publication(row: dict, decisions: dict[str, PublicationDecision]) -> str | None:
    """The publication status a properties row should carry, or None when
    its source cannot be named (left unclassified, never withheld silently
    and never approved by default)."""
    sid = source_id_of(row)
    if not sid or sid not in decisions:
        return None
    return decisions[sid].publication


def _dt(value) -> datetime | None:
    if not value:
        return None
    try:
        t = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return t if t.tzinfo else t.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def measure(rows: Iterable[dict], decisions: dict[str, PublicationDecision], *, now: datetime | None = None,
            unavailable_units: set[tuple[str, str, str]] | None = None, stale_days: int = STALE_DAYS) -> dict:
    """The AVAILABLE-inventory measurement the product needs (counts only):
    total observed, publishable, restricted, unreviewed, blocked,
    unclassified (source not nameable), unavailable-source (the row's unit
    last read SOURCE_UNAVAILABLE), with / without a purchase path, stale
    (not read from its source for `stale_days`, or never)."""
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=stale_days)
    unavailable_units = unavailable_units or set()
    c = {"total_observed": 0, "publishable": 0, "restricted": 0, "unreviewed": 0, "blocked": 0, "unclassified": 0,
         "unavailable_source": 0, "with_purchase_path": 0, "without_purchase_path": 0, "stale": 0, "stale_days": stale_days}
    by_source: dict[str, dict[str, int]] = {}
    for r in rows:
        if r.get("source") not in (None, "laft"):
            continue
        c["total_observed"] += 1
        status = row_publication(r, decisions)
        sid = source_id_of(r) or "(unknown)"
        s = by_source.setdefault(sid, {"rows": 0, "publishable": 0, "with_purchase_path": 0, "stale": 0})
        s["rows"] += 1
        if status is None:
            c["unclassified"] += 1
        elif status in PUBLISHABLE_STATUSES:
            c["publishable"] += 1
            s["publishable"] += 1
        elif status == "RESTRICTED":
            c["restricted"] += 1
        elif status == "BLOCKED":
            c["blocked"] += 1
        else:
            c["unreviewed"] += 1
        if (str(r.get("state") or ""), sid, str(r.get("county") or "")) in unavailable_units:
            c["unavailable_source"] += 1
        # A purchase path is a verified URL OR a typed non-URL process
        # (migration 023's purchase_path_type: phone_mail, quoted_amount,
        # in_person, ... from a reviewed evidence page) - the customer's
        # "how do I buy this" is answered either way.
        if r.get("purchase_url") or r.get("purchase_path_type"):
            c["with_purchase_path"] += 1
            s["with_purchase_path"] += 1
        else:
            c["without_purchase_path"] += 1
        seen = _dt(r.get("last_seen_at"))
        if seen is None or seen < cutoff:
            c["stale"] += 1
            s["stale"] += 1
    return {"counts": c, "by_source": dict(sorted(by_source.items())), "note": "counts only; never a row value"}
