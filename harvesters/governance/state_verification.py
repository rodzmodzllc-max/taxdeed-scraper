"""State verification engine (2026-10-10).

Compares, for every production state, the recorded state rules and ledger
support (``state_rules.py``) and the source registry with what the code and
the customer-facing files actually do. Every check returns one status:

  PASS            a verified requirement is implemented and agrees
  FAIL            the implementation contradicts the record or an invariant
  BLOCKED         a dependency (evidence, permission, network) prevents a decision
  NOT_APPLICABLE  the requirement does not apply to this state's tracked products
  NOT_VERIFIED    the evidence is insufficient to make the claim

A missing record is a FAIL, never a silent pass. There is no score: the output
is the list of findings (``run()``), written by scripts/verify_states.py to
data/state_verification.json and pinned by a test.

Nothing here reaches the network or a database; every input is a repository
file.
"""
from __future__ import annotations

import csv
import json
import re
from collections import defaultdict
from pathlib import Path

from . import states
from . import state_rules as SR

REPO = Path(__file__).resolve().parents[2]
REGISTRY = REPO / "data" / "county_source_registry.csv"
APP_JS = REPO / "public" / "app.js"
STATUSES = ("PASS", "FAIL", "BLOCKED", "NOT_APPLICABLE", "NOT_VERIFIED")
# registry ledger name -> app.js ledger key
APP_LEDGER = {"AUCTIONS": "auction", "AVAILABLE": "laft", "LIENS_CERTIFICATES": "certificate"}
RECORD_SOURCE_LEDGER = {"auction": "AUCTIONS", "laft": "AVAILABLE", "certificate": "LIENS_CERTIFICATES"}
_NOT_TRACKED_COPY = re.compile(r"^No .* source is tracked\.$")


def _finding(state, check, status, detail, subject=""):
    assert status in STATUSES, status
    out = {"state": state, "check": check, "status": status, "detail": detail}
    if subject:
        out["subject"] = subject
    return out


