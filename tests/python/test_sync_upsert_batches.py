"""The state sync saves in 200-row batches and retries a timed-out batch in
halves (2026-10-26). Scheduled run 374: one 500-row Michigan batch crossed the
8 s statement timeout (HTTP 500, 57014) and the whole sync stopped. A timed-out
statement is rolled back whole and the upsert is idempotent on its conflict
key, so a retry can neither double-write nor leave half a batch. The retry is
ported from PR #185 (open)."""
from __future__ import annotations

import io
import json
import sys
import urllib.error
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

from scripts import sync_state_inventory as SYNC  # noqa: E402


def _err(status, code=None):
    body = json.dumps({"code": code, "message": "m"}).encode() if code else b""
    return urllib.error.HTTPError("https://x/rest/v1/properties", status, "e", {}, io.BytesIO(body))


def test_batches_are_200_rows():
    assert SYNC.BATCH == 200 and SYNC.MIN_BATCH < SYNC.BATCH
    sent = []
    SYNC._upsert("https://x", "k", [{"i": i} for i in range(450)], post=lambda c: sent.append(len(c)), sleep=lambda s: None)
    assert sent == [200, 200, 50]


def test_a_timed_out_batch_is_retried_in_halves():
    sent, fail = [], [True]

    def post(chunk):
        if len(chunk) == 200 and fail[0]:
            fail[0] = False
            raise _err(500, "57014")
        sent.append(len(chunk))
    n = SYNC._upsert("https://x", "k", [{"i": i} for i in range(500)], post=post, sleep=lambda s: None)
    assert sent == [100, 100, 200, 100] and n == 4 and sum(sent) == 500


def test_a_rejected_batch_is_never_retried():
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
    assert calls == [SYNC.MIN_BATCH * 2, SYNC.MIN_BATCH]


def test_a_plain_500_without_the_timeout_code_is_final():
    with pytest.raises(SystemExit):
        SYNC._upsert("https://x", "k", [{"i": 1}] * 150, post=lambda c: (_ for _ in ()).throw(_err(500, "XX000")),
                     sleep=lambda s: None)
