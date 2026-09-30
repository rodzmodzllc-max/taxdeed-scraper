#!/usr/bin/env python3
"""Verified auction outcomes from source-published results (auction-outcome
evidence sprint, 2026-09-30).

WHAT THIS DOES

For Florida auction events (migration 014's auction_events) whose sale date
has passed, it reads what the approved auction source itself PUBLISHES
about each sale-day item, deterministically matches each published item to
exactly one event, and records a result only when the source's own status
wording is one a reviewed row of data/auction_outcome_wordings.csv maps.

    RealAuction sale day (the harvester's own host + anonymous session)
        AREA=C "Auctions Closed or Canceled"   -> the items (Case #, Parcel ID)
        FNC=UPDATE&ref=<the items' own ids>    -> each item's status lines
          (the call the sale-day page itself makes to fill its status box:
           A = status wording, C/D = a labelled amount, SL/ST = a purchaser
           CATEGORY such as "3rd Party Bidder" - never a name)

WHAT AN OUTCOME IS, HERE

- A published status wording, verbatim (outcome_raw / raw_status), mapped by
  an enabled, verified wording row to one explicit result:
    sold | struck_off | redeemed | no_sale   (auction_events.outcome)
    withdrawn | cancelled                    (auction_events.lifecycle)
- Matched to the event by the item's own "Case #" cell equal to the event's
  case_no (the same cell the harvester stored). When both sides publish a
  parcel it must agree, or nothing is written. Parcel alone is used only by
  the generic matcher (match_record) for sources whose results carry no case
  number; the RealAuction adapter never needs it.
- Written with the page it was read from (evidence_url = the sale-day page),
  the observation time, and feed 'closed' (the Closed / Canceled listing -
  a property-specific item, never a county-level statement).

WHAT IS NEVER DONE

- Nothing is inferred from absence, a passed date, a bid, a value or a
  count. An event that is not on the closed listing stays as it is.
- A status wording no reviewed row maps is recorded as "checked, not
  published" (an observation with outcome 'unknown' and the wording kept
  verbatim) - never guessed.
- A failed read (transport error, login page, non-JSON) writes NOTHING to
  any event: the last verified outcome is never erased by a failure.
- A later verified result supersedes an earlier 'unknown' through a new
  observation; history is append-only and never rewritten.
- The purchaser is never stored. A winning bid is stored only when the
  wording row names the amount label AND the item publishes that label with
  a money value; a bid count and a bidder identity are never written.
- No login, no credential, no search engine, no homepage, no crawl: only the
  host each production registry row already names, for sale days an event
  already has.

Credentials: SUPABASE_URL / SUPABASE_SERVICE_KEY (same as every sync);
--dry-run reads production and writes nothing. Output: a value-free report
at out/public/auction-outcomes.json and the job summary.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
WORDINGS_PATH = REPO / "data" / "auction_outcome_wordings.csv"
HOSTS_PATH = REPO / "data" / "realauction_counties.csv"
REPORT_PATH = REPO / "out" / "public" / "auction-outcomes.json"

# Migration 014 vocabularies (auction_events / auction_event_observations).
OUTCOMES_014 = frozenset({"sold", "redeemed", "struck_off", "future_sale", "no_sale", "unknown"})
LIFECYCLES_014 = frozenset({"scheduled", "completed", "cancelled", "withdrawn", "stayed", "pending_result", "superseded", "unknown"})

# The explicit, finite result vocabulary a wording row may name, and where
# each lands in migration 014's columns: (outcome, lifecycle).
RESULTS: dict[str, tuple[str, str]] = {
    "sold": ("sold", "completed"),
    "struck_off": ("struck_off", "completed"),   # unsold / struck off to the county / failed sale
    "no_sale": ("no_sale", "completed"),         # the source says no sale took place, without saying why
    "redeemed": ("redeemed", "cancelled"),       # redemption cancels the sale; outcome carries the fact
    "withdrawn": ("unknown", "withdrawn"),
    "cancelled": ("unknown", "cancelled"),
}

# Customer-facing outcome states (the UI derives the same set from the event
# row and its observations; see eventOutcomeState() in public/app.js).
CUSTOMER_STATES = (
    "scheduled", "outcome_not_verified", "outcome_not_published", "sold", "struck_off",
    "no_sale", "withdrawn", "cancelled", "redeemed", "source_unavailable",
)

CLOSED_FEED = "closed"
EVIDENCE_TYPE = "realauction_closed_listing"
EVIDENCE_SCOPE = "property"        # one item of the official sale-day listing, per property
WORDING_COLUMNS = ["source_family", "raw_wording", "result", "amount_label", "enabled", "verified_on",
                   "evidence_run", "notes"]
_TRUE = frozenset({"1", "true", "yes", "y"})
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_MONEY = re.compile(r"^\$\s*([\d,]+(?:\.\d{1,2})?)$")

# Evidence that can never establish an outcome.
SEARCH_HOSTS = re.compile(r"(^|\.)(google|bing|yahoo|duckduckgo|baidu|yandex|ask)\.[a-z.]+$", re.I)
_LOGIN = re.compile(r"(user\s*name|user\s*password|log\s*in to|sign in)", re.I)


class OutcomeError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# Wording table (the only path from a published wording to a result)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Wording:
    source_family: str
    raw_wording: str
    result: str
    amount_label: str
    enabled: bool
    verified_on: str
    evidence_run: str
    notes: str = ""

    def key(self) -> tuple[str, str]:
        return (self.source_family, norm_wording(self.raw_wording))


def norm_wording(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip()).lower()


def wording_problems(w: Wording) -> list[str]:
    p: list[str] = []
    if not w.source_family:
        p.append("source_family required")
    if not w.raw_wording.strip():
        p.append("raw_wording required")
    if w.result not in RESULTS:
        p.append(f"result {w.result!r} (one of {sorted(RESULTS)})")
    if w.amount_label and w.result != "sold":
        p.append("amount_label only on a 'sold' wording")
    if w.enabled and not (_DATE.match(w.verified_on) and w.evidence_run.strip()):
        p.append("an enabled wording needs verified_on (YYYY-MM-DD) and evidence_run (the capture that observed it)")
    return p


def load_wordings(path: Path | str = WORDINGS_PATH) -> dict[tuple[str, str], Wording]:
    p = Path(path)
    if not p.is_file():
        return {}
    out: dict[tuple[str, str], Wording] = {}
    with open(p, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames != WORDING_COLUMNS:
            raise OutcomeError(f"{p.name}: columns must be {WORDING_COLUMNS}, got {reader.fieldnames}")
        for i, r in enumerate(reader, 2):
            w = Wording(source_family=(r["source_family"] or "").strip(), raw_wording=(r["raw_wording"] or "").strip(),
                        result=(r["result"] or "").strip(), amount_label=(r["amount_label"] or "").strip(),
                        enabled=(r["enabled"] or "").strip().lower() in _TRUE, verified_on=(r["verified_on"] or "").strip(),
                        evidence_run=(r["evidence_run"] or "").strip(), notes=(r["notes"] or "").strip())
            problems = wording_problems(w)
            if problems:
                raise OutcomeError(f"{p.name} line {i}: " + "; ".join(problems))
            if w.key() in out:
                raise OutcomeError(f"{p.name} line {i}: duplicate wording {w.raw_wording!r} for {w.source_family}")
            if w.enabled:
                out[w.key()] = w
    return out


# ---------------------------------------------------------------------------
# Evidence validity
# ---------------------------------------------------------------------------

def evidence_refusal(url: str | None, *, page_text: str | None = None) -> str | None:
    """Why a page can never be outcome evidence, or None. A result page must
    be an https page of the source itself, below its homepage, and not the
    login form."""
    if not url:
        return "no evidence URL"
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != "https":
        return "not https"
    host = (parts.hostname or "").lower()
    if SEARCH_HOSTS.search(host):
        return "search engine result"
    if parts.path in ("", "/") and not parts.query:
        return "homepage"
    if page_text is not None and _LOGIN.search(page_text) and "AITEM_" not in page_text and '"ADATA"' not in page_text:
        return "login page"
    return None


# ---------------------------------------------------------------------------
# Published result records and deterministic matching
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ResultRecord:
    """One property-level item a source published for one sale day."""
    source_family: str
    county: str
    sale_date: str            # ISO
    case_no: str
    parcel: str
    raw_wording: str          # the status line, verbatim ('' when the item publishes none)
    amount_label: str = ""    # the label printed beside the amount, verbatim
    amount_text: str = ""     # the amount cell, verbatim
    evidence_url: str = ""
    evidence_scope: str = EVIDENCE_SCOPE


def norm_id(value: str | None) -> str:
    """Identifier comparison form: whitespace collapsed, upper-cased. No
    digit is added, dropped or reordered - 'exact' means exact characters."""
    return re.sub(r"\s+", " ", str(value or "").strip()).upper()


@dataclass
class Match:
    event: dict | None
    key: str | None           # 'case_no' | 'parcel' | None
    reason: str               # why matched / why not


def match_record(rec: ResultRecord, events: list[dict]) -> Match:
    """Exactly one event on the same county and sale date, by exact case
    number; by exact parcel only when the record publishes no case number.
    A conflicting parcel, an ambiguous key or no key refuses the match.
    Owner names, addresses and legal descriptions are never consulted."""
    same_day = [e for e in events if e.get("county") == rec.county and str(e.get("scheduled_sale_date")) == rec.sale_date]
    if rec.case_no:
        hits = [e for e in same_day if norm_id(e.get("case_no")) == norm_id(rec.case_no)]
        if len(hits) > 1:
            return Match(None, None, "ambiguous case number")
        if not hits:
            return Match(None, None, "no event with this case number on this sale day")
        ev = hits[0]
        ev_parcel = norm_id(ev.get("parcel"))
        if rec.parcel and ev_parcel and norm_id(rec.parcel) != ev_parcel:
            return Match(None, None, "case number matches but the published parcel differs")
        return Match(ev, "case_no", "exact case number")
    if rec.parcel:
        hits = [e for e in same_day if e.get("parcel") and norm_id(e.get("parcel")) == norm_id(rec.parcel)]
        if len(hits) == 1:
            return Match(hits[0], "parcel", "exact parcel")
        return Match(None, None, "ambiguous parcel" if hits else "no event with this parcel on this sale day")
    return Match(None, None, "the record publishes no case number or parcel")


def published_amount(rec: ResultRecord, wording: Wording) -> float | None:
    """The sale amount, only when the wording row names the label the source
    prints beside it and the cell is a plain money value."""
    if not wording.amount_label or wording.result != "sold":
        return None
    if norm_wording(rec.amount_label) != norm_wording(wording.amount_label):
        return None
    m = _MONEY.match((rec.amount_text or "").strip())
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", ""))
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Planning (pure; unit-tested without a network or a database)
# ---------------------------------------------------------------------------

@dataclass
class DayRead:
    """One (county, sale day) read of the source."""
    county: str
    sale_date: str
    ok: bool
    error: str | None = None
    records: list[ResultRecord] = field(default_factory=list)
    complete: bool = True     # False when paging may have truncated the listing
    evidence_url: str = ""


@dataclass
class Plan:
    observations: list[dict] = field(default_factory=list)
    patches: list[tuple[str, dict]] = field(default_factory=list)
    stats: dict = field(default_factory=dict)
    by_county: dict = field(default_factory=dict)


def _bump(d: dict, key: str, n: int = 1) -> None:
    d[key] = d.get(key, 0) + n


def is_verified(ev: dict) -> bool:
    """An event already carries a source-published result."""
    if ev.get("outcome") and ev["outcome"] != "unknown" and ev.get("outcome_raw"):
        return True
    return ev.get("lifecycle") in ("withdrawn", "cancelled") and bool(ev.get("outcome_raw"))


def plan_outcomes(reads: list[DayRead], events: list[dict], wordings: dict[tuple[str, str], Wording], *,
                  observed_at: str, run_id: str | None, last_closed: dict[str, dict] | None = None) -> Plan:
    """Observations to append and event patches to apply for one run.
    `last_closed` maps event id -> its latest feed-'closed' observation, so
    an unchanged re-check appends nothing."""
    plan = Plan()
    st = plan.stats
    last_closed = last_closed or {}
    for key in ("days_read", "days_unavailable", "records", "matched", "unmatched_records", "verified_new",
                "verified_unchanged", "not_published", "amounts", "refused_conflict"):
        st[key] = 0
    st["by_result"] = {}
    st["unmatched_reasons"] = {}
    for read in reads:
        county = plan.by_county.setdefault(read.county, {"days_read": 0, "days_unavailable": 0, "records": 0,
                                                         "matched": 0, "verified": 0, "not_published": 0, "unmatched": 0})
        if not read.ok:
            _bump(st, "days_unavailable")
            _bump(county, "days_unavailable")
            continue   # a failed read writes nothing, anywhere
        _bump(st, "days_read")
        _bump(county, "days_read")
        for rec in read.records:
            _bump(st, "records")
            _bump(county, "records")
            m = match_record(rec, events)
            if m.event is None:
                _bump(st, "unmatched_records")
                _bump(county, "unmatched")
                _bump(st["unmatched_reasons"], m.reason)
                if "differs" in m.reason:
                    _bump(st, "refused_conflict")
                continue
            ev = m.event
            _bump(st, "matched")
            _bump(county, "matched")
            if evidence_refusal(rec.evidence_url or read.evidence_url) is not None:
                continue
            wording = wordings.get((rec.source_family, norm_wording(rec.raw_wording))) if rec.raw_wording else None
            prev = last_closed.get(ev["id"]) or {}
            if wording is None:
                # Checked, and the source publishes no result wording we can
                # read as one: never a guess. Recorded once per change.
                raw = rec.raw_wording or None
                if prev.get("outcome", "unknown") == "unknown" and (prev.get("raw_status") or None) == raw and prev:
                    continue
                if is_verified(ev):
                    continue   # a verified result is never overwritten by "not published"
                plan.observations.append(_obs(ev, observed_at, run_id, raw, ev.get("lifecycle") or "unknown", "unknown",
                                              None, rec.evidence_url or read.evidence_url))
                _bump(st, "not_published")
                _bump(county, "not_published")
                continue
            outcome, lifecycle = RESULTS[wording.result]
            amount = published_amount(rec, wording)
            if (ev.get("outcome") == outcome and ev.get("lifecycle") == lifecycle
                    and norm_wording(ev.get("outcome_raw") or "") == norm_wording(rec.raw_wording)):
                _bump(st, "verified_unchanged")
                continue
            obs = _obs(ev, observed_at, run_id, rec.raw_wording, lifecycle, outcome, amount, rec.evidence_url or read.evidence_url)
            patch = {"lifecycle": lifecycle, "outcome": outcome, "outcome_raw": rec.raw_wording,
                     "outcome_observed_at": observed_at}
            if amount is not None:
                patch["winning_bid"] = amount
                _bump(st, "amounts")
            check_patch(patch)
            plan.observations.append(obs)
            plan.patches.append((ev["id"], patch))
            _bump(st, "verified_new")
            _bump(county, "verified")
            _bump(st["by_result"], wording.result)
    return plan


def _obs(ev: dict, observed_at: str, run_id: str | None, raw: str | None, lifecycle: str, outcome: str,
         amount: float | None, evidence_url: str) -> dict:
    if lifecycle not in LIFECYCLES_014 or outcome not in OUTCOMES_014:
        raise OutcomeError(f"invalid lifecycle/outcome {lifecycle!r}/{outcome!r}")
    if (outcome != "unknown" or lifecycle in ("withdrawn", "cancelled")) and not raw:
        raise OutcomeError("a result observation must carry the source's own wording")
    return {"event_id": ev["id"], "observed_at": observed_at, "harvest_run_id": run_id, "feed": CLOSED_FEED,
            "raw_status": raw, "lifecycle": lifecycle, "outcome": outcome, "opening_bid": None,
            "winning_bid": amount, "bid_count": None, "evidence_url": evidence_url}


FORBIDDEN_PATCH_KEYS = frozenset({"winning_bidder_ref", "bid_count", "outcome_effective_date", "scheduled_sale_date",
                                  "property_id", "case_no", "county"})


def check_patch(patch: dict) -> None:
    bad = FORBIDDEN_PATCH_KEYS & set(patch)
    if bad:
        raise OutcomeError(f"an outcome patch must not write {sorted(bad)}")
    if patch.get("outcome") not in OUTCOMES_014 or patch.get("lifecycle") not in LIFECYCLES_014:
        raise OutcomeError("invalid outcome / lifecycle")
    if not patch.get("outcome_raw") or not patch.get("outcome_observed_at"):
        raise OutcomeError("a result carries the source wording and the observation time")


# ---------------------------------------------------------------------------
# RealAuction adapter
# ---------------------------------------------------------------------------

REALAUCTION_FAMILY = "realauction"


def realauction_wording(status: dict) -> str:
    """The status wording the sale-day page prints for one closed item, as
    the site's own status record carries it (observed in capture runs
    36729310846 / 36731088178):
      - a sale: A = "Auction Sold" (B = the time, C/D = "Amount" and value);
      - otherwise: A = a one-letter layout code and B = the wording
        (e.g. "Redeemed").
    Returned verbatim; '' when the record carries no wording."""
    import realauction_results as RR  # sibling module
    a = RR.clean(str(status.get("A") or ""))
    if re.fullmatch(r"[A-Z]", a):
        b = RR.clean(str(status.get("B") or ""))
        return b if re.fullmatch(r"[A-Za-z][A-Za-z\- ]{0,39}", b) else ""
    return a


def records_from_realauction(county: str, sale_date_iso: str, fetch: Any) -> DayRead:
    """Turn one realauction_results.fetch_area() result into a DayRead:
    items joined to their status lines by the site's own item id."""
    import realauction_results as RR  # sibling module
    read = DayRead(county=county, sale_date=sale_date_iso, ok=bool(fetch.ok and not fetch.login_page and not fetch.error),
                   error=fetch.error or ("login page" if fetch.login_page else None), evidence_url=fetch.url)
    if not read.ok:
        return read
    if fetch.aids and fetch.update_raw is None:
        read.ok, read.error = False, f"status refresh unavailable ({fetch.update_error or 'no response'})"
        return read
    status = {str(i.get("AID")): i for i in RR.update_items(fetch.update_raw or "")}
    item_ids = list(fetch.aids)
    if len(item_ids) != len(fetch.items):
        # rlist and the parsed blocks disagree: the join by position is not
        # trustworthy, so the day is treated as unreadable (nothing written).
        read.ok, read.error = False, f"item/id count mismatch ({len(fetch.items)} items, {len(item_ids)} ids)"
        return read
    for aid, item in zip(item_ids, fetch.items):
        s = status.get(aid) or {}
        read.records.append(ResultRecord(
            source_family=REALAUCTION_FAMILY, county=county, sale_date=sale_date_iso,
            case_no=item.case_no, parcel=item.parcel, raw_wording=realauction_wording(s),
            amount_label=RR.clean(str(s.get("C") or "")), amount_text=RR.clean(str(s.get("D") or "")),
            evidence_url=fetch.url))
    read.complete = not fetch.truncated
    return read


