"""Five-state enrichment sprint (2026-10-01): lifecycle, freshness and
provenance for the MI / WY / SC / CO / WI adapter records, plus the sources
added on live-read evidence.

Fixtures are SYNTHETIC (live column names and identifier shapes only).
"""
from __future__ import annotations

import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(1, str(REPO / "scripts"))

from harvesters.governance import inventory_status as IS  # noqa: E402
import harvest_expansion as HX  # noqa: E402
import inventory_status_writer as ISW  # noqa: E402
import sync_state_inventory as SY  # noqa: E402

FIX = REPO / "tests/python/fixtures/expansion"
TODAY = date(2026, 10, 1)


def run(state: str, fixtures: dict[str, str], tmp_path: Path) -> list[dict]:
    args = ["--state", state, "--out-dir", str(tmp_path)]
    for sid, name in fixtures.items():
        args += ["--fixture", f"{sid}={FIX / name}"]
    assert HX.main(args) == 0
    return json.loads((tmp_path / f"{state.lower()}_properties_rows.json").read_text())


def _row(**kw) -> dict:
    base = {"id": "1", "state": "MI", "source": "auction", "county": "Eaton", "case_no": "A", "status": "active",
            "harvester_source": "mi_eaton_treasurer_sale", "otc_provenance": {"adapter": "arcgis"}}
    base.update(kw)
    return base


# ==================== 1. inventory status for adapter records ====================

def test_s01_auction_list_presence_and_dates():
    assert IS.status_for_row(_row(), today=TODAY).status == "active"
    up = IS.status_for_row(_row(sale_date="2026-10-22"), today=TODAY)
    assert (up.status, up.basis) == ("upcoming", "SCHEDULED_DATE")
    past = IS.status_for_row(_row(sale_date="2026-09-17"), today=TODAY)
    assert (past.status, past.basis) == ("unknown", "SCHEDULED_DATE")          # a passed date is never a result


def test_s02_sold_only_from_the_sources_own_flag_or_published_price():
    flag = IS.status_for_row(_row(status="closed", inventory_status_raw="Sold: Yes"), today=TODAY)
    assert (flag.status, flag.basis, flag.raw) == ("sold", "SOURCE_STATUS", "Sold: Yes")
    price = IS.status_for_row(_row(status="closed", state="WI", result_amount=12000), today=TODAY)
    assert (price.status, price.basis) == ("sold", "SOURCE_STATUS")
    gone = IS.status_for_row(_row(status="closed"), today=TODAY)
    assert (gone.status, gone.basis) == ("closed", "LIST_PRESENCE")           # absence alone never sold


def test_s03_certificates_listed_then_closed_never_redeemed():
    c = _row(state="CO", source="certificate", otc_provenance={"adapter": "tabular"})
    assert IS.status_for_row(c, today=TODAY).status == "certificate_listed"
    gone = IS.status_for_row(dict(c, status="closed"), today=TODAY)
    assert gone.status == "closed" and gone.status not in IS.RESULT_STATUSES


def test_s04_other_states_and_non_adapter_rows_are_not_touched():
    # FL / TX / AL / LA keep their own mappings; a row with no adapter provenance maps to nothing.
    assert IS.status_for_row(_row(otc_provenance={}), today=TODAY) is None
    assert IS.status_for_row(_row(state="LA", source="laft"), today=TODAY) is None
    fl = IS.status_for_row({"state": "FL", "source": "auction", "status": "active", "sale_date": "2026-12-01"}, today=TODAY)
    assert fl.status == "upcoming" and "auction feed" in fl.note


def test_s05_writer_plans_transitions_for_expansion_rows():
    rows = [_row(id="1", sale_date="2026-10-22"), _row(id="2", status="closed", inventory_status_raw="Sold: Yes"),
            _row(id="3", state="CO", source="certificate", otc_provenance={"adapter": "tabular"}),
            _row(id="4", status="closed", inventory_status="upcoming")]
    changes, counts = ISW.plan(rows, today=TODAY)
    by = {c["id"]: c for c in changes}
    assert by["1"]["status"] == "upcoming" and by["1"]["transition"] == "newly_observed"
    assert by["2"]["status"] == "sold" and by["2"]["transition"] == "newly_observed"
    assert by["3"]["status"] == "certificate_listed"
    assert by["4"]["status"] == "closed" and by["4"]["transition"] == "removed"
    assert counts["results_from_source"] == 1


