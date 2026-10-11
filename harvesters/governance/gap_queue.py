"""The gap-closure work queue (2026-10-11): every unresolved acquisition-path
unit and every non-current state x ledger unit, each in ONE operational
category, with what is missing, whether the source is reachable and
approved, whether the rule and the process are verified, the exact next
action and whether it can be completed from the repository now.

Categories (the sprint's own vocabulary):
  A  implementable now from verified repository data or an accessible official source
  B  requires a new parser / extractor / adapter / enrichment implementation
  C  requires additional official evidence obtainable through an already-approved
     mechanism (the manual `job=evidence` capture of the harvest workflow)
  D  blocked by source access or a technical restriction
  E  blocked by source-use permission or an explicit owner decision
  F  blocked because the jurisdiction's process or product cannot yet be
     established authoritatively

Inputs are repository records only: public/acquisition-evidence.json (unit
status), data/current_state/state-coverage.json (ledger classification),
data/acquisition_candidate_pages.csv (official pages identified but not yet
captured) and the registry. Counts only; no row value.
"""
from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ACQ = REPO / "public" / "acquisition-evidence.json"
COVERAGE = REPO / "data" / "current_state" / "state-coverage.json"
CANDIDATES = REPO / "data" / "acquisition_candidate_pages.csv"
REGISTRY = REPO / "data" / "county_source_registry.csv"

CATEGORIES = ("A", "B", "C", "D", "E", "F")
CATEGORY_LABELS = {
    "A": "implementable now from repository data or an accessible official source",
    "B": "needs a parser / extractor / adapter / enrichment implementation",
    "C": "needs official evidence through the approved capture mechanism (job=evidence)",
    "D": "blocked by source access or a technical restriction",
    "E": "blocked by source-use permission or an owner decision",
    "F": "the jurisdiction's process or product cannot yet be established authoritatively",
}
# Blocked vendors / legal-review sources the engine refuses (registry governance).
RESTRICTED_SOURCES = {"tx_hctax": "registry governance LEGAL_REVIEW_REQUIRED: hctax.net terms not cleared for redistribution"}
VENDOR_LISTINGS = {"tx_lgbs": "a delinquent-tax counsel's vendor listing; the county publishes no resale process page"}


def load_inputs(acq: Path = ACQ, coverage: Path = COVERAGE, candidates: Path = CANDIDATES, registry: Path = REGISTRY) -> dict:
    with open(candidates, newline="", encoding="utf-8") as fh:
        cands = list(csv.DictReader(fh))
    with open(registry, newline="", encoding="utf-8") as fh:
        reg = list(csv.DictReader(fh))
    return {"acquisition": json.loads(acq.read_text(encoding="utf-8")),
            "coverage": json.loads(coverage.read_text(encoding="utf-8")),
            "candidates": cands, "registry": reg}


def _publication(reg: list[dict], source_id: str, county: str) -> str:
    for r in reg:
        if r.get("source_id") == source_id and r.get("county") == county:
            return r.get("publication_status") or "UNREVIEWED"
    for r in reg:
        if r.get("source_id") == source_id:
            return r.get("publication_status") or "UNREVIEWED"
    return "UNREVIEWED"


