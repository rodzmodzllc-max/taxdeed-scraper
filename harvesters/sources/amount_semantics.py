"""What an AVAILABLE money figure IS, whether it is current, and how a
current statement is read.

Mirrored by ``amountSemanticType()`` / ``amountTemporal()`` in
``public/app.js``; ``tests/python/fixtures/amount_semantics_cases.json`` pins
both. The display labels stay in ``amountInfo()`` and the financial position
(PR #100); this module adds the semantic type and the time status.

Semantic types (the source's own meaning, never collapsed into "price"):
OPENING_BID, MINIMUM_BID, CURRENT_PURCHASE_PRICE, CURRENT_AMOUNT_DUE,
APPLICATION_FEE, DEPOSIT, TAX_AMOUNT, INTEREST_AMOUNT, PENALTY_AMOUNT,
DEED_FEE, RECORDING_FEE, OTHER_PUBLISHED_AMOUNT.

Time status of the row's figure:

- ``CURRENT``: a statement inside its valid-through date, or a figure on the
  source's own list read in the last ``FRESH_DAYS`` days from a list that is
  not older than ``LIST_STALE_DAYS``.
- ``EXPIRED``: a statement past its valid-through date. Never shown as current.
- ``HISTORICAL``: an original / superseded figure (ORIGINAL_OPENING_BID), or
  a figure on a row that is no longer listed.
- ``UNKNOWN``: the list was not read recently, or the list itself is dated
  beyond ``LIST_STALE_DAYS``.

An assessed / market / taxable value is never an amount here. A tax figure
only comes from a statement that prints it.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta

SEMANTIC_TYPES = ("OPENING_BID", "MINIMUM_BID", "CURRENT_PURCHASE_PRICE", "CURRENT_AMOUNT_DUE", "APPLICATION_FEE",
                  "DEPOSIT", "TAX_AMOUNT", "INTEREST_AMOUNT", "PENALTY_AMOUNT", "DEED_FEE", "RECORDING_FEE",
                  "OTHER_PUBLISHED_AMOUNT")
SEMANTIC_LABELS = {
    "OPENING_BID": "Opening bid", "MINIMUM_BID": "Minimum bid", "CURRENT_PURCHASE_PRICE": "Current purchase price",
    "CURRENT_AMOUNT_DUE": "Current amount due", "APPLICATION_FEE": "Application fee", "DEPOSIT": "Deposit",
    "TAX_AMOUNT": "Taxes", "INTEREST_AMOUNT": "Interest", "PENALTY_AMOUNT": "Penalties", "DEED_FEE": "Deed fee",
    "RECORDING_FEE": "Recording fee", "OTHER_PUBLISHED_AMOUNT": "Other published amount",
}
TEMPORAL = ("CURRENT", "HISTORICAL", "EXPIRED", "UNKNOWN")
TEMPORAL_LABELS = {"CURRENT": "Current", "HISTORICAL": "Historical", "EXPIRED": "Expired - request a current statement",
                   "UNKNOWN": "Currency not established"}
FRESH_DAYS = 14
LIST_STALE_DAYS = 365

# purchase_amount_kind -> semantic type. A minimum-named source column turns
# an OPENING_BID into a MINIMUM_BID (Horry 'MINIMUM BID', Fayette 'Min. Bid',
# Ramsey 'MinimumBid'), never into a price.
KIND_SEMANTIC = {
    "OPENING_BID": "OPENING_BID", "ORIGINAL_OPENING_BID": "OPENING_BID", "MINIMUM_PURCHASE_AMOUNT": "MINIMUM_BID",
    "FIXED_PURCHASE_PRICE": "CURRENT_PURCHASE_PRICE", "ESTIMATED_PURCHASE_PRICE": "OTHER_PUBLISHED_AMOUNT",
    "PUBLISHED_AMOUNT_KIND_UNSPECIFIED": "OTHER_PUBLISHED_AMOUNT",
}
# A source whose OWN field is a minimum bid, stored without an amount kind.
MINIMUM_BID_SOURCES = ("tx_lgbs",)
CLOSED = ("closed", "sold", "gone", "expired", "redeemed", "cancelled", "canceled", "withdrawn")


def _num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None


def _day(v) -> date | None:
    if not v:
        return None
    try:
        return datetime.fromisoformat(str(v)[:10]).date()
    except ValueError:
        return None


def _column(row: dict) -> str:
    op = row.get("otc_provenance") if isinstance(row.get("otc_provenance"), dict) else {}
    m = re.search(r"(?:column|attribute) '([^']+)'", str(op.get("amount") or ""))
    return m.group(1) if m else ""


def _statement(row: dict) -> dict | None:
    op = row.get("otc_provenance") if isinstance(row.get("otc_provenance"), dict) else {}
    st = op.get("purchase_statement")
    if isinstance(st, dict) and (_num(st.get("total_due")) or 0) > 0:
        return st
    return None


def row_amount(row: dict) -> float | None:
    for k in ("purchase_amount", "bid"):
        v = _num(row.get(k))
        if v is not None and v > 0:
            return v
    return None


def semantic_type(row: dict) -> str | None:
    """The semantic type of the row's headline figure, or None (no figure)."""
    if _statement(row):
        return "CURRENT_AMOUNT_DUE"
    kind = row.get("purchase_amount_kind")
    if kind in ("NOT_PUBLISHED", "QUOTED_ON_APPLICATION") or row_amount(row) is None:
        return None
    sid = row.get("source_id") or row.get("harvester_source") or ""
    if not kind:
        return "MINIMUM_BID" if sid in MINIMUM_BID_SOURCES else "OTHER_PUBLISHED_AMOUNT"
    sem = KIND_SEMANTIC.get(kind, "OTHER_PUBLISHED_AMOUNT")
    if sem == "OPENING_BID" and re.search(r"min", _column(row), re.I):
        sem = "MINIMUM_BID"
    return sem


