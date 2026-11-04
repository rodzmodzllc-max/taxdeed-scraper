# Source gap closure: validation and test plan

This plan covers three workstreams: (A) listings, (B) permissions, and (C) historical auction outcomes. The
outcome plan (section 2) is complete. The listing and permission sections (3 and 4) list the required cases,
which their workstream owners extend.

For each case the plan gives the existing test that covers it, cited as `file::test_name` after a grep of
`tests/python/` on branch `claude/source-gap-closure` (base `9498836`). Otherwise it says **NEW**, with what the
test must assert. **PARTIAL** means an existing test covers part of the case and the rest must be added.

## 1. Ground rules for every workstream

1. **Unit tests are pure** (no network, no database).
   - They run on synthetic fixtures, marked `SYNTHETIC` the way `tests/python/fixtures/realauction/*.json` are
     (`test_auction_outcomes.py::test_fixture_files_are_marked_synthetic`).
   - A test never reads a live county host.
2. **Live checks are separate.** They are manual, value-free evidence captures (`job=evidence`, `job=outcomes`
   with `--dry-run`). Their logs print counts and masked structure only
   (`test_auction_outcomes.py::test_26_capture_skeleton_never_prints_identifiers`).
3. **Production measurements are read-only SELECTs with GROUP BY**, and counts only. No identifier, amount,
   owner or purchaser leaves the database.
4. **Before any new source is read**, a test proves its reader calls
   `permissions.authorize(source_id, op, state=, dataset=)` for each operation before the first request and the
   first write. A second test proves a denied decision makes zero requests. The `fl_realauction` closed-results
   check in `auction_outcomes.main()` is the pattern.
5. **Every count in a document has a stated denominator** (section 5).

## 2. Workstream C: historical auction outcomes (complete plan)

### 2.1 Outcome semantics

| # | Case | What must hold | Existing coverage | Status |
|---|---|---|---|---|
| C01 | Cancellation | A published cancellation wording sets lifecycle `cancelled`. The outcome stays `unknown`, `outcome_raw` keeps the wording, and `winning_bid` is never set, even when an "Amount" cell is present. | `test_auction_outcomes.py::test_11_to_15_each_published_result_is_captured` ("Canceled per County"); `::test_17_unpublished_amount_stays_null` (amount beside a non-sale result); `::test_24_provenance_survives_lifecycle_changes` | covered |
| C02 | Cancellation wording missing from the table | A cancellation-like wording without a reviewed row is "checked, not published", never `cancelled`. | `::test_15b_redemption_only_when_published` (uses "Canceled per Bankruptcy" against the fixture table) | covered (fixture table) |
| C03 | Postponement | A new date is a new event. The old one becomes `superseded` only with evidence: its date has not passed, the county read was COMPLETE, and the property is listed under another date. "Rescheduled" / "Auction to be rescheduled" never set a result. | `test_phase_b_auction_event_writers.py::test_same_property_new_sale_date_creates_second_event_and_supersedes_with_evidence`; `::test_absence_alone_is_not_evidence` | PARTIAL - **NEW**: load the **real** `data/auction_outcome_wordings.csv` and assert that "Bidder Walked Away", "Auction to be rescheduled" and "Rescheduled" are absent, and that each one yields an `unknown` observation with the wording kept. |
| C04 | Postponement link (proposal) | Once `postponed_to` exists (proposal 7.1), it is set only from a published date. The old and new events stay two rows, and no date is inferred from a re-listing alone. | none | **NEW** (with the migration) |
| C05 | Redemption | `redeemed` / `cancelled` is set only from a published "Redeemed" / "Redeemed After Sale". A certificate leaving the LienHub list is never a redemption. | `test_auction_outcomes.py::test_11_to_15_each_published_result_is_captured`; `::test_15b_redemption_only_when_published`; `test_three_ledger_separation.py::test_certificate_results_are_instrument_results` | covered |
| C06 | Struck off / government retained | `struck_off` (or the proposed `government_retained`) only from a published wording that names it. A Lands Available listing or an FLC listing is INFERRED corroboration only. | `::test_11_to_15_each_published_result_is_captured` ("Struck Off" fixture row); `test_three_ledgers.py::test_t01_an_unsold_auction_becoming_available_keeps_its_auction_event_and_gets_its_own_record` | PARTIAL - **NEW**: an Available row for the same parcel never patches an auction event's outcome (an assertion on the event writer and on any corroboration writer). |
| C07 | Opening bid never becomes a winning bid | `winning_bid` is set only beside the reviewed amount label ("Amount"). An "Opening Bid" label, `properties.bid`, `opening_bid`, a deed consideration or an NAL sale price is never copied into it. | `test_auction_outcomes.py::test_16_published_amount_is_captured_only_beside_its_label`; `::test_17_unpublished_amount_stays_null`; `test_three_ledger_separation.py::test_opening_bid_is_not_a_winning_bid`; `::test_winning_bid_only_from_a_published_sale`; `test_phase_b_auction_event_writers.py::test_writer_can_never_populate_bidder_or_outcome_fields` | covered - **NEW** when deed / NAL sources land: `deed_consideration` and `last_sale_price` never reach `winning_bid` |
| C08 | Disappearance never becomes sold | Absence from Waiting gives `completed` / `unknown` lifecycle only; absence from Closed writes nothing; a passed date alone writes nothing. | `test_auction_outcomes.py::test_01_passed_sale_date_alone_writes_nothing`; `::test_02_03_disappearance_is_never_sold_or_redeemed`; `test_phase_b_auction_event_writers.py::test_listing_gone_before_its_sale_date_is_never_completed`; `::test_listing_seen_on_its_sale_date_then_absent_becomes_completed_outcome_unknown`; `::test_missing_outcome_stays_unknown_and_lifecycle_is_explicit_everywhere` | covered |
| C09 | Purchaser / bidder never stored | No purchaser name or category, no bidder count, no bidder identity, in any table or export. | `test_auction_outcomes.py::test_18_19_bid_count_and_bidder_are_never_written`; `test_phase_b_auction_event_writers.py::test_writer_can_never_populate_bidder_or_outcome_fields` | covered - **NEW** for each new reader (deed index, docket): a grantee / purchaser field is parsed and dropped, never stored or logged |

