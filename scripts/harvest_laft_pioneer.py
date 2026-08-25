#!/usr/bin/env python3
"""
Harvest "Lands Available for Taxes" (LAFT) listings from counties on the
Pioneer/TaxSmartWeb platform (rebranded in the page footer as "Catalis
Courts & Land Records, LLC") - a fourth distinct LAFT vendor, separate from
the PDF counties, the plain-HTML-table counties, and the RealTDM counties
(see harvest_laft_pdfs.py / harvest_laft_html.py / harvest_laft_realtdm.py).

Unlike RealTDM, this vendor does NOT use a shared subdomain convention -
each county runs its own distinct domain (confirmed live 2026-08-25:
Okeechobee is pioneer.okeechobeelandmark.com/TaxSmartWebLive/, Citrus is
search.citrusclerk.org/TaxSmartWeb) - so counties are onboarded here one at
a time as each one's base URL is confirmed, via ../data/laft_pioneer_counties.csv
(columns: County, BaseUrl, Notes).

USES A REAL HEADLESS BROWSER (Playwright/Chromium), unlike every other LAFT
harvester in this repo, which all reproduce their target site's search with
a plain `requests` POST. This is not a stylistic choice - it's a confirmed
requirement for this specific vendor:

  1. Confirmed live via the browser (2026-08-25) that a *real* click on the
     "Search for Lands Available" button (name="buttonSubmitLandsAvailable",
     a plain <button type="submit"> with no CSRF/anti-forgery hidden field
     anywhere on the page) followed by a full-page navigation returns the
     results grid correctly - e.g. Citrus returned 5 real properties,
     Okeechobee genuinely returned 0.
  2. A first attempt at this harvester reproduced that same POST with
     Python's `requests` library (same form fields, same button name/value,
     a `requests.Session()` carrying cookies from an earlier GET, a Referer
     header) - CONFIRMED LIVE IN PRODUCTION (2026-08-25, workflow run #50)
     that this comes back empty even for Citrus, which has 5 real live
     properties. Not a false zero from a network hiccup - it silently
     re-renders the blank search form instead of the results grid, every
     time, exactly like the browser's own fetch() API did when this was
     first being reverse-engineered (see git history for that version if
     you need the discarded `requests`-based approach). Whatever
     distinguishes a genuine browser-navigation POST from either a fetch()
     or a standalone HTTP client's POST on this vendor's stack is not
     understood - possibly some combination of header ordering, TLS/HTTP2
     fingerprinting, or a request property neither a browser's fetch() nor
     `requests` reproduces. It wasn't worth chasing further once a working
     alternative (drive an actual browser) was available.
  3. Playwright reproduces the exact thing that's confirmed to work: load
     the page, click the real button, wait for the real navigation, read
     the real resulting HTML. No form-serialization guesswork needed.

Zero-results counties (Okeechobee) render NO grid/table at all and no
"Results for Lands Available Search" heading - this is indistinguishable
in the HTML from a failed search. Since Playwright reproduces genuine
browser behavior (the one mechanism confirmed to distinguish a real zero
from a false one), a "no grid" result here is trusted as a real zero.

Results table: when there ARE results, they render into a jqGrid table
(<table class="... ui-jqgrid-btable ...">, observed id="TaxDeed" on
Citrus - the id is NOT assumed to be stable across counties, matched by
class instead). Each data cell carries a stable `aria-describedby`
attribute ending in a recognizable field-name suffix (e.g.
"TaxDeed_Applicant", "TaxDeed_CaseNumber", "TaxDeed_CertificateNumber",
"TaxDeed_ParcelID", "TaxDeed_SaleDate", "TaxDeed_Status") - matched by
suffix here rather than assuming the "TaxDeed_" prefix is the same on
every county.

Pagination: not yet handled beyond logging a loud warning if the grid's
own "View X - Y of Z" footer text reports more rows than were parsed -
every LAFT list checked across every platform so far has been small
(single digits to low dozens), so this is treated as an unlikely edge
case worth flagging rather than a routine case worth the complexity of
driving the grid's own pagination controls.

CI note: this is the only LAFT harvester step that needs
`playwright install chromium --with-deps` before it can run - see the
"Install Playwright browser" step immediately before this script's step
in harvest-and-sync.yml. That install alone typically costs @30-60s of
job time, on top of the ~1-2s per county the actual harvest takes.

Output: harvest_laft_pioneer.json / .csv - kept separate from the other
three harvesters' outputs. sync-laft-to-supabase.ps1 merges all four.
"""
from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
SOURCES_CSV = HERE / "../data/laft_pioneer_counties.csv"
OUT_DIR = HERE / "../out"
OUT_JSON = OUT_DIR / "harvest_laft_pioneer.json"
OUT_CSV = OUT_DIR / "harvest_laft_pioneer.csv"

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

