#!/usr/bin/env python3
"""TaxSys (Grant Street's county-taxes.com) county-held certificate reports:
one value-free reachability read (2026-10-26).

WHY

LienHub refuses the GitHub runners (HTTP 403 since 2026-10-01; never worked
around). Two LienHub counties point at another place for their county-held
list: St. Lucie's Tax Collector names the TaxSys "public access system" report
"All County Held Certs", and Hillsborough links TaxSys "tax sale reports"
(`<county>.county-taxes.com/public/reports/real_estate`). TaxSys is operated by
Grant Street Group, LienHub's vendor. The owner decided on 2026-10-26 to try ONE
value-free read; a refusal (HTTP 403 or any other block) is final and is never
worked around: no other address, no proxy, no browser automation, no retry.

PERMISSION

`fl_taxsys_county_held` discover / fetch / parse records in
data/source_permissions.csv - the owner's interim risk acceptance (2026-10-26,
expiring 2027-04-12), not the vendor's or a county's permission. Checked before
any request; a denial exits 3 with zero requests.

WHAT IT PRINTS (and nothing else)

Per county: the HTTP status, the server header name, the final host, the page
title with digits masked, whether the words "county held" appear, and how many
report options mention them. Never a row, an account, an amount or a name.

    harvest_taxsys_certificates.py --check [--county SLUG ...]
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import laft_status as LS  # noqa: E402

SOURCE_ID = "fl_taxsys_county_held"
DATASET = "county_held_certificates"
UA = "taxdeed-scraper/1.0 (+https://github.com/rodzmodzllc-max/taxdeed-scraper)"
# County -> TaxSys subdomain. Only the two counties whose own Tax Collector page
# points at TaxSys for county-held certificates (docs/review/fl-certificate-sources-2026-10-26.md).
COUNTIES = {"Hillsborough": "hillsborough", "St. Lucie": "stlucie"}
REPORTS_PATH = "/public/reports/real_estate"
COUNTY_HELD = re.compile(r"county[\s-]*held", re.I)


def masked(text: str) -> str:
    return re.sub(r"\d", "#", re.sub(r"\s+", " ", text or "")).strip()[:90]


def summarize(status: int, headers: dict, final_url: str, body: str) -> dict:
    title = re.search(r"<title[^>]*>(.*?)</title>", body or "", re.I | re.S)
    options = re.findall(r"<option[^>]*>(.*?)</option>", body or "", re.I | re.S)
    return {
        "http_status": status,
        "server": (headers.get("server") or headers.get("Server") or "")[:40],
        "final_host": urlsplit(final_url).hostname or "",
        "title": masked(title.group(1)) if title else "",
        "mentions_county_held": bool(COUNTY_HELD.search(body or "")),
        "county_held_report_options": sum(1 for o in options if COUNTY_HELD.search(o)),
        "blocked": status in (401, 403, 429) or "access denied" in (body or "").lower()[:4000],
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true", required=True, help="the one value-free reachability read")
    ap.add_argument("--county", action="append", help="limit to these counties (names as in COUNTIES)")
    a = ap.parse_args(argv)
    counties = [c for c in COUNTIES if not a.county or c in a.county]
    for county in counties:
        for op in ("discover", "fetch", "parse"):
            # Source "fl_taxsys_county_held" (named here for the interim-permission call-site inventory).
            d = LS.permission(SOURCE_ID, op, state="FL", county=county, dataset=DATASET)
            if not d.allowed:
                print(f"::error title={SOURCE_ID}::{op} denied for {county} [{d.reason_code}] - 0 requests made", flush=True)
                return LS.PERMISSION_DENIED_EXIT
    import requests
    for county in counties:
        url = f"https://{COUNTIES[county]}.county-taxes.com{REPORTS_PATH}"
        try:
            r = requests.get(url, headers={"User-Agent": UA}, timeout=30, allow_redirects=True)
            s = summarize(r.status_code, dict(r.headers), r.url, r.text if "html" in r.headers.get("content-type", "") else "")
        except Exception as exc:  # noqa: BLE001 - one attempt only, never retried
            cat, detail = LS.describe_exception(exc)
            print(f"TAXSYS {county}: transport failure {cat} ({detail}) - stopped, not retried")
            continue
        verdict = "BLOCKED - stop, recorded, never worked around" if s["blocked"] else "served"
        print(f"TAXSYS {county}: HTTP {s['http_status']} server={s['server']!r} host={s['final_host']} title={s['title']!r} "
              f"county_held_mentioned={s['mentions_county_held']} county_held_report_options={s['county_held_report_options']} -> {verdict}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