def classify_acquisition_unit(u: dict, *, candidates: list[dict], publication: str) -> dict:
    """One acquisition unit (state, source, county) -> category and the
    operational record. The reason is the status file's own wording."""
    st, sid, county, status = u["state"], u["source_id"], u["county"], u["status"]
    reason = str(u.get("reason") or "")
    cands = [c for c in candidates if c.get("state") == st and c.get("county") == county and c.get("source_id", "") in ("", sid)]
    approved = publication in ("APPROVED", "APPROVED_GRANDFATHERED")
    rec = {"kind": "acquisition_unit", "state": st, "county": county, "source_id": sid, "ledger": "AVAILABLE", "status": status,
           "source": "registry source " + sid, "approved_for_customers": approved, "publication_status": publication,
           "rule_verified": None, "process_verified": False, "candidate_pages": len(cands), "reason": reason}
    low = reason.lower()
    if status == "UNAVAILABLE":
        cat, access, action = "D", "no", "The county's official pages answer HTTP 403 to the GitHub runner; a records request or an allow-listed capture host is the only way forward"
    elif sid in RESTRICTED_SOURCES:
        cat, access, action = "E", "yes", f"Owner / legal decision on the source: {RESTRICTED_SOURCES[sid]}"
    elif sid in VENDOR_LISTINGS and status == "NOT_FOUND":
        cat, access, action = "F", "yes", f"No official resale-process page exists to read ({reason}); the path cannot be established from {VENDOR_LISTINGS[sid]}"
    elif "rendered by script" in low:
        cat, access, action = "B", "yes", "Implement a browser-rendered capture for the county's script-rendered process page, then record the evidence row"
    elif "scanned" in low or "ocr" in low:
        cat, access, action = "B", "yes", "Implement OCR extraction of the scanned process packet, then record the evidence row"
    elif status == "NEEDS_REVIEW":
        cat, access, action = "C", "yes", "Capture the identified official page(s) with job=evidence (acquisition_candidates scope), read the digest, record a verified evidence row"
    elif status == "NOT_FOUND" and cands:
        cat, access, action = "C", "yes", "Capture the identified candidate page(s) with job=evidence, read the digest, record a verified evidence row or an outcome"
    elif status == "NOT_FOUND" and ("auction only" in low or "no lands available purchase" in low):
        cat, access, action = "F", "yes", "The official pages read describe the auction only; the Lands Available purchase step is not published online - a clerk enquiry (not an approved mechanism) would be needed"
    elif status == "NOT_FOUND":
        cat, access, action = "F", "unknown", "No official acquisition page identified; identify a candidate page first (add it to data/acquisition_candidate_pages.csv), then capture it"
    else:
        cat, access, action = "C", "yes", "Capture and review"
    rec.update({"category": cat, "source_accessible": access, "next_action": action,
                "completable_now": cat == "A", "requires": CATEGORY_LABELS[cat]})
    return rec


def classify_ledger_unit(st: str, ledger: str, l: dict) -> dict | None:
    """One state x ledger unit from the coverage report -> category, or None
    when it is CURRENT."""
    concept = l["classification"]
    if concept == "CURRENT":
        return None
    reasons = "; ".join(l.get("classification_reasons") or [])
    rec = {"kind": "state_ledger", "state": st, "county": "*", "ledger": ledger, "status": concept,
           "source": f"{l['sources']['implemented']} production source(s) of {l['sources']['known']} known",
           "approved_for_customers": l["sources"]["approved_for_customers"] > 0, "rule_verified": l["eligibility"] in ("OFFERED", "NOT_OFFERED"),
           "eligibility": l["eligibility"], "process_verified": bool(l["acquisition"].get("verified_units")), "reason": reasons}
    if concept == "RULES_NOT_VERIFIED":
        cat, access, action = "C", "not from the sandbox (statute hosts are DNS-blocked); unverified from the GitHub runner", \
            "Read the state's enabling statute / sale-authority page through the approved capture job, record a VERIFIED LAW rule and the ledger's eligibility"
    elif concept == "APPROVAL_UNRESOLVED":
        cat, access, action = "E", "yes", "Owner publication review of the source (admin publication panel): approve, restrict or block"
    elif concept == "SOURCE_RESTRICTED":
        cat, access, action = "E", "yes", "Owner / legal decision on the restricted source"
    elif concept == "OFFERED_SOURCE_NOT_IMPLEMENTED":
        cat, access, action = "B", "yes", "Implement the adapter for the known source (registry candidate), gated and fixture-validated first"
    elif concept == "SOURCE_IMPLEMENTED_NEVER_READ":
        cat, access, action = "C", "yes", "The next scheduled read (or job=evidence) records the first read; nothing to change until it runs"
    elif concept == "SOURCE_FAILED_OR_STALE":
        if "manual-only" in reasons:
            cat, access, action = "E", "yes", "Manual-only source by owner decision (job=texas); a read happens only when the owner dispatches it"
        elif "never stamped" in reasons and ledger == "LIENS_CERTIFICATES":
            cat, access, action = "D", "no", "LienHub answers HTTP 403 to the GitHub runner since 2026-10-01; nothing to change in code until the source is reachable"
        else:
            cat, access, action = "A", "yes", "Deploy the keyset-read fix (PR #132 stack: sync_state_inventory.stored_provenance) - the state's sync has failed on HTTP 500 every run since; no code left to write"
    elif concept == "RECORDS_WITHHELD_NO_PATH":
        cat, access, action = "C", "yes", "Capture the county's acquisition process with job=evidence and record the evidence row"
    elif concept == "OFFERED_VERIFIED_EMPTY":
        cat, access, action = "A", "yes", "Nothing to do: the source was read and lists nothing"
    else:
        cat, access, action = "F", "unknown", "Establish the product and process authoritatively first"
    rec.update({"category": cat, "source_accessible": access, "next_action": action,
                "completable_now": cat == "A", "requires": CATEGORY_LABELS[cat]})
    return rec