def temporal_status(row: dict, today: date | None = None) -> tuple[str, str]:
    """(status, reason). See the module docstring."""
    today = today or date.today()
    st = _statement(row)
    if st:
        through = _day(st.get("valid_through"))
        if through and through < today:
            return "EXPIRED", f"statement valid through {through.isoformat()}"
        return "CURRENT", (f"statement valid through {through.isoformat()}" if through else "statement with no valid-through date")
    if semantic_type(row) is None:
        return "UNKNOWN", "no figure published"
    if str(row.get("status") or "active").lower() in CLOSED:
        return "HISTORICAL", "the record is no longer listed"
    if row.get("purchase_amount_kind") == "ORIGINAL_OPENING_BID":
        return "HISTORICAL", "the original opening bid, superseded"
    seen = _day(row.get("last_seen_at"))
    if not seen or (today - seen) > timedelta(days=FRESH_DAYS):
        return "UNKNOWN", "the source list was not read recently"
    listed = _day(row.get("list_as_of"))
    if listed and (today - listed) > timedelta(days=LIST_STALE_DAYS):
        return "UNKNOWN", f"the source list is dated {listed.isoformat()}"
    return "CURRENT", f"as published on the source list read {seen.isoformat()}"


def money_record(row: dict, today: date | None = None) -> dict | None:
    """The provenance record of the row's headline figure (None without one)."""
    sem = semantic_type(row)
    if sem is None:
        return None
    st = _statement(row)
    status, reason = temporal_status(row, today)
    return {
        "amount": float(st["total_due"]) if st else row_amount(row), "currency": "USD", "semantic_type": sem,
        "temporal": status, "temporal_reason": reason,
        "source": (st or {}).get("publisher") or row.get("source_id") or row.get("harvester_source") or "",
        "source_url": (st or {}).get("document_url") or row.get("document_url") or row.get("list_url") or "",
        "source_date": (st or {}).get("statement_date") or row.get("list_as_of") or row.get("source_published_at") or "",
        "valid_through": (st or {}).get("valid_through") or "",
        "last_read": (st or {}).get("observed_on") or row.get("last_seen_at") or "",
        "direct": True,
    }


# ---- current statements (text from a PDF or an OCR pass) -----------------

