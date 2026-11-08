"""scripts/data_accuracy_watchdog.py: invariant logic on fixtures (no network)."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(1, str(REPO))

import data_accuracy_watchdog as W  # noqa: E402

NOW = datetime(2026, 11, 8, 15, 41, tzinfo=timezone.utc)
SEEN = "2026-11-08T07:00:00Z"


def row(i, **over):
    base = {"id": f"r{i}", "state": "FL", "county": "Alachua", "case_no": f"C-{i}", "parcel": f"P{i}",
            "source": "laft", "source_id": "fl_laft_pdfs", "status": "active", "sale_date": None,
            "last_seen_at": SEEN}
    base.update(over)
    return base


def test_clean_population_has_no_hard_break():
    rows = [row(i) for i in range(5)]
    rep = W.evaluate(rows, [], None, NOW)
    assert rep["hard_breaks"] == []
    assert rep["totals"] == {"active": 5, "not_seen_7d": 0, "missing_county": 0, "past_sale": 0}
    assert list(rep["units"]) == ["FL|AVAILABLE|fl_laft_pdfs"]


def test_closed_rows_are_ignored_and_null_status_is_active():
    rows = [row(1, status="closed"), row(2, status=None), row(3, status="sold")]
    assert W.evaluate(rows, [], None, NOW)["totals"]["active"] == 1


def test_not_seen_and_missing_county_are_counted_not_hard():
    rows = [row(1, last_seen_at=None), row(2, last_seen_at="2026-10-01T00:00:00Z"), row(3, county="")]
    rep = W.evaluate(rows, [], None, NOW)
    cells = rep["units"]["FL|AVAILABLE|fl_laft_pdfs"]
    assert cells["not_seen_7d"] == 2 and cells["missing_county"] == 1
    assert rep["hard_breaks"] == []


def test_same_source_case_duplicate_is_hard():
    rows = [row(1, case_no="X-1"), row(2, case_no="x-1 ")]
    rep = W.evaluate(rows, [], None, NOW)
    assert rep["duplicates"]["dup_case_same_source"] == {"FL|fl_laft_pdfs": 1}
    assert any("case_no" in h for h in rep["hard_breaks"])


def test_cross_source_case_duplicate_is_reported_only():
    rows = [row(1, state="TX", case_no="A1", source="laft", source_id="tx_lgbs"),
            row(2, state="TX", case_no="A1", source="auction", source_id="tx_pbfcm", sale_date="2026-12-01")]
    rep = W.evaluate(rows, [], None, NOW)
    assert rep["duplicates"]["dup_case_cross_source"] == {"TX|tx_lgbs+tx_pbfcm": 1}
    assert rep["hard_breaks"] == []


def test_parcel_duplicate_hard_for_available_info_for_certificates():
    avail = [row(1, parcel="12-34"), row(2, parcel="1234")]
    rep = W.evaluate(avail, [], None, NOW)
    assert rep["duplicates"]["dup_parcel_hard"] == {"FL|AVAILABLE|fl_laft_pdfs": 1}
    assert rep["hard_breaks"]
    certs = [row(1, source="certificate", source_id="fl_sarasota_tc_certificates", parcel="9"),
             row(2, source="certificate", source_id="fl_sarasota_tc_certificates", parcel="9")]
    rep = W.evaluate(certs, [], None, NOW)
    assert rep["duplicates"]["dup_parcel_certificates"] == {"FL|LIENS_CERTIFICATES|fl_sarasota_tc_certificates": 1}
    assert rep["hard_breaks"] == []


def test_texas_cause_number_is_not_a_parcel_identity():
    # one tax-suit cause covers several CAD accounts: not a duplicate
    rows = [row(1, state="TX", source_id="tx_lgbs", parcel="CAUSE-1", case_no="ACC1"),
            row(2, state="TX", source_id="tx_lgbs", parcel="CAUSE-1", case_no="ACC2")]
    assert W.evaluate(rows, [], None, NOW)["duplicates"]["dup_parcel_hard"] == {}


def test_past_dated_auctions_threshold_and_grace():
    def auc(i, d):
        return row(i, source="auction", source_id="mi_x", state="MI", sale_date=d)
    within_grace = [auc(i, "2026-11-06") for i in range(40)]
    rep = W.evaluate(within_grace, [], None, NOW)
    assert rep["totals"]["past_sale"] == 40 and rep["past_dated_auctions"] == {} and rep["hard_breaks"] == []
    few = [auc(i, "2026-10-01") for i in range(W.PAST_AUCTION_MAX)]
    assert W.evaluate(few, [], None, NOW)["hard_breaks"] == []
    many = few + [auc(999, "2026-10-01")]
    rep = W.evaluate(many, [], None, NOW)
    assert rep["past_dated_auctions"] == {"MI|mi_x": W.PAST_AUCTION_MAX + 1}
    assert any("past their sale date" in h for h in rep["hard_breaks"])


def test_source_drop_over_half_is_hard_and_small_sources_are_ignored():
    prev = {"sources": {"FL|fl_laft_pdfs": 100, "FL|tiny": 10, "FL|gone": 40}}
    rows = [row(i) for i in range(49)] + [row(100 + i, source_id="tiny") for i in range(2)]
    rep = W.evaluate(rows, [], prev, NOW)
    dropped = {d["source"] for d in rep["source_drops"]}
    assert dropped == {"FL|fl_laft_pdfs", "FL|gone"}
    assert rep["change_vs_previous"]["FL|fl_laft_pdfs"] == {"previous": 100, "current": 49, "change": -51}
    rows = [row(i) for i in range(50)]
    rep = W.evaluate(rows, [], {"sources": {"FL|fl_laft_pdfs": 100}}, NOW)
    assert rep["source_drops"] == [] and rep["hard_breaks"] == []


def test_first_run_has_no_baseline():
    rep = W.evaluate([row(1)], [], None, NOW)
    assert rep["change_vs_previous"]["FL|fl_laft_pdfs"] == {"previous": None, "current": 1}
    assert rep["source_drops"] == []


def test_failing_units_need_48_hours_and_are_not_hard():
    reg = [
        {"state": "FL", "source_id": "a", "last_attempt_status": "FAILED", "last_attempt_at": SEEN,
         "last_success_at": "2026-11-01T00:00:00Z"},
        {"state": "FL", "source_id": "a", "last_attempt_status": "INCOMPLETE", "last_attempt_at": SEEN,
         "last_success_at": None},
        {"state": "FL", "source_id": "b", "last_attempt_status": "FAILED", "last_attempt_at": SEEN,
         "last_success_at": "2026-11-07T20:00:00Z"},
        {"state": "FL", "source_id": "c", "last_attempt_status": "COMPLETE", "last_attempt_at": SEEN},
        {"state": "FL", "source_id": "d", "last_attempt_status": "FAILED", "last_attempt_at": None},
    ]
    rep = W.evaluate([row(1)], reg, None, NOW)
    assert rep["failing_units"] == {"FL|a|FAILED": 1, "FL|a|INCOMPLETE": 1}
    assert rep["hard_breaks"] == []


def test_output_is_counts_only(tmp_path):
    rows = [row(1, parcel="SECRET-PARCEL-77", case_no="SECRET-CASE-88"),
            row(2, parcel="SECRET-PARCEL-77", case_no="SECRET-CASE-88")]
    rows[0]["address"] = "123 SECRET ST"
    rows_file = tmp_path / "rows.json"
    rows_file.write_text(json.dumps(rows))
    out, cache = tmp_path / "out.json", tmp_path / "cache.json"
    code = W.main(["--rows", str(rows_file), "--now", "2026-11-08T15:41:00Z", "--json", str(out), "--cache", str(cache)])
    assert code == 1
    text = out.read_text() + cache.read_text() + W.render(json.loads(out.read_text()))
    for secret in ("SECRET", "123"):
        assert secret not in text
    assert json.loads(cache.read_text())["sources"] == {"FL|fl_laft_pdfs": 2}


def test_main_cache_round_trip(tmp_path):
    cache, out = tmp_path / "c.json", tmp_path / "o.json"
    rows_file = tmp_path / "rows.json"
    rows_file.write_text(json.dumps([row(i) for i in range(40)]))
    assert W.main(["--rows", str(rows_file), "--now", "2026-11-07T15:41:00Z", "--json", str(out), "--cache", str(cache)]) == 0
    rows_file.write_text(json.dumps([row(i) for i in range(10)]))
    assert W.main(["--rows", str(rows_file), "--now", "2026-11-08T15:41:00Z", "--json", str(out), "--cache", str(cache)]) == 1
    assert json.loads(out.read_text())["source_drops"] == [{"source": "FL|fl_laft_pdfs", "previous": 40, "current": 10}]


def test_live_mode_requires_credentials(monkeypatch, tmp_path):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_KEY", raising=False)
    assert W.main(["--json", str(tmp_path / "o.json"), "--no-cache-write"]) == 2


def test_live_reads_page_by_keyset_per_state(monkeypatch):
    calls = []

    def fake_read_all(base, table, headers, params, **kw):
        calls.append((table, dict(params)))
        return []
    monkeypatch.setattr(W.rest_pages, "read_all", fake_read_all)
    W.fetch_live("https://x.supabase.co", "k")
    prop = [p for t, p in calls if t == "properties"]
    assert prop and all(p["state"].startswith("eq.") for p in prop)
    assert all("offset" not in p and "limit" not in p for _, p in calls)
    assert {t for t, _ in calls} == {"properties", "county_source_registry"}
    # the keyset query string is accepted by rest_pages (no clash with paging)
    for _, p in calls:
        W.rest_pages.keyset_query(p, None)


def test_workflow_is_scheduled_with_own_concurrency_and_uploads_evidence_dirs_only():
    yaml = pytest.importorskip("yaml")
    wf = yaml.safe_load((REPO / ".github" / "workflows" / "data-accuracy-watchdog.yml").read_text())
    on = wf.get("on") or wf.get(True)
    assert on["schedule"][0]["cron"] == "41 15 * * *" and "workflow_dispatch" in on
    assert wf["concurrency"]["group"] == "data-accuracy-watchdog"
    steps = wf["jobs"]["watchdog"]["steps"]
    uploads = [s for s in steps if str(s.get("uses", "")).startswith("actions/upload-artifact")]
    assert uploads and all(set(str(s["with"]["path"]).split()) == {"out/public/", "out/private/"} for s in uploads)
    run = next(s for s in steps if "data_accuracy_watchdog.py" in str(s.get("run", "")))
    assert "out/public/data-accuracy.json" in run["run"] and "SUPABASE_SERVICE_KEY" in run["env"]
