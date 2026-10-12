"""Parcel boundary permission matrix, geometry rules and the read-only dry run.

Every test here is offline. The matrix must cover every parcel source the
enrichment registry knows, and nothing may be enabled.
"""
import contextlib
import io
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from harvesters.boundary import geometry as G  # noqa: E402
from harvesters.boundary import permissions as P  # noqa: E402
from harvesters.enrichment import geocode as GEO  # noqa: E402
from harvesters.enrichment import sources as SRC  # noqa: E402
import scripts.parcel_boundary_harvest as CLI  # noqa: E402


def sq(x0, y0, x1, y1):
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]


OK = {"type": "MultiPolygon", "coordinates": [[sq(-82.05, 26.93, -82.04, 26.94)]]}


# ---- matrix coverage and the default (nothing enabled) ----------------------

def test_matrix_covers_every_registered_parcel_source():
    matrix = P.load_matrix()
    for cfg in SRC.all_sources():
        assert cfg.source_id in matrix, f"{cfg.source_id} missing from the boundary matrix"
    for src in (GEO.FDOR_SOURCE, GEO.SANTA_ROSA_SOURCE):
        assert src.source_id in matrix, f"{src.source_id} missing from the boundary matrix"


def test_nothing_is_enabled_today():
    matrix = P.load_matrix()
    assert P.enabled_sources(matrix) == []
    assert all(not p.enabled() for p in matrix.values())


def test_utah_is_eligible_but_not_enabled():
    p = P.load_matrix()["ut_ugrc_lir_saltlake"]
    assert p.boundary_policy == "ELIGIBLE_NOT_ENABLED"
    assert p.enabled() is False


def test_registry_approval_is_not_boundary_permission():
    """Colorado, Louisiana and Santa Rosa are APPROVED for enrichment; boundary stays off."""
    matrix = P.load_matrix()
    for sid in ("co_oit_public_parcels", "la_ebr_tax_parcels", "fl_santa_rosa_parcels", "fl_fdor_cadastral"):
        assert matrix[sid].enrichment_status.startswith("APPROVED")
        assert matrix[sid].boundary_policy == "DISABLED"


def test_unknown_policy_and_duplicates_are_refused(tmp_path):
    bad = tmp_path / "m.csv"
    bad.write_text("source_id,state,enrichment_status,boundary_policy,geometry_verified,licence_evidence,reason\n"
                   "x,FL,UNREVIEWED,ON,yes,ev,r\n", encoding="utf-8")
    with pytest.raises(ValueError):
        P.load_matrix(bad)
    dup = tmp_path / "d.csv"
    row = "x,FL,UNREVIEWED,DISABLED,yes,ev,r\n"
    dup.write_text("source_id,state,enrichment_status,boundary_policy,geometry_verified,licence_evidence,reason\n" + row + row, encoding="utf-8")
    with pytest.raises(ValueError):
        P.load_matrix(dup)


def test_enabled_needs_every_condition():
    base = dict(source_id="s", state="FL", enrichment_status="APPROVED", boundary_policy="APPROVED",
                geometry_verified=True, licence_evidence="evidence", reason="r")
    assert P.BoundaryPermission(**base).enabled() is True
    assert P.BoundaryPermission(**{**base, "boundary_policy": "ELIGIBLE_NOT_ENABLED"}).enabled() is False
    assert P.BoundaryPermission(**{**base, "geometry_verified": False}).enabled() is False
    assert P.BoundaryPermission(**{**base, "licence_evidence": "  "}).enabled() is False


def test_is_boundary_enabled_is_false_for_unknown_source():
    assert P.is_boundary_enabled("no_such_source") is False


# ---- geometry validation (parity with public/parcel-boundary.js) ------------

