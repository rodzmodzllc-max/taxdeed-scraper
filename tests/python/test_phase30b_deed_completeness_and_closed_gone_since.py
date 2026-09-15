"""Phase 30B (Deed Per-County Completeness Gate + `closed` gone_since Fix)
tests, following claude/phase-30b-deed-completeness-and-closed-gone-since.md.

Eliminates the deed-pipeline data-integrity blocker Phase 29/30 identified:
`sync-harvest-to-supabase.ps1`'s stale-property closeout had no per-county
completeness gate at all (unlike the certificate pipeline's, built in
Phase 23B) - a county whose harvest failed transiently would have every one
of its still-genuinely-listed active properties wrongly flipped to
'closed'. Also fixes a second, independently-discovered false-closure risk
in the same closeout query: no `state` filter, meaning a Texas auction
property (Texas's own RealAuction harvest also writes source='auction' -
see harvesters/texas_harvester.py) whose sale_date passed could have been
silently closed out by the FL-only deed sync job. And separately adds
`closed` to the `gone_since` trigger pair's recognized status list
(scripts/migrations/006_add_closed_to_gone_since_status_list.sql), since
`closed` is a real, live FL auction status the trigger previously ignored
even though app.js's own GONE_STATUSES constant expects it to be tracked.

## Why this file mixes two kinds of test (same discipline as
## test_phase23_certificate_reconciliation.py)

`harvest_all_counties.ps1`, `harvest_okaloosa_bid4assets.ps1`, and
`sync-harvest-to-supabase.ps1` are PowerShell; this sandbox has no `pwsh`
available to execute them (same constraint documented in
test_phase23_certificate_reconciliation.py). Two layers of evidence:

1. **Structural/text assertions** against the actual script/migration
   contents - proving the specific guards, ordering, and query/patch shapes
   this phase's safety invariant demands are actually present in the code
   that will run in production.
2. **`_close_out()`** - a literal, minimal port of the one piece of
   sync-harvest-to-supabase.ps1's closeout step that actually carries
   false-closure risk (which existing active (id, county, case_no) rows are
   absent from their own COMPLETE county's harvested key set this run) -
   structurally identical to test_phase23's `_reconcile()`, since Phase 30B
   deliberately reused that proven decision shape for the closeout step
   (see the file's own header comment on why the *harvester's* completeness
   signal could not be copied verbatim, even though the *reconciliation
   decision* itself could).

Do not assume the certificate implementation could be copied verbatim into
the harvester layer: RealAuction's AJAX feed has no server-reported total
like LienHub's `recordsTotal`, so completeness there is defined by "no
transport-level request failed", not "we retrieved exactly N of N reported"
- see the COMPLETENESS_DEFINITION section of the phase doc.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _read(*parts: str) -> str:
    return (REPO_ROOT / Path(*parts)).read_text()


def _deed_harvester_src() -> str:
    return _read("scripts", "harvest_all_counties.ps1")


def _okaloosa_harvester_src() -> str:
    return _read("scripts", "harvest_okaloosa_bid4assets.ps1")


def _sync_src() -> str:
    return _read("scripts", "sync-harvest-to-supabase.ps1")


def _migration_006_src() -> str:
    return _read("scripts", "migrations", "006_add_closed_to_gone_since_status_list.sql")


def _closeout_section() -> str:
    """Everything from the closeout step's own header comment to the end of
    the file - isolates closeout-specific assertions from the (unrelated,
    unmodified-in-substance) upsert section above it."""
    src = _sync_src()
    marker = "# ---- Close out properties that fell off the Waiting feed ----"
    assert marker in src
    return src[src.index(marker):]


def _sanity_check_deeds_src() -> str:
    return _read("scripts", "sanity_check_deeds.ps1")


# ==================== Structural proof: the RealAuction harvester =========


def test_deed_harvester_checks_curl_exit_code_not_just_content():
    """The old harvester had zero transport-failure detection anywhere - a
    failed curl call and a genuinely empty response were indistinguishable.
    --fail plus an explicit $LASTEXITCODE check is what makes a real failure
    observable at all."""
    src = _deed_harvester_src()
    assert src.count("--fail") >= 3  # calendar fetch, preview fetch, paginated fetch
    assert src.count("if ($LASTEXITCODE -ne 0) {") == 3


def test_deed_harvester_marks_calendar_failure_incomplete_not_no_auction_days():
    """A failed calendar fetch must never fall through to the 'no auction
    days' (COMPLETE, empty) branch - that branch is reachable only when
    $countyOk is still true."""
    src = _deed_harvester_src()
    calendar_block = src[src.index("for ($mOffset = 0"):src.index("$dates = $dates | Select-Object -Unique")]
    assert 'calendar fetch failed for month offset' in calendar_block
    no_days_idx = src.index('if (-not $countyOk) {')
    empty_idx = src.index('if (-not $dates) {')
    assert no_days_idx < empty_idx, (
        "the failure check must be evaluated before the 'no auction days' "
        "check, or a failed calendar fetch could be misread as a confirmed-"
        "empty county"
    )


def test_deed_harvester_marks_confirmed_no_auction_days_complete():
    src = _deed_harvester_src()
    block = src[src.index('if (-not $dates) {'):src.index(':dateLoop foreach')]
    assert 'status   = "COMPLETE"' in block
    assert "confirmed no scheduled auctions" in block


def test_deed_harvester_marks_preview_fetch_failure_incomplete():
    src = _deed_harvester_src()
    assert 'preview/referer warm-up fetch failed for $date' in src
    assert "break dateLoop" in src


def test_deed_harvester_marks_paginated_fetch_failure_incomplete():
    src = _deed_harvester_src()
    assert 'paginated fetch failed for $date page $page' in src


def test_deed_harvester_every_failure_path_sets_county_not_ok():
    """Every one of the three transport failure sites must set $countyOk to
    $false - the single flag the end-of-county verdict below reads."""
    src = _deed_harvester_src()
    for marker in [
        'calendar fetch failed for month offset',
        'preview/referer warm-up fetch failed for $date',
        'paginated fetch failed for $date page $page',
    ]:
        idx = src.index(marker)
        preceding = src[max(0, idx - 200):idx]
        assert '$countyOk = $false' in preceding, f"{marker!r} does not set countyOk = $false nearby"


def test_deed_harvester_end_of_county_verdict_is_never_a_default():
    """The COMPLETE/INCOMPLETE verdict at the end of each county's loop
    reads $countyOk explicitly - it is not a bare 'always COMPLETE unless an
    exception was thrown' pattern."""
    src = _deed_harvester_src()
    verdict_block = src[src.index("if ($countyOk) {\n        $countyStatus += "):src.index("Always written, even when every county failed")]
    assert 'status   = "COMPLETE"' in verdict_block
    assert 'status   = "INCOMPLETE"' in verdict_block
    assert "$countyFailReason" in verdict_block


