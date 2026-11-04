"""Inventory status for every AVAILABLE source and Texas (2026-10-11).

Before this change every `properties` row outside Florida on the AVAILABLE
ledger (54,102 rows across LA, MI, MN, MO, OK, PA, SC, TN, TX on 2026-10-11)
had no inventory_status: status_for_row() sent them to the auction /
certificate adapter rule and returned None. These tests pin the rule that
now maps them, the sources' own "offered" wordings against the adapter
configs they come from, that Florida's mapping is untouched, that absence
is never a result, and the writer's observation source id.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

from harvesters.governance import inventory_status as IS  # noqa: E402
from harvesters.otc.adapters import expansion as EX  # noqa: E402

TODAY = date(2026, 10, 11)
GAP = json.loads((REPO / "data/current_state/inventory-status-gap-2026-10-11.json").read_text(encoding="utf-8"))


def row(**kw) -> dict:
    base = {"state": "MI", "source": "laft", "source_id": "mi_detroit_landbank_lots", "status": "active",
            "inventory_status": None, "inventory_status_raw": None, "otc_provenance": {"adapter": "arcgis"}}
    base.update(kw)
    return base


# ---- 1. the offered-wording table is the adapter configs, nothing more ----

def _cfg(source_id: str):
    for srcs in EX.SOURCES.values():
        for s in srcs:
            if s.config.source_id == source_id:
                return s.config
    raise AssertionError(source_id)


def test_offered_wordings_are_pinned_to_the_adapter_configs():
    assert set(IS.AVAILABLE_OFFERED_WORDINGS["mi_detroit_landbank_lots"]) == set(EX.DLBA_LOT_STATUSES + EX.DLBA_STRUCTURE_STATUSES)
    assert IS.AVAILABLE_OFFERED_WORDINGS["mo_stl_lra_inventory"] == tuple(_cfg("mo_stl_lra_inventory").status_include)
    mn = _cfg("mn_ramsey_tax_forfeit")
    assert IS.AVAILABLE_OFFERED_WORDINGS["mn_ramsey_tax_forfeit"] == tuple(v for f, v in mn.require if f == "Status")
    tn = _cfg("tn_shelby_landbank")
    assert IS.AVAILABLE_OFFERED_WORDINGS["tn_shelby_landbank"] == tuple(v for f, v in tn.offered if f == "currentStatus")
    # Every source in the table is a configured AVAILABLE source; a source
    # with no published per-row wording is deliberately absent.
    for sid in IS.AVAILABLE_OFFERED_WORDINGS:
        assert _cfg(sid).record_source == "laft"
    for sid in ("ok_oklahoma_county_owned", "pa_fayette_repository", "sc_horry_forfeited_land", "mi_oceana_landbank",
                "la_ebr_adjudicated", "mi_detroit_landbank_programs"):
        assert sid not in IS.AVAILABLE_OFFERED_WORDINGS


# ---- 2. the rule, one case per observed shape ----

def test_source_published_offered_wording_is_available_otc_with_the_wording_verbatim():
    for sid, wording in (("mi_detroit_landbank_lots", "Side Lot For Sale"), ("mi_detroit_landbank_lots", "Marketed Structure For Sale"),
                         ("mo_stl_lra_inventory", "Available"), ("mn_ramsey_tax_forfeit", "Available for purchase"),
                         ("tn_shelby_landbank", "FOR SALE")):
        obs = IS.status_for_row(row(state=sid[:2].upper(), source_id=sid, inventory_status_raw=wording), today=TODAY)
        assert (obs.status, obs.basis, obs.raw) == ("available_otc", "SOURCE_STATUS", wording), sid
        assert sid in obs.note
    # Case-insensitive on the wording; never a different word.
    assert IS.status_for_row(row(source_id="mo_stl_lra_inventory", state="MO", inventory_status_raw="available"), today=TODAY).status == "available_otc"
    assert IS.status_for_row(row(source_id="mo_stl_lra_inventory", state="MO", inventory_status_raw="Sold"), today=TODAY).status == "active"


def test_a_program_name_or_unmapped_wording_is_listed_not_available_and_kept_verbatim():
    obs = IS.status_for_row(row(source_id="mi_detroit_landbank_programs", inventory_status_raw="Own It Now"), today=TODAY)
    assert (obs.status, obs.basis, obs.raw) == ("active", "LIST_PRESENCE", "Own It Now")
    assert "not a mapped availability status" in obs.note


def test_list_presence_only_sources_are_listed_and_a_dated_list_is_named():
    for sid, st in (("ok_oklahoma_county_owned", "OK"), ("sc_horry_forfeited_land", "SC"), ("sc_georgetown_forfeited_land", "SC"),
                    ("mi_oceana_landbank", "MI")):
        obs = IS.status_for_row(row(state=st, source_id=sid, otc_provenance={"adapter": "tabular"}), today=TODAY)
        assert (obs.status, obs.basis, obs.raw) == ("active", "LIST_PRESENCE", None), sid
        assert "publishes no per-row availability status" in obs.note
    la = IS.status_for_row(row(state="LA", source_id="la_ebr_adjudicated", list_as_of="2024-02-27", otc_provenance=None), today=TODAY)
    assert la.status == "active" and "dated 2024-02-27" in la.note
    pa = IS.status_for_row(row(state="PA", source_id="pa_fayette_repository", list_as_of="2025-10-07"), today=TODAY)
    assert pa.status == "active" and "dated 2025-10-07" in pa.note


def test_the_rule_does_not_need_the_provenance_adapter_key():
    # 6,334 Louisiana rows had lost otc_provenance.adapter to a later sync.
    for prov in (None, {}, {"layer_url": "https://x"}):
        obs = IS.status_for_row(row(state="LA", source_id="la_ebr_adjudicated", otc_provenance=prov), today=TODAY)
        assert obs is not None and obs.status == "active"
    # harvester_source alone still identifies the source.
    obs = IS.status_for_row({"state": "MO", "source": "laft", "harvester_source": "mo_stl_lra_inventory", "status": "active",
                             "inventory_status_raw": "Available"}, today=TODAY)
    assert obs.status == "available_otc"


def test_absence_is_closed_never_a_result_and_sold_needs_the_sources_own_flag():
    gone = IS.status_for_row(row(status="closed", inventory_status_raw="Side Lot For Sale"), today=TODAY)
    assert (gone.status, gone.basis) == ("closed", "LIST_PRESENCE") and "why is not published" in gone.note
    for ps in ("dropped", "notfound", "sold"):
        assert IS.status_for_row(row(status=ps), today=TODAY).status == "closed"
    sold = IS.status_for_row(row(otc_provenance={"adapter": "arcgis", "published_outcome": "sold"}, inventory_status_raw="Sold: Yes"), today=TODAY)
    assert (sold.status, sold.basis, sold.raw) == ("sold", "SOURCE_STATUS", "Sold: Yes")
    # The flag without the wording asserts nothing.
    assert IS.status_for_row(row(otc_provenance={"adapter": "arcgis", "published_outcome": "sold"}), today=TODAY).status == "active"
    # A result status cannot come from list presence at all (the vocabulary's own guard).
    import pytest
    with pytest.raises(ValueError):
        IS.StatusObservation("sold", "LIST_PRESENCE")


def test_a_row_naming_no_source_is_left_unmapped_never_guessed():
    assert IS.status_for_row({"state": "MI", "source": "laft", "status": "active"}, today=TODAY) is None


# ---- 3. Texas and Florida ----

def test_texas_realauction_auctions_follow_the_feed_rule_and_lgbs_keeps_its_vendor_rule():
    ra = {"state": "TX", "source": "auction", "source_id": "tx_realauction", "status": "active"}
    assert IS.status_for_row({**ra, "sale_date": "2026-11-03"}, today=TODAY).status == "upcoming"
    assert IS.status_for_row({**ra, "sale_date": "2026-09-01"}, today=TODAY).status == "unknown"
    assert IS.status_for_row({**ra, "status": "closed"}, today=TODAY).status == "closed"
    assert "RealAuction" in IS.status_for_row({**ra}, today=TODAY).note
    # LGBS: production rows carry no tx_sale_status - "not published", never inferred from the date.
    lg = {"state": "TX", "source": "laft", "source_id": "tx_lgbs", "status": "active"}
    obs = IS.status_for_row(lg, today=TODAY)
    assert (obs.status, obs.basis) == ("unknown", "NOT_PUBLISHED")
    obs = IS.status_for_row({**lg, "tx_sale_status": "Available for Future Sale"}, today=TODAY)
    assert (obs.status, obs.basis) == ("resale_inventory", "SOURCE_STATUS")
    # Dispatch is by source id, not by harvester_source alone (production TX rows carry source_id).
    assert IS.status_for_row({"state": "TX", "source": "laft", "harvester_source": "tx_lgbs", "status": "active"}, today=TODAY).status == "unknown"


def test_florida_mapping_is_byte_for_byte_unchanged():
    assert IS.status_for_row({"state": "FL", "source": "laft", "source_id": "fl_laft_html", "status": "active"}, today=TODAY).status == "available_otc"
    assert IS.status_for_row({"state": "FL", "source": "laft", "status": "closed"}, today=TODAY).status == "closed"
    up = IS.status_for_row({"state": "FL", "source": "auction", "status": "active", "sale_date": "2026-12-01"}, today=TODAY)
    assert (up.status, up.note) == ("upcoming", "scheduled for 2026-12-01 per the county's auction feed")
    past = IS.status_for_row({"state": "FL", "source": "auction", "status": "active", "sale_date": "2026-01-01"}, today=TODAY)
    assert past.status == "unknown" and "sold / no sale / redeemed are not distinguishable" in past.note
    assert IS.status_for_row({"state": "FL", "source": "auction", "status": "closed"}, today=TODAY).note == "left the county's auction feed; the result is not published there"
    assert IS.status_for_row({"state": "FL", "source": "certificate", "status": "active"}, today=TODAY).status == "certificate_listed"


# ---- 4. the writer: source id on every observation, select carries what the rule reads ----

def test_writer_plans_every_gap_group_and_records_the_source_id():
    import inventory_status_writer as W
    rows = []
    for i, g in enumerate(GAP["groups"]):
        r = {"id": i, "county": "X", "case_no": str(i), "state": g["state"], "source": g["source"], "source_id": g["source_id"],
             "status": g["status"], "inventory_status": None, "inventory_status_raw": g.get("raw"),
             "otc_provenance": {"adapter": g["adapter"]} if g.get("adapter") else None, "list_as_of": g.get("list_date")}
        if g.get("has_sale_date"):
            r["sale_date"] = "2026-12-01"
        rows.append(r)
    changes, counts = W.plan(rows, today=TODAY)
    assert counts["unmapped"] == 0 and counts["mapped"] == len(rows) == len(changes)
    assert all(c["transition"] == "newly_observed" for c in changes)
    assert {c["source_id"] for c in changes} == {g["source_id"] for g in GAP["groups"]}
    # A Florida row (source_id, no harvester_source) names its source too.
    fl, _ = W.plan([{"id": 1, "county": "Bay", "case_no": "1", "state": "FL", "source": "laft", "source_id": "fl_laft_pioneer",
                     "status": "active", "inventory_status": None}], today=TODAY)
    assert fl[0]["source_id"] == "fl_laft_pioneer"
    obs = W.observations(fl, observed_at="2026-10-11T00:00:00Z", run_id="r1")
    assert obs[0]["source_id"] == "fl_laft_pioneer" and obs[0]["harvest_run_id"] == "r1"
    for col in ("source_id", "list_as_of", "inventory_status_raw", "otc_provenance", "tx_sale_status"):
        assert col in W.SELECT.split(",")


def test_writer_never_rewrites_an_unchanged_status():
    import inventory_status_writer as W
    r = row(id=1, county="Wayne", case_no="1", inventory_status="available_otc", inventory_status_raw="Side Lot For Sale")
    changes, counts = W.plan([r], today=TODAY)
    assert changes == [] and counts["unchanged"] == 1


# ---- 5. the dry run is pinned and the workflow runs the writer for Louisiana ----

def test_gap_report_is_current_and_counts_only():
    out = subprocess.run([sys.executable, "scripts/inventory_status_gap_report.py", "--check"], cwd=REPO, capture_output=True, text=True)
    assert out.returncode == 0, out.stdout + out.stderr
    text = (REPO / "docs/review/inventory-status-dryrun-2026-10-11.md").read_text(encoding="utf-8")
    assert "| Rows with no inventory_status (before) | 54,102 |" in text and "| Still unmapped | 0 |" in text
    assert "| LA | la_ebr_adjudicated | laft | 10,334 | 10,334 |" in text
    # No parcel-like or money-like token anywhere in the fixture or the report.
    for t in (text, (REPO / "data/current_state/inventory-status-gap-2026-10-11.json").read_text(encoding="utf-8")):
        assert not re.search(r"\$\d|\b\d{7,}\b", t)


def test_laft_job_runs_the_writer_for_louisiana_after_its_lifecycle():
    wf = (REPO / ".github/workflows/harvest-and-sync.yml").read_text(encoding="utf-8")
    job = wf.split("\n  laft:\n", 1)[1].split("\n  expansion:\n", 1)[0] if "\n  expansion:\n" in wf.split("\n  laft:\n", 1)[1] else wf.split("\n  laft:\n", 1)[1]
    i = job.index("scripts/laft_lifecycle.py --state LA")
    j = job.index("scripts/inventory_status_writer.py --state LA --report out/public/inventory-status-la.json")
    assert i < j
    step = job[job.rindex("- name:", 0, j):j]
    assert "steps.la_sync.outcome == 'success'" in step and "continue-on-error: true" in step
