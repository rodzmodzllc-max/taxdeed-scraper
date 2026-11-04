"""Remediation after the Phase B real-harvest dry-run (PR #33, 2026-09-28):
three defects the audit of harvest run #181 surfaced, none of them in
Phase B itself.

1. Artifact glob. `out/harvest_all.*` never matched harvest_all_status.json
   (underscore, not dot, after `harvest_all`), so the uploaded artifact
   lacked the per-county completeness file that both the closeout in
   sync-harvest-to-supabase.ps1 and the Phase B writer read. The same shape
   hid harvest_certificates_status.json and harvest_texas_status.json.
2. Florida close-out day. The closeout compared sale_date against the
   runner's UTC date with `lte`, so from 8 pm ET a same-day sale already
   counted as passed: run #181 (00:16 UTC 09-28) closed out 11 sales dated
   09-28 during the Florida evening of 09-27. The closeout now measures the
   day at UTC-6 - the earliest local date anywhere in Florida, the same
   convention as auction_events_writer.py's SALE_DAY_UTC_OFFSET - and
   closes only when sale_date is strictly before it.
3. Re-listed rows. The upsert never sent `status`, so a row closed out in
   one run and re-listed by the county under a new date stayed 'closed'
   with a future sale date (15 rows in run #181). The upsert now sends
   status='active' for every harvested row - each was read off a scheduled
   feed this run - and migration 006's trigger clears gone_since on the way
   back. A closed row that is not in the harvest is not in the payload.

PowerShell cannot run in this sandbox (the same constraint
test_phase30b_deed_completeness_and_closed_gone_since.py documents), so each
fix is proven two ways: structural assertions on the exact script/workflow
text that runs in production, and a literal port of the decision the
change makes, exercised against the scenarios the remediation brief names.
The re-listing tests drive the real Phase B writer to show the property
fix leaves event history alone.
"""

from __future__ import annotations

import fnmatch
import pathlib
import sys
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

yaml = pytest.importorskip("yaml", reason="PyYAML is needed to parse the workflow")

REPO = pathlib.Path(__file__).resolve().parents[2]
WORKFLOW = REPO / ".github" / "workflows" / "harvest-and-sync.yml"
SYNC = REPO / "scripts" / "sync-harvest-to-supabase.ps1"
FL_HARVESTER = REPO / "scripts" / "harvest_all_counties.ps1"
CERT_HARVESTER = REPO / "scripts" / "harvest_lienhub_certificates.ps1"
TX_HARVESTER = REPO / "harvesters" / "texas_harvester.py"

sys.path.insert(0, str(REPO / "scripts"))
import auction_events_writer as w  # noqa: E402
import test_phase_b_auction_event_writers as pb  # noqa: E402  (MemoryStore, prop, fl_row)


def _sync_src() -> str:
    return SYNC.read_text()


def _closeout_section() -> str:
    src = _sync_src()
    marker = "# ---- Close out properties that fell off the Waiting feed ----"
    assert marker in src
    return src[src.index(marker):]


def _upsert_row_literal() -> str:
    src = _sync_src()
    start = src.index("$rows += [ordered]@{")
    return src[start:src.index('Write-Output "Prepared', start)]


def _code_lines(text: str) -> list[str]:
    return [ln for ln in text.splitlines() if not ln.strip().startswith("#")]


# ===========================================================================
# 1. Artifact glob
# ===========================================================================


def _upload_steps() -> dict[str, dict]:
    wf = yaml.safe_load(WORKFLOW.read_text())
    out: dict[str, dict] = {}
    for job, spec in wf["jobs"].items():
        for step in spec["steps"]:
            if str(step.get("uses", "")).startswith("actions/upload-artifact"):
                assert job not in out, f"two upload steps in job {job}"
                out[job] = step
    return out


def _patterns(step: dict) -> list[str]:
    return [p.strip() for p in str(step["with"]["path"]).splitlines() if p.strip()]


def _matched(path: str, patterns: list[str]) -> bool:
    # actions/upload-artifact resolves `path` with @actions/glob; for these
    # single-directory names fnmatch's `*` is the same rule.
    return any(fnmatch.fnmatchcase(path, p) for p in patterns)


