"""County intelligence: one record per (production state, county) above the
source registry.

What it answers, per county, from the repository's own records only:

* which sources feed each ledger (Available / Auctions / Liens & Certificates),
  who publishes them, whether they are production-verified and whether they
  are approved for customer publication;
* whether the county's acquisition process has been verified from an official
  page (the purchase-path evidence tables) and whether the source's financial
  terms have been read (data/available_financial_terms.csv);
* what research exists that is not yet a source (discovery candidates,
  acquisition candidate pages, recorded discovery findings).

Two vocabularies come out of it:

* ``COVERAGE`` per ledger - COVERED / PARTIALLY_COVERED / RESEARCH_ONLY /
  NO_SOURCE_BACKED_INVENTORY. SOURCE_UNAVAILABLE is a runtime state: it
  depends on the last read (county_source_registry freshness columns), which
  the repository does not hold, so the frontend overlays it.
* ``INTEL_STATES`` per county - VERIFIED / SOURCE_BACKED / PARTIALLY_VERIFIED /
  NEEDS_REVIEW / NOT_YET_RESEARCHED (SOURCE_UNAVAILABLE again a runtime
  overlay).

Nothing here is a score. Every state is a statement about which records
exist, and ``reasons`` names them. Nothing is fetched; values are never read.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

from harvesters.governance import states as STATES
from harvesters.governance.county_source_registry import load_registry

REPO = Path(__file__).resolve().parents[2]
DATA = REPO / "data"

LEDGERS = ("AVAILABLE", "AUCTIONS", "LIENS_CERTIFICATES")
COVERAGE = ("COVERED", "PARTIALLY_COVERED", "RESEARCH_ONLY", "NO_SOURCE_BACKED_INVENTORY", "SOURCE_UNAVAILABLE")
INTEL_STATES = ("VERIFIED", "SOURCE_BACKED", "PARTIALLY_VERIFIED", "NEEDS_REVIEW", "NOT_YET_RESEARCHED", "SOURCE_UNAVAILABLE")
# The states the repository can decide. SOURCE_UNAVAILABLE needs a read.
STATIC_COVERAGE = COVERAGE[:-1]
STATIC_INTEL = INTEL_STATES[:-1]

CUSTOMER_APPROVED = frozenset({"APPROVED", "APPROVED_GRANDFATHERED"})
EVIDENCE_FILES = ("purchase_path_evidence.csv", "purchase_path_evidence_expansion.csv")
CANDIDATE_FILES = ("available_discovery_pages.csv", "available_source_candidates.csv", "acquisition_candidate_pages.csv")


def _csv(name: str) -> list[dict]:
    path = DATA / name
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def _counties() -> dict[str, list[str]]:
    """Every county of every production state, from the basemap centroids
    (the same names the frontend draws and filters by)."""
    doc = json.loads((REPO / "public" / "county-centroids.json").read_text(encoding="utf-8"))
    return {st: sorted(doc.get(st, {}).keys()) for st in sorted(STATES.PRODUCTION_STATES)}


def _verified_evidence() -> dict[tuple[str, str, str], list[dict]]:
    out: dict[tuple[str, str, str], list[dict]] = {}
    for name in EVIDENCE_FILES:
        for r in _csv(name):
            if (r.get("review_state") or "").strip() != "verified" or (r.get("enabled") or "").strip() != "yes":
                continue
            if not (r.get("evidence_url") or "").startswith("https://"):
                continue
            out.setdefault((r["state"], r["county"], r["source_id"]), []).append(r)
    return out


def _terms() -> list[dict]:
    return _csv("available_financial_terms.csv")


def _terms_for(terms: list[dict], state: str, source_id: str, county: str) -> bool:
    for t in terms:
        if t.get("state") != state:
            continue
        if t.get("source_id") and t["source_id"] != source_id:
            continue
        if t.get("county") and t["county"] != county:
            continue
        return True
    return False


def _candidates() -> dict[tuple[str, str], int]:
    out: dict[tuple[str, str], int] = {}
    for name in CANDIDATE_FILES:
        for r in _csv(name):
            key = (r.get("state", ""), r.get("county", ""))
            out[key] = out.get(key, 0) + 1
    return out


def ledger_coverage(sources: list[dict], research: int) -> tuple[str, list[str]]:
    """One ledger of one county. ``sources`` are registry entries (dicts made
    by ``_source``); ``research`` counts candidate pages for the county."""
    live = [s for s in sources if s["production"] and s["publication"] != "BLOCKED"]
    if any(s["customer_approved"] for s in live):
        return "COVERED", ["a production-verified source approved for customer publication"]
    if live:
        return "PARTIALLY_COVERED", ["a production-verified source is collected but not approved for customer publication"]
    if [s for s in sources if s["publication"] != "BLOCKED"] or research:
        return "RESEARCH_ONLY", ["a source is known but not harvested in production" if sources else "candidate pages recorded; no source harvested"]
    if sources:
        return "NO_SOURCE_BACKED_INVENTORY", ["the only known sources are excluded under the blocked-vendor rule"]
    return "NO_SOURCE_BACKED_INVENTORY", ["no source recorded"]


def intel_state(ledgers: dict, acquisition_verified: bool, terms_known: bool, research: int) -> tuple[str, list[str]]:
    cov = {k: v["coverage"] for k, v in ledgers.items()}
    approved = [k for k, c in cov.items() if c == "COVERED"]
    available_approved = cov.get("AVAILABLE") == "COVERED"
    if approved:
        if available_approved:
            if acquisition_verified and terms_known:
                return "VERIFIED", ["approved source", "acquisition process verified from an official page", "financial terms read from the source"]
            if acquisition_verified or terms_known:
                missing = "financial terms not yet read" if acquisition_verified else "acquisition process not yet verified"
                return "PARTIALLY_VERIFIED", ["approved Available source", missing]
            return "SOURCE_BACKED", ["approved Available source", "acquisition process and financial terms not yet verified"]
        return "SOURCE_BACKED", ["approved source for " + ", ".join(k.replace("_", " ").title() for k in approved)]
    if any(c in ("PARTIALLY_COVERED", "RESEARCH_ONLY") for c in cov.values()) or research:
        return "NEEDS_REVIEW", ["sources or candidates recorded, none approved for customer publication yet"]
    return "NOT_YET_RESEARCHED", ["no source, candidate or evidence recorded for this county"]


def _source(r, approved_override: str | None = None) -> dict:
    pub = r.publication_status or ""
    return {
        "source_id": r.source_id,
        "name": r.source_terminology or r.source_id,
        "publisher": r.publishing_unit_name or r.source_authority or "",
        "url": r.canonical_url or r.document_url or "",
        "publication": pub,
        "customer_approved": pub in CUSTOMER_APPROVED,
        "production": bool(r.is_production),
        "verification": r.verification_status,
        "last_checked": r.last_checked,
    }


def build() -> dict:
    registry = load_registry()
    evidence = _verified_evidence()
    terms = _terms()
    candidates = _candidates()
    counties = _counties()
    out_states = []
    for st, names in counties.items():
        rows = [r for r in registry if r.state == st]
        known = sorted(set(names) | {r.county for r in rows if r.county and r.county != "STATEWIDE"})
        out_counties = []
        for county in known:
            here = [r for r in rows if r.county == county]
            research = candidates.get((st, county), 0)
            ledgers = {}
            for ledger in LEDGERS:
                srcs = [_source(r) for r in here if ledger in r.ledger_set]
                cov, _ = ledger_coverage(srcs, research if ledger == "AVAILABLE" else 0)
                ledgers[ledger] = {"coverage": cov, "sources": srcs}
            avail_ids = [s["source_id"] for s in ledgers["AVAILABLE"]["sources"] if s["production"]]
            ev = [e for sid in avail_ids for e in evidence.get((st, county, sid), [])]
            acq = {
                "verified": bool(ev),
                "path_types": sorted({e["path_type"] for e in ev}),
                "observed_on": max((e.get("observed_on") or "" for e in ev), default=""),
                "office": next((e["office"] for e in ev if e.get("office")), ""),
                "evidence_title": next((e["source_title"] for e in ev if e.get("source_title")), ""),
                "evidence_url": next((e["evidence_url"] for e in ev if e.get("evidence_url")), ""),
            }
            terms_known = bool(avail_ids) and all(_terms_for(terms, st, sid, county) for sid in avail_ids)
            state, _ = intel_state(ledgers, acq["verified"], terms_known, research)
            entry = {"county": county, "intel": state, "ledgers": ledgers,
                     "financial_terms": terms_known, "research_candidates": research}
            if acq["verified"]:
                entry["acquisition"] = acq
            if state == "NOT_YET_RESEARCHED" and not any(v["sources"] for v in ledgers.values()):
                # The default: a county the file does not list is not yet
                # researched, with no source on any ledger.
                continue
            out_counties.append(entry)
        out_states.append({"state": st, "county_total": len(known), "counties": out_counties})
    return {
        "note": "Generated by scripts/build_county_intelligence.py from the source registry, the verified purchase-path "
                "evidence, the Available financial terms and the discovery candidates. SOURCE_UNAVAILABLE depends on "
                "the last read and is decided by the app from county_source_registry freshness, never here.",
        "ledgers": list(LEDGERS), "coverage": list(COVERAGE), "intel_states": list(INTEL_STATES),
        "default_county": {"intel": "NOT_YET_RESEARCHED", "coverage": "NO_SOURCE_BACKED_INVENTORY"},
        "states": out_states,
    }


def problems(doc: dict | None = None) -> list[str]:
    doc = doc or build()
    out = []
    for s in doc["states"]:
        for c in s["counties"]:
            if c["intel"] not in STATIC_INTEL:
                out.append(f"{s['state']}:{c['county']}: intel {c['intel']!r} is not decidable from the repository")
            for ledger, v in c["ledgers"].items():
                if v["coverage"] not in STATIC_COVERAGE:
                    out.append(f"{s['state']}:{c['county']}:{ledger}: coverage {v['coverage']!r}")
            if c["intel"] == "VERIFIED" and not (c.get("acquisition", {}).get("verified") and c["financial_terms"]):
                out.append(f"{s['state']}:{c['county']}: VERIFIED without verified acquisition and terms")
    return out
