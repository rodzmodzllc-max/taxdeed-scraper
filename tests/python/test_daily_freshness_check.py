"""Daily freshness verification (scripts/daily_freshness_check.py)."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import daily_freshness_check as d  # noqa: E402

WORKFLOW = (ROOT / ".github" / "workflows" / "harvest-and-sync.yml").read_text(encoding="utf-8")


class FakeApi:
    """(state, source_id) -> (active, fresh, newest)."""

    def __init__(self, data):
        self.data = data
        self.calls = []

    def _key(self, p):
        return p["state"][3:], p["source_id"][3:]

    def count(self, p):
        self.calls.append(("count", dict(p)))
        active, fresh, _ = self.data.get(self._key(p), (0, 0, None))
        return fresh if "last_seen_at" in p else active

    def newest(self, p):
        return self.data.get(self._key(p), (0, 0, None))[2]


NOW = datetime(2026, 10, 25, 17, 0, tzinfo=timezone.utc)


def test_classify():
    assert d.classify("x", 10, 10) == d.FRESH
    assert d.classify("x", 10, 3) == d.PARTIAL
    assert d.classify("x", 10, 0) == d.STALE
    assert d.classify("x", 0, 0) == d.NO_ROWS
    for sid in d.MANUAL_ONLY_SOURCES:
        assert d.classify(sid, 10, 0) == d.MANUAL


def test_check_and_report():
    api = FakeApi({("FL", "a"): (5, 5, "2026-10-25T10:00:00Z"), ("FL", "b"): (4, 0, None),
                   ("TX", "tx_lgbs"): (9, 0, "2026-10-02T00:00:00Z")})
    res = d.check(api, [("FL", "a"), ("FL", "b"), ("TX", "tx_lgbs"), ("MI", "c")], now=NOW, stale_hours=36)
    status = {r["source_id"]: r["status"] for r in res}
    assert status == {"a": d.FRESH, "b": d.STALE, "tx_lgbs": d.MANUAL, "c": d.NO_ROWS}
    fresh_calls = [p for k, p in api.calls if "last_seen_at" in p]
    assert all(p["last_seen_at"] == "gte.2026-10-24T05:00:00Z" for p in fresh_calls)
    assert all(p["status"] == "eq.active" for _, p in api.calls)
    rep = d.report(res, at="t", stale_hours=36)
    assert rep["stale_sources"] == ["FL:b"]
    assert "| FL | `b` | STALE | 0 / 4 | never |" in d.markdown(rep)


def test_count_of():
    assert d.count_of("0-0/123") == 123
    assert d.count_of("*/0") == 0
    with pytest.raises(ValueError):
        d.count_of(None)
    with pytest.raises(ValueError):
        d.count_of("0-0/*")


def test_production_sources_cover_registry_and_skip_candidates():
    src = d.production_sources()
    ids = {s for _, s in src}
    assert {"fl_realauction", "fl_lienhub_certificates", "la_ebr_adjudicated", "tn_shelby_landbank"} <= ids
    assert "al_ador_state_land" not in ids          # registered, not production
    assert not ({"tx_pbfcm", "tx_mvba", "tx_govease", "tx_ctsa"} & ids)


def test_main_exit_codes(tmp_path, monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_KEY", raising=False)
    assert d.main(["--out", str(tmp_path / "x.json")]) == 2

    monkeypatch.setenv("SUPABASE_URL", "https://example.invalid")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "k")
    monkeypatch.setattr(d, "production_sources", lambda: [("FL", "b")])
    monkeypatch.setattr(d, "Api", lambda url, key: FakeApi({("FL", "b"): (4, 0, None)}))
    out = tmp_path / "f.json"
    assert d.main(["--out", str(out)]) == 1
    assert d.main(["--out", str(out), "--no-fail"]) == 0
    rep = json.loads(out.read_text())
    assert rep["stale_sources"] == ["FL:b"] and set(rep["sources"][0]) == {
        "state", "source_id", "active", "fresh", "newest_last_seen_at", "status"}


def test_workflow_runs_it_daily_and_read_only():
    assert "cron: '0 17 * * *'" in WORKFLOW
    block = WORKFLOW.split("\n  freshness:\n", 1)[1].split("\n  evidence:\n", 1)[0]
    assert "github.event.schedule == '0 17 * * *'" in block
    assert "github.event.inputs.job == 'freshness'" in block
    assert "scripts/daily_freshness_check.py" in block
    # verification only: no sync, enrichment or write script runs in this job
    for w in ("sync", "enrich", "geocode", "lifecycle", "--confirm-apply"):
        assert w not in block.replace("daily_freshness_check", "")


def test_other_jobs_ignore_the_new_schedule():
    """Every pre-existing scheduled job names its own cron; none may start at 17:00."""
    for job in ("deeds", "certificates", "laft", "expansion", "backup"):
        block = WORKFLOW.split(f"\n  {job}:\n", 1)[1].split("\n    steps:", 1)[0]
        assert "'0 17 * * *'" not in block
