"""Ledger eligibility, county coverage, zero-count semantics and rule history
(2026-10-10).

Eligibility (does the state offer the product) is decided apart from tracking
(does TAXACQ read a source) and apart from any count. OFFERED / NOT_OFFERED
need a statute read; COUNTY_DEPENDENT needs a county's own publication read;
NOT_VERIFIED carries no date and never claims absence. The engine refuses a
classification its record does not support, a failed read never closes a row
or prints a bare zero, and a rule's versions are contiguous with history.
"""
from __future__ import annotations

import dataclasses
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from harvesters.governance import state_rules as SR, state_verification as SV, states  # noqa: E402

APP = (ROOT / "public/app.js").read_text(encoding="utf-8")
PAGE = json.loads((ROOT / "public/state-rules.json").read_text(encoding="utf-8"))


def _ledger(**kw):
    base = dict(state="FL", ledger="AUCTIONS", status="TRACKED", note="n", evidence="", eligibility="OFFERED",
                eligibility_basis="statute read", eligibility_source_url="https://example.gov/s",
                eligibility_verified_on="2026-10-05", meaning="m", office="")
    base.update(kw)
    return SR.LedgerSupport(**base)


# ------------------------------------------------------------------ the record

def test_every_state_ledger_carries_an_eligibility_apart_from_tracking():
    assert SR.validate() == []
    ledgers = SR.load_ledgers()
    assert {(l.state, l.ledger) for l in ledgers} == {(s, l) for s in states.PRODUCTION_STATES for l in SR.LEDGERS}
    for l in ledgers:
        assert l.eligibility in SR.ELIGIBILITIES and l.meaning and l.eligibility_basis, (l.state, l.ledger)
    # Eligibility is not tracking: an offered-by-county product can be untracked,
    # and a tracked ledger can still be unverified as a product.
    by = {(l.state, l.ledger): l for l in ledgers}
    assert (by[("WY", "LIENS_CERTIFICATES")].eligibility, by[("WY", "LIENS_CERTIFICATES")].status) == ("COUNTY_DEPENDENT", "NOT_TRACKED")
    assert (by[("TX", "AVAILABLE")].eligibility, by[("TX", "AVAILABLE")].status) == ("NOT_VERIFIED", "TRACKED")


def test_offered_is_claimed_only_where_a_statute_was_read_and_nothing_is_not_offered():
    ledgers = SR.load_ledgers()
    offered = {(l.state, l.ledger) for l in ledgers if l.eligibility == "OFFERED"}
    assert offered == {("FL", "AUCTIONS"), ("FL", "AVAILABLE"), ("FL", "LIENS_CERTIFICATES")}
    assert not [l for l in ledgers if l.eligibility == "NOT_OFFERED"]          # no statute establishing absence was read
    for l in ledgers:
        if l.eligibility in SR.EVIDENCED_ELIGIBILITIES:
            assert l.eligibility_source_url.startswith("https://") and re.match(r"\d{4}-\d{2}-\d{2}$", l.eligibility_verified_on)
        else:
            assert not l.eligibility_verified_on


@pytest.mark.parametrize("change, problem", [
    (dict(eligibility_source_url=""), "needs an https eligibility_source_url"),
    (dict(eligibility_verified_on=""), "needs eligibility_verified_on"),
    (dict(eligibility="NOT_VERIFIED"), "carries no verification date"),
    (dict(eligibility="NOT_OFFERED", evidence="x"), "cannot be TRACKED"),
    (dict(status="NOT_OFFERED", evidence="x"), "needs eligibility NOT_OFFERED"),
    (dict(meaning=""), "meaning"),
    (dict(eligibility_basis=""), "basis"),
    (dict(eligibility="MAYBE"), "eligibility"),
])
def test_an_eligibility_is_never_recorded_without_its_evidence(change, problem):
    assert any(problem in p for p in SR.ledger_problems(_ledger(**change))), change


# ------------------------------------------------------------------ the engine

def _rules(st):
    return [r for r in SR.load_rules() if r.state == st]


def _srcs(st):
    return SV.production_sources().get(st, {})


def _elig(st, ledger, decl, rules=None, srcs=None, restricted=None):
    return SV.eligibility_findings(st, decl, ledger, my_rules=_rules(st) if rules is None else rules,
                                   srcs=_srcs(st) if srcs is None else srcs, restricted=restricted or {})


def _one(findings, check):
    got = [f for f in findings if f["check"] == check]
    assert len(got) == 1, got
    return got[0]


