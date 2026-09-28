#!/usr/bin/env python3
"""Phase B seed (conservative): create an event row ONLY for a current
auction property whose listing is evidenced as scheduled right now. Every
other property is skipped with a stated reason. Nothing is reconstructed.

DRY RUN BY DEFAULT. Nothing is written unless `--apply` is passed, and this
script is wired into no workflow; it is run by hand, once, after review of
its dry-run output. It never touches `properties`.

WHY IT IS CONSERVATIVE
A property row is a snapshot, not a sighting history. `status = 'active'`
only means the close-out never closed the row; `status = 'closed'` only
means the listing was absent from a COMPLETE harvest after its date. Neither
says the listing was on the feed through its sale day, so neither is
evidence for a historical `completed` event, and an active row absent from
the latest harvest is not evidence of a `scheduled` one. The seed therefore
only seeds rows with present-tense source evidence:

  Florida (RealAuction, Okaloosa)
      the property's (county, case_no, sale_date) is in the supplied FL
      harvest file (out/harvest_all.json) AND that county is COMPLETE in the
      status file (out/harvest_all_status.json) AND status is 'active' AND
      the date is today or later                           -> scheduled
  Texas LGBS
      the property's own `tx_sale_status` is one of the two scheduled LGBS
      statuses AND status is 'active' AND the date is today or later
                                                           -> scheduled
  Texas RealAuction
      the property is in the supplied TX harvest file (out/harvest_texas.json)
      AND status 'active' AND the date is today or later   -> scheduled

Skipped, never seeded (reason is counted in the summary):
  closed_status_not_completion_evidence  closed, date passed
  contradictory_closed_future            closed, date today or later
  status_not_active                      dropped / any other status
  date_passed_presence_not_established   active, date passed
  no_harvest_evidence_supplied           FL / TX RealAuction without a harvest file
  county_harvest_not_complete            FL county not COMPLETE in the status file
  absent_from_current_harvest            not in the harvest file (or under another date)
  lgbs_status_not_scheduled              LGBS tx_sale_status missing or not scheduled
  unsupported_source                     any other harvester

Each seeded event gets lifecycle 'scheduled', outcome 'unknown', and one
observation with feed = 'seed' whose raw_status is the evidence's own status
text ('Auctions Waiting' from the harvest, or the LGBS status verbatim).
Idempotent: an existing (property_id, scheduled_sale_date) is skipped - no
second event, no second observation. Because the live writer records the
same harvest-evidenced rows on its first run, the seed adds little beyond
LGBS rows evidenced by `tx_sale_status`; it is optional, not a precondition
for activation.
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
    FL_HARVEST_JSON, FL_STATUS_JSON, LGBS_SCHEDULED_STATUSES, TX_HARVEST_JSON, DryRunStore, PostgrestStore,
    Store, WriterError, _check_event_payload, _num, _observation, complete_counties_from_fl_status,
    sightings_from_fl_harvest, sightings_from_tx_harvest,
)

SEED_FEED = "seed"


class Evidence:
    """Present-tense evidence the seed may rely on. `fl`/`tx` map
    (county, case_no) -> {iso_date: raw_status}; None = no file supplied."""

    def __init__(self, fl: dict | None = None, fl_complete: set[str] | None = None, tx: dict | None = None) -> None:
        self.fl = fl
        self.fl_complete = fl_complete or set()
        self.tx = tx

    @staticmethod
    def index(sightings) -> dict:
        out: dict = {}
        for s in sightings:
            out.setdefault((s.county, s.case_no), {})[s.scheduled_sale_date] = s.raw_status
        return out


def seed_decision(p: dict, today: date, ev: Evidence) -> tuple[str | None, str]:
    """-> (raw_status for the seeded observation, '') when the row is seeded,
    or (None, skip_reason) when it is not. Seeded rows are always 'scheduled'."""
    st = (p.get("status") or "").strip().lower()
    sale = date.fromisoformat(str(p["sale_date"]))
    if st == "closed":
        return None, "contradictory_closed_future" if sale >= today else "closed_status_not_completion_evidence"
    if st != "active":
        return None, "status_not_active"
    if sale < today:
        return None, "date_passed_presence_not_established"
    key, iso = (p["county"], p["case_no"]), str(p["sale_date"])
    if p["state"] == "FL":
        if ev.fl is None:
            return None, "no_harvest_evidence_supplied"
        if p["county"] not in ev.fl_complete:
            return None, "county_harvest_not_complete"
        dates = ev.fl.get(key, {})
        return (dates[iso], "") if iso in dates else (None, "absent_from_current_harvest")
    hs = p.get("harvester_source")
    if hs == "tx_lgbs":
        status = (p.get("tx_sale_status") or "").strip()
        return (status, "") if status in LGBS_SCHEDULED_STATUSES else (None, "lgbs_status_not_scheduled")
    if hs == "tx_realauction":
        if ev.tx is None:
            return None, "no_harvest_evidence_supplied"
        dates = ev.tx.get(key, {})
        return (dates[iso], "") if iso in dates else (None, "absent_from_current_harvest")
    return None, "unsupported_source"


def seed(store: Store, *, states: tuple[str, ...] = ("FL", "TX"), source: str = "auction",
         observed_at: str, run_id: str | None, today: date, evidence: Evidence | None = None) -> dict:
    evidence = evidence or Evidence()
    summary: dict = {"candidates": 0, "already_present": 0, "created": 0, "observations": 0,
                     "by_state": {}, "skipped": {}}
    for state in states:
        props = store.fetch_properties(state, source)
        existing = {(e["property_id"], str(e["scheduled_sale_date"])) for e in store.fetch_events(state, source)}
        rows: list[dict] = []
        raw: list[str | None] = []
        for p in props:
            if not p.get("sale_date"):
                continue
            summary["candidates"] += 1
            if (p["id"], str(p["sale_date"])) in existing:
                summary["already_present"] += 1
                continue
            raw_status, reason = seed_decision(p, today, evidence)
            if reason:
                k = f"{state}/{reason}"
                summary["skipped"][k] = summary["skipped"].get(k, 0) + 1
                continue
            url = (p.get("url_auction") or "").strip() or None
            row = {
                "property_id": p["id"],
                "state": state, "source": source,
                "harvester_source": p.get("harvester_source"),
                "county": p["county"], "case_no": p["case_no"],
                "ledger_type": p.get("ledger_type"),
                "scheduled_sale_date": str(p["sale_date"]),
                "event_url": url, "event_url_kind": p.get("url_auction_kind") if url else None,
                "opening_bid": _num(p.get("bid")),
                "lifecycle": "scheduled",
                "outcome": "unknown",
                "first_seen_at": observed_at, "last_seen_at": observed_at,
            }
            _check_event_payload(row)
            rows.append(row)
            raw.append(raw_status)
        summary["by_state"][state] = len(rows)
        # Same write order as the live writer: insert a batch, observe it,
        # remove the batch again if its observations cannot be written.
        for i in range(0, len(rows), 500):
            batch, batch_raw = rows[i:i + 500], raw[i:i + 500]
            inserted = store.insert_events(batch)
            if len(inserted) != len(batch):
                raise WriterError(f"inserted {len(inserted)} events for {len(batch)} seed rows")
            observations = [
                _observation(ins["id"], observed_at=observed_at, run_id=run_id, feed=SEED_FEED,
                             raw_status=r, lifecycle="scheduled", opening_bid=row["opening_bid"],
                             evidence_url=row["event_url"])
                for ins, row, r in zip(inserted, batch, batch_raw)
            ]
            try:
                store.insert_observations(observations)
            except Exception as exc:
                store.delete_unobserved_events([ins["id"] for ins in inserted], observed_at)
                raise WriterError(f"seed observations failed; {len(inserted)} new events removed again: {exc}") from exc
            summary["created"] += len(batch)
            summary["observations"] += len(observations)
    return summary


def load_evidence(fl_harvest: Path | None, fl_status: Path | None, tx_harvest: Path | None) -> Evidence:
    def read(path: Path | None):
        return json.loads(path.read_text(encoding="utf-8")) if path and path.exists() else None

    fl_rows, fl_st, tx_rows = read(fl_harvest), read(fl_status), read(tx_harvest)
    return Evidence(
        fl=Evidence.index(sightings_from_fl_harvest(fl_rows)) if fl_rows is not None else None,
        fl_complete=complete_counties_from_fl_status(fl_st) if fl_st is not None else set(),
        tx=Evidence.index(s for s in sightings_from_tx_harvest(tx_rows) if s.raw_status == "Auctions Waiting")
        if tx_rows is not None else None,
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Seed auction_events from evidenced current listings (dry run unless --apply).")
    ap.add_argument("--apply", action="store_true", help="actually write; without it the plan is printed and nothing is written")
    ap.add_argument("--state", choices=["FL", "TX"], action="append", help="restrict to a state (repeatable); default both")
    ap.add_argument("--fl-harvest-json", type=Path, default=FL_HARVEST_JSON)
    ap.add_argument("--fl-status-json", type=Path, default=FL_STATUS_JSON)
    ap.add_argument("--tx-harvest-json", type=Path, default=TX_HARVEST_JSON)
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
                   today=now.date(), evidence=load_evidence(args.fl_harvest_json, args.fl_status_json, args.tx_harvest_json))
    print(f"seed_auction_events ({'APPLIED' if args.apply else 'DRY RUN - nothing written'}): {json.dumps(summary, sort_keys=True)}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except WriterError as exc:
        print(f"seed_auction_events: ERROR - {exc}", file=sys.stderr)
        sys.exit(1)
