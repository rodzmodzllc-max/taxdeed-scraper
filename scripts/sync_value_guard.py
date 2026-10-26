#!/usr/bin/env python3
"""Never erase a stored value from the Florida PowerShell syncs (2026-10-26).

THE DEFECT

scripts/sync-harvest-to-supabase.ps1 upserts every harvested RealAuction row
with `resolution=merge-duplicates`. PostgREST's bulk upsert requires every
object of a batch to carry the same keys (PGRST102), so a column the listing
did not publish is SENT as null - and merge-duplicates writes that null over
whatever the row held. The RealAuction feed publishes "Assessed Value" in
some counties only, so every run blanked the `assessed` value the state tax
roll (FDOR NAL, field_provenance source `fdor_nal`) had filled: production,
read-only 2026-10-26, 146 active FL auction rows carried an `fdor_nal`
provenance entry for `assessed` with the value itself blank. The same
erase-on-blank shape exists in sync-certificates-to-supabase.ps1 (owner_name,
parcel, assessed, interest_rate, dates, url_auction; plus the "Account <case>"
address and 0 bid placeholders) and sync-laft-to-supabase.ps1 (parcel,
sale_date, url_auction; plus its address / 0 bid placeholders).

THE RULE (per column of the sync's payload, against the stored row)

  1. A blank or placeholder value never replaces a stored non-blank value: the
     stored value is sent back unchanged (the key must stay in the payload -
     see PGRST102 above - so it carries the value already there).
  2. A stored value whose field_provenance entry names ANOTHER source of equal
     or higher rank than the sync's own source is never replaced
     (scripts/field_provenance.py precedence: a value is replaced only by a
     strictly higher rank; equal rank never overwrites). The sync's own source
     refreshing its own value is allowed - an opening bid or a sale date that
     moves is the list's to change. RealAuction / Bid4Assets / LienHub write as
     `vendor_listing` (rank 1); the county Lands Available lists as
     `county_list` (rank 2).
  3. A stored value with no provenance entry keeps the sync's existing rule
     (the listing's non-blank value is written), exactly as before.
  4. A row not stored yet is sent as harvested.
  5. `url_auction_kind` follows `url_auction`: when the stored URL is kept, its
     stored kind is kept with it.

Pipeline state (`status`) and the identity columns are never guarded.

CLI (called by the three syncs' "Stored-value guard" helper):

    sync_value_guard.py --source auction|certificate|laft --state FL --in rows.json --out guarded.json

Reads the stored rows of the counties in rows.json by keyset pages
(scripts/rest_pages.py), writes the guarded rows (same order, same keys) and
prints counts only - never a value. Exit 2 when the stored rows cannot be
read: the caller writes nothing (fail closed - writing unguarded would erase).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import field_provenance as FP  # noqa: E402

USER_AGENT = "taxdeed-scraper sync-value-guard (+https://github.com/rodzmodzllc-max/taxdeed-scraper)"

# The guarded columns of each sync's payload (everything it sends except the
# identity key and `status`).
GUARDED = {
    "auction": ("parcel", "address", "bid", "assessed", "sale_date", "url_appraiser", "url_auction", "url_auction_kind"),
    "certificate": ("certificate_no", "tax_year", "issued_date", "expiration_date", "bid", "address", "owner_name",
                    "parcel", "assessed", "interest_rate", "url_auction", "url_auction_kind"),
    "laft": ("address", "bid", "parcel", "sale_date", "url_auction", "url_auction_kind"),
}
# The provenance source each sync writes as (scripts/field_provenance.RANK).
SYNC_SOURCE = {"auction": "vendor_listing", "certificate": "vendor_listing", "laft": "county_list"}
# Columns that follow another column rather than being judged on their own.
FOLLOWS = {"url_auction_kind": "url_auction"}

_LAFT_PLACEHOLDER = "Address not published - see county PDF"


def is_placeholder(source: str, column: str, value, row: dict) -> bool:
    """The values a sync invents because the column is NOT NULL and the list
    published nothing (see the syncs' own comments): never a source value."""
    if column == "bid":
        try:
            return float(value) == 0.0
        except (TypeError, ValueError):
            return False
    if column != "address" or not isinstance(value, str):
        return False
    v = value.strip()
    case_no, parcel = str(row.get("case_no") or ""), str(row.get("parcel") or "")
    if source == "certificate":
        return v in {f"Account {case_no}", f"Account {parcel}"}
    if source == "laft":
        return v in {_LAFT_PLACEHOLDER, f"Case {case_no}", f"Parcel {parcel}"}
    return False


def _same(a, b) -> bool:
    if a == b:
        return True
    try:
        return float(a) == float(b)
    except (TypeError, ValueError):
        return False


def protected_by_provenance(stored: dict, column: str, sync_source: str) -> bool:
    entry = FP.load_provenance(stored.get("field_provenance")).get(column)
    if entry is None:
        return False
    if isinstance(entry, dict) and entry.get("source") == sync_source:
        return False
    return FP.rank_of(entry) >= FP.RANK[sync_source]


def guard_row(source: str, row: dict, stored: dict | None, counts: Counter | None = None,
              sync_source: str | None = None) -> dict:
    """`row` with every value the rule forbids replaced by the stored one.
    `sync_source` overrides the provenance source the writer writes as (a
    government list syncing certificate rows writes as `county_list`)."""
    if stored is None:
        return dict(row)
    sync_source = sync_source or SYNC_SOURCE[source]
    out = dict(row)
    kept: set[str] = set()
    for column in GUARDED[source]:
        if column not in row or column in FOLLOWS:
            continue
        sv, nv = stored.get(column), row.get(column)
        if FP.is_blank(sv) or _same(sv, nv):
            continue
        reason = None
        if FP.is_blank(nv):
            reason = "blank"
        elif is_placeholder(source, column, nv, row):
            reason = "placeholder"
        elif protected_by_provenance(stored, column, sync_source):
            reason = "higher_rank"
        if reason:
            out[column] = sv
            kept.add(column)
            if counts is not None:
                counts[f"{column}:{reason}"] += 1
    for follower, leader in FOLLOWS.items():
        if follower in row and leader in kept:
            out[follower] = stored.get(follower)
    return out


def guard_rows(source: str, rows: list[dict], stored_rows: list[dict], counts: Counter | None = None,
               sync_source: str | None = None) -> list[dict]:
    by_key = {(str(s.get("county") or ""), str(s.get("case_no") or "")): s for s in stored_rows}
    return [guard_row(source, r, by_key.get((str(r.get("county") or ""), str(r.get("case_no") or ""))), counts,
                      sync_source=sync_source)
            for r in rows]


def read_stored(base: str, key: str, *, state: str, source: str, counties: list[str]) -> list[dict]:
    import rest_pages as RP
    headers = {"apikey": key, "Authorization": f"Bearer {key}", "User-Agent": USER_AGENT}
    select = ",".join(["id", "county", "case_no", "field_provenance", *GUARDED[source]])
    out: list[dict] = []
    for county in counties:
        out.extend(RP.read_all(base, "properties", headers, {"select": select, "state": f"eq.{state}",
                                                            "source": f"eq.{source}", "county": f"eq.{county}"}))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--source", required=True, choices=sorted(GUARDED))
    ap.add_argument("--state", default="FL")
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    try:
        rows = json.loads(Path(a.inp).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        print("sync_value_guard: rows could not be read - nothing is written", file=sys.stderr)
        return 2
    rows = rows if isinstance(rows, list) else [rows]
    base, key = os.environ.get("SUPABASE_URL", ""), os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not base or not key:
        print("sync_value_guard: SUPABASE_URL / SUPABASE_SERVICE_KEY not set - nothing is written", file=sys.stderr)
        return 2
    counties = sorted({str(r.get("county") or "") for r in rows if isinstance(r, dict)} - {""})
    try:
        stored = read_stored(base, key, state=a.state, source=a.source, counties=counties)
    except Exception as exc:  # noqa: BLE001 - fail closed: an unguarded write would erase stored values
        print(f"sync_value_guard: stored rows could not be read ({type(exc).__name__}) - nothing is written", file=sys.stderr)
        return 2
    counts: Counter = Counter()
    guarded = guard_rows(a.source, rows, stored, counts)
    Path(a.out).write_text(json.dumps(guarded), encoding="utf-8")
    summary = ", ".join(f"{k}={v}" for k, v in sorted(counts.items())) or "none"
    print(f"Stored-value guard ({a.source}): {len(rows)} row(s), {len(stored)} stored row(s) read; "
          f"stored values kept: {summary}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
