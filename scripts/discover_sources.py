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
    ap.add_argument("--state")
    ap.add_argument("--county")
    ap.add_argument("--out", default=str(REPO / "out" / "public" / "source-discovery.json"))
    a = ap.parse_args(argv)
    base, key = os.environ.get("SUPABASE_URL", "").rstrip("/"), os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not base or not key:
        print("skip: SUPABASE_URL / SUPABASE_SERVICE_KEY not set")
        return 0
    units = available_units(base, key, a.state, a.county)
    http = Http()
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
