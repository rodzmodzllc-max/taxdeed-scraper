"""State-by-state source coverage, regulatory verification and acquisition-path
completion (2026-10-11).

Pins:
  * the rules vocabulary gained PARTIALLY_VERIFIED and SOURCE_RESTRICTED, and
    neither ever passes an engine check that requires VERIFIED;
  * the Harris County (TX) tax-sale list is recorded SOURCE_RESTRICTED, never
    verified, citing the registry row that refuses it;
  * every production registry row carries its publisher, amount kind, update
    cadence and terminology (the four metadata columns were blank on 163 of
    185 production rows before this sprint);
  * the machine-readable coverage report (data/current_state/state-coverage.json
    + docs/state-coverage.md) is generated from the registry, the rules, the
    ledger declarations, the counts-only snapshots and the acquisition
    evidence file, pinned by --check, and classifies every production
    state x ledger into exactly one of the nine concepts with a denominator;
  * a zero with eligibility NOT_VERIFIED is never "verified empty";
  * stamp_seen's --provenance pass records list-column provenance once and is
    idempotent (a second plan over the same rows is empty), never replacing
    an existing entry, and both FL stamp steps in the workflow pass the flag.
"""
from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from harvesters.governance import state_coverage as SC, state_rules as SR, state_verification as SV, states  # noqa: E402
from harvesters.governance import county_source_registry as CSR  # noqa: E402
from harvesters.otc.model import AmountKind  # noqa: E402
import stamp_seen as SS  # noqa: E402
import unit_freshness as UF  # noqa: E402

DOC = json.loads((ROOT / "data/current_state/state-coverage.json").read_text(encoding="utf-8"))
REGISTRY = list(csv.DictReader((ROOT / "data/county_source_registry.csv").open(encoding="utf-8", newline="")))
PRODUCTION = [r for r in REGISTRY if r["verification_status"] == "PRODUCTION_VERIFIED"]
WORKFLOW = (ROOT / ".github/workflows/harvest-and-sync.yml").read_text(encoding="utf-8")


def _rule(**kw) -> SR.Rule:
    base = dict(state="FL", county="", topic="t", kind="PROCEDURE", status="VERIFIED", statement="s",
                source_url="https://example.invalid/x", source_title="T", citation="", effective_date="",
                verified_on="2026-10-05", evidence="tests/python/test_state_coverage.py", ambiguity="",
                ledger="AUCTIONS", office="", related_sources="", depends_on="", implementation_status="NOT_IMPLEMENTED",
                test_ref="", version="1", changed_on="2026-10-05")
    base.update(kw)
    return SR.Rule(**base)


# ------------------------------------------------------------------ rules vocabulary

def test_rules_vocabulary_partially_verified_and_source_restricted():
    assert "PARTIALLY_VERIFIED" in SR.STATUSES and "SOURCE_RESTRICTED" in SR.STATUSES
    assert SR.READ_STATUSES == ("VERIFIED", "PARTIALLY_VERIFIED")
    assert SR.STATUS_LABELS["PARTIALLY_VERIFIED"] == "Partially verified" and SR.STATUS_LABELS["SOURCE_RESTRICTED"] == "Source restricted"
    # A partially verified rule must say what is ambiguous and still cite a read source.
    assert SR.rule_problems(_rule(status="PARTIALLY_VERIFIED", ambiguity="the statute names no deadline")) == []
    assert any("ambiguity" in p for p in SR.rule_problems(_rule(status="PARTIALLY_VERIFIED")))
    assert any("source_url" in p or "https" in p for p in SR.rule_problems(_rule(status="PARTIALLY_VERIFIED", ambiguity="a", source_url="")))
    # A restricted source records the evidence of the restriction and no verification date.
    assert SR.rule_problems(_rule(status="SOURCE_RESTRICTED", kind="SOURCE", verified_on="", evidence="registry row tx_hctax LEGAL_REVIEW_REQUIRED")) == []
    assert any("evidence" in p for p in SR.rule_problems(_rule(status="SOURCE_RESTRICTED", kind="SOURCE", verified_on="", evidence="")))
    # UNRESOLVED is never a read status.
    assert SR.rule_problems(_rule(kind="UNRESOLVED", status="PARTIALLY_VERIFIED", ambiguity="a"))
    assert SR.validate() == []


def test_partially_verified_never_passes_an_engine_check_that_needs_verified():
    src = (ROOT / "harvesters/governance/state_verification.py").read_text(encoding="utf-8")
    assert 'status == "VERIFIED"' in src or "== 'VERIFIED'" in src
    assert "PARTIALLY_VERIFIED" not in src.replace("READ_STATUSES", "")


