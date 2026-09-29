"""scripts/laft_status.py - the per-county LAFT status vocabulary, recorder,
error classification and reader-side STALE/NOT_RUN rules.

Pure unit tests: no network, no harvester run.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
import laft_status as ls  # noqa: E402


# ---------------------------------------------------------------- vocabulary


def test_v01_status_vocabulary_is_exactly_the_six_required_values():
    assert ls.STATUSES == ("COMPLETE", "EMPTY", "INCOMPLETE", "FAILED", "STALE", "NOT_RUN")
    assert ls.CLOSEOUT_ELIGIBLE == {"COMPLETE", "EMPTY"}


def test_v02_amount_kinds_match_the_otc_model():
    from harvesters.otc.model import AmountKind
    assert set(ls.AMOUNT_KINDS) == {k.value for k in AmountKind}
    for label, kind in ls.AMOUNT_KIND_BY_HEADER.items():
        assert kind in ls.AMOUNT_KINDS, label
    assert ls.amount_kind_for_header("opening bid") == "OPENING_BID"
    assert ls.amount_kind_for_header("minimum bid") == "MINIMUM_PURCHASE_AMOUNT"
    assert ls.amount_kind_for_header("amount to purchase") == "FIXED_PURCHASE_PRICE"
    assert ls.amount_kind_for_header("original opening bid") == "ORIGINAL_OPENING_BID"
    assert ls.amount_kind_for_header("something new") == "PUBLISHED_AMOUNT_KIND_UNSPECIFIED"
    assert ls.amount_kind_for_header(None) == "PUBLISHED_AMOUNT_KIND_UNSPECIFIED"


# ---------------------------------------------------------------- CountyStatus rules


def test_c01_a_bare_zero_is_never_empty_and_never_complete():
    with pytest.raises(ValueError):
        ls.CountyStatus(county="X", harvester="h", status="EMPTY").validate()
    with pytest.raises(ValueError):
        ls.CountyStatus(county="X", harvester="h", status="COMPLETE", row_count=0).validate()
    # A cached reuse of previously parsed rows is the one COMPLETE-with-zero-rows exception... and it isn't: cached rows exist.
    ls.CountyStatus(county="X", harvester="h", status="COMPLETE", row_count=3, from_cache=True).validate()


def test_c02_empty_requires_a_named_signal_and_no_rows():
    ls.CountyStatus(county="X", harvester="h", status="EMPTY", empty_signal="empty_marker").validate()
    with pytest.raises(ValueError):
        ls.CountyStatus(county="X", harvester="h", status="EMPTY", empty_signal="vibes").validate()
    with pytest.raises(ValueError):
        ls.CountyStatus(county="X", harvester="h", status="EMPTY", empty_signal="empty_table", row_count=1).validate()


def test_c03_failed_and_incomplete_need_a_category_failed_carries_no_rows():
    with pytest.raises(ValueError):
        ls.CountyStatus(county="X", harvester="h", status="FAILED").validate()
    with pytest.raises(ValueError):
        ls.CountyStatus(county="X", harvester="h", status="INCOMPLETE").validate()
    with pytest.raises(ValueError):
        ls.CountyStatus(county="X", harvester="h", status="FAILED", error_category="TRANSPORT_HTTP_404", row_count=2).validate()
    ls.CountyStatus(county="X", harvester="h", status="INCOMPLETE", error_category="PARSE_COUNT_MISMATCH", row_count=2).validate()


def test_c04_unknown_source_class_or_category_rejected():
    with pytest.raises(ValueError):
        ls.CountyStatus(county="X", harvester="h", status="COMPLETE", row_count=1, source_class="THE_INTERNET").validate()
    with pytest.raises(ValueError):
        ls.CountyStatus(county="X", harvester="h", status="FAILED", error_category="OOPS").validate()


def test_c05_to_json_carries_the_deeds_spelling_row_count_for_source_health():
    d = ls.CountyStatus(county="X", harvester="h", status="COMPLETE", row_count=4).to_json()
    assert d["rowCount"] == 4 and d["row_count"] == 4 and d["status"] == "COMPLETE" and d["county"] == "X"


# ---------------------------------------------------------------- exceptions -> categories, redacted


class _Resp:
    def __init__(self, code):
        self.status_code = code


class _HTTPError(Exception):
    def __init__(self, code, msg):
        super().__init__(msg)
        self.response = _Resp(code)


class ConnectTimeoutError(Exception):
    pass


class ConnectionResetError_(Exception):
    pass


def test_e01_http_codes_map_to_transport_categories_and_drop_the_message():
    secret = "owner Jane Q Private at 123 Hidden Lane parcel 00-11-22"
    for code, cat in ((403, "TRANSPORT_HTTP_403_BLOCKED"), (404, "TRANSPORT_HTTP_404"), (410, "TRANSPORT_HTTP_4XX"), (503, "TRANSPORT_HTTP_5XX")):
        c, detail = ls.describe_exception(_HTTPError(code, secret))
        assert c == cat and str(code) in detail and "Jane" not in detail and "Hidden" not in detail


def test_e02_timeouts_connections_and_categorized_errors():
    assert ls.describe_exception(ConnectTimeoutError("x"))[0] == "TRANSPORT_TIMEOUT"
    assert ls.describe_exception(ConnectionResetError_("x"))[0] == "TRANSPORT_CONNECTION"
    assert ls.describe_exception(ValueError("Expecting value"))[0] == "PARSE_FORMAT_CHANGE"
    assert ls.describe_exception(RuntimeError("?"))[0] == "UNKNOWN"
    c, d = ls.describe_exception(ls.CategorizedError("PROXY_FAILURE", "proxy pool 500 for 1234 Hidden Lane"))
    assert c == "PROXY_FAILURE" and d == "CategorizedError"
    with pytest.raises(ValueError):
        ls.CategorizedError("NOT_A_CATEGORY")


# ---------------------------------------------------------------- recorder + file merge


def test_r01_recorder_writes_and_merges_per_harvester(tmp_path):
    path = tmp_path / "harvest_laft_status.json"
    a = ls.StatusRecorder("fl_laft_pdfs", source_class="GOVERNMENT_DIRECT", parser_version="1", path=path)
    a.complete("Marion", 2, source_url="https://m", document_url="https://m/x.pdf", document_sha256="abc")
    a.empty("Glades", "empty_marker", source_url="https://g", source_class="GOVERNMENT_PLATFORM")
    a.incomplete("Brevard", "PARSE_NO_TABLE", "procedural text only", source_url="https://b")
    a.failed("Hendry", _HTTPError(404, "Not Found: /secret/owner-list"), source_url="https://h")
    a.write()
    b = ls.StatusRecorder("fl_laft_html", source_class="GOVERNMENT_DIRECT", path=path)
    b.failed("Union", ls.CategorizedError("PROXY_FAILURE"), source_url="https://u")
    b.write()
    data = json.loads(path.read_text())
    by = {(e["harvester"], e["county"]): e for e in data}
    assert set(by) == {("fl_laft_pdfs", "Marion"), ("fl_laft_pdfs", "Glades"), ("fl_laft_pdfs", "Brevard"),
                       ("fl_laft_pdfs", "Hendry"), ("fl_laft_html", "Union")}
    h = by[("fl_laft_pdfs", "Hendry")]
    assert h["status"] == "FAILED" and h["error_category"] == "TRANSPORT_HTTP_404" and h["transport_ok"] is False
    assert "secret" not in json.dumps(data) and "owner-list" not in json.dumps(data)
    assert by[("fl_laft_pdfs", "Glades")]["source_class"] == "GOVERNMENT_PLATFORM"  # per-entry override
    assert by[("fl_laft_pdfs", "Marion")]["document_sha256"] == "abc"
    assert by[("fl_laft_pdfs", "Brevard")]["parse_ok"] is False and by[("fl_laft_pdfs", "Brevard")]["transport_ok"] is True
    # Re-running the PDF harvester replaces only its own entries.
    a2 = ls.StatusRecorder("fl_laft_pdfs", path=path)
    a2.complete("Marion", 1)
    a2.write()
    data = json.loads(path.read_text())
    assert {(e["harvester"], e["county"]) for e in data} == {("fl_laft_pdfs", "Marion"), ("fl_laft_html", "Union")}
    assert "COMPLETE 1" in a2.summary_line()


def test_r02_load_status_never_raises(tmp_path):
    assert ls.load_status(tmp_path / "missing.json") == []
    p = tmp_path / "bad.json"
    p.write_text("{not json")
    assert ls.load_status(p) == []
    p.write_text('{"a": 1}')
    assert ls.load_status(p) == []


# ---------------------------------------------------------------- reader-side rules


def test_s01_effective_status_downgrades_old_or_undated_entries_to_stale():
    now = time.time()
    fresh = {"status": "COMPLETE", "checked_at": ls.now_iso()}
    assert ls.effective_status(fresh, now=now) == "COMPLETE"
    old = {"status": "COMPLETE", "checked_at": "2026-09-20T00:00:00+00:00"}
    assert ls.effective_status(old, now=now) == "STALE"
    assert ls.effective_status({"status": "COMPLETE"}, now=now) == "STALE"
    assert ls.effective_status({"status": "COMPLETE", "checked_at": "yesterday-ish"}, now=now) == "STALE"
    assert ls.effective_status({"status": "WHATEVER", "checked_at": ls.now_iso()}, now=now) == "NOT_RUN"


def test_s02_statuses_by_county_takes_the_weakest_and_adds_not_run():
    t = ls.now_iso()
    entries = [{"county": "A", "harvester": "h1", "status": "COMPLETE", "checked_at": t},
               {"county": "A", "harvester": "h2", "status": "FAILED", "checked_at": t},
               {"county": "B", "harvester": "h1", "status": "EMPTY", "checked_at": t}]
    out = ls.statuses_by_county(entries, expected=[("h1", "A"), ("h3", "C")])
    assert out["A"]["status"] == "FAILED" and out["B"]["status"] == "EMPTY"
    assert out["C"] == {"status": "NOT_RUN", "harvester": "h3", "entry": None}
