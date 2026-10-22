"""Load parcel outlines for Florida AVAILABLE (Lands Available) properties from
the DOR PTO county PIN shapefiles.

Manual only (.github/workflows/parcel-boundaries-florida-available.yml).
Default mode is dry-run: it lists the counties with active Available
properties, downloads each county's PIN file, matches, and prints COUNTS ONLY.
Nothing is written unless --mode apply AND --confirm APPLY are both given.

Which file: the county's file in the DOR PTO Data Portal folder
"Map Data/<year>F/<year>F PIN", read from the portal's own folder listing
(never a guessed URL); condominium files are never used.

Which records: active Florida properties of the Available ledger
(properties.source = 'laft') only - auctions and certificates are not read.

How a record is joined (harvesters/boundary/fl_dor.py, chosen by the product
owner on 2026-10-22): its validated NAL PARCEL_ID equal to PARCELNO, or its
listing parcel number with separators ignored equal to exactly one PARCELNO
in the county file AND its own stored point inside that polygon. Condominium
units and rights-of-way are never joined; stacked and multi-parcel polygons
are never attached.

Every county is its own refresh: a failed download or read writes nothing for
that county and, in apply mode, is recorded as that county's failed attempt;
the other counties go on. Nothing is deleted. Parcel numbers are never printed.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import requests  # noqa: E402

import parcel_boundary_refresh as refresh  # noqa: E402
from harvesters.boundary import fl_dor  # noqa: E402
from harvesters.boundary import shapefile as R  # noqa: E402
from harvesters.boundary import sources as S  # noqa: E402

SOURCE = S.FL_DOR
AVAILABLE = "laft"
PORTAL = "https://floridarevenue.com/property/dataportal"
FOLDER = "/property/dataportal/Documents/PTO Data Portal/Map Data/{year}F/{year}F PIN"
USER_AGENT = "taxdeed-scraper/1.0 (parcel boundaries)"


def file_stem(county: str) -> str:
    """The portal's own file-name stem for a county: lower case, letters only
    (palmbeach, miamidade, stlucie, indianriver)."""
    return re.sub(r"[^a-z]", "", county.lower())


def list_pin_files(year: int, *, get=requests.get) -> dict:
    """county -> file name, from the portal's folder listing. A county whose
    file is missing, or appears more than once, is left out (reported by the
    caller as NO_COUNTY_FILE); condominium files are never used."""
    folder = FOLDER.format(year=year)
    url = (f"{PORTAL}/_api/web/GetFolderByServerRelativeUrl('{urllib.parse.quote(folder)}')/Files"
           "?$select=Name")
    resp = get(url, headers={"Accept": "application/json;odata=nometadata", "User-Agent": USER_AGENT}, timeout=60)
    resp.raise_for_status()
    names = [f["Name"] for f in resp.json().get("value", [])]
    by_stem: dict = {}
    for name in names:
        low = name.lower()
        if "condo" in low or not low.endswith(".zip"):
            continue
        m = re.match(rf"^([a-z]+)_{year}pin(\.shp)?\.zip$", low)
        if m:
            by_stem.setdefault(m.group(1), []).append(name)
    out = {}
    for county in fl_dor.COUNTY_CODES:
        hits = by_stem.get(file_stem(county), [])
        if len(hits) == 1:
            out[county] = hits[0]
    return out


def file_url(year: int, name: str) -> str:
    return "https://floridarevenue.com" + urllib.parse.quote(FOLDER.format(year=year) + "/" + name)


def download(url: str, dest: Path) -> None:
    with requests.get(url, timeout=1800, stream=True, headers={"User-Agent": USER_AGENT}) as r:
        r.raise_for_status()
        with open(dest, "wb") as fh:
            for chunk in r.iter_content(1 << 20):
                fh.write(chunk)


def available_counties(db) -> dict:
    """county -> number of active Florida Available properties."""
    import rest_pages  # noqa: PLC0415
    rows = rest_pages.read_all(db.url, "properties", db.h,
                               {"select": "id,county", "state": "eq.FL", "source": f"eq.{AVAILABLE}",
                                "status": "eq.active"})
    counts: dict = {}
    for r in rows:
        if r.get("county"):
            counts[r["county"]] = counts.get(r["county"], 0) + 1
    return counts


def run(mode: str, confirm: str, *, year: int, only=None, db=None, list_files=list_pin_files, fetch=download,
        counties_of=available_counties, out=print) -> int:
    perm = {op: S.authorize(SOURCE, op) for op in ("fetch", "parse")}
    if mode == "apply":
        perm["store"] = S.authorize(SOURCE, "store")
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
    if not db.migration_applied(per_county=True):
        out("migrations 034_parcel_boundaries.sql and 035_parcel_boundary_county_refresh.sql are not both applied: "
            "nothing downloaded, nothing written")
        return 4
    counties = counties_of(db)
    if only:
        counties = {c: n for c, n in counties.items() if c in only}
    files = list_files(year)
    summary = {"year": year, "mode": mode, "counties": len(counties), "complete": 0, "failed": 0, "no_file": 0}
    rc = 0
    for county in sorted(counties):
        name = files.get(county)
        if not name:
            summary["no_file"] += 1
            out(json.dumps({"county": county, "status": "NO_COUNTY_FILE", "records": counties[county]}))
            if mode == "apply":
                db.record_refresh(SOURCE.source_id, "FAILED", refresh.now_iso(), unit=county)
            continue
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / name
            try:
                fetch(file_url(year, name), path)
            except Exception as exc:  # noqa: BLE001 - one county's failed download writes nothing for it
                summary["failed"] += 1
                out(json.dumps({"county": county, "status": "FAILED", "error": type(exc).__name__}))
                if mode == "apply":
                    db.record_refresh(SOURCE.source_id, "FAILED", refresh.now_iso(), unit=county)
                rc = 1
                continue
            code = refresh.run(SOURCE.source_id, apply=(mode == "apply"), db=db, out=out,
                               files={"county": county, "path": str(path), "variant": "PIN",
                                      "source": AVAILABLE, "listing_join": True})
        if code == 0:
            summary["complete"] += 1
        else:
            summary["failed"] += 1
            rc = 1
    out(json.dumps(summary))
    return rc


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--mode", choices=["dry_run", "apply"], default="dry_run")
    ap.add_argument("--confirm", default="")
    ap.add_argument("--year", type=int, default=2026, help="the DOR Map Data year folder (2026 = 2026F)")
    ap.add_argument("--counties", default="", help="comma-separated county names; default: every county with "
                                                   "active Florida Available properties")
    a = ap.parse_args(argv)
    only = {c.strip() for c in a.counties.split(",") if c.strip()} or None
    return run(a.mode, a.confirm, year=a.year, only=only)


if __name__ == "__main__":
    sys.exit(main())
