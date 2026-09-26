#!/usr/bin/env python3
"""Phase B of the auction-event history plan: record what each harvest saw
as auction events and observations (migration 014), WITHOUT touching the
property snapshot the existing sync scripts maintain.

    out/harvest_all.json   (FL RealAuction + Okaloosa)  --source fl
    out/harvest_texas.json (TX RealAuction + LGBS)      --source tx
          |
          v  sightings (one per harvested auction row with a sale date)
    auction_events            one row per (property_id, scheduled_sale_date)
    auction_event_observations one append-only row per sighting

WHAT THIS DOES NOT DO
- It never writes `properties`. The property snapshot keeps being produced by
  sync-harvest-to-supabase.ps1 / sync-texas-to-supabase.py exactly as before;
  this script runs after them and only READS `properties` to resolve the
  property_id for each harvested identity (state, source, county, case_no).
  A harvested row with no property (not yet synced, or dropped by the
  governance gate) gets no event - the gate is respected by construction.
- It never infers an outcome. Every event it creates or touches keeps
  `outcome = 'unknown'` unless the source states a result, and no source in
  this pipeline does yet. `winning_bid`, `bid_count`, `winning_bidder_ref` and
  `outcome_effective_date` are never written (enforced in code and tests).
- It never sets `lifecycle` implicitly. Every event row and every observation
  carries an explicit lifecycle from the migration 014 vocabulary; the
  database default is only a fallback this script does not use.

LIFECYCLE RULES (Phase B)
- A row seen on a scheduled feed (RealAuction "Auctions Waiting", LGBS
  "Scheduled for Auction" / "Scheduled for Online Auction", Okaloosa's
  upcoming Bid4Assets listing) is `scheduled` for that (property, date).
- The same property seen under a NEW date is a NEW event; the earlier event
  is never overwritten or deleted.
- An earlier `scheduled` event is marked `superseded` only with evidence:
  its date has not passed, the county's harvest this run was COMPLETE, the
  property is listed under a different date this run, and the earlier date
  was not. Absence from one harvest alone is not evidence.
- A `scheduled` event whose date has passed and which is absent from a
  COMPLETE county harvest:
    * last seen ON or AFTER its sale date -> `completed` (it stayed listed
      through the sale day, then left the feed - migration 014's definition);
    * last seen BEFORE its sale date      -> `unknown` (it left the feed
      before the sale could happen; withdrawn / postponed / redeemed /
      corrected are indistinguishable, so none is claimed).
  Outcome stays `unknown` either way. See lifecycle_after_absence().
- Re-sighting: an event whose own (property, date) is listed on a scheduled
  feed again goes back to `scheduled`, whatever was derived for it before
  (completed / superseded / unknown). The derived observation stays in the
  history; the new sighting is recorded beside it (RESIGHT_LIFECYCLE).
- Derived transitions are recorded as observations with feed = 'derived'
  and raw_status NULL - they are inferences, never sightings of a feed.
- Texas has no per-county completeness file, so neither supersession nor
  completion is applied to Texas events in this phase; they stay `scheduled`
  until a later phase captures results. Nothing is guessed.

Each run stamps one `observed_at` (the run's start) on every observation it
writes, so (event_id, observed_at) is unique per run by construction, and
observation inserts ignore an exact duplicate of that key.

Write order (see record_sightings): an existing event's observation is
stored before the event is patched; a new event's first observation is
stored straight after its insert, and the insert is compensated (deleted)
if that fails. This is ordering plus compensation - PostgREST offers no
multi-table transaction without a schema/RPC change - not atomicity.

Failure visibility: the workflow step is continue-on-error so a writer
failure never fails the property harvest; the writer appends its result to
the job summary ($GITHUB_STEP_SUMMARY) and the workflow raises a warning
annotation when this step fails.

Credentials come from SUPABASE_URL / SUPABASE_SERVICE_KEY, the same secrets
every sync script uses; the service key is never logged. `--dry-run` reads
production and prints what would be written, writing nothing.
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
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Protocol

HERE = Path(__file__).resolve().parent
FL_HARVEST_JSON = HERE / "../out/harvest_all.json"
FL_STATUS_JSON = HERE / "../out/harvest_all_status.json"
TX_HARVEST_JSON = HERE / "../out/harvest_texas.json"

USER_AGENT = "taxdeed-scraper/1.0 (+https://github.com/rodzmodzllc-max/taxdeed-scraper; auction-events writer)"

# Migration 014 vocabularies, byte-for-byte.
LIFECYCLES = frozenset({"scheduled", "completed", "cancelled", "withdrawn", "stayed", "pending_result", "superseded", "unknown"})
OUTCOMES = frozenset({"sold", "redeemed", "struck_off", "future_sale", "no_sale", "unknown"})
URL_KINDS = frozenset({"property", "sale", "county", "info"})

# Never written by Phase B, under any circumstances.
FORBIDDEN_EVENT_KEYS = frozenset({"winning_bidder_ref", "winning_bid", "bid_count", "outcome_effective_date", "outcome_observed_at", "outcome_raw"})

# The only LGBS statuses that mean "scheduled" - the same two the harvester
# maps to the auction ledger (harvesters/texas_harvester.py LGBS_STATUS_TO_LEDGER).
LGBS_SCHEDULED_STATUSES = frozenset({"Scheduled for Auction", "Scheduled for Online Auction"})

REALAUCTION_PREVIEW_RE = re.compile(r"zaction=auction&zmethod=preview&auctiondate=", re.I)
ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
US_DATE_RE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$")


class WriterError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# Sightings: one harvested auction row with a sale date, normalized.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Sighting:
    state: str
    source: str
    county: str
    case_no: str
    scheduled_sale_date: str  # ISO YYYY-MM-DD
    feed: str                 # waiting | api | list
    lifecycle: str            # explicit, from LIFECYCLES
    raw_status: str | None
    opening_bid: float | None
    event_url: str | None
    event_url_kind: str | None

    def __post_init__(self) -> None:
        if self.lifecycle not in LIFECYCLES:
            raise WriterError(f"invalid lifecycle {self.lifecycle!r} for {self.state}/{self.county}/{self.case_no}")
        if self.event_url_kind is not None and self.event_url_kind not in URL_KINDS:
            raise WriterError(f"invalid event_url_kind {self.event_url_kind!r}")
        if not ISO_DATE_RE.match(self.scheduled_sale_date):
            raise WriterError(f"scheduled_sale_date must be ISO: {self.scheduled_sale_date!r}")


def iso_date(value: Any) -> str | None:
    """'MM/DD/YYYY' or 'YYYY-MM-DD' -> 'YYYY-MM-DD'; anything else -> None.
    Same two shapes sync-harvest-to-supabase.ps1's ConvertTo-IsoDate accepts."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    if ISO_DATE_RE.match(s):
        return s
    m = US_DATE_RE.match(s)
    if m:
        mm, dd, yyyy = (int(x) for x in m.groups())
        try:
            return date(yyyy, mm, dd).isoformat()
        except ValueError:
            return None
    return None


