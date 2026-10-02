#!/usr/bin/env python3
"""Read-only STRUCTURAL capture of candidate AVAILABLE sources
(data/available_source_candidates.csv) - the generic form of
scripts/capture_sc_available.py (2026-10-02, AVAILABLE implementation sprint).

Runs only as the manual evidence job (`job=evidence`,
`evidence_scope=available_sources`): no database credential, nothing written
except out/public/available-source-structure.json. It reuses the SC capture's
privacy filters, so it may print only:

  * county-written availability / terms wording (tables removed; any sentence
    with a digit run, amount or e-mail dropped), titles, URLs, HTTP status;
  * for an HTML table: its row count, its header cells when every word of the
    header is whitelisted, and per column the count / SHAPES of
    identifier-shaped cells (digits -> 9, letters -> A);
  * for a PDF: the SC capture's structure (headings whose every word is
    whitelisted, counts, shapes);
  * for an ArcGIS item / layer: title, type, licence / access text, field
    names / aliases / types, the feature count, identifier SHAPES of
    identifier-named fields, and counts of short letters-only values of
    category-named fields (status, type, class ...).

Never: a row, a name, an address, a parcel / account number, raw document text.
tests/python/test_available_sources_capture.py proves it.

    python3 scripts/capture_available_sources.py
    python3 scripts/capture_available_sources.py --digest out/public/available-source-structure.json
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode, urljoin, urlsplit

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO))
import capture_sc_available as SC  # noqa: E402

CANDIDATES = REPO / "data" / "available_source_candidates.csv"
OUT_PATH = REPO / "out" / "public" / "available-source-structure.json"
ARCGIS_ITEM = "https://www.arcgis.com/sharing/rest/content/items/{id}"

LIST_LINK = re.compile(r"\b(available|inventory|for sale|list|properties|parcels|lots|forfeited|tax deed|surplus|resale|struck)\b", re.I)
ID_FIELD = re.compile(r"parcel|pin\b|^pin|apn|tax_?id|taxid|tms|map_?num|account|acct|prop_?id|property_?id|^id$|objectid", re.I)
CAT_FIELD = re.compile(r"status|type|class|program|category|zoning|use|listing|sale|avail|offer|neighborhood_type", re.I)
MAX_FOLLOW = 4
EXTRA_HEADER_WORDS = frozenset("""
price asking list sq ft square feet lot size zoning type class neighborhood ward city township village municipality parcel
id pin acres acre details view apply application link status available sold pending under contract offer
""".split())


def header_ok(cell: str) -> bool:
    words = re.findall(r"[A-Za-z]+", cell or "")
    if not words or len(words) > 8 or re.search(r"\d", SC.YEAR.sub("", cell)):
        return False
    return all(w.lower() in SC.HEADING_WORDS or w.lower() in EXTRA_HEADER_WORDS for w in words)


def table_structure(html: str) -> list[dict]:
    from bs4 import BeautifulSoup  # noqa: PLC0415
    out = []
    for t in BeautifulSoup(html, "html.parser").find_all("table")[:20]:
        rows = [[SC.clean(c.get_text(" ")) for c in tr.find_all(["th", "td"])] for tr in t.find_all("tr")]
        rows = [r for r in rows if any(r)]
        if not rows:
            continue
        header = rows[0]
        cols = Counter()
        shapes = Counter()
        for r in rows[1:]:
            for i, c in enumerate(r):
                if SC.ID_TOKEN.fullmatch(c):
                    cols[i] += 1
                    shapes[SC.shape(c)] += 1
        out.append({"rows": len(rows) - 1, "columns": max(len(r) for r in rows),
                    "header": [SC.mask(c)[:40] if header_ok(c) else ("(not printed)" if c else "") for c in header],
                    "id_cells_by_column": dict(cols), "id_shapes": dict(shapes.most_common(6))})
    return out


def list_links(html: str, url: str) -> list[dict]:
    """Same-site links whose text names a list / inventory (never one with a
    digit run in its text or a 7+ digit run in its address)."""
    from bs4 import BeautifulSoup  # noqa: PLC0415
    host, out = urlsplit(url).hostname, []
    for a in BeautifulSoup(html, "html.parser").find_all("a", href=True):
        text, href = SC.clean(a.get_text(" ")), urljoin(url, a["href"].strip())
        if href.startswith("https://") and urlsplit(href).hostname == host and LIST_LINK.search(text) \
                and not SC.row_like(text) and not re.search(r"\d{7,}", href):
            out.append({"text": text[:100], "href": href})
    return list({l["href"]: l for l in out}.values())[:30]


def _get(session, url, **kw):
    try:
        return session.get(url, headers=SC.PAGE_HEADERS, timeout=60, **kw), None
    except Exception as exc:  # noqa: BLE001
        return None, type(exc).__name__


def capture_html(session, url: str, src: dict, *, follow: bool = True) -> dict:
    r, err = _get(session, url)
    page = {"url": url, "read_at": _now(), "http_status": r.status_code if r is not None else None, "error": err}
    if r is None or not r.ok:
        return page
    ctype = r.headers.get("content-type", "").lower()
    page["content_type"] = ctype.split(";")[0]
    if r.content[:4] == b"%PDF":
        page.update(SC.analyse_pdf(r.content, {"source_id": src["source_id"]}))
        return page
    if "html" not in ctype:
        return page
    page.update(SC.html_wording(r.text, url))
    page["tables"] = table_structure(r.text)
    lists = list_links(r.text, url)
    page["list_links"] = lists
    if follow:
        targets = [l["href"] for l in lists if l["href"].rstrip("/") != url.rstrip("/")]
        page["followed"] = [capture_html(session, u, src, follow=False) for u in list(dict.fromkeys(targets))[:MAX_FOLLOW]]
    return page


def _json(session, url, params=None):
    r, err = _get(session, url + ("?" + urlencode(params) if params else ""))
    if r is None or not r.ok:
        return None, err or (r.status_code if r is not None else None)
    try:
        return r.json(), None
    except ValueError:
        return None, "not json"


def layer_structure(session, layer_url: str) -> dict:
    meta, err = _json(session, layer_url, {"f": "json"})
    out = {"url": layer_url, "error": err}
    if not meta:
        return out
    fields = meta.get("fields") or []
    out.update({"name": SC.mask(str(meta.get("name", "")))[:80], "geometry": meta.get("geometryType"),
                "fields": [{"name": f.get("name"), "alias": SC.mask(str(f.get("alias", "")))[:40], "type": f.get("type")}
                           for f in fields][:80]})
    cnt, _ = _json(session, layer_url + "/query", {"where": "1=1", "returnCountOnly": "true", "f": "json"})
    out["count"] = (cnt or {}).get("count")
    sample, _ = _json(session, layer_url + "/query", {"where": "1=1", "outFields": "*", "returnGeometry": "false",
                                                      "resultRecordCount": 200, "f": "json"})
    feats = [f.get("attributes") or {} for f in (sample or {}).get("features", [])]
    out["sampled"] = len(feats)
    names = [f.get("name") for f in fields if f.get("name")]
    out["id_shapes"] = {n: dict(Counter(SC.shape(str(a.get(n))) for a in feats if a.get(n) not in (None, "")).most_common(4))
                        for n in names if ID_FIELD.search(n)}
    out["filled"] = {n: sum(1 for a in feats if a.get(n) not in (None, "", " ")) for n in names}
    cats = {}
    for n in names:
        if not CAT_FIELD.search(n):
            continue
        vals = Counter()
        for a in feats:
            v = a.get(n)
            if isinstance(v, str) and v.strip() and not re.search(r"[\d,@$]", v) and len(v) <= 40 and len(v.split()) <= 4:
                vals[v.strip()] += 1
        if vals:
            cats[n] = dict(vals.most_common(10))
    out["category_values"] = cats
    return out


def capture_arcgis_item(session, item_id: str) -> dict:
    item, err = _json(session, ARCGIS_ITEM.format(id=item_id), {"f": "json"})
    out = {"url": f"item:{item_id}", "read_at": _now(), "error": err}
    if not item:
        return out
    strip = lambda t: re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", t or "")).strip()  # noqa: E731
    out.update({"title": SC.mask(item.get("title") or "")[:120], "type": item.get("type"), "service_url": item.get("url"),
                "snippet": strip(item.get("snippet"))[:300] if not SC.row_like(strip(item.get("snippet"))) else "(not printed)",
                "license": strip(item.get("licenseInfo"))[:800], "access": strip(item.get("accessInformation"))[:300],
                "modified": item.get("modified")})
    urls = []
    if item.get("url"):
        base = item["url"].rstrip("/")
        if re.search(r"/(Feature|Map)Server$", base):
            svc, _ = _json(session, base, {"f": "json"})
            urls = [f"{base}/{l['id']}" for l in (svc or {}).get("layers", [])][:6]
        else:
            urls = [base]
    elif item.get("type") in ("Web Map", "Web Mapping Application", "Dashboard"):
        data, _ = _json(session, ARCGIS_ITEM.format(id=item_id) + "/data", {"f": "json"})
        urls = [l.get("url") for l in (data or {}).get("operationalLayers", []) if l.get("url")][:6]
        out["operational_layers"] = len(urls)
    out["layers"] = [layer_structure(session, u) for u in urls]
    return out


def _now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def candidates(path: Path = CANDIDATES) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def digest(path: Path) -> str:
    doc = json.loads(path.read_text(encoding="utf-8"))
    out = [f"AVAILABLE source structural capture  generated={doc.get('generated_at')}"]

    def page_lines(p, ind="  "):
        out.append(f"{ind}{p.get('http_status')} {p.get('url')} type={p.get('content_type')} title={p.get('title')!r}")
        for x in p.get("availability_wording", [])[:15]:
            out.append(f"{ind}  avail: {x}")
        for x in p.get("terms_wording", [])[:10]:
            out.append(f"{ind}  terms: {x}")
        for l in p.get("links", [])[:25]:
            out.append(f"{ind}  link: {l['text']!r} -> {l['href']}")
        for l in p.get("list_links", [])[:25]:
            out.append(f"{ind}  list link: {l['text']!r} -> {l['href']}")
        for t in p.get("tables", []):
            out.append(f"{ind}  table rows={t['rows']} cols={t['columns']} header={t['header']} id_cells={t['id_cells_by_column']} shapes={t['id_shapes']}")
        st = p.get("structure")
        if st:
            out.append(f"{ind}  pdf pages={st['pages']} lines={st['lines']} id_lines={st['id_lines']} shapes={st['id_shapes']} "
                       f"years={st['years']} keywords={st['keywords']}")
            for h, n in st["headings"].items():
                out.append(f"{ind}  pdf heading x{n}: {h}")
            for t in st["tables"]:
                out.append(f"{ind}  pdf table p{t['page']} rows={t['rows']} cols={t['columns']} header={t['header']} id_cells={t['id_cells_by_column']}")
        for f in p.get("followed", []):
            page_lines(f, ind + "    ")

    for s in doc.get("sources", []):
        out.append(f"== {s['state']} {s['county']} {s['source_id']} ({s['kind']})")
        r = s.get("result", {})
        if s["kind"] == "arcgis_item":
            out.append(f"  item {r.get('title')!r} type={r.get('type')} modified={r.get('modified')} error={r.get('error')}")
            out.append(f"  service={r.get('service_url')}")
            out.append(f"  snippet: {r.get('snippet')}")
            out.append(f"  license: {r.get('license')}")
            out.append(f"  access: {r.get('access')}")
            for l in r.get("layers", []):
                out.append(f"  layer {l.get('url')} name={l.get('name')!r} geom={l.get('geometry')} count={l.get('count')} sampled={l.get('sampled')} error={l.get('error')}")
                out.append("    fields: " + ", ".join(f"{f['name']}({f['alias']}:{f['type']})" for f in l.get("fields", [])))
                out.append(f"    id_shapes={l.get('id_shapes')}")
                out.append(f"    filled={l.get('filled')}")
                out.append(f"    category_values={l.get('category_values')}")
        else:
            page_lines(r)
    return "\n".join(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--digest")
    ap.add_argument("--out", default=str(OUT_PATH))
    a = ap.parse_args(argv)
    if a.digest:
        print(digest(Path(a.digest)))
        return 0
    import requests  # noqa: PLC0415
    session = requests.Session()
    report = {"generated_at": _now(), "note": "Structural capture only - no row, name, address or identifier.", "sources": []}
    for c in candidates():
        res = capture_arcgis_item(session, c["url"]) if c["kind"] == "arcgis_item" else capture_html(session, c["url"], c)
        report["sources"].append({**{k: c[k] for k in ("source_id", "state", "county", "kind")}, "result": res})
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    print(f"wrote {out} ({len(report['sources'])} sources)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