# ---------------------------------------------------------------------------
# Production I/O
# ---------------------------------------------------------------------------

class Api:
    def __init__(self, url: str, key: str, *, dry_run: bool = False) -> None:
        self.base = url.rstrip("/") + "/rest/v1/"
        self.key = key
        self.dry_run = dry_run

    def _req(self, method: str, path: str, body: Any = None, prefer: str | None = None) -> Any:
        headers = {"apikey": self.key, "Authorization": f"Bearer {self.key}", "Content-Type": "application/json"}
        if prefer:
            headers["Prefer"] = prefer
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=headers)
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read()
            return json.loads(raw) if raw else None

    def get_all(self, path: str) -> list[dict]:
        out: list[dict] = []
        off = 0
        while True:
            sep = "&" if "?" in path else "?"
            page = self._req("GET", f"{path}{sep}limit=1000&offset={off}") or []
            out.extend(page)
            if len(page) < 1000:
                return out
            off += 1000

    def insert_observations(self, rows: list[dict]) -> None:
        if self.dry_run or not rows:
            return
        for i in range(0, len(rows), 200):
            self._req("POST", "auction_event_observations?on_conflict=event_id,observed_at", rows[i:i + 200],
                      prefer="resolution=ignore-duplicates,return=minimal")

    def patch_event(self, event_id: str, patch: dict) -> None:
        if self.dry_run:
            return
        self._req("PATCH", f"auction_events?id=eq.{urllib.parse.quote(event_id)}", patch, prefer="return=minimal")


