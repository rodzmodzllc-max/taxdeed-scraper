# Florida data map (67 counties)

**Status:** Phase 37/38, 2026-09-16. Computed directly from `data/fl_county_coverage_matrix.csv` (Phase 33/35) and `harvesters/governance/verification.py`/`data/fl_verification_map.csv` (this phase) - every number below is a real `len()`/`sum()` over live repository data, not an estimate. See `docs/two-state-data-architecture.md` for what DISCOVERED/VERIFIED/ACQUIRED/AUTHORIZED/PRODUCTION_ENABLED each mean.

## 1. County readiness (Section 22 vocabulary), all 67/67 counties

| Readiness state | Count |
|---|---|
| `PRODUCTION_READY` (at least one real, currently-allowed `CUSTOMER_DISPLAY` decision) | 47 |
| `PARTIALLY_COVERED` (some categories known, none currently production-enabled) | 19 |
| `SOURCE_DISCOVERED` | 1 |
| `NO_SOURCE_IDENTIFIED` | 0 |

**Reading this correctly**: `PRODUCTION_READY` here means "at least one of `fl_realauction`/`fl_lienhub_certificates`/`fl_laft_pdfs` is currently allowed for `CUSTOMER_DISPLAY` in that county" - for the 47 counties in this bucket, that is overwhelmingly `fl_laft_pdfs` (zero `ProviderAuthorization` records, today's unmodified production no-op path), **not** a claim that `fl_realauction`/`fl_lienhub_certificates` have been cleared. Every county with an `fl_realauction`/`fl_lienhub_certificates` source is independently denied for those two sources' own `CUSTOMER_DISPLAY` promotion (see Section 3 below) - this bucket only requires ONE allowed source, and never implies all of a county's sources are enabled.

## 2. Source coverage by category (existing Phase 35 `gap_analysis()`, unchanged this phase)

| Category | Counties with a known source |
|---|---|
| Auction (`fl_realauction`) | 46 / 67 |
| Tax certificate (`fl_lienhub_certificates` + other platforms) | 66 / 67 |
| LAFT deed list (`fl_laft_pdfs`) | 47 / 67 |
| Property Appraiser (individually verified) | 12 / 67 |
| No known source in ANY category | 1 / 67 |

## 3. Production status of the three registered Florida sources, today

| Source | Verification | Technical acquisition | Authorization records | `CUSTOMER_DISPLAY` production status |
|---|---|---|---|---|
| `fl_realauction` | `CONTENT_VERIFIED` | `ACQUIRED` (continuous production) | Alachua, Volusia (`LEGAL_REVIEW_REQUIRED`) | **Denied** for Alachua/Volusia (explicit record); denied for every OTHER county too (Phase 37 Step 3: any authorization record anywhere holds the whole source_id to the strict per-county standard) |
| `fl_lienhub_certificates` | `CONTENT_VERIFIED` | `ACQUIRED` (continuous production) | Grant Street Group, provider-wide (`LEGAL_REVIEW_REQUIRED`) | **Denied** for every county (provider-wide record, `UNKNOWN` per-county in the strict lookup - see `test_02`) |
| `fl_laft_pdfs` | `CONTENT_VERIFIED` | `ACQUIRED` (continuous production) | None | **Allowed** for every one of its 47 covered counties (Phase 37's existing, unmodified no-op path) |

This is the honest, current state of Florida customer-facing production: text/PDF-derived LAFT deed data is unblocked by the gate; the two vendor-platform sources (RealAuction, LienHub) - which supply most of what the frontend actually displays today (bid, assessed value, certificate numbers) - are `LEGAL_REVIEW_REQUIRED` under the real per-use gate, running in production only because that gate is not yet wired into Florida's PowerShell pipeline (Section 4 below, unchanged from Phase 37).

## 4. Florida's real, unresolved enforcement gap (restated from Phase 37, not newly changed)

Florida's harvesters (`scripts/harvest_all_counties.ps1`, `scripts/harvest_lienhub_certificates.ps1`, `scripts/harvest_laft_pdfs.py`'s siblings, all the `sync-*-to-supabase.ps1` scripts) have **zero coupling** to `harvesters.governance` - confirmed again this phase by the same inspection Phase 37 performed. `can_promote_source_for_use()`'s real denial for `fl_realauction`/`fl_lienhub_certificates` above is therefore **not enforced today** - the PowerShell pipeline does not call it. This phase did not attempt an unsafe cross-language workaround (per this project's standing rule); it is restated here because Section 39 of this phase's instructions require the application to let a user "understand ... whether it's production-enabled" honestly, and the honest answer for these two sources is "the gate says no, but nothing currently checks."

## 5. Florida statewide sources (Section 7)

`fl_dor_statewide` (Florida DOR's NAL/NAP assessment rolls, sales files, GIS) remains `LEGAL_REVIEW_REQUIRED`, `MECHANISM_CONFIRMED` (direct-download links located, Phase 33), `NOT_ACQUIRED` (no file has ever actually been downloaded or parsed by this project). It is the single highest-leverage Florida gap-filler identified to date - one source, all 67 counties, currently free, Chapter 119 public-records basis - and remains entirely unimplemented. See `docs/vendor-acquisition.md` Section 2 for why it is tracked as a government source, not a vendor.

## 6. Known Florida gaps (none newly invented this phase)

- 35 of 67 counties have no LAFT harvester coverage (Phase 33.5, unchanged).
- 55 of 67 counties have no individually-verified Property Appraiser URL (Phase 35, unchanged).
- No auction-event history exists for any Florida county - a re-offered or postponed sale silently overwrites the prior row (`docs/production-data-contract.md` limitation #3).
- `fl_dor_statewide` remains entirely unimplemented (Section 5 above).

See `data/fl_verification_map.csv` for the full 335-row (67 counties x 5 tracked categories) machine-readable detail this document summarizes.