# ==================== 2. sync: freshness, provenance, key alignment ====================

def test_y01_sync_stamps_last_seen_and_list_provenance(tmp_path):
    rows = run("SC", {"sc_york_tax_sale": "sc_york_page.json"}, tmp_path)
    sent, _ = SY.plan("SC", rows, SY.registry_rows("SC"), {"York": "COMPLETE"}, observed_at="2026-10-01T12:00:00+00:00")
    assert sent and all(r["last_seen_at"] == "2026-10-01T12:00:00+00:00" for r in sent)
    fp = sent[0]["field_provenance"]
    assert fp["owner_name"]["source"] == "county_list" and fp["owner_name"]["source_id"] == "sc_york_tax_sale"
    assert "derived" in fp["latitude"]                                         # centroid of the layer's own polygon, said so
    assert "address" not in fp or not sent[0]["address"].startswith(("Parcel ", "Case "))


def test_y02_enrichment_provenance_survives_and_list_entries_follow_the_list(tmp_path):
    rows = run("CO", {"co_morgan_county_held_certificates": "co_morgan.html"}, tmp_path)
    ident = SY.identity(dict(rows[0], source="certificate"))
    stored = {ident: {"latitude": {"source": "statewide_parcel", "source_id": "co_oit_public_parcels"},
                      "market": {"source": "county_list", "source_id": "co_morgan_county_held_certificates"}}}
    sent, _ = SY.plan("CO", rows, SY.registry_rows("CO"), {"Morgan": "COMPLETE"}, stored_provenance=stored)
    row = next(r for r in sent if SY.identity(r) == ident)
    assert row["field_provenance"]["latitude"]["source"] == "statewide_parcel"   # enrichment entry kept verbatim
    assert row["field_provenance"]["owner_name"]["source"] == "county_list"


def test_y03_rows_are_key_aligned_per_source_so_enriched_values_are_never_nulled(tmp_path):
    rows = run("MI", {"mi_eaton_treasurer_sale": "mi_eaton_page.json", "mi_lenawee_tax_sale": "mi_lenawee_page.json"}, tmp_path)
    sent, _ = SY.plan("MI", rows, SY.registry_rows("MI"), {"Eaton": "COMPLETE", "Lenawee": "COMPLETE"})
    lenawee = [r for r in sent if r["harvester_source"] == "mi_lenawee_tax_sale"]
    eaton = [r for r in sent if r["harvester_source"] == "mi_eaton_treasurer_sale"]
    assert lenawee and eaton
    # Eaton publishes SEV / taxable value; Lenawee does not - so Lenawee rows never SEND those
    # columns (a value another step filled stays), while Eaton rows send them (NULL = the list's blank).
    assert all("assessed" not in r and "taxable_value" not in r for r in lenawee)
    assert all("assessed" in r for r in eaton)
    assert len({tuple(sorted(r)) for r in lenawee}) == 1 and len({tuple(sorted(r)) for r in eaton}) == 1


def test_y04_close_out_stamps_delisted_at_and_never_a_result():
    stored = [{"id": "9", "state": "MI", "source": "auction", "county": "Eaton", "case_no": "Z", "status": "active",
               "harvester_source": "mi_eaton_treasurer_sale"}]
    closes = SY.plan_close("MI", [], stored, {"Eaton": "COMPLETE"}, {"mi_eaton_treasurer_sale"})
    assert closes and closes[0]["status"] == "closed" and closes[0]["delisted_at"]
    assert SY.plan_close("MI", [], stored, {"Eaton": "FAILED"}, {"mi_eaton_treasurer_sale"}) == []


