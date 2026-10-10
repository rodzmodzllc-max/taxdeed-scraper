#!/usr/bin/env python3
"""Reproducible record-quality benchmark for a small set of counties.

Two input modes, never mixed:

  --rows FILE      a read-only export of properties rows (the columns
                   get_properties() returns; a JSON list or {"rows": [...]}).
                   Computes every metric and every invariant
                   (harvesters/quality/record_invariants.py) per
                   state x county x ledger. Requires --now (the export time)
                   so freshness is reproducible.
  --snapshot FILE  the counts-only audit snapshot (data/market_audit_snapshot.json).
                   Reports only what the snapshot measured; everything else
                   is printed as "not in snapshot" - never estimated.

County selection (both modes, deterministic): for each ledger, the
--per-ledger counties with the most customer-visible active records
(ties by state, county). Chosen by existing coverage, not geography.

Writes Markdown to stdout, or to --out; --check compares --out instead
(the committed results file is pinned by a test). No network, no database.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from harvesters.quality.record_invariants import INVARIANTS, METRICS, county_metrics  # noqa: E402

LEDGER_NAMES = {"AUCTIONS": "Auctions", "AVAILABLE": "Available", "LIENS_CERTIFICATES": "Liens & Certificates"}
SNAPSHOT_LEDGERS = {"AUCTION": "AUCTIONS", "AVAILABLE": "AVAILABLE", "LIEN": "LIENS_CERTIFICATES"}
SNAPSHOT_COLUMNS = ("active", "visible", "parcel", "coordinates", "authoritative_coordinates", "auction_url", "purchase_url",
                    "acquisition_evidence", "missing_source_truth", "incomplete_provenance")
NOT_IN_SNAPSHOT = ("dated records", "published amounts (with amount kind)", "freshness (last read)", "duplicates",
                   "lifecycle / status inconsistencies")


def select(units: list[dict], key: str, per_ledger: int) -> list[dict]:
    chosen = []
    for ledger in ("AUCTIONS", "AVAILABLE", "LIENS_CERTIFICATES"):
        pool = [u for u in units if u["ledger"] == ledger and u.get(key, 0) > 0]
        pool.sort(key=lambda u: (-u[key], u["state"], u["county"]))
        chosen.extend(pool[:per_ledger])
    return chosen


def pct(n, d):
    return "-" if not d else f"{n} ({round(100 * n / d)}%)"


def from_rows(rows: list[dict], now: datetime, per_ledger: int) -> str:
    units = county_metrics(rows, now)
    chosen = select(units, "active", per_ledger)
    lines = [f"Mode: rows export · measured at {now.isoformat()} · {len(rows)} rows read", "",
             "| State | County | Ledger | Active | Source link | Parcel # | Dated | Published amount | Read ≤36 h | Acquisition path | Violations |",
             "|---|---|---|---|---|---|---|---|---|---|---|"]
    for u in chosen:
        a = u["active"]
        viol = ", ".join(f"{k} {v}" for k, v in u["violations"].items()) or "none"
        lines.append(f"| {u['state']} | {u['county']} | {LEDGER_NAMES[u['ledger']]} | {a} | " +
                     " | ".join(pct(u[m], a) for m in METRICS[1:]) + f" | {viol} |")
    lines += ["", "Invariants checked: " + ", ".join(INVARIANTS) + "."]
    return "\n".join(lines) + "\n"


def from_snapshot(snap: dict, per_ledger: int) -> str:
    units = []
    for u in snap.get("county_units", []):
        ledger = SNAPSHOT_LEDGERS.get(u.get("ledger"))
        if ledger:
            units.append({**u, "ledger": ledger})
    chosen = select(units, "visible", per_ledger)
    lines = [f"Mode: counts-only snapshot · measured on {snap.get('measured_on', 'unknown')} (read-only production audit, committed as data/market_audit_snapshot.json)", "",
             "| State | County | Ledger | " + " | ".join(c.replace("_", " ").capitalize() for c in SNAPSHOT_COLUMNS) + " |",
             "|---|---|---|" + "---|" * len(SNAPSHOT_COLUMNS)]
    for u in chosen:
        a = u.get("active", 0)
        cells = [str(a)] + [pct(u.get(c, 0), a) if c not in ("active",) else str(a) for c in SNAPSHOT_COLUMNS[1:]]
        lines.append(f"| {u['state']} | {u['county']} | {LEDGER_NAMES[u['ledger']]} | " + " | ".join(cells) + " |")
    lines += ["", "Not in this snapshot (measure with --rows on a read-only export): " + "; ".join(NOT_IN_SNAPSHOT) + "."]
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--rows")
    src.add_argument("--snapshot")
    ap.add_argument("--now", help="ISO time the rows were exported (required with --rows)")
    ap.add_argument("--per-ledger", type=int, default=3)
    ap.add_argument("--out")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args(argv)
    if a.rows:
        if not a.now:
            ap.error("--now is required with --rows (the export time)")
        data = json.loads(Path(a.rows).read_text(encoding="utf-8"))
        rows = data["rows"] if isinstance(data, dict) else data
        now = datetime.fromisoformat(a.now.replace("Z", "+00:00"))
        now = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
        text = from_rows(rows, now, a.per_ledger)
    else:
        text = from_snapshot(json.loads(Path(a.snapshot).read_text(encoding="utf-8")), a.per_ledger)
    if a.check:
        current = Path(a.out).read_text(encoding="utf-8") if a.out and Path(a.out).exists() else ""
        if current != text:
            print(f"{a.out} is out of date - rerun without --check", file=sys.stderr)
            return 1
        return 0
    if a.out:
        Path(a.out).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