def fl_today() -> date:
    return datetime.now(timezone(timedelta(hours=-5))).date()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--days", type=int, default=21, help="sale days within this many days before today")
    ap.add_argument("--county", action="append", default=[])
    ap.add_argument("--report", default=str(REPORT_PATH))
    args = ap.parse_args(argv)
    url, key = os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_SERVICE_KEY")
    if not url or not key:
        print("SUPABASE_URL / SUPABASE_SERVICE_KEY not set", file=sys.stderr)
        return 2
    import requests
    import realauction_results as RR
    api = Api(url, key, dry_run=args.dry_run)
    wordings = load_wordings()
    today = fl_today()
    since = today - timedelta(days=args.days)
    events = api.get_all(
        "auction_events?state=eq.FL&source=eq.auction&lifecycle=neq.superseded"
        f"&scheduled_sale_date=lt.{today.isoformat()}&scheduled_sale_date=gte.{since.isoformat()}"
        "&select=id,property_id,county,case_no,scheduled_sale_date,lifecycle,outcome,outcome_raw,event_url")
    # Parcel for the agreement check comes from the property row the event
    # belongs to (the harvester's own 'Parcel ID' cell).
    parcels: dict[str, str] = {}
    pids = sorted({e["property_id"] for e in events})
    for i in range(0, len(pids), 150):
        chunk = ",".join(pids[i:i + 150])
        for p in api.get_all(f"properties?id=in.({chunk})&select=id,parcel"):
            parcels[p["id"]] = p.get("parcel") or ""
    for e in events:
        e["parcel"] = parcels.get(e["property_id"], "")
    last_closed: dict[str, dict] = {}
    ids = [e["id"] for e in events]
    for i in range(0, len(ids), 150):
        chunk = ",".join(ids[i:i + 150])
        for o in api.get_all(f"auction_event_observations?feed=eq.{CLOSED_FEED}&event_id=in.({chunk})"
                             "&select=event_id,observed_at,raw_status,outcome,lifecycle&order=observed_at.asc"):
            last_closed[o["event_id"]] = o
    with open(HOSTS_PATH, newline="", encoding="utf-8") as fh:
        hosts = {r["County"]: r["Host"] for r in csv.DictReader(fh)}
    days = sorted({(e["county"], str(e["scheduled_sale_date"])) for e in events if not args.county or e["county"] in args.county})
    reads: list[DayRead] = []
    skipped_no_host = 0
    for county, iso in days:
        host = hosts.get(county)
        if not host:
            skipped_no_host += 1
            continue
        mdy = datetime.strptime(iso, "%Y-%m-%d").strftime("%m/%d/%Y")
        fetch = RR.fetch_area(requests.Session(), host, mdy)
        read = records_from_realauction(county, iso, fetch)
        reads.append(read)
        print(f"  {county:<14} {iso}: {'read' if read.ok else 'UNAVAILABLE'} records={len(read.records)}"
              f"{'' if read.complete else ' (listing may be truncated)'}{'' if read.ok else ' - ' + str(read.error)}", flush=True)
    observed_at = datetime.now(timezone.utc).isoformat()
    run_id = os.environ.get("GITHUB_RUN_ID")
    plan = plan_outcomes(reads, events, wordings, observed_at=observed_at, run_id=run_id, last_closed=last_closed)
    api.insert_observations(plan.observations)
    for event_id, patch in plan.patches:
        api.patch_event(event_id, patch)
    past_events = len(events)
    report = {"generated_at": observed_at, "dry_run": args.dry_run, "window": {"from": since.isoformat(), "to_before": today.isoformat()},
              "events_in_window": past_events, "sale_days": len(days), "sale_days_without_host": skipped_no_host,
              "wordings_enabled": len(wordings), **plan.stats, "by_county": plan.by_county,
              "observations_written": 0 if args.dry_run else len(plan.observations),
              "events_patched": 0 if args.dry_run else len(plan.patches)}
    out = Path(args.report)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    line = (f"auction outcomes (FL, sale days {since}..{today - timedelta(days=1)}): events {past_events}, days read "
            f"{plan.stats['days_read']}, unavailable {plan.stats['days_unavailable']}, records {plan.stats['records']}, "
            f"matched {plan.stats['matched']}, unmatched {plan.stats['unmatched_records']}, verified new {plan.stats['verified_new']} "
            f"{plan.stats['by_result']}, unchanged {plan.stats['verified_unchanged']}, not published {plan.stats['not_published']}, "
            f"amounts {plan.stats['amounts']}{' [dry run]' if args.dry_run else ''}")
    print(line)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(f"### Auction outcomes\n\n{line}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
