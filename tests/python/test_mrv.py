"""MRV - Marc Research Value (owner, 2026-11-25).

* scripts/fetch_rentcast_estimates.py: which rows are looked up, with what,
  within which budget, and which answers are kept - no network here.
* data/source_permissions.csv: RentCast allowed on an interim owner decision,
  Zillow denied until its API is approved.
* migration 045: side table gated on the property's own readability.
* app.js: the median, the references-only bubble, comparables.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(1, str(ROOT))

import fetch_rentcast_estimates as RC  # noqa: E402
from harvesters.governance import permissions as PERM  # noqa: E402

APP = (ROOT / "public" / "app.js").read_text(encoding="utf-8")
M045 = (ROOT / "scripts" / "migrations" / "045_property_value_estimates.sql").read_text(encoding="utf-8")
TODAY = "2026-11-25"


def row(**kw):
    base = {"id": "a1", "state": "FL", "county": "Bay", "source": "laft", "status": "available", "sale_date": None,
            "address": "12 Oak St, Panama City, FL 32401", "latitude": None, "longitude": None}
    base.update(kw)
    return base


def test_lookup_uses_a_full_address_else_the_rows_own_point():
    assert RC.lookup_params(row()) == {"address": "12 Oak St, Panama City, FL 32401"}
    assert RC.lookup_params(row(address="12 Oak St", latitude=30.1, longitude=-85.6)) == {"latitude": "30.100000", "longitude": "-85.600000"}
    assert RC.lookup_params(row(address="12 Oak St")) is None                         # no ZIP, no point: skipped
    assert RC.lookup_params(row(address="Parcel 123", latitude=30.1, longitude=-85.6)) is None   # no street: skipped


def test_only_available_rows_and_upcoming_auctions_never_certificates():
    assert RC.is_candidate(row(), TODAY)
    assert RC.is_candidate(row(source="auction", sale_date="2026-12-01"), TODAY)
    assert not RC.is_candidate(row(source="auction", sale_date="2026-11-01"), TODAY)
    assert not RC.is_candidate(row(source="auction", sale_date=None), TODAY)
    assert not RC.is_candidate(row(source="certificate"), TODAY)
    assert not RC.is_candidate(row(status="closed"), TODAY)


def test_plan_puts_available_first_and_keeps_the_budget_and_the_refresh_window():
    rows = [row(id="auc", source="auction", sale_date="2026-12-01"), row(id="av1"), row(id="av2"), row(id="fresh")]
    stored = {"fresh": "2026-11-20T00:00:00+00:00", "av2": "2026-01-01T00:00:00+00:00"}
    todo = RC.plan(rows, stored, today=TODAY, refresh_before="2026-08-27T00:00:00+00:00", budget=2)
    assert [r["id"] for r in todo] == ["av1", "av2"]        # Available first; a fresh estimate is not looked up again
    assert RC.plan(rows, stored, today=TODAY, refresh_before="2026-08-27T00:00:00+00:00", budget=0) == []


def test_an_estimate_far_from_the_rows_point_or_without_a_price_is_refused():
    r = row(latitude=30.10, longitude=-85.60)
    assert RC.accept(r, {"price": 100000, "latitude": 30.101, "longitude": -85.601}) == (True, "OK")
    assert RC.accept(r, {"price": 100000, "latitude": 30.30, "longitude": -85.60})[1] == "LOCATION_MISMATCH"
    assert RC.accept(r, {"price": 0})[1] == "NO_PRICE"
    assert RC.accept(r, {})[1] == "NO_PRICE"


def test_stored_row_shape():
    out = RC.estimate_row(row(), {"price": 123456.7, "priceRangeLow": 100000, "priceRangeHigh": 0, "comparables": [1, 2]}, "2026-11-25T00:00:00Z")
    assert out["source"] == "rentcast_avm" and out["value"] == 123456.7 and out["value_low"] == 100000 and out["value_high"] is None
    assert out["provenance"] == {"api": "rentcast /v1/avm/value", "lookup": "address", "comparables": 2}


def test_no_key_means_no_lookup(monkeypatch, capsys):
    monkeypatch.delenv("RENTCAST_API_KEY", raising=False)
    assert RC.main([]) == 0
    assert "not set" in capsys.readouterr().out


def test_permissions_rentcast_interim_zillow_denied():
    perms = PERM.Permissions.from_file()
    assert PERM.validate(perms.records) == []
    for op in ("fetch", "store", "display"):
        d = perms.authorize("rentcast_avm", op, state="FL")
        assert d.allowed and d.basis == "INTERIM", (op, d.reason_code)
        assert not perms.authorize("zillow_zestimate", op, state="FL").allowed


def test_migration_045_gates_reads_on_the_propertys_own_readability():
    assert "revoke all on table public.property_value_estimates from anon, authenticated;" in M045
    assert "grant select on table public.property_value_estimates to authenticated;" in M045
    assert "exists (select 1 from public.properties p where p.id = property_value_estimates.property_id)" in M045
    assert "is_approved()" not in M045.split("create policy", 1)[1]
    assert "check (source in ('rentcast_avm', 'zillow_zestimate'))" in M045


def test_frontend_shows_a_median_and_never_an_individual_estimate():
    body = APP[APP.index("function mrvNoteText("):APP.index("function mrvHtml(")]
    assert "mrvMoney(x.value)" not in body and "x.value" not in body          # references only, no figure
    assert "Individual estimates are not shown" in body
    assert "medianOf(parts.map(x => x.value))" in APP
    assert "if (!outside.length && !comps) return null;" in APP                  # county value alone shows no MRV
    assert re.search(r"var MRV_COMPS_MIN = 5", APP)
