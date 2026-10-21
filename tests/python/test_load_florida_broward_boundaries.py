"""Broward outline loader: the pure matching and filtering logic.

SYNTHETIC features and property rows only. No network, no database, and no
parcel number from the real file or the real database is in this file.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from harvesters.boundary import plan, sources as S

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("load_broward", ROOT / "scripts" / "load_florida_broward_boundaries.py")
L = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(L)

SQUARE = [[-80.20, 26.10], [-80.20, 26.11], [-80.19, 26.11], [-80.19, 26.10], [-80.20, 26.10]]


def _feature(parcelno: str, fid: int, ring=SQUARE) -> dict:
    return {"properties": {"PARCELNO": parcelno, "FID": fid},
            "geometry": {"type": "MultiPolygon", "coordinates": [[ring]]}}


def test_a_property_matches_on_the_alnum_key_and_gets_one_row():
    feats = [_feature("484106070240", 1)]
    good, _ = plan.prepare_features(feats, S.FL_DOR)
    props = [{"id": "11111111-1111-1111-1111-111111111111", "parcel": "484106-07-0240"}]
    rows, counts = L.select_matches(good, props)
    assert counts == {"MATCHED": 1}
    assert len(rows) == 1
    r = rows[0]
    assert r["county"] == "Broward" and r["state"] == "FL" and r["match_method"] == "EXACT_PARCEL_ID"
    assert r["source_feature_id"] == "1" and r["parcel"] == "484106-07-0240"
    assert r["content_sha256"] == good[0]["sha256"]
    assert r["simplify_tolerance_deg"] == L.geometry.SIMPLIFY_TOLERANCE_DEG


def test_a_property_with_no_feature_is_unmatched_and_writes_nothing():
    good, _ = plan.prepare_features([_feature("484106070240", 1)], S.FL_DOR)
    props = [{"id": "22222222-2222-2222-2222-222222222222", "parcel": "494107-10-0034"}]
    rows, counts = L.select_matches(good, props)
    assert counts == {"UNMATCHED": 1} and rows == []


def test_filter_keeps_only_wanted_keys_and_counts_duplicates_across_the_file():
    feats = [_feature("484106070240", 1), _feature("484106070240", 2), _feature("999999999999", 3)]
    kept, seen, total = L.filter_features(iter(feats), {"484106070240"})
    assert total == 3
    assert len(kept) == 2
    assert seen == {"484106070240": 2}


def test_a_null_geometry_is_refused_not_written():
    feats = [{"properties": {"PARCELNO": "484106070240", "FID": 1}, "geometry": None}]
    good, refused = plan.prepare_features(feats, S.FL_DOR)
    rows, counts = L.select_matches(good, [{"id": "33333333-3333-3333-3333-333333333333", "parcel": "484106-07-0240"}])
    assert rows == [] and counts == {"UNMATCHED": 1}
    assert refused["INVALID_GEOMETRY"] == 1


def test_counts_never_contain_a_parcel_number():
    good, _ = plan.prepare_features([_feature("484106070240", 1)], S.FL_DOR)
    _, counts = L.select_matches(good, [{"id": "44444444-4444-4444-4444-444444444444", "parcel": "484106-07-0240"}])
    assert not any("484106" in str(k) or "484106" in str(v) for k, v in counts.items())


def test_extract_refuses_a_path_that_leaves_the_target_folder(tmp_path):
    import zipfile
    bad = tmp_path / "bad.zip"
    with zipfile.ZipFile(bad, "w") as z:
        z.writestr("../escape.shp", b"x")
    with pytest.raises(RuntimeError, match="unsafe path"):
        L.extract_shapefile(bad, tmp_path)
