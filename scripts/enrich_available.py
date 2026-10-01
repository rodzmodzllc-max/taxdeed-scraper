#!/usr/bin/env python3
"""The all-sources AVAILABLE enrichment engine (2026-10-01).

Every active AVAILABLE property of every production state is an enrichment
target - not only newly harvested rows. For each row the engine works out:

  1. its state, county, identifiers and existing provenance;
  2. which customer-facing DIMENSIONS are filled and which are missing
     (identity, legal description, assessment, acreage, land use,
     coordinates, imagery, flood, acquisition path, acquisition contact,
     instructions, source document, source date, provenance);
  3. for each missing dimension, the sources in the unified inventory
     (harvesters/sources) able to fill it, and the outcome:
        SOURCE_FOUND            an APPROVED, accessible source covers it -
                                eligible for the next enrichment pass
        SOURCE_REVIEW_REQUIRED  only REVIEW_REQUIRED sources cover it
        SOURCE_HARD_BLOCKED     only HARD_BLOCKED sources cover it
        SOURCE_UNAVAILABLE      the APPROVED sources were refused / unreachable
        SOURCE_EMPTY            the APPROVED sources were read and do not publish it
        NO_SOURCE_FOUND         nothing in the inventory covers it
        MATCH_FAILED / MATCHED  (parcel layers) the deterministic identifier
                                match result of this run
  4. whether the row's availability is VERIFIED_AVAILABLE (approved source,
     read within STALE_DAYS) or NOT_VERIFIED_AVAILABLE (with the reason).

Modes:

  --plan       read-only: the coverage matrix (state x county), per-row gap /
               outcome counts, and the EXPECTED writes of each enricher. The
               parcel enricher runs its real queries and matches in this mode
               (reads only), so its expected writes are measured, not guessed.
  --apply      the parcel / tax-roll layers write through the shared field
               provenance precedence (a blank is filled; a stronger existing
               value is never replaced). Imagery, flood and geocoding are the
               existing runners, invoked by the workflow job right after this
               step with the same state scope.

Governance never organises the work: a REVIEW_REQUIRED source only marks its
own dimension, every other source is still used, and a source failure never
closes, hides or marks stale any AVAILABLE row. Nothing is written for a
REVIEW_REQUIRED or HARD_BLOCKED source.

Outputs out/public/available-enrichment.json (counts only - never a row
value) and a markdown summary for the job summary.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))
from harvesters.enrichment import parcels as P  # noqa: E402
from harvesters.enrichment.sources import all_sources  # noqa: E402
from harvesters.governance import states as ST  # noqa: E402
from harvesters.sources import inventory as INV  # noqa: E402

PAGE = 1000
STALE_DAYS = 14
PUBLISHABLE = {"APPROVED", "APPROVED_GRANDFATHERED"}
SELECT = ("id,state,county,source,status,parcel,case_no,address,legal_desc,assessed,market,taxable_value,land_value,"
          "improvement_value,acreage,land_use,dor_use_code,prop_type,latitude,longitude,photo_url,photo_checked_at,"
          "flood_checked_at,purchase_path_type,otc_provenance,document_url,list_url,list_as_of,source_published_at,"
          "field_provenance,last_seen_at,publication_status,source_id,harvester_source,owner_name,year_built,"
          "living_area,value_year,homestead")

# Customer dimension -> the inventory role that can fill it.
DIMENSIONS = ("identity", "legal", "assessment", "acreage", "land_use", "coordinates", "imagery", "flood",
              "acquisition", "acquisition_contact", "instructions", "source_document", "source_date", "provenance")
DIMENSION_ROLE = {"identity": "identity", "legal": "legal", "assessment": "assessment", "acreage": "acreage",
                  "land_use": "land_use", "coordinates": "coordinates", "imagery": "imagery", "flood": "flood",
                  "acquisition": "acquisition", "acquisition_contact": "acquisition", "instructions": "acquisition",
                  "source_document": "availability", "source_date": "source_date", "provenance": None}
# Dimensions that need another one first (the enricher reads it).
PREREQUISITE = {"imagery": "coordinates", "flood": "coordinates"}
PARCEL_COLUMNS = {"legal": ("legal_desc",), "assessment": ("assessed", "market", "taxable_value", "land_value"),
                  "acreage": ("acreage",), "land_use": ("land_use",), "coordinates": ("latitude",)}


def _blank(v) -> bool:
    return v is None or (isinstance(v, str) and not v.strip())


def _acq(row: dict) -> dict:
    prov = row.get("otc_provenance") or {}
    return (prov.get("acquisition") or {}) if isinstance(prov, dict) else {}


def has_dimension(row: dict, dim: str) -> bool:
    if dim == "identity":
        return not (_blank(row.get("parcel")) and _blank(row.get("case_no")))
    if dim == "legal":
        return not _blank(row.get("legal_desc"))
    if dim == "assessment":
        return any(not _blank(row.get(c)) for c in ("assessed", "market", "taxable_value", "land_value"))
    if dim == "acreage":
        return not _blank(row.get("acreage"))
    if dim == "land_use":
        return not (_blank(row.get("land_use")) and _blank(row.get("dor_use_code")))
    if dim == "coordinates":
        return not (_blank(row.get("latitude")) or _blank(row.get("longitude")))
    if dim == "imagery":
        return not _blank(row.get("photo_url"))
    if dim == "flood":
        return not _blank(row.get("flood_checked_at"))
    if dim == "acquisition":
        return not _blank(row.get("purchase_path_type"))
    if dim == "acquisition_contact":
        a = _acq(row)
        return any(not _blank(a.get(k)) for k in ("phone", "email", "office", "mailing_address", "address"))
    if dim == "instructions":
        a = _acq(row)
        prov = row.get("otc_provenance") or {}
        return bool(a.get("steps")) or not _blank(a.get("instructions")) or not _blank((prov or {}).get("purchase_instructions"))
    if dim == "source_document":
        return not (_blank(row.get("document_url")) and _blank(row.get("list_url")))
    if dim == "source_date":
        return not (_blank(row.get("list_as_of")) and _blank(row.get("source_published_at")))
    if dim == "provenance":
        fp = row.get("field_provenance")
        return isinstance(fp, dict) and bool(fp)
    raise KeyError(dim)


def imagery_checked_empty(row: dict) -> bool:
    """'' = checked, no coverage (the photo_url contract) - not a gap to retry."""
    return row.get("photo_url") == ""


def row_gaps(row: dict) -> list[str]:
    gaps = [d for d in DIMENSIONS if not has_dimension(row, d)]
    if imagery_checked_empty(row) and "imagery" in gaps:
        gaps.remove("imagery")
    return gaps


def gap_outcome(row: dict, dim: str, sources: list, *, capture_outcome: str | None = None,
                match_outcome: str | None = None) -> str:
    """The outcome vocabulary for one missing dimension of one row."""
    pre = PREREQUISITE.get(dim)
    role = DIMENSION_ROLE.get(dim)
    if role is None:
        return "SOURCE_FOUND" if any(s.may_write for s in sources) else "NO_SOURCE_FOUND"
    able = [s for s in sources if role in s.roles]
    if not able:
        return "NO_SOURCE_FOUND"
    approved = [s for s in able if s.governance == "APPROVED"]
    if match_outcome in ("UNMATCHED", "NO_IDENTIFIER"):
        return "MATCH_FAILED"
    if match_outcome == "AMBIGUOUS":
        return "MATCH_FAILED"
    if match_outcome == "SOURCE_UNAVAILABLE":
        return "SOURCE_UNAVAILABLE"
    if approved:
        accessible = [s for s in approved if s.access in ("ACCESSIBLE", "NOT_CHECKED")]
        if pre and not has_dimension(row, pre):
            return f"NEEDS_{pre.upper()}"
        if dim in ("acquisition", "acquisition_contact", "instructions") and capture_outcome in (
                "SOURCE_EMPTY", "SOURCE_UNAVAILABLE", "SOURCE_PARSE_FAILED", "NO_SOURCE_FOUND"):
            return capture_outcome
        if not accessible:
            return "SOURCE_UNAVAILABLE"
        return "SOURCE_FOUND"
    if any(s.governance == "REVIEW_REQUIRED" for s in able):
        return "SOURCE_REVIEW_REQUIRED"
    return "SOURCE_HARD_BLOCKED"


def _dt(v):
    if not v:
        return None
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def availability(row: dict, *, now: datetime, manual_only: frozenset = frozenset()) -> tuple[str, str]:
    """(VERIFIED_AVAILABLE | NOT_VERIFIED_AVAILABLE, reason). Never closes or hides a row."""
    if (row.get("publication_status") or "") not in PUBLISHABLE and row.get("publication_status") is not None:
        return "NOT_VERIFIED_AVAILABLE", f"source publication {row.get('publication_status')}"
    seen = _dt(row.get("last_seen_at"))
    src = row.get("source_id") or row.get("harvester_source") or ""
    if seen is None:
        if src in manual_only:
            return "NOT_VERIFIED_AVAILABLE", "manual-only source; no read recorded since read-stamping"
        return "NOT_VERIFIED_AVAILABLE", "no source read recorded for this row"
    if now - seen > timedelta(days=STALE_DAYS):
        return "NOT_VERIFIED_AVAILABLE", f"last source read older than {STALE_DAYS} days"
    return "VERIFIED_AVAILABLE", "read from its approved source within the freshness window"


def capture_outcomes() -> dict:
    return {(r["state"], r["county"]): r["capture_outcome"] for r in INV._csv(INV.CAPTURE_OUTCOMES_PATH)}


def coverage(rows: list[dict], *, now: datetime | None = None, match_outcomes: dict | None = None,
             inventory=None) -> dict:
    """The state x county coverage matrix + per-dimension outcome counts.
    Counts only."""
    now = now or datetime.now(timezone.utc)
    inv = INV.build_inventory() if inventory is None else inventory
    from unit_freshness import MANUAL_ONLY_SOURCES  # noqa: PLC0415
    manual = frozenset(MANUAL_ONLY_SOURCES)
    caps = capture_outcomes()
    match_outcomes = match_outcomes or {}
    units: dict = {}
    for row in rows:
        key = (row.get("state"), row.get("county"))
        u = units.get(key)
        if u is None:
            srcs = INV.sources_for(*key, inventory=inv)
            u = units[key] = {"state": key[0], "county": key[1], "available_records": 0, "_sources": srcs,
                              "with": defaultdict(int), "outcomes": defaultdict(lambda: defaultdict(int)),
                              "availability": defaultdict(int), "last_successful_read": None, "records_matched": 0,
                              "enriched": 0, "partially_enriched": 0, "unchanged_gaps": 0}
        u["available_records"] += 1
        for d in DIMENSIONS:
            if has_dimension(row, d):
                u["with"][d] += 1
        gaps = row_gaps(row)
        for d in gaps:
            mo = match_outcomes.get(row["id"]) if d in PARCEL_COLUMNS else None
            u["outcomes"][d][gap_outcome(row, d, u["_sources"], capture_outcome=caps.get(key), match_outcome=mo)] += 1
        status, _ = availability(row, now=now, manual_only=manual)
        u["availability"][status] += 1
        seen = row.get("last_seen_at")
        if seen and (u["last_successful_read"] is None or str(seen) > u["last_successful_read"]):
            u["last_successful_read"] = str(seen)
        prov = row.get("otc_provenance") or {}
        if (isinstance(prov, dict) and prov.get("source_match")) or any(
                isinstance(v, dict) and v.get("matched_parcel_id") for v in (row.get("field_provenance") or {}).values()):
            u["records_matched"] += 1
        if not gaps:
            u["enriched"] += 1
        elif len(gaps) < len(DIMENSIONS):
            u["partially_enriched"] += 1
    out = []
    for key in sorted(units):
        u = units.pop(key)
        srcs = u.pop("_sources")
        types = defaultdict(int)
        for s in srcs:
            types[s.source_type] += 1
        out.append({
            **{k: v for k, v in u.items() if k not in ("with", "outcomes", "availability")},
            "sources_discovered": len(srcs),
            "sources_accessible": sum(1 for s in srcs if s.access == "ACCESSIBLE"),
            "sources_approved": sum(1 for s in srcs if s.governance == "APPROVED"),
            "sources_review_required": sum(1 for s in srcs if s.governance == "REVIEW_REQUIRED"),
            "sources_hard_blocked": sum(1 for s in srcs if s.governance == "HARD_BLOCKED"),
            "government_sources": types["GOVERNMENT"], "document_sources": types["DOCUMENT"], "gis_sources": types["GIS"],
            "court_sources": types["COURT_PUBLIC_RECORD"], "public_notice_sources": types["PUBLIC_NOTICE"],
            "vendor_sources": types["AUCTION_VENDOR"] + types["THIRD_PARTY"], "federal_sources": types["FEDERAL_DATASET"],
            "with_acquisition_path": u["with"]["acquisition"], "with_coordinates": u["with"]["coordinates"],
            "with_legal_description": u["with"]["legal"], "with_assessment": u["with"]["assessment"],
            "with_imagery": u["with"]["imagery"], "with": dict(u["with"]),
            "gap_outcomes": {d: dict(v) for d, v in u["outcomes"].items()},
            "availability": dict(u["availability"]),
        })
    return {"generated_at": now.replace(microsecond=0).isoformat(), "units": out, "totals": _totals(out)}


def _totals(units: list[dict]) -> dict:
    t = {"states": sorted({u["state"] for u in units}), "counties": len(units),
         "available_records": sum(u["available_records"] for u in units), "with": defaultdict(int),
         "gap_outcomes": defaultdict(lambda: defaultdict(int)), "availability": defaultdict(int)}
    for u in units:
        for d, n in u["with"].items():
            t["with"][d] += n
        for d, oc in u["gap_outcomes"].items():
            for k, n in oc.items():
                t["gap_outcomes"][d][k] += n
        for k, n in u["availability"].items():
            t["availability"][k] += n
    t["with"] = dict(t["with"])
    t["gap_outcomes"] = {d: dict(v) for d, v in t["gap_outcomes"].items()}
    t["availability"] = dict(t["availability"])
    return t


# ------------------------------------------------------------ parcel enricher

def parcel_plan(rows: list[dict], fetch_json, *, write=None, recorded_at: str) -> tuple[list[dict], dict]:
    """Run every cleared parcel / tax-roll layer over the AVAILABLE rows it
    covers that miss one of its dimensions. Read-only unless `write` is given.
    Returns (per-source reports, row id -> match outcome)."""
    import enrich_statewide_parcels as ESP  # noqa: PLC0415
    reports, outcomes = [], {}
    for cfg in all_sources():
        ok, why = P.enrichment_allowed(cfg)
        if not ST.is_activated(cfg.state):
            reports.append({"source_id": cfg.source_id, "state": cfg.state, "skipped": "state not activated"})
            continue
        if not ok:
            reports.append({"source_id": cfg.source_id, "state": cfg.state, "skipped": why,
                            "governance": "REVIEW_REQUIRED"})
            continue
        dims = {d for d, cols in PARCEL_COLUMNS.items() if any(c in cfg.field_map for c in cols)
                or (d == "coordinates" and cfg.centroid)}
        targets = [r for r in rows if r.get("state") == cfg.state and cfg.covers(r.get("county") or "")
                   and any(not has_dimension(r, d) for d in dims)]
        if not targets:
            reports.append({"source_id": cfg.source_id, "state": cfg.state, "rows_considered": 0,
                            "skipped": "no AVAILABLE row misses a dimension this layer publishes"})
            continue
        mine = {}
        rep = ESP.run(cfg.state, targets, fetch_json, write=write, recorded_at=recorded_at, cfg=cfg, outcomes=mine)
        for rid, oc in mine.items():
            if outcomes.get(rid) != "MATCHED":
                outcomes[rid] = oc
        reports.append(rep)
    return reports, outcomes


def other_enricher_plan(rows: list[dict], *, storage_headroom_bytes: int | None, avg_image_bytes: int = 46000) -> dict:
    """Expected work for the existing runners (imagery, flood, geocoding),
    from the rows' own state - no request made."""
    no_img = [r for r in rows if r.get("photo_url") is None and has_dimension(r, "coordinates")]
    no_flood = [r for r in rows if _blank(r.get("flood_checked_at")) and has_dimension(r, "coordinates")]
    placeholder = lambda r: str(r.get("address") or "").startswith(("Parcel ", "Case ", "Account "))  # noqa: E731
    geocodable = [r for r in rows if not has_dimension(r, "coordinates") and not _blank(r.get("address")) and not placeholder(r)]
    cap = None if storage_headroom_bytes is None else max(0, storage_headroom_bytes // avg_image_bytes)
    by_state = lambda rs: dict(sorted(defaultdict(int, {s: sum(1 for r in rs if r["state"] == s) for s in {r["state"] for r in rs}}).items()))  # noqa: E731
    return {"imagery": {"eligible_rows": len(no_img), "by_state": by_state(no_img),
                        "storage_headroom_images": cap,
                        "expected_writes": len(no_img) if cap is None else min(len(no_img), cap),
                        "note": "USDA NAIP; 950 MB budget fails closed; deferred rows stay unchecked"},
            "flood": {"eligible_rows": len(no_flood), "by_state": by_state(no_flood), "expected_writes": len(no_flood),
                      "note": "FEMA NFHL; a failed request writes nothing"},
            "geocode": {"eligible_rows": len(geocodable), "by_state": by_state(geocodable),
                        "expected_writes": None, "note": "Census geocoder; only a verified match is written"}}


# ------------------------------------------------------------ I/O

def fetch_rows(base: str, key: str, states: list[str]) -> list[dict]:
    import urllib.parse  # noqa: PLC0415
    import enrich_statewide_parcels as ESP  # noqa: PLC0415
    hdr = {"apikey": key, "Authorization": f"Bearer {key}"}
    rows = []
    for st in states:
        offset = 0
        while True:
            q = urllib.parse.urlencode({"select": SELECT, "state": f"eq.{st}", "source": "eq.laft", "status": "eq.active",
                                        "order": "id.asc", "limit": PAGE, "offset": offset})
            page = ESP.http_json(f"{base}/rest/v1/properties?{q}", headers=hdr, timeout=120) or []
            rows += page
            if len(page) < PAGE:
                break
            offset += len(page)
    return rows


def markdown(report: dict) -> str:
    t = report["coverage"]["totals"]
    lines = [f"## AVAILABLE enrichment ({report['mode']})", "",
             f"States {', '.join(t['states'])}; {t['counties']} counties; {t['available_records']} active AVAILABLE rows.", "",
             "| Dimension | With | Missing - outcome counts |", "|---|---|---|"]
    for d in DIMENSIONS:
        lines.append(f"| {d} | {t['with'].get(d, 0)} | {t['gap_outcomes'].get(d, {})} |")
    lines += ["", f"Availability: {t['availability']}", "", "| State | County | Rows | Sources (A / R / B) | Coords | Legal | Assess | Imagery | Acq. path | Last read |",
              "|---|---|---|---|---|---|---|---|---|---|"]
    for u in report["coverage"]["units"]:
        lines.append(f"| {u['state']} | {u['county']} | {u['available_records']} | {u['sources_approved']} / "
                     f"{u['sources_review_required']} / {u['sources_hard_blocked']} | {u['with_coordinates']} | "
                     f"{u['with_legal_description']} | {u['with_assessment']} | {u['with_imagery']} | "
                     f"{u['with_acquisition_path']} | {(u['last_successful_read'] or '-')[:10]} |")
    lines += ["", "Parcel / tax-roll layers:"]
    for r in report["parcels"]:
        lines.append(f"- {r.get('source_id')} ({r.get('state')}): " + (r.get("skipped") or
                     f"considered {r.get('rows_considered')}, matched {r.get('matched')}, unmatched {r.get('unmatched')}, "
                     f"ambiguous {r.get('ambiguous')}, failed queries {r.get('failed_queries')}, rows "
                     f"{'written' if report['mode'] == 'apply' else 'to write'} {r.get('rows_written')}, fields {r.get('fields_written')}"))
    lines += ["", f"Other enrichers (expected): {json.dumps(report['other_enrichers'])}"]
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--plan", action="store_true")
    mode.add_argument("--apply", action="store_true")
    ap.add_argument("--states", default="", help="comma-separated; blank = every production state")
    ap.add_argument("--label", default="")
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    base, key = os.environ.get("SUPABASE_URL", "").rstrip("/"), os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not base or not key:
        print("skip: SUPABASE_URL / SUPABASE_SERVICE_KEY not set")
        return 0
    states = [s.strip().upper() for s in a.states.split(",") if s.strip()] or INV.production_states()
    states = [s for s in states if ST.is_activated(s)]
    rows = fetch_rows(base, key, states)
    import enrich_statewide_parcels as ESP  # noqa: PLC0415
    import field_provenance as FP  # noqa: PLC0415

    def fetch_json(url):
        time.sleep(0.3)
        return ESP.http_json(url)

    write = (lambda i, f: ESP.patch(base, key, i, f)) if a.apply else None
    parcels, outcomes = parcel_plan(rows, fetch_json, write=write, recorded_at=FP.now_iso())
    headroom = None
    try:
        import enrich_property_photos_naip as NAIP  # noqa: PLC0415
        used = NAIP.storage_used_bytes()
        headroom = None if used is None else max(0, int(NAIP.STORAGE_BUDGET_MB * 1048576) - used)
    except Exception:  # noqa: BLE001 - an unknown usage means no estimate, never a guess
        headroom = None
    if a.apply:
        rows = fetch_rows(base, key, states)       # measure the state AFTER the writes
    report = {"mode": "apply" if a.apply else "plan", "label": a.label, "states": states, "rows_examined": len(rows),
              "coverage": coverage(rows, match_outcomes=outcomes), "parcels": parcels,
              "other_enrichers": other_enricher_plan(rows, storage_headroom_bytes=headroom),
              "inventory": INV.summary(), "note": "counts only; never a row value"}
    name = f"available-enrichment{('-' + a.label) if a.label else ''}.json"
    out = Path(a.out or REPO / "out" / "public" / name)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    md = markdown(report)
    print(md)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(md + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
