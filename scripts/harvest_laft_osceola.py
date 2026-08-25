#!/usr/bin/env python3
"""
Harvest "Lands Available for Taxes" (LAFT) listings for Osceola County from
its own NewVision Systems Corporation search tool -
officialrecords.osceolaclerk.org/browserviewtd/ - a seventh distinct LAFT
vendor, separate from the PDF counties, the plain-HTML-table counties, the
RealTDM counties, the Pioneer/TaxSmartWeb counties, Orange County's TDSM
tool, and St. Lucie's AcclaimWeb/TributeWeb tool (see harvest_laft_pdfs.py /
harvest_laft_html.py / harvest_laft_realtdm.py / harvest_laft_pioneer.py /
harvest_laft_orange.py / harvest_laft_stlucie.py).

Single county so far - built as a standalone script (same pattern as Orange
and St. Lucie's harvesters) rather than a CSV-driven list, since Osceola is
the only confirmed county on this exact NewVision platform.

USES A REAL HEADLESS BROWSER (Playwright/Chromium), for the same class of
reason established for Pioneer and St. Lucie:

1. Confirmed live via the browser (2026-08-25) that the "Lands Available"
   search option is a plain `<a>` bound via AngularJS (no href, no visible
   onclick attribute in the DOM) that must be clicked before its own
   "Search" button (ng-click="runSearch(true)") becomes usable - the exact
   same "hidden tab/panel" class of dependency already confirmed on Pioneer
   and St. Lucie. No form-serialization or __VIEWSTATE reproduction was
   attempted given this project's established "don't trust an HTTP-level
   reproduction of an unfamiliar site's search" lesson (see
   harvest_laft_pioneer.py) - Playwright drives the real click sequence
   instead.
2. Confirmed live: clicking "Lands Available" then "Search" correctly
   returns Osceola's real live Lands Available list via a JSON POST to
   /browserviewtd/api/search (confirmed via the browser's network panel) -
   the results grid is populated client-side by AngularJS from that
   response, not a page reload. Confirmed with 10 real live LANDA-status
   properties at the time of writing.

CRITICAL ag-Grid VIRTUALIZATION HANDLING: the results grid is a genuine
ag-Grid instance (`.ag-header-cell` / `.ag-row` / `.ag-cell` with
`cell-col-N` classes), confirmed live via inspecting the DOM. ag-Grid only
renders rows currently scrolled into view in the DOM (a standard
virtualization optimization) - reading `.ag-row` once after search would
silently drop any rows beyond the initial viewport for a county with more
listings than fit on screen, a materially worse failure mode than the
"grid footer count vs parsed count" mismatch this project already warns
about for Pioneer's jqGrid. Each `.ag-row` carries a stable `row="N"`
attribute (the row's absolute index in the full result set, confirmed live
via the browser - NOT just its visible position), so this harvester
scrolls the grid's `.ag-body-viewport` in a loop, collecting every row seen
by that stable index into a dict (so a row that scrolls in and out more
than once is naturally deduplicated), until scrolling no longer advances
`scrollTop` (bottom reached). The grid's own "Retrieved records 1 through N
of N records" footer count is read and compared against the number of rows
actually collected - a loud (non-fatal) warning is logged on a mismatch,
mirroring the same discipline already used for Pioneer's jqGrid pagination
footer.

Results table: columns are matched by reading the live `.ag-header-cell`
text into a name->index map (same principle as St. Lucie's plain-`<td>`
table and Pioneer's aria-describedby suffixes) rather than assuming a fixed
`cell-col-N` order - confirmed live that `cell-col-N`'s N directly matches
the header cell's own 0-indexed position, so this holds even if the vendor
reorders columns later. The "Detail" column (index 0) is an action-button
column with no real data ("View" literal text) and is explicitly dropped
from the parsed record rather than being kept under a slugified key.

Zero-results handling: not yet confirmed live what a genuine zero looks
like on this platform (Osceola has had live LAFT properties whenever
checked so far) - treated as a real zero if no `.ag-row` element appears
within the wait timeout after clicking Search, consistent with every other
LAFT vendor's "no grid rendered = no error, real zero" pattern used
throughout this project. Worth re-confirming by hand if this ever silently
returns 0 in production, per the same known-nonzero-county discipline used
for Pioneer and St. Lucie.

CI note: relies on the same `playwright install chromium --with-deps` CI
step already added for the Pioneer and St. Lucie harvesters.

Output: harvest_laft_osceola.json / .csv - kept separate from the other
harvesters' outputs. sync-laft-to-supabase.ps1 merges all of them.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
OUT_DIR = HERE / "../out"
OUT_JSON = OUT_DIR / "harvest_laft_osceola.json"
OUT_CSV = OUT_DIR / "harvest_laft_osceola.csv"

BASE_URL = "https://officialrecords.osceolaclerk.org/browserviewtd/"
COUNTY = "Osceola"

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

# Matched by visible text, not by any id/href - see module docstring. Same
# hidden-tab dependency confirmed on Pioneer and St. Lucie.
LANDS_AVAILABLE_LINK_SELECTOR = 'a:text-is("Lands Available")'
SEARCH_BUTTON_SELECTOR = 'button:text-is("Search")'
HEADER_CELL_SELECTOR = ".ag-header-cell.ag-header-cell-not-grouped"
ROW_SELECTOR = ".ag-row"
VIEWPORT_SELECTOR = ".ag-body-viewport"

# Output field name for each known header-row label. "Detail" is
# deliberately absent - it's an action-button column with no real data and
# is dropped explicitly in _parse_results rather than falling through to
# the slugify fallback.
HEADER_FIELD_MAP = {
    "tax number": "case_no",
    "base bid": "bid",
    "highest bid": "high_bid",
    "type": "type",
    "name": "owners",
    "parcel number": "parcel",
    "status": "status",
    "sale date": "sale_date",
    "tax deed id": "tax_deed_id",
}

FOOTER_COUNT_RE = re.compile(r"of\s+(\d+)\s+records", re.IGNORECASE)

# Scrolls the ag-Grid viewport collecting every row seen (keyed by its
# stable `row` attribute) until scrollTop stops advancing - see module
# docstring's "CRITICAL ag-Grid VIRTUALIZATION HANDLING" section. Returns
# {rowIndex: {colIndex: cellText}}.
SCROLL_COLLECT_JS = """
async () => {
    const viewport = document.querySelector('.ag-body-viewport');
    const collected = {};
    function collectVisible() {
        document.querySelectorAll('.ag-row').forEach(row => {
            const idx = row.getAttribute('row');
            if (idx === null) return;
            const cells = {};
            row.querySelectorAll('.ag-cell').forEach(cell => {
                const m = cell.className.match(/cell-col-(\\d+)/);
                if (m) cells[m[1]] = cell.textContent.trim();
            });
            collected[idx] = cells;
        });
    }
    collectVisible();
    let guard = 0;
    while (guard < 500) {
        guard++;
        const before = viewport.scrollTop;
        viewport.scrollTop = viewport.scrollTop + viewport.clientHeight;
        await new Promise(r => setTimeout(r, 60));
        collectVisible();
        if (viewport.scrollTop === before) break;
    }
    return collected;
}
"""


def harvest() -> list[dict]:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(user_agent=UA)
        try:
            page.goto(BASE_URL, timeout=30_000, wait_until="load")
            # Activate the "Lands Available" search option first - see
            # module docstring. Its own Search button depends on this.
            page.click(LANDS_AVAILABLE_LINK_SELECTOR, timeout=10_000)
            page.wait_for_selector(SEARCH_BUTTON_SELECTOR, state="visible", timeout=10_000)
            page.click(SEARCH_BUTTON_SELECTOR, timeout=10_000)

            # No grid rendering within the timeout is treated as a real
            # zero-result search - see module docstring's "Zero-results
            # handling" section.
            try:
                page.wait_for_selector(ROW_SELECTOR, state="visible", timeout=15_000)
            except Exception:
                browser.close()
                return []

            header_labels = page.eval_on_selector_all(
                HEADER_CELL_SELECTOR, "els => els.map(e => e.textContent.trim())"
            )
            footer_text = page.inner_text("body")
            collected = page.evaluate(SCROLL_COLLECT_JS)
            html_for_debug = None  # not needed - parsed entirely via the JS collection above
        finally:
            browser.close()
    return _parse_results(collected, header_labels, footer_text)


def _slugify(label: str) -> str:
    return "_".join(label.lower().split())


def _parse_results(collected: dict, header_labels: list[str], footer_text: str) -> list[dict]:
    if not header_labels:
        return []
    field_names = [
        HEADER_FIELD_MAP.get(label.lower(), _slugify(label)) for label in header_labels
    ]

    out: list[dict] = []
    for row_idx in sorted(collected.keys(), key=lambda k: int(k)):
        cell_map = collected[row_idx]
        record: dict = {}
        for col_idx_str, text in cell_map.items():
            col_idx = int(col_idx_str)
            if col_idx == 0 or col_idx >= len(field_names):
                # Column 0 ("Detail") is an action button, not data - see
                # module docstring.
                continue
            field = field_names[col_idx]
            if text:
                record[field] = text
        if record.get("case_no") or record.get("parcel"):
            record["county"] = COUNTY
            record["source"] = "laft"
            record["url_auction"] = BASE_URL
            out.append(record)

    # Loud (non-fatal) mismatch check against the grid's own reported total
    # - same discipline as Pioneer's jqGrid pagination-footer check. See
    # module docstring.
    m = FOOTER_COUNT_RE.search(footer_text or "")
    if m and int(m.group(1)) > len(out):
        print(
            f"    WARNING: grid footer reports {m.group(1)} total records but only "
            f"{len(out)} were collected via scroll - possible virtualization/scroll "
            f"issue not fully handled",
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
    print(f"Harvested {len(rows)} LAFT properties total (Osceola County)")
    print("=" * 50)
    print(f"Saved: {OUT_JSON}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