def test_offered_needs_a_verified_law_rule_for_that_ledger():
    decl = _ledger(state="FL", ledger="AUCTIONS")
    assert _one(_elig("FL", "AUCTIONS", decl), "ledger_eligibility")["status"] == "PASS"
    assert _one(_elig("FL", "AUCTIONS", decl, rules=[]), "ledger_eligibility")["status"] == "FAIL"
    not_off = _ledger(state="FL", ledger="AUCTIONS", status="NOT_OFFERED", eligibility="NOT_OFFERED", evidence="x")
    assert _one(_elig("FL", "AUCTIONS", not_off, rules=[r for r in _rules("FL") if r.kind != "LAW"]), "ledger_eligibility")["status"] == "FAIL"


def test_county_dependent_needs_a_government_publication_read():
    decl = _ledger(state="MI", ledger="AUCTIONS", eligibility="COUNTY_DEPENDENT")
    assert _one(_elig("MI", "AUCTIONS", decl), "ledger_eligibility")["status"] == "PASS"
    # No source and no verified county procedure: refused.
    assert _one(_elig("MI", "AUCTIONS", decl, rules=[], srcs={}), "ledger_eligibility")["status"] == "FAIL"
    # Only a vendor listing, no government page or procedure read: refused.
    vendor = {"v": {"ledgers": {"AUCTIONS"}, "publication": {"APPROVED"}, "counties": {"X"}, "urls": set(), "authority": {"VENDOR_COUNSEL"}}}
    assert "only vendor listings" in _one(_elig("MI", "AUCTIONS", decl, rules=[], srcs=vendor), "ledger_eligibility")["detail"]
    # A verified county procedure alone establishes the county (Albany's lien sale).
    wy = next(l for l in SR.load_ledgers() if (l.state, l.ledger) == ("WY", "LIENS_CERTIFICATES"))
    f = _one(_elig("WY", "LIENS_CERTIFICATES", wy), "ledger_eligibility")
    assert f["status"] == "PASS" and "Albany" in f["detail"] and "no inventory source" in f["detail"]


def test_source_restricted_and_not_verified_are_refused_when_the_record_says_more():
    sr = _ledger(state="TX", ledger="AVAILABLE", eligibility="SOURCE_RESTRICTED", eligibility_source_url="", eligibility_verified_on="")
    f = _one(_elig("TX", "AVAILABLE", sr, restricted={"tx_hctax": {"ledgers": {"AVAILABLE"}, "publication": {"RESTRICTED"}}}), "ledger_eligibility")
    assert f["status"] == "FAIL" and "approved source(s) feed this ledger" in f["detail"]          # LGBS is approved
    f = _one(_elig("TX", "AVAILABLE", sr, srcs={}), "ledger_eligibility")
    assert f["status"] == "FAIL" and "needs a RESTRICTED / BLOCKED" in f["detail"]
    f = _one(_elig("TX", "AVAILABLE", sr, srcs={}, restricted={"tx_hctax": {"ledgers": {"AVAILABLE"}, "publication": {"RESTRICTED"}}}), "ledger_eligibility")
    assert f["status"] == "BLOCKED"                                                                  # never permission to activate
    nv = _ledger(state="FL", ledger="AVAILABLE", eligibility="NOT_VERIFIED", eligibility_source_url="", eligibility_verified_on="")
    f = _one(_elig("FL", "AVAILABLE", nv), "ledger_eligibility")
    assert f["status"] == "FAIL" and "VERIFIED LAW rule covers this ledger" in f["detail"]


def test_county_coverage_comes_from_the_registry_and_verified_procedures_never_from_rows():
    tx = SV.county_coverage("TX", "AUCTIONS", rules=_rules("TX"))
    assert len(tx) == 31 and tx[0]["county"] == "Angelina" and all(c["sources"] for c in tx)
    assert all(s["source_id"] in ("tx_realauction", "tx_lgbs") for c in tx for s in c["sources"])
    wy = SV.county_coverage("WY", "LIENS_CERTIFICATES", rules=_rules("WY"))
    assert wy == [{"county": "Albany", "sources": [], "procedures": ["tax_sale_model"]}]
    assert SV.county_coverage("TN", "AUCTIONS", rules=_rules("TN")) == []
    assert SV.county_coverage("TN", "AVAILABLE", rules=_rules("TN"))[0]["sources"][0]["publication"] == "UNREVIEWED"


def test_engine_has_no_failure_and_blocked_never_activates():
    doc = json.loads((ROOT / "data/state_verification.json").read_text())
    assert doc["summary"]["FAIL"] == 0 and doc["summary"]["BLOCKED"] == 0
    checks = {f["check"] for f in doc["findings"]}
    assert {"ledger_eligibility", "county_coverage", "rule_history", "zero_state_cases", "no_false_zero_copy",
            "no_false_zero_lifecycle", "tx_classification", "tx_struck_off_copy", "fl_separation"} <= checks
    for st in states.PRODUCTION_STATES:
        for ledger in SR.LEDGERS:
            assert [f for f in doc["findings"] if f["state"] == st and f["check"] == "ledger_eligibility" and f["subject"] == ledger], (st, ledger)
    assert all(f["status"] == "PASS" for f in doc["findings"] if f["check"] in ("tx_classification", "tx_struck_off_copy", "fl_separation", "no_false_zero_lifecycle"))


