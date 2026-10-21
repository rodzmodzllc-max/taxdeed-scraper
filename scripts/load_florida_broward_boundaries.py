"""Load Broward County parcel outlines from the DOR PTO 2025 PIN file.

Manual only (.github/workflows/parcel-boundaries-broward.yml). Default mode is
dry-run: it downloads the file, matches, and prints COUNTS ONLY. Nothing is
written unless --mode apply AND --confirm APPLY are both given.

The download is the only thing this script adds. Reading, matching and
writing go through the shared Florida path
(scripts/parcel_boundary_refresh.py run_files, harvesters/boundary/fl_dor.py),
so every rule there applies (docs/parcel-boundaries.md):
- PARCELNO joins only to the record's VALIDATED NAL PARCEL_ID, exact string
  equality, after a value-free format check; listing parcels are never
  reformatted into a key;
- condominium units (use code 04) and rights-of-way (94) are never attached;
- a PARCELNO held by more than one feature, or one geometry under several
  PARCELNOs, is never associated;
- a failed download or read writes nothing; in apply mode it is recorded as a
  FAILED Broward attempt (never as the statewide source's refresh);
- nothing is deleted.

Parcel numbers are never printed.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import requests  # noqa: E402

import parcel_boundary_refresh as refresh  # noqa: E402
from harvesters.boundary import shapefile as R  # noqa: E402
from harvesters.boundary import sources as S  # noqa: E402

COUNTY = "Broward"
ENTRY = S.FL_DOR_PIN_FILES[COUNTY]
SOURCE = S.FL_DOR


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
    return R.extract_zip(zip_path, out_dir)


def run(mode: str, confirm: str, *, db=None, fetch=download, out=print) -> int:
    perm = {op: S.authorize(SOURCE, op, county=COUNTY) for op in ("fetch", "parse")}
    if mode == "apply":
        perm["store"] = S.authorize(SOURCE, "store", county=COUNTY)
    denied = {op: d.reason_code for op, d in perm.items() if not d.allowed}
    if denied:
        out(json.dumps({"status": "NOT_PERMITTED", "denied": denied}))
        return 3
    if mode == "apply" and confirm != "APPLY":
        out(json.dumps({"status": "REFUSED", "reason": "apply needs --confirm APPLY"}))
        return 2
    if db is None:
        url, key = os.environ.get("SUPABASE_URL", ""), os.environ.get("SUPABASE_SERVICE_KEY", "")
        if not (url and key):
            out("SUPABASE_URL / SUPABASE_SERVICE_KEY are not set: nothing read, nothing written")
            return 2
        db = refresh.Db(url, key)
    if not db.migration_applied():
        out("migration 034_parcel_boundaries.sql is not applied: nothing downloaded, nothing written")
        return 4
    with tempfile.TemporaryDirectory() as td:
        tdir = Path(td)
        try:
            zip_path = tdir / "pin.zip"
            fetch(ENTRY["url"], zip_path)
            out_dir = tdir / "shp"
            out_dir.mkdir()
            shp = extract_shapefile(zip_path, out_dir)
        except Exception as exc:  # noqa: BLE001 - a failed download writes nothing
            out(json.dumps({"county": COUNTY, "mode": mode, "status": "FAILED", "error": type(exc).__name__}))
            if mode == "apply":
                db.record_refresh(SOURCE.source_id, "FAILED", refresh.now_iso(), unit=COUNTY)
            return 1
        return refresh.run(SOURCE.source_id, apply=(mode == "apply"), db=db, out=out,
                           files={"county": COUNTY, "path": str(shp), "variant": ENTRY["variant"]})


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--mode", choices=["dry_run", "apply"], default="dry_run")
    ap.add_argument("--confirm", default="")
    args = ap.parse_args(argv)
    return run(args.mode, args.confirm)


if __name__ == "__main__":
    sys.exit(main())
