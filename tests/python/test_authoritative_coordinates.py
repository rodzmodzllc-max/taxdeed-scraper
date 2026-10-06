"""Authoritative coordinates (2026-10-06): method / geometry provenance,
deterministic matching, no-downgrade replacement, the Census geocode path."""
import json
import re
from pathlib import Path

import pytest

from harvesters.sources import coordinates as C

REPO = Path(__file__).resolve().parents[2]
CASES = json.loads((REPO / "tests/python/fixtures/coordinate_cases.json").read_text(encoding="utf-8"))
APP = (REPO / "public/app.js").read_text(encoding="utf-8")


@pytest.mark.parametrize("case", CASES["provenance"], ids=lambda c: c["name"])
def test_provenance_vectors(case):
    got = C.coordinate_provenance(case["row"])
    assert (got["method"], got["geometry"], got["authoritative"]) == (case["method"], case["geometry"], case["authoritative"])


@pytest.mark.parametrize("case", CASES["replace"])
def test_replacement_only_goes_up_and_never_downgrades_authoritative(case):
    assert C.should_replace(case["existing"], case["new"]) is case["replace"]


@pytest.mark.parametrize("case", CASES["match"])
def test_only_deterministic_matches_produce_coordinates(case):
    assert C.accept_match(case["kind"], case["features"], address_agrees=case.get("address_agrees", False)) is case["accept"]


@pytest.mark.parametrize("case", CASES["county"])
def test_county_matching_handles_independent_cities(case):
    assert C.county_matches(case["county"], case["census"]) is case["match"]


@pytest.mark.parametrize("case", CASES["address"])
def test_address_agreement_requires_same_house_number_and_street(case):
    assert C.address_agrees(case["input"], case["matched"]) is case["agrees"]


def _js_obj(name):
    return re.search(r"var " + name + r" = \{(.*?)\n?\};", APP, re.S).group(1)


def test_js_mirrors_python():
    labels = dict(re.findall(r"(\w+): \"([^\"]+)\"", _js_obj("COORD_METHOD_LABELS")))
    assert labels == C.METHOD_LABELS
    geo = dict(re.findall(r"(\w+): \"([^\"]+)\"", _js_obj("COORD_GEOMETRY_LABELS")))
    assert geo == C.GEOMETRY_LABELS
    src = {k: (a, b) for k, a, b in re.findall(r"(\w+): \[\"(\w+)\", \"(\w+)\"\]", _js_obj("COORD_SOURCE_COORDINATES"))}
    assert src == {k: v[:2] for k, v in C.SOURCE_COORDINATES.items()}
    prov = {k: (a, b) for k, a, b in re.findall(r"(\w+): \[\"(\w+)\", \"(\w+)\"\]", _js_obj("COORD_PROVENANCE_COORDINATES"))}
    assert prov == C.PROVENANCE_COORDINATES
    auth = set(re.findall(r'"(\w+)"', re.search(r"var COORD_AUTHORITATIVE = \[(.*?)\];", APP).group(1)))
    assert auth == set(C.AUTHORITATIVE)


def test_geocode_entry_is_never_authoritative_and_ranks_lowest():
    import sys
    sys.path.insert(0, str(REPO / "scripts"))
    import field_provenance as FP
    e = C.geocode_provenance_entry("census_matched_address")
    assert e["method"] == "DETERMINISTIC_GEOCODE" and e["source"] == "census_geocoder"
    assert C.coordinate_provenance({"latitude": 1, "longitude": 1, "field_provenance": {"latitude": e}})["authoritative"] is False
    assert FP.RANK["census_geocoder"] < min(v for k, v in FP.RANK.items() if k != "census_geocoder")
    # A parcel layer may replace a geocode; a geocode may not replace a parcel layer.
    assert FP.may_write({"latitude": e}, "latitude", "statewide_parcel", 1.0)
    assert not FP.may_write({"latitude": {"source": "statewide_parcel"}}, "latitude", "census_geocoder", 1.0)


