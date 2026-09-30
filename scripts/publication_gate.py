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
  3. once migration 023 exists, reads the admin publication reviews
     (public.source_publication_reviews, written from the app's admin
     panel) and applies the LATEST decision per (state, source_id) - but
     only after validating it against the registry's governance state
     with the same rules as the committed CSV (publication_problems): a
     blocked vendor, a source under legal review, a candidate that is not
     production-verified cannot be approved by a review row; a RESTRICTED
     review must say why. A rejected review is reported by name and the
     registry value stands. An applied decision is also written back to
     the county_source_registry table's own publication columns so the
     Dashboard and the gate agree.

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
import purchase_path_engine as PE  # noqa: E402

REPORT_PATH = REPO / "out" / "public" / "publication-gate.json"
FRESHNESS_PERSIST = REPO / "out" / "unit-freshness-persist.json"
SELECT = "id,state,county,source,harvester_source,source_id,publication_status,purchase_url,last_seen_at,inventory_status"
SELECT_023 = SELECT + ",purchase_path_type,purchase_path_scope,list_as_of,source_published_at,otc_provenance"     # once migration 023 exists (probed)
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

    def has_reviews_table(self) -> bool:
        """Migration 023's source_publication_reviews (service_role reads it)."""
        try:
            self.get("source_publication_reviews", "select=id&limit=0")
            return True
        except urllib.error.HTTPError as exc:
            if exc.code in (400, 404):
                return False
            raise

    def has_migration_023(self) -> bool:
        try:
            self.get("properties", "select=purchase_path_type,purchase_path_scope&limit=0")
            return True
        except urllib.error.HTTPError as exc:
            if exc.code in (400, 404):
                return False
            raise

    def has_migration_022(self) -> bool:
        try:
            self.get("properties", "select=publication_status&limit=0")
            return True
        except urllib.error.HTTPError as exc:
            if exc.code in (400, 404):
                return False
            raise


def fetch_rows(api: Api, state: str, *, select: str = SELECT) -> list[dict]:
    rows: list[dict] = []
    offset = 0
    while True:
        page = api.get("properties", f"select={select}&state=eq.{urllib.parse.quote(state)}&source=eq.laft&order=id.asc&limit=1000&offset={offset}")
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


# ---------------------------------------------------------------------------
# Admin publication reviews (migration 023)
# ---------------------------------------------------------------------------
REVIEW_SELECT = "id,state,source_id,publication_status,restrictions,decision_note,evidence,decided_at,next_review"


def latest_reviews(rows: list[dict]) -> dict[tuple[str, str], dict]:
    """The newest review per (state, source_id) - by decided_at, then id."""
    out: dict[tuple[str, str], dict] = {}
    for r in rows:
        key = (str(r.get("state") or ""), str(r.get("source_id") or ""))
        prev = out.get(key)
        if prev is None or (str(r.get("decided_at") or ""), int(r.get("id") or 0)) > (str(prev.get("decided_at") or ""), int(prev.get("id") or 0)):
            out[key] = r
    return out


def fetch_reviews(api: Api) -> dict[tuple[str, str], dict]:
    return latest_reviews(api.get("source_publication_reviews", f"select={REVIEW_SELECT}&order=decided_at.asc,id.asc&limit=5000"))


def apply_reviews(registry: list, reviews: dict[tuple[str, str], dict]) -> tuple[list, dict]:
    """Registry rows with each source's latest VALID review applied
    (publication_status + restrictions), plus a report: applied / rejected
    (with the validator's reasons) / unknown source. A review never
    weakens the two non-negotiable overrides (effective_publication) and
    never passes a row publication_problems would refuse in the CSV."""
    from dataclasses import replace
    report = {"applied": {}, "rejected": {}, "unknown_source": []}
    by_source: dict[tuple[str, str], list[int]] = {}
    for i, r in enumerate(registry):
        by_source.setdefault((r.state, r.source_id), []).append(i)
    out = list(registry)
    for key, review in sorted(reviews.items()):
        status = str(review.get("publication_status") or "").strip()
        restrictions = str(review.get("restrictions") or "").strip()
        idx = by_source.get(key)
        if not idx:
            report["unknown_source"].append(f"{key[0]}/{key[1]}")
            continue
        candidates = [replace(registry[i], publication_status=status, restrictions=restrictions) for i in idx]
        problems = sorted({p for c in candidates for p in pub.publication_problems(c)})
        if problems:
            report["rejected"][f"{key[0]}/{key[1]}"] = {"review_id": review.get("id"), "wanted": status, "reasons": problems}
            continue
        for i, c in zip(idx, candidates):
            out[i] = c
        report["applied"][f"{key[0]}/{key[1]}"] = {"review_id": review.get("id"), "publication_status": status,
                                                  "decided_at": review.get("decided_at"), "next_review": review.get("next_review")}
    return out, report