def test_texas_and_florida_are_told_apart_by_the_source_not_by_assumption():
    f = {x["check"]: x for x in SV.run()["findings"] if x["state"] == "TX"}
    assert "by its own status" in f["tx_classification"]["detail"]
    tx_avail = APP[APP.index("  laft: {"):APP.index("  certificate: {")]
    assert "not automatically" in tx_avail.lower() and "fixed price" not in tx_avail.lower().replace("not at a fixed price", "")
    fl = {x["check"]: x for x in SV.run()["findings"] if x["state"] == "FL"}
    assert fl["fl_separation"]["status"] == "PASS"
    srcs = SV.production_sources()["FL"]
    cert = {sid for sid, s in srcs.items() if "LIENS_CERTIFICATES" in s["ledgers"]}
    assert cert == {"fl_lienhub_certificates"} and not any({"AUCTIONS", "AVAILABLE"} & srcs[sid]["ledgers"] for sid in cert)


# ------------------------------------------------------------------ rule history

def _rule(**kw):
    base = dict(state="TX", county="", topic="t", kind="UNRESOLVED", status="NOT_VERIFIED", statement="s", source_url="", source_title="",
                citation="", effective_date="", verified_on="", evidence="", ambiguity="", ledger="AUCTIONS", version="2", changed_on="2026-10-10")
    base.update(kw)
    return SR.Rule(**base)


def _hist(**kw):
    base = dict(state="TX", county="", topic="t", version="1", changed_on="2026-10-10", change="c", prior_status="NOT_VERIFIED",
                prior_statement="old", affects="")
    base.update(kw)
    return SR.RuleHistory(**base)


def test_versions_are_contiguous_and_every_change_is_recorded():
    assert SR.history_problems([_rule()], [_hist()]) == []
    assert any("needs history rows [1]" in p for p in SR.history_problems([_rule()], []))
    assert any("needs history rows [1, 2]" in p for p in SR.history_problems([_rule(version="3")], [_hist()]))
    assert any("does not exist" in p for p in SR.history_problems([], [_hist()]))
    assert any("prior statement" in p for p in SR.history_problems([_rule()], [_hist(prior_statement="")]))
    assert any("version" in p for p in SR.rule_problems(_rule(version="0")))
    assert any("changed_on" in p for p in SR.rule_problems(_rule(changed_on="")))


def test_the_texas_sale_model_rule_is_at_version_two_with_its_prior_text_kept():
    r = next(x for x in _rules("TX") if x.topic == "tax_sale_model")
    h = [x for x in SR.load_history() if x.key == r.key]
    assert r.version == "2" and [x.version for x in h] == ["1"]
    assert "not automatically for sale" in r.statement and "34.05" in r.statement
    assert h[0].prior_statement and h[0].prior_statement != r.statement and h[0].affects
    page = PAGE["states"]["TX"]
    assert [(x["topic"], x["version"]) for x in page["history"]] == [("tax_sale_model", "1")]


def test_rules_name_their_ledger_office_dependents_and_tests():
    for r in SR.load_rules():
        assert r.ledgers and set(r.ledgers) <= set(SR.LEDGERS), r.key
        assert r.implementation_status in SR.IMPLEMENTATION_STATUSES
        if r.implementation_status == "IMPLEMENTED":
            assert r.depends_on and (ROOT / r.test_ref).is_file(), r.key
    fl = {r.topic: r for r in _rules("FL")}
    assert fl["certificate_instrument"].ledgers == ("LIENS_CERTIFICATES",) and fl["certificate_instrument"].kind == "LAW"
    assert "not ownership" in fl["certificate_instrument"].statement
    wy = next(r for r in _rules("WY") if r.topic == "tax_sale_model")
    assert set(wy.ledgers) == {"AUCTIONS", "LIENS_CERTIFICATES"}


# ------------------------------------------------------------------ the customer files

