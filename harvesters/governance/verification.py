"""Five-state verification/authorization/production operating model - Phase
37/38 (Two-State Verification Build: Florida + Texas Verification Map).

Repository audit finding (Phase 37/38 Section 1): every governance layer
built through Phase 37 already answers a LEGAL/COMMERCIAL question -
"is this source_id, for this use, currently authorized" (`registry.py`,
`authorization.py`, `promotion.py`) - or a DISCOVERY-stage question -
"what source exists for this county/category, and what raw evidence do we
have about it" (`source_catalog.py`). None of them answer a third, purely
ENGINEERING question this phase's instructions require to be representable
and non-conflatable: for a given source, how far has THIS PROJECT actually
gotten in (a) finding it, (b) inspecting what it returns, (c) successfully
pulling data from it by a permitted method, independent of whether that use
is currently authorized? Conflating "we could technically get this" with
"we may put this in front of a customer" is exactly the error Phase 37/38's
"MOST IMPORTANT RULE" forbids in both directions - neither state may borrow
the other's meaning.

This module adds that missing axis. It duplicates NOTHING from the layers
above:

  - `DiscoveryStatus`/`VerificationStatus`/`TechnicalAcquisitionStatus` are
    NEW, narrow, engineering-only vocabularies - they say nothing about
    legal permission and are never consulted by `gate.py`/`authorization.py`/
    `promotion.py`.
  - AUTHORIZATION is not re-modeled here at all - it is exactly Phase 34A/
    34B's `AuthorizationStatus`/`ProviderAuthorization`, referenced by
    source_id, never copied.
  - PRODUCTION status is never stored as a field on anything in this module.
    `SourceVerificationRecord.production_status_for()` always calls Phase
    37's `can_promote_source_for_use()` live - a derived value can never
    drift from the real gate's real answer (Phase 37/38 Section 31: "if
    Phase 37 promotion-gate work already exists, REUSE IT").

Everything in `SOURCE_VERIFICATION_RECORDS` below is a TRANSCRIPTION of
findings this project already made and already published (Phases 8, 9,
9.5, 9.6, 10A, 10B, 33, 33.5, 34A, 35, 36, 37 - see each record's
`evidence_reference`), reshaped into the new record structure. No new live
web verification was performed to build this module (Phase 37/38 Section
23's "do not invent data" - a claim of "verified this phase" would itself
be inventing evidence this session never gathered). Where this project's
prior knowledge is itself incomplete (e.g. GovEase's TX county-slug
enumeration), that incompleteness is preserved here, not smoothed over.

`county_readiness()`/`COUNTY_READINESS_CATEGORY_COLUMNS` compute Section
22's per-county workflow state DIRECTLY from the existing, live
`data/fl_county_coverage_matrix.csv`/`data/tx_county_coverage_matrix.csv`
rows (via `source_catalog.load_fl_matrix()`/`load_tx_matrix()`) - a real
function over real data, not a hand-maintained parallel judgment that could
silently drift from the CSVs. It is explicitly NOT a quality score (Section
22's own instruction) - two counties both at `PARTIALLY_COVERED` are not
being ranked against each other, only described.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from .promotion import PromotionDecision, can_promote_source_for_use
from .source_catalog import is_approved_status, is_unknown_or_unreviewed_status, load_fl_matrix, load_tx_matrix


class DiscoveryStatus(str, Enum):
    """Section 2: "a source is located, says nothing about legality or
    usability." Two values only - discovery is binary; how much is known
    beyond "it exists" is VerificationStatus's job, not this enum's."""

    NOT_FOUND = "NOT_FOUND"
    DISCOVERED = "DISCOVERED"


class VerificationStatus(str, Enum):
    """Section 2: "the source has been inspected and it is confirmed what
    information it actually provides" - explicitly NOT a claim of
    commercial authorization. Ordered from least to most inspected, though
    (matching CoverageState's own documented discipline) nothing in this
    module treats a later value as automatically implying an earlier one
    was skipped over correctly - each record states its own real level."""

    UNVERIFIED = "UNVERIFIED"
    MECHANISM_CONFIRMED = "MECHANISM_CONFIRMED"  # a real, live endpoint/page/pattern exists - content/fields not sampled
    CONTENT_VERIFIED = "CONTENT_VERIFIED"  # actual fields/data returned by the source have been inspected
    STALE = "STALE"  # was CONTENT_VERIFIED at verified_at; not re-confirmed since and may no longer be accurate


class TechnicalAcquisitionStatus(str, Enum):
    """Section 2: "data has actually been obtained through a permitted,
    tested method" - independent of AuthorizationStatus. A source can be
    ACQUIRED (this project has real code that has pulled real rows from it)
    while still being LEGAL_REVIEW_REQUIRED for every customer-facing use
    (fl_realauction is the exact, current, real example of this)."""

    NOT_ACQUIRED = "NOT_ACQUIRED"
    ACQUIRABLE_UNTESTED = "ACQUIRABLE_UNTESTED"  # believed technically reachable; no harvester has ever actually run against it
    ACQUIRED = "ACQUIRED"  # a real harvest_*() function has successfully pulled rows from this source
    ACQUISITION_BLOCKED_TECHNICAL = "ACQUISITION_BLOCKED_TECHNICAL"  # a real technical barrier was found (paywall, auth wall, unresolved API shape) - distinct from a LEGAL block


class DataMissingReason(str, Enum):
    """Section 14's exact nine-value vocabulary. `AVAILABLE` is included so
    every field can be classified by the same function, not just the
    missing ones. A legally-restricted field must classify here as
    `LEGAL_RESTRICTION`, never `TECHNICAL_FAILURE` (Section 14's explicit
    warning) - callers pass the reason they actually determined; this enum
    does not infer one on its own."""

    AVAILABLE = "AVAILABLE"
    LAWFULLY_COLLECTABLE_BUT_MISSING = "LAWFULLY_COLLECTABLE_BUT_MISSING"
    NOT_AVAILABLE_AT_SOURCE = "NOT_AVAILABLE_AT_SOURCE"
    SOURCE_NOT_FOUND = "SOURCE_NOT_FOUND"
    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"
    TEMPORARILY_UNAVAILABLE = "TEMPORARILY_UNAVAILABLE"
    TECHNICAL_FAILURE = "TECHNICAL_FAILURE"
    LEGAL_RESTRICTION = "LEGAL_RESTRICTION"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class CountyReadinessState(str, Enum):
    """Section 22's exact seven-value vocabulary. Explicitly a WORKFLOW
    state, not a ranking - `county_readiness()` never compares one county's
    value to another's, it only classifies each county independently
    against its own matrix row."""

    NO_SOURCE_IDENTIFIED = "NO_SOURCE_IDENTIFIED"
    SOURCE_DISCOVERED = "SOURCE_DISCOVERED"
    SOURCE_VERIFIED = "SOURCE_VERIFIED"
    TECHNICAL_SOURCE_AVAILABLE = "TECHNICAL_SOURCE_AVAILABLE"
    PARTIALLY_COVERED = "PARTIALLY_COVERED"
    FULLY_MAPPED = "FULLY_MAPPED"
    PRODUCTION_READY = "PRODUCTION_READY"


@dataclass(frozen=True)
class SourceVerificationRecord:
    """Section 5's per-source verification record. References `source_id`
    (the same string used throughout `registry.py`/`authorization.py`/
    `promotion.py`) rather than duplicating any of `SourceRecord`'s legal/
    commercial fields - this record answers "how much engineering work has
    been done", not "is it authorized" (that stays `SOURCE_REGISTRY`'s/
    `PROVIDER_AUTHORIZATIONS`'s job, composed live via `production_status_for()`
    below, never copied here)."""

    source_id: str
    state: str
    county: str | None  # None = statewide/multi-county, matching authorization.py's own convention
    data_categories_verified: tuple[str, ...]
    discovery_status: DiscoveryStatus
    verification_status: VerificationStatus
    verification_method: str
    technical_acquisition_status: TechnicalAcquisitionStatus
    access_method_verified: str | None
    verified_at: str | None
    verified_by: str
    evidence_reference: str
    technical_notes: str
    notes: str = ""

    def production_status_for(self, use: str, *, county: str | None = None) -> PromotionDecision:
        """The ONLY place this record touches production status - always a
        live call into Phase 37's `can_promote_source_for_use()`, never a
        stored field. `county` defaults to this record's own county but may
        be overridden (e.g. a statewide record checked against one specific
        county)."""
        return can_promote_source_for_use(
            self.source_id,
            use,
            state=self.state,
            county=county if county is not None else self.county,
        )


# ---------------------------------------------------------------------------
# Source verification records - one per SOURCE_REGISTRY entry (Phase 10A's
# 12 sources), transcribed from Phases 8/9/9.5/9.6/10A/10B/33/33.5/34A/35/36
# findings already on file. No new live verification performed this phase -
# see module docstring.
# ---------------------------------------------------------------------------

_TX_LGBS_V = SourceVerificationRecord(
    source_id="tx_lgbs",
    state="TX",
    county=None,
    data_categories_verified=("auction", "valuation_raw", "legal_description", "gis_coordinates"),
    discovery_status=DiscoveryStatus.DISCOVERED,
    verification_status=VerificationStatus.CONTENT_VERIFIED,
    verification_method="Live JSON API inspection (taxsales.lgbs.com/api/property_sales/) plus ongoing production runs",
    technical_acquisition_status=TechnicalAcquisitionStatus.ACQUIRED,
    access_method_verified="json_api_paginated",
    verified_at="2026-09-14",
    verified_by="Phase 10A/10B (docs/lgbs-rights-audit.md)",
    evidence_reference="harvesters/texas_harvester.py (harvest_lgbs), docs/lgbs-rights-audit.md",
    technical_notes="Real, production-verified API (workflow_dispatch run #128, 2026-09-14). Field meaning of raw 'value' not independently confirmed against vendor documentation (none found).",
)

_TX_REALAUCTION_V = SourceVerificationRecord(
    source_id="tx_realauction",
    state="TX",
    county=None,
    data_categories_verified=("auction",),
    discovery_status=DiscoveryStatus.DISCOVERED,
    verification_status=VerificationStatus.CONTENT_VERIFIED,
    verification_method="Live HTML/AJAX inspection across 24 TX county deployments plus ongoing production runs",
    technical_acquisition_status=TechnicalAcquisitionStatus.ACQUIRED,
    access_method_verified="html_calendar_plus_ajax_pagination",
    verified_at="2026-09-14",
    verified_by="Phase 10A/10B (docs/realauction-rights-audit.md)",
    evidence_reference="harvesters/texas_harvester.py (harvest_realauction), docs/realauction-rights-audit.md",
    technical_notes="No legal_description/coordinates published by this vendor for TX - reliant on Census-Geocoder fill-blank for map placement.",
)

_TX_HCTAX_V = SourceVerificationRecord(
    source_id="tx_hctax",
    state="TX",
    county="Harris",
    data_categories_verified=("auction",),
    discovery_status=DiscoveryStatus.DISCOVERED,
    verification_status=VerificationStatus.CONTENT_VERIFIED,
    verification_method="Live HTML page inspection (Phase 8/9)",
    technical_acquisition_status=TechnicalAcquisitionStatus.ACQUIRABLE_UNTESTED,
    access_method_verified="http_get_html_single_page",
    verified_at="2026-09-14",
    verified_by="Phase 8/9/9.5/9.6 (claude/harris-hctax-implementation-readiness.md)",
    evidence_reference="claude/harris-hctax-implementation-readiness.md, claude/harris-hctax-rights-resolution-package.md",
    technical_notes="Technically ready (single-GET, no pagination) but no harvest_hctax() has ever been built or run - legal_status remains LEGAL_REVIEW_REQUIRED, unaffected by this record.",
)

_TX_PBFCM_V = SourceVerificationRecord(
    source_id="tx_pbfcm",
    state="TX",
    county=None,
    data_categories_verified=("auction",),
    discovery_status=DiscoveryStatus.DISCOVERED,
    verification_status=VerificationStatus.CONTENT_VERIFIED,
    verification_method="Live site inspection, 11 counties + Harris County precincts + 2 ISDs (Phase 9/10A)",
    technical_acquisition_status=TechnicalAcquisitionStatus.ACQUIRABLE_UNTESTED,
    access_method_verified="pdf_per_jurisdiction",
    verified_at="2026-09-14",
    verified_by="claude/pbfcm-source-reconnaissance-blocked.md",
    evidence_reference="claude/pbfcm-source-reconnaissance-blocked.md",
    technical_notes="No CAPTCHA/login encountered technically; harvest_pbfcm() remains an architectural stub - not run in production, independent of the affirmative legal BLOCKED finding.",
)

_TX_MVBA_V = SourceVerificationRecord(
    source_id="tx_mvba",
    state="TX",
    county=None,
    data_categories_verified=(),
    discovery_status=DiscoveryStatus.DISCOVERED,
    verification_status=VerificationStatus.MECHANISM_CONFIRMED,
    verification_method="Site-level reconnaissance only (Phase 10A) - fields not individually sampled",
    technical_acquisition_status=TechnicalAcquisitionStatus.NOT_ACQUIRED,
    access_method_verified="pdf_and_online_auction_mixed",
    verified_at="2026-09-14",
    verified_by="claude/mvba-source-reconnaissance-blocked.md",
    evidence_reference="claude/mvba-source-reconnaissance-blocked.md",
    technical_notes="9 counties. No harvest_mvba() exists anywhere in this codebase.",
)

_TX_CTSA_V = SourceVerificationRecord(
    source_id="tx_ctsa",
    state="TX",
    county="Harris",
    data_categories_verified=(),
    discovery_status=DiscoveryStatus.DISCOVERED,
    verification_status=VerificationStatus.CONTENT_VERIFIED,
    verification_method="Live site inspection - paywall and ToS clause read directly (Phase 10A)",
    technical_acquisition_status=TechnicalAcquisitionStatus.ACQUISITION_BLOCKED_TECHNICAL,
    access_method_verified="paywalled_web_app",
    verified_at="2026-09-14",
    verified_by="claude/ctsa-source-reconnaissance.md",
    evidence_reference="claude/ctsa-source-reconnaissance.md",
    technical_notes="Paywalled - republishes the same underlying hctax.net data. Technical block (paywall) independent of the affirmative legal BLOCKED finding.",
)

_TX_GOVEASE_V = SourceVerificationRecord(
    source_id="tx_govease",
    state="TX",
    county=None,
    data_categories_verified=(),
    discovery_status=DiscoveryStatus.DISCOVERED,
    verification_status=VerificationStatus.MECHANISM_CONFIRMED,
    verification_method="Live URL pattern confirmed (liveauctions.govease.com/tx/<slug>/<id>/browse) - full county slug/ID enumeration and rendered-HTML-vs-JSON question left open",
    technical_acquisition_status=TechnicalAcquisitionStatus.NOT_ACQUIRED,
    access_method_verified=None,
    verified_at="2026-09-14",
    verified_by="claude/govease-source-onboarding-blocked.md",
    evidence_reference="claude/govease-source-onboarding-blocked.md, harvesters/texas_harvester.py (harvest_govease docstring)",
    technical_notes=(
        "harvest_govease() is confirmed, by direct re-read this phase, to STILL raise NotImplementedError - "
        "an architectural stub, not stale documentation (this reconciles a discrepancy this phase set out to "
        "resolve). robots.txt blanket Disallow: / is the deciding legal-gate factor independent of this."
    ),
)

_TX_COMPTROLLER_DIRECTORY_V = SourceVerificationRecord(
    source_id="tx_comptroller_directory",
    state="TX",
    county=None,
    data_categories_verified=("directory_links",),
    discovery_status=DiscoveryStatus.DISCOVERED,
    verification_status=VerificationStatus.MECHANISM_CONFIRMED,
    verification_method="Live per-county URL pattern confirmed (Phase 33); 254-row extraction not yet performed",
    technical_acquisition_status=TechnicalAcquisitionStatus.ACQUIRABLE_UNTESTED,
    access_method_verified="one_html_page_per_county",
    verified_at="2026-09-15",
    verified_by="Phase 33 (claude/phase-33-source-compliance-audit.md)",
    evidence_reference="claude/phase-33-source-compliance-audit.md",
    technical_notes="A directory of WHO to contact per county, not a data source itself. No terms review performed.",
)

_FL_REALAUCTION_V = SourceVerificationRecord(
    source_id="fl_realauction",
    state="FL",
    county=None,
    data_categories_verified=("auction", "valuation_raw", "case_identity"),
    discovery_status=DiscoveryStatus.DISCOVERED,
    verification_status=VerificationStatus.CONTENT_VERIFIED,
    verification_method="Long-running production harvesting (scripts/harvest_all_counties.ps1) across 46 counties",
    technical_acquisition_status=TechnicalAcquisitionStatus.ACQUIRED,
    access_method_verified="html_calendar_plus_ajax_pagination",
    verified_at="2026-09-15",
    verified_by="Phase 33.5/34A",
    evidence_reference="scripts/harvest_all_counties.ps1, claude/phase-33-5-florida-production-source-rights-audit.md, harvesters/governance/authorization.py",
    technical_notes=(
        "Technically acquired and in continuous production use. Authorization status is the separate, stricter "
        "axis - see production_status_for(): Alachua/Volusia EULAs on file are LEGAL_REVIEW_REQUIRED, and per "
        "Phase 37 Step 3 that record's existence holds EVERY fl_realauction county to the strict per-county "
        "standard, so CUSTOMER_DISPLAY denies today for counties with no authorization record of their own too."
    ),
)

_FL_LAFT_PDFS_V = SourceVerificationRecord(
    source_id="fl_laft_pdfs",
    state="FL",
    county=None,
    data_categories_verified=("auction", "case_identity", "legal_description"),
    discovery_status=DiscoveryStatus.DISCOVERED,
    verification_status=VerificationStatus.CONTENT_VERIFIED,
    verification_method="Long-running production harvesting (scripts/harvest_laft_pdfs.py) across ~47 confirmed county sources",
    technical_acquisition_status=TechnicalAcquisitionStatus.ACQUIRED,
    access_method_verified="pdf_per_jurisdiction",
    verified_at="2026-09-15",
    verified_by="Phase 33.5",
    evidence_reference="scripts/harvest_laft_pdfs.py, data/laft_pdf_sources.csv, claude/phase-33-5-florida-production-source-rights-audit.md",
    technical_notes="~35 of 67 FL counties remain uncovered by any of the 9 current LAFT harvesters - a real, unresolved coverage gap, not a rights gap.",
)

_FL_LIENHUB_CERTIFICATES_V = SourceVerificationRecord(
    source_id="fl_lienhub_certificates",
    state="FL",
    county=None,
    data_categories_verified=("tax_certificate", "valuation_raw", "owner_identity"),
    discovery_status=DiscoveryStatus.DISCOVERED,
    verification_status=VerificationStatus.CONTENT_VERIFIED,
    verification_method="Long-running production harvesting (scripts/harvest_lienhub_certificates.ps1) across 32 counties",
    technical_acquisition_status=TechnicalAcquisitionStatus.ACQUIRED,
    access_method_verified="html_scrape",
    verified_at="2026-09-15",
    verified_by="Phase 33.5/34A",
    evidence_reference="scripts/harvest_lienhub_certificates.ps1, harvesters/governance/authorization.py",
    technical_notes="Technically acquired and in continuous production use. The LienHub User Agreement (Phase 34A) is LEGAL_REVIEW_REQUIRED - the strictest of the three grandfathered FL sources.",
)

_FL_DOR_STATEWIDE_V = SourceVerificationRecord(
    source_id="fl_dor_statewide",
    state="FL",
    county=None,
    data_categories_verified=("assessment_roll_fields", "sales_history", "gis"),
    discovery_status=DiscoveryStatus.DISCOVERED,
    verification_status=VerificationStatus.MECHANISM_CONFIRMED,
    verification_method="Live page review of floridarevenue.com/dataPortal (Phase 33) - direct-download links for current-year NAL/NAP/sales/GIS confirmed; no file was actually downloaded or parsed this project",
    technical_acquisition_status=TechnicalAcquisitionStatus.ACQUIRABLE_UNTESTED,
    access_method_verified="direct_download_current_year; request_by_email_fax_mail_or_phone for historical years",
    verified_at="2026-09-15",
    verified_by="Phase 33 (claude/phase-33-source-compliance-audit.md)",
    evidence_reference="claude/phase-33-source-compliance-audit.md",
    technical_notes="Single statewide source covering all 67 counties in one place, if acquired - the highest-leverage FL gap-filler identified to date. Not wired into any harvester.",
)


SOURCE_VERIFICATION_RECORDS: dict[str, SourceVerificationRecord] = {
    r.source_id: r
    for r in (
        _TX_LGBS_V,
        _TX_REALAUCTION_V,
        _TX_HCTAX_V,
        _TX_PBFCM_V,
        _TX_MVBA_V,
        _TX_CTSA_V,
        _TX_GOVEASE_V,
        _TX_COMPTROLLER_DIRECTORY_V,
        _FL_REALAUCTION_V,
        _FL_LAFT_PDFS_V,
        _FL_LIENHUB_CERTIFICATES_V,
        _FL_DOR_STATEWIDE_V,
    )
}


def get_verification_record(source_id: str) -> SourceVerificationRecord | None:
    """Fail-closed lookup, matching `registry.get_source()`'s own contract:
    returns None rather than raising, so an unrepresented source_id is
    ordinary, checkable data, not an exceptional code path."""
    return SOURCE_VERIFICATION_RECORDS.get(source_id)


def all_verification_records(*, state: str | None = None) -> list[SourceVerificationRecord]:
    values = list(SOURCE_VERIFICATION_RECORDS.values())
    if state is not None:
        values = [r for r in values if r.state == state]
    return sorted(values, key=lambda r: r.source_id)


# ---------------------------------------------------------------------------
# Vendor placeholder model - Section 25/26. Tracks future commercial
# acquisition candidates WITHOUT purchasing, contacting, or accepting terms
# from any of them (Section 25's explicit hard stop). Seeded only with
# vendors this project has ALREADY discovered through Phases 9/10A/10B/33.5/
# 34A reconnaissance - no new vendor was searched for or invented this phase.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class VendorCandidate:
    """Section 25's exact field list."""

    vendor_id: str
    vendor_name: str
    product: str
    states: tuple[str, ...]
    counties: tuple[str, ...]  # empty tuple = statewide/multi-county by product design
    categories: tuple[str, ...]
    fields: tuple[str, ...]
    api_available: bool | None
    bulk_available: bool | None
    historical_available: bool | None
    pricing_notes: str
    license_notes: str
    commercial_use_status: str
    customer_display_status: str
    export_status: str
    api_redistribution_status: str
    storage_status: str
    retention_notes: str
    images_status: str
    documents_status: str
    contract_status: str  # e.g. NOT_CONTACTED | DEMO_REQUESTED | TERMS_UNDER_REVIEW | CONTRACT_EXECUTED
    authorization_status: str  # mirrors AuthorizationStatus vocabulary where a real record exists, else a plain description
    contact_status: str
    reviewed_at: str | None
    notes: str = ""


