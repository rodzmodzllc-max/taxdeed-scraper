"""Enrichment priority: which active records are enriched first, by explicit rules.

There is no score. A record's priority is the FIRST rule below that holds for
it; records are worked in rule order, then by state, county and id, so two
runs over the same rows always visit them in the same order.

  P1  customer-visible AVAILABLE record
  P2  customer-visible AUCTION record
  P3  customer-visible LIEN / CERTIFICATE record
  P4  record in a county with a VERIFIED acquisition path
      (public/acquisition-evidence.json status VERIFIED)
  P5  record in a county listed for market testing
      (data/market_test_counties.csv, when present)
  P6  record with a strong property identity (a parcel / account identifier
      with a digit) that is still missing enrichment
  P7  every other active record

"Customer-visible" is the frontend's own rule: an active record whose
publication_status is NULL (auction / lien sources keep today's behaviour) or
APPROVED / APPROVED_GRANDFATHERED. UNREVIEWED, RESTRICTED and BLOCKED rows are
collected for admins only, so they never outrank a record a customer can see.
Inactive records (closed, dropped, not found) are never enriched.

Standard library only.
"""
from __future__ import annotations

import csv
import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

ACTIVE_STATUSES = frozenset({"active", "available"})
CUSTOMER_PUBLICATION = frozenset({"APPROVED", "APPROVED_GRANDFATHERED"})
LEDGER_OF = {"buy": "AVAILABLE", "laft": "AVAILABLE", "auctions": "AUCTION", "auction": "AUCTION",
             "lien": "LIEN", "certificate": "LIEN"}

RULES = (
    ("P1", "Customer-visible AVAILABLE record"),
    ("P2", "Customer-visible AUCTION record"),
    ("P3", "Customer-visible LIEN / CERTIFICATE record"),
    ("P4", "County with a verified acquisition path"),
    ("P5", "County considered for market testing"),
    ("P6", "Strong property identity, enrichment missing"),
    ("P7", "Remaining active record"),
)
RULE_IDS = tuple(r[0] for r in RULES)
RULE_LABELS = dict(RULES)

# The gaps a record can have, in the order an investor needs them. Each is a
# plain presence test on the row; nothing is inferred.
GAPS = ("coordinates", "parcel", "legal_description", "assessed_value", "taxable_value",
        "acreage", "land_use", "acquisition_evidence", "imagery")


def _blank(v) -> bool:
    return v is None or (isinstance(v, str) and v.strip() == "")


def _num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None


def ledger_of(row: dict) -> str:
    """AVAILABLE / AUCTION / LIEN from ledger_type, else the source column."""
    return LEDGER_OF.get(str(row.get("ledger_type") or "").lower()) or LEDGER_OF.get(str(row.get("source") or "").lower(), "")


def is_active(row: dict) -> bool:
    return str(row.get("status") or "").lower() in ACTIVE_STATUSES


def customer_visible(row: dict) -> bool:
    pub = row.get("publication_status")
    return is_active(row) and (pub is None or pub in CUSTOMER_PUBLICATION)


def strong_identity(row: dict) -> bool:
    """A parcel / account identifier carrying at least one digit (the same
    plausibility the harvesters' identifier gate uses). Texas rows carry the
    appraisal-district account in case_no."""
    for col in ("parcel", "case_no") if str(row.get("state") or "") == "TX" else ("parcel",):
        v = row.get(col)
        if not _blank(v) and re.search(r"\d", str(v)) and len(str(v).strip()) <= 40:
            return True
    return False


def has_coordinates(row: dict) -> bool:
    lat, lng = _num(row.get("latitude")), _num(row.get("longitude"))
    return lat is not None and lng is not None and not (lat == 0 and lng == 0)


def gaps(row: dict) -> list[str]:
    """The enrichment gaps of one record, in GAPS order."""
    out = []
    if not has_coordinates(row):
        out.append("coordinates")
    if _blank(row.get("parcel")):
        out.append("parcel")
    if _blank(row.get("legal_desc")):
        out.append("legal_description")
    if _num(row.get("assessed")) is None and _num(row.get("market")) is None:
        out.append("assessed_value")
    if _num(row.get("taxable_value")) is None:
        out.append("taxable_value")
    if _num(row.get("acreage")) is None and _num(row.get("lot_sqft")) is None:
        out.append("acreage")
    if _blank(row.get("land_use")) and _blank(row.get("dor_use_code")):
        out.append("land_use")
    if ledger_of(row) == "AVAILABLE":
        otc = row.get("otc_provenance") if isinstance(row.get("otc_provenance"), dict) else {}
        if _blank(row.get("purchase_path_type")) and not otc.get("acquisition"):
            out.append("acquisition_evidence")
    if _blank(row.get("photo_url")) and not has_coordinates(row):
        out.append("imagery")
    return out


class Context:
    """The county lists the rules read. Built once per run."""

    def __init__(self, verified_counties=(), market_counties=()):
        self.verified = {(s.upper(), c.strip().lower()) for s, c in verified_counties}
        self.market = {(s.upper(), c.strip().lower()) for s, c in market_counties}

    @classmethod
    def from_repo(cls, repo: Path = REPO) -> "Context":
        return cls(load_verified_counties(repo), load_market_counties(repo))


def load_verified_counties(repo: Path = REPO) -> set[tuple[str, str]]:
    """(state, county) with a VERIFIED acquisition-evidence status."""
    p = repo / "public" / "acquisition-evidence.json"
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    return {(str(s.get("state") or ""), str(s.get("county") or "")) for s in data.get("status") or []
            if s.get("status") == "VERIFIED" and s.get("state") and s.get("county")}


def load_market_counties(repo: Path = REPO) -> set[tuple[str, str]]:
    """(state, county) listed in data/market_test_counties.csv (absent = none)."""
    p = repo / "data" / "market_test_counties.csv"
    if not p.exists():
        return set()
    with p.open(encoding="utf-8", newline="") as fh:
        return {(r["state"].strip(), r["county"].strip()) for r in csv.DictReader(fh)
                if (r.get("state") or "").strip() and (r.get("county") or "").strip()}


def rule_of(row: dict, ctx: Context | None = None) -> str | None:
    """The first rule (P1..P7) that holds, or None for an inactive record."""
    if not is_active(row):
        return None
    ctx = ctx or Context()
    if customer_visible(row):
        ledger = ledger_of(row)
        if ledger == "AVAILABLE":
            return "P1"
        if ledger == "AUCTION":
            return "P2"
        if ledger == "LIEN":
            return "P3"
    key = (str(row.get("state") or "").upper(), str(row.get("county") or "").strip().lower())
    if key in ctx.verified:
        return "P4"
    if key in ctx.market:
        return "P5"
    if strong_identity(row) and gaps(row):
        return "P6"
    return "P7"


def sort_key(row: dict, ctx: Context | None = None) -> tuple:
    rule = rule_of(row, ctx)
    rank = RULE_IDS.index(rule) if rule else len(RULE_IDS)
    return (rank, str(row.get("state") or ""), str(row.get("county") or ""), str(row.get("id") or ""))


def ordered(rows, ctx: Context | None = None) -> list[dict]:
    """Active rows in priority order; inactive rows are dropped."""
    ctx = ctx or Context()
    return sorted((r for r in rows if is_active(r)), key=lambda r: sort_key(r, ctx))


def summary(rows, ctx: Context | None = None) -> dict:
    """Counts per rule (counts only)."""
    ctx = ctx or Context()
    out = {rid: 0 for rid in RULE_IDS}
    for r in rows:
        rule = rule_of(r, ctx)
        if rule:
            out[rule] += 1
    return out