def _num(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    # The property pipeline stores an unpublished bid as 0 (see the sync
    # scripts' own headers); that sentinel is "not published", not a bid.
    return f if f > 0 else None


def sightings_from_fl_harvest(rows: Iterable[dict]) -> list[Sighting]:
    """out/harvest_all.json rows: county, sale_date (MM/DD/YYYY), case, bid,
    auction_url, host - exactly what harvest_all_counties.ps1 and
    harvest_okaloosa_bid4assets.ps1 emit and sync-harvest-to-supabase.ps1
    consumes. Every row here comes from a scheduled feed."""
    out: list[Sighting] = []
    for r in rows:
        county = (r.get("county") or "").strip()
        case_no = (r.get("case") or "").strip()
        sale = iso_date(r.get("sale_date"))
        if not county or not case_no or not sale:
            continue
        url = (r.get("auction_url") or "").strip() or None
        preview = bool(url and REALAUCTION_PREVIEW_RE.search(url))
        out.append(Sighting(
            state="FL", source="auction", county=county, case_no=case_no,
            scheduled_sale_date=sale,
            feed="waiting" if preview else "list",
            lifecycle="scheduled",
            raw_status="Auctions Waiting" if preview else None,
            opening_bid=_num(r.get("bid")),
            event_url=url,
            event_url_kind=("sale" if preview else "county") if url else None,
        ))
    return out


def sightings_from_tx_harvest(rows: Iterable[dict]) -> list[Sighting]:
    """out/harvest_texas.json rows (TexasSaleRow as dicts). Only auction-ledger
    rows with an ISO auction_date become sightings. LGBS rows must carry one
    of the two scheduled statuses; anything else is skipped rather than
    labelled scheduled. Struck-off / future-sale rows have no sale date and
    are inventory, not events."""
    out: list[Sighting] = []
    for r in rows:
        if r.get("source") != "auction":
            continue
        county = (r.get("county") or "").strip()
        case_no = (r.get("account_number") or "").strip()
        sale = iso_date(r.get("auction_date"))
        hs = r.get("harvester_source") or ""
        if not county or not case_no or not sale:
            continue
        if hs == "tx_realauction":
            url = (r.get("auction_url") or "").strip() or None
            kind = r.get("auction_url_kind") if url else None
            out.append(Sighting(
                state="TX", source="auction", county=county, case_no=case_no,
                scheduled_sale_date=sale, feed="waiting", lifecycle="scheduled",
                raw_status="Auctions Waiting", opening_bid=_num(r.get("min_bid")),
                event_url=url, event_url_kind=kind if kind in URL_KINDS else None,
            ))
        elif hs == "tx_lgbs":
            status = (r.get("sale_status") or "").strip()
            if status not in LGBS_SCHEDULED_STATUSES:
                continue
            out.append(Sighting(
                state="TX", source="auction", county=county, case_no=case_no,
                scheduled_sale_date=sale, feed="api", lifecycle="scheduled",
                raw_status=status, opening_bid=_num(r.get("min_bid")),
                event_url=None, event_url_kind=None,
            ))
        # Any other vendor: no writer here. Blocked vendors never reach
        # properties either (governance gate), so they get no events.
    return out


def complete_counties_from_fl_status(status_rows: Iterable[dict]) -> set[str]:
    """harvest_all_status.json: [{county, status, rowCount, reason}]. Only a
    county explicitly marked COMPLETE this run is evidence of absence -
    identical to the close-out gate in sync-harvest-to-supabase.ps1."""
    return {str(r.get("county")) for r in status_rows if r.get("status") == "COMPLETE" and r.get("county")}


# ---------------------------------------------------------------------------
# Store: the five calls the writer needs. PostgREST for real; tests use an
# in-memory implementation of the same protocol.
# ---------------------------------------------------------------------------

class Store(Protocol):
    def fetch_properties(self, state: str, source: str) -> list[dict]: ...
    def fetch_events(self, state: str, source: str) -> list[dict]: ...
    def insert_events(self, rows: list[dict]) -> list[dict]: ...
    def update_event(self, event_id: str, patch: dict) -> None: ...
    def insert_observations(self, rows: list[dict]) -> None: ...
    def delete_unobserved_events(self, event_ids: list[str], first_seen_at: str) -> None: ...


PROPERTY_COLUMNS = "id,state,source,county,case_no,harvester_source,ledger_type,sale_date,bid,status,url_auction,url_auction_kind,tx_sale_status"
EVENT_COLUMNS = "id,property_id,state,source,county,case_no,scheduled_sale_date,lifecycle,outcome,opening_bid,event_url,event_url_kind,first_seen_at,last_seen_at"

# Observations are the evidence; they are written in batches of this size.
BATCH = 500


class PostgrestStore:
    PAGE = 1000

    def __init__(self, supabase_url: str, service_key: str) -> None:
        self.base = supabase_url.rstrip("/") + "/rest/v1/"
        self._headers = {
            "apikey": service_key,
            "Authorization": f"Bearer {service_key}",
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
        }

    def _request(self, method: str, path: str, *, body: Any = None, prefer: str | None = None) -> Any:
        headers = dict(self._headers)
        if prefer:
            headers["Prefer"] = prefer
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw) if raw.strip() else None
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise WriterError(f"{method} {path} -> HTTP {exc.code}: {detail}") from exc

    def _paged(self, path: str) -> list[dict]:
        out: list[dict] = []
        offset = 0
        while True:
            sep = "&" if "?" in path else "?"
            page = self._request("GET", f"{path}{sep}limit={self.PAGE}&offset={offset}")
            page = page or []
            out.extend(page)
            if len(page) < self.PAGE:
                return out
            offset += self.PAGE

    def fetch_properties(self, state: str, source: str) -> list[dict]:
        q = urllib.parse.urlencode({"select": PROPERTY_COLUMNS, "state": f"eq.{state}", "source": f"eq.{source}", "order": "id"})
        return self._paged(f"properties?{q}")

    def fetch_events(self, state: str, source: str) -> list[dict]:
        q = urllib.parse.urlencode({"select": EVENT_COLUMNS, "state": f"eq.{state}", "source": f"eq.{source}", "order": "id"})
        return self._paged(f"auction_events?{q}")

    def insert_events(self, rows: list[dict]) -> list[dict]:
        return self._request("POST", "auction_events", body=rows, prefer="return=representation") or []

    def update_event(self, event_id: str, patch: dict) -> None:
        self._request("PATCH", f"auction_events?id=eq.{urllib.parse.quote(event_id)}", body=patch, prefer="return=minimal")

    def insert_observations(self, rows: list[dict]) -> None:
        # Idempotent on the table's own unique key: re-sending the same
        # (event_id, observed_at) is a no-op, never a second row.
        self._request("POST", "auction_event_observations?on_conflict=event_id,observed_at", body=rows,
                      prefer="return=minimal,resolution=ignore-duplicates")

    def delete_unobserved_events(self, event_ids: list[str], first_seen_at: str) -> None:
        # Compensation only: removes events THIS run inserted a moment ago
        # whose first observation could not be written. The first_seen_at
        # filter makes it impossible to touch an event from any other run.
        ids = ",".join(urllib.parse.quote(i) for i in event_ids)
        self._request("DELETE", f"auction_events?id=in.({ids})&first_seen_at=eq.{urllib.parse.quote(first_seen_at)}",
                      prefer="return=minimal")


