"""2026-10-27 operations: the FEMA flood step's backoff and spreading, the
nightly per-state flood slices in harvest-and-sync.yml, and the paced
last_seen_at re-stamps (scripts/write_diff.py). No network, no database."""
from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import requests
import yaml

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
import write_diff as WD  # noqa: E402

WF = REPO / ".github" / "workflows" / "harvest-and-sync.yml"


@pytest.fixture()
def flood(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://example.test")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "not-a-real-key")
    spec = importlib.util.spec_from_file_location("_ops_flood", REPO / "scripts" / "enrich_flood_zone.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_ops_flood"] = mod
    spec.loader.exec_module(mod)
    return mod


class _Ok:
    status_code = 200

    def raise_for_status(self):
        pass

    def json(self):
        return {"features": [{"attributes": {"FLD_ZONE": "X", "SFHA_TF": "F"}}]}


def _wire(flood, monkeypatch, slices, get):
    import permission_gate
    monkeypatch.setattr(permission_gate, "allowed", lambda *a, **k: True)
    monkeypatch.setattr(flood, "schema_is_ready", lambda: True)
    units = [u for u, _ in slices]
    monkeypatch.setattr(flood, "fetch_counties_needing_flood", lambda: units)
    monkeypatch.setattr(flood, "plan_slices", lambda c: [(u, 1000, None) for u in c])
    monkeypatch.setattr(flood, "fetch_county_batch", lambda unit, limit, outstanding=None: dict(slices)[unit][:limit])
    monkeypatch.setattr(flood, "REQUEST_DELAY_SECONDS", 0.0)
    sleeps, patched = [], []
    monkeypatch.setattr(flood.time, "sleep", lambda s: sleeps.append(s))
    monkeypatch.setattr(flood, "patch_property", lambda pid, fields: patched.append(pid))
    monkeypatch.setattr(flood.requests, "get", get)
    return sleeps, patched


def _rows(prefix, n, lat=42.3):
    return [{"id": f"{prefix}{i}", "latitude": lat, "longitude": -83.0} for i in range(n)]


# ------------------------------------------------------------ backoff + spreading

def test_backoff_is_exponential_capped_and_zero_without_failures(flood):
    assert flood.backoff_seconds(0) == 0.0
    assert [flood.backoff_seconds(n, 2, 30) for n in range(1, 7)] == [2, 4, 8, 16, 30, 30]
    assert flood.backoff_seconds(10_000, 2, 30) == 30
    assert flood.backoff_seconds(3, 0, 30) == 0.0


def test_interleave_spreads_counties_and_keeps_every_row_once(flood):
    a, b, c = ("MI", "Wayne"), ("MI", "Saginaw"), ("MI", "Oceana")
    out = list(flood.interleave([(a, [1, 2, 3, 4]), (b, [5]), (c, [6, 7])]))
    assert [r for _, r in out] == [1, 5, 6, 2, 7, 3, 4]
    assert sorted(r for _, r in out) == [1, 2, 3, 4, 5, 6, 7]
    assert [r for u, r in out if u == a] == [1, 2, 3, 4]


def test_requests_alternate_between_counties(flood, monkeypatch):
    seen = []

    def get(url, params=None, timeout=None):
        seen.append(params["geometry"])
        return _Ok()

    slices = [(("MI", "Wayne"), _rows("w", 3, 42.3)), (("MI", "Saginaw"), _rows("s", 3, 43.4))]
    _sleeps, patched = _wire(flood, monkeypatch, slices, get)
    assert flood.main() == 0
    assert [g.split(",")[1] for g in seen] == ["42.3", "43.4"] * 3
    assert len(patched) == 6


def test_a_failure_backs_off_before_the_next_request_and_a_success_resets(flood, monkeypatch, capsys):
    answers = iter([requests.ConnectionError("drop"), requests.ConnectionError("drop"), None,
                    requests.ConnectionError("drop"), None])

    def get(url, params=None, timeout=None):
        a = next(answers)
        if a is not None:
            raise a
        return _Ok()

    sleeps, patched = _wire(flood, monkeypatch, [(("MI", "Wayne"), _rows("w", 5))], get)
    monkeypatch.setattr(flood, "BACKOFF_BASE_SECONDS", 2.0)
    monkeypatch.setattr(flood, "BACKOFF_MAX_SECONDS", 30.0)
    assert flood.main() == 0
    # delay is 0 here, so the only non-zero sleeps are the backoff waits
    assert [s for s in sleeps if s] == [2.0, 4.0, 2.0]
    assert len(patched) == 2
    assert "failed 3" in capsys.readouterr().out


def test_backoff_never_outlasts_the_time_budget(flood, monkeypatch):
    t = {"now": 0.0}
    monkeypatch.setattr(flood.time, "monotonic", lambda: t["now"])

    def get(url, params=None, timeout=None):
        t["now"] += 25.0
        raise requests.ConnectionError("drop")

    sleeps, _ = _wire(flood, monkeypatch, [(("MI", "Wayne"), _rows("w", 9))], get)
    monkeypatch.setattr(flood, "TIME_BUDGET_SECONDS", 60.0)
    monkeypatch.setattr(flood, "BACKOFF_BASE_SECONDS", 20.0)
    monkeypatch.setattr(flood, "BACKOFF_MAX_SECONDS", 30.0)
    assert flood.main() == 0
    assert max(s for s in sleeps) <= 60.0 - 25.0


def test_one_failing_county_is_skipped_while_the_others_continue(flood, monkeypatch, capsys):
    def get(url, params=None, timeout=None):
        if params["geometry"].endswith(",42.3"):
            raise requests.ConnectionError("drop")
        return _Ok()

    slices = [(("MI", "Wayne"), _rows("w", 30, 42.3)), (("MI", "Saginaw"), _rows("s", 30, 43.4))]
    _sleeps, patched = _wire(flood, monkeypatch, slices, get)
    monkeypatch.setattr(flood, "COUNTY_MISS_STREAK", 10)
    assert flood.main() == 0
    out = capsys.readouterr().out
    assert "10 consecutive request failures (connection=10)" in out
    assert len(patched) == 30 and all(p.startswith("s") for p in patched)
    assert "Attempted 40." in out


# ------------------------------------------------------------ workflow slices

def _wf():
    return yaml.safe_load(WF.read_text(encoding="utf-8"))


def _flood_step(job):
    (step,) = [s for s in job["steps"] if "enrich_flood_zone.py" in str(s.get("run", ""))]
    return step


@pytest.mark.parametrize("job_name", ["expansion", "texas"])
def test_state_legs_run_a_bounded_flood_slice(job_name):
    job = _wf()["jobs"][job_name]
    step = _flood_step(job)
    env = step["env"]
    assert step.get("continue-on-error") is True
    budget = float(env["FLOOD_TIME_BUDGET_SECONDS"])
    assert 0 < budget < step["timeout-minutes"] * 60
    assert step["timeout-minutes"] + 25 <= job["timeout-minutes"]     # room for the leg's harvest + sync
    assert 0 < int(env["FLOOD_BATCH_LIMIT"]) <= 2000
    assert 0 < int(env["FLOOD_PER_COUNTY_LIMIT"]) <= int(env["FLOOD_BATCH_LIMIT"])
    expected_state = "${{ matrix.state }}" if job_name == "expansion" else "TX"
    assert env["ENRICH_STATE"] == expected_state


def test_the_expansion_matrix_still_runs_one_leg_at_a_time():
    assert _wf()["jobs"]["expansion"]["strategy"]["max-parallel"] == 1


# ------------------------------------------------------------ paced re-stamps

NOW = datetime(2026, 10, 27, 12, 0, tzinfo=timezone.utc)


def _key(r):
    return r["case_no"]


def test_split_restamps_returns_ids_only_for_restamp_rows():
    old = (NOW - timedelta(hours=WD.FRESH_HOURS + 1)).isoformat()
    fresh = (NOW - timedelta(hours=1)).isoformat()
    stored = {
        "a": {"id": 1, "case_no": "a", "bid": 10, "last_seen_at": old},       # unchanged, aged -> restamp
        "b": {"id": 2, "case_no": "b", "bid": 10, "last_seen_at": fresh},     # unchanged, fresh -> skip
        "c": {"id": 3, "case_no": "c", "bid": 10, "last_seen_at": old},       # changed -> full row
        "e": {"case_no": "e", "bid": 10, "last_seen_at": old},                # no id -> full row
    }
    rows = [{"case_no": k, "bid": 11 if k == "c" else 10, "last_seen_at": NOW.isoformat()} for k in "abcde"]
    out, ids, counts = WD.split_restamps(rows, stored, _key, NOW)
    assert ids == [1]
    assert [r["case_no"] for r in out] == ["c", "d", "e"]
    assert counts == {"new": 1, "changed": 1, "restamp": 2, "unchanged_skipped": 1}
    # Same classification as split(): only the shape of the restamp write differs.
    plain, plain_counts = WD.split(rows, stored, _key, NOW)
    assert plain_counts == counts and len(plain) == len(out) + len(ids)


def test_restamp_queries_batch_dedupe_and_never_move_a_stamp_backwards():
    qs = WD.restamp_queries(list(range(450)) + [5], "2026-10-27T12:00:00+00:00", size=200)
    assert len(qs) == 3
    assert qs[0].startswith("id=in.(0,1,") and qs[2].startswith("id=in.(400,")
    assert sum(q.split(")")[0].count(",") + 1 for q in qs) == 450
    for q in qs:
        assert q.endswith("&or=(last_seen_at.is.null,last_seen_at.lt.2026-10-27T12%3A00%3A00%2B00%3A00)")
    with pytest.raises(ValueError):
        WD.restamp_queries([1], "x", size=0)


def test_run_restamps_pauses_between_batches_and_survives_a_failed_batch(capsys):
    sent_queries, sleeps = [], []

    def patch(query, body):
        assert body == {"last_seen_at": "T"}
        if "id=in.(200," in query:
            raise OSError("boom")
        sent_queries.append(query)

    sent, failed = WD.run_restamps(list(range(500)), "T", patch, size=200, pause=0.5, sleep=sleeps.append)
    assert (sent, failed) == (2, 1)
    assert sleeps == [0.5, 0.5]                     # between batches, never before the first
    assert "a re-stamp batch failed (OSError)" in capsys.readouterr().out
    assert WD.run_restamps([], "T", patch, sleep=sleeps.append) == (0, 0)


def test_a_michigan_sized_restamp_is_a_few_hundred_small_requests():
    """~32,000 re-stamps: 160 PATCHes of 200 ids (each URL under 8 KB with
    uuids), not 160 full-row upserts."""
    ids = [f"{i:08x}-0000-4000-8000-000000000000" for i in range(32_000)]
    qs = WD.restamp_queries(ids, "2026-10-27T04:20:00+00:00")
    assert len(qs) == 160
    assert max(len(q) for q in qs) < 8_000


def test_restamp_keeps_the_daily_cadence():
    """The re-stamp rule is unchanged: a row read more than FRESH_HOURS after
    its last stamp is re-stamped on that read, so twice-daily reads keep every
    listed row under 24 h (the 36 h freshness rules never fire for a listed row)."""
    assert WD.FRESH_HOURS < 24
    last = NOW - timedelta(hours=WD.FRESH_HOURS + 0.1)
    row = {"case_no": "a", "bid": 1, "last_seen_at": NOW.isoformat()}
    assert WD.needs_write(row, {"id": 1, "case_no": "a", "bid": 1, "last_seen_at": last.isoformat()}, NOW) == "restamp"
