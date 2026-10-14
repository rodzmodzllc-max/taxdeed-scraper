"""scripts/laft_lifecycle.py under the ledger health reader (2026-10-14).

The lifecycle closes AVAILABLE rows that left a county's list. Since this
change every status entry passes harvesters/ledgers/health.py first, and
close-out is decided per SOURCE, not per county:

  * FAILED, INCOMPLETE, SOURCE_UNAVAILABLE, STALE, NOT_RUN and a missing
    status file close nothing;
  * EMPTY closes only with row count 0, an explicit empty signal and a read
    that did not fail at transport or parse;
  * a COMPLETE from a read that failed at transport or parse closes nothing;
  * a row naming its source closes only on that source's own read; a
    sibling source's COMPLETE never closes it;
  * a denied `store` permission withdraws the county (fail closed);
  * a re-listed row is reactivated with status alone - its history and
    provenance columns are never written by the reactivation.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
import laft_lifecycle as L  # noqa: E402
import laft_status as ls  # noqa: E402

NOW = ls.now_iso()
PDFS, HTML = "fl_laft_pdfs", "fl_laft_html"


def entry(county, status, source=PDFS, **kw):
    e = {"county": county, "harvester": source, "source_id": source, "status": status, "checked_at": NOW,
         "state": "FL", "row_count": kw.pop("row_count", 0 if status == "EMPTY" else 3)}
    e.update(kw)
    return e


def db(*rows):
    out = []
    for i, r in enumerate(rows):
        county, case, *rest = r
        row = {"id": i + 1, "county": county, "case_no": case, "status": "active"}
        if rest:
            row["source_id"] = rest[0]
        out.append(row)
    return out


def closes(entries, rows, observed=(), expected=()):
    gates = L.county_gates(entries, list(expected), state="FL")
    plan = L.plan_lifecycle(gates, L.observed_by_county([{"county": c, "case_no": k} for c, k in observed]), rows)
    return sorted(r["case_no"] for r in plan.close), gates, plan


# ------------------------------------------------------------- failures never close

@pytest.mark.parametrize("bad", [
    entry("Marion", "FAILED", error_category="TRANSPORT_TIMEOUT"),          # transport failure
    entry("Marion", "FAILED", error_category="TRANSPORT_HTTP_403_BLOCKED"),  # source unavailable
    entry("Marion", "FAILED", error_category="PARSE_FORMAT_CHANGE"),         # parser failure
    entry("Marion", "INCOMPLETE", error_category="UNCONFIRMED_EMPTY"),      # partial harvest
    entry("Marion", "SOURCE_UNAVAILABLE"),
    entry("Marion", "COMPLETE", transport_ok=False),                         # broken read recorded COMPLETE
    entry("Marion", "COMPLETE", parse_ok=False),
    entry("Marion", "COMPLETE", checked_at="2000-01-01T00:00:00+00:00"),     # stale
])
def test_a_failed_partial_or_stale_read_closes_nothing(bad):
    closed, gates, _ = closes([bad], db(("Marion", "GONE", PDFS), ("Marion", "GONE2")))
    assert closed == []
    assert gates["Marion"]["closeout_ok"] is False


def test_missing_status_closes_nothing():
    closed, gates, _ = closes([], db(("Marion", "GONE", PDFS)))
    assert closed == [] and gates == {}


def test_expected_county_with_no_entry_is_not_run():
    closed, gates, _ = closes([], db(("Marion", "GONE", PDFS)), expected=[(PDFS, "Marion")])
    assert closed == [] and gates["Marion"]["status"] == "NOT_RUN"


# ------------------------------------------------------------- EMPTY needs a valid signal

def test_a_valid_empty_closes_the_sources_rows():
    closed, gates, _ = closes([entry("Marion", "EMPTY", empty_signal="empty_marker")],
                              db(("Marion", "GONE", PDFS), ("Marion", "GONE2")))
    assert closed == ["GONE", "GONE2"] and gates["Marion"]["status"] == "EMPTY"


@pytest.mark.parametrize("bad", [
    {"empty_signal": None},                                       # no signal
    {"empty_signal": "empty_marker", "row_count": 4},             # rows despite "empty"
    {"empty_signal": "empty_marker", "transport_ok": False},      # failed fetch
    {"empty_signal": "empty_marker", "parse_ok": False},          # failed parse
])
def test_an_invalid_empty_is_incomplete_and_closes_nothing(bad):
    e = entry("Marion", "EMPTY")
    e.update(bad)
    closed, gates, _ = closes([e], db(("Marion", "GONE", PDFS)))
    assert closed == []
    assert gates["Marion"]["status"] == "INCOMPLETE"
    assert gates["Marion"]["entry"]["health_downgrade"].startswith("EMPTY->")


# ------------------------------------------------------------- source isolation

def test_a_sibling_sources_complete_read_never_closes_another_sources_rows():
    # Two LAFT sources list the same county; only the PDF source read it.
    entries = [entry("Marion", "COMPLETE", PDFS)]
    rows = db(("Marion", "PDF-GONE", PDFS), ("Marion", "HTML-ROW", HTML))
    closed, gates, plan = closes(entries, rows, expected=[(PDFS, "Marion"), (HTML, "Marion")])
    assert closed == ["PDF-GONE"]
    assert gates["Marion"]["missing_sources"] == [HTML]
    assert plan.kept_unattributed == 1


def test_a_row_without_a_source_is_not_closed_when_the_county_has_several_sources():
    entries = [entry("Marion", "COMPLETE", PDFS), entry("Marion", "COMPLETE", HTML)]
    closed, _, plan = closes(entries, db(("Marion", "UNKNOWN-SOURCE"), ("Marion", "HTML-GONE", HTML)))
    assert closed == ["HTML-GONE"] and plan.kept_unattributed == 1


def test_a_row_without_a_source_closes_on_the_countys_only_source():
    closed, _, _ = closes([entry("Marion", "COMPLETE", PDFS)], db(("Marion", "LEGACY")), expected=[(PDFS, "Marion")])
    assert closed == ["LEGACY"]


def test_one_failed_source_blocks_the_county_but_never_closes_by_a_sibling():
    entries = [entry("Marion", "COMPLETE", PDFS), entry("Marion", "FAILED", HTML, error_category="TRANSPORT_TIMEOUT")]
    closed, gates, _ = closes(entries, db(("Marion", "PDF-GONE", PDFS), ("Marion", "HTML-GONE", HTML)))
    assert closed == [] and gates["Marion"]["closeout_ok"] is False


def test_an_entry_from_a_source_outside_the_available_ledger_is_not_a_unit():
    entries = [entry("Marion", "COMPLETE", PDFS), entry("Marion", "COMPLETE", "fl_realauction")]
    gates = L.county_gates(entries, [], state="FL")
    assert set(gates["Marion"]["units"]) == {PDFS}
    closed, _, _ = closes(entries, db(("Marion", "AUCTION-SOURCE-ROW", "fl_realauction")))
    assert closed == []


def test_another_states_entry_never_gates_this_state():
    e = entry("Escambia", "COMPLETE", PDFS)
    e["state"] = "AL"
    closed, gates, _ = closes([e], db(("Escambia", "GONE", PDFS)))
    assert closed == [] and gates == {}


# ------------------------------------------------------------- permission stays fail-closed

def test_store_denial_withdraws_the_county():
    gates = L.county_gates([entry("Marion", "COMPLETE")], [], state="FL")
    denied = type("D", (), {"allowed": False, "reason_code": "NO_RECORD"})()
    withdrawn = L.apply_store_permission(gates, "FL", authorize=lambda s, c: denied)
    assert withdrawn == {"Marion": "NO_RECORD"}
    plan = L.plan_lifecycle(gates, L.observed_by_county([{"county": "Marion", "case_no": "A"}]),
                            db(("Marion", "GONE", PDFS), ("Marion", "A", PDFS)))
    assert plan.close == [] and plan.observe == [] and plan.ignored_rows == 1


def test_governance_error_withdraws_the_county():
    gates = L.county_gates([entry("Marion", "COMPLETE")], [], state="FL")

    def broken(s, c):
        raise RuntimeError("no records")
    assert L.apply_store_permission(gates, "FL", authorize=broken) == {"Marion": "GOVERNANCE_UNAVAILABLE:RuntimeError"}
    assert gates["Marion"]["closeout_ok"] is False


# ------------------------------------------------------------- reappearance

class FakeApi:
    def __init__(self):
        self.patches = []

    def patch(self, query, body):
        self.patches.append((query, body))


def test_reappearance_reactivates_with_status_only_and_keeps_history():
    gates = L.county_gates([entry("Marion", "COMPLETE")], [], state="FL")
    rows = [{"id": 7, "county": "Marion", "case_no": "BACK", "status": "closed", "source_id": PDFS,
             "delisted_at": "2026-09-01T00:00:00+00:00", "otc_provenance": {"purchase_instructions": "x"}}]
    observed = L.observed_by_county([{"county": "Marion", "case_no": "BACK"}])
    plan = L.plan_lifecycle(gates, observed, rows)
    assert plan.reactivate == [("Marion", "BACK")] and plan.close == []
    api = FakeApi()
    counts = L.execute(plan, gates, observed, api, state="FL", have_017=False, retrieved_at=NOW)
    assert counts["reactivated"] == 1
    assert api.patches == [("state=eq.FL&source=eq.laft&county=eq.Marion&case_no=in.%28%22BACK%22%29", {"status": "active"})]


def test_a_reactivated_row_is_never_closed_in_the_same_run():
    gates = L.county_gates([entry("Marion", "COMPLETE")], [], state="FL")
    plan = L.plan_lifecycle(gates, L.observed_by_county([{"county": "Marion", "case_no": "BACK"}]),
                            db(("Marion", "BACK", PDFS)) + [{"id": 9, "county": "Marion", "case_no": "OLD", "status": "closed",
                                                              "source_id": PDFS}])
    assert plan.close == []          # the gone row stays gone; the observed row stays open


def test_close_out_body_writes_status_and_delisted_at_only():
    gates = L.county_gates([entry("Marion", "COMPLETE")], [], state="FL")
    plan = L.plan_lifecycle(gates, {}, db(("Marion", "GONE", PDFS)))
    api = FakeApi()
    L.execute(plan, gates, {}, api, state="FL", have_017=True, retrieved_at=NOW, db_rows=None)
    assert api.patches[-1] == ("id=in.(1)", {"status": "closed", "delisted_at": NOW})