def build(inputs: dict | None = None) -> dict:
    inp = inputs or load_inputs()
    acq, cov, cands, reg = inp["acquisition"], inp["coverage"], inp["candidates"], inp["registry"]
    units = []
    for u in acq["status"]:
        if u["status"] == "VERIFIED":
            continue
        units.append(classify_acquisition_unit(u, candidates=cands, publication=_publication(reg, u["source_id"], u["county"])))
    for st, e in sorted(cov["states"].items()):
        for ledger, l in e["ledgers"].items():
            rec = classify_ledger_unit(st, ledger, l)
            if rec:
                units.append(rec)
    units.sort(key=lambda r: (r["category"], r["kind"], r["state"], r["ledger"], r["county"]))
    acq_total = len(acq["status"])
    acq_by = Counter(u["status"] for u in acq["status"])
    return {
        "generated_from": {"acquisition": "public/acquisition-evidence.json", "coverage": "data/current_state/state-coverage.json",
                           "candidates": "data/acquisition_candidate_pages.csv", "registry": "data/county_source_registry.csv",
                           "note": "counts only; every reason is the status file's own wording; no row value"},
        "categories": CATEGORY_LABELS,
        "denominators": {
            "acquisition_units": acq_total, "acquisition_by_status": dict(sorted(acq_by.items())),
            "acquisition_unresolved": acq_total - acq_by.get("VERIFIED", 0),
            "state_ledger_units": sum(len(e["ledgers"]) for e in cov["states"].values()),
            "state_ledger_by_classification": cov["summary"],
        },
        "summary": {"by_category": dict(sorted(Counter(u["category"] for u in units).items())),
                    "completable_now": sum(1 for u in units if u["completable_now"]),
                    "acquisition_units_queued": sum(1 for u in units if u["kind"] == "acquisition_unit"),
                    "state_ledger_units_queued": sum(1 for u in units if u["kind"] == "state_ledger")},
        "units": units,
    }


def render_markdown(doc: dict) -> str:
    d, s = doc["denominators"], doc["summary"]
    out = ["# Gap-closure work queue", "",
           f"Generated from {doc['generated_from']['acquisition']}, {doc['generated_from']['coverage']}, "
           f"{doc['generated_from']['candidates']} and the registry. Counts only.", "",
           f"- Acquisition-path units: {d['acquisition_units']} total, {d['acquisition_unresolved']} unresolved "
           f"({', '.join(f'{k} {v}' for k, v in d['acquisition_by_status'].items())}).",
           f"- State x ledger units: {d['state_ledger_units']} total "
           f"({', '.join(f'{k} {v}' for k, v in d['state_ledger_by_classification'].items())}).",
           f"- Queue: {len(doc['units'])} entries - by category "
           f"{', '.join(f'{k} {v}' for k, v in s['by_category'].items())}; completable now from the repository: {s['completable_now']}.", ""]
    for cat in CATEGORIES:
        rows = [u for u in doc["units"] if u["category"] == cat]
        if not rows:
            continue
        out += [f"## {cat}. {doc['categories'][cat]} ({len(rows)})", "",
                "| Unit | Ledger | Status | Source reachable | Approved | Rule verified | Process verified | Next action |",
                "|---|---|---|---|---|---|---|---|"]
        for u in rows:
            name = f"{u['state']} {u['county']}" + (f" ({u['source_id']})" if u.get("source_id") else "")
            rule = {None: "n/a", True: "yes", False: "no"}[u.get("rule_verified")]
            out.append(f"| {name} | {u['ledger']} | {u['status']} | {u['source_accessible']} | "
                       f"{'yes' if u['approved_for_customers'] else 'no'} | {rule} | {'yes' if u['process_verified'] else 'no'} | "
                       f"{u['next_action']} |")
        out.append("")
    return "\n".join(out)