def test_harris_tax_sale_list_is_source_restricted_and_cites_the_registry_refusal():
    r = next(x for x in SR.load_rules() if x.state == "TX" and x.county == "Harris" and x.topic == "tax_sale_list_source")
    assert r.kind == "SOURCE" and r.status == "SOURCE_RESTRICTED" and r.verified_on == ""
    assert r.source_url.startswith("https://www.hctax.net/") and "tx_hctax" in r.evidence and "LEGAL_REVIEW_REQUIRED" in r.evidence
    assert r.ledgers == ("AUCTIONS",) and "tx_hctax" in r.related_sources
    reg = next(x for x in REGISTRY if x["state"] == "TX" and x["county"] == "Harris" and x["source_id"] == "tx_hctax")
    assert reg["verification_status"] != "PRODUCTION_VERIFIED" and reg["governance_status"] == "LEGAL_REVIEW_REQUIRED"
    assert (ROOT / r.test_ref).is_file() and r.implementation_status == "IMPLEMENTED"
    page = json.loads((ROOT / "public/state-rules.json").read_text(encoding="utf-8"))
    tx = page["states"]["TX"]
    hit = [x for x in tx["county_rules"] if x.get("county") == "Harris" and x["topic"] == "tax_sale_list_source"]
    assert len(hit) == 1 and hit[0]["status"] == "SOURCE_RESTRICTED"
    assert page == json.loads((ROOT / "state-rules.json").read_text(encoding="utf-8"))


# ------------------------------------------------------------------ registry metadata

def test_every_production_registry_row_names_publisher_amount_kind_cadence_and_terminology():
    assert len(PRODUCTION) >= 185
    for col in ("publishing_unit_name", "amount_kind", "update_frequency", "source_terminology"):
        blank = [(r["state"], r["county"], r["source_id"]) for r in PRODUCTION if not r[col].strip()]
        assert blank == [], (col, blank[:5])
    kinds = {r["amount_kind"] for r in PRODUCTION}
    assert kinds <= {k.value for k in AmountKind}
    assert CSR.validate_registry(CSR.load_registry()) == []
    # The publishing unit is the government unit, never the platform or vendor.
    assert {r["publishing_unit"] for r in PRODUCTION} <= {u.value for u in states.PublishingUnit}
    lgbs = [r for r in PRODUCTION if r["source_id"] == "tx_lgbs"]
    assert lgbs and all(r["publishing_unit"] == "COUNTY" and "Linebarger" in r["publishing_unit_name"] for r in lgbs)
    lienhub = [r for r in PRODUCTION if r["source_id"] == "fl_lienhub_certificates"]
    assert len(lienhub) == 32 and all(r["restrictions"].startswith("SOURCE_UNAVAILABLE since 2026-10-01") for r in lienhub)
    okaloosa = next(r for r in PRODUCTION if r["source_id"] == "fl_bid4assets_okaloosa")
    assert "Bid4Assets" in okaloosa["publishing_unit_name"] and okaloosa["amount_kind"] == "OPENING_BID"
    orange = next(r for r in PRODUCTION if r["state"] == "FL" and r["county"] == "Orange" and r["source_id"].startswith("fl_laft"))
    assert orange["publishing_unit_name"].startswith("Orange County Comptroller")


def test_registry_builder_output_is_pinned():
    out = subprocess.run([sys.executable, "scripts/build_county_source_registry.py", "--check"], cwd=ROOT, capture_output=True, text=True)
    assert out.returncode == 0, out.stdout + out.stderr


# ------------------------------------------------------------------ the coverage report

def test_coverage_report_is_generated_and_pinned():
    out = subprocess.run([sys.executable, "scripts/build_state_coverage.py", "--check"], cwd=ROOT, capture_output=True, text=True)
    assert out.returncode == 0, out.stdout + out.stderr
    assert DOC == SC.build()
    md = (ROOT / "docs/state-coverage.md").read_text(encoding="utf-8")
    assert md == SC.render_markdown(DOC)


