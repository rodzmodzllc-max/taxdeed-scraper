"""scripts/schedule_watchdog.py: the missed-schedule decision, with injected
run / job lists (no network), and its tables pinned to harvest-and-sync.yml."""
from __future__ import annotations

import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
import schedule_watchdog as W  # noqa: E402

WF = REPO / ".github" / "workflows" / "harvest-and-sync.yml"
WATCHDOG_WF = REPO / ".github" / "workflows" / "schedule-watchdog.yml"
UTC = timezone.utc

NAMES = {
    "deeds": "Harvest deed auctions + sync",
    "certificates": "Harvest certificates + sync (experimental)",
    "laft": "Harvest Lands Available PDFs + sync",
    "expansion": "Harvest six-state expansion (MI) + sync",
    "texas": "Harvest Texas tax sales (LGBS) + sync - daily",
    "backup": "Export database backup",
}


def at(hh, mm, day=27):
    return datetime(2026, 10, day, hh, mm, tzinfo=UTC)


def iso(t):
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def jobs(ran, skipped=()):
    out = [{"name": NAMES[j], "conclusion": "success"} for j in ran]
    out += [{"name": NAMES[j], "conclusion": "skipped"} for j in (set(NAMES) - set(ran)) | set(skipped)
            if j not in ran]
    out.append({"name": "Capture purchase / application evidence (manual only)", "conclusion": "skipped"})
    return out


_ids = iter(range(1000, 100000))


def run(created, ran, *, event="schedule", status="completed", bot=False, listed=True):
    rid = next(_ids)
    r = {"id": rid, "created_at": iso(created), "status": status, "event": event,
         "triggering_actor": {"login": W.BOT_LOGIN if bot else "rodzmodzllc-max"}}
    return r, (rid, jobs(ran) if listed else [])


def world(*items):
    runs = [r for r, _ in items]
    return runs, dict(j for _, j in items)


# Yesterday's full day of scheduled runs: everything covered up to 2026-10-27 00:00.
def yesterday():
    return [run(at(3, 40, 26), ["certificates", "laft", "expansion"]),
            run(at(4, 15, 26), ["deeds"]),
            run(at(10, 15, 26), ["deeds"]),
            run(at(11, 40, 26), ["certificates", "laft", "expansion", "texas", "backup"])]


# ---------------------------------------------------------------- decisions

def test_nothing_missed_means_no_action():
    items = yesterday() + [run(at(3, 40), ["certificates", "laft", "expansion"]), run(at(4, 20), ["deeds"])]
    d = W.decide(at(6, 49), *world(*items))
    assert d.action == "none" and d.job_input is None


def test_the_2026_10_27_drop_dispatches_deeds_first_then_one_job_per_tick():
    """03:37 and 04:13 never fired. 06:49: deeds, certificates, laft and
    expansion are due; `all` would add the once-a-day texas read, so one job
    goes per tick."""
    items = yesterday()
    d = W.decide(at(6, 49), *world(*items))
    assert d.action == "dispatch" and d.job_input == "deeds"
    assert d.due == ["certificates", "deeds", "expansion", "laft"]
    # While the dispatched run is queued / running: wait, never a second dispatch.
    items.append(run(at(6, 50), [], event="workflow_dispatch", status="in_progress", bot=True, listed=False))
    assert W.decide(at(7, 49), *world(*items)).action == "wait"
    # It finished (deeds attempted): the next missed job goes, never deeds again.
    items[-1] = run(at(6, 50), ["deeds"], event="workflow_dispatch", bot=True)
    d = W.decide(at(7, 49), *world(*items))
    assert d.action == "dispatch" and d.job_input == "laft"
    items.append(run(at(7, 50), ["laft"], event="workflow_dispatch", bot=True))
    assert W.decide(at(8, 49), *world(*items)).job_input == "expansion"
    items.append(run(at(8, 50), ["expansion"], event="workflow_dispatch", bot=True))
    assert W.decide(at(9, 49), *world(*items)).job_input == "certificates"
    items.append(run(at(9, 50), ["certificates"], event="workflow_dispatch", bot=True))
    assert W.decide(at(10, 49), *world(*items)).action == "none"