def _evidence_steps() -> dict[str, dict]:
    """The `Prepare artifact` step of each job - the only writer of the
    out/public/ and out/private/ directories the upload step publishes
    (SaaS hardening, 2026-09-29: raw harvests are no longer uploaded in the
    clear; see scripts/artifact_evidence.py and
    tests/python/test_artifact_privacy.py)."""
    wf = yaml.safe_load(WORKFLOW.read_text())
    out: dict[str, dict] = {}
    for job, spec in wf["jobs"].items():
        for step in spec["steps"]:
            if "scripts/artifact_evidence.py" in str(step.get("run", "")):
                assert job not in out, f"two evidence steps in job {job}"
                out[job] = step
    return out


def _evidence_args(step: dict) -> str:
    return str(step["run"]).split("scripts/artifact_evidence.py", 1)[1]


def test_A1_deeds_artifact_captures_the_status_file_and_the_harvest():
    """The status file is reproduced verbatim inside the public evidence
    file (--status) and the harvest files are hashed, counted and, with a
    key, encrypted (the raw glob). Both directories are what gets uploaded."""
    args = _evidence_args(_evidence_steps()["deeds"])
    assert "--status out/harvest_all_status.json" in args
    assert '"out/harvest_all.*"' in args
    assert _patterns(_upload_steps()["deeds"]) == ["out/public/", "out/private/"]


def test_A2_the_previous_glob_alone_never_matched_the_status_file():
    """The regression itself: `harvest_all.*` needs a dot right after
    `harvest_all`, and the status file has an underscore there. The glob
    still feeds the raw files to the evidence step; the status file is named
    explicitly (--status) because the glob cannot cover it."""
    assert not fnmatch.fnmatchcase("out/harvest_all_status.json", "out/harvest_all.*")
    args = _evidence_args(_evidence_steps()["deeds"])
    assert "out/harvest_all.*" in args
    assert "out/harvest_all_status.json" in args


def test_A3_status_filename_matches_what_the_harvester_writes_and_the_readers_read():
    assert 'Join-Path $outDir "harvest_all_status.json"' in FL_HARVESTER.read_text()
    assert '"../out/harvest_all_status.json"' in _sync_src()
    assert w.FL_STATUS_JSON.name == "harvest_all_status.json"
    assert "out/harvest_all_status.json" in _evidence_args(_evidence_steps()["deeds"])


def test_A4_certificate_and_texas_status_files_are_captured_too():
    steps = _evidence_steps()
    assert 'Join-Path $outDir "harvest_certificates_status.json"' in CERT_HARVESTER.read_text()
    assert "--status out/harvest_certificates_status.json" in _evidence_args(steps["certificates"])
    assert '"out/harvest_certificates.*"' in _evidence_args(steps["certificates"])
    assert 'out_dir / "harvest_texas_status.json"' in TX_HARVESTER.read_text()
    assert "--status out/harvest_texas_status.json" in _evidence_args(steps["texas"])
    assert '"out/harvest_texas.*"' in _evidence_args(steps["texas"])


def test_A5_upload_steps_are_otherwise_unchanged():
    steps = _upload_steps()
    # "evidence" (Customer Value / Evidence Acquisition sprint) is manual-only
    # and uploads the same evidence-only layout; the five original jobs are unchanged.
    # "outcomes" (auction-outcome evidence sprint) is manual-only and uploads
    # the same evidence-only layout.
    # "expansion" (six-state sprint) uploads the same evidence-only layout per matrix leg.
    # "enrich" (property-enrichment sprint) is manual-only and uploads the same layout per matrix leg.
    # "available" (all-sources AVAILABLE enrichment engine) is manual-only and uploads the same layout.
    # "geocode" (authoritative geocoding, 2026-10-06) is manual-only and uploads the same layout.
    assert set(steps) == {"deeds", "certificates", "laft", "texas", "backup", "evidence", "outcomes", "expansion", "enrich", "storage", "available", "geocode", "publication"}
    assert _patterns(steps["geocode"]) == ["out/public/", "out/private/"]
    assert _patterns(steps["available"]) == ["out/public/", "out/private/"]
    assert _patterns(steps["expansion"]) == ["out/public/", "out/private/"]
    assert _patterns(steps["enrich"]) == ["out/public/", "out/private/"]
    deeds = steps["deeds"]
    assert deeds["if"] == "always()"
    assert deeds["with"]["name"] == "harvest-deeds-${{ github.run_id }}"
    assert deeds["with"]["retention-days"] == 30
    assert deeds["with"]["if-no-files-found"] == "warn"
    # The backup is uploaded only as evidence + encrypted copies; the export
    # itself still lands in out/backup/ and is fed to the evidence step.
    assert _patterns(steps["backup"]) == ["out/public/", "out/private/"]
    assert "--status out/backup/manifest.json" in _evidence_args(_evidence_steps()["backup"])
    assert '"out/backup/*"' in _evidence_args(_evidence_steps()["backup"])
    # The Phase B step still follows the property sync in both jobs.
    wf = yaml.safe_load(WORKFLOW.read_text())
    for job in ("deeds", "texas"):
        names = [s.get("name", "") for s in wf["jobs"][job]["steps"]]
        assert "Record auction events (Phase B)" in names
        assert names.index("Record auction events (Phase B)") > names.index("Upload artifact (evidence + encrypted raw)")