### 2.2 Matching and joins

| # | Case | What must hold | Existing coverage | Status |
|---|---|---|---|---|
| C10 | Exact case join | County + sale day + exact case number. A published parcel must agree. | `test_auction_outcomes.py::test_04_exact_case_number_produces_the_outcome`; `::test_06b_conflicting_parcel_refuses_the_case_match` | covered |
| C11 | Incorrect joins refused | No fuzzy case, near-identical parcel, owner, address or legal description match. A record with no identifier is refused. Two events sharing a parcel are refused. | `::test_05_exact_parcel_matches_only_when_no_case_is_published`; `::test_06_fuzzy_owner_or_address_cannot_match`; `::test_07_record_without_any_identifier_cannot_produce_an_outcome` | covered |
| C12 | Item / status join by the site's own id | A count mismatch makes the day unreadable (nothing written). | `::test_realauction_adapter_joins_items_to_status_by_the_sites_own_id`; `::test_realauction_adapter_without_status_refresh_is_unavailable_not_unknown` | covered - **NEW**: two items with the same case number on one day give a count mismatch, so the day is unavailable (a fixture with a duplicated case and two ids) |
| C13 | Texas key | A TX outcome reader matches on the CAD account (`case_no`), never on `parcel`, which holds the tax-suit cause number. Two accounts sharing a cause are two events. | `test_phase14a_customer_safety_hardening.py::test_G_two_parcels_sharing_one_cause_number_are_not_treated_as_duplicate_properties` (property level) | **NEW** (before any TX reader) |
| C14 | Instrument / certificate keys (proposal) | `EXACT_INSTRUMENT` only from an instrument number already held, e.g. the NAL `CLERK_NO1`. `EXACT_CERTIFICATE` only on an equal certificate number. A name-indexed search result is never a match. | none | **NEW** |
| C15 | Match method recorded (proposal) | Every observation carries one `match_method` value from the closed vocabulary, and the vocabulary contains no fuzzy method. | none | **NEW** |

### 2.3 Lifecycle, history and corrections

| # | Case | What must hold | Existing coverage | Status |
|---|---|---|---|---|
| C16 | Duplicate events | One event per (property, sale date); repeated sightings are observations; duplicates in one harvest give one observation. | `test_phase_b_auction_event_writers.py::test_same_event_harvested_twice_one_event_many_observations`; `::test_duplicate_rows_in_one_harvest_yield_one_observation`; `test_migration_014_auction_event_history.py` (unique key) | covered |
| C17 | Late results | An event first checked as "not published", and later given a mapped wording, is resolved by an appended observation. | `test_auction_outcomes.py::test_21_verified_result_supersedes_unknown_by_appending`; `::test_21b_an_unchanged_recheck_appends_nothing` | covered |
| C18 | Late results outside the window | An event whose sale day has left the `--days` window is no longer read. A widened one-off run (`--days N`) resolves it if the source still serves the day, and writes nothing if the day read fails. | none | **NEW**: a plan test with a 30-day-old event and `days=45` (pure), plus a CLI test that `--days` reaches the events query |
| C19 | Corrected outcomes | A verified result followed by a *different* mapped wording (e.g. "Auction Sold", then "Redeemed After Sale") appends a new observation and changes the event. The earlier observation is never updated or deleted. With the proposal, `supersedes_observation_id` points at the earlier row and `outcome_status='corrected'`. | none - `plan_outcomes` handles it today (the stored state differs, so it patches), but no test pins the behaviour | **NEW** |
| C20 | Conflicting records | Two REPORTED sources disagree on one event, with no correction wording: the event is held at `conflicting`. Neither side wins, and both observations are kept. | none | **NEW** (with the proposal) |
| C21 | Temporary failure | A failed read writes nothing and never downgrades a verified result. | `test_auction_outcomes.py::test_20_temporary_source_failure_preserves_the_verified_outcome` | covered |
| C22 | Re-listing after a derived state | Re-sighting returns the event to `scheduled` and keeps the history. | `test_phase_b_auction_event_writers.py::test_resighted_completed_event_goes_back_to_scheduled_and_keeps_history` | covered |
| C23 | Append-only | No code path updates or deletes `auction_event_observations`. | `test_auction_outcomes.py::test_21_verified_result_supersedes_unknown_by_appending` (source grep) | covered |

### 2.4 Completeness and coverage reporting

| # | Case | What must hold | Existing coverage | Status |
|---|---|---|---|---|
| C24 | Truncated closed listing is reported | When the second page repeats the first, the day is marked possibly incomplete. Today `fetch_area()` breaks on `fresh == 0` without setting `truncated`, so `DayRead.complete` stays True. The report must count such days (`days_possibly_truncated`), and an item absent from a possibly truncated day is never treated as checked. | none | **NEW** (and the code fix in backlog C-1) |
| C25 | Evidence validity | A login page, a search-engine result or a homepage is never evidence. | `test_auction_outcomes.py::test_08_login_page_is_not_evidence`; `::test_09_search_engine_result_is_not_evidence`; `::test_10_homepage_is_not_evidence` | covered |
| C26 | Coverage report denominators | A counts-only coverage report gives total, past, verified (sold / redeemed / cancelled), unknown, winning bid and deed-confirmed per state, county and month. Every percentage names its denominator, and the report never contains a "sold rate" label. | none | **NEW** (with backlog C-6) |
| C27 | Cross-ledger isolation | The outcome writer never writes `properties`, Available rows or certificate rows. | `test_auction_outcomes.py::test_22_a_failed_auction_never_writes_the_available_ledger`; `test_phase_b_auction_event_writers.py::test_writer_reads_but_never_writes_properties` | covered |
| C28 | Expansion results in events (if built) | MI Eaton "Has Been Sold" and WI Green "Previous Sales" become event observations only with REPORTED basis and the source's own wording, with a sale amount only from WI's Sale Price. | none | **NEW** (backlog C-5) |
| C29 | Scope pin | No LGBS, GovEase or Bid4Assets reads, and no new state, without an explicit change to this test. | `test_auction_outcomes.py::test_28_no_lgbs_govease_and_no_new_state` | covered (update deliberately when TX is approved) |
| C30 | Wording table discipline | Every enabled row cites a capture run and a date. The result vocabulary is finite, and an amount label is allowed only on a sale. | `::test_wording_table_is_valid_and_every_enabled_row_cites_an_observation`; `::test_wording_table_refuses_unreviewed_rows` | covered |

