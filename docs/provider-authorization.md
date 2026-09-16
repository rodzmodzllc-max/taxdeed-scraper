# Provider authorization framework

**Status:** Phase 34A (Provider Authorization & Commercial Data License Framework) built the model; Phase 34B (Authorization Gate Integration & Source-Policy Hardening), both 2026-09-15, wired the first real production enforcement point on top of it (see "Production enforcement" below). Companion to `docs/source-registry.md` (what a source's *ingestion* status is), `docs/data-licensing.md` (how that status is enforced), and `claude/phase-33-5-florida-production-source-rights-audit.md` (the audit that found the evidence this framework now tracks structurally). Implementation: `harvesters/governance/authorization.py`.

## Why this exists

Phase 33.5's audit of the three grandfathered Florida sources found that a single whole-source `legal_status` (`harvesters/governance/registry.py`) is too coarse a question for what a real commercial license actually grants. A provider's agreement can license a narrow activity (viewing one county's auction calendar to place a bid) while saying nothing about, or expressly prohibiting, a much broader set of activities this project actually performs (automated retrieval, storage, customer display, CSV export). Treating "the source is `APPROVED`" as "every one of those activities is therefore permitted" would repeat exactly the technical-accessibility-as-legal-permission conflation `docs/data-licensing.md`'s own "core rule" forbids.

This framework answers a narrower, additive question: for a specific source, at a specific provider/county deployment, has an actual documented authorization been recorded that covers a specific use? It never replaces or weakens the existing ingestion gate (`harvesters/governance/gate.py`'s `check_ingestion_gate()`) - it sits alongside it, and can only ever be stricter.

## The scope hierarchy (Phase 34A Section 4)

```
Provider
   |
Platform / deployment
   |
County / jurisdiction
   |
Specific source (source_id, in harvesters/governance/registry.py)
   |
Specific permitted use (one of 12 dimensions - see below)
```

The same underlying provider can therefore have different authorization status by deployment or county. `RealAuction.com, LLC` is one provider; `fl_realauction` is one `source_id` covering 46 Florida counties; but an authorization record is scoped to `(source_id, county)` - a record for Alachua County says nothing about Volusia County, Duval County, or any of the other ~44 counties that platform also serves, even though they share a `source_id` and a provider. This is enforced structurally, not just by convention - see `authorization_for_scope()`'s exact-match lookup and `tests/python/test_provider_authorization.py`'s county-isolation tests.

## The model

One normalized record type, `ProviderAuthorization` (not four separate tables - see the module's own docstring for why), with three small nested value types:

- **`AuthorizationDocument`** - a *reference* to a contract/EULA/agreement, never the document's own text and never a fabricated repository path. `is_pending=True` (the default) means no file is actually on file in this repository; `document_location` stays `None` in that case. Every record created this phase is `is_pending=True` because the two agreements this phase worked from (LienHub's User Agreement, RealAuction's Alachua/Volusia EULAs) were supplied as prose inside chat instructions, not as files this repository can reference by path.
- **`AuthorizationScope`** - the full 12-dimension permission matrix: `automated_access`, `commercial_use`, `storage`, `historical_storage`, `normalization`, `derived_data`, `customer_display`, `customer_export`, `api_access`, `api_redistribution`, `image_use`, `document_use`. Each dimension is a `UsePermission(requested: bool, authorized: bool)` pair - **asking is not the same event as receiving** (Section 7). `api_access` (does an official API/feed exist that this project may use) is kept distinct from `api_redistribution` (may this project re-expose the data through its own customer-facing API) - two genuinely different grants.
- **`AuditLogEntry`** - one immutable audit-trail entry per state change (Section 16): `event`, `who`, `when`, `old_status`, `new_status`, `reason`, `document_reference`.

`ProviderAuthorization` itself carries the rest of Section 5's field list (`authorization_id`, `source_id` - a reference into `SOURCE_REGISTRY`, never a duplicate of its fields - `provider`, `government_entity`, `state`, `county`, `deployment_scope`, request/contact fields, `request_status`, `authorization_status`, the embedded `document`, agreement dates, `effective_date`/`expiration_date`/`review_due_date`, the embedded `scope`, `attribution_required`, `rate_limit`, `retention_requirement`, `privacy_restrictions`, `technical_restrictions`, `written_permission`, `reviewed_by`/`reviewed_at`, `notes`, `terms_version`/`terms_hash`/`last_terms_check`, and the `audit_log` tuple).

## Controlled states (Section 6)

`AuthorizationStatus`: `REQUEST_NOT_STARTED`, `DRAFT`, `CONTACTED`, `AWAITING_RESPONSE`, `RECEIVED`, `UNDER_REVIEW`, `APPROVED`, `APPROVED_WITH_RESTRICTIONS`, `DECLINED`, `EXPIRED`, `REVOKED`, `LEGAL_REVIEW_REQUIRED`, plus `TERMS_CHANGED` (Section 14 calls for this state or an equivalent; this module reuses the exact spelling `registry.py`'s own `SourceStatus.TERMS_CHANGED` already uses, one level down).

Only two of these, `AUTHORIZATION_GRANTED_STATUSES = {APPROVED, APPROVED_WITH_RESTRICTIONS}`, may ever carry an `authorized=True` flag on any dimension. This is enforced structurally by `ProviderAuthorization.__post_init__()` - a record that tries to set `authorized=True` while its status is `CONTACTED` or `RECEIVED` raises `ValueError` at construction time, not merely as a convention a caller has to remember. `CONTACTED` does not mean `APPROVED`. `RECEIVED` does not mean `APPROVED`. Only documented authorization plus appropriate review can result in `APPROVED`.

## Expiration and revocation (Section 13)

`effective_authorization_status(record, as_of=None)` computes the status that actually governs *today*, which can differ from the literal stored value: `REVOKED` always wins (terminal); an expired `expiration_date` is treated as `EXPIRED` regardless of what `authorization_status` still says, computed at read time rather than depending on a background job to flip a field. `check_authorized_use()` (below) always calls this function, never the raw stored field.

## The combined gate: `check_authorized_use()`

```python
check_authorized_use(source_id, use, *, county=None, as_of=None) -> UseDecision
```

1. Unknown `use` name -> raises `ValueError` immediately (a typo must never silently look like "denied").
2. `check_ingestion_gate(source_id)` (the existing, **completely unmodified** Phase 10A gate) denies -> denied, full stop. Section 12 is explicit: the existing gate is never weakened. This new gate can only add restriction on top of it, never lift it.
3. No authorization record exists for `(source_id, county)` exactly -> denied. Missing is never approved.
4. The matching record's `effective_authorization_status()` is not one of `AUTHORIZATION_GRANTED_STATUSES` -> denied.
5. The matching record's `scope.<use>.authorized` is not `True` -> denied. An `APPROVED_WITH_RESTRICTIONS` record authorizes only the specific dimensions it says it does.
6. Otherwise -> allowed.

**Precisely what `check_authorized_use()` checks, and does not check** (Phase 34B Section 2): it always requires an exact `(source_id, county)` match against a real `ProviderAuthorization` record - there is no opt-in/no-op fallback inside this function itself for a source with zero records; a source with no record on file is simply denied at step 3 above, the same as one with a record in the wrong status. The opt-in/no-op behavior described in "Production enforcement" below lives *only* in the three wrapper functions, one layer up - `check_authorized_use()` itself is unconditionally strict. It does not read `SourceRecord.historical_project_status` or `SourceRecord.current_commercial_authorization_status` at all (confirmed by `test_phase34b_section12_historical_approved_status_never_satisfies_a_current_authorization_check`, which greps the module's own source for those two field names) - a source's historical/legacy `APPROVED` status can never, by itself, satisfy a current commercial-authorization check. It does not re-implement per-field restriction stripping (`NO_RAW_HTML`/`NO_IMAGES`/`NO_DOCUMENTS`) - that source-vs-field distinction (Section 7) already exists in `restrictions.py`/`gate.py` (Phase 11) and is applied by the wrapper functions calling `project_row_for_customer_output()`/`project_row_for_api_export()` *before* the per-use authorization check runs; `AuthorizationScope` is deliberately dimension-level, not field-name-level, and Phase 34B did not add new field-level granularity to it, since the existing mechanism already covers that need (Section 7's own instruction not to over-build).

## Production enforcement (Phase 34B)

Three wrapper functions in `harvesters/governance/authorization.py` compose the existing (Phase 10A/11) gate/projection functions with the new per-use authorization check, sharing one governing rule: **a `source_id` with zero `ProviderAuthorization` records anywhere is a byte-for-byte no-op**, deferring entirely to the pre-existing, unmodified function it wraps. Only a `source_id` that has at least one record on file (today: `fl_realauction`, `fl_lienhub_certificates`) is held to the stricter, per-county/per-use standard.

- **`authorized_for_ingestion(source_id, *, county=None) -> bool`** - the raw-acquisition boundary (should a harvester run at all). Built and tested; **not wired into any harvester entry point this phase** (`harvesters/texas_harvester.py` was deliberately left untouched - the safest reading of "do not rewrite the TX harvesters").
- **`authorized_for_customer_output(row, source_id, *, county=None) -> dict | None`** - the customer-facing-exposure boundary. **This is the one function actually wired into live code this phase**: `scripts/sync-texas-to-supabase.py`'s row-building loop now calls this in place of the old direct `project_row_for_customer_output(row, harvester_source)` call, passing the row's own `county`. Because `tx_lgbs` and `tx_realauction` - the only two real, live TX sources this script ever processes - have zero `ProviderAuthorization` records, this change is a verified no-op for current production traffic (see `test_new_customer_output_check_is_a_no_op_for_sources_with_no_authorization_records`, and the real end-to-end `tests/python/test_provenance_integration.py::test_G_integration_sync_script_never_builds_provenance_for_ungated_rows`, which loads and runs the actual file). The stricter behavior only activates for a source once it has an authorization record - today, that would deny `fl_realauction`/`fl_lienhub_certificates` display if this script ever handled Florida rows (it doesn't - Florida's pipeline is described below).
- **`authorized_for_api_export(row, source_id, *, county=None) -> dict | None`** - the export/API-redistribution boundary, requiring *both* `customer_export` and `api_redistribution` to be authorized (Section 6: never conflate `customer_display` with `api_redistribution`). Built and tested; **not wired into any live call site this phase**, because no live export or API surface distinct from the CSV-download button in `public/app.js` exists in Python for it to sit in front of.

**The named, unchanged gap:** Florida's actual harvesting/sync pipeline (`harvest_all_counties.ps1`, `harvest_lienhub_certificates.ps1`, `sync-harvest-to-supabase.ps1`, `sync-certificates-to-supabase.ps1`, plus the one Python `harvest_laft_pdfs.py` and its own PowerShell sync) does not import `harvesters.governance` at all - not before Phase 34A, not after Phase 34B. This is not an oversight; rewriting any of those files is explicitly forbidden this phase. It means the two sources this framework actually has real authorization findings for (`fl_realauction`, `fl_lienhub_certificates`) are *governed on paper and in tests*, but not *live-enforced* in Florida's real pipeline. This is the single largest limitation of the framework as it stands after Phase 34B, and is called out again in the Phase 34B report.

## Terms-change tracking (Section 14; extended Phase 37 Section 13)

`terms_version`/`terms_hash`/`last_terms_check` exist on every record so a future check can detect drift from what was reviewed. Phase 34A/34B did **not** build an automated live-terms-diff checker (that would require unattended network calls to provider sites, out of scope for a repository-implementation-only phase) - `TERMS_CHANGED` was a state the model could *represent* but had no mechanism to *compute*.

Phase 37 (Production Source Promotion Gate) closed that gap partially, without automating legal interpretation (its own Section 12's explicit prohibition): `ProviderAuthorization` gained a `terms_changed_detected: bool` field (default `False`, backward-compatible with every existing record), and `effective_authorization_status()` now checks it immediately after `REVOKED` - a record with `terms_changed_detected=True` is `TERMS_CHANGED` at read time regardless of what its stored `authorization_status` or dates say, the same "computed live, never a stored field a job has to remember to flip" pattern `EXPIRED`/`NOT_YET_EFFECTIVE` already used. Two small, honest primitives support setting it: `compute_terms_hash(text) -> str` (a plain SHA-256 of terms text a human fetched) and `terms_hash_mismatch(record, current_text) -> bool` (compares against `record.terms_hash`, returning `False` - not "changed" - if the record was never hashed at all, since "never checked" and "checked and unchanged" are different facts). `flag_terms_changed(record, *, reason, who)` returns a **new** record (this dataclass is frozen) with the flag set and an appended, immutable `AuditLogEntry`. Applying that new record - replacing the corresponding entry in `PROVIDER_AUTHORIZATIONS` - remains a deliberate, human-reviewed code change, the same trust model this repository already uses for every other status transition (see `docs/data-licensing.md`'s "Remaining risks" #4). Nothing in this phase scrapes a provider's site to detect a change on its own initiative.

## Production source-promotion gate (Phase 37)

Phase 37 added `harvesters/governance/promotion.py`, a single function - `can_promote_source_for_use(source_id, use, *, state=None, county=None, as_of=None) -> PromotionDecision` - that answers "may this source be used for this exact purpose" by composing the three existing layers above (the whole-source registry gate, this module's own per-use authorization check, and the Phase 36 terms-review ledger) in one fixed, fail-closed order, rather than requiring every caller to know which of the three to consult and in what sequence. **It holds no authorization data of its own** - see `harvesters/governance/promotion.py`'s own module docstring for the full 5-step decision order and the worked examples in `tests/python/test_phase37_promotion_gate.py`.

Twelve recognized purposes (`PROMOTION_USES`, Phase 37 Section 2's exact vocabulary, never collapsed into one boolean): `INGEST`, `STORE`, `CACHE`, `NORMALIZE`, `DERIVE`, `CUSTOMER_DISPLAY`, `CUSTOMER_EXPORT`, `API`, `HISTORICAL_RETENTION`, `IMAGE_DISPLAY`, `IMAGE_DOWNLOAD`, `DOCUMENT_DISPLAY`, `DOCUMENT_DOWNLOAD`. Each maps to one `AuthorizationScope` dimension (`PROMOTION_USE_TO_SCOPE_DIMENSION`); five of those dimensions (`caching`, `image_display`, `image_download`, `document_display`, `document_download`) are new fields Phase 37 added to `AuthorizationScope` itself (see "The model" above) rather than a second, competing vocabulary this module would have to keep in sync by hand - every existing `ProviderAuthorization` record leaves them at their default (`UsePermission()`, unauthorized), which changes no existing record's behavior.

`PromotionDecision` is always a structured object (`allowed`, `status`, `reason`, `source_id`, `state`, `county`, `use`, `evidence`, `reviewed_at`, `checked_at`), never a bare boolean - matching Phase 37 Section 8's required shape exactly, and this project's own established `GateDecision`/`UseDecision` pattern.

**This is a read/decision function only - Phase 37 did not wire it into `harvesters/texas_harvester.py` or `scripts/sync-texas-to-supabase.py`.** Both files' existing calls (`check_ingestion_gate()` in `main()`; `authorized_for_customer_output()` in the sync script) are proven, by `test_can_promote_source_for_use_agrees_with_texas_harvesters_main_loop` and `test_can_promote_source_for_use_agrees_with_sync_scripts_customer_output_check` in `tests/python/test_phase37_promotion_gate.py`, to already produce the identical `allowed`/denied outcome `can_promote_source_for_use()` would for every real, currently-registered source - so wiring it in later is a safe, verified drop-in replacement, not a leap of faith, and not wiring it in now avoids Phase 37 Section 22's "do not mass-rewrite harvesters" for zero behavioral gain today.

**Discovery vs. production (Phase 37 Section 20):** a source that exists only in the Phase 35 county-coverage catalog or the Phase 36 terms-review ledger - never promoted into `SOURCE_REGISTRY` - denies for *every* promotion use, by construction: `can_promote_source_for_use()` never treats a catalog/ledger-only `source_id` as anything better than the ledger's own (never-better-than-`LEGAL_REVIEW_REQUIRED`) finding. See `test_23_discovery_only_source_cannot_reach_production_for_any_use`, which checks this against every one of the 20 ledger rows with no `SOURCE_REGISTRY` counterpart.

**Florida enforcement status, stated plainly (Phase 37 Section 14):** the safest existing production-ingestion boundary for Texas is `harvesters/texas_harvester.py`'s `main()` loop and `scripts/sync-texas-to-supabase.py`'s per-row loop - both already call into this governance package today. **No equivalent boundary exists for Florida and Phase 37 did not create an unsafe cross-language workaround to fake one.** Florida's harvesting/sync pipeline (`harvest_all_counties.ps1`, `harvest_lienhub_certificates.ps1`, `sync-harvest-to-supabase.ps1`, `sync-certificates-to-supabase.ps1`, plus the Python `harvest_laft_pdfs.py` and its own PowerShell sync counterpart) still does not import `harvesters.governance` at all, exactly as documented after Phase 34B. `can_promote_source_for_use("fl_realauction", "INGEST", county="Alachua")` and every other Florida county both correctly return `allowed=False` when called directly and tested - but nothing in Florida's actual running pipeline calls this function, or any governance function, before harvesting or syncing a row. **Florida production ingestion is not governed today - it is only decidable, on demand, by a caller that chooses to ask.** This is Phase 37's single largest limitation, restated rather than minimized, and the identical honest gap Phase 34B's own report already named.

## No database migration

This framework is a pure-Python module, exactly like `registry.py`/`gate.py`/`provenance.py` before it (Phase 10A's own established pattern: governance state lives in git-tracked code, referenced by `source_id`, never in a Supabase table). **No migration was written or executed in Phase 34A or Phase 34B.** See `claude/phase-34a-provider-authorization-framework.md` and `claude/phase-34b-authorization-gate-integration-and-source-policy-hardening.md` for the explicit statements. True server-side field-level enforcement (so that even a direct Supabase query, not just this project's own sync/frontend code, could not surface a `customer_display=NO` field) would require either of the already-designed-but-unexecuted migrations `scripts/migrations/005_customer_safe_properties_projection.sql` (Phase 14A) and `005a_close_direct_properties_grant.sql` (Phase 14B), or a new Supabase edge function acting as a real API boundary - neither is drafted or executed by this phase; see the Phase 34B report's database-decision section for why.

## Checklist (Section 20)

A reusable per-source-authorization checklist, for a human working an authorization request through to completion:

- [ ] Provider identified
- [ ] Government relationship identified
- [ ] Source identified (`source_id` in `SOURCE_REGISTRY`)
- [ ] County/deployment identified
- [ ] Terms obtained
- [ ] Terms version recorded
- [ ] License obtained
- [ ] API availability checked
- [ ] Bulk-feed availability checked
- [ ] Automated access permission checked
- [ ] Commercial use checked
- [ ] Storage checked
- [ ] Historical storage checked
- [ ] Normalization checked
- [ ] Derived data checked
- [ ] Customer display checked
- [ ] Export checked
- [ ] API redistribution checked
- [ ] Image rights checked
- [ ] Document rights checked
- [ ] Attribution checked
- [ ] Rate limits checked
- [ ] Retention checked
- [ ] Privacy checked
- [ ] Technical restrictions checked
- [ ] Written authorization obtained
- [ ] Human/legal review completed
- [ ] Approval scope recorded
- [ ] Expiration/review date recorded

## Current records

As of Phase 34A, exactly three `ProviderAuthorization` records exist, all `LEGAL_REVIEW_REQUIRED`, all `written_permission=False`, all with every scope dimension `authorized=False`:

| `authorization_id` | `source_id` | `county` | `deployment_scope` | `authorization_status` |
|---|---|---|---|---|
| `fl_lienhub_certificates__provider__grant_street_group` | `fl_lienhub_certificates` | `None` (provider-wide) | `provider` | `LEGAL_REVIEW_REQUIRED` |
| `fl_realauction__county__alachua` | `fl_realauction` | `Alachua` | `county` | `LEGAL_REVIEW_REQUIRED` |
| `fl_realauction__county__volusia` | `fl_realauction` | `Volusia` | `county` | `LEGAL_REVIEW_REQUIRED` |

See `docs/provider-authorization-status.md` for the narrative explanation of each, and `docs/provider-authorization-requests.md` for the (unsent) request templates that would move these forward.