def test_a_missed_0413_alone_dispatches_job_deeds():
    items = yesterday() + [run(at(3, 40), ["certificates", "laft", "expansion"])]
    d = W.decide(at(6, 49), *world(*items))
    assert (d.action, d.job_input, d.due) == ("dispatch", "deeds", ["deeds"])


def test_a_fully_missed_1137_dispatches_job_all():
    items = yesterday() + [run(at(3, 40), ["certificates", "laft", "expansion"]), run(at(4, 20), ["deeds"]),
                           run(at(10, 20), ["deeds"])]
    d = W.decide(at(13, 49), *world(*items))
    assert (d.action, d.job_input) == ("dispatch", "all")
    assert set(d.due) == {"certificates", "laft", "expansion", "texas", "backup"}


def test_grace_a_late_scheduled_run_is_not_duplicated():
    """At 04:49 the 03:37 slot is only 72 minutes old: GitHub may still start
    it, so nothing is due yet."""
    d = W.decide(at(4, 49), *world(*yesterday()))
    assert d.action == "none"


def test_a_manual_dispatch_of_another_job_does_not_cover_the_slot():
    items = yesterday() + [run(at(4, 20), ["deeds"]),
                           run(at(4, 0), [], event="workflow_dispatch")]     # e.g. job=evidence: every harvest job skipped
    d = W.decide(at(6, 49), *world(*items))
    assert d.action == "dispatch" and set(d.due) == {"certificates", "laft", "expansion"}


def test_a_manual_dispatch_of_the_same_job_covers_it():
    items = yesterday() + [run(at(4, 20), ["deeds"]),
                           run(at(4, 30), ["certificates", "laft", "expansion", "deeds", "texas", "backup"],
                               event="workflow_dispatch")]
    assert W.decide(at(6, 49), *world(*items)).action == "none"


def test_a_failed_or_cancelled_job_is_attempted_not_missed():
    items = yesterday() + [run(at(4, 20), ["deeds"])]
    r, (rid, js) = run(at(3, 40), ["certificates", "laft", "expansion"])
    for j in js:
        if j["conclusion"] == "success":
            j["conclusion"] = "failure"
    assert W.decide(at(6, 49), *world(*items, (r, (rid, js)))).action == "none"


def test_a_bot_dispatch_cancelled_before_it_listed_jobs_blocks_a_second_dispatch():
    items = yesterday() + [run(at(4, 20), ["deeds"]),
                           run(at(5, 20), [], event="workflow_dispatch", status="completed", bot=True, listed=False)]
    d = W.decide(at(6, 49), *world(*items))
    assert d.action == "none"


def test_a_scheduled_run_cancelled_while_pending_does_not_cover():
    items = yesterday() + [run(at(4, 20), ["deeds"]), run(at(3, 40), [], listed=False)]
    d = W.decide(at(6, 49), *world(*items))
    assert d.action == "dispatch" and set(d.due) == {"certificates", "laft", "expansion"}


def test_never_dispatches_while_a_run_is_queued_or_in_progress():
    for status in ("queued", "in_progress", "waiting", "pending", "requested"):
        items = yesterday() + [run(at(6, 0), [], event="workflow_dispatch", status=status, listed=False)]
        d = W.decide(at(6, 49), *world(*items))
        assert d.action == "wait", status


def test_a_job_whose_next_slot_is_soon_is_left_to_it():
    """At 09:30 a missed 04:13 deeds read is left to the 10:13 run."""
    items = yesterday() + [run(at(3, 40), ["certificates", "laft", "expansion"])]
    assert W.decide(at(9, 30), *world(*items)).action == "none"