class DryRunStore:
    """Reads through to a real store; records every write instead of sending
    it. Inserted events get synthetic ids so observations can reference them."""

    def __init__(self, inner: Store) -> None:
        self.inner = inner
        self.inserted_events: list[dict] = []
        self.updates: list[tuple[str, dict]] = []
        self.observations: list[dict] = []

    def fetch_properties(self, state: str, source: str) -> list[dict]:
        return self.inner.fetch_properties(state, source)

    def fetch_events(self, state: str, source: str) -> list[dict]:
        return self.inner.fetch_events(state, source)

    def insert_events(self, rows: list[dict]) -> list[dict]:
        out = []
        for r in rows:
            row = dict(r, id=f"dry-run-{len(self.inserted_events) + 1}")
            self.inserted_events.append(row)
            out.append(row)
        return out

    def update_event(self, event_id: str, patch: dict) -> None:
        self.updates.append((event_id, dict(patch)))

    def insert_observations(self, rows: list[dict]) -> None:
        self.observations.extend(dict(r) for r in rows)

    def delete_unobserved_events(self, event_ids: list[str], first_seen_at: str) -> None:
        pass


# ---------------------------------------------------------------------------
# Core: record sightings.
# ---------------------------------------------------------------------------

# Feed label for observations the writer DERIVES (supersession, completion,
# unknown) rather than reads off a source. Never a sighting of any feed.
DERIVED_FEED = "derived"

