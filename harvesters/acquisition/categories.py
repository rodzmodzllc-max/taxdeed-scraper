"""Data-category taxonomy - Phase 39 Sections 19 and 27.

One vocabulary for "what kind of information does this source provide",
shared by adapters, the completeness engine, the acquisition maps, and the
county configuration. Deliberately distinct from, and never a replacement
for:

  - `governance.restrictions.Restriction` - what a source forbids.
  - `governance.promotion.PROMOTION_USES` - what this project wants to DO
    with data (INGEST/STORE/CUSTOMER_DISPLAY/...). A category is the noun;
    a promotion use is the verb. `IMAGE`/`DOCUMENT` appear in both
    vocabularies precisely because Section 41 requires binary content to be
    tracked as its own category AND gated as its own use.
  - The free-text column names in `data/fl_county_coverage_matrix.csv` -
    those are per-state discovery columns; `MATRIX_COLUMN_TO_CATEGORY`
    below is the one mapping between them and this taxonomy, so the
    translation happens in exactly one place.
"""

from __future__ import annotations

from enum import Enum


class DataCategory(str, Enum):
    """Section 27's taxonomy, plus the finer Section 19 identity/value
    members the Florida activation plan names explicitly. A source may
    provide several."""

    # Identity and description
    PROPERTY = "PROPERTY"
    PROPERTY_IDENTITY = "PROPERTY_IDENTITY"
    PARCEL_APN = "PARCEL_APN"
    ADDRESS = "ADDRESS"
    LEGAL_DESCRIPTION = "LEGAL_DESCRIPTION"
    PROPERTY_TYPE = "PROPERTY_TYPE"
    PROPERTY_CHARACTERISTICS = "PROPERTY_CHARACTERISTICS"
    ACREAGE = "ACREAGE"

    # Valuation
    ASSESSMENT = "ASSESSMENT"
    ASSESSED_VALUE = "ASSESSED_VALUE"
    MARKET_VALUE = "MARKET_VALUE"
    JUST_VALUE = "JUST_VALUE"
    TAXABLE_VALUE = "TAXABLE_VALUE"

    # Tax
    TAX = "TAX"
    ANNUAL_TAX = "ANNUAL_TAX"
    DELINQUENT_TAX = "DELINQUENT_TAX"
    TAX_CERTIFICATE = "TAX_CERTIFICATE"

    # Sale / auction
    TAX_SALE = "TAX_SALE"
    AUCTION = "AUCTION"
    AUCTION_DATE = "AUCTION_DATE"
    OPENING_BID = "OPENING_BID"
    MINIMUM_BID = "MINIMUM_BID"
    SALE_STATUS = "SALE_STATUS"
    CASE_NUMBER = "CASE_NUMBER"

    # Ownership and records
    OWNERSHIP = "OWNERSHIP"
    RECORDED_RECORDS = "RECORDED_RECORDS"
    RECORDED_TRANSFER = "RECORDED_TRANSFER"
    SALES_HISTORY = "SALES_HISTORY"
    LIEN = "LIEN"
    JUDGMENT = "JUDGMENT"

    # Spatial
    GIS = "GIS"
    PARCEL_GEOMETRY = "PARCEL_GEOMETRY"
    LATITUDE = "LATITUDE"
    LONGITUDE = "LONGITUDE"

    # Binary content - tracked separately on purpose (Section 41)
    IMAGE = "IMAGE"
    DOCUMENT = "DOCUMENT"

    # Derived/secondary
    ENRICHMENT = "ENRICHMENT"


# Binary categories never inherit rights from ordinary structured data
# (Section 41). Callers check membership here rather than string-matching
# category names.
BINARY_CATEGORIES = frozenset({DataCategory.IMAGE, DataCategory.DOCUMENT})


