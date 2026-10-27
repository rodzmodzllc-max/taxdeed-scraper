#!/usr/bin/env python3
"""Missed-schedule watchdog for harvest-and-sync.yml (2026-10-27).

On 2026-10-27 GitHub never started the 03:37 and 04:13 UTC scheduled runs of
harvest-and-sync.yml (a schedule drop: no run, no error, nothing to retry).
This script runs on its own cron (.github/workflows/schedule-watchdog.yml)
and, when a scheduled read was missed, dispatches the harvest workflow once
with the `job` input that reproduces it.

The decision (`decide()`) is pure and works per JOB, not per run:

  * each scheduled job (deeds, certificates, laft, expansion, texas, backup)
    has a LAST EXPECTED time - the latest cron slot that runs it and lies at
    least GRACE before now (GitHub delays scheduled runs; a run that is only
    late must not be duplicated);
  * the job is COVERED when any run of the workflow (schedule, a manual
    dispatch, an earlier watchdog dispatch - any event) created since that
    time actually attempted it: the job is listed in the run's jobs and was
    not skipped. A dispatch of job=evidence, or the 04:13 deeds run, does not
    cover laft - its laft job was skipped;
  * a job is never dispatched twice for the same slot: a run this watchdog
    dispatched (triggering actor github-actions[bot]) since the slot blocks
    every job it attempted, and blocks every due job when its job list is
    empty (cancelled while pending - which job it was for cannot be told);
  * nothing is dispatched while any run of the workflow is queued or in
    progress (one concurrency slot: a second pending run would replace the
    first), nor for a job whose next scheduled slot is less than SOON away.

What is dispatched (the workflow's `job` input takes ONE value):
  * deeds slots ('13 10', '13 4')        -> job=deeds (exact);
  * the '37 11' slot when everything it runs is due -> job=all: `all` runs
    the same five jobs plus deeds, a read that already runs twice a day and
    writes only what changed (scripts/write_diff.py) - the closest set;
  * the '37 3' slot (certificates + laft + expansion) has no single input:
    `all` would add the once-a-day Texas read. The watchdog dispatches one
    job per tick in DISPATCH_PRIORITY order (laft, expansion, certificates);
    each later tick, once the previous dispatch has finished, sends the next.

Logs: counts, job names and run ids only.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

WORKFLOW_FILE = "harvest-and-sync.yml"
BOT_LOGIN = "github-actions[bot]"

# cron (as written in harvest-and-sync.yml) -> the jobs that run on it. Pinned
# against the workflow's own `if:` conditions by tests/python/test_schedule_watchdog.py.
SCHEDULES: dict[str, tuple[str, ...]] = {
    "13 10 * * *": ("deeds",),
    "13 4 * * *": ("deeds",),
    "37 11 * * *": ("certificates", "laft", "expansion", "texas", "backup"),
    "37 3 * * *": ("certificates", "laft", "expansion"),
}
# job key -> the start of its display name in the jobs API (pinned by the test).
JOB_NAME_PREFIXES: dict[str, str] = {
    "deeds": "Harvest deed auctions",
    "certificates": "Harvest certificates",
    "laft": "Harvest Lands Available",
    "expansion": "Harvest six-state expansion",
    "texas": "Harvest Texas tax sales",
    "backup": "Export database backup",
}
# The jobs a `job=all` dispatch runs (pinned by the test).
ALL_JOBS = frozenset(JOB_NAME_PREFIXES)
# Jobs `all` may add beyond what is due: deeds is read twice a day anyway.
SAFE_EXTRA_FOR_ALL = frozenset({"deeds"})
DISPATCH_PRIORITY = ("deeds", "laft", "expansion", "certificates", "texas", "backup")

GRACE = timedelta(minutes=100)     # GitHub has started scheduled runs ~90 min late
SKEW = timedelta(minutes=10)       # a run created just before the slot still counts
SOON = timedelta(minutes=60)       # the next scheduled slot will do it
ACTIVE_STATUSES = frozenset({"queued", "in_progress", "waiting", "pending", "requested"})


def _ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _parse_cron(cron: str) -> tuple[int, int]:
    minute, hour, *rest = cron.split()
    if rest != ["*", "*", "*"]:
        raise ValueError(f"only daily 'M H * * *' crons are supported: {cron!r}")
    return int(minute), int(hour)


def last_slot(cron: str, before: datetime) -> datetime:
    """The latest time this daily cron fired at or before `before`."""
    minute, hour = _parse_cron(cron)
    t = before.replace(hour=hour, minute=minute, second=0, microsecond=0)
    return t if t <= before else t - timedelta(days=1)


def next_slot(cron: str, after: datetime) -> datetime:
    minute, hour = _parse_cron(cron)
    t = after.replace(hour=hour, minute=minute, second=0, microsecond=0)
    return t if t > after else t + timedelta(days=1)


def last_expected(job: str, now: datetime, grace: timedelta = GRACE) -> datetime:
    return max(last_slot(c, now - grace) for c, jobs in SCHEDULES.items() if job in jobs)


def next_expected(job: str, now: datetime) -> datetime:
    return min(next_slot(c, now) for c, jobs in SCHEDULES.items() if job in jobs)


def job_key(name: str) -> str | None:
    for key, prefix in JOB_NAME_PREFIXES.items():
        if (name or "").startswith(prefix):
            return key
    return None


def attempted(jobs: list[dict] | None) -> set[str] | None:
    """The scheduled-job keys a run attempted (listed and not skipped), or
    None when the run lists no jobs at all (cancelled while pending)."""
    if not jobs:
        return None
    out = set()
    for j in jobs:
        key = job_key(j.get("name", ""))
        if key and j.get("conclusion") != "skipped":
            out.add(key)
    return out


@dataclass
class Decision:
    action: str                    # "none" | "wait" | "dispatch"
    job_input: str | None = None
    due: list[str] = field(default_factory=list)
    reason: str = ""


def due_jobs(now: datetime, runs: list[dict], jobs_by_run: dict) -> dict[str, str]:
    """{job: why} for every scheduled job that is missed and may be dispatched;
    `why` is 'missed' - jobs that are covered, blocked or due soon are left out."""
    out = {}
    for job in sorted(ALL_JOBS):
        since = last_expected(job, now)
        if next_expected(job, now) - now < SOON:
            continue
        covered = blocked = False
        for run in runs:
            if _ts(run["created_at"]) < since - SKEW:
                continue
            tried = attempted(jobs_by_run.get(run["id"]))
            if tried is not None and job in tried:
                covered = True
                break
            by_bot = (run.get("event") == "workflow_dispatch"
                      and (run.get("triggering_actor") or {}).get("login") == BOT_LOGIN
                      and _ts(run["created_at"]) >= since)
            if by_bot and tried is None:
                blocked = True
        if not covered and not blocked:
            out[job] = "missed"
    return out


def decide(now: datetime, runs: list[dict], jobs_by_run: dict) -> Decision:
    """Pure. `runs`: workflow runs (id, created_at, status, event,
    triggering_actor). `jobs_by_run`: run id -> that run's jobs (name,
    conclusion)."""
    active = [r["id"] for r in runs if r.get("status") in ACTIVE_STATUSES]
    due = sorted(due_jobs(now, runs, jobs_by_run))
    if active:
        return Decision("wait", due=due, reason=f"{len(active)} run(s) queued or in progress: {','.join(map(str, active))}")
    if not due:
        return Decision("none", reason="every scheduled job ran (or was dispatched) since its last slot")
    if ALL_JOBS - set(due) <= SAFE_EXTRA_FOR_ALL:
        return Decision("dispatch", "all", due, "every job of job=all is due (deeds may repeat)")
    first = next(j for j in DISPATCH_PRIORITY if j in due)
    return Decision("dispatch", first, due, "one job per tick; no single input reproduces the missed set")


# ------------------------------------------------------------------- I/O

class GitHub:
    def __init__(self, repo: str, token: str, api: str = "https://api.github.com"):
        self.repo, self.token, self.api = repo, token, api.rstrip("/")

    def _req(self, method: str, path: str, body: dict | None = None):
        req = urllib.request.Request(
            f"{self.api}/repos/{self.repo}/{path}", method=method,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"Authorization": f"Bearer {self.token}", "Accept": "application/vnd.github+json",
                     "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "taxdeed-scraper-watchdog"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
        return json.loads(raw) if raw else None

    def runs_since(self, since: datetime) -> list[dict]:
        out, page = [], 1
        created = since.strftime("%Y-%m-%dT%H:%M:%SZ")
        while page <= 5:
            data = self._req("GET", f"actions/workflows/{WORKFLOW_FILE}/runs?per_page=100&page={page}"
                                    f"&created=%3E%3D{created}")
            batch = data.get("workflow_runs") or []
            out.extend(batch)
            if len(batch) < 100:
                break
            page += 1
        return out

    def jobs(self, run_id) -> list[dict]:
        data = self._req("GET", f"actions/runs/{run_id}/jobs?per_page=100")
        return data.get("jobs") or []

    def dispatch(self, ref: str, job_input: str) -> None:
        self._req("POST", f"actions/workflows/{WORKFLOW_FILE}/dispatches", {"ref": ref, "inputs": {"job": job_input}})


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dry-run", action="store_true", help="decide and print, never dispatch")
    ap.add_argument("--ref", default=os.environ.get("WATCHDOG_REF") or "main")
    a = ap.parse_args(argv)
    repo, token = os.environ.get("GITHUB_REPOSITORY", ""), os.environ.get("GITHUB_TOKEN", "")
    if not repo or not token:
        print("::error title=watchdog::GITHUB_REPOSITORY / GITHUB_TOKEN not set - nothing checked")
        return 2
    gh = GitHub(repo, token, os.environ.get("GITHUB_API_URL", "https://api.github.com"))
    now = datetime.now(timezone.utc)
    oldest = min(last_expected(j, now) for j in ALL_JOBS) - SKEW
    try:
        runs = gh.runs_since(oldest)
        jobs_by_run = {r["id"]: gh.jobs(r["id"]) for r in runs if r.get("status") not in ACTIVE_STATUSES}
    except (urllib.error.URLError, ValueError) as exc:
        print(f"::warning title=watchdog::could not read the workflow's runs ({type(exc).__name__}) - nothing dispatched")
        return 0
    d = decide(now, runs, jobs_by_run)
    print(f"watchdog: {len(runs)} run(s) since {oldest:%Y-%m-%d %H:%M} UTC; due: {','.join(d.due) or 'none'}; "
          f"action: {d.action}{' job=' + d.job_input if d.job_input else ''} ({d.reason})")
    if d.action != "dispatch" or a.dry_run:
        return 0
    try:
        gh.dispatch(a.ref, d.job_input)
    except urllib.error.HTTPError as exc:
        print(f"::error title=watchdog::dispatch of job={d.job_input} refused: HTTP {exc.code}")
        return 1
    print(f"::notice title=watchdog::dispatched {WORKFLOW_FILE} job={d.job_input} on {a.ref} for missed: {','.join(d.due)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
