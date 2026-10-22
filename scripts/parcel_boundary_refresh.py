"""Parcel boundary refresh for the approved parcel-geometry sources.

    python3 scripts/parcel_boundary_refresh.py                     # readiness only: no request, no database
    python3 scripts/parcel_boundary_refresh.py --source ut_ugrc_lir_saltlake --dry-run
    python3 scripts/parcel_boundary_refresh.py --source ut_ugrc_lir_saltlake --apply --confirm-apply
    python3 scripts/parcel_boundary_refresh.py --source fl_dor_pto_parcel_gis --county Leon \
        --files /path/to/leon_pin.zip --dry-run          # a DOR county PIN shapefile a person downloaded

Sources and gates: harvesters/boundary/sources.py (the approval register and
permissions.authorize() decide). Florida DOR files and their join rules:
harvesters/boundary/fl_dor.py. Plan rules: harvesters/boundary/plan.py. Storage: migrations
034_parcel_boundaries.sql and (for a files source) 035_parcel_boundary_county_refresh.sql;
without them --dry-run and --apply stop before reading the source.

What a run may change:
* only rows of the one source named, for properties whose identifier matches
  exactly one feature;
* a read that is not COMPLETE (any failed or truncated page) writes no
  boundary and only counts a failed attempt - the last successful refresh
  stays as it was;
* nothing is ever deleted.

Called by the manual Broward workflow (scripts/load_florida_broward_boundaries.py,
.github/workflows/parcel-boundaries-broward.yml); no schedule runs it. Output is
counts only: no parcel identifier, no geometry and no address is printed.
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

from harvesters.boundary import fl_dor  # noqa: E402
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

    def migration_applied(self, per_county: bool = False) -> bool:
        """034 (boundary storage) is present; with per_county, 035 as well (the
        per-county refresh units a files source records into)."""
        probes = ["/rest/v1/parcel_boundary_sources?select=source_id&limit=1"]
        if per_county:
            probes.append("/rest/v1/parcel_boundary_refresh_units?select=source_id&limit=1")
        try:
            for path in probes:
                self._req("GET", path)
            return True
        except Exception:  # noqa: BLE001 - absent table / function = not applied
            return False

    def properties(self, src, county: str | None = None, source: str | None = None) -> list[dict]:
        import rest_pages  # noqa: PLC0415 - scripts/ helper
        if src.location == "files":
            # Florida: the join key is derived from field_provenance; the use
            # code decides the condominium / right-of-way exclusions.
            select = "id,state,county,parcel,dor_use_code,field_provenance,latitude,longitude"
        else:
            select = f"id,state,county,{src.record_key}"
        params = {"select": select, "state": f"eq.{src.state}", "status": "eq.active"}
        if source:
            # One ledger (e.g. laft = Available) or a comma-separated set of them.
            ledgers = [x.strip() for x in str(source).split(",") if x.strip()]
            params["source"] = f"eq.{ledgers[0]}" if len(ledgers) == 1 else "in.(" + ",".join(ledgers) + ")"
        if county:
            params["county"] = f'eq.{county}'
        elif src.counties:
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

    def record_refresh(self, source_id: str, status: str, at: str, unit: str | None = None,
                       dataset: str | None = None, dataset_date: str | None = None) -> None:
        body = {"p_source_id": source_id, "p_status": status, "p_at": at}
        if unit:
            body.update({"p_unit": unit, "p_dataset": dataset, "p_dataset_date": dataset_date})
        self._req("POST", "/rest/v1/rpc/record_parcel_boundary_refresh", body)


def run_files(src, *, apply: bool, db, out, county: str = "", path: str = "", variant: str = "PIN",
              allow_par_geometry: bool = False, source: str | None = None, listing_join: bool = False) -> int:
    """One Florida DOR county shapefile. Nothing is written unless the file
    read COMPLETE; validated-id records also need the county's identifier
    format to match, listing-joined records (listing_join) need their own
    point inside the polygon. A failed, refused or unvalidated read only
    records the attempt. `source` limits the records to one ledger."""
    if not (county and path):
        out("a files source needs --county and --files: nothing read, nothing written")
        return 2
    started = now_iso()
    rows = db.properties(src, county, source=source) if source else db.properties(src, county)
    records, excluded = fl_dor.prepare_records(rows, county, listing_join=listing_join)
    validated = [r for r in records if r["join_method"] == fl_dor.METHOD_VALIDATED]
    listing = [r for r in records if r["join_method"] == fl_dor.METHOD_LISTING]
    read = fl_dor.read_county(path, county, variant=variant, allow_par_geometry=allow_par_geometry,
                              keys={r["nal_parcel_id"] for r in validated},
                              listing_keys={r["listing_key"] for r in listing} if listing_join else None)
    status, note = read.status, read.reason
    if status == "COMPLETE" and validated:
        ok, why = fl_dor.format_check(validated, read.features, read.identifier_shapes)
        if not ok and not listing:
            status, note = "JOIN_NOT_VALIDATED", why
        elif not ok:
            # The validated ids do not look like this file's PARCELNO: they are
            # not joined; listing-joined records still need their own point.
            records, note = listing, why
            excluded["JOIN_FORMAT_MISMATCH"] = len(validated)
    if status == "COMPLETE":
        records, resolved = fl_dor.resolve_listing_keys(records, read.features)
        # Ambiguity before distance: a key on several file records is never joined.
        records, duplicated = fl_dor.reject_duplicate_keys(records, read.duplicate_keys)
        read.features, located = fl_dor.location_check(records, read.features)
        records, confirmed = fl_dor.confirm_listing_points(records, read.features)
        read.counts = {**read.counts, **resolved, **duplicated, **located, **confirmed}
    plan = boundary_plan.plan_refresh(records, read.features if status == "COMPLETE" else [], db.stored(
        [x["id"] for x in records]) if status == "COMPLETE" else {}, src, read_status=status, observed_at=started,
        dataset=read.dataset or None, dataset_date=read.dataset_date)
    counts = {k: v for k, v in sorted({**read.counts, **plan["counts"]}.items()) if v}
    out(f"{src.source_id} [{county}]: read {status}{' (' + note + ')' if note else ''}; records {len(rows)} "
        f"(joinable {len(validated) + len(listing)}, not joinable {json.dumps(dict(sorted(excluded.items())))}); "
        f"features {len(read.features)}; plan {json.dumps(counts)}")
    if not apply:
        out(f"dry run: would write {len(plan['rows'])}; would record {county} as {status}")
        return 0
    payload = [{k: v for k, v in row.items() if k != "change"} for row in plan["rows"]]
    result = db.upsert(src.source_id, payload) if payload else {}
    db.record_refresh(src.source_id, status, started, unit=county, dataset=read.dataset or None,
                      dataset_date=read.dataset_date)
    out(f"written: {json.dumps(result)}; {county} recorded as {status}"
        + ("" if status == "COMPLETE" else " (its last successful refresh unchanged)"))
    return 0 if status == "COMPLETE" else 5


def run(source_id: str, *, apply: bool, db: Db, read=arcgis_read, out=print, today=None, files: dict | None = None) -> int:
    src = SOURCES.get(source_id)
    if src is None:
        out(f"unknown boundary source {source_id}")
        return 2
    r = readiness(src, today=today)
    if not r["runnable"]:
        out(f"REFUSED {source_id}: {', '.join(r['reasons'])}; requests: 0; writes: 0")
        return 3
    if not db.migration_applied(per_county=src.location == "files"):
        out("migrations 034_parcel_boundaries.sql" + (" and 035_parcel_boundary_county_refresh.sql"
                                                     if src.location == "files" else "")
            + " are not both applied: nothing read, nothing written" if src.location == "files"
            else "migration 034_parcel_boundaries.sql is not applied: nothing read, nothing written")
        return 4
    if src.location == "files":
        return run_files(src, apply=apply, db=db, out=out, **(files or {}))
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
    ap.add_argument("--county", default="", help="files sources: the county the file belongs to")
    ap.add_argument("--files", default="", help="files sources: a county shapefile (.zip or .shp with siblings)")
    ap.add_argument("--variant", default="PIN", choices=fl_dor.VARIANTS)
    ap.add_argument("--records-source", default="", choices=["", "laft", "auction", "certificate"],
                    help="files sources: only records of this ledger (laft = Available)")
    ap.add_argument("--listing-join", action="store_true",
                    help="files sources: also join on the listing parcel number, separators ignored, "
                         "only when the record's own point lies inside the polygon")
    ap.add_argument("--allow-par-geometry", action="store_true",
                    help="read a PAR file's geometry (its attributes are never decoded)")
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
    return run(a.source, apply=a.apply, db=Db(url, key),
               files={"county": a.county, "path": a.files, "variant": a.variant,
                      "allow_par_geometry": a.allow_par_geometry, "source": a.records_source or None,
                      "listing_join": a.listing_join})


if __name__ == "__main__":
    raise SystemExit(main())
