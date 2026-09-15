"""Phase 23B (Safe Certificate Status Reconciliation) tests, updated by
Phase 27 (claude/phase-27-certificate-reconciliation-schema-truth-redesign.md)
to match the *verified production schema*.

Implements the Phase 23A design (claude/phase-23a-certificate-reconciliation-
design.md) as corrected by Phase 27: an existing `active` Florida LienHub
certificate that is absent from a demonstrably COMPLETE county harvest is
reconciled to `status='notfound'` - never for a county the harvester could
not positively confirm it fully retrieved.

Phase 27 removed `outcome` from the reconciliation PATCH. Phase 26's live
forensic audit (claude/phase-26-production-schema-forensic-audit.md)
confirmed production `properties` has no `outcome` column and no
`sold_price` column - Phase 23B's original PATCH body
(`{"status":"notfound","outcome":"no longer listed"}`) was rejected
atomically in production with `PGRST204: Could not find the 'outcome'
column of 'properties' in the schema cache`, and no false closures occurred
because PostgREST validates the whole batch before writing anything. Phase
14D (docs/phase-14d-migration-reconciliation.md) had already independently
established that `outcome`/`sold_price` were deliberately deferred, not
merely unimplemented, and built the sibling regression test
`test_outcome_and_sold_price_have_no_writer_anywhere_in_the_repo` (in
tests/python/test_phase14d_migration_reconciliation.py) that this file's
fix must make pass again without weakening it. The status-only transition
is not a loss of information: `gone_since` is a verified, trigger-managed
production column (`properties_gone_since` -> `track_gone_since()`, no
`source` filter) that stamps itself the moment `status` enters
`('dropped','sold','notfound')`, so certificate rows get the same gone-
tracking as every other source without this script writing it.

## Why this file mixes two kinds of test

`harvest_lienhub_certificates.ps1` and `sync-certificates-to-supabase.ps1`
are PowerShell, and this sandbox has no `pwsh` available to execute them
directly (confirmed this phase: `which pwsh` finds nothing, and installing
it is blocked by the environment's egress policy - see the Phase 23B final
report). Two independent layers of evidence are used instead, matching the
discipline of every prior *-through-14-style test file in this repo (real
repository text, not a reimplemented model, wherever the text alone can
prove the property):

1. **Structural/text assertions** against the actual `.ps1` file contents -
   proving the specific guards, ordering, and query/patch shapes this
   phase's hard safety requirement demands are actually present in the code
   that will run in production, not merely described in a design doc.
2. **`_reconcile()`** - a small, deliberately literal Python port of *only*
   the case_no-membership decision (the one piece that actually carries
   false-closure risk; the state/source/status/county scoping is instead
   proven present verbatim in the real query string via (1) above). Tests
   against this port exercise the exact false-closure scenarios the phase
   asks for exhaustively, including the explicit two-county fixture Section
   7 of the implementation prompt describes by name.

Neither layer alone would be sufficient - (1) can't prove the decision
logic is right, (2) can't prove the real script actually contains what (1)
asserts it does. Together they cover the full
"county request -> complete source retrieval -> complete parsing/pagination
-> COMPLETE marker -> upsert -> scoped reconciliation" chain the
implementation prompt asks to see proven, not merely claimed.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _read(*parts: str) -> str:
    return (REPO_ROOT / Path(*parts)).read_text()


def _harvester_src() -> str:
    return _read("scripts", "harvest_lienhub_certificates.ps1")


def _sync_src() -> str:
    return _read("scripts", "sync-certificates-to-supabase.ps1")


def _sync_reconciliation_section() -> str:
    """Everything from the reconciliation step's own header comment to the
    end of the file - isolates reconciliation-specific assertions from the
    (unrelated, unmodified-in-substance) upsert section above it."""
    src = _sync_src()
    marker = "# ---- Reconcile certificates absent from a COMPLETE county's harvest ----"
    assert marker in src
    return src[src.index(marker):]


# ==================== Structural proof: the harvester ====================


def test_harvester_never_defaults_a_missing_recordstotal_to_zero():
    """The completeness signal must be POSITIVE. A DataTables response
    missing `recordsTotal` must be treated as malformed/failed, never
    silently coerced to 0 (which would make it indistinguishable from a
    confirmed-empty county)."""
    src = _harvester_src()
    assert 'if ($null -eq $postResp.recordsTotal) {' in src
    assert 'throw "malformed DataTables response - missing recordsTotal' in src


def test_harvester_detects_a_pagination_stall_before_the_reported_total():
    """A page returning 0 rows before the server's own reported total is
    reached is a partial/stalled pagination failure, not a legitimately
    short result - this is the check that distinguishes the two, which the
    original (pre-Phase-23) loop exit condition alone could not do."""
    src = _harvester_src()
    assert "if ($collected.Count -lt $recordsTotal) {" in src
    assert 'throw "pagination incomplete - collected' in src


def test_harvester_marks_confirmed_empty_county_complete_not_incomplete():
    """A county whose server-reported total is genuinely 0 is a *positive*
    confirmation, not an absence of information - it must be COMPLETE."""
    src = _harvester_src()
    empty_block = src[src.index("if ($collected.Count -eq 0) {"):]
    empty_block = empty_block[:empty_block.index("foreach ($d in $collected)")]
    assert 'status   = "COMPLETE"' in empty_block
    assert "confirmed empty" in empty_block


def test_harvester_marks_every_failure_path_incomplete():
    """Every distinct failure path this phase enumerates (missing CSRF
    token, and the general catch that GET-retry-exhaustion / malformed
    response / pagination-stall / any other exception all fall into) must
    record INCOMPLETE, never silently produce no record at all."""
    src = _harvester_src()
    # csrf-missing path
    csrf_block = src[src.index("if (-not $csrf) {"):]
    csrf_block = csrf_block[:csrf_block.index("$start = 0")]
    assert 'status   = "INCOMPLETE"' in csrf_block

    # outer catch (GET-retry exhaustion, malformed response, pagination
    # stall, and any other unhandled exception all propagate here)
    catch_block = src[src.rindex("} catch {"):]
    assert 'status   = "INCOMPLETE"' in catch_block
    assert '"$($_.Exception.Message)"' in catch_block


def test_harvester_always_writes_the_status_file_even_when_nothing_harvested():
    """The completeness file must be written unconditionally - including
    when every county failed, or every county was confirmed complete-and-
    empty (so $all.Count is 0 either way). If the early 'nothing harvested'
    exit ran BEFORE the status file was written, a fully-failed run would
    leave no status file at all, and the sync step's fail-closed default
    (no file = no county reconciled) would happen to still be safe - but
    only by accident, and a fully-successful-but-empty run would incorrectly
    look identical to a fully-failed one without this file. Ordering is
    asserted directly rather than assumed."""
    src = _harvester_src()
    write_idx = src.index("$countyStatus | ConvertTo-Json -Depth 3 | Set-Content $outStatus")
    early_exit_idx = src.index('if ($all.Count -eq 0) { Write-Host "No certificate rows harvested this run')
    assert write_idx < early_exit_idx, (
        "the status file must be written before the early exit for an empty "
        "harvest, or a fully-failed/fully-empty run would never produce one"
    )


def test_harvester_never_uses_certificate_number_as_the_row_identity():
    """case_no must come from account_number, not certificate_number - the
    identity the sync's upsert and this phase's reconciliation both key
    on."""
    src = _harvester_src()
    assert "case_no         = $d.account_number" in src
    assert "certificate_no  = [string]$d.certificate_number" in src


# ==================== Structural proof: the sync/reconciliation step =====


def test_reconciliation_runs_after_the_upsert_section():
    """Implementation prompt requirement: 'perform scoped reconciliation
    after successful upsert'."""
    src = _sync_src()
    upsert_idx = src.index("Done. $sent certificates upserted to Supabase.")
    reconcile_idx = src.index("# ---- Reconcile certificates absent from a COMPLETE county's harvest ----")
    assert upsert_idx < reconcile_idx


