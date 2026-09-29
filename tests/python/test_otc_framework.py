"""harvesters/otc/ - the OTC record contract, the run gate, the generic
tabular adapter (fixtures only) and the LGBS bridge."""
from __future__ import annotations

import ast
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

from harvesters.governance.county_source_registry import load_registry, lookup  # noqa: E402
from harvesters.otc import (DB_SUPPORTED_AMOUNT_KINDS, DB_SUPPORTED_INVENTORY_TYPES, AmountKind, InventoryType,  # noqa: E402
                            OtcRecord, PurchaseUrlKind, SourceAuthority, UrlRef)
from harvesters.otc.adapters import TX_CANDIDATES, ColumnMap, TabularConfig, TabularListAdapter  # noqa: E402
from harvesters.otc.adapters.tabular import list_as_of_from_name  # noqa: E402
from harvesters.otc.gate import evaluate_source  # noqa: E402
from harvesters.otc.lgbs_bridge import classify_lgbs_status, lgbs_row_provenance  # noqa: E402
import laft_status as ls  # noqa: E402

T = datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)
ROWS = load_registry()


def _rec(**kw):
    base = dict(state="TX", county="Camp", case_no="A1", source_id="tx_camp_cad", source_authority=SourceAuthority.GOVERNMENT_DIRECT,
                inventory_type=InventoryType.STRUCK_OFF_HELD_IN_TRUST, retrieved_at=T)
    base.update(kw)
    return OtcRecord(**base)


# ---------------------------------------------------------------- model


def test_m01_vocabularies_are_distinct_and_shared():
    # What public.properties can store today (migration 017's constraints)
    # is pinned separately from the model's wider vocabulary: the DB sets
    # are exactly the three / seven original values, and every value the
    # model adds beyond them is NOT in the 017 SQL (a future migration adds
    # it; until then OtcRecord.to_properties_row() refuses it - see m06).
    assert DB_SUPPORTED_INVENTORY_TYPES == {"POST_SALE_FIXED_PRICE", "STRUCK_OFF_HELD_IN_TRUST", "FUTURE_RESALE"}
    assert {i.value for i in InventoryType} == DB_SUPPORTED_INVENTORY_TYPES | {"POST_SALE", "STATE_HELD_TAX_LAND", "ADJUDICATED_PROPERTY"}
    assert {a.value for a in SourceAuthority} == {"GOVERNMENT_DIRECT", "GOVERNMENT_PLATFORM", "VENDOR_COUNSEL", "VENDOR_AUCTION"}
    assert DB_SUPPORTED_AMOUNT_KINDS == {"MINIMUM_PURCHASE_AMOUNT", "OPENING_BID", "ORIGINAL_OPENING_BID", "FIXED_PURCHASE_PRICE",
                                         "ESTIMATED_PURCHASE_PRICE", "PUBLISHED_AMOUNT_KIND_UNSPECIFIED", "NOT_PUBLISHED"}
    assert {k.value for k in AmountKind} == DB_SUPPORTED_AMOUNT_KINDS | {"QUOTED_ON_APPLICATION"}
    assert {k.value for k in AmountKind} == set(ls.AMOUNT_KINDS)
    assert set(ls.DB_AMOUNT_KINDS) == DB_SUPPORTED_AMOUNT_KINDS
    assert {k.value for k in PurchaseUrlKind} == {"purchase_instructions", "offer_form", "bid_form", "application_form", "online_purchase"}
    sql = (REPO / "scripts/migrations/017_otc_inventory_provenance_lifecycle.sql").read_text(encoding="utf-8")
    for enum in (SourceAuthority, PurchaseUrlKind):
        for v in enum:
            assert f"'{v.value}'" in sql, v
    for v in InventoryType:
        assert (f"'{v.value}'" in sql) == (v.value in DB_SUPPORTED_INVENTORY_TYPES), v
    for v in AmountKind:
        assert (f"'{v.value}'" in sql) == (v.value in DB_SUPPORTED_AMOUNT_KINDS), v