# ===========================================================================
# 2. Florida close-out day
# ===========================================================================

FLORIDA_DAY_OFFSET = timedelta(hours=-6)
NEW_YORK = ZoneInfo("America/New_York")   # Florida east of the Apalachicola
CHICAGO = ZoneInfo("America/Chicago")     # the Florida panhandle west of it


def florida_today(utc_now: datetime) -> date:
    """Port of `[DateTime]::UtcNow.AddHours(-6).ToString("yyyy-MM-dd")`."""
    assert utc_now.tzinfo == timezone.utc
    return (utc_now + FLORIDA_DAY_OFFSET).date()


def sale_day_ended(sale_date: date, utc_now: datetime) -> bool:
    """Port of the closeout query's `sale_date=lt.$floridaToday`."""
    return sale_date < florida_today(utc_now)


def old_rule(sale_date: date, utc_now: datetime) -> bool:
    """What ran before: `(Get-Date)` on a UTC runner, compared with `lte`."""
    return sale_date <= utc_now.date()


def _utc(y, m, d, hh=0, mm=0, ss=0) -> datetime:
    return datetime(y, m, d, hh, mm, ss, tzinfo=timezone.utc)


def test_B1_closeout_measures_the_day_at_utc_minus_6_and_compares_strictly():
    section = _closeout_section()
    define = '$floridaToday = [DateTime]::UtcNow.AddHours(-6).ToString("yyyy-MM-dd")'
    assert define in section
    assert "sale_date=lt.$floridaToday" in section
    assert "sale_date=lte." not in section
    code = "\n".join(_code_lines(section))
    assert "(Get-Date)" not in code
    assert "$today" not in code
    assert section.index(define) < section.index("sale_date=lt.$floridaToday")
    # Still inside the completeness gate: no COMPLETE county, no date, no closeout.
    assert section.index("if ($completeCounties.Count -gt 0) {") < section.index(define)


def test_B2_same_convention_as_phase_b():
    assert w.SALE_DAY_UTC_OFFSET == timezone(FLORIDA_DAY_OFFSET)


def test_B3_run_181_utc_rollover_does_not_close_a_same_day_sale():
    """The production case: 00:16 UTC on 09-28 is 8:16 pm EDT on 09-27."""
    sale = date(2026, 9, 28)
    now = _utc(2026, 9, 28, 0, 16, 40)
    assert now.astimezone(NEW_YORK).date() == date(2026, 9, 27)
    assert old_rule(sale, now) is True, "the old rule reproduces the bug"
    assert sale_day_ended(sale, now) is False


def test_B4_shortly_before_midnight_eastern_on_the_sale_day_does_not_close():
    sale = date(2026, 9, 28)
    now = _utc(2026, 9, 29, 3, 59, 59)  # 11:59:59 pm EDT on the sale day
    assert now.astimezone(NEW_YORK).date() == sale
    assert old_rule(sale, now) is True
    assert sale_day_ended(sale, now) is False