def test_reconciliation_fails_closed_when_status_file_is_absent():
    section = _sync_reconciliation_section()
    assert "$completeCounties = [System.Collections.Generic.HashSet[string]]::new()" in section
    assert "if (Test-Path $statusPath) {" in section
    assert "skipping reconciliation entirely this run (fail closed" in section


def test_reconciliation_fails_closed_when_status_file_is_unparseable():
    section = _sync_reconciliation_section()
    assert "$completeCounties.Clear()" in section
    assert "could not be parsed - skipping reconciliation entirely this run (fail closed" in section


def test_reconciliation_only_considers_counties_explicitly_marked_complete():
    section = _sync_reconciliation_section()
    assert 'if ($cs.status -eq "COMPLETE")' in section
    # No other status string is ever treated as eligible.
    assert '$cs.status -eq "INCOMPLETE"' not in section


def test_reconciliation_query_is_scoped_to_state_source_status_and_complete_counties():
    """Hard isolation requirement: never touch another state, another
    source, or a county this run didn't confirm complete."""
    section = _sync_reconciliation_section()
    assert "state=eq.FL&source=eq.certificate&status=eq.active&county=in.($encodedCounties)" in section


def test_reconciliation_rechecks_county_membership_defensively():
    """Belt-and-suspenders: even though the query already filters by
    county, the per-row loop re-checks membership before ever adding a row
    to the stale set."""
    section = _sync_reconciliation_section()
    loop_start = section.index("foreach ($ar in $activeRows) {")
    loop_body = section[loop_start:section.index("if ($staleIds.Count -gt 0)")]
    assert "if (-not $completeCounties.Contains([string]$ar.county)) { continue }" in loop_body