VENDOR_CANDIDATES: dict[str, VendorCandidate] = {
    "grant_street_lienhub": VendorCandidate(
        vendor_id="grant_street_lienhub",
        vendor_name="Grant Street Group",
        product="LienHub tax certificate sale platform",
        states=("FL",),
        counties=(),
        categories=("tax_certificate", "auction"),
        fields=("account_number", "certificate_no", "tax_year", "bid", "assessed", "owner_name", "interest_rate"),
        api_available=None,
        bulk_available=None,
        historical_available=None,
        pricing_notes="Not investigated - no pricing conversation has occurred.",
        license_notes="LienHub User Agreement on file (harvesters/governance/authorization.py _LIENHUB_GRANT_STREET) - expressly prohibits automated devices; carve-out for express written permission exists but has not been sought.",
        commercial_use_status="LEGAL_REVIEW_REQUIRED (existing production relationship, terms already reviewed Phase 34A)",
        customer_display_status="LEGAL_REVIEW_REQUIRED",
        export_status="LEGAL_REVIEW_REQUIRED",
        api_redistribution_status="LEGAL_REVIEW_REQUIRED",
        storage_status="LEGAL_REVIEW_REQUIRED (narrow internal-recordkeeping exception only)",
        retention_notes="No source-stated retention limit found beyond the recordkeeping exception.",
        images_status="N/A - product publishes no images",
        documents_status="N/A - product publishes no documents",
        contract_status="EXISTING_RELATIONSHIP_UNRESOLVED",
        authorization_status="LEGAL_REVIEW_REQUIRED",
        contact_status="NOT_CONTACTED (no outreach performed - see docs/provider-authorization-requests.md for the drafted-not-sent request)",
        reviewed_at="2026-09-15",
        notes="Already a production data source (fl_lienhub_certificates) - vendor tracking exists here so the SAME commercial-resolution process (Section 37) applies to it, not a special case.",
    ),
    "realauction": VendorCandidate(
        vendor_id="realauction",
        vendor_name="RealAuction.com, LLC",
        product="RealAuction / RealForeclose tax deed and foreclosure auction platform",
        states=("FL", "TX"),
        counties=(),
        categories=("auction",),
        fields=("case_no", "parcel", "address", "bid", "assessed", "sale_date"),
        api_available=False,
        bulk_available=False,
        historical_available=None,
        pricing_notes="Not investigated.",
        license_notes="Alachua/Volusia EULAs on file (Phase 34A) - prohibit automated access/robots/spiders and unauthorized redistribution absent prior written consent.",
        commercial_use_status="LEGAL_REVIEW_REQUIRED",
        customer_display_status="LEGAL_REVIEW_REQUIRED",
        export_status="LEGAL_REVIEW_REQUIRED",
        api_redistribution_status="LEGAL_REVIEW_REQUIRED",
        storage_status="LEGAL_REVIEW_REQUIRED",
        retention_notes="Not addressed in the two EULAs on file.",
        images_status="N/A - no image URLs published by this vendor in either state's harvested field set",
        documents_status="N/A",
        contract_status="EXISTING_RELATIONSHIP_UNRESOLVED",
        authorization_status="LEGAL_REVIEW_REQUIRED (2 of ~70 total FL+TX deployments have any record at all)",
        contact_status="NOT_CONTACTED",
        reviewed_at="2026-09-15",
        notes="Single vendor spans both states (fl_realauction, tx_realauction) - tracked once here even though registry.py has two source_ids for it.",
    ),
    "lgbs": VendorCandidate(
        vendor_id="lgbs",
        vendor_name="Linebarger Goggan Blair & Sampson, LLP",
        product="taxsales.lgbs.com public JSON API",
        states=("TX",),
        counties=(),
        categories=("auction", "valuation"),
        fields=("account_number", "cause_number", "min_bid", "value", "legal_description", "latitude", "longitude"),
        api_available=True,
        bulk_available=False,
        historical_available=None,
        pricing_notes="No fee encountered - public, unauthenticated API.",
        license_notes="www.lgbs.com/legal-disclosures/ (different subdomain) prohibits reproduction/redistribution without permission; scope as applied to the API subdomain is unresolved (docs/lgbs-rights-audit.md).",
        commercial_use_status="LEGAL_REVIEW_REQUIRED (unresolved scope question, not a clearance)",
        customer_display_status="In production use pending resolution",
        export_status="Not currently exposed via a separate export/API surface",
        api_redistribution_status="LEGAL_REVIEW_REQUIRED",
        storage_status="In production use",
        retention_notes="No source-side restriction found or ruled out.",
        images_status="N/A - no images published",
        documents_status="N/A",
        contract_status="EXISTING_RELATIONSHIP_UNRESOLVED",
        authorization_status="No ProviderAuthorization record - registry legal_status APPROVED (production-practice, not formally cleared)",
        contact_status="NOT_CONTACTED",
        reviewed_at="2026-09-14",
        notes="Already a production data source (tx_lgbs).",
    ),
    "pbfcm": VendorCandidate(
        vendor_id="pbfcm",
        vendor_name="Perdue Brandon Fielder Collins & Mott, LLP",
        product="pbfcm.com tax-sale PDF listings",
        states=("TX",),
        counties=(),
        categories=("auction",),
        fields=(),
        api_available=False,
        bulk_available=False,
        historical_available=None,
        pricing_notes="Not investigated.",
        license_notes="disclosure.html explicitly prohibits reproduction/republication/retransmission/distribution without prior written permission.",
        commercial_use_status="PROHIBITED",
        customer_display_status="PROHIBITED",
        export_status="PROHIBITED",
        api_redistribution_status="PROHIBITED",
        storage_status="PROHIBITED",
        retention_notes="Moot given blanket prohibition.",
        images_status="N/A - PDFs are the product; covered by the same prohibition",
        documents_status="PROHIBITED",
        contract_status="NOT_CONTACTED",
        authorization_status="BLOCKED",
        contact_status="NOT_CONTACTED",
        reviewed_at="2026-09-14",
        notes="A future written-permission request would need to specifically address the disclosure.html prohibition before any technical integration.",
    ),
    "mvba": VendorCandidate(
        vendor_id="mvba",
        vendor_name="MVBA Law",
        product="mvbalaw.com / mvbataxsales.com Texas tax-sale listings",
        states=("TX",),
        counties=(),
        categories=("auction",),
        fields=(),
        api_available=None,
        bulk_available=None,
        historical_available=None,
        pricing_notes="Not investigated.",
        license_notes="Explicit prohibition found - see claude/mvba-source-reconnaissance-blocked.md.",
        commercial_use_status="PROHIBITED",
        customer_display_status="PROHIBITED",
        export_status="PROHIBITED",
        api_redistribution_status="PROHIBITED",
        storage_status="PROHIBITED",
        retention_notes="Moot given blanket prohibition.",
        images_status="PROHIBITED",
        documents_status="PROHIBITED",
        contract_status="NOT_CONTACTED",
        authorization_status="BLOCKED",
        contact_status="NOT_CONTACTED",
        reviewed_at="2026-09-14",
    ),
    "ctsa": VendorCandidate(
        vendor_id="ctsa",
        vendor_name="County Tax Sale App",
        product="countytaxsaleapp.org paywalled Harris County product",
        states=("TX",),
        counties=("Harris",),
        categories=("auction",),
        fields=(),
        api_available=None,
        bulk_available=None,
        historical_available=None,
        pricing_notes="Paywalled subscription product - pricing not investigated.",
        license_notes="Explicit anti-competitive-use ToS clause found (claude/ctsa-source-reconnaissance.md).",
        commercial_use_status="PROHIBITED",
        customer_display_status="PROHIBITED",
        export_status="PROHIBITED",
        api_redistribution_status="PROHIBITED",
        storage_status="PROHIBITED",
        retention_notes="Moot given blanket prohibition.",
        images_status="Not separately addressed",
        documents_status="Not separately addressed",
        contract_status="NOT_CONTACTED",
        authorization_status="BLOCKED",
        contact_status="NOT_CONTACTED",
        reviewed_at="2026-09-14",
        notes="Republishes the same underlying Harris County data hctax.net publishes directly - the government-first source (tx_hctax) is the preferred path, not this vendor.",
    ),
    "govease": VendorCandidate(
        vendor_id="govease",
        vendor_name="GovEase",
        product="liveauctions.govease.com online tax-deed auction platform",
        states=("TX",),
        counties=("Denton", "Parker", "Wichita", "Wise"),
        categories=("auction",),
        fields=(),
        api_available=None,
        bulk_available=None,
        historical_available=None,
        pricing_notes="Not investigated.",
        license_notes="No Terms of Use located; robots.txt blanket Disallow: / treated conservatively as blocking.",
        commercial_use_status="BLOCKED (conservative, robots-based - no ToS to weigh against it)",
        customer_display_status="BLOCKED",
        export_status="BLOCKED",
        api_redistribution_status="BLOCKED",
        storage_status="Not evaluated further",
        retention_notes="Not evaluated further",
        images_status="Not evaluated further",
        documents_status="Not evaluated further",
        contract_status="NOT_CONTACTED",
        authorization_status="BLOCKED",
        contact_status="NOT_CONTACTED",
        reviewed_at="2026-09-14",
        notes="Technical integration path (JSON API vs. rendered HTML, county slug/ID enumeration) is also still unresolved independent of the legal block - see SOURCE_VERIFICATION_RECORDS['tx_govease'].",
    ),
}


