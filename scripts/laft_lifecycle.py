#!/usr/bin/env python3
"""LAFT / OTC inventory lifecycle for one state: last_seen_at, gated
close-out, reactivation, and (once migration 017 is applied) row-level
source provenance and honest purchase-amount semantics.

THE STATE IS A PARAMETER (`--state`, default FL - the only state whose
harvesters write this ledger today). It must be registered in
harvesters/governance/states.py; an unregistered code stops the run before
any query (fail closed). Every query and patch is scoped to that state and
source='laft', and the inventory type stamped on observed rows comes from
the state's StateConfig (`lifecycle_inventory_type`), never from a literal
in this file. Nothing about the gates below is per-state.

Runs in the `laft` job right after scripts/sync-laft-to-supabase.ps1's
upsert. The upsert already made every harvested row exist and `active`
(see that script's `status = "active"` line); this script does the part
an upsert cannot: say which rows were NOT seen, and only when that absence
means something.

DECISION RULES (scripts/laft_status.py is the vocabulary):

  1. A county's status for this run comes from out/harvest_laft_status.json,
     downgraded to STALE when older than --max-age-hours and to NOT_RUN when
     the county source registry expects a harvester that left no entry.
  2. OBSERVED rows (a harvested row whose county is COMPLETE or INCOMPLETE -
     i.e. a harvester really read it this run) get last_seen_at = now and,
     if they had been closed, status = 'active' again (migration 006's
     trigger clears gone_since when status leaves the gone set). A FAILED /
     STALE / NOT_RUN county has no observations by construction.
  3. CLOSE-OUT: only for a county whose status is COMPLETE or EMPTY (an
     authoritative whole-list observation). Every open row of that county
     that is not in this run's observed keys leaves the county's published
     list -> status = 'closed' (+ delisted_at). INCOMPLETE, FAILED, STALE,
     NOT_RUN and a missing or unreadable status file close NOTHING -
     fail closed, exactly like sync-harvest-to-supabase.ps1's deeds gate.
  4. Nothing here infers sold / redeemed / escheated. 'closed' means "no
     longer on the county's Lands Available list", and that is all.

MIGRATION 017 AWARENESS: the lifecycle columns (last_seen_at, delisted_at,
inventory_type, source_authority, source_id, list_url, document_url,
purchase_amount, purchase_amount_kind, source document hash/ETag/
Last-Modified, otc_provenance) do not exist until
scripts/migrations/017_otc_inventory_provenance_lifecycle.sql is applied
by hand. This script probes for them once and, when absent, limits itself
to status reactivation and close-out (both on columns that exist today),
saying so in the log. It never applies a migration.

SOURCE FIELDS (2026-09-29, enrichment phase): after the provenance step,
scripts/laft_source_fields.py carries the list-published columns the sync
drops (legal_desc, owner_name, assessed, certificate_no, homestead, and -
once migration 019 exists - escheatment_date / available_date) onto the
same OBSERVED rows, fill-blank only, with field_provenance. That step
needs none of the 017 columns and runs whether or not 017 is applied.

Standard library only (like scripts/source_health.py). Every Supabase call
sends an explicit non-browser User-Agent - see the sync script's comment
on sb_secret keys.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(1, str(Path(__file__).resolve().parent.parent))  # harvesters.* (repo root)
from laft_status import (DB_AMOUNT_KINDS, CLOSEOUT_ELIGIBLE, load_status,  # noqa: E402
                         statuses_by_county)
import laft_source_fields as SF  # noqa: E402
from harvesters.governance import states  # noqa: E402
from harvesters.governance.county_source_registry import DB_SUPPORTED_INVENTORY_TYPES, PurchaseUrlKind  # noqa: E402

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
DEFAULT_STATUS = REPO / "out/harvest_laft_status.json"
DEFAULT_REGISTRY = REPO / "data/county_source_registry.csv"
DEFAULT_HARVEST_FILES = [REPO / "out" / n for n in (
    "harvest_laft.json", "harvest_laft_html.json", "harvest_laft_realtdm.json", "harvest_laft_pioneer.json",
    "harvest_laft_orange.json", "harvest_laft_stlucie.json", "harvest_laft_osceola.json",
    "harvest_laft_hillsborough.json", "harvest_laft_leon.json",
)]

USER_AGENT = "taxdeed-scraper/1.0 (+https://github.com/rodzmodzllc-max/taxdeed-scraper; GitHub Actions)"
# The only state whose harvesters feed this script today. Not a module-wide
# assumption any more: every function that touches the database takes the
# state explicitly (see main()).
DEFAULT_STATE = "FL"
SOURCE = "laft"
# Statuses that mean "gone" (app.js GONE_STATUSES + migration 006's trigger list).
GONE_STATUSES = frozenset({"closed", "dropped", "sold", "notfound"})
OBSERVED_STATUSES = frozenset({"COMPLETE", "INCOMPLETE"})
BATCH = 40
# Columns that only exist once migration 017 is applied.
MIGRATION_017_COLUMNS = ("last_seen_at", "delisted_at", "inventory_type", "source_authority", "source_id",
                         "list_url", "document_url", "purchase_amount", "purchase_amount_kind",
                         "source_document_sha256", "source_etag", "source_last_modified", "otc_provenance",
                         "list_as_of", "source_published_at")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Pure decision layer (tested directly, no network)
# ---------------------------------------------------------------------------

def identity_key(row: dict) -> tuple[str, str] | None:
    """Exactly sync-laft-to-supabase.ps1's identity: county + (case_no or
    parcel). A row with neither was never upserted and is not an observation."""
    county = str(row.get("county") or "").strip()
    case_no = str(row.get("case_no") or "").strip() or str(row.get("parcel") or "").strip()
    if not county or not case_no:
        return None
    return county, case_no


def load_harvest_rows(paths: list[Path]) -> list[dict]:
    rows: list[dict] = []
    for p in paths:
        if not p.is_file():
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except ValueError:
            print(f"::warning title=laft_lifecycle::{p.name} is not valid JSON - its rows are not treated as observations")
            continue
        if isinstance(data, list):
            rows.extend(r for r in data if isinstance(r, dict))
    return rows


def observed_by_county(rows: list[dict]) -> dict[str, dict[str, dict]]:
    """{county: {case_no: row}} - last row wins per key, like the sync's dedupe."""
    out: dict[str, dict[str, dict]] = {}
    for r in rows:
        key = identity_key(r)
        if not key:
            continue
        out.setdefault(key[0], {})[key[1]] = r
    return out