# Section 65's dataset priority, as an explicit ordering the acquisition
# planner can sort by. This is a DATA-FOUNDATION priority (which fields
# make the platform usable at all), never an investment or property
# ranking - Section 66's prohibition.
DATASET_PRIORITY: tuple[tuple[str, tuple[DataCategory, ...]], ...] = (
    (
        "core_identity",
        (DataCategory.PROPERTY_IDENTITY, DataCategory.PARCEL_APN, DataCategory.ADDRESS, DataCategory.LEGAL_DESCRIPTION),
    ),
    (
        "characteristics",
        (DataCategory.PROPERTY_TYPE, DataCategory.ACREAGE, DataCategory.PROPERTY_CHARACTERISTICS),
    ),
    (
        "financial",
        (
            DataCategory.MARKET_VALUE,
            DataCategory.JUST_VALUE,
            DataCategory.ASSESSED_VALUE,
            DataCategory.TAXABLE_VALUE,
            DataCategory.ANNUAL_TAX,
            DataCategory.DELINQUENT_TAX,
        ),
    ),
    (
        "auction",
        (DataCategory.AUCTION_DATE, DataCategory.OPENING_BID, DataCategory.MINIMUM_BID, DataCategory.CASE_NUMBER, DataCategory.SALE_STATUS),
    ),
    (
        "history",
        (DataCategory.SALES_HISTORY, DataCategory.OWNERSHIP, DataCategory.RECORDED_TRANSFER),
    ),
    (
        "location",
        (DataCategory.GIS, DataCategory.LATITUDE, DataCategory.LONGITUDE, DataCategory.PARCEL_GEOMETRY),
    ),
    (
        "secondary_enrichment",
        (DataCategory.ENRICHMENT, DataCategory.LIEN, DataCategory.JUDGMENT, DataCategory.IMAGE, DataCategory.DOCUMENT),
    ),
)


def priority_rank(category: DataCategory) -> int:
    """Lower is higher-priority. Used only to order acquisition work
    (Section 45's "objective technical criteria"), never to rank a
    property, a county, or an investment."""
    for index, (_tier, members) in enumerate(DATASET_PRIORITY):
        if category in members:
            return index
    return len(DATASET_PRIORITY)


# The one translation between the Phase 33/35 coverage-matrix column names
# and this taxonomy.
MATRIX_COLUMN_TO_CATEGORY: dict[str, DataCategory] = {
    "auction_source": DataCategory.AUCTION,
    "tax_certificate_source": DataCategory.TAX_CERTIFICATE,
    "laft_source": DataCategory.TAX_SALE,
    "gis_source": DataCategory.GIS,
    "property_appraiser_source": DataCategory.ASSESSMENT,
    "appraisal_district_source": DataCategory.ASSESSMENT,
    "recorded_document_source": DataCategory.RECORDED_RECORDS,
    "public_record_request_source": DataCategory.RECORDED_RECORDS,
}


# Section 6's source hierarchy, as an explicit preference ordering so
# "prefer the highest available source that provides equivalent
# information" is a computable rule rather than a habit.
class SourceTier(str, Enum):
    OFFICIAL_GOVERNMENT_API = "OFFICIAL_GOVERNMENT_API"
    OFFICIAL_GOVERNMENT_BULK = "OFFICIAL_GOVERNMENT_BULK"
    OFFICIAL_GOVERNMENT_OPEN_DATA = "OFFICIAL_GOVERNMENT_OPEN_DATA"
    OFFICIAL_GOVERNMENT_DATABASE = "OFFICIAL_GOVERNMENT_DATABASE"
    OFFICIAL_GOVERNMENT_WEBSITE = "OFFICIAL_GOVERNMENT_WEBSITE"
    PUBLIC_RECORD_REQUEST = "PUBLIC_RECORD_REQUEST"
    AUTHORIZED_GOVERNMENT_CONTRACTOR = "AUTHORIZED_GOVERNMENT_CONTRACTOR"
    LICENSED_COMMERCIAL_PROVIDER = "LICENSED_COMMERCIAL_PROVIDER"
    OTHER_PUBLIC_THIRD_PARTY = "OTHER_PUBLIC_THIRD_PARTY"
    UNLICENSED_AGGREGATION = "UNLICENSED_AGGREGATION"


_TIER_ORDER = {tier: index for index, tier in enumerate(SourceTier)}


def tier_rank(tier: SourceTier) -> int:
    """Lower is more preferred (Section 6's numbered hierarchy, 1-10)."""
    return _TIER_ORDER[tier]