def all_vendor_candidates() -> list[VendorCandidate]:
    return sorted(VENDOR_CANDIDATES.values(), key=lambda v: v.vendor_id)


# ---------------------------------------------------------------------------
# County readiness (Section 22) - computed directly from the live coverage
# matrices, never hand-maintained.
# ---------------------------------------------------------------------------

FL_READINESS_COLUMNS: tuple[str, ...] = (
    "auction_source_status",
    "tax_certificate_source_status",
    "laft_source_status",
    "gis_source_status",
    "property_appraiser_verification_status",
)

TX_READINESS_COLUMNS: tuple[str, ...] = (
    "auction_source_status",
    "appraisal_district_source_status",
    "gis_source_status",
    "appraisal_district_verification_status",
)


def _classify_cell(raw: str | None) -> str:
    """Classifies one free-text matrix cell into one of a small number of
    buckets, reusing `source_catalog`'s own existing, tested string
    predicates rather than re-deriving a second interpretation of the same
    text (Section 31's reuse discipline applied within this phase's own new
    code, not just against Phase 37)."""
    if raw is None or is_unknown_or_unreviewed_status(raw):
        return "NONE"
    if is_approved_status(raw):
        return "APPROVED"
    stripped = raw.strip()
    if stripped.startswith("BLOCKED"):
        return "BLOCKED"
    if stripped.startswith("LEGAL_REVIEW_REQUIRED"):
        return "LEGAL_REVIEW"
    return "DISCOVERED"  # any other non-empty, non-unknown value is at least discovery-stage evidence


