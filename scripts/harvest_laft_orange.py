#!/usr/bin/env python3
"""
Harvest "Lands Available for Taxes" (LAFT) listings for Orange County from
the Orange County COMPTROLLER's own Tax Deed Sales Management search tool
("TDSM"), at or.occompt.com/recorder/tdsmweb/.

This is a fifth distinct LAFT source in this project - not the same vendor
as any of Pioneer/TaxSmartWeb, RealTDM, the plain-HTML-table counties, or
the PDF-published counties. It looks purpose-built for Orange County
specifically (the "Orange County Comptroller" is a separate elected office
from the Clerk of Courts in Orange County, FL, unlike every other county in
this project) - no other county has been found on this exact platform, so
unlike harvest_laft_pioneer.py / harvest_laft_realtdm.py / harvest_laft_html.py
this is NOT CSV-driven for multiple counties. If a second county ever turns
up on the same or.occompt.com-style TDSM platform, this should be
generalized the same way those were.

IMPORTANT CONTEXT (confirmed live 2026-08-25 via the browser): this
supersedes the original research pass's "Orange County's Esri ArcGIS
Hub/FeatureServer, flagged as possibly stale" candidate. That ArcGIS Hub
page exists and may still be useful for a map view, but the Comptroller's
own official LAFT page (occompt.com/158/Land-Available-For-Taxes) points
people at THIS search tool as the authoritative source ("To search for
properties on the list of Lands Available for Taxes, you will use the Tax
Deed Sale Search... select 'Lands Available' in the Status field") - not
the GIS map, which the same page describes as a supplementary visualization
("Properties on Lands Available for Taxes can be viewed on a map with the
GIS application"). Confirmed live with 3 real current Lands Available
properties (Tax Sale 2021-1975, 2020-8215, 2020-3877).

ACCESS PATTERN - a real disclaimer + guest access flow, NOT a login:
  1. GET  https://or.occompt.com/recorder/web/login.jsp
     A standard old JSP disclaimer page. It has TWO forms: a real
     username/password login form (never used here - see the project's
     standing "never enter credentials, never create accounts" rule) and a
     separate, genuinely public "I Acknowledge" form with a hidden
     `guest=true` field and no credential fields at all.
  2. POST https://or.occompt.com/recorder/web/loginPOST.jsp
     Body: {"submit": "I Acknowledge", "guest": "true"}
     This establishes an anonymous "public" guest session (confirmed live -
     the page header shows "Logout public" afterward, not a named user).
     No password, no account, nothing this project's credential rules would
     prohibit - it's the same as clicking an "I agree" button on a plain
     disclaimer page.
  3. POST https://or.occompt.com/recorder/tdsmweb/applicationSearchPost.jsp
     Body: the full SEARCH_FORM_DEFAULTS below, with DeedStatusID="LA".
     Confirmed live via the browser: this is a plain, server-rendered
     <form method="post"> (no jqGrid/AJAX/websocket anywhere on this
     platform, unlike Pioneer/TaxSmartWeb) - the browser test that
     confirmed this searched cleanly and landed on a normal new URL
     (.../applicationSearchResults.jsp?searchId=N), which is exactly the
     kind of real full-page form-POST navigation that (per the Pioneer
     lesson - see that harvester's module docstring) has reliably matched
     a plain `requests` reproduction on every OTHER LAFT vendor in this
     project. Unlike Pioneer, this is NOT expected to need a real browser -
     but per that same lesson, this has NOT yet been independently
     confirmed against a live, known-nonzero run in production (no network
     egress from the sandbox that wrote this script) - treat the first
     live run's count for Orange as the actual verification, the same
     discipline applied to every other new harvester in this project.
  4. `requests` follows the resulting redirect automatically (session
     cookies carry over within the same Session), landing on the results
     page.

Results page format: NOT a clean data table - a nested old-JSP table/card
layout, but with a completely consistent per-property TEXT pattern
regardless of the exact HTML structure around it:

    Tax Sale
    <case-like-id, e.g. 2021-1975>

    Sale Date: <MM/DD/YYYY>
    Applicant Name: <name>

    Status: Lands Available
    Parcel: <parcel id>

    Min Bid: $<amount>
    High Bid: $<amount>

Parsed with a single regex over the page's flattened text (BeautifulSoup's
get_text(" ", strip=True)) rather than trying to walk the nested table/DOM
structure - confirmed against the exact live text captured from the browser
for all 3 currently-listed properties, matching every field cleanly. This
mirrors the same "extract via labeled-field regex over flattened text"
approach already used for Putnam's card-style HTML table in
harvest_laft_html.py and for Marion's PDF in harvest_laft_pdfs.py, rather
than inventing a fourth parsing strategy.

Output: harvest_laft_orange.json / .csv - kept separate from every other
LAFT harvester's output. sync-laft-to-supabase.ps1 merges all of them.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import requests
from bs4 import BeautifulSoup

HERE = Path(__file__).resolve().parent
OUT_DIR = HERE / "../out"
OUT_JSON = OUT_DIR / "harvest_laft_orange.json"
OUT_CSV = OUT_DIR / "harvest_laft_orange.csv"

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

DISCLAIMER_URL = "https://or.occompt.com/recorder/web/login.jsp"
LOGIN_POST_URL = "https://or.occompt.com/recorder/web/loginPOST.jsp"
SEARCH_URL = "https://or.occompt.com/recorder/tdsmweb/applicationSearch.jsp"
SEARCH_POST_URL = "https://or.occompt.com/recorder/tdsmweb/applicationSearchPost.jsp"
SOURCE_PAGE_URL = "https://occompt.com/158/Land-Available-For-Taxes"

COUNTY = "Orange"

# Guest access, not a login - see module docstring. No credentials of any
# kind are sent; this is the same public "I Acknowledge" disclaimer flow
# every visitor to this site clicks through, confirmed live 2026-08-25.
GUEST_ACK_DATA = {"submit": "I Acknowledge", "guest": "true"}

# Every field the live search form actually has (confirmed live via the
# browser's DOM), sent with its default/blank value except DeedStatusID.
# PostgREST-style "every row needs the same keys" isn't a concern here, but
# some old JSP apps 500 on a genuinely missing form field rather than an
# empty one - safer to always send the full set.
SEARCH_FORM_DEFAULTS = {
    "AllPartiesIDSearchString": "",
    "AllPartiesIDSearchType": "Exact Match",
    "ApplicationNumIDSearchString": "",
    "ApplicationNumIDSearchType": "Exact Match",
    "DeedStatusID": "LA",  # "Lands Available" - confirmed live via the Status dropdown's <option value="LA">
    "SaleDateID": "",
    "ReceivedDateIDStart": "",
    "ReceivedDateIDEnd": "",
    "TaxDeedParcelIDSearchString": "",
    "TaxDeedParcelIDSearchType": "Exact Match",
    "CutoffDateIDStart": "",
    "CutoffDateIDEnd": "",
}

# Matches one property record in the results page's flattened text. See the
# module docstring for the exact live-confirmed text shape this is built
# from. \s+ (not \s*) between fields deliberately requires real separation,
# so this can't accidentally match across two unrelated snippets of body
# text that happen to contain "Sale Date:" and "Parcel:" close together
# outside of a real record.
RECORD_RE = re.compile(
    r"Tax Sale\s+([\w.\-/]+)\s+"
    r"Sale Date:\s*([\d/]+)\s+"
    r"Applicant Name:\s*(.+?)\s+"
    r"Status:\s*(.+?)\s+"
    r"Parcel:\s*(\S+)\s+"
    r"Min Bid:\s*\$?([\d,]+\.\d{2})\s+"
    r"High Bid:\s*\$?([\d,]+\.\d{2})",
)

NO_RESULTS_MARKERS = ("0 items found", "no items found", "no results found")


def harvest() -> list[dict]:
    session = requests.Session()
    session.headers.update({"User-Agent": UA})

    session.get(DISCLAIMER_URL, timeout=30).raise_for_status()
    session.post(LOGIN_POST_URL, data=GUEST_ACK_DATA, timeout=30).raise_for_status()
    # Load the search page itself first, matching real browser behavior
    # (and picking up any per-session state the JSP app sets on this GET) -
    # harmless if unnecessary, cheap insurance if it turns out to matter.
    session.get(SEARCH_URL, timeout=30).raise_for_status()

    resp = session.post(SEARCH_POST_URL, data=SEARCH_FORM_DEFAULTS, timeout=30)
    resp.raise_for_status()

    return _parse_results(resp.text)


def _parse_results(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(" ", strip=True)

    low = text.lower()
    if any(marker in low for marker in NO_RESULTS_MARKERS):
        return []

    out: list[dict] = []
    for case_no, sale_date, applicant, status, parcel, min_bid, high_bid in RECORD_RE.findall(text):
        if "lands available" not in status.strip().lower():
            # Defensive - DeedStatusID=LA should mean every result already
            # has this status, but never trust a filter param over what the
            # response itself actually says.
            continue
        out.append(
            {
                "county": COUNTY,
                "source": "laft",
                "url_auction": SOURCE_PAGE_URL,
                "case_no": case_no.strip(),
                "sale_date": sale_date.strip(),
                "applicant": applicant.strip(),
                "parcel": parcel.strip(),
                "bid": min_bid.strip(),
                "high_bid": high_bid.strip(),
            }
        )
    return out


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"[1/1] {COUNTY}", flush=True)
    try:
        rows = harvest()
        if rows:
            print(f"    {len(rows)} properties", flush=True)
        else:
            print("    no properties currently listed", flush=True)
    except Exception as exc:  # noqa: BLE001 - never let this crash the whole CI job
        print(f"    ERROR: {exc}", flush=True)
        rows = []

    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2)

    if rows:
        import csv

        fieldnames = sorted({k for row in rows for k in row.keys()})
        with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
    else:
        OUT_CSV.write_text("", encoding="utf-8")

    print("")
    print("=" * 50)
    print(f"Harvested {len(rows)} LAFT properties total (Orange County)")
    print("=" * 50)
    print(f"Saved: {OUT_JSON}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
