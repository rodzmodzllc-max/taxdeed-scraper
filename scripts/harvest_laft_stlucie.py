#!/usr/bin/env python3
"""
Harvest "Lands Available for Taxes" (LAFT) listings for St. Lucie County from
its AcclaimWeb/TributeWeb platform (by Aptitude Solutions) -
acclaimweb.stlucieclerk.gov/TributeWeb/ - a sixth distinct LAFT vendor,
separate from the PDF counties, the plain-HTML-table counties, the RealTDM
counties, the Pioneer/TaxSmartWeb counties, and Orange County's own TDSM
tool (see harvest_laft_pdfs.py / harvest_laft_html.py / harvest_laft_realtdm.py
/ harvest_laft_pioneer.py / harvest_laft_orange.py).

Single county so far - built as a standalone script (same pattern as Orange
County's harvester) rather than a CSV-driven list, since St. Lucie is the
only confirmed county on this exact platform. If more AcclaimWeb/TributeWeb
counties are confirmed later, this should be refactored into a CSV-driven
harvester the same way Pioneer/RealTDM are.

USES A REAL HEADLESS BROWSER (Playwright/Chromium), matching the same
precaution established for the Pioneer/TaxSmartWeb harvester, for the same
class of reason:

1. Confirmed live via the browser (2026-08-25) that clicking the "Lands
   Available" search-option link (a plain `<a href="#">` with NO visible
   onclick attribute in the DOM - it's bound via whatever JS framework this
   app uses, not inline HTML) is required before the "Search Records"
   button (`<input type="submit" id="butSearch">`) will search the right
   record set. This is the exact same "hidden tab/panel" class of bug that
   broke the Pioneer harvester's first Playwright attempt - see that
   module's docstring for the general lesson. Confirmed this app's page is
   real ASP.NET WebForms (a `__VIEWSTATE` hidden field is present), so the
   fix used for Volusia's __doPostBack pattern (a plain `requests`
   GET-then-POST with the captured viewstate) might also work here, but
   given the confirmed hidden-JS-click-handler dependency (not just a
   __doPostBack call) and this project's now-established "don't trust an
   HTTP-level reproduction of an unfamiliar site's search without checking
   it against a county KNOWN to have live data" lesson (see
   harvest_laft_pioneer.py), Playwright is used here from the start rather
   than attempting a `requests`-based reproduction first.
2. Confirmed live: clicking "Lands Available" then "Search Records" (a real
   `<form method="post">` submit, same URL, page reload) correctly returns
   St. Lucie's real live Lands Available list - confirmed with 5 real
   properties at the time of writing (Applicant/Case Number/Certificate
   Number/Issue Year/Parcel ID/Sale Date/Current Status/Opening
   Bid/Property Owners, status "LA" on every row).

Results table: a plain Bootstrap table, `<table id="dgResults"
class="table table-condensed">` - NOT a jqGrid like Pioneer's. Its header
row uses plain `<td>` cells (not `<th>`) with no id/class/aria-describedby
of any kind, so columns are matched by READING THE HEADER ROW'S TEXT AND
BUILDING A NAME->INDEX MAP at parse time, rather than assuming a fixed
column order - this is more robust to the vendor silently reordering
columns than a hardcoded positional index would be, and mirrors the
suffix-matching approach used for Pioneer's jqGrid (matching by a stable
identifier found in the live markup, not by position/assumption).

Zero-results handling: not yet confirmed live what a genuine zero look like
on this platform (St. Lucie has always had live LAFT properties whenever
checked so far) - treated the same as Pioneer's "no grid found" case (an
empty list, not an error) since that's the most common zero-result pattern
across every LAFT vendor in this project so far. Worth re-confirming by
hand if this ever silently returns 0 in production, per the same
known-nonzero-county discipline used for Pioneer.

CI note: relies on the same `playwright install chromium --with-deps` CI
step already added for the Pioneer harvester.

Output: harvest_laft_stlucie.json / .csv - kept separate from the other
harvesters' outputs. sync-laft-to-supabase.ps1 merges all of them.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
OUT_DIR = HERE / "../out"
OUT_JSON = OUT_DIR / "harvest_laft_stlucie.json"
OUT_CSV = OUT_DIR / "harvest_laft_stlucie.csv"

BASE_URL = "https://acclaimweb.stlucieclerk.gov/TributeWeb/"
COUNTY = "St. Lucie"

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

# Matched by visible text, not by any id/href - see module docstring. The
# link has no stable id/onclick attribute in the DOM to key off of.
LANDS_AVAILABLE_LINK_SELECTOR = 'a:text-is("Lands Available")'
SEARCH_BUTTON_SELECTOR = "#butSearch"
RESULTS_TABLE_SELECTOR = "table#dgResults"

# Output field name for each known header-row label. Any header cell not in
# this map is still captured (slugified) rather than silently dropped, so a
# new column the vendor adds shows up in the output instead of vanishing.
HEADER_FIELD_MAP = {
    "applicant": "applicant",
    "case number": "case_no",
    "certificate number": "certificate_no",
    "issue year": "issue_year",
    "parcel id": "parcel",
    "sale date": "sale_date",
    "current status": "status",
    "opening bid": "bid",
    "property owners": "owners",
}


def harvest() -> list[dict]:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(user_agent=UA)
        try:
            page.goto(BASE_URL, timeout=30_000, wait_until="load")
            # Activate the "Lands Available" search option first - see
            # module docstring. Its own search-criteria panel (and correct
            # search-button behavior) depends on this being clicked first,
            # the same class of dependency confirmed for Pioneer.
            page.click(LANDS_AVAILABLE_LINK_SELECTOR, timeout=10_000)
            page.wait_for_selector(SEARCH_BUTTON_SELECTOR, state="visible", timeout=10_000)
            page.click(SEARCH_BUTTON_SELECTOR, timeout=10_000)
            page.wait_for_load_state("load", timeout=30_000)
            html = page.content()
        finally:
            browser.close()
    return _parse_results(html)


def _slugify(label: str) -> str:
    return "_".join(label.lower().split())


def _parse_results(html: str) -> list[dict]:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    table = soup.select_one(RESULTS_TABLE_SELECTOR)
    if table is None:
        # No results table at all is treated as a real zero - see module
        # docstring's "Zero-results handling" section.
        return []

    rows = table.find_all("tr")
    if not rows:
        return []

    header_cells = [c.get_text(strip=True) for c in rows[0].find_all(["td", "th"])]
    if not header_cells or not any(header_cells):
        return []
    field_names = [
        HEADER_FIELD_MAP.get(label.lower(), _slugify(label)) for label in header_cells
    ]

    out: list[dict] = []
    for row in rows[1:]:
        cells = row.find_all("td")
        if not cells or len(cells) != len(field_names):
            # Pagination/footer rows (e.g. a lone page-number cell) won't
            # match the header's column count - skip rather than misalign.
            continue
        record = {
            field_names[i]: cells[i].get_text(strip=True)
            for i in range(len(cells))
            if cells[i].get_text(strip=True)
        }
        if record.get("case_no") or record.get("parcel") or record.get("certificate_no"):
            record["county"] = COUNTY
            record["source"] = "laft"
            record["url_auction"] = BASE_URL
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
        print(f"    {len(rows)} properties", flush=True)
    else:
        print("    no properties currently listed", flush=True)

    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2)

    if rows:
        fieldnames = sorted({k for row in rows for k in row.keys()})
        with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
            import csv

            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
    else:
        OUT_CSV.write_text("", encoding="utf-8")

    print("")
    print("=" * 50)
    print(f"Harvested {len(rows)} LAFT properties total (St. Lucie County)")
    print("=" * 50)
    print(f"Saved: {OUT_JSON}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