def test_parcel_coordinate_configs_are_inert_until_verified():
    from harvesters.enrichment import parcels as P, sources as S
    cfg = next(c for c in S.all_sources() if c.source_id == "mo_stl_parcels_coordinates")
    assert cfg.centroid and cfg.field_map == {} and cfg.counties == ("St. Louis City",)
    assert P.enrichment_allowed(cfg)[0] is False


def test_coordinate_probe_targets_exist_for_every_coordinate_gap_state():
    src = (REPO / "scripts/discover_sources.py").read_text(encoding="utf-8")
    for st in ("MO", "OK", "PA", "SC"):
        assert re.search(r'\{"state": "' + st + r'", "county": "[^"]+", "kind": "arcgis", "purpose": "coordinates"', src), st


# ---- the geocode script's scoped (AVAILABLE) mode ----
@pytest.fixture
def geo(monkeypatch):
    import importlib.util
    monkeypatch.setenv("SUPABASE_URL", "https://example.test")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "not-a-real-key")
    monkeypatch.setenv("GEOCODE_SOURCE_ID", "mo_stl_lra_inventory")
    monkeypatch.setattr("time.sleep", lambda *_: None)
    spec = importlib.util.spec_from_file_location("_coord_geo", REPO / "scripts/geocode_properties.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _census(lat, lng, county_name, matched, base="St. Louis"):
    return {"coordinates": {"x": lng, "y": lat}, "matchedAddress": matched,
            "addressComponents": {"state": "MO"}, "geographies": {"Counties": [{"BASENAME": base, "NAME": county_name}]}}


class _Resp:
    def __init__(self, data, status=200):
        self._d, self.status_code, self.text = data, status, ""

    def json(self):
        return self._d

    def raise_for_status(self):
        return None


def _wire(mod, monkeypatch, rows, census):
    calls = {"fetch": [], "patch": [], "out": []}

    def fake_get(url, params=None, headers=None, timeout=None):
        if "/rest/v1/properties" in url:
            calls["fetch"].append(dict(params or {}))
            return _Resp(rows if len(calls["fetch"]) == 1 else [])
        return _Resp({"result": {"addressMatches": census}})

    def fake_patch(url, headers=None, json=None, timeout=None):
        calls["patch"].append(json)
        return _Resp({})
    monkeypatch.setattr(mod.requests, "get", fake_get)
    monkeypatch.setattr(mod.requests, "patch", fake_patch)
    return calls


def test_scoped_geocode_writes_provenance_and_scopes_the_fetch(geo, monkeypatch, capsys):
    rows = [{"id": "m1", "address": "1234 N FIXTURE ST", "county": "St. Louis City", "state": "MO", "field_provenance": {"address": {"source": "county_list"}}}]
    calls = _wire(geo, monkeypatch, rows, [_census(38.63, -90.2, "St. Louis city", "1234 N FIXTURE ST, ST LOUIS, MO, 63101")])
    geo.main()
    assert calls["fetch"][0]["source_id"] == "eq.mo_stl_lra_inventory" and calls["fetch"][0]["latitude"] == "is.null"
    (body,) = calls["patch"]
    assert body["latitude"] == 38.63 and body["longitude"] == -90.2
    assert body["field_provenance"]["latitude"]["method"] == "DETERMINISTIC_GEOCODE"
    assert body["field_provenance"]["address"] == {"source": "county_list"}  # kept
    out = capsys.readouterr().out
    assert "FIXTURE" not in out  # public log: no address


def test_scoped_geocode_rejects_wrong_house_number_and_st_louis_county(geo, monkeypatch):
    rows = [{"id": "m2", "address": "1234 FIXTURE ST", "county": "St. Louis City", "state": "MO"}]
    calls = _wire(geo, monkeypatch, rows, [
        _census(38.6, -90.3, "St. Louis County", "1234 FIXTURE ST, CLAYTON, MO, 63105"),   # the county, not the city
        _census(38.6, -90.2, "St. Louis city", "1236 FIXTURE ST, ST LOUIS, MO, 63101"),    # neighbouring house
    ])
    geo.main()
    assert calls["patch"] == []
