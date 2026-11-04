"""State-by-state coverage, generated from the repository's own records
(2026-10-11). One document, data/current_state/state-coverage.json, that
answers for every production state, each of its three ledgers and each of
their sources: what is legally applicable and verified, which official
sources are known, approved, implemented and have run, how fresh they are,
what the records carry, how much of the inventory has a verified
acquisition path, and what the next concrete action is.

Inputs (all version-controlled; nothing here reaches a network or a database):
  data/state_ledgers.csv                 ledger eligibility + tracking per state (harvesters/governance/state_rules)
  data/state_rules.csv                   the rules registry (statuses per ledger)
  data/county_source_registry.csv        every source: harvester, approval, publication, restrictions, evidence
  data/current_state/coverage-*.json     counts-only read-only snapshot per state x ledger (scripts/sql/current_state_coverage.sql)
  data/current_state/source-quality-*.json  counts-only snapshot per county x ledger (field population; scripts/sql/source_quality_matrix.sql)
  public/acquisition-evidence.json       the acquisition-path status per (state, source, county) unit

Every state x ledger is classified into exactly ONE of these concepts, in
this order of precedence - and a ledger whose eligibility or rules are not
verified is never reported as a verified zero:
  PRODUCT_NOT_OFFERED              authoritative evidence says the state has no such product
  RULES_NOT_VERIFIED               eligibility NOT_VERIFIED and nothing implemented: no claim either way
  APPROVAL_UNRESOLVED              sources exist but none is approved for customer publication (review pending)
  SOURCE_RESTRICTED                the only relevant source cannot be used under the approved access rules
  OFFERED_SOURCE_NOT_IMPLEMENTED   the product is established but no production source feeds it
  SOURCE_IMPLEMENTED_NEVER_READ    a production source exists and no row has ever been read from it
  SOURCE_FAILED_OR_STALE           rows exist but none was read within the freshness window at the snapshot (or ever stamped)
  RECORDS_WITHHELD_NO_PATH         rows exist but no unit of the ledger has a VERIFIED acquisition path (AVAILABLE)
  OFFERED_VERIFIED_EMPTY           the product is established, a source was read successfully and lists nothing
  CURRENT                          rows were read within the window from approved sources
Counts always carry their denominators; the snapshot's own date is named.
"""
from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path

from harvesters.governance import state_rules as SR
from harvesters.governance import states

REPO = Path(__file__).resolve().parents[2]
REGISTRY = REPO / "data" / "county_source_registry.csv"
CURRENT = REPO / "data" / "current_state"
ACQ = REPO / "public" / "acquisition-evidence.json"

LEDGERS = ("AUCTIONS", "AVAILABLE", "LIENS_CERTIFICATES")
LEDGER_SOURCE = {"AUCTIONS": "auction", "AVAILABLE": "laft", "LIENS_CERTIFICATES": "certificate"}
CONCEPTS = ("PRODUCT_NOT_OFFERED", "RULES_NOT_VERIFIED", "APPROVAL_UNRESOLVED", "SOURCE_RESTRICTED",
            "OFFERED_SOURCE_NOT_IMPLEMENTED", "SOURCE_IMPLEMENTED_NEVER_READ", "SOURCE_FAILED_OR_STALE",
            "RECORDS_WITHHELD_NO_PATH", "OFFERED_VERIFIED_EMPTY", "CURRENT")