def test_slot_arithmetic_wraps_midnight():
    now = at(0, 30)
    assert W.last_slot("37 11 * * *", now) == at(11, 37, 26)
    assert W.next_slot("13 4 * * *", now) == at(4, 13)
    assert W.last_expected("deeds", at(5, 0)) == at(10, 13, 26)       # 04:13 + grace not yet reached
    assert W.last_expected("deeds", at(6, 0)) == at(4, 13)


# ---------------------------------------------------------------- pinned to the workflow

def _wf():
    return yaml.safe_load(WF.read_text(encoding="utf-8"))


def test_schedules_match_the_workflow_crons_and_job_conditions():
    wf = _wf()
    on = wf.get("on") or wf.get(True)
    crons = {c["cron"] for c in on["schedule"]}
    assert crons == set(W.SCHEDULES)
    for job in W.ALL_JOBS:
        cond = wf["jobs"][job]["if"]
        scheduled_on = {c for c in crons if f"github.event.schedule == '{c}'" in cond}
        assert scheduled_on == {c for c, js in W.SCHEDULES.items() if job in js}, job
    # No other job runs on a schedule.
    for name, job in wf["jobs"].items():
        if name not in W.ALL_JOBS:
            assert "github.event.schedule" not in str(job.get("if", "")), name


def test_job_all_runs_exactly_all_jobs_and_names_match():
    wf = _wf()
    for name, job in wf["jobs"].items():
        runs_on_all = "github.event.inputs.job == 'all'" in str(job.get("if", ""))
        assert runs_on_all == (name in W.ALL_JOBS), name
    for key, prefix in W.JOB_NAME_PREFIXES.items():
        assert wf["jobs"][key]["name"].startswith(prefix), key
        assert W.job_key(wf["jobs"][key]["name"]) == key
    options = wf.get("on", wf.get(True))["workflow_dispatch"]["inputs"]["job"]["options"]
    assert {"all", *W.ALL_JOBS} <= set(options)


def test_watchdog_workflow_is_offset_hourly_and_can_dispatch():
    wf = yaml.safe_load(WATCHDOG_WF.read_text(encoding="utf-8"))
    on = wf.get("on") or wf.get(True)
    (cron,) = [c["cron"] for c in on["schedule"]]
    minute = int(cron.split()[0])
    assert minute not in {13, 37} and all(abs(minute - m) >= 10 for m in (13, 37))
    assert wf["permissions"]["actions"] == "write"
    assert wf["concurrency"]["group"] != "harvest-and-sync"
    step = wf["jobs"]["watchdog"]["steps"][-1]
    assert "scripts/schedule_watchdog.py" in step["run"]
    assert step["env"]["GITHUB_TOKEN"] == "${{ secrets.GITHUB_TOKEN }}"


def test_logs_carry_no_property_data():
    src = (REPO / "scripts" / "schedule_watchdog.py").read_text(encoding="utf-8")
    assert not re.search(r"parcel|address|owner", src.split("# ------------------------------------------------------------------- I/O")[1], re.I)


def test_main_dispatches_once_with_injected_api(monkeypatch, capsys):
    calls = []
    items = yesterday()
    runs, by_run = world(*items)

    class FakeGH:
        def __init__(self, *a, **k):
            pass

        def runs_since(self, since):
            return runs

        def jobs(self, rid):
            return by_run[rid]

        def dispatch(self, ref, job_input):
            calls.append((ref, job_input))

    class FakeDT(datetime):
        @classmethod
        def now(cls, tz=None):
            return at(6, 49)

    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    monkeypatch.setenv("GITHUB_TOKEN", "x")
    monkeypatch.setattr(W, "GitHub", FakeGH)
    monkeypatch.setattr(W, "datetime", FakeDT)
    assert W.main(["--ref", "main"]) == 0
    assert calls == [("main", "deeds")]
    assert W.main(["--dry-run"]) == 0 and len(calls) == 1
    out = capsys.readouterr().out
    assert "action: dispatch job=deeds" in out


def test_main_without_a_token_does_nothing(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    assert W.main([]) == 2
