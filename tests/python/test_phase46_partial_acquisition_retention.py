"""Phase 46. The defect: a transport failure on page N discarded every
record already retrieved from pages 1..N-1.

Live evidence, run 35109232214 (commit 5161e63, mode sample, limit 501):

    pages_retrieved:  1        <- a page WAS retrieved, in 6.194s
    records_seen:     0        <- yet nothing was seen
    is_balanced:      true     <- and the accounting called that consistent
    errors: ["SOURCE_UNAVAILABLE: ...?area=TX&limit=500&offset=500: timed out"]

The `offset=500` in that URL is the proof that page 1 answered with a usable
`next` cursor: the adapter's first URL carries no offset, and the only way
one appears is `next_url(payload)` reading page 1's `next` link. So page 1
succeeded and its records vanished.

Mechanism: `JsonApiAdapter._acquire()` accumulated into local variables, the
page-2 `TransportError` escaped the loop, and `SourceAdapter.acquire()`'s
`except TransportError` built a result from scratch - with no access to
those locals, and therefore no records.

These tests exercise the real acquisition path through a fixture transport.
None of them string-match source code; each drives `LgbsAdapter.acquire()`
and asserts on the returned result and on `AcquisitionRun.finalize()`.

The invariant under test:

    NO SUCCESSFULLY RETRIEVED RECORD MAY DISAPPEAR FROM THE RESULT
    BECAUSE A LATER PAGE FAILED.

and its necessary companion - retaining those records must NOT make a
failed walk look finished.
"""

from __future__ import annotations

import pytest

from harvesters.acquisition import (
    ACQUISITION_FAILURE_STATUSES,
    ACQUISITION_PRODUCED_RECORDS,
    AcquisitionStatus,
    FixtureTransport,
)
from harvesters.acquisition.adapters import LgbsAdapter
from harvesters.acquisition.adapters.json_api import LGBS_CONFIG
from harvesters.acquisition.run import AcquisitionRun, RejectionReason, RunStatus
from harvesters.acquisition.transport import SchemaError, SourceUnavailable

PAGE1 = f"{LGBS_CONFIG.base_url}?area=TX&limit={LGBS_CONFIG.page_size}"
PAGE2 = f"{LGBS_CONFIG.base_url}?area=TX&limit={LGBS_CONFIG.page_size}&offset=500"
PAGE3 = f"{LGBS_CONFIG.base_url}?area=TX&limit={LGBS_CONFIG.page_size}&offset=1000"


def row(**overrides) -> dict:
    base = {
        "uid": "u1", "sale_id": 101, "state": "TX", "county": "HARRIS COUNTY",
        "status": "Scheduled for Auction", "sale_type": "SALE",
        "account_nbr": "A1", "cause_nbr": "C1",
        "sale_date": "2026-10-06T10:00:00Z", "sale_date_only": "2026-10-06",
        "minimum_bid": "1000.00", "value": "50000", "sale_notes": "LOT 1",
        "prop_address_one": "1 Main St", "prop_city": "HOUSTON", "prop_zipcode": "77002",
        "geometry": {"coordinates": [-95.37, 29.76]},
    }
    base.update(overrides)
    return base


def tx_rows(n: int, *, start: int = 1) -> list[dict]:
    return [row(uid=f"u{i}", account_nbr=f"A{i}", cause_nbr=f"C{i}") for i in range(start, start + n)]


def envelope(results, next_url=None) -> dict:
    return {"count": len(results), "next": next_url, "previous": None, "results": results}


def finalize(result, *, exhausted: bool = False) -> AcquisitionRun:
    run = AcquisitionRun(source_id="tx_lgbs", state="TX")
    run.record_result(result, county="Harris")
    run.pagination_exhausted = exhausted
    run.finalize(expected_denominator=None)
    return run


# ===========================================================================
# A. page 1 succeeds, page 2 raises a TransportError  (the live defect)
# ===========================================================================


def test_p46_A1_page1_records_survive_a_page2_transport_error():
    t = (FixtureTransport()
         .add_json(PAGE1, envelope(tx_rows(3), next_url=PAGE2))
         .add_error(PAGE2, SourceUnavailable(f"{PAGE2}: timed out")))

    result = LgbsAdapter(transport=t).acquire()

    assert result.records_acquired == 3, "page-1 records were discarded by the page-2 failure"
    assert len(result.records) == 3
    assert result.records_seen == 3
    assert {r["_source_record_id"] for r in result.records} == {"u1", "u2", "u3"}