### 2.5 Live validation (manual, read-only, owner-authorized)

1. **Dry run.** `job=outcomes` with `--dry-run`, then compare `verified_new`, `not_published`,
   `unmatched_reasons` and per-county `records` with the baseline. A rise in `unmatched_reasons["no event with
   this case number on this sale day"]` signals a case-format drift.
2. **Truncation check.** After C24 lands: count days whose read returned exactly ten records. The expected
   denominator is the number of (county, sale day) pairs in the window.
3. **Re-measurement.** Repeat the baseline queries (outcome-coverage-baseline.md section 8) and report each
   delta against the same denominators: 531 FL past, 257 FL past unknown, 86 TX past.

## 3. Workstream A: listings (required cases)

| # | Case | What must hold | Existing coverage | Status |
|---|---|---|---|---|
| L01 | Missing ≠ negative | A bare zero is never EMPTY. EMPTY needs a named signal and no rows. A missing status file closes nothing. An INCOMPLETE or FAILED read never closes a row. | `test_laft_status.py::test_c01_a_bare_zero_is_never_empty_and_never_complete`; `::test_c02_empty_requires_a_named_signal_and_no_rows`; `test_laft_lifecycle.py::test_d02_incomplete_source_and_property_absent_remains_active`; `::test_d03_failed_source_and_property_absent_remains_active`; `::test_d08_missing_status_file_closes_nothing`; `test_laft_lifecycle_ledger_health.py::test_missing_status_closes_nothing`; `::test_an_invalid_empty_is_incomplete_and_closes_nothing`; `test_three_ledgers.py::test_d03_empty_is_only_valid_after_a_successful_read` | covered |
| L02 | Stale handling | Old or undated status entries read STALE. A stale read closes nothing. Stale rows are admin-only and keep their path. | `test_laft_status.py::test_s01_effective_status_downgrades_old_or_undated_entries_to_stale`; `test_laft_lifecycle_ledger_health.py::test_a_failed_partial_or_stale_read_closes_nothing`; `test_publication_state_gate.py::test_e13_stale_observation_and_passed_sale_date_are_admin_only_stale_with_the_path_kept`; `::test_e14_county_path_evidence_older_than_180_days_is_stale_not_missing` | covered - **NEW** for the TX manual-only units: `manual_only` is never aged by the clock and never advanced (pin against `unit_freshness.MANUAL_ONLY_SOURCES`) if the workstream touches them |
| L03 | Per-county failure isolation | One failed county or source closes nothing elsewhere. A sibling's complete read never closes another source's rows. One ledger's failure never empties another ledger. | `test_laft_lifecycle_ledger_health.py::test_one_failed_source_blocks_the_county_but_never_closes_by_a_sibling`; `::test_a_sibling_sources_complete_read_never_closes_another_sources_rows`; `::test_a_row_without_a_source_is_not_closed_when_the_county_has_several_sources`; `test_three_ledgers.py::test_d02_a_failed_or_unreachable_read_in_one_ledger_closes_nothing_and_never_empties_another` | covered |
| L04 | Dedup | Identity is (state, source, county, case_no). Duplicate identifiers keep the first listing. Duplicate database rows are rejected untouched. An upsert batch never updates one conflict target twice. | `test_available_expansion_mo_ok_pa_mn.py::test_dedupe_identity_is_county_source_case_no`; `test_six_state_expansion.py::test_f02_duplicate_identifiers_keep_the_first_listing`; `test_laft_source_fields.py::test_m04_ambiguous_duplicate_database_rows_are_rejected_untouched` | PARTIAL - **NEW** for each new listing source: a fixture with a repeated identifier gives one row, and the sync body contains no duplicate conflict key (the 2026-08-25 certificates failure mode) |
| L05 | Reappearance | A closed row that reappears is reactivated, and is never closed in the same run. | `test_laft_lifecycle.py::test_d05_reappearance_of_a_closed_property_reactivates`; `test_laft_lifecycle_ledger_health.py::test_a_reactivated_row_is_never_closed_in_the_same_run` | covered |
| L06 | Keyset population reads | No offset paging in sync, lifecycle or status writers. | `test_current_state_sprint.py::test_no_offset_paging_left_in_the_population_readers`; `::test_keyset_reads_every_row_exactly_once_across_pages`; `test_gap_closure.py::test_change_detection_reads_the_population_by_keyset`; `::test_inventory_status_and_publication_gate_read_by_keyset` | covered for those scripts - **NEW** if the workstream adds a population read. Note: `auction_outcomes.Api.get_all` still uses offset paging; it is bounded by the 21-day window. |

## 4. Workstream B: permissions (required cases)

