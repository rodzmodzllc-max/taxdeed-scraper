# Vendor acquisition placeholder and process

**Status:** Phase 37/38, 2026-09-16. Implements Sections 25-26 and 37 of this phase's instructions: a clean architectural place to track future commercial vendor relationships, and a factual (not evaluative) gap analysis of where a vendor could fill a coverage gap. **No vendor was purchased, contacted, or accepted this phase.** No account was created. No terms were accepted on this project's behalf.

## 1. The data model

`harvesters/governance/verification.py`'s `VendorCandidate` dataclass, seeded in `VENDOR_CANDIDATES` (7 entries, all vendors this project already found through Phases 9/10A/10B/33.5/34A reconnaissance - none newly searched for this phase):

`vendor_id`, `vendor_name`, `product`, `states`, `counties`, `categories`, `fields`, `api_available`, `bulk_available`, `historical_available`, `pricing_notes`, `license_notes`, `commercial_use_status`, `customer_display_status`, `export_status`, `api_redistribution_status`, `storage_status`, `retention_notes`, `images_status`, `documents_status`, `contract_status`, `authorization_status`, `contact_status`, `reviewed_at`, `notes` - exactly Section 25's field list.

Two of the seven (`grant_street_lienhub`, `realauction`) are vendors this project **already has a production relationship with** - they are tracked here too, deliberately, so the same commercialization process (Section 3 below) applies to resolving their existing `LEGAL_REVIEW_REQUIRED` status as would apply to onboarding a brand-new vendor. The other five (`lgbs`, `pbfcm`, `mvba`, `ctsa`, `govease`) cover the remaining Texas vendor landscape found in Phases 9/10A.

Every seeded candidate's `contract_status` is `NOT_CONTACTED` or `EXISTING_RELATIONSHIP_UNRESOLVED` - never `CONTRACT_EXECUTED` (enforced by `test_18_vendor_candidates_never_claim_contract_executed_this_phase`).

## 2. Vendor gap analysis (Section 26), factual, not evaluative

Using the coverage counts in `docs/florida-data-map.md`/`docs/texas-data-map.md`:

**Florida:** Property Appraiser individually verified for 12/67 counties; auction source known for 46/67; tax-certificate source known for 66/67; LAFT deed list known for 47/67. The largest concrete gap a commercial or official-government provider could fill is the 55/67 counties without an individually-verified Property Appraiser page - `fl_dor_statewide` (a government source, Section 5 of `docs/florida-data-map.md`) is the highest-coverage candidate for closing that gap in one pass, ahead of any commercial vendor, because it is a single source spanning all 67 counties rather than a per-county integration.

**Texas:** Auction source known for 42/254 counties; appraisal district individually verified for 42/254; the Comptroller directory mechanism exists for all 254 but only 42 have been extracted. The largest gap is the 212/254 counties with no auction-source finding at all. No statewide auction aggregator equivalent to Florida's RealAuction/LienHub concentration was found in this project's own prior reconnaissance (Phases 9/10A) - Texas's auction landscape is genuinely fragmented across `tx_realauction` (24 counties), `tx_lgbs` (statewide multi-county, exact roster not fully re-extracted), and several BLOCKED law-firm vendors (`tx_pbfcm`, `tx_mvba`) each covering a handful of counties.

**Known government alternatives** (not yet integrated): `fl_dor_statewide` (FL, statewide); `tx_comptroller_directory` (TX, statewide directory only - not itself a data source); `tx_hctax` (Harris County, government-hosted, `LEGAL_REVIEW_REQUIRED`, technically ready).

**Known licensed-provider candidates** (already discovered, all currently `BLOCKED`/`LEGAL_REVIEW_REQUIRED`): the five vendor entries in Section 1. No vendor is recommended as legally usable here - none of their terms currently support that conclusion (`SOURCE_REGISTRY`'s own `legal_status` for each is unchanged by this phase).

## 3. The vendor process (Section 37), documented not executed

1. Identify gap (Section 2 above, this document).
2. Identify candidate provider (`VENDOR_CANDIDATES`, this document).
3. Request API/demo/documentation - **not performed this phase for any vendor**.
4. Request commercial terms - not performed.
5. Request redistribution/customer-display rights - not performed. (`docs/provider-authorization-requests.md`, from an earlier phase, already contains a drafted-but-unsent LienHub request; nothing was sent this phase either.)
6. Review contract - not applicable; nothing was requested.
7. Record authorization - would be written to `harvesters/governance/authorization.py`'s `PROVIDER_AUTHORIZATIONS`, exactly the existing Phase 34A structure. No new record was added this phase.
8. Technical integration - would reuse the existing `SourceRecord`/harvester pattern (`docs/production-data-contract.md` Section 22's "future source onboarding contract," unchanged).
9. Production enablement - automatic and mechanical once step 7 exists: `can_promote_source_for_use()` would pick up the new authorization record without any code change, because it already checks `authorizations_for_source()` live (Phase 37's own design goal, restated in Section 40 of this phase's instructions: "when permission arrives, the source should become usable through configuration/authorization rather than requiring an architectural rewrite").

This project is **not being sold or marketed commercially at this time** (Section 37's own framing) - this document exists so that future commercial work has a ready, structured home, not because any commercial process is underway.
