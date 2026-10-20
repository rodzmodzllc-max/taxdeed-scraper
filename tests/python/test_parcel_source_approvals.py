"""Florida DOR and Utah UGRC parcel-source approvals (2026-10-20).

data/source_approvals.csv + harvesters/governance/source_approvals.py, the
permission records in data/source_permissions.csv and the DOR record in
harvesters/governance/authorization.py. Offline: no network, no database.
"""
from __future__ import annotations

import csv
import io
import sys
from datetime import date
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from harvesters.governance import permissions as P  # noqa: E402
from harvesters.governance import source_approvals as A  # noqa: E402
from harvesters.governance.authorization import (  # noqa: E402
    AUTHORIZATION_GRANTED_STATUSES, PROVIDER_AUTHORIZATIONS, authorizations_for_source)

TODAY = date(2026, 10, 21)
FL, UT = "fl_dor_pto_parcel_gis", "ut_ugrc_lir_saltlake"
FL_DS = "county_parcel_geometry"
ORIGINAL_REGISTER = A.APPROVALS_CSV


@pytest.fixture
def perms():
    return P.Permissions.from_file()


def _register_with(tmp_path, monkeypatch, changes):
    """A copy of the real register with some fields changed, installed as the
    register the permission conditions read."""
    rows = list(csv.DictReader(ORIGINAL_REGISTER.open(newline="", encoding="utf-8")))
    for r in rows:
        for (sid, col), val in changes.items():
            if r["source_id"] == sid:
                r[col] = val
    path = tmp_path / "source_approvals.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=A.COLUMNS, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    monkeypatch.setattr(A, "APPROVALS_CSV", path)
    return path


README_DONE = {(FL, "technical_readme_reviewed_on"): "2026-10-21",
               (FL, "technical_caveats"): "Caveats transcribed from the Readme (test fixture)"}
UT_DISCLAIMER = {(UT, "disclaimer"): "UGRC disclaimer text (test fixture)"}


# --- the register ----------------------------------------------------------

def test_register_records_both_sources_with_conditions():
    reg = A.load()
    assert set(reg) == {FL, UT}
    for a in reg.values():
        assert a.status == "APPROVED_WITH_CONDITIONS"
        assert a.dataset_scope and a.excluded_scope and a.permitted_activities and a.conditions
        assert a.evidence_sender and a.evidence_supplied_on == "2026-10-20"
        assert "not in this repository" in a.evidence_limitation.lower()
        # Never invented: the email's received date was not supplied.
        assert a.evidence_received_on == ""
    assert reg[FL].basis == "WRITTEN_PERMISSION" and reg[UT].basis == "PUBLISHED_LICENSE"
    assert reg[UT].license_name == "CC BY 4.0" and reg[UT].license_url == "https://creativecommons.org/licenses/by/4.0/"


def test_scope_excludes_unrelated_data():
    reg = A.load()
    for word in ("tax-sale", "auction", "third-party"):
        assert word in reg[FL].excluded_scope
        assert word in reg[UT].excluded_scope
    assert "personal fields are NOT covered" in reg[FL].excluded_scope
    assert "parcels page" in reg[UT].dataset_scope


def test_expected_cadence_is_not_an_actual_refresh():
    reg = A.load()
    assert "mid-August" in reg[FL].expected_refresh_cadence and "monthly" in reg[UT].expected_refresh_cadence
    for a in reg.values():
        assert a.last_successful_refresh == "NEVER"          # no ingestion path has run for either


def test_readme_is_recorded_as_not_read():
    fl = A.load()[FL]
    assert fl.technical_readme_url.endswith("Parcel%20Shapefiles%20Readme.pdf")
    assert fl.technical_readme_reviewed_on == "" and fl.technical_caveats.startswith(A.NOT_YET_READ)
    assert not fl.readme_reviewed
    for topic in ("PIN/PAR", "PARCELNO to PARCEL_ID", "condominium", "stacked polygons", "unmatched geometries"):
        assert topic in fl.technical_caveats
    assert "not permission restrictions" in fl.technical_caveats


@pytest.mark.parametrize("col,val,expect", [
    ("last_successful_refresh", "Annual, mid-August", "last_successful_refresh"),
    ("technical_readme_reviewed_on", "2026-10-21", "caveats were not recorded"),
    ("evidence_received_on", "October", "not an ISO date"),
    ("status", "APPROVED_GRANDFATHERED", "status"),
    ("license_url", "http://creativecommons.org/licenses/by/4.0/", "https licence_url"),
])
def test_register_validation_refuses_bad_rows(col, val, expect):
    rows = list(csv.DictReader(A.APPROVALS_CSV.open(newline="", encoding="utf-8")))
    for r in rows:
        if r["source_id"] == (UT if col == "license_url" else FL):
            r[col] = val
    problems = A.validate(A.parse(rows))
    assert any(expect in p for p in problems), problems


