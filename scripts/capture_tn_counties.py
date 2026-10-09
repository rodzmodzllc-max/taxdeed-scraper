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
C.OFFICIAL_HOSTS = C.OFFICIAL_HOSTS + ("nashville.gov", "hamiltontn.gov", "padctn.org",
                                       "montgomerytn.gov", "mcgtn.org", "rcchancery.com", "rutherfordcountytn.gov",
                                       "knoxcounty.org", "knoxcountytrustee.org", "blounttn.gov", "campbellcountytn.gov")
C.SAFE_WORDS = C.SAFE_WORDS | frozenset("""
acct appraisal assessed assessment balance bidding block case cases chancery civil control davidson district docket
group hamilton id item judgment montgomery rutherford knox knoxville clarksville murfreesboro trustee results
surplus blount campbell maryville jacksboro list updated lien map nashville no number opened opening parcel pin real rpo sealed sold subdivision
tract value ward amount due assessor
""".split())

DAVIDSON_HAMILTON = [
    ("davidson", "cm_tax_schedule", "https://chanceryclerkandmaster.nashville.gov/fees/property-tax-schedule/"),
    ("hamilton", "rpo_home", "https://hamiltontn.gov/Department_RealPropertyOffice.aspx"),
    ("hamilton", "rpo_sold_list", "https://www.hamiltontn.gov/pdf/RealProperty/2025sale/March/Sold-Property-List.pdf"),
    ("hamilton", "cm_tax_sale_notice",
     "https://www.hamiltontn.gov/Clerkmasterforms/taxsale/2026TaxSale/TAX%20SALE%20INFORMATION%202026.pdf"),
]
# Tennessee step 3 (2026-10-09): Montgomery, Rutherford, Knox (docs/tennessee-survey.md).
MONTGOMERY_RUTHERFORD_KNOX = [
    ("montgomery", "cm_tax_sale", "https://montgomerytn.gov/chancery/tax-sale"),
    ("montgomery", "cm_tax_sale_www", "https://www.montgomerytn.gov/chancery/tax-sale"),
    ("montgomery", "mcgtn_chancery", "https://mcgtn.org/chancery"),
    ("rutherford", "cm_delinquent_sales", "https://rcchancery.com/delinquent_sales"),
    ("knox", "trustee_tax_sale", "https://www.knoxcounty.org/trustee/tax_sale_info.php"),
]
# County sites behind a WAF refuse a bot User-Agent (Montgomery answered 403
# on 2026-10-09); the same browser User-Agent the harvesters and the purchase
# evidence capture use. Read-only GETs either way.
C.UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36")
PRIORITY = re.compile(r"(tax.?sale|taxsale|results|delinquent|surplus|sold)", re.I)
# Tennessee step 4 (2026-10-09): the two counties the survey found posting a
# list ahead of the sale.
BLOUNT_CAMPBELL = [
    ("blount", "delinquent_tax_sale", "https://blounttn.gov/2029/Delinquent-Property-Tax-Sale"),
    ("blount", "procedures_2026", "https://www.blounttn.gov/DocumentCenter/View/26595/2026-Delinquent-Tax-Procedures-PDF"),
    ("campbell", "home", "https://campbellcountytn.gov/"),
    ("campbell", "site_search", "https://campbellcountytn.gov/?s=tax+sale"),
    ("campbell", "wp_media", "https://campbellcountytn.gov/wp-json/wp/v2/media?search=tax%20sale&per_page=50"
                             "&_fields=source_url,mime_type,date"),
    ("campbell", "tax_sale_list",
     "https://campbellcountytn.gov/wp-content/uploads/2024/10/2023-DT-Tax-Sale-List-updated-04-14-26-@11.pdf"),
]
PAGE_SETS = {"davidson_hamilton": DAVIDSON_HAMILTON, "montgomery_rutherford_knox": MONTGOMERY_RUTHERFORD_KNOX,
             "blount_campbell": BLOUNT_CAMPBELL}
PAGES = DAVIDSON_HAMILTON
FOLLOW = re.compile(r"(\.pdf$|\.xlsx?$|\.csv$|tax.?sale|delinquent|surplus|sealed|bid|property.?list|real.?property|"
                    r"results|sold|search)", re.I)
MAX_FOLLOW = 16


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


