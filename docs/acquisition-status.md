# Acquisition status

**Status:** Phase 39, 2026-09-16. What this platform can technically acquire today, measured. Companion to `docs/florida-acquisition.md` and `docs/texas-acquisition.md`.

## 1. The honest headline

**No production acquisition run was performed in Phase 39.** Every `records_acquired` figure in `data/fl_acquisition_map.csv` and `data/tx_acquisition_map.csv` is `0`, and every `coverage_percentage` is blank.

Two independent reasons, both real:

1. **The sandbox cannot reach any source host.** An organization egress policy returns `403 Forbidden` at the proxy for every property-data host. The engine records this as `ENVIRONMENT_EGRESS_BLOCKED` — deliberately distinct from a source-level refusal, because it says nothing about the source (see `docs/acquisition-engine.md` §2).
2. **Most sources are not authorized for production acquisition anyway.** `fl_realauction`, `fl_lienhub_certificates`, `fl_dor_statewide` and `tx_hctax` are all denied by the Phase 37 promotion gate. That denial is correct and unchanged.

A source directory is not acquired data. A successful contract check is not coverage. One verified county is not a state. Those distinctions are the whole reason this document exists.

## 2. Technical acquisition state, by state

Computed from `data/fl_acquisition_map.csv` / `data/tx_acquisition_map.csv`.

### Florida — 226 county-source rows, 67 counties

| Technical state | Rows |
|---|---|
| `TECHNICAL_ACQUISITION_SUCCESS` (existing production harvesters, pre-dating this phase) | 159 |
| `TECHNICAL_ACQUISITION_READY` (new adapter implemented and contract-verified this phase) | 67 |

| Production status | Rows |
|---|---|
| `NOT_ENABLED` | 179 |
| `ENABLED` | 47 |

Internal technical testing is permitted for **all 226** rows: no Florida source carries an affirmative prohibition, so every open question there is commercial rather than a found block.

### Texas — 257 county-source rows, 254 counties

| Technical state | Rows |
|---|---|
| `DISCOVERED` (no acquisition mechanism identified) | 225 |
| `TECHNICAL_ACQUISITION_SUCCESS` (existing `tx_realauction` production harvester) | 24 |
| `TECHNICAL_ACQUISITION_READY` (new `LgbsAdapter`) | 8 |

| Production status | Rows |
|---|---|
| `NOT_ENABLED` | 225 |
| `ENABLED` | 32 |

Internal technical testing is permitted for 32 rows and refused for 225 — the refusals are counties with no identified source at all, plus the four `BLOCKED` vendors, which testing does not unlock.

## 3. Reading `production_status = ENABLED` correctly

47 Florida rows and 32 Texas rows show `ENABLED`. That means the Phase 37 promotion gate currently allows `CUSTOMER_DISPLAY` for that specific source in that specific county. In Florida it is almost entirely `fl_laft_pdfs` (the only Florida source with no `ProviderAuthorization` record, so it remains on the pre-existing production no-op path); in Texas it is `tx_lgbs` and `tx_realauction`, neither of which has an authorization record either.

It does **not** mean the data has been acquired, that coverage has been measured, or that the remaining sources for that county are usable. A county row showing `ENABLED` for one source and `NOT_ENABLED` for three others is the normal case, and is exactly the granularity this map exists to preserve.

## 4. Source health

`SourceHealth` tracks attempts, successes, failures, blocked attempts, records seen/acquired/failed, last attempt, last success, mean latency, and a schema-change signal derived from payload hashes. It deliberately carries **no** authorization field — Section 36's "do not confuse source health with legal approval." A source can be perfectly healthy and entirely unauthorized; `fl_realauction` is exactly that today.

`last_success` only advances for a result that actually produced records. A `NO_DATA` result updates `last_attempt` and leaves `last_success` alone, so a source that has been quietly returning nothing for weeks cannot look fresh.

## 5. Missing-data classification

Every absent value is classifiable, never a bare `NULL`: `NOT_APPLICABLE`, `NOT_AVAILABLE_AT_SOURCE`, `SOURCE_NOT_FOUND`, `SOURCE_UNAVAILABLE`, `TECHNICAL_FAILURE`, `TEMPORARILY_UNAVAILABLE`, `LEGAL_RESTRICTION`, `NOT_YET_ACQUIRED`, `MISSING_FROM_RECORD`.

The mapping from acquisition outcome to reason lives in one place (`ACQUISITION_STATUS_TO_MISSING_REASON`), so Section 34's explicit warning — never classify a legally restricted field as an ordinary technical failure — is enforced once rather than at each call site. A test asserts the two never collapse.

## 6. What would change these numbers

Running the engine from an environment with real outbound access — GitHub Actions, where this project's harvesters already run — against the two implemented adapters, for the source/county pairs whose policy currently allows acquisition. That is a scheduling and environment question, not an engineering one: the adapters are built, contract-verified and tested.
