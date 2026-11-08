"""CO-1 / CO-5 (2026-11-08).

CO-1: Saguache CO's '2026 Tax Sale' ArcGIS layer carries no date and no
cycle attribute, so all its rows were synced with no sale date and read as
upcoming auctions after the county's November 2-4, 2026 lien auction. An
ArcGIS config may now carry the county's own published sale date
(`published_sale_date`, mirroring TabularConfig's); once the read is more
than the grace window past it the layer is a past list (EMPTY past_cycle).

CO-5: a stored active auction row whose sale date has passed, which the
read did not list (Morgan CO: every read since failed), is closed by the
sync's close-out - closed, never sold.

Synthetic features and rows only; no network, no database."""
from __future__ import annotations

import dataclasses
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

from harvesters.otc.adapters import arcgis as AG  # noqa: E402
from harvesters.otc.adapters import expansion as EX  # noqa: E402
import sync_state_inventory as SY  # noqa: E402

CFG = EX.CO_SAGUACHE_TAX_SALE


def _payload(n=3):
    return {"objectIdFieldName": "OBJECTID", "features": [
        {"attributes": {"OBJECTID": i, "TaxSale_Account": f"SYN{i:04d}", "TaxSale_Parcel": f"SYNP{i:04d}",
                        "Legal_Description": "SYNTHETIC LOT", "Total_Due": 100.0 + i, "Deeded_Acres": None}}
        for i in range(1, n + 1)]}


def _read(at):
    return AG.fetch_all(CFG, lambda url: _payload(), retrieved_at=at)


def test_saguache_carries_the_county_published_sale_date():
    assert CFG.published_sale_date[0] == "2026-11-02"
    assert "November 2-4, 2026" in CFG.published_sale_date[1]
    res = _read(datetime(2026, 11, 8, tzinfo=timezone.utc))
    assert res.outcome == "COMPLETE" and len(res.records) == 3
    for r in res.records:
        assert r.sale_date == date(2026, 11, 2)
        assert "November 2-4, 2026" in r.provenance["sale_date"]


def test_a_past_list_reads_empty_past_cycle_never_undated_rows():
    res = _read(datetime(2026, 12, 20, tzinfo=timezone.utc))   # beyond the grace window
    assert res.outcome == "EMPTY" and res.records == [] and res.skipped_cycle == 3


def test_published_sale_date_is_validated():
    with pytest.raises(ValueError):
        dataclasses.replace(CFG, cycle_field="Tax_Year", cycles=(("2025", "2026-11-05"),))
    with pytest.raises(ValueError):
        dataclasses.replace(CFG, record_source="laft")
    with pytest.raises(ValueError):
        dataclasses.replace(CFG, published_sale_date=("2026-11-02", " "))
    with pytest.raises(ValueError):
        dataclasses.replace(CFG, published_sale_date=("not a date", "quote"))


def test_layers_without_the_option_are_unchanged():
    wright = EX.MN_WRIGHT_TAX_FORFEIT
    assert wright.published_sale_date is None


def test_dated_saguache_rows_are_closed_by_the_listed_past_sale_close():
    rows = [r.to_properties_row() for r in _read(datetime(2026, 11, 8, tzinfo=timezone.utc)).records]
    assert all(r["sale_date"] == "2026-11-02" for r in rows)
    sent, counts = SY.plan("CO", rows, SY.registry_rows("CO"), {("co_saguache_tax_sale", "Saguache"): "COMPLETE"},
                           observed_at="2026-11-08T12:00:00+00:00")
    assert counts.get("closed_past_sale") == 3
    assert all(r["status"] == "closed" for r in sent)
    assert all(r.get("result_amount") is None for r in sent)


def _stored(n, sale_date, **kw):
    row = {"id": f"id-{n}", "state": "CO", "source": "auction", "county": "Morgan", "case_no": f"SYN-{n}",
           "status": "active", "harvester_source": "co_morgan_treasurer_deed_auctions", "sale_date": sale_date,
           "result_amount": None, "result_date": None}
    row.update(kw)
    return row


def test_stored_past_sale_rows_close_even_when_the_read_failed():
    sids = {"co_morgan_treasurer_deed_auctions"}
    stored = [_stored(1, "2026-10-28"), _stored(2, "2026-11-18"), _stored(3, "2026-12-16"), _stored(4, None),
              _stored(5, "2026-10-28", result_amount=500), _stored(6, "2026-10-28", harvester_source="other_source"),
              _stored(7, "2026-10-28", source="laft"), _stored(8, "2026-10-28", state="TX")]
    closes = SY.plan_stored_past_sale_close("CO", stored, sids, date(2026, 11, 8))
    assert [c["id"] for c in closes] == ["id-1"]
    assert closes[0]["status"] == "closed" and closes[0]["delisted_at"]


def test_stored_read_selects_the_columns_the_past_sale_close_needs():
    src = (REPO / "scripts" / "sync_state_inventory.py").read_text(encoding="utf-8")
    assert "harvester_source,sale_date,result_amount,result_date" in src
    assert "plan_stored_past_sale_close(args.state, active" in src
