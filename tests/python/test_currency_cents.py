"""Currency amounts are rounded to whole cents once, at the record -> row
boundary (harvesters/otc/model.py `to_cents`).

Regression for Horry SC (2026-10-09): the FLC workbooks' cells reach the
adapter as floats with representation noise or a third decimal; `bid` is
numeric(12,2) and `purchase_amount` unbounded numeric, so 23 production rows
held the same figure rounded in one column and raw in the other
(|bid - purchase_amount| <= 0.005). Identity (state, source, county, case_no)
and every non-currency field are untouched.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from harvesters.otc.adapters import expansion as EX  # noqa: E402
from harvesters.otc.adapters.tabular import TabularListAdapter  # noqa: E402
from harvesters.otc.model import AmountKind, InventoryType, OtcRecord, SourceAuthority, to_cents  # noqa: E402

T = datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize("raw, cents", [
    (1234.565, 1234.57),                  # third decimal 5 -> rounds up (half away from zero)
    (1234.566, 1234.57),                  # rounds up
    (1234.564, 1234.56),                  # rounds down
    (0.1 + 0.2, 0.3),                     # 0.30000000000000004: representation noise
    (1234.5600000000002, 1234.56),        # noise above
    (1234.5599999999999, 1234.56),        # noise below
    (2.675, 2.68),                        # binary 2.67499999...; repr is '2.675' -> half up, as Postgres does
    (1500.0, 1500.0),                     # whole dollars unchanged
    (1500, 1500.0),                       # an int is accepted
    (0.0, 0.0),
    (None, None),                         # missing stays missing
])
def test_to_cents(raw, cents):
    assert to_cents(raw) == cents


def _rec(**kw) -> OtcRecord:
    base = dict(state="SC", county="Horry", case_no="12345678901", source_id="sc_horry_forfeited_land",
                source_authority=SourceAuthority.GOVERNMENT_DIRECT, inventory_type=InventoryType.POST_SALE,
                retrieved_at=T, parcel="12345678901", amount=1234.565, amount_kind=AmountKind.OPENING_BID,
                list_url="https://example.gov/flc", record_source="laft")
    base.update(kw)
    return OtcRecord(**base)


def test_bid_and_purchase_amount_are_one_rounded_figure():
    row = _rec().to_properties_row()
    assert row["bid"] == row["purchase_amount"] == 1234.57
    assert _rec().to_harvest_row()["bid"] == 1234.57
    # Identity is unchanged by the rounding.
    assert (row["state"], row["source"], row["county"], row["case_no"]) == ("SC", "laft", "Horry", "12345678901")


@pytest.mark.parametrize("raw", [1234.565, 1234.564, 0.1 + 0.2, 1234.5600000000002, 1500.0])
def test_bid_matches_purchase_amount_and_fits_numeric_12_2(raw):
    row = _rec(amount=raw).to_properties_row()
    assert row["bid"] == row["purchase_amount"]
    assert round(row["purchase_amount"], 2) == row["purchase_amount"]


def test_missing_amount_keeps_its_meaning():
    row = _rec(amount=None, amount_kind=AmountKind.NOT_PUBLISHED).to_properties_row()
    assert row["purchase_amount"] is None and row["bid"] == 0
    assert _rec(amount=None, amount_kind=AmountKind.NOT_PUBLISHED).to_harvest_row()["bid"] == ""


def test_auction_min_bid_and_result_amount_rounded_consistently():
    rec = _rec(record_source="auction", inventory_type=None, amount=850.005, amount_kind=AmountKind.OPENING_BID)
    row = rec.to_properties_row()
    assert row["min_bid"] == row["bid"] == 850.01
    closed = _rec(record_source="auction", inventory_type=None, amount=None, amount_kind=AmountKind.NOT_PUBLISHED,
                  result_amount=9100.4999999999).to_properties_row()
    assert closed["result_amount"] == 9100.5


def test_currency_values_rounded_non_currency_fields_untouched():
    rec = _rec(assessed=50000.004, market=60000.005, taxable_value=0.1 + 0.2, land_value=12.345, improvement_value=None,
               acreage=1.23456789, latitude=33.123456789, longitude=-79.987654321, tax_year="2022")
    row = rec.to_properties_row()
    assert (row["assessed"], row["market"], row["taxable_value"], row["land_value"]) == (50000.0, 60000.01, 0.3, 12.35)
    assert "improvement_value" not in row                     # absent stays absent
    assert row["acreage"] == 1.23456789                        # not currency
    assert (row["latitude"], row["longitude"]) == (33.123456789, -79.987654321)
    assert row["tax_year"] == "2022"
    assert row["parcel"] == row["case_no"] == "12345678901"  # identifiers never touched
    h = rec.to_harvest_row()
    assert (h["assessed"], h["market"], h["taxable_value"], h["land_value"]) == (50000.0, 60000.01, 0.3, 12.35)
    assert h["acreage"] == 1.23456789 and h.get("improvement_value") is None


def test_horry_workbook_cell_noise_reaches_both_columns_rounded():
    """The real Horry path: a workbook cell's float text through the tabular adapter."""
    a = TabularListAdapter(EX.SC_HORRY_FLC)
    rows = [["PIN", "ITEM #", "DESCRIPTION", "MINIMUM BID"],
            ["12345678901", "1", "LOT 1", "1234.5650000000001"],
            ["12345678902", "2", "LOT 2", "412.33999999999997"],
            ["12345678903", "3", "LOT 3", "900"]]
    recs = a._records(rows, retrieved_at=T, document_name=None)
    out = [r.to_properties_row() for r in recs]
    assert [(r["case_no"], r["bid"], r["purchase_amount"]) for r in out] == [
        ("12345678901", 1234.57, 1234.57), ("12345678902", 412.34, 412.34), ("12345678903", 900.0, 900.0)]
