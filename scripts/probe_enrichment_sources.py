#!/usr/bin/env python3
"""READ-ONLY evidence probe for two proposed enrichment fixes. Writes nothing.

Why this exists
---------------
Enrichment coverage for auction + LAFT/OTC rows is stuck at 57.7%, and the
remaining Florida gap is NOT a parcel-format problem. It is an identifier
problem: for the stalled counties we store the county's own account/folio
number, while the FDOR statewide cadastral layer is keyed on PARCEL_ID.

The FDOR FeatureServer was characterised live on 2026-09-18. It answers
exactly one kind of question reliably:

    PARCEL_ID='<exact>' (+ CO_NO)   -> works, and will return ALT_KEY
    CO_NO=<n> scan, 3 rows          -> HTTP 400 after ~55 seconds
    CO_NO=<n> scan incl. ALT_KEY    -> hangs
    ALT_KEY='<exact>'               -> HTTP 400, every county tried
    PHY_ADDR1='<exact>'             -> HTTP 400

So the API cannot discover a PARCEL_ID from an account number: every query
path that would do so is one the service refuses. ALT_KEY was confirmed to
hold a county account number for ONE county (Alachua parcel 08197-101-000 ->
ALT_KEY 105284), but that could not be verified for the stalled counties for
exactly the same reason.

This probe therefore tests the only remaining lawful route - the bulk
published dataset - and answers, with measurements rather than projections:

  FL: does ALT_KEY actually equal our stored account for Hillsborough,
      Brevard and Suwannee, and is the account -> PARCEL_ID mapping
      deterministic (1:1) or ambiguous (1:many)?
  TX: does Galveston CAD's published Parcel DBF carry the appraisal
      attributes needed to enrich our 203 Galveston rows, or only geometry?

Hard boundaries (enforced by construction, not by convention)
------------------------------------------------------------
Every outbound call in this file is a GET. There is no INSERT, UPDATE,
PATCH, POST or DELETE anywhere, no schema access, no write to
public.properties, and no enrichment. The Supabase read uses a plain
?select= REST call. If this script is ever extended, that property is what
must be preserved: it exists to produce evidence, not to change anything.

Output: JSON to out/probe_enrichment_sources.json plus a human-readable
markdown summary to out/probe-evidence.md. Both are uploaded as workflow
artifacts; neither is committed by this script.
"""

from __future__ import annotations

import io
import json
import os
import pathlib
import re
import struct
import sys
import time
import zipfile
from collections import defaultdict
from datetime import datetime, timezone

import requests

UA = {"User-Agent": "taxdeed-scraper-probe/1.0 (read-only evidence probe)"}
TIMEOUT = 90
OUT_DIR = pathlib.Path("out")

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")

# FDOR / FGIO statewide cadastral. Same layer behind the FeatureServer the
# module docstring describes, but reached through the published dataset.
FGIO_LAYER = (
    "https://services9.arcgis.com/Gh9awoU677aKree0/arcgis/rest/services/"
    "Florida_Statewide_Cadastral/FeatureServer/0"
)
# FL DOR county codes for the three counties under test (alphabetical 11-77).
FL_COUNTIES = {"Hillsborough": 39, "Brevard": 15, "Suwannee": 71}