def production_sources(path: Path = REGISTRY) -> dict[str, dict[str, dict]]:
    """state -> source_id -> {ledgers:set, publication:set, counties:set, urls:set}."""
    out: dict[str, dict[str, dict]] = defaultdict(dict)
    with open(path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if r["state"] not in states.PRODUCTION_STATES or r["verification_status"] != "PRODUCTION_VERIFIED":
                continue
            s = out[r["state"]].setdefault(r["source_id"], {"ledgers": set(), "publication": set(), "counties": set(),
                                                            "urls": set()})
            s["ledgers"].update(x for x in (r.get("ledgers") or "").split("|") if x)
            s["publication"].add(r.get("publication_status") or "")
            s["counties"].add(r["county"])
            s["urls"].update(u for u in (r.get("canonical_url"), r.get("document_url"), r.get("purchase_url")) if u)
    return out


def app_ledger_copy(path: Path = APP_JS) -> dict:
    """EXPANSION_LEDGER_COPY from app.js (a JSON-shaped literal)."""
    s = path.read_text(encoding="utf-8")
    marker = "const EXPANSION_LEDGER_COPY = "
    i = s.index(marker) + len(marker)
    depth = 0
    for j in range(i, len(s)):
        if s[j] == "{":
            depth += 1
        elif s[j] == "}":
            depth -= 1
            if depth == 0:
                return json.loads(s[i:j + 1])
    raise ValueError("EXPANSION_LEDGER_COPY not closed")


_CITATION = re.compile(r"(?:§\s*|F\.S\.\s*|Tax Code\s*§?\s*|Code\s*§\s*|Stat\.\s*)(\d+[\.-]\d+(?:[\.-]\d+)?)")
_STRING = re.compile(r'(?:sub|how|empty|question)\s*:\s*"((?:[^"\\]|\\.)*)"')


def copy_law_claims(path: Path = APP_JS, rules=None) -> list[dict]:
    """Every customer ledger string (the LEDGERS block of app.js, including the
    per-state copy) that cites a statute: PASS when a VERIFIED LAW rule
    carries that citation, PASS when the string itself says the claim is not
    verified, otherwise FAIL - an unverified legal rule shown as a fact."""
    rules = SR.load_rules() if rules is None else rules
    verified = {m for r in rules if r.kind == "LAW" and r.status == "VERIFIED" for m in re.findall(r"\d+[\.-]\d+", r.citation)}
    src = path.read_text(encoding="utf-8")
    start = src.index("const LEDGERS = {")
    end = src.index("for (const [ledgerKey, byState] of Object.entries(EXPANSION_LEDGER_COPY))")
    out = []
    for m in _STRING.finditer(src[start:end]):
        text = m.group(1)
        cites = _CITATION.findall(text)
        if not cites:
            continue
        ok_verified = all(c in verified for c in cites)
        disclosed = "not verified" in text.lower()
        status = "PASS" if ok_verified or disclosed else "FAIL"
        detail = ("cites verified law " if ok_verified else "discloses the claim is not verified: " if disclosed
                  else "cites a statute no verified LAW rule records: ") + ", ".join(cites)
        out.append(_finding("*", "copy_law_claims", status, detail, text[:80]))
    return out


def recorded_urls() -> set[str]:
    """Every URL the repository itself records as read (registry rows and the
    verified evidence tables)."""
    urls = set()
    with open(REGISTRY, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            urls.update(u for u in (r.get("canonical_url"), r.get("document_url"), r.get("purchase_url")) if u)
    for name in ("purchase_path_evidence.csv", "purchase_path_evidence_expansion.csv"):
        with open(REPO / "data" / name, newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                urls.update(u for u in (r.get("evidence_url"), r.get("url"), r.get("application_url")) if u)
    return urls


def _terms_sources() -> set[str]:
    with open(REPO / "data" / "available_financial_terms.csv", newline="", encoding="utf-8") as fh:
        return {r["source_id"] for r in csv.DictReader(fh)}


def _acquisition_units() -> list[dict]:
    return json.loads((REPO / "public" / "acquisition-evidence.json").read_text(encoding="utf-8")).get("status", [])


def _paid_beta() -> set[str]:
    return set(json.loads((REPO / "public" / "commercial-scope.json").read_text(encoding="utf-8"))["paid_beta_source_ids"])


def _state_page(st: str) -> Path:
    return REPO / "public" / ("index.html" if st == "FL" else f"{st.lower()}.html")


def verify_state(st: str, *, rules, ledgers, sources, copy, urls, terms, units, paid_beta, rules_json) -> list[dict]:
    f = []
    my_rules = [r for r in rules if r.state == st]
    problems = [p for r in my_rules for p in SR.rule_problems(r)]
    f.append(_finding(st, "rules_valid", "FAIL" if problems else ("PASS" if my_rules else "FAIL"),
                      "; ".join(problems) if problems else (f"{len(my_rules)} rule(s) recorded" if my_rules
                                                            else "no rule recorded for this state")))
    laws = [r for r in my_rules if r.kind == "LAW" and r.status == "VERIFIED"]
    unresolved = sorted({r.topic for r in my_rules if r.status != "VERIFIED"})
    f.append(_finding(st, "state_law_recorded", "PASS" if laws else "NOT_VERIFIED",
                      (f"{len(laws)} statute provision(s) read and recorded" if laws else
                       "no statute has been read and recorded for this state")
                      + (f"; unresolved: {', '.join(unresolved)}" if unresolved else "")))
    # Ledgers: declared, and declared support matches the production sources.
    support = SR.ledger_support(st, ledgers)
    srcs = sources.get(st, {})
    for ledger in SR.LEDGERS:
        decl = support.get(ledger)
        have = sorted(sid for sid, s in srcs.items() if ledger in s["ledgers"])
        if decl is None:
            f.append(_finding(st, "ledger_declared", "FAIL", "no ledger support recorded", ledger))
            continue
        if decl.status == "TRACKED" and not have:
            f.append(_finding(st, "ledger_tracking", "FAIL", "recorded as TRACKED but no production source feeds it", ledger))
        elif decl.status != "TRACKED" and have:
            f.append(_finding(st, "ledger_tracking", "FAIL",
                              f"recorded as {decl.status} but production source(s) feed it: {', '.join(have)}", ledger))
        else:
            f.append(_finding(st, "ledger_tracking", "PASS",
                              f"{decl.status}" + (f": {', '.join(have)}" if have else ""), ledger))
        # Customer copy (generated state pages): never "no source is tracked"
        # for a ledger that is fed, never a source description for one that is not.
        block = copy.get(APP_LEDGER[ledger], {}).get(st)
        if block is not None:
            says_none = bool(_NOT_TRACKED_COPY.match(block.get("sub", "")))
            if decl.status == "TRACKED" and says_none:
                f.append(_finding(st, "ledger_copy", "FAIL", f"customer copy says no source is tracked: {block['sub']!r}", ledger))
            elif decl.status != "TRACKED" and not says_none:
                f.append(_finding(st, "ledger_copy", "FAIL", "customer copy describes a source for an untracked ledger", ledger))
            else:
                f.append(_finding(st, "ledger_copy", "PASS", "customer copy agrees with tracking", ledger))
    # Source classification: registry ledgers == the ledger domain map.
    from harvesters.ledgers import SOURCE_LEDGERS  # noqa: PLC0415
    for sid, s in sorted(srcs.items()):
        dom = {l.value for l in SOURCE_LEDGERS.get(sid, set())}
        if not dom:
            f.append(_finding(st, "source_classification", "FAIL", "source has no ledger in harvesters.ledgers", sid))
        elif dom != s["ledgers"]:
            f.append(_finding(st, "source_classification", "FAIL",
                              f"registry ledgers {sorted(s['ledgers'])} != ledger map {sorted(dom)}", sid))
        else:
            f.append(_finding(st, "source_classification", "PASS", "/".join(sorted(dom)), sid))
        # Publication gate: an unreviewed source is never in the paid-beta scope.
        if s["publication"] & {"UNREVIEWED", "RESTRICTED", "BLOCKED"} and sid in paid_beta:
            f.append(_finding(st, "publication_gate", "FAIL", "source awaiting review is in the paid-beta scope", sid))
    # AVAILABLE: financial terms and acquisition evidence.
    avail = [sid for sid, s in srcs.items() if "AVAILABLE" in s["ledgers"]]
    if not avail:
        f.append(_finding(st, "available_terms", "NOT_APPLICABLE", "no AVAILABLE source tracked"))
        f.append(_finding(st, "acquisition_path", "NOT_APPLICABLE", "no AVAILABLE source tracked"))
    else:
        missing = sorted(sid for sid in avail if sid not in terms)
        f.append(_finding(st, "available_terms", "FAIL" if missing else "PASS",
                          f"no financial-terms row for {', '.join(missing)}" if missing else
                          f"every AVAILABLE source has a terms row ({len(avail)})"))
        mine = [u for u in units if u["state"] == st and u["source_id"] in avail]
        ver = sum(1 for u in mine if u["status"] == "VERIFIED")
        status = "PASS" if mine and ver == len(mine) else "NOT_VERIFIED"
        f.append(_finding(st, "acquisition_path", status,
                          f"{ver}/{len(mine)} AVAILABLE unit(s) with a verified official process"
                          + ("" if status == "PASS" else " - the rest show 'Not yet verified' / 'No online purchase link on file'")))
    # Customer page and data file.
    f.append(_finding(st, "state_page", "PASS" if _state_page(st).is_file() else "FAIL", _state_page(st).name))
    entry = (rules_json or {}).get("states", {}).get(st)
    f.append(_finding(st, "customer_rules", "PASS" if entry and entry.get("rules") is not None else "FAIL",
                      "rules page data present (public/state-rules.json)" if entry else "state missing from public/state-rules.json"))
    # Links: a rule's link is either recorded as read in this repository, or
    # shown as an official pointer that was not opened from this environment.
    unopened = sorted({r.source_url for r in my_rules if r.source_url and r.source_url not in urls and r.status != "VERIFIED"})
    if unopened:
        f.append(_finding(st, "rule_links", "NOT_VERIFIED",
                          f"{len(unopened)} official link(s) for unresolved rules were not opened from this environment"))
    else:
        f.append(_finding(st, "rule_links", "PASS", "every link is a recorded source or a verified rule's source"))
    return f


def run(rules_json: dict | None = None) -> dict:
    rules, ledgers = SR.load_rules(), SR.load_ledgers()
    if rules_json is None:
        p = REPO / "public" / "state-rules.json"
        rules_json = json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None
    ctx = dict(rules=rules, ledgers=ledgers, sources=production_sources(), copy=app_ledger_copy(),
               urls=recorded_urls(), terms=_terms_sources(), units=_acquisition_units(), paid_beta=_paid_beta(),
               rules_json=rules_json)
    findings = [x for st in sorted(states.PRODUCTION_STATES) for x in verify_state(st, **ctx)]
    findings += copy_law_claims(rules=rules)
    stray = sorted({r.state for r in rules} - set(states.PRODUCTION_STATES))
    for st in stray:
        findings.append(_finding(st, "rules_state", "FAIL", "rules recorded for a state that is not in production"))
    summary = {s: sum(1 for x in findings if x["status"] == s) for s in STATUSES}
    by_state = defaultdict(lambda: {s: 0 for s in STATUSES})
    for x in findings:
        by_state[x["state"]][x["status"]] += 1
    return {"summary": summary, "by_state": dict(sorted(by_state.items())), "findings": findings}
