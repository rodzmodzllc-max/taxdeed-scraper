"""Per-state AVAILABLE coverage: why a supported state shows the AVAILABLE
count it does, from what the repository records (no network, no database).

A zero is not one fact. This module names which of these a state's zero is:

  SOURCE_TRACKED          a production AVAILABLE source is harvested; a zero
                          then means the last read found nothing current
  SOURCE_EMPTY            the production source's last read was EMPTY
  SOURCE_UNAVAILABLE      every production source's last read FAILED
  MATCHING_FAILED         the last read could not be matched to identifiers
  REVIEW_REQUIRED         no production source; discovered candidates await
                          a capture and publication review
  HARD_BLOCKED            the only sources found are blocked
  NO_QUALIFYING_PROGRAM   researched: the state's post-sale instrument is a
                          lien / auction, not government-held property
  NO_SOURCE_DISCOVERED    nothing found yet

Only a source whose own ledger is AVAILABLE counts. An auction or lien
source never makes a state "covered" for AVAILABLE, and nothing here turns
an auction row into an AVAILABLE row.
"""
from __future__ import annotations

import csv
from pathlib import Path

from harvesters.governance.county_source_registry import load_registry

from . import inventory as INV

REPO = Path(__file__).resolve().parent.parent.parent
RESEARCH_PATH = REPO / "data" / "available_state_research.csv"
DISCOVERY_PATH = REPO / "data" / "available_discovery_pages.csv"

STATUSES = ("SOURCE_TRACKED", "SOURCE_EMPTY", "SOURCE_UNAVAILABLE", "MATCHING_FAILED", "REVIEW_REQUIRED",
            "HARD_BLOCKED", "NO_QUALIFYING_PROGRAM", "NO_SOURCE_DISCOVERED")
RESEARCH_FINDINGS = ("NO_QUALIFYING_PROGRAM", "CANDIDATES_FOUND")
_PUBLISHED = {"APPROVED", "APPROVED_GRANDFATHERED"}


def _csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def research() -> dict[str, dict]:
    out = {}
    for r in _csv(RESEARCH_PATH):
        if r["finding"] not in RESEARCH_FINDINGS:
            raise ValueError(f"{r['state']}: unknown research finding {r['finding']!r}")
        out[r["state"]] = r
    return out


def production_available_sources(state: str) -> list:
    """Registry rows whose ledger is AVAILABLE, verified in production and
    approved for publication - the only sources that can put rows there."""
    return [r for r in load_registry()
            if r.state == state and "AVAILABLE" in r.ledger_set and r.verification_status == "PRODUCTION_VERIFIED"
            and (r.publication_status or "") in _PUBLISHED]


def discovery_candidates(state: str, inventory=None) -> list:
    """Every non-production source recorded for AVAILABLE in this state:
    catalog / candidate rows with the availability role, and registry
    AVAILABLE rows not (yet) production-verified."""
    inv = INV.build_inventory() if inventory is None else inventory
    prod = {f"{r.state}:{r.county}:{r.source_id or 'unharvested_list'}" for r in production_available_sources(state)}
    return [s for s in inv if s.state == state and "availability" in s.roles and s.source_id not in prod]


def state_coverage(state: str, inventory=None) -> dict:
    prod = production_available_sources(state)
    cands = discovery_candidates(state, inventory)
    found = research().get(state, {})
    if prod:
        done = [r.completeness_status for r in prod]
        if all(c == "FAILED" for c in done):
            status = "SOURCE_UNAVAILABLE"
        elif any(c == "MATCH_FAILED" for c in done) and not any(c == "COMPLETE" for c in done):
            status = "MATCHING_FAILED"
        elif done and all(c == "EMPTY" for c in done):
            status = "SOURCE_EMPTY"
        else:
            status = "SOURCE_TRACKED"
    elif any(s.governance == "REVIEW_REQUIRED" for s in cands):
        status = "REVIEW_REQUIRED"
    elif cands and all(s.governance == "HARD_BLOCKED" for s in cands):
        status = "HARD_BLOCKED"
    elif found.get("finding") == "NO_QUALIFYING_PROGRAM":
        status = "NO_QUALIFYING_PROGRAM"
    else:
        status = "NO_SOURCE_DISCOVERED"
    return {
        "state": state,
        "status": status,
        "production_sources": len(prod),
        "production_counties": sorted({r.county for r in prod}),
        "last_reads": {c: sum(1 for r in prod if r.completeness_status == c) for c in sorted({r.completeness_status for r in prod})},
        "candidates": [{"source_id": s.source_id, "county": s.county, "name": s.name, "governance": s.governance,
                        "access": s.access, "url": s.url} for s in sorted(cands, key=lambda s: (s.county, s.source_id))],
        "research": {k: found.get(k, "") for k in ("finding", "mechanism", "detail", "evidence", "checked_on", "next_action")} if found else {},
    }


def coverage(inventory=None) -> list[dict]:
    inv = INV.build_inventory() if inventory is None else inventory
    return [state_coverage(st, inv) for st in INV.supported_states()]


def problems() -> list[str]:
    """Discovery pages and catalog rows must agree; a research finding must
    name a supported state."""
    out = []
    catalog = {r["source_id"]: r for r in _csv(INV.CATALOG_PATH)}
    states = set(INV.supported_states())
    for r in _csv(DISCOVERY_PATH):
        c = catalog.get(r["source_id"])
        if not c:
            out.append(f"{r['source_id']}: discovery page has no catalog row")
        elif (c["state"], c["county"], c["url"]) != (r["state"], r["county"], r["url"]):
            out.append(f"{r['source_id']}: discovery page and catalog row disagree")
        if not r["url"].startswith("https://"):
            out.append(f"{r['source_id']}: discovery url must be https")
    for st in research():
        if st not in states:
            out.append(f"{st}: research row for an unsupported state")
    return out