def test_every_production_state_and_ledger_is_classified_exactly_once_with_a_denominator():
    assert set(DOC["states"]) == set(states.PRODUCTION_STATES)
    assert DOC["concepts"] == list(SC.CONCEPTS) and set(SC.NEXT_ACTION) == set(SC.CONCEPTS)
    seen = 0
    for st, e in DOC["states"].items():
        assert set(e["ledgers"]) == set(SC.LEDGERS)
        for ledger, l in e["ledgers"].items():
            seen += 1
            assert l["classification"] in SC.CONCEPTS and l["classification_reasons"] and l["next_action"]
            assert l["eligibility"] in SR.ELIGIBILITIES
            s = l["sources"]
            assert s["approved_for_customers"] <= s["implemented"] <= s["known"]
            assert len(s["rows"]) == s["known"]
            for f, nN in l["fields"].items():
                assert 0 <= nN["n"] <= nN["N"], (st, ledger, f)
            if l["records"] is not None:
                assert l["records"]["active"] <= l["records"]["total"]
            assert set(l["acquisition"]["by_status"]) <= {"VERIFIED", "NEEDS_REVIEW", "UNAVAILABLE", "NOT_FOUND"}
            assert len(l["acquisition"]["verified_units"]) == l["acquisition"]["by_status"].get("VERIFIED", 0)
    assert seen == sum(DOC["summary"].values()) == 3 * len(states.PRODUCTION_STATES)
    assert DOC["generated_from"]["coverage_measured_at"] and DOC["generated_from"]["quality_measured_at"]


def test_classification_facts_from_the_2026_10_10_snapshots():
    fl = DOC["states"]["FL"]["ledgers"]
    assert fl["AUCTIONS"]["classification"] == "CURRENT" and fl["AVAILABLE"]["classification"] == "CURRENT"
    assert len(fl["AVAILABLE"]["acquisition"]["verified_units"]) >= 16
    # LienHub has answered 403 since 2026-10-01: every active certificate row is unstamped.
    liens = fl["LIENS_CERTIFICATES"]
    # 32 LienHub rows (SOURCE_UNAVAILABLE) + Sarasota's Tax Collector, whose
    # restrictions column records the owner's 2026-10-26 approval.
    assert liens["classification"] == "SOURCE_FAILED_OR_STALE" and liens["sources"]["restricted"] == 33
    assert liens["records"]["act_never_seen"] == liens["records"]["active"]
    # Shelby's source was collected but UNREVIEWED until the owner's 2026-10-26 decision
    # published it: approval is resolved; the unverified acquisition path is what remains.
    assert DOC["states"]["TN"]["ledgers"]["AVAILABLE"]["classification"] == "RECORDS_WITHHELD_NO_PATH"
    assert DOC["states"]["TN"]["ledgers"]["AVAILABLE"]["withheld"]["source_not_approved"] == 0
    # Texas auctions are manual-only: the stale read names the last dispatch, not a scheduled failure.
    txa = DOC["states"]["TX"]["ledgers"]["AUCTIONS"]
    # (Since 2026-10-26 the vendor sources are not manual-only, so the reason names the unstamped rows instead.)
    assert txa["classification"] == "SOURCE_FAILED_OR_STALE" and txa["classification_reasons"]
    assert set(SC.MANUAL_ONLY_SOURCES) == set(UF.MANUAL_ONLY_SOURCES)
    # Nothing is PRODUCT_NOT_OFFERED: no ledger carries NOT_OFFERED evidence yet.
    assert DOC["summary"].get("PRODUCT_NOT_OFFERED", 0) == 0
    assert "RULES_NOT_VERIFIED" in DOC["summary"]


