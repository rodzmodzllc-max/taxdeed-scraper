"""Tennessee (2026-10-08): the Shelby County Land Bank's ePropertyPlus portal.

The fixture (tests/python/fixtures/tennessee/) carries the LIVE field names
read by the tn_shelby evidence passes with SYNTHETIC values in the live
shapes. The source is collected UNREVIEWED: admins see it labelled; customers
do not until an admin review approves it."""
import dataclasses
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import harvest_expansion as HE  # noqa: E402
import source_publication as SP  # noqa: E402
import sync_state_inventory as SY  # noqa: E402
from harvesters.governance import states  # noqa: E402
from harvesters.ledgers import SOURCE_LEDGERS, Ledger  # noqa: E402
from harvesters.otc.adapters import epropertyplus as EPP, expansion as EX  # noqa: E402
from harvesters.otc.model import AmountKind, InventoryType  # noqa: E402
from harvesters.sources import coordinates as CO  # noqa: E402

AT = datetime(2026, 10, 8, 12, tzinfo=timezone.utc)
FX = ROOT / "tests/python/fixtures/tennessee/tn_shelby_landbank.json"
SID = "tn_shelby_landbank"


def _reg():
    return SP.registry_with_reviews("TN", reviews={})[0]


def _src():
    (src,) = EX.SOURCES["TN"]
    return src


def _pages():
    return json.loads(FX.read_text())


def _fetch(pages):
    def fj(url):
        n = int(url.split("page=")[1].split("&")[0])
        return pages[min(n, len(pages)) - 1]
    return fj


def _run(tmp_path, fixture=FX):
    out = tmp_path / "tn"
    assert HE.main(["--state", "TN", "--fixture", f"{SID}={fixture}", "--out-dir", str(out)]) == 0
    return json.loads((out / "tn_properties_rows.json").read_text()), SY.status_units(out / "harvest_tn_status.json")


def test_tennessee_is_an_activated_county_level_available_state():
    cfg = states.get_state("TN")
    assert states.is_activated("TN") and "TN" in states.PRODUCTION_STATES
    assert cfg.production_inventory_types == frozenset({"", "POST_SALE"})
    ev = states.EXPANSION_EVIDENCE["TN"]
    assert list(ev) == list(states.ACTIVATION_REQUIREMENTS)
    assert "37856396525" in ev["live_source_verified"] and "UNREVIEWED" in ev["governance_approved"]


def test_shelby_is_available_unreviewed_collected_never_published():
    cfg = _src().config
    assert _src().kind == "epropertyplus" and cfg.record_source == "laft" and cfg.inventory_type is InventoryType.POST_SALE
    assert SOURCE_LEDGERS[SID] == {Ledger.AVAILABLE} and EX.PUBLICATION[SID] == ("UNREVIEWED", EX.HELD_AVAILABLE)
    row = _reg()[SID]
    assert row.is_production and row.publication_status == "UNREVIEWED" and row.ledgers == "AVAILABLE"
    assert row.machine_format == "JSON" and row.purchase_url == "" and row.document_url.endswith("getPublishedProperties")
    assert SP.collectable(row, "laft") and not SP.publishable(row)
    assert HE.gate("TN", reg=_reg()) == []
    reg = dict(_reg())
    reg[SID] = dataclasses.replace(reg[SID], publication_status="BLOCKED")
    assert HE.runnable_sources("TN", reg) == ([], [(SID, "BLOCKED")])      # blocked: zero requests


