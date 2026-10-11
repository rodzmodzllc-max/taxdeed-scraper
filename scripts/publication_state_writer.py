#!/usr/bin/env python3
"""Decide and write the customer-publication state of every active row of
one state (harvesters/governance/publication_state.py; migration 031).

  python3 scripts/publication_state_writer.py --state FL              # decide + write (needs credentials)
  python3 scripts/publication_state_writer.py --state FL --dry-run    # decide, write nothing, counts only
  python3 scripts/publication_state_writer.py --state FL --rows f.json  # decide a rows file, no network

Reads every active row of the state by keyset pages (scripts/rest_pages.py),
builds the context once from repository files (source registry decisions,
state ledgers eligibility + county coverage, public/acquisition-evidence.json),
decides each row, and
  - PATCHes properties.publication_state / _progress / _reasons /
    _remediation / _path / _state_at for rows whose state or reasons changed
    (grouped per identical decision, ids in chunks);
  - appends one publication_decisions row per changed row (the audit log);
  - writes a counts-only report to out/public/publication-state-<st>.json.

Fail-safe: when migration 031 is absent the run is plan-only (exit 0, nothing
written); a failed read raises and writes nothing; a row is never closed here
(CLOSED only mirrors a lifecycle status that is already not active).
Credentials: SUPABASE_URL + SUPABASE_SERVICE_KEY (never printed).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

from harvesters.governance import publication_state as PS  # noqa: E402
import rest_pages as RP  # noqa: E402

SELECT = ("id,state,county,source,source_id,harvester_source,ledger_type,status,case_no,parcel,certificate_no,url_auction,"
          "url_auction_kind,sale_date,last_seen_at,updated_at,purchase_path_type,purchase_path_scope,purchase_path_observed_on,"
          "purchase_url,inventory_type,publication_state,publication_progress,publication_reasons")
USER_AGENT = "taxdeed-scraper publication-state (+https://github.com/rodzmodzllc-max/taxdeed-scraper)"
CHUNK = 200
REPORT_DIR = REPO / "out" / "public"


class Api:
    def __init__(self, url: str, key: str, *, dry_run: bool) -> None:
        self.url, self.key, self.dry_run, self.requests_made = url.rstrip("/"), key, dry_run, 0

    def headers(self, extra: dict | None = None) -> dict:
        h = {"apikey": self.key, "Authorization": f"Bearer {self.key}", "User-Agent": USER_AGENT, "Content-Type": "application/json"}
        h.update(extra or {})
        return h

    def has_migration_031(self) -> bool:
        try:
            RP.get_json(f"{self.url}/rest/v1/properties?select=publication_state,publication_path&limit=0", self.headers())
            return True
        except urllib.error.HTTPError as exc:
            if exc.code in (400, 404):
                return False
            raise

    def read_rows(self, state: str) -> list[dict]:
        return RP.read_all(self.url, "properties", self.headers(), {"select": SELECT, "state": f"eq.{state}", "status": "eq.active"})

    def patch(self, ids: list[str], body: dict) -> None:
        if self.dry_run:
            return
        q = "id=in.(" + ",".join(ids) + ")"
        req = urllib.request.Request(f"{self.url}/rest/v1/properties?{q}", data=json.dumps(body).encode(), method="PATCH",
                                     headers=self.headers({"Prefer": "return=minimal"}))
        with urllib.request.urlopen(req, timeout=120):
            self.requests_made += 1

    def insert_decisions(self, rows: list[dict]) -> None:
        if self.dry_run or not rows:
            return
        req = urllib.request.Request(f"{self.url}/rest/v1/publication_decisions", data=json.dumps(rows).encode(), method="POST",
                                     headers=self.headers({"Prefer": "return=minimal"}))
        with urllib.request.urlopen(req, timeout=120):
            self.requests_made += 1


def plan(rows: list[dict], ctx: PS.Context) -> tuple[list[tuple[dict, PS.Decision]], dict]:
    """Decide every row; return (row, decision) pairs and counts only."""
    decided = [(r, PS.decide(r, ctx)) for r in rows]
    counts = {"rows": len(rows), "by_state": dict(Counter(d.state for _, d in decided)),
              "by_ledger_state": {}, "changed": 0, "by_reason": dict(Counter(x for _, d in decided for x in d.reasons))}
    for r, d in decided:
        k = f"{r.get('ledger_type') or '?'}:{d.state}"
        counts["by_ledger_state"][k] = counts["by_ledger_state"].get(k, 0) + 1
        if changed(r, d):
            counts["changed"] += 1
    return decided, counts


def changed(row: dict, d: PS.Decision) -> bool:
    return (row.get("publication_state") != d.state or row.get("publication_progress") != d.progress
            or list(row.get("publication_reasons") or []) != list(d.reasons))


def execute(api: Api, decided, *, run_id: str, now: datetime) -> dict:
    """PATCH changed rows grouped by identical decision; log each change."""
    groups: dict[str, list[tuple[dict, PS.Decision]]] = {}
    for r, d in decided:
        if not changed(r, d):
            continue
        key = json.dumps({"s": d.state, "p": d.progress, "r": d.reasons, "m": d.remediation, "e": d.path.as_dict() if d.path else None}, sort_keys=True)
        groups.setdefault(key, []).append((r, d))
    patches = decisions = 0
    for key, items in groups.items():
        d = items[0][1]
        body = {"publication_state": d.state, "publication_progress": d.progress, "publication_reasons": d.reasons,
                "publication_remediation": d.remediation or None, "publication_path": d.path.as_dict() if d.path else None,
                "publication_state_at": now.isoformat()}
        ids = [str(r["id"]) for r, _ in items]
        for i in range(0, len(ids), CHUNK):
            api.patch(ids[i:i + CHUNK], body)
            patches += 1
        log = [{"property_id": str(r["id"]), "state": r.get("state"), "county": r.get("county"), "ledger_type": r.get("ledger_type"),
                "source_id": r.get("source_id") or r.get("harvester_source"), "prior_state": r.get("publication_state"),
                "publication_state": d.state, "publication_progress": d.progress, "reasons": d.reasons,
                "remediation": d.remediation or None, "path_evidence": d.path.as_dict() if d.path else None, "run_id": run_id}
               for r, _ in items]
        for i in range(0, len(log), 500):
            api.insert_decisions(log[i:i + 500])
            decisions += 1
    return {"groups": len(groups), "patch_requests": patches, "decision_batches": decisions}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--state", required=True)
    ap.add_argument("--rows", default=None, help="decide a rows JSON file (no network, no writes)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--report", default=None)
    args = ap.parse_args(argv)
    now = datetime.now(timezone.utc)
    run_id = os.environ.get("GITHUB_RUN_ID") or now.strftime("local-%Y%m%d%H%M%S")
    ctx = PS.build_context(now=now)
    report: dict = {"generated_at": now.isoformat(), "state": args.state, "mode": None, "run_id": run_id,
                    "note": "counts only; a row's decision names its reasons and remediation; nothing here closes a row"}
    if args.rows:
        rows = [r for r in json.loads(Path(args.rows).read_text(encoding="utf-8")) if str(r.get("state") or args.state) == args.state]
        report["mode"] = "rows-file"
        _, counts = plan(rows, ctx)
    else:
        url, key = os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_SERVICE_KEY")
        if not (url and key):
            report["mode"] = "no credentials"
            counts = {}
        else:
            api = Api(url, key, dry_run=args.dry_run)
            if not api.has_migration_031():
                report["mode"] = "plan-only (migration 031 absent)"
                rows = api.read_rows(args.state) if False else []
                counts = {}
            else:
                rows = api.read_rows(args.state)
                decided, counts = plan(rows, ctx)
                if args.dry_run:
                    report["mode"] = "dry-run"
                else:
                    report["mode"] = "applied"
                    report["writes"] = execute(api, decided, run_id=run_id, now=now)
    report["counts"] = counts
    out = Path(args.report) if args.report else REPORT_DIR / f"publication-state-{args.state.lower()}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"publication state ({args.state}): mode {report['mode']}; " + (
        f"{counts['rows']} rows, {counts['changed']} changed; by state {counts['by_state']}" if counts else "nothing decided"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
