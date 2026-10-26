#!/usr/bin/env python3
"""Texas close-out and reactivation (2026-10-26).

The Texas sync (scripts/sync-texas-to-supabase.py) is upsert-only and never
sends `status`, so a row LGBS or a Texas RealAuction county stopped listing
stayed 'active' forever (165 such rows were closed by hand on 2026-10-26),
and a row closed earlier stayed closed when the source listed it again.
This step runs after the sync and the last_seen_at stamp:

  close       a stored ACTIVE row of tx_lgbs / tx_realauction whose
              (source, county) read this run was COMPLETE or EMPTY
              (harvesters/ledgers/health.py, via the harvester's
              out/harvest_texas_status.json `counties` entries) and whose
              (ledger, county, account) the read no longer lists ->
              status 'closed', delisted_at = now. Never on an INCOMPLETE /
              FAILED / SOURCE_UNAVAILABLE / missing read; never a row of a
              ledger the reading source does not feed; never 'sold' or any
              other result - absence only means the list dropped it. The
              decision is scripts/sync_state_inventory.py's plan_close(),
              the same rule every other state's close-out uses.
  reactivate  a stored row this run's harvest lists again whose status is
              'closed' (or the older 'dropped' / 'notfound') -> status
              'active', delisted_at cleared. A row with a recorded result
              ('sold') is never reopened by a listing.

Guards: every source needs a recorded `store` permission
(data/source_permissions.csv); a source whose plan would close more than
MAX_CLOSE_SHARE of its active rows in one run is refused (a read that lost
half a feed is not trusted, whatever its status says) unless
--allow-large-close. Counts only are printed (public logs).

    python3 scripts/texas_closeout.py                 # live (SUPABASE_URL + SUPABASE_SERVICE_KEY)
    python3 scripts/texas_closeout.py --dry-run       # plan only, prints counts, writes nothing
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(HERE))
from harvesters.ledgers import health as LH  # noqa: E402
import field_provenance as FP  # noqa: E402
import rest_pages as RP  # noqa: E402
import sync_state_inventory as SI  # noqa: E402

STATE = "TX"
# + the vendors the owner unblocked on 2026-10-26 (harvesters/texas_vendors.py writes the same
# per-(source, county) entries; a county whose index page was not read is never COMPLETE).
SOURCE_IDS = frozenset({"tx_lgbs", "tx_realauction", "tx_pbfcm", "tx_mvba", "tx_govease"})
# The dataset their permission records name (scripts/stamp_seen.py STORE_SOURCES).
DATASET = "tax_sale_listing"
REACTIVATABLE = frozenset({"closed", "dropped", "notfound"})
MAX_CLOSE_SHARE = 0.5
CHUNK = 100
USER_AGENT = "taxdeed-scraper texas-closeout (+https://github.com/rodzmodzllc-max/taxdeed-scraper)"
PERMISSION_DENIED_EXIT = 3


def harvest_identities(harvest: list[dict]) -> set[tuple]:
    """(state, ledger source, county, account) of every Texas row this run's
    harvest lists - the account is what the sync stores as case_no. A row the
    sync later refused is still LISTED by the source: it is never closed."""
    out = set()
    for p in harvest:
        if not isinstance(p, dict) or p.get("harvester_source") not in SOURCE_IDS:
            continue
        source, county, account = p.get("source"), p.get("county"), p.get("account_number")
        if source and county and account:
            out.add((STATE, source, county, account))
    return out


def plan(harvest: list[dict], stored: list[dict], units: dict, permitted: set[str],
         *, max_share: float | None = MAX_CLOSE_SHARE, now: datetime | None = None) -> dict:
    """The whole decision, as data. Pure."""
    listed = harvest_identities(harvest)
    as_rows = [{"state": s, "source": src, "county": c, "case_no": a} for s, src, c, a in listed]
    sids = set(SOURCE_IDS) & set(permitted)
    active = [r for r in stored if r.get("status") == "active" and r.get("harvester_source") in sids]
    closes = SI.plan_close(STATE, as_rows, active, units, sids)
    by_id = {r["id"]: r for r in active}

    refused: dict[str, int] = {}
    if max_share is not None:
        # A row whose sale day has passed leaving the waiting list is the
        # expected case (the whole list goes after each sale day); only the
        # rest count toward the "lost half the feed" guard.
        today = (now or datetime.now(timezone.utc)).date().isoformat()
        per_source = Counter(by_id[c["id"]].get("harvester_source") for c in closes
                             if not (by_id[c["id"]].get("sale_date") and str(by_id[c["id"]]["sale_date"])[:10] < today))
        totals = Counter(r.get("harvester_source") for r in active)
        for sid, n in per_source.items():
            if totals[sid] and n / totals[sid] > max_share:
                refused[sid] = n
        closes = [c for c in closes if by_id[c["id"]].get("harvester_source") not in refused]

    reactivate = [r["id"] for r in stored
                  if str(r.get("status") or "").lower() in REACTIVATABLE
                  and r.get("harvester_source") in sids
                  and (STATE, r.get("source"), r.get("county"), r.get("case_no")) in listed]

    # What was kept and why (counts only).
    kept = Counter()
    closing = {c["id"] for c in closes}
    for r in active:
        if r["id"] in closing:
            continue
        if (STATE, r.get("source"), r.get("county"), r.get("case_no")) in listed:
            kept["listed"] += 1
            continue
        status = LH.unit_status(units, r.get("harvester_source"), r.get("county"))
        kept["absent, refused (large close)" if r.get("harvester_source") in refused
             else f"absent, read {status or 'NOT_RUN'}"] += 1
    return {"close": closes, "reactivate": sorted(reactivate), "refused_sources": refused,
            "kept": dict(sorted(kept.items())),
            "close_by_unit": dict(sorted(Counter(f"{by_id[c['id']].get('harvester_source')}:{by_id[c['id']].get('source')}"
                                                  for c in closes).items()))}


def units_from(path: Path) -> dict:
    """{(source_id, county): reader status} from the harvester's status file
    (its `counties` entries). A missing / unreadable file is no read at all."""
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return {}
    entries = data.get("counties") if isinstance(data, dict) else None
    # Only entries naming a source: a bare-county entry would stand in for
    # every source of that county (health.ledger_units' fallback).
    return LH.ledger_units([e for e in entries or [] if isinstance(e, dict) and e.get("source_id") in SOURCE_IDS])


def store_permitted() -> set[str]:
    import permission_gate as PG  # noqa: PLC0415
    return {s for s in SOURCE_IDS if PG.allowed(s, ("store",), state=STATE, dataset=DATASET, label="texas_closeout")}


def _headers(key: str) -> dict:
    return {"apikey": key, "Authorization": f"Bearer {key}", "User-Agent": USER_AGENT}


def stored_rows(base: str, key: str) -> list[dict]:
    return RP.read_all(base, "properties", _headers(key),
                       {"select": "id,state,source,county,case_no,status,harvester_source,ledger_type,sale_date",
                        "state": f"eq.{STATE}", "harvester_source": f"in.({','.join(sorted(SOURCE_IDS))})"})


def patch_ids(base: str, key: str, ids: list, body: dict, *, send=None) -> int:
    """PATCH `body` onto these ids, CHUNK at a time, filtered by state too."""
    send = send or _send
    done = 0
    for i in range(0, len(ids), CHUNK):
        part = ids[i:i + CHUNK]
        send(f"{base.rstrip('/')}/rest/v1/properties?state=eq.{STATE}&id=in.({','.join(str(x) for x in part)})", body, key)
        done += len(part)
    return done


def _send(url: str, body: dict, key: str) -> None:
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="PATCH",
                                 headers={**_headers(key), "Content-Type": "application/json", "Prefer": "return=minimal"})
    with urllib.request.urlopen(req, timeout=60):
        pass


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--harvest", default=str(REPO / "out" / "harvest_texas.json"))
    ap.add_argument("--status", default=str(REPO / "out" / "harvest_texas_status.json"))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--allow-large-close", action="store_true",
                    help=f"close even when a source would lose more than {MAX_CLOSE_SHARE:.0%} of its active rows")
    args = ap.parse_args(argv)

    harvest_path = Path(args.harvest)
    harvest = json.loads(harvest_path.read_text(encoding="utf-8")) if harvest_path.exists() else []
    units = units_from(Path(args.status))
    reads = Counter(f"{k[0]}:{st}" for k, st in units.items() if isinstance(k, tuple))
    print(f"TX close-out: {len(harvest_identities(harvest))} listed identities; county reads {dict(sorted(reads.items()))}")
    if not units:
        print("TX close-out: no per-county read status - nothing is closed (rows listed again are still reactivated)")

    permitted = store_permitted()
    if not permitted:
        print("::error title=texas_closeout::no Texas source has a recorded store permission - nothing written")
        return PERMISSION_DENIED_EXIT

    base, key = os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_SERVICE_KEY")
    if not base or not key:
        print("SUPABASE_URL / SUPABASE_SERVICE_KEY not set", file=sys.stderr)
        return 1
    stored = stored_rows(base, key)
    p = plan(harvest, stored, units, permitted, max_share=None if args.allow_large_close else MAX_CLOSE_SHARE)
    print(f"TX close-out plan: close {len(p['close'])} {p['close_by_unit']}, reactivate {len(p['reactivate'])}, "
          f"kept active {p['kept']}")
    for sid, n in p["refused_sources"].items():
        print(f"::warning title=texas_closeout::{sid}: {n} closes refused - more than {MAX_CLOSE_SHARE:.0%} of its active "
              "rows in one run; nothing of this source was closed (rerun with --allow-large-close after checking the read)")
    if args.dry_run:
        print("TX close-out: dry run - nothing written")
        return 0
    now = FP.now_iso()
    closed = patch_ids(base, key, [c["id"] for c in p["close"]], {"status": "closed", "delisted_at": now})
    reopened = patch_ids(base, key, p["reactivate"], {"status": "active", "delisted_at": None})
    print(f"TX close-out: closed {closed}, reactivated {reopened}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
