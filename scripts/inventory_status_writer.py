#!/usr/bin/env python3
"""Write each property's normalized inventory / lifecycle status and its
observation history (migration 021) - production-readiness program,
2026-09-30.

    properties (one state)  --->  harvesters/governance/inventory_status.py
    + out/harvest_laft_sold*.json (FL lists' own 'Sold To' rows, identities only)
          |
          v
    properties.inventory_status / _raw / _basis / _observed_at   (PATCH, on change only)
    inventory_status_observations                                (INSERT, one row per change)

RULES (all enforced by inventory_status.StatusObservation and repeated here)
- sold / redeemed / withdrawn / cancelled / struck_off come ONLY from a
  status the source published (basis SOURCE_STATUS). A row that left a
  list is `closed`; a past-dated auction with no published result is
  `unknown`. Nothing is inferred from absence, dates, bids or counts.
- The FL lists' own 'Sold To' / 'Purchaser' column is a published status:
  the HTML/PDF harvesters write those rows' IDENTITIES (county + case /
  parcel - never the purchaser) to out/harvest_laft_sold*.json, and a
  matching stored row is marked `sold` with raw 'Sold To'.
- A status is written only when it differs from the stored one (status or
  raw wording changed); every write is paired with an observation row, so
  the history is complete and the newest state never overwrites it.
- Migration 021 is probed. Until it is applied the script plans and
  reports and writes nothing.
- Rows with no mapping (certificates, unknown vendors) are left alone.

Standard library only; SUPABASE_URL / SUPABASE_SERVICE_KEY like the other
sync scripts; --dry-run plans against production and writes nothing. The
public report and the log carry counts and county names only.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(1, str(REPO))
from harvesters.governance import inventory_status as IS  # noqa: E402
from harvesters.governance import states  # noqa: E402
import outcome_ingest as OI  # noqa: E402

DEFAULT_SOLD_FILES = [REPO / "out" / n for n in ("harvest_laft_sold.json", "harvest_laft_sold_html.json", "harvest_laft_sold_pdfs.json")]
REPORT_PATH = REPO / "out" / "public" / "inventory-status.json"
USER_AGENT = "taxdeed-scraper/1.0 (+https://github.com/rodzmodzllc-max/taxdeed-scraper; inventory status writer)"
SELECT = ("id,state,county,case_no,source,harvester_source,status,sale_date,tx_sale_status,list_url,url_auction,"
          "inventory_status,inventory_status_raw,otc_provenance")
BATCH = 40
STATUS_COLUMNS = ("inventory_status", "inventory_status_raw", "inventory_status_basis", "inventory_status_observed_at")
RESULT_COLUMNS = ("result_amount", "result_date", "result_party")   # migration 023, probed


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


# ---------------------------------------------------------------------------
# Pure planning (tested without a network)
# ---------------------------------------------------------------------------
def load_sold_identities(paths) -> set[tuple[str, str]]:
    """(county, case_no) of rows the FL lists themselves mark sold. The
    harvesters write county + case_no (+ parcel); identity is the sync's:
    case_no, else parcel."""
    out: set[tuple[str, str]] = set()
    for p in paths:
        p = Path(p)
        if not p.is_file():
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except ValueError:
            continue
        for r in data if isinstance(data, list) else []:
            if not isinstance(r, dict):
                continue
            county = str(r.get("county") or "").strip()
            key = str(r.get("case_no") or "").strip() or str(r.get("parcel") or "").strip()
            if county and key:
                out.add((county, key))
    return out


def plan(rows: list[dict], *, today: date, sold: set[tuple[str, str]] | None = None,
         results: dict[tuple[str, str], dict] | None = None) -> tuple[list[dict], dict]:
    """[{id, county, case_no, status, raw, basis, evidence_url, transition,
    result?}] for every row whose observation differs from what is stored,
    plus counts. `results` = source-published result fields by identity
    (scripts/outcome_ingest.py); attached only to a result_published change."""
    sold = sold or set()
    results = results or {}
    changes: list[dict] = []
    counts = {"rows": len(rows), "mapped": 0, "unmapped": 0, "unchanged": 0, "changed": 0, "by_status": {}, "results_from_source": 0}
    for r in rows:
        is_sold = (str(r.get("county") or ""), str(r.get("case_no") or "")) in sold
        obs = IS.status_for_row(r, today=today, sold_column_present=is_sold)
        if obs is None:
            counts["unmapped"] += 1
            continue
        counts["mapped"] += 1
        counts["by_status"][obs.status] = counts["by_status"].get(obs.status, 0) + 1
        if obs.status in IS.RESULT_STATUSES:
            counts["results_from_source"] += 1
        if r.get("inventory_status") == obs.status and (r.get("inventory_status_raw") or None) == obs.raw:
            counts["unchanged"] += 1
            continue
        counts["changed"] += 1
        # The transition this observation records (migration 022's column on
        # the history table): the first status for the row, a change, a
        # removal (closed - never sold from absence), or a result the source
        # itself published.
        # (migration 023 adds `reactivated`: a row that had left the list -
        # stored closed - and is on it again.)
        if not r.get("inventory_status"):
            transition = "newly_observed"
        elif obs.status == "closed":
            transition = "removed"
        elif obs.status in IS.RESULT_STATUSES:
            transition = "result_published"
        elif r.get("inventory_status") == "closed":
            transition = "reactivated"
        else:
            transition = "status_changed"
        counts.setdefault("by_transition", {})[transition] = counts.get("by_transition", {}).get(transition, 0) + 1
        change = {"id": r["id"], "county": r.get("county"), "case_no": r.get("case_no"), "status": obs.status,
                  "raw": obs.raw, "basis": obs.basis_text(), "source_id": r.get("harvester_source"),
                  "evidence_url": r.get("list_url") or r.get("url_auction"), "transition": transition}
        if transition == "result_published":
            fields = results.get((str(r.get("county") or ""), str(r.get("case_no") or ""))) or {}
            result = {k: fields[k] for k in RESULT_COLUMNS if fields.get(k) not in (None, "")}
            if result:
                change["result"] = result
                counts["results_with_fields"] = counts.get("results_with_fields", 0) + 1
        changes.append(change)
    return changes, counts


def group_changes(changes: list[dict], *, include_results: bool = False) -> list[tuple[dict, list[str]]]:
    """Identical payloads share one PATCH: [(payload, [id...])]. The
    result columns ride along only once migration 023 exists (probed)."""
    groups: dict[str, tuple[dict, list[str]]] = {}
    for c in changes:
        payload = {"inventory_status": c["status"], "inventory_status_raw": c["raw"], "inventory_status_basis": c["basis"]}
        if include_results and c.get("result"):
            payload.update(c["result"])
        key = json.dumps(payload, sort_keys=True)
        groups.setdefault(key, (payload, []))[1].append(c["id"])
    return list(groups.values())


def observations(changes: list[dict], *, observed_at: str, run_id: str | None, include_transition: bool = False,
                 include_results: bool = False) -> list[dict]:
    """One history row per change. `transition` is included only once
    migration 022's column exists (the caller probes) - an insert naming an
    unknown column would fail the whole batch; `reactivated` and the result
    columns only once 023's are there."""
    out = []
    for c in changes:
        row = {"property_id": c["id"], "observed_at": observed_at, "harvest_run_id": run_id, "source_id": c["source_id"],
               "raw_status": c["raw"], "inventory_status": c["status"], "basis": c["basis"], "evidence_url": c["evidence_url"]}
        transition = c.get("transition")
        if transition == "reactivated" and not include_results:
            transition = "status_changed"          # 022's check constraint does not know `reactivated`
        if include_transition and transition:
            row["transition"] = transition
        if include_results and c.get("result"):
            row.update(c["result"])
        out.append(row)
    return out


