"""Texas AVAILABLE rows against the LGBS feed they were harvested from.

Every active Texas AVAILABLE row in production came from Linebarger Goggan
Blair & Sampson's public property-sales API (harvesters/texas_harvester.py,
`tx_lgbs`), but no run since read-stamping shipped has observed them: the
`texas` job is manual-only and also runs the TX RealAuction harvest and the
auction-ledger sync. This script reads ONLY the LGBS feed, through the same
ingestion gate the harvester uses, and touches ONLY the active Texas
AVAILABLE rows (state=TX, source=laft):

  --probe   value-free inventory: records walked, Texas records, how many of
            our rows the feed carries (exact county + account number), the
            feed's own status / sale-type categories for the matched records,
            and the fill count of every raw key among them. No write.
  --apply   for a row the feed still lists with a struck-off / available
            status (the harvester's own LGBS_STATUS_TO_LEDGER mapping):
              * last_seen_at = now (only when the walk was COMPLETE - a
                truncated walk never refreshes a row's last read);
              * field_provenance entries (source vendor_listing, rank 1) for
                the columns the sync writes from LGBS, ONLY where the stored
                value equals what the feed publishes today and the column has
                no entry yet - an attestation of where the value came from,
                never a new value;
              * a blank legal_desc / coordinate pair is filled from the feed's
                own fields, exactly as the existing sync would (fill-blank,
                field_provenance precedence enforced).
            A row the feed no longer lists, or lists with another status, is
            only COUNTED: absence is never a sale, a redemption or a close.

Governance: tx_lgbs passes the repository ingestion gate (registry
APPROVED, production-practice) but its reuse terms are under legal review
(docs/lgbs-rights-audit.md), so the unified source model classifies it
REVIEW_REQUIRED. Nothing here publishes a new kind of LGBS field; the
availability measurement reports these rows as observed on a
REVIEW_REQUIRED source, never as verified by an approved one.

Counts only are printed (public logs).

    python3 scripts/lgbs_available_refresh.py --probe
    python3 scripts/lgbs_available_refresh.py --apply
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO / "harvesters"))
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(HERE))

import field_provenance as FP  # noqa: E402

SOURCE_ID = "tx_lgbs"
USER_AGENT = "taxdeed-scraper lgbs-available-refresh (+https://github.com/rodzmodzllc-max/taxdeed-scraper)"
READ_COLUMNS = ("id,county,case_no,parcel,address,legal_desc,assessed,min_bid,latitude,longitude,"
                "field_provenance,last_seen_at,first_seen_at")
PAGE = 1000


# ------------------------------------------------------------ pure logic

def norm_account(v) -> str | None:
    s = str(v or "").strip().upper()
    return s or None


def feed_record(raw: dict, *, normalize_county, status_to_ledger: dict, to_float, compose_address) -> dict | None:
    """One raw LGBS record as the fields the sync derives from it, or None
    for a non-Texas record (the API's area=TX is not a strict filter)."""
    if raw.get("state") != "TX":
        return None
    county = normalize_county(raw.get("county"))
    account = norm_account(raw.get("account_nbr"))
    if not county or not account:
        return None
    coords = ((raw.get("geometry") or {}).get("coordinates")) or [None, None]
    lon, lat = (list(coords) + [None, None])[:2]
    return {
        "county": county, "account": account, "status": raw.get("status"),
        "ledger": status_to_ledger.get(raw.get("status")),
        "values": {
            "legal_desc": (raw.get("sale_notes") or "").strip() or None,
            "assessed": to_float(raw.get("value")),
            "min_bid": to_float(raw.get("minimum_bid")),
            "address": compose_address(raw),
            "parcel": raw.get("cause_nbr") or None,
            "latitude": to_float(lat), "longitude": to_float(lon),
        },
        "raw_keys": sorted(k for k, v in raw.items() if v not in (None, "", [], {})),
    }


# The column -> raw key the existing sync maps (scripts/sync-texas-to-supabase.py).
RAW_KEY = {"legal_desc": "sale_notes", "assessed": "value", "min_bid": "minimum_bid", "address": "composed address fields",
           "parcel": "cause_nbr", "latitude": "geometry.coordinates[1]", "longitude": "geometry.coordinates[0]"}


def same(column: str, stored, published) -> bool:
    if FP.is_blank(stored) or published is None:
        return False
    if column in ("assessed", "min_bid"):
        try:
            return abs(float(stored) - float(published)) < 0.005
        except (TypeError, ValueError):
            return False
    if column in ("latitude", "longitude"):
        try:
            return abs(float(stored) - float(published)) < 1e-6
        except (TypeError, ValueError):
            return False
    return " ".join(str(stored).split()).upper() == " ".join(str(published).split()).upper()


def index_feed(records: list[dict]) -> dict:
    """(county, account) -> records. Two records for one key is ambiguous."""
    idx: dict = defaultdict(list)
    for r in records:
        idx[(r["county"], r["account"])].append(r)
    return idx


def plan_row(row: dict, idx: dict, *, now: str, walk_complete: bool) -> tuple[str, dict]:
    """(outcome, PATCH body). Outcomes: NOT_IN_FEED | AMBIGUOUS | OTHER_STATUS | OBSERVED."""
    hits = idx.get((row.get("county"), norm_account(row.get("case_no"))), [])
    if not hits:
        return "NOT_IN_FEED", {}
    if len(hits) > 1:
        return "AMBIGUOUS", {}
    rec = hits[0]
    if rec["ledger"] != "laft":
        return "OTHER_STATUS", {}
    body: dict = {}
    prov_updates: dict = {}
    stored_prov = FP.load_provenance(row.get("field_provenance"))
    meta = {"source_id": SOURCE_ID, "dataset": "taxsales.lgbs.com property_sales API", "governance": "REVIEW_REQUIRED",
            "matched_on": "county + account number (case_no), exact", "recorded_at": now}
    # Fill-blank: only what the existing sync already writes from LGBS.
    fills = {}
    if FP.is_blank(row.get("legal_desc")) and rec["values"]["legal_desc"]:
        fills["legal_desc"] = rec["values"]["legal_desc"]
    if (row.get("latitude") is None or row.get("longitude") is None) and rec["values"]["latitude"] is not None \
            and rec["values"]["longitude"] is not None:
        fills["latitude"], fills["longitude"] = rec["values"]["latitude"], rec["values"]["longitude"]
    fills = FP.filter_by_provenance(row, fills, "vendor_listing")
    for column, value in fills.items():
        body[column] = value
        prov_updates[column] = FP.provenance_entry("vendor_listing", field=RAW_KEY[column], **meta)
    # Attestation: an un-provenanced stored value equal to the feed's value.
    for column, published in rec["values"].items():
        if column in fills or column in stored_prov:
            continue
        if same(column, row.get(column), published):
            prov_updates[column] = FP.provenance_entry("vendor_listing", field=RAW_KEY[column], attested="stored value equals the feed's value", **meta)
    if prov_updates:
        body["field_provenance"] = FP.merge_field_provenance(row.get("field_provenance"), prov_updates)
    if walk_complete:
        body["last_seen_at"] = now
    return "OBSERVED", body


# ------------------------------------------------------------ I/O

def http_json(url: str, *, headers: dict | None = None, method: str = "GET", body: bytes | None = None, timeout: int = 60):
    req = urllib.request.Request(url, data=body, method=method, headers={"User-Agent": USER_AGENT, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    return json.loads(raw) if raw else None


def fetch_rows(base: str, key: str) -> list[dict]:
    hdr = {"apikey": key, "Authorization": f"Bearer {key}"}
    rows, offset = [], 0
    while True:
        q = urllib.parse.urlencode({"select": READ_COLUMNS, "state": "eq.TX", "source": "eq.laft", "status": "eq.active",
                                    "order": "id.asc", "limit": PAGE, "offset": offset})
        page = http_json(f"{base}/rest/v1/properties?{q}", headers=hdr, timeout=120) or []
        rows += page
        if len(page) < PAGE:
            return rows
        offset += PAGE


def walk_feed() -> tuple[list[dict], dict]:
    """Every raw record of the LGBS feed, the harvester's own way (same URL,
    page size, retries, http->https upgrade on `next`)."""
    import texas_harvester as TH  # noqa: PLC0415
    from governance.gate import check_ingestion_gate  # noqa: PLC0415
    decision = check_ingestion_gate(SOURCE_ID)
    stats = {"gate_allowed": decision.allowed, "gate_reason": decision.reason, "pages": 0, "raw": 0, "complete": False}
    if not decision.allowed:
        return [], stats
    url = f"{TH.LGBS_API_URL}?{urllib.parse.urlencode({'area': 'TX', 'limit': str(TH.LGBS_PAGE_SIZE)})}"
    records: list[dict] = []
    while url:
        stats["pages"] += 1
        payload = None
        for attempt in range(1, TH.LGBS_PAGE_ATTEMPTS + 1):
            try:
                payload = http_json(url, timeout=30)
                break
            except Exception:  # noqa: BLE001 - counted, retried, then reported as an incomplete walk
                time.sleep(TH.LGBS_RETRY_BACKOFF_SECONDS * (2 ** (attempt - 1)))
        if payload is None:
            stats["truncated_at_page"] = stats["pages"]
            return records, stats
        for raw in payload.get("results", []):
            stats["raw"] += 1
            rec = feed_record(raw, normalize_county=TH._lgbs_normalize_county, status_to_ledger=TH.LGBS_STATUS_TO_LEDGER,
                              to_float=TH._lgbs_to_float, compose_address=TH._lgbs_compose_address)
            if rec:
                rec["_raw_status"] = raw.get("status")
                rec["_raw_sale_type"] = raw.get("sale_type")
                records.append(rec)
        url = payload.get("next")
        if url and url.startswith("http://"):
            url = "https://" + url[len("http://"):]
        time.sleep(0.3)
    stats["complete"] = True
    return records, stats


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--probe", action="store_true")
    mode.add_argument("--apply", action="store_true")
    ap.add_argument("--out", default=str(REPO / "out" / "public" / "lgbs-available-refresh.json"))
    a = ap.parse_args(argv)
    base, key = os.environ.get("SUPABASE_URL", "").rstrip("/"), os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not base or not key:
        print("skip: SUPABASE_URL / SUPABASE_SERVICE_KEY not set")
        return 0
    rows = fetch_rows(base, key)
    records, stats = walk_feed()
    print(f"LGBS gate: allowed={stats['gate_allowed']} ({stats['gate_reason']}); pages {stats['pages']}, raw records {stats['raw']}, "
          f"Texas records {len(records)}, walk {'COMPLETE' if stats['complete'] else 'INCOMPLETE'}")
    idx = index_feed(records)
    now = FP.now_iso()
    outcomes: Counter = Counter()
    by_county: dict = defaultdict(Counter)
    status_cats: Counter = Counter()
    key_fill: Counter = Counter()
    planned = []
    for r in rows:
        oc, body = plan_row(r, idx, now=now, walk_complete=stats["complete"])
        outcomes[oc] += 1
        by_county[r.get("county")][oc] += 1
        hits = idx.get((r.get("county"), norm_account(r.get("case_no"))), [])
        if len(hits) == 1:
            status_cats[(hits[0].get("_raw_status"), hits[0].get("_raw_sale_type"))] += 1
            key_fill.update(hits[0]["raw_keys"])
        if body:
            planned.append((r["id"], body))
    fields = Counter(k for _, b in planned for k in b if k not in ("field_provenance", "last_seen_at"))
    prov_cols = Counter(k for (rid, b) in planned for k in (b.get("field_provenance") or {}))
    print(f"TX AVAILABLE rows {len(rows)}; outcomes {dict(outcomes)}")
    for c, oc in sorted(by_county.items()):
        print(f"  {c}: {dict(oc)}")
    print(f"feed status / sale_type among matched rows: {[(list(k), v) for k, v in status_cats.most_common()]}")
    print(f"raw keys published among matched rows (key: rows with a value): {dict(sorted(key_fill.items()))}")
    print(f"planned: rows {len(planned)}, last_seen stamps {sum(1 for _, b in planned if 'last_seen_at' in b)}, "
          f"fills {dict(fields)}, provenance columns {dict(prov_cols)}")
    written = errors = 0
    if a.apply:
        hdr = {"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json", "Prefer": "return=minimal"}
        for rid, body in planned:
            try:
                http_json(f"{base}/rest/v1/properties?id=eq.{rid}&state=eq.TX&source=eq.laft", headers=hdr, method="PATCH",
                          body=json.dumps(body).encode(), timeout=60)
                written += 1
            except Exception as exc:  # noqa: BLE001 - counted; the row keeps its stored values
                errors += 1
                print(f"  write failed: {type(exc).__name__}")
        print(f"apply: written {written}, errors {errors}")
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"mode": "apply" if a.apply else "probe", "feed": stats, "texas_records": len(records),
                               "rows": len(rows), "outcomes": dict(outcomes), "by_county": {k: dict(v) for k, v in by_county.items()},
                               "raw_key_fill": dict(key_fill), "fills": dict(fields), "provenance_columns": dict(prov_cols),
                               "written": written, "errors": errors}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
