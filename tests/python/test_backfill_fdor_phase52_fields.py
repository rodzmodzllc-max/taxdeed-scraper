"""scripts/backfill_fdor_phase52_fields.py - fill-only backfill of the Phase 52
FDOR columns on rows stamped before the field expansion.

Contract under test: the dry run never writes; apply writes only the five
target columns, only where still empty at write time, never fdor_enriched_at
or any other column, never a row outside the target predicate; the lookups
and the field mapping are the production module's own.

No network, no database: requests.get / requests.patch are replaced.
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "backfill_fdor_phase52_fields.py"


def load(monkeypatch, tmp_path, mode="dry-run", plan_in=""):
    monkeypatch.setenv("SUPABASE_URL", "https://example.test")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "not-a-real-key")
    monkeypatch.setenv("BACKFILL_MODE", mode)
    monkeypatch.setenv("BACKFILL_PLAN_OUT", str(tmp_path / "plan.json"))
    monkeypatch.setenv("BACKFILL_PLAN_IN", plan_in)
    spec = importlib.util.spec_from_file_location("_backfill_p52", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_backfill_p52"] = mod
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod.time, "sleep", lambda *_: None)
    return mod


class FakeResponse:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status
        self.text = ""

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def row(id_, source, county, parcel, **fields):
    base = {"id": id_, "state": "FL", "source": source, "county": county, "parcel": parcel, "address": "1 A ST",
            "prop_type": "House", "market": 100.0, "assessed": 90.0, "owner_name": "Someone", "latitude": 28.0,
            "longitude": -81.0, "gone_since": None, "fdor_enriched_at": "2026-09-05T00:00:00+00:00",
            "dor_use_code": None, "taxable_value": None, "acreage": None, "land_use": None, "fdor_alt_key": None}
    base.update(fields)
    return base


FDOR_HIT = {"PARCEL_ID": "x", "DOR_UC": 1, "TV_NSD": 12345.0, "LND_SQFOOT": 43560, "PA_UC": "0100",
            "ALT_KEY": "ALT-9", "JV": 150000.0, "LND_VAL": 50000.0, "ACT_YR_BLT": 1990, "S_LEGAL": "LOT 1"}


class Harness:
    """Fake REST + fake FDOR layer. Records every GET and PATCH."""

    def __init__(self, mod, monkeypatch, rows):
        self.rows = {r["id"]: r for r in rows}
        self.patches = []
        self.gets = []

        def fake_get(url, headers=None, params=None, timeout=None):
            params = params or {}
            self.gets.append((url, dict(params)))
            if "rest/v1/properties" in url:
                if params.get("limit") == "0":
                    return FakeResponse([])  # the production module's column-presence probe
                # Every row read must carry the full target predicate.
                assert params.get("state") == "eq.FL"
                assert params.get("gone_since") == "is.null"
                assert params.get("fdor_enriched_at", "").startswith("lt.")
                if "id" in params:
                    rid = params["id"].split("eq.", 1)[1]
                    r = self.rows.get(rid)
                    return FakeResponse([r] if r and r["gone_since"] is None else [])
                off, lim = int(params.get("offset", 0)), int(params.get("limit", 1000))
                return FakeResponse(list(self.rows.values())[off:off + lim])
            if url == mod.prod.FDOR_ENDPOINT:
                where = params["where"]
                if "PARCEL_ID='HIT-" in where:
                    return FakeResponse({"features": [{"attributes": dict(FDOR_HIT), "centroid": {"x": -81.0, "y": 28.0}}]})
                if "PARCEL_ID='THIN-" in where:
                    thin = dict(FDOR_HIT, TV_NSD=None, PA_UC=None, ALT_KEY=None)
                    return FakeResponse({"features": [{"attributes": thin, "centroid": {"x": -81.0, "y": 28.0}}]})
                return FakeResponse({"features": []})
            if url == mod.prod.SANTA_ROSA_GIS_ENDPOINT:
                return FakeResponse({"features": [{"attributes": {"PAR_NUM": "SR-1", "OwnerName": "O", "Addr1": "5 B ST",
                                                                   "City": "MILTON", "Zip5": "32570", "CALC_ACRE": 2.5,
                                                                   "PropertyUs": "SFR"}, "centroid": {"x": -87.0, "y": 30.6}}]})
            raise AssertionError(f"unexpected GET {url}")

        def fake_patch(url, headers=None, json=None, timeout=None):
            rid = url.rsplit("eq.", 1)[1]
            self.patches.append((rid, dict(json)))
            self.rows[rid].update(json)
            return FakeResponse(None, status=204)

        monkeypatch.setattr(mod.requests, "get", fake_get)
        monkeypatch.setattr(mod.requests, "patch", fake_patch)
        monkeypatch.setattr(mod.prod.requests, "get", fake_get)
        monkeypatch.setattr(mod.prod.requests, "patch", fake_patch)


ROWS = [
    row("a1", "auction", "Charlotte", "HIT-1"),                                   # gains all five
    row("a2", "auction", "Lee", "HIT-2", dor_use_code="01"),                        # four gains, one already populated
    row("c1", "certificate", "Duval", "THIN-3"),                                     # match, roll thin: two gains
    row("l1", "laft", "Putnam", "MISS-4"),                                           # no match
    row("s1", "auction", "Santa Rosa", "SR-1"),                                      # fallback path: acreage only
    row("g1", "auction", "Orange", "HIT-5", gone_since="2026-09-10T00:00:00+00:00"),  # gone: outside the predicate
]


def test_dry_run_writes_nothing_and_measures_gains(monkeypatch, tmp_path):
    mod = load(monkeypatch, tmp_path)
    h = Harness(mod, monkeypatch, [r for r in ROWS if r["gone_since"] is None])
    s = mod.run_dry_run()
    assert h.patches == []
    assert s["targets"] == 5 and s["match"] == 4 and s["no_match"] == 1 and s["exception"] == 0
    # a1 gains all five; a2 four (dor_use_code already set); c1 two (thin
    # roll: no TV_NSD / PA_UC / ALT_KEY); s1 acreage only (fallback layer).
    assert s["gain"] == {"dor_use_code": 2, "taxable_value": 2, "acreage": 4, "land_use": 2, "fdor_alt_key": 2}
    assert s["already"]["dor_use_code"] == 1
    assert s["roll_empty"]["taxable_value"] == 2  # THIN row + Santa Rosa fallback
    assert s["by_strategy"] == {"fdor:identity": 3, "santa_rosa_gis:identity": 1}
    assert s["by_ledger"]["laft"]["match"] == 0
    plan = json.load(open(tmp_path / "plan.json"))
    assert {r["id"] for r in plan["rows"]} == {"a1", "a2", "c1", "s1"}


def test_apply_writes_only_planned_empty_target_fields(monkeypatch, tmp_path):
    mod = load(monkeypatch, tmp_path)
    Harness(mod, monkeypatch, [r for r in ROWS if r["gone_since"] is None])
    mod.run_dry_run()
    plan_path = tmp_path / "plan.json"
    mod2 = load(monkeypatch, tmp_path, mode="apply", plan_in=str(plan_path))
    live = [dict(r) for r in ROWS]
    # Between dry run and apply, a1's taxable_value got populated by something
    # else: apply must leave it alone and write the other four.
    live[0]["taxable_value"] = 999.0
    h = Harness(mod2, monkeypatch, live)
    out = mod2.run_apply()
    written = {rid: fields for rid, fields in h.patches}
    assert set(written) == {"a1", "a2", "c1", "s1"}
    assert set(written["a1"]) == {"dor_use_code", "acreage", "land_use", "fdor_alt_key"}
    assert set(written["a2"]) == {"taxable_value", "acreage", "land_use", "fdor_alt_key"}
    assert set(written["c1"]) == {"dor_use_code", "acreage"}
    assert set(written["s1"]) == {"acreage"}
    for fields in written.values():
        assert "fdor_enriched_at" not in fields
        assert set(fields) <= set(mod2.TARGET_FIELDS)
    assert h.rows["a1"]["taxable_value"] == 999.0
    assert out["counts"] == {"dor_use_code": 2, "taxable_value": 1, "acreage": 4, "land_use": 2, "fdor_alt_key": 2}
    assert out["skipped"] == [] and out["errors"] == []


def test_apply_skips_rows_that_left_the_target_population(monkeypatch, tmp_path):
    mod = load(monkeypatch, tmp_path)
    Harness(mod, monkeypatch, [ROWS[0]])
    mod.run_dry_run()
    mod2 = load(monkeypatch, tmp_path, mode="apply", plan_in=str(tmp_path / "plan.json"))
    gone = dict(ROWS[0], gone_since="2026-09-21T00:00:00+00:00")
    h = Harness(mod2, monkeypatch, [gone])
    out = mod2.run_apply()
    assert h.patches == []
    assert out["skipped"][0]["reason"] == "row no longer satisfies the target predicate"


def test_apply_refuses_a_plan_for_a_different_cutoff(monkeypatch, tmp_path):
    mod = load(monkeypatch, tmp_path)
    Harness(mod, monkeypatch, [ROWS[0]])
    mod.run_dry_run()
    plan_path = tmp_path / "plan.json"
    plan = json.load(open(plan_path))
    plan["cutoff"] = "2026-01-01T00:00:00Z"
    json.dump(plan, open(plan_path, "w"))
    mod2 = load(monkeypatch, tmp_path, mode="apply", plan_in=str(plan_path))
    h = Harness(mod2, monkeypatch, [ROWS[0]])
    with pytest.raises(SystemExit):
        mod2.run_apply()
    assert h.patches == []


def test_lookup_exception_is_recorded_not_guessed(monkeypatch, tmp_path):
    mod = load(monkeypatch, tmp_path)
    h = Harness(mod, monkeypatch, [ROWS[0]])

    def boom(*a, **k):
        raise mod.requests.ConnectionError("layer down")

    monkeypatch.setattr(mod.prod, "lookup_fdor", boom)
    s = mod.run_dry_run()
    assert s["exception"] == 1 and s["match"] == 0 and h.patches == []
    assert json.load(open(tmp_path / "plan.json"))["rows"] == []
