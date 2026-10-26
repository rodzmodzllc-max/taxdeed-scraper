"""FL auction ledger kept current by one deeds run (2026-10-26).

- scripts/auction_outcomes.py also reads UPCOMING sale days holding an item
  the Waiting harvest no longer read (redeemed / cancelled before the sale);
- scripts/auction_outcome_status.py moves a property out of `active` from a
  verified result on its CURRENT sale day's event ('sold' / 'closed');
- the deeds job wires both, and a failed sanity check no longer skips them.
"""
from __future__ import annotations

import json
import re
import sys
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))
import auction_outcome_status as S  # noqa: E402
import auction_outcomes as AO  # noqa: E402

WF = (REPO / ".github" / "workflows" / "harvest-and-sync.yml").read_text(encoding="utf-8")
SRC = (REPO / "scripts" / "auction_outcome_status.py").read_text(encoding="utf-8")


def _deeds_job() -> str:
    start = WF.index("\n  deeds:\n")
    end = WF.index("\n  certificates:", start) if "\n  certificates:" in WF[start:] else len(WF)
    return WF[start:end]


# ==================== upcoming sale days ====================

def _ev(i, case, county="Lee", day="2026-11-05", lifecycle="scheduled", **kw):
    return {"id": f"e{i}", "property_id": f"p{i}", "case_no": case, "county": county, "scheduled_sale_date": day,
            "lifecycle": lifecycle, **kw}


def test_upcoming_days_are_only_days_with_an_item_off_the_waiting_list():
    today = date(2026, 10, 26)
    events = [_ev(1, "2024 TD 1"), _ev(2, "2024 TD 2"),                       # day 11-05: TD 2 not harvested
              _ev(3, "2024 TD 3", day="2026-11-12"),                          # every item still waiting
              _ev(4, "2024 TD 4", day="2026-10-20"),                          # past: the existing window reads it
              _ev(5, "2024 TD 5", day="2026-11-19", lifecycle="cancelled"),   # already has a result
              _ev(6, "2024 td 6", county="Orange", day="2026-11-05")]         # case compared normalized
    harvested = {"Lee": {AO.norm_id("2024 TD 1"), AO.norm_id("2024 TD 3")}, "Orange": {AO.norm_id("2024 TD 6")}}
    assert AO.upcoming_days_off_list(events, harvested, today) == {("Lee", "2026-11-05")}
    # No readable harvest: no upcoming day is read (fail closed, zero requests).
    assert AO.upcoming_days_off_list(events, None, today) == set()


def test_harvested_cases_reads_the_harvest_file(tmp_path):
    p = tmp_path / "h.json"
    p.write_text(json.dumps([{"county": "Lee", "case": " 2024 TD 1 "}, {"county": "Lee", "case": ""}]))
    assert AO.harvested_cases(p) == {"Lee": {"2024 TD 1"}}
    p.write_text(json.dumps({"county": "Lee", "case": "X"}))           # PowerShell one-element array
    assert AO.harvested_cases(p) == {"Lee": {"X"}}
    p.write_text("not json")
    assert AO.harvested_cases(p) is None and AO.harvested_cases(tmp_path / "missing.json") is None


def test_an_upcoming_redemption_is_matched_and_recorded_like_a_past_one():
    words = {("realauction", "redeemed"): AO.Wording("realauction", "Redeemed", "redeemed", "", True, "2026-09-30", "1")}
    ev = _ev(1, "2024 TD 1", county="Jackson", day="2026-11-05", outcome="unknown", outcome_raw=None, parcel="")
    rec = AO.ResultRecord(source_family="realauction", county="Jackson", sale_date="2026-11-05", case_no="2024 TD 1",
                          parcel="", raw_wording="Redeemed", evidence_url="https://jackson.realtaxdeed.com/index.cfm?zaction=AUCTION")
    plan = AO.plan_outcomes([AO.DayRead("Jackson", "2026-11-05", True, records=[rec])], [ev], words,
                            observed_at="2026-10-26T12:00:00+00:00", run_id="1")
    assert plan.patches == [("e1", {"lifecycle": "cancelled", "outcome": "redeemed", "outcome_raw": "Redeemed",
                                     "outcome_observed_at": "2026-10-26T12:00:00+00:00"})]


def test_outcomes_still_never_writes_properties():
    src = (REPO / "scripts" / "auction_outcomes.py").read_text(encoding="utf-8")
    assert "PATCH\", f\"properties" not in src and "source=eq.laft" not in src


# ==================== property status from a verified result ====================

def _p(i, status="active", day="2026-10-20", county="Lee", case=None):
    return {"id": f"p{i}", "status": status, "sale_date": day, "county": county, "case_no": case or f"2024 TD {i}"}


