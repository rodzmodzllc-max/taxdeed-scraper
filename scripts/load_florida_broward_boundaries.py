"""Load Broward County parcel outlines from the DOR PTO 2025 PIN file.

Manual only (.github/workflows/parcel-boundaries-broward.yml). Default mode is
dry-run: it downloads the file, matches, and prints COUNTS ONLY. Nothing is
written unless --mode apply AND --confirm APPLY are both given.

Rules (docs/parcel-boundaries.md):
- a property gets an outline only on an exact identifier match (alnum rule);
- a PARCELNO held by more than one feature is AMBIGUOUS and never associated;
- a failed or partial download writes nothing and records FAILED, never an
  empty successful read;
- nothing is deleted.

Parcel numbers are never printed.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
import tempfile
import zipfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import requests  # noqa: E402

from harvesters.boundary import geometry, plan, sources as S  # noqa: E402
from harvesters.boundary import shapefile as R  # noqa: E402
from harvesters.enrichment.parcels import normalize_id  # noqa: E402
from harvesters.governance.source_approvals import match_geometries  # noqa: E402

COUNTY = "Broward"
ENTRY = S.FL_DOR_PIN_FILES[COUNTY]
SOURCE = S.FL_DOR
DATASET = f"DOR PTO PIN {ENTRY['tax_year']}F {COUNTY}"
# Publication date of the file, from its own metadata (.shp.xml pubdate 2025-03-21).
OBSERVED_AT = "2025-03-21T00:00:00+00:00"
EXTENSIONS = (".shp", ".shx", ".dbf", ".prj", ".cpg")


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _normalize(value) -> str:
    return normalize_id(value, SOURCE.id_rule) or ""


def select_matches(features: list[dict], props: list[dict], *, observed_at: str = OBSERVED_AT,
                   dataset: str = DATASET) -> tuple[list[dict], Counter]:
    """Pure: match the property rows to the features and build the rows to write.

    `features` are the file's features already restricted to the wanted keys
    (see filter_features) and prepared by plan.prepare_features. Returns the
    upsert rows and counts of each outcome. No parcel number is returned in the
    counts.
    """
    records = [{"id": p["id"], "parcel": p["parcel"]} for p in props]
    matches = match_geometries(records, features, record_key="parcel", feature_key="PARCELNO",
                               normalize=_normalize)
    parcel_of = {p["id"]: p["parcel"] for p in props}
    counts: Counter = Counter()
    rows: list[dict] = []
    for m in matches:
        counts[m.outcome] += 1
        if m.outcome != "MATCHED":
            continue
        f = m.feature
        rows.append({
            "property_id": str(m.property_id),
            "state": "FL",
            "county": COUNTY,
            "parcel": parcel_of[m.property_id],
            "source_dataset": dataset,
            "source_feature_id": str(f["feature_id"]),
            "geometry": f["geometry"],
            "content_sha256": f["sha256"],
            "simplify_tolerance_deg": geometry.SIMPLIFY_TOLERANCE_DEG,
            "source_observed_at": observed_at,
            "match_method": "EXACT_PARCEL_ID",
        })
    return rows, counts


def filter_features(raw_features, wanted_keys: set[str]):
    """Stream the file, keep only features whose PARCELNO is a wanted key, and
    count how many features each wanted key has across the WHOLE file."""
    kept: list[dict] = []
    seen: Counter = Counter()
    total = 0
    for f in raw_features:
        total += 1
        key = _normalize((f.get("properties") or {}).get("PARCELNO"))
        if key and key in wanted_keys:
            seen[key] += 1
            kept.append(f)
    return kept, seen, total


def _supabase_env() -> tuple[str, dict]:
    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not url or not key:
        raise SystemExit("SUPABASE_URL / SUPABASE_SERVICE_KEY are not set")
    return url, {"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json"}


def fetch_properties(url: str, headers: dict) -> list[dict]:
    r = requests.get(f"{url}/rest/v1/properties", headers=headers, timeout=120, params={
        "select": "id,parcel", "state": "eq.FL", "county": f"eq.{COUNTY}", "parcel": "not.is.null"})
    r.raise_for_status()
    return [row for row in r.json() if str(row.get("parcel") or "").strip()]


def download(url: str, dest: Path) -> None:
    with requests.get(url, timeout=900, stream=True) as r:
        r.raise_for_status()
        with open(dest, "wb") as fh:
            for chunk in r.iter_content(1 << 20):
                fh.write(chunk)
    if not zipfile.is_zipfile(dest):
        raise RuntimeError("download is not a ZIP file")


def extract_shapefile(zip_path: Path, out_dir: Path) -> Path:
    """Extract only the shapefile parts, refusing any path that leaves out_dir."""
    with zipfile.ZipFile(zip_path) as z:
        shp_names = []
        for info in z.infolist():
            name = info.filename
            if name.startswith("/") or ".." in Path(name).parts:
                raise RuntimeError("unsafe path in ZIP")
            if not name.lower().endswith(EXTENSIONS):
                continue
            target = out_dir / Path(name).name
            with z.open(info) as src, open(target, "wb") as dst:
                dst.write(src.read())
            if name.lower().endswith(".shp"):
                shp_names.append(target)
    if len(shp_names) != 1:
        raise RuntimeError("expected exactly one .shp in the ZIP")
    return shp_names[0]


def run(mode: str, confirm: str) -> int:
    summary: dict = {"county": COUNTY, "mode": mode, "source_id": SOURCE.source_id}
    url, headers = _supabase_env()
    perm = {op: S.authorize(SOURCE, op, county=COUNTY) for op in ("fetch", "parse")}
    if mode == "apply":
        perm["store"] = S.authorize(SOURCE, "store", county=COUNTY)
    denied = {op: d.reason_code for op, d in perm.items() if not d.allowed}
    if denied:
        print(json.dumps({"status": "NOT_PERMITTED", "denied": denied}))
        return 3
    if mode == "apply" and confirm != "APPLY":
        print(json.dumps({"status": "REFUSED", "reason": "apply needs --confirm APPLY"}))
        return 2

    props = fetch_properties(url, headers)
    wanted = {_normalize(p["parcel"]) for p in props} - {""}
    summary["properties_in_county"] = len(props)

    try:
        with tempfile.TemporaryDirectory() as td:
            tdir = Path(td)
            zip_path = tdir / "pin.zip"
            download(ENTRY["url"], zip_path)
            out = tdir / "shp"
            out.mkdir()
            shp = extract_shapefile(zip_path, out)
            raw = R.read_pin_features(shp)
            kept, seen, total = filter_features(raw, wanted)
    except Exception as exc:  # a failed read writes nothing and is recorded as FAILED
        summary["status"] = "FAILED"
        summary["error"] = type(exc).__name__
        if mode == "apply":
            requests.post(f"{url}/rest/v1/rpc/record_parcel_boundary_refresh", headers=headers, timeout=60,
                          json={"p_source_id": SOURCE.source_id, "p_status": "FAILED", "p_at": _now()})
        print(json.dumps(summary))
        return 1

    summary["features_in_file"] = total
    good, refused = plan.prepare_features(kept, SOURCE)
    refused = {k: v for k, v in refused.items() if k != "_invalid_keys"}
    # A property key the file holds on more than one feature is AMBIGUOUS, even
    # when only one of those features survived preparation.
    ambiguous = {k for k, v in seen.items() if v > 1}
    usable = [p for p in props if _normalize(p["parcel"]) not in ambiguous]
    rows, counts = select_matches(good, usable)
    counts["AMBIGUOUS_IN_FILE"] = len(props) - len(usable)
    summary["file_features_per_property_key"] = dict(Counter(seen.values()))
    summary["refused_features"] = refused
    summary["outcomes"] = dict(counts)
    summary["rows_to_write"] = len(rows)

    if mode != "apply":
        summary["status"] = "DRY_RUN_NO_WRITES"
        print(json.dumps(summary))
        return 0

    written = {"inserted": 0, "replaced": 0, "unchanged": 0, "invalid": 0, "kept_other_source": 0,
               "feature_already_attached": 0, "no_property": 0}
    for i in range(0, len(rows), 200):
        r = requests.post(f"{url}/rest/v1/rpc/upsert_parcel_boundaries", headers=headers, timeout=300,
                          json={"p_source_id": SOURCE.source_id, "p_rows": rows[i:i + 200]})
        r.raise_for_status()
        for k, v in (r.json() or {}).items():
            if k in written:
                written[k] += int(v)
    summary["write_result"] = written
    requests.post(f"{url}/rest/v1/rpc/record_parcel_boundary_refresh", headers=headers, timeout=60,
                  json={"p_source_id": SOURCE.source_id, "p_status": "COMPLETE", "p_at": _now()}
                  ).raise_for_status()
    summary["status"] = "COMPLETE"
    print(json.dumps(summary))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--mode", choices=["dry_run", "apply"], default="dry_run")
    ap.add_argument("--confirm", default="")
    args = ap.parse_args(argv)
    return run(args.mode, args.confirm)


if __name__ == "__main__":
    sys.exit(main())