def county_readiness(row: dict[str, str], columns: tuple[str, ...]) -> CountyReadinessState:
    """Section 22's per-county workflow state, computed from one matrix row.

    Deliberately conservative about `PRODUCTION_READY`: this function alone
    NEVER returns it, because a matrix cell saying "APPROVED (grandfathered)"
    is `SOURCE_REGISTRY`'s whole-source legal_status, not a real, per-county,
    per-use production decision (Phase 37's own point). Every matrix-based
    call site in this module returns at most `FULLY_MAPPED` from cell text
    alone; `production_enabled_for_county()` below is the only function that
    may add `PRODUCTION_READY`, and only by calling the real gate."""
    classes = [_classify_cell(row.get(c)) for c in columns]
    known = [c for c in classes if c != "NONE"]
    if not known:
        return CountyReadinessState.NO_SOURCE_IDENTIFIED
    if len(known) == len(columns):
        return CountyReadinessState.FULLY_MAPPED
    if len(known) == 1:
        return CountyReadinessState.SOURCE_DISCOVERED
    return CountyReadinessState.PARTIALLY_COVERED


# For each state, which (matrix free-text description column -> keyword ->
# real, registered source_id) actually names a promotable source for a
# GIVEN county's row - deliberately keyword-matched against the row's own
# free text rather than a fixed source list applied to every county
# uniformly, because none of these sources actually covers 100% of its
# state (fl_realauction covers 46/67 FL counties, fl_lienhub_certificates
# 32/67, fl_laft_pdfs 47/67, tx_realauction 24/254 TX counties - see each
# CSV's own row count) - a county this project has never actually attributed
# a source to must never be checked against a source_id it was never
# actually reported to use, or PRODUCTION_READY would be fabricated for it.
_FL_SOURCE_KEYWORD_COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("auction_source", "realauction", "fl_realauction"),
    ("tax_certificate_source", "lienhub", "fl_lienhub_certificates"),
    ("laft_source", "laft", "fl_laft_pdfs"),
)
_TX_SOURCE_KEYWORD_COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("auction_source", "lgbs", "tx_lgbs"),
    ("auction_source", "realauction", "tx_realauction"),
)


