"""County/source acquisition configuration - Phase 39 Sections 5, 25, 26,
46, 47.

The single most important requirement of this phase is Section 5's "do not
build 321 independent scrapers". This module is how that is avoided: a
county is a CONFIGURATION ROW naming a mechanism, and mechanisms are the
small, fixed set of adapters in `harvesters/acquisition/adapters/`.

Configuration is generated from data this repository already maintains
rather than hand-listed a second time:

  - `data/fl_county_coverage_matrix.csv` (67 rows, Phase 33/35)
  - `data/tx_county_coverage_matrix.csv` (254 rows, Phase 33/35)
  - `harvesters/governance/registry.py`'s `SOURCE_REGISTRY`
  - `harvesters/governance/verification.py`'s per-county source attribution

Section 26 suggests a YAML file per county. This module deliberately does
NOT introduce YAML: this repository's existing configuration convention is
CSV-plus-Python-dataclasses (`data/*.csv` + `source_catalog.CatalogSource`
+ `registry.SourceRecord`), and Section 26's own instruction is to "use the
repository's existing configuration conventions if available". Adding a
third config format for one phase's convenience would make the county
source of truth ambiguous, which is the exact problem Phase 35 solved.

The rule this module enforces: a county entry may only name a mechanism
that actually exists as an adapter. An unknown mechanism is
`AcquisitionMechanism.NONE`, which produces no adapter and no acquisition
attempt - never a silent fallback to "just try scraping it" (Section 16).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ..governance.source_catalog import load_fl_matrix, load_tx_matrix
from ..governance.verification import _source_ids_named_for_county
from .categories import DataCategory, SourceTier


class AcquisitionMechanism(str, Enum):
    """The fixed, small set of ways data is actually obtained. Section 5's
    adapter list. `NONE` is a first-class, honest value: most Texas
    counties genuinely have no identified acquisition mechanism today, and
    recording that is the point."""

    JSON_API = "JSON_API"
    ARCGIS_REST = "ARCGIS_REST"
    BULK_DOWNLOAD = "BULK_DOWNLOAD"
    OPEN_DATA_PORTAL = "OPEN_DATA_PORTAL"
    PUBLIC_DATABASE = "PUBLIC_DATABASE"
    DOCUMENT_PDF = "DOCUMENT_PDF"
    HTML_PUBLIC_SEARCH = "HTML_PUBLIC_SEARCH"
    LICENSED_PROVIDER = "LICENSED_PROVIDER"
    COUNTY_SPECIFIC = "COUNTY_SPECIFIC"
    PUBLIC_RECORD_REQUEST = "PUBLIC_RECORD_REQUEST"
    LINK_ONLY = "LINK_ONLY"
    NONE = "NONE"


# Mechanisms that have a real, implemented adapter in this phase. Anything
# else is configuration for future work and must never be presented as
# acquirable today (Section 70).
IMPLEMENTED_MECHANISMS = frozenset(
    {
        AcquisitionMechanism.JSON_API,
        AcquisitionMechanism.ARCGIS_REST,
    }
)


# How each known source_id is actually reached. The one place a source_id
# becomes a mechanism; adding a source means adding a row here, not
# branching inside an adapter.
SOURCE_MECHANISM: dict[str, AcquisitionMechanism] = {
    "tx_lgbs": AcquisitionMechanism.JSON_API,
    "tx_realauction": AcquisitionMechanism.HTML_PUBLIC_SEARCH,
    "tx_hctax": AcquisitionMechanism.HTML_PUBLIC_SEARCH,
    "tx_comptroller_directory": AcquisitionMechanism.HTML_PUBLIC_SEARCH,
    "tx_pbfcm": AcquisitionMechanism.DOCUMENT_PDF,
    "tx_mvba": AcquisitionMechanism.DOCUMENT_PDF,
    "tx_ctsa": AcquisitionMechanism.LICENSED_PROVIDER,
    "tx_govease": AcquisitionMechanism.NONE,  # mechanism genuinely unresolved - see Section 23
    "fl_realauction": AcquisitionMechanism.HTML_PUBLIC_SEARCH,
    "fl_lienhub_certificates": AcquisitionMechanism.HTML_PUBLIC_SEARCH,
    "fl_laft_pdfs": AcquisitionMechanism.DOCUMENT_PDF,
    # fl_dor_statewide has TWO real mechanisms. The ArcGIS FeatureServer
    # ("FDOR Cadastral 2025", 124 fields) is the one this phase verified
    # live and implemented an adapter for, so it is the mechanism recorded
    # here. The Data Portal's downloadable NAL/NAP/SDF files are a separate,
    # not-yet-verified BULK_DOWNLOAD path for the same source - see
    # docs/florida-acquisition.md.
    "fl_dor_statewide": AcquisitionMechanism.ARCGIS_REST,
    # CAD enrichment layers (not SOURCE_REGISTRY entries of their own -
    # they are reached under their county's government source_id).
    "tx_cad_harris_hcad": AcquisitionMechanism.ARCGIS_REST,
    "tx_cad_tarrant_tad": AcquisitionMechanism.ARCGIS_REST,
}


@dataclass(frozen=True)
class CountySourceConfig:
    """One (county, source, mechanism) acquisition configuration row."""

    state: str
    county: str
    source_id: str
    mechanism: AcquisitionMechanism
    categories: tuple[DataCategory, ...]
    tier: SourceTier
    adapter_available: bool
    notes: str = ""

    @property
    def jurisdiction(self) -> str:
        return f"{self.state}/{self.county}"


def _categories_for_source(source_id: str) -> tuple[DataCategory, ...]:
    if source_id in ("fl_realauction", "tx_realauction"):
        return (DataCategory.AUCTION, DataCategory.AUCTION_DATE, DataCategory.OPENING_BID, DataCategory.CASE_NUMBER)
    if source_id == "fl_lienhub_certificates":
        return (DataCategory.TAX_CERTIFICATE, DataCategory.ASSESSED_VALUE, DataCategory.OWNERSHIP)
    if source_id == "fl_laft_pdfs":
        return (DataCategory.TAX_SALE, DataCategory.PARCEL_APN, DataCategory.LEGAL_DESCRIPTION)
    if source_id == "tx_lgbs":
        return (DataCategory.AUCTION, DataCategory.MINIMUM_BID, DataCategory.MARKET_VALUE, DataCategory.GIS)
    if source_id == "fl_dor_statewide":
        return (DataCategory.ASSESSMENT, DataCategory.JUST_VALUE, DataCategory.SALES_HISTORY, DataCategory.GIS)
    if source_id.startswith("tx_cad_"):
        return (DataCategory.ASSESSMENT, DataCategory.MARKET_VALUE, DataCategory.PROPERTY_CHARACTERISTICS)
    return (DataCategory.PROPERTY,)


def _tier_for_source(source_id: str) -> SourceTier:
    if source_id in ("fl_dor_statewide", "tx_comptroller_directory"):
        return SourceTier.OFFICIAL_GOVERNMENT_DATABASE
    if source_id.startswith("tx_cad_"):
        return SourceTier.OFFICIAL_GOVERNMENT_API
    if source_id in ("tx_hctax",):
        return SourceTier.OFFICIAL_GOVERNMENT_WEBSITE
    if source_id == "fl_laft_pdfs":
        return SourceTier.OFFICIAL_GOVERNMENT_WEBSITE
    if source_id in ("tx_ctsa",):
        return SourceTier.LICENSED_COMMERCIAL_PROVIDER
    return SourceTier.OTHER_PUBLIC_THIRD_PARTY


def build_county_configs(state: str) -> list[CountySourceConfig]:
    """Generate acquisition configuration for every county in `state`,
    from the live coverage matrices. 67 rows for FL, 254 for TX - every
    county appears, including the many whose mechanism is `NONE`, because
    Section 64 requires "source identified" to stay distinguishable from
    "records actually obtained"."""
    rows = load_fl_matrix() if state == "FL" else load_tx_matrix()
    configs: list[CountySourceConfig] = []

    for row in rows:
        county = row["county"]
        named = list(_source_ids_named_for_county(state, row))

        # Statewide sources are not named per-county in the coverage
        # matrices (those columns record per-county auction/certificate/LAFT
        # attribution), but a statewide layer genuinely serves every county
        # in its state - that is the whole point of Section 46's
        # statewide-over-per-county preference. Florida's FDOR cadastral
        # FeatureServer covers all 67 counties from one layer, confirmed
        # live 2026-09-16 with a real county-scoped query.
        if state == "FL":
            named.append("fl_dor_statewide")

        if not named:
            configs.append(
                CountySourceConfig(
                    state=state,
                    county=county,
                    source_id="",
                    mechanism=AcquisitionMechanism.NONE,
                    categories=(),
                    tier=SourceTier.OTHER_PUBLIC_THIRD_PARTY,
                    adapter_available=False,
                    notes="no promotable source named for this county in the Phase 33/35 coverage matrix",
                )
            )
            continue
        for source_id in named:
            mechanism = SOURCE_MECHANISM.get(source_id, AcquisitionMechanism.NONE)
            configs.append(
                CountySourceConfig(
                    state=state,
                    county=county,
                    source_id=source_id,
                    mechanism=mechanism,
                    categories=_categories_for_source(source_id),
                    tier=_tier_for_source(source_id),
                    adapter_available=mechanism in IMPLEMENTED_MECHANISMS,
                    notes="",
                )
            )
    return configs


def mechanism_summary(state: str) -> dict[str, int]:
    """How many county-source pairs use each mechanism - the number that
    actually answers "how many scrapers would a naive implementation have
    needed, and how many adapters does this design need instead"."""
    summary: dict[str, int] = {}
    for config in build_county_configs(state):
        summary[config.mechanism.value] = summary.get(config.mechanism.value, 0) + 1
    return summary


def counties_with_adapter(state: str) -> list[CountySourceConfig]:
    """Only the county-source pairs an implemented adapter can actually
    serve today. This is the honest denominator for "what could this engine
    acquire right now" - Section 70."""
    return [c for c in build_county_configs(state) if c.adapter_available]
