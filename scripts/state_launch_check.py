#!/usr/bin/env python3
"""Repeatable state-launch check (Customer-value sprint, 2026-10-01).

One command answers "is this state wired end to end?" for a state already
registered in harvesters/governance/states.py. It reads the repository only:
no network, no database, no credentials. It never activates anything and
never changes a source decision; it reports.

    python3 scripts/state_launch_check.py --state MI
    python3 scripts/state_launch_check.py --all          # every production state

REQUIRED items (a launch is blocked until each passes):
  registered / activated      states.py knows the state and it is activated
  page                        public/<page>.html exists (index.html for FL)
  page_current                a generated page matches build_state_page.py
  app_state_meta              app.js STATE_META row
  explore_assets              explore.js STATE_ASSETS row
  satellite_view              satellite-map.js STATEWIDE_VIEW row
  centroids                   county-centroids.json has the state
  basemap                     the basemap SVG named by STATE_ASSETS exists
  sw_shell                    sw.js precaches the page
  mirror_files                sync-public-to-root.yml mirrors the page
  ci_importmap                playwright-test.yml injects the stub into it
  registry_rows               data/county_source_registry.csv has the
                              state's sources, each with a publication
                              decision recorded

ADVISORY items (reported, never blocking - their absence is a customer gap,
not a wiring fault):
  acquisition_evidence        a verified purchase-path evidence row exists
  change_detection            the state is wired into a change-detection step

docs/state-launch-playbook.md is the human procedure this checks.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from harvesters.governance import states  # noqa: E402

REQUIRED = ("registered", "activated", "page", "page_current", "app_state_meta", "explore_assets", "satellite_view",
            "centroids", "basemap", "sw_shell", "mirror_files", "ci_importmap", "registry_rows")
ADVISORY = ("acquisition_evidence", "change_detection")


def _read(rel: str) -> str:
    p = REPO / rel
    return p.read_text(encoding="utf-8") if p.exists() else ""


def page_for(code: str) -> str:
    return "index.html" if code == "FL" else f"{code.lower()}.html"


def _table_row(src: str, table: str, code: str) -> str | None:
    """The `  XX: { ... }` row of a `const TABLE = {` literal, or None."""
    start = src.find(f"const {table} = {{")
    if start < 0:
        return None
    m = re.search(rf"^\s*{code}:\s*\{{(.*?)\}}", src[start:start + 20000], re.M | re.S)
    return m.group(1) if m else None


def check_state(code: str) -> dict[str, tuple[bool, str]]:
    code = code.upper()
    out: dict[str, tuple[bool, str]] = {}
    cfg = states.get_state(code)
    out["registered"] = (cfg is not None, "in harvesters/governance/states.py" if cfg else "not registered")
    activated = states.is_activated(code) if cfg else False
    blockers = states.activation_blockers(code) if cfg and not activated else []
    out["activated"] = (activated, "activated" if activated else "not activated: " + ", ".join(blockers or ["not registered"]))
    page = page_for(code)
    out["page"] = ((REPO / "public" / page).exists(), f"public/{page}")
    if code in ("FL", "TX"):
        out["page_current"] = (True, f"{page} is hand-maintained (the template), not generated")
    else:
        r = subprocess.run([sys.executable, str(REPO / "scripts/build_state_page.py"), "--check"], capture_output=True, text=True)
        stale = page in (r.stdout + r.stderr) and r.returncode != 0
        exists = (REPO / "public" / page).exists()
        out["page_current"] = (exists and not stale, "generated page is current" if exists and not stale else
                               ("no page yet - add the state to scripts/build_state_page.py PAGES and run it" if not exists else "re-run scripts/build_state_page.py"))
    app, explore, sat = _read("public/app.js"), _read("public/explore.js"), _read("public/satellite-map.js")
    meta = _table_row(app, "STATE_META", code)
    out["app_state_meta"] = (meta is not None and f'page: "{page}"' in meta, "app.js STATE_META row names the page" if meta else "no STATE_META row")
    assets = _table_row(explore, "STATE_ASSETS", code)
    out["explore_assets"] = (assets is not None, "explore.js STATE_ASSETS row" if assets else "no STATE_ASSETS row")
    out["satellite_view"] = (_table_row(sat, "STATEWIDE_VIEW", code) is not None, "satellite-map.js STATEWIDE_VIEW row")
    try:
        centroids = json.loads(_read("public/county-centroids.json") or "{}")
    except ValueError:
        centroids = {}
    out["centroids"] = (bool(centroids.get(code)), f"{len(centroids.get(code) or {})} unit centroid(s)")
    basemap = re.search(r'basemap:\s*"([^"]+)"', assets or "")
    bm = basemap.group(1) if basemap else ""
    out["basemap"] = (bool(bm) and ((REPO / "public" / bm).exists() or (REPO / bm).exists()), bm or "no basemap named")
    sw = _read("public/sw.js")
    shell = sw[sw.find("const SHELL = ["):sw.find("];", sw.find("const SHELL = ["))]
    out["sw_shell"] = (f'"/{page}"' in shell, f"sw.js SHELL precaches /{page}")
    sync = _read(".github/workflows/sync-public-to-root.yml")
    files = re.search(r'FILES="([^"]+)"', sync)
    names = files.group(1).split() if files else []
    out["mirror_files"] = (page in names, f"{page} in the mirror FILES list")
    ci = _read(".github/workflows/playwright-test.yml")
    out["ci_importmap"] = (f"/tmp/serve/{page}" in ci, f"CI injects the stub importmap into {page}")
    rows = [r for r in csv.DictReader((REPO / "data/county_source_registry.csv").open(encoding="utf-8")) if r.get("state") == code]
    undecided = [r["source_id"] for r in rows if not (r.get("publication_status") or "").strip()]
    out["registry_rows"] = (bool(rows) and not undecided,
                            f"{len(rows)} registry row(s)" + (f"; no publication decision: {', '.join(sorted(set(undecided))[:5])}" if undecided else ""))
    ev = 0
    for name in ("data/purchase_path_evidence.csv", "data/purchase_path_evidence_expansion.csv"):
        p = REPO / name
        if p.exists():
            ev += sum(1 for r in csv.DictReader(p.open(encoding="utf-8")) if r.get("state") == code and (r.get("review_state") or "") == "verified")
    out["acquisition_evidence"] = (ev > 0, f"{ev} verified evidence row(s)")
    wf = _read(".github/workflows/harvest-and-sync.yml")
    matrix = re.search(r"state:\s*\[([^\]]+)\]", wf)
    in_matrix = bool(matrix) and code in [s.strip() for s in matrix.group(1).split(",")]
    explicit = f"detect_property_changes.py --state {code} " in wf
    out["change_detection"] = (in_matrix or explicit, "wired" if (in_matrix or explicit) else "not wired into a change-detection step")
    return out


def report(code: str, results: dict[str, tuple[bool, str]]) -> bool:
    ok = all(results[k][0] for k in REQUIRED)
    print(f"{code}: {'READY' if ok else 'BLOCKED'}")
    for k in REQUIRED + ADVISORY:
        passed, note = results[k]
        tag = "PASS" if passed else ("FAIL" if k in REQUIRED else "GAP ")
        print(f"  {tag} {k:<22} {note}")
    return ok


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--state")
    g.add_argument("--all", action="store_true", help="every production state")
    args = ap.parse_args(argv)
    codes = sorted(states.PRODUCTION_STATES) if args.all else [args.state.upper()]
    ok = True
    for code in codes:
        ok = report(code, check_state(code)) and ok
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