def test_y05_workflow_writes_inventory_status_for_every_expansion_leg():
    wf = (REPO / ".github/workflows/harvest-and-sync.yml").read_text(encoding="utf-8")
    job = wf.split("\n  expansion:\n", 1)[1].split("\n  texas:\n", 1)[0]
    assert "inventory_status_writer.py --state ${{ matrix.state }}" in job
    assert "five_state" in wf and "capture_state_sources.py --five-state --skip-registry" in wf


def test_c01_capture_keeps_process_dates_and_masks_identifiers():
    import capture_state_sources as C
    kept = C.process_text("The sale will be held on Friday, August 7th, 2026 at 9:00 a.m.; call (307) 721-2502.")
    assert "August 7th, 2026" in kept and "(307) 721-2502" in kept
    masked = C.process_text("Parcel 261-1176-90-000 opens at $95,000 on October 6, 2026")
    assert "261-1176-90-000" not in masked and "October 6, 2026" in masked
    assert C.process_text("Account R0012345 is listed") == "Account R9999999 is listed"


# ==================== 3. the sprint's new sources (synthetic fixtures, live columns) ====================

from harvesters.governance import county_source_registry as csr  # noqa: E402
from harvesters.governance import publication as pub  # noqa: E402
from harvesters.otc.adapters import arcgis as AG, expansion as EX  # noqa: E402
from harvesters.otc.adapters.tabular import TabularListAdapter  # noqa: E402
import source_publication as SP  # noqa: E402

T = datetime(2026, 10, 1, 12, tzinfo=timezone.utc)


def _page(name):
    return json.loads((FIX / name).read_text())


def test_n01_douglas_county_held_liens_are_certificates_with_their_sale_date():
    res = AG.fetch_all(EX.CO_DOUGLAS_COUNTY_HELD_LIENS, lambda url: _page("co_douglas_liens_page.json"), retrieved_at=T)
    assert res.outcome == "COMPLETE" and len(res.records) == 2
    r = res.records[0]
    assert r.record_source == "certificate" and r.county == "Douglas" and r.certificate_no == r.case_no == "2023-10001"
    assert r.parcel == "R0000001" and r.tax_year == "2022" and r.issued_date == date(2023, 11, 2)
    assert r.amount_kind.value == "PUBLISHED_AMOUNT_KIND_UNSPECIFIED"          # a principal balance, never a price
    row = r.to_properties_row()
    assert row["source"] == "certificate" and row["issued_date"] == "2023-11-02" and "sale_date" not in row
    # The county-held filter is server-side AND re-checked: an investor-held lien makes the read untrusted.
    bad = _page("co_douglas_liens_page.json")
    bad["features"][1]["attributes"]["type"] = "L"
    res = AG.fetch_all(EX.CO_DOUGLAS_COUNTY_HELD_LIENS, lambda url: bad, retrieved_at=T)
    assert res.outcome == "FAILED" and res.records == []
    assert "type" in AG.query_params(EX.CO_DOUGLAS_COUNTY_HELD_LIENS)["outFields"].split(",")
    assert AG.query_params(EX.CO_DOUGLAS_COUNTY_HELD_LIENS)["where"] == "type = 'CHL'"


def test_n02_douglas_sale_list_cycle_guard_reads_only_the_published_sale_cycle(tmp_path):
    old = AG.fetch_all(EX.CO_DOUGLAS_TAX_SALE_LIST, lambda url: _page("co_douglas_sale_list_2024.json"), retrieved_at=T)
    assert old.outcome == "EMPTY" and old.skipped_cycle == 2 and old.records == []     # last year's list is not current inventory
    new = AG.fetch_all(EX.CO_DOUGLAS_TAX_SALE_LIST, lambda url: _page("co_douglas_sale_list_2025.json"), retrieved_at=T)
    assert new.outcome == "COMPLETE" and {r.sale_date for r in new.records} == {date(2026, 11, 5)}
    r = new.records[0]
    assert r.address is None                         # the layer's Address1 / City are the OWNER's mailing address
    assert r.owner_name and r.legal_desc and r.amount_kind.value == "PUBLISHED_AMOUNT_KIND_UNSPECIFIED"
    assert IS.status_for_row({**r.to_properties_row(), "id": "x"}, today=TODAY).status == "upcoming"
    # Through the runner: an all-past-cycle layer is EMPTY with its own signal.
    import harvest_expansion as HX2
    st, recs, _, _, empty = HX2.run_source(EX.ExpansionSource("arcgis", EX.CO_DOUGLAS_TAX_SALE_LIST, EX.CO_DOUGLAS_TAX_SALE_LIST.layer_url),
                                           None, None, retrieved_at=T, fixture=str(FIX / "co_douglas_sale_list_2024.json"))
    assert (st, recs, empty) == ("EMPTY", [], "past_cycle")