def _source_ids_named_for_county(state: str, row: dict[str, str]) -> tuple[str, ...]:
    """Which promotable source_ids this SPECIFIC county's own matrix row
    actually names - not which sources exist for the state in general."""
    keyword_columns = _FL_SOURCE_KEYWORD_COLUMNS if state == "FL" else _TX_SOURCE_KEYWORD_COLUMNS if state == "TX" else ()
    found: list[str] = []
    for column, keyword, source_id in keyword_columns:
        text = (row.get(column) or "").lower()
        if keyword in text and source_id not in found:
            found.append(source_id)
    return tuple(found)


def production_enabled_for_county(state: str, county: str, row: dict[str, str], *, use: str = "CUSTOMER_DISPLAY") -> dict[str, PromotionDecision]:
    """The only function in this module permitted to assert production
    readiness - and only by calling Phase 37's real
    `can_promote_source_for_use()`, and only for source_ids this county's
    OWN matrix row actually names (see `_source_ids_named_for_county()`).
    Returns one `PromotionDecision` per named source_id (never a single
    boolean - Phase 37 Section 2's "never collapse to one boolean" rule
    applies here too). Returns an empty dict for a county with no promotable
    source named at all - that is the honest, correct answer, not an error."""
    source_ids = _source_ids_named_for_county(state, row)
    return {sid: can_promote_source_for_use(sid, use, state=state, county=county) for sid in source_ids}


