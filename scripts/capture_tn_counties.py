#!/usr/bin/env python3
"""Read-only STRUCTURAL capture of the Davidson and Hamilton County,
Tennessee candidate sources (2026-10-09, Tennessee build order step 2;
docs/tennessee-survey.md):

  * Davidson - Chancery Court Clerk & Master tax-sale schedule page and the
    per-sale PDF lists it links;
  * Hamilton - Real Property Office (county-held parcels sold by sealed bid,
    with sold lists) and the Clerk & Master's annual tax-sale notice.

Same rules as scripts/capture_tn_shelby.py, whose helpers it reuses: it runs
only as the manual evidence job (`job=evidence`,
`evidence_scope=tn_davidson_hamilton`), no database credential reaches it,
and it prints / writes (out/public/tn-counties-structure.json) only
  * titles, HTTP status, content type, Last-Modified, official link HREFs;
  * headings, link text, PDF lines and TABLE HEADER CELLS only when every
    word is in the whitelist (an owner name, a street or a legal description
    can never pass), digits masked to 9 except years;
  * PDF page / line counts, identifier SHAPES, keyword counts.
Never a row, a name, an address, a parcel number or an amount.
tests/python/test_capture_tn_counties.py proves it with synthetic PII.

    python3 scripts/capture_tn_counties.py
    python3 scripts/capture_tn_counties.py --digest out/public/tn-counties-structure.json
"""
from __future__ import annotations

import argparse
import io
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import capture_tn_shelby as C  # noqa: E402

OUT_PATH = C.REPO / "out" / "public" / "tn-counties-structure.json"
C.OFFICIAL_HOSTS = C.OFFICIAL_HOSTS + ("nashville.gov", "hamiltontn.gov", "padctn.org")
C.SAFE_WORDS = C.SAFE_WORDS | frozenset("""
acct appraisal assessed assessment balance bidding block case cases chancery civil control davidson district docket
group hamilton id item judgment lien map nashville no number opened opening parcel pin real rpo sealed sold subdivision
tract value ward amount due assessor
""".split())

PAGES = [
    ("davidson", "cm_tax_schedule", "https://chanceryclerkandmaster.nashville.gov/fees/property-tax-schedule/"),
    ("hamilton", "rpo_home", "https://hamiltontn.gov/Department_RealPropertyOffice.aspx"),
    ("hamilton", "rpo_sold_list", "https://www.hamiltontn.gov/pdf/RealProperty/2025sale/March/Sold-Property-List.pdf"),
    ("hamilton", "cm_tax_sale_notice",
     "https://www.hamiltontn.gov/Clerkmasterforms/taxsale/2026TaxSale/TAX%20SALE%20INFORMATION%202026.pdf"),
]
FOLLOW = re.compile(r"(\.pdf$|\.xlsx?$|\.csv$|tax.?sale|delinquent|surplus|sealed|bid|property.?list|real.?property)", re.I)
MAX_FOLLOW = 8


def table_headers(rows: list[list]) -> list[list[str]]:
    """The first two rows of an extracted table, each cell through the
    whitelist (a data row's cells are withheld, never printed)."""
    return [[C.safe_text(str(c or "")) for c in row] for row in rows[:2]]


def html_tables(html: str) -> list[dict]:
    from bs4 import BeautifulSoup
    out = []
    for t in BeautifulSoup(html, "html.parser").find_all("table")[:6]:
        heads = [C.safe_text(th.get_text(" ")) for th in t.find_all("th")][:30]
        out.append({"id": t.get("id"), "rows": len(t.find_all("tr")), "headers": heads})
    return out


def entry(session, county: str, kind: str, url: str) -> dict:
    e = C.page_entry(session, kind, url)
    e["county"] = county
    if e.get("pdf"):
        r, _ = C.fetch(session, url)
        if r is not None and r.status_code == 200:
            try:
                import pdfplumber
                with pdfplumber.open(io.BytesIO(r.content)) as pdf:
                    tabs = []
                    for p in pdf.pages[:3]:
                        tabs += [table_headers(t) for t in (p.extract_tables() or [])]
                    e["pdf_tables"] = tabs[:6]
            except Exception as ex:  # noqa: BLE001
                e["pdf_table_error"] = type(ex).__name__
    elif e.get("html"):
        r, _ = C.fetch(session, url)
        if r is not None and r.status_code == 200:
            e["html_tables"] = html_tables(r.text)
    return e


def capture() -> dict:
    import requests
    session = requests.Session()
    report = {"generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(), "pages": []}
    seen = set()
    for county, kind, url in PAGES:
        e = entry(session, county, kind, url)
        report["pages"].append(e)
        seen.add(url)
        print(f"  {county:<9} {kind:<22} {e.get('status', e.get('error'))}", flush=True)
        time.sleep(0.6)
    followed = 0
    for p in list(report["pages"]):
        for link in (p.get("html") or {}).get("links", []):
            href = link["href"].split("#")[0]
            if followed >= MAX_FOLLOW or href in seen or not FOLLOW.search(href):
                continue
            seen.add(href)
            followed += 1
            e = entry(session, p["county"], f"linked_from_{p['kind']}", href)
            report["pages"].append(e)
            print(f"  {p['county']:<9} follow {href} -> {e.get('status', e.get('error'))}", flush=True)
            time.sleep(0.6)
    return report


def digest(report: dict) -> str:
    out = [f"Davidson / Hamilton TN structure capture {report.get('generated_at')}"]
    for p in report["pages"]:
        out.append(C.digest({"pages": [p]}).split("\n", 1)[1])
        for t in p.get("pdf_tables") or []:
            out.append(f"  pdf table header rows: {t}")
        for t in p.get("html_tables") or []:
            out.append(f"  html table id={t['id']} rows={t['rows']} headers={t['headers']}")
    return "\n".join(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--digest")
    ap.add_argument("--out", default=str(OUT_PATH))
    a = ap.parse_args(argv)
    if a.digest:
        print(digest(json.loads(Path(a.digest).read_text(encoding="utf-8"))))
        return 0
    report = capture()
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(digest(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
