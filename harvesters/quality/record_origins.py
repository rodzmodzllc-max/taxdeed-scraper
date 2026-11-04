"""Record origins: what each key fact on a property record is based on.

One classification, shared by the property page (``public/app.js``
``recordOriginsFromFacts``) and this module, pinned by
``tests/python/fixtures/record_origin_cases.json``. It answers, per field,
which of these the customer is looking at:

- ``PUBLISHED``: the government source (or the vendor listing it names)
  published the value; it came with the harvested list or a recorded
  provenance entry says so.
- ``ENRICHED``: TAXACQ attached it deterministically from a matched public
  dataset (tax roll / parcel layer by exact identifier, FEMA flood layer at
  the record's point) or from recorded hand research.
- ``INFERRED``: derived by a documented rule, not published as such - an
  address geocode (approximate point), or a status that only reflects the
  record's presence on, or absence from, the source list.
- ``STALE``: published, but the record has not been re-read from the source
  within the freshness window; the value may have changed.
- ``NOT_PUBLISHED``: a field the source list would carry, but it did not.
- ``NOT_AVAILABLE``: a field that only enrichment can supply, not supplied.
- ``NOT_VERIFIED``: a value is present but no origin is recorded for it.

There is no score and no confidence. The input is FACTS, not values: per
field ``{"present": bool, "src": <code>}`` plus ``stale`` for the record.
``src`` codes are a closed vocabulary (``SRC_ORIGIN``); an unknown code is
treated as unrecorded (``NOT_VERIFIED``), never as published.
"""
from __future__ import annotations

STATES = ("PUBLISHED", "ENRICHED", "INFERRED", "STALE", "NOT_PUBLISHED", "NOT_AVAILABLE", "NOT_VERIFIED")
STATE_LABELS = {
    "PUBLISHED": "Published by the source",
    "ENRICHED": "Added from a matched public dataset",
    "INFERRED": "Derived by a documented rule",
    "STALE": "Published - not refreshed recently",
    "NOT_PUBLISHED": "Not published",
    "NOT_AVAILABLE": "Not available",
    "NOT_VERIFIED": "Origin not recorded",
}

# The key facts a customer checks first, in display order.
FIELDS = ("identity", "address", "amount", "date", "status", "value", "coordinates", "flood")
FIELD_LABELS = {
    "identity": "Parcel / record identifier",
    "address": "Property address",
    "amount": "Amount",
    "date": "Sale / list date",
    "status": "Status",
    "value": "Assessed / market value",
    "coordinates": "Map location",
    "flood": "Flood zone",
}
# Fields a source list carries itself; a missing one is "Not published".
# The rest come only from enrichment; a missing one is "Not available".
LIST_NATIVE = frozenset({"identity", "address", "amount", "date", "status"})

SRC_ORIGIN = {
    "list": "PUBLISHED",            # came with the harvested listing
    "county_list": "PUBLISHED",
    "vendor_listing": "PUBLISHED",  # published by the vendor listing the source names
    "source_point": "PUBLISHED",    # the source's own published point
    "result": "PUBLISHED",          # a source-published status / result wording
    "fdor_nal": "ENRICHED",
    "county_gis": "ENRICHED",
    "statewide_parcel": "ENRICHED",
    "parcel_gis": "ENRICHED",
    "fema": "ENRICHED",
    "hand_research": "ENRICHED",
    "geocode": "INFERRED",          # street-address geocode - approximate
    "rule": "INFERRED",             # status from list presence / absence
}
# Origins that age with the record's last read. Enrichment does not: a
# matched tax-roll value is not "refreshed" by re-reading the sale list.
STALE_SENSITIVE = frozenset({"list", "county_list", "vendor_listing", "result"})


def classify_field(field: str, present: bool, src: str, stale: bool) -> str:
    if field not in FIELDS:
        raise ValueError(f"unknown field {field!r}")
    if not present:
        return "NOT_PUBLISHED" if field in LIST_NATIVE else "NOT_AVAILABLE"
    state = SRC_ORIGIN.get(src or "", "NOT_VERIFIED")
    if stale and state == "PUBLISHED" and src in STALE_SENSITIVE:
        return "STALE"
    return state


def classify(facts: dict) -> dict:
    """{field: state} for every field in FIELDS."""
    stale = bool(facts.get("stale"))
    out = {}
    for f in FIELDS:
        fact = facts.get(f) or {}
        out[f] = classify_field(f, bool(fact.get("present")), str(fact.get("src") or ""), stale)
    return out


def summary(states: dict) -> dict:
    """Counts per state - for the benchmark and reports (never a score)."""
    counts = {s: 0 for s in STATES}
    for v in states.values():
        counts[v] = counts.get(v, 0) + 1
    return counts
