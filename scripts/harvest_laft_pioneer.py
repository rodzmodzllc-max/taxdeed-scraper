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

Confirmed live via the browser on both counties above: the search UI is a
tabbed ASP.NET-rendered page (jQuery + jqGrid, NOT Blazor/SignalR - no
websocket, a plain server-rendered HTML response). There is no CSRF/anti-
forgery hidden field on either confirmed county's form. The "Lands
Available" tab's submit button is a plain <button type="submit"
name="buttonSubmitLandsAvailable"> with an empty value, inside a single
<form method="post"> whose action is the county's base URL (sometimes with
a trailing slash added by the server). Submitting the form with every
other field left at its default/empty value reproduces exactly what a
real user gets by loading the page and clicking straight to "Search for
Lands Available" with no filters - confirmed via the browser's native
click + full-page-navigation on both counties (Citrus returned 5 real
properties, Okeechobee genuinely returned 0).

IMPORTANT caveat, not yet fully resolved: reproducing this same POST via
the browser's fetch() API (same-origin, same form data, same cookies)
did NOT return the results grid - it silently re-rendered the blank
search form instead, even though the real click-triggered navigation
worked every time. The likely explanation is a page-level CSP or
Referrer-Policy restriction that constrains in-browser fetch() but has no
bearing on a standalone HTTP client - `requests` here is not a browser and
isn't subject to that page's CSP, so it should behave like the successful
native-navigation case rather than the failed fetch() case. This has NOT
been independently verified against the live sites from outside a
browser (this sandbox's network egress can't reach arbitrary external
domains either) - if a production run of this script keeps coming back
empty for a county confirmed to have live properties, that mismatch
theory is the first thing to revisit (next step would be adding a
Playwright-based fallback that drives a real headless browser click
instead of a raw POST, at the cost of a much heavier CI job).

Zero-results counties (Okeechobee) render NO grid/table at all and no
"Results for Lands Available Search" heading - this is indistinguishable
in the HTML from "the search silently failed", which is exactly why the
fetch()-vs-navigation mismatch above matters: a false "0 results" is a
silent failure mode this script cannot currently tell apart from a real
zero, beyond logging it clearly so a human can sanity-check a suspicious
run.

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
case worth flagging rather than a routine case worth the complexity of a
second per-county request.

Output: harvest_laft_pioneer.json / .csv - kept separate from the other
three harvesters' outputs. sync-laft-to-supabase.ps1 merges all four.
"""
from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path

import requests
from bs4 import BeautifulSoup

HERE = Path(__file__).resolve().parent
SOURCES_CSV = HERE / "../data/laft_pioneer_counties.csv"
OUT_DIR = HERE / "../out"
OUT_JSON = OUT_DIR / "harvest_laft_pioneer.json"
OUT_CSV = OUT_DIR / "harvest_laft_pioneer.csv"

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

SEARCH_BUTTON_NAME = "buttonSubmitLandsAvailable"

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


def _serialize_form(form, base_url: str) -> tuple[str, dict[str, str]]:
    """Reproduce jQuery's $(form).serialize() closely enough for this
    vendor's forms: every named, non-disabled input/select/textarea at its
    current value. Submit buttons are excluded here (browsers only send the
    ONE button that was actually clicked) - the caller adds that one
    separately."""
    action = form.get("action") or base_url
    data: dict[str, str] = {}
    for el in form.find_all(["input", "select", "textarea"]):
        name = el.get("name")
        if not name or el.get("disabled") is not None:
            continue
        tag = el.name
        if tag == "input":
            itype = (el.get("type") or "text").lower()
            if itype in ("submit", "button", "reset", "image", "checkbox", "radio"):
                # Checkboxes/radios only serialize when checked; none of
                # this vendor's confirmed counties use them on the search
                # form, so unconditionally skipping keeps this simple
                # rather than guessing at a "checked" default.
                if itype in ("checkbox", "radio") and el.get("checked") is not None:
                    data[name] = el.get("value", "on")
                continue
            data[name] = el.get("value", "")
        elif tag == "textarea":
            data[name] = el.text or ""
        elif tag == "select":
            selected = el.find("option", selected=True)
            if selected is None:
                selected = el.find("option")
            data[name] = selected.get("value", selected.get_text(strip=True)) if selected else ""
    return action, data


def harvest_county(session: requests.Session, county: str, base_url: str) -> list[dict]:
    resp = session.get(base_url, headers={"User-Agent": UA}, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.content, "html.parser")

    form = soup.find("form")
    if form is None:
        raise RuntimeError("no <form> found on the search page - page structure may have changed")

    btn = form.find("button", attrs={"name": SEARCH_BUTTON_NAME})
    if btn is None:
        raise RuntimeError(f'no "{SEARCH_BUTTON_NAME}" submit button found - page structure may have changed')

    action, form_data = _serialize_form(form, base_url)
    form_data[SEARCH_BUTTON_NAME] = btn.get("value", "")

    if action.startswith("/"):
        from urllib.parse import urljoin
        action = urljoin(base_url, action)

    resp = session.post(
        action,
        data=form_data,
        headers={"User-Agent": UA, "Referer": base_url},
        timeout=30,
    )
    resp.raise_for_status()
    return _parse_results(resp.content, county, base_url)


def _parse_results(html: bytes, county: str, source_url: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", class_=lambda c: c and "ui-jqgrid-btable" in c.split())
    if table is None:
        # No grid at all is this platform's normal rendering for a true
        # zero-result search (confirmed live on Okeechobee) - not
        # necessarily an error, so this returns cleanly rather than
        # raising. See the fetch()-vs-navigation caveat in the module
        # docstring for the one thing that COULD make this a false zero.
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
    for i, src in enumerate(sources, 1):
        county, base_url = src["County"], src["BaseUrl"]
        print(f"[{i}/{len(sources)}] {county}", flush=True)
        try:
            session = requests.Session()
            rows = harvest_county(session, county, base_url)
            if rows:
                print(f"    {len(rows)} properties", flush=True)
                all_rows.extend(rows)
            else:
                print("    no properties currently listed", flush=True)
        except Exception as exc:  # noqa: BLE001 - one bad county must not kill the whole run
            print(f"    ERROR: {exc}", flush=True)

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