def test_m02_amount_rules_no_zero_sentinel_in_the_contract():
    assert _rec().validate() == []
    assert _rec(amount=None, amount_kind=AmountKind.OPENING_BID).validate()
    assert _rec(amount=10.0, amount_kind=AmountKind.NOT_PUBLISHED).validate()
    assert _rec(amount=-1.0, amount_kind=AmountKind.OPENING_BID).validate()
    row = _rec().to_properties_row()
    assert row["purchase_amount"] is None and row["purchase_amount_kind"] == "NOT_PUBLISHED" and row["bid"] == 0
    row = _rec(amount=250.0, amount_kind=AmountKind.MINIMUM_PURCHASE_AMOUNT).to_properties_row()
    assert row["purchase_amount"] == 250.0 and row["bid"] == 250.0
    with pytest.raises(ValueError):
        _rec(amount=None, amount_kind=AmountKind.OPENING_BID).to_properties_row()


def test_m03_url_roles_stay_distinct():
    r = _rec(list_url="https://cad/list", document_url="https://cad/list.pdf", purchase_url="https://cad/offer", purchase_url_kind=PurchaseUrlKind.OFFER_FORM)
    row = r.to_properties_row()
    assert row["list_url"] == "https://cad/list" and row["document_url"] == "https://cad/list.pdf" and row["purchase_url"] == "https://cad/offer"
    assert row["url_auction"] == "https://cad/list" and row["url_auction_kind"] == "county"
    assert _rec(purchase_url="https://cad/list", purchase_url_kind=PurchaseUrlKind.PURCHASE_INSTRUCTIONS, list_url="https://cad/list").validate()
    assert _rec(purchase_url="https://cad/offer").validate()  # kind missing
    assert _rec(list_url="http://cad/list").validate()
    with pytest.raises(ValueError):
        UrlRef("https://x", "homepage")
    with pytest.raises(ValueError):
        UrlRef("http://x", "list")


def test_m04_no_manufactured_dates_or_outcomes():
    r = _rec(list_as_of=T.date())
    assert r.validate()  # as-of == retrieval date without provenance is refused
    r = _rec(list_as_of=date(2026, 6, 2), provenance={"list_as_of": "filename"})
    row = r.to_properties_row()
    assert row["list_as_of"] == "2026-06-02" and row["source_published_at"] is None and row["status"] == "active"
    for forbidden in ("sold", "redeemed", "outcome", "winning", "sale_date"):
        assert forbidden not in row or row[forbidden] is None, forbidden
    assert _rec(inventory_type=None).to_properties_row()["inventory_type"] is None
    assert _rec(source_status_text="Struck off").to_properties_row()["tx_sale_status"] == "Struck off"
    assert _rec(state="FL", county="Marion", source_status_text="x").to_properties_row()["tx_sale_status"] is None


# ---------------------------------------------------------------- tabular adapter (fixtures only)


CFG = TabularConfig(source_id="fixture_tx_camp", state="TX", county="Camp", source_authority=SourceAuthority.GOVERNMENT_DIRECT,
                    inventory_type=InventoryType.STRUCK_OFF_HELD_IN_TRUST,
                    columns=ColumnMap(case_no=("Account", "Account No."), parcel=("Property ID",), address=("Address",), amount=("Minimum Bid",), status=("Status",)),
                    amount_kind=AmountKind.MINIMUM_PURCHASE_AMOUNT, list_url="https://example.invalid/struck-off-list/",
                    list_as_of_pattern=r"(\d{1,2}\.\d{1,2}\.\d{4})")


def test_t01_csv_and_html_tables_produce_the_same_records():
    csv_text = "Account,Property ID,Address,Minimum Bid,Status\nA1,P1,1 Main,\"$1,200.00\",Struck off\nA2,P2,2 Main,,Trust\n,,,,\n"
    html = ("<html><table><tr><td>decoy</td></tr></table><table><tr><th>Account</th><th>Property ID</th><th>Address</th><th>Minimum Bid</th><th>Status</th></tr>"
            "<tr><td>A1</td><td>P1</td><td>1 Main</td><td>$1,200.00</td><td>Struck off</td></tr><tr><td>A2</td><td>P2</td><td>2 Main</td><td></td><td>Trust</td></tr></table></html>")
    ad = TabularListAdapter(CFG)
    a = ad.parse_csv(csv_text, retrieved_at=T, document_name="Camp-Struck-Off-List 3.3.2026.csv")
    b = ad.parse_html_table(html, retrieved_at=T, document_name="Camp-Struck-Off-List 3.3.2026.csv")
    assert [r.as_dict() for r in a] == [r.as_dict() for r in b]
    assert a[0].amount == 1200.0 and a[0].amount_kind is AmountKind.MINIMUM_PURCHASE_AMOUNT and a[0].source_status_text == "Struck off"
    assert a[1].amount is None and a[1].amount_kind is AmountKind.NOT_PUBLISHED
    assert a[0].list_as_of == date(2026, 3, 3) and a[0].provenance["list_as_of"].startswith("parsed from document name")
    assert all(r.validate() == [] for r in a)
    assert ad.parse_csv("Nothing,Here\n1,2\n", retrieved_at=T) == []