# ---------------------------------------------------------------------------
# Supabase I/O
# ---------------------------------------------------------------------------
class Api:
    def __init__(self, url: str, key: str, *, dry_run: bool = False) -> None:
        self.base = url.rstrip("/") + "/rest/v1"
        self.key = key
        self.dry_run = dry_run
        self.requests_made = 0

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
        req = urllib.request.Request(f"{self.base}/{table}?{query}", data=json.dumps(body, default=str).encode(), method="PATCH",
                                     headers=self._headers({"Prefer": "return=minimal"}))
        with urllib.request.urlopen(req, timeout=60):
            self.requests_made += 1

    def insert(self, table: str, rows: list[dict]) -> None:
        if self.dry_run or not rows:
            return
        req = urllib.request.Request(f"{self.base}/{table}", data=json.dumps(rows, default=str).encode(), method="POST",
                                     headers=self._headers({"Prefer": "return=minimal,resolution=ignore-duplicates"}))
        with urllib.request.urlopen(req, timeout=60):
            self.requests_made += 1

    def has_migration_022(self) -> bool:
        """Migration 022's `transition` column on the history table."""
        try:
            self.get("inventory_status_observations", "select=transition&limit=0")
            return True
        except urllib.error.HTTPError as exc:
            if exc.code in (400, 404):
                return False
            raise

    def has_migration_023(self) -> bool:
        """Migration 023's result columns on both tables."""
        try:
            self.get("properties", f"select={','.join(RESULT_COLUMNS)}&limit=0")
            self.get("inventory_status_observations", f"select={','.join(RESULT_COLUMNS)}&limit=0")
            return True
        except urllib.error.HTTPError as exc:
            if exc.code in (400, 404):
                return False
            raise

    def has_migration_021(self) -> bool:
        try:
            self.get("properties", f"select={','.join(STATUS_COLUMNS)}&limit=0")
            self.get("inventory_status_observations", "select=id&limit=0")
            return True
        except urllib.error.HTTPError as exc:
            if exc.code in (400, 404):
                return False
            raise


