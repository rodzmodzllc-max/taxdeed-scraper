#!/usr/bin/env python3
"""Phase B seed: give every CURRENT auction property with a sale date its
event row, so the event history starts from the state we actually know at
implementation time instead of from the next harvest onward.

    properties (source = 'auction', sale_date is not null)  -> auction_events
                                                            -> one observation, feed = 'seed'

DRY RUN BY DEFAULT. Nothing is written unless `--apply` is passed, and this
script is wired into no workflow; it is run by hand, once, after review of
its dry-run output. It never touches `properties`.

WHAT THE SEED KNOWS AND WHAT IT DOES NOT
- It knows the property's current `sale_date`, `bid`, `status` and auction
  link. It does not know when the listing was first seen (the property's
  `updated_at` is a sync timestamp, not a first sighting), so
  `first_seen_at`/`last_seen_at` are the seed time - honest, not fabricated.
- The observation's `feed` is 'seed' and its `raw_status` is the property's
  own `status` word verbatim, so a seeded observation can never be mistaken
  for a harvest sighting.
- lifecycle is EXPLICIT per row, from what `status` and the date support:
      status 'active', date today or later   -> scheduled
      status 'active', date passed           -> pending_result
                    (still on the feed after its date, or a county the
                     close-out never reconciles - the result is not known)
      status 'closed', date passed           -> completed
                    (left the county feed after the sale date - the same
                     evidence the close-out used; outcome stays unknown)
      status 'closed', date today or later   -> scheduled
                    (the latest harvest re-listed it under a future date;
                     the stale 'closed' is a known property-status defect)
      anything else ('dropped', ...)         -> unknown
- outcome is 'unknown' for every seeded event. No outcome is inferred.
- Idempotent: an existing (property_id, scheduled_sale_date) is skipped
  entirely - no second event, no second observation.

Population is recalculated from the database at run time; the dry run prints
it by state, source and lifecycle before anything is written.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from auction_events_writer import (  # noqa: E402
    DryRunStore, PostgrestStore, Store, WriterError, _check_event_payload, _num, _observation,
)

SEED_FEED = "seed"


def seed_lifecycle(status: str | None, sale_date: date, today: date) -> str:
    st = (status or "").strip().lower()
    if st == "active":
        return "scheduled" if sale_date >= today else "pending_result"
    if st == "closed":
        return "completed" if sale_date < today else "scheduled"
    return "unknown"


def seed(store: Store, *, states: tuple[str, ...] = ("FL", "TX"), source: str = "auction",
         observed_at: str, run_id: str | None, today: date) -> dict:
    summary: dict = {"eligible": 0, "already_present": 0, "created": 0, "observations": 0, "by_lifecycle": {}}
    for state in states:
        props = store.fetch_properties(state, source)
        existing = {(e["property_id"], str(e["scheduled_sale_date"])) for e in store.fetch_events(state, source)}
        rows: list[dict] = []
        obs_seed: list[tuple[dict, dict]] = []
        for p in props:
            sale = p.get("sale_date")
            if not sale:
                continue
            summary["eligible"] += 1
            key = (p["id"], str(sale))
            if key in existing:
                summary["already_present"] += 1
                continue
            lifecycle = seed_lifecycle(p.get("status"), date.fromisoformat(str(sale)), today)
            url = (p.get("url_auction") or "").strip() or None
            kind = p.get("url_auction_kind") if url else None
            row = {
                "property_id": p["id"],
                "state": state, "source": source,
                "harvester_source": p.get("harvester_source"),
                "county": p["county"], "case_no": p["case_no"],
                "ledger_type": p.get("ledger_type"),
                "scheduled_sale_date": str(sale),
                "event_url": url, "event_url_kind": kind,
                "opening_bid": _num(p.get("bid")),
                "lifecycle": lifecycle,
                "outcome": "unknown",
                "first_seen_at": observed_at, "last_seen_at": observed_at,
            }
            _check_event_payload(row)
            rows.append(row)
            obs_seed.append((row, p))
            k = f"{state}/{lifecycle}"
            summary["by_lifecycle"][k] = summary["by_lifecycle"].get(k, 0) + 1
        if rows:
            inserted = store.insert_events(rows)
            if len(inserted) != len(rows):
                raise WriterError(f"inserted {len(inserted)} events for {len(rows)} seed rows")
            observations = [
                _observation(ins["id"], observed_at=observed_at, run_id=run_id, feed=SEED_FEED,
                             raw_status=(p.get("status") or None), lifecycle=row["lifecycle"],
                             opening_bid=row["opening_bid"], evidence_url=row["event_url"])
                for ins, (row, p) in zip(inserted, obs_seed)
            ]
            store.insert_observations(observations)
            summary["created"] += len(rows)
            summary["observations"] += len(observations)
    return summary


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Seed auction_events from current auction properties (dry run unless --apply).")
    ap.add_argument("--apply", action="store_true", help="actually write; without it the plan is printed and nothing is written")
    ap.add_argument("--state", choices=["FL", "TX"], action="append", help="restrict to a state (repeatable); default both")
    args = ap.parse_args(argv)

    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_KEY")  # never logged
    if not url or not key:
        raise WriterError("SUPABASE_URL / SUPABASE_SERVICE_KEY are not set")
    real = PostgrestStore(url, key)
    store: Store = real if args.apply else DryRunStore(real)
    now = datetime.now(timezone.utc)
    summary = seed(store, states=tuple(args.state) if args.state else ("FL", "TX"),
                   observed_at=now.isoformat(), run_id=os.environ.get("GITHUB_RUN_ID") or f"seed-{now:%Y%m%dT%H%M%SZ}",
                   today=now.date())
    print(f"seed_auction_events ({'APPLIED' if args.apply else 'DRY RUN - nothing written'}): {json.dumps(summary, sort_keys=True)}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except WriterError as exc:
        print(f"seed_auction_events: ERROR - {exc}", file=sys.stderr)
        sys.exit(1)