# Two more counties whose RealAuction skin publishes NO parcel number at all,
# only the property appraiser's own key (confirmed live 2026-09-18, Actions
# run 35402576827): Citrus labels it "Alternate Key", Hernando "Parcel Key".
# Their stored `parcel` is '' for every row, so the keys are read live from
# the same public listing pages the harvester reads, and tested against
# FDOR's ALT_KEY exactly like the stored accounts above. If they join 1:1,
# those 50 rows become enrichable through the same ALT_KEY -> PARCEL_ID map.
FL_LIVE_KEY_COUNTIES = {
    "Citrus":   {"co_no": 19, "host": "citrus.realtaxdeed.com",   "labels": ("Alternate Key",)},
    "Hernando": {"co_no": 37, "host": "hernando.realtaxdeed.com", "labels": ("Parcel Key",)},
}
REALAUCTION_UA = {"User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                                 "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")}

GALVESTON_GIS_PAGE = "https://galvestoncad.org/gis-data/"

# Appraisal attributes that would make the Galveston DBF useful: these are the
# columns currently at 0 rows populated for every TX row we hold.
WANTED_TX_FIELDS = (
    "account", "acct", "prop_id", "propid", "quick_ref", "geo_id",
    "owner", "name", "situs", "addr", "market", "appraised", "assessed",
    "land_val", "imp_val", "value", "yr_built", "year_built", "yrblt",
    "living", "sqft", "area", "acres", "legal", "use", "class",
)


def _log(msg: str) -> None:
    print(f"[probe] {msg}", flush=True)


def _get(url: str, **kw):
    """The only network verb this module uses.

    Callers may pass their own headers (the Supabase read adds apikey /
    Authorization); they are merged over the probe's User-Agent rather than
    passed alongside it, which requests rejects as a duplicate keyword.
    """
    headers = {**UA, **kw.pop("headers", {})}
    return requests.get(url, headers=headers, timeout=TIMEOUT, **kw)


# --------------------------------------------------------------------------
# Our own data (read-only SELECT)
# --------------------------------------------------------------------------
def fetch_stored_accounts() -> dict[str, list[str]]:
    """Stored parcel values for the three FL counties, unenriched in-scope rows.

    Scope mirrors the coverage baseline exactly: source in (auction, laft),
    i.e. auction + LAFT/OTC. Certificate rows are deliberately excluded - that
    work is on hold and this probe must not widen its own scope.
    """
    if not SUPABASE_URL or not SERVICE_KEY:
        return {"_error": "SUPABASE_URL / SUPABASE_SERVICE_KEY not set"}
    out: dict[str, list[str]] = {}
    for county in FL_COUNTIES:
        url = (
            f"{SUPABASE_URL}/rest/v1/properties"
            f"?select=parcel&state=eq.FL&county=eq.{requests.utils.quote(county)}"
            f"&source=in.(auction,laft)&fdor_enriched_at=is.null"
            f"&parcel=not.is.null&limit=2000"
        )
        r = _get(url, headers={**UA, "apikey": SERVICE_KEY,
                               "Authorization": f"Bearer {SERVICE_KEY}"})
        r.raise_for_status()
        vals = [row["parcel"].strip() for row in r.json()
                if row.get("parcel") and row["parcel"].strip()]
        out[county] = sorted(set(vals))
        _log(f"{county}: {len(out[county])} distinct stored accounts")
    return out


# --------------------------------------------------------------------------
# FL: live appraiser keys from RealAuction skins that publish no parcel number
# --------------------------------------------------------------------------
def extract_alt_keys(listing_text: str, labels: tuple[str, ...]) -> list[str]:
    """Values under the given labels, one per AITEM_ block, in page order.

    Same block split and the same label -> CAD_DTA regex shape as
    harvest_all_counties.ps1's Get-Field, applied to the raw JSON-escaped
    listing text. Anchor text wins when the value is a link.
    """
    keys: list[str] = []
    for block in re.split(r"AITEM_", listing_text)[1:]:
        for label in labels:
            m = re.search(re.escape(label) + r':(?:@F|<)[\s\S]{0,200}?CAD_DTA\\?">\s*'
                          r'([^@<]*(?:<a[^>]*>([^<]*)</a>)?[^@<]*)', block)
            if m:
                v = (m.group(2) or m.group(1)).replace('\\"', '"')
                v = re.sub(r"\s+", " ", v).strip()
                if v:
                    keys.append(v)
                break
    return keys


def realauction_live_keys(county: str, host: str, labels: tuple[str, ...]) -> dict:
    """Appraiser keys from the county's next auction date(s), read-only.

    Calendar for this month + next two -> preview warm-up -> the same
    paginated AJAX listing the harvester reads, up to 3 pages per date and
    at most 2 dates, so this stays a few dozen requests. Nothing is stored.
    """
    result = {"county": county, "host": host, "dates": [], "keys": [], "errors": [], "requests": 0}
    s = requests.Session()
    s.headers.update(REALAUCTION_UA)
    today = datetime.now(timezone.utc)
    y, mth = today.year, today.month
    dates: list[str] = []
    for _ in range(3):
        try:
            r = s.get(f"https://{host}/index.cfm", timeout=30, params={
                "zaction": "user", "zmethod": "calendar",
                "selCalDate": f"{{ts '{y:04d}-{mth:02d}-01 00:00:00'}}"})
            result["requests"] += 1
            r.raise_for_status()
            dates += re.findall(r"CALSELT[^>]*dayid=['\"](\d{2}/\d{2}/\d{4})['\"]", r.text)
        except requests.RequestException as exc:
            result["errors"].append(f"calendar {y}-{mth:02d}: {exc!r}"[:200])
        mth += 1
        if mth == 13:
            y, mth = y + 1, 1
        time.sleep(0.5)
    dates = list(dict.fromkeys(dates))
    result["dates"] = dates
    for d in dates[:2]:
        preview = f"https://{host}/index.cfm?zaction=AUCTION&zmethod=PREVIEW&AuctionDate={d}"
        try:
            s.get(preview, timeout=30, headers={
                "Referer": f"https://{host}/index.cfm?zaction=USER&zmethod=CALENDAR"}).raise_for_status()
            result["requests"] += 1
        except requests.RequestException as exc:
            result["errors"].append(f"preview {d}: {exc!r}"[:200])
            continue
        for page in range(3):
            try:
                r = s.get(f"https://{host}/index.cfm", timeout=30, params={
                    "zaction": "AUCTION", "Zmethod": "UPDATE", "FNC": "LOAD", "AREA": "W",
                    "PageDir": str(page), "doR": "1", "bypassPage": "1", "test": "1"},
                    headers={"Accept": "application/json, text/javascript, */*; q=0.01",
                             "X-Requested-With": "XMLHttpRequest", "Referer": preview})
                result["requests"] += 1
                r.raise_for_status()
            except requests.RequestException as exc:
                result["errors"].append(f"listing {d} p{page}: {exc!r}"[:200])
                break
            found = extract_alt_keys(r.text, labels)
            if not found:
                break
            result["keys"] += found
            time.sleep(0.5)
    result["keys"] = sorted(set(result["keys"]))
    _log(f"{county}: {len(result['keys'])} distinct live appraiser keys from {len(dates)} date(s), "
         f"{result['requests']} requests")
    return result


# --------------------------------------------------------------------------
# FL: pull PARCEL_ID + ALT_KEY for a county
# --------------------------------------------------------------------------
def fgio_county_pairs(co_no: int, county: str) -> dict:
    """Return {'strategy': str, 'pairs': [(PARCEL_ID, ALT_KEY)], ...}.

    Two strategies, tried in order, because the plain attribute scan is the
    one already proven to fail:

      1. objectIds paging. `returnIdsOnly=true` is far cheaper than an
         attribute scan, and fetching by explicit objectIds hits the primary
         key rather than forcing a table scan. This is the standard way to
         page an ArcGIS service that refuses bulk attribute queries.
      2. Plain resultOffset paging, recorded as a control so the evidence
         shows whether the documented failure still reproduces.

    Whichever strategy works is reported, so the result is not just data but
    a statement about which access pattern this service actually supports.
    """
    result = {"county": county, "co_no": co_no, "strategy": None,
              "pairs": [], "errors": [], "requests": 0}

    # -- strategy 1: objectIds
    try:
        t0 = time.time()
        r = _get(f"{FGIO_LAYER}/query",
                 params={"where": f"CO_NO={co_no}", "returnIdsOnly": "true", "f": "json"})
        result["requests"] += 1
        d = r.json()
        if isinstance(d, dict) and d.get("error"):
            result["errors"].append(f"returnIdsOnly: {json.dumps(d['error'])[:200]}")
        else:
            oids = d.get("objectIds") or []
            result["objectid_count"] = len(oids)
            _log(f"{county}: {len(oids)} objectIds in {time.time()-t0:.1f}s")
            if oids:
                pairs = []
                CHUNK = 400
                for i in range(0, len(oids), CHUNK):
                    chunk = oids[i:i + CHUNK]
                    rr = _get(f"{FGIO_LAYER}/query",
                              params={"objectIds": ",".join(map(str, chunk)),
                                      "outFields": "PARCEL_ID,ALT_KEY",
                                      "returnGeometry": "false", "f": "json"})
                    result["requests"] += 1
                    dd = rr.json()
                    if isinstance(dd, dict) and dd.get("error"):
                        result["errors"].append(
                            f"objectIds chunk {i}: {json.dumps(dd['error'])[:160]}")
                        break
                    for f in dd.get("features", []):
                        a = f.get("attributes", {})
                        pairs.append((a.get("PARCEL_ID"), a.get("ALT_KEY")))
                    if (i // CHUNK) % 25 == 0:
                        _log(f"{county}: {len(pairs)} pairs so far")
                    time.sleep(0.05)
                if pairs:
                    result["strategy"] = "objectIds"
                    result["pairs"] = pairs
                    return result
    except Exception as exc:  # noqa: BLE001 - evidence probe records, never raises
        result["errors"].append(f"objectIds strategy: {exc!r}"[:220])

    # -- strategy 2: resultOffset control
    try:
        pairs, offset = [], 0
        while offset < 200_000:
            rr = _get(f"{FGIO_LAYER}/query",
                      params={"where": f"CO_NO={co_no}",
                              "outFields": "PARCEL_ID,ALT_KEY",
                              "returnGeometry": "false",
                              "resultOffset": offset, "resultRecordCount": 2000,
                              "f": "json"})
            result["requests"] += 1
            dd = rr.json()
            if isinstance(dd, dict) and dd.get("error"):
                result["errors"].append(
                    f"resultOffset {offset}: {json.dumps(dd['error'])[:160]}")
                break
            feats = dd.get("features", [])
            if not feats:
                break
            for f in feats:
                a = f.get("attributes", {})
                pairs.append((a.get("PARCEL_ID"), a.get("ALT_KEY")))
            offset += len(feats)
            if not dd.get("exceededTransferLimit"):
                break
            time.sleep(0.05)
        if pairs:
            result["strategy"] = "resultOffset"
            result["pairs"] = pairs
    except Exception as exc:  # noqa: BLE001
        result["errors"].append(f"resultOffset strategy: {exc!r}"[:220])

    return result


def analyse_fl_county(county: str, co_no: int, stored: list[str]) -> dict:
    """Measure the account -> PARCEL_ID join. No guessing, no fuzzy matching."""
    pulled = fgio_county_pairs(co_no, county)
    pairs = [(p, k) for p, k in pulled["pairs"] if p is not None]

    # ALT_KEY -> set(PARCEL_ID). A set, so 1:many is detectable rather than
    # silently collapsed - an account resolving to several parcels is an
    # ambiguity to classify, never a match to force.
    by_alt: dict[str, set] = defaultdict(set)
    for parcel_id, alt in pairs:
        if alt is None:
            continue
        by_alt[str(alt).strip()].add(parcel_id)

    exact, ambiguous, unmatched, examples = [], [], [], []
    for acct in stored:
        hits = by_alt.get(acct)
        if not hits:
            # one conservative normalisation only: leading zeros. Stored
            # values and ALT_KEY are both plain integers-as-text for these
            # counties, so this is a representation difference, not a guess.
            hits = by_alt.get(acct.lstrip("0")) or by_alt.get(str(int(acct))) \
                if acct.isdigit() else None
        if not hits:
            unmatched.append(acct)
        elif len(hits) == 1:
            exact.append(acct)
            if len(examples) < 5:
                examples.append({"stored_account": acct,
                                 "fdor_parcel_id": next(iter(hits))})
        else:
            ambiguous.append({"stored_account": acct,
                              "parcel_count": len(hits),
                              "parcel_ids": sorted(hits)[:4]})

    n = len(stored)
    return {
        "county": county,
        "co_no": co_no,
        "strategy_used": pulled["strategy"],
        "fgio_requests": pulled["requests"],
        "fgio_records_pulled": len(pairs),
        "fgio_records_with_alt_key": sum(1 for _, k in pairs if k is not None),
        "distinct_alt_keys": len(by_alt),
        "rows_examined": n,
        "exact_matches": len(exact),
        "ambiguous_matches": len(ambiguous),
        "unmatched": len(unmatched),
        "one_to_one_pct": round(100.0 * len(exact) / n, 1) if n else None,
        "mapping_count": len(by_alt),
        "examples": examples,                       # account -> parcel only; no PII
        "ambiguous_examples": ambiguous[:5],
        "unmatched_examples": unmatched[:5],
        "errors": pulled["errors"][:6],
    }


# --------------------------------------------------------------------------
# TX: Galveston published Parcel DBF
# --------------------------------------------------------------------------
DBF_TYPES = {"C": "character", "N": "numeric", "F": "float", "D": "date",
             "L": "logical", "M": "memo", "B": "binary/double", "I": "integer"}


def parse_dbf_header(blob: bytes) -> dict:
    """Field list + record count straight from the DBF header.

    Parsed by hand rather than with a dependency: the header layout is fixed
    and this keeps the probe free of an install step that could itself fail
    and be mistaken for the source being unavailable.
    """
    if len(blob) < 32:
        return {"error": "file shorter than a DBF header"}
    _, _, _, _, n_records, header_len, record_len = struct.unpack("<4BIHH", blob[:12])
    fields = []
    pos = 32
    while pos + 32 <= len(blob) and blob[pos] not in (0x0D, 0x00):
        raw = blob[pos:pos + 32]
        name = raw[:11].split(b"\x00")[0].decode("ascii", "replace").strip()
        ftype = chr(raw[11])
        flen = raw[16]
        fdec = raw[17]
        fields.append({"name": name, "type": ftype,
                       "type_name": DBF_TYPES.get(ftype, ftype),
                       "length": flen, "decimals": fdec})
        pos += 32
    return {"record_count": n_records, "header_length": header_len,
            "record_length": record_len, "field_count": len(fields),
            "fields": fields}


def probe_galveston_dbf() -> dict:
    """Locate, download and describe the published Parcel DBF. Read-only."""
    res = {"source_page": GALVESTON_GIS_PAGE, "candidate_urls": [],
           "download": None, "dbf": None, "errors": []}
    try:
        page = _get(GALVESTON_GIS_PAGE)
        res["source_page_status"] = page.status_code
        hrefs = re.findall(r'href=["\']([^"\']+)["\']', page.text, re.I)
        cands = [h for h in hrefs if re.search(r'\.(zip|dbf)(\?|$)', h, re.I)]
        cands = [h if h.startswith("http") else requests.compat.urljoin(GALVESTON_GIS_PAGE, h)
                 for h in cands]
        # Prefer anything that names parcels/data.
        cands.sort(key=lambda u: (0 if re.search(r'parcel|data', u, re.I) else 1, len(u)))
        res["candidate_urls"] = cands[:12]
    except Exception as exc:  # noqa: BLE001
        res["errors"].append(f"listing page: {exc!r}"[:200])
        return res

    for url in res["candidate_urls"][:4]:
        try:
            _log(f"Galveston: trying {url}")
            r = _get(url, stream=True)
            if r.status_code != 200:
                res["errors"].append(f"{url} -> HTTP {r.status_code}")
                continue
            blob = r.content
            info = {"url": url, "http_status": r.status_code,
                    "bytes": len(blob),
                    "content_type": r.headers.get("Content-Type"),
                    "filename": url.rsplit("/", 1)[-1]}
            if zipfile.is_zipfile(io.BytesIO(blob)):
                with zipfile.ZipFile(io.BytesIO(blob)) as zf:
                    names = zf.namelist()
                    info["zip_contents"] = names[:40]
                    dbfs = [n for n in names if n.lower().endswith(".dbf")]
                    if not dbfs:
                        res["errors"].append(f"{url}: zip has no .dbf")
                        continue
                    info["dbf_member"] = dbfs[0]
                    with zf.open(dbfs[0]) as fh:
                        res["dbf"] = parse_dbf_header(fh.read(65536))
            elif url.lower().endswith(".dbf") or blob[:1] in (b"\x03", b"\x30", b"\x05"):
                res["dbf"] = parse_dbf_header(blob[:65536])
            else:
                res["errors"].append(f"{url}: not a zip or dbf")
                continue
            res["download"] = info
            break
        except Exception as exc:  # noqa: BLE001
            res["errors"].append(f"{url}: {exc!r}"[:200])

    if res.get("dbf") and res["dbf"].get("fields"):
        names = [f["name"].lower() for f in res["dbf"]["fields"]]
        res["appraisal_fields_present"] = sorted(
            {w for w in WANTED_TX_FIELDS if any(w in n for n in names)})
        res["has_value_field"] = any(
            any(k in n for k in ("market", "appraised", "assessed", "value"))
            for n in names)
        res["has_year_built"] = any(
            any(k in n for k in ("yr_built", "year_built", "yrblt")) for n in names)
        res["has_owner_field"] = any("owner" in n or "name" in n for n in names)
        res["has_account_field"] = any(
            any(k in n for k in ("account", "acct", "prop_id", "propid", "geo_id"))
            for n in names)
    return res


# --------------------------------------------------------------------------
def _write_evidence_json(evidence: dict) -> None:
    (OUT_DIR / "probe_enrichment_sources.json").write_text(
        json.dumps(evidence, indent=2, default=str), encoding="utf-8")


def verdict_fl(rows: list[dict]) -> str:
    scored = [r for r in rows if r.get("rows_examined")]
    if not scored or all(r["strategy_used"] is None for r in scored):
        return "NOT_VIABLE"
    pcts = [r["one_to_one_pct"] or 0 for r in scored if r["strategy_used"]]
    if not pcts:
        return "NOT_VIABLE"
    best = max(pcts)
    if best >= 80:
        return "VIABLE"
    if best > 0:
        return "PARTIAL"
    return "NOT_VIABLE"


def verdict_tx(g: dict) -> str:
    if not g.get("dbf"):
        return "NOT_VIABLE"
    if g.get("has_account_field") and (g.get("has_value_field") or g.get("has_year_built")):
        return "VIABLE"
    if g.get("has_account_field"):
        return "PARTIAL"
    return "NOT_VIABLE"


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    started = datetime.now(timezone.utc).isoformat()
    evidence = {
        "probe": "enrichment source evidence (READ-ONLY)",
        "started_utc": started,
        "scope": "FL auction+LAFT/OTC unenriched; TX Galveston published DBF",
        "writes_performed": "none - every request in this probe is a GET",
        "fdor_api_prior_findings": {
            "exact PARCEL_ID lookup": "works, returns ALT_KEY",
            "CO_NO scan": "HTTP 400 after ~55s",
            "ALT_KEY filter": "HTTP 400 every county",
            "PHY_ADDR1 filter": "HTTP 400",
            "conclusion": "API cannot discover PARCEL_ID from a county account",
        },
        "sources": {"fl_fgio_layer": FGIO_LAYER,
                    "tx_galveston_page": GALVESTON_GIS_PAGE},
    }

    _log("reading stored accounts (SELECT only)")
    stored = fetch_stored_accounts()
    evidence["stored_account_counts"] = {
        k: (len(v) if isinstance(v, list) else v) for k, v in stored.items()}

    # Each FL county is a long paged pull (Hillsborough alone is hundreds of
    # thousands of parcels). Persist after every county so a job timeout
    # keeps the counties already measured instead of losing the whole run.
    fl_rows = []
    evidence["fl_results"] = fl_rows
    evidence["status"] = "in progress"
    _write_evidence_json(evidence)
    for county, co_no in FL_COUNTIES.items():
        accounts = stored.get(county) if isinstance(stored.get(county), list) else []
        _log(f"--- FL {county} (CO_NO={co_no}), {len(accounts)} accounts")
        row = analyse_fl_county(county, co_no, accounts)
        row["key_source"] = "stored parcel column"
        fl_rows.append(row)
        _write_evidence_json(evidence)
    live_key_runs = {}
    evidence["fl_live_keys"] = live_key_runs
    for county, cfg in FL_LIVE_KEY_COUNTIES.items():
        _log(f"--- FL {county} (CO_NO={cfg['co_no']}), live appraiser keys from {cfg['host']}")
        live = realauction_live_keys(county, cfg["host"], cfg["labels"])
        live_key_runs[county] = live
        row = analyse_fl_county(county, cfg["co_no"], live["keys"])
        row["key_source"] = f"live RealAuction {'/'.join(cfg['labels'])}"
        row["errors"] = (live["errors"] + row["errors"])[:6]
        fl_rows.append(row)
        _write_evidence_json(evidence)
    evidence["fl_verdict"] = verdict_fl(fl_rows)

    _log("--- TX Galveston DBF")
    gal = probe_galveston_dbf()
    evidence["tx_galveston"] = gal
    evidence["tx_verdict"] = verdict_tx(gal)
    evidence["finished_utc"] = datetime.now(timezone.utc).isoformat()
    evidence["status"] = "complete"
    _write_evidence_json(evidence)

    # Human-readable summary
    L = [f"# Enrichment source probe - evidence", "",
         f"Run (UTC): {started} -> {evidence['finished_utc']}",
         f"Writes performed: **none** (every request is a GET)", "",
         f"## Verdicts", "",
         f"- **FL ALT_KEY -> PARCEL_ID mapping: {evidence['fl_verdict']}**",
         f"- **TX Galveston CAD DBF: {evidence['tx_verdict']}**", "",
         "## FL results", "",
         "| County | Key source | Rows examined | FGIO pulled | Exact | Ambiguous | Unmatched | 1:1 % | Strategy |",
         "|---|---|---|---|---|---|---|---|---|"]
    for r in fl_rows:
        L.append(f"| {r['county']} | {r.get('key_source', '')} | {r['rows_examined']} | "
                 f"{r['fgio_records_pulled']} | {r['exact_matches']} | {r['ambiguous_matches']} | "
                 f"{r['unmatched']} | {r['one_to_one_pct']} | {r['strategy_used']} |")
    for r in fl_rows:
        if r["examples"]:
            L += ["", f"### {r['county']} - proof of join (account -> PARCEL_ID)", ""]
            L += [f"- `{e['stored_account']}` -> `{e['fdor_parcel_id']}`" for e in r["examples"]]
        if r["errors"]:
            L += ["", f"### {r['county']} - errors", ""] + [f"- `{e}`" for e in r["errors"]]
    L += ["", "## TX Galveston DBF", ""]
    if gal.get("download"):
        d = gal["download"]
        L += [f"- URL: `{d['url']}`", f"- HTTP: {d['http_status']}",
              f"- Filename: `{d['filename']}`  Size: {d['bytes']:,} bytes"]
        if gal.get("dbf"):
            L += [f"- Records: {gal['dbf'].get('record_count'):,}",
                  f"- Fields: {gal['dbf'].get('field_count')}", "",
                  "| Field | Type | Len |", "|---|---|---|"]
            L += [f"| {f['name']} | {f['type_name']} | {f['length']} |"
                  for f in gal["dbf"].get("fields", [])]
            L += ["", f"- account-like field: {gal.get('has_account_field')}",
                  f"- value field: {gal.get('has_value_field')}",
                  f"- year built: {gal.get('has_year_built')}",
                  f"- owner field: {gal.get('has_owner_field')}"]
    else:
        L += ["- No DBF retrieved.", ""] + [f"- `{e}`" for e in gal.get("errors", [])[:8]]
    (OUT_DIR / "probe-evidence.md").write_text("\n".join(L), encoding="utf-8")

    _log(f"FL verdict={evidence['fl_verdict']}  TX verdict={evidence['tx_verdict']}")
    _log("wrote out/probe_enrichment_sources.json and out/probe-evidence.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
