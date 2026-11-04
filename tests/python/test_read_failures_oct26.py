"""Regression tests for the read failures found in the 2026-10-26 sweep of
harvest-and-sync.yml runs (#376-#383).

1. The deeds job was cancelled at its 60-minute limit inside the FEMA flood
   step (run 381: 36 minutes, 308 of 445 lookups failed, cause not logged).
   The flood step now stops at a wall-clock budget, logs each failure's
   cause, and every deeds enrichment step has its own timeout.
2. Colorado's statewide parcel enrichment lost both counties to one failed
   query each (run 382: matched 0, failed_queries 2; run 380: matched 117).
   A failed query is now retried, and the cause is reported.

Fakes behave like the real servers: requests raises the same exception types
it raises for a timed-out / refused connection, and ArcGIS answers an error
inside an HTTP 200 body.
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest
import requests
import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO))


# ---------------------------------------------------------------------------
# 1. FEMA flood step
# ---------------------------------------------------------------------------

@pytest.fixture()
def flood(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://example.test")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "not-a-real-key")
    spec = importlib.util.spec_from_file_location("_oct26_flood", REPO / "scripts" / "enrich_flood_zone.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_oct26_flood"] = mod
    spec.loader.exec_module(mod)
    return mod


def _raise(exc):
    def get(*a, **k):
        raise exc
    return get


def test_flood_timeout_is_recorded_as_timeout(flood, monkeypatch):
    monkeypatch.setattr(flood.requests, "get", _raise(requests.ReadTimeout("read timed out")))
    attrs, ok = flood.lookup_flood_zone(29.42, -98.49)
    assert (attrs, ok) == (None, False) and flood.LAST_FAILURE == "timeout"


def test_flood_connection_error_is_recorded(flood, monkeypatch):
    monkeypatch.setattr(flood.requests, "get", _raise(requests.ConnectionError("refused")))
    flood.lookup_flood_zone(29.42, -98.49)
    assert flood.LAST_FAILURE == "connection"


def test_flood_http_status_is_recorded(flood, monkeypatch):
    class Resp:
        status_code = 503
        def raise_for_status(self):
            raise requests.HTTPError("503 Server Error", response=self)
    monkeypatch.setattr(flood.requests, "get", lambda *a, **k: Resp())
    flood.lookup_flood_zone(29.42, -98.49)
    assert flood.LAST_FAILURE == "http_503"


def test_flood_arcgis_error_envelope_is_recorded_with_its_code(flood, monkeypatch):
    class Resp:
        status_code = 200
        def raise_for_status(self):
            pass
        def json(self):
            return {"error": {"code": 500, "message": "Unable to complete operation.", "details": []}}
    monkeypatch.setattr(flood.requests, "get", lambda *a, **k: Resp())
    attrs, ok = flood.lookup_flood_zone(29.42, -98.49)
    assert ok is False and flood.LAST_FAILURE == "arcgis_error_500"


def test_flood_success_clears_the_last_failure(flood, monkeypatch):
    flood.LAST_FAILURE = "timeout"
    class Resp:
        status_code = 200
        def raise_for_status(self):
            pass
        def json(self):
            return {"features": []}
    monkeypatch.setattr(flood.requests, "get", lambda *a, **k: Resp())
    assert flood.lookup_flood_zone(29.42, -98.49) == (None, True)
    assert flood.LAST_FAILURE is None


def _wire_main(flood, monkeypatch, rows_per_unit, clock):
    import permission_gate
    monkeypatch.setattr(permission_gate, "allowed", lambda *a, **k: True)
    monkeypatch.setattr(flood, "schema_is_ready", lambda: True)
    units = [("TX", f"County{i}") for i in range(len(rows_per_unit))]
    monkeypatch.setattr(flood, "fetch_counties_needing_flood", lambda: units)
    monkeypatch.setattr(flood, "plan_slices", lambda c: [(u, 1000, None) for u in c])
    monkeypatch.setattr(flood, "fetch_county_batch",
                        lambda unit, limit, outstanding=None: rows_per_unit[units.index(unit)])
    monkeypatch.setattr(flood.EU, "label", lambda unit: f"{unit[1]}, {unit[0]}")
    monkeypatch.setattr(flood.time, "sleep", lambda s: None)
    monkeypatch.setattr(flood.time, "monotonic", clock)
    patched = []
    monkeypatch.setattr(flood, "patch_property", lambda pid, fields: patched.append(pid))
    return patched


def test_flood_stops_at_the_time_budget_and_still_prints_the_summary(flood, monkeypatch, capsys):
    """Each lookup takes 20 'seconds' (a timeout); with a 60 s budget only
    three lookups happen, then the step ends normally - it is never the job
    limit that stops it."""
    t = {"now": 0.0}
    def clock():
        return t["now"]
    def slow_timeout(*a, **k):
        t["now"] += 20.0
        raise requests.ReadTimeout("read timed out")
    rows = [[{"id": f"r{u}{i}", "latitude": 31.5, "longitude": -97.1} for i in range(5)] for u in range(4)]
    _wire_main(flood, monkeypatch, rows, clock)
    monkeypatch.setattr(flood, "TIME_BUDGET_SECONDS", 60.0)
    monkeypatch.setattr(flood.requests, "get", slow_timeout)
    assert flood.main() == 0
    out = capsys.readouterr().out
    assert "Attempted 3." in out
    assert "time budget of 60s spent" in out
    assert "Failed lookups by cause: timeout=3" in out


def test_flood_without_a_budget_is_unbounded_as_before(flood, monkeypatch, capsys):
    t = {"now": 0.0}
    def slow_ok(*a, **k):
        t["now"] += 1000.0
        class Resp:
            status_code = 200
            def raise_for_status(self):
                pass
            def json(self):
                return {"features": [{"attributes": {"FLD_ZONE": "X", "SFHA_TF": "F"}}]}
        return Resp()
    rows = [[{"id": f"r{u}{i}", "latitude": 31.5, "longitude": -97.1} for i in range(3)] for u in range(2)]
    patched = _wire_main(flood, monkeypatch, rows, lambda: t["now"])
    monkeypatch.setattr(flood, "TIME_BUDGET_SECONDS", 0.0)
    monkeypatch.setattr(flood.requests, "get", slow_ok)
    assert flood.main() == 0
    assert len(patched) == 6 and "Attempted 6." in capsys.readouterr().out


def test_flood_streak_line_names_the_cause(flood, monkeypatch, capsys):
    rows = [[{"id": f"r{i}", "latitude": 31.5, "longitude": -97.1} for i in range(12)]]
    _wire_main(flood, monkeypatch, rows, lambda: 0.0)
    monkeypatch.setattr(flood.requests, "get", _raise(requests.ConnectionError("refused")))
    flood.main()
    out = capsys.readouterr().out
    assert "10 consecutive request failures (connection=10)" in out


def _deeds_job():
    wf = yaml.safe_load((REPO / ".github" / "workflows" / "harvest-and-sync.yml").read_text())
    return wf["jobs"]["deeds"]


ENRICH_STEPS = (
    "Backfill geocoding",
    "Backfill address/property-type enrichment",
    "Backfill FEMA flood hazard",
    "Backfill property imagery",
)


def test_every_deeds_enrichment_step_has_its_own_timeout_within_the_job_limit():
    job = _deeds_job()
    steps = {s["name"]: s for s in job["steps"] if "name" in s}
    total = 0
    for prefix in ENRICH_STEPS:
        (step,) = [s for n, s in steps.items() if n.startswith(prefix)]
        assert step.get("continue-on-error") is True, prefix
        assert isinstance(step.get("timeout-minutes"), int), prefix
        total += step["timeout-minutes"]
    # Harvest + sync + Phase B + outcomes took ~15 minutes in run 381; the
    # enrichment steps can never push the job past its own limit.
    assert total + 20 <= job["timeout-minutes"]


def test_deeds_flood_step_stops_before_its_step_timeout():
    job = _deeds_job()
    (step,) = [s for s in job["steps"] if s.get("name", "").startswith("Backfill FEMA flood hazard")]
    budget = float(step["env"]["FLOOD_TIME_BUDGET_SECONDS"])
    assert 0 < budget < step["timeout-minutes"] * 60


# ---------------------------------------------------------------------------
# 2. Statewide parcel enrichment retries a failed query
# ---------------------------------------------------------------------------

def test_statewide_parcel_query_is_retried_after_a_transient_failure():
    from scripts import enrich_statewide_parcels as ESP
    calls = {"n": 0}
    def flaky(url):
        calls["n"] += 1
        if calls["n"] == 1:
            raise TimeoutError("The read operation timed out")
        return {"objectIdFieldName": "OBJECTID", "features": []}
    kinds = {}
    data, ok = ESP._fetch_with_retry(flaky, "https://gis.example/query", 2, lambda s: None, kinds)
    assert ok and data["features"] == [] and kinds == {"timeout": 1} and calls["n"] == 2


def test_statewide_parcel_error_envelope_is_retried_then_reported():
    from scripts import enrich_statewide_parcels as ESP
    envelope = {"error": {"code": 500, "message": "Unable to perform query.", "details": []}}
    calls = {"n": 0}
    def always_error(url):
        calls["n"] += 1
        return envelope
    kinds = {}
    data, ok = ESP._fetch_with_retry(always_error, "https://gis.example/query", 2, lambda s: None, kinds)
    assert not ok and data is None and calls["n"] == 3 and kinds == {"arcgis_error_500": 3}


def test_http_error_cause_is_its_status_code():
    import urllib.error
    from scripts import enrich_statewide_parcels as ESP
    exc = urllib.error.HTTPError("https://gis.example/query", 504, "Gateway Timeout", {}, None)
    assert ESP._query_failure(exc) == "http_504"


def test_run_recovers_a_county_after_one_failed_query_and_reports_the_cause():
    """The Colorado shape: one county, one query, first attempt fails."""
    from scripts import enrich_statewide_parcels as ESP
    from harvesters.enrichment import parcels as P
    from harvesters.enrichment.sources import for_state
    cfg = for_state("CO")
    assert cfg is not None and P.enrichment_allowed(cfg)[0]
    calls = {"n": 0}
    def flaky(url):
        calls["n"] += 1
        if calls["n"] == 1:
            raise TimeoutError("timed out")
        return {"objectIdFieldName": "OBJECTID", "features": []}
    rows = [{"id": "r1", "county": "Douglas", cfg.row_id_column: "R0000001", "field_provenance": {}}]
    rep = ESP.run("CO", rows, flaky, write=None, recorded_at="t", cfg=cfg, retries=2, sleep=lambda s: None)
    assert rep["failed_queries"] == 0 and rep["unmatched"] == 1
    assert rep["query_failures_by_cause"] == {"timeout": 1}


def test_run_default_does_not_retry_so_existing_callers_keep_their_behaviour():
    from scripts import enrich_statewide_parcels as ESP
    from harvesters.enrichment.sources import for_state
    cfg = for_state("CO")
    calls = {"n": 0}
    def boom(url):
        calls["n"] += 1
        raise OSError("down")
    rows = [{"id": "r1", "county": "Douglas", cfg.row_id_column: "R0000001", "field_provenance": {}}]
    rep = ESP.run("CO", rows, boom, write=None, recorded_at="t", cfg=cfg)
    assert rep["failed_queries"] == 1 and calls["n"] == 1


def test_one_failed_batch_costs_only_its_own_rows():
    """Run 405 (2026-10-27): one Detroit batch answered HTTP 404 and every
    Wayne row (31,348) was given up. A failed batch now marks only the rows
    it asked about; the county's other batches still match."""
    import dataclasses
    import urllib.error
    from urllib.parse import parse_qs, urlparse
    from scripts import enrich_statewide_parcels as ESP
    from harvesters.enrichment import sources as S
    cfg = next(v for v in vars(S).values() if getattr(v, "source_id", None) == "mi_detroit_assessor_parcels")
    cfg = dataclasses.replace(cfg, batch_size=2)
    ids = ["01000001.", "01000002.", "01000003.", "01000004."]

    def fetch(url):
        where = parse_qs(urlparse(url).query)["where"][0]
        if "01000001." in where:
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
        asked = [i for i in ids if f"'{i}'" in where]
        return {"features": [{"attributes": {cfg.id_field: i, "year_built": 1925}} for i in asked]}

    rows = [{"id": f"r{n}", "county": "Wayne", cfg.row_id_column: i, "field_provenance": {}} for n, i in enumerate(ids)]
    outcomes, written = {}, {}
    rep = ESP.run("MI", rows, fetch, write=lambda rid, f: written.update({rid: f}), recorded_at="t",
                  cfg=cfg, outcomes=outcomes, sleep=lambda s: None)
    assert rep["failed_queries"] == 1 and rep["matched"] == 2
    assert outcomes["r0"] == outcomes["r1"] == "SOURCE_UNAVAILABLE"
    assert outcomes["r2"] == outcomes["r3"] == "MATCHED"
    assert set(written) == {"r2", "r3"} and written["r2"]["year_built"] == 1925
    assert rep["query_failures_by_cause"] == {"http_404": 1}
