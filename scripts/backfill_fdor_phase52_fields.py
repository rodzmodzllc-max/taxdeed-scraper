#!/usr/bin/env python3
"""Fill-only backfill of the Phase 52 FDOR fields on rows enriched before the
field expansion shipped.

Why: enrich_property_details.py stamps a row once (fdor_enriched_at) and never
re-queries it. Rows stamped before 2026-09-17 therefore never received the
Phase 52 columns (dor_use_code was added 2026-09-08, the rest with migration
009). Measured 2026-09-22: 1,550 active FL rows (1,038 auction, 389
certificate, 123 LAFT) hold taxable_value / acreage / land_use / fdor_alt_key
on 0 rows and dor_use_code on 162.

What this does, and only this:
  - selects active FL rows stamped BEFORE a cut-off (never unstamped rows -
    those belong to the scheduled job, which this script does not replace);
  - looks each one up through the UNMODIFIED production path in
    enrich_property_details.py: lookup_fdor(), then the Santa Rosa and
    Flagler fallbacks exactly as main() orders them, and maps the answer with
    build_update_fields(). No candidate, rule, endpoint or field mapping is
    added here;
  - keeps only the five target columns, and only where the stored value is
    empty. Everything else build_update_fields() would refresh is discarded;
  - dry-run (default) writes nothing and emits a plan; apply consumes a plan
    from a dry run, re-reads each row, re-checks the target predicate and the
    emptiness of every field at write time, and PATCHes only what is still
    empty. fdor_enriched_at is never sent: the stamp already records the
    original match and this pass adds columns to it.

Note on updated_at: the database's own BEFORE UPDATE trigger
(touch_updated_at) sets updated_at = now() on every UPDATE, exactly as it
does for the scheduled job's PATCHes. This script cannot and does not try to
prevent that.
"""
from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import sys
import time
from datetime import datetime, timezone

import requests

HERE = pathlib.Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("enrich_property_details", HERE / "enrich_property_details.py")
prod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(prod)

TARGET_FIELDS = ("dor_use_code", "taxable_value", "acreage", "land_use", "fdor_alt_key")
MODE = os.environ.get("BACKFILL_MODE", "dry-run")
CUTOFF = os.environ.get("BACKFILL_CUTOFF", "2026-09-17T00:00:00Z")
LIMIT = int(os.environ.get("BACKFILL_LIMIT", "0") or 0)
PLAN_OUT = os.environ.get("BACKFILL_PLAN_OUT", "out/fdor_backfill_plan.json")
PLAN_IN = os.environ.get("BACKFILL_PLAN_IN", "")
# Same columns fetch_county_batch() gives build_update_fields(), plus the
# five targets so "already populated" is decided from the row itself.
ROW_SELECT = ",".join((
    "id", "state", "source", "county", "parcel", "address", "prop_type", "market",
    "assessed", "owner_name", "latitude", "longitude", "gone_since", "fdor_enriched_at",
    *TARGET_FIELDS,
))


def _empty(value):
    return value is None or (isinstance(value, str) and value.strip() == "")


def target_params(extra=None):
    params = {
        "select": ROW_SELECT,
        "state": "eq.FL",
        "gone_since": "is.null",
        "fdor_enriched_at": f"lt.{CUTOFF}",
        "order": "id.asc",
    }
    if extra:
        params.update(extra)
    return params


def fetch_targets():
    rows, offset, page = [], 0, 1000
    while True:
        params = target_params({"offset": str(offset), "limit": str(page)})
        resp = requests.get(f"{prod.SUPABASE_URL}/rest/v1/properties", headers=prod.HEADERS, params=params, timeout=30)
        resp.raise_for_status()
        chunk = resp.json()
        rows.extend(chunk)
        if len(chunk) < page:
            break
        offset += page
    return rows[:LIMIT] if LIMIT else rows


def production_lookup(row):
    """The exact order main() uses: FDOR, then the county-specific fallbacks."""
    county = row["county"]
    canon = prod.COUNTY_ALIASES.get(county, county)
    if canon not in prod.COUNTY_CODES:
        return None, None, None, "unmapped"
    attrs, centroid, cand = prod.lookup_fdor(county, row["parcel"])
    path = "fdor"
    if attrs is None and canon == "Santa Rosa":
        attrs, centroid, cand = prod.lookup_santa_rosa_gis(row["parcel"])
        path = "santa_rosa_gis" if attrs is not None else "fdor"
    if attrs is None and canon == "Flagler":
        attrs, centroid, cand = prod.lookup_flagler_gis(row["parcel"])
        path = "flagler_gis" if attrs is not None else "fdor"
    return attrs, centroid, cand, path


