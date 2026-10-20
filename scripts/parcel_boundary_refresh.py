"""Parcel boundary refresh for the approved parcel-geometry sources.

    python3 scripts/parcel_boundary_refresh.py                     # readiness only: no request, no database
    python3 scripts/parcel_boundary_refresh.py --source ut_ugrc_lir_saltlake --dry-run
    python3 scripts/parcel_boundary_refresh.py --source ut_ugrc_lir_saltlake --apply --confirm-apply

Sources and gates: harvesters/boundary/sources.py (the approval register and
permissions.authorize() decide; Florida's join waits for the Parcel Shapefiles
Readme). Plan rules: harvesters/boundary/plan.py. Storage: migration
034_parcel_boundaries.sql - NOT applied; without it --dry-run and --apply stop
before reading the source.

What a run may change:
* only rows of the one source named, for properties whose identifier matches
  exactly one feature;
* a read that is not COMPLETE (any failed or truncated page) writes no
  boundary and only counts a failed attempt - the last successful refresh
  stays as it was;
* nothing is ever deleted.

Not wired into any workflow. Output is counts only: no parcel identifier, no
geometry and no address is printed.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from harvesters.boundary import plan as boundary_plan  # noqa: E402
from harvesters.boundary.sources import SOURCES, readiness  # noqa: E402
from harvesters.enrichment.parcels import normalize_id  # noqa: E402
from harvesters.governance.source_approvals import RefreshState, apply_refresh  # noqa: E402

BATCH = 100
USER_AGENT = "taxdeed-scraper/1.0 (parcel boundaries)"


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def report_readiness(out=print) -> int:
    for sid in sorted(SOURCES):
        r = readiness(SOURCES[sid])
        state = "READY" if r["runnable"] else "NOT READY"
        out(f"{state:9} {sid}: display {'allowed' if r['display_allowed'] else 'denied (' + r['display_reason'] + ')'}"
            + ("" if r["runnable"] else f"; refresh refused: {', '.join(r['reasons'])}"))
    out("requests: 0; writes: 0")
    return 0


# --- the source read ----------------------------------------------------------

def arcgis_read(src, keys: list[str], *, opener=urllib.request.urlopen) -> tuple[str, list[dict]]:
    """Features whose identifier is one of `keys`, as GeoJSON in WGS84.
    COMPLETE only when every batch answered without error and without the
    server truncating the result; otherwise INCOMPLETE with what was read
    (which the plan then ignores)."""
    features: list[dict] = []
    for i in range(0, len(keys), BATCH):
        chunk = keys[i:i + BATCH]
        quoted = ",".join("'" + k.replace("'", "''") + "'" for k in chunk)
        qs = urllib.parse.urlencode({
            "where": f"{src.feature_key_field} IN ({quoted})",
            "outFields": f"{src.feature_key_field},{src.feature_id_field}",
            "returnGeometry": "true", "outSR": "4326", "f": "geojson",
        })
        req = urllib.request.Request(f"{src.layer_url}/query?{qs}", headers={"User-Agent": USER_AGENT})
        try:
            with opener(req, timeout=60) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except Exception:  # noqa: BLE001 - any failure makes the read incomplete
            return "INCOMPLETE", features
        if not isinstance(body, dict) or "error" in body or body.get("type") != "FeatureCollection":
            return "INCOMPLETE", features
        if body.get("exceededTransferLimit") or (body.get("properties") or {}).get("exceededTransferLimit"):
            return "INCOMPLETE", features
        features.extend(body.get("features") or [])
    return "COMPLETE", features


# --- the database ---------------------------------------------------------------

class Db:
    def __init__(self, url: str, key: str, *, opener=urllib.request.urlopen):
        self.url, self.opener = url.rstrip("/"), opener
        self.h = {"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json"}

    def _req(self, method: str, path: str, body=None):
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(f"{self.url}{path}", data=data, method=method, headers=self.h)
        with self.opener(req, timeout=120) as resp:
            raw = resp.read().decode("utf-8")
        return json.loads(raw) if raw else None

    def migration_applied(self) -> bool:
        try:
            self._req("GET", "/rest/v1/parcel_boundary_sources?select=source_id&limit=1")
            return True
        except Exception:  # noqa: BLE001 - absent table / function = not applied
            return False

    def properties(self, src) -> list[dict]:
        import rest_pages  # noqa: PLC0415 - scripts/ helper
        params = {"select": f"id,state,county,{src.record_key}", "state": f"eq.{src.state}", "status": "eq.active"}
        if src.counties:
            params["county"] = "in.(" + ",".join(f'"{c}"' for c in src.counties) + ")"
        return rest_pages.read_all(self.url, "properties", self.h, params)

    def stored(self, ids: list) -> dict:
        out = {}
        for i in range(0, len(ids), BATCH):
            q = ",".join(str(x) for x in ids[i:i + BATCH])
            for r in self._req("GET", f"/rest/v1/parcel_boundaries?select=property_id,source_id,content_sha256"
                                      f"&property_id=in.({q})") or []:
                out[r["property_id"]] = r
        return out

    def upsert(self, source_id: str, rows: list[dict]) -> dict:
        totals: dict = {}
        for i in range(0, len(rows), BATCH):
            res = self._req("POST", "/rest/v1/rpc/upsert_parcel_boundaries",
                            {"p_source_id": source_id, "p_rows": rows[i:i + BATCH]}) or {}
            for k, v in res.items():
                totals[k] = totals.get(k, 0) + int(v)
        return totals

    def record_refresh(self, source_id: str, status: str, at: str) -> None:
        self._req("POST", "/rest/v1/rpc/record_parcel_boundary_refresh",
                  {"p_source_id": source_id, "p_status": status, "p_at": at})


def run(source_id: str, *, apply: bool, db: Db, read=arcgis_read, out=print, today=None) -> int:
    src = SOURCES.get(source_id)
    if src is None:
        out(f"unknown boundary source {source_id}")
        return 2
    r = readiness(src, today=today)
    if not r["runnable"]:
        out(f"REFUSED {source_id}: {', '.join(r['reasons'])}; requests: 0; writes: 0")
        return 3
    if not db.migration_applied():
        out("migration 034_parcel_boundaries.sql is not applied: nothing read, nothing written")
        return 4
    records = db.properties(src)
    norm = lambda v: normalize_id(v, src.id_rule)  # noqa: E731
    keys = sorted({k for k in (norm(x.get(src.record_key)) for x in records) if k})
    if not keys:
        out(f"{source_id}: no active property with an identifier in scope; requests: 0; writes: 0")
        return 0
    started = now_iso()
    status, features = read(src, keys)
    stored = db.stored([x["id"] for x in records])
    plan = boundary_plan.plan_refresh(records, features, stored, src, read_status=status, observed_at=started)
    counts = {k: v for k, v in sorted(plan["counts"].items()) if v}
    out(f"{source_id}: read {status}; records {len(records)}; features {len(features)}; plan {json.dumps(counts)}")
    state = apply_refresh(RefreshState(expected_cadence="", last_successful_refresh="UNKNOWN"),
                          status=status, at=started)
    if not apply:
        out(f"dry run: would write {len(plan['rows'])}; would record refresh status {state.last_attempt_status}")
        return 0
    payload = [{k: v for k, v in row.items() if k != "change"} for row in plan["rows"]]
    result = db.upsert(source_id, payload) if payload else {}
    db.record_refresh(source_id, status, started)
    out(f"written: {json.dumps(result)}; refresh recorded as {status}"
        + ("" if status == "COMPLETE" else " (last successful refresh unchanged)"))
    return 0 if status == "COMPLETE" else 5


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", choices=sorted(SOURCES))
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="read the source and the database, write nothing")
    mode.add_argument("--apply", action="store_true", help="write boundaries (needs --confirm-apply)")
    ap.add_argument("--confirm-apply", action="store_true")
    a = ap.parse_args(argv)
    if not (a.dry_run or a.apply):
        return report_readiness()
    if not a.source:
        ap.error("--dry-run / --apply need --source")
    if a.apply and not a.confirm_apply:
        ap.error("--apply writes to the database: pass --confirm-apply as well")
    url, key = os.environ.get("SUPABASE_URL", ""), os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not (url and key):
        print("SUPABASE_URL / SUPABASE_SERVICE_KEY are not set: nothing read, nothing written")
        return 2
    return run(a.source, apply=a.apply, db=Db(url, key))


if __name__ == "__main__":
    raise SystemExit(main())
