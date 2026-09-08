"""Texas tax-sale statutory redemption math (Tex. Tax Code Sec. 34.21).

INFORMATIONAL ONLY - NOT LEGAL OR FINANCIAL ADVICE. This module computes
figures directly from the current text of Tex. Tax Code Sec. 34.21 as
verified against three independent sources during this module's drafting
(texas.public.law, FindLaw, and Justia's copy of the Texas Statutes), but
statutes change, home-rule cities and specific counties can vary in ways
not captured here, and redemption is a fact-specific legal process. Anyone
relying on these numbers for a real bid should verify current law and
consult a Texas attorney - this module is a research/UI aid, not a
guarantee of any return, and most tax-sale purchases are never redeemed at
all (in which case the purchaser simply keeps the property rather than
receiving any premium).

--- The statute, as verified ---

Sec. 34.21(a): a former owner of HOMESTEAD, AGRICULTURAL-USE, or MINERAL
INTEREST property has TWO YEARS from the date the purchaser's deed is
filed for record to redeem, by paying the purchaser (or, for a taxing-unit
purchase, the taxing unit):
    - the amount the purchaser bid for the property,
    - the deed recording fee,
    - all taxes, penalties, interest, and costs paid on the property, and
    - a REDEMPTION PREMIUM of 25% of that AGGREGATE TOTAL if redeemed in
      the first year, or 50% of the aggregate total if redeemed in the
      second year.

Sec. 34.21(e): for any OTHER property (i.e. not homestead, agricultural-
use, or mineral interest), the former owner has 180 DAYS from the date the
deed is filed for record to redeem, on the same aggregate-total basis, but
the redemption premium payable to a purchaser other than a taxing unit
"may not exceed 25 percent" - flat, no second-tier escalation, because the
whole period is shorter than a year.

Two things worth being precise about, both reflected in the code below:
    1. The premium is calculated on the AGGREGATE TOTAL (bid + recording
       fee + taxes/penalties/interest/costs already paid), not on the bid
       alone. This module accepts an optional `recording_fee` and
       `taxes_penalties_interest_costs` on top of the bid; when the caller
       doesn't have those figures yet (the common case straight off a
       harvester, before any of that has actually been paid), it falls
       back to computing the premium on the bid alone and flags the
       result as a floor, not the true aggregate-based figure - a
       property with real back-taxes/costs will have a HIGHER true
       maximum than a bid-only estimate shows.
    2. 180 days is not 6 calendar months. redemption_period_months (6 or
       24) is a coarse, display-friendly summary; the actual deadline
       computed here always uses exact days (180) or exact years (2), per
       the statute's own wording.

--- What determines which period applies ---

The statute keys off HOMESTEAD, AGRICULTURAL-USE, or MINERAL-INTEREST
status of the property AT THE TIME OF THE TAX SALE - not its Comptroller
SPTB category code alone. A category code (see tx_use_codes.py) is a
useful signal (D1 "Qualified Open-Space" strongly implies agricultural
use) but is not proof: an "A1" single-family property might or might not
carry a homestead exemption, and that has to come from the CAD's own
exemption data (a Homestead/"HS" exemption flag), not be inferred from the
category alone. Callers should pass explicit is_homestead /
is_agricultural / is_mineral_interest flags whenever the CAD enrichment
step has real exemption/use data, and should treat a category-code-only
guess as exactly that - a guess, worth surfacing to the user as
"unconfirmed" rather than presented as certain.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass

SHORT_PERIOD_DAYS = 180
LONG_PERIOD_YEARS = 2

SHORT_PERIOD_PREMIUM = 0.25  # flat, Sec. 34.21(e)
LONG_PERIOD_YEAR1_PREMIUM = 0.25  # Sec. 34.21(a), redeemed in year 1
LONG_PERIOD_YEAR2_PREMIUM = 0.50  # Sec. 34.21(a), redeemed in year 2


@dataclass
class RedemptionTerms:
    is_long_period: bool  # True = homestead/agricultural/mineral, 2-year path
    redemption_period_months: int  # 24 or 6 - coarse/display field
    redemption_expiration_date: _dt.date  # exact deadline
    max_premium_rate: float  # 0.25 or 0.50 - the ceiling rate that applies
    max_statutory_return_usd: float  # aggregate_total * (1 + max_premium_rate)
    aggregate_total_is_estimate: bool  # True if recording fee / T&C costs weren't supplied
    basis: str  # human-readable one-liner for a UI tooltip / audit trail


def classify_redemption_period(
    *,
    is_homestead: bool | None = None,
    is_agricultural: bool | None = None,
    is_mineral_interest: bool | None = None,
    tx_category: str | None = None,
) -> tuple[bool, str]:
    """Decide long (2-yr) vs. short (180-day) redemption period.

    Returns (is_long_period, basis) where `basis` documents which signal
    decided it, so a caller can distinguish a confirmed classification
    from a category-code guess when presenting this to a user.

    Precedence: explicit CAD-sourced flags first (these are the actual
    legal determinants - see the module docstring); tx_category is used
    only as a fallback when none of the three flags is available, and the
    result is labeled as an unconfirmed guess in `basis`.
    """
    if is_homestead:
        return True, "confirmed: CAD homestead exemption on file"
    if is_agricultural:
        return True, "confirmed: CAD agricultural-use designation on file"
    if is_mineral_interest:
        return True, "confirmed: mineral interest"

    if is_homestead is False and is_agricultural is False and is_mineral_interest is False:
        # All three explicitly known and all false - genuinely the short
        # period, not just "we don't know."
        return False, "confirmed: CAD data shows no homestead/agricultural/mineral-interest status"

    # No confirmed CAD flags available - fall back to the category code as
    # an unconfirmed signal. Only D1 (qualified open-space/agricultural)
    # is treated as suggestive here; A1/single-family is deliberately NOT
    # treated as implying homestead, because most single-family CAD
    # records do NOT carry a homestead exemption (rentals, second homes,
    # investor-owned property, and the property that was just tax-sold
    # itself, whose owner may well have lost or never claimed the
    # exemption).
    from tx_use_codes import is_probably_agricultural  # local import avoids a hard dependency for callers that don't need it

    if is_probably_agricultural(tx_category):
        return True, "UNCONFIRMED guess: category code D1 (qualified open-space) suggests agricultural use - verify against the CAD's actual ag-use designation before relying on this"

    return False, "UNCONFIRMED default: no CAD homestead/agricultural/mineral-interest data available - defaulting to the shorter 180-day period as the more conservative (shorter-lockup) assumption, NOT a confirmed classification"


def compute_redemption_terms(
    *,
    sale_or_deed_filed_date: _dt.date,
    bid_usd: float,
    is_homestead: bool | None = None,
    is_agricultural: bool | None = None,
    is_mineral_interest: bool | None = None,
    tx_category: str | None = None,
    recording_fee_usd: float | None = None,
    taxes_penalties_interest_costs_usd: float | None = None,
) -> RedemptionTerms:
    """Compute the full set of statutory redemption terms for one property.

    `sale_or_deed_filed_date` should be the deed-filing date once a
    harvester captures it; until then, the auction/sale date is a
    reasonable proxy but will understate the true deadline by however long
    the deed took to record after the sale - flag this in the caller if
    deed-filing dates aren't yet tracked (see the architectural notes in
    harvesters/texas_harvester.py and enrich_property_details_tx.py).
    """
    is_long, basis = classify_redemption_period(
        is_homestead=is_homestead,
        is_agricultural=is_agricultural,
        is_mineral_interest=is_mineral_interest,
        tx_category=tx_category,
    )

    if is_long:
        redemption_period_months = 24
        expiration = _add_years(sale_or_deed_filed_date, LONG_PERIOD_YEARS)
        max_premium_rate = LONG_PERIOD_YEAR2_PREMIUM
    else:
        redemption_period_months = 6
        expiration = sale_or_deed_filed_date + _dt.timedelta(days=SHORT_PERIOD_DAYS)
        max_premium_rate = SHORT_PERIOD_PREMIUM

    aggregate_total = bid_usd
    is_estimate = True
    if recording_fee_usd is not None:
        aggregate_total += recording_fee_usd
        is_estimate = False
    if taxes_penalties_interest_costs_usd is not None:
        aggregate_total += taxes_penalties_interest_costs_usd
        is_estimate = False

    max_return = round(aggregate_total * (1 + max_premium_rate), 2)

    return RedemptionTerms(
        is_long_period=is_long,
        redemption_period_months=redemption_period_months,
        redemption_expiration_date=expiration,
        max_premium_rate=max_premium_rate,
        max_statutory_return_usd=max_return,
        aggregate_total_is_estimate=is_estimate,
        basis=basis,
    )


def _add_years(date: _dt.date, years: int) -> _dt.date:
    """Add whole calendar years to a date, handling Feb 29 safely."""
    try:
        return date.replace(year=date.year + years)
    except ValueError:
        # Feb 29 on a source date with no Feb 29 `years` later - land on
        # Feb 28, the same convention Python's own dateutil.relativedelta
        # uses, rather than raising.
        return date.replace(month=2, day=28, year=date.year + years)


if __name__ == "__main__":
    # Quick manual sanity check against the worked examples this module
    # was designed around - not a substitute for real unit tests once this
    # is wired into the enrichment pipeline.
    terms = compute_redemption_terms(
        sale_or_deed_filed_date=_dt.date(2026, 1, 15),
        bid_usd=10_000.0,
        is_homestead=True,
    )
    print(terms)
    assert terms.is_long_period is True
    assert terms.redemption_period_months == 24
    assert terms.redemption_expiration_date == _dt.date(2028, 1, 15)
    assert terms.max_statutory_return_usd == 15_000.0  # 10,000 * 1.50

    terms2 = compute_redemption_terms(
        sale_or_deed_filed_date=_dt.date(2026, 1, 15),
        bid_usd=10_000.0,
        is_homestead=False,
        is_agricultural=False,
        is_mineral_interest=False,
    )
    print(terms2)
    assert terms2.is_long_period is False
    assert terms2.redemption_period_months == 6
    assert terms2.redemption_expiration_date == _dt.date(2026, 7, 14)
    assert terms2.max_statutory_return_usd == 12_500.0  # 10,000 * 1.25

    print("OK")