def full_county_readiness(state: str, county: str, row: dict[str, str], *, use: str = "CUSTOMER_DISPLAY") -> CountyReadinessState:
    """Combines the matrix-cell-based readiness with a real production-gate
    check: a county whose matrix cells are `FULLY_MAPPED` AND which has at
    least one real, currently-allowed production decision for `use`
    advances to `PRODUCTION_READY`; otherwise the matrix-based state stands.
    This is the one place `PRODUCTION_READY` can be produced, and it can
    never be produced by matrix text alone."""
    columns = FL_READINESS_COLUMNS if state == "FL" else TX_READINESS_COLUMNS
    base = county_readiness(row, columns)
    decisions = production_enabled_for_county(state, county, row, use=use)
    if any(d.allowed for d in decisions.values()):
        return CountyReadinessState.PRODUCTION_READY
    return base


def all_county_readiness(state: str) -> dict[str, CountyReadinessState]:
    """Section 36's "Florida 67/67 counties mapped, Texas 254/254 counties
    mapped" requirement, satisfied literally: every row in the live matrix
    gets a real, computed readiness state - never a placeholder, never
    skipped."""
    rows = load_fl_matrix() if state == "FL" else load_tx_matrix()
    return {row["county"]: full_county_readiness(state, row["county"], row) for row in rows}
