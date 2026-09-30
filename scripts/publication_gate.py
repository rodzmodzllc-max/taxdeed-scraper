#!/usr/bin/env python3
"""Source-level publication gate for the AVAILABLE ledger (2026-09-30).

Reads data/county_source_registry.csv, takes one publication decision per
source (harvesters/governance/publication.py), and:

  1. writes out/public/publication-gate.json - every source's decision
     (harvestable / establishes availability / purchase info / governance /
     publication) and the AVAILABLE-inventory measurement: total observed,
     publishable, restricted, unreviewed, blocked, unclassified,
     unavailable-source, with / without purchase path, stale. Counts only.
  2. once migration 022 exists, propagates each row's SOURCE decision to
     properties.publication_status (one PATCH per changed value group), so
     the API and the frontend can withhold restricted inventory. Probes for
     the column and plans only until then. Never touches a row whose source
     it cannot name.

Usage:
    python3 scripts/publication_gate.py --state FL            # live (needs SUPABASE_URL + SUPABASE_SERVICE_KEY)
    python3 scripts/publication_gate.py --state FL --dry-run
    python3 scripts/publication_gate.py --state FL --rows out/harvest_laft.json   # measure a harvest file, no API

Exit 0 always for a plan / report; the workflow step is continue-on-error.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

from harvesters.governance import county_source_registry as csr  # noqa: E402
from harvesters.governance import publication as pub  # noqa: E402
import laft_purchase_paths as PP  # noqa: E402

REPORT_PATH = REPO / "out" / "public" / "publication-gate.json"
FRESHNESS_PERSIST = REPO / "out" / "unit-freshness-persist.json"
SELECT = "id,state,county,source,harvester_source,source_id,publication_status,purchase_url,last_seen_at,inventory_status"
USER_AGENT = "taxdeed-scraper publication-gate (+https://github.com/rodzmodzllc-max/taxdeed-scraper)"


class Api:
    def __init__(self, url: str, key: str, *, dry_run: bool) -> None:
        self.base, self.key, self.dry_run, self.requests_made = url.rstrip("/") + "/rest/v1", key, dry_run, 0

    def _headers(self, extra: dict | None = None) -> dict:
        h = {"apikey": self.key, "Authorization": f"Bearer {self.key}", "User-Agent": USER_AGENT, "Content-Type": "application/json"}
        h.update(extra or {})
        return h

    def get(self, table: str, query: str) -> list[dict]:
        req = urllib.request.Request(f"{self.base}/{table}?{query}", headers=self._headers())
        with urllib.request.urlopen(req, timeout=60) as resp:
            self.requests_made += 1
            return json.loads(resp.read().decode())

    def patch(self, table: str, query: str, body: dict) -> None:
        if self.dry_run:
            return
        req = urllib.request.Request(f"{self.base}/{table}?{query}", data=json.dumps(body).encode(), method="PATCH",
                                     headers=self._headers({"Prefer": "return=minimal"}))
        with urllib.request.urlopen(req, timeout=60):
            self.requests_made += 1

    def has_migration_022(self) -> bool:
        try:
            self.get("properties", "select=publication_status&limit=0")
            return True
        except urllib.error.HTTPError as exc:
            if exc.code in (400, 404):
                return False
            raise


def fetch_rows(api: Api, state: str) -> list[dict]:
    rows: list[dict] = []
    offset = 0
    while True:
        page = api.get("properties", f"select={SELECT}&state=eq.{urllib.parse.quote(state)}&source=eq.laft&order=id.asc&limit=1000&offset={offset}")
        rows.extend(page)
        if len(page) < 1000:
            return rows
        offset += 1000


def plan(rows: list[dict], decisions: dict[str, pub.PublicationDecision]) -> tuple[dict[str, list[str]], dict]:
    """{publication_status: [ids]} for rows whose stored value differs;
    counts of rows left alone."""
    groups: dict[str, list[str]] = {}
    counts = {"rows": len(rows), "unclassified": 0, "unchanged": 0, "changed": 0}
    for r in rows:
        if r.get("source") not in (None, "laft"):
            continue                                    # the AVAILABLE ledger only; other ledgers keep their own rules
        status = pub.row_publication(r, decisions)
        if status is None:
            counts["unclassified"] += 1
            continue
        if r.get("publication_status") == status:
            counts["unchanged"] += 1
            continue
        counts["changed"] += 1
        groups.setdefault(status, []).append(str(r["id"]))
    return groups, counts


def execute(api: Api, groups: dict[str, list[str]]) -> int:
    patches = 0
    for status, ids in groups.items():
        for i in range(0, len(ids), 200):
            chunk = ",".join(ids[i:i + 200])
            api.patch("properties", f"id=in.({chunk})", {"publication_status": status})
            patches += 1
    return patches


def unavailable_units(persist_path: Path = FRESHNESS_PERSIST) -> set[tuple[str, str, str]]:
    """(state, source_id, county) whose last attempt was SOURCE_UNAVAILABLE
    (scripts/unit_freshness.py's persisted record), for the measurement."""
    try:
        record = json.loads(Path(persist_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    units = record.get("units", record) if isinstance(record, dict) else {}
    out = set()
    for u in (units.values() if isinstance(units, dict) else []):
        if isinstance(u, dict) and u.get("last_attempt_status") == "SOURCE_UNAVAILABLE":
            out.add((str(u.get("state") or ""), str(u.get("source_id") or ""), str(u.get("county") or "")))
    return out


def load_rows_file(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = data.get("rows", data) if isinstance(data, dict) else data
    return [r for r in rows if isinstance(r, dict)]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--state", default="FL")
    ap.add_argument("--registry", default=str(csr.REGISTRY_PATH))
    ap.add_argument("--rules", default=str(PP.RULES_PATH))
    ap.add_argument("--rows", default=None, help="measure a harvest / rows JSON file instead of the API (no writes)")
    ap.add_argument("--report", default=str(REPORT_PATH))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    registry = csr.load_registry(args.registry)
    rule_sources = frozenset(r.source_id for r in PP.load_rules(args.rules) if r.enabled and r.purchase_url_kind in PP.PROPERTY_KINDS)
    decisions = pub.decisions_by_source(registry, property_rule_sources=rule_sources)
    state_decisions = {k: v for k, v in decisions.items() if v.state == args.state}
    now = datetime.now(timezone.utc)
    report: dict = {"generated_at": now.isoformat(), "state": args.state, "mode": None,
                    "sources": {k: v.as_dict() for k, v in sorted(state_decisions.items())},
                    "note": "one decision per source; counts only; a row whose source cannot be named is unclassified, never withheld or approved by default"}

    rows: list[dict] = []
    if args.rows:
        rows = [r for r in load_rows_file(Path(args.rows)) if str(r.get("state") or args.state) == args.state]
        report["mode"] = "rows-file"
    else:
        url, key = os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_SERVICE_KEY")
        if not url or not key:
            report["mode"] = "registry-only (no credentials)"
        else:
            api = Api(url, key, dry_run=args.dry_run)
            have_022 = api.has_migration_022()
            report["migration_022"] = "present" if have_022 else "absent - publication_status not written"
            if have_022:
                rows = fetch_rows(api, args.state)
                groups, counts = plan(rows, decisions)
                report["plan"] = {"counts": counts, "by_status": {k: len(v) for k, v in groups.items()}}
                if args.dry_run:
                    report["mode"] = "dry-run"
                else:
                    report["mode"] = "applied"
                    report["patches"] = execute(api, groups)
            else:
                report["mode"] = "plan-only (migration 022 absent)"
    if rows:
        report["measurement"] = pub.measure(rows, decisions, now=now, unavailable_units=unavailable_units())
    Path(args.report).parent.mkdir(parents=True, exist_ok=True)
    Path(args.report).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    publishable = sum(1 for d in state_decisions.values() if d.customer_publishable)
    print(f"publication gate ({args.state}): {len(state_decisions)} source(s), {publishable} publishable; mode {report['mode']}")
    if "measurement" in report:
        c = report["measurement"]["counts"]
        print(f"  AVAILABLE rows: {c['total_observed']} observed, {c['publishable']} publishable, {c['restricted']} restricted, "
              f"{c['unreviewed']} unreviewed, {c['blocked']} blocked, {c['unclassified']} unclassified; "
              f"{c['with_purchase_path']} with a purchase path; {c['stale']} stale (> {c['stale_days']}d)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