def test_B5_closes_only_after_the_florida_day_has_ended():
    sale = date(2026, 9, 28)
    assert sale_day_ended(sale, _utc(2026, 9, 29, 5, 59, 59)) is False  # 00:59 CDT, 01:59 EDT on 09-29: not yet
    assert sale_day_ended(sale, _utc(2026, 9, 29, 6, 0, 0)) is True      # 00:00 at UTC-6
    assert sale_day_ended(sale, _utc(2026, 9, 29, 10, 0, 0)) is True     # the next scheduled harvest
    for utc_dt in (_utc(2026, 9, 29, 6), _utc(2026, 9, 29, 10)):
        assert utc_dt.astimezone(NEW_YORK).date() > sale
        assert utc_dt.astimezone(CHICAGO).date() > sale


@pytest.mark.parametrize("sale", [
    date(2026, 3, 8),    # spring forward (EST->EDT, CST->CDT at 2 am local)
    date(2026, 11, 1),   # fall back
    date(2026, 3, 7),    # the day before the transition
    date(2026, 11, 2),   # the day after
    date(2026, 7, 15),   # plain DST
    date(2026, 1, 15),   # plain standard time
])
def test_B6_dst_never_closes_early_in_either_florida_zone(sale):
    start = _utc(sale.year, sale.month, sale.day)
    end = start + timedelta(hours=36)
    t = start
    fired_at = None
    while t <= end:
        ended = sale_day_ended(sale, t)
        ny, chi = t.astimezone(NEW_YORK).date(), t.astimezone(CHICAGO).date()
        # Never later than any Florida-local date (the UTC-6 guarantee).
        assert florida_today(t) <= ny and florida_today(t) <= chi, t
        if ended:
            assert ny > sale and chi > sale, f"closed at {t} while a Florida clock still showed {sale}"
            fired_at = fired_at or t
        else:
            assert t < start + timedelta(hours=30), f"still not closed at {t}"
        t += timedelta(minutes=15)
    assert fired_at == start + timedelta(hours=30), "closes at exactly 00:00 of the next day at UTC-6"


def test_B7_never_later_than_a_florida_clock_across_a_full_year():
    t = _utc(2026, 1, 1)
    while t < _utc(2027, 1, 1):
        fl = florida_today(t)
        assert fl <= t.astimezone(NEW_YORK).date()
        assert fl <= t.astimezone(CHICAGO).date()
        t += timedelta(hours=1)


def test_B8_closeout_still_writes_only_status_closed_and_infers_nothing():
    section = _closeout_section()
    assert '\'{"status":"closed"}\'' in section
    code = "\n".join(_code_lines(section))
    for forbidden in ("sold", "redeemed", "outcome", "sold_price", "winning"):
        assert forbidden not in code


# ===========================================================================
# 3. Re-listed rows
# ===========================================================================

GONE = {"dropped", "sold", "notfound", "closed"}
PAYLOAD_COLUMNS = ("source", "county", "case_no", "parcel", "address", "bid", "assessed",
                   "sale_date", "url_appraiser", "url_auction", "url_auction_kind", "status")


def payload_from_harvest_row(r: dict) -> dict:
    """Mirror of the `$rows += [ordered]@{ ... }` literal: only these columns."""
    url = r.get("auction_url") or ""
    return {
        "source": "auction", "county": r["county"], "case_no": r["case"], "parcel": r.get("parcel"),
        "address": r["address"], "bid": r.get("bid"), "assessed": r.get("assessed"),
        "sale_date": r.get("sale_date_iso"), "url_appraiser": r.get("appraiser"),
        "url_auction": url or None,
        "url_auction_kind": None if not url else ("sale" if "zaction=auction&zmethod=preview&auctiondate=" in url.lower() else "county"),
        "status": "active",
    }


def track_gone_since(old: dict, new: dict, now: str) -> None:
    """Port of migration 006's track_gone_since() BEFORE UPDATE trigger."""
    gone_now = new.get("status") in GONE
    gone_was = (old.get("status") or "") in GONE
    if gone_now and not gone_was:
        new["gone_since"] = now
    elif not gone_now:
        new["gone_since"] = None
    else:
        new["gone_since"] = old.get("gone_since")


