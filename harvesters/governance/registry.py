"""State-agnostic source registry - Phase 10A (Commercial Source Governance
Infrastructure).

Repository audit finding (Phase 10A, Step 1): before this module, this
project had no formal source-registry file. Every prior reconnaissance
phase (claude/*.md docs in the "tax florida app" claude.ai Project - see
each SourceRecord's `doc_refs` below) said explicitly that a source's
status "lives in its own claude/*.md document" as "the de facto registry",
by convention, not by any structured/queryable data. This module is the
first actual structured registry - it does not replace those documents
(they remain the detailed evidence trail; `doc_refs` below points back to
them) but gives the codebase one place a harvester/sync/customer-output
path can *check programmatically* before acting, per Phase 10A's own
instruction not to equate technical accessibility with legal permission.

Nothing in this module changes any source's actual legal status - it
TRANSCRIBES the determinations already reached in claude/*.md documents
(Phase 8/9/9.5/9.6 for Harris; the GovEase/PBFCM/MVBA/CTSA reconnaissance
docs for the four blocked vendors) plus this project's own existing
production practice for tx_lgbs/tx_realauction (shipped, live,
production-verified - see harvesters/texas_harvester.py's module
docstring) and Florida's long-standing production sources (grandfathered -
see the FL entries' own notes for the honest caveat about what "approved"
means for them).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from .restrictions import Restriction


class SourceStatus(str, Enum):
    """The approval-state model required by Phase 10A Step 3. Ordered
    roughly from "just found" to "terminal" states, though the model does
    not enforce a strict linear transition - a source can move from
    APPROVED to TERMS_CHANGED to LEGAL_REVIEW_REQUIRED, for instance, if a
    vendor changes its terms after approval."""

    DISCOVERED = "DISCOVERED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    APPROVED_WITH_RESTRICTIONS = "APPROVED_WITH_RESTRICTIONS"
    LEGAL_REVIEW_REQUIRED = "LEGAL_REVIEW_REQUIRED"
    BLOCKED = "BLOCKED"
    DISABLED = "DISABLED"
    TERMS_CHANGED = "TERMS_CHANGED"


# The ONLY statuses under which the ingestion gate (gate.py) allows a
# harvester/ingestion process to proceed. Everything else - including a
# status this enum doesn't even define, see gate.py's fail-closed handling
# of an unknown/missing source - is rejected. Technical accessibility
# (whether a URL 200s) is never part of this decision; only legal_status is.
INGESTION_ALLOWED_STATUSES = frozenset(
    {
        SourceStatus.APPROVED,
        SourceStatus.APPROVED_WITH_RESTRICTIONS,
    }
)


@dataclass(frozen=True)
class SourceRecord:
    """One row of the source registry. Field list matches Phase 10A Step 2
    exactly (source ID/name/state/jurisdiction/URL/type/official-vendor/
    access method/automation status/legal status/commercial-use status/
    storage status/customer-display status/redistribution status/
    API-export status/historical-retention status/document-image-rights
    status/attribution requirement/rate limit/robots status/terms status/
    review date/reviewer/notes/restrictions/source version-change state) -
    every field from that list has a slot here, none renamed or dropped.

    The per-right "*_status" fields below are intentionally free-text
    (not a second enum) because the underlying reconnaissance documents
    (Phase 9.5 in particular) use a richer vocabulary than a 6-value
    approval enum can carry - e.g. Harris's commercial_use_status is "NO
    RESTRICTION FOUND; NO PERMISSION FOUND (LEGAL_REVIEW_REQUIRED)", which
    is meaningfully different from PBFCM's "PROHIBITED - explicit
    disclosure.html clause". `legal_status` (the SourceStatus enum) is
    what the ingestion gate actually checks; the free-text fields are the
    human-readable "why", preserved from the source documents rather than
    lossily compressed into one of six buckets.
    """

    source_id: str  # matches harvester_source values already used by TexasSaleRow, e.g. "tx_lgbs"
    source_name: str
    state: str  # "TX" | "FL" | ... - state-agnostic by design (Step 2)
    jurisdiction: str  # county/ISD/statewide
    source_url: str
    source_type: str  # "government" | "vendor_law_firm" | "vendor_platform" | "vendor_product"
    official_or_vendor: str  # "official" | "vendor"
    access_method: str  # e.g. "http_get_html_single_page", "json_api_paginated", "pdf_per_jurisdiction"
    automation_status: str  # technical-only summary, e.g. "READY_FOR_FUTURE_IMPLEMENTATION"
    legal_status: SourceStatus
    commercial_use_status: str
    storage_status: str
    customer_display_status: str
    redistribution_status: str
    api_export_status: str
    historical_retention_status: str
    document_image_rights_status: str
    attribution_required: bool
    rate_limit: str | None
    robots_status: str
    terms_status: str
    review_date: str  # ISO date (YYYY-MM-DD) of the most recent reconnaissance/review pass
    reviewer: str
    notes: str
    restrictions: tuple[Restriction, ...] = field(default_factory=tuple)
    source_version: str = "1"
    change_state: str = "stable"  # "stable" | "under_change_review" | "superseded"
    doc_refs: tuple[str, ...] = field(default_factory=tuple)  # claude/*.md docs this entry transcribes


# ---------------------------------------------------------------------------
# Texas sources
# ---------------------------------------------------------------------------

_TX_LGBS = SourceRecord(
    source_id="tx_lgbs",
    source_name="Linebarger Goggan Blair & Sampson - taxsales.lgbs.com public API",
    state="TX",
    jurisdiction="statewide (multi-county)",
    source_url="https://taxsales.lgbs.com/api/property_sales/",
    source_type="vendor_law_firm",
    official_or_vendor="vendor",
    access_method="json_api_paginated",
    automation_status="READY - shipped and production-verified (workflow_dispatch run #128, 2026-09-14)",
    legal_status=SourceStatus.APPROVED,
    commercial_use_status=(
        "PRODUCTION-PRACTICE APPROVAL, NOT FORMALLY RIGHTS-CLEARED - approval basis requires legal review "
        "(Phase 10B finding). www.lgbs.com/legal-disclosures/ (a DIFFERENT subdomain of the same legal "
        "entity) contains an affirmative prohibition: 'Reproduction, republication, retransmission, and/or "
        "distribution of material contained within this web site is prohibited unless the prior permission "
        "of Linebarger has been obtained.' Whether 'this web site' extends to taxsales.lgbs.com (the "
        "subdomain/API this project actually uses, which has no terms page of its own) is genuinely "
        "unresolved - see docs/lgbs-rights-audit.md Section 5. Not treated as either a block or a clearance."
    ),
    storage_status="In production use - stored in Supabase `properties` table today. See commercial_use_status above for the unresolved scope question this now sits under.",
    customer_display_status="In production use - displayed to approved app users today. See commercial_use_status above.",
    redistribution_status="LEGAL_REVIEW_REQUIRED - see commercial_use_status above; the www.lgbs.com/legal-disclosures/ prohibition is real, its scope as applied to taxsales.lgbs.com is what's unresolved.",
    api_export_status="Not currently exposed through a customer-facing export/API distinct from the app itself. Would inherit the same open scope question above if built.",
    historical_retention_status="Retained indefinitely, same as every other production row. No source-side retention restriction found or ruled out.",
    document_image_rights_status="N/A - LGBS's API does not publish images/documents.",
    attribution_required=False,
    rate_limit="Polite pacing already implemented (0.3s between paginated requests) - not a source-stated requirement, a courtesy. No source-stated rate limit was found (docs/lgbs-rights-audit.md Section 15).",
    robots_status="OPEN - taxsales.lgbs.com/robots.txt is exactly 'User-agent: *' with no Disallow line (confirmed live, Phase 10B). The most permissive robots.txt found for any TX source reconnoitered to date.",
    terms_status="No Terms of Use exists on taxsales.lgbs.com itself. www.lgbs.com (a different subdomain) has a legal-disclosures page with a redistribution prohibition of uncertain scope - see docs/lgbs-rights-audit.md.",
    review_date="2026-09-14",
    reviewer="Phase 10B formal rights audit (docs/lgbs-rights-audit.md)",
    notes=(
        "Shipped 2026-09-09, production-verified 2026-09-14 (Phase 10A). Formally rights-audited 2026-09-14 "
        "(Phase 10B) - see docs/lgbs-rights-audit.md for the full review. legal_status intentionally left "
        "APPROVED and unchanged by that audit: Phase 10B's hard rules forbid deactivating a production "
        "harvester based solely on this project's own interpretation, and the audit's central finding (a "
        "same-entity, different-subdomain prohibition of unresolved scope) was escalated to the user for a "
        "human decision rather than acted on unilaterally. See docs/commercial-data-inventory.md for how "
        "this status is distinguished from a formally rights-CLEARED source."
    ),
    restrictions=(),
    doc_refs=("harvesters/texas_harvester.py (module docstring)", "docs/lgbs-rights-audit.md"),
)

_TX_REALAUCTION = SourceRecord(
    source_id="tx_realauction",
    source_name="Texas RealAuction/RealForeclose county sites (sheriffsaleauctions.com / realforeclose.com)",
    state="TX",
    jurisdiction="24 counties (see data/tx_realauction_counties.csv)",
    source_url="https://<county>.texas.sheriffsaleauctions.com (or .realforeclose.com for Montgomery/Travis)",
    source_type="vendor_platform",
    official_or_vendor="vendor",
    access_method="html_calendar_plus_ajax_pagination",
    automation_status="READY - shipped and production-verified (workflow_dispatch run #128, 2026-09-14). See robots_status below for a Phase 10B finding that qualifies this.",
    legal_status=SourceStatus.APPROVED,
    commercial_use_status=(
        "PRODUCTION-PRACTICE APPROVAL, NOT FORMALLY RIGHTS-CLEARED - approval basis requires legal review "
        "(Phase 10B finding). No Terms of Use was found or reviewed for this vendor anywhere (neither on "
        "realauction.com nor any county instance - see docs/realauction-rights-audit.md Section 5); this is "
        "an absence of evidence, not evidence of absence, and is not read as permission. Compounded by the "
        "robots.txt finding in robots_status below."
    ),
    storage_status="In production use. No source-side restriction found or ruled out (nothing was reviewable - see docs/realauction-rights-audit.md).",
    customer_display_status="In production use. No source-side restriction found or ruled out.",
    redistribution_status="UNKNOWN - no Terms of Use was reachable to review (docs/realauction-rights-audit.md Section 5/10).",
    api_export_status="Not currently exposed through a customer-facing export/API distinct from the app itself.",
    historical_retention_status="Retained indefinitely, same as every other production row. No source-side restriction found or ruled out.",
    document_image_rights_status="Not confirmed either way this phase - this vendor's harvested TX fields include no image/document URLs, but this was not independently re-verified against the vendor's own terms (docs/realauction-rights-audit.md Section 13).",
    attribution_required=False,
    rate_limit="Polite pacing already implemented (0.2s between AJAX pages) - not a source-stated requirement, a courtesy. No source-stated rate limit was found (nothing was reviewable).",
    robots_status=(
        "SIGNIFICANT PHASE 10B FINDING: every fetch attempted this phase against dallas.texas."
        "sheriffsaleauctions.com, smith.texas.sheriffsaleauctions.com, and montgomery.texas.realforeclose.com "
        "(root pages, an auction-preview page, and robots.txt itself) was refused by this session's "
        "robots-respecting web-fetch tool with ROBOTS_DISALLOWED - consistently, across all 3 counties and "
        "both TX hostname patterns. The literal robots.txt text could not be obtained through any tool "
        "available this phase. harvest_realauction() uses Python's urllib.request directly and has NEVER "
        "checked robots.txt at any point in its history - this is the first time this project has looked. "
        "See docs/realauction-rights-audit.md Section 4/6 - escalated to the user, not acted on unilaterally."
    ),
    terms_status="No Terms of Use was found or reviewed for this vendor anywhere - see commercial_use_status above.",
    review_date="2026-09-14",
    reviewer="Phase 10B formal rights audit (docs/realauction-rights-audit.md)",
    notes=(
        "Shipped 2026-09-14, production-verified the same day (Phase 10A). Formally rights-audited 2026-09-14 "
        "(Phase 10B) - see docs/realauction-rights-audit.md. legal_status intentionally left APPROVED and "
        "unchanged: Phase 10B's hard rules forbid deactivating a production harvester based solely on this "
        "project's own interpretation. The robots.txt finding above is, in the auditor's own assessment, the "
        "single most actionable finding of Phase 10B - concrete and touching an already-running production "
        "source - and is escalated to the user directly rather than acted on here. See "
        "docs/commercial-data-inventory.md for how this status is distinguished from a formally "
        "rights-CLEARED source."
    ),
    restrictions=(),
    doc_refs=("harvesters/texas_harvester.py (module docstring)", "docs/realauction-rights-audit.md"),
)

_TX_HCTAX = SourceRecord(
    source_id="tx_hctax",
    source_name="Harris County Tax Assessor-Collector - hctax.net tax-sale property listing",
    state="TX",
    jurisdiction="Harris County (all 8 precincts)",
    source_url="https://www.hctax.net/Property/listings/taxsalelisting",
    source_type="government",
    official_or_vendor="official",
    access_method="http_get_html_single_page (entire dataset in one GET, no pagination requests)",
    automation_status="READY_FOR_FUTURE_IMPLEMENTATION (technical readiness only - see claude/harris-hctax-implementation-readiness.md)",
    legal_status=SourceStatus.LEGAL_REVIEW_REQUIRED,
    commercial_use_status="NO RESTRICTION FOUND; NO PERMISSION FOUND. Absence of a prohibition is explicitly not treated as permission (Phase 9.5). Twelve open rights questions recorded in claude/harris-hctax-rights-resolution-package.md; none sent to the county as of this entry.",
    storage_status="NO RESTRICTION FOUND; NO PERMISSION FOUND.",
    customer_display_status="NO RESTRICTION FOUND; NO PERMISSION FOUND.",
    redistribution_status="NO RESTRICTION FOUND; NO PERMISSION FOUND.",
    api_export_status="NO RESTRICTION FOUND; NO PERMISSION FOUND.",
    historical_retention_status="NO RESTRICTION FOUND; NO PERMISSION FOUND.",
    document_image_rights_status="Reliability disclaimer only (photos/geocoding 'not reliable, subject to change'); no reuse-rights statement found either way.",
    attribution_required=False,  # no requirement FOUND - not the same as "not required"; see notes
    rate_limit="No source-stated limit found. Recommendation only (not a confirmed requirement): no more than once daily, matching the site's own stated update cadence.",
    robots_status="MIXED/AMBIGUOUS - disallows /Property/TaxSales/ and /TaxSales/, but not the literal listing path used (/Property/listings/taxsalelisting). Treated as a technical signal only, never as a legal conclusion.",
    terms_status="No site-wide Terms of Use exists. The listing page's own clickwrap is a liability/accuracy disclaimer only - no automation/storage/commercial-use/redistribution language found in either direction.",
    review_date="2026-09-14",
    reviewer="Phase 8/9/9.5/9.6 reconnaissance (this session)",
    notes=(
        "STATUS IS INTENTIONALLY LEGAL_REVIEW_REQUIRED - do not upgrade or downgrade based on "
        "interpretation (Phase 10A Step 10's explicit instruction). Silence on hctax.net's part is never "
        "read as permission anywhere in this project's reconnaissance. Full technical readiness is "
        "separately established (see claude/harris-hctax-implementation-readiness.md) and is NOT a basis "
        "for treating this source as approved - technical accessibility and legal/commercial approval are "
        "kept strictly separate throughout every doc this entry transcribes. No harvest_hctax() function "
        "exists in harvesters/texas_harvester.py's SOURCES dict; this registry entry exists so the source "
        "is representable and its status is checkable even though nothing yet calls the gate for it."
    ),
    restrictions=(),  # no restrictions recorded because none has been confirmed to exist - NOT the same as "no restrictions apply"; legal_status alone is what blocks ingestion here
    source_version="3",  # Phase 9 (technical), Phase 9.5 (rights), Phase 9.6 (resolution package)
    change_state="under_change_review",  # awaiting a response to the Section 6 rights questions
    doc_refs=(
        "claude/county-first-fallback-reconnaissance.md",
        "claude/harris-hctax-implementation-readiness.md",
        "claude/harris-hctax-legal-commercial-gate.md",
        "claude/harris-hctax-rights-resolution-package.md",
    ),
)

_TX_PBFCM = SourceRecord(
    source_id="tx_pbfcm",
    source_name="Perdue Brandon Fielder Collins & Mott - pbfcm.com tax-sale PDFs",
    state="TX",
    jurisdiction="11 counties + Harris County (7 precincts) + 2 ISDs (see claude/pbfcm-source-reconnaissance-blocked.md)",
    source_url="https://www.pbfcm.com/taxsale.html",
    source_type="vendor_law_firm",
    official_or_vendor="vendor",
    access_method="pdf_per_jurisdiction",
    automation_status="Technically accessible (no CAPTCHA/login encountered); not otherwise evaluated further given the legal block below.",
    legal_status=SourceStatus.BLOCKED,
    commercial_use_status="PROHIBITED - disclosure.html: 'User shall not reproduce, republish, retransmit, and/or distribute any material contained on this Site' without prior written permission.",
    storage_status="PROHIBITED (same clause - covers reproduction of site material generally).",
    customer_display_status="PROHIBITED (same clause).",
    redistribution_status="PROHIBITED (same clause, explicit).",
    api_export_status="PROHIBITED (same clause).",
    historical_retention_status="Not separately addressed; moot given the blanket prohibition above.",
    document_image_rights_status="PDFs are the entire product here; covered by the same blanket prohibition.",
    attribution_required=False,
    rate_limit=None,
    robots_status="robots.txt absent (404) - not a blocking signal by itself; the Terms of Use clause is what blocks this source, independent of robots.txt.",
    terms_status="Explicit, affirmative prohibition found (disclosure.html) - stronger and more decisive than a robots.txt-only finding.",
    review_date="2026-09-14",
    reviewer="claude/pbfcm-source-reconnaissance-blocked.md",
    notes="BLOCKED. harvest_pbfcm() in harvesters/texas_harvester.py remains an architectural stub (raises NotImplementedError) - this registry entry is a second, independent layer of enforcement so that even if someone later fills in that stub without re-reading the blocked-vendor docs, the ingestion gate still rejects it.",
    restrictions=(Restriction.NO_REDISTRIBUTION, Restriction.NO_CUSTOMER_DISPLAY, Restriction.NO_API_EXPORT, Restriction.NO_DOCUMENTS),
    doc_refs=("claude/pbfcm-source-reconnaissance-blocked.md",),
)

_TX_MVBA = SourceRecord(
    source_id="tx_mvba",
    source_name="MVBA Law (mvbalaw.com / mvbataxsales.com) - Texas tax-sale listings",
    state="TX",
    jurisdiction="9 counties (see claude/mvba-source-reconnaissance-blocked.md)",
    source_url="https://www.mvbalaw.com/",
    source_type="vendor_law_firm",
    official_or_vendor="vendor",
    access_method="pdf_and_online_auction_mixed",
    automation_status="Not the deciding factor - see legal_status.",
    legal_status=SourceStatus.BLOCKED,
    commercial_use_status="PROHIBITED - see claude/mvba-source-reconnaissance-blocked.md for the full clause text.",
    storage_status="PROHIBITED (same finding class as PBFCM/CTSA).",
    customer_display_status="PROHIBITED.",
    redistribution_status="PROHIBITED.",
    api_export_status="PROHIBITED.",
    historical_retention_status="Not separately addressed; moot given the blanket prohibition.",
    document_image_rights_status="Covered by the same blanket prohibition.",
    attribution_required=False,
    rate_limit=None,
    robots_status="Not the deciding factor - see legal_status.",
    terms_status="Explicit prohibition found - see companion doc.",
    review_date="2026-09-14",
    reviewer="claude/mvba-source-reconnaissance-blocked.md",
    notes="BLOCKED. No harvest_mvba() exists anywhere in this codebase; this registry entry exists purely so the source is representable per Phase 10A Step 11.",
    restrictions=(Restriction.NO_REDISTRIBUTION, Restriction.NO_CUSTOMER_DISPLAY, Restriction.NO_API_EXPORT),
    doc_refs=("claude/mvba-source-reconnaissance-blocked.md",),
)

_TX_CTSA = SourceRecord(
    source_id="tx_ctsa",
    source_name="County Tax Sale App (CTSA) - Harris County paywalled product",
    state="TX",
    jurisdiction="Harris County",
    source_url="https://countytaxsaleapp.org/",
    source_type="vendor_product",
    official_or_vendor="vendor",
    access_method="paywalled_web_app",
    automation_status="Paywalled - not evaluated further given the legal/commercial block below.",
    legal_status=SourceStatus.BLOCKED,
    commercial_use_status="PROHIBITED - paywall plus an explicit anti-competitive-use Terms of Service clause (see claude/ctsa-source-reconnaissance.md).",
    storage_status="PROHIBITED.",
    customer_display_status="PROHIBITED.",
    redistribution_status="PROHIBITED.",
    api_export_status="PROHIBITED.",
    historical_retention_status="Not separately addressed; moot given the blanket prohibition.",
    document_image_rights_status="Not separately addressed; moot given the blanket prohibition.",
    attribution_required=False,
    rate_limit=None,
    robots_status="Not the deciding factor - see legal_status.",
    terms_status="Explicit anti-competitive-use clause found - see companion doc.",
    review_date="2026-09-14",
    reviewer="claude/ctsa-source-reconnaissance.md",
    notes="BLOCKED. Notably, CTSA republishes the SAME underlying Harris County data hctax.net publishes directly - this is why hctax.net (the first-party government source) was investigated separately rather than treated as inheriting CTSA's block (see claude/county-first-fallback-reconnaissance.md's reasoning on government-hosted vs. vendor-hosted content).",
    restrictions=(Restriction.NO_REDISTRIBUTION, Restriction.NO_CUSTOMER_DISPLAY, Restriction.NO_API_EXPORT, Restriction.OTHER_CONTRACTUAL_RESTRICTION),
    doc_refs=("claude/ctsa-source-reconnaissance.md",),
)

_TX_GOVEASE = SourceRecord(
    source_id="tx_govease",
    source_name="GovEase (liveauctions.govease.com) - Texas online tax-deed auctions",
    state="TX",
    jurisdiction="Denton, Parker, Wichita, Wise",
    source_url="https://liveauctions.govease.com/",
    source_type="vendor_platform",
    official_or_vendor="vendor",
    access_method="not fully characterized (rendered-HTML-vs-JSON-API question left open)",
    automation_status="Not the deciding factor - see legal_status.",
    legal_status=SourceStatus.BLOCKED,
    commercial_use_status="LEGAL_REVIEW_REQUIRED-grade finding treated conservatively as BLOCKED for ingestion-gate purposes - robots.txt blanket disallow (`Disallow: /`) with no locatable Terms of Use to weigh against it, per claude/govease-source-onboarding-blocked.md's own decision rule.",
    storage_status="Not evaluated further given the blocking robots.txt signal.",
    customer_display_status="Not evaluated further given the blocking robots.txt signal.",
    redistribution_status="Not evaluated further given the blocking robots.txt signal.",
    api_export_status="Not evaluated further given the blocking robots.txt signal.",
    historical_retention_status="Not evaluated further given the blocking robots.txt signal.",
    document_image_rights_status="Not evaluated further given the blocking robots.txt signal.",
    attribution_required=False,
    rate_limit=None,
    robots_status="Blanket `Disallow: /` - the deciding factor for this source, in the absence of any locatable Terms of Use.",
    terms_status="No Terms of Use page was located.",
    review_date="2026-09-14",
    reviewer="claude/govease-source-onboarding-blocked.md",
    notes="BLOCKED (registry legal_status). harvest_govease() in harvesters/texas_harvester.py remains an architectural stub (raises NotImplementedError) independent of this registry entry - two independent layers of enforcement, same as tx_pbfcm.",
    restrictions=(Restriction.NO_REDISTRIBUTION, Restriction.NO_CUSTOMER_DISPLAY, Restriction.NO_API_EXPORT),
    doc_refs=("claude/govease-source-onboarding-blocked.md",),
)

# ---------------------------------------------------------------------------
# Florida sources (registered to prove the registry is genuinely
# state-agnostic per Phase 10A Step 2 - NOT a request to re-review Florida's
# legal status, and NOT wired into any Florida harvester's actual code path;
# Florida's harvesters are PowerShell scripts entirely outside this Python
# governance package's reach, per Step 9's own instruction not to touch
# Florida's production behavior. These entries are additive documentation +
# registry data only.)
# ---------------------------------------------------------------------------

_FL_REALAUCTION = SourceRecord(
    source_id="fl_realauction",
    source_name="Florida RealAuction/RealForeclose county sites",
    state="FL",
    jurisdiction="46 counties (see data/realauction_counties.csv)",
    source_url="https://<county>.realtaxdeed.com (and sibling hosts - see data/realauction_counties.csv)",
    source_type="vendor_platform",
    official_or_vendor="vendor",
    access_method="html_calendar_plus_ajax_pagination",
    automation_status="READY - this project's longest-running, most-verified production source.",
    legal_status=SourceStatus.APPROVED,
    commercial_use_status="GRANDFATHERED - this is a long-standing production source that predates this governance framework entirely. No formal Phase-8/9.5-style redistribution-rights document exists for it. Registered APPROVED to reflect years of existing, unchallenged production use, not because a rights audit of this specific class ever happened. Flagged in docs/commercial-data-inventory.md as a backfill-review candidate, not as a reason to disrupt production.",
    storage_status="In production use.",
    customer_display_status="In production use.",
    redistribution_status="Not formally reviewed.",
    api_export_status="Not currently exposed through a customer-facing export/API distinct from the app itself.",
    historical_retention_status="Retained indefinitely, same as every other production row.",
    document_image_rights_status="Not formally reviewed.",
    attribution_required=False,
    rate_limit="Existing polite pacing in harvest_all_counties.ps1, not a source-stated requirement.",
    robots_status="Not formally reviewed.",
    terms_status="Not formally reviewed.",
    review_date="2026-09-14",
    reviewer="Phase 10A repository audit (registered for state-agnostic design proof, not re-reviewed)",
    notes="Registered so the registry is genuinely state-agnostic (Phase 10A Step 2), not just Texas-shaped. This entry does NOT change, gate, or otherwise touch Florida's actual PowerShell harvesting pipeline - nothing in that pipeline calls this Python governance package.",
    restrictions=(),
    doc_refs=(),
)

_FL_LAFT_PDFS = SourceRecord(
    source_id="fl_laft_pdfs",
    source_name="Florida Lands Available for Taxes (LAFT) - per-county PDF lists",
    state="FL",
    jurisdiction="multiple counties (see data/laft_pdf_sources.csv)",
    source_url="varies per county - see data/laft_pdf_sources.csv",
    source_type="government",
    official_or_vendor="official",
    access_method="pdf_per_jurisdiction",
    automation_status="READY - long-standing production source (scripts/harvest_laft_pdfs.py).",
    legal_status=SourceStatus.APPROVED,
    commercial_use_status="GRANDFATHERED - same caveat as fl_realauction above: long-standing production use, no formal rights-audit document exists specifically for this class. County-published LAFT lists are themselves official/government sources (not vendor-authored), which is a materially different starting posture than the blocked TX vendors, but that observation has not been formalized into a document the way Harris/hctax.net's has.",
    storage_status="In production use.",
    customer_display_status="In production use.",
    redistribution_status="Not formally reviewed.",
    api_export_status="Not currently exposed through a customer-facing export/API distinct from the app itself.",
    historical_retention_status="Retained indefinitely, same as every other production row.",
    document_image_rights_status="Not formally reviewed.",
    attribution_required=False,
    rate_limit=None,
    robots_status="Not formally reviewed.",
    terms_status="Not formally reviewed.",
    review_date="2026-09-14",
    reviewer="Phase 10A repository audit (registered for state-agnostic design proof, not re-reviewed)",
    notes="Registered for state-agnostic design proof only - see fl_realauction's notes for the same caveat, which applies here too.",
    restrictions=(),
    doc_refs=(),
)

_FL_LIENHUB_CERTIFICATES = SourceRecord(
    source_id="fl_lienhub_certificates",
    source_name="LienHub tax certificate sales",
    state="FL",
    jurisdiction="32 counties",
    source_url="varies per county - see scripts/harvest_lienhub_certificates.ps1",
    source_type="vendor_platform",
    official_or_vendor="vendor",
    access_method="html_scrape",
    automation_status="READY - production source, reliability fix shipped 2026-08-25 (see CLAUDE.md 'Certificates sync fix').",
    legal_status=SourceStatus.APPROVED,
    commercial_use_status="GRANDFATHERED - same caveat as fl_realauction above.",
    storage_status="In production use.",
    customer_display_status="In production use.",
    redistribution_status="Not formally reviewed.",
    api_export_status="Not currently exposed through a customer-facing export/API distinct from the app itself.",
    historical_retention_status="Retained indefinitely, same as every other production row.",
    document_image_rights_status="Not formally reviewed.",
    attribution_required=False,
    rate_limit=None,
    robots_status="Not formally reviewed.",
    terms_status="Not formally reviewed.",
    review_date="2026-09-14",
    reviewer="Phase 10A repository audit (registered for state-agnostic design proof, not re-reviewed)",
    notes="Registered for state-agnostic design proof only - see fl_realauction's notes for the same caveat, which applies here too.",
    restrictions=(),
    doc_refs=(),
)


SOURCE_REGISTRY: dict[str, SourceRecord] = {
    r.source_id: r
    for r in (
        _TX_LGBS,
        _TX_REALAUCTION,
        _TX_HCTAX,
        _TX_PBFCM,
        _TX_MVBA,
        _TX_CTSA,
        _TX_GOVEASE,
        _FL_REALAUCTION,
        _FL_LAFT_PDFS,
        _FL_LIENHUB_CERTIFICATES,
    )
}


def get_source(source_id: str) -> SourceRecord | None:
    """Look up one registry entry. Returns None for an unknown source_id -
    callers (see gate.py) must treat that as fail-closed LEGAL_REVIEW_REQUIRED,
    never as approved. Deliberately does NOT raise KeyError, so a caller
    cannot accidentally let an unhandled exception skip the gate check
    entirely (fail-open by accident) - a missing source is ordinary,
    checkable data (`None`), not an exceptional code path."""
    return SOURCE_REGISTRY.get(source_id)


def all_sources(*, state: str | None = None) -> list[SourceRecord]:
    """List every registered source, optionally filtered by state - used by
    docs generation and by the test suite; not itself part of the
    enforcement path."""
    values = list(SOURCE_REGISTRY.values())
    if state is not None:
        values = [r for r in values if r.state == state]
    return sorted(values, key=lambda r: r.source_id)
