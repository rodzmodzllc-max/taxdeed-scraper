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
        if "lifecycle" in patch and patch["lifecycle"] not in w.LIFECYCLES:
            raise RuntimeError("check constraint")
        for e in self.events:
            if e["id"] == event_id:
                e.update(patch)
                self.patches.append((event_id, dict(patch)))
                return
        raise RuntimeError(f"no event {event_id}")

    def insert_observations(self, rows):
        for r in rows:
            key = (r["event_id"], r["observed_at"])
            if any((o["event_id"], o["observed_at"]) == key for o in self.observations):
                raise RuntimeError(f"duplicate observation {key}")
            if r["lifecycle"] not in w.LIFECYCLES:
                raise RuntimeError("check constraint")
            self.observations.append(dict(r))


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


def test_date_passed_and_absent_from_complete_county_becomes_completed_outcome_unknown():
    store = MemoryStore([prop("p1", "Lee", "2026000001", sale_date="2026-10-06")])
    run_fl(store, [fl_row("Lee", "2026000001", "10/06/2026")], T1)
    later = w.record_sightings(store, w.sightings_from_fl_harvest([]), scope=("FL", "auction"), observed_at=T3,
                               run_id=RUN, complete_counties={"Lee"}, today=date(2026, 10, 7))
    assert later.events_completed == 1
    ev = store.events[0]
    assert ev["lifecycle"] == "completed" and ev["outcome"] == "unknown"
    obs = store.observations[-1]
    assert obs["lifecycle"] == "completed" and obs["outcome"] == "unknown" and obs["raw_status"] is None
    # Without a completeness gate (Texas), nothing transitions.
    store2 = MemoryStore([prop("t1", "Nueces", "9377", state="TX", sale_date="2026-10-06", hs="tx_realauction")])
    w.record_sightings(store2, w.sightings_from_tx_harvest([tx_row("Nueces", "9377", "2026-10-06", "tx_realauction")]),
                       scope=("TX", "auction"), observed_at=T1, run_id=RUN, complete_counties=None, today=TODAY)
    w.record_sightings(store2, [], scope=("TX", "auction"), observed_at=T3, run_id=RUN, complete_counties=None, today=date(2026, 10, 7))
    assert store2.events[0]["lifecycle"] == "scheduled"


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


def test_seed_lifecycle_mapping():
    t = TODAY
    assert seedmod.seed_lifecycle("active", date(2026, 10, 6), t) == "scheduled"
    assert seedmod.seed_lifecycle("active", date(2026, 9, 16), t) == "pending_result"
    assert seedmod.seed_lifecycle("closed", date(2026, 9, 16), t) == "completed"
    assert seedmod.seed_lifecycle("closed", date(2026, 10, 6), t) == "scheduled"
    assert seedmod.seed_lifecycle("dropped", date(2026, 8, 6), t) == "unknown"
    assert seedmod.seed_lifecycle(None, date(2026, 8, 6), t) == "unknown"


def test_seed_is_idempotent_and_labels_its_observations():
    store = MemoryStore([
        prop("p1", "Lee", "A", sale_date="2026-10-06", bid=1500, url="https://lee.realforeclose.com/index.cfm?zaction=AUCTION&zmethod=PREVIEW&AuctionDate=10/06/2026", kind="sale"),
        prop("p2", "Lee", "B", sale_date="2026-09-16", status="closed", bid=0),
        prop("p3", "Lee", "C", sale_date=None),
        prop("p4", "DeSoto", "D", sale_date="2026-09-16", status="active"),
        prop("t1", "Nueces", "9377", state="TX", sale_date="2026-10-06", hs="tx_realauction", bid=21800),
    ])
    s1 = seedmod.seed(store, observed_at=T1, run_id="seed-1", today=TODAY)
    assert s1["eligible"] == 4 and s1["created"] == 4 and s1["observations"] == 4 and s1["already_present"] == 0
    assert s1["by_lifecycle"] == {"FL/scheduled": 1, "FL/completed": 1, "FL/pending_result": 1, "TX/scheduled": 1}
    assert all(o["feed"] == "seed" and o["harvest_run_id"] == "seed-1" for o in store.observations)
    by_case = {e["case_no"]: e for e in store.events}
    assert by_case["B"]["opening_bid"] is None            # bid 0 = not published
    assert by_case["A"]["event_url_kind"] == "sale"
    assert all(e["outcome"] == "unknown" for e in store.events)
    assert {o["raw_status"] for o in store.observations} == {"active", "closed"}
    s2 = seedmod.seed(store, observed_at=T2, run_id="seed-2", today=TODAY)
    assert s2["created"] == 0 and s2["already_present"] == 4 and s2["observations"] == 0
    assert len(store.events) == 4 and len(store.observations) == 4
    # A harvest after the seed re-observes the seeded event rather than duplicating it.
    s3 = run_fl(store, [fl_row("Lee", "A", "10/06/2026")], T3)
    assert s3.events_created == 0 and s3.events_seen_again == 1 and len(store.events) == 4


def test_seed_cli_is_dry_run_by_default(monkeypatch, capsys):
    calls = []

    class FakeReal:
        def fetch_properties(self, state, source):
            return [prop("p1", "Lee", "A", sale_date="2026-10-06")] if state == "FL" else []

        def fetch_events(self, state, source):
            return []

        def insert_events(self, rows):
            calls.append("insert")
            return rows

        def update_event(self, *_):
            calls.append("update")

        def insert_observations(self, rows):
            calls.append("obs")

    monkeypatch.setenv("SUPABASE_URL", "https://example.invalid")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "not-a-real-key")
    monkeypatch.setattr(seedmod, "PostgrestStore", lambda url, key: FakeReal())
    assert seedmod.main([]) == 0
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
                     "`properties` is never written"):
        assert required in section, required