def test_an_invalid_register_fails_the_conditions_closed(tmp_path, monkeypatch, perms):
    bad = tmp_path / "broken.csv"
    bad.write_text("not,a,register\n", encoding="utf-8")
    monkeypatch.setattr(A, "APPROVALS_CSV", bad)
    assert A.get(UT) is None
    assert perms.authorize(UT, "display", state="UT", today=TODAY).reason_code == "CONDITION_UNMET"


# --- Florida DOR: permission gate --------------------------------------------

@pytest.mark.parametrize("op", ["fetch", "parse", "store", "enrich", "display"])
def test_florida_is_denied_until_the_readme_is_reviewed(perms, op):
    d = perms.authorize(FL, op, state="FL", county="Leon", dataset=FL_DS, today=TODAY)
    assert not d.allowed and d.reason_code == "CONDITION_UNMET"


@pytest.mark.parametrize("op", ["fetch", "parse", "store", "enrich", "display"])
def test_florida_is_allowed_once_the_readme_is_recorded(tmp_path, monkeypatch, perms, op):
    _register_with(tmp_path, monkeypatch, README_DONE)
    for county in ("Leon", "Miami-Dade", None):         # no separate county permission needed
        d = perms.authorize(FL, op, state="FL", county=county, dataset=FL_DS, today=TODAY)
        assert d.allowed and d.basis == "DOCUMENTED" and d.evidence_type == "WRITTEN_PERMISSION", (op, county)


def test_florida_never_covers_export_proxy_other_datasets_or_states(tmp_path, monkeypatch, perms):
    _register_with(tmp_path, monkeypatch, README_DONE)
    for op in ("redistribute", "fetch_via_proxy", "discover", "link"):
        assert not perms.authorize(FL, op, state="FL", dataset=FL_DS, today=TODAY).allowed, op
    for ds in (None, "tax_roll_attributes", "sale_calendar", "lands_available"):
        assert perms.authorize(FL, "store", state="FL", dataset=ds, today=TODAY).reason_code == "NO_RECORD", ds
    assert perms.authorize(FL, "store", state="GA", dataset=FL_DS, today=TODAY).reason_code == "NO_RECORD"


def test_florida_approval_leaves_existing_florida_sources_unchanged(tmp_path, monkeypatch, perms):
    _register_with(tmp_path, monkeypatch, README_DONE)
    # The existing statewide cadastral path keeps its interim attribute / centroid allowance only.
    for ds in ("parcel_attributes", "parcel_centroid"):
        d = perms.authorize("fl_fdor_cadastral", "enrich", state="FL", dataset=ds, today=TODAY)
        assert d.allowed and d.basis == "INTERIM"
        assert not perms.authorize("fl_fdor_cadastral", "store", state="FL", dataset=ds, today=TODAY).allowed
        assert not perms.authorize("fl_fdor_cadastral", "display", state="FL", dataset=ds, today=TODAY).allowed
    assert not perms.authorize("fl_dor_statewide", "fetch", state="FL", today=TODAY).allowed
    # Tax-sale and auction feeds keep their own (interim) records.
    assert perms.authorize("fl_realauction", "display", state="FL", county="Leon", dataset="sale_calendar",
                           today=TODAY).basis == "INTERIM"
    for blocked in sorted(P.HARD_BLOCKED_SOURCE_IDS):
        assert perms.authorize(blocked, "fetch", state="TX", today=TODAY).reason_code == "HARD_BLOCKED"


def test_dor_authorization_record_claims_no_document_it_does_not_have():
    recs = authorizations_for_source(FL)
    assert len(recs) == 1
    r = recs[0]
    assert r.authorization_status in AUTHORIZATION_GRANTED_STATUSES
    assert r.written_permission is False and r.document.is_pending and r.document.document_location is None
    assert r.contact_email is None and r.document.document_hash is None
    for granted in ("automated_access", "commercial_use", "storage", "normalization", "derived_data",
                    "customer_display", "image_display"):
        assert r.scope.get(granted).authorized, granted
    for not_granted in ("customer_export", "api_redistribution", "document_use", "image_download"):
        assert not r.scope.get(not_granted).authorized, not_granted
    # Only the DOR record is granted; no other source gains a grant.
    assert {a.source_id for a in PROVIDER_AUTHORIZATIONS.values()
            if a.authorization_status in AUTHORIZATION_GRANTED_STATUSES} == {FL}