def plan_row(row):
    """Dry-run record for one row. Never writes."""
    rec = {"id": row["id"], "source": row["source"], "county": row["county"], "parcel": row.get("parcel")}
    if _empty(row.get("parcel")):
        rec.update(case="exception", reason="empty parcel")
        return rec
    try:
        attrs, centroid, cand, path = production_lookup(row)
    except requests.RequestException as e:
        rec.update(case="exception", reason=f"{type(e).__name__}: {e}"[:160])
        return rec
    if path == "unmapped":
        rec.update(case="exception", reason="county not in COUNTY_CODES")
        return rec
    if attrs is None:
        rec.update(case="no_match", path=path)
        return rec
    fields = prod.build_update_fields(row, attrs, centroid)
    gains, already, roll_empty = {}, [], []
    for f in TARGET_FIELDS:
        if not _empty(row.get(f)):
            already.append(f)
        elif not _empty(fields.get(f)):
            gains[f] = fields[f]
        else:
            roll_empty.append(f)
    strategy = "identity" if cand == (row.get("parcel") or "").strip() else "normalized"
    rec.update(case="match", path=path, strategy=strategy, matched_candidate=cand,
               gains=gains, already=already, roll_empty=roll_empty)
    return rec


def summarize(records):
    s = {"targets": len(records), "match": 0, "no_match": 0, "exception": 0, "rows_with_gain": 0,
         "gain": {f: 0 for f in TARGET_FIELDS}, "already": {f: 0 for f in TARGET_FIELDS},
         "roll_empty": {f: 0 for f in TARGET_FIELDS}, "by_strategy": {}, "by_ledger": {}, "by_county": {},
         "exceptions": []}

    def bucket(d, key):
        return d.setdefault(key, {"targets": 0, "match": 0, "rows_with_gain": 0, **{f: 0 for f in TARGET_FIELDS}})

    for r in records:
        led, cty = bucket(s["by_ledger"], r["source"]), bucket(s["by_county"], r["county"])
        led["targets"] += 1
        cty["targets"] += 1
        if r["case"] == "match":
            s["match"] += 1
            led["match"] += 1
            cty["match"] += 1
            key = f"{r['path']}:{r['strategy']}"
            s["by_strategy"][key] = s["by_strategy"].get(key, 0) + 1
            for f in r["gains"]:
                s["gain"][f] += 1
                led[f] += 1
                cty[f] += 1
            for f in r["already"]:
                s["already"][f] += 1
            for f in r["roll_empty"]:
                s["roll_empty"][f] += 1
            if r["gains"]:
                s["rows_with_gain"] += 1
                led["rows_with_gain"] += 1
                cty["rows_with_gain"] += 1
        elif r["case"] == "no_match":
            s["no_match"] += 1
        else:
            s["exception"] += 1
            s["exceptions"].append({"id": r["id"], "county": r["county"], "reason": r.get("reason")})
    return s


def print_report(title, s):
    print(f"\n=== {title} ===")
    print(f"1. Target rows: {s['targets']}")
    print(f"2. FDOR matches: {s['match']}")
    print(f"3. Rows gaining at least one field: {s['rows_with_gain']}")
    print("4. Gains per field: " + ", ".join(f"{f}={s['gain'][f]}" for f in TARGET_FIELDS))
    print("   Already populated (never touched): " + ", ".join(f"{f}={s['already'][f]}" for f in TARGET_FIELDS))
    print("   Match but roll has no value: " + ", ".join(f"{f}={s['roll_empty'][f]}" for f in TARGET_FIELDS))
    print(f"5. Rows with no match: {s['no_match']}")
    print(f"6. Exceptions: {s['exception']}")
    for e in s["exceptions"][:50]:
        print(f"   - {e['id']} [{e['county']}] {e['reason']}")
    print("7. County breakdown (targets/match/rows_with_gain + per-field gains):")
    for county, b in sorted(s["by_county"].items(), key=lambda kv: -kv[1]["targets"]):
        print(f"   {county}: {b['targets']}/{b['match']}/{b['rows_with_gain']} " +
              " ".join(f"{f}={b[f]}" for f in TARGET_FIELDS))
    print("8. Ledger breakdown:")
    for ledger, b in sorted(s["by_ledger"].items()):
        print(f"   {ledger}: {b['targets']}/{b['match']}/{b['rows_with_gain']} " +
              " ".join(f"{f}={b[f]}" for f in TARGET_FIELDS))
    print("   Matching strategy: " + ", ".join(f"{k}={v}" for k, v in sorted(s["by_strategy"].items())))
    print("9. Matching behaviour: enrich_property_details.lookup_fdor / lookup_santa_rosa_gis / "
          "lookup_flagler_gis / normalize_candidates / build_update_fields, imported unmodified; "
          "no rule, endpoint or field mapping added.")


