"""Record-quality invariants and per-county benchmark metrics.

Pure functions over ``properties`` rows as ``get_properties()`` returns them
(or a read-only export of the same columns). Nothing here reads a network,
writes a database or fills a value in: a check either finds a violation in
the row as stored or it does not.

Invariants (each violation names its code; ``INVARIANTS`` is the list):

- ``DUPLICATE_IDENTITY``: two rows share the sync's own identity
  ``(state, source, county, case_no)``.
- ``LEDGER_MISMATCH``: ``source`` and ``ledger_type`` disagree
  (auction -> auctions, laft -> buy, certificate -> lien).
- ``STATUS_OUTSIDE_LEDGER``: ``inventory_status`` is not a status its own
  ledger may carry (harvesters.ledgers.LEDGER_STATUSES).
- ``RESULT_WITHOUT_PUBLISHED_BASIS``: a result status (sold, redeemed, ...)
  whose basis is not the source's own published wording - absence from a
  feed is never a result.
- ``RESULT_AMOUNT_WITHOUT_RESULT``: a result amount on a row whose status is
  not a published result (an opening bid is never a winning bid).
- ``QUOTE_WITH_AMOUNT``: ``purchase_amount_kind`` says the price is quoted on
  application, yet an amount is stored.
- ``ACTIVE_BUT_DELISTED``: ``status`` is active while ``delisted_at`` is set.
- ``SEEN_ORDER``: ``last_seen_at`` earlier than ``first_seen_at``.
- ``IMPLAUSIBLE_IDENTIFIER``: a stored parcel / case number with no digit or
  longer than 60 characters (list text stored as an identifier).
- ``CERTIFICATE_WITHOUT_IDENTITY``: a certificate row with neither a
  certificate number nor an account number.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone

from harvesters.governance.inventory_status import RESULT_STATUSES
from harvesters.ledgers import LEDGER_STATUSES, LEDGER_BY_SOURCE

INVARIANTS = (
    "DUPLICATE_IDENTITY", "LEDGER_MISMATCH", "STATUS_OUTSIDE_LEDGER", "RESULT_WITHOUT_PUBLISHED_BASIS",
    "RESULT_AMOUNT_WITHOUT_RESULT", "QUOTE_WITH_AMOUNT", "ACTIVE_BUT_DELISTED", "SEEN_ORDER",
    "IMPLAUSIBLE_IDENTIFIER", "CERTIFICATE_WITHOUT_IDENTITY",
)
PUBLISHED_BASIS = "SOURCE_STATUS"
FRESH_HOURS = 36           # the same window unit_freshness / the frontend use
ACTIVE_STATUSES = frozenset({"active", "available", "available_otc", "scheduled"})


def _num(v):
    try:
        return None if v is None or v == "" else float(v)
    except (TypeError, ValueError):
        return None


def _ts(v):
    if not v:
        return None
    try:
        s = str(v).replace("Z", "+00:00")
        d = datetime.fromisoformat(s if "T" in s or " " in s else s + "T00:00:00+00:00")
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def identity_key(row: dict) -> tuple:
    return (row.get("state") or "", row.get("source") or "", row.get("county") or "", str(row.get("case_no") or ""))


def plausible_identifier(value) -> bool:
    s = str(value or "").strip()
    return bool(s) and any(c.isdigit() for c in s) and len(s) <= 60 and "\n" not in s


def row_violations(row: dict) -> list[str]:
    out = []
    ledger = LEDGER_BY_SOURCE.get(row.get("source"))
    lt = row.get("ledger_type")
    if ledger and lt and lt != ledger.ledger_type:
        out.append("LEDGER_MISMATCH")
    inv = row.get("inventory_status")
    if ledger and inv and inv not in LEDGER_STATUSES[ledger]:
        out.append("STATUS_OUTSIDE_LEDGER")
    if inv in RESULT_STATUSES and row.get("inventory_status_basis") != PUBLISHED_BASIS:
        out.append("RESULT_WITHOUT_PUBLISHED_BASIS")
    if _num(row.get("result_amount")) is not None and inv not in RESULT_STATUSES:
        out.append("RESULT_AMOUNT_WITHOUT_RESULT")
    if row.get("purchase_amount_kind") == "QUOTED_ON_APPLICATION" and _num(row.get("purchase_amount")) is not None:
        out.append("QUOTE_WITH_AMOUNT")
    if row.get("status") in ACTIVE_STATUSES and row.get("delisted_at"):
        out.append("ACTIVE_BUT_DELISTED")
    first, last = _ts(row.get("first_seen_at")), _ts(row.get("last_seen_at"))
    if first and last and last < first:
        out.append("SEEN_ORDER")
    for col in ("parcel", "case_no"):
        if row.get(col) not in (None, "") and not plausible_identifier(row.get(col)):
            out.append("IMPLAUSIBLE_IDENTIFIER")
            break
    if row.get("source") == "certificate" and not (row.get("certificate_no") or row.get("case_no")):
        out.append("CERTIFICATE_WITHOUT_IDENTITY")
    return out


def check(rows: list[dict]) -> dict:
    """{code: count} over all rows, duplicates included."""
    counts = Counter()
    ids = Counter(identity_key(r) for r in rows)
    counts["DUPLICATE_IDENTITY"] = sum(n - 1 for n in ids.values() if n > 1)
    for r in rows:
        counts.update(row_violations(r))
    return {code: counts.get(code, 0) for code in INVARIANTS}


# ---- benchmark metrics -----------------------------------------------------

def _is_active(row: dict) -> bool:
    return (row.get("status") or "active") in ACTIVE_STATUSES and not row.get("delisted_at")


def has_source_link(row: dict) -> bool:
    url = str(row.get("url_auction") or "")
    return url.startswith("https://")


def has_published_amount(row: dict) -> bool:
    """A figure the source published, with its kind respected: a quote on
    application is not an amount; the legacy 0 bid sentinel is not one."""
    if row.get("purchase_amount_kind") == "QUOTED_ON_APPLICATION":
        return False
    if _num(row.get("purchase_amount")) not in (None, 0.0):
        return True
    bid = _num(row.get("min_bid") if row.get("min_bid") is not None else row.get("bid"))
    return bid is not None and bid > 0


def has_relevant_date(row: dict) -> bool:
    src = row.get("source")
    if src == "auction":
        return bool(row.get("sale_date"))
    if src == "laft":
        return bool(row.get("list_as_of") or row.get("source_published_at") or row.get("available_date"))
    return bool(row.get("issued_date") or row.get("sale_date") or row.get("tax_year"))


def has_acquisition_path(row: dict) -> bool:
    src = row.get("source")
    if src == "laft":
        return bool(row.get("purchase_path_type"))
    return has_source_link(row)


def is_fresh(row: dict, now: datetime) -> bool:
    seen = _ts(row.get("last_seen_at"))
    return bool(seen) and (now - seen).total_seconds() <= FRESH_HOURS * 3600


METRICS = ("active", "source_link", "parcel", "dated", "published_amount", "fresh", "acquisition_path")


def county_metrics(rows: list[dict], now: datetime) -> list[dict]:
    """One row per (state, county, ledger) with counts of active records and
    the invariant violations found among ALL its rows."""
    groups: dict[tuple, list[dict]] = {}
    for r in rows:
        ledger = LEDGER_BY_SOURCE.get(r.get("source"))
        if not ledger:
            continue
        groups.setdefault((r.get("state") or "", r.get("county") or "", ledger.value), []).append(r)
    out = []
    for (state, county, ledger), grp in sorted(groups.items()):
        act = [r for r in grp if _is_active(r)]
        m = {"state": state, "county": county, "ledger": ledger, "rows": len(grp), "active": len(act),
             "source_link": sum(has_source_link(r) for r in act),
             "parcel": sum(plausible_identifier(r.get("parcel")) for r in act),
             "dated": sum(has_relevant_date(r) for r in act),
             "published_amount": sum(has_published_amount(r) for r in act),
             "fresh": sum(is_fresh(r, now) for r in act),
             "acquisition_path": sum(has_acquisition_path(r) for r in act)}
        m["violations"] = {k: v for k, v in check(grp).items() if v}
        out.append(m)
    return out