SKIP_HOSTS = ("facebook.com", "twitter.com", "x.com", "instagram.com", "youtube.com", "linkedin.com", "google.com",
              "govease.com")          # GovEase: a vendor this project does not implement - never followed


def all_links(html: str, base: str) -> list[dict]:
    """Every link on the page INCLUDING those inside tables (the Shelby
    helper drops tables before collecting links) and on any host. Link text
    only through the whitelist; the href is a public URL."""
    from bs4 import BeautifulSoup
    out, seen = [], set()
    for a in BeautifulSoup(html, "html.parser").find_all("a", href=True):
        href = urljoin(base, a["href"]).split("#")[0]
        host = (C.urlsplit(href).hostname or "").lower()
        if not href.startswith(("http://", "https://")) or href in seen or any(host.endswith(h) for h in SKIP_HOSTS):
            continue
        seen.add(href)
        out.append({"href": href, "text": C.safe_text(a.get_text(" ", strip=True)), "official": C.official(href),
                    "in_table": a.find_parent("table") is not None})
    return out[:150]


def entry(session, county: str, kind: str, url: str) -> dict:
    e = C.page_entry(session, kind, url)
    e["county"] = county
    if "/wp-json/wp/v2/media" in url and e.get("status") == 200:
        # A WordPress media index: public document URLs, their type and date only.
        r, _ = C.fetch(session, url)
        try:
            e["media"] = [{"url": m.get("source_url"), "mime": m.get("mime_type"), "date": (m.get("date") or "")[:10]}
                          for m in (r.json() if r is not None else [])][:50]
        except (ValueError, AttributeError):
            e["media_error"] = "not a media list"
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
            e["all_links"] = all_links(r.text, r.url)
            e["forms"] = forms(r.text, r.url)
    return e


def forms(html: str, base: str) -> list[dict]:
    """A search form's action, method and FIELD NAMES (never a value)."""
    from bs4 import BeautifulSoup
    out = []
    for f in BeautifulSoup(html, "html.parser").find_all("form")[:6]:
        names = [i.get("name") for i in f.find_all(["input", "select", "textarea"]) if i.get("name")]
        out.append({"action": urljoin(base, f.get("action") or ""), "method": (f.get("method") or "get").lower(),
                    "fields": [n for n in names if not n.startswith("__")][:30]})
    return out


APP_ID = re.compile(r"(?:webappviewer/index\.html\?id=|experience/|[?&](?:appid|webmap|id)=)([0-9a-f]{32})", re.I)
ITEM_DATA = "https://www.arcgis.com/sharing/rest/content/items/{}/data?f=json"
ITEM_META = "https://www.arcgis.com/sharing/rest/content/items/{}?f=json"
MAX_APP_LAYERS = 12


def _webmap_ids(data) -> set[str]:
    """Web-map item ids named anywhere inside an app's JSON (Web AppBuilder
    puts it under map.itemId, Experience Builder under dataSources)."""
    found = set()
    if isinstance(data, dict):
        for k, v in data.items():
            if k in ("itemId", "webmap") and isinstance(v, str) and re.fullmatch(r"[0-9a-f]{32}", v):
                found.add(v)
            found |= _webmap_ids(v)
    elif isinstance(data, list):
        for v in data:
            found |= _webmap_ids(v)
    return found


def arcgis_apps(session, endpoints) -> list[dict]:
    """An embedded ArcGIS app -> its web map(s) -> operational layers: title
    (digits masked), URL, field names / types and a record COUNT. No row."""
    out, seen_layers = [], set()
    for app_id in sorted({m for e in endpoints for m in APP_ID.findall(e)}):
        entry = {"app": app_id, "webmaps": []}
        r, err = C.fetch(session, ITEM_DATA.format(app_id))
        try:
            data = r.json() if r is not None and r.status_code == 200 else {}
        except ValueError:
            data = {}
        maps = _webmap_ids(data) - {app_id}
        meta, _ = C.fetch(session, ITEM_META.format(app_id))
        try:
            if meta is not None and meta.json().get("type") == "Web Map":
                maps.add(app_id)
        except ValueError:
            pass
        for mid in sorted(maps)[:4]:
            w, _ = C.fetch(session, ITEM_DATA.format(mid))
            try:
                wm = w.json() if w is not None and w.status_code == 200 else {}
            except ValueError:
                wm = {}
            layers = []
            for lyr in (wm.get("operationalLayers") or [])[:30]:
                url = lyr.get("url") or ""
                title = C.mask(str(lyr.get("title") or ""))[:80]
                info = {"title": title, "url": url}
                if url and url not in seen_layers and len(seen_layers) < MAX_APP_LAYERS:
                    seen_layers.add(url)
                    info["layer"] = C.layer_entry(session, url)
                    time.sleep(0.3)
                layers.append(info)
            entry["webmaps"].append({"id": mid, "layers": layers})
        out.append(entry)
        time.sleep(0.4)
    return out