def test_reconciliation_keys_on_case_no_not_certificate_no():
    section = _sync_reconciliation_section()
    assert "$harvestedKeysByCounty[$r.county].Add([string]$r.case_no)" in section
    assert "$keysForCounty.Contains([string]$ar.case_no)" in section
    assert "certificate_no" not in section


def test_reconciliation_only_ever_patches_never_posts_or_deletes():
    """Reconciliation must never create new rows or delete rows - only
    PATCH the status of rows already known to exist."""
    section = _sync_reconciliation_section()
    assert "-Method Patch" in section
    assert "-Method Post" not in section
    assert "-Method Delete" not in section


def test_reconciliation_patch_body_is_exactly_status_notfound():
    """Phase 27: the PATCH body must be exactly `{"status":"notfound"}` -
    only a column verified to exist in production (Phase 26's live audit)
    is ever written."""
    section = _sync_reconciliation_section()
    assert '\'{"status":"notfound"}\'' in section


def test_reconciliation_patch_does_not_contain_outcome():
    """Phase 27 Part 4 item 2: production `properties` has no `outcome`
    column (Phase 26 forensic audit) - the PATCH body itself must never
    reference it, or PostgREST rejects the whole batch with PGRST204
    (the exact Phase 25 production failure this phase exists to fix)."""
    section = _sync_reconciliation_section()
    patch_body_idx = section.index("$patchBody = [System.Text.Encoding]::UTF8.GetBytes(")
    patch_body_line = section[patch_body_idx:section.index("\n", patch_body_idx)]
    assert "outcome" not in patch_body_line


def test_reconciliation_patch_does_not_contain_sold_price():
    """Phase 27 Part 4 item 3: production `properties` has no `sold_price`
    column either (Phase 26 forensic audit) - same reasoning as the
    `outcome` check above, and Phase 14D established both fields were
    deliberately deferred together."""
    section = _sync_reconciliation_section()
    patch_body_idx = section.index("$patchBody = [System.Text.Encoding]::UTF8.GetBytes(")
    patch_body_line = section[patch_body_idx:section.index("\n", patch_body_idx)]
    assert "sold_price" not in patch_body_line


def test_reconciliation_patch_writes_no_other_field():
    """The PATCH body must carry only `status` - every other column
    (owner_name, assessed, interest_rate, hand research, `gone_since`,
    etc.) must be left completely untouched, matching the upsert's own
    safe-merge discipline. `gone_since` in particular must NOT be written
    here - it is trigger-managed in production (verified live in Phase 27
    Part 1: `properties_gone_since` -> `track_gone_since()`, no `source`
    filter) and would be redundant/risky to also set from application
    code."""
    section = _sync_reconciliation_section()
    json_literal = '{"status":"notfound"}'
    assert json_literal in section
    assert json_literal.count(":") == 1  # exactly {"status": ...}, nothing else
    # The PATCH body itself (not the surrounding explanatory comments, which
    # correctly document *why* gone_since isn't written here) must not
    # reference gone_since.
    patch_body_idx = section.index("$patchBody = [System.Text.Encoding]::UTF8.GetBytes(")
    patch_body_line = section[patch_body_idx:section.index("\n", patch_body_idx)]
    assert "gone_since" not in patch_body_line


