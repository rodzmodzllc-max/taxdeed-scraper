#!/usr/bin/env python3
"""READ-ONLY evidence probe: are the unenriched Volusia / Escambia / Santa Rosa
auction rows matchable by the production FDOR rules (and therefore never
attempted), or were they attempted and missed? Also measures the certificate
rows that share those counties' quota, and tests the Pasco 19-character
identifier against the transformation the county's own appraiser links show.

Why a probe: enrich_property_details.py stamps `fdor_enriched_at` only on a
hit and leaves a miss unmarked, so the database cannot distinguish "attempted
and missed" from "never attempted". Asking the layer directly, through the
same `lookup_fdor()` / `lookup_santa_rosa_gis()` the production job uses,
settles it: a row that hits here would have been stamped by any production
attempt, so an unstamped hit is a row that was never reached.

Hard boundaries: every outbound call is a GET (Supabase `?select=` reads and
ArcGIS `query` reads). No PATCH, no schema access, no write of any kind. The
production module is imported for its lookup functions only; its `main()` is
never called.
"""
from __future__ import annotations

import importlib.util
import os
import pathlib
import re
import sys
import time
from collections import Counter, defaultdict

import requests

HERE = pathlib.Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("enrich", HERE / "enrich_property_details.py")
enrich = importlib.util.module_from_spec(spec)
spec.loader.exec_module(enrich)

COUNTIES = ["Volusia", "Escambia", "Santa Rosa", "Pasco"]
CERT_SAMPLE = int(os.environ.get("PROBE_CERT_SAMPLE", "12"))
DELAY = 0.4


def fetch(county, source_filter, limit):
    params = {
        "select": "id,source,parcel,address,case_no",
        "state": "eq.FL",
        "county": f"eq.{county}",
        "and": "(parcel.not.is.null,parcel.neq.\"\")",
        "fdor_enriched_at": "is.null",
        "gone_since": "is.null",
        "source": source_filter,
        "order": "id.asc",
        "limit": str(limit),
    }
    resp = requests.get(f"{enrich.SUPABASE_URL}/rest/v1/properties", headers=enrich.HEADERS, params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def resolve_like_production(county, parcel):
    """Mirror of main()'s lookup sequence in enrich_property_details.py,
    minus the PATCH: FDOR first, then the Santa Rosa / Flagler county-GIS
    fallbacks. Returns (hit, via, matched_candidate)."""
    attrs, centroid, cand = enrich.lookup_fdor(county, parcel)
    if attrs is not None:
        return True, "fdor", cand
    canon = enrich.COUNTY_ALIASES.get(county, county)
    if canon == "Santa Rosa":
        attrs, centroid, cand = enrich.lookup_santa_rosa_gis(parcel)
        if attrs is not None:
            return True, "santa_rosa_gis", cand
    if canon == "Flagler":
        attrs, centroid, cand = enrich.lookup_flagler_gis(parcel)
        if attrs is not None:
            return True, "flagler_gis", cand
    return False, None, None


def pasco_swapped(parcel):
    """Pasco's appraiser link encodes a dashed parcel SS-TT-RR-BBBB-BBBBB-LLLL
    as RRTTSSBBBBBBBBBLLLL (range/township/section order, no dashes) -
    measured on enriched rows: 26-24-21-0120-00000-00B1 <-> 21242601200000000B1,
    18-26-16-0400-00004-014A <-> 162618040000004014A. The 19-character values
    stored for the 7 unenriched rows are that appraiser key, so the layer's
    PARCEL_ID should be the dashed form with the first and third pairs swapped.
    Returns (swapped_dashed, naive_dashed) so the run reports both."""
    p = parcel.strip()
    if len(p) != 19 or "-" in p:
        return None, None
    rr, tt, ss, blk, sub, lot = p[0:2], p[2:4], p[4:6], p[6:10], p[10:15], p[15:19]
    return f"{ss}-{tt}-{rr}-{blk}-{sub}-{lot}", f"{rr}-{tt}-{ss}-{blk}-{sub}-{lot}"


def fdor_exact(county, candidate):
    """One exact PARCEL_ID lookup, bypassing normalize_candidates()."""
    co_no = enrich.COUNTY_CODES[enrich.COUNTY_ALIASES.get(county, county)]
    safe = candidate.replace("'", "''")
    params = {
        "where": f"PARCEL_ID='{safe}' AND CO_NO={co_no}",
        "outFields": "PARCEL_ID,PHY_ADDR1,PHY_CITY,JV",
        "returnGeometry": "false",
        "f": "json",
    }
    resp = requests.get(enrich.FDOR_ENDPOINT, params=params, timeout=20)
    resp.raise_for_status()
    feats = resp.json().get("features", [])
    return feats[0]["attributes"] if feats else None


def main():
    print("# FDOR starvation probe (read-only)\n")
    verdict = {}
    for county in COUNTIES:
        print(f"\n## {county}")
        auction = fetch(county, "in.(auction,laft)", 500)
        certs = fetch(county, "eq.certificate", CERT_SAMPLE)
        results = defaultdict(Counter)
        for group, rows in (("auction/laft", auction), (f"certificate (first {CERT_SAMPLE} by id)", certs)):
            print(f"\n### {group}: {len(rows)} rows")
            for row in rows:
                parcel = row["parcel"]
                try:
                    hit, via, cand = resolve_like_production(county, parcel)
                except requests.RequestException as e:
                    results[group]["error"] += 1
                    print(f"- ERROR {row['source']} {parcel!r}: {e}")
                    time.sleep(DELAY)
                    continue
                results[group]["hit" if hit else "miss"] += 1
                tag = f"HIT via {via} as {cand!r}" if hit else "miss"
                print(f"- {row['source']} {parcel!r} (case {row.get('case_no')}): {tag}")
                time.sleep(DELAY)
            print(f"  -> {dict(results[group])}")
        verdict[county] = {k: dict(v) for k, v in results.items()}

        if county == "Pasco":
            print("\n### Pasco 19-character identifiers: proposed swap vs naive re-dash")
            for row in auction:
                swapped, naive = pasco_swapped(row["parcel"])
                if not swapped:
                    continue
                try:
                    a = fdor_exact(county, swapped)
                    time.sleep(DELAY)
                    b = fdor_exact(county, naive)
                    time.sleep(DELAY)
                except requests.RequestException as e:
                    print(f"- ERROR {row['parcel']!r}: {e}")
                    continue
                print(f"- {row['parcel']!r} -> swapped {swapped!r}: {'HIT ' + str(a) if a else 'miss'} | naive {naive!r}: {'HIT' if b else 'miss'}")

    print("\n## Verdict inputs")
    for county, groups in verdict.items():
        print(f"- {county}: {groups}")
    print(
        "\nReading: an auction/laft row that HITS here would have been stamped by any production "
        "attempt (the stamp is written in the same PATCH as the match). Unstamped hits are rows the "
        "production job never reached. Certificate misses show what consumes the county's miss streak."
    )


if __name__ == "__main__":
    main()
