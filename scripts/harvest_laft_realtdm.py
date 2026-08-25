#!/usr/bin/env python3
"""
Harvest "Lands Available for Taxes" (LAFT) listings from counties on the
RealTDM platform (realtdm.com) - a shared, multi-tenant case-management
system used by a cluster of Florida county Clerks (confirmed live 2026-08:
Alachua, Highlands, Lee, Sarasota, Flagler, Santa Rosa, Washington - see
../data/laft_realtdm_counties.csv). Different from harvest_all_counties.ps1's
RealForeclose/Realauction auction platform and from harvest_laft_html.py's
plain static-table counties - this is a third, distinct vendor.

RealTDM LOOKS like a JS search-form portal (confirmed via browser: dropdown
selection triggers no visible network activity until you click "Process
Search"), but turns out to be a plain HTML <form method="post"> - the
"Process Search" click just submits a normal form POST back to the same
URL and the server re-renders the page with results baked into the HTML.
No JavaScript execution or session/cookie dance is required - `requests`
alone reproduces it. Confirmed live via the browser's network panel on
Alachua and Highlands before writing this script.

Two real requests per county, no more:
1. GET the list page. Each tenant assigns its OWN numeric ID to each case
status (confirmed: Alachua's "List of Lands - Available For Public" is
status 1171; Highlands' is 1857 - NOT a shared enum across tenants),
but the status LABEL TEXT is identical across tenants (same vendor
template) - the ID is embedded in the page as
`<a data-status-id="NNNN">List of Lands - Available For Public</a>`,
so it's looked up per county rather than hardcoded.
2. POST the same URL with `filtercasestatus=<that ID>` and the rest of
the form's fields empty/default. The response HTML contains the
result cards directly - no separate AJAX/JSON call to chase down.

A few RealTDM subdomains that LOOK like real tenants from search results
turn out to be unconfigured placeholders - confirmed live: osceola.realtdm.com
and nassau.realtdm.com both render as clerk name "TEST" instead of a real
county name. Treated as a hard signal to skip that tenant entirely rather
than harvest garbage - see _is_placeholder_tenant().

Known gap: the case-list view (what this script reads) does not surface a
purchase price/bid or a street address at all - only case #, parcel #, and
sale date. Getting the price would mean a THIRD request per case (the
"cases/details" endpoint, one call per property rather than per county) -
deliberately not built yet given the fan-out cost; `bid` is left absent and
sync-laft-to-supabase.ps1 already defaults it to 0 (same as any other
county with no published price), and `address` falls back to "Parcel X"
via that same script's existing fallback chain.

Output: harvest_laft_realtdm.json / .csv - kept separate from the PDF and
plain-HTML harvesters' outputs. sync-laft-to-supabase.ps1 merges all three.
"""
from __future__ import annotations

import csv
import json
import re
import sys
from datetime import datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup

HERE = Path(__file__).resolve().parent
SOURCES_CSV = HERE / "../data/laft_realtdm_counties.csv"
OUT_DIR = HERE / "../out"
OUT_JSON = OUT_DIR / "harvest_laft_realtdm.json"
OUT_CSV = OUT_DIR / "harvest_laft_realtdm.csv"

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

# Different RealTDM tenants word this status differently even though it's
# the same status semantically. Confirmed live 2026-08: Alachua's and
# Highlands' tenants use the full "List of Lands - Available For Public",
# but Flagler's and Santa Rosa's tenants use the shorter "List of Lands"
# for what is otherwise the identical status - checked directly on each
# tenant's own /public/cases/list page via its data-status-id links.
# Before this fix, Flagler and Santa Rosa ERRORed on every single run
# ("status ... not found on this tenant") - not because they have no LAFT
# list, but because the exact-string match only ever tried the long
# variant. Tried in order, first match wins; exact string match (not a
# substring/contains check) so this can't accidentally match some other,
# unrelated status on a tenant that happens to contain "List of Lands" as
# a fragment of a longer label.
STATUS_LABELS = ("List of Lands - Available For Public", "List of Lands")

# .search + rest-of-string capture, not \S+ - confirmed live some counties'
# case numbers contain a space (Alachua: "TD 2025-003"), others don't
# (Highlands: "25000019") - \S+ would silently truncate the former at the
# first space.
CASE_NO_RE = re.compile(r"CASE #(.+)")

# RealTDM's own date format ("Oct 21, 2025") isn't one
# sync-laft-to-supabase.ps1's ConvertTo-IsoDate knows how to parse (it only
# tries MM/dd/yyyy, M/d/yyyy, yyyy-MM-dd) - converted here at harvest time
# instead of teaching the PowerShell side a fourth format, so every
# harvester keeps writing the same date shape.
def _reformat_date(s: str) -> str | None:
    s = (s or "").strip()
    if not s:
        return None
    try:
        return datetime.strptime(s, "%b %d, %Y").strftime("%m/%d/%Y")
    except ValueError:
        return s or None  # pass through unrecognized shapes rather than drop the data

