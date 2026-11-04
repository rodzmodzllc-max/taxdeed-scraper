#!/usr/bin/env python3
"""Value-free probe of the Florida / Texas county sources the 2026-10-26
county-source sprint could not read from the sandbox (Cloudflare challenges,
403s, TLS chains, an unreachable port). Manual only: `job=evidence`,
`evidence_scope=county_sources`. No database credential exists in that job and
nothing is written except the counts-only discovery report.

Every request goes through harvesters/governance/discovery_guard.py: a URL is
read only when the registry names its source and that source holds an
in-date `discover` permission (data/source_permissions.csv). A challenge page,
a 403 or a refused connection is printed as such and never retried with
different headers - nothing here works around a block.

Printed per target, and nothing else: HTTP status, final host, content type,
byte count, whether the body is a bot / WAF challenge, the page title with
digits masked, the number of <table> / <tr> elements, and up to 12 links whose
text names a list (lands available, struck off, resale, trust, sale list,
constable) - link text and the URL path, digits masked. Never a row, name,
address, parcel, account or amount.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import urljoin, urlsplit

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

UA = "taxdeed-scraper/1.0 (+https://github.com/rodzmodzllc-max/taxdeed-scraper)"

# (label, source_id, url) - every URL is a registry row's own canonical_url.
TARGETS = (
    ("FL Broward LAFT (County Records, Taxes & Treasury)", "fl_laft_portals",
     "https://www.broward.org/RecordsTaxesTreasury/TaxesFees/Pages/LandsAvailableforTaxes.aspx"),
    ("FL Broward LAFT list (SharePoint list view)", "fl_laft_portals",
     "https://www.broward.org/RecordsTaxesTreasury/FAQs/Lists/LandsAvailable/AllItems.aspx"),
    ("FL Baker Clerk", "fl_laft_portals", "https://www.bakerclerk.com"),
    ("FL Lake realTDM", "fl_laft_realtdm", "https://lake.realtdm.com/public/cases/list"),
    ("TX Johnson constable sale", "tx_johnson_constable_sale",
     "https://www.johnsoncountytx.org/public-safety/constables/constable-sale"),
    ("TX Brazoria sheriff sale & tax resales", "tx_brazoria_tax_resale",
     "https://www.brazoriacountytx.gov/departments/tax-office/property-taxes/sheriff-sale-tax-resales"),
    ("TX Jefferson County site", "tx_jefferson_county_resale", "https://www.jeffersoncountytx.gov"),
    ("TX Jefferson Tax Office sale page", "tx_jefferson_sheriff_sale", "https://jeffcotax.com/property-tax/delinquent-tax-sale/"),
    ("TX Grayson struck-off portal", "tx_grayson_struck_off", "https://taxsearch.co.grayson.tx.us:8443/Sales/Struck-Off-Properties"),
    ("TX Gregg tax resale PDF", "tx_gregg_tax_resale",
     "https://www.greggcounty.texas.gov/assets/main/tax-assessor-collector/tax-resale-property.pdf"),
)

LIST_WORDS = re.compile(r"lands? available|struck|resale|re-sale|trust propert|sale list|propert(y|ies) (list|for sale)|"
                        r"constable|sheriff.?s? sale|tax sale|notice of sale|tax deed|laft|certificat|county.held", re.I)

# Florida Tax Collector county-held certificate candidates (data/county_source_candidates.csv),
# read with --certificates. Each gets one value-free read and one hop to same-host list links.
CANDIDATES = HERE.parent / "data" / "county_source_candidates.csv"
HERNANDO_FTP = ("ftp.hernandocounty.us", "TCData", "BIDCERAUTO.TXT")
CHALLENGE = re.compile(r"attention required|cf-chl|cloudflare|sucuri|captcha|access denied|are you a robot|request rejected", re.I)


def mask(s: str) -> str:
    return re.sub(r"\d", "9", re.sub(r"\s+", " ", s or "")).strip()


FOLLOW_HOSTS = {"www.broward.org", "baycountyfltax.gov", "www.citrustc.us", "citrustc.us", "mdctaxcollector.gov",
                "www.mdctaxcollector.gov", "escambiataxsale.com", "www.escambiataxsale.com", "www.hernandocounty.us"}
MAX_FOLLOW = 6


def table_shapes(body: str) -> None:
    from bs4 import BeautifulSoup  # noqa: PLC0415
    for t in BeautifulSoup(body, "html.parser").find_all("table")[:8]:
        rows = t.find_all("tr")
        hdr = [mask(c.get_text(" "))[:25] for c in rows[0].find_all(["th", "td"])][:10] if rows else []
        # header cells only when they are short labels (never a data row's values)
        hdr = [h for h in hdr if h and len(h) <= 25 and not re.search(r"9{3}", h)]
        print(f"     table rows={len(rows)} header~{hdr}", flush=True)


def probe(session, label: str, url: str, depth: int = 0) -> None:
    print(f"{'  ' * depth}== {label}", flush=True)
    try:
        r = session.get(url, timeout=40)
    except Exception as exc:  # noqa: BLE001 - reported, never retried
        print(f"   request failed: {type(exc).__name__}", flush=True)
        return
    ctype = (r.headers.get("content-type") or "").split(";")[0]
    body = r.text if ("html" in ctype or "text" in ctype) else ""
    title = re.findall(r"<title[^>]*>(.*?)</title>", body, re.S | re.I)[:1]
    print(f"   HTTP {r.status_code} host={urlsplit(r.url).hostname} type={ctype} bytes={len(r.content)} "
          f"pdf={r.content[:5] == b'%PDF-'} challenge={bool(CHALLENGE.search(body[:4000]))}", flush=True)
    print(f"   title={mask(title[0])[:80] if title else ''!r} tables={body.lower().count('<table')} "
          f"tr={body.lower().count('<tr')}", flush=True)
    print(f"   redirects={[h.status_code for h in r.history]}", flush=True)
    if "<table" in body.lower():
        table_shapes(body)
    n = 0
    follow = []
    for m in re.finditer(r'<a\b[^>]*?href=\s*["\']([^"\']+)["\'][^>]*>(.*?)</a>', body, re.S | re.I):
        text = re.sub(r"<[^>]+>", " ", m.group(2))
        if LIST_WORDS.search(text) or LIST_WORDS.search(m.group(1)):
            full = urljoin(r.url, m.group(1).replace("&amp;", "&"))
            u = urlsplit(full)
            print(f"   link {mask(text)[:60]!r} -> {u.hostname}{mask(u.path)[:90]}", flush=True)
            if depth == 0 and u.hostname in FOLLOW_HOSTS and full not in follow and u.scheme == "https":
                follow.append(full)
            n += 1
            if n >= 20:
                break
    for f in follow[:MAX_FOLLOW]:
        probe(session, "follow " + mask(urlsplit(f).path)[:70], f, depth + 1)


def line_shape(line: str) -> str:
    """digits -> 9, letters -> A: the layout of a line, never its value."""
    return re.sub(r"[A-Za-z]", "A", re.sub(r"\d", "9", line))[:160]


def probe_hernando_ftp() -> None:
    """Anonymous public FTP (the Tax Collector's own published location). ftplib
    is not covered by the HTTP discovery guard, so the discover permission is
    checked here explicitly before the connection. Prints sizes and the SHAPE
    of the header and first line only."""
    import ftplib  # noqa: PLC0415
    import permission_gate as PG  # noqa: PLC0415
    print("== FL Hernando county-held certificates (anonymous FTP)", flush=True)
    d = PG.decide("fl_hernando_tc_certificates", "discover", state="FL", county="Hernando")
    if d is None or not d.allowed:
        print("   discover not permitted - 0 requests", flush=True)
        return
    host, folder, name = HERNANDO_FTP
    try:
        ftp = ftplib.FTP(host, timeout=40)
        ftp.login()  # anonymous, as the Tax Collector's page instructs
        ftp.cwd(folder)
        names = ftp.nlst()
        print(f"   folder entries={len(names)} target_present={name in names} "
              f"txt_files={sum(1 for n in names if n.lower().endswith('.txt'))}", flush=True)
        if name in names:
            chunks: list[bytes] = []
            ftp.retrbinary(f"RETR {name}", chunks.append)
            text = b"".join(chunks).decode("latin-1")
            lines = [ln for ln in text.splitlines() if ln.strip()]
            delims = {d: sum(ln.count(d) for ln in lines[:200]) for d in (",", "|", "\t", ";")}
            widths = sorted({len(ln) for ln in lines[:500]})
            print(f"   bytes={len(text)} lines={len(lines)} delimiter_counts={delims} line_widths~{widths[:8]}", flush=True)
            for ln in lines[:3]:
                print(f"   shape {line_shape(ln)!r}", flush=True)
        ftp.quit()
    except Exception as exc:  # noqa: BLE001 - reported, never retried
        print(f"   FTP failed: {type(exc).__name__}", flush=True)


def main() -> int:
    import permission_gate as PG  # noqa: PLC0415
    PG.install_discovery_guard("capture_county_sources")
    import requests  # noqa: PLC0415
    session = requests.Session()
    session.headers["User-Agent"] = UA
    if "--certificates" in sys.argv:
        import csv  # noqa: PLC0415
        with open(CANDIDATES, newline="", encoding="utf-8") as fh:
            for c in csv.DictReader(fh):
                probe(session, f"FL {c['county']} county-held certificates ({c['source_id']})", c["url"])
        probe_hernando_ftp()
        return 0
    for label, _sid, url in TARGETS:
        probe(session, label, url)
    return 0


if __name__ == "__main__":
    sys.exit(main())
