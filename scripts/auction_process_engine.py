#!/usr/bin/env python3
"""Auction sale-process engine: the ONE place an auction row's "how does
this county's tax sale run" is established from evidence (cross-state
enrichment sprint, 2026-10-02).

This is NOT a purchase path. A purchase path (scripts/purchase_path_engine.py)
answers how to buy a property the county holds; an auction row is offered at
a sale, and what a bidder needs is the county's SALE PROCESS: how and where
the sale runs, whether bidders register (and where / by when), the deposit,
the payment method and deadline, bidder and identification requirements,
the published sale time, and the office to contact. It is always
COUNTY-LEVEL guidance - the county publishes one process for every property
on its sale list - and is stored as such:

    properties.otc_provenance.auction_process = {
        "scope": "county", "method": ..., "steps": [...], "deposit": ..., ...
        "evidence_url": ..., "source_title": ..., "observed_on": ..., "source_id": ...}

Evidence comes from ONE table, data/auction_process_evidence.csv, and every
field in a row is quoted from (or a faithful short form of) the evidence page
a person read in a value-free capture. A blank cell means the page does not
publish it - never a guess, never a typical value from another county. A row
is applied only when enabled, review_state=verified and anchored to an https
evidence page.

Two date fields, kept apart on purpose:
  sale_date + sale_date_applies=yes   the page states the sale date for the
                                      CURRENT sale list; the apply step may
                                      fill a BLANK properties.sale_date with it
                                      (fill-blank, field_provenance recorded);
  next_sale_date                      a FUTURE sale the county announces (e.g.
                                      Albany WY's next sale) - county
                                      information only, never written onto a
                                      row of an earlier list.
An auction time is stored only when the page publishes it.
"""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
EVIDENCE_PATH = REPO / "data" / "auction_process_evidence.csv"

COLUMNS = ["state", "source_id", "county", "method", "platform_url", "registration_required", "registration_url",
           "registration_deadline", "deposit", "payment_methods", "payment_deadline", "bidder_requirements",
           "id_requirement", "sale_location", "sale_time", "sale_date", "sale_date_applies", "next_sale_date",
           "office", "phone", "email", "address", "steps", "instructions_url", "evidence_url", "evidence_type",
           "source_title", "observed_on", "review_state", "enabled", "notes"]
METHODS = ("online", "in_person", "online_and_in_person", "sealed_bid")
METHOD_LABELS = {"online": "Online auction", "in_person": "In-person sale", "online_and_in_person": "Online and in-person sale",
                 "sealed_bid": "Sealed-bid sale"}
EVIDENCE_TYPES = ("county_page", "county_document", "county_faq", "statute", "vendor_page")
REVIEW_STATES = ("verified", "captured", "rejected")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TRUE = {"yes", "true", "1", "y"}
# The record keys a row carries (otc_provenance.auction_process) - the
# frontend's auctionProcessOf() reads the same keys (a test pins them).
RECORD_KEYS = ("scope", "method", "method_label", "platform_url", "registration_required", "registration_url",
               "registration_deadline", "deposit", "payment_methods", "payment_deadline", "bidder_requirements",
               "id_requirement", "sale_location", "sale_time", "sale_date", "next_sale_date", "office", "phone", "email",
               "address", "steps", "instructions_url", "evidence_url", "evidence_type", "source_title", "observed_on",
               "source_id")


@dataclass(frozen=True)
class ProcessRow:
    state: str
    source_id: str
    county: str
    method: str
    evidence_url: str
    observed_on: str
    review_state: str
    enabled: bool
    values: dict = field(default_factory=dict)      # every other published field, blank = not published
    steps: tuple = ()

    @property
    def applicable(self) -> bool:
        return self.enabled and self.review_state == "verified" and self.evidence_url.startswith("https://")

    def matches(self, *, state: str, source_id: str | None, county: str) -> bool:
        return (self.state == state and self.county in (county, "*")
                and (self.source_id == "*" or not source_id or self.source_id == source_id))