def test_deed_harvester_always_writes_status_file_unconditionally():
    """The status file write is not gated behind any row-count or
    early-exit condition - it always runs once the county loop finishes,
    matching harvest_lienhub_certificates.ps1's 'always written' discipline."""
    src = _deed_harvester_src()
    write_idx = src.index("$countyStatus | ConvertTo-Json -Depth 3 | Set-Content $outStatus")
    loop_end_idx = src.rindex("\n}\n", 0, write_idx)  # the county loop's closing brace
    assert loop_end_idx < write_idx
    json_write_idx = src.index('$all | ConvertTo-Json -Depth 4 | Set-Content $outJson')
    assert write_idx < json_write_idx, "status file must be written before/independent of harvest_all.json"


def test_deed_harvester_does_not_touch_dedup_or_row_shape():
    """Preserve the existing deed identity/dedup model - the phase's own
    constraint, since the audit found no evidence dedup was involved in the
    false-closure defect."""
    src = _deed_harvester_src()
    assert "$seenKeys.Add($key)" in src
    assert 'county      = $c.County' in src
    assert 'case        = $case' in src


# ==================== Structural proof: the Okaloosa (Bid4Assets) harvester


def test_okaloosa_checks_curl_exit_code_on_every_fetch():
    src = _okaloosa_harvester_src()
    assert src.count("--fail") >= 3  # listings page, per-date listings, per-property detail
    assert src.count("if ($LASTEXITCODE -ne 0) {") == 3