def test_a_not_verified_zero_is_never_verified_empty():
    snap_empty = {"total": 0, "active": 0, "act_never_seen": 0, "act_seen_gt36h": 0, "last_seen_max": "2026-10-10 00:00:00+00"}
    src = [{"source_id": "x", "implemented": True, "approved_for_customers": True, "restrictions": "", "publication_status": "APPROVED"}]
    acq = {"units": 0, "by_status": {}, "verified_units": 0}
    assert SC.classify(eligibility="NOT_VERIFIED", sources=src, snap=snap_empty, acq=acq, ledger="AUCTIONS")[0] == "RULES_NOT_VERIFIED"
    assert SC.classify(eligibility="OFFERED", sources=src, snap=snap_empty, acq=acq, ledger="AUCTIONS")[0] == "OFFERED_VERIFIED_EMPTY"
    assert SC.classify(eligibility="OFFERED", sources=src, snap=None, acq=acq, ledger="AUCTIONS")[0] == "SOURCE_IMPLEMENTED_NEVER_READ"
    assert SC.classify(eligibility="NOT_OFFERED", sources=[], snap=None, acq=acq, ledger="AUCTIONS")[0] == "PRODUCT_NOT_OFFERED"
    assert SC.classify(eligibility="OFFERED", sources=[], snap=None, acq=acq, ledger="AUCTIONS")[0] == "OFFERED_SOURCE_NOT_IMPLEMENTED"
    assert SC.classify(eligibility="SOURCE_RESTRICTED", sources=[], snap=None, acq=acq, ledger="AUCTIONS")[0] == "SOURCE_RESTRICTED"
    unreviewed = [dict(src[0], approved_for_customers=False, publication_status="UNREVIEWED")]
    assert SC.classify(eligibility="OFFERED", sources=unreviewed, snap=snap_empty, acq=acq, ledger="AVAILABLE")[0] == "APPROVAL_UNRESOLVED"
    live = dict(snap_empty, total=10, active=10)
    no_path = {"units": 2, "by_status": {"NEEDS_REVIEW": 2}, "verified_units": 0}
    assert SC.classify(eligibility="OFFERED", sources=src, snap=live, acq=no_path, ledger="AVAILABLE")[0] == "RECORDS_WITHHELD_NO_PATH"
    stale = dict(live, act_never_seen=4, act_seen_gt36h=6)
    assert SC.classify(eligibility="OFFERED", sources=src, snap=stale, acq=acq, ledger="AUCTIONS")[0] == "SOURCE_FAILED_OR_STALE"
    assert SC.classify(eligibility="OFFERED", sources=src, snap=live, acq=acq, ledger="AUCTIONS")[0] == "CURRENT"


def test_coverage_report_carries_no_row_value():
    text = json.dumps(DOC)
    for forbidden in ("address", "owner_name", "\"parcel\":", "\"bid\":"):
        assert forbidden not in text.lower() or forbidden == "\"parcel\":" and "act_parcel" in text
    assert "note" in DOC["generated_from"] and "no row value" in DOC["generated_from"]["note"]


# ------------------------------------------------------------------ list-column provenance (stamp_seen --provenance)

def test_stamp_seen_provenance_is_recorded_once_and_never_replaces_an_entry():
    rows = [{"county": "Alachua", "case": "2026-TD-1", "parcel": "P", "address": "A", "bid": "100", "assessed": "", "sale_date": "2026-11-01"},
            {"county": "Alachua", "case": "2026-TD-2", "parcel": "", "address": "", "bid": "", "assessed": "", "sale_date": ""},
            {"county": "Baker", "case": "2026-TD-9", "parcel": "Q", "bid": "5"}]
    stored = [{"id": 1, "case_no": "2026-TD-1", "field_provenance": {"parcel": {"source": "hand_research", "recorded_at": "2026-09-01"}}},
              {"id": 2, "case_no": "2026-TD-2", "field_provenance": None},
              {"id": 3, "case_no": "2026-TD-3", "field_provenance": None}]
    plan = SS.plan_provenance(rows, stored, source="auction", county="Alachua", case_key="case", recorded_at="2026-10-11T00:00:00Z")
    assert [pid for pid, _ in plan] == [1]                       # row 2 has no non-blank column; row 3 was not read
    merged = plan[0][1]
    assert merged["parcel"]["source"] == "hand_research"           # never replaced
    assert set(merged) == {"parcel", "address", "bid", "sale_date"}  # assessed blank -> no entry
    assert merged["bid"]["source"] == SS.PROVENANCE_SOURCE == "vendor_listing"
    assert merged["bid"].get("source_id") == "fl_realauction"
    stored[0]["field_provenance"] = merged
    assert SS.plan_provenance(rows, stored, source="auction", county="Alachua", case_key="case", recorded_at="2026-10-12T00:00:00Z") == []
    assert SS.source_id_for("auction", "Okaloosa") == "fl_bid4assets_okaloosa"
    assert SS.source_id_for("certificate", "Alachua") == "fl_lienhub_certificates"
    assert set(SS.PROVENANCE_COLUMNS) == {"auction", "certificate"}
    assert SS.PROVENANCE_COLUMNS["auction"]["auction_url"] == "url_auction"


def test_both_florida_stamp_steps_pass_the_provenance_flag():
    lines = [l for l in WORKFLOW.splitlines() if "scripts/stamp_seen.py" in l and "--state FL" in l]
    assert len(lines) == 2 and all("--provenance" in l for l in lines)
    assert any("--source auction" in l for l in lines) and any("--source certificate" in l and "--status" in l for l in lines)
    assert "--provenance" in (ROOT / "scripts/stamp_seen.py").read_text(encoding="utf-8")
