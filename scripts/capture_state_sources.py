"""Value-free live capture of the candidate (non-production) state sources.

State-expansion sprint (2026-09-30). AL / AR / LA / AZ are registered but
not activated: every fact about their sources is search-index evidence
because the sandbox cannot reach them. This script runs ONLY in the manual
`job=evidence` / `evidence_scope=state_sources` job of harvest-and-sync.yml
and reads, once, the pages / documents the registry rows and the adapters
already name, plus the terms / disclaimer / licence pages those pages link
to (one hop, same site, capped). It writes nothing to any database and
enables nothing.

What it prints is STRUCTURE, never a row value:
  * page title, headings, status, content type, Last-Modified;
  * table header texts and body-row counts; form field names; select
    option texts (digits masked) - the selector vocabulary a parser needs;
  * sentences carrying terms / licence / purchase vocabulary with no
    7+ digit run, every digit masked;
  * for a CSV: the header row, the number of rows read, and per identifier-
    like column the SHAPE of its values (every digit -> 9, every letter ->
    A), never the values;
  * for a Socrata dataset: the dataset's own metadata (name, licence,
    attribution, update timestamps, column names and types).
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode, urljoin, urlsplit

import requests

try:
    from bs4 import BeautifulSoup
except ImportError:  # pragma: no cover - the workflow installs it
    BeautifulSoup = None

REPO = Path(__file__).resolve().parents[1]
REGISTRY = REPO / "data" / "county_source_registry.csv"
OUT_PATH = REPO / "out" / "public" / "state-source-capture.json"
CANDIDATE_STATES = ("AL", "AR", "LA", "AZ")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
HEADERS = {"User-Agent": UA, "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
           "Accept-Language": "en-US,en;q=0.9"}

# Extra pages the adapters' evidence ledgers name (same hosts as the registry rows).
EXTRA_URLS = {
    "AL": ["https://www.revenue.alabama.gov/faqs/where-can-i-find-a-list-of-tax-delinquent-property/",
           "https://www.revenue.alabama.gov/faq-categories/land-sales/"],
    "AR": ["https://cosl.org/Home/Faq", "https://cosl.org/Home/Laws", "https://auction.cosl.org/"],
    "LA": ["https://data.brla.gov/api/views/a4h4-zi7e.json"],
    "AZ": ["https://treasurer.maricopa.gov/TaxLien", "https://ftp.treasurer.maricopa.gov/TaxAssignment/State_CP/state-cp-data.csv"],
}
# Candidate NEW sources (not in the registry): official pages named by a web
# search, read once for structure and terms. Discovery only.
DISCOVERY_PAGES = {
    "MN": ["https://www.stlouiscountymn.gov/departments-a-z/land-minerals/sales-and-contracts/tax-forfeited-land-sales",
           "https://www.hennepincounty.gov/services/property/tax-forfeited-land",
           "https://gishub-beltramicounty.hub.arcgis.com/datasets/county-land-sales/about",
           "https://www.itascacountymn.gov/616/Tax-Forfeit-Land",
           "https://www.carltoncountymn.gov/935/Tax-Forfeited-Land-Sale",
           "https://www.hubbardcounty.gov/tfl",
           "https://ottertailcounty.gov/property-home/property-sales/tax-forfeited-lands/"],
}
DISCOVERY_QUERIES = ('("tax forfeited" OR "tax forfeit" OR "tax-forfeited") type:"Feature Service"',
                     '"adjudicated" property type:"Feature Service"')
TERMS_VOCAB = re.compile(r"terms|disclaimer|legal|licen[cs]e|conditions|copyright|policy|privacy|open data|use of (this|the) (site|data)", re.I)
SNIPPET_VOCAB = re.compile(r"terms|disclaim|licen[cs]|copyright|permission|commercial|redistribut|reproduc|public record|open data|"
                           r"warrant|liabil|accuracy|purchas|apply|application|bid|auction|redeem|redemption|inventory|"
                           r"adjudicat|certificate|assign|updated|weekly|daily|monthly", re.I)
ID_HEADER = re.compile(r"parcel|number|\bno\b|\bnum|\bid\b|\bcp\b|cert|case|year|date|amount|value|rate|zip|ward", re.I)
LONG_DIGITS = re.compile(r"\d{7,}")
MAX_SNIPPETS, MAX_SNIPPET_CHARS = 40, 320
MAX_TERMS_FOLLOW = 4
CSV_BYTES = 3_000_000


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def mask_digits(text: str) -> str:
    return re.sub(r"\d", "9", text or "")


def shape(value: str) -> str:
    return re.sub(r"[A-Za-z]", "A", re.sub(r"\d", "9", (value or "").strip()))


def fetch(session: requests.Session, url: str, *, stream: bool = False):
    try:
        return session.get(url, headers=HEADERS, timeout=25, allow_redirects=True, stream=stream), None
    except requests.RequestException as exc:
        return None, f"{type(exc).__name__}: {str(exc)[:160]}"


def html_structure(html: str, url: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    title = clean(soup.title.get_text(" ")) if soup.title else ""
    headings = [clean(h.get_text(" "))[:120] for h in soup.find_all(["h1", "h2", "h3"])][:20]
    tables = []
    for t in soup.find_all("table")[:8]:
        hdr = [clean(th.get_text(" "))[:60] for th in t.find_all("th")][:30]
        body_rows = [tr for tr in t.find_all("tr") if tr.find("td")]
        cells = Counter(len(tr.find_all("td")) for tr in body_rows)
        tables.append({"headers": [mask_digits(h) for h in hdr], "body_rows": len(body_rows),
                       "cells_per_row": dict(cells.most_common(3)), "id": t.get("id") or "", "class": " ".join(t.get("class") or [])})
    forms = []
    for f in soup.find_all("form")[:6]:
        fields = []
        for el in f.find_all(["input", "select", "textarea", "button"])[:40]:
            entry = {"tag": el.name, "name": el.get("name") or "", "type": el.get("type") or ""}
            if el.name == "select":
                opts = [mask_digits(clean(o.get_text(" ")))[:40] for o in el.find_all("option")]
                entry["options"] = len(opts)
                entry["option_texts"] = opts[:120]
                vals = [o.get("value") or "" for o in el.find_all("option")]
                entry["value_shapes"] = dict(Counter(shape(v) for v in vals).most_common(5))
            fields.append(entry)
        forms.append({"method": (f.get("method") or "get").lower(), "action": mask_digits(urljoin(url, f.get("action") or "")), "fields": fields})
    terms_links = []
    for a in soup.find_all("a", href=True):
        text = clean(a.get_text(" "))
        href = urljoin(url, a["href"].strip())
        if href.startswith(("http://", "https://")) and (TERMS_VOCAB.search(text) or TERMS_VOCAB.search(urlsplit(href).path)) \
                and not LONG_DIGITS.search(href):
            terms_links.append({"text": text[:80], "href": href})
    for tag in soup.find_all(["table", "script", "style", "noscript", "select", "form"]):
        tag.decompose()
    snippets = []
    for s in re.split(r"(?<=[.!?])\s+|\n{2,}", soup.get_text("\n")):
        s = clean(s)
        if len(s) > 25 and SNIPPET_VOCAB.search(s) and not LONG_DIGITS.search(s):
            snippets.append(mask_digits(s)[:MAX_SNIPPET_CHARS])
        if len(snippets) >= MAX_SNIPPETS:
            break
    return {"title": title, "headings": headings, "tables": tables, "forms": forms,
            "terms_links": terms_links[:15], "snippets": snippets}


def csv_structure(resp) -> dict:
    raw = b""
    for chunk in resp.iter_content(65536):
        raw += chunk
        if len(raw) >= CSV_BYTES:
            break
    complete = len(raw) < CSV_BYTES
    text = raw.decode("utf-8-sig", errors="replace")
    if not complete:
        text = text[: text.rfind("\n")]
    rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        return {"csv_rows": 0}
    header = rows[0]
    body = [r for r in rows[1:] if any(c.strip() for c in r)]
    columns = []
    for i, h in enumerate(header):
        vals = [r[i] for r in body if i < len(r) and r[i].strip()]
        col = {"header": h, "non_empty": len(vals)}
        if ID_HEADER.search(h):
            col["shapes"] = dict(Counter(shape(v) for v in vals).most_common(4))
            col["distinct"] = len(set(vals))
        columns.append(col)
    return {"csv_header": header, "csv_rows": len(body), "csv_read_complete": complete, "csv_bytes_read": len(raw), "columns": columns}


def socrata_structure(data: dict) -> dict:
    lic = data.get("license") or {}
    meta = data.get("metadata") or {}
    return {"name": data.get("name"), "description": mask_digits((data.get("description") or "")[:700]),
            "licenseId": data.get("licenseId"), "license": {k: lic.get(k) for k in ("name", "termsLink")},
            "attribution": data.get("attribution"), "attributionLink": data.get("attributionLink"),
            "provenance": data.get("provenance"), "publicationDate": data.get("publicationDate"),
            "rowsUpdatedAt": data.get("rowsUpdatedAt"), "viewLastModified": data.get("viewLastModified"),
            "custom_fields": meta.get("custom_fields"),
            "columns": [{"name": c.get("name"), "type": c.get("dataTypeName")} for c in data.get("columns") or []]}


def capture(session: requests.Session, url: str, kind: str) -> dict:
    out = {"url": url, "kind": kind, "fetched_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat()}
    is_csv = ".csv" in urlsplit(url).path.lower()
    resp, err = fetch(session, url, stream=is_csv)
    if err:
        out["error"] = err
        return out
    out.update({"status": resp.status_code, "final_url": resp.url, "content_type": resp.headers.get("Content-Type", ""),
                "last_modified": resp.headers.get("Last-Modified"), "content_length": resp.headers.get("Content-Length")})
    if resp.status_code != 200:
        return out
    ctype = out["content_type"].lower()
    try:
        if is_csv or "text/csv" in ctype:
            out.update(csv_structure(resp))
        elif "json" in ctype or url.endswith(".json"):
            data = resp.json()
            out["socrata"] = socrata_structure(data) if isinstance(data, dict) and "columns" in data else {"keys": sorted(data)[:40] if isinstance(data, dict) else type(data).__name__}
        elif BeautifulSoup is not None:
            out.update(html_structure(resp.text, resp.url))
    except Exception as exc:  # noqa: BLE001 - evidence capture reports, never crashes
        out["parse_error"] = f"{type(exc).__name__}: {str(exc)[:160]}"
    return out


def form_probe(session: requests.Session, url: str) -> dict:
    """Submit the page's own GET search form once, with the FIRST non-blank
    option of its first select and every other field at its page default -
    the site's own parameter names and option value, never a guessed URL.
    Only the structure of the result page is kept (the URL is printed with
    digits masked)."""
    resp, err = fetch(session, url)
    if err or resp is None or resp.status_code != 200:
        return {"error": err or f"status {getattr(resp, 'status_code', None)}"}
    soup = BeautifulSoup(resp.text, "html.parser")
    for f in soup.find_all("form"):
        if (f.get("method") or "get").lower() != "get":
            continue
        sel = next((s for s in f.find_all("select") if s.get("name") and len(s.find_all("option")) > 2), None)
        if sel is None:
            continue
        value = next((o.get("value") for o in sel.find_all("option") if (o.get("value") or "").strip()), None)
        if value is None:
            continue
        params = {}
        for el in f.find_all(["input", "button"]):
            if el.get("name") and (el.get("type") or "").lower() not in ("checkbox", "radio", "reset"):
                params.setdefault(el["name"], el.get("value") or "")
        params[sel["name"]] = value
        target = urljoin(resp.url, f.get("action") or "") + "?" + urlencode(params)
        page = capture(session, target, "form_probe")
        page["url"] = mask_digits(target)
        page["final_url"] = mask_digits(page.get("final_url") or "")
        page["probe_params"] = sorted(params)
        return page
    return {"error": "no GET form with a select on the page"}


ARCGIS_SEARCH = "https://www.arcgis.com/sharing/rest/search"


def strip_html(text: str) -> str:
    return clean(re.sub(r"<[^>]+>", " ", text or ""))


def arcgis_layer_meta(session: requests.Session, url: str) -> list[dict]:
    """A feature / map service's layers: name, fields, edit date and feature
    count. Metadata only - never a feature."""
    out = []
    resp, err = fetch(session, url.rstrip("/") + "?f=json")
    if err or resp is None or resp.status_code != 200:
        return [{"error": err or f"status {getattr(resp, 'status_code', None)}"}]
    try:
        svc = resp.json()
    except ValueError:
        return [{"error": "not json"}]
    layers = svc.get("layers") or []
    if not layers and re.search(r"/(FeatureServer|MapServer)/\d+$", url):
        layers = [{"id": int(url.rstrip("/").rsplit("/", 1)[1])}]
        url = url.rstrip("/").rsplit("/", 1)[0]
    for lyr in layers[:3]:
        lurl = f"{url.rstrip('/')}/{lyr.get('id')}"
        rec: dict = {"layer": lurl}
        r2, e2 = fetch(session, lurl + "?f=json")
        if e2 or r2 is None or r2.status_code != 200:
            rec["error"] = e2 or f"status {getattr(r2, 'status_code', None)}"
            out.append(rec)
            continue
        try:
            meta = r2.json()
        except ValueError:
            rec["error"] = "not json"
            out.append(rec)
            continue
        rec.update({"name": meta.get("name"), "geometry": meta.get("geometryType"), "max_records": meta.get("maxRecordCount"),
                    "last_edit": (meta.get("editingInfo") or {}).get("lastEditDate"),
                    "copyright": strip_html(meta.get("copyrightText") or "")[:300],
                    "fields": [f"{f.get('name')}:{(f.get('type') or '').replace('esriFieldType', '')}" + (f"({f.get('alias')})" if f.get("alias") and f.get("alias") != f.get("name") else "")
                               for f in meta.get("fields") or []][:60]})
        r3, _ = fetch(session, lurl + "/query?where=1%3D1&returnCountOnly=true&f=json")
        try:
            rec["count"] = r3.json().get("count") if r3 is not None and r3.status_code == 200 else None
        except ValueError:
            rec["count"] = None
        out.append(rec)
        time.sleep(0.4)
    return out


def arcgis_discover(session: requests.Session, query: str, *, limit: int = 25) -> list[dict]:
    """ArcGIS Online's own catalog search for public items matching `query`:
    who publishes them, their licence / access text, and (for services) the
    layers' field names and counts."""
    params = {"q": query, "f": "json", "num": limit, "sortField": "modified", "sortOrder": "desc"}
    resp, err = fetch(session, ARCGIS_SEARCH + "?" + urlencode(params))
    if err or resp is None or resp.status_code != 200:
        return [{"error": err or f"status {getattr(resp, 'status_code', None)}"}]
    items = []
    for it in (resp.json().get("results") or [])[:limit]:
        rec = {"id": it.get("id"), "title": it.get("title"), "type": it.get("type"), "owner": it.get("owner"),
               "org": it.get("orgId"), "url": it.get("url"), "modified": it.get("modified"),
               "tags": (it.get("tags") or [])[:12], "snippet": strip_html(it.get("snippet") or "")[:240],
               "license": strip_html(it.get("licenseInfo") or "")[:600], "access": strip_html(it.get("accessInformation") or "")[:240]}
        if it.get("type") in ("Feature Service", "Map Service") and it.get("url"):
            rec["layers"] = arcgis_layer_meta(session, it["url"])
        items.append(rec)
        time.sleep(0.3)
    return items


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--digest", default=None)
    ap.add_argument("--state", action="append", default=[])
    ap.add_argument("--arcgis-search", action="append", default=[], help="ArcGIS Online catalog query (repeatable); metadata only")
    ap.add_argument("--skip-registry", action="store_true")
    ap.add_argument("--discovery", action="store_true", help="also read DISCOVERY_PAGES and run DISCOVERY_QUERIES")
    ap.add_argument("--out", default=str(OUT_PATH))
    args = ap.parse_args(argv)
    if args.digest:
        print(digest(Path(args.digest)))
        return 0
    wanted = set(args.state) or set(CANDIDATE_STATES)
    session = requests.Session()
    report: dict = {"generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(), "states": {}}
    with open(REGISTRY, newline="", encoding="utf-8") as fh:
        rows = [] if args.skip_registry else [r for r in csv.DictReader(fh) if r["state"] in wanted]
    for code, urls in DISCOVERY_PAGES.items():
        if not args.discovery:
            break
        entry = {"source_id": f"discovery_{code.lower()}", "county": "(discovery)", "pages": []}
        for url in urls:
            entry["pages"].append(capture(session, url, "discovery"))
            print(f"  {code} discovery      {entry['pages'][-1].get('status', entry['pages'][-1].get('error'))} {url}", flush=True)
            time.sleep(0.8)
        report["states"].setdefault(code, {"sources": []})["sources"].append(entry)
    for q in (args.arcgis_search or (DISCOVERY_QUERIES if args.discovery else ())):
        report.setdefault("arcgis", {})[q] = arcgis_discover(session, q)
        print(f"  arcgis search {q!r}: {len(report['arcgis'][q])} item(s)", flush=True)
    for r in rows:
        st = report["states"].setdefault(r["state"], {"sources": []})
        entry = {"source_id": r["source_id"], "county": r["county"], "pages": []}
        seen: set[str] = set()
        urls = [("canonical_url", r["canonical_url"]), ("document_url", r["document_url"]), ("purchase_url", r["purchase_url"])]
        if r["state"] == "AR":
            urls.insert(1, ("county_list", r["canonical_url"] + "?" + urlencode({"county": "DALLAS"})))
        urls += [("extra", u) for u in EXTRA_URLS.get(r["state"], [])]
        for kind, url in urls:
            url = (url or "").strip()
            if not url or url in seen:
                continue
            seen.add(url)
            entry["pages"].append(capture(session, url, kind))
            print(f"  {r['state']} {kind:<14} {entry['pages'][-1].get('status', entry['pages'][-1].get('error'))} {url}", flush=True)
            time.sleep(0.8)
        terms = []
        for pg in list(entry["pages"]):
            for link in pg.get("terms_links") or []:
                href = link["href"]
                if href in seen or len(terms) >= MAX_TERMS_FOLLOW:
                    continue
                if ".".join((urlsplit(href).hostname or "").split(".")[-2:]) != ".".join((urlsplit(pg.get("final_url") or pg["url"]).hostname or "").split(".")[-2:]):
                    continue
                seen.add(href)
                terms.append(href)
                page = capture(session, href, "terms")
                page["link_text"] = link["text"]
                entry["pages"].append(page)
                print(f"  {r['state']} terms          {page.get('status', page.get('error'))} {href}", flush=True)
                time.sleep(0.8)
        # Alabama: the search page's own county form, submitted once.
        if r["state"] == "AL" and BeautifulSoup is not None:
            probe = form_probe(session, r["canonical_url"])
            entry["pages"].append({"kind": "form_probe", "url": probe.pop("url", r["canonical_url"]), **probe})
            print(f"  AL form_probe     {probe.get('status', probe.get('error'))}", flush=True)
        st["sources"].append(entry)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {out}")
    return 0


def digest(path: Path) -> str:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    out = [f"# state-source capture {data.get('generated_at')}"]
    for state, st in sorted((data.get("states") or {}).items()):
        for e in st["sources"]:
            out.append(f"@@ {state} | {e['county']} | {e['source_id']}")
            for pg in e["pages"]:
                out.append(f"  ## {pg['kind']} {pg['url']} -> {pg.get('status', pg.get('error'))} final={pg.get('final_url')} "
                           f"ct={str(pg.get('content_type', ''))[:40]} lm={pg.get('last_modified')} len={pg.get('content_length')}"
                           + (f" linktext={pg.get('link_text')!r}" if pg.get("link_text") else ""))
                if pg.get("probe_params"):
                    out.append(f"  probe params: {pg['probe_params']}")
                if pg.get("parse_error"):
                    out.append(f"  parse_error: {pg['parse_error']}")
                if pg.get("title"):
                    out.append(f"  title: {pg['title'][:160]}")
                if pg.get("headings"):
                    out.append("  headings: " + " || ".join(pg["headings"][:12]))
                for t in pg.get("tables") or []:
                    out.append(f"  table id={t['id']!r} class={t['class']!r} rows={t['body_rows']} cells={t['cells_per_row']} headers={t['headers']}")
                for f in pg.get("forms") or []:
                    out.append(f"  form {f['method']} {f['action']}")
                    for x in f["fields"]:
                        extra = f" options={x.get('options')} shapes={x.get('value_shapes')} texts={x.get('option_texts')}" if x["tag"] == "select" else ""
                        out.append(f"    field {x['tag']} name={x['name']!r} type={x['type']!r}{extra}")
                for l in pg.get("terms_links") or []:
                    out.append(f"  terms-link: {l['text']!r} -> {l['href']}")
                if pg.get("csv_header") is not None:
                    out.append(f"  csv rows={pg.get('csv_rows')} complete={pg.get('csv_read_complete')} bytes={pg.get('csv_bytes_read')}")
                    for c in pg.get("columns") or []:
                        out.append(f"    col {c['header']!r} non_empty={c['non_empty']}" + (f" distinct={c.get('distinct')} shapes={c.get('shapes')}" if "shapes" in c else ""))
                if pg.get("socrata"):
                    out.append("  socrata: " + json.dumps(pg["socrata"])[:3000])
                for s in pg.get("snippets") or []:
                    out.append(f"  s: {s}")
    for q, items in (data.get("arcgis") or {}).items():
        out.append(f"@@ ARCGIS {q}")
        for it in items:
            if it.get("error"):
                out.append(f"  error: {it['error']}")
                continue
            out.append(f"  * {it['type']} | {it['title']} | owner={it['owner']} org={it['org']} id={it['id']} modified={it['modified']}")
            out.append(f"    url={it.get('url')} tags={it.get('tags')}")
            if it.get("snippet"):
                out.append(f"    snippet: {it['snippet']}")
            if it.get("license"):
                out.append(f"    license: {it['license']}")
            if it.get("access"):
                out.append(f"    access: {it['access']}")
            for l in it.get("layers") or []:
                if l.get("error"):
                    out.append(f"    layer error: {l['error']}")
                    continue
                out.append(f"    layer {l['layer']} name={l.get('name')} geom={l.get('geometry')} count={l.get('count')} last_edit={l.get('last_edit')} max={l.get('max_records')}")
                out.append(f"      fields: {', '.join(l.get('fields') or [])}")
                if l.get("copyright"):
                    out.append(f"      copyright: {l['copyright']}")
    return "\n".join(out)


if __name__ == "__main__":
    sys.exit(main())