# A money token must start a token: "1,2O4.56" (an OCR letter O) must not
# yield "4.56".
_MONEY = re.compile(r"(?<![\w,.])\$?\s*(\d{1,3}(?:,\d{3})*|\d+)\.(\d{2})(?![\d\w])")
_DATE = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})")
TOTAL_LABELS = ("total amount due", "total due", "amount due", "total to purchase", "payoff amount")
THROUGH_LABELS = ("good through", "good thru", "valid through", "valid thru", "good until")
COMPONENT_LABELS = {
    "delinquent taxes": "delinquent_taxes", "current taxes": "current_taxes", "omitted taxes": "omitted_taxes",
    "subsequent taxes": "subsequent_taxes", "taxes": "taxes", "interest": "interest", "penalties": "penalties",
    "penalty": "penalty", "recording fees": "recording_fees", "recording fee": "recording_fees",
    "documentary stamp": "doc_stamps", "doc stamps": "doc_stamps", "clerk fees": "clerk_fees", "clerk fee": "clerk_fees",
    "deed fee": "deed_fees", "opening bid": "opening_bid",
}
STATEMENT_STATUSES = ("COMPLETE", "NEEDS_REVIEW", "FAILED")


def _money_on(line: str) -> list[float]:
    return [float(a.replace(",", "") + "." + c) for a, c in _MONEY.findall(line)]


def parse_statement_text(text: str, *, rights_status: str, document_url: str, publisher: str,
                         observed_on: str, today: date | None = None) -> dict:
    """Read a purchase statement's TEXT into the otc_provenance.purchase_statement
    shape, with validation:

    - exactly one total: two different totals are NEEDS_REVIEW, none is FAILED;
    - each amount must be a well-formed money value. An OCR-garbled figure
      ("1,2O4.56") is not read as a number;
    - when two or more components are printed, they must reconcile with the
      total to the cent, otherwise NEEDS_REVIEW (the components are never
      added to MAKE a total);
    - a document whose reuse is not cleared (rights_status != PERMITTED) is
      for internal verification only: displayable False, NEEDS_REVIEW.

    Returns {"status", "reasons", "displayable", "statement"}."""
    today = today or date.today()
    reasons: list[str] = []
    totals, through, comps = [], None, {}
    for raw in (text or "").splitlines():
        line = raw.strip()
        low = line.lower()
        if any(lbl in low for lbl in THROUGH_LABELS):
            m = _DATE.search(line)
            if m:
                through = date(int(m.group(3)), int(m.group(1)), int(m.group(2))).isoformat()
            continue
        if any(lbl in low for lbl in TOTAL_LABELS):
            vals = _money_on(line)
            if vals:
                totals.append(vals[-1])
            elif re.search(r"\d", line):
                reasons.append("a total line carries a figure that is not a well-formed amount")
            continue
        for lbl, key in COMPONENT_LABELS.items():
            if low.startswith(lbl):
                vals = _money_on(line)
                if vals:
                    comps[key] = round(comps.get(key, 0.0) + vals[-1], 2)
                elif re.search(r"\d", line):
                    reasons.append(f"the {lbl} line carries a figure that is not a well-formed amount")
                break
    distinct = sorted(set(totals))
    if not distinct:
        return {"status": "FAILED", "reasons": reasons + ["no total found"], "displayable": False, "statement": None}
    if len(distinct) > 1:
        return {"status": "NEEDS_REVIEW", "reasons": reasons + ["two different totals"], "displayable": False, "statement": None}
    total = distinct[0]
    if len(comps) >= 2 and abs(round(sum(comps.values()), 2) - total) > 0.005:
        reasons.append("the printed components do not reconcile with the total")
    if rights_status != "PERMITTED":
        reasons.append("reuse of this document is not established - internal verification only")
    statement = {"total_due": total, "valid_through": through or "", "document_url": document_url,
                 "observed_on": observed_on, "publisher": publisher, "components": comps}
    status = "COMPLETE" if not reasons else "NEEDS_REVIEW"
    expired = bool(through) and through < today.isoformat()
    return {"status": status, "reasons": reasons, "displayable": status == "COMPLETE",
            "statement": statement, "expired": expired}