def test_a_run_with_zero_complete_counties_reconciles_nothing():
    """'If the entire harvest fails, reconciliation must not run against
    any county.'"""
    section = _sync_reconciliation_section()
    assert "if ($completeCounties.Count -gt 0) {" in section
    assert "Zero COMPLETE counties this run - reconciliation skipped entirely" in section


def test_upsert_still_never_sends_status_or_outcome():
    """The upsert step must remain exactly as safe-merge as before this
    phase - status/outcome are only ever written by the separate
    reconciliation PATCH, never by the upsert."""
    src = _sync_src()
    upsert_section = src[:src.index("# ---- Reconcile certificates absent")]
    row_literal_start = upsert_section.index("$rows += [ordered]@{")
    row_literal = upsert_section[row_literal_start:upsert_section.index("}", row_literal_start)]
    assert "status" not in row_literal
    assert "outcome" not in row_literal


def test_a_data_quality_failure_still_hard_fails_before_reconciliation():
    """A harvest that produced rows but where every single one was missing
    case_no is a real data problem (distinct from a legitimately empty/
    absent harvest) and must still throw, same as before this phase."""
    src = _sync_src()
    assert 'throw "Every harvested row was missing case_no - nothing to sync."' in src


# ==================== Behavioral proof: the reconciliation decision ======


