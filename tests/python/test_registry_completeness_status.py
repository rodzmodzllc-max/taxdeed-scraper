"""OK-1 (2026-11-09): county_source_registry.completeness_status kept the
CSV's build-time value (UNKNOWN) on rows with a recorded read, because no
writer owned it after INSERT. unit_freshness's registry PATCH now sends the
last read's verdict; last_checked (the source's verification date) is never
sent. Synthetic units only."""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

import unit_freshness as UF  # noqa: E402

AT = "2026-11-07T17:04:00+00:00"


def _entry(status, *, county="Synthetic", signal=None, rows=5, category=None):
    e = {"state": "OK", "source_id": "ok_synthetic_source", "county": county, "status": status,
         "checked_at": AT, "row_count": rows, "error_category": category, "empty_signal": signal}
    return UF.normalize_entry(e, default_state="OK", default_source=None)


def _body(record, county="Synthetic"):
    units = {UF.unit_key("OK", "ok_synthetic_source", county): {}}
    (match, body), = UF.registry_patches(record, units, error_category=True)
    return body


def test_each_read_status_becomes_the_completeness_status():
    for status in ("COMPLETE", "EMPTY", "INCOMPLETE", "FAILED"):
        record, _ = UF.merge({}, [_entry(status, category="TRANSPORT_TIMEOUT" if status == "FAILED" else None)], at=AT)
        assert _body(record)["completeness_status"] == status


def test_last_checked_is_never_sent():
    record, _ = UF.merge({}, [_entry("COMPLETE", rows=193)], at=AT)
    body = _body(record)
    assert "last_checked" not in body
    assert body["last_success_row_count"] == 193 and body["completeness_status"] == "COMPLETE"


def test_a_superseded_list_leaves_the_stored_completeness_alone():
    record, _ = UF.merge({}, [_entry("EMPTY", signal=UF.SUPERSEDED_SIGNAL, rows=0)], at=AT)
    assert "completeness_status" not in _body(record)
    # A later real read sets it again.
    record, _ = UF.merge(record, [_entry("COMPLETE", rows=3)], at="2026-11-08T00:00:00+00:00")
    assert _body(record)["completeness_status"] == "COMPLETE"


def test_a_unit_with_no_attempt_sends_no_completeness():
    assert UF.completeness_of({"last_attempt_status": None}) is None
    assert UF.completeness_of({}) is None


def test_the_insert_for_a_new_unit_carries_the_read_verdict():
    record, _ = UF.merge({}, [_entry("COMPLETE")], at=AT)
    body = _body(record)
    row = UF.registry_insert_row({"state": "OK", "county": "Synthetic", "source_id": "ok_synthetic_source",
                                  "completeness_status": "UNKNOWN", "last_checked": "2026-10-04"}, body)
    assert row["completeness_status"] == "COMPLETE" and row["last_checked"] == "2026-10-04"


def test_values_are_inside_the_production_check_constraint():
    import sync_registry_to_supabase as S
    for status in UF.ATTEMPT:
        assert status in S.ALLOWED["completeness_status"]
