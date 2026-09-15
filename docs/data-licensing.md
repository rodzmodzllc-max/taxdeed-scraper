# Data licensing & enforcement

**Status:** Phase 10A (Commercial Source Governance Infrastructure), 2026-09-14. Companion to `docs/source-registry.md` (what a source's status *is*) — this page is about how that status is *enforced* in code, and what it means for a restriction to survive downstream.

## The core rule

**Technical accessibility is never treated as legal/commercial permission.** A source that 200s to a plain `curl` and has no CAPTCHA can still be, and several already-researched sources are, `BLOCKED` or `LEGAL_REVIEW_REQUIRED`. This project's reconnaissance docs (`claude/harris-hctax-*.md` in particular) drew this line explicitly and repeatedly; the enforcement code in `harvesters/governance/` is what makes that line mechanical rather than something a future contributor has to remember to re-derive from first principles.

## The enforcement gate

`harvesters/governance/gate.py`'s `check_ingestion_gate(source_id)` is the single reusable decision point (Phase 10A Step 4). It:

- looks up `source_id` in `SOURCE_REGISTRY` (see `docs/source-registry.md`),
- returns `allowed=True` **only** if the registry's `legal_status` is `APPROVED` or `APPROVED_WITH_RESTRICTIONS`,
- returns `allowed=False` for `LEGAL_REVIEW_REQUIRED`, `BLOCKED`, `DISABLED`, `TERMS_CHANGED`,
- returns `allowed=False` for a **missing/unknown** `source_id` too — treated as `LEGAL_REVIEW_REQUIRED`, never as approved (see [Fail-closed guarantees](#fail-closed-guarantees) below),
- never raises — always returns a `GateDecision`, so a caller can't accidentally skip the check via an unhandled exception.

### Where it's actually wired in (two real call sites)

1. **`harvesters/texas_harvester.py`, `main()`** — the primary enforcement point. Before calling any `harvest_*()` function, the gate is checked for that vendor's `source_id`. A non-approved source's harvester is never called at all. `tx_lgbs`/`tx_realauction` (both `APPROVED`) run exactly as before this phase; `tx_pbfcm`/`tx_govease` (both `BLOCKED`) are skipped before being called, instead of being called and catching a `NotImplementedError` as before — same net effect, one more independent layer of protection for the day someone fills in those stubs.
2. **`scripts/sync-texas-to-supabase.py`** — a second, defense-in-depth check, per row, right before that row is added to the Supabase upsert payload. This exists because `public.properties` has no field-level Row Level Security — a row that reaches that table is immediately visible to every approved app user, so "reaches the sync script's payload" and "becomes customer output" are, in this codebase's current architecture, effectively the same event. This is *why* the sync script is the natural second (and currently last) real chokepoint, not an arbitrary choice.

### Not yet wired in (an honest gap, not an oversight)

`filter_rows_for_customer_output()` and `filter_rows_for_api_export()` (also in `gate.py`) exist and are tested, but nothing in `public/app.js` or any export feature calls them yet. This is deliberate for this phase: no `APPROVED_WITH_RESTRICTIONS` source exists today that would need a *field-specific* restriction enforced at display time (both current `APPROVED` sources, `tx_lgbs`/`tx_realauction`, carry zero restrictions; both `LEGAL_REVIEW_REQUIRED`/`BLOCKED` sources are stopped upstream at the two chokepoints above, before any row exists to restrict). Building a per-field customer-output enforcement layer into the frontend speculatively, before a real restricted-but-approved source exists to drive its design, would be exactly the kind of over-engineering Phase 10A's own instructions warn against (Step 5: "do not over-engineer a completely separate system"). See [Remaining risks](#remaining-risks) for what this means concretely the day a restricted source is approved.

## Restrictions are data, not comments

`harvesters/governance/restrictions.py` defines the `Restriction` enum (Phase 10A Step 7):

`attribution_required`, `no_raw_html`, `no_images`, `no_documents`, `no_redistribution`, `no_customer_display`, `no_api_export`, `no_historical_retention`, `field_specific_restriction`, `rate_limit`, `retention_period`, `source_only_display`, `other_contractual_restriction`.

A `SourceRecord.restrictions` tuple is explicit, checkable data — `gate.py`'s `BLOCKS_CUSTOMER_DISPLAY`/`BLOCKS_API_EXPORT` sets are themselves data too (not an inline `if` scattered across call sites), so extending which restrictions block which surface is a one-line change to a set literal, not a hunt through the codebase for every place that needs to know.

## Provenance and the "no laundering" guarantee

`harvesters/governance/provenance.py` models the pipeline Phase 10A Step 5 specifies:

```
SOURCE -> RAW -> NORMALIZED -> ENRICHED -> DERIVED -> CUSTOMER -> EXPORT/API
```

`advance()` moves a `Provenance` record forward one or more stages. Its signature has **no parameter that can remove a restriction** — only `additional_restrictions`, which is unioned in. This is enforced structurally (there's no code path in `advance()` that can shrink the restriction set), not just documented as a convention — see `tests/python/test_source_governance.py::test_7_restriction_cannot_be_dropped_downstream`, which also asserts the signature itself has no such parameter, so a future edit that tried to add one would have to consciously break an explicit test, not just slip past a comment.

`derive()` builds a `DERIVED`-stage record from one or more parent records (e.g. a bid-to-value ratio computed from a `min_bid` field and a `cad_market_value` field, potentially from two *different* sources once cross-source enrichment is in play). The derived record's restriction set is the **union** of every parent's restrictions — deriving a new value from restricted data does not launder the restriction away. `origin_source_ids()` walks a derived record's lineage recursively and returns every source it ultimately traces back to, so "which source(s) is this number actually built from" stays a checkable fact rather than something only reconstructable by reading code history.

This directly encodes Phase 9.5's own unresolved question (`claude/harris-hctax-legal-commercial-gate.md`, Section 10, "derived data") into runtime behavior: that document explicitly declined to conclude whether a derived metric is "the source's data" or "this project's own analysis" for rights purposes, and left it as an open legal question. `derive()`'s behavior encodes the conservative answer — treat it as still carrying the source's restrictions until a human resolves the question — without this codebase quietly assuming an answer either way.

## Fail-closed guarantees (Phase 10A Step 14)

Reviewed specifically for ways a future change could accidentally bypass governance:

- **Unknown/missing source_id → `LEGAL_REVIEW_REQUIRED`, never `APPROVED`.** `get_source()` returns `None` for a miss rather than raising, and `check_ingestion_gate()` treats `None` as not-allowed — there is no code path where "I don't recognize this source" resolves to "so let it through." (`test_unknown_source_fails_closed`, `test_empty_or_none_source_id_fails_closed`.)
- **No default-approved status.** `SourceStatus` has no "default" member and `SourceRecord.legal_status` is a required constructor argument with no default value — a new registry entry that forgets to set it fails at construction time, not silently as `APPROVED`.
- **No hard-coded source exceptions anywhere in `gate.py`.** The gate's entire decision is `record.legal_status in INGESTION_ALLOWED_STATUSES` — there is no `if source_id == "some_special_case": allow_anyway`.
- **The two blocked-vendor stubs (`harvest_pbfcm`, `harvest_govease`) are protected twice, independently** — the `NotImplementedError` they still raise, and now the gate that skips them before they're even called. Removing one protection doesn't remove the other.
- **`test_every_registered_source_has_a_legal_status_that_is_a_real_enum_member`** guards against a future entry setting `legal_status` to a raw string or `None` instead of a `SourceStatus` member, which would silently make `in INGESTION_ALLOWED_STATUSES` behave unpredictably.
- **Background jobs**: the only background job that touches Texas data is the `texas` job in `.github/workflows/harvest-and-sync.yml`, which runs exactly `harvesters/texas_harvester.py` then `scripts/sync-texas-to-supabase.py` — both of the two enforced chokepoints above. No other job or script reads `harvest_texas.json` or writes Texas rows to Supabase.
- **Customer UI / API paths**: `public/app.js` reads from `public.properties` directly via Supabase's client SDK — it doesn't call any harvester or sync script, so there's no *additional* bypass path there to worry about; the enforcement already happened before a row ever reached that table (see [Remaining risks](#remaining-risks) for the one real gap this leaves).

## Remaining risks

Stated plainly, not minimized:

1. **No per-field restriction enforcement yet exists at customer-display or export time.** Today's two enforced chokepoints are whole-row/whole-source, not whole-row *and* per-field. If a future source is approved `APPROVED_WITH_RESTRICTIONS` with a `field_specific_restriction` (e.g., "you may store and display this data but may not display the source's photos"), the current architecture has nowhere to enforce "drop just the photo field, keep the rest" — it would need either a new column-level filter in the sync script (straightforward) or a genuinely new customer-display-time check in `public/app.js` (a real frontend change, not yet built). Flagged, not built speculatively.
2. **UPDATED Phase 10B**: `tx_lgbs` and `tx_realauction` now DO have a Phase-8/9.5-style formal rights audit each (`docs/lgbs-rights-audit.md`, `docs/realauction-rights-audit.md`) — but both audits concluded with unresolved, LEGAL_REVIEW_REQUIRED-grade findings (a same-entity/different-subdomain redistribution prohibition of uncertain scope for LGBS; a robots.txt signal this project's harvester has never checked, for RealAuction), not a clean bill of health. Both sources remain `APPROVED` in production because Phase 10B's hard rules forbade deactivating a running harvester based solely on this project's own interpretation — but "approved" for these two should now be read as "formally reviewed, with open questions escalated for a human decision," not "reviewed and cleared." See `docs/commercial-data-inventory.md`'s "Approval-basis classification" section.
3. **The Florida `APPROVED` entries are grandfathered, not reviewed** — see `docs/source-registry.md`'s own section on this. Their entries don't gate anything in practice (Florida's PowerShell pipeline doesn't call this package), so this is a documentation-completeness gap, not a live enforcement risk.
4. **The registry itself is a Python module a developer with repo write access can edit directly** — there is no admin-panel/RLS-gated interface to it (see `docs/source-registry.md`'s migration-considerations section for what that would take). A malicious or careless direct edit to `registry.py` could set any `legal_status`. This is the same trust model this entire repository already operates under for every other file (harvester logic, sync logic, RLS policies themselves) — not a new risk this phase introduces, but worth naming rather than implying the registry is somehow tamper-proof.
5. **Tests are not wired into CI** — see `docs/commercial-data-inventory.md`'s test-status note.
6. **UPDATED Phase 35**: a new, deliberately unenforced discovery-stage catalog (`harvesters/governance/source_catalog.py`, `data/fl_county_coverage_matrix.csv`, `data/tx_county_coverage_matrix.csv`) now records 54 newly-identified government sources (12 Florida Property Appraiser sites, 42 Texas Appraisal District/Tax Assessor-Collector sites) — none of them enforced by, gated by, or even known to this enforcement gate. This is intentional (see `docs/source-registry.md`'s "The catalog vs. the registry" section) and does not weaken anything described above; it is named here so "does the enforcement gate know about every source this repository has ever looked at" has an honest answer: no, and it isn't supposed to until a source is deliberately promoted into `SOURCE_REGISTRY`.
7. **UPDATED Phase 36**: `data/phase36_terms_review.csv` (see `docs/source-registry.md`'s "The terms-review ledger" section) found real, evidence-backed reasons to keep every reviewed source at `LEGAL_REVIEW_REQUIRED` or `DISCOVERED` — including a fresh, live-reconfirmed `ROBOTS_DISALLOWED` finding across four independent RealAuction deployments (Alachua, Miami-Dade, and Brevard in Florida; Travis in Texas), an explicit "electronic data harvesting" prohibition on Pinellas County's Property Appraiser site, and the absence of any stated terms of use on Florida DOR's statewide Data Portal or Texas's TNRIS/StratMap statewide GIS parcel layer despite both being free and technically accessible. None of this changes any `SOURCE_REGISTRY` entry or this gate's behavior — `fl_realauction`/`fl_laft_pdfs`/`fl_lienhub_certificates` remain grandfathered `APPROVED` at the registry level exactly as before (Phase 36 did not touch production or the registry), and the terms-review findings exist specifically to inform whether and how any *new* county or provider should ever be promoted into the registry in the first place. The gap this closes is evidentiary, not architectural: before Phase 36, "verified website" (Phase 35) and "verified commercial-use rights" were easy to conflate; now there is a citable, per-source record of which is which.