def _reconcile(existing_active, harvested_rows, county_status):
    """A literal, minimal port of the one piece of sync-certificates-to-
    supabase.ps1's reconciliation step that actually carries false-closure
    risk: which existing active (id, county, case_no) rows are absent from
    their own COMPLETE county's harvested key set. The state/source/status/
    county scoping this depends on in production is instead proven present
    verbatim in the real query string by the structural tests above - this
    function intentionally does not re-implement that part, to avoid
    silently drifting from what the actual query does.

    existing_active: list of {"id", "county", "case_no"}
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


def test_1_active_certificate_still_harvested_remains_active():
    existing = [{"id": 1, "county": "Duval", "case_no": "A1"}]
    harvested = [{"county": "Duval", "case_no": "A1"}]
    status = {"Duval": "COMPLETE"}
    assert _reconcile(existing, harvested, status) == set()


def test_2_active_certificate_absent_from_complete_county_becomes_stale():
    existing = [{"id": 1, "county": "Duval", "case_no": "A1"}]
    harvested = []  # Duval harvested nothing this run, but was COMPLETE
    status = {"Duval": "COMPLETE"}
    assert _reconcile(existing, harvested, status) == {1}


def test_3_absent_certificate_transitions_to_status_notfound_only():
    """The PATCH body producing this transition is proven verbatim in
    test_reconciliation_patch_body_is_exactly_status_notfound; this test
    anchors that the same identity that goes stale under _reconcile()
    (test_2, above) is exactly what the production PATCH body (asserted
    here) is applied to - `status` is the only field this PATCH ever sets.
    `gone_since` still gets tracked (verified live in Phase 27 Part 1 as a
    database trigger keyed off the `status` transition itself), it's just
    never written by this script."""
    existing = [{"id": 1, "county": "Duval", "case_no": "A1"}]
    stale = _reconcile(existing, [], {"Duval": "COMPLETE"})
    assert stale == {1}
    section = _sync_reconciliation_section()
    assert '{"status":"notfound"}' in section


def test_4_failed_county_active_certificate_remains_active():
    existing = [{"id": 1, "county": "Baker", "case_no": "A1"}]
    harvested = []
    status = {"Baker": "INCOMPLETE"}
    assert _reconcile(existing, harvested, status) == set()


def test_5_403_waf_county_active_certificate_remains_active():
    existing = [{"id": 1, "county": "Nassau", "case_no": "A1"}]
    harvested = []
    status = {"Nassau": "INCOMPLETE"}  # recorded via the outer catch, WAF/403 message
    assert _reconcile(existing, harvested, status) == set()


def test_6_timeout_county_active_certificate_remains_active():
    existing = [{"id": 1, "county": "Lee", "case_no": "A1"}]
    harvested = []
    status = {"Lee": "INCOMPLETE"}  # recorded via the outer catch, timeout message
    assert _reconcile(existing, harvested, status) == set()


def test_7_parser_pagination_failure_county_active_certificate_remains_active():
    existing = [{"id": 1, "county": "Orange", "case_no": "A1"}]
    # Orange's harvest stalled mid-pagination; whatever partial rows the
    # harvester saw before throwing are never upserted (the real script
    # discards $collected entirely on that throw - see
    # test_harvester_detects_a_pagination_stall_before_the_reported_total),
    # so harvested_rows correctly contains nothing for Orange either way.
    harvested = []
    status = {"Orange": "INCOMPLETE"}
    assert _reconcile(existing, harvested, status) == set()


def test_8_successful_zero_result_county_reconciled_only_when_explicitly_complete():
    existing = [{"id": 1, "county": "Pinellas", "case_no": "A1"}]
    harvested = []
    # Not marked at all (e.g. an older/unaware harvester, or the key
    # missing from the status file for any reason) must NOT be treated as
    # complete-and-empty by default.
    assert _reconcile(existing, harvested, {}) == set()
    # Only explicit COMPLETE reconciles it.
    assert _reconcile(existing, harvested, {"Pinellas": "COMPLETE"}) == {1}


def test_9_one_failed_county_cannot_affect_another_successful_county():
    existing = [
        {"id": 1, "county": "Baker", "case_no": "A1"},   # Baker: failed
        {"id": 2, "county": "Duval", "case_no": "A2"},   # Duval: complete, still listed
        {"id": 3, "county": "Duval", "case_no": "A3"},   # Duval: complete, now gone
    ]
    harvested = [{"county": "Duval", "case_no": "A2"}]
    status = {"Baker": "INCOMPLETE", "Duval": "COMPLETE"}
    assert _reconcile(existing, harvested, status) == {3}


def test_10_another_state_is_untouched():
    """Modeled at the query-scoping layer (state=eq.FL is proven present
    verbatim in production above); here, confirming the Python decision
    layer only ever operates on rows it was given, so a caller that (per
    the real query) never fetches a non-FL row can never have one reconciled
    by accident."""
    existing = [{"id": 1, "county": "Orange", "case_no": "A1"}]  # TX Orange, hypothetically
    harvested = []
    status = {"Orange": "COMPLETE"}
    # Without state scoping this would go stale - the real query prevents a
    # non-FL row from ever reaching this function at all (see
    # test_reconciliation_query_is_scoped_to_state_source_status_and_complete_counties).
    assert _reconcile(existing, harvested, status) == {1}
    section = _sync_reconciliation_section()
    assert "state=eq.FL" in section


def test_11_another_source_is_untouched():
    """Same shape as test_10 - source=eq.certificate is what actually keeps
    auction/laft rows out of $activeRows in production; confirmed verbatim
    above (test_reconciliation_query_is_scoped_to_state_source_status_and_complete_counties)."""
    section = _sync_reconciliation_section()
    assert "source=eq.certificate" in section
    assert "source=eq.auction" not in section
    assert "source=eq.laft" not in section


def test_12_another_ledger_type_is_untouched_status_scoping():
    """status=eq.active is what keeps this query from ever returning a row
    that's already dropped/sold/notfound/closed."""
    section = _sync_reconciliation_section()
    assert "status=eq.active" in section


def test_13_existing_notfound_rows_remain_unchanged():
    """A row already status='notfound' would never be returned by the
    status=eq.active query in the first place, so it can never appear in
    existing_active and can never be reconciled a second time."""
    existing_active_only = [{"id": 1, "county": "Duval", "case_no": "A1"}]
    # A hypothetical already-notfound row simply never enters this input -
    # that's the point being tested: the production query's status=eq.active
    # filter (test_12) is what guarantees this, not any logic inside the
    # reconciliation decision itself.
    harvested = []
    status = {"Duval": "COMPLETE"}
    result = _reconcile(existing_active_only, harvested, status)
    assert result == {1}
    assert 2 not in result


def test_14_new_certificates_remain_active():
    """A certificate freshly inserted this run was never 'existing active'
    before this run - it's simply not part of the existing_active input at
    all, so it can never be reconciled."""
    existing_active_before_this_run: list[dict] = []
    harvested = [{"county": "Duval", "case_no": "NEW1"}]
    status = {"Duval": "COMPLETE"}
    assert _reconcile(existing_active_before_this_run, harvested, status) == set()