def test_page_data_carries_eligibility_coverage_and_meaning_per_ledger():
    assert PAGE["eligibilities"] == SR.ELIGIBILITY_LABELS
    for st, e in PAGE["states"].items():
        for ledger in SR.LEDGERS:
            l = e["ledgers"][ledger]
            assert l["eligibility"] in SR.ELIGIBILITIES and l["meaning"] and l["eligibility_basis"] and isinstance(l["coverage"], list)
            if l["eligibility"] in SR.EVIDENCED_ELIGIBILITIES:
                assert l["eligibility_source_url"].startswith("https://") and l["eligibility_verified_on"]
            else:
                assert "eligibility_verified_on" not in l
    assert PAGE["states"]["FL"]["ledgers"]["LIENS_CERTIFICATES"]["eligibility"] == "OFFERED"
    assert [c["county"] for c in PAGE["states"]["MI"]["ledgers"]["AUCTIONS"]["coverage"]] == ["Eaton", "Lenawee"]
    assert PAGE == json.loads((ROOT / "state-rules.json").read_text(encoding="utf-8"))


def test_app_zero_cases_mirror_the_engine_and_a_failed_read_never_prints_a_bare_zero():
    block = APP[APP.index("var ZERO_CASE_COPY"):APP.index("function ledgerZeroState(")]
    assert [c for c in SV.ZERO_CASES if f"{c}:" not in block] == []
    assert re.findall(r"^  ([A-Z_]+): \{", block, re.M) == list(SV.ZERO_CASES)
    assert "Last known" in APP[APP.index("function ledgerStatusHtml"):APP.index("function ledgerStatusHtml") + 4000]
    fn = APP[APP.index("function ledgerZeroState("):APP.index("function ledgerNoun(")]
    order = [fn.index(x) for x in ('if (loadFailed) zeroCase = "SOURCE_FAILURE"', 'eligibility === "NOT_OFFERED"', 'count > 0 || !settled',
                                   'unhealthy && !readOk) zeroCase = "SOURCE_FAILURE"', '!tracked) zeroCase = "NOT_IMPLEMENTED"', 'zeroCase = "SOURCE_RESTRICTED"',
                                   'zeroCase = "NOT_VERIFIED"', 'zeroCase = "COUNTY_DEPENDENT"', 'zeroCase = "NO_CURRENT_INVENTORY"')]
    assert order == sorted(order)                       # the documented precedence
    assert 'eligibility = led && led.eligibility ? led.eligibility : "NOT_VERIFIED"' in fn   # no record = not verified, never not offered
    assert "A failed or incomplete read never" in APP or "never turns into a bare zero" in APP
    html = APP[APP.index("function ledgerStatusHtml"):APP.index("function ruleLedgers")]
    assert 'z.loadFailed ? (z.count ? `${ledgerNoun(kind, z.count)} loaded - load failed, may be incomplete` : "Count unavailable - load failed")' in html
    assert "var LEDGER_NAME_FOR_KEY = { auction: \"AUCTIONS\", laft: \"AVAILABLE\", certificate: \"LIENS_CERTIFICATES\" };" in APP
    assert {v: k for k, v in SV.APP_LEDGER.items()} == {"auction": "AUCTIONS", "laft": "AVAILABLE", "certificate": "LIENS_CERTIFICATES"}


def test_no_customer_string_promises_a_purchase_or_a_score_in_the_zero_copy():
    block = APP[APP.index("var ZERO_CASE_COPY"):APP.index("function ledgerZeroState(")]
    assert not re.search(r"\b(score|confidence|guarantee|buy now|purchasable)\b", block, re.I)
    for case in ("NOT_IMPLEMENTED", "SOURCE_RESTRICTED", "NOT_VERIFIED"):
        text = re.search(case + r': \{ label: "[^"]+", text: "([^"]+)"', block).group(1)
        assert "not proof" in text or "not a statement" in text, case


def test_failed_reads_close_nothing():
    f = [x for x in SV.lifecycle_findings()]
    assert [x["status"] for x in f] == ["PASS", "PASS"]
    import importlib.util
    spec = importlib.util.spec_from_file_location("sync_state_inventory", ROOT / "scripts/sync_state_inventory.py")
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    assert mod.CLOSEABLE == frozenset({"COMPLETE", "EMPTY"})
    assert mod.plan_close("TN", [], [{"id": "x", "county": "Shelby", "source_id": "tn_shelby_landbank", "status": "active"}],
                          {"Shelby": "FAILED"}, {"tn_shelby_landbank"}) == []


def test_zero_state_check_refuses_an_app_without_every_case(tmp_path):
    bad = tmp_path / "app.js"
    bad.write_text('var ZERO_CASE_COPY = {\n  NOT_OFFERED: { label: "x", text: "y" },\n  SOURCE_FAILURE: { label: "f", text: "no count" }\n};\nfunction ledgerZeroState(k) {}\n')
    got = {f["check"]: f["status"] for f in SV.zero_state_findings(bad)}
    assert got == {"zero_state_cases": "FAIL", "no_false_zero_copy": "FAIL"}
    assert {f["check"]: f["status"] for f in SV.zero_state_findings()} == {"zero_state_cases": "PASS", "no_false_zero_copy": "PASS"}
