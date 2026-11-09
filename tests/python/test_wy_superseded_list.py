"""WY-1 / WY-2 (2026-11-08): a superseded list (Albany WY's finished 2026
sale) is never recorded as a fresh verified-empty read, and the runner warns
when the county publishes a later year's list service.

Synthetic fixtures only: no parcel, owner or address appears here."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO))

import harvest_expansion as HX  # noqa: E402
import unit_freshness as UF  # noqa: E402
from laft_status import StatusRecorder, load_status  # noqa: E402
from harvesters.otc.adapters.expansion import WY_ALBANY  # noqa: E402

AT = "2026-11-08T12:00:00+00:00"


def _entry(status="EMPTY", signal="superseded_list", rows=0):
    return {"state": "WY", "source_id": "wy_albany_tax_sale", "county": "Albany", "status": status,
            "checked_at": AT, "row_count": rows, "error_category": None, "reason": "",
            "empty_signal": signal, "skipped": False}


# ---- WY-1: freshness -----------------------------------------------------------

def test_status_file_entry_carries_the_superseded_signal_into_freshness(tmp_path):
    rec = StatusRecorder("expansion_wy", source_class="GOVERNMENT_DIRECT", source_id="expansion_wy",
                         parser_version="t", path=tmp_path / "s.json", state="WY")
    rec.empty("Albany", "superseded_list", source_url="https://example.invalid/", source_id="wy_albany_tax_sale")
    rec.write()
    entries = [UF.normalize_entry(e, default_state="WY", default_source=None) for e in UF.read_status(tmp_path / "s.json")]
    entries = [e for e in entries if e]
    assert len(entries) == 1 and entries[0]["empty_signal"] == "superseded_list"
    assert load_status(tmp_path / "s.json")  # the file itself is a normal status file


def test_superseded_read_never_advances_last_success():
    prev = {UF.unit_key("WY", "wy_albany_tax_sale", "Albany"): {
        "state": "WY", "source_id": "wy_albany_tax_sale", "county": "Albany",
        "last_attempt_at": "2026-08-01T00:00:00+00:00", "last_attempt_status": "COMPLETE",
        "last_success_at": "2026-08-01T00:00:00+00:00", "last_success_row_count": 253,
        "consecutive_failures": 0, "last_error_category": None}}
    record, counts = UF.merge(prev, [_entry()], at=AT)
    u = record[UF.unit_key("WY", "wy_albany_tax_sale", "Albany")]
    assert u["last_success_at"] == "2026-08-01T00:00:00+00:00"   # unchanged
    assert u["last_success_row_count"] == 253                     # unchanged, never 0
    assert u["last_attempt_at"] == AT and u["last_attempt_status"] == "EMPTY"  # close-out status kept
    assert u["last_error_category"] == UF.SUPERSEDED_CATEGORY
    assert counts["succeeded"] == 0 and counts["superseded"] == 1 and counts["failed"] == 0


def test_superseded_never_read_has_no_success_timestamp():
    record, _ = UF.merge({}, [_entry()], at=AT)
    u = next(iter(record.values()))
    assert u["last_success_at"] is None and u["last_success_row_count"] is None
    # The registry patch never sends a NULL success over a stored one.
    patches = UF.registry_patches(record, {UF.unit_key("WY", "wy_albany_tax_sale", "Albany"): {}}, error_category=True)
    body = patches[0][1]
    assert "last_success_at" not in body and "last_success_row_count" not in body
    assert body["last_attempt_status"] == "EMPTY" and body["last_error_category"] == "SUPERSEDED_LIST"


def test_a_real_empty_read_is_still_a_success():
    record, counts = UF.merge({}, [_entry(signal="empty_layer")], at=AT)
    u = next(iter(record.values()))
    assert u["last_success_at"] == AT and u["last_success_row_count"] == 0 and u["last_error_category"] is None
    assert counts["succeeded"] == 1 and counts["superseded"] == 0


def test_a_later_real_read_clears_the_superseded_category():
    record, _ = UF.merge({}, [_entry()], at=AT)
    record, _ = UF.merge(record, [_entry(status="COMPLETE", signal=None, rows=12)], at="2027-08-01T00:00:00+00:00")
    u = next(iter(record.values()))
    assert u["last_error_category"] is None and u["last_success_row_count"] == 12


def test_customer_health_reads_superseded_not_checked_zero():
    now = datetime(2026, 11, 8, 13, tzinfo=timezone.utc)
    unit = {"source_id": "wy_albany_tax_sale", "last_attempt_status": "EMPTY", "last_error_category": "SUPERSEDED_LIST",
            "last_success_at": "2026-11-07T16:56:39+00:00", "last_success_row_count": 0}
    assert UF.customer_health(unit, now=now) == {"state": "SUPERSEDED", "checked_zero": False}
    report = UF.public_report({"k": dict(unit, state="WY", county="Albany", ledgers="AUCTIONS")}, {}, at=AT, now=now)
    assert report["units"][0]["superseded"] is True
    assert report["by_ledger"]["AUCTIONS"]["current"] == 0 and report["by_ledger"]["AUCTIONS"]["superseded"] == 1


def test_shared_vectors_cover_superseded():
    cases = json.loads((REPO / "tests/python/fixtures/source_health_cases.json").read_text())["cases"]
    assert sum(1 for c in cases if c["state"] == "SUPERSEDED") >= 2
    assert "SUPERSEDED" in UF.CUSTOMER_HEALTH_STATES


# ---- WY-2: next-list discovery -------------------------------------------------

LISTING = {"services": [
    {"name": "2024_TAXSALEPROP_1ST", "type": "FeatureServer"},
    {"name": "2025TAXSALEPROP_1ST", "type": "FeatureServer"},
    {"name": "2026TAXSALEPROP_1ST", "type": "FeatureServer"},
    {"name": "2026TAXSALEPROP_1STC", "type": "FeatureServer"},
    {"name": "Roads", "type": "FeatureServer"},
]}


def test_albany_config_names_a_successor_pattern():
    assert WY_ALBANY.superseded and WY_ALBANY.successor_service_pattern
    assert HX.services_root(WY_ALBANY.layer_url) == "https://services1.arcgis.com/EmwrhKkmuQhTATzU/arcgis/rest/services"


def test_no_later_year_published_yet():
    assert HX.newer_services(WY_ALBANY, LISTING) == []


def test_a_later_year_service_is_reported(capsys):
    listing = {"services": LISTING["services"] + [{"name": "2027TAXSALEPROP_1ST", "type": "FeatureServer"},
                                                  {"name": "folder/2027_TAXSALEPROP_2ND", "type": "FeatureServer"}]}
    asked = []

    def fj(url):
        asked.append(url)
        return listing
    newer = HX.successor_check(WY_ALBANY, fj)
    assert newer == ["2027TAXSALEPROP_1ST", "2027_TAXSALEPROP_2ND"]
    assert asked == ["https://services1.arcgis.com/EmwrhKkmuQhTATzU/arcgis/rest/services?f=json"]  # names only, one request
    out = capsys.readouterr().out
    assert "::warning" in out and "2027TAXSALEPROP_1ST" in out


def test_discovery_failure_is_never_fatal(capsys):
    def boom(url):
        raise OSError("down")
    assert HX.successor_check(WY_ALBANY, boom) is None
    assert "next-list check not done" in capsys.readouterr().out


def test_superseded_read_itself_still_makes_no_request():
    from harvesters.otc.adapters.expansion import SOURCES
    src = next(s for s in SOURCES["WY"] if s.config is WY_ALBANY)

    def no_request(*_a, **_k):
        raise AssertionError("a superseded list is never requested")
    out = HX.run_source(src, no_request, no_request, retrieved_at=datetime.now(timezone.utc), fetch_bytes=no_request)
    assert out == ("EMPTY", [], None, None, "superseded_list")


def test_runner_calls_the_successor_check_for_a_superseded_list():
    src = (REPO / "scripts/harvest_expansion.py").read_text(encoding="utf-8")
    assert 'if empty == "superseded_list" and not fixtures:\n            successor_check(cfg, fetch_json)' in src
