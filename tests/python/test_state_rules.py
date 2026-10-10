"""State rules registry and verification engine (2026-10-10).

The registry keeps state law, government procedure, source behaviour and
unresolved items apart; a VERIFIED row must carry its official source, title,
verification date and repository evidence (and a LAW row its citation). The
engine compares the registry with the source registry, the ledger map and the
customer copy, and a missing record is a FAIL - never a silent pass.
"""
from __future__ import annotations

import dataclasses
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from harvesters.governance import state_rules as SR, state_verification as SV, states  # noqa: E402
import build_state_rules as B  # noqa: E402


def _rule(**kw):
    base = dict(state="FL", county="", topic="t", kind="LAW", status="VERIFIED", statement="s",
                source_url="https://example.gov/s", source_title="Statute", citation="F.S. 1.1", effective_date="",
                verified_on="2026-10-05", evidence="read in run 1", ambiguity="")
    base.update(kw)
    return SR.Rule(**base)


# ------------------------------------------------------------------ registry

def test_registry_is_valid_and_covers_every_production_state():
    assert SR.validate() == []
    rules, ledgers = SR.load_rules(), SR.load_ledgers()
    assert {r.state for r in rules} == set(states.PRODUCTION_STATES)
    for st in states.PRODUCTION_STATES:
        assert set(SR.ledger_support(st, ledgers)) == set(SR.LEDGERS), st


@pytest.mark.parametrize("change, problem", [
    (dict(kind="UNRESOLVED"), "never VERIFIED"),
    (dict(verified_on=""), "verified_on"),
    (dict(source_url=""), "needs source_url"),
    (dict(evidence=""), "needs source_url, source_title and evidence"),
    (dict(citation=""), "needs its citation"),
    (dict(citation="F.S. 1.1 (lead only)"), "lead only"),
    (dict(source_url="http://example.gov"), "https"),
    (dict(status="NOT_VERIFIED"), "verified_on is set"),        # a date only on a verified row
    (dict(status="CONFLICT", verified_on=""), "describe the conflict"),
    (dict(kind="OPINION"), "kind"),
])
def test_a_rule_is_never_verified_without_its_evidence(change, problem):
    assert any(problem in p for p in SR.rule_problems(_rule(**change))), change


def test_an_unverified_rule_without_a_date_is_valid():
    assert SR.rule_problems(_rule(kind="UNRESOLVED", status="NOT_VERIFIED", verified_on="", citation="X (lead only)")) == []


def test_verified_law_rows_are_only_those_read_and_recorded():
    laws = [r for r in SR.load_rules() if r.kind == "LAW" and r.status == "VERIFIED"]
    assert {r.state for r in laws} == {"FL"}           # the only statutes read from this repository (2026-10-05)
    assert all("docs/available-amount-semantics.md" in r.evidence for r in laws)
    assert {c for r in laws for c in [r.citation]} == {"F.S. 197.502(6)(a), (6)(c)", "F.S. 197.502(7)", "F.S. 197.542(1)"}
    # Citations seen in the repository but never read stay leads, never verified.
    leads = {r.citation for r in SR.load_rules() if "lead only" in r.citation}
    assert {"F.S. 197.502(8) (lead only)", "Tex. Tax Code 34.21 (lead only)", "S.C. Code 12-51-90 (lead only)"} <= leads


def test_county_rules_override_statewide_only_for_that_county():
    rules = [_rule(state="SC", topic="redemption", kind="UNRESOLVED", status="NOT_VERIFIED", verified_on="", citation=""),
             _rule(state="SC", county="Georgetown", topic="redemption", kind="PROCEDURE", citation=""),
             _rule(state="SC", topic="other", kind="SOURCE", citation="")]
    statewide = {r.topic: r for r in SR.rules_for("SC", "", rules)}
    gt = {r.topic: r for r in SR.rules_for("SC", "Georgetown", rules)}
    horry = {r.topic: r for r in SR.rules_for("SC", "Horry", rules)}
    assert statewide["redemption"].status == "NOT_VERIFIED" and horry["redemption"].status == "NOT_VERIFIED"
    assert gt["redemption"].county == "Georgetown" and gt["redemption"].status == "VERIFIED"
    assert set(gt) == set(statewide) == set(horry) == {"redemption", "other"}
    assert SR.rules_for("FL", "Georgetown", rules) == []              # never another state's


def test_not_offered_needs_evidence():
    bad = SR.LedgerSupport("TN", "LIENS_CERTIFICATES", "NOT_OFFERED", "Tennessee sells no certificates", "")
    assert any("NOT_OFFERED needs evidence" in p for p in SR.validate(rules=[], ledgers=[bad]))


# ------------------------------------------------------------------ engine

def test_engine_findings_are_current_and_have_no_failure():
    assert B.main(["--check"]) == 0
    doc = json.loads((ROOT / "data/state_verification.json").read_text())
    assert doc["summary"]["FAIL"] == 0
    assert set(doc["summary"]) == set(SV.STATUSES)
    assert not any(k in json.dumps(doc).lower() for k in ("score", "confidence"))


def _ctx():
    page = B.build_page()
    return dict(rules=SR.load_rules(), ledgers=SR.load_ledgers(), sources=SV.production_sources(), copy=SV.app_ledger_copy(),
                urls=SV.recorded_urls(), terms=SV._terms_sources(), units=SV._acquisition_units(), paid_beta=SV._paid_beta(),
                rules_json=page)


def _status(findings, check, subject=None):
    return [f["status"] for f in findings if f["check"] == check and (subject is None or f.get("subject") == subject)]


