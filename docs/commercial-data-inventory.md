# Commercial data inventory

**Status:** Phase 10A (Commercial Source Governance Infrastructure), 2026-09-14. This is the summary/audit page — `docs/source-registry.md` has the per-source detail, `docs/data-licensing.md` has the enforcement model, `docs/data-provenance.md` has the lineage model. This page exists so "what data does this product actually use commercially, and under what status" has one place to check without reading all three.

## Inventory by state

### Texas

| source_id | legal_status | in production today? | harvester exists? |
|---|---|---|---|
| `tx_lgbs` | `APPROVED` | Yes | `harvest_lgbs()` |
| `tx_realauction` | `APPROVED` | Yes | `harvest_realauction()` |
| `tx_hctax` (Harris County) | `LEGAL_REVIEW_REQUIRED` | No | None (no `harvest_hctax()` exists anywhere in this codebase) |
| `tx_pbfcm` | `BLOCKED` | No | Architectural stub only (`harvest_pbfcm()` raises `NotImplementedError`) |
| `tx_govease` | `BLOCKED` | No | Architectural stub only (`harvest_govease()` raises `NotImplementedError`) |
| `tx_mvba` | `BLOCKED` | No | None |
| `tx_ctsa` | `BLOCKED` | No | None |

### Florida

| source_id | legal_status | in production today? | notes |
|---|---|---|---|
| `fl_realauction` | `APPROVED` (grandfathered) | Yes | PowerShell (`harvest_all_counties.ps1`), not this Python governance package |
| `fl_laft_pdfs` | `APPROVED` (grandfathered) | Yes | Python (`scripts/harvest_laft_pdfs.py`), doesn't import `harvesters.governance` |
| `fl_lienhub_certificates` | `APPROVED` (grandfathered) | Yes | PowerShell (`scripts/harvest_lienhub_certificates.ps1`) |

Florida also runs several other harvesters not individually registered this phase (`harvest_laft_html.py`, `harvest_laft_realtdm.py`, and the six county-specific LAFT scripts — Hillsborough/Leon/Orange/Osceola/St. Lucie/Pioneer-counties). They are out of scope for this phase's registry population (three representative entries were enough to prove state-agnostic design, per Phase 10A Step 2) and, like every other Florida script, are untouched by and unaware of this governance package.

## What "commercial use" means for each status, in one line

- **`APPROVED`** — this project treats itself as cleared to retrieve, store, normalize, combine, derive from, display to customers, and (subject to no other restriction) export this source's data.
- **`APPROVED_WITH_RESTRICTIONS`** — cleared, but specific `Restriction` values apply (see `docs/data-licensing.md`) and must be enforced, not just noted.
- **`LEGAL_REVIEW_REQUIRED`** — nothing beyond a human manually reading the public page is cleared; the ingestion gate rejects any automated retrieval attempt.
- **`BLOCKED`** — an explicit prohibition was found; same enforcement result as `LEGAL_REVIEW_REQUIRED` today (both are simply "not in `INGESTION_ALLOWED_STATUSES`"), but recorded with a different, more specific reason.

## Test coverage

`tests/python/test_source_governance.py` — 25 tests, all passing as of this phase (`pytest tests/python/`, 0.13s). Covers every scenario Phase 10A Step 12 lists by number (1 through 14), plus additional fail-closed guarantees for Step 14's security review. See `docs/data-licensing.md`'s "Fail-closed guarantees" section for what each of the extra tests actually protects against.

**Not wired into CI.** `.github/workflows/` was deliberately left untouched this phase (Phase 10A's own Step 16 instruction not to dispatch a production workflow merely to test this work, plus a conservative reading of "do not change production behavior unnecessarily" extending to not modifying workflow YAML at all in this pass). Concretely: `pytest tests/python/` must be run locally (or added to a workflow in a dedicated, reviewed follow-up) before trusting a future change to `harvesters/governance/` or its two call sites. This is a real, named gap — see "Remaining risks" in `docs/data-licensing.md` and `docs/data-provenance.md`.

## Regression verification (Phase 10A Step 9 / Step 13)

Performed without dispatching any production workflow or making any network call to a live vendor (Step 16):

- **`git diff harvesters/texas_harvester.py`** — confirms the only change is inside `main()`: a gate check inserted before each `harvest_*()` call, plus an updated docstring. `harvest_lgbs()`, `harvest_realauction()`, `harvest_pbfcm()`, `harvest_govease()`, `TexasSaleRow`, and the `SOURCES` dict itself are byte-for-byte unchanged.
- **`test_14_lgbs_and_realauction_unchanged_and_approved`** — asserts `SOURCES` still has exactly its original 4 keys mapped to functions of the original names, asserts `TexasSaleRow`'s field set is exactly its original 13 fields (a hard-coded snapshot, so any future accidental field addition/removal to that dataclass fails this test immediately), and asserts both production sources gate-pass as `APPROVED`.
- **`test_florida_sources_registered_for_state_agnostic_design_but_untouched`** — asserts no `.ps1` file under `scripts/` mentions "governance" anywhere, confirming Florida's PowerShell pipeline has zero coupling to this new package.
- **Sync-script defense-in-depth check, manually verified** with a synthetic two-row fixture (one `tx_lgbs` row, one `tx_hctax` row): the `tx_lgbs` row passed through to the would-be upsert payload unchanged; the `tx_hctax` row was rejected by the gate with the reason `'tx_hctax' is LEGAL_REVIEW_REQUIRED - ingestion NOT permitted`. Fixture removed after verification — not committed.
- **State isolation / unique constraint**: untouched — no migration was written or executed this phase (see `docs/source-registry.md`'s and `docs/data-provenance.md`'s migration-consideration sections, both identified-but-not-executed per Step 15), so `(state, source, county, case_no)` remains exactly as `004_widen_unique_constraint_for_state.sql` left it.
- **No production harvest workflow was dispatched** to produce this verification — it was done entirely through static diff review, unit tests, and one local synthetic-fixture run against the sync script's logic (not against real Supabase credentials).

## Blocked-vendor status (Phase 10A Step 11)

GovEase, PBFCM, MVBA, and CTSA are all represented in `harvesters/governance/registry.py` with `legal_status=SourceStatus.BLOCKED` and their `restrictions` tuples populated (`no_redistribution`, `no_customer_display`, `no_api_export`, and — for PBFCM specifically — `no_documents`, since PDFs are that source's entire product). None was reactivated, re-scraped, or otherwise touched beyond transcribing their already-completed reconnaissance docs into registry data. `test_blocked_vendors_are_all_representable_in_the_registry` and `test_govease_mvba_ctsa_all_blocked_and_rejected` both check this directly.

## Harris County status (Phase 10A Step 10)

`tx_hctax` is registered `LEGAL_REVIEW_REQUIRED`, exactly as it has been since Phase 9.5. Not upgraded, not downgraded — `test_harris_status_was_not_upgraded_or_downgraded` asserts both that the status is neither `APPROVED` nor `APPROVED_WITH_RESTRICTIONS` and that the registry entry cites `claude/harris-hctax-rights-resolution-package.md`, so a future edit can't quietly drop the paper trail while changing the status. No `harvest_hctax()` function exists anywhere in this codebase — there is nothing for the gate to have blocked yet in practice, only a registry entry ready for the day a harvester is written.

## Future source onboarding

See `docs/source-registry.md`'s "Future source onboarding process" section for the full six-step process, generalized from how Harris County was actually worked through Phases 8 through 9.6.