def test_only_the_portals_own_for_sale_and_available_rows_are_read():
    res = EPP.fetch_all(EX.TN_SHELBY_LANDBANK, _fetch(_pages()), retrieved_at=AT)
    assert res.outcome == "COMPLETE" and res.size == res.rows_read == 5
    assert [r.case_no for r in res.records] == ["07001200000010", "0700120000002A"]
    assert res.excluded_status == 3          # SALE COMPLETE, SALE PENDING (even with Y), FOR SALE with N
    a, b = res.records
    assert a.parcel == a.case_no and a.source_status_text == "FOR SALE" and a.land_use == "Residential Vacant"
    assert (a.latitude, a.longitude) == (35.1, -90.0) and a.assessed == 1001.0 and a.tax_year == "2026"
    assert a.amount == 4500.0 and a.amount_kind is AmountKind.PUBLISHED_AMOUNT_KIND_UNSPECIFIED
    assert b.amount is None and b.amount_kind is AmountKind.NOT_PUBLISHED and b.land_use is None and b.latitude is None
    assert a.owner_name is None and "comments" not in json.dumps(a.provenance)   # free text never mapped
    assert a.purchase_url is None


def test_a_short_read_or_bad_page_fails_whole_never_partial():
    pages = _pages()
    short = [dict(pages[0], size=9), dict(pages[1], size=9, rows=[])]
    res = EPP.fetch_all(EX.TN_SHELBY_LANDBANK, _fetch(short), retrieved_at=AT)
    assert res.outcome == "FAILED" and res.records == [] and "read 3 of 9" in res.error_detail
    bad = [pages[0], {"success": False}]
    assert EPP.fetch_all(EX.TN_SHELBY_LANDBANK, _fetch(bad), retrieved_at=AT).outcome == "FAILED"
    renamed = [dict(pages[0], rows=[{k.replace("currentStatus", "status"): v for k, v in r.items()} for r in pages[0]["rows"]])]
    res = EPP.fetch_all(EX.TN_SHELBY_LANDBANK, _fetch(renamed), retrieved_at=AT)
    assert res.outcome == "FAILED" and res.error_category == "PARSE_FORMAT_CHANGE"

    def boom(url):
        raise ConnectionError("synthetic")
    assert EPP.fetch_all(EX.TN_SHELBY_LANDBANK, boom, retrieved_at=AT).error_category == "TRANSPORT_CONNECTION"


def test_no_offered_row_is_the_portals_own_empty():
    pages = [{"success": True, "size": 1, "rows": [dict(_pages()[0]["rows"][2])]}]
    res = EPP.fetch_all(EX.TN_SHELBY_LANDBANK, _fetch(pages), retrieved_at=AT)
    assert res.outcome == "EMPTY" and res.records == []


def test_rows_sync_labelled_unreviewed_and_close_only_after_a_trusted_read(tmp_path):
    rows, units = _run(tmp_path)
    assert units == {"Shelby": "COMPLETE"} and len(rows) == 2
    r = rows[0]
    assert r["inventory_status_raw"] == "FOR SALE" and r["purchase_amount_kind"] == "PUBLISHED_AMOUNT_KIND_UNSPECIFIED"
    sent, counts = SY.plan("TN", rows, _reg(), units)
    assert counts["upsert"] == 2 and {s["publication_status"] for s in sent} == {"UNREVIEWED"}
    assert {s["ledger_type"] for s in sent} == {"buy"}
    gone = {"id": "x", "state": "TN", "status": "active", "harvester_source": SID, "source": "laft", "county": "Shelby",
            "case_no": "NO-LONGER-LISTED"}
    assert [c["status"] for c in SY.plan_close("TN", rows, [gone], {"Shelby": "COMPLETE"}, {SID})] == ["closed"]
    assert SY.plan_close("TN", rows, [gone], {"Shelby": "FAILED"}, {SID}) == []


def test_coordinates_are_the_land_banks_own_points():
    assert CO.SOURCE_COORDINATES[SID][:2] == ("LAND_BANK_GIS", "POINT")
    js = (ROOT / "public/app.js").read_text()
    assert 'tn_shelby_landbank: ["LAND_BANK_GIS", "POINT"]' in js


def test_workflow_collects_tn_and_validates_it_read_only():
    wf = (ROOT / ".github/workflows/harvest-and-sync.yml").read_text()
    assert "state: [MI, WY, SC, CO, WI, MO, OK, PA, MN, TN]" in wf
    assert 'for st in MI SC TN; do python3 scripts/harvest_expansion.py' in wf