# --- Utah UGRC: permission gate ----------------------------------------------

@pytest.mark.parametrize("op", ["fetch", "enrich", "store"])
def test_utah_collection_is_allowed_on_the_published_licence(perms, op):
    d = perms.authorize(UT, op, state="UT", today=TODAY)
    assert d.allowed and d.basis == "DOCUMENTED" and d.evidence_type == "PUBLISHED_LICENSE"
    assert "attribution_text_recorded" in d.conditions


def test_utah_display_needs_the_full_attribution_including_a_disclaimer(tmp_path, monkeypatch, perms):
    d = perms.authorize(UT, "display", state="UT", today=TODAY)
    assert not d.allowed and d.reason_code == "CONDITION_UNMET"          # no disclaimer recorded yet
    _register_with(tmp_path, monkeypatch, UT_DISCLAIMER)
    assert perms.authorize(UT, "display", state="UT", today=TODAY).allowed
    for col in ("credit", "change_notice", "metadata_url", "license_url"):
        _register_with(tmp_path, monkeypatch, {**UT_DISCLAIMER, (UT, col): ""})
        assert not perms.authorize(UT, "display", state="UT", today=TODAY).allowed, col


def test_utah_attribution_carries_ugrc_credit_and_the_cc_by_link(tmp_path, monkeypatch):
    _register_with(tmp_path, monkeypatch, UT_DISCLAIMER)
    a = A.get(UT)
    assert a.attribution_complete
    assert a.credit == "Utah Geospatial Resource Center (UGRC)"
    assert a.license_url == "https://creativecommons.org/licenses/by/4.0/"
    assert "centroid derived from the parcel polygon" in a.change_notice
    assert a.metadata_url.startswith("https://") and "Parcels_SaltLake_LIR" in a.metadata_url


def test_utah_never_covers_export_other_sources_or_states(perms):
    for op in ("redistribute", "fetch_via_proxy", "parse", "link"):
        assert not perms.authorize(UT, op, state="UT", today=TODAY).allowed, op
    assert perms.authorize("ut_ugrc_address_points", "fetch", state="UT", today=TODAY).reason_code == "UNKNOWN_SOURCE"
    assert perms.authorize(UT, "fetch", state="CO", today=TODAY).reason_code == "NO_RECORD"


def test_the_two_approvals_are_independent(tmp_path, monkeypatch, perms):
    _register_with(tmp_path, monkeypatch, UT_DISCLAIMER)
    assert perms.authorize(UT, "display", state="UT", today=TODAY).allowed
    assert not perms.authorize(FL, "display", state="FL", dataset=FL_DS, today=TODAY).allowed
    _register_with(tmp_path, monkeypatch, README_DONE)
    assert perms.authorize(FL, "display", state="FL", dataset=FL_DS, today=TODAY).allowed
    assert not perms.authorize(UT, "display", state="UT", today=TODAY).allowed


def test_the_utah_state_is_still_not_activated():
    from harvesters.governance import states
    assert not states.is_activated("UT") and "UT" not in states.PRODUCTION_STATES


# --- refresh: expected cadence versus actual success ------------------------

def _state():
    return A.RefreshState(expected_cadence="Generally monthly", last_successful_refresh="NEVER")


@pytest.mark.parametrize("status,signal", [("FAILED", False), ("INCOMPLETE", False), ("SOURCE_UNAVAILABLE", False),
                                           ("STALE", False), ("EMPTY", False), ("", False)])
def test_a_failed_partial_or_unsignalled_read_never_counts_as_a_refresh(status, signal):
    s = A.apply_refresh(_state(), status=status, at="2026-11-01T06:00:00+00:00", empty_signal=signal)
    assert s.last_successful_refresh == "NEVER" and s.consecutive_failures == 1
    assert s.expected_cadence == "Generally monthly"


def test_only_a_complete_read_or_a_signalled_empty_advances_the_last_success():
    s = A.apply_refresh(_state(), status="COMPLETE", at="2026-11-01T06:00:00+00:00")
    assert s.last_successful_refresh == "2026-11-01T06:00:00+00:00" and s.consecutive_failures == 0
    s2 = A.apply_refresh(s, status="FAILED", at="2026-12-01T06:00:00+00:00")
    assert s2.last_successful_refresh == "2026-11-01T06:00:00+00:00" and s2.last_attempt_status == "FAILED"
    s3 = A.apply_refresh(s2, status="EMPTY", at="2026-12-02T06:00:00+00:00", empty_signal=True)
    assert s3.last_successful_refresh == "2026-12-02T06:00:00+00:00"