def test_a_missing_ledger_record_fails_never_passes():
    ctx = _ctx()
    ctx["ledgers"] = [l for l in ctx["ledgers"] if not (l.state == "TN" and l.ledger == "AVAILABLE")]
    assert _status(SV.verify_state("TN", **ctx), "ledger_declared", "AVAILABLE") == ["FAIL"]


def test_tracking_must_match_the_production_sources_both_ways():
    ctx = _ctx()
    ctx["ledgers"] = [dataclasses.replace(l, status="NOT_TRACKED") if (l.state, l.ledger) == ("TN", "AVAILABLE") else l
                      for l in ctx["ledgers"]]
    assert _status(SV.verify_state("TN", **ctx), "ledger_tracking", "AVAILABLE") == ["FAIL"]
    ctx = _ctx()
    ctx["ledgers"] = [dataclasses.replace(l, status="TRACKED") if (l.state, l.ledger) == ("TN", "AUCTIONS") else l
                      for l in ctx["ledgers"]]
    assert _status(SV.verify_state("TN", **ctx), "ledger_tracking", "AUCTIONS") == ["FAIL"]


def test_customer_copy_that_denies_a_tracked_source_fails():
    """The defect this engine found on 2026-10-10: Michigan and South Carolina
    Available copy said "No ... post-sale available source is tracked" while
    Detroit / Oceana and Horry / Georgetown are collected."""
    ctx = _ctx()
    ctx["copy"] = json.loads(json.dumps(ctx["copy"]))
    ctx["copy"]["laft"]["MI"]["sub"] = "No Michigan post-sale available source is tracked."
    assert _status(SV.verify_state("MI", **ctx), "ledger_copy", "AVAILABLE") == ["FAIL"]
    assert _status(SV.verify_state("MI", **_ctx()), "ledger_copy", "AVAILABLE") == ["PASS"]


def test_an_unverified_statute_in_customer_copy_fails_unless_disclosed(tmp_path):
    app = tmp_path / "app.js"
    app.write_text('const LEDGERS = {\n  x: { how: "You can redeem for 3 years (Tex. Tax Code §34.21)." },\n  y: { how: "Opening bid per F.S. 197.502(6)." }\n};\n'
                   "for (const [ledgerKey, byState] of Object.entries(EXPANSION_LEDGER_COPY)) {}\n")
    got = SV.copy_law_claims(app)
    assert [(f["status"], f["detail"].split(":")[0]) for f in got] == [
        ("FAIL", "cites a statute no verified LAW rule records"), ("PASS", "cites verified law 197.502")]
    app.write_text(app.read_text().replace("(Tex. Tax Code §34.21)", "(Tex. Tax Code §34.21 - not verified)"))
    assert {f["status"] for f in SV.copy_law_claims(app)} == {"PASS"}


def test_source_classification_matches_the_ledger_map():
    findings = SV.run()["findings"]
    cls = [f for f in findings if f["check"] == "source_classification"]
    assert cls and all(f["status"] == "PASS" for f in cls)
    tn = [f for f in cls if f["state"] == "TN"]
    assert [(f["subject"], f["detail"]) for f in tn] == [("tn_shelby_landbank", "AVAILABLE")]


def test_unreviewed_sources_never_enter_the_paid_beta():
    ctx = _ctx()
    ctx["paid_beta"] = set(ctx["paid_beta"]) | {"tn_shelby_landbank"}
    assert _status(SV.verify_state("TN", **ctx), "publication_gate") == ["FAIL"]


def test_acquisition_path_is_never_called_verified_without_evidence():
    findings = SV.run()["findings"]
    tn = [f for f in findings if f["state"] == "TN" and f["check"] == "acquisition_path"]
    assert tn[0]["status"] == "NOT_VERIFIED" and tn[0]["detail"].startswith("0/1 ")
    wy = [f for f in findings if f["state"] == "WY" and f["check"] == "acquisition_path"]
    assert wy[0]["status"] == "NOT_APPLICABLE"


# ------------------------------------------------------------------ the customer page data

def test_page_data_keeps_statuses_and_never_invents_a_link():
    page = json.loads((ROOT / "public/state-rules.json").read_text())
    assert page == json.loads((ROOT / "state-rules.json").read_text())             # root mirror
    urls = SV.recorded_urls()
    for st, e in page["states"].items():
        for r in e["rules"] + e["county_rules"]:
            assert r["status"] in SR.STATUSES and r["kind"] in SR.KINDS
            if r["status"] == "VERIFIED":
                assert r.get("verified_on") and r.get("evidence")
            else:
                assert "verified_on" not in r
        for p in e["county_procedures"]:
            assert p["evidence_url"].startswith("https://") and p["evidence_url"] in urls
    tn = page["states"]["TN"]
    assert tn["ledgers"]["LIENS_CERTIFICATES"]["status"] == "NOT_TRACKED"         # never claimed "not offered"
    assert tn["ledgers"]["AVAILABLE"]["status"] == "TRACKED"


def test_app_mirrors_the_county_override_rule():
    app = (ROOT / "public/app.js").read_text()
    assert "function rulesForCounty(entry, county)" in app
    assert 'if (county) (entry.county_rules || []).filter(r => r.county === county).forEach(r => { merged[r.topic] = r; });' in app
    assert 'fetch("state-rules.json"' in app and '"rules": "pageRules"' not in app
    assert 'rules: "pageRules"' in app


def test_customer_copy_no_longer_states_unverified_law_as_fact():
    app = (ROOT / "public/app.js").read_text()
    for gone in ("Tennessee sells no tax-lien certificates.", "Tennessee tax sales sell redeemable deeds, not certificates.",
                 "subject to the same statutory redemption rights", "No Michigan post-sale available source is tracked.",
                 "No South Carolina post-sale available source is tracked."):
        assert gone not in app, gone
