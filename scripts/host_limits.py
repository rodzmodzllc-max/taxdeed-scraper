"""Request limits an office set for automated reading of its website
(data/office_replies.csv `collection_limits`; 2026-11-05: Citrus County Clerk,
"no more than 2,000 requests per day, with at least 60 seconds between
requests").

HostLimiter.before_request(url) is called before every request a harvester
sends. For a host with recorded limits it

  * waits until at least `min_interval_s` seconds have passed since the last
    request to that host (in this process, and in any earlier process of the
    same day whose count file it reads);
  * refuses (DailyLimitReached) once `max_per_day` requests were sent to that
    host on the current UTC day.

The per-day count lives in a small JSON file (HOST_LIMITS_STATE, default
out/.harvest_cache/host_request_counts.json) so two runs on one day share the
budget. Hosts without recorded limits pass straight through.
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from harvesters.governance.office_replies import collection_limits_for  # noqa: E402

DEFAULT_STATE = REPO / "out" / ".harvest_cache" / "host_request_counts.json"


class DailyLimitReached(RuntimeError):
    """The office's daily request limit for this host is used up."""


class HostLimiter:
    def __init__(self, state_path: Path | str | None = None, *, clock=time.time, sleep=time.sleep,
                 limits_for=collection_limits_for):
        self.state_path = Path(state_path or os.environ.get("HOST_LIMITS_STATE") or DEFAULT_STATE)
        self.clock = clock
        self.sleep = sleep
        self.limits_for = limits_for

    def _day(self, now: float) -> str:
        return datetime.fromtimestamp(now, tz=timezone.utc).strftime("%Y-%m-%d")

    def _read(self) -> dict:
        try:
            return json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _write(self, state: dict) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(state, sort_keys=True), encoding="utf-8")

    def before_request(self, url: str) -> None:
        host = (urlsplit(url).hostname or "").lower()
        limits = self.limits_for(host)
        if not limits:
            return
        max_per_day, min_interval = limits
        state = self._read()
        entry = state.get(host) or {}
        now = self.clock()
        if entry.get("day") != self._day(now):
            entry = {"day": self._day(now), "count": 0, "last": entry.get("last")}
        if entry["count"] >= max_per_day:
            raise DailyLimitReached(f"{host}: {max_per_day} requests already sent today (office limit)")
        last = entry.get("last")
        if last is not None and now - last < min_interval:
            self.sleep(min_interval - (now - last))
            now = self.clock()
            if entry["day"] != self._day(now):
                entry = {"day": self._day(now), "count": 0, "last": last}
        entry["count"] += 1
        entry["last"] = now
        state[host] = entry
        self._write(state)
