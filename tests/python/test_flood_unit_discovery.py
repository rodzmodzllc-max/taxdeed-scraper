"""MI-1 (2026-11-08): the FEMA flood step's unit discovery read every
matching row of a state in id order; past Michigan's first page the keyset
read hit the statement timeout (HTTP 500) at the same cursor every run and
the step stopped silently. Units are now found by a loose index scan plus one
bounded count per unit, retried on 5xx, and a failure is a ::warning.
Synthetic data only; no network, no database."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
import requests

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
import enrichment_units as EU  # noqa: E402

ROWS = (
    [{"state": "MI", "county": "Wayne", "flood_checked_at": None, "latitude": 1.0, "longitude": 2.0}] * 5
    + [{"state": "MI", "county": "Oceana", "flood_checked_at": None, "latitude": None, "longitude": None}] * 3
    + [{"state": "MI", "county": "Calhoun", "flood_checked_at": "2026-11-01", "latitude": 1.0, "longitude": 2.0}] * 4
    + [{"state": "MI", "county": "Calhoun", "flood_checked_at": None, "latitude": 1.0, "longitude": 2.0}] * 2
    + [{"state": "MO", "county": "St. Louis City", "flood_checked_at": None, "latitude": 1.0, "longitude": 2.0}] * 2
    + [{"state": "MI", "county": None, "flood_checked_at": None, "latitude": 1.0, "longitude": 2.0}]
)


def _match(row, params):
    for key, val in params.items():
        if key in ("select", "order", "limit"):
            continue
        v = row.get(key)
        if val == "is.null":
            if v is not None:
                return False
            continue
        if val == "not.is.null":
            if v is None:
                return False
            continue
        op, _, arg = val.partition(".")
        if op == "eq" and v != arg:
            return False
        if op == "gt" and (v is None or not v > arg):
            return False
    return True


def fake_get(calls):
    def get(url, params):
        calls.append(dict(params))
        assert "id" not in params, "discovery never pages by id"
        col = params["order"].split(".")[0]
        rows = sorted((r for r in ROWS if _match(r, params)), key=lambda r: r[col])
        return [{col: r[col]} for r in rows][: int(params["limit"])]
    return get


def fake_count(url, params):
    return sum(1 for r in ROWS if _match(r, params))


def test_distinct_values_is_a_loose_scan_one_row_per_request():
    calls = []
    got = EU.distinct_values(fake_get(calls), "u", "county", {"state": "eq.MI", "flood_checked_at": "is.null"})
    assert got == ["Calhoun", "Oceana", "Wayne"]           # a null county is never a unit
    assert all(c["limit"] == "1" for c in calls) and len(calls) == 4


def test_discover_units_counts_only_rows_with_coordinates_and_skips_empty_units():
    units = EU.discover_units(fake_get([]), fake_count, "u", {"flood_checked_at": "is.null"},
                              {"latitude": "not.is.null"}, ["MI"], shuffle=False)
    assert units == [(("MI", "Calhoun"), 2), (("MI", "Wayne"), 5)]


def test_discover_units_finds_states_when_none_given():
    units = EU.discover_units(fake_get([]), fake_count, "u", {"flood_checked_at": "is.null"},
                              {"latitude": "not.is.null"}, [], shuffle=False)
    assert (("MO", "St. Louis City"), 2) in units and len(units) == 3


def test_a_failing_unit_count_is_a_warning_not_a_stop():
    def count(url, params):
        if params.get("county") == "eq.Wayne":
            raise requests.HTTPError("500")
        return fake_count(url, params)
    warnings = []
    units = EU.discover_units(fake_get([]), count, "u", {"flood_checked_at": "is.null"},
                              {"latitude": "not.is.null"}, ["MI"], warn=warnings.append, shuffle=False)
    assert units == [(("MI", "Calhoun"), 2)]
    assert len(warnings) == 1 and warnings[0].startswith("::warning::Wayne, MI")


@pytest.fixture()
def flood(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://example.test")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "not-a-real-key")
    monkeypatch.setenv("ENRICH_STATE", "MI")
    spec = importlib.util.spec_from_file_location("_disc_flood", REPO / "scripts" / "enrich_flood_zone.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_disc_flood"] = mod
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod.time, "sleep", lambda s: None)
    return mod


class _Resp:
    def __init__(self, status, body=None, headers=None):
        self.status_code, self._body, self.headers = status, body, headers or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code}", response=self)

    def json(self):
        return self._body


def test_flood_discovery_end_to_end_with_a_transient_500(flood, monkeypatch):
    calls, failed = [], {"n": 0}
    get = fake_get(calls)

    def req_get(url, headers=None, params=None, timeout=None):
        if params.get("county") == "gt.Calhoun" and not failed["n"]:
            failed["n"] += 1
            return _Resp(500)
        return _Resp(200, get(url, params))

    def req_head(url, headers=None, params=None, timeout=None):
        assert headers["Prefer"] == "count=exact" and "id" not in params
        return _Resp(200, headers={"Content-Range": f"*/{fake_count(url, params)}"})

    monkeypatch.setattr(flood.requests, "get", req_get)
    monkeypatch.setattr(flood.requests, "head", req_head)
    units = sorted(flood.fetch_counties_needing_flood())
    assert units == [(("MI", "Calhoun"), 2), (("MI", "Wayne"), 5)]
    assert failed["n"] == 1                                  # retried, not fatal
    assert all(c.get("state") == "eq.MI" for c in calls)


def test_discovery_failure_is_reported_as_a_warning(flood, monkeypatch, capsys):
    import permission_gate
    monkeypatch.setattr(permission_gate, "allowed", lambda *a, **k: True)
    monkeypatch.setattr(flood, "schema_is_ready", lambda: True)
    monkeypatch.setattr(flood.requests, "get", lambda *a, **k: _Resp(500))
    assert flood.main() == 1
    assert "::warning::flood unit discovery failed" in capsys.readouterr().out