APPROVED = ("APPROVED", "APPROVED_GRANDFATHERED")
STALE_HOURS = 36
# Sources read only by a manual workflow dispatch (scripts/unit_freshness.MANUAL_ONLY_SOURCES
# pins the same set): their rows are never aged by the clock, so a stale read
# there names the last manual dispatch, not a scheduled failure.
MANUAL_ONLY_SOURCES = ("tx_lgbs", "tx_realauction")
NEXT_ACTION = {
    "PRODUCT_NOT_OFFERED": "Nothing to harvest; keep the eligibility evidence current.",
    "RULES_NOT_VERIFIED": "Read the state's statute / an official county procedure and record it in data/state_rules.csv before any source is built.",
    "APPROVAL_UNRESOLVED": "An administrator records a publication review for the source (data/available_publication_reviews.csv / admin panel); until then rows stay admin-only.",
    "SOURCE_RESTRICTED": "Resolve the recorded access restriction with the source's owner; nothing is read until a review records permission.",
    "OFFERED_SOURCE_NOT_IMPLEMENTED": "Locate the official list for this ledger (job=evidence capture), register it, then build the adapter.",
    "SOURCE_IMPLEMENTED_NEVER_READ": "Dispatch the source's job once (owner decision) and read its status file; a failure is a source problem, not an empty list.",
    "SOURCE_FAILED_OR_STALE": "Investigate the last read's error category (registry last_error_category / unit freshness) and restore the read; rows are kept, never closed, until a COMPLETE read.",
    "RECORDS_WITHHELD_NO_PATH": "Capture the county's official acquisition process (job=evidence, acquisition_candidates) and record a verified evidence row; rows stay admin-only.",
    "OFFERED_VERIFIED_EMPTY": "Nothing to publish; the next scheduled read re-checks the list.",
    "CURRENT": "Keep reading; raise field population where a verified official layer exists (see fields).",
}