# --- geometry: deterministic association, simplification, refresh plan ------

SQ = [[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]


def _feat(pid, ring=SQ):
    return {"attributes": {"PARCEL_ID": pid}, "geometry": {"rings": [ring]}}


RECORDS = [{"id": 1, "parcel": "12-34 567"}, {"id": 2, "parcel": "999"}, {"id": 3, "parcel": "777"},
           {"id": 4, "parcel": ""}]
FEATURES = [_feat("1234567"), _feat("777"), _feat("777", [[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]), _feat("555")]


def test_geometry_is_associated_only_on_one_exact_identifier():
    m = {x.property_id: x for x in A.match_geometries(RECORDS, FEATURES, record_key="parcel", feature_key="PARCEL_ID",
                                                       normalize=lambda v: "".join(ch for ch in str(v or "") if ch.isalnum()))}
    assert m[1].outcome == "MATCHED" and m[1].feature["attributes"]["PARCEL_ID"] == "1234567"
    assert m[2].outcome == "UNMATCHED" and m[2].feature is None
    assert m[3].outcome == "AMBIGUOUS" and m[3].feature is None       # stacked polygons / condominium units
    assert m[4].outcome == "NO_IDENTIFIER"
    assert A.unmatched_features(FEATURES, RECORDS, record_key="parcel", feature_key="PARCEL_ID",
                                normalize=lambda v: "".join(ch for ch in str(v or "") if ch.isalnum())) == 1


def test_a_failed_or_partial_refresh_changes_and_deletes_nothing():
    stored = {1: {"source_id": FL, "geometry": {"rings": [SQ]}}, 9: {"source_id": FL, "geometry": {"rings": [SQ]}}}
    matches = A.match_geometries(RECORDS, FEATURES, record_key="parcel", feature_key="PARCEL_ID")
    for status in ("FAILED", "INCOMPLETE", "SOURCE_UNAVAILABLE", "EMPTY"):
        plan = A.plan_geometry_refresh(stored, matches, source_id=FL, read_status=status, observed_at="t")
        assert plan["skipped_read_not_complete"] and not plan["insert"] and not plan["replace"] and not plan["deleted"]


def test_a_complete_refresh_keeps_missing_geometry_and_never_duplicates():
    stored = {1: {"source_id": FL, "geometry": {"rings": [SQ]}}, 9: {"source_id": FL, "geometry": {"rings": [SQ]}}}
    norm = lambda v: "".join(ch for ch in str(v or "") if ch.isalnum())  # noqa: E731
    matches = A.match_geometries(RECORDS + [{"id": 1, "parcel": "1234567"}], FEATURES, record_key="parcel",
                                 feature_key="PARCEL_ID", normalize=norm)
    plan = A.plan_geometry_refresh(stored, matches, source_id=FL, read_status="COMPLETE", observed_at="t")
    assert plan["unchanged"] == [1] and not plan["insert"] and not plan["replace"]   # one row per property
    assert plan["kept_not_in_read"] == [9] and plan["deleted"] == []
    assert sorted(plan["unmatched"], key=str) == [2, 4] and plan["ambiguous"] == [3]
    fresh = A.plan_geometry_refresh({}, matches, source_id=FL, read_status="COMPLETE", observed_at="t")
    assert [r["property_id"] for r in fresh["insert"]] == [1]


def test_simplification_keeps_a_valid_closed_ring():
    ring = [[0, 0], [1, 0.0001], [2, 0], [2, 2], [1, 2.0001], [0, 2], [0, 0]]
    out = A.simplify_ring(ring, 0.01)
    assert out[0] == out[-1] and len(out) >= 4 and len(out) < len(ring)
    tiny = [[0, 0], [1, 0], [1, 0.000001], [0, 0]]
    assert A.simplify_ring(tiny, 1.0) == tiny                       # never collapsed to a zero-area ring
    with pytest.raises(ValueError):
        A.simplify_ring([[0, 0], [1, 0], [1, 1]], 0.1)              # not closed


def test_no_parcel_geometry_storage_exists_on_main_yet():
    """The approvals record permission only: no migration on main creates a
    geometry table, so nothing is stored or served until a separate, approved
    change adds one (PR #144 carries an unmerged design)."""
    migrations = (REPO / "scripts" / "migrations").glob("*.sql")
    for m in migrations:
        text = m.read_text(encoding="utf-8").lower()
        assert "geometry(multipolygon" not in text and "parcel_boundaries" not in text, m.name
