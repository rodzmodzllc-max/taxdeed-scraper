"""The fair, bounded, resumable enrichment queue (2026-10-10).

Production evidence (read-only, 2026-10-10): 248 address-context rows that the
Census geocoder keeps failing filled 248 of the 250-row budget every run, while
9,759 Missouri rows in the second tier got about two attempts a run. These
tests pin the mechanism that replaces that order: validated limits, a fair
plan per (state, county), a checkpointed cursor that resumes after an
interruption without skipping or repeating, bounded retry of transient
provider failures only, and a write that can never overwrite or double-apply.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import enrichment_queue as EQ  # noqa: E402

SCRIPTS = ROOT / "scripts"


# ------------------------------------------------------------------ limits

def test_env_limit_default_maximum_and_invalid():
    assert EQ.env_limit("X", 250, 1000, env={}) == 250
    assert EQ.env_limit("X", 250, 1000, env={"X": " 600 "}) == 600
    assert EQ.env_limit("X", 250, 1000, env={"X": "1000"}) == 1000
    for bad in ("0", "-5", "1001", "lots", "2.5"):
        with pytest.raises(ValueError):
            EQ.env_limit("X", 250, 1000, env={"X": bad})


def _load(name, monkeypatch, **env):
    monkeypatch.setenv("SUPABASE_URL", "https://example.test")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "not-a-real-key")
    monkeypatch.delenv("GEOCODE_SOURCE_ID", raising=False)
    for k in ("GEOCODE_BATCH_LIMIT", "GEOCODE_PER_UNIT_LIMIT", "GEOCODE_CHECKPOINT", "FLOOD_BATCH_LIMIT",
              "FLOOD_PER_COUNTY_LIMIT", "GEOCODE_DRY_RUN"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, str(v))
    spec = importlib.util.spec_from_file_location(f"_q_{name}", SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_scripts_refuse_an_invalid_or_unbounded_limit(monkeypatch, capsys):
    geo = _load("geocode_properties", monkeypatch)
    assert (geo.BATCH_LIMIT, geo.PER_UNIT_LIMIT, geo.GEOCODE_MAX_BATCH) == (250, 50, 1000)
    flood = _load("enrich_flood_zone", monkeypatch)
    assert (flood.BATCH_LIMIT, flood.PER_COUNTY_LIMIT, flood.FLOOD_MAX_BATCH) == (500, 40, 10000)
    with pytest.raises(SystemExit) as e:
        _load("geocode_properties", monkeypatch, GEOCODE_BATCH_LIMIT="50000")
    assert e.value.code == 2 and "outside 1..1000" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        _load("enrich_flood_zone", monkeypatch, FLOOD_BATCH_LIMIT="abc")
    # The manual enrich job's 9,000 stays inside the ceiling.
    wf = (ROOT / ".github/workflows/harvest-and-sync.yml").read_text()
    assert "FLOOD_BATCH_LIMIT: '9000'" in wf and 9000 <= flood.FLOOD_MAX_BATCH


# ------------------------------------------------------------------ fairness

def test_plan_slices_and_rotation_reach_every_unit():
    units = [(("FL", c), 100) for c in "ABCDEFGH"]
    first = EQ.plan_slices(units, 120, 40)
    assert [u[1] for u, _, _ in first] == ["A", "B", "C"]             # budget < units x per_unit
    nxt = EQ.rotate(units, EQ.unit_key(first[-1][0]))
    assert [u[1] for u, _ in nxt][:3] == ["D", "E", "F"]              # the next run starts after C
    seen = set()
    start = None
    for _ in range(3):
        order = EQ.rotate(units, start)
        plan = EQ.plan_slices(order, 120, 40)
        seen |= {u for u, _, _ in plan}
        start = EQ.unit_key(plan[-1][0])
    assert seen == {u for u, _ in units}                              # every unit within three runs


def test_take_after_walks_then_wraps_once():
    keys = ["1:a", "1:b", "2:c", "2:d"]
    assert EQ.take_after(keys, None, 2) == ["1:a", "1:b"]
    assert EQ.take_after(keys, "1:b", 3) == ["2:c", "2:d", "1:a"]
    assert EQ.take_after(keys, "2:d", 9) == keys                      # wrap, never a key twice
    assert EQ.take_after([], None, 3) == [] and EQ.take_after(keys, None, 0) == []


def test_checkpoint_is_atomic_and_a_bad_file_starts_from_the_top(tmp_path):
    p = tmp_path / "c" / "ck.json"
    ck = EQ.Checkpoint(p)
    ck.advance(("MO", "St. Louis City"), "2:x")
    ck.set_next_unit("MO|St. Louis City")
    again = EQ.Checkpoint(p)
    assert again.cursor(("MO", "St. Louis City")) == "2:x" and again.data["next_unit"] == "MO|St. Louis City"
    assert not list(p.parent.glob("*.tmp"))
    p.write_text("{not json")
    assert EQ.Checkpoint(p).cursor(("MO", "St. Louis City")) is None
    assert EQ.Checkpoint(None).cursor(("MO", "X")) is None            # no path: nothing persisted


# ------------------------------------------------------------------ the geocoder

class _R:
    def __init__(self, body, status=200):
        self._b, self.status_code, self.text = body, status, ""

    def json(self):
        return self._b

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError(f"HTTP {self.status_code}")


def _match(lat, lng, state, county):
    return {"matchedAddress": "M", "coordinates": {"x": lng, "y": lat}, "addressComponents": {"state": state},
            "geographies": {"Counties": [{"BASENAME": county, "NAME": f"{county} County"}]}}


class Fake:
    """PostgREST + Census fake. `tier1` / `tier2` rows are served by the
    address-context filter; keyset `id=gt.` is honoured; a written row leaves
    the pool (latitude is no longer NULL)."""

    def __init__(self, geo, monkeypatch, tier1, tier2, census, fail_census=None):
        self.geo, self.tier1, self.tier2, self.census = geo, tier1, tier2, census
        self.written, self.patch_urls, self.census_calls = {}, [], []
        self.fail_census = fail_census or {}
        monkeypatch.setattr(geo.requests, "get", self.get)
        monkeypatch.setattr(geo.requests, "patch", self.patch)
        monkeypatch.setattr(geo.time, "sleep", lambda *_: None)

    def get(self, url, headers=None, params=None, timeout=None):
        if "rest/v1/properties" in url:
            rows = self.tier2 if self.geo.ADDRESS_NO_CONTEXT_FILTER in params.get("and", "") else self.tier1
            rows = sorted((r for r in rows if r["id"] not in self.written), key=lambda r: r["id"])
            if "id" in params:
                rows = [r for r in rows if r["id"] > params["id"][3:]]
            return _R(rows[: int(params["limit"])])
        import urllib.parse
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)["address"][0]
        self.census_calls.append(q)
        if self.fail_census.get(q):
            return _R({}, self.fail_census[q].pop(0)) if self.fail_census[q] else _R({"result": {"addressMatches": self.census.get(q, [])}})
        return _R({"result": {"addressMatches": self.census.get(q, [])}})

    def patch(self, url, headers=None, json=None, timeout=None):
        rid = url.split("id=eq.")[1].split("&")[0]
        self.patch_urls.append(url)
        assert rid not in self.written, "duplicate write"
        self.written[rid] = json
        return _R(None, 204)


def _fl_junk(n):
    return [{"id": f"f{i:04d}", "address": f"JUNK {i}, NOWHERE", "county": "Lee", "state": "FL"} for i in range(n)]


def _mo(n):
    return [{"id": f"m{i:05d}", "address": f"{100 + i} MAIN ST", "county": "St. Louis City", "state": "MO"} for i in range(n)]


def _mo_census(rows):
    return {f"{r['address']}, MO": [_match(38.6, -90.2, "MO", "St. Louis city")] for r in rows}


def test_failing_context_rows_no_longer_starve_the_second_tier(monkeypatch, tmp_path):
    geo = _load("geocode_properties", monkeypatch, GEOCODE_CHECKPOINT=tmp_path / "ck.json")
    mo = _mo(500)
    census = _mo_census(mo)
    # Census answers St. Louis City with its NAME "St. Louis city".
    for q in census:
        census[q][0]["geographies"]["Counties"][0].update(BASENAME="St. Louis", NAME="St. Louis city")
    fake = Fake(geo, monkeypatch, _fl_junk(248), mo, census)
    geo.main()
    # Before: about 2 Missouri attempts a run behind 248 failing rows. Now the
    # budget is shared round robin: 100 Missouri rows, 150 Florida rows.
    assert len(fake.written) == 100 and len(fake.census_calls) == 250
    assert all(u.endswith("&latitude=is.null") for u in fake.patch_urls)


def test_an_interrupted_run_resumes_after_the_last_finished_row(monkeypatch, tmp_path):
    ck = tmp_path / "ck.json"
    geo = _load("geocode_properties", monkeypatch, GEOCODE_CHECKPOINT=ck, GEOCODE_BATCH_LIMIT=10, GEOCODE_PER_UNIT_LIMIT=10)
    rows = _fl_junk(30)                                   # never match: the cursor alone decides progress
    fake = Fake(geo, monkeypatch, rows, [], {})
    calls = {"n": 0}
    real = geo.geocode_one

    def boom(*a, **k):
        calls["n"] += 1
        if calls["n"] == 4:
            raise KeyboardInterrupt                       # the workflow is cancelled mid-row
        return real(*a, **k)
    monkeypatch.setattr(geo, "geocode_one", boom)
    with pytest.raises(KeyboardInterrupt):
        geo.main()
    first = list(fake.census_calls)
    assert len(first) == 3                                # rows 0-2 finished; row 3 interrupted
    monkeypatch.setattr(geo, "geocode_one", real)
    geo.main()
    second = fake.census_calls[3:]
    assert second[0] == "JUNK 3, NOWHERE, FL"             # resumes AT the unfinished row
    assert len(second) == 10 and not set(first) & set(second)
    geo.main()                                            # the next batch continues, no repeats
    third = fake.census_calls[13:]
    assert third[0] == "JUNK 13, NOWHERE, FL" and not set(third) & set(first + second)
    assert json.loads(ck.read_text())["units"]["FL|Lee"] == "1:f0022"


def test_unmatched_rows_wrap_only_after_a_full_pass_and_matches_are_not_repeated(monkeypatch, tmp_path):
    geo = _load("geocode_properties", monkeypatch, GEOCODE_CHECKPOINT=tmp_path / "ck.json", GEOCODE_BATCH_LIMIT=4)
    rows = [{"id": f"r{i}", "address": f"{i} OAK ST, LEE", "county": "Lee", "state": "FL"} for i in range(6)]
    census = {"1 OAK ST, LEE, FL": [_match(26.6, -81.8, "FL", "Lee")]}
    fake = Fake(geo, monkeypatch, rows, [], census)
    geo.main()
    geo.main()
    geo.main()
    assert list(fake.written) == ["r1"]                                   # written once
    assert fake.census_calls.count("1 OAK ST, LEE, FL") == 1              # never re-geocoded
    # 5 unmatched rows over 3 runs of 4: each retried only after the pass wrapped.
    assert fake.census_calls[:6] == [f"{i} OAK ST, LEE, FL" for i in (0, 1, 2, 3, 4, 5)][:4] + ["4 OAK ST, LEE, FL", "5 OAK ST, LEE, FL"]


def test_census_transient_failure_is_retried_permanent_failure_is_not(monkeypatch, tmp_path):
    geo = _load("geocode_properties", monkeypatch)
    rows = [{"id": "a", "address": "1 A ST, X", "county": "Lee", "state": "FL"},
            {"id": "b", "address": "2 B ST, X", "county": "Lee", "state": "FL"}]
    census = {"1 A ST, X, FL": [_match(26.6, -81.8, "FL", "Lee")]}
    fake = Fake(geo, monkeypatch, rows, [], census, fail_census={"1 A ST, X, FL": [503], "2 B ST, X, FL": [400, 400, 400]})
    geo.main()
    assert fake.census_calls.count("1 A ST, X, FL") == 2 and "a" in fake.written     # 503 then success
    assert fake.census_calls.count("2 B ST, X, FL") == 1 and "b" not in fake.written # 400: no retry loop


def test_dry_run_reads_but_writes_nothing_and_keeps_no_cursor(monkeypatch, tmp_path):
    ck = tmp_path / "ck.json"
    geo = _load("geocode_properties", monkeypatch, GEOCODE_CHECKPOINT=ck, GEOCODE_DRY_RUN="1")
    rows = [{"id": "a", "address": "1 A ST, X", "county": "Lee", "state": "FL"}]
    fake = Fake(geo, monkeypatch, rows, [], {"1 A ST, X, FL": [_match(26.6, -81.8, "FL", "Lee")]})
    geo.main()
    assert fake.written == {} and not ck.exists()


def test_run_log_reports_budget_and_outcomes(monkeypatch, tmp_path, capsys):
    geo = _load("geocode_properties", monkeypatch, GEOCODE_CHECKPOINT=tmp_path / "ck.json")
    Fake(geo, monkeypatch, _fl_junk(3), [], {})
    geo.main()
    out = capsys.readouterr().out
    assert "budget 250 per run, 50 per unit first" in out and "3 planned across 1 unit(s)" in out
    assert "Verified 0, no match 3" in out and "(of 3 attempted" in out