def fetch_rows(api: Api, state: str, *, with_results: bool = False) -> list[dict]:
    """Every row of one state. `with_results` adds migration 023's
    result_amount (probed by the caller): a published sale price in a
    county's past-sales table is what marks such a row sold
    (inventory_status.adapter_record_status)."""
    out: list[dict] = []
    offset, page = 0, 1000
    select = SELECT + (",result_amount" if with_results else "")
    while True:
        chunk = api.get("properties", f"select={select}&state=eq.{state}&order=id&limit={page}&offset={offset}")
        out.extend(chunk)
        if len(chunk) < page:
            return out
        offset += page


def execute(api: Api, changes: list[dict], *, observed_at: str, run_id: str | None, include_transition: bool = False,
            include_results: bool = False) -> dict:
    counts = {"patches": 0, "observations": 0}
    obs = observations(changes, observed_at=observed_at, run_id=run_id, include_transition=include_transition,
                       include_results=include_results)
    # Observations first (history is never behind the current state), then the state.
    for i in range(0, len(obs), BATCH):
        api.insert("inventory_status_observations", obs[i:i + BATCH])
        counts["observations"] += len(obs[i:i + BATCH])
    for payload, ids in group_changes(changes, include_results=include_results):
        for i in range(0, len(ids), BATCH):
            api.patch("properties", "id=in.(" + ",".join(ids[i:i + BATCH]) + ")", {**payload, "inventory_status_observed_at": observed_at})
            counts["patches"] += 1
    return counts


def summarize(state: str, counts: dict, write_counts: dict | None, have_021: bool | None, dry_run: bool) -> str:
    lines = [f"Inventory status ({state}): {counts['rows']} rows - mapped {counts['mapped']}, unmapped {counts['unmapped']}, "
             f"unchanged {counts['unchanged']}, changed {counts['changed']}, results from a source-published status {counts['results_from_source']}",
             "  by status: " + (", ".join(f"{k} {v}" for k, v in sorted(counts["by_status"].items())) or "none")]
    if have_021 is False:
        lines.append("  migration 021 not applied - nothing written (plan only)")
    elif write_counts is not None:
        lines.append(f"  written: {write_counts['patches']} patch(es), {write_counts['observations']} observation(s)" + (" (dry run - nothing written)" if dry_run else ""))
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--state", default="FL")
    ap.add_argument("--sold", nargs="*", default=[str(p) for p in DEFAULT_SOLD_FILES], help="harvest_laft_sold*.json identity files")
    ap.add_argument("--report", default=str(REPORT_PATH))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    state = args.state
    problems = states.state_problems(state)
    if problems:
        print(f"::error title=inventory_status::{'; '.join(problems)} - nothing written")
        return 2
    url, key = os.environ.get("SUPABASE_URL", ""), os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not url or not key:
        print("::warning title=inventory_status::SUPABASE_URL / SUPABASE_SERVICE_KEY not set - nothing to plan against")
        return 0
    api = Api(url, key, dry_run=args.dry_run)
    have_021 = api.has_migration_021()
    rows = fetch_rows(api, state, with_results=bool(have_021) and api.has_migration_023())
    sold = load_sold_identities(args.sold) if state == "FL" else set()
    # Source-published result fields (date / amount / party) ride only on
    # a result the harvester resolved through an enabled outcome rule
    # (scripts/outcome_ingest.py); identity-only sold files yield none.
    results = OI.load_result_files(args.sold) if state == "FL" else {}
    changes, counts = plan(rows, today=date.today(), sold=sold, results=results)
    write_counts = None
    if have_021:
        have_023 = api.has_migration_023()
        write_counts = execute(api, changes, observed_at=now_iso(), run_id=os.environ.get("GITHUB_RUN_ID"),
                               include_transition=api.has_migration_022(), include_results=have_023)
        write_counts["migration_023"] = have_023
    text = summarize(state, counts, write_counts, have_021, args.dry_run)
    print(text)
    rp = Path(args.report)
    rp.parent.mkdir(parents=True, exist_ok=True)
    rp.write_text(json.dumps({"state": state, "migration_021": have_021, "dry_run": args.dry_run, **counts, "written": write_counts,
                              "note": "counts only; never a row value"}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write("```\n" + text + "\n```\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