SEARCH_BUTTON_SELECTOR = 'button[name="buttonSubmitLandsAvailable"]'

# aria-describedby suffix -> output field name. Matched with str.endswith()
# against each <td>'s aria-describedby, NOT an exact/prefix match, since the
# prefix before the underscore (confirmed "TaxDeed_" on Citrus) is not
# assumed stable across every county's grid configuration.
FIELD_SUFFIXES = {
    "Applicant": "applicant",
    "CaseNumber": "case_no",
    "CertificateNumber": "certificate_no",
    "ParcelID": "parcel",
    "SaleDate": "sale_date",
    "Status": "status",
    "OpeningBid": "bid",
    "HighBid": "high_bid",
    "Surplus": "surplus",
    "Owners": "owners",
}

VIEW_COUNT_RE = re.compile(r"View\s+\d+\s*-\s*\d+\s+of\s+(\d+)", re.IGNORECASE)


def harvest_county(browser, county: str, base_url: str) -> list[dict]:
    page = browser.new_page(user_agent=UA)
    try:
        page.goto(base_url, timeout=30_000, wait_until="load")
        page.click(SEARCH_BUTTON_SELECTOR, timeout=10_000)
        # The click submits a real <form method="post"> - wait for the
        # resulting full-page navigation to finish loading rather than any
        # fixed sleep, matching how this was confirmed to work by hand.
        page.wait_for_load_state("load", timeout=30_000)
        html = page.content()
    finally:
        page.close()
    return _parse_results(html, county, base_url)


def _parse_results(html: str, county: str, source_url: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", class_=lambda c: c and "ui-jqgrid-btable" in c.split())
    if table is None:
        # No grid at all is this platform's normal rendering for a true
        # zero-result search (confirmed live on Okeechobee) - not
        # necessarily an error, so this returns cleanly rather than
        # raising.
        return []

    out: list[dict] = []
    for row in table.find_all("tr"):
        cells = row.find_all("td")
        if not cells:
            continue
        record: dict = {}
        for cell in cells:
            described_by = cell.get("aria-describedby") or ""
            for suffix, field in FIELD_SUFFIXES.items():
                if described_by.endswith("_" + suffix):
                    text = cell.get_text(strip=True)
                    if text:
                        record[field] = text
                    break
        if record.get("case_no") or record.get("parcel") or record.get("certificate_no"):
            record["county"] = county
            record["source"] = "laft"
            record["url_auction"] = source_url
            out.append(record)

    # Loud (non-fatal) pagination check - see module docstring.
    footer_text = soup.get_text(" ", strip=True)
    m = VIEW_COUNT_RE.search(footer_text)
    if m and int(m.group(1)) > len(out):
        print(
            f'    WARNING: grid footer reports {m.group(1)} total rows but only '
            f'{len(out)} were parsed - possible pagination not yet handled',
            flush=True,
        )

    return out


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(SOURCES_CSV, newline="", encoding="utf-8") as f:
        sources = list(csv.DictReader(f))

    all_rows: list[dict] = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            for i, src in enumerate(sources, 1):
                county, base_url = src["County"], src["BaseUrl"]
                print(f"[{i}/{len(sources)}] {county}", flush=True)
                try:
                    rows = harvest_county(browser, county, base_url)
                    if rows:
                        print(f"    {len(rows)} properties", flush=True)
                        all_rows.extend(rows)
                    else:
                        print("    no properties currently listed", flush=True)
                except Exception as exc:  # noqa: BLE001 - one bad county must not kill the whole run
                    print(f"    ERROR: {exc}", flush=True)
        finally:
            browser.close()

    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(all_rows, f, indent=2)

    if all_rows:
        fieldnames = sorted({k for row in all_rows for k in row.keys()})
        with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(all_rows)
    else:
        OUT_CSV.write_text("", encoding="utf-8")

    print("")
    print("=" * 50)
    print(f"Harvested {len(all_rows)} LAFT properties total")
    print(f"Counties with matches: {len({r['county'] for r in all_rows})} of {len(sources)} checked")
    print("=" * 50)
    print(f"Saved: {OUT_JSON}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
