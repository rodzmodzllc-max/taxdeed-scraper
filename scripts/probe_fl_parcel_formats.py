#!/usr/bin/env python3
"""READ-ONLY probe: why do same-format Florida parcels miss FDOR?

For each county whose auction/LAFT rows are partly enriched under the SAME
parcel shape (Lee, Volusia, Miami-Dade, Leon, Escambia, Pinellas, Lake,
Pasco, Citrus), take a few live unenriched parcels and ask the FDOR layer:

  1. exact   - every candidate scripts/enrich_property_details.py would try,
               with the same `PARCEL_ID='x' AND CO_NO=n` filter;
  2. like    - `PARCEL_ID LIKE 'x%'` for the first candidates, which catches
               a stored value with trailing characters/whitespace;
  3. prefix  - `PARCEL_ID LIKE '<short prefix>%'`, up to 5 neighbours, to see
               the county's real PARCEL_ID shape next to ours;
Returned PARCEL_IDs are printed with repr() so whitespace is visible.
GET only; the one Supabase read is `select=parcel,address,source`.
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import sys
import time

import requests

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from enrich_property_details import (  # noqa: E402  (production rules, not a copy)
    COUNTY_ALIASES, COUNTY_CODES, FDOR_ENDPOINT, normalize_candidates,
)

OUT_DIR = HERE / "../out"
SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")
UA = {"User-Agent": "taxdeed-scraper-probe/1.0 (read-only parcel-format probe)"}
COUNTIES = ["Lee", "Volusia", "Miami-Dade", "Leon", "Escambia", "Pinellas", "Lake", "Pasco", "Citrus"]
PER_COUNTY = 5
DELAY = 0.3


def _log(m):
    print(f"[fmt] {m}", flush=True)


def fdor(where: str, extra: dict | None = None) -> dict:
    params = {"where": where, "outFields": "PARCEL_ID,ASMNT_YR,CO_NO,PHY_ADDR1",
              "returnGeometry": "false", "resultRecordCount": 5, "f": "json"}
    params.update(extra or {})
    try:
        r = requests.get(FDOR_ENDPOINT, params=params, headers=UA, timeout=25)
    except requests.RequestException as exc:
        time.sleep(DELAY)
        return {"error": f"{type(exc).__name__}"}
    time.sleep(DELAY)
    try:
        d = r.json()
    except ValueError:
        return {"error": f"non-JSON HTTP {r.status_code}"}
    if "error" in d:
        return {"error": json.dumps(d["error"])[:140]}
    if "count" in d:
        return {"count": d["count"]}
    return {"hits": [{"PARCEL_ID": f["attributes"].get("PARCEL_ID"), "ASMNT_YR": f["attributes"].get("ASMNT_YR"),
                      "PHY_ADDR1": f["attributes"].get("PHY_ADDR1")} for f in d.get("features", [])]}


def stored_unenriched(county: str) -> list[dict]:
    url = (f"{SUPABASE_URL}/rest/v1/properties?select=parcel,address,source"
           f"&state=eq.FL&county=eq.{requests.utils.quote(county)}&source=in.(auction,laft)"
           f"&fdor_enriched_at=is.null&gone_since=is.null&parcel=not.is.null&order=updated_at.desc&limit=40")
    r = requests.get(url, headers={**UA, "apikey": SERVICE_KEY, "Authorization": f"Bearer {SERVICE_KEY}"}, timeout=30)
    r.raise_for_status()
    rows = [x for x in r.json() if (x.get("parcel") or "").strip()]
    seen, out = set(), []
    for x in rows:
        if x["parcel"] not in seen:
            seen.add(x["parcel"])
            out.append(x)
    return out[:PER_COUNTY]


def short_prefixes(candidate: str) -> list[str]:
    alnum = re.sub(r"[^A-Za-z0-9]", "", candidate)
    out = []
    if "-" in candidate:
        parts = candidate.split("-")
        out.append("-".join(parts[:3]) + "-")  # dashed STR groups as stored
    out.append(alnum[:6])
    return list(dict.fromkeys(p for p in out if len(p) >= 4))


def main() -> int:
    OUT_DIR.mkdir(exist_ok=True)
    if not SUPABASE_URL or not SERVICE_KEY:
        print("SUPABASE_URL / SUPABASE_SERVICE_KEY not set", file=sys.stderr)
        return 1
    evidence = {}
    for county in COUNTIES:
        co_no = COUNTY_CODES.get(COUNTY_ALIASES.get(county, county))
        # No county-wide count: `CO_NO=n` alone is the scan shape the layer
        # is already known to hang on (timed out at 30 s on the first run).
        entry = {"co_no": co_no, "parcels": []}
        _log(f"=== {county} (CO_NO={co_no})")
        for row in stored_unenriched(county):
            parcel = row["parcel"].strip()
            cands = normalize_candidates(parcel)
            rec = {"stored": parcel, "source": row["source"], "address": row.get("address"),
                   "candidates": cands, "exact": {}, "like_self": {}, "prefix": {}}
            for c in cands:
                safe = c.replace("'", "''")
                rec["exact"][c] = fdor(f"PARCEL_ID='{safe}' AND CO_NO={co_no}")
                if rec["exact"][c].get("hits"):
                    break
            exact_hit = any(v.get("hits") for v in rec["exact"].values())
            if not exact_hit:
                for c in cands[:2]:
                    safe = c.replace("'", "''")
                    rec["like_self"][c] = fdor(f"PARCEL_ID LIKE '{safe}%' AND CO_NO={co_no}")
                for p in short_prefixes(cands[0]):
                    rec["prefix"][p] = fdor(f"PARCEL_ID LIKE '{p}%' AND CO_NO={co_no}")
            entry["parcels"].append(rec)
            _log(f"{county} {parcel!r}: exact={'HIT' if exact_hit else 'miss'}"
                 + ("" if exact_hit else f" like_self={[repr(h['PARCEL_ID']) for v in rec['like_self'].values() for h in v.get('hits', [])][:3]}"
                                        f" prefix={[repr(h['PARCEL_ID']) for v in rec['prefix'].values() for h in v.get('hits', [])][:5]}"))
        evidence[county] = entry
    (OUT_DIR / "probe_fl_parcel_formats.json").write_text(json.dumps(evidence, indent=2, default=str))
    L = ["# FL parcel-format probe", ""]
    for county, e in evidence.items():
        L += [f"## {county} (CO_NO={e['co_no']})", ""]
        for rec in e["parcels"]:
            hit = [c for c, v in rec["exact"].items() if v.get("hits")]
            L.append(f"- stored `{rec['stored']}` ({rec['source']}): exact **{'HIT via ' + hit[0] if hit else 'miss'}**")
            if not hit:
                for c, v in rec["like_self"].items():
                    L.append(f"  - LIKE `{c}%` -> {[repr(h['PARCEL_ID']) for h in v.get('hits', [])] or v.get('error')}")
                for p, v in rec["prefix"].items():
                    L.append(f"  - prefix `{p}%` -> {[(repr(h['PARCEL_ID']), h['ASMNT_YR']) for h in v.get('hits', [])] or v.get('error')}")
        L.append("")
    (OUT_DIR / "probe-fl-parcel-formats.md").write_text("\n".join(L))
    print("\n".join(L))
    return 0


if __name__ == "__main__":
    sys.exit(main())
