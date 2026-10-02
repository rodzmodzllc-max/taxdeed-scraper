#!/usr/bin/env python3
"""Detect meaningful, source-backed changes to properties and turn them into
customer alerts (Customer-value sprint, 2026-10-01).

Runs after a state's syncs (laft / deeds / certificates / expansion jobs).
Compares each row of the state to the snapshot taken at the previous run and
records what changed - nothing else:

  status            -> removed (active -> closed/gone), reactivated, status_changed
  inventory_status  -> status_changed
  sale_date         -> sale_date_changed
  opening bid       -> opening_bid_changed (purchase_amount, else min_bid, else bid)
  acquisition path  -> acquisition_path_changed (type, URL)
  acquisition evid. -> acquisition_evidence_changed (evidence page, last verified)
  source            -> source_changed (source id, listing URL, publication status)
  result fields     -> result_published (only when the SOURCE published them)
  enrichment fields -> field_changed (assessed, taxable, acreage, land use, flood
                       zone, coordinates/imagery/legal description on file)
  new row           -> new_listing (only after a baseline exists for the state)

No speculation: dropping off a list is "removed" (the lifecycle's own close-out,
never a sale); no event is derived from anything the row does not carry.

Storage, probed (migration 024 written, applied separately):
  * 024 present  -> snapshots in property_change_snapshots, events in
                    property_change_events, per-source run counts in
                    source_observation_runs, alerts in user_alerts for
                    watchers (bid_list) and for saved searches whose criteria a
                    new listing matches (scripts/saved_search_match.py);
                    alert_preferences opt-outs honoured.
  * 024 absent   -> snapshots in the job's harvest cache
                    (out/.harvest_cache/change_snapshots_<STATE>.json) and the
                    same per-source counts in the evidence report; no customer
                    table is written.
Counts only are printed (public logs).

    python3 scripts/detect_property_changes.py --state FL --source laft [--dry-run]

--source (auction | laft | certificate) scopes one ledger, so each job detects
only what it just synced; omitted = every ledger of the state.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import saved_search_match as SSM  # noqa: E402

USER_AGENT = "taxdeed-scraper change-detection (+https://github.com/rodzmodzllc-max/taxdeed-scraper)"
CACHE_DIR = HERE.parent / "out" / ".harvest_cache"
PAGE = 1000
SELECT = ("id,state,county,source,source_id,harvester_source,case_no,parcel,address,status,inventory_status,sale_date,bid,min_bid,"
          "purchase_amount,purchase_path_type,purchase_url,purchase_path_observed_on,list_url,publication_status,assessed,"
          "taxable_value,acreage,land_use,prop_type,flood_zone,latitude,photo_url,legal_desc,result_date,result_amount,"
          "last_seen_at,evidence_url:otc_provenance->>purchase_evidence_url")
GONE = SSM.GONE
# field -> event kind (status is classified separately)
FIELD_KIND = {
    "inventory_status": "status_changed",
    "sale_date": "sale_date_changed",
    "opening_bid": "opening_bid_changed",
    "purchase_path_type": "acquisition_path_changed",
    "purchase_url": "acquisition_path_changed",
    "evidence_url": "acquisition_evidence_changed",
    "purchase_path_observed_on": "acquisition_evidence_changed",
    "source_id": "source_changed",
    "list_url": "source_changed",
    "publication_status": "source_changed",
    "assessed": "field_changed",
    "taxable_value": "field_changed",
    "acreage": "field_changed",
    "land_use": "field_changed",
    "flood_zone": "field_changed",
    "has_coordinates": "field_changed",
    "has_imagery": "field_changed",
    "legal_desc_hash": "field_changed",
}
# The enrichment fields a watcher is alerted about (coordinates / imagery / a
# rewritten legal description are recorded as events, never pushed as alerts).
ALERT_FIELDS = frozenset({"assessed", "taxable_value", "acreage", "land_use", "flood_zone"})
ALERT_KIND = {"removed": "watched_status", "reactivated": "watched_status", "status_changed": "watched_status",
              "result_published": "watched_status", "sale_date_changed": "watched_auction",
              "opening_bid_changed": "watched_auction", "acquisition_path_changed": "watched_acquisition",
              "acquisition_evidence_changed": "watched_acquisition", "source_changed": "watched_source",
              "field_changed": "watched_field"}
FIELD_LABEL = {"status": "Status", "inventory_status": "Availability status", "sale_date": "Sale date",
               "opening_bid": "Opening bid / published amount", "purchase_path_type": "Acquisition path",
               "purchase_url": "Acquisition page", "evidence_url": "Acquisition evidence page",
               "purchase_path_observed_on": "Acquisition process last verified", "source_id": "Source",
               "list_url": "Source listing", "publication_status": "Publication decision", "assessed": "Assessed value",
               "taxable_value": "Taxable value", "acreage": "Acreage", "land_use": "Land use", "flood_zone": "Flood zone",
               "result_date": "Published result date", "result_amount": "Published result amount"}
LEDGER_WORD = {"auction": "Auction", "laft": "Available", "certificate": "Lien / certificate"}


def _norm(v):
    if v is None or v == "":
        return None
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def snapshot(row: dict) -> dict:
    """The tracked, normalised view of one row (strings or None)."""
    legal = row.get("legal_desc")
    return {
        "status": _norm(str(row.get("status") or "active").lower()),
        "inventory_status": _norm(row.get("inventory_status")),
        "sale_date": _norm(str(row.get("sale_date") or "")[:10] or None),
        "opening_bid": _norm(SSM.opening_bid(row)),
        "purchase_path_type": _norm(row.get("purchase_path_type")),
        "purchase_url": _norm(row.get("purchase_url")),
        "evidence_url": _norm(row.get("evidence_url")),
        "purchase_path_observed_on": _norm(row.get("purchase_path_observed_on")),
        "source_id": _norm(row.get("source_id") or row.get("harvester_source")),
        "list_url": _norm(row.get("list_url")),
        "publication_status": _norm(row.get("publication_status")),
        "assessed": _norm(row.get("assessed")),
        "taxable_value": _norm(row.get("taxable_value")),
        "acreage": _norm(row.get("acreage")),
        "land_use": _norm(row.get("land_use")),
        "flood_zone": _norm(row.get("flood_zone")),
        "has_coordinates": "yes" if row.get("latitude") is not None else None,
        "has_imagery": "yes" if row.get("photo_url") else None,
        "legal_desc_hash": hashlib.sha256(str(legal).encode()).hexdigest()[:16] if legal else None,
        "result_date": _norm(row.get("result_date")),
        "result_amount": _norm(row.get("result_amount")),
    }


def _active(status) -> bool:
    return str(status or "active").lower() not in GONE


def diff(old: dict | None, new: dict) -> list[tuple[str, str, str | None, str | None]]:
    """[(kind, field, old, new)] - deterministic, ordered by field."""
    if old is None:
        return [("new_listing", "status", None, new.get("status"))]
    out = []
    if old.get("status") != new.get("status"):
        a, b = _active(old.get("status")), _active(new.get("status"))
        kind = "removed" if a and not b else "reactivated" if b and not a else "status_changed"
        out.append((kind, "status", old.get("status"), new.get("status")))
    for f in FIELD_KIND:
        if old.get(f) != new.get(f):
            out.append((FIELD_KIND[f], f, old.get(f), new.get(f)))
    for f in ("result_date", "result_amount"):
        if not old.get(f) and new.get(f):
            out.append(("result_published", f, None, new.get(f)))
    return out


def plan(rows: list[dict], stored: dict[str, dict], *, baseline_exists: bool) -> dict:
    """Pure: the events, snapshot writes and per-source counts for one run."""
    events, writes = [], {}
    counts: dict[str, Counter] = defaultdict(Counter)
    for r in rows:
        pid = str(r["id"])
        snap = snapshot(r)
        sid = snap["source_id"] or "unknown"
        c = counts[(sid, r.get("source"))]
        c["observed"] += 1
        old = stored.get(pid)
        if old is None:
            writes[pid] = snap
            if baseline_exists:
                c["added"] += 1
                events.append({"property_id": pid, "row": r, "kind": "new_listing", "field": "status", "old": None, "new": snap["status"]})
            continue
        changes = diff(old, snap)
        if not changes:
            continue
        writes[pid] = snap
        c["changed"] += 1
        for kind, field, a, b in changes:
            if kind == "removed":
                c["closed"] += 1
            if kind == "reactivated":
                c["reactivated"] += 1
            events.append({"property_id": pid, "row": r, "kind": kind, "field": field, "old": a, "new": b})
    return {"events": events, "writes": writes, "counts": counts}


def describe(event: dict) -> tuple[str, str]:
    """Customer-facing alert title and detail - the stated change, nothing more."""
    r = event["row"]
    place = f"{r.get('address') or r.get('parcel') or r.get('case_no') or 'Property'} ({r.get('county')}, {r.get('state')})"
    ledger = LEDGER_WORD.get(r.get("source"), "Property")
    kind, field = event["kind"], event["field"]
    label = FIELD_LABEL.get(field, field.replace("_", " "))
    if kind == "new_listing":
        return f"New {ledger} match: {place}", "Newly listed by the source and matching your saved search."
    if kind == "removed":
        return f"No longer listed: {place}", (f"{ledger} record is no longer on the source list (status {event['old']} -> {event['new']}). "
                                             "This is not a sale or a result - the source simply no longer lists it.")
    if kind == "reactivated":
        return f"Back on the list: {place}", f"{ledger} record is listed again by the source."
    if kind == "result_published":
        return f"Result published: {place}", f"The source published {label.lower()}: {event['new']}."
    return f"{label} changed: {place}", f"{label}: {event['old'] or 'not on file'} -> {event['new'] or 'not on file'}."


# --------------------------------------------------------------------------- I/O

class Api:
    def __init__(self, base: str, key: str, *, dry_run: bool = False):
        self.base, self.key, self.dry_run = base.rstrip("/"), key, dry_run

    def req(self, method: str, path: str, body=None, prefer: str | None = None):
        data = json.dumps(body).encode() if body is not None else None
        headers = {"apikey": self.key, "Authorization": f"Bearer {self.key}", "Content-Type": "application/json", "User-Agent": USER_AGENT}
        if prefer:
            headers["Prefer"] = prefer
        req = urllib.request.Request(f"{self.base}/rest/v1/{path}", data=data, method=method, headers=headers)
        with urllib.request.urlopen(req, timeout=90) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else None

    def has_table(self, table: str) -> bool:
        try:
            self.req("GET", f"{table}?select=*&limit=0")
            return True
        except urllib.error.HTTPError as e:
            if e.code in (404, 400):
                return False
            raise

    def paged(self, path: str) -> list[dict]:
        out, offset = [], 0
        while True:
            page = self.req("GET", f"{path}&limit={PAGE}&offset={offset}") or []
            out.extend(page)
            if not page:
                return out
            offset += len(page)


def _cache_name(state: str, source: str | None) -> str:
    return f"change_snapshots_{state}{'_' + source if source else ''}.json"


def load_cache(state: str, source: str | None = None) -> dict:
    p = CACHE_DIR / _cache_name(state, source)
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}
    except ValueError:
        return {}


def save_cache(state: str, snaps: dict, source: str | None = None) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    (CACHE_DIR / _cache_name(state, source)).write_text(json.dumps(snaps, sort_keys=True), encoding="utf-8")


def alerts_for(events: list[dict], *, watchers: dict[str, list[str]], searches: list[dict], prefs: dict[str, dict]) -> list[dict]:
    """user_alerts rows (without change_event_id) for the events of one run."""
    out = []
    for ev in events:
        title, detail = describe(ev)
        if ev["kind"] == "new_listing" or ev["kind"] == "reactivated":
            for s in searches:
                if not s.get("alerts_enabled", True) or s.get("state") != ev["row"].get("state"):
                    continue
                if prefs.get(s["user_id"], {}).get("saved_search_matches", True) is False:
                    continue
                if SSM.matches(s.get("criteria") or {}, ev["row"]):
                    out.append({"user_id": s["user_id"], "kind": "saved_search_new_match", "property_id": ev["property_id"],
                                "saved_search_id": s["id"], "title": title if ev["kind"] == "new_listing" else f"Back on the list: {title.split(': ', 1)[-1]}",
                                "detail": f"Matches your saved search \"{s.get('name')}\".", "_event": ev})
        if ev["kind"] == "new_listing":
            continue
        if ev["kind"] == "field_changed" and ev["field"] not in ALERT_FIELDS:
            continue
        for uid in watchers.get(ev["property_id"], []):
            if prefs.get(uid, {}).get("watch_changes", True) is False:
                continue
            out.append({"user_id": uid, "kind": ALERT_KIND[ev["kind"]], "property_id": ev["property_id"], "saved_search_id": None,
                        "title": title, "detail": detail, "_event": ev})
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--state", required=True)
    ap.add_argument("--source", choices=("auction", "laft", "certificate"), default=None)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--report", default=None)
    a = ap.parse_args(argv)
    state = a.state.upper()
    base, key = os.environ.get("SUPABASE_URL", ""), os.environ.get("SUPABASE_SERVICE_KEY", "")
    src = a.source
    report_path = Path(a.report or f"out/public/change-detection-{state.lower()}{'-' + src if src else ''}.json")
    if not base or not key:
        print("SUPABASE_URL / SUPABASE_SERVICE_KEY not set - nothing detected")
        return 0
    api = Api(base, key, dry_run=a.dry_run)
    run_id = os.environ.get("GITHUB_RUN_ID") or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    have_024 = api.has_table("property_change_events")
    src_q = f"&source=eq.{src}" if src else ""
    rows = api.paged(f"properties?select={urllib.parse.quote(SELECT, safe=',:>-_')}&state=eq.{state}{src_q}&order=id.asc")
    ids = {str(r["id"]) for r in rows}
    if have_024:
        stored = {s["property_id"]: s["snapshot"] for s in api.paged(f"property_change_snapshots?select=property_id,snapshot&state=eq.{state}&order=property_id.asc")
                  if s["property_id"] in ids or not src}
    else:
        stored = load_cache(state, src)
    baseline_exists = bool(stored)
    p = plan(rows, stored, baseline_exists=baseline_exists)
    kinds = Counter(e["kind"] for e in p["events"])
    report = {"state": state, "source": src or "all", "run_id": run_id, "storage": "migration 024 tables" if have_024 else "harvest cache (migration 024 not applied)",
              "baseline_run": not baseline_exists, "rows": len(rows), "snapshots_written": len(p["writes"]),
              "events": dict(kinds), "sources": {f"{k[0]} ({k[1]})": dict(v) for k, v in sorted(p["counts"].items(), key=lambda kv: str(kv[0]))},
              "alerts": 0, "dry_run": a.dry_run}
    if not a.dry_run:
        if have_024:
            ev_rows = [{"property_id": e["property_id"], "state": state, "county": e["row"].get("county"), "source": e["row"].get("source"),
                        "source_id": e["row"].get("source_id") or e["row"].get("harvester_source"), "kind": e["kind"], "field": e["field"],
                        "old_value": e["old"], "new_value": e["new"], "run_id": run_id} for e in p["events"]]
            ids = []
            for i in range(0, len(ev_rows), 500):
                ids += [x["id"] for x in (api.req("POST", "property_change_events", ev_rows[i:i + 500], prefer="return=representation") or [])]
            for e, eid in zip(p["events"], ids):
                e["id"] = eid
            snaps = [{"property_id": pid, "state": state, "snapshot": s, "taken_at": datetime.now(timezone.utc).isoformat()} for pid, s in p["writes"].items()]
            for i in range(0, len(snaps), 500):
                api.req("POST", "property_change_snapshots?on_conflict=property_id", snaps[i:i + 500], prefer="resolution=merge-duplicates,return=minimal")
            runs = [{"state": state, "source_id": k[0], "ledger": k[1], "run_id": run_id, "rows_observed": v["observed"], "rows_added": v["added"],
                     "rows_changed": v["changed"], "rows_closed": v["closed"], "rows_reactivated": v["reactivated"]} for k, v in p["counts"].items()]
            if runs:
                api.req("POST", "source_observation_runs", runs, prefer="return=minimal")
            if p["events"]:
                watchers: dict[str, list[str]] = defaultdict(list)
                for w in api.paged("bid_list?select=user_id,property_id&order=user_id.asc"):
                    watchers[str(w["property_id"])].append(w["user_id"])
                searches = api.paged(f"saved_searches?select=id,user_id,name,state,criteria,alerts_enabled&state=eq.{state}&order=id.asc")
                prefs = {x["user_id"]: x for x in api.paged("alert_preferences?select=user_id,watch_changes,saved_search_matches&order=user_id.asc")}
                alerts = alerts_for(p["events"], watchers=watchers, searches=searches, prefs=prefs)
                rows_out = [{**{k: v for k, v in al.items() if k != "_event"}, "change_event_id": al["_event"].get("id")} for al in alerts]
                for i in range(0, len(rows_out), 500):
                    api.req("POST", "user_alerts?on_conflict=user_id,change_event_id,saved_search_id", rows_out[i:i + 500],
                            prefer="resolution=ignore-duplicates,return=minimal")
                report["alerts"] = len(rows_out)
        else:
            merged = dict(stored)
            merged.update(p["writes"])
            save_cache(state, merged, src)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"change detection ({state}{' ' + src if src else ''}): {report['rows']} rows, storage {report['storage']}, baseline={report['baseline_run']}, "
          f"events {dict(kinds)}, alerts {report['alerts']}")
    for k, v in report["sources"].items():
        print(f"  {k}: observed {v.get('observed', 0)}, added {v.get('added', 0)}, changed {v.get('changed', 0)}, "
              f"closed {v.get('closed', 0)}, reactivated {v.get('reactivated', 0)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
