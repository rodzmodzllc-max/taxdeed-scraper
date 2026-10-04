"""Research screen (screening-v1): the Python mirror of public/screening.js.

The two implementations are pinned to the same answers by
tests/python/fixtures/screening_cases.json (tests/python/test_investor_screening.py
runs the vectors through both). Change them together and bump
SCREENING_VERSION. Rationale and thresholds: docs/investor-screening.md.

Screening classifies; it never deletes, closes, hides or rewrites a row.
"""
from .rules import (  # noqa: F401
    BUY_BOX_DEFAULTS,
    CLASSIFICATIONS,
    DEFAULT_DISCOVERY,
    REASON_LABELS,
    SCREENED_SOURCES,
    SCREENING_DEFAULTS,
    SCREENING_VERSION,
    acreage_of,
    amount_of,
    has_parcel_id,
    has_property_class,
    key_reasons,
    occupancy_of,
    passes_buy_box,
    screen_property,
    value_of,
)