def test_p46_A2_the_failure_is_preserved_not_swallowed():
    t = (FixtureTransport()
         .add_json(PAGE1, envelope(tx_rows(3), next_url=PAGE2))
         .add_error(PAGE2, SourceUnavailable(f"{PAGE2}: timed out")))

    result = LgbsAdapter(transport=t).acquire()

    assert result.status == AcquisitionStatus.SOURCE_UNAVAILABLE
    assert result.status in ACQUISITION_FAILURE_STATUSES
    assert result.status not in ACQUISITION_PRODUCED_RECORDS
    assert result.errors and "timed out" in result.errors[0]
    assert PAGE2 in result.errors[0], "the error must name the page that failed"


def test_p46_A3_retaining_records_does_not_make_the_run_look_finished():
    """The counterpart to A1. Keeping the records must not upgrade the run."""
    t = (FixtureTransport()
         .add_json(PAGE1, envelope(tx_rows(3), next_url=PAGE2))
         .add_error(PAGE2, SourceUnavailable(f"{PAGE2}: timed out")))

    result = LgbsAdapter(transport=t).acquire()
    run = finalize(result)

    assert run.status == RunStatus.INCOMPLETE
    assert run.status != RunStatus.COMPLETE
    assert run.pagination_exhausted is False
    assert run.errors, "the run must carry the failure, not just the result"


def test_p46_A4_a_failed_walk_leaves_a_checkpoint_that_retries_the_failed_page():
    """Resuming must re-request the page that failed, not skip past it -
    skipping would silently drop that page's records from the resumed run."""
    t = (FixtureTransport()
         .add_json(PAGE1, envelope(tx_rows(3), next_url=PAGE2))
         .add_error(PAGE2, SourceUnavailable(f"{PAGE2}: timed out")))

    result = LgbsAdapter(transport=t).acquire()

    assert result.checkpoint is not None
    assert result.checkpoint["next_url"] == PAGE2


def test_p46_A5_accounting_reflects_records_actually_seen():
    t = (FixtureTransport()
         .add_json(PAGE1, envelope(tx_rows(3), next_url=PAGE2))
         .add_error(PAGE2, SourceUnavailable(f"{PAGE2}: timed out")))

    run = finalize(LgbsAdapter(transport=t).acquire())
    tally = run.tally

    assert tally.records_seen == 3, "0 = 0+0+0+0 balanced but hid three retrieved records"
    assert tally.records_acquired == 3
    assert tally.is_balanced
    assert tally.records_seen == (
        tally.records_acquired + tally.records_rejected
        + tally.records_failed + tally.records_duplicated
    )


# ===========================================================================
# B. both pages succeed - the unchanged happy path
# ===========================================================================


def test_p46_B1_two_good_pages_retain_everything_and_walk_to_the_end():
    t = (FixtureTransport()
         .add_json(PAGE1, envelope(tx_rows(3), next_url=PAGE2))
         .add_json(PAGE2, envelope(tx_rows(2, start=4), next_url=None)))

    result = LgbsAdapter(transport=t).acquire()

    assert result.status == AcquisitionStatus.SUCCESS
    assert result.records_acquired == 5
    assert result.records_seen == 5
    assert result.errors == ()
    assert result.checkpoint is None, "a fully-walked run leaves nothing to resume"
    assert t.requested_urls == [PAGE1, PAGE2]


def test_p46_B2_a_completed_walk_can_still_reach_COMPLETE():
    """Proof the fix did not make success unreachable."""
    t = (FixtureTransport()
         .add_json(PAGE1, envelope(tx_rows(3), next_url=PAGE2))
         .add_json(PAGE2, envelope(tx_rows(2, start=4), next_url=None)))

    result = LgbsAdapter(transport=t).acquire()
    run = AcquisitionRun(source_id="tx_lgbs", state="TX")
    run.record_result(result, county="Harris")
    run.pagination_exhausted = True
    run.tally.records_observed_at_source = 5
    run.finalize(expected_denominator=5)

    assert run.status == RunStatus.COMPLETE


# ===========================================================================
# C. page 1 itself fails
# ===========================================================================


