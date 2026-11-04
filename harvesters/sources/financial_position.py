"""The financial position of one AVAILABLE record, by source semantics.

This is the single rule for what a customer is told about money on an
Available property. ``public/app.js`` ``financialPositionCore()`` is the same
function in JavaScript; ``tests/python/fixtures/financial_position_cases.json``
pins both to the same answers.

The input is already normalized: the amount description (the app's
``amountInfo()`` state, label, value and display), the source's terms row
(``data/available_financial_terms.csv``) and the clerk's statement, if one is
stored. The output separates the money into groups and NEVER adds numbers
unless the source itself published the total:

- ``acquisition``: the current acquisition amount. It is authoritative only
  when it is the source's current official total (a clerk statement inside
  its valid-through date). Otherwise it is the figure the source published,
  with its own label: an opening bid stays an opening bid.
- ``taxes``, ``interest``, ``fees``, ``other``: each line is one of these.
  - ``published``: an amount the source printed for this record.
  - ``included``: an amount, or a named item, that the source says is
    already inside the figure or total. Never added again.
  - ``added_not_published``: an item the source says is added on top, with
    no amount on file.
- ``application_costs`` / ``deposit``: always separate, never added to a
  price, with the source's own statement of whether they are in it.
- ``total``: the source's own current total, or nothing. A total is never
  computed from parts. Without one, the record says how to obtain it.

No tax amount is ever derived from a value (assessed / market / taxable). A
value is not an obligation.
"""
from __future__ import annotations

# The statement / addition keys, grouped. A key not named here is "other".
TAX_KEYS = ("omitted_taxes", "taxes", "delinquent_taxes", "current_taxes", "subsequent_taxes")
INTEREST_KEYS = ("interest", "penalties", "penalty")
FEE_KEYS = ("doc_stamps", "recording_fees", "clerk_fees", "fees", "deed_fees")
GROUPS = ("taxes", "interest", "fees", "other")

LABELS = {
    "omitted_taxes": "Taxes that came due after the listed figure was set",
    "taxes": "Taxes",
    "delinquent_taxes": "Delinquent taxes",
    "current_taxes": "Current-year taxes",
    "subsequent_taxes": "Subsequent years' taxes",
    "interest": "Interest",
    "penalties": "Penalties",
    "penalty": "Penalty",
    "doc_stamps": "Documentary stamp tax on the deed",
    "recording_fees": "Recording fees",
    "clerk_fees": "Clerk fees",
    "fees": "Fees",
    "deed_fees": "Deed fees",
}

# Bases whose listed figure is a starting amount the source adds items to.
ADDING_BASES = ("OPENING_BID_PLUS_ADDITIONS", "BASE_PRICE_PLUS_ADDITIONS")


def group_of(key: str) -> str:
    if key in TAX_KEYS:
        return "taxes"
    if key in INTEREST_KEYS:
        return "interest"
    if key in FEE_KEYS:
        return "fees"
    return "other"


def label_of(key: str) -> str:
    return LABELS.get(key) or key.replace("_", " ").capitalize()


def _num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None  # NaN guard


def _round(v: float) -> float:
    return round(v + 0.0, 2)


def position(amount: dict, terms: dict | None = None, statement: dict | None = None) -> dict:
    """The financial position. Pure; see the module docstring for the rules."""
    amount = amount or {}
    terms = terms or {}
    statement = statement or None
    groups = {g: [] for g in GROUPS}

    st_current = bool(statement and not statement.get("expired") and _num(statement.get("total")) is not None)
    st_expired = bool(statement and statement.get("expired"))
    value = _num(amount.get("value"))

    # 1. The acquisition amount.
    if st_current:
        acquisition = {"label": "Official total due", "value": _num(statement["total"]), "display": None,
                       "authoritative": True, "basis": "official_statement"}
    elif st_expired:
        acquisition = {"label": "Total due", "value": None, "display": "Expired - request a current statement",
                       "authoritative": False, "basis": "expired_statement"}
    else:
        acquisition = {"label": amount.get("label") or "Price", "value": value,
                       "display": None if value is not None else (amount.get("display") or "Not published"),
                       "authoritative": amount.get("state") == "price" and value is not None,
                       "basis": amount.get("state") or "not_published"}

    # 2. Statement components: inside the statement's total, never added.
    comps = (statement or {}).get("components") or {}
    if statement:
        for key in sorted(comps):
            amt = _num(comps[key])
            if amt is None:
                continue
            groups[group_of(key)].append({"key": key, "label": label_of(key), "amount": _round(amt),
                                          "status": "included" if st_current else "expired_statement"})

    # 3. Items the source adds on top of a starting figure - named, never
    #    priced unless a CURRENT statement printed them (handled above).
    adds = terms.get("additions") or []
    if isinstance(adds, str):
        adds = [a for a in adds.split("|") if a]
    if terms.get("basis") in ADDING_BASES and not st_current:
        for key in adds:
            if any(line["key"] == key for line in groups[group_of(key)]):
                continue
            groups[group_of(key)].append({"key": key, "label": label_of(key), "amount": None,
                                          "status": "added_not_published"})
        if terms.get("included_in_figure"):
            groups["taxes"].insert(0, {"key": "included_in_figure", "label": "Already inside the listed figure",
                                       "amount": None, "status": "included",
                                       "note": terms["included_in_figure"]})

    # 4. Known tax obligation: only amounts a current statement printed.
    tax_lines = [l for l in groups["taxes"] + groups["interest"] if l["amount"] is not None and l["status"] == "included"]
    known_tax = _round(sum(l["amount"] for l in tax_lines)) if tax_lines else None

    # 5. The total: the source's own, or none.
    if st_current:
        total = {"amount": _num(statement["total"]), "basis": "official_statement",
                 "note": "The official total published by the source. Its parts are shown as included, never added again."}
    else:
        total = {"amount": None, "basis": "none",
                 "note": terms.get("official_total") or "The source publishes no total for this record."}

    def side(text_key, in_key):
        text = terms.get(text_key) or ""
        if not text:
            return None
        flag = terms.get(in_key) or "unknown"
        return {"text": text, "in_price": flag if flag in ("yes", "no") else "unknown"}

    return {
        "acquisition": acquisition,
        "taxes": groups["taxes"], "interest": groups["interest"], "fees": groups["fees"], "other": groups["other"],
        "known_tax_obligation": known_tax,
        "application_costs": side("application_costs", "application_costs_in_price"),
        "deposit": side("deposit", "deposit_in_price"),
        "total": total,
    }
