"""Texas Comptroller property-classification (SPTB) code lookup.

Mirrors the role scripts/enrich_property_details.py's dor_use_code_str()/
dor_use_to_prop_type() play for Florida's DOR use codes: keep the raw code
(for tx_category, so the frontend can show the state's own exact category -
see schema-v9-dor-use-code.sql for the FL precedent this follows) alongside
a translated, coarser bucket for anywhere the app wants a generic label.

IMPORTANT - verified before writing this module, not assumed: the Texas
Comptroller's own Property Classification Guide
(comptroller.texas.gov/taxes/property-tax/docs/96-313.pdf) documents this
list as the state's *recommended* "State Property Tax Board" (SPTB) code
set, but individual county appraisal districts are NOT required to follow
it exactly - multiple independent sources state plainly that state codes
are not standardized across all counties in Texas. Treat CODE_LABELS below
the same way this project treats FDOR per-county parcel-ID normalization
in enrich_property_details.py: a reasonable statewide default, verified
live against each CAD (HCAD, TAD, DCAD, BCAD, TCAD, ...) before being
trusted for that county, never assumed to transfer unchanged.

This module is descriptive only - it does not determine homestead,
agricultural-use, or mineral-interest status (see tx_yield_calc.py), which
Tex. Tax Code 34.21's redemption-period split actually turns on. A
property's SPTB category is a useful signal (e.g. D1 strongly implies
agricultural use) but is not itself the legal determinant - a CAD's own
exemption/appraisal flags (e.g. a Homestead ("HS") exemption on file) are.
"""

from __future__ import annotations

# Primary codes named in the roadmap request, confirmed against the
# Comptroller's Property Classification Guide and cross-checked against a
# second independent source (TaxNetUSA's SPTB reference) before being
# treated as reliable enough to ship.
CODE_LABELS: dict[str, str] = {
    # A - Real, Residential
    "A": "Real, Residential",
    "A1": "Single-Family Residential",
    "A2": "Real, Residential, Mobile Home",
    # B - Real, Residential (multi-family)
    "B": "Real, Residential (Multi-Family)",
    "B1": "Real, Residential, Multi-Family (2 units)",
    "B2": "Real, Residential, Multi-Family (3-4 units)",
    "B3": "Real, Residential, Multi-Family (5+ units)",
    "B4": "Real, Residential, Multi-Family (Condominium)",
    # C - Vacant lots and land tracts
    "C": "Vacant Lots / Land Tracts",
    "C1": "Vacant Lots / Residential Tracts",
    "C2": "Vacant Lots / Colonia Tracts",
    "C3": "Vacant Lots / Commercial Tracts",
    # D - Qualified agricultural / open-space land
    "D": "Agricultural / Open-Space Land",
    "D1": "Qualified Open-Space / Agricultural Land",
    "D2": "Non-Qualified (Non-Exempt) Agricultural Land / Timberland",
    # E - Farm and ranch improvements
    "E": "Farm & Ranch Improvements",
    "E1": "Real, Farm & Ranch Improved",
    # F - Commercial and industrial
    "F": "Commercial / Industrial Real Property",
    "F1": "Commercial Real Property",
    "F2": "Industrial / Manufacturing Real Property",
    # G - Oil, gas, and other minerals
    "G": "Oil, Gas & Mineral Reserves",
    "G1": "Oil & Gas Reserves",
    "G2": "Other (Non-Oil/Gas) Minerals",
    # J - Utilities
    "J": "Utilities",
    "J1": "Water Systems",
    "J2": "Gas Companies",
    "J3": "Electric Companies",
    "J4": "Telephone Companies",
    "J5": "Railroads",
    "J6": "Pipelines",
    "J7": "Cable Television Companies",
    # L - Commercial / industrial tangible personal property
    "L": "Commercial / Industrial Personal Property",
    "L1": "Commercial Personal Property",
    "L2": "Industrial & Manufacturing Personal Property",
    # M - Mobile, motor, and other tangible personal property
    "M": "Mobile / Other Tangible Personal Property",
    "M1": "Tangible Other Personal, Mobile Homes",
    "M2": "Tangible Other Personal, Travel Trailers",
    "M3": "Tangible Other Personal, Watercraft",
    "M4": "Tangible Other Personal, Aircraft",
    # X - Exempt property
    "X": "Exempt Property",
    "X0": "Exempt Property (Total)",
    "X1": "Exempt - Government-Owned",
}

# The subset of top-level categories that are, on their own, a reasonably
# strong SIGNAL (not proof) of a use-type relevant to the Event Terminal /
# OTC Catalog / Yield Desk views. Do not use this to decide redemption
# period - see the module docstring and tx_yield_calc.py.
RESIDENTIAL_PREFIXES = ("A", "B")
VACANT_PREFIXES = ("C",)
AGRICULTURAL_PREFIXES = ("D", "E")
COMMERCIAL_INDUSTRIAL_PREFIXES = ("F",)


def normalize_category(raw: str | None) -> str | None:
    """Uppercase/trim a raw CAD category string, or None if empty/unusable.

    CADs have been observed (per the per-CAD-variance caution above) to
    return this field with inconsistent casing or stray whitespace; this
    does not attempt any county-specific remapping - that belongs in a
    per-CAD normalization table once real per-CAD samples have been
    collected, the same way enrich_property_details.py's
    normalize_candidates() does for Florida parcel IDs.
    """
    if raw is None:
        return None
    value = raw.strip().upper()
    return value or None


def category_label(raw: str | None) -> str | None:
    """Human-readable label for a raw tx_category value, or None.

    Tries an exact match first (e.g. "A1"), then falls back to the
    single-letter top-level bucket (e.g. "A") if the CAD only reports the
    coarse code or reports a sub-code this module doesn't have a specific
    label for yet - better to show "Commercial / Industrial Real Property"
    than nothing at all for an uncommon sub-code.
    """
    code = normalize_category(raw)
    if code is None:
        return None
    if code in CODE_LABELS:
        return CODE_LABELS[code]
    if code[0] in CODE_LABELS:
        return CODE_LABELS[code[0]]
    return None


def is_probably_agricultural(raw: str | None) -> bool:
    """True if the category code suggests agricultural/open-space use.

    A SIGNAL for the yield calculator's default when a CAD does not
    separately expose an agricultural-use flag - not a substitute for one
    when it's available. See tx_yield_calc.py's docstring for why this
    matters: Tex. Tax Code 34.21's 2-year redemption period turns on
    actual agricultural-use designation, which D1 ("Qualified Open-Space")
    specifically indicates, but D2 ("Non-Qualified") does NOT - so this
    checks the leading digit, not just the leading letter.
    """
    code = normalize_category(raw)
    return code is not None and code.startswith("D1")


def is_probably_vacant(raw: str | None) -> bool:
    """True if the category code suggests unimproved/vacant land.

    Used for the OTC Catalog's existing junk-land filter (<0.10 acre, $0
    improvement value) as an additional signal alongside the acreage/
    improvement-value thresholds already specified for that filter -
    vacant-lot categories are exactly the population that filter targets.
    """
    code = normalize_category(raw)
    return code is not None and code.startswith(VACANT_PREFIXES)
