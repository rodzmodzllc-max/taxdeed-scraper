"""Parcel boundaries from the two approved parcel-geometry sources (2026-10-20).

harvesters/boundary (geometry, sources, plan), scripts/parcel_boundary_refresh.py
and the read path in public/parcel-boundary.js / app.js. Offline: no network,
no database (the migration's live layer is test_migration_034_parcel_boundaries.py).
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

from harvesters.boundary import geometry as G  # noqa: E402
from harvesters.boundary import plan as PL  # noqa: E402
from harvesters.boundary import sources as S  # noqa: E402
from harvesters.governance import permissions as P  # noqa: E402
from harvesters.governance import source_approvals as A  # noqa: E402

import parcel_boundary_refresh as R  # noqa: E402

TODAY = date(2026, 10, 21)
FL, UT = "fl_dor_pto_parcel_gis", "ut_ugrc_lir_saltlake"
APP = (REPO / "public/app.js").read_text(encoding="utf-8")
M034 = (REPO / "scripts/migrations/034_parcel_boundaries.sql").read_text(encoding="utf-8")


def poly(x, y, h=0.0003, extra=True):
    ring = [[x, y], [x + h, y], [x + h, y + h]]
    if extra:   # a vertex inside the simplification tolerance
        ring.append([x + h / 2, y + h + 0.0000001])
    ring += [[x, y + h], [x, y]]
    return {"type": "Polygon", "coordinates": [ring]}


def feat(pid, oid, geom):
    return {"type": "Feature", "properties": {"PARCEL_ID": pid, "OBJECTID": oid}, "geometry": geom}


# --- exact source-to-dataset scope mapping -----------------------------------

def test_boundary_sources_are_exactly_the_two_approved_sources():
    assert set(S.SOURCES) == set(A.load()) == {FL, UT}


def test_each_source_maps_its_own_dataset_and_names_what_is_unresolved():
    reg = A.load()
    fl, ut = reg[FL], reg[UT]
    assert fl.covered_datasets[0].startswith("fl_dor_pto_parcel_gis <- ") and "MAPPED" in fl.covered_datasets[0]
    assert "Request Assessment Roll GIS Data" in fl.covered_datasets[0] and "county_parcel_geometry" in fl.covered_datasets[0]
    assert "Florida GeoData" in fl.covered_datasets[1] and "NOT mapped" in fl.covered_datasets[1]
    # The statewide cadastral FeatureServer is NOT the covered dataset.
    assert "fl_statewide_cadastral_fgio" in fl.unresolved_mapping and "NOT approved for geometry" in fl.unresolved_mapping
    assert ut.covered_datasets[0].startswith("ut_ugrc_lir_saltlake <- Parcels_SaltLake_LIR") and "MAPPED" in ut.covered_datasets[0]
    assert "NOT mapped" in ut.covered_datasets[1]
    assert "Utah COUNTY" in ut.unresolved_mapping            # Parcels_Utah_LIR is not statewide
    assert S.UT_UGRC.dataset == "Parcels_SaltLake_LIR" and S.UT_UGRC.counties == ("Salt Lake",)
    assert "Parcels_SaltLake_LIR" in S.UT_UGRC.layer_url


def test_register_refuses_a_row_that_does_not_map_its_own_source():
    rows = [{c: "" for c in A.COLUMNS}]
    approval = A.parse(rows)[0]
    assert any("covered_datasets is required" in p for p in A.validate([approval]))
    good = A.load()[UT]
    from dataclasses import replace
    wrong = replace(good, covered_datasets=("ut_other <- something: MAPPED",))
    assert any("must map the source's own id" in p for p in A.validate([wrong]))


def test_expected_cadence_is_separate_from_the_actual_refresh():
    reg = A.load()
    assert reg[FL].expected_refresh_cadence.startswith("Annual, published about mid-August to early September")
    assert reg[UT].expected_refresh_cadence.startswith("Generally monthly")
    assert reg[FL].last_successful_refresh == reg[UT].last_successful_refresh == "NEVER"


def test_evidence_records_only_what_was_supplied():
    for a in A.load().values():
        assert a.evidence_received_on == ""             # never supplied, never invented
        assert "Implement Confirmed Florida DOR and Utah UGRC Parcel Approvals" in a.evidence_ref
        assert "@" not in a.evidence_ref + a.evidence_sender   # no address recorded
    assert A.load()[FL].readme_reviewed and A.load()[FL].technical_readme_reviewed_on == "2026-10-20"
    assert A.load()[FL].technical_caveats.startswith("Reviewed from the Parcel Shapefiles Readme")
    assert A.load()[FL].readme_reviewed


# --- permission gates ----------------------------------------------------------

def test_utah_is_runnable_and_displayable():
    r = S.readiness(S.UT_UGRC, today=TODAY)
    assert r == {"source_id": UT, "runnable": True, "reasons": [], "display_allowed": True,
                 "display_reason": "ALLOWED_DOCUMENTED"}


def test_florida_reads_local_dor_files_once_the_readme_is_recorded():
    r = S.readiness(S.FL_DOR, today=TODAY)
    assert r["runnable"] and r["display_allowed"]
    assert S.FL_DOR.location == "files" and S.FL_DOR.layer_url is None      # no download URL is guessed
    assert S.FL_DOR.feature_key_field == "PARCELNO" and S.FL_DOR.id_rule == "exact"


@pytest.mark.parametrize("source_id,state,dataset", [
    ("fl_fdor_cadastral", "FL", "parcel_centroid"), ("fl_fdor_cadastral", "FL", None),
    ("fl_santa_rosa_parcels", "FL", None), ("co_oit_public_parcels", "CO", None),
    ("wi_sco_v12_parcels", "WI", None), ("fl_dor_statewide", "FL", None),
])
def test_unrelated_sources_are_never_approved_to_store_or_display_geometry(source_id, state, dataset):
    for op in ("store", "display"):
        d = P.authorize(source_id, op, state=state, dataset=dataset, today=TODAY)
        assert not (d.allowed and d.basis == "DOCUMENTED" and source_id in S.SOURCES), (source_id, op)
    assert source_id not in S.SOURCES


@pytest.mark.parametrize("dataset", [None, "tax_roll_attributes", "nal", "sdf", "sale_calendar", "lands_available"])
def test_the_florida_approval_covers_no_other_dor_dataset_or_field(dataset):
    for op in ("store", "display", "enrich"):
        assert P.authorize(FL, op, state="FL", dataset=dataset, today=TODAY).reason_code == "NO_RECORD"


def test_no_approval_covers_export_or_redistribution():
    for sid, st, ds in ((FL, "FL", "county_parcel_geometry"), (UT, "UT", None)):
        for op in ("redistribute", "fetch_via_proxy"):
            assert not P.authorize(sid, op, state=st, dataset=ds, today=TODAY).allowed


# --- geometry: storage format, simplification ---------------------------------

def test_polygon_is_normalised_to_multipolygon_and_simplified():
    prep = G.prepare(poly(-111.9, 40.7))
    assert prep["ok"] and prep["geometry"]["type"] == "MultiPolygon"
    assert prep["vertices_in"] == 6 and prep["vertices_out"] == 5        # the near-collinear vertex goes
    ring = prep["geometry"]["coordinates"][0][0]
    assert ring[0] == ring[-1] and len(ring) >= 4
    assert all(len(str(v).split(".")[-1]) <= G.COORD_DECIMALS for p in ring for v in p)


def test_simplification_keeps_every_part_and_hole():
    outer = [[0, 0], [0.001, 0], [0.001, 0.001], [0, 0.001], [0, 0]]
    hole = [[0.0004, 0.0004], [0.0006, 0.0004], [0.0006, 0.0006], [0.0004, 0.0006], [0.0004, 0.0004]]
    other = [[0.002, 0], [0.003, 0], [0.003, 0.001], [0.002, 0.001], [0.002, 0]]
    mp = {"type": "MultiPolygon", "coordinates": [[outer, hole], [other]]}
    out = G.prepare(mp)["geometry"]
    assert len(out["coordinates"]) == 2 and len(out["coordinates"][0]) == 2


@pytest.mark.parametrize("geom,reason", [
    (None, "missing"), ({"type": "Point", "coordinates": [0, 0]}, "unsupported_type"),
    ({"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1]]]}, "open_ring"),
    ({"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [2, 0], [0, 0]]]}, "zero_area"),
    ({"type": "Polygon", "coordinates": [[[0, 0], [200, 0], [1, 1], [0, 0]]]}, "out_of_range"),
])
def test_invalid_geometry_is_refused(geom, reason):
    assert G.prepare(geom) == {"ok": False, "reason": reason}


def test_content_hash_is_stable_and_order_sensitive():
    a = G.prepare(poly(-111.9, 40.7))
    assert a["sha256"] == G.prepare(poly(-111.9, 40.7))["sha256"]
    assert a["sha256"] != G.prepare(poly(-111.9, 40.71))["sha256"]


@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
def test_python_validation_matches_the_front_end():
    cases = [
        {"type": "MultiPolygon", "coordinates": [[[[0, 0], [1, 0], [1, 1], [0, 0]]]]},
        {"type": "MultiPolygon", "coordinates": [[[[0, 0], [1, 0], [1, 1], [0, 1]]]]},
        {"type": "MultiPolygon", "coordinates": [[[[0, 0], [1, 0], [2, 0], [0, 0]]]]},
        {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]},
        {"type": "MultiPolygon", "coordinates": []},
        {"type": "MultiPolygon", "coordinates": [[[[0, 0], [181, 0], [1, 1], [0, 0]]]]},
    ]
    js = ("import('" + (REPO / "public/parcel-boundary.js").as_uri() + "').then(m => {"
          "const cases = JSON.parse(process.argv[1]);"
          "console.log(JSON.stringify(cases.map(c => { const v = m.validateBoundary(c); return v.ok ? 'ok' : v.reason; })));});")
    out = subprocess.run(["node", "--input-type=module", "-e", js, json.dumps(cases)],
                         capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    py = [("ok" if (v := G.validate(c))["ok"] else v["reason"]) for c in cases]
    assert json.loads(out.stdout) == py


# --- the plan: association, Florida caveats, duplicates, failures ---------------

RECS = [
    {"id": "a", "state": "UT", "county": "Salt Lake", "parcel": "15-01-101-001-0000"},
    {"id": "b", "state": "UT", "county": "Salt Lake", "parcel": "15011010020000"},      # stacked polygons
    {"id": "c", "state": "UT", "county": "Salt Lake", "parcel": "15011010030000"},      # only in a multi-parcel feature
    {"id": "d", "state": "UT", "county": "Salt Lake", "parcel": ""},                    # no identifier
    {"id": "e", "state": "UT", "county": "Salt Lake", "parcel": "15011010050000"},      # condo unit: no polygon
    {"id": "f", "state": "UT", "county": "Salt Lake", "parcel": "15011010060000"},      # invalid geometry
]
FEATS = [
    feat("15011010010000", 1, poly(-111.9, 40.70)),
    feat("15011010020000", 2, poly(-111.9, 40.71)), feat("15011010020000", 3, poly(-111.9, 40.72)),
    feat("15011010030000, 15011010040000", 4, poly(-111.9, 40.73)),
    feat("15011010060000", 6, {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1]]]}),
    feat("15011019990000", 9, poly(-111.9, 40.79)),                                    # claimed by no record
]


def test_plan_associates_only_one_exact_identifier_match():
    plan = PL.plan_refresh(RECS, FEATS, {}, S.UT_UGRC, read_status="COMPLETE", observed_at="2026-10-21T00:00:00Z")
    assert [r["property_id"] for r in plan["rows"]] == ["a"]
    row = plan["rows"][0]
    assert row["source_feature_id"] == "1" and row["source_dataset"] == "Parcels_SaltLake_LIR"
    assert row["source_id"] == UT and row["match_method"] == "EXACT_PARCEL_ID" and row["parcel"] == "15-01-101-001-0000"
    assert row["attribution"] == "Utah Geospatial Resource Center (UGRC)"
    assert row["geometry"]["type"] == "MultiPolygon" and re.fullmatch(r"[0-9a-f]{64}", row["content_sha256"])
    c = plan["counts"]
    assert c["matched"] == 1 and c["ambiguous"] == 1 and c["no_identifier"] == 1
    assert c["MULTI_PARCEL_FEATURE"] == 1 and c["INVALID_GEOMETRY"] == 1 and c["invalid_geometry"] == 1
    assert c["unmatched"] == 2                   # c (only a multi-parcel feature) and e (condo unit, no polygon)
    assert c["unclaimed_features"] == 1 and c["deleted"] == 0


def test_one_feature_claimed_by_two_records_is_attached_to_neither():
    recs = [{"id": "x", "parcel": "15011010010000"}, {"id": "y", "parcel": "1501101001-0000"}]
    plan = PL.plan_refresh(recs, FEATS[:1], {}, S.UT_UGRC, read_status="COMPLETE", observed_at="t")
    assert plan["rows"] == [] and plan["counts"]["ambiguous"] == 2


def test_unchanged_geometry_is_not_rewritten_and_a_changed_one_replaces_its_own_row():
    first = PL.plan_refresh(RECS[:1], FEATS[:1], {}, S.UT_UGRC, read_status="COMPLETE", observed_at="t1")
    sha = first["rows"][0]["content_sha256"]
    same = PL.plan_refresh(RECS[:1], FEATS[:1], {"a": {"source_id": UT, "content_sha256": sha}}, S.UT_UGRC,
                           read_status="COMPLETE", observed_at="t2")
    assert same["rows"] == [] and same["counts"]["unchanged"] == 1
    moved = PL.plan_refresh(RECS[:1], [feat("15011010010000", 1, poly(-111.9, 40.701))],
                            {"a": {"source_id": UT, "content_sha256": sha}}, S.UT_UGRC,
                            read_status="COMPLETE", observed_at="t3")
    assert [r["change"] for r in moved["rows"]] == ["replace"]


def test_another_sources_boundary_is_never_replaced():
    plan = PL.plan_refresh(RECS[:1], FEATS[:1], {"a": {"source_id": FL, "content_sha256": "0" * 64}}, S.UT_UGRC,
                           read_status="COMPLETE", observed_at="t")
    assert plan["rows"] == [] and plan["counts"]["kept_other_source"] == 1


@pytest.mark.parametrize("status", ["INCOMPLETE", "FAILED", "SOURCE_UNAVAILABLE", "STALE", "EMPTY", "", None])
def test_a_failed_or_partial_read_changes_nothing(status):
    plan = PL.plan_refresh(RECS, FEATS, {"a": {"source_id": UT, "content_sha256": "1" * 64}}, S.UT_UGRC,
                           read_status=status, observed_at="t")
    assert plan["rows"] == [] and plan["counts"] == {"skipped_read_not_complete": 1}


def test_a_parcel_missing_from_a_complete_read_keeps_its_boundary():
    stored = {"a": {"source_id": UT, "content_sha256": "1" * 64}}
    plan = PL.plan_refresh(RECS[:1], [], stored, S.UT_UGRC, read_status="COMPLETE", observed_at="t")
    assert plan["rows"] == [] and plan["counts"]["kept_not_in_read"] == 1 and plan["counts"]["deleted"] == 0


# --- the refresh script ------------------------------------------------------------

class FakeDb:
    def __init__(self, applied=True, records=None, stored=None):
        self.applied, self.records, self._stored = applied, records or [], stored or {}
        self.upserts, self.refreshes = [], []

    def migration_applied(self):
        return self.applied

    def properties(self, src, county=None):
        return list(self.records)

    def stored(self, ids):
        return {k: v for k, v in self._stored.items() if k in ids}

    def upsert(self, source_id, rows):
        self.upserts.append((source_id, rows))
        return {"inserted": len(rows)}

    def record_refresh(self, source_id, status, at):
        self.refreshes.append((source_id, status))


def test_readiness_report_makes_no_request_and_prints_no_identifier(capsys):
    assert R.main([]) == 0
    out = capsys.readouterr().out
    assert "READY     ut_ugrc_lir_saltlake" in out and "READY     fl_dor_pto_parcel_gis" in out
    assert "requests: 0; writes: 0" in out


def test_florida_refuses_before_any_request_or_database_read():
    db, reads = FakeDb(), []
    # Florida is read from local county files; without a county and a file
    # nothing is read and nothing is written (no download URL is guessed).
    rc = R.run(FL, apply=True, db=db, read=lambda *a: reads.append(a) or ("COMPLETE", []), out=lambda m: None, today=TODAY)
    assert rc == 2 and reads == [] and db.upserts == [] and db.refreshes == []


def test_without_migration_034_nothing_is_read_or_written():
    db, reads = FakeDb(applied=False, records=RECS), []
    assert R.run(UT, apply=True, db=db, read=lambda *a: reads.append(a) or ("COMPLETE", []), out=lambda m: None,
                 today=TODAY) == 4
    assert reads == [] and db.upserts == []


def test_apply_writes_the_planned_rows_and_records_a_complete_refresh():
    db, lines = FakeDb(records=RECS), []
    rc = R.run(UT, apply=True, db=db, read=lambda src, keys: ("COMPLETE", FEATS), out=lines.append, today=TODAY)
    assert rc == 0 and len(db.upserts) == 1
    sid, rows = db.upserts[0]
    assert sid == UT and [r["property_id"] for r in rows] == ["a"] and "change" not in rows[0]
    assert db.refreshes == [(UT, "COMPLETE")]
    printed = "\n".join(lines)
    for r in RECS:
        if r["parcel"]:
            assert r["parcel"] not in printed and r["parcel"].replace("-", "") not in printed


def test_an_incomplete_read_writes_no_boundary_and_records_a_failed_attempt():
    db, lines = FakeDb(records=RECS, stored={"a": {"source_id": UT, "content_sha256": "1" * 64}}), []
    rc = R.run(UT, apply=True, db=db, read=lambda src, keys: ("INCOMPLETE", FEATS[:1]), out=lines.append, today=TODAY)
    assert rc == 5 and db.upserts == [] and db.refreshes == [(UT, "INCOMPLETE")]
    assert "last successful refresh unchanged" in lines[-1]


def test_dry_run_writes_nothing():
    db = FakeDb(records=RECS)
    assert R.run(UT, apply=False, db=db, read=lambda src, keys: ("COMPLETE", FEATS), out=lambda m: None,
                 today=TODAY) == 0
    assert db.upserts == [] and db.refreshes == []


def test_no_property_in_scope_means_no_request():
    db, reads = FakeDb(records=[]), []
    assert R.run(UT, apply=True, db=db, read=lambda *a: reads.append(a) or ("COMPLETE", []), out=lambda m: None,
                 today=TODAY) == 0
    assert reads == [] and db.refreshes == []


class _Resp:
    def __init__(self, body):
        self.body = json.dumps(body).encode()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self.body


def test_arcgis_read_is_incomplete_on_any_error_or_truncation():
    ok = {"type": "FeatureCollection", "features": FEATS[:1]}
    assert R.arcgis_read(S.UT_UGRC, ["1"], opener=lambda req, timeout: _Resp(ok)) == ("COMPLETE", FEATS[:1])
    assert R.arcgis_read(S.UT_UGRC, ["1"], opener=lambda req, timeout: _Resp({**ok, "exceededTransferLimit": True}))[0] == "INCOMPLETE"
    assert R.arcgis_read(S.UT_UGRC, ["1"], opener=lambda req, timeout: _Resp({"error": {"code": 400}}))[0] == "INCOMPLETE"

    def boom(req, timeout):
        raise OSError("down")
    assert R.arcgis_read(S.UT_UGRC, ["1"], opener=boom)[0] == "INCOMPLETE"
    seen = []
    R.arcgis_read(S.UT_UGRC, [str(i) for i in range(250)], opener=lambda req, timeout: seen.append(req.full_url) or _Resp(ok))
    assert len(seen) == 3 and all("outSR=4326" in u and "f=geojson" in u and "Parcels_SaltLake_LIR" in u for u in seen)


def test_refresh_bookkeeping_only_advances_on_a_complete_read():
    s0 = A.RefreshState(expected_cadence="Generally monthly", last_successful_refresh="NEVER")
    s1 = A.apply_refresh(s0, status="INCOMPLETE", at="2026-10-21T00:00:00Z")
    assert s1.last_successful_refresh == "NEVER" and s1.consecutive_failures == 1
    s2 = A.apply_refresh(s1, status="COMPLETE", at="2026-10-22T00:00:00Z")
    assert s2.last_successful_refresh == "2026-10-22T00:00:00Z" and s2.expected_cadence == "Generally monthly"
    # The SQL bookkeeping follows the same rule.
    assert "ok boolean := upper(coalesce(p_status, '')) = 'COMPLETE';" in M034
    assert "last_successful_refresh_at = case when ok then p_at else last_successful_refresh_at end" in M034


# --- attribution on every customer-facing surface ---------------------------------

def test_migration_seed_matches_the_approval_register():
    reg = A.load()
    for sid, a in reg.items():
        attr = S.attribution(sid)
        cols = ["credit", "change_notice", "disclaimer_url", "metadata_url"]
        # Only a published licence is shown as a licence; DOR's written
        # permission is not one, so Florida's licence columns seed empty.
        cols += ["license_name", "license_url"] if a.basis == "PUBLISHED_LICENSE" else []
        for col in cols:
            if attr[col]:
                assert "'" + attr[col].replace("'", "''") + "'" in M034, (sid, col)
        assert a.expected_refresh_cadence.split(" (")[0] in M034


def test_the_read_contract_returns_the_full_attribution():
    fn = M034[M034.index("create or replace function public.get_property_boundary"):]
    fn = fn[:fn.index("$$;")]
    for col in ("attribution text", "license_name text", "license_url text", "change_notice text", "disclaimer text",
                "disclaimer_url text", "metadata_url text", "source_dataset text", "source_feature_id text"):
        assert col in fn, col
    assert "security invoker" in fn and "s.display_approved" in fn


def test_the_front_end_shows_credit_licence_changes_disclaimer_and_metadata():
    for needle in ('"Parcel outline: "', "Licence: ", "Changes: ", "Source disclaimer", "Dataset metadata",
                   "it is not a survey and does not show ownership or title"):
        assert needle.strip('"') in APP, needle
    js = (REPO / "public/parcel-boundary.js").read_text(encoding="utf-8")
    assert "if (!attribution.credit || !attribution.changeNotice) return { status: \"none\" };" in js
    assert "if (attribution.licenseName && !attribution.licenseUrl) return { status: \"none\" };" in js


def test_exports_and_list_payloads_never_carry_geometry():
    # The boundary is fetched per property into its own cache and drawn as an
    # overlay; it is never assigned onto a property row, so no export, list,
    # map or saved-search path can carry it.
    assert not re.search(r"\bp\.(boundary|geom|geometry)\b", APP)
    assert "BOUNDARY_CACHE" in APP and "fetchPropertyBoundary(sb, pid, row)" in APP
    for path in sorted((REPO / "scripts/migrations").glob("0*.sql")):
        if path.name in ("034_parcel_boundaries.sql",):
            continue
        assert "parcel_boundaries" not in path.read_text(encoding="utf-8")


def test_unrelated_assessment_attributes_are_never_requested_with_geometry():
    # The boundary read asks for the identifier and the feature id only.
    seen = []
    R.arcgis_read(S.UT_UGRC, ["1"], opener=lambda req, timeout: seen.append(req.full_url)
                  or _Resp({"type": "FeatureCollection", "features": []}))
    assert "outFields=PARCEL_ID%2COBJECTID" in seen[0]
    for col in ("TOTAL_MKT_VALUE", "OWN", "PARCEL_ADD"):
        assert col not in seen[0]


def test_the_owners_summaries_of_both_replies_are_recorded_as_summaries():
    reg = A.load()
    fl, ut = reg[FL].evidence_ref, reg[UT].evidence_ref
    assert "no separate county-level permissions required" in fl and "mid-August and early September" in fl
    assert "all statewide and county parcels fall under this licence" in ut and "no strict limits on caching" in ut
    for a in reg.values():
        assert "owner's summary of the reply" in a.evidence_ref
        assert "not in this repository" in a.evidence_limitation.lower()     # still not the original


def test_florida_pin_file_location_is_recorded_for_broward_only_and_nothing_reads_it():
    # The owner copied this exact link from the portal (2026-10-20). No other
    # county is assumed from its pattern. Only the manual Broward loader reads it
    # (dry run by default); the join itself is the validated-NAL-id rule.
    files = S.FL_DOR_PIN_FILES
    assert set(files) == {"Broward"}
    b = files["Broward"]
    assert b["url"] == ("https://floridarevenue.com/property/dataportal/Documents/PTO%20Data%20Portal/"
                        "Map%20Data/2025F/2025F%20PIN/broward_2025pin.zip")
    assert b["variant"] == "PIN" and b["tax_year"] == 2025 and b["copied_on"] == "2026-10-20"
    assert S.FL_DOR.join_configured is True and S.FL_DOR.location == "files" and S.FL_DOR.layer_url is None
    assert S.FL_DOR.record_key == "nal_parcel_id" and S.FL_DOR.id_rule == "exact"
    assert S.FL_DOR.feature_key_field == "PARCELNO" and S.FL_DOR.feature_id_field == "FID"