def test_n03_dane_available_and_sold_tables_and_the_rows_own_bid_form():
    html = (FIX / "wi_dane.html").read_text()
    avail = TabularListAdapter(EX.WI_DANE_AVAILABLE).parse_html_table(html, retrieved_at=T)
    assert [r.case_no for r in avail] == ["0000-000-0001-0", "0000-000-0002-0"]
    assert avail[0].sale_date == date(2026, 10, 6) and avail[0].amount == 12500.0 and avail[0].amount_kind.value == "OPENING_BID"
    assert avail[0].purchase_url == "https://treasurer.danecounty.gov/TaxDeedAuction/BidForm/1"
    assert avail[1].purchase_url is None                       # a link to another host is never taken
    sold = TabularListAdapter(EX.WI_DANE_SOLD).parse_html_table(html, retrieved_at=T)
    assert len(sold) == 1 and sold[0].amount == 900.0 and sold[0].result_amount == 1500.0
    row = sold[0].to_properties_row()
    assert row["status"] == "closed" and row["result_amount"] == 1500.0 and row["inventory_status_raw"] == "SOLD"
    assert row.get("purchase_url") is None
    st = IS.status_for_row({**row, "id": "y", "otc_provenance": {"adapter": "tabular"}}, today=TODAY)
    assert (st.status, st.basis, st.raw) == ("sold", "SOURCE_STATUS", "SOLD")


def test_n04_morgan_deed_auctions_and_oconee_placeholder():
    recs = TabularListAdapter(EX.CO_MORGAN_DEED_AUCTIONS).parse_html_table((FIX / "co_morgan_deed_auctions.html").read_text(), retrieved_at=T)
    assert [(r.case_no, r.parcel, r.sale_date) for r in recs] == [("2026001", "R000101", date(2026, 11, 4)), ("2025004", "R000102", date(2026, 6, 17))]
    assert recs[0].record_source == "auction" and recs[0].certificate_no == "2021-00001"
    a = TabularListAdapter(EX.SC_OCONEE)
    assert a.parse_html_table((FIX / "sc_oconee.html").read_text(), retrieved_at=T) == [] and a.empty_statement
    listed = TabularListAdapter(EX.SC_OCONEE).parse_html_table((FIX / "sc_oconee_listed.html").read_text(), retrieved_at=T)
    assert [(r.case_no, r.amount) for r in listed] == [("000-00-00-001", 1234.56)]


def test_n05_albany_superseded_list_reads_not_published_never_listed():
    page = _page("wy_albany_page.json")
    res = AG.fetch_all(EX.WY_ALBANY, lambda url: page, retrieved_at=T)
    row = res.records[0].to_properties_row()
    assert "2027" in row["otc_provenance"]["list_superseded"]
    st = IS.status_for_row({**row, "id": "z"}, today=TODAY)
    assert st.status == "unknown" and "2027" in st.note


# ==================== 4. governance: what may be requested and written ====================