# Purchase-path kinds (migration 017 / county_source_registry.PurchaseUrlKind).
# PROPERTY kinds are links a buyer uses for THIS parcel; INSTRUCTION kinds
# are the county's process page. Both are stored in purchase_url +
# purchase_url_kind; the kind is what keeps them apart downstream (the app
# never presents an instructions page as a property link).
PURCHASE_URL_KINDS = frozenset(k.value for k in PurchaseUrlKind)
PROPERTY_PURCHASE_KINDS = frozenset({"online_purchase", "offer_form", "bid_form"})


def load_registry_purchase_paths(registry_path: Path, state: str = DEFAULT_STATE) -> dict[tuple[str, str], tuple[str, str]]:
    """(source_id, county) -> (purchase_url, purchase_url_kind) for the
    state's PRODUCTION_VERIFIED registry rows that carry one. A source-
    level path (an application / instructions page verified for that
    county's source) - never a per-property link, which only a harvester
    row can supply. Blank in the committed registry today: this returns {}
    until a county's path is verified and added there."""
    import csv
    if not registry_path.is_file():
        return {}
    out: dict[tuple[str, str], tuple[str, str]] = {}
    with open(registry_path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if r.get("state") != state or r.get("verification_status") != "PRODUCTION_VERIFIED":
                continue
            url, kind = (r.get("purchase_url") or "").strip(), (r.get("purchase_url_kind") or "").strip()
            if url and kind:
                out[(r.get("source_id") or "", r.get("county") or "")] = (url, kind)
    return out


def load_registry_purchase_modes(registry_path: Path, state: str = DEFAULT_STATE) -> dict[tuple[str, str], tuple[str, str]]:
    """(source_id, county) -> (purchase_path_mode, purchase_path_evidence)
    for the state's production registry rows that state a NON-URL mode
    (in_person_only / phone_mail / none). Carried into otc_provenance so
    the customer sees "in-person process published by the source" rather
    than a bare "no link"; never a URL, never a guess (unknown = absent)."""
    import csv
    if not registry_path.is_file():
        return {}
    out: dict[tuple[str, str], tuple[str, str]] = {}
    with open(registry_path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if r.get("state") != state or r.get("verification_status") != "PRODUCTION_VERIFIED":
                continue
            mode, evidence = (r.get("purchase_path_mode") or "").strip(), (r.get("purchase_path_evidence") or "").strip()
            if mode in ("in_person_only", "phone_mail", "none") and evidence:
                out[(r.get("source_id") or "", r.get("county") or "")] = (mode, evidence)
    return out


def purchase_path_of(row: dict, *, list_url: str | None, document_url: str | None, source_id: str | None,
                     county: str | None, registry_paths: dict | None) -> tuple[str | None, str | None, str]:
    """(purchase_url, purchase_url_kind, basis) for one observed row.

    1. The harvester row's own purchase_url + purchase_url_kind - a link the
       SOURCE published for this exact property (kind in PurchaseUrlKind).
    2. Else the registry's source-level path for (source_id, county).
    3. Else (None, None) - nothing is derived from a list page, a document
       URL or a county homepage; the row keeps whatever it already holds.
    A URL is accepted only if it is https and differs from the list and
    document URLs (a list page is never a purchase URL - 017's rule)."""
    def ok(url, kind):
        return (isinstance(url, str) and url.startswith("https://") and kind in PURCHASE_URL_KINDS
                and url != list_url and url != document_url)
    url, kind = row.get("purchase_url"), row.get("purchase_url_kind")
    if ok(url, kind):
        level = "property-level" if kind in PROPERTY_PURCHASE_KINDS else "source-level"
        return url, kind, f"{level} {kind} link published by the source for this property"
    if registry_paths and source_id is not None and county is not None:
        found = registry_paths.get((source_id, county))
        if found and ok(*found):
            url, kind = found
            level = "property-level" if kind in PROPERTY_PURCHASE_KINDS else "source-level"
            return url, kind, f"{level} {kind} page for this county's source (data/county_source_registry.csv)"
    return None, None, "no purchase path published by the source or verified in the registry - none invented"


def load_expected_units(registry_path: Path, state: str = DEFAULT_STATE) -> list[tuple[str, str]]:
    """(source_id, county) pairs the registry expects one of `state`'s
    harvesters to cover this run. Read with csv directly - scripts/ is not
    a package. Another state's rows never enter this state's run."""
    import csv
    if not registry_path.is_file():
        return []
    # Only the AVAILABLE ledger's units (data/county_source_registry.csv
    # `ledgers`): this lifecycle reads harvest_laft_status.json, and an
    # AUCTIONS or LIENS_CERTIFICATES unit for the same county name must never
    # appear here as NOT_RUN and block the county. A registry without the
    # column (an older fixture) is taken whole.
    with open(registry_path, newline="", encoding="utf-8") as fh:
        return sorted({(r["source_id"], r["county"]) for r in csv.DictReader(fh)
                       if r.get("state") == state and r.get("verification_status") == "PRODUCTION_VERIFIED"
                       and (not (r.get("ledgers") or "").strip() or "AVAILABLE" in (r.get("ledgers") or "").split("|"))})


def county_gates(status_entries: list[dict], expected: list[tuple[str, str]], *, now: float | None = None,
                 max_age_hours: float = 36.0, state: str | None = None) -> dict[str, dict]:
    """{county: {"status", "observed_ok", "closeout_ok", "entry"}}. With
    `state`, an entry that names another state is dropped: county NAMES
    repeat across states (Alabama and Florida both have an Escambia, a
    Jackson, a Franklin ...), so another state's status entry must never
    gate this state's rows. Every harvester's recorder writes its state
    (CountyStatus.state, FL by default); an entry with no state at all is
    kept, as before."""
    if state is not None:
        status_entries = [e for e in status_entries if not e.get("state") or str(e["state"]) == state]
    by_county = statuses_by_county(status_entries, expected=expected, now=now, max_age_hours=max_age_hours)
    gates: dict[str, dict] = {}
    for county, info in by_county.items():
        status = info["status"]
        gates[county] = {
            "status": status,
            "observed_ok": status in OBSERVED_STATUSES,
            "closeout_ok": status in CLOSEOUT_ELIGIBLE,
            "harvester": info.get("harvester"),
            "entry": info.get("entry"),
        }
    return gates


@dataclass
class Plan:
    observe: list[tuple[str, str]] = field(default_factory=list)        # (county, case_no) seen this run
    reactivate: list[tuple[str, str]] = field(default_factory=list)     # subset of observe whose DB status is gone
    close: list[dict] = field(default_factory=list)                     # DB rows {id, county, case_no}
    skipped_counties: dict[str, str] = field(default_factory=dict)      # county -> why nothing may be closed
    ignored_rows: int = 0                                               # harvested rows from non-observed counties


def plan_lifecycle(gates: dict[str, dict], observed: dict[str, dict[str, dict]], db_rows: list[dict]) -> Plan:
    """The whole decision, as data. `db_rows` are the state's LAFT rows
    with at least id/county/case_no/status."""
    plan = Plan()
    db_by_key = {(str(r.get("county")), str(r.get("case_no"))): r for r in db_rows}
    for county, keys in observed.items():
        gate = gates.get(county)
        if not gate or not gate["observed_ok"]:
            # A harvester wrote rows for a county it did not report as
            # COMPLETE/INCOMPLETE (or the status file is missing). Not an
            # observation this script will vouch for.
            plan.ignored_rows += len(keys)
            continue
        for case_no in keys:
            plan.observe.append((county, case_no))
            existing = db_by_key.get((county, case_no))
            if existing is not None and str(existing.get("status") or "").lower() in GONE_STATUSES:
                plan.reactivate.append((county, case_no))
    observed_keys = set(plan.observe)
    for county, gate in gates.items():
        if not gate["closeout_ok"]:
            plan.skipped_counties[county] = gate["status"]
            continue
        for r in db_rows:
            if str(r.get("county")) != county:
                continue
            if str(r.get("status") or "active").lower() in GONE_STATUSES:
                continue
            if (county, str(r.get("case_no"))) in observed_keys:
                continue
            plan.close.append({"id": r.get("id"), "county": county, "case_no": str(r.get("case_no"))})
    plan.observe.sort()
    plan.reactivate.sort()
    plan.close.sort(key=lambda r: (r["county"], r["case_no"]))
    return plan


_NUM_RE = re.compile(r"^\d+(\.\d+)?$")


def amount_of(row: dict, *, storable_kinds=DB_AMOUNT_KINDS) -> tuple[float | None, str]:
    """(purchase_amount, purchase_amount_kind) from a harvested row. Same
    numeric cleanup as the sync's ToNum, but a missing/unparseable amount is
    NULL + NOT_PUBLISHED - never 0. A harvester that says WHY there is no
    figure (bid_kind QUOTED_ON_APPLICATION - the Alabama adapter) keeps that
    kind only once the database can store it (migration 020); until then
    it is NOT_PUBLISHED, the storable truth. No FL harvester emits it."""
    raw = row.get("bid")
    if raw is None or str(raw).strip() == "":
        kind = str(row.get("bid_kind") or "")
        if kind == "QUOTED_ON_APPLICATION" and kind in storable_kinds:
            return None, kind
        return None, "NOT_PUBLISHED"
    cleaned = re.sub(r"[^0-9.]", "", str(raw))
    if not _NUM_RE.match(cleaned):
        return None, "NOT_PUBLISHED"
    value = float(cleaned)
    kind = str(row.get("bid_kind") or "PUBLISHED_AMOUNT_KIND_UNSPECIFIED")
    # Only a kind migration 017 can store, and never an amount-less kind
    # (NOT_PUBLISHED / QUOTED_ON_APPLICATION) next to a real figure.
    if kind not in DB_AMOUNT_KINDS or kind == "NOT_PUBLISHED":
        kind = "PUBLISHED_AMOUNT_KIND_UNSPECIFIED"
    return value, kind


def lifecycle_inventory(state: str) -> tuple[str | None, str | None]:
    """(inventory_type, basis) the lifecycle stamps on `state`'s observed
    rows, from the state's registration. (None, None) = this state's
    lifecycle asserts no inventory type (the column is left alone)."""
    cfg = states.get_state(state)
    if cfg is None:
        raise ValueError(f"state {state!r} is not registered (harvesters/governance/states.py)")
    if not states.is_activated(state):
        # Registered is not activated: a state whose sources have not been
        # verified and authorised (Alabama today) never reaches the database,
        # not even as a filter.
        raise ValueError(f"state {state!r} is registered but not activated for production - blockers: "
                         f"{', '.join(states.activation_blockers(state))}")
    if cfg.lifecycle_inventory_type is not None and cfg.lifecycle_inventory_type not in DB_SUPPORTED_INVENTORY_TYPES:
        # public.properties' check constraint (migration 017) would reject
        # the PATCH; refuse up front instead of failing per batch.
        raise ValueError(f"{state}: lifecycle inventory type {cfg.lifecycle_inventory_type!r} is not storable until a migration widens the constraint")
    return cfg.lifecycle_inventory_type, cfg.lifecycle_inventory_basis


def provenance_payload(row: dict, gate: dict, retrieved_at: str, *, state: str = DEFAULT_STATE,
                       registry_paths: dict | None = None, registry_modes: dict | None = None) -> dict:
    """The migration-017 columns for one observed row. Every value comes
    from the harvester's own status entry or the row it read; nothing is
    derived from the county name or guessed. The inventory type is the
    state's registered lifecycle type (FL: the statutory fixed-price list).
    purchase_url / purchase_url_kind are set only when purchase_path_of()
    finds one; otherwise the keys are absent so an existing value is never
    overwritten with NULL."""
    entry = gate.get("entry") or {}
    inventory_type, inventory_basis = lifecycle_inventory(state)
    amount, kind = amount_of(row)
    list_url = entry.get("source_url") or row.get("url_auction") or None
    document_url = entry.get("document_url") or None
    if document_url == list_url:
        document_url = document_url  # a PDF list is both the list and the document
    list_as_of = entry.get("list_as_of") or None
    published_at = published_at_from_last_modified(entry.get("document_last_modified"))
    source_id = entry.get("source_id") or gate.get("harvester")
    purchase_url, purchase_kind, purchase_basis = purchase_path_of(
        row, list_url=list_url, document_url=document_url, source_id=source_id, county=row.get("county"),
        registry_paths=registry_paths)
    # The source-level purchase-path MODE (scripts/laft_purchase_paths.PURCHASE_PATH_MODES):
    # derived from the URL kind when there is a URL; a registry-stated
    # non-URL mode (in-person / phone-mail / none, with the source's own
    # wording) when there is not; "unknown" otherwise - never inferred.
    if purchase_url is not None:
        purchase_mode = {"online_purchase": "online_property", "offer_form": "online_property", "bid_form": "online_property",
                         "purchase_instructions": "online_instructions", "application_form": "application"}.get(purchase_kind, "online_instructions")
    else:
        stated = (registry_modes or {}).get((source_id or "", row.get("county") or ""))
        if stated:
            purchase_mode, evidence = stated
            purchase_basis = (f"{purchase_mode.replace('_', ' ')} process published by the source: {evidence} "
                              f"(data/county_source_registry.csv); no online path")
        else:
            purchase_mode = "unknown"
    payload = {
        "last_seen_at": retrieved_at,
        # Currentness, from the source's own statements only: list_as_of is the
        # date the harvester read off the document/filename; source_published_at
        # is the server's Last-Modified for the document. Retrieval time is
        # never written into either (migration 017's rule).
        "list_as_of": list_as_of,
        "source_published_at": published_at,
        "inventory_type": inventory_type,
        "source_authority": entry.get("source_class"),
        "source_id": entry.get("source_id") or gate.get("harvester"),
        "list_url": list_url,
        "document_url": document_url,
        "purchase_amount": amount,
        "purchase_amount_kind": kind,
        "source_document_sha256": entry.get("document_sha256"),
        "source_etag": entry.get("document_etag"),
        "source_last_modified": entry.get("document_last_modified"),
        "otc_provenance": {
            "harvester": gate.get("harvester"),
            "source_id": entry.get("source_id") or gate.get("harvester"),
            "retrieved_at": entry.get("checked_at") or retrieved_at,
            "list_url": list_url,
            "document_url": document_url,
            "inventory_type": inventory_basis,
            "purchase_amount": ("not published by the source" if amount is None else f"source column/field: {kind}"),
            "list_as_of": ("stated by the list document/filename" if list_as_of else "not stated by the source"),
            "source_published_at": ("HTTP Last-Modified of the source document" if published_at else "no Last-Modified from the source"),
            "purchase_url": purchase_basis,
            "purchase_path_mode": purchase_mode,
            "status_terminology": "active = on the county list this run; closed = absent from a COMPLETE/EMPTY harvest",
        },
    }
    if purchase_url is not None:
        payload["purchase_url"] = purchase_url
        payload["purchase_url_kind"] = purchase_kind
    if inventory_type is None:
        # This state's lifecycle does not classify inventory: leave the
        # column untouched rather than writing NULL over a harvester's value.
        del payload["inventory_type"]
        del payload["otc_provenance"]["inventory_type"]
    return payload


def published_at_from_last_modified(value) -> str | None:
    """RFC 1123 Last-Modified -> ISO 8601 UTC, or None. Deterministic; a
    value that does not parse is dropped, never approximated."""
    if not value or not str(value).strip():
        return None
    try:
        dt = parsedate_to_datetime(str(value).strip())
    except (TypeError, ValueError, IndexError):
        return None
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def group_provenance(rows: list[tuple[str, dict]], gate: dict, retrieved_at: str, *, state: str = DEFAULT_STATE,
                     registry_paths: dict | None = None, registry_modes: dict | None = None) -> list[tuple[dict, list[str]]]:
    """[(payload, [case_no...])] - identical payloads share one PATCH."""
    groups: dict[str, tuple[dict, list[str]]] = {}
    for case_no, row in rows:
        payload = provenance_payload(row, gate, retrieved_at, state=state, registry_paths=registry_paths, registry_modes=registry_modes)
        key = json.dumps(payload, sort_keys=True, default=str)
        groups.setdefault(key, (payload, []))[1].append(case_no)
    return list(groups.values())


# ---------------------------------------------------------------------------
# Supabase I/O (stdlib)
# ---------------------------------------------------------------------------

class Api:
    def __init__(self, url: str, key: str, *, dry_run: bool = False) -> None:
        self.base = url.rstrip("/") + "/rest/v1/properties"
        self.key = key
        self.dry_run = dry_run
        self.requests_made = 0

    def _headers(self, extra: dict | None = None) -> dict:
        h = {"apikey": self.key, "Authorization": f"Bearer {self.key}", "User-Agent": USER_AGENT,
             "Content-Type": "application/json"}
        h.update(extra or {})
        return h

    def get(self, query: str) -> list[dict]:
        req = urllib.request.Request(f"{self.base}?{query}", headers=self._headers())
        with urllib.request.urlopen(req, timeout=60) as resp:
            self.requests_made += 1
            return json.loads(resp.read().decode())

    def patch(self, query: str, body: dict) -> None:
        if self.dry_run:
            return
        req = urllib.request.Request(f"{self.base}?{query}", data=json.dumps(body, default=str).encode(),
                                     method="PATCH", headers=self._headers({"Prefer": "return=minimal"}))
        with urllib.request.urlopen(req, timeout=60):
            self.requests_made += 1

    def has_columns(self, columns) -> bool:
        """Probe a set of columns. PostgREST answers HTTP 400 / 42703 for
        an unknown column."""
        try:
            self.get(f"select={','.join(columns)}&limit=0")
            return True
        except urllib.error.HTTPError as exc:
            text = exc.read().decode(errors="replace")[:300]
            if exc.code == 400 or "42703" in text or "does not exist" in text:
                return False
            raise

    def has_migration_017(self) -> bool:
        """Probe the lifecycle columns."""
        return self.has_columns(MIGRATION_017_COLUMNS)

    def has_migration_019(self) -> bool:
        """Probe the list-date columns (escheatment_date, available_date)."""
        return self.has_columns(tuple(SF.OPTIONAL_COLUMNS))


def q(value: str) -> str:
    return urllib.parse.quote(str(value), safe="")


def in_list(values: list[str]) -> str:
    return "(" + ",".join('"' + str(v).replace('"', '\\"') + '"' for v in values) + ")"


def fetch_state_rows(api: Api, state: str, counties: list[str], extra_columns=()) -> list[dict]:
    """The state's laft rows for these counties: identity + status for the
    lifecycle plan, plus the source-field columns (and field_provenance) the
    fill-blank step needs to know what is already there."""
    select = ["id", "county", "case_no", "status", "field_provenance", *SF.BASE_COLUMNS, *extra_columns]
    rows: list[dict] = []
    for i in range(0, len(counties), 25):
        chunk = counties[i:i + 25]
        rows.extend(api.get(f"state=eq.{state}&source=eq.{SOURCE}&county=in.{q(in_list(chunk))}"
                            f"&select={','.join(select)}&limit=10000"))
    return rows


def run_source_fields(observed: dict[str, dict[str, dict]], gates: dict[str, dict], db_rows: list[dict], api: Api,
                      *, have_019: bool, retrieved_at: str) -> tuple[SF.Counters, list[str]]:
    """The fill-blank carry of list-published fields (scripts/laft_source_fields.py)
    onto the observed rows. Independent of migration 017; the 019 date
    columns are included only when the database has them."""
    columns = list(SF.BASE_COLUMNS) + (list(SF.OPTIONAL_COLUMNS) if have_019 else [])
    updates, counters = SF.plan_source_fields(observed, db_rows, columns)
    SF.execute_source_fields(api, updates, gates, retrieved_at, counters)
    return counters, columns


def execute(plan: Plan, gates: dict[str, dict], observed: dict[str, dict[str, dict]], api: Api,
            *, state: str, have_017: bool, retrieved_at: str, registry_paths: dict | None = None,
            registry_modes: dict | None = None) -> dict:
    counts = {"observed": len(plan.observe), "reactivated": 0, "closed": 0, "provenance_patches": 0}
    # 1. Reactivation (status column exists today).
    by_county: dict[str, list[str]] = {}
    for county, case_no in plan.reactivate:
        by_county.setdefault(county, []).append(case_no)
    for county, keys in by_county.items():
        for i in range(0, len(keys), BATCH):
            api.patch(f"state=eq.{state}&source=eq.{SOURCE}&county=eq.{q(county)}&case_no=in.{q(in_list(keys[i:i + BATCH]))}",
                      {"status": "active"})
            counts["reactivated"] += len(keys[i:i + BATCH])
    # 2. last_seen_at + provenance (migration 017 only).
    if have_017:
        obs_by_county: dict[str, list[tuple[str, dict]]] = {}
        for county, case_no in plan.observe:
            obs_by_county.setdefault(county, []).append((case_no, observed[county][case_no]))
        for county, rows in obs_by_county.items():
            for payload, keys in group_provenance(rows, gates[county], retrieved_at, state=state, registry_paths=registry_paths,
                                                  registry_modes=registry_modes):
                for i in range(0, len(keys), BATCH):
                    api.patch(f"state=eq.{state}&source=eq.{SOURCE}&county=eq.{q(county)}&case_no=in.{q(in_list(keys[i:i + BATCH]))}",
                              payload)
                    counts["provenance_patches"] += 1
    # 3. Close-out.
    ids = [r["id"] for r in plan.close if r.get("id")]
    body = {"status": "closed"}
    if have_017:
        body["delisted_at"] = retrieved_at
    for i in range(0, len(ids), BATCH):
        api.patch(f"id=in.({','.join(str(x) for x in ids[i:i + BATCH])})", body)
        counts["closed"] += len(ids[i:i + BATCH])
    return counts


def summarize(plan: Plan, gates: dict[str, dict], counts: dict | None, have_017: bool | None, *, state: str = DEFAULT_STATE) -> str:
    by_status: dict[str, list[str]] = {}
    for county, g in sorted(gates.items()):
        by_status.setdefault(g["status"], []).append(county)
    lines = [f"LAFT lifecycle ({state}):"]
    for status in ("COMPLETE", "EMPTY", "INCOMPLETE", "FAILED", "SOURCE_UNAVAILABLE", "STALE", "NOT_RUN"):
        if status in by_status:
            lines.append(f"  {status}: {len(by_status[status])} - {', '.join(by_status[status])}")
    lines.append(f"  observed rows: {len(plan.observe)} (reactivated {len(plan.reactivate)}); "
                 f"close-out candidates: {len(plan.close)} across {len({r['county'] for r in plan.close})} county(ies); "
                 f"rows ignored (county not COMPLETE/INCOMPLETE): {plan.ignored_rows}")
    if plan.skipped_counties:
        lines.append("  close-out skipped (fail closed): " + ", ".join(f"{c} [{s}]" for c, s in sorted(plan.skipped_counties.items())))
    lines.append("  migration 017 columns: " + ("present" if have_017 else "absent - last_seen_at/provenance not written" if have_017 is False else "not probed"))
    if counts:
        lines.append(f"  applied: reactivated {counts['reactivated']}, provenance patches {counts['provenance_patches']}, closed {counts['closed']}")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--state", default=DEFAULT_STATE,
                    help="two-letter state whose laft rows this run may touch; must be registered in harvesters/governance/states.py")
    ap.add_argument("--status", default=str(DEFAULT_STATUS))
    ap.add_argument("--registry", default=str(DEFAULT_REGISTRY))
    ap.add_argument("--harvest", nargs="*", default=[str(p) for p in DEFAULT_HARVEST_FILES])
    ap.add_argument("--max-age-hours", type=float, default=36.0)
    ap.add_argument("--dry-run", action="store_true", help="plan and report; write nothing")
    ap.add_argument("--report", default="out/public/laft-lifecycle.json", help="counts-only report (no row values)")
    args = ap.parse_args(argv)

    state = args.state
    problems = states.state_problems(state)
    if problems:
        # Fail closed before any query: an unregistered state never reaches
        # the database, not even as a filter.
        print(f"::error title=laft_lifecycle::{'; '.join(problems)} - nothing observed, written or closed")
        return 2
    try:
        lifecycle_inventory(state)
    except ValueError as exc:
        print(f"::error title=laft_lifecycle::{exc} - nothing observed, written or closed")
        return 2

    status_path = Path(args.status)
    entries = load_status(status_path)
    if not status_path.is_file():
        print(f"::warning title=laft_lifecycle::{status_path} not found - nothing is observed or closed this run (fail closed)")
    elif not entries:
        print(f"::warning title=laft_lifecycle::{status_path} unreadable or empty - nothing is observed or closed this run (fail closed)")
    expected = load_expected_units(Path(args.registry), state)
    registry_paths = load_registry_purchase_paths(Path(args.registry), state)
    registry_modes = load_registry_purchase_modes(Path(args.registry), state)
    gates = county_gates(entries, expected, max_age_hours=args.max_age_hours, state=state) if entries else {}
    # A harvest row that names another state is not this run's (the FL
    # harvesters write no state key and are kept; the Alabama harvester
    # writes "AL" and is kept only by an AL run).
    observed = observed_by_county([r for r in load_harvest_rows([Path(p) for p in args.harvest])
                                   if not r.get("state") or str(r["state"]) == state])

    url = os.environ.get("SUPABASE_URL", "")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not url or not key:
        print("::warning title=laft_lifecycle::SUPABASE_URL / SUPABASE_SERVICE_KEY not set - planning only")
        plan = plan_lifecycle(gates, observed, [])
        print(summarize(plan, gates, None, None, state=state))
        return 0

    api = Api(url, key, dry_run=args.dry_run)
    counties = sorted(gates)
    have_017 = api.has_migration_017()
    have_019 = api.has_migration_019()
    db_rows = fetch_state_rows(api, state, counties, tuple(SF.OPTIONAL_COLUMNS) if have_019 else ()) if counties else []
    plan = plan_lifecycle(gates, observed, db_rows)
    if not have_017:
        print("::notice title=laft_lifecycle::migration 017 not applied - reactivation and close-out only; last_seen_at and provenance columns are not written")
    if not have_019:
        print("::notice title=laft_lifecycle::migration 019 not applied - escheatment_date / available_date are not written")
    retrieved_at = now_iso()
    counts = execute(plan, gates, observed, api, state=state, have_017=have_017, retrieved_at=retrieved_at,
                     registry_paths=registry_paths, registry_modes=registry_modes)
    # Observed rows only: the same COMPLETE/INCOMPLETE gate as last_seen_at.
    observed_gated = {c: rows for c, rows in observed.items() if gates.get(c, {}).get("status") in OBSERVED_STATUSES}
    sf_counts, sf_columns = run_source_fields(observed_gated, gates, db_rows, api, have_019=have_019, retrieved_at=retrieved_at)
    text = summarize(plan, gates, counts, have_017, state=state) + "\n" + SF.summarize(sf_counts, sf_columns)
    print(text + ("\n  (dry run - nothing written)" if args.dry_run else ""))
    report = {"state": state, "observed": counts["observed"], "reactivated": counts["reactivated"], "closed": counts["closed"],
              "provenance_patches": counts["provenance_patches"], "migration_017": have_017, "migration_019": have_019,
              "dry_run": args.dry_run, "source_fields": sf_counts.to_json(),
              "counties": {c: g["status"] for c, g in gates.items()}, "note": "counts and county names only; never a row value"}
    rp = Path(args.report)
    rp.parent.mkdir(parents=True, exist_ok=True)
    rp.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write("```\n" + text + "\n```\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