def _read_csv(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _latest(prefix: str) -> Path | None:
    files = sorted(CURRENT.glob(f"{prefix}-*.json"))
    return files[-1] if files else None


def load_inputs(registry: Path = REGISTRY, current: Path = CURRENT, acq: Path = ACQ) -> dict:
    cov_path = _latest("coverage") if current == CURRENT else sorted(current.glob("coverage-*.json"))[-1]
    qual_path = _latest("source-quality") if current == CURRENT else sorted(current.glob("source-quality-*.json"))[-1]
    cov = json.loads(cov_path.read_text(encoding="utf-8")) if cov_path else {"rows": [], "measured_at": None}
    qual = json.loads(qual_path.read_text(encoding="utf-8")) if qual_path else {"rows": [], "measured_at": None}
    acqd = json.loads(acq.read_text(encoding="utf-8")) if acq.is_file() else {"status": [], "records": []}
    return {"registry": _read_csv(registry), "rules": SR.load_rules(), "ledgers": SR.load_ledgers(),
            "coverage": cov, "quality": qual, "acquisition": acqd,
            "snapshot_files": {"coverage": cov_path.name if cov_path else None, "quality": qual_path.name if qual_path else None}}


def _sources_for(registry: list[dict], st: str, ledger: str) -> list[dict]:
    out = []
    for r in registry:
        if r["state"] != st or ledger not in (r.get("ledgers") or "").split("|"):
            continue
        out.append({
            "county": r["county"], "source_id": r["source_id"], "harvester": r.get("harvester") or "",
            "implemented": bool((r.get("harvester") or "").strip()) and r.get("verification_status") == "PRODUCTION_VERIFIED",
            "verification_status": r.get("verification_status") or "", "governance_status": r.get("governance_status") or "",
            "publication_status": r.get("publication_status") or "", "approved_for_customers": (r.get("publication_status") or "") in APPROVED,
            "restrictions": r.get("restrictions") or "", "canonical_url": r.get("canonical_url") or "",
            "has_evidence": bool((r.get("evidence_ref") or "").strip()), "last_checked": r.get("last_checked") or "",
            "update_frequency": r.get("update_frequency") or "", "publishing_unit_name": r.get("publishing_unit_name") or "",
            "amount_kind": r.get("amount_kind") or "",
        })
    return sorted(out, key=lambda x: (x["county"], x["source_id"]))


def _snapshot(cov: dict, st: str, source: str) -> dict | None:
    for r in cov.get("rows", []):
        if r.get("state") == st and r.get("source") == source:
            return r
    return None


def _fields(qual: dict, st: str, source: str) -> tuple[dict, list[dict]]:
    """Field population summed over the ledger's county rows: {field: {n, N}}
    plus the per-county rows (counts only, as the snapshot carries them)."""
    rows = [r for r in qual.get("rows", []) if r.get("state") == st and r.get("ledger") == source]
    skip = {"state", "county", "ledger", "active", "total", "last_seen_max", "baseline_commit"}
    agg: dict[str, dict] = {}
    denom = sum(int(r.get("active") or 0) for r in rows)
    for r in rows:
        for k, v in r.items():
            if k in skip or not isinstance(v, (int, float)) or isinstance(v, bool):
                continue
            agg.setdefault(k, {"n": 0, "N": denom})
            agg[k]["n"] += int(v)
    counties = [{"county": r.get("county"), "active": int(r.get("active") or 0),
                 "fields": {k: int(v) for k, v in r.items() if k not in skip and isinstance(v, (int, float)) and not isinstance(v, bool)}}
                for r in sorted(rows, key=lambda x: str(x.get("county")))]
    return dict(sorted(agg.items())), counties


def _acquisition(acqd: dict, st: str, source_ids: set[str]) -> dict:
    units = [u for u in acqd.get("status", []) if u.get("state") == st and u.get("source_id") in source_ids]
    by = defaultdict(int)
    for u in units:
        by[u.get("status") or "UNKNOWN"] += 1
    return {"units": len(units), "by_status": dict(sorted(by.items())),
            "verified_units": [f"{u['county']} ({u['source_id']})" for u in units if u.get("status") == "VERIFIED"]}


def _rules(rules: list, st: str, ledger: str) -> dict:
    mine = [r for r in rules if r.state == st and ledger in r.ledgers]
    by = defaultdict(int)
    for r in mine:
        by[r.status] += 1
    return {"count": len(mine), "by_status": dict(sorted(by.items())),
            "verified_law": sorted(r.topic for r in mine if r.kind == "LAW" and r.status == "VERIFIED"),
            "unresolved": sorted(f"{r.county + ': ' if r.county else ''}{r.topic}" for r in mine if r.status != "VERIFIED"),
            "county_rules": sorted({r.county for r in mine if r.county})}


def _in_snapshot(sources: list[dict], measured_at) -> list[dict]:
    """The sources that can have rows in a snapshot taken at `measured_at`:
    a source first checked after it (registry last_checked) was added later
    and contributes nothing to the snapshot's counts."""
    day = str(measured_at or "")[:10]
    if not day:
        return sources
    return [s for s in sources if not s.get("last_checked") or s["last_checked"] <= day]


def classify(*, eligibility: str, sources: list[dict], snap: dict | None, acq: dict, ledger: str,
             measured_at=None) -> tuple[str, list[str]]:
    reasons: list[str] = []
    implemented = [s for s in sources if s["implemented"]]
    approved = [s for s in implemented if s["approved_for_customers"]]
    restricted = [s for s in sources if s["restrictions"].upper().startswith(("LEGAL_REVIEW_REQUIRED", "SOURCE_RESTRICTED", "BLOCKED"))]
    if eligibility == "NOT_OFFERED":
        return "PRODUCT_NOT_OFFERED", ["eligibility NOT_OFFERED (authoritative evidence recorded)"]
    if not implemented:
        if eligibility == "NOT_VERIFIED":
            return "RULES_NOT_VERIFIED", ["eligibility NOT_VERIFIED; no production source"]
        if restricted and not sources:
            return "SOURCE_RESTRICTED", [f"{len(restricted)} restricted source(s), none usable"]
        if eligibility == "SOURCE_RESTRICTED":
            return "SOURCE_RESTRICTED", ["eligibility SOURCE_RESTRICTED"]
        return "OFFERED_SOURCE_NOT_IMPLEMENTED", [f"eligibility {eligibility}; {len(sources)} known source(s), none in production"]
    if not approved:
        return "APPROVAL_UNRESOLVED", [f"{len(implemented)} production source(s), none APPROVED for customers: " + ", ".join(sorted({s['publication_status'] or 'UNREVIEWED' for s in implemented}))]
    total = int((snap or {}).get("total") or 0)
    active = int((snap or {}).get("active") or 0)
    never = int((snap or {}).get("act_never_seen") or 0)
    stale = int((snap or {}).get("act_seen_gt36h") or 0)
    last_seen = (snap or {}).get("last_seen_max")
    if snap is None or (total == 0 and not last_seen):
        return "SOURCE_IMPLEMENTED_NEVER_READ", ["no row and no read recorded in the snapshot"]
    if active and (never + stale) >= active:
        reasons.append(f"{never} of {active} active rows never stamped, {stale} read more than {STALE_HOURS} h before the snapshot")
        seen = _in_snapshot(implemented, measured_at)
        if seen and all(s["source_id"] in MANUAL_ONLY_SOURCES for s in seen):
            reasons.append("every production source is manual-only (dispatched by hand, never scheduled): the last read is the last manual dispatch")
        return "SOURCE_FAILED_OR_STALE", reasons
    if ledger == "AVAILABLE" and active and acq["units"] and not acq["by_status"].get("VERIFIED"):
        return "RECORDS_WITHHELD_NO_PATH", [f"{acq['units']} acquisition unit(s), none VERIFIED: " + ", ".join(f"{k} {v}" for k, v in acq["by_status"].items())]
    if active == 0:
        if eligibility in ("OFFERED", "COUNTY_DEPENDENT") and last_seen:
            return "OFFERED_VERIFIED_EMPTY", [f"0 active rows; last read {last_seen}"]
        return "RULES_NOT_VERIFIED", [f"0 active rows and eligibility {eligibility}: not a verified zero"]
    return "CURRENT", [f"{active} active rows; {never} never stamped, {stale} older than {STALE_HOURS} h at the snapshot"]


def build(inputs: dict | None = None) -> dict:
    inp = inputs or load_inputs()
    registry, rules, ledgers = inp["registry"], inp["rules"], inp["ledgers"]
    cov, qual, acqd = inp["coverage"], inp["quality"], inp["acquisition"]
    out_states = {}
    totals = defaultdict(int)
    for st in sorted(states.PRODUCTION_STATES):
        support = SR.ledger_support(st, ledgers)
        st_out = {"ledgers": {}}
        for ledger in LEDGERS:
            decl = support.get(ledger)
            elig = decl.eligibility if decl else "NOT_VERIFIED"
            sources = _sources_for(registry, st, ledger)
            source_key = LEDGER_SOURCE[ledger]
            snap = _snapshot(cov, st, source_key)
            fields, counties = _fields(qual, st, source_key)
            acq = _acquisition(acqd, st, {s["source_id"] for s in sources})
            concept, reasons = classify(eligibility=elig, sources=sources, snap=snap, acq=acq, ledger=ledger,
                                        measured_at=cov.get("measured_at"))
            totals[concept] += 1
            pub_statuses = sorted({s["publication_status"] or "UNREVIEWED" for s in sources if s["implemented"]})
            withheld = None
            if snap is not None:
                if pub_statuses and all(p in APPROVED for p in pub_statuses):
                    withheld = {"source_not_approved": 0, "basis": "every production source of the ledger is customer-approved"}
                elif pub_statuses and not any(p in APPROVED for p in pub_statuses):
                    withheld = {"source_not_approved": int(snap.get("active") or 0), "basis": "no production source of the ledger is customer-approved"}
                else:
                    withheld = {"source_not_approved": None, "basis": "the ledger mixes approved and unreviewed sources; the snapshot does not split rows by source"}
            st_out["ledgers"][ledger] = {
                "eligibility": elig, "eligibility_basis": (decl.eligibility_basis if decl else ""),
                "eligibility_verified_on": (decl.eligibility_verified_on if decl else ""),
                "tracked": (decl.status if decl else "NOT_VERIFIED"),
                "rules": _rules(rules, st, ledger),
                "sources": {"known": len(sources), "implemented": sum(1 for s in sources if s["implemented"]),
                            "approved_for_customers": sum(1 for s in sources if s["implemented"] and s["approved_for_customers"]),
                            "restricted": sum(1 for s in sources if s["restrictions"]),
                            "with_evidence": sum(1 for s in sources if s["has_evidence"]),
                            "counties": sorted({s["county"] for s in sources if s["implemented"]}),
                            "rows": sources},
                "records": ({k: snap.get(k) for k in ("total", "active", "act_parcel", "act_coords", "act_assessed", "act_landuse",
                                                       "act_flood", "act_url", "act_never_seen", "act_seen_gt36h", "act_past_sale",
                                                       "act_prov", "last_seen_max") if k in snap} if snap else None),
                "fields": fields, "counties": counties,
                "acquisition": acq,
                "withheld": withheld,
                "classification": concept, "classification_reasons": reasons,
                "next_action": NEXT_ACTION[concept],
            }
        out_states[st] = st_out
    return {"generated_from": {"registry": "data/county_source_registry.csv", "rules": "data/state_rules.csv",
                               "ledgers": "data/state_ledgers.csv", "acquisition": "public/acquisition-evidence.json",
                               "coverage_snapshot": inp["snapshot_files"]["coverage"], "coverage_measured_at": cov.get("measured_at"),
                               "quality_snapshot": inp["snapshot_files"]["quality"], "quality_measured_at": qual.get("measured_at"),
                               "note": "counts only; a snapshot's own date bounds every freshness statement; no row value"},
            "concepts": list(CONCEPTS), "stale_hours": STALE_HOURS,
            "summary": dict(sorted(totals.items())), "states": out_states}


def render_markdown(doc: dict) -> str:
    g = doc["generated_from"]
    lines = ["# State-by-state coverage (generated)", "",
             f"Built by `scripts/build_state_coverage.py` from the registry, the rules, the ledger table, the acquisition "
             f"evidence and the counts-only snapshots `{g['coverage_snapshot']}` (measured {g['coverage_measured_at']}) and "
             f"`{g['quality_snapshot']}` (measured {g['quality_measured_at']}). Every count carries its denominator; nothing "
             "here is read live. Classification precedence and meanings: `harvesters/governance/state_coverage.py`.", "",
             "| Classification | State x ledger |", "|---|---|"]
    for k, v in doc["summary"].items():
        lines.append(f"| {k} | {v} |")
    for st, sd in doc["states"].items():
        lines += ["", f"## {st}", "", "| Ledger | Eligibility | Classification | Sources known / implemented / approved | Active rows | Never stamped | Older than 36 h | Acquisition units VERIFIED | Next action |",
                  "|---|---|---|---|---|---|---|---|---|"]
        for ledger, L in sd["ledgers"].items():
            rec = L["records"] or {}
            s = L["sources"]
            acq = L["acquisition"]
            lines.append(f"| {ledger} | {L['eligibility']} | {L['classification']} | {s['known']} / {s['implemented']} / {s['approved_for_customers']} | "
                         f"{rec.get('active', '-')} | {rec.get('act_never_seen', '-')} | {rec.get('act_seen_gt36h', '-')} | "
                         f"{acq['by_status'].get('VERIFIED', 0)} of {acq['units']} | {L['next_action']} |")
        for ledger, L in sd["ledgers"].items():
            if L["fields"]:
                lines += ["", f"{st} - {ledger} field population (active rows, snapshot): " +
                          "; ".join(f"{k} {v['n']}/{v['N']}" for k, v in L["fields"].items())]
            if L["classification_reasons"]:
                lines.append(f"{st} - {ledger}: " + "; ".join(L["classification_reasons"]))
    lines.append("")
    return "\n".join(lines)