# Lifecycle applied when an event's own (property, date) is listed on a
# scheduled feed again. The source currently lists it, so it is scheduled -
# whatever this writer derived before (completed / superseded / unknown).
# The earlier derived observation stays in history; nothing is deleted.
RESIGHT_LIFECYCLE = "scheduled"

# Florida sale days are local days, and the state spans two time zones. A
# sighting counts as "on or after the sale date" using the date at UTC-6 -
# the earliest local date anywhere in Florida at that instant - so a late
# evening sighting the day BEFORE a sale can never count as a sale-day
# sighting. (The scheduled harvests run at 10:00 and 22:00 UTC.)
SALE_DAY_UTC_OFFSET = timezone(timedelta(hours=-6))


def sighting_local_date(ts: Any) -> date | None:
    """last_seen_at (ISO timestamptz) -> the conservative Florida-local date."""
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(SALE_DAY_UTC_OFFSET).date()


def lifecycle_after_absence(scheduled_sale_date: date, last_seen_at: Any) -> str:
    """The lifecycle for a `scheduled` event whose sale date has passed and
    which is absent from a COMPLETE county feed.

    - Last seen ON or AFTER its sale date -> 'completed': it stayed listed
      through the sale day and then left the feed (migration 014's definition).
    - Last seen BEFORE its sale date (or never recorded) -> 'unknown': it
      left the feed before the sale could happen. Withdrawn, postponed,
      redeemed, corrected - the feed does not say which, so nothing is
      claimed. 'pending_result' is not used: it would assert that the sale
      was held.
    Outcome is 'unknown' in every case."""
    seen = sighting_local_date(last_seen_at)
    return "completed" if seen is not None and seen >= scheduled_sale_date else "unknown"