| # | Case | What must hold | Existing coverage | Status |
|---|---|---|---|---|
| P01 | A blocked source cannot activate | A hard-blocked vendor is denied for every operation and every entry point. Editing the record, stale evidence or a publication review cannot unblock it. | `test_source_permissions.py::test_govease_is_denied_for_every_operation`; `::test_govease_cannot_be_unblocked_by_editing_the_record`; `::test_stale_or_missing_evidence_cannot_unblock_govease`; `::test_govease_block_holds_on_every_other_layer`; `::test_a_publication_review_cannot_publish_a_blocked_vendor`; `test_permission_gaps.py::test_govease_denied_by_every_entry_point_helper`; `test_discovery_guard.py::test_blocked_and_restricted_vendors_are_refused` | covered - **NEW**: parametrize the "every entry point" test over all four blocked ids (`tx_pbfcm`, `tx_mvba`, `tx_ctsa`, `tx_govease`), not GovEase alone |
| P02 | Official-link-only is never harvested | A LINK_ONLY record allows `link` and denies fetch, parse, store and display. | `test_source_permissions.py::test_link_only_allows_only_the_link` | covered - **NEW**: an end-to-end check that a LINK_ONLY source added to the registry gets zero requests from the discovery guard and the harvest runner |
| P03 | Geometry approval does not authorize attributes or listings | `fl_dor_pto_parcel_gis` / `ut_ugrc_lir_saltlake` approvals cover their geometry datasets only. They never cover export, proxy fetch, other datasets, other states, or `fl_fdor_cadastral` attributes. Unrelated attributes are never requested with geometry. | `test_parcel_source_approvals.py::test_scope_excludes_unrelated_data`; `::test_florida_never_covers_export_proxy_other_datasets_or_states`; `::test_utah_never_covers_export_other_sources_or_states`; `::test_florida_approval_leaves_existing_florida_sources_unchanged`; `::test_the_two_approvals_are_independent`; `test_parcel_boundaries.py::test_unrelated_assessment_attributes_are_never_requested_with_geometry` | covered |
| P04 | Unresolved fails closed | An unknown source, operation or state denies. An open status without an interim allowance denies. An invalid or unreadable file denies everything. Expired records deny. A source with no records reads "denied" in the inventory. | `test_source_permissions.py::test_unknown_source_denies`; `::test_unknown_operation_and_missing_state_deny`; `::test_an_open_status_without_an_interim_allowance_denies`; `::test_invalid_or_unavailable_configuration_denies_everything`; `::test_expired_permission_denies_and_in_date_allows`; `::test_conflicting_records_deny`; `test_permission_gaps.py::test_inventory_basis_for_a_source_without_records_says_denied`; `test_discovery_guard.py::test_invalid_governance_configuration_denies` | covered - **NEW** for Workstream C: a results dataset with no record (e.g. `fl_bid4assets_okaloosa` results, `fl_lienhub_certificates` redemptions) is denied even though the same source has an allowed record for a different dataset |
| P05 | Attribution preserved | A display that needs attribution is denied until the full attribution is recorded, and the read contract returns it. | `test_parcel_source_approvals.py::test_utah_display_needs_the_full_attribution_including_a_disclaimer`; `::test_utah_attribution_carries_ugrc_credit_and_the_cc_by_link`; `test_parcel_boundaries.py::test_the_read_contract_returns_the_full_attribution` | PARTIAL - **NEW**: CC BY-SA sources (Douglas CO) carry their attribution on every customer surface and in every export that includes their rows |
| P06 | A permission change does not silently activate | An interim allowance is never documented permission. A terms change does not keep an approval. A registered state stays inactive until activation. Blocked never activates. | `test_source_permissions.py::test_internal_risk_acceptance_is_never_documented_permission`; `test_phase39_acquisition_engine.py::test_adv_14_terms_change_does_not_silently_preserve_approval`; `test_parcel_source_approvals.py::test_the_utah_state_is_still_not_activated`; `test_ledger_eligibility.py::test_engine_has_no_failure_and_blocked_never_activates`; `test_state_expansion_la.py::test_s02_sync_syncs_nothing_for_a_unit_that_was_not_read_and_refuses_unactivated_states` | PARTIAL - **NEW**: changing a `source_permissions.csv` row from denied to allowed changes neither the registry `publication_status`, nor state activation, nor any workflow schedule. A source still needs its own reviewed publication decision before customers see a row. |
| P07 | Interim expiry is visible | Allowances report before they expire. Every INTERIM record behind an outcome source (`fl_realauction` closed_results, 2027-04-12) appears in `source_permission_check.py --due`. | `test_source_permissions.py::test_allowances_expire_and_are_reported_before_they_do` | covered |

## 5. Measurement rules for every coverage claim

- Report numerator and denominator together. Examples: "285 of 531 FL past events carry a source-stated result",
  "172 of 172 sold events carry a published amount".
- Never compute or label a sold rate, a win rate or a bidder metric (outcome-coverage-baseline.md, preface).
- A derived number names its derivation, as the 11 / 47 / 198 / 1 split is in the baseline.
- An "unknown" is never counted as a negative (unsold, not redeemed), and "not attempted" is reported apart from
  "source unavailable".

## Permission enforcement gaps found in code (Workstream B)

Repository state analysed: `main` at `9498836`.
Read-only analysis; nothing was run against production. Each gap below was found by reading the code path it names,
and several were confirmed by calling `permissions.authorize()` locally (evaluation date 2026-10-22). Line numbers
refer to `main` at `9498836`.

"Covered?" says whether an existing test already catches the gap. Where a test exists but stubs the decisive
function, it is listed as **not covered** and the stub is cited.

PR #158 (`claude/hopeful-feynman-ykxl7y`, **unmerged**) adds `harvesters/governance/source_rights.py`, which
reconciles the 2026-10-12 register with the permission records and reports `CLIENT_SIDE_NO_RECORD` for the
browser map providers. It is a report: it adds no enforcement at any call site below. Gaps T-6 and T-8 overlap its
findings. The others are not addressed by it.

### Summary

