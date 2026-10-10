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
    """state -> source_id -> {ledgers:set, publication:set, counties:set, urls:set, authority:set}."""
    out: dict[str, dict[str, dict]] = defaultdict(dict)
    with open(path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if r["state"] not in states.PRODUCTION_STATES or r["verification_status"] != "PRODUCTION_VERIFIED":
                continue
            s = out[r["state"]].setdefault(r["source_id"], {"ledgers": set(), "publication": set(), "counties": set(),
                                                            "urls": set(), "authority": set()})
            s["ledgers"].update(x for x in (r.get("ledgers") or "").split("|") if x)
            s["publication"].add(r.get("publication_status") or "")
            s["counties"].add(r["county"])
            s["authority"].add(r.get("source_authority") or "")
            s["urls"].update(u for u in (r.get("canonical_url"), r.get("document_url"), r.get("purchase_url")) if u)
    return out


def restricted_sources(path: Path = REGISTRY) -> dict[str, dict[str, dict]]:
    """state -> source_id -> {ledgers:set, publication:set} for every registry
    row whose publication is RESTRICTED or BLOCKED (any verification status)."""
    out: dict[str, dict[str, dict]] = defaultdict(dict)
    with open(path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if r["state"] not in states.PRODUCTION_STATES or (r.get("publication_status") or "") not in ("RESTRICTED", "BLOCKED"):
                continue
            s = out[r["state"]].setdefault(r["source_id"] or f"(unnamed {r['county']})", {"ledgers": set(), "publication": set()})
            s["ledgers"].update(x for x in (r.get("ledgers") or "").split("|") if x)
            s["publication"].add(r.get("publication_status") or "")
    return out


def county_coverage(st: str, ledger: str, sources: dict[str, dict[str, dict]] | None = None, path: Path = REGISTRY,
                    rules=None) -> list[dict]:
    """The counties a ledger's production sources feed in one state, each with
    its sources and their publication status - what COUNTY_DEPENDENT means in
    practice - plus the counties whose procedure for that ledger was verified
    (a county can be established by its own pages without an inventory
    source). Read from the registry and the rules, never from inventory."""
    rows: dict[str, dict] = {}
    for r in (rules or []):
        if r.state == st and r.county and r.status == "VERIFIED" and r.kind in ("PROCEDURE", "SOURCE") and ledger in r.ledgers:
            c = rows.setdefault(r.county, {"county": r.county, "sources": []})
            c.setdefault("procedures", []).append(r.topic)
    with open(path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if r["state"] != st or r["verification_status"] != "PRODUCTION_VERIFIED":
                continue
            if ledger not in (r.get("ledgers") or "").split("|"):
                continue
            c = rows.setdefault(r["county"], {"county": r["county"], "sources": []})
            c["sources"].append({"source_id": r["source_id"], "publication": r.get("publication_status") or "",
                                 "authority": r.get("source_authority") or ""})
    for c in rows.values():
        c["sources"].sort(key=lambda x: x["source_id"])
    return [rows[k] for k in sorted(rows)]


ZERO_CASES = ("NOT_OFFERED", "NO_CURRENT_INVENTORY", "COUNTY_DEPENDENT", "NOT_VERIFIED", "NOT_IMPLEMENTED",
              "SOURCE_RESTRICTED", "SOURCE_FAILURE", "WITHHELD")


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


def _ledger_rules(my_rules, ledger):
    return [r for r in my_rules if ledger in r.ledgers]


def eligibility_findings(st: str, decl: SR.LedgerSupport, ledger: str, *, my_rules, srcs, restricted) -> list[dict]:
    """The eligibility classification must be supported by the record it
    claims: a statute read (OFFERED / NOT_OFFERED), a county source or
    procedure read (COUNTY_DEPENDENT), a restricted source and nothing
    approved (SOURCE_RESTRICTED), or neither (NOT_VERIFIED)."""
    f = []
    problems = SR.ledger_problems(decl)
    if problems:
        return [_finding(st, "ledger_eligibility", "FAIL", "; ".join(problems), ledger)]
    laws = [r for r in _ledger_rules(my_rules, ledger) if r.kind == "LAW" and r.status == "VERIFIED"]
    procs = [r for r in _ledger_rules(my_rules, ledger) if r.kind in ("PROCEDURE", "SOURCE") and r.status == "VERIFIED"]
    have = sorted(sid for sid, x in srcs.items() if ledger in x["ledgers"])
    approved = [sid for sid in have if srcs[sid]["publication"] & {"APPROVED", "APPROVED_GRANDFATHERED"}]
    gov = [sid for sid in have if "GOVERNMENT_DIRECT" in srcs[sid]["authority"] or "GOVERNMENT_PLATFORM" in srcs[sid]["authority"]]
    restricted_here = sorted(sid for sid, x in restricted.items() if ledger in x["ledgers"])
    e = decl.eligibility
    if e in ("OFFERED", "NOT_OFFERED"):
        if not laws:
            f.append(_finding(st, "ledger_eligibility", "FAIL", f"{e} needs a VERIFIED LAW rule for this ledger; none recorded", ledger))
        else:
            f.append(_finding(st, "ledger_eligibility", "PASS", f"{e}: {', '.join(r.citation for r in laws)} read {decl.eligibility_verified_on}", ledger))
    elif e == "COUNTY_DEPENDENT":
        county_procs = [r for r in procs if r.county]
        if not have and not county_procs:
            f.append(_finding(st, "ledger_eligibility", "FAIL", "COUNTY_DEPENDENT needs a production source feeding this ledger or a verified county procedure for it", ledger))
        elif not have:
            f.append(_finding(st, "ledger_eligibility", "PASS", "COUNTY_DEPENDENT by verified procedure in " + ", ".join(sorted({r.county for r in county_procs}))
                              + " - no inventory source feeds this ledger", ledger))
        elif not (gov or procs or decl.eligibility_source_url in _evidence_urls()):
            f.append(_finding(st, "ledger_eligibility", "FAIL", "COUNTY_DEPENDENT needs a government publication read (a government source, a verified procedure or a verified evidence page); only vendor listings feed this ledger", ledger))
        else:
            f.append(_finding(st, "ledger_eligibility", "PASS", f"COUNTY_DEPENDENT: {len(have)} source(s) ({', '.join(have)}) read {decl.eligibility_verified_on}", ledger))
    elif e == "SOURCE_RESTRICTED":
        if approved:
            f.append(_finding(st, "ledger_eligibility", "FAIL", f"SOURCE_RESTRICTED but approved source(s) feed this ledger: {', '.join(approved)}", ledger))
        elif not restricted_here:
            f.append(_finding(st, "ledger_eligibility", "FAIL", "SOURCE_RESTRICTED needs a RESTRICTED / BLOCKED registry source for this ledger", ledger))
        else:
            f.append(_finding(st, "ledger_eligibility", "BLOCKED", f"the only relevant source(s) are restricted: {', '.join(restricted_here)}", ledger))
    else:  # NOT_VERIFIED
        if laws:
            f.append(_finding(st, "ledger_eligibility", "FAIL", f"recorded NOT_VERIFIED although a VERIFIED LAW rule covers this ledger: {laws[0].citation}", ledger))
        elif gov and procs:
            f.append(_finding(st, "ledger_eligibility", "FAIL", "recorded NOT_VERIFIED although a government source is read and a procedure is verified - COUNTY_DEPENDENT is supported", ledger))
        else:
            f.append(_finding(st, "ledger_eligibility", "NOT_VERIFIED", decl.eligibility_basis[:160], ledger))
    # County coverage: COUNTY_DEPENDENT names the counties; every other class lists what feeds it.
    cov = county_coverage(st, ledger, srcs, rules=my_rules)
    if e == "COUNTY_DEPENDENT":
        f.append(_finding(st, "county_coverage", "PASS" if cov else "FAIL",
                          (f"{len(cov)} {('county' if len(cov) == 1 else 'counties')}: " + ", ".join(c['county'] for c in cov[:12])
                           + (" …" if len(cov) > 12 else "")) if cov else "no county source feeds this ledger", ledger))
    elif cov:
        f.append(_finding(st, "county_coverage", "PASS", f"{len(cov)} count{'y' if len(cov) == 1 else 'ies'} fed; eligibility is {e}", ledger))
    else:
        f.append(_finding(st, "county_coverage", "NOT_APPLICABLE", "no county source feeds this ledger", ledger))
    return f


_EVIDENCE_URLS: set[str] | None = None


def _evidence_urls() -> set[str]:
    global _EVIDENCE_URLS
    if _EVIDENCE_URLS is None:
        urls = set()
        for name in ("purchase_path_evidence.csv", "purchase_path_evidence_expansion.csv"):
            with open(REPO / "data" / name, newline="", encoding="utf-8") as fh:
                for r in csv.DictReader(fh):
                    if (r.get("review_state") or "") == "verified":
                        urls.update(u for u in (r.get("evidence_url"), r.get("application_url")) if u)
        _EVIDENCE_URLS = urls
    return _EVIDENCE_URLS


def zero_state_findings(path: Path = APP_JS) -> list[dict]:
    """The customer zero-count presentation handles every case the record
    can produce (app.js ledgerZeroState / ZERO_CASE_COPY), and a failed read
    never prints a bare zero (the copy names 'last known')."""
    src = path.read_text(encoding="utf-8")
    out = []
    if "function ledgerZeroState(" not in src or "var ZERO_CASE_COPY" not in src:
        return [_finding("*", "zero_state_cases", "FAIL", "app.js has no ledgerZeroState / ZERO_CASE_COPY")]
    block = src[src.index("var ZERO_CASE_COPY"):src.index("function ledgerZeroState(")]
    missing = [c for c in ZERO_CASES if f"{c}:" not in block]
    out.append(_finding("*", "zero_state_cases", "FAIL" if missing else "PASS",
                        f"copy missing for {', '.join(missing)}" if missing else "every zero case has customer copy: " + ", ".join(ZERO_CASES)))
    fail_copy = block[block.index("SOURCE_FAILURE:"):] if "SOURCE_FAILURE:" in block else ""
    out.append(_finding("*", "no_false_zero_copy", "PASS" if "last known" in fail_copy else "FAIL",
                        "a failed or incomplete read shows the last known count, labelled as such" if "last known" in fail_copy
                        else "the SOURCE_FAILURE copy does not label the count as last known"))
    return out


def lifecycle_findings() -> list[dict]:
    """A failed or incomplete read closes nothing: the close-out gates in the
    sync and the lifecycle are exactly COMPLETE / EMPTY."""
    out = []
    import importlib.util
    spec = importlib.util.spec_from_file_location("sync_state_inventory", REPO / "scripts" / "sync_state_inventory.py")
    try:
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        closeable = set(getattr(mod, "CLOSEABLE", set()))
        out.append(_finding("*", "no_false_zero_lifecycle", "PASS" if closeable == {"COMPLETE", "EMPTY"} else "FAIL",
                            f"sync_state_inventory.CLOSEABLE = {sorted(closeable)}", "scripts/sync_state_inventory.py"))
    except Exception as exc:  # noqa: BLE001
        out.append(_finding("*", "no_false_zero_lifecycle", "BLOCKED", f"could not import sync_state_inventory: {exc}", "scripts/sync_state_inventory.py"))
    text = (REPO / "scripts" / "laft_lifecycle.py").read_text(encoding="utf-8")
    ok = "only for a county whose status is COMPLETE or EMPTY" in text
    out.append(_finding("*", "no_false_zero_lifecycle", "PASS" if ok else "FAIL",
                        "close-out only after a COMPLETE or EMPTY read" if ok else "laft_lifecycle close-out gate not found", "scripts/laft_lifecycle.py"))
    return out


def verify_state(st: str, *, rules, ledgers, sources, copy, urls, terms, units, paid_beta, rules_json, restricted=None, history=None) -> list[dict]:
    f = []
    restricted = (restricted if restricted is not None else restricted_sources()).get(st, {})
    history = SR.load_history() if history is None else history
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
        f.extend(eligibility_findings(st, decl, ledger, my_rules=my_rules, srcs=srcs, restricted=restricted))
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
    # Rule history: versions are contiguous and every change is recorded.
    hp = SR.history_problems(my_rules, [h for h in history if h.state == st])
    versioned = [r for r in my_rules if r.version != "1"]
    f.append(_finding(st, "rule_history", "FAIL" if hp else "PASS",
                      "; ".join(hp) if hp else (f"{len(versioned)} rule(s) with a recorded prior version" if versioned else "every rule is at version 1")))
    # Source classification: registry ledgers == the ledger domain map.
    from harvesters.ledgers import SOURCE_LEDGERS, BLOCKED_SOURCE_IDS  # noqa: PLC0415
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
    # Texas: the sale, the strike-off and the resale are told apart by the
    # source's own status; blocked vendors feed nothing; no fixed-price claim.
    if st == "TX":
        lg = srcs.get("tx_lgbs", {}).get("ledgers", set())
        ra = srcs.get("tx_realauction", {}).get("ledgers", set())
        ok = lg == {"AUCTIONS", "AVAILABLE"} and ra == {"AUCTIONS"} and not (set(srcs) & BLOCKED_SOURCE_IDS)
        f.append(_finding(st, "tx_classification", "PASS" if ok else "FAIL",
                          "LGBS feeds sale and struck-off rows by its own status, RealAuction sale rows only, blocked vendors feed nothing"
                          if ok else f"tx_lgbs {sorted(lg)}, tx_realauction {sorted(ra)}, blocked in production: {sorted(set(srcs) & BLOCKED_SOURCE_IDS)}"))
        avail_copy = copy.get("laft", {}).get("TX") or {}
        app = APP_JS.read_text(encoding="utf-8")
        tx_block = app[app.index("  laft: {"):app.index("  certificate: {")]
        claims_fixed = "fixed price" in tx_block.lower() and "not automatically" not in tx_block.lower()
        f.append(_finding(st, "tx_struck_off_copy", "FAIL" if claims_fixed else "PASS",
                          "struck-off copy claims a fixed price" if claims_fixed else "struck-off copy does not treat the property as for sale at a fixed price",
                          "LEDGERS.laft.tx"))
        del avail_copy
    # Florida: certificates, deed auctions and Lands Available are three
    # separate products with disjoint sources, and a certificate is never
    # called ownership.
    if st == "FL":
        by_ledger = {l: {sid for sid, x in srcs.items() if l in x["ledgers"]} for l in SR.LEDGERS}
        disjoint = all(not (by_ledger[a] & by_ledger[b]) for a in SR.LEDGERS for b in SR.LEDGERS if a < b)
        app = APP_JS.read_text(encoding="utf-8")
        cert = app[app.index("  certificate: {"):app.index("  certificate: {") + 1200]
        instrument = "not the land" in cert or "never the land" in cert
        f.append(_finding(st, "fl_separation", "PASS" if disjoint and instrument else "FAIL",
                          "three products, disjoint sources, certificate copy says the lien is not the land" if disjoint and instrument
                          else f"disjoint={disjoint}, certificate copy names the instrument={instrument}"))
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
               rules_json=rules_json, restricted=restricted_sources(), history=SR.load_history())
    findings = [x for st in sorted(states.PRODUCTION_STATES) for x in verify_state(st, **ctx)]
    findings += copy_law_claims(rules=rules)
    findings += zero_state_findings()
    findings += lifecycle_findings()
    stray = sorted({r.state for r in rules} - set(states.PRODUCTION_STATES))
    for st in stray:
        findings.append(_finding(st, "rules_state", "FAIL", "rules recorded for a state that is not in production"))
    summary = {s: sum(1 for x in findings if x["status"] == s) for s in STATUSES}
    by_state = defaultdict(lambda: {s: 0 for s in STATUSES})
    for x in findings:
        by_state[x["state"]][x["status"]] += 1
    return {"summary": summary, "by_state": dict(sorted(by_state.items())), "findings": findings}
