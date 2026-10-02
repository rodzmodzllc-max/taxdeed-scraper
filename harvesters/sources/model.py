"""One source model for every enrichment / availability / acquisition source
(all-sources enrichment engine, 2026-10-01).

The repository already records sources in several places, each with its own
vocabulary:

  * data/county_source_registry.csv - inventory lists, publication_status
    APPROVED / APPROVED_GRANDFATHERED / UNREVIEWED / RESTRICTED / BLOCKED;
  * harvesters/enrichment/sources.py - statewide / county parcel layers,
    publication_status in the same vocabulary;
  * data/purchase_path_evidence*.csv - verified official acquisition pages;
  * data/acquisition_candidate_pages.csv - official pages still to verify;
  * the federal datasets the enrichers call (FEMA NFHL, USDA NAIP, Census).

This module puts all of them in ONE shape, `UnifiedSource`, with ONE
governance vocabulary:

  APPROVED         known acceptable for the current collection / publication
                   scope; its verified values may be written to customer
                   fields.
  REVIEW_REQUIRED  potentially usable; permission, terms, commercial-use
                   rights, attribution, access or publication scope need a
                   review. It stays visible to Admin with the reason and a
                   next action. It may be READ for discovery / verification
                   counts; it never writes a customer-visible field.
  HARD_BLOCKED     prohibited under the project's rules and not curable by a
                   review; never accessed.

Governance is a DIMENSION of a source, never the organising principle of the
enrichment: one source needing review never stops another source from being
used (see scripts/enrich_available.py).

Nothing here makes a legal decision. The mapping from the older vocabularies
is mechanical, and every override carries its documented basis.
"""
from __future__ import annotations

from dataclasses import dataclass, field

GOVERNANCE = ("APPROVED", "REVIEW_REQUIRED", "HARD_BLOCKED")

# What kind of publisher / artefact a source is (Part 3-8 of the brief).
SOURCE_TYPES = (
    "GOVERNMENT",            # county / state office web page or list
    "DOCUMENT",              # an official PDF / spreadsheet / notice document
    "GIS",                   # parcel / cadastral layer (ArcGIS, Socrata, download)
    "COURT_PUBLIC_RECORD",   # dockets, clerk / sheriff notices, recorded documents
    "PUBLIC_NOTICE",         # legal notices, newspaper notice sites, classifieds
    "AUCTION_VENDOR",        # sale platforms (RealAuction, LienHub, ...)
    "THIRD_PARTY",           # counsel / aggregator listings (LGBS, ...)
    "FEDERAL_DATASET",       # FEMA NFHL, USDA NAIP, Census geocoder
)

# What a source can be used for.
ROLES = ("availability", "identity", "assessment", "legal", "acreage", "land_use", "coordinates",
         "imagery", "flood", "acquisition", "lifecycle", "source_date", "discovery")

# Access as last observed (never a guess).
ACCESS = (
    "ACCESSIBLE",            # read successfully by a runner
    "SOURCE_UNAVAILABLE",    # refused / unreachable for the runner (403, proxy, timeout)
    "NOT_CHECKED",           # recorded, not yet read
    "NOT_ACCESSED_BLOCKED",  # HARD_BLOCKED: never requested
)

# Per (property, dimension) outcome vocabulary (Part 14 of the brief).
OUTCOMES = (
    "NO_SOURCE_FOUND", "SOURCE_FOUND", "SOURCE_REVIEW_REQUIRED", "SOURCE_HARD_BLOCKED", "SOURCE_EMPTY",
    "SOURCE_UNAVAILABLE", "SOURCE_PARSE_FAILED", "MATCH_FAILED", "MATCHED", "ENRICHED", "PARTIALLY_ENRICHED",
    "VERIFIED_AVAILABLE", "NOT_VERIFIED_AVAILABLE",
)

NATIONAL = "NATIONAL"     # a source covering every state
STATEWIDE = "STATEWIDE"   # a source covering every county of one state

# The older vocabularies -> the unified one. RESTRICTED is a reviewed
# restriction, which a further review (or permission) can lift: REVIEW_REQUIRED.
_PUBLICATION_TO_GOVERNANCE = {
    "APPROVED": "APPROVED", "APPROVED_GRANDFATHERED": "APPROVED",
    "UNREVIEWED": "REVIEW_REQUIRED", "RESTRICTED": "REVIEW_REQUIRED", "": "REVIEW_REQUIRED",
    "BLOCKED": "HARD_BLOCKED",
}