@dataclass
class Summary:
    sightings: int = 0
    unmatched: int = 0          # harvested rows with no property row (not synced / gated)
    events_created: int = 0
    events_seen_again: int = 0
    events_reopened: int = 0    # re-sighted after a derived completed/superseded/unknown
    events_superseded: int = 0
    events_completed: int = 0
    events_unknown: int = 0     # left the feed before the sale date
    observations: int = 0
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}


def _check_event_payload(payload: dict) -> None:
    bad = FORBIDDEN_EVENT_KEYS & set(payload)
    if bad:
        raise WriterError(f"Phase B must not write {sorted(bad)}")
    if "lifecycle" in payload and payload["lifecycle"] not in LIFECYCLES:
        raise WriterError(f"invalid lifecycle {payload['lifecycle']!r}")
    if "outcome" in payload and payload["outcome"] != "unknown":
        raise WriterError("Phase B never sets an outcome other than 'unknown'")


def _observation(event_id: str, *, observed_at: str, run_id: str | None, feed: str, raw_status: str | None,
                 lifecycle: str, opening_bid: float | None, evidence_url: str | None) -> dict:
    if lifecycle not in LIFECYCLES:
        raise WriterError(f"invalid lifecycle {lifecycle!r}")
    return {
        "event_id": event_id,
        "observed_at": observed_at,
        "harvest_run_id": run_id,
        "feed": feed,
        "raw_status": raw_status,
        "lifecycle": lifecycle,
        "outcome": "unknown",
        "opening_bid": opening_bid,
        "evidence_url": evidence_url,
    }


def _batches(rows: list, size: int = BATCH) -> Iterable[list]:
    for i in range(0, len(rows), size):
        yield rows[i:i + size]


