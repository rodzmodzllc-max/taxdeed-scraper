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
