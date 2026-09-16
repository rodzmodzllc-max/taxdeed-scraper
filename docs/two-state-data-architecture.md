# Two-state data architecture: discovery, verification, technical acquisition, authorization, production

**Status:** Phase 37/38 (Two-State Verification Build), 2026-09-16. Companion to `docs/provider-authorization.md` (the legal/commercial authorization model, Phase 34A/34B/37), `docs/source-registry.md` (the whole-source ingestion gate, Phase 10A), and `docs/data-licensing.md` (restriction enforcement). This page is the one about the **engineering-progress axis** those documents deliberately do not cover: how far has this project actually gotten in finding, inspecting, and pulling data from a source, kept strictly separate from whether that data may be shown to a customer.

## 1. Why this document exists

Every governance document through Phase 37 answers a legal/commercial question. None of them answer "have we actually looked at this source, and did we get real data out of it." Phase 37/38's own framing makes this gap explicit: a source can be `LEGAL_REVIEW_REQUIRED` (an authorization question) while simultaneously being the single most **technically mature, most heavily verified, most continuously operated** source in the entire platform (`fl_realauction` is the literal, current example - a multi-year production harvester with an unresolved EULA). Conflating those two facts in either direction is an error this document exists to make structurally impossible.

## 2. The five states, exactly as required

| State | Question it answers | Where it lives |
|---|---|---|
| **DISCOVERY** | Does a source exist for this county/category at all? | `harvesters/governance/source_catalog.py` (`CatalogSource`, the FL/TX coverage matrices) and `harvesters/governance/verification.py` (`DiscoveryStatus`) |
| **VERIFICATION** | Has this project actually inspected what the source returns? | `harvesters/governance/verification.py` (`VerificationStatus`: `UNVERIFIED` / `MECHANISM_CONFIRMED` / `CONTENT_VERIFIED` / `STALE`) |
| **TECHNICAL ACQUISITION** | Has this project successfully pulled real data through a permitted, tested method? | `harvesters/governance/verification.py` (`TechnicalAcquisitionStatus`: `NOT_ACQUIRED` / `ACQUIRABLE_UNTESTED` / `ACQUIRED` / `ACQUISITION_BLOCKED_TECHNICAL`) |
| **AUTHORIZATION** | Is a specific use, for a specific source/county, actually permitted? | `harvesters/governance/authorization.py` (Phase 34A/34B, unchanged) |
| **PRODUCTION** | May this source/use combination actually feed the customer-facing system, right now? | `harvesters/governance/promotion.py`'s `can_promote_source_for_use()` (Phase 37, unchanged) - always computed live, never stored |

Each state is a **separate dataclass/enum, in a separate module, with zero field-name overlap on the legal/commercial axis** (enforced by `tests/python/test_phase37_38_verification_model.py::test_01`). A source moving forward on one axis never advances any other axis automatically - `SourceVerificationRecord.production_status_for()` is the *only* place engineering-progress data and production status meet, and it does so by calling Phase 37's real gate, never by asserting its own opinion.

## 3. The concrete case that makes the distinction real

`fl_realauction` (Alachua County), read directly from this repository's own data:

| Axis | Value | Source |
|---|---|---|
| Discovery | `DISCOVERED` | `harvesters/governance/registry.py` |
| Verification | `CONTENT_VERIFIED` | `scripts/harvest_all_counties.ps1`, years of production runs |
| Technical acquisition | `ACQUIRED` | Same - real rows harvested twice daily |
| Authorization (`CUSTOMER_DISPLAY`, Alachua) | `LEGAL_REVIEW_REQUIRED` | RealAuction EULA on file, `harvesters/governance/authorization.py` |
| Production (`CUSTOMER_DISPLAY`, Alachua) | **DENIED** | `can_promote_source_for_use("fl_realauction", "CUSTOMER_DISPLAY", county="Alachua")` |

Same county, same row, `fl_laft_pdfs` for the LAFT deed-list category:

| Axis | Value |
|---|---|
| Discovery | `DISCOVERED` |
| Verification | `CONTENT_VERIFIED` |
| Technical acquisition | `ACQUIRED` |
| Authorization | No `ProviderAuthorization` record exists |
| Production (`CUSTOMER_DISPLAY`) | **ALLOWED** (today's existing, unmodified production no-op path - Phase 37 Section 22) |

Two sources, same county, same technical maturity - opposite production outcomes, because authorization is a genuinely separate fact. This is not a hypothetical; it is `data/fl_verification_map.csv`'s actual Alachua rows (Section 6 below).

## 4. Source substitution and fallback (Sections 11-12)

Nothing in this project's normalized property model (`public.properties`, `TexasSaleRow`) is keyed to a single provider. `PROMOTION_USE_TO_SCOPE_DIMENSION` and `SOURCE_REGISTRY` both index by `source_id`, and a county's actual sources are looked up by scanning the coverage matrix's free-text description columns (`harvesters/governance/verification.py`'s `_source_ids_named_for_county()`), not hard-coded per county. This means a future source can be substituted for an existing one (e.g. a licensed CAD vendor replacing `enrich_property_details_tx.py`'s stubbed per-CAD fetchers) by adding a `SourceRecord`/`CatalogSource` entry and updating the relevant matrix cell - no change to the property model itself.

The fallback ordering Section 12 describes (PRIMARY -> SECONDARY OFFICIAL -> AUTHORIZED PROVIDER -> MANUAL/PUBLIC-RECORD -> LINK-ONLY) is represented today by `source_catalog.py`'s existing `SourcePriorityTier` enum (`PRIMARY`/`SECONDARY`/`FALLBACK`/`LINK_ONLY`/`RESTRICTED`, Phase 35) - this phase does not introduce a second tiering vocabulary. **No automatic fallback execution exists or was built this phase** - a fallback source must independently satisfy its own promotion decision; nothing in this codebase silently substitutes an unapproved source when a preferred one is unavailable.

## 5. What this phase did NOT build (explicit, not silent)

- No live re-verification of the ~9 data categories across all 321 counties. Every `SourceVerificationRecord` in `SOURCE_VERIFICATION_RECORDS` transcribes findings this project already published in Phases 8-37; none reflects new web research performed this session (see `claude/phase-37-38-two-state-verification-build.md` Section 15 for the honest count of how much of the category space remains `UNVERIFIED`).
- No auction-event-history schema (Section 16-17) - the current `public.properties` table has no migration path for multiple historical states of one auction; this is documented as a known gap (`docs/production-data-contract.md` limitation #3), not newly resolved.
- No frontend changes (Sections 18-21, 28) - `public/app.js` was read, not modified, this phase.

See `docs/florida-data-map.md`, `docs/texas-data-map.md`, `docs/vendor-acquisition.md`, and `docs/verification-vs-commercial.md` for the state-specific and commercialization-track detail this document intentionally keeps out.