| # | Gap | Direction | Size (baseline 2026-10-22) | Covered? |
|---|---|---|---|---|
| T-1 | CSV export never checks `redistribute` | Leaks: exports data whose redistribution is RESTRICTED or not recorded | Every exportable row; co_oit fields on 141 CO rows; FDOR fields on FL rows | No |
| T-2 | Values from enrichment sources are displayed without a `display` record for that source | Leaks: display not permitted | FDOR, CO OIT, EBR tax roll/parcels, FEMA, Census, Santa Rosa, Palm Coast | No |
| T-3 | `publication_state._display_permitted` ignores the record's dataset | Over-withholds: every FL source reads `NO_RECORD` | All FL rows once 031 + writer run (≈2,834 active) | No (stubbed) |
| T-4 | Before 031, customer display ignores `display` permission and its expiry; a NULL `publication_status` is shown | Leaks after expiry; shows rows with no decision | 2,798 active NULL-publication rows; all interim-display rows after 2027-04-12 | No |
| T-5 | Boundary display grant is a static DB boolean, not tied to the permission record | Leaks after expiry or after a condition fails | All stored boundaries (FL 64 written so far) | No |
| T-6 | Browser map/imagery providers are outside the permission engine | Unrecorded commercial use | Every map view; Google Demo Key in production | No (PR #158 reports it, unmerged) |
| T-7 | `excluded_from_paid_tier` condition is vacuous | Condition can never fail | co_oit values on Douglas/Morgan rows | No (tests stub the checker) |
| T-8 | Registry `governance_status` / config `publication_status` contradict the permission records | Two sources of truth; registry can publish what the record has not cleared | 20+ sources | No |
| T-9 | Attribution conditions check that text is recorded, not that it is shown or exported | Licence condition unmet on export | Douglas CC BY-SA, EBR, NAIP, UGRC | No |
| T-10 | `source_publication.permitted()` drops county and dataset | Latent: county/dataset records ignored for registry sources | None today | No |
| T-11 | A link-only source with no `link` record is denied linking | Over-withholds (minor) | wi_dane_tax_deed_auction | No |
| T-12 | `WRITTEN_PERMISSION` validation does not require the document | Documented basis rests on an absent document | fl_dor_pto_parcel_gis | Pinned as intended (see below) |

---

### T-1. The customer CSV export never asks for `redistribute`

**Code path.** The export lives in `public/app.js:11368-11609`:

- The click handler is at `11368`.
- `availableCols` starts at `11377`; the general `cols` at `11445`.
- The blob is built at `11609`.

The handler exports whatever is in `ALL` that passes the List filters. `redistribute` ("export, API, resale or any
re-publication outside the app", `harvesters/governance/permissions.py:71`) is evaluated nowhere in `public/`,
`scripts/` or `supabase/`. A grep for `redistribute` finds only the engine, the CLI and a docstring.

**What it exports.**

- `owner_name` (`11425` "Name Assessed", `11453` "Owner").
- `market`, `taxable_value`, `assessed`, `legal_desc`, `acreage` and `land_use` (`11416-11424`).
- `latitude`, `longitude` and `flood_zone` (`11429-11431`).

On Colorado rows these fields come from `co_oit_public_parcels`. Its `redistribute` record is `RESTRICTED`, with the
reason "Resale of the data is forbidden by the State's terms" (`data/source_permissions.csv`, co_oit redistribute
row). On Florida rows they come from `fl_fdor_cadastral`, whose `redistribute` record is LEGAL_REVIEW_REQUIRED with
no allowance. No source in the file holds an allowed `redistribute` record, so every export is unpermitted by the
engine's own rule.

**Existing tests.**

- `tests/python/test_phase22_track_f_verification.py:87-215` pins the export column list against field-name *shapes*.
- `tests/python/test_source_permissions.py:128` asserts the engine returns `RESTRICTED` for co_oit redistribute.

Neither connects the export to the engine. **Not covered.**

**Proposed tests.**

1. new `tests/python/test_export_redistribute_gate.py::test_every_exported_source_has_redistribute_or_is_excluded`.
   - Parse the `availableCols` / `cols` / `certificateCols` accessors in `public/app.js`. Use the same transcription
     technique `test_phase22_track_f_verification.py` already uses.
   - Map each column to the source(s) that can populate it: the row source, plus every enrichment source whose
     `field_map` writes that column (`harvesters/enrichment/sources.py`, `scripts/enrich_property_details.py`).
   - Assert one of two things for every (column, source) pair: `permissions.authorize(source, "redistribute", ...)`
     is allowed, or app.js carries an explicit exclusion for that source and column.
   - Expected to FAIL today. That failure is the gap.
2. A Playwright check `exportExcludesRestrictedSources`.
   - Use a stub row (`tests/vendor/supabase-stub.js`) whose `field_provenance.owner_name.source` is
     `statewide_parcel` with dataset co_oit.
   - Assert the downloaded CSV has an empty `Owner` cell, or that the export is refused with a reason.

### T-2. Enrichment values are displayed with no `display` record for their source

**Code path.**

- Enrichment writes into `properties`:
  - `scripts/enrich_property_details.py:1258-1281` writes `market`, `assessed`, `owner_name` and the centroid
    `latitude`/`longitude` from FDOR, plus `acreage` and `land_use` at `1321-1324`;
  - `harvesters/enrichment/parcels.py:226` writes the parcel-layer values.
- The gates ask only for the enrichment source's `fetch` + `enrich`:
  - `harvesters/enrichment/parcels.py:218-230` (`recorded_permission`) and `238-246` (`enrichment_allowed`);
  - `scripts/enrich_property_details.py:1400-1415`.
- Customer display asks only the **row's own** source:
  - `harvesters/governance/publication_state.py:357`;
  - `scripts/source_publication.py:76-81`.

Nothing asks `authorize(<enrichment source>, "display")`.

**Records.** `docs/source-permissions.md:199` says of FDOR: "Every other operation has no allowance and is denied.
That covers display ...". Yet `public/app.js` shows those values; for example, Taxable Value at `9348` and the
assessor land-use label at `8757-8761`. The same pattern holds for every source below. None has a `display` record:

- `co_oit_public_parcels`;
- `la_ebr_tax_roll`, `la_ebr_tax_parcels`;
- `fema_nfhl` (flood zone);
- `census_geocoder` (coordinates);
- `fl_santa_rosa_parcels`, `fl_palm_coast_flagler_parcels`.

`ut_ugrc_lir_saltlake` is the only enrichment source with a `display` record.

**Existing tests.** `tests/python/test_permission_gaps.py` covers fetch/enrich refusal inside the FDOR lookups
(`171-212`), not display. **Not covered.**

**Proposed tests.**

1. new `tests/python/test_enrichment_display_gate.py::test_enrichment_sources_whose_values_are_rendered_have_display`.
   - Build the set of enrichment source ids from `harvesters/enrichment/sources.py`, plus the FDOR / Santa Rosa /
     Palm Coast / Census / FEMA writers.
   - Assert each one either has an allowed `display` decision, or is listed in a new explicit
     `DISPLAY_WITHHELD_FIELDS` map that the frontend honours.
   - Expected to FAIL today for 8 sources.
2. A unit test for a proposed helper, `field_display_permitted(row, column)`, in `publication_state.py`.
   - It takes `field_provenance[column].source` and dataset and evaluates display for that source.
   - A row whose `market` came from `fdor_nal` must return False until a display record exists.

### T-3. `publication_state._display_permitted` drops the dataset, so every Florida source is `NO_RECORD`

**Code path.**

- `harvesters/governance/publication_state.py:201-203` calls
  `PERM.authorize(source_id, "display", state=state, county=county or None)` with no `dataset`.
- That result is used by `decide()` at `357`.

Every Florida listing record is dataset-scoped:

| Source | Dataset |
|---|---|
| `fl_realauction` | `sale_calendar` |
| `fl_bid4assets_okaloosa` | `sale_calendar` |
| `fl_lienhub_certificates` | `county_held_certificates` |
| the nine `fl_laft_*` | `lands_available` |

`_applicable()` (`permissions.py:390-404`) matches a named dataset only when the caller names it. The local
evaluation on 2026-10-22 returned `False` for each of `fl_realauction`, `fl_lienhub_certificates`, `fl_laft_html`,
`fl_laft_realtdm` and `fl_bid4assets_okaloosa`, and `True` for `tx_lgbs` and `sc_york_tax_sale`.

`scripts/source_publication.py:69-73` has the same omission (`permitted()`). `publishable()` and `collectable()`
therefore return `PERMISSION_NO_RECORD` for every FL source too. It does not bite today, because
`source_publication` is only called for expansion and LA sources.

**Effect.** This fails closed, so nothing leaks, but it is wrong. Once migration 031 is applied and
`publication_state_writer.py` runs for FL, every FL row is decided `SOURCE_RESTRICTED`. The baseline has
1,065 + 1,611 + 158 = 2,834 active rows, all of which customers would lose, although the records do allow display.

**Existing tests.** `tests/python/test_publication_state_gate.py:52` replaces `display_permitted` with a lambda, so
the real dataset handling is never exercised. **Not covered.**

**Proposed tests.**

1. `test_publication_state_gate.py::test_real_display_permission_uses_the_sources_dataset`.
   - Run `build_context()` without stubbing `display_permitted`.
   - Decide one active row each for fl_realauction, fl_lienhub_certificates and fl_laft_html.
   - Assert `gates["source"] == "PASS"` (registry APPROVED_GRANDFATHERED plus the interim display records).
   - Fails today.
2. `test_source_permissions.py::test_source_publication_permitted_passes_dataset_and_county` (existing file; it already imports `source_publication`).
   - Assert that `permitted()` forwards the registry row's county and the source's dataset.
   - Assert that a county-scoped DENY record (fixture via `permission_fixtures.install`) wins over the state record.
   - This also covers T-10.

The fix needs one place that maps source_id to the permission dataset key. Today that mapping is implicit in
`laft_status.permission_gate` (`lands_available`), `stamp_seen.STORE_SOURCES` and
`auction_events_writer.STORE_SOURCES`. Add a test that pins those maps against the dataset values in
`data/source_permissions.csv`.

### T-4. Before 031, customer display ignores `display` permission and its expiry, and NULL means "show"

**Code path.**

- `public/app.js:702-705` (`isCustomerPublishable`) returns `true` when `publication_status` is null.
- `public/app.js:872-885` (`isPublishable`) uses it for every non-admin while `PUBLICATION.enforced` is false
  (031 not applied).
- The stored `publication_status` is written without any permission check:
  - `scripts/publication_gate.py:127-145` (`plan()` takes `pub.row_publication()` from the registry/review decision);
  - `scripts/sync_state_inventory.py:266` (`effective_publication(reg)`).

`docs/source-permissions.md:105,152-153` states that display is gated in `publishable()` /
`publication_state.decide()`. That is true for the writers' own decisions, but neither one feeds what the browser
filters on today.

**Effect.**

- Baseline: 2,798 active rows carry NULL `publication_status` and are customer-visible with no decision at all.
  - `fl_realauction` 1,065;
  - `fl_lienhub_certificates` 1,611;
  - `tx_realauction` 103;
  - `tx_lgbs` auctions 19.
- On 2027-04-12 every interim `display` record expires. The engine will deny, but nothing on screen changes for the
  4,524 active rows shown under interim display today.

**Existing tests.** None connects a `display` denial to `publication_status` or to the browser rule. **Not covered.**

**Proposed tests.**

1. `test_available_commercialization.py::test_publication_gate_plan_downgrades_rows_whose_display_permission_is_denied` (existing file that exercises `publication_gate`).
   - Install permission fixtures with display EXPIRED for one laft source.
   - Assert `plan()` moves its rows to a non-publishable status (e.g. `RESTRICTED`).
2. `test_five_state_enrichment.py::test_sync_written_publication_status_reflects_display_permission` (existing file that exercises `sync_state_inventory`). Same idea, for the
   expansion sync at `:266`.
3. Playwright, `nullPublicationNotCustomerVisible`.
   - Stub a non-admin, non-preview session and a row with `publication_status: null`.
   - Assert it is not rendered.
   - This is a behaviour change: owner decision needed. Today NULL deliberately "keeps today's behaviour"
     (`harvesters/governance/publication.py:35-40`).

### T-5. The parcel-boundary display grant is a static DB boolean

**Code path.**

- `scripts/migrations/034_parcel_boundaries.sql:35` declares `display_approved boolean`. It is seeded `true` for both
  sources (`54-66`) with `on conflict do nothing`.
- `get_property_boundary()` returns the literal `true` as `display_permitted` (`153`) and filters on
  `s.display_approved` (`160`). Migration 035 repeats this at `112` / `120`.
- No script ever recomputes it. A grep for `display_approved` in `scripts/` and `harvesters/` finds nothing.
- The permission records decide display differently:
  - FL display expires 2027-10-20;
  - UT display expires 2027-10-12, and its condition `attribution_terms_recorded` must keep holding.
- `harvesters/boundary/sources.readiness()` (`harvesters/boundary/sources.py:103-124`) computes `display_allowed`
  but only reports it.

**Existing tests.**

- `tests/python/test_parcel_boundaries.py:406` asserts the SQL text contains `s.display_approved`.
- `tests/python/test_migration_034_parcel_boundaries.py:182-187` toggles the column by hand.

Neither ties it to `authorize()`. **Not covered.**

**Proposed tests.**

1. `test_parcel_boundaries.py::test_seeded_display_approved_equals_authorize_display`.
   - For each source in `harvesters/boundary/sources.SOURCES`, assert the migration's seeded `display_approved`
     equals `readiness(src)["display_allowed"]` today.
   - With `today=` set past the expiry, assert `display_allowed` is False. This proves a refresh path is needed.
2. Once a writer exists (`parcel_boundary_refresh.py --apply` or a new `--sync-display`): assert it PATCHes
   `display_approved=false` when `authorize(display)` denies. Live-Postgres variant in
   `test_migration_034_parcel_boundaries.py`.

### T-6. Browser map and imagery providers are outside the permission engine

**Code path.**

- `public/app.js:1732-1752` (`staticImageUrl`) uses the MapTiler static API, falling back to the Google Static Maps
  hybrid.
- `public/app.js:2301-2304` and `8800` embed an OpenStreetMap iframe.
- `public/satellite-map.js:156-163`, `447` and `667` load the Google Maps JS and MapTiler/MapLibre basemaps.
- `harvesters/imagery/__init__.py:110-117` (`usable()`) decides from `terms_status` alone and is never called. A grep
  finds no caller.

There are no permission records for `google_static`, `maptiler_static`, Google Maps JS, MapTiler tiles or OSM. The
Google key is a Demo Key. Google documents it as testing-only, and it is listed as pre-sale blocker 7
(`docs/legal/pre-sale-blockers.md`).

**Existing tests.** None.

- PR #158 (unmerged) reports `CLIENT_SIDE_NO_RECORD` for these sources but enforces nothing.

**Not covered.**

**Proposed tests.**

1. new `tests/python/test_imagery_permissions.py::test_every_client_provider_has_a_permission_record`.
   - The provider set is the keys of `harvesters/imagery.SOURCES` with `delivery` containing `provider_static`, plus
     a pinned list of the JS/iframe providers found by grepping `public/*.js` for `maps.googleapis.com`,
     `api.maptiler.com` and `openstreetmap.org`.
   - Assert each has a `display` record, or that the config flag disabling it is pinned off.
   - Fails today.
2. `test_imagery_permissions.py::test_usable_consults_permissions`.
   - `usable("usda_naip", "stored")` must be False when the usda_naip `store` record is expired. Use a fixture
     `today=`.

### T-7. The `excluded_from_paid_tier` condition can never fail

**Code path.** `harvesters/governance/permissions.py:335-336` returns `rec.source_id not in _paid_beta_sources()`.

The condition sits on `co_oit_public_parcels` records, and co_oit is an enrichment layer, never a registry/listing
source. So it can never be in `data/paid_beta_sources.csv`, and the condition is always true.

The real exposure is different: co_oit values riding on Colorado rows of a paid-beta source.
`data/paid_beta_sources.csv` keeps `co_douglas_county_held_liens` and `co_morgan_county_held_certificates` at
`paid_beta=no`, but only by a prose reason. If either is flipped to `yes`, nothing fails.

**Existing tests.**

- `tests/python/test_source_permissions.py:124` and `tests/python/test_interim_expiry.py:97-99` replace the checker
  with a lambda.
- The real checker is never evaluated against a paid-beta CO source.

**Not covered.**

**Proposed test.** `test_source_permissions.py::test_excluded_from_paid_tier_fails_when_an_enriched_state_source_is_paid_beta`.

1. Monkeypatch `_paid_beta_sources` to include `co_douglas_county_held_liens`.
2. Assert `authorize("co_oit_public_parcels", "enrich", state="CO")` is denied with `CONDITION_UNMET`.

Fails today. The fix is for the checker to consider paid-beta sources in the enriched source's state and counties
(`harvesters/enrichment/sources.CO_OIT_PARCELS.state` / `county_field`).

### T-8. The registry and code configs contradict the permission records

**Code path.**

- `harvesters/governance/publication.py:83-94` (`effective_publication`) downgrades only when the registry's
  `governance_status` is `LEGAL_REVIEW_REQUIRED` or `BLOCKED`.
- `data/county_source_registry.csv` records `governance_status=APPROVED` for sources whose permission records say
  otherwise.

| Source(s) | Registry governance | Permission record |
|---|---|---|
| `tx_lgbs`, `tx_realauction` | APPROVED | LEGAL_REVIEW_REQUIRED |
| `wi_dane_tax_deed_auction` | APPROVED | RESTRICTED |
| `sc_oconee_tax_sale_list`, `co_morgan_treasurer_deed_auctions` | APPROVED | OWNER_PERMISSION_REQUIRED, NO_EVIDENCE |
| the six owner-accepted expansion sources | APPROVED | OWNER_PERMISSION_REQUIRED, interim |
| the ten admin-only AVAILABLE sources | APPROVED | OWNER_PERMISSION_REQUIRED, interim |

`harvesters/enrichment/sources.py:77` sets `CO_OIT_PARCELS.publication_status="APPROVED"`, and
`harvesters/enrichment/parcels.py:241` accepts that as "reuse cleared", while the permission record is
OWNER_PERMISSION_REQUIRED interim. The registry is the gate for publication, while `source_permissions.csv` is the
gate for operations. Nothing checks that they agree.

**Existing tests.** None check registry governance against permission status. PR #158 (unmerged) reconciles the
2026-10-12 *register* with the records, not the registry `governance_status`. **Not covered.**

**Proposed test.** `test_source_permissions.py::test_registry_governance_never_exceeds_the_permission_record`.

- For every registry row with a source_id, `governance_status in {APPROVED}` requires every `fetch`/`store` record of
  that source to be `APPROVED*` on `DOCUMENTED_EVIDENCE`.
- `APPROVED_GRANDFATHERED` requires interim evidence.
- Enrichment configs get the same check: `publication_status="APPROVED"` requires documented records.

Fails today for 20+ sources. The fix is a data change (relabel to `APPROVED_GRANDFATHERED` or a new `INTERIM` value).
That is an owner decision, out of scope for this draft.

### T-9. Attribution conditions are checked as recorded text, never as rendered or exported text

**Code path.** `harvesters/governance/permissions.py:344-345` (`_cond_attribution_text_recorded`) checks only that
the permission row's `attribution` column is non-empty.

- Douglas County CC BY-SA 4.0 is attributed in the UI source label (`public/app.js:2738-2740`) and in ledger copy
  (`1176`, `1285`). The CSV export (T-1) carries no attribution or licence column.
- The NAIP, EBR Assessor and UGRC attributions have the same problem for exports.

**Existing tests.** None for exports. **Not covered.**

**Proposed test.** `test_export_redistribute_gate.py::test_export_carries_attribution_for_licence_conditioned_sources`.
When an export can contain rows or fields from a source whose records name `attribution_text_recorded`, the CSV
must include that attribution text (e.g. a trailing `Source attribution` column, or a header comment line). This
applies only once T-1 allows any such export.

### T-10. `source_publication.permitted()` drops county and dataset (latent)

`scripts/source_publication.py:73`, `81`, `101` and `108` call `authorize(source_id, op, state=row.state)` with no
county and no dataset. A county-scoped record, like the `fl_laft_pdfs` Volusia row, would be ignored for any
registry source routed through this helper. Today no expansion source has a county or dataset record, so nothing is
affected. This is the same fix and test as T-3 (2).

### T-11. A link-only decision with no `link` record

The `wi_dane_tax_deed_auction` records say "link only" (RESTRICTED fetch/parse/store), but there is no `link`
record. So `authorize(..., "link")` returns `NO_RECORD`, and the decision can never be honoured through the engine.

**Proposed test.** `test_source_permissions.py::test_every_link_only_reason_has_a_link_record`: any record whose
`reason` says "link only" implies a `LINK_ONLY` `link` record for that source. It fails today for one source.

### T-12. `WRITTEN_PERMISSION` validation does not require the document (pinned as intended)

`harvesters/governance/permissions.py:281-298` checks only the authorization status and scope.
`fl_dor_pto_parcel_gis` passes with `written_permission=False` and `document_location=None`
(`harvesters/governance/authorization.py:1058-1075`, `1101`). The documented basis therefore rests on the owner's
relayed summary.

`tests/python/test_parcel_source_approvals.py:189` asserts this state explicitly
(`written_permission is False and document.is_pending`). It is **covered as intended**, not as a defect. Tightening
it would deny the Florida boundary path, so it is an owner decision. See backlog item B-03.

---

### Already covered (checked, no gap)

| Path | Test |
|---|---|
| Hard-blocked vendors denied whatever the file says; invalid file denies all | `tests/python/test_source_permissions.py`, `test_permission_gaps.py:352-379` |
| Interim expiry boundaries (`NOT_YET_EFFECTIVE`, inclusive expiry, `EXPIRED`, no fallback, 210-day cap) | `tests/python/test_interim_expiry.py` |
| Florida PowerShell harvesters/syncs refuse before any request | `tests/python/ps1_permission_guard.py`, `test_permission_gaps.py:330-343` |
| FL LAFT harvesters `permission_gate` | `tests/python/test_laft_harvester_gates.py` |
| Lifecycle / stamp_seen / auction_events_writer / apply_acquisition_paths store gates | `test_permission_gaps.py:73-160` |
| FDOR / Santa Rosa / Flagler lookups refuse before any request (fetch/enrich) | `test_permission_gaps.py:171-212` |
| Discovery guard (no `discover` record means no request) | `tests/python/test_discovery_guard.py` |
| Boundary readiness needs approval + mapping + fetch/parse/store | `tests/python/test_parcel_boundaries.py`, `test_fl_dor_boundaries.py` |
| No approval covers export/redistribution of geometry | `test_parcel_boundaries.py:132`, `test_parcel_source_approvals.py:194` |