def record_sightings(store: Store, sightings: list[Sighting], *, scope: tuple[str, str], observed_at: str,
                     run_id: str | None, complete_counties: set[str] | None, today: date) -> Summary:
    """Record one harvest's sightings for one (state, source) scope.
    `complete_counties` is the set of counties whose harvest this run is
    known COMPLETE (FL); None means no absence-based transition (supersession
    / completion) is applied at all. The scope is processed even when the
    harvest produced no sightings in it, because a COMPLETE county with zero
    rows ("confirmed no scheduled auctions") is exactly the evidence that
    its past-dated events are over.

    WRITE ORDER (no database transaction is available over PostgREST without
    a schema/RPC change, so this is ordering plus compensation, not atomicity):
    1. Existing events: every observation is written FIRST, then the event
       is patched. An event's state (lifecycle, last_seen_at) therefore never
       advances without its observation already stored. If a patch fails
       after its observation is stored, the event merely lags its evidence
       and the next run re-derives it - and a lagging last_seen_at can only
       make the completion rule more conservative, never less.
    2. New events (the observation needs the event's id, and the foreign key
       needs the event first): each batch is inserted, then its observations
       are written immediately; if those fail, this run's just-inserted,
       never-observed events are deleted again (filtered on this run's
       first_seen_at) before the error is raised. An event row never
       survives without its first observation unless that compensating
       delete itself fails, which is reported in the error."""
    summary = Summary(sightings=len(sightings))
    state, source = scope
    in_scope = [s for s in sightings if (s.state, s.source) == scope]
    if len(in_scope) != len(sightings):
        summary.notes.append(f"{len(sightings) - len(in_scope)} sighting(s) outside scope {scope} ignored")

    props = {(p["county"], p["case_no"]): p for p in store.fetch_properties(state, source)}
    existing = store.fetch_events(state, source)
    by_key: dict[tuple[str, str], dict] = {(e["property_id"], str(e["scheduled_sale_date"])): e for e in existing}

    sighted: dict[tuple[str, str], Sighting] = {}
    for s in in_scope:
        p = props.get((s.county, s.case_no))
        if p is None:
            summary.unmatched += 1
            continue
        key = (p["id"], s.scheduled_sale_date)
        if key in sighted:
            continue  # duplicate row in one harvest: one observation per event per run
        sighted[key] = s

    # ---- plan: (observation, event_id, patch) for existing events, new rows
    existing_ops: list[tuple[dict, str, dict]] = []
    new_rows: list[tuple[dict, Sighting]] = []
    for key, s in sighted.items():
        p = props[(s.county, s.case_no)]
        ev = by_key.get(key)
        if ev is not None:
            patch: dict = {"lifecycle": RESIGHT_LIFECYCLE if s.lifecycle == "scheduled" else s.lifecycle,
                           "last_seen_at": observed_at}
            if s.event_url:
                patch["event_url"] = s.event_url
                patch["event_url_kind"] = s.event_url_kind
            if ev.get("opening_bid") is None and s.opening_bid is not None:
                patch["opening_bid"] = s.opening_bid
            _check_event_payload(patch)
            obs = _observation(ev["id"], observed_at=observed_at, run_id=run_id, feed=s.feed,
                               raw_status=s.raw_status, lifecycle=patch["lifecycle"],
                               opening_bid=s.opening_bid, evidence_url=s.event_url)
            existing_ops.append((obs, ev["id"], patch))
            summary.events_seen_again += 1
            if ev.get("lifecycle") != patch["lifecycle"]:
                summary.events_reopened += 1
        else:
            row = {
                "property_id": p["id"],
                "state": state, "source": source,
                "harvester_source": p.get("harvester_source"),
                "county": p["county"], "case_no": p["case_no"],
                "ledger_type": p.get("ledger_type"),
                "scheduled_sale_date": s.scheduled_sale_date,
                "event_url": s.event_url, "event_url_kind": s.event_url_kind,
                "opening_bid": s.opening_bid,
                "lifecycle": s.lifecycle,   # explicit, never the DB default
                "outcome": "unknown",
                "first_seen_at": observed_at, "last_seen_at": observed_at,
            }
            _check_event_payload(row)
            new_rows.append((row, s))

    # Absence-based transitions: only with a completeness gate, only for
    # events that were `scheduled` before this run, and only for properties
    # in COMPLETE counties. Derived observations carry feed 'derived' and no
    # raw status - they record an inference, not a sighting.
    if complete_counties is not None:
        for ev in existing:
            key = (ev["property_id"], str(ev["scheduled_sale_date"]))
            if ev.get("lifecycle") != "scheduled" or key in sighted or ev.get("county") not in complete_counties:
                continue
            ev_date = date.fromisoformat(str(ev["scheduled_sale_date"]))
            if ev_date >= today:
                # Not yet passed. Evidence of replacement = the same property
                # is listed under a different date this run.
                other = next((sighted[k] for k in sighted if k[0] == ev["property_id"]), None)
                if other is None:
                    continue  # absent but not re-listed: no evidence, leave scheduled
                lifecycle, evidence = "superseded", other.event_url
                summary.events_superseded += 1
            else:
                lifecycle, evidence = lifecycle_after_absence(ev_date, ev.get("last_seen_at")), None
                if lifecycle == "completed":
                    summary.events_completed += 1
                else:
                    summary.events_unknown += 1
            patch = {"lifecycle": lifecycle}
            _check_event_payload(patch)
            obs = _observation(ev["id"], observed_at=observed_at, run_id=run_id, feed=DERIVED_FEED,
                               raw_status=None, lifecycle=lifecycle, opening_bid=None, evidence_url=evidence)
            existing_ops.append((obs, ev["id"], patch))
        if sighted and not complete_counties:
            summary.notes.append(f"{state}/{source}: no COMPLETE county this run - no absence-based transitions")

    # ---- 1. existing events: observations first, then patches
    for batch in _batches([op[0] for op in existing_ops]):
        store.insert_observations(batch)
        summary.observations += len(batch)
    for _obs, event_id, patch in existing_ops:
        store.update_event(event_id, patch)

    # ---- 2. new events: insert batch, observe it, compensate on failure
    for batch in _batches(new_rows):
        inserted = store.insert_events([row for row, _ in batch])
        if len(inserted) != len(batch):
            raise WriterError(f"inserted {len(inserted)} events for {len(batch)} rows")
        observations = [
            _observation(ins["id"], observed_at=observed_at, run_id=run_id, feed=s.feed,
                         raw_status=s.raw_status, lifecycle=s.lifecycle,
                         opening_bid=s.opening_bid, evidence_url=s.event_url)
            for ins, (_row, s) in zip(inserted, batch)
        ]
        try:
            store.insert_observations(observations)
        except Exception as exc:
            ids = [ins["id"] for ins in inserted]
            try:
                store.delete_unobserved_events(ids, observed_at)
            except Exception as comp_exc:
                raise WriterError(f"observations failed ({exc}) AND compensating delete of {len(ids)} new events "
                                  f"failed ({comp_exc}) - those events have no observation") from exc
            raise WriterError(f"observations failed for {len(ids)} new events; they were removed again: {exc}") from exc
        summary.events_created += len(batch)
        summary.observations += len(observations)

    return summary


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _load_json(path: Path) -> Any:
    if not path.exists():
        raise WriterError(f"{path} not found - run the harvester first")
    return json.loads(path.read_text(encoding="utf-8"))