def _is_placeholder_tenant(soup: BeautifulSoup) -> bool:
    """Confirmed live: osceola.realtdm.com and nassau.realtdm.com both exist
    as DNS/routes but were never configured for that county - the page
    renders clerk name "TEST" instead of a real county name. A subdomain
    guess that lands on one of these would otherwise harvest nothing
    silently (0 results looks identical to "no properties right now") -
    this makes it a loud skip instead."""
    header = soup.find(string=re.compile(r"\bTEST\b"))
    return header is not None and soup.title is not None and "TEST" in soup.title.get_text()

def _find_status_id(soup: BeautifulSoup, labels: tuple[str, ...]) -> tuple[str, str] | None:
    """Return (status_id, matched_label) for the first of `labels` found on
    this tenant's page, or None if none of them are present. Exact text
    match against each `<a data-status-id="...">` link's text, tried in
    the order given in `labels` - see the STATUS_LABELS comment for why
    more than one variant needs to be tried."""
    for a in soup.find_all("a", attrs={"data-status-id": True}):
        text = a.get_text(strip=True)
        if text in labels:
            return a["data-status-id"], text
    return None

def _parse_cases(html: bytes, county: str, source_url: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    cards = soup.select(".content-box.load-case")
    out: list[dict] = []
    for card in cards:
        case_el = card.select_one(".fs-5")
        case_text = case_el.get_text(strip=True) if case_el else ""
        m = CASE_NO_RE.search(case_text)
        if not m:
            continue
        record: dict = {"county": county, "source": "laft", "url_auction": source_url, "case_no": m.group(1)}
        for row in card.select(".data-row"):
            label_el = row.select_one(".data-label")
            value_el = row.select_one(".data-value")
            if not label_el or not value_el:
                continue
            label = label_el.get_text(strip=True).lower()
            value = value_el.get_text(strip=True)
            if not value or value.upper() == "N/A":
                continue
            if label == "parcel number":
                record["parcel"] = value
            elif label == "sale date":
                d = _reformat_date(value)
                if d:
                    record["sale_date"] = d
            # "Date Created" and "Surplus Balance" are real fields on the
            # card but not ones sync-laft-to-supabase.ps1 reads - skipped
            # rather than mapped to something misleading (Surplus Balance
            # in particular is NOT the LAFT purchase price - a different
            # figure entirely, almost always $0.00 for a LAFT case - do not
            # ever map it to `bid`).
        if record.get("case_no") or record.get("parcel"):
            out.append(record)
    return out

def harvest_county(session: requests.Session, county: str, subdomain: str) -> list[dict]:
    url = f"https://{subdomain}.realtdm.com/public/cases/list"
    resp = session.get(url, headers={"User-Agent": UA}, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.content, "html.parser")

    if _is_placeholder_tenant(soup):
        raise RuntimeError(f"{subdomain}.realtdm.com is an unconfigured placeholder tenant (renders as \"TEST\") - not a real county instance")

    found = _find_status_id(soup, STATUS_LABELS)
    if not found:
        raise RuntimeError(f'none of the known "List of Lands" status labels {STATUS_LABELS!r} were found on this tenant - label wording may differ here')
    status_id, matched_label = found
    if matched_label != STATUS_LABELS[0]:
        print(f" (matched alternate label {matched_label!r})", flush=True)

    form_data = {
        "filterPageNumber": "1",
        "filterFiltered": "1",
        "sectionRouteCode": "",
        "isPublic": "1",
        "filtercasestatus": status_id,
        "filterPartyName": "",
        "filterCaseNumber": "",
        "filterParcelNumber": "",
        "filterAppNumber": "",
        "filterCertNumber": "",
        "filterPropAddress": "",
        "filterSaleDateStart": "",
        "filterSaleDateStop": "",
        "filterBalanceType": "",
        # Confirmed default is 20/page - set high enough that a LAFT-sized
        # result set (single digits to low dozens, per every county checked
        # so far) never needs real pagination handling.
        "filterCasesPerPage": "500",
    }
    resp = session.post(url, data=form_data, headers={"User-Agent": UA}, timeout=30)
    resp.raise_for_status()
    return _parse_cases(resp.content, county, url)

def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(SOURCES_CSV, newline="", encoding="utf-8") as f:
        sources = list(csv.DictReader(f))

    all_rows: list[dict] = []
    for i, src in enumerate(sources, 1):
        county, subdomain = src["County"], src["Subdomain"]
        print(f"[{i}/{len(sources)}] {county}", flush=True)
        try:
            session = requests.Session()
            rows = harvest_county(session, county, subdomain)
            if rows:
                print(f"  {len(rows)} properties", flush=True)
                all_rows.extend(rows)
            else:
                print("  no properties currently listed", flush=True)
        except Exception as exc:  # noqa: BLE001 - one bad county must not kill the whole run
            print(f"  ERROR: {exc}", flush=True)

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