def sync_registry_table(api: Api, registry: list, applied: dict) -> int:
    """Write an applied review's publication_status / restrictions to the
    county_source_registry TABLE rows of that source (the CSV stays the
    committed baseline; the table is what the Dashboard reads)."""
    if not applied:
        return 0
    patches = 0
    for key in applied:
        state, sid = key.split("/", 1)
        rows = [r for r in registry if r.state == state and r.source_id == sid]
        if not rows:
            continue
        status, restrictions = rows[0].publication_status, (rows[0].restrictions or None)
        current = api.get("county_source_registry", f"select=state,county,source_id,publication_status,restrictions&state=eq.{urllib.parse.quote(state)}&source_id=eq.{urllib.parse.quote(sid)}")
        if any(c.get("publication_status") != status or (c.get("restrictions") or None) != restrictions for c in current):
            api.patch("county_source_registry", f"state=eq.{urllib.parse.quote(state)}&source_id=eq.{urllib.parse.quote(sid)}",
                      {"publication_status": status, "restrictions": restrictions})
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
    now = datetime.now(timezone.utc)
    report: dict = {"generated_at": now.isoformat(), "state": args.state, "mode": None,
                    "note": "one decision per source; counts only; a row whose source cannot be named is unclassified, never withheld or approved by default"}
    api: Api | None = None
    rows: list[dict] = []
    if not args.rows:
        url, key = os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_SERVICE_KEY")
        if url and key:
            api = Api(url, key, dry_run=args.dry_run)
            # Admin reviews (migration 023) are applied to the registry BEFORE
            # the decisions are taken, each one validated like a CSV value.
            if api.has_reviews_table():
                registry, review_report = apply_reviews(registry, fetch_reviews(api))
                report["reviews"] = review_report
                report["registry_patches"] = sync_registry_table(api, registry, review_report["applied"])
            else:
                report["reviews"] = "migration 023 absent - no admin reviews to apply"
    decisions = pub.decisions_by_source(registry, property_rule_sources=rule_sources)
    state_decisions = {k: v for k, v in decisions.items() if v.state == args.state}
    report["sources"] = {k: v.as_dict() for k, v in sorted(state_decisions.items())}

    if args.rows:
        rows = [r for r in load_rows_file(Path(args.rows)) if str(r.get("state") or args.state) == args.state]
        report["mode"] = "rows-file"
    else:
        if api is None:
            report["mode"] = "registry-only (no credentials)"
        else:
            have_022 = api.has_migration_022()
            report["migration_022"] = "present" if have_022 else "absent - publication_status not written"
            if have_022:
                have_023 = api.has_migration_023()
                rows = fetch_rows(api, args.state, select=SELECT_023 if have_023 else SELECT)
                if have_023:
                    report["purchase_paths"] = PE.measure(rows)
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
        pp = report.get("purchase_paths")
        if pp:
            print(f"  acquisition (rows {pp['rows']}): {pp['with_source_listing']} with a source listing / document ({pp['pct_with_source_listing']}%), "
                  f"{pp['with_source_match']} property-to-source matched, {pp['with_acquisition_path']} with a verified acquisition path "
                  f"({pp['pct_with_acquisition_path']}%), {pp['acquisition_unverified']} unverified; by mode {pp['by_mode']}; "
                  f"{pp['with_direct_document']} direct document, {pp['with_source_date']} source date, {pp['with_last_verified']} last verified")
    return 0


if __name__ == "__main__":
    sys.exit(main())
