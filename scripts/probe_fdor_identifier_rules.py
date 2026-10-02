#!/usr/bin/env python3
"""READ-ONLY, value-free probe: for Florida rows the FDOR enricher has not
matched, which exact identifier transform (if any) resolves to exactly ONE
feature of the statewide FDOR parcel layer in the same county?

Why: the deeds job's own report lists the unmatched identifier SHAPES per
county (e.g. Brevard d7, Hillsborough d10, Suwannee d9-d11, Leon d6A1d4) and
every PARCEL_ID spelling enrich_property_details.normalize_candidates() tries
has already missed. Some counties publish an ACCOUNT number that the layer
carries as ALT_KEY (Escambia's proven rule); others may simply be absent from
the layer (a newer split, a roll-year gap). A format rule is added to the
production enricher only when this probe shows a transform that resolves
uniquely for the county's rows and never ambiguously.

Transforms tried, each an exact equality, county-scoped (CO_NO), two-record
limit so "exactly one" is distinguishable from "more than one":
  alt_digits   ALT_KEY = the identifier's digits
  alt_raw      ALT_KEY = the identifier as stored
  pid_digits   PARCEL_ID = the identifier's digits
For an alt_* hit the feature's own ALT_KEY must equal the value asked for.

Output is counts only (rows probed, unique / ambiguous / miss per transform,
and the shape of the layer's PARCEL_ID on unique hits - never a value), so
it is safe for a public log. Every outbound call is a GET.

    python3 scripts/probe_fdor_identifier_rules.py [--county Brevard ...] [--per-county 12]
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import sys
import time
import urllib.parse
from collections import Counter, defaultdict
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("enrich", HERE / "enrich_property_details.py")
enrich = importlib.util.module_from_spec(spec)
spec.loader.exec_module(enrich)

DEFAULT_COUNTIES = ["Brevard", "Hillsborough", "Suwannee", "Leon", "Pinellas", "Lake", "Lee", "Pasco", "Miami-Dade",
                    "Volusia", "Monroe", "Citrus", "Osceola", "Walton", "Martin", "Hernando", "Alachua", "Santa Rosa"]
DELAY = 0.35


def transforms(parcel: str) -> dict[str, tuple[str, str]]:
    """name -> (layer field, value). Only exact spellings derived from the
    stored identifier; an empty digit string is no candidate."""
    p = str(parcel or "").strip()
    digits = re.sub(r"\D", "", p)
    out = {}
    if digits:
        out["alt_digits"] = ("ALT_KEY", digits)
        out["pid_digits"] = ("PARCEL_ID", digits)
    if p and p != digits:
        out["alt_raw"] = ("ALT_KEY", p)
    return out


def fetch_unmatched(county: str, per_county: int) -> list[dict]:
    base, key = os.environ["SUPABASE_URL"].rstrip("/"), os.environ["SUPABASE_SERVICE_KEY"]
    q = {"select": "id,county,source,parcel", "state": "eq.FL", "county": f"eq.{county}", "fdor_enriched_at": "is.null",
         "parcel": "not.is.null", "order": "id", "limit": str(per_county)}
    r = requests.get(f"{base}/rest/v1/properties?{urllib.parse.urlencode(q)}",
                     headers={"apikey": key, "Authorization": f"Bearer {key}"}, timeout=60)
    r.raise_for_status()
    return [row for row in r.json() if str(row.get("parcel") or "").strip()]


def probe(counties: list[str], per_county: int) -> dict:
    report: dict = {}
    for county in counties:
        co_no = enrich.COUNTY_CODES.get(enrich.COUNTY_ALIASES.get(county, county))
        if co_no is None:
            report[county] = {"skipped": "no CO_NO"}
            continue
        rows = fetch_unmatched(county, per_county)
        tally: dict[str, Counter] = defaultdict(Counter)
        shapes: Counter = Counter()
        row_shapes: Counter = Counter()
        unavailable = 0
        for row in rows:
            row_shapes[enrich.identifier_shape(row["parcel"])] += 1
            for name, (field, value) in transforms(row["parcel"]).items():
                try:
                    feats = enrich._query_layer(f"{field}='{enrich._sql_str(value)}' AND CO_NO={co_no}")
                except Exception:   # noqa: BLE001 - counted, never raised: a probe must finish
                    unavailable += 1
                    continue
                finally:
                    time.sleep(DELAY)
                if len(feats) > 1:
                    tally[name]["ambiguous"] += 1
                elif feats:
                    attrs = feats[0].get("attributes", {}) or {}
                    if field == "ALT_KEY" and re.sub(r"\s", "", str(attrs.get("ALT_KEY") or "")) != value:
                        tally[name]["mismatch"] += 1
                        continue
                    tally[name]["unique"] += 1
                    shapes[f"{name}->{enrich.identifier_shape(attrs.get('PARCEL_ID'))}"] += 1
                else:
                    tally[name]["miss"] += 1
        report[county] = {"co_no": co_no, "rows_probed": len(rows), "row_shapes": dict(row_shapes),
                          "transforms": {k: dict(v) for k, v in sorted(tally.items())},
                          "unique_hit_parcel_id_shapes": dict(shapes), "layer_unavailable": unavailable}
    return report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--county", action="append")
    ap.add_argument("--per-county", type=int, default=12)
    a = ap.parse_args(argv)
    if not os.environ.get("SUPABASE_URL") or not os.environ.get("SUPABASE_SERVICE_KEY"):
        print("SUPABASE_URL / SUPABASE_SERVICE_KEY not set - nothing probed")
        return 0
    report = probe(a.county or DEFAULT_COUNTIES, a.per_county)
    for county, r in report.items():
        print(f"{county}: {json.dumps(r, sort_keys=True)}")
    Path("out/public").mkdir(parents=True, exist_ok=True)
    Path("out/public/fdor-identifier-probe.json").write_text(json.dumps(report, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