def test_valid_multipolygon_with_hole_and_component():
    multi = {"type": "MultiPolygon", "coordinates": [[sq(0, 0, 1, 1), sq(0.3, 0.3, 0.6, 0.6)], [sq(2, 0, 3, 1)]]}
    v = G.validate(multi)
    assert v["ok"] is True and len(v["polygons"]) == 2
    assert v["bbox"] == {"minX": 0, "minY": 0, "maxX": 3, "maxY": 1}


@pytest.mark.parametrize("input_,reason", [
    (None, "missing"),
    ("{not json", "malformed"),
    ({"type": "Polygon", "coordinates": [sq(0, 0, 1, 1)]}, "unsupported_type"),
    ({"type": "MultiPolygon", "coordinates": []}, "empty"),
    ({"type": "MultiPolygon", "coordinates": [[]]}, "malformed"),
    ({"type": "MultiPolygon", "coordinates": [[[[0, 0], [1, 0], [0, 0]]]]}, "short_ring"),
    ({"type": "MultiPolygon", "coordinates": [[[[0, 0], [1, 0], [1, 1], [0, 1], [0.5, 0.5]]]]}, "open_ring"),
    ({"type": "MultiPolygon", "coordinates": [[[[0, 0], [1, 0], [True, 1], [0, 1], [0, 0]]]]}, "malformed"),
    ({"type": "MultiPolygon", "coordinates": [[sq(0, 0, 200, 1)]]}, "out_of_range"),
    ({"type": "MultiPolygon", "coordinates": [[sq(0, 0, 0, 0)]]}, "zero_area"),
])
def test_invalid_geometry_is_refused(input_, reason):
    assert G.validate(input_) == {"ok": False, "reason": reason}


def test_point_match_allows_small_tolerance_only():
    bbox = G.validate(OK)["bbox"]
    assert G.point_matches(-82.045, 26.935, bbox) is True
    assert G.point_matches(-82.0, 26.935, bbox) is False


def test_content_hash_is_stable_and_order_independent():
    a = {"type": "MultiPolygon", "coordinates": [[sq(0, 0, 1, 1)]]}
    b = {"coordinates": [[sq(0, 0, 1, 1)]], "type": "MultiPolygon"}
    assert G.content_sha256(a) == G.content_sha256(b)
    assert len(G.content_sha256(a)) == 64


# ---- write decisions: never overwrite good geometry -------------------------

def rec(source="s1", when="2026-10-01", sha="a" * 64, valid=True):
    return {"source_id": source, "source_observed_at": when, "content_sha256": sha, "valid": valid}


@pytest.mark.parametrize("existing,incoming,expected", [
    (None, rec(), "insert"),
    (None, rec(valid=False), "skip_invalid"),
    (rec(), rec(valid=False), "skip_invalid"),
    (rec(), rec(), "unchanged"),
    (rec(sha="a" * 64), rec(sha="b" * 64, when="2026-10-05"), "replace"),
    (rec(when="2026-10-05"), rec(sha="b" * 64, when="2026-10-01"), "keep_newer_existing"),
    (rec(source="s1"), rec(source="s2", sha="b" * 64, when="2026-10-09"), "keep_existing_other_source"),
])
def test_write_decisions(existing, incoming, expected):
    assert G.decide_write(existing, incoming) == expected


# ---- the read-only dry run --------------------------------------------------

def test_dry_run_makes_no_requests_and_writes_nothing():
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        assert CLI.main([]) == 0
    out = buf.getvalue()
    assert "enabled: 0; requests: 0; writes: 0" in out
    assert "ENABLED " not in out.replace("NOT ENABLED", "")


def test_backfill_plan_reports_zero_eligible():
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        assert CLI.main(["--plan-backfill"]) == 0
    assert "enabled sources 0; eligible properties 0" in buf.getvalue()


def test_cli_has_no_apply_path():
    src = (REPO / "scripts" / "parcel_boundary_harvest.py").read_text(encoding="utf-8")
    assert "--apply" not in src and "create_client" not in src and "requests.get" not in src and "urlopen" not in src