def capture(pages=None) -> dict:
    pages = pages or PAGES
    import requests
    session = requests.Session()
    report = {"generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(), "pages": []}
    seen = set()
    for county, kind, url in pages:
        e = entry(session, county, kind, url)
        report["pages"].append(e)
        seen.add(url)
        print(f"  {county:<9} {kind:<22} {e.get('status', e.get('error'))}", flush=True)
        time.sleep(0.6)
    followed = 0
    i = 0
    while i < len(report["pages"]):             # pages reached by following are followed too
        p = report["pages"][i]
        i += 1
        for link in sorted(p.get("all_links") or [], key=lambda l: not PRIORITY.search(l["href"])):
            href = link["href"]
            if followed >= MAX_FOLLOW or href in seen or not link["official"] or not FOLLOW.search(href):
                continue
            seen.add(href)
            followed += 1
            e = entry(session, p["county"], f"linked_from_{p['kind']}", href)
            report["pages"].append(e)
            print(f"  {p['county']:<9} follow {href} -> {e.get('status', e.get('error'))}", flush=True)
            time.sleep(0.6)
    endpoints = {ep for p in report["pages"] for ep in ((p.get("html") or {}).get("endpoints") or [])}
    report["arcgis_apps"] = arcgis_apps(session, endpoints)
    return report


def digest(report: dict) -> str:
    out = [f"Tennessee county structure capture ({report.get('set', 'davidson_hamilton')}) {report.get('generated_at')}"]
    for p in report["pages"]:
        out.append(C.digest({"pages": [p]}).split("\n", 1)[1])
        for t in p.get("pdf_tables") or []:
            out.append(f"  pdf table header rows: {t}")
        for l in p.get("all_links") or []:
            if l["in_table"] or not l["official"] or FOLLOW.search(l["href"]):
                out.append(f"  any-link{' [table]' if l['in_table'] else ''}{'' if l['official'] else ' [external]'}: "
                           f"{l['text']} -> {l['href']}")
        for m in p.get("media") or []:
            out.append(f"  media {m['date']} {m['mime']} {m['url']}")
        for f in p.get("forms") or []:
            out.append(f"  form {f['method'].upper()} {f['action']} fields={f['fields']}")
        for t in p.get("html_tables") or []:
            out.append(f"  html table id={t['id']} rows={t['rows']} headers={t['headers']}")
    for a in report.get("arcgis_apps") or []:
        out.append(f"\n[arcgis app] {a['app']}")
        for w in a["webmaps"]:
            out.append(f"  webmap {w['id']}")
            for l in w["layers"]:
                lay = l.get("layer") or {}
                out.append(f"    layer '{l['title']}' {l['url']} name={lay.get('name')} geom={lay.get('geometry_type')} "
                           f"count={lay.get('count')} err={lay.get('error')}")
                if lay.get("fields"):
                    out.append("      fields: " + ", ".join(f"{n}:{t}" for n, t in lay["fields"]))
                if lay.get("sublayers"):
                    out.append("      sublayers: " + ", ".join(f"{i}:{n}" for i, n in lay["sublayers"]))
    return "\n".join(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--digest")
    ap.add_argument("--out", default=str(OUT_PATH))
    ap.add_argument("--set", default="davidson_hamilton", choices=sorted(PAGE_SETS))
    a = ap.parse_args(argv)
    if a.digest:
        print(digest(json.loads(Path(a.digest).read_text(encoding="utf-8"))))
        return 0
    report = capture(PAGE_SETS[a.set])
    report["set"] = a.set
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(digest(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
