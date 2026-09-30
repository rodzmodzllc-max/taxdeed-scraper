"""May an OTC adapter run against a county source? One function, one
structured answer, three layers consulted in a fixed order - the same
discipline as harvesters/governance/gate.py and promotion.py, applied to
the county source registry:

  1. Blocked vendors are refused by name, whatever the row says
     (tx_pbfcm, tx_mvba, tx_govease, tx_ctsa - registry.py BLOCKED).
  2. The vendor/platform registry (registry.py) must not say BLOCKED,
     LEGAL_REVIEW_REQUIRED, DISABLED or TERMS_CHANGED for the row's
     source_id when it has one there.
  3. The row's STATE must be activated (harvesters/governance/states.py:
     a production state with every ACTIVATION_REQUIREMENTS item satisfied).
     A registered-but-inactive state (Alabama today) is refused here
     whatever its rows say.
  4. The county source registry row itself must be runnable:
     PRODUCTION_VERIFIED, approved governance, a harvester, a URL.

Search-engine evidence is not verification. Every Texas government
candidate the audit found fails layer 4 today; Alabama fails layer 3.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..governance import states
from ..governance.county_source_registry import BLOCKED_SOURCE_IDS, CountySourceRow, VerificationStatus
from ..governance.registry import INGESTION_ALLOWED_STATUSES, get_source


@dataclass(frozen=True)
class GateDecision:
    allowed: bool
    reason: str
    layer: str


def evaluate_source(row: CountySourceRow) -> GateDecision:
    if row.source_id in BLOCKED_SOURCE_IDS:
        return GateDecision(False, f"{row.source_id} is a BLOCKED vendor - discovery only, never fetched", "blocked_vendor")
    if row.source_id:
        rec = get_source(row.source_id)
        if rec is not None and rec.legal_status not in INGESTION_ALLOWED_STATUSES:
            return GateDecision(False, f"registry.py: {row.source_id} is {rec.legal_status.value}", "vendor_registry")
    if not states.is_activated(row.state):
        return GateDecision(False, f"state {row.state} is not activated for production - blockers: "
                                   f"{', '.join(states.activation_blockers(row.state))}", "state_activation")
    if row.verification_status != VerificationStatus.PRODUCTION_VERIFIED.value:
        return GateDecision(False, f"source is {row.verification_status}, not PRODUCTION_VERIFIED - search evidence is not verification", "verification")
    if not row.runnable:
        return GateDecision(False, f"row not runnable (governance {row.governance_status}, harvester {row.harvester or 'none'}, url {'set' if row.canonical_url else 'none'})", "county_registry")
    return GateDecision(True, "production-verified, approved, harvester named", "ok")