def build_store(dry_run: bool) -> Store:
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_KEY")  # never logged
    if not url or not key:
        raise WriterError("SUPABASE_URL / SUPABASE_SERVICE_KEY are not set")
    real = PostgrestStore(url, key)
    return DryRunStore(real) if dry_run else real


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--source", choices=["fl", "tx"], required=True)
    ap.add_argument("--dry-run", action="store_true", help="read production, write nothing, print the plan")
    ap.add_argument("--harvest-json", type=Path, default=None)
    ap.add_argument("--status-json", type=Path, default=None)
    args = ap.parse_args(argv)

    observed_at = datetime.now(timezone.utc).isoformat()
    run_id = os.environ.get("GITHUB_RUN_ID") or None
    today = datetime.now(timezone.utc).date()

    if args.source == "fl":
        rows = _load_json(args.harvest_json or FL_HARVEST_JSON)
        sightings = sightings_from_fl_harvest(rows)
        status_path = args.status_json or FL_STATUS_JSON
        complete = complete_counties_from_fl_status(_load_json(status_path)) if status_path.exists() else set()
        if not status_path.exists():
            print(f"auction_events_writer: {status_path} missing - no county treated as COMPLETE (fail closed)", file=sys.stderr)
    else:
        rows = _load_json(args.harvest_json or TX_HARVEST_JSON)
        sightings = sightings_from_tx_harvest(rows)
        complete = None  # no per-county completeness for Texas yet - see header

    scope = ("FL", "auction") if args.source == "fl" else ("TX", "auction")
    store = build_store(args.dry_run)
    summary = record_sightings(store, sightings, scope=scope, observed_at=observed_at, run_id=run_id,
                               complete_counties=complete, today=today)
    label = "DRY RUN - nothing written" if args.dry_run else "written"
    print(f"auction_events_writer ({args.source.upper()}, {label}): {json.dumps(summary.as_dict())}")
    if args.dry_run and isinstance(store, DryRunStore):
        print(f"  would insert {len(store.inserted_events)} events, patch {len(store.updates)} events, append {len(store.observations)} observations")
    write_step_summary(f"### Phase B event recording ({args.source.upper()}): OK ({label})\n\n"
                       f"```\n{json.dumps(summary.as_dict(), indent=1)}\n```\n")
    return 0


def write_step_summary(markdown: str) -> None:
    """Append to the GitHub Actions job summary when running in Actions."""
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    try:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(markdown + "\n")
    except OSError:
        pass


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # WriterError or anything unexpected: fail loudly, never silently
        print(f"auction_events_writer: ERROR - {exc}", file=sys.stderr)
        write_step_summary("### Phase B event recording: FAILED\n\n"
                           "The property harvest and sync already completed before this step; only the "
                           f"auction-event recording failed.\n\n`{type(exc).__name__}: {str(exc)[:300]}`\n")
        sys.exit(1)