def run_dry_run():
    rows = fetch_targets()
    print(f"targets fetched: {len(rows)} (state=FL, gone_since null, fdor_enriched_at < {CUTOFF})")
    records = []
    for row in rows:
        rec = plan_row(row)
        records.append(rec)
        print("ROW " + json.dumps(rec, separators=(",", ":")))
        time.sleep(prod.REQUEST_DELAY_SECONDS)
    s = summarize(records)
    print_report("DRY-RUN REPORT (nothing written)", s)
    plan = {"mode": "dry-run", "cutoff": CUTOFF, "generated_at": datetime.now(timezone.utc).isoformat(),
            "target_fields": TARGET_FIELDS, "summary": s,
            "rows": [r for r in records if r["case"] == "match" and r["gains"]]}
    pathlib.Path(PLAN_OUT).parent.mkdir(parents=True, exist_ok=True)
    with open(PLAN_OUT, "w", encoding="utf-8") as fh:
        json.dump(plan, fh, indent=1)
    print(f"plan written: {PLAN_OUT} ({len(plan['rows'])} rows with gains)")
    return s


def apply_plan_row(planned):
    """Write-time guard: the row must still be a target and each planned
    field must still be empty. Returns (written_fields, skipped_reason)."""
    resp = requests.get(
        f"{prod.SUPABASE_URL}/rest/v1/properties",
        headers=prod.HEADERS,
        params=target_params({"id": f"eq.{planned['id']}", "limit": "1"}),
        timeout=30,
    )
    resp.raise_for_status()
    current = resp.json()
    if not current:
        return {}, "row no longer satisfies the target predicate"
    current = current[0]
    fields = {f: v for f, v in planned["gains"].items() if f in TARGET_FIELDS and _empty(current.get(f))}
    fields = prod.drop_unavailable_columns(fields)
    if not fields:
        return {}, "every planned field already populated at write time"
    assert "fdor_enriched_at" not in fields and set(fields) <= set(TARGET_FIELDS)
    url = f"{prod.SUPABASE_URL}/rest/v1/properties?id=eq.{planned['id']}"
    headers = dict(prod.HEADERS)
    headers["Prefer"] = "return=minimal"
    resp = requests.patch(url, headers=headers, json=fields, timeout=15)
    resp.raise_for_status()
    return fields, None


def run_apply():
    if not PLAN_IN:
        sys.exit("BACKFILL_PLAN_IN is required for apply: point it at a dry-run plan file")
    with open(PLAN_IN, encoding="utf-8") as fh:
        plan = json.load(fh)
    if plan.get("cutoff") != CUTOFF or tuple(plan.get("target_fields", ())) != TARGET_FIELDS:
        sys.exit("plan cut-off / target fields do not match this run - refusing")
    planned_rows = plan["rows"]
    print(f"apply: {len(planned_rows)} planned rows from {PLAN_IN} (dry run generated {plan.get('generated_at')})")
    written, skipped, errors = [], [], []
    for planned in planned_rows:
        try:
            fields, reason = apply_plan_row(planned)
        except requests.RequestException as e:
            errors.append({"id": planned["id"], "county": planned["county"], "reason": f"{type(e).__name__}: {e}"[:160]})
            print("ERR " + json.dumps(errors[-1], separators=(",", ":")))
            time.sleep(prod.REQUEST_DELAY_SECONDS)
            continue
        if reason:
            skipped.append({"id": planned["id"], "county": planned["county"], "reason": reason})
            print("SKIP " + json.dumps(skipped[-1], separators=(",", ":")))
        else:
            rec = {"id": planned["id"], "source": planned["source"], "county": planned["county"], "written": sorted(fields)}
            written.append(rec)
            print("WROTE " + json.dumps(rec, separators=(",", ":")))
        time.sleep(prod.REQUEST_DELAY_SECONDS)
    counts = {f: sum(1 for w in written if f in w["written"]) for f in TARGET_FIELDS}
    print("\n=== APPLY REPORT ===")
    print(f"planned rows: {len(planned_rows)}; rows written: {len(written)}; skipped: {len(skipped)}; errors: {len(errors)}")
    print("values written per field: " + ", ".join(f"{f}={counts[f]}" for f in TARGET_FIELDS))
    for s in skipped[:50]:
        print(f"   skipped {s['id']} [{s['county']}]: {s['reason']}")
    for e in errors[:50]:
        print(f"   error {e['id']} [{e['county']}]: {e['reason']}")
    out = {"mode": "apply", "cutoff": CUTOFF, "plan": PLAN_IN, "applied_at": datetime.now(timezone.utc).isoformat(),
           "written": written, "skipped": skipped, "errors": errors, "counts": counts}
    pathlib.Path(PLAN_OUT).parent.mkdir(parents=True, exist_ok=True)
    with open(PLAN_OUT, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1)
    return out


def main():
    if not prod.SUPABASE_URL or not prod.SERVICE_KEY:
        sys.exit("SUPABASE_URL / SUPABASE_SERVICE_KEY are required")
    if MODE == "dry-run":
        run_dry_run()
    elif MODE == "apply":
        run_apply()
    else:
        sys.exit(f"unknown BACKFILL_MODE {MODE!r}")


if __name__ == "__main__":
    main()
