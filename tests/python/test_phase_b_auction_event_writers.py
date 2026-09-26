"""Phase B (auction-event writers + current-state seed) - contract tests.

The writer and the seed are driven against an in-memory implementation of
the same Store protocol the PostgREST client implements, so every rule is
checked on real code paths with no network and no database. Migration 014's
own tests (test_migration_014_auction_event_history.py) cover the SQL side of
the same identities and constraints.

Also checked statically: the workflow steps are wired AFTER the existing
property syncs, no existing harvester or sync script imports or references
the new writer (the property snapshot pipeline is untouched), and the
frontend does not read the new tables.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import date
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

import auction_events_writer as w  # noqa: E402
import seed_auction_events as seedmod  # noqa: E402

TODAY = date(2026, 9, 25)
RUN = "run-1"
T1 = "2026-09-25T10:00:00+00:00"
T2 = "2026-09-25T22:00:00+00:00"
T3 = "2026-10-07T10:00:00+00:00"


class MemoryStore:
    """Same five calls as PostgrestStore, backed by dicts. Enforces the two
    uniqueness rules migration 014 enforces, so a writer bug that would
    violate them fails here the way it would fail in production."""

    def __init__(self, properties: list[dict]) -> None:
        self.properties = [dict(p) for p in properties]
        self.events: list[dict] = []
        self.observations: list[dict] = []
        self.patches: list[tuple[str, dict]] = []
        self.deleted: list[str] = []
        self.fail_observations = False   # simulate a failed observation write
        self.fail_patch_after = None     # simulate a failed PATCH after N successes
        self._n = 0

    def fetch_properties(self, state, source):
        return [dict(p) for p in self.properties if p["state"] == state and p["source"] == source]

    def fetch_events(self, state, source):
        return [dict(e) for e in self.events if e["state"] == state and e["source"] == source]

    def insert_events(self, rows):
        out = []
        for r in rows:
            key = (r["property_id"], r["scheduled_sale_date"])
            if any((e["property_id"], e["scheduled_sale_date"]) == key for e in self.events):
                raise RuntimeError(f"duplicate event {key}")
            if r["lifecycle"] not in w.LIFECYCLES or r["outcome"] not in w.OUTCOMES:
                raise RuntimeError("check constraint")
            self._n += 1
            row = dict(r, id=f"ev-{self._n}")
            self.events.append(row)
            out.append(dict(row))
        return out

    def update_event(self, event_id, patch):
        if self.fail_patch_after is not None and len(self.patches) >= self.fail_patch_after:
            raise RuntimeError("simulated PATCH failure")
        if "lifecycle" in patch and patch["lifecycle"] not in w.LIFECYCLES:
            raise RuntimeError("check constraint")
        for e in self.events:
            if e["id"] == event_id:
                e.update(patch)
                self.patches.append((event_id, dict(patch)))
                return
        raise RuntimeError(f"no event {event_id}")

    def insert_observations(self, rows):
        if self.fail_observations:
            raise RuntimeError("simulated observation failure")
        for r in rows:
            key = (r["event_id"], r["observed_at"])
            if any((o["event_id"], o["observed_at"]) == key for o in self.observations):
                raise RuntimeError(f"duplicate observation {key}")
            if r["lifecycle"] not in w.LIFECYCLES:
                raise RuntimeError("check constraint")
            self.observations.append(dict(r))

    def delete_unobserved_events(self, event_ids, first_seen_at):
        keep = []
        for e in self.events:
            if e["id"] in event_ids and e["first_seen_at"] == first_seen_at:
                self.deleted.append(e["id"])
            else:
                keep.append(e)
        self.events = keep


def prop(pid, county, case_no, *, state="FL", sale_date=None, bid=1500, status="active", hs=None, url=None, kind=None):
    return {"id": pid, "state": state, "source": "auction", "county": county, "case_no": case_no,
            "harvester_source": hs, "ledger_type": "auctions", "sale_date": sale_date, "bid": bid,
            "status": status, "url_auction": url, "url_auction_kind": kind}


def fl_row(county, case, sale_date_us, bid=1500, host="lee.realforeclose.com"):
    return {"county": county, "host": host, "sale_date": sale_date_us, "case": case, "cert": "", "bid": bid,
            "assessed": 10000, "parcel": "P", "appraiser": None, "address": "1 Main St",
            "auction_url": f"https://{host}/index.cfm?zaction=AUCTION&zmethod=PREVIEW&AuctionDate={sale_date_us}"}


def tx_row(county, account, iso_date, hs, status=None, min_bid=2000, url=None):
    return {"account_number": account, "county": county, "state": "TX", "auction_date": iso_date, "min_bid": min_bid,
            "source": "auction", "harvester_source": hs, "sale_status": status, "auction_url": url,
            "auction_url_kind": "sale" if url else None}


# ==================== sightings from real artifact shapes ====================


def test_fl_sightings_parse_us_dates_and_classify_feed():
    s = w.sightings_from_fl_harvest([fl_row("Lee", "2026000001", "10/06/2026"),
                                     {"county": "Okaloosa", "case": "OK-1", "sale_date": "2026-10-20", "bid": "900",
                                      "auction_url": "https://www.bid4assets.com/auction/index/123"},
                                     {"county": "Lee", "case": "", "sale_date": "10/06/2026"},
                                     {"county": "Lee", "case": "X", "sale_date": "not a date"}])
    assert [(x.county, x.scheduled_sale_date, x.feed, x.event_url_kind, x.raw_status, x.lifecycle) for x in s] == [
        ("Lee", "2026-10-06", "waiting", "sale", "Auctions Waiting", "scheduled"),
        ("Okaloosa", "2026-10-20", "list", "county", None, "scheduled"),
    ]
    assert s[1].opening_bid == 900.0


def test_tx_sightings_only_scheduled_statuses_and_dated_auction_rows():
    rows = [
        tx_row("Nueces", "9377", "2026-10-06", "tx_realauction", url="https://nueces.texas.sheriffsaleauctions.com/index.cfm?zaction=AUCTION&zmethod=PREVIEW&AuctionDate=10/06/2026"),
        tx_row("Concho", "C-1", "2026-10-06", "tx_lgbs", status="Scheduled for Online Auction"),
        tx_row("Concho", "C-2", "2026-10-06", "tx_lgbs", status="Scheduled for Auction"),
        tx_row("Concho", "C-3", "2026-10-06", "tx_lgbs", status="Sale Results Pending"),
        tx_row("Concho", "C-4", "2026-10-06", "tx_lgbs", status="Cancelled"),
        tx_row("Concho", "C-5", "2026-10-06", "tx_lgbs", status=None),
        dict(tx_row("Galveston", "G-1", None, "tx_lgbs", status="Struck off to Jurisdiction"), source="laft"),
        tx_row("Harris", "H-1", "2026-10-06", "tx_pbfcm", status="Scheduled for Auction"),
    ]
    s = w.sightings_from_tx_harvest(rows)
    assert [(x.county, x.case_no, x.feed, x.raw_status) for x in s] == [
        ("Nueces", "9377", "waiting", "Auctions Waiting"),
        ("Concho", "C-1", "api", "Scheduled for Online Auction"),
        ("Concho", "C-2", "api", "Scheduled for Auction"),
    ]
    assert all(x.lifecycle == "scheduled" for x in s)
    assert s[0].event_url_kind == "sale" and s[1].event_url is None


def test_sighting_rejects_invalid_lifecycle_and_kind():
    with pytest.raises(w.WriterError):
        w.Sighting("FL", "auction", "Lee", "1", "2026-10-06", "waiting", "left_feed", None, None, None, None)
    with pytest.raises(w.WriterError):
        w.Sighting("FL", "auction", "Lee", "1", "2026-10-06", "waiting", "scheduled", None, None, "x", "homepage")


# ==================== writer rules ====================


def run_fl(store, rows, observed_at, complete=("Lee",)):
    return w.record_sightings(store, w.sightings_from_fl_harvest(rows), scope=("FL", "auction"), observed_at=observed_at,
                              run_id=RUN, complete_counties=set(complete) if complete is not None else None, today=TODAY)


def test_same_event_harvested_twice_one_event_many_observations():
    store = MemoryStore([prop("p1", "Lee", "2026000001", sale_date="2026-10-06")])
    s1 = run_fl(store, [fl_row("Lee", "2026000001", "10/06/2026")], T1)
    s2 = run_fl(store, [fl_row("Lee", "2026000001", "10/06/2026")], T2)
    assert (s1.events_created, s1.observations) == (1, 1)
    assert (s2.events_created, s2.events_seen_again, s2.observations) == (0, 1, 1)
    assert len(store.events) == 1
    ev = store.events[0]
    assert ev["lifecycle"] == "scheduled" and ev["outcome"] == "unknown"
    assert ev["first_seen_at"] == T1 and ev["last_seen_at"] == T2
    assert ev["opening_bid"] == 1500.0 and ev["event_url_kind"] == "sale"
    assert [o["observed_at"] for o in store.observations] == [T1, T2]
    assert {o["feed"] for o in store.observations} == {"waiting"}
    assert all(o["raw_status"] == "Auctions Waiting" and o["harvest_run_id"] == RUN for o in store.observations)


def test_same_property_new_sale_date_creates_second_event_and_supersedes_with_evidence():
    store = MemoryStore([prop("p1", "Lee", "2026000001", sale_date="2026-10-06")])
    run_fl(store, [fl_row("Lee", "2026000001", "10/06/2026")], T1)
    s2 = run_fl(store, [fl_row("Lee", "2026000001", "11/03/2026", bid=1600)], T2)
    assert s2.events_created == 1 and s2.events_superseded == 1
    by_date = {e["scheduled_sale_date"]: e for e in store.events}
    assert set(by_date) == {"2026-10-06", "2026-11-03"}
    assert by_date["2026-10-06"]["lifecycle"] == "superseded"
    assert by_date["2026-10-06"]["opening_bid"] == 1500.0  # first event untouched otherwise
    assert by_date["2026-11-03"]["lifecycle"] == "scheduled" and by_date["2026-11-03"]["opening_bid"] == 1600.0
    sup = [o for o in store.observations if o["lifecycle"] == "superseded"]
    assert len(sup) == 1 and sup[0]["raw_status"] is None and "11/03/2026" in sup[0]["evidence_url"]
    assert sup[0]["feed"] == "derived"  # an inference, never a sighting of the Waiting feed
    assert all(e["outcome"] == "unknown" for e in store.events)


def test_absence_alone_is_not_evidence():
    store = MemoryStore([prop("p1", "Lee", "2026000001", sale_date="2026-10-06")])
    run_fl(store, [fl_row("Lee", "2026000001", "10/06/2026")], T1)
    # Next run: county COMPLETE, property simply absent, date still in the future.
    s2 = run_fl(store, [fl_row("Lee", "2026000099", "10/06/2026")], T2)
    assert store.events[0]["lifecycle"] == "scheduled" and s2.events_superseded == 0 and s2.events_completed == 0
    # Same absence with NO county complete this run: still nothing, even
    # though the date has passed by now.
    s3 = w.record_sightings(store, [], scope=("FL", "auction"), observed_at=T3, run_id=RUN, complete_counties=set(), today=date(2026, 10, 7))
    assert store.events[0]["lifecycle"] == "scheduled"
    assert s3.events_completed == 0 and s3.events_superseded == 0


def test_listing_gone_before_its_sale_date_is_never_completed():
    # Last seen 2026-09-25, sale date 2026-10-06; then absent from a COMPLETE
    # county. It left the feed before the sale could happen -> 'unknown'.
    store = MemoryStore([prop("p1", "Lee", "2026000001", sale_date="2026-10-06")])
    run_fl(store, [fl_row("Lee", "2026000001", "10/06/2026")], T1)
    later = w.record_sightings(store, [], scope=("FL", "auction"), observed_at=T3,
                               run_id=RUN, complete_counties={"Lee"}, today=date(2026, 10, 7))
    assert later.events_completed == 0 and later.events_unknown == 1
    ev = store.events[0]
    assert ev["lifecycle"] == "unknown" and ev["outcome"] == "unknown"
    obs = store.observations[-1]
    assert (obs["feed"], obs["raw_status"], obs["lifecycle"], obs["outcome"], obs["evidence_url"]) == \
        ("derived", None, "unknown", "unknown", None)
    # Never any outcome word, and never a lifecycle that claims a reason.
    assert all(o["lifecycle"] not in ("cancelled", "withdrawn", "stayed", "completed") for o in store.observations)


def test_listing_seen_on_its_sale_date_then_absent_becomes_completed_outcome_unknown():
    store = MemoryStore([prop("p1", "Lee", "2026000001", sale_date="2026-10-06")])
    run_fl(store, [fl_row("Lee", "2026000001", "10/06/2026")], T1)
    sale_day = "2026-10-06T10:00:00+00:00"   # the 06:00 ET harvest on the sale day
    w.record_sightings(store, w.sightings_from_fl_harvest([fl_row("Lee", "2026000001", "10/06/2026")]),
                       scope=("FL", "auction"), observed_at=sale_day, run_id=RUN, complete_counties={"Lee"},
                       today=date(2026, 10, 6))
    later = w.record_sightings(store, [], scope=("FL", "auction"), observed_at=T3,
                               run_id=RUN, complete_counties={"Lee"}, today=date(2026, 10, 7))
    assert later.events_completed == 1 and later.events_unknown == 0
    ev = store.events[0]
    assert ev["lifecycle"] == "completed" and ev["outcome"] == "unknown"
    obs = store.observations[-1]
    assert (obs["feed"], obs["raw_status"], obs["lifecycle"], obs["outcome"], obs["evidence_url"]) == \
        ("derived", None, "completed", "unknown", None)
    # Without a completeness gate (Texas), nothing transitions.
    store2 = MemoryStore([prop("t1", "Nueces", "9377", state="TX", sale_date="2026-10-06", hs="tx_realauction")])
    w.record_sightings(store2, w.sightings_from_tx_harvest([tx_row("Nueces", "9377", "2026-10-06", "tx_realauction")]),
                       scope=("TX", "auction"), observed_at=T1, run_id=RUN, complete_counties=None, today=TODAY)
    w.record_sightings(store2, [], scope=("TX", "auction"), observed_at=T3, run_id=RUN, complete_counties=None, today=date(2026, 10, 7))
    assert store2.events[0]["lifecycle"] == "scheduled"


def test_sale_day_boundary_is_conservative_across_florida_time_zones():
    d = date(2026, 10, 6)
    assert w.lifecycle_after_absence(d, "2026-10-06T10:00:00+00:00") == "completed"   # 04:00 at UTC-6
    assert w.lifecycle_after_absence(d, "2026-10-06T05:59:00+00:00") == "unknown"     # still Oct 5 at UTC-6
    assert w.lifecycle_after_absence(d, "2026-10-05T22:00:00+00:00") == "unknown"
    assert w.lifecycle_after_absence(d, "2026-10-08T10:00:00Z") == "completed"
    assert w.lifecycle_after_absence(d, None) == "unknown"
    assert w.lifecycle_after_absence(d, "not a time") == "unknown"


def test_resighted_completed_event_goes_back_to_scheduled_and_keeps_history():
    store = MemoryStore([prop("p1", "Lee", "2026000001", sale_date="2026-10-06")])
    sale_day = "2026-10-06T10:00:00+00:00"
    run_fl(store, [fl_row("Lee", "2026000001", "10/06/2026")], sale_day)
    w.record_sightings(store, [], scope=("FL", "auction"), observed_at=T3, run_id=RUN,
                       complete_counties={"Lee"}, today=date(2026, 10, 7))
    assert store.events[0]["lifecycle"] == "completed"
    again = "2026-10-08T10:00:00+00:00"
    s = w.record_sightings(store, w.sightings_from_fl_harvest([fl_row("Lee", "2026000001", "10/06/2026")]),
                           scope=("FL", "auction"), observed_at=again, run_id=RUN, complete_counties={"Lee"},
                           today=date(2026, 10, 8))
    assert w.RESIGHT_LIFECYCLE == "scheduled"
    assert s.events_seen_again == 1 and s.events_reopened == 1 and s.events_created == 0
    assert store.events[0]["lifecycle"] == "scheduled" and store.events[0]["last_seen_at"] == again
    assert [o["lifecycle"] for o in store.observations] == ["scheduled", "completed", "scheduled"]
    assert [o["feed"] for o in store.observations] == ["waiting", "derived", "waiting"]


def test_existing_event_is_never_advanced_before_its_observation_is_stored():
    store = MemoryStore([prop("p1", "Lee", "2026000001", sale_date="2026-10-06")])
    run_fl(store, [fl_row("Lee", "2026000001", "10/06/2026")], T1)
    store.fail_observations = True
    with pytest.raises(RuntimeError):
        run_fl(store, [fl_row("Lee", "2026000001", "10/06/2026")], T2)
    assert store.events[0]["last_seen_at"] == T1 and len(store.patches) == 0
    # A PATCH failing after the observation is stored leaves the event
    # lagging its evidence (never ahead of it); the next run catches up.
    store.fail_observations = False
    store.fail_patch_after = 0
    with pytest.raises(RuntimeError):
        run_fl(store, [fl_row("Lee", "2026000001", "10/06/2026")], T2)
    assert store.events[0]["last_seen_at"] == T1 and [o["observed_at"] for o in store.observations] == [T1, T2]
    store.fail_patch_after = None
    run_fl(store, [fl_row("Lee", "2026000001", "10/06/2026")], "2026-09-26T10:00:00+00:00")
    assert store.events[0]["last_seen_at"] == "2026-09-26T10:00:00+00:00" and len(store.events) == 1


def test_new_event_without_its_first_observation_is_removed_again():
    store = MemoryStore([prop("p1", "Lee", "2026000001", sale_date="2026-10-06")])
    store.fail_observations = True
    with pytest.raises(w.WriterError, match="removed again"):
        run_fl(store, [fl_row("Lee", "2026000001", "10/06/2026")], T1)
    assert store.events == [] and store.deleted == ["ev-1"] and store.observations == []
    # The compensation only ever touches rows this run inserted.
    store.fail_observations = False
    run_fl(store, [fl_row("Lee", "2026000001", "10/06/2026")], T1)
    assert len(store.events) == 1 and len(store.observations) == 1


def test_property_identity_and_snapshot_untouched():
    props = [prop("p1", "Lee", "2026000001", sale_date="2026-10-06", bid=1500)]
    store = MemoryStore(props)
    before = json.dumps(store.properties, sort_keys=True)
    run_fl(store, [fl_row("Lee", "2026000001", "10/06/2026", bid=9999)], T1)
    assert json.dumps(store.properties, sort_keys=True) == before
    assert store.events[0]["property_id"] == "p1" and store.events[0]["case_no"] == "2026000001"


def test_unmatched_rows_get_no_event():
    store = MemoryStore([prop("p1", "Lee", "2026000001", sale_date="2026-10-06")])
    s = run_fl(store, [fl_row("Lee", "NOT-SYNCED", "10/06/2026"), fl_row("Lee", "2026000001", "10/06/2026")], T1)
    assert s.unmatched == 1 and s.events_created == 1 and len(store.events) == 1


def test_duplicate_rows_in_one_harvest_yield_one_observation():
    store = MemoryStore([prop("p1", "Lee", "2026000001", sale_date="2026-10-06")])
    s = run_fl(store, [fl_row("Lee", "2026000001", "10/06/2026")] * 3, T1)
    assert s.events_created == 1 and s.observations == 1


def test_missing_outcome_stays_unknown_and_lifecycle_is_explicit_everywhere():
    store = MemoryStore([prop("p1", "Lee", "2026000001", sale_date="2026-10-06")])
    run_fl(store, [fl_row("Lee", "2026000001", "10/06/2026")], T1)
    for e in store.events:
        assert e["outcome"] == "unknown" and e["lifecycle"] in w.LIFECYCLES
    for o in store.observations:
        assert o["outcome"] == "unknown" and o["lifecycle"] in w.LIFECYCLES
    for pid, patch in store.patches:
        assert "lifecycle" in patch and patch["lifecycle"] in w.LIFECYCLES


def test_writer_can_never_populate_bidder_or_outcome_fields():
    with pytest.raises(w.WriterError):
        w._check_event_payload({"lifecycle": "scheduled", "winning_bidder_ref": "x"})
    with pytest.raises(w.WriterError):
        w._check_event_payload({"winning_bid": 1})
    with pytest.raises(w.WriterError):
        w._check_event_payload({"outcome": "sold"})
    with pytest.raises(w.WriterError):
        w._observation("e", observed_at=T1, run_id=None, feed="waiting", raw_status=None, lifecycle="closed", opening_bid=None, evidence_url=None)
    src = (REPO / "scripts" / "auction_events_writer.py").read_text() + (REPO / "scripts" / "seed_auction_events.py").read_text()
    for name in ("winning_bidder_ref", "winning_bid", "bid_count", "outcome_effective_date"):
        # Present only in the forbidden list / prose, never as an assigned key.
        assert not re.search(rf'"{name}"\s*:', src), name


def test_invalid_lifecycle_fails_loudly():
    # A Sighting cannot even be constructed with a value outside the
    # vocabulary, so nothing downstream can insert one.
    with pytest.raises(w.WriterError):
        w.Sighting("FL", "auction", "Lee", "2026000001", "2026-10-06", "waiting", "active", None, None, None, None)
    # And every payload that reaches a store is re-checked.
    for bad in ("active", "closed", "left_feed", "notfound", ""):
        with pytest.raises(w.WriterError):
            w._check_event_payload({"lifecycle": bad})
    # The store itself (like the migration's CHECK) refuses too, as a last line.
    store = MemoryStore([prop("p1", "Lee", "2026000001", sale_date="2026-10-06")])
    with pytest.raises(RuntimeError):
        store.insert_events([{"property_id": "p1", "state": "FL", "source": "auction", "scheduled_sale_date": "2026-10-06",
                              "lifecycle": "active", "outcome": "unknown"}])
    assert store.events == []


# ==================== seed ====================


def seed_fixture():
    return MemoryStore([
        prop("p1", "Lee", "A", sale_date="2026-10-06", bid=1500, url="https://lee.realforeclose.com/index.cfm?zaction=AUCTION&zmethod=PREVIEW&AuctionDate=10/06/2026", kind="sale"),
        prop("p2", "Lee", "B", sale_date="2026-09-16", status="closed", bid=0),       # closed, past
        prop("p3", "Lee", "C", sale_date=None),                                        # no date: not a candidate
        prop("p4", "DeSoto", "D", sale_date="2026-09-16", status="active"),           # active, past
        prop("p5", "Lee", "E", sale_date="2026-10-20", status="active"),              # active, absent from harvest
        prop("p6", "Lee", "F", sale_date="2026-10-20", status="closed"),              # closed + future: contradictory
        prop("p7", "Bay", "G", sale_date="2026-10-06", status="active"),              # county not COMPLETE
        prop("p8", "Lee", "H", sale_date="2026-08-06", status="dropped"),
        dict(prop("t1", "Nueces", "9377", state="TX", sale_date="2026-10-06", hs="tx_realauction", bid=21800)),
        dict(prop("t2", "Concho", "C-1", state="TX", sale_date="2026-10-06", hs="tx_lgbs"), tx_sale_status="Scheduled for Online Auction"),
        dict(prop("t3", "Concho", "C-2", state="TX", sale_date="2026-10-06", hs="tx_lgbs"), tx_sale_status=None),
        dict(prop("t4", "Concho", "C-3", state="TX", sale_date="2026-10-06", hs="tx_lgbs"), tx_sale_status="Sale Results Pending"),
    ])


def fl_evidence(rows, complete=("Lee",)):
    return seedmod.Evidence(fl=seedmod.Evidence.index(w.sightings_from_fl_harvest(rows)), fl_complete=set(complete))


def test_seed_only_seeds_rows_with_present_tense_evidence():
    t = TODAY
    ev = fl_evidence([fl_row("Lee", "A", "10/06/2026"), fl_row("Bay", "G", "10/06/2026")])
    decide = lambda p: seedmod.seed_decision(p, t, ev)  # noqa: E731
    by_id = {p["id"]: p for p in seed_fixture().properties}
    assert decide(by_id["p1"]) == ("Auctions Waiting", "")
    assert decide(by_id["p2"]) == (None, "closed_status_not_completion_evidence")
    assert decide(by_id["p4"]) == (None, "date_passed_presence_not_established")
    assert decide(by_id["p5"]) == (None, "absent_from_current_harvest")
    assert decide(by_id["p6"]) == (None, "contradictory_closed_future")
    assert decide(by_id["p7"]) == (None, "county_harvest_not_complete")
    assert decide(by_id["p8"]) == (None, "status_not_active")
    assert decide(by_id["t1"]) == (None, "no_harvest_evidence_supplied")
    assert decide(by_id["t2"]) == ("Scheduled for Online Auction", "")
    assert decide(by_id["t3"]) == (None, "lgbs_status_not_scheduled")
    assert decide(by_id["t4"]) == (None, "lgbs_status_not_scheduled")
    # No harvest file at all: no Florida row is seeded.
    assert seedmod.seed_decision(by_id["p1"], t, seedmod.Evidence()) == (None, "no_harvest_evidence_supplied")
    # The same row listed in the harvest under a DIFFERENT date is not evidence for this date.
    moved = fl_evidence([fl_row("Lee", "A", "11/03/2026")])
    assert seedmod.seed_decision(by_id["p1"], t, moved) == (None, "absent_from_current_harvest")


def test_seed_never_writes_completed_or_pending_result_and_is_idempotent():
    store = seed_fixture()
    tx = seedmod.Evidence.index(w.sightings_from_tx_harvest([tx_row("Nueces", "9377", "2026-10-06", "tx_realauction")]))
    ev = fl_evidence([fl_row("Lee", "A", "10/06/2026")])
    ev.tx = tx
    s1 = seedmod.seed(store, observed_at=T1, run_id="seed-1", today=TODAY, evidence=ev)
    assert s1["candidates"] == 11 and s1["created"] == 3 and s1["observations"] == 3
    assert s1["by_state"] == {"FL": 1, "TX": 2}
    assert sum(s1["skipped"].values()) == 8
    assert {e["lifecycle"] for e in store.events} == {"scheduled"}
    assert all(e["outcome"] == "unknown" for e in store.events)
    assert all(o["feed"] == "seed" and o["harvest_run_id"] == "seed-1" for o in store.observations)
    assert {o["raw_status"] for o in store.observations} == {"Auctions Waiting", "Scheduled for Online Auction"}
    assert {e["case_no"] for e in store.events} == {"A", "9377", "C-1"}
    s2 = seedmod.seed(store, observed_at=T2, run_id="seed-2", today=TODAY, evidence=ev)
    assert s2["created"] == 0 and s2["already_present"] == 3 and s2["observations"] == 0
    # A harvest after the seed re-observes the seeded event rather than duplicating it.
    s3 = run_fl(store, [fl_row("Lee", "A", "10/06/2026")], T3)
    assert s3.events_created == 0 and s3.events_seen_again == 1 and len(store.events) == 3


def test_seed_removes_events_whose_observations_fail():
    store = seed_fixture()
    store.fail_observations = True
    with pytest.raises(w.WriterError):
        seedmod.seed(store, states=("FL",), observed_at=T1, run_id="seed-1", today=TODAY,
                     evidence=fl_evidence([fl_row("Lee", "A", "10/06/2026")]))
    assert store.events == [] and store.deleted


def test_seed_cli_is_dry_run_by_default(monkeypatch, capsys, tmp_path):
    calls = []

    class FakeReal:
        def fetch_properties(self, state, source):
            return [prop("p1", "Lee", "A", sale_date="2099-10-06")] if state == "FL" else []

        def fetch_events(self, state, source):
            return []

        def insert_events(self, rows):
            calls.append("insert")
            return rows

        def update_event(self, *_):
            calls.append("update")

        def insert_observations(self, rows):
            calls.append("obs")

        def delete_unobserved_events(self, *_):
            calls.append("delete")

    monkeypatch.setenv("SUPABASE_URL", "https://example.invalid")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "not-a-real-key")
    monkeypatch.setattr(seedmod, "PostgrestStore", lambda url, key: FakeReal())
    harvest = tmp_path / "harvest_all.json"
    status = tmp_path / "harvest_all_status.json"
    harvest.write_text(json.dumps([fl_row("Lee", "A", "10/06/2099")]))
    status.write_text(json.dumps([{"county": "Lee", "status": "COMPLETE"}]))
    missing = tmp_path / "absent.json"
    assert seedmod.main(["--fl-harvest-json", str(harvest), "--fl-status-json", str(status),
                         "--tx-harvest-json", str(missing)]) == 0
    out = capsys.readouterr().out
    assert "DRY RUN - nothing written" in out and calls == []
    assert '"created": 1' in out


# ==================== wiring / boundaries ====================


def test_workflow_runs_writer_after_each_property_sync_and_never_the_seed():
    yml = (REPO / ".github" / "workflows" / "harvest-and-sync.yml").read_text()
    assert "seed_auction_events" not in yml
    deeds = yml.split("\n  deeds:")[1].split("\n  certificates:")[0]
    texas = yml.split("\n  texas:")[1].split("\n  backup:")[0]
    for job, flag in ((deeds, "--source fl"), (texas, "--source tx")):
        sync_pos = job.index("Sync to Supabase")
        writer_pos = job.index("scripts/auction_events_writer.py " + flag)
        assert writer_pos > sync_pos, "the event writer must run after the property sync"
        step = job[job.rfind("- name:", 0, writer_pos):writer_pos]
        assert "continue-on-error: true" in step, "a writer failure must not fail the property pipeline"
        assert "SUPABASE_SERVICE_KEY" in step
        # ...but a failure must be visible: a warning annotation + job summary,
        # keyed to this step's own outcome and never to the harvest's.
        sid = re.search(r"id: (phase_b_events_\w+)", step).group(1)
        report = job[writer_pos:]
        report = report[report.index("- name: Report Phase B event recording failure"):]
        report = report[:report.index("\n      - name:", 1)] if "\n      - name:" in report[1:] else report
        assert f"steps.{sid}.outcome == 'failure'" in report and "!cancelled()" in report
        assert "::warning title=Phase B event recording failed" in report and "GITHUB_STEP_SUMMARY" in report
        assert "Property harvest and sync succeeded" in report
        assert "continue-on-error" not in report
    # Texas is still workflow_dispatch only - Phase B changes no schedule.
    assert "if: github.event_name == 'workflow_dispatch'" in texas
    assert yml.count("cron:") == 3


def test_existing_pipeline_files_do_not_reference_the_writer():
    for rel in ("scripts/sync-harvest-to-supabase.ps1", "scripts/sync-texas-to-supabase.py", "scripts/sync-laft-to-supabase.ps1",
                "scripts/sync-certificates-to-supabase.ps1", "harvesters/texas_harvester.py", "scripts/harvest_all_counties.ps1",
                "scripts/harvest_okaloosa_bid4assets.ps1", "public/app.js", "public/explore.js", "public/satellite-map.js",
                "public/index.html", "public/tx.html"):
        text = (REPO / rel).read_text(encoding="utf-8", errors="replace")
        assert "auction_events" not in text and "auction_event_writer" not in text, rel


def test_writer_reads_but_never_writes_properties():
    src = (REPO / "scripts" / "auction_events_writer.py").read_text() + (REPO / "scripts" / "seed_auction_events.py").read_text()
    # The only PostgREST paths written are the two event tables.
    writes = re.findall(r'_request\("(POST|PATCH|DELETE)",\s*f?"([a-z_]+)', src)
    assert writes and all(table in ("auction_events", "auction_event_observations") for _, table in writes), writes
    assert "properties?" in src  # read path exists
    assert not re.search(r'_request\("(POST|PATCH|DELETE)",\s*f?"properties', src)


def test_data_contract_documents_phase_b():
    doc = (REPO / "docs" / "production-data-contract.md").read_text()
    section = doc.split("## 27. Auction-event writers")[1]
    for required in ("feed = 'seed'", "superseded", "completed", "outcome stays `unknown`", "winning_bidder_ref", "Texas",
                     "`properties` is never written", "feed = 'derived'", "last_seen_at", "on or after its",
                     "RESIGHT_LIFECYCLE", "ordering plus compensation", "::warning title=Phase B event recording failed",
                     "never seeds `completed` or `pending_result`"):
        assert required in section, required


def test_writer_failure_exits_nonzero_and_says_so_in_the_job_summary(tmp_path):
    # Fails before any network call (the harvest file is missing), exactly as
    # a broken run would, and must leave a visible FAILED section behind.
    import os
    import subprocess
    summary = tmp_path / "summary.md"
    env = {k: v for k, v in os.environ.items() if not k.startswith("SUPABASE")}
    env["GITHUB_STEP_SUMMARY"] = str(summary)
    proc = subprocess.run([sys.executable, str(REPO / "scripts" / "auction_events_writer.py"), "--source", "fl",
                           "--harvest-json", str(tmp_path / "missing.json")], env=env, capture_output=True, text=True)
    assert proc.returncode == 1
    assert "ERROR" in proc.stderr
    text = summary.read_text()
    assert "Phase B event recording: FAILED" in text and "property harvest and sync already completed" in text
