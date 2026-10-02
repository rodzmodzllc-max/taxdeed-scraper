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
import re
from pathlib import Path

from harvesters.governance.county_source_registry import load_registry

from . import inventory as INV

REPO = Path(__file__).resolve().parent.parent.parent
RESEARCH_PATH = REPO / "data" / "available_state_research.csv"
DISCOVERY_PATH = REPO / "data" / "available_discovery_pages.csv"
EVIDENCE_PATH = REPO / "data" / "available_discovery_evidence.csv"
REVIEWS_PATH = REPO / "data" / "available_publication_reviews.csv"

STATUSES = ("SOURCE_TRACKED", "SOURCE_EMPTY", "SOURCE_UNAVAILABLE", "MATCHING_FAILED", "REVIEW_REQUIRED",
            "HARD_BLOCKED", "NO_QUALIFYING_PROGRAM", "NO_SOURCE_DISCOVERED")
RESEARCH_FINDINGS = ("NO_QUALIFYING_PROGRAM", "CANDIDATES_FOUND")
_PUBLISHED = {"APPROVED", "APPROVED_GRANDFATHERED"}

# What a value-free read of a candidate page established (2026-10-02). Only
# CURRENT_INVENTORY is government-held property the source itself offers now;
# every other value is a reason the page is NOT an AVAILABLE list today. An
# AUCTION_ONLY page (forfeited land sold only at the tax sale), a HISTORICAL
# list, or a REDEMPTION_ASSIGNMENT list (the commission's tax-sale bid assigned
# while the owner may still redeem - not property held for purchase) is
# rejected as non-AVAILABLE, never relabelled.
AVAILABILITY = ("CURRENT_INVENTORY", "EMPTY", "UNAVAILABLE", "SEASONAL_NOT_POSTED", "NOT_ESTABLISHED",
                "AUCTION_ONLY", "HISTORICAL", "REDEMPTION_ASSIGNMENT")
REJECTED_AVAILABILITY = {"AUCTION_ONLY", "HISTORICAL", "REDEMPTION_ASSIGNMENT"}
# A list that was actually read (so its identifier column can be confirmed).
LIST_READ = {"CURRENT_INVENTORY", "HISTORICAL", "REDEMPTION_ASSIGNMENT"}
REVIEW_CLASSIFICATIONS = ("APPROVED", "REVIEW_REQUIRED", "HARD_BLOCKED")
REVIEW_FLAGS = ("yes", "no", "not_stated", "undetermined")


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


def evidence() -> dict[str, dict]:
    """source_id -> the recorded read of that candidate page."""
    out = {}
    for r in _csv(EVIDENCE_PATH):
        if r["availability"] not in AVAILABILITY:
            raise ValueError(f"{r['source_id']}: unknown availability {r['availability']!r}")
        out[r["source_id"]] = r
    return out


def _base(source_id: str) -> str:
    """A registry source's unified id is '<ST>:<County>:<source_id>'."""
    return source_id.split(":")[-1]


def reviews() -> dict[str, dict]:
    """source_id -> the recorded publication review of that candidate."""
    return {r["source_id"]: r for r in _csv(REVIEWS_PATH)}


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
    ev = evidence()
    rv = reviews()
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
                        "access": s.access, "url": s.url,
                        "availability": ev.get(_base(s.source_id), {}).get("availability", "NOT_READ"),
                        "identifier_confirmed": ev.get(_base(s.source_id), {}).get("identifier_confirmed", "") == "yes",
                        "read_at": ev.get(_base(s.source_id), {}).get("read_at", ""),
                        "publication_review": rv.get(_base(s.source_id), {}).get("classification", "")}
                       for s in sorted(cands, key=lambda s: (s.county, s.source_id))],
        # Pages read and found NOT to offer AVAILABLE property (forfeited land
        # sold only at the auction, a past list): recorded, never a candidate.
        "rejected": [{"source_id": r["source_id"], "county": r["county"], "availability": r["availability"],
                      "url": r["evidence_url"]}
                     for r in sorted(ev.values(), key=lambda r: (r["county"], r["source_id"]))
                     if r["state"] == state and r["availability"] in REJECTED_AVAILABILITY],
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
    pages = {r["source_id"]: r for r in _csv(DISCOVERY_PATH)}
    for r in _csv(EVIDENCE_PATH):
        sid = r["source_id"]
        if sid not in pages:
            out.append(f"{sid}: evidence row for a page not in the discovery list")
        elif (r["state"], r["county"]) != (pages[sid]["state"], pages[sid]["county"]):
            out.append(f"{sid}: evidence row and discovery page disagree on state / county")
        if r["availability"] not in AVAILABILITY:
            out.append(f"{sid}: unknown availability {r['availability']!r}")
        if not r["evidence_url"].startswith("https://"):
            out.append(f"{sid}: evidence url must be https")
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", r["read_at"]) or not r["read_run"].isdigit():
            out.append(f"{sid}: evidence needs the capture run and its UTC read time")
        if r["identifier_confirmed"] not in ("yes", "no") or (r["identifier_confirmed"] == "yes" and not r["identifier_field"]):
            out.append(f"{sid}: a confirmed identifier names its column")
        if r["identifier_confirmed"] == "yes" and r["availability"] not in LIST_READ:
            out.append(f"{sid}: only a list that was read can confirm an identifier")
        # An adapter needs current inventory, a deterministic identifier and a
        # publication review; no read has met all three.
        if r["adapter_warranted"] not in ("yes", "no"):
            out.append(f"{sid}: adapter_warranted must be yes / no")
        elif r["adapter_warranted"] == "yes" and not (r["availability"] == "CURRENT_INVENTORY"
                                                       and r["identifier_confirmed"] == "yes"):
            out.append(f"{sid}: an adapter needs current inventory with a confirmed identifier")
        c = catalog.get(sid)
        if c and r["availability"] in REJECTED_AVAILABILITY and "availability" in c["roles"].split("|"):
            out.append(f"{sid}: a page rejected as {r['availability']} keeps the availability role")
        if c and c["governance"] != "REVIEW_REQUIRED":
            out.append(f"{sid}: a read page stays REVIEW_REQUIRED until a publication review")
    for sid, r in reviews().items():
        c = catalog.get(sid)
        if not c:
            out.append(f"{sid}: publication review for a source with no catalog row")
            continue
        if r["classification"] not in REVIEW_CLASSIFICATIONS:
            out.append(f"{sid}: unknown review classification {r['classification']!r}")
        # The review IS the source's governance: the catalog may never say more.
        if c["governance"] != r["classification"]:
            out.append(f"{sid}: catalog governance {c['governance']} disagrees with its publication review")
        if r["classification"] == "APPROVED" and r["commercial_use_permitted"] != "yes" and r["written_permission_needed"] != "no":
            out.append(f"{sid}: APPROVED needs a published reuse grant or recorded written permission")
        for k in ("commercial_use_permitted", "attribution_required", "republication_prohibited", "written_permission_needed"):
            if r[k] not in REVIEW_FLAGS:
                out.append(f"{sid}: {k} must be one of {REVIEW_FLAGS}")
        if not r["evidence_run"].isdigit() or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", r["reviewed_at"]):
            out.append(f"{sid}: a review cites its evidence run and UTC time")
        if not all(u.startswith("https://") for u in [r["source_url"], r["document_url"]] + r["terms_urls"].split(" | ")):
            out.append(f"{sid}: review URLs must be https")
    return out