def test_okaloosa_fails_closed_on_listings_page_fetch_failure():
    src = _okaloosa_harvester_src()
    block = src[src.index("# ---- 1. discover"):src.index("# ---- 2. per date")]
    assert 'Write-OkaloosaStatus "INCOMPLETE" 0 "listings page fetch failed' in block


def test_okaloosa_marks_confirmed_no_dates_complete():
    src = _okaloosa_harvester_src()
    block = src[src.index("# ---- 1. discover"):src.index("# ---- 2. per date")]
    assert 'Write-OkaloosaStatus "COMPLETE" 0 "confirmed no upcoming sale dates' in block


def test_okaloosa_per_date_listing_failure_is_incomplete_not_silently_skipped():
    src = _okaloosa_harvester_src()
    block = src[src.index("# ---- 2. per date"):src.index("# ---- 3. per property")]
    assert 'Write-OkaloosaStatus "INCOMPLETE" 0 "listings page fetch failed for salesdate' in block


def test_okaloosa_detail_page_failure_is_tracked_not_silently_continued():
    """The pre-Phase-30B code was `if (-not $html) { continue }` - a failed
    detail-page fetch simply vanished with zero signal. It must now be
    counted."""
    src = _okaloosa_harvester_src()
    assert "$detailFailures++" in src
    # The pre-Phase-30B behavior (a bare, silent per-property skip with no
    # tracking) must not appear as an actual statement. Checked line-by-line
    # so this doesn't get confused by the explanatory comment above the new
    # code, which discusses that old behavior in prose.
    code_lines = [ln.strip() for ln in src.splitlines() if not ln.strip().startswith("#")]
    assert "if (-not $html) { continue }" not in code_lines


def test_okaloosa_partial_detail_retrieval_is_incomplete_even_with_nonzero_results():
    """'Partial data must never be interpreted as complete' - even when
    $results.Count -gt 0, any detail-page failure makes the county
    INCOMPLETE, not COMPLETE-with-fewer-rows."""
    src = _okaloosa_harvester_src()
    tail = src[src.index("# ---- 4. merge into"):]
    assert "if ($detailFailures -gt 0) {" in tail
    assert 'Write-OkaloosaStatus "INCOMPLETE" $results.Count' in tail


def test_okaloosa_writes_status_at_every_exit_point():
    """Every `exit` in the script must be preceded by a Write-OkaloosaStatus
    call, or a failure could exit before any record is left behind - same
    discipline as the certificate harvester's 'always written' guarantee,
    applied here across multiple early-exit points instead of one."""
    src = _okaloosa_harvester_src()
    # Matches call sites only (`Write-OkaloosaStatus <arg>`) - the function
    # definition itself is `function Write-OkaloosaStatus($status, ...)`
    # with no space before the paren, so it doesn't match this pattern.
    write_status_calls = src.count("Write-OkaloosaStatus ")
    # listings-fetch failure, confirmed-no-dates, per-date-fetch failure,
    # zero-results, and the two-way final success/partial branch = 6 call sites.
    assert write_status_calls == 6, f"expected exactly 6 Write-OkaloosaStatus call sites, found {write_status_calls}"


def test_okaloosa_status_write_replaces_not_duplicates_its_own_prior_entry():
    src = _okaloosa_harvester_src()
    func_block = src[src.index("function Write-OkaloosaStatus"):src.index("# ---- 1. discover")]
    assert "Where-Object { [string]$_.county -ne $county }" in func_block


# ==================== Structural proof: the sync/closeout step ============


def test_closeout_runs_after_the_upsert_section():
    src = _sync_src()
    upsert_idx = src.index("Done. $sent properties upserted to Supabase")
    closeout_idx = src.index("# ---- Close out properties that fell off the Waiting feed ----")
    assert upsert_idx < closeout_idx


def test_closeout_fails_closed_when_status_file_is_absent():
    section = _closeout_section()
    assert "$completeCounties = [System.Collections.Generic.HashSet[string]]::new()" in section
    assert "if (Test-Path $statusPath) {" in section
    assert "skipping stale-property closeout entirely this run (fail closed" in section


def test_closeout_fails_closed_when_status_file_is_unparseable():
    section = _closeout_section()
    assert "$completeCounties.Clear()" in section
    assert "could not be parsed - skipping stale-property closeout entirely this run (fail closed" in section