def problems(r: ProcessRow) -> list[str]:
    out = []
    if not re.match(r"^[A-Z]{2}$", r.state):
        out.append(f"state {r.state!r}")
    if not r.source_id:
        out.append("source_id required ('*' = every source of the county)")
    if r.method and r.method not in METHODS:
        out.append(f"method {r.method!r}")
    if r.review_state not in REVIEW_STATES:
        out.append(f"review_state {r.review_state!r}")
    v = r.values
    if v.get("evidence_type") and v["evidence_type"] not in EVIDENCE_TYPES:
        out.append(f"evidence_type {v['evidence_type']!r}")
    for k in ("sale_date", "next_sale_date"):
        if v.get(k) and not _DATE.match(v[k]):
            out.append(f"{k} must be YYYY-MM-DD")
    if v.get("sale_date_applies", "").lower() in _TRUE and not v.get("sale_date"):
        out.append("sale_date_applies needs a sale_date")
    for k in ("platform_url", "registration_url", "instructions_url"):
        if v.get(k) and not v[k].startswith("https://"):
            out.append(f"{k} must be https")
    if v.get("email") and "@" not in v["email"]:
        out.append("email is not an address")
    if r.enabled:
        if r.review_state != "verified":
            out.append("an enabled row must be review_state=verified")
        if not r.evidence_url.startswith("https://"):
            out.append("an enabled row needs an https evidence_url")
        if not _DATE.match(r.observed_on or ""):
            out.append("an enabled row needs observed_on (YYYY-MM-DD)")
        if not r.method and not r.steps:
            out.append("an enabled row states at least the method or the published steps")
    return out


def load(path: Path | str = EVIDENCE_PATH) -> list[ProcessRow]:
    p = Path(path)
    if not p.is_file():
        return []
    rows = []
    with open(p, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames != COLUMNS:
            raise ValueError(f"{p.name}: columns must be {COLUMNS}, got {reader.fieldnames}")
        for i, raw in enumerate(reader, 2):
            g = {k: (raw.get(k) or "").strip() for k in COLUMNS}
            row = ProcessRow(state=g["state"], source_id=g["source_id"], county=g["county"] or "*", method=g["method"],
                             evidence_url=g["evidence_url"], observed_on=g["observed_on"], review_state=g["review_state"],
                             enabled=g["enabled"].lower() in _TRUE,
                             values={k: g[k] for k in COLUMNS if k not in ("state", "source_id", "county", "method", "evidence_url",
                                                                         "observed_on", "review_state", "enabled", "steps", "notes")},
                             steps=tuple(s.strip() for s in g["steps"].split("|") if s.strip()))
            errs = problems(row)
            if errs:
                raise ValueError(f"{p.name} line {i}: " + "; ".join(errs))
            rows.append(row)
    return rows


def resolve(rows: list[ProcessRow], *, state: str, source_id: str | None, county: str) -> ProcessRow | None:
    """The applicable row for (state, source, county): a county row wins
    over a state-wide '*' row, a source-specific row over a '*' source."""
    hits = [r for r in rows if r.applicable and r.matches(state=state, source_id=source_id, county=county)]
    if not hits:
        return None
    hits.sort(key=lambda r: (r.county == "*", r.source_id == "*"))
    return hits[0]


def record(r: ProcessRow) -> dict:
    """otc_provenance.auction_process for a row: only published fields."""
    v = r.values
    rec = {"scope": "county", "method": r.method or None, "method_label": METHOD_LABELS.get(r.method),
           "steps": list(r.steps), "evidence_url": r.evidence_url, "observed_on": r.observed_on, "source_id": r.source_id}
    for k in ("platform_url", "registration_url", "registration_deadline", "deposit", "payment_methods", "payment_deadline",
              "bidder_requirements", "id_requirement", "sale_location", "sale_time", "next_sale_date", "office", "phone",
              "email", "address", "instructions_url", "evidence_type", "source_title"):
        if v.get(k):
            rec[k] = v[k]
    req = v.get("registration_required", "").lower()
    if req in ("yes", "no"):
        rec["registration_required"] = req == "yes"
    if v.get("sale_date") and v.get("sale_date_applies", "").lower() in _TRUE:
        rec["sale_date"] = v["sale_date"]
    return {k: val for k, val in rec.items() if val not in (None, "", [])}


def complete(rec: dict | None) -> bool:
    """A bidder can act on it: how the sale runs AND a way to reach the
    office or the sale's own page."""
    if not rec:
        return False
    how = bool(rec.get("method") or rec.get("steps"))
    reach = bool(rec.get("phone") or rec.get("email") or rec.get("address") or rec.get("platform_url") or rec.get("registration_url"))
    return how and reach
