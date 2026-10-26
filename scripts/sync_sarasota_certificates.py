#!/usr/bin/env python3
"""Sync the Sarasota Tax Collector's county-held certificates (2026-10-26).

Reads out/harvest_certificates_sarasota.json + out/harvest_sarasota_certificates_status.json
(scripts/harvest_sarasota_certificates.py) and writes `properties` rows with
source='certificate', source_id = harvester_source = 'fl_sarasota_tc_certificates',
source_authority 'GOVERNMENT_DIRECT' - one row per certificate (case_no =
'<tax year>-<certificate number>'), never LienHub's rows (their case_no is the
account; scripts/sync-certificates-to-supabase.ps1's close-out reads only
LienHub's own source_id).

Rules (the same ones every sync here follows):

  * store permission first (data/source_permissions.csv, owner's interim
    decision of 2026-10-26); denied -> exit 3, nothing read or written;
  * nothing is written unless the read is COMPLETE or INCOMPLETE (a FAILED read
    writes nothing; rows read in an INCOMPLETE run are written, nothing closed);
  * every row passes the LIENS_CERTIFICATES record contract
    (harvesters/ledgers/records.problems) before any write;
  * a blank or placeholder never replaces a stored value, nor does this source
    replace a higher-ranked one (scripts/sync_value_guard.py, written as
    `county_list` - a county government's own list);
  * last_seen_at = this run; first_seen_at = the stored value, else this run
    (properties_seen_order_check rejects an insert whose default lands later);
  * field_provenance is merged, never replaced (other sources' entries stay);
  * close-out only after a COMPLETE read, only this source's own active rows
    absent from it, to 'notfound' (the certificate reconciliation status) -
    absence is never a redemption or a sale.

Prints counts only.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
for p in (str(HERE), str(REPO)):
    if p not in sys.path:
        sys.path.insert(0, p)

import field_provenance as FP  # noqa: E402
import laft_status as LS  # noqa: E402
import rest_pages as RP  # noqa: E402
import sync_value_guard as G  # noqa: E402

SOURCE_ID = "fl_sarasota_tc_certificates"
DATASET = "county_held_certificates"
COUNTY = "Sarasota"
HARVEST = REPO / "out" / "harvest_certificates_sarasota.json"
STATUS = REPO / "out" / "harvest_sarasota_certificates_status.json"
USER_AGENT = "taxdeed-scraper sync-sarasota-certificates (+https://github.com/rodzmodzllc-max/taxdeed-scraper)"
PROVENANCE_SOURCE = "county_list"
BATCH = 200
WRITABLE = ("COMPLETE", "INCOMPLETE")
PROVENANCED = ("certificate_no", "tax_year", "bid", "assessed", "interest_rate", "parcel")


def build_rows(records: list[dict], stored: dict, now: str) -> list[dict]:
    """Harvest records -> payload rows (one key set), before the guard."""
    out = []
    for r in records:
        prev = stored.get(r["case_no"]) or {}
        out.append({
            "state": "FL", "source": "certificate", "county": COUNTY, "case_no": r["case_no"],
            "certificate_no": r.get("certificate_no"), "tax_year": r.get("tax_year"),
            "issued_date": None, "expiration_date": None,
            "bid": r.get("bid") if r.get("bid") is not None else 0,
            # address is NOT NULL with no default; the list publishes none, so the
            # same placeholder the LienHub sync uses (sync_value_guard keeps a real
            # stored address over it).
            "address": f"Account {r.get('parcel')}",
            "owner_name": None, "parcel": r.get("parcel"), "assessed": r.get("assessed"),
            "interest_rate": r.get("interest_rate"),
            "url_auction": r.get("url_auction"), "url_auction_kind": "county" if r.get("url_auction") else None,
            "status": "active", "source_id": SOURCE_ID, "harvester_source": SOURCE_ID,
            "source_authority": "GOVERNMENT_DIRECT",
            "last_seen_at": now, "first_seen_at": prev.get("first_seen_at") or now,
            "field_provenance": FP.load_provenance(prev.get("field_provenance")),
        })
    return out


def attach_provenance(guarded: list[dict], built: list[dict], stored: dict, now: str) -> list[dict]:
    """After the guard: a `county_list` entry for each column this run actually
    wrote (the guard did not keep the stored value) - never over another
    source's entry for that column; every other entry is kept verbatim."""
    out = []
    for g, b in zip(guarded, built):
        prev = FP.load_provenance((stored.get(b["case_no"]) or {}).get("field_provenance"))
        entries = {}
        for c in PROVENANCED:
            if FP.is_blank(b.get(c)) or g.get(c) != b.get(c):
                continue
            existing = prev.get(c)
            if isinstance(existing, dict) and existing.get("source") not in (None, PROVENANCE_SOURCE):
                continue
            entries[c] = FP.provenance_entry(PROVENANCE_SOURCE, source_id=SOURCE_ID, recorded_at=now)
        out.append({**g, "field_provenance": FP.merge_field_provenance(prev, entries)})
    return out


