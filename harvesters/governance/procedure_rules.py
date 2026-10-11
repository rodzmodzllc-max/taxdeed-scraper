"""County acquisition-procedure rules derived from verified acquisition
evidence (2026-10-11).

Every APPLICABLE row of the two acquisition evidence tables
(``data/purchase_path_evidence.csv``, ``data/purchase_path_evidence_expansion.csv``:
enabled, review_state=verified, anchored to an https evidence page the
capture job read) is an official county procedure that was actually read
and reviewed. The rules registry (``data/state_rules.csv``) is where the
product's verified jurisdiction rules live, and the verification engine's
county coverage counts a county as established for a ledger when a
county-scoped VERIFIED PROCEDURE rule names it. Before this module those two
records drifted: 21 verified evidence rows, 6 county PROCEDURE rules.

This module derives ONE rule per applicable evidence row, deterministically:
topic ``acquisition_procedure``, kind PROCEDURE, status VERIFIED, the
statement = the evidence wording the reviewer quoted, source_url = the
evidence page, verified_on = the day it was observed. The rule says nothing
the evidence row does not say. ``scripts/build_procedure_rules.py`` appends
the missing rules to the registry; its ``--check`` (pinned by a test) fails
when an applicable evidence row has no rule, or a rule's statement / source
drifted from its evidence row (a drift is corrected by a history row and a
version bump, never by a silent overwrite - the builder refuses to rewrite
an existing row).
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO / "scripts"))

from harvesters.governance import state_rules as SR  # noqa: E402
import purchase_path_engine as PPE  # noqa: E402

TOPIC = "acquisition_procedure"   # + "_<ledger>" per ledger: a county may have one procedure per ledger


def topic_for(ledger: str) -> str:
    """acquisition_procedure_available / _auctions / _liens_certificates (a
    '|'-joined ledger keeps both names)."""
    return TOPIC + "_" + ledger.lower().replace("|", "_")
EVIDENCE_TABLES = (REPO / "data" / "purchase_path_evidence.csv", REPO / "data" / "purchase_path_evidence_expansion.csv")
REGISTRY = REPO / "data" / "county_source_registry.csv"
TEST_REF = "tests/python/test_gap_closure.py"
DEPENDS_ON = ("scripts/purchase_path_engine.py resolve(): the evidence row is the acquisition record carried onto every "
              "active row of the unit (otc_provenance.acquisition) and the county's VERIFIED acquisition-evidence status "
              "(public/acquisition-evidence.json)")


def source_ledgers(registry: Path = REGISTRY) -> dict[str, str]:
    """source_id -> the registry's '|'-joined ledgers for it (AVAILABLE when
    the registry names none)."""
    out: dict[str, str] = {}
    with open(registry, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            sid = r.get("source_id") or ""
            if sid and sid not in out:
                out[sid] = (r.get("ledgers") or "").strip() or "AVAILABLE"
    return out


def applicable_evidence(tables=EVIDENCE_TABLES) -> list[tuple[str, PPE.EvidenceRow]]:
    """[(table name, row)] for every applicable (enabled + verified + https
    evidence page) row with a real county (never a '*' source-wide row)."""
    out = []
    for table in tables:
        for e in PPE.load_evidence(table):
            if e.applicable and e.county and e.county != "*":
                out.append((Path(table).name, e))
    return out


def rule_for(table: str, e: PPE.EvidenceRow, *, ledgers: dict[str, str], changed_on: str) -> SR.Rule:
    """The rule one evidence row establishes. Nothing here is invented: every
    field is the evidence row's own, or a fixed description of what depends
    on it."""
    ledger = ledgers.get(e.source_id, "AVAILABLE")
    return SR.Rule(
        state=e.state, county=e.county, topic=topic_for(ledger), kind="PROCEDURE", status="VERIFIED",
        statement=e.evidence,
        source_url=e.evidence_url, source_title=e.source_title or e.evidence_url, citation="", effective_date="",
        verified_on=e.observed_on,
        evidence=f"data/{table}: {e.state}/{e.source_id}/{e.county} ({e.path_type}; review_state verified)",
        ambiguity="",
        ledger=ledger, office=e.office, related_sources=e.source_id,
        depends_on=DEPENDS_ON, implementation_status="IMPLEMENTED", test_ref=TEST_REF,
        version="1", changed_on=changed_on,
    )


def expected_rules(*, changed_on: str, tables=EVIDENCE_TABLES, registry: Path = REGISTRY) -> list[SR.Rule]:
    ledgers = source_ledgers(registry)
    rules: dict[tuple, SR.Rule] = {}
    for table, e in applicable_evidence(tables):
        # One rule per county AND ledger (Morgan CO: county-held certificates
        # and treasurer-deed auctions are two procedures). A second evidence
        # row for the same county and ledger keeps the first table's row.
        r = rule_for(table, e, ledgers=ledgers, changed_on=changed_on)
        rules.setdefault((e.state, e.county, r.topic), r)
    return [rules[k] for k in sorted(rules)]


def _key(r: SR.Rule) -> tuple:
    return (r.state, r.county, r.topic)


def missing(existing: list[SR.Rule], expected: list[SR.Rule]) -> list[SR.Rule]:
    have = {_key(r) for r in existing}
    return [r for r in expected if _key(r) not in have]


def drifted(existing: list[SR.Rule], expected: list[SR.Rule]) -> list[str]:
    """Rules whose evidence row no longer says what the rule says. A drift
    is fixed by a history row + version bump in data/state_rules.csv, never
    by this builder."""
    by_key = {_key(r): r for r in existing}
    out = []
    for r in expected:
        cur = by_key.get(_key(r))
        if cur is None:
            continue
        for field in ("statement", "source_url", "verified_on", "ledger", "related_sources"):
            if getattr(cur, field) != getattr(r, field):
                out.append(f"{r.state}/{r.county}/{r.topic}: {field} differs from its evidence row")
    return out


def problems(existing: list[SR.Rule] | None = None, *, changed_on: str = "0000-00-00") -> list[str]:
    """Everything --check reports: missing rules and drifted rules. The
    `changed_on` of an expected rule is irrelevant to both."""
    existing = SR.load_rules() if existing is None else existing
    expected = expected_rules(changed_on=changed_on)
    return [f"missing rule {r.state}/{r.county}/{r.topic} (evidence {r.related_sources})" for r in missing(existing, expected)] + \
        drifted(existing, expected)
