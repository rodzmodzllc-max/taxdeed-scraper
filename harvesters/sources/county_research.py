"""County research status: how far the evidence for one county goes.

One ladder per (state, county), each step decided only from records that
exist - never from the fact that rows are on file, and never a score:

1. ``DISCOVERED`` - a source, candidate page or recorded finding names the
   county.
2. ``SOURCE_VERIFIED`` - at least one source for the county is
   production-verified and not blocked.
3. ``INVENTORY_VERIFIED`` - those production sources have a recorded complete
   read (COMPLETE or EMPTY). Some but not all is PARTIAL; a source that could
   not be read at its last attempt is named in the reason.
4. ``ACQUISITION_PATH_VERIFIED`` - every Available unit of the county has a
   VERIFIED acquisition-evidence status, and an Auctions ledger has a verified
   county sale process. NOT_APPLICABLE when the county has neither ledger.
5. ``PROPERTY_DATA_VERIFIED`` - every row on file carries a parcel identifier
   AND authoritative coordinates (harvesters/sources/coordinates.py). A row
   with a populated value of unknown origin does not count.
6. ``OUTCOME_DATA_VERIFIED`` - every past auction on file has an outcome the
   source itself published (a reviewed wording). NOT_APPLICABLE without a past
   auction on file.

Each step is VERIFIED / PARTIAL / NOT_VERIFIED / NOT_APPLICABLE. ``reached``
is the last step such that it and every step before it is VERIFIED or
NOT_APPLICABLE - so a county is never shown as researched further than its
weakest earlier step.

``public/app.js`` ``countyResearchStatus()`` is the same function;
``tests/python/fixtures/county_research_cases.json`` pins both.
"""
from __future__ import annotations

STEPS = ("DISCOVERED", "SOURCE_VERIFIED", "INVENTORY_VERIFIED", "ACQUISITION_PATH_VERIFIED",
         "PROPERTY_DATA_VERIFIED", "OUTCOME_DATA_VERIFIED")
STEP_LABELS = {
    "DISCOVERED": "Discovered",
    "SOURCE_VERIFIED": "Source verified",
    "INVENTORY_VERIFIED": "Inventory verified",
    "ACQUISITION_PATH_VERIFIED": "Acquisition path verified",
    "PROPERTY_DATA_VERIFIED": "Property data verified",
    "OUTCOME_DATA_VERIFIED": "Outcome data verified",
}
STATES = ("VERIFIED", "PARTIAL", "NOT_VERIFIED", "NOT_APPLICABLE")

FACT_KEYS = ("known", "production_sources", "sources_read", "sources_unavailable", "available_units",
             "available_units_verified", "auction_ledger", "auction_process_verified", "rows", "rows_property_ok",
             "past_auctions", "past_auctions_outcome")


def _n(facts: dict, key: str) -> int:
    v = facts.get(key) or 0
    return int(v) if not isinstance(v, bool) else int(v)


def _ratio(done: int, total: int) -> str:
    if total <= 0:
        return "NOT_APPLICABLE"
    if done >= total:
        return "VERIFIED"
    return "PARTIAL" if done > 0 else "NOT_VERIFIED"


def research_status(facts: dict) -> dict:
    """{"steps": [{"step", "state", "reason"}], "reached": step or None}."""
    steps = []
    known = bool(facts.get("known"))
    steps.append(("DISCOVERED", "VERIFIED" if known else "NOT_VERIFIED",
                  "A source or research record names this county" if known else "No source, candidate page or finding is recorded"))

    prod = _n(facts, "production_sources")
    steps.append(("SOURCE_VERIFIED", "VERIFIED" if prod else "NOT_VERIFIED",
                  f"{prod} production-verified source(s)" if prod else "No production-verified source"))

    read, unavailable = _n(facts, "sources_read"), _n(facts, "sources_unavailable")
    if not prod:
        inv, why = "NOT_VERIFIED", "No production source to read"
    else:
        inv = _ratio(read, prod)
        why = f"{min(read, prod)} of {prod} source(s) with a recorded complete read"
        if unavailable:
            why += f"; {unavailable} could not be read at the last attempt"
    steps.append(("INVENTORY_VERIFIED", inv, why))

    units = _n(facts, "available_units") + (1 if facts.get("auction_ledger") else 0)
    done = _n(facts, "available_units_verified") + (1 if facts.get("auction_ledger") and facts.get("auction_process_verified") else 0)
    acq = _ratio(done, units)
    steps.append(("ACQUISITION_PATH_VERIFIED", acq,
                  "No Available or Auctions ledger here" if acq == "NOT_APPLICABLE" else f"{min(done, units)} of {units} acquisition / sale process(es) verified from an official page"))

    rows, ok = _n(facts, "rows"), _n(facts, "rows_property_ok")
    prop = _ratio(ok, rows)
    steps.append(("PROPERTY_DATA_VERIFIED", prop,
                  "No property on file" if prop == "NOT_APPLICABLE" else f"{min(ok, rows)} of {rows} on file with a parcel identifier and authoritative coordinates"))

    past, out = _n(facts, "past_auctions"), _n(facts, "past_auctions_outcome")
    oc = _ratio(out, past)
    steps.append(("OUTCOME_DATA_VERIFIED", oc,
                  "No past auction on file" if oc == "NOT_APPLICABLE" else f"{min(out, past)} of {past} past auction(s) with an outcome published by the source"))

    reached = None
    for name, st, _ in steps:
        if st in ("VERIFIED", "NOT_APPLICABLE"):
            if st == "VERIFIED":
                reached = name
            continue
        break
    return {"steps": [{"step": n, "state": s, "reason": r} for n, s, r in steps], "reached": reached}


def label(reached: str | None) -> str:
    return STEP_LABELS[reached] if reached else "Not yet researched"