def _vev(i, outcome, lifecycle, raw, day="2026-10-20", **kw):
    return {"id": f"e{i}", "property_id": f"p{i}", "scheduled_sale_date": day, "outcome": outcome, "lifecycle": lifecycle,
            "outcome_raw": raw, **kw}


def test_verified_results_move_the_property_out_of_active():
    events = [_vev(1, "sold", "completed", "Auction Sold"),
              _vev(2, "redeemed", "cancelled", "Redeemed"),
              _vev(3, "unknown", "cancelled", "Canceled per County"),
              _vev(4, "sold", "completed", "Auction Sold"),
              _vev(5, "redeemed", "cancelled", "Redeemed"),
              _vev(6, "struck_off", "completed", "Struck Off")]
    props = [_p(1), _p(2), _p(3), _p(4, status="closed"), _p(5, status="closed"), _p(6)]
    changes, counts = S.plan(events, props)
    assert sorted(changes) == [("p1", "active", "sold"), ("p2", "active", "closed"), ("p3", "active", "closed"),
                               ("p4", "closed", "sold"), ("p6", "active", "closed")]
    assert counts["already_closed"] == 1 and counts["active_to_closed"] == 3 and counts["active_to_sold"] == 1


def test_never_from_another_sale_day_a_still_listed_row_or_an_unverified_event():
    events = [_vev(1, "sold", "completed", "Auction Sold", day="2026-09-15"),     # re-listed: the old sale says nothing
              _vev(2, "redeemed", "cancelled", "Redeemed"),                         # still on this run's Waiting list
              _vev(3, "unknown", "completed", None),                                # passed date, no wording -> no result
              _vev(4, "unknown", "scheduled", "Bidder Walked Away"),                # unmapped wording stays unknown
              _vev(5, "sold", "completed", "Auction Sold"),                         # dropped / notfound rows untouched
              _vev(6, "sold", "completed", "Auction Sold", lifecycle_note=None)]
    events[5]["lifecycle"] = "superseded"
    props = [_p(1, day="2026-11-05"), _p(2), _p(3), _p(4), _p(5, status="dropped"), _p(6)]
    changes, counts = S.plan(events, props, harvested={"Lee": {AO.norm_id("2024 TD 2")}})
    assert changes == []
    assert counts["result_for_another_sale_day"] == 1 and counts["still_on_waiting_list"] == 1
    assert counts["left_alone_dropped"] == 1


def test_conflicting_results_on_one_sale_day_change_nothing():
    events = [_vev(1, "sold", "completed", "Auction Sold"), dict(_vev(1, "redeemed", "cancelled", "Redeemed"), id="e9")]
    changes, counts = S.plan(events, [_p(1)])
    assert changes == [] and counts["conflicting_results"] == 1


def test_status_writer_writes_status_only_and_only_fl_auction_rows():
    writes = re.findall(r'json\.dumps\(([^)]*)\)\.encode\(\)', SRC)
    assert writes == ['{"status": to}']
    assert SRC.count("state=eq.FL&source=eq.auction") == 1 and '"state": "eq.FL", "source": "eq.auction"' in SRC
    for forbidden in ("winning_bid", "result_amount", "result_party", "winning_bidder", "purchaser\"", "laft", "certificate"):
        assert forbidden not in SRC.split('"""', 2)[2]
    assert "store_permitted(\"FL\", \"auction\")" in SRC
    assert S.GONE == frozenset({"dropped", "sold", "notfound", "closed"})


def test_status_writer_is_plan_only_without_credentials(capsys, monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_KEY", raising=False)
    assert S.main(["--apply"]) == 0 and "skipped" in capsys.readouterr().out


# ==================== workflow wiring ====================

def test_deeds_job_wires_the_steps_in_order_and_a_failed_sanity_check_skips_none_of_them():
    job = _deeds_job()
    i_sanity = job.index("scripts/sanity_check_deeds.ps1")
    i_events = job.index("scripts/auction_events_writer.py --source fl")
    i_outcomes = job.index("scripts/auction_outcomes.py --harvest out/harvest_all.json")
    i_status = job.index("scripts/auction_outcome_status.py --harvest out/harvest_all.json --apply")
    assert i_sanity < i_events < i_outcomes < i_status
    for marker in ("- name: Set up Python\n", "- name: Install Python dependencies (geocoding)",
                   "- name: Record auction events (Phase B)", "- name: Verified auction outcomes",
                   "- name: Outcome status - verified results move the property out of active"):
        step = job[job.index(marker):]
        step = step[:step.index("run:")]
        assert "!cancelled()" in step, marker
    off = job[job.index("- name: Off-list close-out"):]
    off = off[:off.index("run:")]
    assert "ON; vars.AUCTION_OFFLIST_CLOSE == '0' stops it" in off