def contract_refusals(rows: list[dict]) -> list[int]:
    from harvesters.ledgers import Ledger, ledger_for_row
    from harvesters.ledgers import records as LR
    return [i for i, r in enumerate(rows) if ledger_for_row(r) is not Ledger.LIENS_CERTIFICATES or LR.problems(r)]


def close_plan(stored_rows: list[dict], harvested: set[str]) -> list:
    return [s["id"] for s in stored_rows
            if s.get("status") == "active" and s.get("source_id") == SOURCE_ID and s.get("case_no") not in harvested]


def _headers(key: str) -> dict:
    return {"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json", "User-Agent": USER_AGENT}


def _send(url: str, method: str, body, headers: dict) -> None:
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method=method, headers=headers)
    with urllib.request.urlopen(req, timeout=120):
        pass


def main(argv=None) -> int:
    # Source "fl_sarasota_tc_certificates" (named here for the interim-permission call-site inventory).
    d = LS.permission(SOURCE_ID, "store", state="FL", county=COUNTY, dataset=DATASET)
    if not d.allowed:
        print(f"::error title={SOURCE_ID}::store denied [{d.reason_code}] - nothing read or written")
        return LS.PERMISSION_DENIED_EXIT
    try:
        entries = json.loads(STATUS.read_text(encoding="utf-8"))
        records = json.loads(HARVEST.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        print(f"{SOURCE_ID}: no readable harvest / status file - nothing written")
        return 0
    entry = next((e for e in entries if e.get("source_id") == SOURCE_ID and e.get("county") == COUNTY), {})
    status = str(entry.get("status") or "")
    if status not in WRITABLE:
        print(f"{SOURCE_ID}: read {status or 'missing'} - nothing written, nothing closed")
        return 0
    base, key = os.environ.get("SUPABASE_URL", ""), os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not base or not key:
        print("skip: SUPABASE_URL / SUPABASE_SERVICE_KEY not set")
        return 0
    headers = _headers(key)
    select = ",".join(["id", "county", "case_no", "status", "source_id", "first_seen_at", "field_provenance",
                       *G.GUARDED["certificate"]])
    stored_rows = RP.read_all(base, "properties", headers, {"select": select, "state": "eq.FL", "source": "eq.certificate",
                                                           "county": f"eq.{COUNTY}"})
    stored = {s["case_no"]: s for s in stored_rows}
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    rows = build_rows(records, stored, now)
    refused = set(contract_refusals(rows))
    rows = [r for i, r in enumerate(rows) if i not in refused]
    kept = attach_provenance(G.guard_rows("certificate", rows, stored_rows, sync_source=PROVENANCE_SOURCE), rows, stored, now)
    endpoint = f"{base.rstrip('/')}/rest/v1/properties?on_conflict=state,source,county,case_no"
    up = {**headers, "Prefer": "resolution=merge-duplicates,return=minimal"}
    for i in range(0, len(kept), BATCH):
        _send(endpoint, "POST", kept[i:i + BATCH], up)
    closed = 0
    if status == "COMPLETE":
        ids = close_plan(stored_rows, {r["case_no"] for r in kept})
        patch = {**headers, "Prefer": "return=minimal"}
        for i in range(0, len(ids), 50):
            chunk = ids[i:i + 50]
            _send(f"{base.rstrip('/')}/rest/v1/properties?id=in.({','.join(urllib.parse.quote(str(x)) for x in chunk)})",
                  "PATCH", {"status": "notfound"}, patch)
            closed += len(chunk)
    new = sum(1 for r in kept if r["case_no"] not in stored)
    print(f"{SOURCE_ID}: read {status}; {len(kept)} certificate row(s) upserted ({new} new), {len(refused)} refused by the "
          f"ledger contract, {closed} closed to notfound")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