def test_closeout_only_considers_counties_explicitly_marked_complete():
    section = _closeout_section()
    assert 'if ($cs.status -eq "COMPLETE")' in section
    assert '$cs.status -eq "INCOMPLETE"' not in section


def test_closeout_query_is_scoped_to_state_source_status_and_complete_counties():
    """Hard isolation requirement, same shape as the certificate
    reconciliation query: never touch another state, another source, a
    still-upcoming sale date, or a county this run didn't confirm complete.
    The `state=eq.FL` clause is the Phase 30B cross-state fix - it was
    absent before this phase."""
    section = _closeout_section()
    assert "state=eq.FL&source=eq.auction&status=eq.active&sale_date=lte.$today&county=in.($encodedCounties)" in section


def test_closeout_rechecks_county_membership_defensively():
    section = _closeout_section()
    loop_start = section.index("foreach ($ar in $activeRows) {")
    loop_body = section[loop_start:section.index("if ($staleIds.Count -gt 0)")]
    assert "if (-not $completeCounties.Contains([string]$ar.county)) { continue }" in loop_body


def test_closeout_keys_on_case_no_scoped_per_county():
    section = _closeout_section()
    assert "$harvestedKeysByCounty[$r.county].Add([string]$r.case_no)" in section
    assert "$keysForCounty.Contains([string]$ar.case_no)" in section


def test_closeout_only_ever_patches_never_posts_or_deletes():
    section = _closeout_section()
    assert "-Method Patch" in section
    assert "-Method Post" not in section
    assert "-Method Delete" not in section


def test_closeout_patch_body_is_exactly_status_closed():
    section = _closeout_section()
    assert '\'{"status":"closed"}\'' in section


def test_closeout_patch_writes_no_other_field():
    """gone_since in particular must not be written from application code -
    it is trigger-managed (see migration 006 tests below)."""
    section = _closeout_section()
    patch_body_idx = section.index("Invoke-RestMethod -Uri $patchUrl -Method Patch")
    patch_body_line = section[patch_body_idx:section.index("\n", patch_body_idx)]
    assert 'status":"closed"' in patch_body_line
    assert "gone_since" not in patch_body_line
    assert "outcome" not in patch_body_line
    assert "sold_price" not in patch_body_line


def test_a_run_with_zero_complete_counties_closes_out_nothing():
    section = _closeout_section()
    assert "if ($completeCounties.Count -gt 0) {" in section
    assert "Zero COMPLETE counties this run - stale-property closeout skipped entirely" in section


def test_upsert_section_still_never_sends_status():
    """The upsert step must remain exactly as safe-merge as before this
    phase - status is only ever written by the separate closeout PATCH."""
    src = _sync_src()
    upsert_section = src[:src.index("# ---- Close out properties that fell off")]
    row_literal_start = upsert_section.index("$rows += [ordered]@{")
    row_literal = upsert_section[row_literal_start:upsert_section.index("}", row_literal_start)]
    assert "status" not in row_literal
    assert "gone_since" not in row_literal


def test_whole_run_threshold_check_is_untouched_and_not_a_substitute():
    """Part 2's explicit constraint: sanity_check_deeds.ps1's whole-run
    ≥15-counties-fresh check must remain exactly as it was - a separate,
    independent circuit breaker, never relied upon as the completeness
    gate. This just confirms Phase 30B did not modify that file at all."""
    src = _sanity_check_deeds_src()
    assert "$MinFreshCounties = 15" in src
    assert "SANITY CHECK FAILED" in src
    # The per-county gate lives entirely in sync-harvest-to-supabase.ps1 /
    # the harvesters' status files - this file has no knowledge of either.
    assert "harvest_all_status" not in src
    assert "COMPLETE" not in src
    assert "INCOMPLETE" not in src


# ==================== Behavioral proof: the closeout decision =============


