#!/usr/bin/env python3
"""
Harvest "Lands Available for Taxes" (LAFT) listings for Leon County from
its lforms.leonclerk.com tax-deed portal.

Added 2026-08-31 while investigating why Leon's LAFT count kept showing 0
in production despite `data/laft_html_sources.csv` listing it as a
confirmed-live source (https://lforms.leonclerk.com/tax_deeds/lands-available.html).

THE BUG (in harvest_laft_html.py, not fixable there): that page has no real
HTML table at all. `#results_table` is an empty DataTables skeleton -
column definitions only, no `<tr>` data rows - populated client-side via an
AJAX GET to a static JSON file after the page's own JS runs. A plain
`requests.get()` + BeautifulSoup scan (what harvest_laft_html.py does) sees
only the empty skeleton and correctly, silently reports 0 rows. This isn't
the same bug as Gadsden/commit 81e22d6 (a header-text-matching bug on a
real table) - Leon never reaches a real table row to begin with.

THE FIX: skip the HTML page entirely and hit the JSON file directly - GET
`https://lforms.leonclerk.com/tax_deeds/listoflands.txt` returns
`{"data": [...]}`, no auth, no session, confirmed live 2026-08-31 with 2
real properties (bids $77,445.14 and $18,937.00 - real, non-zero values,
unlike the empty page scan). Same category of fix as Osceola and Pioneer:
stop trying to parse/drive the rendered page, go straight to the data
source the page's own JS already uses.

Leon was removed from `data/laft_html_sources.csv` in the same commit that
added this file - leaving it in would just waste an HTTP request fetching a
page this script no longer needs, since the empty-skeleton scan can never
find real rows there.

Output: harvest_laft_leon.json / .csv - kept separate from the other
harvesters' outputs, same convention as harvest_laft_osceola.py etc.
sync-laft-to-supabase.ps1 merges all of them.
"""
from __future__ import annotations

import csv
import json
import sys
from datetime import datetime
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
OUT_DIR = HERE / "../out"
OUT_JSON = OUT_DIR / "harvest_laft_leon.json"
OUT_CSV = OUT_DIR / "harvest_laft_leon.csv"

COUNTY = "Leon"
PAGE_URL = "https://lforms.leonclerk.com/tax_deeds/lands-available.html"
DATA_URL = "https://lforms.leonclerk.com/tax_deeds/listoflands.txt"

# Confirmed live field names in the JSON response (2026-08-31).
FIELD_MAP = {
    "NewCert": "case_no",
    "Parcel_Number": "parcel",
    "Legal_Address": "address",
    "Legal_Description": "legal_desc",
    "Homestead": "homestead",
    "Assessed_Value": "assessed",
    "Opening_Bid": "bid",
    "Escheatment_Date": "escheatment_date",
}

# Already MM/DD/YYYY on the wire (e.g. "10/22/2025"), which is exactly what
# sync-laft-to-supabase.ps1's ConvertTo-IsoDate expects first - passed
# through as-is rather than reformatted, same as most other harvesters.
DATE_FIELD = "Auction_Date"


def _clean(value) -> str:
    if value is None:
        return ""
    return str(value).strip()


def harvest() -> list[dict]:
    resp = requests.get(DATA_URL, timeout=30, headers={"Accept": "application/json, text/plain, */*"})
    resp.raise_for_status()
    payload = resp.json()
    entries = payload.get("data", []) if isinstance(payload, dict) else []

    out: list[dict] = []
    for entry in entries:
        record: dict = {"county": COUNTY, "source": "laft", "url_auction": PAGE_URL}
        for api_field, out_field in FIELD_MAP.items():
            value = _clean(entry.get(api_field))
            if value:
                record[out_field] = value
        sale_date = _clean(entry.get(DATE_FIELD))
        if sale_date:
            # Defensive normalisation in case the source ever changes shape -
            # pass through untouched if it's already MM/DD/YYYY.
            try:
                datetime.strptime(sale_date, "%m/%d/%Y")
                record["sale_date"] = sale_date
            except ValueError:
                record["sale_date"] = sale_date  # pass through rather than drop the data
        if record.get("case_no") or record.get("parcel"):
            out.append(record)
    return out


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"[1/1] {COUNTY}", flush=True)
    try:
        rows = harvest()
    except Exception as exc:  # noqa: BLE001 - report cleanly, don't crash the job
        print(f"    ERROR: {exc}", flush=True)
        rows = []

    if rows:
        priced = sum(1 for r in rows if r.get("bid"))
        print(f"    {len(rows)} properties ({priced} with an opening bid)", flush=True)
    else:
        print("    no properties currently listed", flush=True)

    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2)

    if rows:
        fieldnames = sorted({k for row in rows for k in row.keys()})
        with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
    else:
        OUT_CSV.write_text("", encoding="utf-8")

    print("")
    print("=" * 50)
    print(f"Harvested {len(rows)} LAFT properties total (Leon County)")
    print("=" * 50)
    print(f"Saved: {OUT_JSON}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