def test_15_rerunning_the_same_complete_harvest_is_idempotent():
    existing = [{"id": 1, "county": "Duval", "case_no": "A1"}, {"id": 2, "county": "Duval", "case_no": "A2"}]
    harvested = [{"county": "Duval", "case_no": "A1"}]  # A2 goes stale
    status = {"Duval": "COMPLETE"}
    first = _reconcile(existing, harvested, status)
    assert first == {2}
    # Second run: id 2 is no longer status=active (it was just flipped to
    # notfound), so the query that builds existing_active for a real re-run
    # would no longer return it - modeled here by removing it before the
    # second call.
    existing_after_first_run = [row for row in existing if row["id"] not in first]
    second = _reconcile(existing_after_first_run, harvested, status)
    assert second == set()


# ==================== Section 7: the explicit false-closure fixture ======


def test_false_closure_regression_county_a_complete_partial_vs_county_b_incomplete():
    """The exact fixture the implementation prompt asks for by name, to
    make it impossible to accidentally replace the completeness gate with a
    global 'missing from this run' query in the future:

    County A: 10 existing active certificates, harvest returns 8 (2 truly
    redeemed/delisted), County A marked COMPLETE -> the 2 missing ones
    become notfound.

    County B: 10 existing active certificates, harvest hits a WAF/403 after
    partial retrieval, County B marked INCOMPLETE -> none of County B's
    existing active certificates change, even though all 10 are equally
    "missing from this run's output" as County A's 2 are.
    """
    county_a_existing = [{"id": i, "county": "A", "case_no": f"A{i}"} for i in range(1, 11)]
    county_a_harvested = [{"county": "A", "case_no": f"A{i}"} for i in range(1, 9)]  # 8 of 10

    county_b_existing = [{"id": 100 + i, "county": "B", "case_no": f"B{i}"} for i in range(1, 11)]
    county_b_harvested: list[dict] = []  # WAF/403 after partial retrieval - nothing usable upserted

    existing_active = county_a_existing + county_b_existing
    harvested_rows = county_a_harvested + county_b_harvested
    county_status = {"A": "COMPLETE", "B": "INCOMPLETE"}

    stale = _reconcile(existing_active, harvested_rows, county_status)

    # County A: exactly the 2 missing certificates (ids 9, 10) go stale.
    assert stale == {9, 10}, (
        "a global 'missing from this run' query (no completeness gate) "
        "would have produced {9, 10} PLUS all ten of County B's ids "
        "(101-110) here - this fixture exists specifically to catch that "
        "regression"
    )
    # County B: none of its 10 existing active certificates are touched,
    # despite being 100% absent from this run's harvested output - this is
    # the entire point of the completeness gate.
    county_b_ids = {row["id"] for row in county_b_existing}
    assert stale.isdisjoint(county_b_ids)


def test_false_closure_regression_a_naive_global_query_would_have_failed_this():
    """Directly demonstrates what the bug this suite guards against would
    have looked like, so the protection above isn't just asserting its own
    correct behavior in isolation."""
    county_a_existing = [{"id": i, "county": "A", "case_no": f"A{i}"} for i in range(1, 11)]
    county_a_harvested = [{"county": "A", "case_no": f"A{i}"} for i in range(1, 9)]
    county_b_existing = [{"id": 100 + i, "county": "B", "case_no": f"B{i}"} for i in range(1, 11)]

    existing_active = county_a_existing + county_b_existing
    harvested_rows = county_a_harvested  # County B contributed nothing (WAF/403)

    def _naive_global_reconcile(existing_active, harvested_rows):
        harvested_keys = {(r["county"], r["case_no"]) for r in harvested_rows}
        return {row["id"] for row in existing_active if (row["county"], row["case_no"]) not in harvested_keys}

    naive_result = _naive_global_reconcile(existing_active, harvested_rows)
    county_b_ids = {row["id"] for row in county_b_existing}
    # The naive, completeness-blind approach WOULD have false-closed all of
    # County B - proving the gate in _reconcile() (and in production) is
    # doing real work, not a no-op.
    assert county_b_ids.issubset(naive_result)

    gated_result = _reconcile(existing_active, harvested_rows, {"A": "COMPLETE", "B": "INCOMPLETE"})
    assert gated_result.isdisjoint(county_b_ids)