def _close_out(existing_active, harvested_rows, county_status):
    """A literal, minimal port of sync-harvest-to-supabase.ps1's closeout
    decision - structurally identical to test_phase23's _reconcile(), since
    Phase 30B reused that proven decision shape for this step (see module
    docstring for why the *harvester's* completeness signal, unlike this
    decision, could not be copied verbatim).

    existing_active: list of {"id", "county", "case_no"} - already
                      state=FL, source=auction, status=active, sale_date
                      passed (all proven scoped in production by the
                      structural test above).
    harvested_rows:  list of {"county", "case_no"} - this run's upserted keys
    county_status:   dict county -> "COMPLETE" | "INCOMPLETE" (absent = unknown)
    """
    complete = {c for c, s in county_status.items() if s == "COMPLETE"}
    harvested_keys_by_county: dict[str, set[str]] = {}
    for r in harvested_rows:
        if r["county"] not in complete:
            continue
        harvested_keys_by_county.setdefault(r["county"], set()).add(r["case_no"])

    stale_ids = set()
    for row in existing_active:
        if row["county"] not in complete:
            continue
        keys = harvested_keys_by_county.get(row["county"], set())
        if row["case_no"] not in keys:
            stale_ids.add(row["id"])
    return stale_ids


def test_A_complete_county_still_listed_property_remains_active():
    existing = [{"id": 1, "county": "Duval", "case_no": "A1"}]
    harvested = [{"county": "Duval", "case_no": "A1"}]
    status = {"Duval": "COMPLETE"}
    assert _close_out(existing, harvested, status) == set()


def test_A_complete_county_no_longer_listed_property_closes_out():
    existing = [{"id": 1, "county": "Duval", "case_no": "A1"}]
    harvested: list[dict] = []  # Duval harvested nothing else this run, but was COMPLETE
    status = {"Duval": "COMPLETE"}
    assert _close_out(existing, harvested, status) == {1}


def test_B_complete_empty_county_closes_out_its_stale_rows():
    """A county whose calendar fetch positively confirmed zero scheduled
    auctions (COMPLETE, rowCount 0) is exactly as eligible for closeout as
    one that harvested real rows."""
    existing = [{"id": 1, "county": "Hamilton", "case_no": "A1"}]
    harvested: list[dict] = []
    status = {"Hamilton": "COMPLETE"}  # confirmed-empty county
    assert _close_out(existing, harvested, status) == {1}


def test_C_retrieval_failure_county_existing_rows_untouched():
    existing = [{"id": 1, "county": "Baker", "case_no": "A1"}]
    harvested: list[dict] = []
    status = {"Baker": "INCOMPLETE"}  # calendar fetch failed
    assert _close_out(existing, harvested, status) == set()


def test_D_partial_retrieval_county_existing_rows_untouched():
    """Pagination failed partway through - whatever the harvester already
    added to $all before the failure may still be upserted (see the deed
    harvester's own header comment / IMPLEMENTATION section for why this
    phase chose not to discard partial rows the way the certificate
    harvester does), but the county is still INCOMPLETE and none of its
    other existing active rows may be closed out."""
    existing = [{"id": 1, "county": "Orange", "case_no": "A1"}, {"id": 2, "county": "Orange", "case_no": "A2"}]
    harvested = [{"county": "Orange", "case_no": "A1"}]  # A1 was retrieved before the page-3 failure; A2 was not
    status = {"Orange": "INCOMPLETE"}
    assert _close_out(existing, harvested, status) == set(), (
        "an INCOMPLETE county must close out nothing, even though A2 looks "
        "identically 'missing from this run' to a genuinely-gone property"
    )


def test_E_one_failed_county_cannot_affect_another_successful_county():
    existing = [
        {"id": 1, "county": "Baker", "case_no": "A1"},    # Baker: failed
        {"id": 2, "county": "Duval", "case_no": "A2"},    # Duval: complete, still listed
        {"id": 3, "county": "Duval", "case_no": "A3"},    # Duval: complete, now gone
    ]
    harvested = [{"county": "Duval", "case_no": "A2"}]
    status = {"Baker": "INCOMPLETE", "Duval": "COMPLETE"}
    assert _close_out(existing, harvested, status) == {3}


