#!/usr/bin/env python3
"""
Harvest "Lands Available for Taxes" (LAFT) listings for Hillsborough County
from its OnBase-based "Public Access View" (PAV) search tool -
publicaccess.hillsclerk.com/TD/ - an eighth distinct LAFT vendor, separate
from the PDF counties, the plain-HTML-table counties, the RealTDM counties,
the Pioneer/TaxSmartWeb counties, Orange County's TDSM tool, St. Lucie's
AcclaimWeb/TributeWeb tool, and Osceola's NewVision tool (see
harvest_laft_pdfs.py / harvest_laft_html.py / harvest_laft_realtdm.py /
harvest_laft_pioneer.py / harvest_laft_orange.py / harvest_laft_stlucie.py /
harvest_laft_osceola.py).

Single county so far - built as a standalone script (same pattern as Orange/
St. Lucie/Osceola) rather than a CSV-driven list, since Hillsborough is the
only confirmed county on this exact OnBase PAV platform.

USES A REAL HEADLESS BROWSER (Playwright/Chromium), for the same class of
reason established for every other LAFT vendor here: this is an Angular
reactive-forms app and its "List of Lands Available" search TYPE is
misleading - see below - so the search has to be driven exactly the way a
real browser session was confirmed to behave, not guessed at via HTTP.

IMPORTANT PLATFORM QUIRK - the search type's name lies: despite this page
being titled "List of Lands Available Search" and its (fixed, unchangeable)
Search Type field reading "PAV - TD - List of Lands Available", confirmed
live (2026-08-25) that searching with only a date range returns EVERY
tax-deed case in that window regardless of status - SOLD, REDEEMED, SALE,
PENDING, etc. - and every document type filed against it (TD - O & E
Report, TD - Tax Collector App DR512, TD - Tax Collector Cert DR513, TD -
Tax Deed, TD - Certificate of Mailing), with a banner reading "There are
more results than what is displayed. Please narrow your search criteria."
This is NOT a pre-filtered Lands-Available-only list like every other LAFT
vendor in this project - it's a general case-search tool whose default
search type just happens to be labeled after the county's LAFT program.

THE FIX: the "Case Status" field (id `obpa_kw_1014`) is a plain HTML5
`<input list="obpa_kw_1014_list">` backed by a `<datalist>` of allowed
values - confirmed live by reading the datalist's `<option>` elements
directly out of the DOM (not by opening any visible dropdown UI, which this
project's tools could not read - see below). Its values are: BANKRUPTCY,
CANCELED, CLOSED, ESCHEAT, LANDS FOR SALE, PENDING, REDEEMED, RESCHEDULED,
SALE, SOLD, STAY BY COURT ORDER, WITHDRAWN / NON-PAYM, WITHDRAWN / TAX
COLL. Setting this field to exactly "LANDS FOR SALE" (via the same
native-input-value-setter + dispatched input/change/blur events pattern
used throughout this project for framework-bound fields, since a plain
`.value =` assignment doesn't trigger Angular's change detection) and then
searching returns ONLY genuine Lands-Available-status cases - confirmed
live: every row of every result came back tagged "LANDS FOR SALE" with no
"more results" truncation banner. This is the actual, correct way to get a
clean Lands Available list from this platform.

(Aside for future maintainers: the on-page dropdown-looking affordance next
to Case Status does not expose its option list to DOM text-extraction tools
- no `role="listbox"`/`role="option"` elements, no visible `<select>`, no
`aria-controls`/`aria-owns` link, and it lives outside normal `get_page_text`
extraction. The datalist is bound to the input via the standard `list=`
attribute and is always present in the DOM regardless of dropdown UI state,
so reading `#obpa_kw_1014_list option` directly is both the reliable path
and the one used to discover the values above.)

Per this page's own on-screen hint - "To search for a complete list of Tax
Deeds Lands Available use a start and end date with a 3 year span." - this
harvester always searches a trailing 3-year window ending today (computed
at run time, not hardcoded), matching the exact span confirmed live to
return a complete, non-truncated result set together with the Case Status
filter.

No hidden-tab-click dependency here, unlike Pioneer/St. Lucie/Osceola -
this page's single search type is fixed and already active; only the date
range and Case Status fields need to be filled before clicking Search.

Results table: a plain (non-virtualized) Infragistics igGrid HTML table,
`<table id="obpa-grid" class="ui-iggrid-table ...">` - confirmed live that
every result row is present in the DOM at once (rowCount matched the
visible result count exactly), so unlike Osceola's ag-Grid this needs NO
scroll-and-collect handling. Its header row has a leading and trailing
blank `<td>` (an expand-icon column and an unused trailing column) plus:
File #, Folio #, Auction Date, Certificate #, Case Status, Opening Bid,
Winning Bid, Document Type - matched by header TEXT into a name->index map,
same discipline as every other harvester here, so a vendor column reorder
doesn't silently misalign data.

CRITICAL DEDUPE STEP: this platform files multiple DOCUMENT records per
case (one row per Document Type - e.g. a single Lands-Available case shows
up as 3-4 rows, one each for "TD - Certificate of Mailing", "TD - O & E
Report", "TD - Tax Collector App (DR512)", "TD - Tax Collector Cert
(DR513)") - confirmed live: all of a case's rows share an identical File #/
Folio #/Auction Date/Certificate #/Case Status/Opening Bid/Winning Bid and
differ ONLY in Document Type. Document Type is dropped entirely (like
Osceola's "Detail" action column) and rows are de-duplicated by File #,
keeping the first-seen row - this is a per-CASE list, not a per-document
list, matching what every other LAFT harvester in this project produces.

Zero-results / truncation handling: no `#obpa-grid` rendering within the
wait timeout is treated as a real zero (consistent with every other LAFT
vendor's pattern here). The "more results than what is displayed" banner
text is also checked for even with the Case Status filter applied - not
observed in production as of 2026-08-25, but logged as a loud (non-fatal)
warning if it ever reappears, since it would mean this county's Lands
Available inventory has grown large enough to need pagination or a
narrower per-request date window, mirroring the pagination/virtualization
discipline used for Pioneer and Osceola.

CI note: relies on the same `playwright install chromium --with-deps` CI
step already added for the Pioneer/St. Lucie/Osceola harvesters.

Output: harvest_laft_hillsborough.json / .csv - kept separate from the
other harvesters' outputs. sync-laft-to-supabase.ps1 merges all of them.
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
OUT_DIR = HERE / "../out"
OUT_JSON = OUT_DIR / "harvest_laft_hillsborough.json"
OUT_CSV = OUT_DIR / "harvest_laft_hillsborough.csv"

BASE_URL = "https://publicaccess.hillsclerk.com/TD/"
COUNTY = "Hillsborough"

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

DATE_FROM_SELECTOR = "#obpa_date_from"
DATE_TO_SELECTOR = "#obpa_date_to"
CASE_STATUS_SELECTOR = "#obpa_kw_1014"
CASE_STATUS_VALUE = "LANDS FOR SALE"
SEARCH_BUTTON_SELECTOR = 'button[type="submit"]'
RESULTS_TABLE_SELECTOR = "table#obpa-grid"
MORE_RESULTS_BANNER_TEXT = "more results than what is displayed"

# Output field name for each known header-row label. Blank header cells
# (the leading expand-icon column and a trailing unused column) and
# "Document Type" are all deliberately absent - see module docstring's
# "CRITICAL DEDUPE STEP". Any header cell not in this map is still
# captured (slugified) rather than silently dropped, so a new column the
# vendor adds shows up in the output instead of vanishing.
HEADER_FIELD_MAP = {
    "file #": "case_no",
    "folio #": "parcel",
    "auction date": "sale_date",
    "certificate #": "certificate_no",
    "case status": "status",
    "opening bid": "bid",
    "winning bid": "winning_bid",
}
DROPPED_HEADERS = {"", "document type"}

# Native-setter + dispatched-events pattern for Angular reactive-forms
# fields - a plain Playwright `.fill()` was not trusted here without a live
# confirmation, so this mirrors the exact JS confirmed live in the browser
# to correctly update Angular's bound model (a plain `.value =` assignment
# does not trigger Angular's change detection on this app).
SET_FIELD_JS = """
([sel, val]) => {
    const el = document.querySelector(sel);
    if (!el) return false;
    const nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
    nativeSetter.call(el, val);
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
    el.dispatchEvent(new Event('blur', { bubbles: true }));
    return el.value === val;
}
"""


def _three_year_window() -> tuple[str, str]:
    """Trailing 3-year window ending today, MM/DD/YYYY - see module
    docstring's date-range rationale. Computed at run time, not hardcoded,
    so the harvester keeps working correctly on every future run."""
    today = date.today()
    try:
        start = today.replace(year=today.year - 3)
    except ValueError:
        # Feb 29 on a non-leap 3-years-ago year - fall back a day.
        start = today.replace(year=today.year - 3, day=28)
    return start.strftime("%m/%d/%Y"), today.strftime("%m/%d/%Y")


def harvest() -> list[dict]:
    date_from, date_to = _three_year_window()
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(user_agent=UA)
        try:
            page.goto(BASE_URL, timeout=30_000, wait_until="load")
            page.wait_for_selector(CASE_STATUS_SELECTOR, state="visible", timeout=15_000)

            ok = True
            ok &= page.evaluate(SET_FIELD_JS, [DATE_FROM_SELECTOR, date_from])
            ok &= page.evaluate(SET_FIELD_JS, [DATE_TO_SELECTOR, date_to])
            ok &= page.evaluate(SET_FIELD_JS, [CASE_STATUS_SELECTOR, CASE_STATUS_VALUE])
            if not ok:
                raise RuntimeError(
                    "one or more search fields failed to set (selector missing or "
                    "value mismatch after set) - page structure may have changed"
                )

            page.click(SEARCH_BUTTON_SELECTOR, timeout=10_000)

            # No results table rendering within the timeout is treated as a
            # real zero-result search - see module docstring's "Zero-results
            # / truncation handling" section.
            try:
                page.wait_for_selector(RESULTS_TABLE_SELECTOR, state="visible", timeout=15_000)
            except Exception:
                browser.close()
                return []

            body_text = page.inner_text("body")
            header_cells = page.eval_on_selector_all(
                f"{RESULTS_TABLE_SELECTOR} thead tr, {RESULTS_TABLE_SELECTOR} tr",
                "els => els.length ? Array.from(els[0].querySelectorAll('th, td')).map(c => c.textContent.trim()) : []",
            )
            body_rows = page.eval_on_selector_all(
                f"{RESULTS_TABLE_SELECTOR} tbody tr",
                "rows => rows.map(r => Array.from(r.querySelectorAll('td')).map(c => c.textContent.trim()))",
            )
        finally:
            browser.close()
    return _parse_results(header_cells, body_rows, body_text)


def _slugify(label: str) -> str:
    return "_".join(label.lower().split())


def _parse_results(header_cells: list[str], body_rows: list[list[str]], body_text: str) -> list[dict]:
    if not header_cells or not body_rows:
        return []

    field_names: list[str | None] = []
    for label in header_cells:
        key = label.lower().strip()
        if key in DROPPED_HEADERS:
            field_names.append(None)
        else:
            field_names.append(HEADER_FIELD_MAP.get(key, _slugify(label)))

    seen_case_nos: set[str] = set()
    out: list[dict] = []
    for cells in body_rows:
        if len(cells) != len(field_names):
            # A row that doesn't match the header's column count - skip
            # rather than risk misaligning data (same discipline used for
            # St. Lucie's pagination/footer rows).
            continue
        record: dict = {}
        for i, text in enumerate(cells):
            field = field_names[i]
            if field is None or not text:
                continue
            record[field] = text
        case_no = record.get("case_no")
        if not (case_no or record.get("parcel")):
            continue
        # De-dup by case_no - see module docstring's "CRITICAL DEDUPE
        # STEP": this platform files one row per Document Type per case,
        # all otherwise identical. Keep the first-seen row per case.
        dedup_key = case_no or record.get("parcel")
        if dedup_key in seen_case_nos:
            continue
        seen_case_nos.add(dedup_key)
        record["county"] = COUNTY
        record["source"] = "laft"
        record["url_auction"] = BASE_URL
        out.append(record)

    # Loud (non-fatal) mismatch check - see module docstring's
    # "Zero-results / truncation handling" section. Not observed in
    # production with the Case Status filter applied as of 2026-08-25, but
    # kept as a safety net.
    if MORE_RESULTS_BANNER_TEXT in (body_text or "").lower():
        print(
            "    WARNING: page reports more results than displayed even with the "
            "Case Status='LANDS FOR SALE' filter applied - this county's Lands "
            "Available inventory may now need a narrower per-request date window "
            "to harvest completely",
            flush=True,
        )

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
    print(f"Harvested {len(rows)} LAFT properties total (Hillsborough County)")
    print("=" * 50)
    print(f"Saved: {OUT_JSON}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