def test_p46_C1_first_page_failure_yields_zero_records_and_preserves_the_error():
    t = FixtureTransport().add_error(PAGE1, SourceUnavailable(f"{PAGE1}: timed out"))

    result = LgbsAdapter(transport=t).acquire()

    assert result.records_acquired == 0
    assert result.records == ()
    assert result.records_seen == 0
    assert result.status == AcquisitionStatus.SOURCE_UNAVAILABLE
    assert result.errors and "timed out" in result.errors[0]


def test_p46_C2_first_page_failure_is_INCOMPLETE_not_NO_DATA():
    """'Reached and empty' and 'could not be reached' must stay distinct."""
    t = FixtureTransport().add_error(PAGE1, SourceUnavailable(f"{PAGE1}: timed out"))

    result = LgbsAdapter(transport=t).acquire()
    run = finalize(result)

    assert result.status != AcquisitionStatus.NO_DATA
    assert run.status == RunStatus.INCOMPLETE


# ===========================================================================
# D. page 2 returns a malformed response
# ===========================================================================


def test_p46_D1_page1_records_survive_a_malformed_page2():
    t = (FixtureTransport()
         .add_json(PAGE1, envelope(tx_rows(3), next_url=PAGE2))
         .add_error(PAGE2, SchemaError(f"{PAGE2}: response envelope has no 'results' key")))

    result = LgbsAdapter(transport=t).acquire()

    assert result.records_acquired == 3
    assert result.status == AcquisitionStatus.SCHEMA_FAILURE
    assert result.errors and "results" in result.errors[0]
    assert finalize(result).status == RunStatus.INCOMPLETE


def test_p46_D2_a_schema_failure_is_not_reported_as_a_source_outage():
    t = (FixtureTransport()
         .add_json(PAGE1, envelope(tx_rows(3), next_url=PAGE2))
         .add_error(PAGE2, SchemaError(f"{PAGE2}: not JSON")))

    result = LgbsAdapter(transport=t).acquire()
    assert result.status == AcquisitionStatus.SCHEMA_FAILURE
    assert result.status != AcquisitionStatus.SOURCE_UNAVAILABLE


# ===========================================================================
# E. rejected and duplicate records on page 1, then a page-2 failure
# ===========================================================================


def test_p46_E1_every_accounting_category_survives_a_later_failure():
    page1 = [
        row(uid="t1", account_nbr="A1", cause_nbr="C1"),
        row(uid="t2", account_nbr="A2", cause_nbr="C2"),
        row(uid="pa1", state="PA", county="PHILADELPHIA COUNTY", account_nbr="P1"),
        row(uid="t1", account_nbr="A1", cause_nbr="C1"),          # duplicate of t1
        row(uid="x1", status="Some Unmapped Status", account_nbr="A9"),
    ]
    t = (FixtureTransport()
         .add_json(PAGE1, envelope(page1, next_url=PAGE2))
         .add_error(PAGE2, SourceUnavailable(f"{PAGE2}: timed out")))

    run = finalize(LgbsAdapter(transport=t).acquire())
    tally = run.tally

    assert tally.records_seen == 5
    assert tally.records_acquired == 2
    assert tally.records_duplicated == 1
    assert tally.rejections_by_reason.get(RejectionReason.OUT_OF_STATE.value) == 1
    assert tally.is_balanced, (
        f"seen={tally.records_seen} vs accounted_for={tally.accounted_for}"
    )
    assert run.status == RunStatus.INCOMPLETE


def test_p46_E2_out_of_state_rejections_are_still_classified_after_a_failure():
    """The PA rejection must not be downgraded to UNCLASSIFIED just because
    the walk ended badly."""
    page1 = [row(), row(uid="pa1", state="PA", county="PHILADELPHIA COUNTY", account_nbr="P1")]
    t = (FixtureTransport()
         .add_json(PAGE1, envelope(page1, next_url=PAGE2))
         .add_error(PAGE2, SourceUnavailable(f"{PAGE2}: timed out")))

    run = finalize(LgbsAdapter(transport=t).acquire())

    assert run.tally.rejections_by_reason.get(RejectionReason.OUT_OF_STATE.value) == 1
    assert "UNCLASSIFIED" not in run.tally.rejections_by_reason


# ===========================================================================
# F. several good pages, then a failure
# ===========================================================================