def test_g01_publication_decisions_per_source():
    reg = {r.source_id: r for r in csr.load_registry()}
    approved = {"co_douglas_county_held_liens", "co_douglas_tax_sale_list"} | set(EX.SIX_STATE_SOURCE_IDS)
    gated = {"co_morgan_treasurer_deed_auctions", "wi_dane_tax_deed_auction", "sc_oconee_tax_sale_list"}
    for sid in approved:
        assert SP.publishable(reg[sid]) and pub.publication_problems(reg[sid]) == [], sid
    for sid in ("co_douglas_county_held_liens", "co_douglas_tax_sale_list"):
        assert "Creative Commons Attribution-ShareAlike 4.0" in reg[sid].restrictions
    for sid in gated:
        assert pub.effective_publication(reg[sid]) == "UNREVIEWED" and not SP.publishable(reg[sid]), sid
    assert set(EX.PUBLICATION) == approved | gated


def test_g02_unreviewed_sources_make_no_request_and_write_no_row():
    import harvest_expansion as HX2
    reg, _ = SP.registry_with_reviews("WI", reviews={})
    run, gated = HX2.runnable_sources("WI", reg)
    assert {s.config.source_id for s in run} == {"wi_green_tax_deed_sales"} and gated == [("wi_dane_tax_deed_auction", "UNREVIEWED")]
    rows = [r.to_properties_row() for r in TabularListAdapter(EX.WI_DANE_AVAILABLE).parse_html_table((FIX / "wi_dane.html").read_text(), retrieved_at=T)]
    sent, counts = SY.plan("WI", rows, reg, {"Dane": "COMPLETE"})
    assert sent == [] and counts["withheld_not_publishable"] == 2


def test_g03_an_admin_review_turns_a_source_on_and_an_invalid_one_does_not():
    review = {("WI", "wi_dane_tax_deed_auction"): {"id": 1, "state": "WI", "source_id": "wi_dane_tax_deed_auction",
                                                    "publication_status": "APPROVED", "restrictions": "owner decision (test)",
                                                    "decided_at": "2026-10-01T00:00:00Z"}}
    reg, report = SP.registry_with_reviews("WI", reviews=review)
    assert SP.publishable(reg["wi_dane_tax_deed_auction"]) and "WI/wi_dane_tax_deed_auction" in report["reviews"]["applied"]
    # A review that tries to publish a blocked vendor is refused by the same validator publication_gate uses.
    bad = {("TX", "tx_govease"): {"id": 2, "state": "TX", "source_id": "tx_govease", "publication_status": "APPROVED",
                                  "restrictions": "", "decided_at": "2026-10-01T00:00:00Z"}}
    reg_tx, rep_tx = SP.registry_with_reviews("TX", reviews=bad)
    assert not SP.publishable(reg_tx.get("tx_govease")) and ("TX/tx_govease" in rep_tx["reviews"]["rejected"] or "TX/tx_govease" in rep_tx["reviews"]["unknown_source"])


def test_g04_acquisition_evidence_rows_are_verified_and_anchored():
    import purchase_path_engine as PPE
    ev = PPE.load_evidence(REPO / "data/purchase_path_evidence_expansion.csv")
    by = {e.source_id: e for e in ev}
    for sid in ("mi_eaton_treasurer_sale", "mi_lenawee_tax_sale", "sc_york_tax_sale", "co_douglas_county_held_liens"):
        e = by[sid]
        assert e.applicable and PPE.evidence_problems(e) == [] and e.steps and e.evidence_url.startswith("https://"), sid
    assert by["mi_eaton_treasurer_sale"].address.startswith("Eaton County Governmental Complex")
    assert "Zeus" not in (by["mi_lenawee_tax_sale"].url or "") and "lenawee.mi.us" in by["mi_lenawee_tax_sale"].url
    # A per-parcel bid form keeps its property scope and inherits the source's verified steps.
    row = {"purchase_url": "https://treasurer.danecounty.gov/TaxDeedAuction/BidForm/1", "purchase_url_kind": "bid_form", "status": "active"}
    path, _ = PPE.resolve(row, state="WI", source_id="wi_dane_tax_deed_auction", county="Dane", registry_row=None, evidence=ev,
                          list_url="https://treasurer.danecounty.gov/taxdeedauction", harvest_date="2026-10-01")
    assert path and path.scope == "property" and path.url.endswith("/BidForm/1") and path.steps and path.email == "treasurer@danecounty.gov"
