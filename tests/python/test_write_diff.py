"""Write only what changed (scripts/write_diff.py, 2026-10-26 production overload)."""
from __future__ import annotations

import sys
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import stamp_seen  # noqa: E402
import write_diff as W  # noqa: E402

NOW = datetime(2026, 10, 26, 20, 0, tzinfo=timezone.utc)


def iso(dt):
    return dt.isoformat()


def test_same_value_rules():
    assert W.same(12.5, "12.50") and W.same(1000, 1000.0)
    assert W.same("2026-10-26T19:00:00Z", "2026-10-26T19:00:00+00:00")
    assert not W.same("", None) and not W.same("01", "1") and not W.same(True, 1)
    assert W.same({"a": [1, {"b": "x"}]}, {"a": [1.0, {"b": "x"}]})
    assert not W.same({"a": 1}, {"a": 1, "b": None})


def test_unchanged_fresh_row_is_skipped_and_provenance_stamp_ignored():
    stored = {"county": "Wayne", "case_no": "1", "bid": 500, "last_seen_at": iso(NOW - timedelta(hours=2)),
              "field_provenance": {"bid": {"source": "county_list", "recorded_at": "2026-10-26T18:00:00+00:00"}}}
    row = {"county": "Wayne", "case_no": "1", "bid": 500.0, "last_seen_at": iso(NOW),
           "field_provenance": {"bid": {"source": "county_list", "recorded_at": iso(NOW)}}}
    assert W.needs_write(row, stored, NOW) is None


def test_a_layers_row_number_never_makes_a_row_changed():
    """2026-11-11: mi_detroit_landbank_lots - 29,767 rows 'changed' on every read by
    otc_provenance.object_id alone (the publisher renumbers features)."""
    stored = {"case_no": "1", "bid": 500, "last_seen_at": iso(NOW - timedelta(hours=2)),
              "otc_provenance": {"harvester": "mi_detroit_landbank_lots", "object_id": 1001, "layer": "lots"}}
    row = {"case_no": "1", "bid": 500, "last_seen_at": iso(NOW),
           "otc_provenance": {"harvester": "mi_detroit_landbank_lots", "object_id": 48213, "layer": "lots"}}
    assert ("otc_provenance", "object_id") in W.VOLATILE_PATHS
    assert W.unchanged(row, stored) and W.changed_columns(row, stored) == []
    assert W.needs_write(row, stored, NOW) is None
    # A row number that appears or disappears is not a change either ...
    gone = {**row, "otc_provenance": {"harvester": "mi_detroit_landbank_lots", "layer": "lots"}}
    assert W.unchanged(gone, stored)
    # ... but any other key of the same column still is.
    moved = {**row, "otc_provenance": {**row["otc_provenance"], "layer": "structures"}}
    assert not W.unchanged(moved, stored) and W.changed_columns(moved, stored) == ["otc_provenance.layer"]
    assert W.needs_write(moved, stored, NOW) == "changed"


def test_a_coordinate_is_the_same_point_to_six_decimals():
    stored = {"case_no": "1", "latitude": 42.3314271, "longitude": -83.0457538, "last_seen_at": iso(NOW - timedelta(hours=2))}
    jitter = {"case_no": "1", "latitude": 42.33142712, "longitude": "-83.04575379", "last_seen_at": iso(NOW)}
    assert W.unchanged(jitter, stored) and W.changed_columns(jitter, stored) == []
    moved = {"case_no": "1", "latitude": 42.33143, "longitude": -83.0457538}
    assert not W.unchanged(moved, stored) and W.changed_columns(moved, stored) == ["latitude"]
    # A coordinate that appears or is cleared is a change; other numbers keep exact comparison.
    assert not W.unchanged({"case_no": "1", "latitude": None}, stored)
    assert not W.unchanged({"case_no": "1", "latitude": 42.3314271}, {**stored, "latitude": None})
    assert not W.same_column("bid", 500.0000001, 500) and W.same_column("bid", 500.0, "500")


def test_stale_stamp_new_and_changed_rows_are_written():
    old = {"case_no": "1", "bid": 500, "last_seen_at": iso(NOW - timedelta(hours=25))}
    assert W.needs_write({"case_no": "1", "bid": 500, "last_seen_at": iso(NOW)}, old, NOW) == "restamp"
    assert W.needs_write({"case_no": "1", "bid": 500, "last_seen_at": iso(NOW)}, {**old, "last_seen_at": None}, NOW) == "restamp"
    assert W.needs_write({"case_no": "1", "bid": 600}, old, NOW) == "changed"
    assert W.needs_write({"case_no": "1", "extra": None}, old, NOW) == "changed"   # column not on the stored row
    assert W.needs_write({"case_no": "2"}, None, NOW) == "new"
    rows = [{"k": 1, "v": 1, "last_seen_at": iso(NOW)}, {"k": 2, "v": 2, "last_seen_at": iso(NOW)}, {"k": 3, "v": 0}]
    stored = {1: {"k": 1, "v": 1, "last_seen_at": iso(NOW)}, 2: {"k": 2, "v": 9, "last_seen_at": iso(NOW)}}
    out, counts = W.split(rows, stored, lambda r: r["k"], NOW)
    assert [r["k"] for r in out] == [2, 3]
    assert counts == {"new": 1, "changed": 1, "restamp": 0, "unchanged_skipped": 1}


def test_stamp_seen_patch_only_matches_rows_not_stamped_recently():
    cutoff = W.stale_before(NOW)
    url = stamp_seen.patch_urls("https://x.supabase.co", "FL", "auction", {"Lee": ["A-1"]}, stale_before=cutoff)[0]
    q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    assert q["or"] == [f"(last_seen_at.is.null,last_seen_at.lt.{cutoff})"]
    assert "or" not in urllib.parse.parse_qs(urllib.parse.urlparse(
        stamp_seen.patch_urls("https://x.supabase.co", "FL", "auction", {"Lee": ["A-1"]})[0]).query)


def test_state_sync_main_sends_only_changed_rows(monkeypatch, tmp_path):
    import sync_state_inventory as S
    sent = []
    planned = [{"source": "laft", "county": "Wayne", "case_no": str(i), "harvester_source": "s", "bid": i,
                "last_seen_at": iso(NOW)} for i in range(3)]

    def fake_stored(*a, full_out=None, **k):
        full_out.update({("laft", "Wayne", "0"): {**planned[0], "last_seen_at": iso(datetime.now(timezone.utc))},
                         ("laft", "Wayne", "1"): {**planned[1], "bid": 99, "last_seen_at": iso(datetime.now(timezone.utc))}})
        return {}
    rows = tmp_path / "rows.json"
    rows.write_text("[]")
    status = tmp_path / "status.json"
    status.write_text("[]")
    monkeypatch.setenv("SUPABASE_URL", "https://x.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "k")
    monkeypatch.setattr(S, "stored_provenance", fake_stored)
    monkeypatch.setattr(S, "plan", lambda *a, **k: (list(planned), {"upsert": 3}))
    monkeypatch.setattr(S, "upsert", lambda base, key, r: sent.extend(r) or 1)
    monkeypatch.setattr(S.states, "is_activated", lambda st: True)
    import source_publication as SP
    monkeypatch.setattr(SP, "registry_with_reviews", lambda *a, **k: ({}, None))
    assert S.main(["--state", "MI", "--rows", str(rows), "--status", str(status)]) == 0
    assert [r["case_no"] for r in sent] == ["1", "2"]