def test_F_whole_run_threshold_trap_one_failed_county_still_protected():
    """The exact trap Part 5F names: far more than sanity_check_deeds.ps1's
    $MinFreshCounties=15 threshold succeed (20 here), while exactly one
    county fails - sanity_check_deeds.ps1 would PASS (20 >= 15) and the
    workflow would report green, but the failed county's existing rows must
    still be completely untouched. This is the fixture that proves the
    per-county gate is not merely redundant with, or overridden by, the
    whole-run check."""
    status = {}
    existing = []
    harvested = []
    for i in range(20):
        county = f"Success{i}"
        status[county] = "COMPLETE"
        existing.append({"id": i, "county": county, "case_no": "A1"})
        harvested.append({"county": county, "case_no": "A1"})  # still listed - not stale

    failed_county = "Baker"
    status[failed_county] = "INCOMPLETE"
    existing.append({"id": 999, "county": failed_county, "case_no": "A1"})
    # Baker contributed nothing this run - looks identical to "gone" without the gate.

    fresh_count = 20  # what sanity_check_deeds.ps1's independent whole-run check would see
    assert fresh_count >= 15, "this fixture only proves the point if the whole-run check would have passed"

    stale = _close_out(existing, harvested, status)
    assert 999 not in stale, "Baker's existing row must remain untouched despite the whole-run check passing"
    assert stale == set(), "none of the 20 successful counties' still-listed rows should close out either"


def test_naive_global_query_would_have_failed_the_threshold_trap():
    """Directly demonstrates what the pre-Phase-30B bug looked like: a
    global 'missing from this run' query with no completeness gate at all
    would have closed out Baker's row specifically because it's
    successfully indistinguishable from a real closure."""
    existing_active = [{"id": 1, "county": "Duval", "case_no": "A2"}, {"id": 999, "county": "Baker", "case_no": "A1"}]
    harvested_rows = [{"county": "Duval", "case_no": "A2"}]  # Baker contributed nothing (failed)

    def _naive_global_closeout(existing_active, harvested_rows):
        harvested_keys = {(r["county"], r["case_no"]) for r in harvested_rows}
        return {row["id"] for row in existing_active if (row["county"], row["case_no"]) not in harvested_keys}

    naive_result = _naive_global_closeout(existing_active, harvested_rows)
    assert 999 in naive_result, "the naive approach would have closed out Baker's row"

    gated_result = _close_out(existing_active, harvested_rows, {"Duval": "COMPLETE", "Baker": "INCOMPLETE"})
    assert 999 not in gated_result


def test_state_scoping_is_enforced_at_the_query_layer_not_the_python_layer():
    """Modeled the same way test_phase23's test_10 models FL/TX county-name
    collisions: the Python decision layer only ever operates on rows it's
    given, so state isolation depends on the real query's `state=eq.FL`
    clause (proven present verbatim above), not on anything in _close_out()
    itself."""
    existing = [{"id": 1, "county": "Orange", "case_no": "TX-1"}]  # hypothetically a TX row, if it ever reached here
    harvested: list[dict] = []
    status = {"Orange": "COMPLETE"}
    # Without state scoping this would go stale - the real query's state=eq.FL
    # clause is what actually prevents a TX row from ever being fetched into
    # existing_active in production (test_closeout_query_is_scoped_to_state...).
    assert _close_out(existing, harvested, status) == {1}
    section = _closeout_section()
    assert "state=eq.FL" in section


# ==================== `closed` / gone_since migration (Part 4 / Part 5G) ==


def test_migration_006_adds_closed_to_both_trigger_functions():
    sql = _migration_006_src()
    assert "create or replace function public.track_gone_since()" in sql
    assert "create or replace function public.track_gone_since_insert()" in sql
    # 2 occurrences in track_gone_since() (gone_now + gone_was) + 1 in
    # track_gone_since_insert() = 3.
    assert sql.count("'dropped','sold','notfound','closed'") == 3


def test_migration_006_keeps_sold_even_though_unused():
    """No correctness reason to remove it - this phase adds 'closed', it
    doesn't redesign the set."""
    sql = _migration_006_src()
    assert "'sold'" in sql


def test_migration_006_does_not_redesign_or_recreate_the_trigger():
    """'Do not redesign the trigger' - only the function bodies change via
    CREATE OR REPLACE; no DROP TRIGGER / CREATE TRIGGER statement appears,
    so the trigger's own name, timing, and firing conditions are untouched."""
    sql = _migration_006_src().lower()
    assert "drop trigger" not in sql
    assert "create trigger" not in sql
    assert "create or replace function" in sql


