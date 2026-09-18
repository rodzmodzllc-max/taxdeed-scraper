#!/usr/bin/env python3
"""READ-ONLY probe: which field labels do RealAuction county sites expose?

Every Citrus and Hernando auction row in production (25 + 25, measured
2026-09-18) has parcel='' and url_appraiser=NULL while case #, opening bid,
assessed value and address on the same rows are all populated. All four of
those come from the same per-block label lookup in harvest_all_counties.ps1:

    parcel    = Get-Field $b 'Parcel ID'
    appraiser = Get-Href  $b 'Parcel ID'

so the block parses, and only the 'Parcel ID' label is missing on those two
sites. This script replays the harvester's own request sequence (calendar ->
preview warm-up -> paginated AJAX JSON) against a small county list, splits
the response into AITEM_ blocks exactly as the harvester does, and reports:

  * the distinct CAD_LBL labels each county's blocks carry;
  * for the first block, every label -> value pair, using the same regex
    shape as Get-Field, so the parcel's real label (if any) is visible next
    to a known-good county's 'Parcel ID';
  * whether 'Parcel ID' resolves at all.

GET only. No Supabase access, no secrets, nothing written but out/. Public
auction listing pages, same UA and cadence the production harvester uses.
"""
from __future__ import annotations

import csv
import json
import pathlib
import re
import sys
import time
from datetime import date

import requests

HERE = pathlib.Path(__file__).resolve().parent
COUNTIES_CSV = HERE / "../data/realauction_counties.csv"
OUT_DIR = HERE / "../out"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

# The two broken counties plus known-good controls with real parcels in
# production (Alachua: 'Parcel ID' resolves; Lee: 22-char STRAP resolves).
TARGETS = ["Citrus", "Hernando", "Alachua", "Lee"]

# Same shape as Get-Field's pattern in harvest_all_counties.ps1: the block is
# JSON-escaped HTML, so quotes arrive as \" - tolerate both raw and escaped.
LABEL_RE = re.compile(r'CAD_LBL\\?"[^>]*>\s*([^@<>]{1,60}?)\s*:')
def field_value(block: str, label: str) -> str | None:
    pat = (re.escape(label) + r':(?:@F|<)[\s\S]{0,200}?CAD_DTA\\?">\s*'
           r'([^@<]*(?:<a[^>]*>([^<]*)</a>)?[^@<]*)')
    m = re.search(pat, block)
    if not m:
        return None
    v = m.group(2) if m.group(2) else m.group(1)
    return re.sub(r"\s+", " ", v.replace('\\"', '"')).strip()


def href_for(block: str, label: str) -> str | None:
    m = re.search(re.escape(label) + r':[\s\S]{0,200}?href=\\?"([^\\"]+)\\?"', block)
    return m.group(1).replace("&amp;", "&") if m else None


def month_starts(n: int = 3):
    today = date.today()
    y, m = today.year, today.month
    for _ in range(n):
        yield f"{y:04d}-{m:02d}"
        m += 1
        if m == 13:
            y, m = y + 1, 1


def probe_county(county: str, host: str) -> dict:
    s = requests.Session()
    s.headers["User-Agent"] = UA
    result = {"county": county, "host": host, "dates": [], "errors": [], "blocks_seen": 0,
              "labels": [], "first_block_fields": {}, "parcel_id_value": None,
              "parcel_id_href": None, "first_block_excerpt": ""}
    dates: list[str] = []
    for ym in month_starts():
        ts = f"{{ts '{ym}-01 00:00:00'}}"
        try:
            r = s.get(f"https://{host}/index.cfm", timeout=20,
                      params={"zaction": "user", "zmethod": "calendar", "selCalDate": ts})
            r.raise_for_status()
        except requests.RequestException as exc:
            result["errors"].append(f"calendar {ym}: {exc!r}"[:200])
            continue
        dates += re.findall(r"CALSELT[^>]*dayid=['\"](\d{2}/\d{2}/\d{4})['\"]", r.text)
        time.sleep(0.5)
    dates = list(dict.fromkeys(dates))
    result["dates"] = dates
    if not dates:
        return result

    for d in dates[:3]:  # first date with listings wins; most counties have one
        preview = f"https://{host}/index.cfm?zaction=AUCTION&zmethod=PREVIEW&AuctionDate={d}"
        try:
            s.get(preview, timeout=20,
                  headers={"Referer": f"https://{host}/index.cfm?zaction=USER&zmethod=CALENDAR"}).raise_for_status()
            time.sleep(0.5)
            r = s.get(f"https://{host}/index.cfm", timeout=25,
                      params={"zaction": "AUCTION", "Zmethod": "UPDATE", "FNC": "LOAD", "AREA": "W",
                              "PageDir": "0", "doR": "1", "bypassPage": "1", "test": "1"},
                      headers={"Accept": "application/json, text/javascript, */*; q=0.01",
                               "X-Requested-With": "XMLHttpRequest", "Referer": preview})
            r.raise_for_status()
        except requests.RequestException as exc:
            result["errors"].append(f"listing {d}: {exc!r}"[:200])
            continue
        txt = r.text
        blocks = re.split(r"AITEM_", txt)[1:]
        if not blocks:
            continue
        result["blocks_seen"] = len(blocks)
        result["listing_date"] = d
        labels: list[str] = []
        for b in blocks:
            labels += LABEL_RE.findall(b)
        result["labels"] = sorted(set(l.strip() for l in labels))
        first = blocks[0]
        result["first_block_fields"] = {lab: field_value(first, lab) for lab in dict.fromkeys(LABEL_RE.findall(first))}
        result["parcel_id_value"] = field_value(first, "Parcel ID")
        result["parcel_id_href"] = href_for(first, "Parcel ID")
        result["first_block_excerpt"] = first[:1800].replace("\\\"", "\"")
        break
    return result


def main() -> int:
    OUT_DIR.mkdir(exist_ok=True)
    hosts = {r["County"]: r["Host"] for r in csv.DictReader(open(COUNTIES_CSV, newline=""))}
    out = []
    for county in TARGETS:
        host = hosts.get(county)
        print(f"\n=== {county} ({host}) ===", flush=True)
        if not host:
            print("  not in realauction_counties.csv", flush=True)
            continue
        res = probe_county(county, host)
        out.append(res)
        print(f"  dates: {res['dates']}", flush=True)
        print(f"  blocks seen on {res.get('listing_date')}: {res['blocks_seen']}", flush=True)
        print(f"  labels: {res['labels']}", flush=True)
        print(f"  'Parcel ID' -> value={res['parcel_id_value']!r} href={res['parcel_id_href']!r}", flush=True)
        for k, v in res["first_block_fields"].items():
            print(f"    {k!r}: {v!r}", flush=True)
        if res["errors"]:
            print(f"  errors: {res['errors']}", flush=True)
        print("  --- first block excerpt ---", flush=True)
        print("  " + res["first_block_excerpt"].replace("\n", "\n  "), flush=True)
        time.sleep(1.0)
    (OUT_DIR / "probe_realauction_labels.json").write_text(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
