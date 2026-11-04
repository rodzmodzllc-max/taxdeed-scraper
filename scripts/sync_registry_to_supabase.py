#!/usr/bin/env python3
"""Bring public.county_source_registry in line with data/county_source_registry.csv
(audit B14 / F4, 2026-10-29).

Why: the production table was seeded by hand on 2026-09-29 / 30. Since
audit ops #251, scripts/unit_freshness.py inserts the CSV row of a unit the
table lacks - but only for a unit a harvest just read. Two gaps remain:
a source no freshness run has reported yet has no row (customers read
"No read of this source has been recorded yet"), and an existing row's
metadata is never refreshed from the CSV (the Louisiana row still named the
retired a4h4-zi7e dataset; the Minnesota rows named REST endpoints).

What it does (dry run unless --apply):

* reads the CSV (the source of truth for a source's metadata) and the
  table (keyset pages, scripts/rest_pages.py);
* matches a CSV row to a table row on (state, county, source_id); a candidate
  row (no source_id) on (state, county, canonical URL) with the scheme,
  "www." and a trailing slash ignored;
* INSERTs each CSV row the table lacks, built by
  unit_freshness.registry_insert_row (the same insert as #251, without
  freshness values) and sent through unit_freshness.RegistryApi.insert;
* PATCHes an existing row's METADATA columns only where a value differs.

What it never does:

* never deletes a row (a table row the CSV no longer names is counted and
  left as it is);
* never writes the freshness columns (last_attempt_*, last_success_*,
  consecutive_failures, last_error_category) - scripts/unit_freshness.py owns
  them;
* never changes an existing row's publication_status / restrictions -
  scripts/publication_gate.py owns them (an admin review is applied there);
* never sends a value the table's CHECK constraints refuse: such a CSV row is
  counted as refused and skipped.

Logs: counts only (states, sources, columns), never a URL.

    python3 scripts/sync_registry_to_supabase.py            # plan (no write)
    python3 scripts/sync_registry_to_supabase.py --apply    # write
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Callable

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(HERE))

import unit_freshness as UF  # noqa: E402  - the one INSERT shape (registry_insert_row)

REGISTRY = REPO / "data" / "county_source_registry.csv"
TABLE = "county_source_registry"
USER_AGENT = "taxdeed-scraper/1.0 (registry sync)"

# Columns this script keeps in step with the CSV on existing rows.
# Set on INSERT only: owned afterwards by another writer (see the docstring).
INSERT_ONLY = ("completeness_status", "publication_status", "restrictions")
IDENTITY = ("state", "county", "source_id")
# Columns this script keeps in step with the CSV on existing rows: every table
# column a CSV row carries (unit_freshness.REGISTRY_TABLE_COLUMNS) except the
# identity and the insert-only ones.
METADATA = tuple(c for c in UF.REGISTRY_TABLE_COLUMNS if c not in (*IDENTITY, *INSERT_ONLY))
NOT_NULL = {"access_method", "machine_format", "verification_status", "governance_status", "last_checked",
            "completeness_status", "evidence_ref", "publication_status", "publishing_unit"}

# The production CHECK constraints (read 2026-10-29; migrations 018 / 020 / 021 / 022).
ALLOWED = {
    "inventory_type": {"POST_SALE_FIXED_PRICE", "STRUCK_OFF_HELD_IN_TRUST", "FUTURE_RESALE", "POST_SALE",
                       "STATE_HELD_TAX_LAND", "ADJUDICATED_PROPERTY"},
    "source_authority": {"GOVERNMENT_DIRECT", "GOVERNMENT_PLATFORM", "VENDOR_COUNSEL", "VENDOR_AUCTION"},
    "purchase_url_kind": {"purchase_instructions", "offer_form", "bid_form", "application_form", "online_purchase"},
    "access_method": {"HTTP_GET_PDF", "HTTP_GET_HTML", "HTTP_POST_FORM", "JSON_ENDPOINT", "HEADLESS_BROWSER",
                      "VENDOR_API", "UNKNOWN", "NONE"},
    "machine_format": {"PDF", "HTML_TABLE", "HTML_CARDS", "JSON", "XLSX", "DOCX", "PORTAL", "UNKNOWN", "NONE", "CSV"},
    "verification_status": {"PRODUCTION_VERIFIED", "SEARCH_EVIDENCE_ONLY", "SOURCE_EXISTS_ACCESS_UNKNOWN",
                            "HISTORICAL_ONLY", "NOT_FOUND_AFTER_SEARCH", "MANUAL_REVIEW_REQUIRED", "BLOCKED_VENDOR_ONLY"},
    "governance_status": {"APPROVED", "APPROVED_GRANDFATHERED", "TERMS_NOT_VERIFIED", "LEGAL_REVIEW_REQUIRED",
                          "BLOCKED", "NOT_APPLICABLE"},
    "completeness_status": {"COMPLETE", "EMPTY", "INCOMPLETE", "FAILED", "UNKNOWN"},
    "publication_status": {"APPROVED", "APPROVED_GRANDFATHERED", "UNREVIEWED", "RESTRICTED", "BLOCKED"},
    "publishing_unit": {"COUNTY", "PARISH", "BOROUGH", "MUNICIPALITY", "STATE"},
    "amount_kind": {"MINIMUM_PURCHASE_AMOUNT", "OPENING_BID", "ORIGINAL_OPENING_BID", "FIXED_PURCHASE_PRICE",
                    "ESTIMATED_PURCHASE_PRICE", "PUBLISHED_AMOUNT_KIND_UNSPECIFIED", "NOT_PUBLISHED",
                    "QUOTED_ON_APPLICATION"},
}
LEDGER_WORDS = {"AUCTIONS", "AVAILABLE", "LIENS_CERTIFICATES"}


def _v(x):
    """CSV '' -> None (the table stores NULL, never an empty string)."""
    x = (x or "").strip() if isinstance(x, str) or x is None else x
    return x if x not in ("", None) else None


def url_key(u) -> str:
    u = (u or "").strip().lower()
    for p in ("https://", "http://"):
        if u.startswith(p):
            u = u[len(p):]
    if u.startswith("www."):
        u = u[4:]
    return u.rstrip("/")


def row_key(r: dict) -> tuple:
    sid = _v(r.get("source_id"))
    if sid:
        return (r.get("state"), r.get("county"), sid)
    return (r.get("state"), r.get("county"), None, url_key(r.get("canonical_url")))


def problems(body: dict) -> list[str]:
    """CHECK-constraint violations of a body (an insert or a patch merged on
    its row), named by column."""
    out = []
    for c, ok in ALLOWED.items():
        v = body.get(c)
        if v is not None and v not in ok:
            out.append(c)
    led = body.get("ledgers")
    if led is not None and not set(str(led).split("|")) <= LEDGER_WORDS:
        out.append("ledgers")
    for c in NOT_NULL:
        if c in body and body[c] is None:
            out.append(c)
    if "purchase_url" in body and (body.get("purchase_url") is None) != (body.get("purchase_url_kind") is None):
        out.append("purchase_pair")
    if body.get("governance_status") == "BLOCKED" and body.get("canonical_url") is not None:
        out.append("blocked_has_url")
    if body.get("verification_status") == "PRODUCTION_VERIFIED" and not body.get("harvester"):
        out.append("production_without_harvester")
    if "publishing_unit" in body and (body.get("publishing_unit") == "STATE") != (body.get("county") == "STATEWIDE"):
        out.append("statewide")
    return out


def csv_rows(path: Path = REGISTRY) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def plan(csv_in: list[dict], table: list[dict]) -> dict:
    """{'insert': [body], 'patch': [(id, body)], 'refused': Counter, 'table_only': int,
    'patched_columns': Counter}. Pure: no I/O."""
    by_key: dict[tuple, dict] = {}
    for t in table:
        by_key.setdefault(row_key(t), t)
    seen: set = set()
    inserts, patches = [], []
    refused: Counter = Counter()
    cols: Counter = Counter()
    for r in csv_in:
        k = row_key(r)
        if k in seen:
            refused["duplicate_csv_key"] += 1
            continue
        seen.add(k)
        meta = {c: _v(r.get(c)) for c in METADATA}
        cur = by_key.get(k)
        if cur is None:
            # The same INSERT unit_freshness sends for a unit the table lacks
            # (audit ops #251) - one insert shape, no freshness values.
            body = UF.registry_insert_row(r, {})
            bad = problems(body)
            if bad:
                refused.update(bad)
                continue
            inserts.append(body)
            continue
        diff = {c: v for c, v in meta.items() if _v(cur.get(c)) != v and str(_v(cur.get(c))) != str(v)}
        if not diff:
            continue
        merged = {**{c: _v(cur.get(c)) for c in (*IDENTITY, *METADATA, *INSERT_ONLY) if c in cur}, **diff}
        bad = problems(merged)
        if bad:
            refused.update(bad)
            continue
        cols.update(list(diff))
        patches.append((cur["id"], diff))
    matched = {row_key(r) for r in csv_in}
    table_only = sum(1 for t in table if row_key(t) not in matched)
    return {"insert": inserts, "patch": patches, "refused": refused, "table_only": table_only, "patched_columns": cols}


class Api:
    def __init__(self, base: str, key: str):
        self.base = base.rstrip("/")
        self.h = {"apikey": key, "Authorization": f"Bearer {key}", "User-Agent": USER_AGENT,
                  "Accept": "application/json"}

    def read(self, fetch: Callable | None = None) -> list[dict]:
        import rest_pages  # noqa: PLC0415
        return rest_pages.read_all(self.base, TABLE, self.h,
                                   {"select": ",".join(("id", *IDENTITY, *METADATA, *INSERT_ONLY))}, fetch=fetch)

    def _send(self, method: str, path: str, body) -> None:
        req = urllib.request.Request(f"{self.base}/rest/v1/{path}", data=json.dumps(body, default=str).encode(),
                                     method=method, headers={**self.h, "Content-Type": "application/json",
                                                             "Prefer": "return=minimal"})
        with urllib.request.urlopen(req, timeout=60):
            pass

    def insert(self, rows: list[dict]) -> int:
        """One POST per row through unit_freshness.RegistryApi.insert (the
        single insert path); returns how many were sent."""
        api = UF.RegistryApi(self.base, self.h["apikey"])
        for r in rows:
            api.insert(r)
        return len(rows)

    def patch(self, row_id: str, body: dict) -> None:
        self._send("PATCH", f"{TABLE}?id=eq.{urllib.parse.quote(str(row_id), safe='')}", body)


def summary(p: dict) -> str:
    ins_by = Counter(f"{b['state']}" for b in p["insert"])
    lines = [f"registry sync plan: insert {len(p['insert'])}, patch {len(p['patch'])}, "
             f"refused {sum(p['refused'].values())}, table-only rows left unchanged {p['table_only']}",
             "  inserts by state: " + (", ".join(f"{k} {v}" for k, v in sorted(ins_by.items())) or "none"),
             "  patched columns: " + (", ".join(f"{k} {v}" for k, v in sorted(p["patched_columns"].items())) or "none")]
    if p["refused"]:
        lines.append("  refused (constraint): " + ", ".join(f"{k} {v}" for k, v in sorted(p["refused"].items())))
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--apply", action="store_true", help="write the plan (default: print it only)")
    ap.add_argument("--registry", default=str(REGISTRY))
    a = ap.parse_args(argv)
    base, key = os.environ.get("SUPABASE_URL", ""), os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not base or not key:
        print("SUPABASE_URL / SUPABASE_SERVICE_KEY not set - nothing read or written")
        return 0
    api = Api(base, key)
    p = plan(csv_rows(Path(a.registry)), api.read())
    print(summary(p))
    if not a.apply:
        print("plan only - nothing written (pass --apply to write)")
        return 0
    n = api.insert(p["insert"])
    for rid, body in p["patch"]:
        api.patch(rid, body)
    print(f"wrote: inserted {n}, patched {len(p['patch'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