def test_migration_006_preserves_the_update_functions_three_way_branch():
    sql = _migration_006_src()
    assert "if gone_now and not gone_was then" in sql
    assert "elsif not gone_now then" in sql
    assert "new.gone_since := old.gone_since;" in sql


def test_migration_006_documents_the_hand_applied_trigger_origin():
    """Part 4: 'If production schema history reveals that this trigger is
    currently hand-applied rather than migration-managed, document that
    fact.' Confirmed this phase: schema-v2-gone-tracking.sql does not exist
    anywhere in this repository's tracked history."""
    sql = _migration_006_src()
    assert "schema-v2-gone-tracking.sql" in sql
    assert "does not exist anywhere in this repository" in sql


def test_gone_since_status_source_files_confirm_no_schema_v1_v2_v3_tracked():
    """Guards the claim the migration's own comment makes - fails loudly if
    someone later adds these files without updating the comment (or if the
    comment's claim was ever wrong)."""
    for name in ("schema.sql", "schema-v1.sql", "schema-v2-gone-tracking.sql", "schema-v3-calendar.sql"):
        assert not (REPO_ROOT / name).exists(), f"{name} now exists - migration 006's provenance comment is stale"


def test_no_application_code_writes_gone_since_directly():
    """'Do not manually write gone_since from application code' - scan
    every deed-pipeline script this phase touched (plus the certificate
    sync, for the same regression test_phase23 already covers from its own
    side) for a PATCH/POST body literal containing gone_since."""
    for parts in (
        ("scripts", "harvest_all_counties.ps1"),
        ("scripts", "harvest_okaloosa_bid4assets.ps1"),
        ("scripts", "sync-harvest-to-supabase.ps1"),
    ):
        text = _read(*parts)
        assert "gone_since" not in text, f"{'/'.join(parts)} references gone_since - it must stay trigger-managed only"


# ==================== Part 6: regression / repo audit checks ==============


DEED_PHASE_FILES = (
    ("scripts", "harvest_all_counties.ps1"),
    ("scripts", "harvest_okaloosa_bid4assets.ps1"),
    ("scripts", "sync-harvest-to-supabase.ps1"),
)


def test_part6_no_new_writer_for_outcome():
    for parts in DEED_PHASE_FILES:
        text = _read(*parts)
        assert '"outcome"' not in text and "'outcome'" not in text


def test_part6_no_new_writer_for_sold_price():
    for parts in DEED_PHASE_FILES:
        text = _read(*parts)
        assert '"sold_price"' not in text and "'sold_price'" not in text


def test_part6_certificate_reconciliation_files_untouched_in_substance():
    """This phase must not weaken or alter certificate reconciliation
    behavior - confirms the exact PATCH body certificate reconciliation
    uses is still status-only notfound, unchanged from Phase 27."""
    cert_sync = _read("scripts", "sync-certificates-to-supabase.ps1")
    assert '\'{"status":"notfound"}\'' in cert_sync
    assert "state=eq.FL&source=eq.certificate&status=eq.active&county=in.($encodedCounties)" in cert_sync


def test_part6_no_workflow_schedule_change():
    """Phase 30B is implementation-only per its own instructions - the
    harvest-and-sync.yml cron schedule and job trigger conditions must be
    byte-identical to before this phase."""
    workflow = _read(".github", "workflows", "harvest-and-sync.yml")
    assert "0 10,22 * * *" not in workflow  # this schedule string was never in this file to begin with; see next line
    assert "'0 10 * * *'" in workflow
    assert "'0 22 * * *'" in workflow
    assert "'0 12 * * *'" in workflow


def test_part6_deed_job_step_order_unchanged():
    workflow = _read(".github", "workflows", "harvest-and-sync.yml")
    deeds_start = workflow.index("  deeds:")
    deeds_end = workflow.index("  certificates:")
    deeds_job = workflow[deeds_start:deeds_end]
    harvest_idx = deeds_job.index("harvest_all_counties.ps1")
    okaloosa_idx = deeds_job.index("harvest_okaloosa_bid4assets.ps1")
    sync_idx = deeds_job.index("sync-harvest-to-supabase.ps1")
    sanity_idx = deeds_job.index("sanity_check_deeds.ps1")
    assert harvest_idx < okaloosa_idx < sync_idx < sanity_idx