def test_p46_F1_all_prior_pages_remain_represented():
    t = (FixtureTransport()
         .add_json(PAGE1, envelope(tx_rows(3), next_url=PAGE2))
         .add_json(PAGE2, envelope(tx_rows(3, start=4), next_url=PAGE3))
         .add_error(PAGE3, SourceUnavailable(f"{PAGE3}: timed out")))

    result = LgbsAdapter(transport=t).acquire()

    assert result.records_acquired == 6
    assert {r["_source_record_id"] for r in result.records} == {"u1", "u2", "u3", "u4", "u5", "u6"}
    assert result.checkpoint["next_url"] == PAGE3
    assert t.requested_urls == [PAGE1, PAGE2, PAGE3]
    assert finalize(result).status == RunStatus.INCOMPLETE


def test_p46_F2_retrieval_metadata_is_kept_for_every_page_that_answered():
    t = (FixtureTransport()
         .add_json(PAGE1, envelope(tx_rows(3), next_url=PAGE2))
         .add_json(PAGE2, envelope(tx_rows(3, start=4), next_url=PAGE3))
         .add_error(PAGE3, SourceUnavailable(f"{PAGE3}: timed out")))

    result = LgbsAdapter(transport=t).acquire()

    assert len(result.retrievals) == 2, "the two pages that answered must stay in the evidence"
    assert [r.records_seen for r in result.retrievals] == [3, 3]


# ===========================================================================
# G. limit interaction - a limit must still stop the walk cleanly
# ===========================================================================


def test_p46_G1_limit_still_stops_the_walk_without_a_failure_status():
    t = (FixtureTransport()
         .add_json(PAGE1, envelope(tx_rows(5), next_url=PAGE2))
         .add_error(PAGE2, SourceUnavailable("page 2 must never be requested")))

    result = LgbsAdapter(transport=t).acquire(limit=3)

    assert result.records_acquired == 3
    assert result.status == AcquisitionStatus.SUCCESS
    assert result.errors == ()
    assert t.requested_urls == [PAGE1], "a satisfied limit must not request another page"


# ===========================================================================
# H. the regression itself, stated as the live run's shape
# ===========================================================================


def test_p46_H1_the_run3_shape_can_no_longer_occur():
    """Run 35109232214 reported pages_retrieved=1 with records_seen=0. That
    combination - a page retrieved, nothing seen - is the defect's
    signature, and must now be unreachable when the page returned records."""
    t = (FixtureTransport()
         .add_json(PAGE1, envelope(tx_rows(500), next_url=PAGE2))
         .add_error(PAGE2, SourceUnavailable(f"{PAGE2}: timed out")))

    run = finalize(LgbsAdapter(transport=t).acquire())

    assert run.pages_retrieved >= 1
    assert not (run.pages_retrieved >= 1 and run.tally.records_seen == 0), (
        "a retrieved page that returned records must never report records_seen=0"
    )
    assert run.tally.records_seen == 500
    assert run.tally.records_acquired == 500
    assert run.status == RunStatus.INCOMPLETE


# ===========================================================================
# I. the workflow flaw that cost us the denominator on run 35109232214
# ===========================================================================


def test_p46_I1_denominator_step_survives_a_failed_acquisition():
    """Run 35109232214's acquisition step failed, so GitHub skipped the
    denominator step - a measurement that has nothing to do with acquisition
    was cancelled by acquisition failing. `always()` is what stops that."""
    yaml = pytest.importorskip("yaml")
    import pathlib

    wf = pathlib.Path(__file__).resolve().parents[2] / ".github/workflows/lgbs-acquisition-validation.yml"
    steps = yaml.safe_load(wf.read_text(encoding="utf-8"))["jobs"]["acquire"]["steps"]
    step = next(s for s in steps if s.get("name", "").startswith("Measure live TX denominator"))

    assert step["if"] == "always() && inputs.mode != 'probe'"
    assert "always()" in step["if"], "a failed acquisition must not cancel the measurement"
    assert "inputs.mode != 'probe'" in step["if"], "probe stays minimal - still skipped there"


def test_p46_I2_the_acquisition_step_still_fails_the_job():
    """`always()` on a later step must not turn the acquisition step itself
    into a soft failure - no `|| true`, no continue-on-error."""
    yaml = pytest.importorskip("yaml")
    import pathlib

    wf = pathlib.Path(__file__).resolve().parents[2] / ".github/workflows/lgbs-acquisition-validation.yml"
    steps = yaml.safe_load(wf.read_text(encoding="utf-8"))["jobs"]["acquire"]["steps"]
    acquire = next(s for s in steps if s.get("name", "").startswith("Run acquisition"))

    assert acquire.get("continue-on-error") is None
    assert "|| true" not in acquire["run"]
