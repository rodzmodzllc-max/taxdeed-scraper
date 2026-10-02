"""Customer-value sprint (2026-10-01): deterministic change detection, alerts
and saved-search matching. No speculation: every event is a field the row
carries changing; dropping off a list is "removed", never a sale."""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
import detect_property_changes as D  # noqa: E402
import saved_search_match as SSM  # noqa: E402

CASES = json.loads((REPO / "tests/python/fixtures/saved_search_cases.json").read_text(encoding="utf-8"))
WORKFLOW = (REPO / ".github/workflows/harvest-and-sync.yml").read_text(encoding="utf-8")


def _row(**kw):
    base = {"id": "p1", "state": "FL", "county": "Bay", "source": "laft", "source_id": "fl_laft_pioneer", "case_no": "C-1", "address": "3 Oak Ave",
            "status": "active", "purchase_amount": 2000, "purchase_path_type": None, "list_url": "https://x", "publication_status": "APPROVED_GRANDFATHERED",
            "assessed": 60000, "acreage": 1.0}
    base.update(kw)
    return base


@pytest.mark.parametrize("i", range(len(CASES["cases"])))
def test_c01_saved_search_cases(i):
    case = CASES["cases"][i]
    now = datetime.fromisoformat(CASES["now"].replace("Z", "+00:00"))
    assert SSM.matches(case["criteria"], CASES["rows"][case["row"]], now=now) is case["match"], case


def test_c02_first_run_is_a_baseline_and_emits_nothing():
    p = D.plan([_row()], {}, baseline_exists=False)
    assert p["events"] == [] and list(p["writes"]) == ["p1"] and p["counts"][("fl_laft_pioneer", "laft")]["observed"] == 1


def test_c03_new_listing_only_after_a_baseline():
    p = D.plan([_row(id="p2")], {"p1": D.snapshot(_row())}, baseline_exists=True)
    assert [(e["kind"], e["property_id"]) for e in p["events"]] == [("new_listing", "p2")]
    assert p["counts"][("fl_laft_pioneer", "laft")]["added"] == 1


def test_c04_status_transitions_never_say_sold():
    old = D.snapshot(_row())
    assert D.diff(old, D.snapshot(_row(status="closed")))[0][:2] == ("removed", "status")
    assert D.diff(D.snapshot(_row(status="closed")), D.snapshot(_row()))[0][:2] == ("reactivated", "status")
    title, detail = D.describe({"kind": "removed", "field": "status", "old": "active", "new": "closed", "row": _row(), "property_id": "p1"})
    assert title.startswith("No longer listed") and "not a sale" in detail and "sold" not in (title + detail).lower().replace("not a sale", "")


def test_c05_each_field_maps_to_its_kind_and_unchanged_rows_write_nothing():
    old = D.snapshot(_row())
    assert D.plan([_row()], {"p1": old}, baseline_exists=True)["events"] == []
    changed = _row(purchase_amount=2500, purchase_path_type="phone_mail", list_url="https://y", assessed=61000, sale_date="2026-11-01")
    kinds = {(k, f) for k, f, _, _ in D.diff(old, D.snapshot(changed))}
    assert kinds == {("opening_bid_changed", "opening_bid"), ("acquisition_path_changed", "purchase_path_type"),
                     ("source_changed", "list_url"), ("field_changed", "assessed"), ("sale_date_changed", "sale_date")}
    assert ("result_published", "result_date") in {(k, f) for k, f, _, _ in D.diff(old, D.snapshot(_row(result_date="2026-10-02")))}


def test_c06_alerts_go_to_watchers_and_matching_saved_searches_only():
    old = D.snapshot(_row())
    events = D.plan([_row(status="closed"), _row(id="p9", county="Polk")], {"p1": old, "p0": old}, baseline_exists=True)["events"]
    searches = [{"id": "s1", "user_id": "u2", "name": "Bay", "state": "FL", "criteria": {"counties": ["Polk"]}, "alerts_enabled": True},
                {"id": "s2", "user_id": "u3", "name": "Other", "state": "FL", "criteria": {"counties": ["Leon"]}, "alerts_enabled": True},
                {"id": "s3", "user_id": "u4", "name": "Off", "state": "FL", "criteria": {}, "alerts_enabled": False}]
    alerts = D.alerts_for(events, watchers={"p1": ["u1", "u5"]}, searches=searches, prefs={"u5": {"watch_changes": False}})
    got = sorted((a["user_id"], a["kind"], a["property_id"]) for a in alerts)
    assert got == [("u1", "watched_status", "p1"), ("u2", "saved_search_new_match", "p9")]


def test_c07_coordinates_and_imagery_are_events_never_alerts():
    old = D.snapshot(_row())
    ev = D.plan([_row(latitude=29.1, photo_url="https://i")], {"p1": old}, baseline_exists=True)["events"]
    assert {e["field"] for e in ev} == {"has_coordinates", "has_imagery"}
    assert D.alerts_for(ev, watchers={"p1": ["u1"]}, searches=[], prefs={}) == []


def test_c08_wired_into_every_sync_job_without_failing_it():
    for args in ("--state FL --source auction", "--state FL --source certificate", "--state FL --source laft || true",
                 "--state LA --source laft || true", "--state TX --source laft || true", "--state ${{ matrix.state }}"):
        assert f"detect_property_changes.py {args}" in WORKFLOW, args
    assert WORKFLOW.count("name: Change detection - deterministic property changes and customer alerts") == 4
    assert WORKFLOW.count("name: Restore change-detection snapshot cache") == 3
    src = (REPO / "scripts/detect_property_changes.py").read_text(encoding="utf-8")
    assert "texas_harvester" not in src and "requests" not in src.split('"""', 2)[2]


def test_c09_no_credentials_means_no_writes(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_KEY", raising=False)
    assert D.main(["--state", "FL"]) == 0
    assert "nothing detected" in capsys.readouterr().out


def test_c10_frontend_mirrors_every_criterion_and_degrades_without_024():
    app = (REPO / "public/app.js").read_text(encoding="utf-8")
    body = app[app.index("function savedSearchMatches("):app.index("window.__tdwSavedSearchMatches")]
    for key in SSM.CRITERIA_KEYS:
        assert f"c.{key}" in body, key
    assert (REPO / "app.js").read_text(encoding="utf-8") == app                     # mirrored
    # Every 024 table is feature-detected; nothing assumes the migration ran.
    for wording in ("Alerts are not enabled on this deployment yet", "Server change history is not enabled on this deployment yet",
                    "Saved in this browser only", "E-mail - not configured on this deployment"):
        assert wording in app, wording
    # Analytics never send the search text.
    track_calls = [l for l in app.splitlines() if 'track("search_performed"' in l]
    assert track_calls and all("state.search)" not in l.replace("!!state.search", "") for l in track_calls)
