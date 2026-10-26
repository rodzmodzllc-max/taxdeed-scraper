#!/usr/bin/env python3
"""Move a Florida deed-auction property out of `active` once the auction
source itself published its result (2026-10-26).

scripts/auction_outcomes.py records a source-published result (a wording row
of data/auction_outcome_wordings.csv: Auction Sold, Redeemed, Redeemed After
Sale, Canceled per County, Canceled per Bankruptcy) on the auction EVENT
(auction_events.outcome / lifecycle / outcome_raw) and never touches
`properties`. Until now nothing carried that result to the property row: a
row redeemed or cancelled before its sale stayed `active` until its sale day
passed, and a verified sale ended as a plain `closed` (production 2026-10-26:
173 rows with a verified "Auction Sold" stored as 'closed'). This step, run
right after the outcomes step in the deeds job, applies one rule:

    verified event, same sale day as the row     -> properties.status
      outcome 'sold'                               'sold'
      anything else verified (redeemed, cancelled,  'closed'
      withdrawn, struck off, no sale)

The statuses are the existing pipeline vocabulary (the gone set of the
track_gone_since trigger: dropped / sold / notfound / closed); gone_since is
set by that trigger. Transitions are only active -> sold / closed and
closed -> sold. Never:
  * a row whose current sale_date differs from the event's sale day (a
    re-listed row's earlier sale says nothing about the current one -
    production: 3 active rows re-listed after an earlier "Auction Sold");
  * a row whose case number this run's Waiting harvest read (the county
    still lists it, so the sync's own `active` stands);
  * a row of another state or ledger (state=eq.FL, source=eq.auction in
    every read and write), and never 'dropped' / 'notfound' / 'sold' rows;
  * an event without the source's own wording (auction_outcomes.is_verified);
  * a result field, an amount, a purchaser: only `status` is written.

Output: counts only, never a case number or an address. Plan-only unless
--apply (the workflow passes it); the recorded FL auction `store`
permission is required before any write.

    python3 scripts/auction_outcome_status.py --harvest out/harvest_all.json [--apply]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(1, str(REPO))

import auction_outcomes as AO  # noqa: E402

GONE = frozenset({"dropped", "sold", "notfound", "closed"})
EVENT_SELECT = "id,property_id,county,case_no,scheduled_sale_date,lifecycle,outcome,outcome_raw,outcome_observed_at"
PROPERTY_SELECT = "id,county,case_no,status,sale_date"
BATCH = 100


def target_status(event: dict) -> str | None:
    """The property status a verified event implies, or None."""
    if not AO.is_verified(event):
        return None
    # auction_events.outcome (migration 014) - read, never written here.
    return "sold" if event.get(AO.EVENT_OUTCOME_COLUMN) == "sold" else "closed"


def plan(events: list[dict], properties: list[dict], *, harvested: dict[str, set[str]] | None = None
         ) -> tuple[list[tuple[str, str, str]], dict]:
    """[(property id, from status, to status)] and counts. Pure."""
    harvested = harvested or {}
    by_property: dict[str, list[dict]] = {}
    for e in events:
        if e.get("lifecycle") == "superseded" or not e.get("property_id"):
            continue
        by_property.setdefault(str(e["property_id"]), []).append(e)
    counts: Counter = Counter()
    changes: list[tuple[str, str, str]] = []
    for p in properties:
        evs = by_property.get(str(p.get("id")))
        if not evs:
            continue
        sale = str(p.get("sale_date") or "")[:10]
        same_day = [e for e in evs if str(e.get("scheduled_sale_date") or "")[:10] == sale and sale]
        targets = {t for t in (target_status(e) for e in same_day) if t}
        if not targets:
            if any(target_status(e) for e in evs):
                counts["result_for_another_sale_day"] += 1
            continue
        if len(targets) > 1:
            counts["conflicting_results"] += 1
            continue
        to = targets.pop()
        current = str(p.get("status") or "").lower()
        county = str(p.get("county") or "")
        if AO.norm_id(p.get("case_no")) in harvested.get(county, set()):
            counts["still_on_waiting_list"] += 1
            continue
        if current == to:
            counts["already_" + to] += 1
            continue
        if current == "active" or (current == "closed" and to == "sold"):
            changes.append((str(p["id"]), current, to))
            counts[f"{current}_to_{to}"] += 1
            continue
        counts["left_alone_" + (current or "blank")] += 1
    return changes, dict(counts)


def _headers(key: str) -> dict:
    return {"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json",
            "User-Agent": "taxdeed-scraper/1.0 (+https://github.com/rodzmodzllc-max/taxdeed-scraper; GitHub Actions)"}


def fetch(base: str, key: str) -> tuple[list[dict], list[dict]]:
    import rest_pages as RP  # noqa: PLC0415
    h = _headers(key)
    events = RP.read_all(base, "auction_events", h, {"select": EVENT_SELECT, "state": "eq.FL", "source": "eq.auction",
                                                    "outcome_raw": "not.is.null"})
    props = RP.read_all(base, "properties", h, {"select": PROPERTY_SELECT, "state": "eq.FL", "source": "eq.auction",
                                               "status": "in.(active,closed)"})
    return events, props


def write(base: str, key: str, changes: list[tuple[str, str, str]]) -> int:
    groups: dict[tuple[str, str], list[str]] = {}
    for pid, frm, to in changes:
        groups.setdefault((frm, to), []).append(pid)
    done = 0
    for (frm, to), ids in sorted(groups.items()):
        for i in range(0, len(ids), BATCH):
            chunk = ids[i:i + BATCH]
            url = (f"{base.rstrip('/')}/rest/v1/properties?state=eq.FL&source=eq.auction&status=eq.{frm}"
                   f"&id=in.({','.join(chunk)})")
            req = urllib.request.Request(url, data=json.dumps({"status": to}).encode(), method="PATCH",
                                         headers={**_headers(key), "Prefer": "return=minimal"})
            with urllib.request.urlopen(req, timeout=120):
                pass
            done += len(chunk)
    return done


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--harvest", default=str(AO.HARVEST_PATH))
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args(argv)
    base, key = os.environ.get("SUPABASE_URL", ""), os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not base or not key:
        print("auction outcome status: SUPABASE_URL / SUPABASE_SERVICE_KEY not set - skipped")
        return 0
    events, props = fetch(base, key)
    changes, counts = plan(events, props, harvested=AO.harvested_cases(a.harvest))
    print(f"auction outcome status (FL): verified events {sum(1 for e in events if AO.is_verified(e))}; "
          f"{'apply' if a.apply else 'plan-only'}; would move {len(changes)} row(s)")
    print("  counts: " + json.dumps(counts, sort_keys=True))
    if a.apply and changes:
        import stamp_seen  # noqa: PLC0415 - the recorded FL auction `store` permission
        if not stamp_seen.store_permitted("FL", "auction"):
            return stamp_seen.PERMISSION_DENIED_EXIT
        print(f"  moved {write(base, key, changes)} row(s) (status only; the result itself stays on the auction event)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