# Documented overrides: a source running in production under a grandfathered
# approval whose own formal rights audit found an open, LEGAL_REVIEW_REQUIRED-
# grade finding. The registry's publication decision for rows already served
# is NOT changed here (docs/commercial-data-inventory.md: production behaviour
# unchanged); the unified model just refuses to call the source cleared.
REVIEW_OVERRIDES = {
    "tx_lgbs": "grandfathered production source; docs/lgbs-rights-audit.md (Phase 10B) found a firm-wide "
               "reproduction/redistribution clause whose scope over taxsales.lgbs.com is unresolved "
               "(LEGAL_REVIEW_REQUIRED). Existing rows stay published under the registry decision.",
    "tx_realauction": "grandfathered production source; docs/realauction-rights-audit.md (Phase 10B) recorded a "
                      "platform-wide robots-disallow signal and no reviewed Terms of Use (LEGAL_REVIEW_REQUIRED).",
}


def governance_from_publication(publication_status: str | None, *, source_id: str = "") -> tuple[str, str]:
    """(unified governance, reason) for a registry / parcel-config publication value."""
    pub = (publication_status or "").strip().upper()
    if source_id in REVIEW_OVERRIDES and pub != "BLOCKED":
        return "REVIEW_REQUIRED", REVIEW_OVERRIDES[source_id]
    gov = _PUBLICATION_TO_GOVERNANCE.get(pub, "REVIEW_REQUIRED")
    reason = {
        "APPROVED": "publication approved after review",
        "APPROVED_GRANDFATHERED": "served to customers before the publication gate; carried forward",
        "UNREVIEWED": "no publication / reuse review recorded yet",
        "RESTRICTED": "reviewed and restricted (see the registry restrictions column)",
        "BLOCKED": "blocked vendor under the project's source rules",
        "": "no publication decision recorded",
    }.get(pub, f"unrecognised publication status {pub!r}")
    return gov, reason


@dataclass(frozen=True)
class UnifiedSource:
    source_id: str
    state: str                    # two-letter code, or NATIONAL
    county: str                   # county / parish name, STATEWIDE or NATIONAL
    name: str
    publisher: str
    source_type: str              # SOURCE_TYPES
    url: str
    roles: frozenset = field(default_factory=frozenset)
    governance: str = "REVIEW_REQUIRED"
    governance_reason: str = ""
    access: str = "NOT_CHECKED"
    access_note: str = ""
    evidence: str = ""            # where the governance / access facts were read
    last_checked: str = ""
    next_action: str = ""
    origin: str = ""              # registry | parcel_config | evidence | candidate | builtin | catalog
    legacy_status: str = ""       # the value in the older vocabulary, verbatim

    def __post_init__(self) -> None:
        if self.governance not in GOVERNANCE:
            raise ValueError(f"{self.source_id}: governance {self.governance!r}")
        if self.source_type not in SOURCE_TYPES:
            raise ValueError(f"{self.source_id}: source_type {self.source_type!r}")
        if self.access not in ACCESS:
            raise ValueError(f"{self.source_id}: access {self.access!r}")
        unknown = set(self.roles) - set(ROLES)
        if unknown:
            raise ValueError(f"{self.source_id}: unknown roles {sorted(unknown)}")
        if self.governance == "HARD_BLOCKED" and self.access not in ("NOT_ACCESSED_BLOCKED",):
            raise ValueError(f"{self.source_id}: a HARD_BLOCKED source is never accessed")
        if self.governance != "APPROVED" and not self.governance_reason:
            raise ValueError(f"{self.source_id}: {self.governance} needs a reason")

    # ---- what the engine may do with it --------------------------------
    @property
    def may_access(self) -> bool:
        """May a runner request it at all (discovery, verification, enrichment)?"""
        return self.governance != "HARD_BLOCKED"

    @property
    def may_write(self) -> bool:
        """May its verified values be written to customer-visible fields?"""
        return self.governance == "APPROVED"

    def covers(self, state: str, county: str) -> bool:
        if self.state == NATIONAL:
            return True
        if self.state != state:
            return False
        return self.county in (STATEWIDE, county)

    def as_dict(self) -> dict:
        return {"source_id": self.source_id, "state": self.state, "county": self.county, "name": self.name,
                "publisher": self.publisher, "source_type": self.source_type, "url": self.url,
                "roles": sorted(self.roles), "governance": self.governance, "governance_reason": self.governance_reason,
                "access": self.access, "access_note": self.access_note, "evidence": self.evidence,
                "last_checked": self.last_checked, "next_action": self.next_action, "origin": self.origin,
                "legacy_status": self.legacy_status}
