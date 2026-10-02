"""Deterministic saved-search criteria (Customer-value sprint, 2026-10-01).

One vocabulary, two implementations: this module (used by
scripts/detect_property_changes.py to decide which saved searches a newly
listed property matches) and savedSearchMatches() in public/app.js (the
customer's own view of a saved search). tests/python/fixtures/
saved_search_cases.json pins both to the same answers.

No scoring, no ranking, no inference: a property matches when every criterion
the customer set holds on a field the property actually carries. A criterion
on a field the property does not carry does not match (an unknown acreage is
never "at least 1 acre").
"""
from __future__ import annotations

from datetime import date, datetime, timezone

GONE = frozenset({"closed", "expired", "gone", "sold", "redeemed", "cancelled", "canceled"})
URL_TYPES = frozenset({"direct_property_url", "county_instructions", "application_page", "application_download"})
CRITERIA_KEYS = ("ledger", "counties", "acreage_min", "acreage_max", "assessed_min", "assessed_max", "taxable_min",
                 "taxable_max", "bid_min", "bid_max", "sale_from", "sale_to", "available_only", "land_use",
                 "acquisition", "imagery", "fresh_days")


def _num(v):
    try:
        return None if v is None or v == "" else float(v)
    except (TypeError, ValueError):
        return None


def opening_bid(row: dict):
    """The published amount the list states: purchase_amount, else min_bid, else bid (0 = not published)."""
    for k in ("purchase_amount", "min_bid", "bid"):
        n = _num(row.get(k))
        if n is not None and n > 0:
            return n
    return None


def acquisition_verified(row: dict) -> bool:
    t = row.get("purchase_path_type")
    return bool(t) and t != "none_published"


def has_imagery(row: dict) -> bool:
    return bool(row.get("photo_url"))


def _between(v, lo, hi) -> bool:
    if lo is None and hi is None:
        return True
    if v is None:
        return False
    return (lo is None or v >= lo) and (hi is None or v <= hi)


def matches(criteria: dict, row: dict, *, now: datetime | None = None) -> bool:
    c = criteria or {}
    if c.get("ledger") and row.get("source") != c["ledger"]:
        return False
    if c.get("counties") and row.get("county") not in set(c["counties"]):
        return False
    if not _between(_num(row.get("acreage")), _num(c.get("acreage_min")), _num(c.get("acreage_max"))):
        return False
    if not _between(_num(row.get("assessed")), _num(c.get("assessed_min")), _num(c.get("assessed_max"))):
        return False
    if not _between(_num(row.get("taxable_value")), _num(c.get("taxable_min")), _num(c.get("taxable_max"))):
        return False
    if not _between(opening_bid(row), _num(c.get("bid_min")), _num(c.get("bid_max"))):
        return False
    if c.get("sale_from") or c.get("sale_to"):
        sd = str(row.get("sale_date") or "")[:10]
        if not sd or (c.get("sale_from") and sd < c["sale_from"]) or (c.get("sale_to") and sd > c["sale_to"]):
            return False
    if c.get("available_only") and str(row.get("status") or "active").lower() in GONE:
        return False
    if c.get("land_use"):
        lu = " ".join(str(row.get(k) or "") for k in ("land_use", "prop_type")).lower()
        if str(c["land_use"]).lower() not in lu:
            return False
    if c.get("acquisition") == "verified" and not acquisition_verified(row):
        return False
    if c.get("acquisition") == "not_verified" and acquisition_verified(row):
        return False
    if c.get("imagery") == "has" and not has_imagery(row):
        return False
    if c.get("imagery") == "none" and has_imagery(row):
        return False
    if c.get("fresh_days") not in (None, ""):
        seen = row.get("last_seen_at")
        if not seen:
            return False
        try:
            t = datetime.fromisoformat(str(seen).replace("Z", "+00:00"))
        except ValueError:
            return False
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        now = now or datetime.now(timezone.utc)
        if (now - t).total_seconds() > float(c["fresh_days"]) * 86400:
            return False
    return True


def clean_criteria(criteria: dict) -> dict:
    """Only the known keys, empty values dropped - what is stored and compared."""
    out = {}
    for k in CRITERIA_KEYS:
        v = (criteria or {}).get(k)
        if v in (None, "", [], False):
            continue
        out[k] = v
    return out


if __name__ == "__main__":  # pragma: no cover
    print(", ".join(CRITERIA_KEYS), date.today())