def upsert_merge(existing: dict, payload: dict, now: str) -> dict:
    """`Prefer: resolution=merge-duplicates`: only payload columns touch the
    row, then the trigger runs."""
    assert set(payload) == set(PAYLOAD_COLUMNS)
    new = dict(existing)
    new.update(payload)
    track_gone_since(existing, new, now)
    return new


def test_C1_upsert_sends_status_active_and_no_hand_researched_column():
    literal = _upsert_row_literal()
    assert 'status        = "active"' in literal
    assert '"closed"' not in literal
    for never in ("gone_since", "owner_name", "lien_level", "lien_note", "notes", "homestead",
                  "outcome", "sold_price", "url_streetview", "url_zillow", "url_taxcoll", "url_title"):
        assert never not in literal, never
    # The payload columns the port mirrors are exactly the ones the script sends.
    for col in PAYLOAD_COLUMNS:
        assert f"{col} " in literal, col


def test_C2_active_is_written_only_by_the_upsert_and_closed_only_by_the_closeout():
    code = "\n".join(_code_lines(_sync_src()))
    assert code.count('"active"') == 1
    assert code.count('"closed"') == 1
    assert code.index('"active"') < code.index('"closed"')


def test_C3_a_closed_row_that_is_relisted_comes_back_active_and_keeps_hand_research():
    existing = {"id": "p1", "state": "FL", "source": "auction", "county": "Lee", "case_no": "2026-TD-1",
                "status": "closed", "gone_since": "2026-09-20T22:16:00+00:00", "sale_date": "2026-09-20",
                "owner_name": "Jane Doe", "lien_level": "clear", "lien_note": "checked 9/1", "bid": 1500}
    harvested = {"county": "Lee", "case": "2026-TD-1", "address": "1 Main St", "bid": 1800, "sale_date_iso": "2026-10-20",
                 "auction_url": "https://lee.realforeclose.com/index.cfm?zaction=AUCTION&zmethod=PREVIEW&AuctionDate=10/20/2026"}
    merged = upsert_merge(existing, payload_from_harvest_row(harvested), now="2026-09-28T10:00:00+00:00")
    assert merged["status"] == "active"
    assert merged["gone_since"] is None
    assert merged["sale_date"] == "2026-10-20" and merged["bid"] == 1800
    assert merged["owner_name"] == "Jane Doe" and merged["lien_level"] == "clear" and merged["lien_note"] == "checked 9/1"
    assert merged["id"] == "p1"


def test_C4_a_closed_row_absent_from_the_harvest_is_not_touched():
    """The payload is built from harvest rows only, so a genuinely closed
    listing (not on the Waiting feed) never receives status='active'; and
    the closeout can only ever write 'closed', never reopen."""
    harvest = [{"county": "Lee", "case": "2026-TD-2", "address": "2 Main St", "sale_date_iso": "2026-10-20"}]
    payload_keys = {(payload_from_harvest_row(r)["county"], payload_from_harvest_row(r)["case_no"]) for r in harvest}
    closed = {"county": "Lee", "case_no": "2026-TD-1", "status": "closed", "gone_since": "2026-09-20T22:16:00+00:00"}
    assert (closed["county"], closed["case_no"]) not in payload_keys
    assert '\'{"status":"closed"}\'' in _closeout_section()