def test_t02_list_as_of_never_defaults_to_today():
    assert list_as_of_from_name(None, CFG) is None
    assert list_as_of_from_name("ResaleList.xlsx", CFG) is None
    assert list_as_of_from_name("6.2.2026_Resale_List.pdf", CFG) == date(2026, 6, 2)
    assert list_as_of_from_name("13.45.2026_x.pdf", CFG) is None


def test_t03_adapter_package_never_fetches():
    for path in (REPO / "harvesters/otc").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = [a.name for a in node.names] + ([node.module] if isinstance(node, ast.ImportFrom) and node.module else [])
                for n in names:
                    assert not n.startswith(("requests", "urllib", "http", "playwright", "socket")), f"{path.name} imports {n}"


# ---------------------------------------------------------------- gate


def test_g01_every_texas_candidate_is_refused_and_florida_production_is_allowed():
    for county, fmt, family, blocker in TX_CANDIDATES:
        row = lookup(ROWS, "TX", county, "tx_hctax" if county == "Harris" else "")
        assert row is not None, county
        d = evaluate_source(row)
        assert d.allowed is False and d.layer in ("verification", "vendor_registry"), (county, d)
        assert blocker
    for county, sid in (("Chambers", "tx_pbfcm"), ("Calhoun", "tx_mvba")):
        d = evaluate_source(lookup(ROWS, "TX", county, sid))
        assert d.allowed is False and d.layer == "blocked_vendor"
    d = evaluate_source(lookup(ROWS, "TX", "Harris", "tx_hctax"))
    assert d.allowed is False and d.layer == "vendor_registry" and "LEGAL_REVIEW_REQUIRED" in d.reason
    assert evaluate_source(lookup(ROWS, "FL", "Marion")).allowed is True
    assert evaluate_source(lookup(ROWS, "TX", "Galveston", "tx_lgbs")).allowed is True  # production practice, unchanged
    assert evaluate_source(lookup(ROWS, "FL", "Broward")).allowed is False


# ---------------------------------------------------------------- LGBS bridge == migration rule


def test_l01_lgbs_bridge_matches_migration_017_and_invents_nothing():
    assert classify_lgbs_status("Struck off to Jurisdiction") is InventoryType.STRUCK_OFF_HELD_IN_TRUST
    assert classify_lgbs_status("Available for Future Sale") is InventoryType.FUTURE_RESALE
    assert classify_lgbs_status(None) is None and classify_lgbs_status("") is None and classify_lgbs_status("Sold") is None
    p = lgbs_row_provenance({"tx_sale_status": None, "min_bid": 900, "bid": 900})
    assert p["inventory_type"] is None and p["purchase_amount"] is None and p["purchase_amount_kind"] is None
    assert p["list_url"] is None and p["document_url"] is None and p["purchase_url"] is None
    assert p["source_authority"] == "VENDOR_COUNSEL" and p["source_id"] == "tx_lgbs"
    sql = (REPO / "scripts/migrations/017_otc_inventory_provenance_lifecycle.sql").read_text(encoding="utf-8")
    assert "when 'Struck off to Jurisdiction' then 'STRUCK_OFF_HELD_IN_TRUST'" in sql
    assert "when 'Available for Future Sale' then 'FUTURE_RESALE'" in sql
    body = "\n".join(l for l in sql.splitlines() if not l.strip().startswith("--"))
    i = body.index("harvester_source = 'tx_lgbs'")
    tx_block = body[body.rindex("update public.properties", 0, i):i]
    assert "purchase_amount" not in tx_block and "list_url" not in tx_block and "document_url" not in tx_block


def test_l02_texas_pipeline_untouched_by_this_phase():
    for rel in ("harvesters/texas_harvester.py", "scripts/sync-texas-to-supabase.py"):
        src = (REPO / rel).read_text(encoding="utf-8")
        assert "inventory_type" not in src and "laft_lifecycle" not in src and "county_source_registry" not in src, rel
    wf = (REPO / ".github/workflows/lgbs-acquisition-validation.yml").read_text(encoding="utf-8")
    assert "otc" not in wf.lower().replace("otc", "", 0) or "harvesters/otc" not in wf
