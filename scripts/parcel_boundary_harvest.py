"""Parcel boundary dry run (read-only).

Reads data/parcel_boundary_permissions.csv and reports, per source, whether
boundary storage is enabled. This change has NO apply path: the script never
fetches geometry, never connects to a database and never writes. It prints
counts and reasons only.

    python3 scripts/parcel_boundary_harvest.py            # dry run (default)
    python3 scripts/parcel_boundary_harvest.py --plan-backfill

Enabling a source is a permission decision in the CSV (boundary_policy =
APPROVED, geometry_verified = yes, licence_evidence present), reviewed by the
owner, and is not made by this script.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harvesters.boundary.permissions import enabled_sources, load_matrix  # noqa: E402


def dry_run(out=print) -> int:
    matrix = load_matrix()
    requests = 0
    for sid in sorted(matrix):
        p = matrix[sid]
        if p.enabled():
            out(f"ENABLED   {sid}: would plan (live fetch is not implemented in this change)")
        else:
            out(f"NOT ENABLED {sid} [{p.boundary_policy}]: {p.reason}")
    out(f"sources listed: {len(matrix)}; enabled: {len(enabled_sources(matrix))}; requests: {requests}; writes: 0")
    return 0


def plan_backfill(out=print) -> int:
    matrix = load_matrix()
    enabled = enabled_sources(matrix)
    out(f"backfill plan (counts only, no database read): enabled sources {len(enabled)}; eligible properties 0")
    if not enabled:
        out("no source is enabled, so no backfill can run. Nothing is planned or written.")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--plan-backfill", action="store_true", help="report the backfill plan (counts only)")
    args = ap.parse_args(argv)
    return plan_backfill() if args.plan_backfill else dry_run()


if __name__ == "__main__":
    raise SystemExit(main())