def test_C5_relisting_under_a_new_date_creates_a_new_event_and_keeps_the_old_one():
    """Driven through the real writer. The property row's status is 'closed'
    throughout (as it was before the upsert fix) - the writer does not read
    it - and event identity stays (property_id, scheduled_sale_date)."""
    store = pb.MemoryStore([pb.prop("p1", "Lee", "A1", sale_date="2026-09-20", status="closed")])
    first = w.record_sightings(store, w.sightings_from_fl_harvest([pb.fl_row("Lee", "A1", "09/20/2026")]),
                               scope=("FL", "auction"), observed_at="2026-09-10T10:00:00+00:00", run_id="r1",
                               complete_counties={"Lee"}, today=date(2026, 9, 10))
    assert first.events_created == 1
    old_event = dict(store.events[0])
    old_obs = [dict(o) for o in store.observations]

    # Later (the old date still ahead) the county lists the same property
    # under a new date. No COMPLETE evidence this run: the old event is left
    # exactly as it was.
    second = w.record_sightings(store, w.sightings_from_fl_harvest([pb.fl_row("Lee", "A1", "10/20/2026")]),
                                scope=("FL", "auction"), observed_at="2026-09-15T10:00:00+00:00", run_id="r2",
                                complete_counties=set(), today=date(2026, 9, 15))
    assert second.events_created == 1 and second.events_superseded == 0
    assert len(store.events) == 2
    assert {(e["property_id"], e["scheduled_sale_date"]) for e in store.events} == {("p1", "2026-09-20"), ("p1", "2026-10-20")}
    assert [e for e in store.events if e["id"] == old_event["id"]][0] == old_event
    assert [o for o in store.observations if o["event_id"] == old_event["id"]] == old_obs

    # With COMPLETE evidence the old, not-yet-passed event is superseded per
    # Phase B's approved rule - still present, never deleted, its history kept.
    third = w.record_sightings(store, w.sightings_from_fl_harvest([pb.fl_row("Lee", "A1", "10/20/2026")]),
                               scope=("FL", "auction"), observed_at="2026-09-15T22:00:00+00:00", run_id="r3",
                               complete_counties={"Lee"}, today=date(2026, 9, 15))
    assert third.events_created == 0 and third.events_seen_again == 1 and third.events_superseded == 1
    kept = [e for e in store.events if e["id"] == old_event["id"]][0]
    assert kept["scheduled_sale_date"] == "2026-09-20" and kept["lifecycle"] == "superseded" and kept["outcome"] == "unknown"
    assert old_obs[0] in store.observations
    derived = [o for o in store.observations if o["event_id"] == old_event["id"] and o["feed"] == w.DERIVED_FEED]
    assert len(derived) == 1 and derived[0]["raw_status"] is None and derived[0]["outcome"] == "unknown"
    assert store.deleted == []


def test_C5b_relisting_after_the_old_date_passed_marks_it_unknown_never_completed():
    """Same re-listing, but the county re-lists only after the old sale day
    has passed and the listing was last seen BEFORE that day. Phase B's rule
    (unchanged by this remediation): the old event becomes `unknown`, not
    `completed` - it left the feed before the sale could happen - and it is
    kept beside the new event."""
    store = pb.MemoryStore([pb.prop("p1", "Lee", "A1", sale_date="2026-09-20", status="closed")])
    w.record_sightings(store, w.sightings_from_fl_harvest([pb.fl_row("Lee", "A1", "09/20/2026")]),
                       scope=("FL", "auction"), observed_at="2026-09-10T10:00:00+00:00", run_id="r1",
                       complete_counties={"Lee"}, today=date(2026, 9, 10))
    old_id = store.events[0]["id"]
    s = w.record_sightings(store, w.sightings_from_fl_harvest([pb.fl_row("Lee", "A1", "10/20/2026")]),
                           scope=("FL", "auction"), observed_at="2026-09-28T10:00:00+00:00", run_id="r2",
                           complete_counties={"Lee"}, today=date(2026, 9, 28))
    assert s.events_created == 1 and s.events_unknown == 1 and s.events_completed == 0 and s.events_superseded == 0
    old = [e for e in store.events if e["id"] == old_id][0]
    assert old["scheduled_sale_date"] == "2026-09-20" and old["lifecycle"] == "unknown" and old["outcome"] == "unknown"
    assert len(store.events) == 2 and store.deleted == []


def test_C6_property_status_never_reaches_the_events():
    rows = w.sightings_from_fl_harvest([pb.fl_row("Lee", "A1", "10/20/2026")])
    results = []
    for status in ("closed", "active", "dropped"):
        store = pb.MemoryStore([pb.prop("p1", "Lee", "A1", sale_date="2026-10-20", status=status)])
        w.record_sightings(store, rows, scope=("FL", "auction"), observed_at="2026-09-28T10:00:00+00:00",
                           run_id="r", complete_counties={"Lee"}, today=date(2026, 9, 28))
        results.append((store.events, store.observations))
    assert results[0] == results[1] == results[2]
    for ev in results[0][0]:
        assert ev["outcome"] == "unknown" and not (w.FORBIDDEN_EVENT_KEYS & set(ev))
