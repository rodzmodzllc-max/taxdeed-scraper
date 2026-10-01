#!/usr/bin/env python3
"""Source discovery for every AVAILABLE (state, county) - value-free
(all-sources enrichment engine, 2026-10-01).

Two probes, both read-only (no database write, no source write):

  --gis        For each AVAILABLE unit with a property-intelligence gap, search
               the public ArcGIS Online catalog and the Socrata Discovery API
               for parcel / tax-roll / cadastral datasets naming the county.
               For each ArcGIS service found: its parcel-like layers, their
               field NAMES, the item's licence / access-information text and
               copyright line, and an identifier MATCH PROBE - how many of the
               unit's own identifiers (parcel / account / case number) equal a
               value of each identifier-like field (returnCountOnly). Counts
               only: no identifier and no attribute value is printed.
  --documents  For each AVAILABLE unit: every official document the inventory
               names (registry list / document URLs, verified evidence pages,
               acquisition candidates ending in .pdf) read through
               harvesters/documents: method, pages, OCR status, document date,
               how many of the unit's identifiers it carries (deterministic,
               counts only), and the office contacts / process sentences it
               publishes (digit runs of 5+ masked, so no parcel number leaks).

Governance: a HARD_BLOCKED source is never requested. A catalog search result
is a CANDIDATE: it is REVIEW_REQUIRED until its licence is reviewed and its
identifier match verified; nothing here enables it.

    python3 scripts/discover_sources.py --gis --documents [--state LA] [--county "East Baton Rouge"]

Writes out/public/source-discovery.json and prints a digest to the job log.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.parse
from collections import defaultdict
from pathlib import Path

import requests

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
from harvesters.documents import extract as D  # noqa: E402
from harvesters.governance import states as ST  # noqa: E402
from harvesters.sources import inventory as INV  # noqa: E402

UA = "taxdeed-scraper source-discovery (+https://github.com/rodzmodzllc-max/taxdeed-scraper)"
ARCGIS_SEARCH = "https://www.arcgis.com/sharing/rest/search"
SOCRATA_SEARCH = "https://api.us.socrata.com/api/catalog/v1"
LAYER_NAME = re.compile(r"parcel|tax|cad\b|apprais|assess|propert|cadastr|lot", re.I)
ID_FIELD = re.compile(r"^(prop_?id|propid|property_?id|parcel(_?id|_?no|_?num(ber)?)?|pin|apn|acct|account(_?num(ber)?)?|"
                      r"geo_?id|geoid|tax_?id|quick_?ref|folio|strap|assessment_?num(ber)?|parcelnumb|parcel_number|pid)$", re.I)
USEFUL = {"acreage": re.compile(r"acre|acres|area_ac|legal_acre", re.I),
          "land_use": re.compile(r"land_?use|use_?code|state_?cd|prop_?class|class_?cd|luc\b|dor_?uc", re.I),
          "legal": re.compile(r"legal", re.I),
          "values": re.compile(r"(appr|mkt|market|land|impr|assess|tot).*val|val.*(tot|land|impr)", re.I),
          "situs": re.compile(r"situs|site_?addr|prop_?addr", re.I)}
LONG_DIGITS = re.compile(r"\d{5,}")
MAX_ITEMS = 12
MAX_LAYERS = 3
MAX_ID_FIELDS = 5
SAMPLE_IDS = 25
GAP_COLUMNS = {"legal": "legal_desc", "acreage": "acreage", "land_use": "land_use", "coordinates": "latitude",
               "assessment": "assessed"}


def mask(text: str) -> str:
    return LONG_DIGITS.sub(lambda m: "#" * len(m.group(0)), text or "")


class Http:
    def __init__(self, pause: float = 0.3):
        self.s = requests.Session()
        self.s.headers["User-Agent"] = UA
        self.pause = pause
        self.requests = 0

    def json(self, url: str, params: dict | None = None, timeout: int = 40):
        time.sleep(self.pause)
        self.requests += 1
        try:
            r = self.s.get(url, params=params, timeout=timeout)
        except requests.RequestException as exc:
            return None, f"{type(exc).__name__}"
        if r.status_code != 200:
            return None, f"HTTP {r.status_code}"
        try:
            return r.json(), None
        except ValueError:
            return None, "not JSON"

    def raw(self, url: str, timeout: int = 60):
        time.sleep(self.pause)
        self.requests += 1
        try:
            r = self.s.get(url, timeout=timeout)
        except requests.RequestException as exc:
            return None, f"{type(exc).__name__}"
        if r.status_code != 200:
            return None, f"HTTP {r.status_code}"
        return r, None


# ---------------------------------------------------------------- units

def available_units(base: str, key: str, state: str | None, county: str | None) -> dict:
    """(state, county) -> {"rows": n, "ids": [identifiers...], "gaps": {...}} for active AVAILABLE rows."""
    hdr = {"apikey": key, "Authorization": f"Bearer {key}"}
    units: dict = defaultdict(lambda: {"rows": 0, "ids": [], "gaps": defaultdict(int)})
    offset = 0
    sel = "id,state,county,parcel,case_no,legal_desc,acreage,land_use,latitude,assessed,market"
    while True:
        q = {"select": sel, "source": "eq.laft", "status": "eq.active", "order": "id.asc", "limit": 1000, "offset": offset}
        if state:
            q["state"] = f"eq.{state}"
        if county:
            q["county"] = f"eq.{county}"
        r = requests.get(f"{base}/rest/v1/properties", params=q, headers=hdr, timeout=60)
        r.raise_for_status()
        page = r.json()
        for row in page:
            u = units[(row["state"], row["county"])]
            u["rows"] += 1
            for ident in (row.get("parcel"), row.get("case_no")):
                if ident and len(u["ids"]) < SAMPLE_IDS * 2 and ident not in u["ids"]:
                    u["ids"].append(str(ident))
            for gap, col in GAP_COLUMNS.items():
                v = row.get(col)
                if v in (None, "") and not (gap == "assessment" and row.get("market") not in (None, "")):
                    u["gaps"][gap] += 1
        if len(page) < 1000:
            return units
        offset += 1000


# ---------------------------------------------------------------- GIS

def arcgis_candidates(http: Http, state: str, county: str) -> tuple[list[dict], str | None]:
    sname = ST.get_state(state).name if ST.get_state(state) else state
    unit = "Parish" if state == "LA" else "County"
    q = f'(parcel OR parcels OR cadastral OR "tax parcels" OR appraisal) "{county}" {sname} type:"Feature Service" OR type:"Map Service"'
    data, err = http.json(ARCGIS_SEARCH, {"q": q, "f": "json", "num": 50, "sortField": "numviews", "sortOrder": "desc"})
    if err:
        return [], err
    out = []
    for it in (data or {}).get("results", []):
        text = " ".join(str(it.get(k) or "") for k in ("title", "snippet", "tags", "description"))
        if county.lower() not in text.lower() and f"{county} {unit}".lower() not in text.lower():
            continue
        if not it.get("url"):
            continue
        out.append({"title": it.get("title"), "owner": it.get("owner"), "url": it["url"], "type": it.get("type"),
                    "licence": re.sub(r"<[^>]+>", " ", str(it.get("licenseInfo") or ""))[:240].strip(),
                    "access_information": str(it.get("accessInformation") or "")[:200].strip(),
                    "item": f"https://www.arcgis.com/home/item.html?id={it.get('id')}"})
        if len(out) >= MAX_ITEMS:
            break
    return out, None


def _quote(field_type: str, values: list[str]) -> str | None:
    if field_type in ("esriFieldTypeString",):
        return ",".join("'" + v.replace("'", "''") + "'" for v in values)
    nums = sorted({re.sub(r"\D", "", v).lstrip("0") for v in values if re.sub(r"\D", "", v)})
    return ",".join(n for n in nums if n) or None


def probe_layer(http: Http, layer_url: str, ids: list[str]) -> dict:
    meta, err = http.json(layer_url, {"f": "json"})
    if err or not isinstance(meta, dict) or "error" in meta:
        return {"layer_url": layer_url, "error": err or "layer error"}
    fields = meta.get("fields") or []
    names = [f.get("name") for f in fields if f.get("name")]
    out = {"layer_url": layer_url, "name": meta.get("name"), "geometry": meta.get("geometryType"),
           "copyright": (meta.get("copyrightText") or "")[:200], "field_count": len(names),
           "useful_fields": {k: [n for n in names if rx.search(n)][:6] for k, rx in USEFUL.items()},
           "id_match": {}}
    variants = sorted({v.strip() for v in ids} | {re.sub(r"[^0-9A-Za-z]", "", v) for v in ids} | {v.strip().upper() for v in ids})
    for f in [f for f in fields if ID_FIELD.match(f.get("name") or "")][:MAX_ID_FIELDS]:
        in_list = _quote(f.get("type"), variants)
        if not in_list:
            continue
        data, qerr = http.json(f"{layer_url}/query", {"where": f"{f['name']} IN ({in_list})", "returnCountOnly": "true", "f": "json"})
        out["id_match"][f["name"]] = (data or {}).get("count") if not qerr and isinstance(data, dict) and "count" in data else (qerr or "query error")
    return out


def discover_gis(http: Http, units: dict) -> list[dict]:
    report = []
    for (state, county), u in sorted(units.items()):
        gaps = {k: v for k, v in u["gaps"].items() if v}
        entry = {"state": state, "county": county, "rows": u["rows"], "gaps": gaps, "sample_ids": min(len(u["ids"]), SAMPLE_IDS * 2),
                 "arcgis": [], "socrata": []}
        cands, err = arcgis_candidates(http, state, county)
        entry["arcgis_error"] = err
        for c in cands:
            svc, serr = http.json(c["url"], {"f": "json"})
            c["layers"] = []
            if serr or not isinstance(svc, dict):
                c["error"] = serr or "service error"
                entry["arcgis"].append(c)
                continue
            layers = [l for l in (svc.get("layers") or []) if LAYER_NAME.search(str(l.get("name") or ""))][:MAX_LAYERS]
            if re.search(r"/(FeatureServer|MapServer)/\d+$", c["url"]):
                layers = [{"id": None}]
            for l in layers:
                lurl = c["url"] if l["id"] is None else f"{c['url'].rstrip('/')}/{l['id']}"
                c["layers"].append(probe_layer(http, lurl, u["ids"]))
            entry["arcgis"].append(c)
        sname = ST.get_state(state).name if ST.get_state(state) else state
        data, serr = http.json(SOCRATA_SEARCH, {"q": f"{county} parcel", "only": "dataset", "limit": 20})
        for res in ((data or {}).get("results") or []):
            r, md = res.get("resource") or {}, res.get("metadata") or {}
            blob = " ".join(str(x) for x in (r.get("name"), r.get("description"), md.get("domain")))
            if county.lower() not in blob.lower() or (sname.lower() not in blob.lower() and state != "LA"):
                continue
            entry["socrata"].append({"name": r.get("name"), "domain": md.get("domain"), "id": r.get("id"),
                                     "license": md.get("license"), "columns": (r.get("columns_field_name") or [])[:40],
                                     "updated": r.get("data_updated_at")})
        entry["socrata_error"] = serr
        report.append(entry)
    return report


# ---------------------------------------------------------------- deep probe

# Candidate datasets to probe in depth (every identifier of the unit, not a
# sample). Each named here because the catalog discovery found it with a
# matching identifier field; the probe decides nothing - it measures.
DEEP_TARGETS = [
    {"state": "LA", "county": "East Baton Rouge", "kind": "socrata", "url": "https://data.brla.gov/resource/ei2c-krsr.json",
     "meta": "https://data.brla.gov/api/views/ei2c-krsr.json"},
    {"state": "LA", "county": "East Baton Rouge", "kind": "socrata", "url": "https://data.brla.gov/resource/myfc-nh6n.json",
     "meta": "https://data.brla.gov/api/views/myfc-nh6n.json", "id_fields": ["assessment_no", "assessment_no_new"],
     "categories": ["structure_use", "vacant_lot_yn", "unit_type", "tax_year", "assessment_type", "assessment_status"]},
    {"state": "LA", "county": "East Baton Rouge", "kind": "socrata", "url": "https://data.brla.gov/resource/shrr-fsqq.json",
     "meta": "https://data.brla.gov/api/views/shrr-fsqq.json"},
    {"state": "TX", "county": "Jim Wells", "kind": "arcgis",
     "url": "https://services8.arcgis.com/36tOt5wOeEMz3tyS/arcgis/rest/services/JimWellsCADWebService/FeatureServer/0"},
    {"state": "TX", "county": "Hardin", "kind": "arcgis",
     "url": "https://services9.arcgis.com/8oveauLo4lI1NjDp/arcgis/rest/services/HardinCADWebService/FeatureServer/0"},
    {"state": "TX", "county": "Liberty", "kind": "arcgis",
     "url": "https://services3.arcgis.com/LbQai106UcFy2LlR/arcgis/rest/services/LibertyCADWebService/FeatureServer/0"},
    {"state": "TX", "county": "Goliad", "kind": "arcgis",
     "url": "https://services8.arcgis.com/WbC8UcChzGlcbEPR/arcgis/rest/services/GoliadCADWebService/FeatureServer/0"},
]


def shape(v) -> str:
    """Value-free identifier shape: digits -> 9, letters -> A, separators kept."""
    return re.sub(r"[A-Za-z]", "A", re.sub(r"\d", "9", str(v)))


def _top(counter: dict, n: int = 5) -> list:
    return sorted(counter.items(), key=lambda kv: -kv[1])[:n]


def all_unit_rows(base: str, key: str, state: str, county: str) -> list[dict]:
    hdr = {"apikey": key, "Authorization": f"Bearer {key}"}
    rows, offset = [], 0
    while True:
        q = {"select": "id,parcel,case_no,legal_desc,acreage,land_use,latitude", "source": "eq.laft", "status": "eq.active",
             "state": f"eq.{state}", "county": f"eq.{county}", "order": "id.asc", "limit": 1000, "offset": offset}
        r = requests.get(f"{base}/rest/v1/properties", params=q, headers=hdr, timeout=60)
        r.raise_for_status()
        page = r.json()
        rows += page
        if len(page) < 1000:
            return rows
        offset += 1000


def deep_probe(http: Http, target: dict, rows: list[dict]) -> dict:
    """Exact-identifier match counts (normalized alnum on both sides) per
    identifier field, ambiguity, and per-column fill among matched records."""
    from harvesters.enrichment.parcels import normalize_id  # noqa: PLC0415
    out = {"state": target["state"], "county": target["county"], "url": target["url"], "rows": len(rows)}
    cols, types = [], {}
    if target["kind"] == "socrata":
        meta, err = http.json(target["meta"])
        if err:
            return {**out, "error": err}
        cols = [c.get("fieldName") for c in (meta or {}).get("columns", []) if c.get("fieldName") and not c["fieldName"].startswith(":")]
        out["licence"] = ((meta or {}).get("license") or {}).get("name")
        out["rows_updated"] = (meta or {}).get("rowsUpdatedAt")
        id_fields = target.get("id_fields") or [c for c in cols if ID_FIELD.match(c) or c in ("prono", "assessment_number")]
    else:
        meta, err = http.json(target["url"], {"f": "json"})
        if err or "error" in (meta or {}):
            return {**out, "error": err or "layer error"}
        cols = [f["name"] for f in meta.get("fields", [])]
        types = {f["name"]: f.get("type") for f in meta.get("fields", [])}
        out["copyright"] = (meta.get("copyrightText") or "")[:160]
        id_fields = [c for c in cols if ID_FIELD.match(c)]
    out["columns"] = cols[:80]
    out["row_id_shapes"] = {c: _top(_count(shape(r.get(c)) for r in rows if r.get(c))) for c in ("parcel", "case_no")}
    out["id_fields"] = {}
    for idf in id_fields[:4]:
        res = {"matched_rows": 0, "ambiguous_rows": 0, "source_shapes": {}, "fill_among_matched": {}}
        for col in ("parcel", "case_no"):
            keyed = {}
            for r in rows:
                k = normalize_id(r.get(col), "alnum")
                if k:
                    keyed.setdefault(k, []).append(r)
            if not keyed:
                continue
            raw = sorted({str(r.get(col)).strip() for r in rows if r.get(col)})
            found: dict = {}
            for i in range(0, len(raw), 100):
                chunk = raw[i:i + 100]
                variants = sorted(set(chunk) | {re.sub(r"[^0-9A-Za-z]", "", v) for v in chunk})
                if target["kind"] == "socrata":
                    lst = ",".join("'" + v.replace("'", "''") + "'" for v in variants)
                    data, qerr = http.json(target["url"], {"$where": f"{idf} in({lst})", "$limit": 5000})
                    recs = data if isinstance(data, list) else []
                else:
                    lst = _quote(types.get(idf, "esriFieldTypeString"), variants)
                    if not lst:
                        continue
                    data, qerr = http.json(f"{target['url']}/query", {"where": f"{idf} IN ({lst})", "outFields": "*",
                                                                     "returnGeometry": "false", "f": "json"})
                    recs = [ft.get("attributes") or {} for ft in (data or {}).get("features", [])] if isinstance(data, dict) else []
                for rec in recs:
                    k = normalize_id(rec.get(idf), "alnum")
                    if k:
                        found.setdefault(k, []).append(rec)
                        res["source_shapes"][shape(rec.get(idf))] = res["source_shapes"].get(shape(rec.get(idf)), 0) + 1
            fill: dict = {}
            cats = res.setdefault("categories", {})
            for k, recs in found.items():
                if k in keyed:
                    for rec in recs:
                        for c in target.get("categories", []):
                            v = str(rec.get(c) or "").strip()[:40]
                            if v and not LONG_DIGITS.search(v):
                                cats.setdefault(c, {})
                                cats[c][v] = cats[c].get(v, 0) + 1
                if k not in keyed:
                    continue
                if len(recs) > 1:
                    res["ambiguous_rows"] += len(keyed[k])
                    continue
                res["matched_rows"] += len(keyed[k])
                for c, v in recs[0].items():
                    if v not in (None, "", " ") and str(v).strip() not in ("0", "0.0"):
                        fill[c] = fill.get(c, 0) + len(keyed[k])
            res[f"via_{col}"] = len([k for k in found if k in keyed])
            for c, n in fill.items():
                res["fill_among_matched"][c] = res["fill_among_matched"].get(c, 0) + n
        res["source_shapes"] = _top(res["source_shapes"])
        res["categories"] = {c: _top(v, 15) for c, v in res.get("categories", {}).items()}
        res["records_per_key"] = None
        res["fill_among_matched"] = dict(sorted(res["fill_among_matched"].items()))
        out["id_fields"][idf] = res
    return out


def _count(it) -> dict:
    c: dict = {}
    for x in it:
        c[x] = c.get(x, 0) + 1
    return c


# ---------------------------------------------------------------- documents

def document_urls(state: str, county: str) -> list[tuple[str, str]]:
    out = []
    for s in INV.sources_for(state, county):
        if not s.may_access or not s.url or s.state != state:
            continue
        if s.source_type == "DOCUMENT" or s.url.lower().split("?")[0].endswith((".pdf", ".csv", ".xlsx")):
            out.append((s.source_id, s.url))
    seen, uniq = set(), []
    for sid, url in out:
        if url not in seen:
            seen.add(url)
            uniq.append((sid, url))
    return uniq


def discover_documents(http: Http, units: dict) -> list[dict]:
    report = []
    for (state, county), u in sorted(units.items()):
        for sid, url in document_urls(state, county):
            resp, err = http.raw(url)
            entry = {"state": state, "county": county, "source_id": sid, "url": url}
            if err:
                report.append({**entry, "read_status": "SOURCE_UNAVAILABLE", "error": err})
                continue
            doc = D.read_document(resp.content, url=url, content_type=resp.headers.get("Content-Type", ""),
                                  last_modified=resp.headers.get("Last-Modified"))
            hits = D.find_identifier_records(doc, u["ids"], "alnum") if doc.readable else {}
            facts = D.acquisition_facts(doc) if doc.readable else {}
            status = defaultdict(int)
            for h in hits.values():
                status[h.status] += 1
            report.append({**entry, "read_status": "SOURCE_FOUND" if doc.readable else ("SOURCE_PARSE_FAILED" if doc.error else "SOURCE_EMPTY"),
                           "summary": D.summarize(doc), "identifier_match": dict(status),
                           "phones": [p["value"] for p in facts.get("phones", [])][:6],
                           "emails": [e["value"] for e in facts.get("emails", [])][:6],
                           "steps": [{"page": s["page"], "text": mask(s["text"])[:300]} for s in facts.get("steps", [])][:12]})
    return report


def digest(gis: list, docs: list) -> str:
    lines = []
    for e in gis:
        lines.append(f"== GIS {e['state']} / {e['county']}: {e['rows']} AVAILABLE rows; gaps {e['gaps']}; "
                     f"{len(e['arcgis'])} ArcGIS item(s), {len(e['socrata'])} Socrata dataset(s)")
        for c in e["arcgis"]:
            lines.append(f"  - [{c.get('type')}] {c.get('title')} (owner {c.get('owner')}) {c.get('url')}")
            if c.get("licence") or c.get("access_information"):
                lines.append(f"      licence: {mask(c.get('licence') or '-')[:200]} | access: {mask(c.get('access_information') or '-')[:160]}")
            for l in c.get("layers", []):
                if l.get("error"):
                    lines.append(f"      layer {l['layer_url']}: {l['error']}")
                    continue
                useful = {k: v for k, v in l["useful_fields"].items() if v}
                lines.append(f"      layer '{l.get('name')}' ({l.get('geometry')}, {l['field_count']} fields) copyright: {mask(l.get('copyright') or '-')[:120]}")
                lines.append(f"        useful fields: {useful}")
                lines.append(f"        identifier match (of {e['sample_ids']} sample ids): {l['id_match']}")
        for s in e["socrata"]:
            lines.append(f"  - [socrata] {s['name']} @ {s['domain']} ({s['id']}) licence={s.get('license')} cols={s['columns'][:20]}")
    for d in docs:
        lines.append(f"== DOC {d['state']} / {d['county']} {d['source_id']}: {d['read_status']} {d['url']}")
        if d.get("error"):
            lines.append(f"  error: {d['error']}")
            continue
        lines.append(f"  {d['summary']}")
        lines.append(f"  identifier match: {d['identifier_match']}; phones {d['phones']}; emails {d['emails']}")
        for s in d["steps"]:
            lines.append(f"    p{s['page']}: {s['text']}")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--gis", action="store_true")
    ap.add_argument("--documents", action="store_true")
    ap.add_argument("--deep", action="store_true", help="exact-identifier match + fill probe of DEEP_TARGETS (every unit row)")
    ap.add_argument("--state")
    ap.add_argument("--county")
    ap.add_argument("--out", default=str(REPO / "out" / "public" / "source-discovery.json"))
    a = ap.parse_args(argv)
    base, key = os.environ.get("SUPABASE_URL", "").rstrip("/"), os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not base or not key:
        print("skip: SUPABASE_URL / SUPABASE_SERVICE_KEY not set")
        return 0
    http = Http()
    if a.deep:
        deep = []
        for t in DEEP_TARGETS:
            if (a.state and t["state"] != a.state) or (a.county and t["county"] != a.county):
                continue
            deep.append(deep_probe(http, t, all_unit_rows(base, key, t["state"], t["county"])))
        out = Path(a.out.replace(".json", "-deep.json"))
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(deep, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
        for d in deep:
            print(f"== DEEP {d['state']} / {d['county']} {d['url']}: {d['rows']} AVAILABLE rows "
                  f"licence={d.get('licence')} copyright={mask(d.get('copyright') or '-')} updated={d.get('rows_updated')} error={d.get('error')}")
            print(f"   columns: {d.get('columns')}")
            print(f"   our id shapes: {d.get('row_id_shapes')}")
            for f, r in (d.get("id_fields") or {}).items():
                print(f"   [{f}] matched rows {r['matched_rows']}, ambiguous rows {r['ambiguous_rows']}, "
                      f"via parcel {r.get('via_parcel')}, via case_no {r.get('via_case_no')}; source shapes {r['source_shapes']}")
                print(f"      fill among matched: {r['fill_among_matched']}")
                if r.get("categories"):
                    print(f"      category values among matched records: {r['categories']}")
        if not (a.gis or a.documents):
            return 0
    units = available_units(base, key, a.state, a.county)
    gis = discover_gis(http, units) if a.gis else []
    docs = discover_documents(http, units) if a.documents else []
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    # The JSON carries counts, names and URLs only (sample identifiers never leave memory).
    out.write_text(json.dumps({"units": len(units), "requests": http.requests, "gis": gis, "documents": docs},
                              indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    print(f"discovery: {len(units)} AVAILABLE unit(s), {http.requests} request(s)")
    print(digest(gis, docs))
    return 0


if __name__ == "__main__":
    sys.exit(main())
