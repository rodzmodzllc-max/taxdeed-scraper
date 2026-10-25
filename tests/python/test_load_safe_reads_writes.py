"""Population reads and the state sync survive a loaded database (2026-10-25).

Run 40206132797: the AVAILABLE enrichment's population reads (offset pages)
hit HTTP 500 statement timeouts and the run wrote nothing. Run 40208807557:
one 500-row Michigan upsert batch crossed the 8 s statement timeout and the
whole sync stopped. Reads now page by keyset; a timed-out upsert batch is
retried in halves (rolled back whole, idempotent on its conflict key)."""
from __future__ import annotations

import io
import json
import re
import sys
import urllib.error
from pathlib import Path
from urllib.parse import parse_qs

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

import apply_acquisition_paths as AAP  # noqa: E402
import enrich_available as EA  # noqa: E402
import enrich_statewide_parcels as ESP  # noqa: E402
import rest_pages as RP  # noqa: E402
from scripts import sync_state_inventory as SYNC  # noqa: E402


def _err(status, code=None):
    body = json.dumps({"code": code, "message": "m"}).encode() if code else b""
    return urllib.error.HTTPError("https://x/rest/v1/properties", status, "e", {}, io.BytesIO(body))


# --- keyset reads ----------------------------------------------------------------
def test_enrichment_reader_pages_by_keyset_with_retry(monkeypatch):
    calls, failed = [], {"once": False}

    def fake(url, headers=None, timeout=0):
        q = parse_qs(url.split("?", 1)[1])
        calls.append(q)
        assert "offset" not in q and q["order"] == ["id.asc"]
        if not failed["once"]:
            failed["once"] = True
            raise _err(500, "57014")               # a transient 500 is retried, not fatal
        after = int(q["id"][0][3:]) if "id" in q else -1
        return [{"id": i} for i in range(after + 1, min(after + 1 + 1000, 1500))]
    monkeypatch.setattr(ESP, "http_json", fake)
    monkeypatch.setattr("time.sleep", lambda s: None)
    rows = EA.fetch_rows("https://x", "k", ["LA"])
    assert len(rows) == 1500 and [r["id"] for r in rows] == list(range(1500))
    assert calls[-1]["id"] == ["gt.999"]


def test_acquisition_reader_pages_by_keyset(monkeypatch):
    seen = []

    def fake_read_all(base, table, headers, params, **kw):
        seen.append(params)
        return [{"id": 1}]
    monkeypatch.setattr(RP, "read_all", fake_read_all)
    assert AAP.fetch_rows("https://x", "k", "TX", "tx_lgbs") == [{"id": 1}]
    assert seen[0]["source_id"] == "eq.tx_lgbs" and not ({"order", "limit", "offset"} & set(seen[0]))


def test_no_offset_paging_in_these_readers():
    for name in ("enrich_available.py", "apply_acquisition_paths.py"):
        src = (REPO / "scripts" / name).read_text()
        body = src[src.index("def fetch_rows"):]
        body = body[:body.index("\ndef ", 1)]
        assert "read_all(" in body and not re.search(r"[\"']offset[\"']", body), name


# --- the sync's upsert ---------------------------------------------------------------
def test_a_timed_out_batch_is_retried_in_halves(monkeypatch):
    sent, fail_sizes = [], {500}

    def post(chunk):
        if len(chunk) in fail_sizes:
            fail_sizes.discard(len(chunk))
            raise _err(500, "57014")
        sent.append(len(chunk))
    rows = [{"i": i} for i in range(700)]
    n = SYNC._upsert("https://x", "k", rows, post=post, sleep=lambda s: None)
    assert sent == [250, 250, 200] and n == 3 and sum(sent) == 700


def test_a_rejected_batch_is_never_retried(monkeypatch):
    calls = []

    def post(chunk):
        calls.append(len(chunk))
        raise _err(400, "23502")
    with pytest.raises(SystemExit) as e:
        SYNC._upsert("https://x", "k", [{"i": i} for i in range(10)], post=post, sleep=lambda s: None)
    assert calls == [10] and "HTTP 400 23502" in str(e.value)


def test_a_persistent_timeout_stops_at_the_floor():
    calls = []

    def post(chunk):
        calls.append(len(chunk))
        raise _err(500, "57014")
    with pytest.raises(SystemExit):
        SYNC._upsert("https://x", "k", [{"i": i} for i in range(SYNC.MIN_BATCH * 2)], post=post, sleep=lambda s: None)
    assert calls[0] == SYNC.MIN_BATCH * 2 and calls[1] == SYNC.MIN_BATCH and len(calls) == 2


def test_a_plain_500_without_the_timeout_code_is_final():
    with pytest.raises(SystemExit):
        SYNC._upsert("https://x", "k", [{"i": 1}] * 200, post=lambda c: (_ for _ in ()).throw(_err(500, "XX000")),
                     sleep=lambda s: None)
