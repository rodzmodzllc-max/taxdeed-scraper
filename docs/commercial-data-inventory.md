# Commercial data inventory

**Status:** Phase 10B (Production Source Rights Audit + Governance CI Gate), 2026-09-14, updating Phase 10A's original version. This is the summary/audit page — `docs/source-registry.md` has the per-source detail, `docs/data-licensing.md` has the enforcement model, `docs/data-provenance.md` has the lineage model, `docs/lgbs-rights-audit.md`/`docs/realauction-rights-audit.md` have the two Phase 10B formal audits. This page exists so "what data does this product actually use commercially, and under what status" has one place to check without reading all of the above.

## Approval-basis classification (Phase 10B)

Phase 10A registered `tx_lgbs`/`tx_realauction` as `APPROVED` and Florida's three representative entries as `APPROVED` too, without distinguishing *why* each was approved. Phase 10B's own formal audits of LGBS and RealAuction (below) found that distinction matters enough to make explicit — **`legal_status=APPROVED` in the registry does not by itself tell you whether a source was actually rights-reviewed.** Every current registry entry now falls into exactly one of these four buckets:

| Bucket | Meaning | Sources |
|---|---|---|
| **FORMALLY RIGHTS-REVIEWED** | A dedicated Terms-of-Use/robots.txt/rights-matrix document exists (the Phase 8/9/9.5-style template), with concrete findings, even if the conclusion is still `LEGAL_REVIEW_REQUIRED` or `BLOCKED`. | `tx_hctax` (`claude/harris-hctax-*.md`), `tx_pbfcm`/`tx_mvba`/`tx_ctsa`/`tx_govease` (their own `claude/*-blocked.md` docs), and now `tx_lgbs`/`tx_realauction` (`docs/lgbs-rights-audit.md`/`docs/realauction-rights-audit.md`, Phase 10B) |
| **PRODUCTION-APPROVED BY EXISTING PRACTICE** | Registered `APPROVED` because it is already shipped, unauthenticated, and has never encountered an access wall — NOT because a rights review concluded it was clear. | `fl_realauction`, `fl_laft_pdfs`, `fl_lienhub_certificates` (still not formally audited as of this phase — out of Phase 10B's scope, which covered the two *Texas* production sources only) |
| **LEGAL_REVIEW_REQUIRED** | No restriction found, no permission found — automated ingestion blocked by the gate. | `tx_hctax` |
| **BLOCKED** | An explicit prohibition was found. | `tx_pbfcm`, `tx_mvba`, `tx_ctsa`, `tx_govease` |

**The critical distinction this phase makes explicit: `tx_lgbs` and `tx_realauction` are now FORMALLY RIGHTS-REVIEWED, but their review did NOT conclude "clear."** Both audits found genuine, unresolved, LEGAL_REVIEW_REQUIRED-grade findings — a same-entity/different-subdomain redistribution prohibition of uncertain scope for LGBS, and a robots.txt signal this project's own harvester has never checked for RealAuction (full detail in each audit doc). **Neither source's `legal_status` was changed** — both remain `APPROVED` in the registry, because Phase 10B's hard rules forbid deactivating a production harvester "based solely on your interpretation" and forbid this project from making the actual legal determination. This is recorded honestly as **"approval basis requires legal review"** in each `SourceRecord`'s `commercial_use_status` field (Phase 10B Step 7's exact required language) — production behavior is unchanged, but the registry no longer implies these two sources were ever cleared, only that they've been running.

**Do not read "FORMALLY RIGHTS-REVIEWED" as "cleared."** A review can conclude LEGAL_REVIEW_REQUIRED just as easily as APPROVED — the label only says a real audit happened and its findings are documented, not what those findings were. Check `legal_status` (and, for `tx_lgbs`/`tx_realauction` specifically, the `commercial_use_status` caveat) for the actual conclusion.

## Inventory by state

### Texas

| source_id | legal_status | approval basis | in production today? | harvester exists? |
|---|---|---|---|---|
| `tx_lgbs` | `APPROVED` | Production-practice approval; **formally audited Phase 10B** — approval basis requires legal review (see `docs/lgbs-rights-audit.md`) | Yes | `harvest_lgbs()` |
| `tx_realauction` | `APPROVED` | Production-practice approval; **formally audited Phase 10B** — approval basis requires legal review (see `docs/realauction-rights-audit.md`) | Yes | `harvest_realauction()` |
| `tx_hctax` (Harris County) | `LEGAL_REVIEW_REQUIRED` | Formally rights-reviewed (Phase 8/9/9.5/9.6) | No | None (no `harvest_hctax()` exists anywhere in this codebase) |
| `tx_pbfcm` | `BLOCKED` | Formally rights-reviewed | No | Architectural stub only (`harvest_pbfcm()` raises `NotImplementedError`) |
| `tx_govease` | `BLOCKED` | Formally rights-reviewed | No | Architectural stub only (`harvest_govease()` raises `NotImplementedError`) |
| `tx_mvba` | `BLOCKED` | Formally rights-reviewed | No | None |
| `tx_ctsa` | `BLOCKED` | Formally rights-reviewed | No | None |

### Florida

| source_id | legal_status | approval basis | in production today? | notes |
|---|---|---|---|---|
| `fl_realauction` | `APPROVED` (grandfathered) | Production-approved by existing practice — **not formally audited** (out of Phase 10B's scope) | Yes | PowerShell (`harvest_all_counties.ps1`), not this Python governance package |
| `fl_laft_pdfs` | `APPROVED` (grandfathered) | Production-approved by existing practice — **not formally audited** | Yes | Python (`scripts/harvest_laft_pdfs.py`), doesn't import `harvesters.governance` |
| `fl_lienhub_certificates` | `APPROVED` (grandfathered) | Production-approved by existing practice — **not formally audited** | Yes | PowerShell (`scripts/harvest_lienhub_certificates.ps1`) |

Florida also runs several other harvesters not individually registered this phase (`harvest_laft_html.py`, `harvest_laft_realtdm.py`, and the six county-specific LAFT scripts — Hillsborough/Leon/Orange/Osceola/St. Lucie/Pioneer-counties). They are out of scope for this phase's registry population and, like every other Florida script, are untouched by and unaware of this governance package. Phase 10B's rights-audit scope was explicitly the two Texas production sources only (Step 4/5) — Florida's grandfathered entries remain exactly as flagged in Phase 10A, a backfill-review candidate, not reviewed this phase either.

## What "commercial use" means for each status, in one line

- **`APPROVED`** — this project treats itself as cleared to retrieve, store, normalize, combine, derive from, display to customers, and (subject to no other restriction) export this source's data. **As of Phase 10B: check the approval-basis column above** — an `APPROVED` source may be production-approved-by-practice rather than formally cleared, in which case treat "cleared" as informal, not legal fact.
- **`APPROVED_WITH_RESTRICTIONS`** — cleared, but specific `Restriction` values apply (see `docs/data-licensing.md`) and must be enforced, not just noted.
- **`LEGAL_REVIEW_REQUIRED`** — nothing beyond a human manually reading the public page is cleared; the ingestion gate rejects any automated retrieval attempt. **This means "we found no restriction," never "we found affirmative permission" — the two are not the same, and this project does not treat them as the same anywhere.**
- **`BLOCKED`** — an explicit prohibition was found; same enforcement result as `LEGAL_REVIEW_REQUIRED` today (both are simply "not in `INGESTION_ALLOWED_STATUSES`"), but recorded with a different, more specific reason.

## Test coverage

`tests/python/test_source_governance.py` — 25 tests. `tests/python/test_customer_api_enforcement.py` — 26 tests (Phase 11). `tests/python/test_provenance_integration.py` — 24 tests (Phase 12, added below). 75 tests total, all passing (`pytest tests/python/`, ~0.1s). The first file covers every scenario Phase 10A Step 12 lists by number (1 through 14), plus additional fail-closed guarantees; the second covers every scenario Phase 11 Step 9's own lettered matrix (A through T) lists, plus two extra tests for the field-shape mechanism's inertness against today's real schema and for restriction types that carry no field-shape mapping; the third covers Phase 12 Step 25's own lettered matrix (A through J), including a full end-to-end integration test that runs the real, unmodified `scripts/sync-texas-to-supabase.py` against a synthetic multi-source fixture. See `docs/data-licensing.md`'s "Fail-closed guarantees" section for what each of the Phase 10A extra tests protects against, `docs/customer-api-data-enforcement.md` for the Phase 11 suite, and `docs/provenance-production-integration.md` for the Phase 12 suite.

**Wired into CI as of Phase 10B, still targeting the whole `tests/python/` directory as of Phase 12** — `.github/workflows/python-governance-test.yml`, triggered on every push/PR to `main`, mirroring the existing `playwright-test.yml` pattern (same triggers, same "a failing test fails the job" contract, no `continue-on-error` or equivalent soft-fail mechanism anywhere in the workflow). Neither Phase 11 nor Phase 12 needed to touch the workflow itself — `pytest tests/python/ -v` already picks up every file in that directory, including the new Phase 12 one. This workflow has not yet actually executed on GitHub's runners as of this phase — it was authored and locally validated (YAML parses correctly; the exact `pip install pytest && pytest tests/python/ -v` sequence it runs was reproduced locally and passed, now against 75 tests) but this sandbox has no push access to `taxdeed-scraper` (see `docs/source-registry.md`/commit-hash notes elsewhere), so the workflow itself will not actually run on GitHub until a human pushes these commits. This is a real, named limitation, not a claim that CI has been "verified working" in the full end-to-end sense.

## Customer/API data-restriction enforcement (Phase 11)

Full detail: `docs/customer-api-data-enforcement.md`. Summary: Phase 10A's own report named a gap — "Customer/API enforcement functions built/tested but NOT wired into frontend." Phase 11 closed it, but not by editing `public/app.js` directly (this application has no application server, and `app.js`/the CSV export/`supabase/functions/send-digest` all read Supabase's `public.properties` table directly with no way to execute Python at read time). Given Phase 11's hard "no migrations" rule, the only real, exercisable enforcement boundary for field-level restrictions is where it already was for whole-source restrictions: `scripts/sync-texas-to-supabase.py`, the write-time chokepoint, which is now the customer-facing representation's one controllable projection point in this architecture. `harvesters/governance/gate.py` gained `project_row_for_customer_output()` / `project_row_for_api_export()` (per-row, field-aware versions of the existing whole-list `filter_rows_for_*` functions), wired into that sync script's row-building loop. For `tx_lgbs`/`tx_realauction` (both `APPROVED`, zero restrictions) this is a verified no-op — confirmed by regression tests — so today's production behavior is unchanged; the mechanism exists and is tested so a future `APPROVED_WITH_RESTRICTIONS` source is enforced from day one instead of needing this built under time pressure. No source's `legal_status` or `restrictions` changed this phase.

## Production provenance & data lineage (Phase 12)

Full detail: `docs/provenance-production-integration.md` (and the model reference, `docs/data-provenance.md`). Summary: Phase 10A built a `Provenance` lineage model but, per Phase 11's own finding, no production code path ever constructed one. Phase 12 closed that gap at the same write-time chokepoint used for Phase 11's enforcement: `harvesters/texas_harvester.py` gained `FIELD_LINEAGE_MAP` (a static source-field → normalized-field map, read directly from `harvest_lgbs()`/`harvest_realauction()`) and `build_row_provenance()` (constructs a real `Provenance` record from the same registry/gate data already used for ingestion enforcement — never a second, divergent copy). Both are wired into `scripts/sync-texas-to-supabase.py`, guarded by a runtime assertion that provenance restrictions can never diverge from the ingestion gate's own decision. Provenance stays pipeline-side/audit-only — never persisted to Supabase, no schema change, no new `TexasSaleRow` field. No source's `legal_status` or `restrictions` changed this phase; `harvesters/governance/registry.py` is byte-for-byte untouched.

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

## Harris County status (Phase 10A Step 10 / Phase 10B Step 11)

`tx_hctax` is registered `LEGAL_REVIEW_REQUIRED`, exactly as it has been since Phase 9.5. Not upgraded, not downgraded, and not touched at all this phase beyond re-confirming it — `test_harris_status_was_not_upgraded_or_downgraded` still passes unchanged. No `harvest_hctax()` function exists anywhere in this codebase. Harris County was not contacted, scraped, or otherwise acted on in Phase 10B.

## LGBS and RealAuction formal rights audits (Phase 10B Step 4/5)

Full detail: `docs/lgbs-rights-audit.md`, `docs/realauction-rights-audit.md`. Summary of what changed this phase:

- **LGBS**: `taxsales.lgbs.com` itself has an open `robots.txt` (`User-agent: *`, no disallow) and no Terms of Use page of its own. A DIFFERENT subdomain of the same legal entity, `www.lgbs.com/legal-disclosures/`, contains an affirmative reproduction/redistribution prohibition whose scope — does it extend to the subdomain/API this project actually uses? — is genuinely unresolved. **We found a restriction whose applicability is uncertain; we did not find affirmative permission for `taxsales.lgbs.com` specifically, and we did not find this restriction to definitively apply to it either.**
- **RealAuction**: no Terms of Use was found or reviewed anywhere for this vendor (corporate site or any county instance). Every robots.txt-respecting fetch attempted this phase against three different Texas county instances (both hostname patterns) was refused — the literal robots.txt text could not be obtained by any tool available this phase, but the refusal pattern itself is a concrete, previously-unchecked restrictive-access signal that this project's own `harvest_realauction()` (built on Python's `urllib.request`, which never consults `robots.txt`) has operated without regard to since it shipped. **We found no Terms of Use at all (true absence of evidence, not evidence of absence) and a robots.txt signal suggesting restricted automated access (not itself a commercial-use prohibition, and not proof this project's harvesting has been non-compliant — proof only that the question was never checked before now).**

**Neither finding changed either source's `legal_status`.** Both remain `APPROVED` in production. Both `SourceRecord.commercial_use_status` fields now explicitly say "approval basis requires legal review." Both findings are escalated for a human decision in Phase 10B's own final report, per Step 7's explicit instruction not to silently upgrade, downgrade, or otherwise act on this alone.

## Future source onboarding

See `docs/source-registry.md`'s "Future source onboarding process" section for the full six-step process, generalized from how Harris County was actually worked through Phases 8 through 9.6.
