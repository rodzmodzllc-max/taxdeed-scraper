#!/usr/bin/env python3
"""Sync one activated state's adapter records into public.properties
(state-expansion sprint, 2026-09-30).

    python3 scripts/sync_state_inventory.py --state LA                 # live (SUPABASE_URL + SUPABASE_SERVICE_KEY)
    python3 scripts/sync_state_inventory.py --state LA --dry-run       # plan only, no request

Reads the rows `scripts/harvest_state_inventory.py` wrote with
`OtcRecord.to_properties_row()` (out/<state>_properties_rows.json - private,
never uploaded unencrypted) and upserts them on the table's own identity
(state, source, county, case_no). It refuses, before any request, unless:

  * the state is ACTIVATED (harvesters/governance/states.py);
  * the source is a PRODUCTION_VERIFIED registry row of that state with a
    runnable governance status;
  * the harvester's status file says the unit was read COMPLETE or
    INCOMPLETE (a FAILED / EMPTY / missing read syncs nothing - absence is
    for scripts/laft_lifecycle.py to judge, never this script).

Each row is stamped with the registry's publication decision
(publication_status - the frontend withholds anything not APPROVED*), its
ledger (ledger_type 'buy' for the AVAILABLE ledger) and harvester_source =
the source id. Public log discipline: counts only, never a row value.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO))
from harvesters.governance import states  # noqa: E402
from harvesters.governance.county_source_registry import RUNNABLE_GOVERNANCE, load_registry  # noqa: E402
from harvesters.governance.publication import PUBLISHABLE_STATUSES, effective_publication  # noqa: E402
sys.path.insert(1, str(Path(__file__).resolve().parent))
from source_publication import collectable  # noqa: E402
sys.path.insert(0, str(HERE))
import field_provenance as FP  # noqa: E402
import rest_pages as RP  # noqa: E402

REGISTRY = REPO / "data" / "county_source_registry.csv"
OUT = REPO / "out"
USER_AGENT = "taxdeed-scraper state-inventory-sync (+https://github.com/rodzmodzllc-max/taxdeed-scraper)"
BATCH = 500
LEDGER_TYPE_FOR_SOURCE = {"laft": "buy", "auction": "auctions", "certificate": "lien"}
OBSERVED = frozenset({"COMPLETE", "INCOMPLETE"})


def _read_headers(key: str) -> dict:
    return {"apikey": key, "Authorization": f"Bearer {key}", "User-Agent": USER_AGENT}


# Columns a county list can supply, recorded in field_provenance as
# source `county_list` (rank 2) so the statewide enrichment factory never
# overwrites them and a reader can tell list values from enriched ones.
LIST_FIELDS = ("parcel", "owner_name", "address", "legal_desc", "assessed", "market", "taxable_value", "land_value",
               "improvement_value", "acreage", "land_use", "tax_year", "latitude", "longitude", "certificate_no",
               "min_bid", "purchase_amount", "sale_date", "result_amount", "result_date")
PLACEHOLDER_PREFIXES = ("Parcel ", "Case ")


NEVER_NULL_PATH_KEYS = ("purchase_url", "purchase_url_kind")

# ---------------------------------------------------------------------------
# Acquisition-evidence persistence (2026-10-05)
# ---------------------------------------------------------------------------
# PostgREST's merge-duplicates upsert REPLACES a jsonb column. A row carries
# the adapter's own otc_provenance (layer, identifier, coordinates ...), while
# the verified acquisition record - steps, office, contacts, form, evidence
# page - is written by the laft lifecycle / purchase-path engine into the SAME
# column. Sending the adapter's dict as-is erased that record: on 2026-10-04
# 3,500 East Baton Rouge rows kept purchase_path_type but lost the record.
# The sync now merges into the stored dict (stored_rows) and keeps verified
# evidence unless this read carries equal-or-richer evidence for the same
# path type. The group below moves together - never key by key, so evidence
# from two observations is never spliced into one record.
ACQUISITION_KEYS = ("acquisition", "purchase_evidence_url", "purchase_evidence_type", "purchase_evidence_title",
                    "purchase_instructions", "purchase_path_observed_on")
PATH_COLUMNS = ("purchase_path_type", "purchase_path_scope", "purchase_path_evidence", "purchase_path_observed_on",
                "purchase_url", "purchase_url_kind")
_CONTACT_KEYS = ("phone", "email", "address", "mailing_address", "application_url", "office", "payment")


def acquisition_strength(prov) -> tuple:
    """How much VERIFIED acquisition evidence an otc_provenance dict carries:
    (complete record, published steps + contact fields, has an evidence
    page). () when it carries none. Only what the source published counts."""
    if not isinstance(prov, dict):
        return ()
    acq = prov.get("acquisition")
    if not isinstance(acq, dict) or not acq.get("mode"):
        return ()
    steps = [s for s in (acq.get("steps") or []) if str(s).strip()]
    complete = bool(steps) and any(acq.get(k) for k in ("phone", "email", "address", "mailing_address", "application_url"))
    fields = len(steps) + sum(1 for k in _CONTACT_KEYS if acq.get(k))
    return (int(complete), fields, int(bool(acq.get("evidence_url") or prov.get("purchase_evidence_url"))))


def merge_acquisition(row: dict, stored: dict | None) -> tuple[dict, dict, str]:
    """(otc_provenance to send, path columns to restore, outcome) for one row
    of the SAME identity (state, source, county, case_no) and the same
    harvester_source as `stored` - the caller guarantees that. Pure.

    - The stored dict is the base; the row's own non-blank keys overwrite it
      (adapter facts are refreshed, never lost to a blank).
    - Verified acquisition evidence (ACQUISITION_KEYS) is a unit:
        * a row that states a DIFFERENT, non-null path type than the stored
          one takes only its own evidence (never mixed across path types);
        * a row whose evidence is at least as strong as the stored one
          replaces it (a newer equal-or-richer observation);
        * otherwise the stored evidence is kept - a read that lacks the
          field, or carries weaker evidence, erases nothing.
    - An ACTIVE row that states no path (purchase_path_type null) over a
      stored verified path keeps the stored path columns too, so the record
      and the columns it belongs to stay together. A row that is no longer
      active sheds its path, as before (a closed listing has no acquisition
      path - scripts/harvest_expansion.py)."""
    new = row.get("otc_provenance") if isinstance(row.get("otc_provenance"), dict) else {}
    stored = stored or {}
    sprov = stored.get("otc_provenance") if isinstance(stored.get("otc_provenance"), dict) else {}
    merged = dict(sprov)
    merged.update({k: v for k, v in new.items() if not FP.is_blank(v)})
    stored_type = stored.get("purchase_path_type")
    states_path = "purchase_path_type" in row
    row_type = row.get("purchase_path_type") if states_path else stored_type
    active = str(row.get("status") or "active").lower() == "active"
    restore: dict = {}
    s_strength, n_strength = acquisition_strength(sprov), acquisition_strength(new)

    def take(src: dict) -> None:
        for k in ACQUISITION_KEYS:
            if k in src and not FP.is_blank(src[k]):
                merged[k] = src[k]
            else:
                merged.pop(k, None)

    if not s_strength:
        take(new)
        return merged, restore, ("acquisition_added" if n_strength else "no_acquisition")
    if states_path and row_type is None:
        if not active:
            take(new)
            return merged, restore, "acquisition_shed_not_active"
        if stored_type:
            restore = {k: stored.get(k) for k in PATH_COLUMNS if k in stored}
        take(sprov)
        return merged, restore, "acquisition_preserved"
    if stored_type and row_type and row_type != stored_type:
        take(new)
        return merged, restore, "acquisition_path_type_changed"
    if n_strength and n_strength >= s_strength:
        take(new)
        return merged, restore, "acquisition_replaced_equal_or_richer"
    take(sprov)
    return merged, restore, "acquisition_preserved"


def _record_source(source_id: str) -> str:
    """The properties.source a configured adapter source writes ('laft' /
    'auction' / 'certificate'); '' for a source no adapter configures."""
    from harvesters.otc.adapters import expansion as EX  # noqa: PLC0415
    for srcs in EX.SOURCES.values():
        for src in srcs:
            if src.config.source_id == source_id:
                return src.config.record_source
    return ""


def identity(row: dict) -> tuple:
    return (row.get("source"), row.get("county"), row.get("case_no"))


def list_provenance(row: dict, stored, observed_at: str) -> dict:
    """The row's field_provenance after this read: the stored entries, with
    every column the county list supplied (a non-null value) stamped
    `county_list` and every list column the list now leaves blank dropped
    - but only where the stored entry was the list's own (an enrichment
    entry for a column the list never carries is kept verbatim)."""
    prov = (row.get("otc_provenance") or {}) if isinstance(row.get("otc_provenance"), dict) else {}
    merged = FP.load_provenance(stored)
    for col in LIST_FIELDS:
        if col not in row:
            continue
        value = row[col]
        if FP.is_blank(value) or (col == "address" and str(value).startswith(PLACEHOLDER_PREFIXES)):
            if (merged.get(col) or {}).get("source") == "county_list":
                merged.pop(col, None)
            continue
        meta = {"source_id": row.get("source_id"), "list_url": row.get("list_url"), "layer_url": prov.get("layer_url"),
                "adapter": prov.get("adapter"), "recorded_at": observed_at}
        if col in ("latitude", "longitude") and prov.get("coordinates"):
            meta["derived"] = prov["coordinates"]
        merged[col] = FP.provenance_entry("county_list", **meta)
    return merged


def rows_path(state: str) -> Path:
    return OUT / f"{state.lower()}_properties_rows.json"


def registry_rows(state: str, path: Path = REGISTRY) -> dict[str, object]:
    return {r.source_id: r for r in load_registry(path) if r.state == state}


def plan(state: str, rows: list[dict], registry: dict, status_units: dict[str, str], *, observed_at: str | None = None,
         stored_provenance: dict | None = None, stored_first_seen: dict | None = None,
         stored_rows: dict | None = None) -> tuple[list[dict], dict]:
    """(rows to upsert, counts). Pure - no I/O. Raises ValueError when the
    state or a row's source may not be synced at all.

    Every row read this run is stamped `last_seen_at` = observed_at (the
    freshness the Dashboard and the stale check read) and its
    field_provenance merged from `stored_provenance` (identity -> stored
    jsonb). Rows are key-aligned PER SOURCE, not per batch: a column one
    source publishes is sent (NULL when that source's row leaves it blank),
    a column the source never publishes is not sent at all - so a value the
    enrichment factory filled is never nulled by another source's columns.

    `first_seen_at` is sent too (properties_seen_order_check requires
    last_seen_at >= first_seen_at): a row already stored keeps its stored
    value (`stored_first_seen`, identity -> timestamp), a new row is first
    seen at this run's observed_at - never the insert's later now() default.

    `stored_rows` (identity -> {harvester_source, otc_provenance, path
    columns}) is what the row's otc_provenance is MERGED into
    (merge_acquisition): verified acquisition evidence is never erased by a
    read that lacks it, and a stored row of another source is never used."""
    observed_at = observed_at or FP.now_iso()
    stored_provenance = stored_provenance or {}
    stored_first_seen = stored_first_seen or {}
    stored_rows = stored_rows or {}
    if not states.is_activated(state):
        raise ValueError(f"state {state} is not activated: {', '.join(states.activation_blockers(state))}")
    counts = {"input": len(rows), "upsert": 0, "skipped_unit_not_read": 0, "wrong_state": 0, "withheld_not_publishable": 0,
              "written_review_pending": 0}
    out: list[dict] = []
    keys: dict[str, set[str]] = {}
    for r in rows:
        if r.get("state") != state:
            counts["wrong_state"] += 1
            continue
        reg = registry.get(r.get("source_id") or "")
        if reg is None or not reg.is_production or reg.governance_status not in RUNNABLE_GOVERNANCE:
            raise ValueError(f"source {r.get('source_id')!r} is not a production, governance-approved {state} registry row")
        if unit_status(status_units, r.get("source_id"), r.get("county")) not in OBSERVED:
            counts["skipped_unit_not_read"] += 1
            continue
        if not collectable(reg, r.get("source") or ""):
            # A BLOCKED source, or an auction / lien source without an APPROVED
            # publication decision: not written at all.
            counts["withheld_not_publishable"] += 1
            continue
        row = dict(r)
        # The source's review status rides on every row: an AVAILABLE source
        # awaiting review is written (admins and customer preview see it,
        # labelled) and the frontend keeps customers on the publication rule.
        row["publication_status"] = effective_publication(reg)
        if row["publication_status"] not in PUBLISHABLE_STATUSES:
            counts["written_review_pending"] += 1
        row["ledger_type"] = LEDGER_TYPE_FOR_SOURCE[row["source"]]
        row["harvester_source"] = reg.source_id
        row["last_seen_at"] = observed_at
        first = stored_first_seen.get(identity(row)) if identity(row) in stored_first_seen else observed_at
        row["first_seen_at"] = first if first is None or FP_ts(first) <= FP_ts(observed_at) else observed_at
        row["field_provenance"] = list_provenance(row, stored_provenance.get(identity(row)), observed_at)
        prior = stored_rows.get(identity(row))
        if prior is not None and prior.get("harvester_source") not in (None, reg.source_id):
            prior = None                        # another source's row: never a merge base
        if prior is not None:                    # a new row's own dict is sent unchanged
            prov, restore, outcome = merge_acquisition(row, prior)
            row["otc_provenance"] = prov
            row.update(restore)
            if outcome != "no_acquisition":
                # Reported only when it happens (counts only, never a value).
                counts[outcome] = counts.get(outcome, 0) + 1
        keys.setdefault(reg.source_id, set()).update(row)
        out.append(row)
    # A source whose rows do not state their own acquisition path (Louisiana:
    # the laft lifecycle writes it - purchase_path_type + purchase_url, tied by
    # migration 023's properties_purchase_path_url_check) never sends a NULL
    # purchase URL over that verified path. Sources that state the path on the
    # row (scripts/harvest_expansion.py) keep sending the pair with it, so the
    # pairing constraint always sees a consistent row.
    for sid in keys:
        if "purchase_path_type" not in keys[sid] and any(r.get("purchase_url") is None for r in out if r["harvester_source"] == sid):
            keys[sid].difference_update(NEVER_NULL_PATH_KEYS)
    # PostgREST bulk upserts need one key set per request: rows are aligned
    # on their own SOURCE's key set (upsert() sends one source per request).
    out = [{k: r.get(k) for k in sorted(keys[r["harvester_source"]])} for r in out]
    counts["upsert"] = len(out)
    return out, counts


def FP_ts(value: str):
    """A comparable instant for an ISO timestamp (PostgREST or FP.now_iso)."""
    from datetime import datetime, timezone  # noqa: PLC0415
    t = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


CLOSEABLE = frozenset({"COMPLETE", "EMPTY"})


def plan_close(state: str, harvested: list[dict], stored: list[dict], units: dict[str, str], source_ids: set[str]) -> list[dict]:
    """Stored ACTIVE rows of this state's own production sources that a
    COMPLETE or EMPTY read of their county no longer lists -> closed. Pure.
    Absence is only 'closed' (the list dropped it) - never sold, redeemed or
    any other result; an INCOMPLETE / FAILED / unread county closes nothing."""
    seen = {(r.get("source"), r.get("county"), r.get("case_no")) for r in harvested if r.get("state") == state}
    out = []
    for r in stored:
        if r.get("state") != state or r.get("status") != "active" or r.get("harvester_source") not in source_ids:
            continue
        if unit_status(units, r.get("harvester_source"), r.get("county")) not in CLOSEABLE:
            continue
        if (r.get("source"), r.get("county"), r.get("case_no")) not in seen:
            out.append({"id": r["id"], "status": "closed", "delisted_at": FP.now_iso()})
    return out


def stored_active(base: str, key: str, state: str, source_ids: set[str]) -> list[dict]:
    """Every stored active row of these sources - keyset pages with a bounded
    retry (rest_pages): an offset read sorted the whole state per page and
    crossed the statement timeout under load (HTTP 500)."""
    return RP.read_all(base, "properties", _read_headers(key),
                       {"select": "id,state,source,county,case_no,status,harvester_source", "state": f"eq.{state}",
                        "status": "eq.active", "harvester_source": f"in.({','.join(sorted(source_ids))})"})


def close_rows(base: str, key: str, closes: list[dict]) -> None:
    for c in closes:
        req = urllib.request.Request(
            f"{base.rstrip('/')}/rest/v1/properties?id=eq.{c['id']}", data=json.dumps({k: v for k, v in c.items() if k != "id"}).encode(),
            method="PATCH", headers={"apikey": key, "Authorization": f"Bearer {key}", "User-Agent": USER_AGENT,
                                     "Content-Type": "application/json", "Prefer": "return=minimal"})
        with urllib.request.urlopen(req, timeout=60):
            pass


# Worst first: a county-level fallback is only as good as its weakest read.
_FALLBACK_ORDER = ("FAILED", "INCOMPLETE", "COMPLETE", "EMPTY")


def unit_status(units: dict, source_id, county) -> str | None:
    """The status of ONE source's read of ONE county. A per-source entry
    ((source_id, county) key) decides for that source alone; a bare county
    key is the fallback for status files whose entries name no source."""
    hit = units.get((str(source_id or ""), str(county or "")))
    return hit if hit is not None else units.get(str(county or ""))


def _entries(path: Path) -> list[dict]:
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    entries = data.get("counties") if isinstance(data, dict) else data
    if isinstance(entries, dict):
        entries = [{"county": k, **v} for k, v in entries.items()]
    return [e for e in entries or [] if isinstance(e, dict)]


def _rank(status: str) -> int:
    return _FALLBACK_ORDER.index(status) if status in _FALLBACK_ORDER else 0


def status_units(path: Path) -> dict[str, str]:
    """{county: status} = the WORST status any entry of that county reports
    (FAILED > INCOMPLETE > COMPLETE > EMPTY). The fallback for rows whose
    source has no entry of its own (source_units)."""
    out: dict[str, str] = {}
    for e in _entries(path):
        county, status = str(e.get("county")), str(e.get("status"))
        if county not in out or _rank(status) < _rank(out[county]):
            out[county] = status
    return out


def source_units(path: Path) -> dict[tuple[str, str], str]:
    """{(source_id, county): status} - one source's own read of one county.
    2026-10-09: a single merged county verdict let a failed Detroit programs
    read hide the complete Detroit lots read, so 30,706 lot rows were not
    synced and kept their 2026-10-06 last read."""
    return {(str(e["source_id"]), str(e.get("county"))): str(e.get("status")) for e in _entries(path) if e.get("source_id")}


def units_for(path: Path) -> dict:
    """Both maps in one: unit_status() reads the per-source key first."""
    return {**status_units(path), **source_units(path)}


def stored_provenance(base: str, key: str, state: str, source_ids: set[str], first_seen: dict | None = None,
                      rows_out: dict | None = None) -> dict:
    """identity -> the stored field_provenance of this state's rows from
    these sources (every status), so a sync merges into it. When
    `first_seen` is given it is filled with identity -> stored first_seen_at;
    when `rows_out` is given, with identity -> the stored harvester_source,
    otc_provenance and acquisition path columns (merge_acquisition)."""
    out: dict = {}
    rows = RP.read_all(base, "properties", _read_headers(key),
                       {"select": "id,source,county,case_no,field_provenance,first_seen_at,harvester_source,otc_provenance,"
                                  + ",".join(PATH_COLUMNS), "state": f"eq.{state}",
                        "harvester_source": f"in.({','.join(sorted(source_ids))})"})
    for r in rows:
        out[identity(r)] = r.get("field_provenance")
        if first_seen is not None:
            first_seen[identity(r)] = r.get("first_seen_at")
        if rows_out is not None:
            rows_out[identity(r)] = {k: r.get(k) for k in ("harvester_source", "otc_provenance", *PATH_COLUMNS)}
    return out


def upsert(base: str, key: str, rows: list[dict]) -> int:
    groups: dict[str, list[dict]] = {}
    for r in rows:
        groups.setdefault(r.get("harvester_source") or "", []).append(r)
    return sum(_upsert(base, key, g) for g in groups.values())


def _upsert(base: str, key: str, rows: list[dict]) -> int:
    requests = 0
    for i in range(0, len(rows), BATCH):
        chunk = rows[i:i + BATCH]
        req = urllib.request.Request(
            f"{base.rstrip('/')}/rest/v1/properties?on_conflict=state,source,county,case_no",
            data=json.dumps(chunk).encode(), method="POST",
            headers={"apikey": key, "Authorization": f"Bearer {key}", "User-Agent": USER_AGENT, "Content-Type": "application/json",
                     "Prefer": "resolution=merge-duplicates,return=minimal"})
        try:
            with urllib.request.urlopen(req, timeout=120):
                requests += 1
        except urllib.error.HTTPError as exc:
            # Public log: PostgREST's code + message name the constraint / column; its
            # `details` can echo the failing row, so it is never printed.
            try:
                err = json.loads(exc.read().decode("utf-8", "replace"))
            except ValueError:
                err = {}
            raise SystemExit(f"::error title=sync::upsert rejected: HTTP {exc.code} {err.get('code')} {str(err.get('message'))[:200]}") from None
    return requests


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--state", required=True)
    ap.add_argument("--rows", default=None)
    ap.add_argument("--status", required=True, help="the harvester's status file (per-unit COMPLETE / INCOMPLETE / ...)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--close-absent", action="store_true",
                    help="close stored active rows a COMPLETE / EMPTY county read no longer lists (status 'closed' only)")
    args = ap.parse_args(argv)
    path = Path(args.rows) if args.rows else rows_path(args.state)
    if not path.exists():
        print(f"{args.state}: no rows file ({path.name}) - nothing to sync")
        return 0
    rows = json.loads(path.read_text(encoding="utf-8"))
    url, key = os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_SERVICE_KEY")
    import source_publication as SP  # noqa: PLC0415 - registry + latest valid admin review
    reg, _ = SP.registry_with_reviews(args.state) if (url and key and not args.dry_run) else SP.registry_with_reviews(args.state, reviews={})
    stored, first_seen, stored_rows = {}, {}, {}
    if url and key and not args.dry_run and states.is_activated(args.state):
        stored = stored_provenance(url, key, args.state, {sid for sid, r in reg.items() if r.is_production} or {"-"},
                                   first_seen=first_seen, rows_out=stored_rows)
    try:
        to_send, counts = plan(args.state, rows, reg, units_for(Path(args.status)), stored_provenance=stored,
                               stored_first_seen=first_seen, stored_rows=stored_rows)
    except ValueError as exc:
        print(f"::error title=sync_{args.state.lower()}::{exc} - 0 requests made")
        return 2
    print(f"{args.state} sync plan: " + ", ".join(f"{k}={v}" for k, v in counts.items()))
    if args.dry_run or not (to_send or args.close_absent):
        return 0
    if not url or not key:
        print(f"::error title=sync_{args.state.lower()}::SUPABASE_URL / SUPABASE_SERVICE_KEY not set - 0 requests made")
        return 2
    n = upsert(url, key, to_send) if to_send else 0
    print(f"{args.state}: upserted {len(to_send)} row(s) in {n} request(s)")
    if args.close_absent:
        # Only sources this run may publish: a gated source's stored rows are never
        # 'closed' by another source's read of the same county.
        source_ids = {sid for sid, r in reg.items() if r.is_production and collectable(r, _record_source(sid))}
        units = units_for(Path(args.status))
        closes = plan_close(args.state, rows, stored_active(url, key, args.state, source_ids), units, source_ids)
        close_rows(url, key, closes)
        print(f"{args.state}: closed {len(closes)} row(s) no longer listed by a COMPLETE / EMPTY county read")
    return 0


if __name__ == "__main__":
    sys.exit(main())
