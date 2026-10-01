"""The reusable statewide parcel enrichment factory (six-state sprint):
deterministic matching only, a gate on verified + approved sources,
field-level provenance, no derived values the source does not publish."""
from __future__ import annotations

import re
from urllib.parse import parse_qs, urlsplit

import pytest

from harvesters.enrichment import parcels as P
from scripts import field_provenance as FP


def cfg(**kw):
    base = dict(source_id="xx_parcels", state="NC", agency="Agency", dataset="Statewide Parcels",
                landing_url="https://example.gov/parcels", layer_url="https://example.gov/arcgis/rest/services/P/FeatureServer/1",
                id_field="PARNO", id_rule="alnum", county_field="CNTYNAME",
                field_map={"owner_name": "OWNNAME", "land_value": "LANDVAL", "improvement_value": "IMPROVVAL",
                           "market": "PARVAL", "acreage": "GISACRES", "address": "SITEADD"},
                licence="free to use by anyone without restriction", publication_status="APPROVED",
                value_year_field="REVISEDATE_YR", centroid=True, columns_verified=True)
    base.update(kw)
    return P.ParcelSourceConfig(**base)


def feat(parno, county="WAKE", **attrs):
    a = {"PARNO": parno, "CNTYNAME": county, "OWNNAME": "SMITH JOHN", "LANDVAL": 10000, "IMPROVVAL": 0,
         "PARVAL": 10000, "GISACRES": 1.25, "SITEADD": "1 MAIN ST", "REVISEDATE_YR": 2026}
    a.update(attrs)
    ring = [[-78.64, 35.78], [-78.63, 35.78], [-78.63, 35.79], [-78.64, 35.79], [-78.64, 35.78]]
    return {"attributes": a, "geometry": {"rings": [ring]}}


def test_f01_ids_normalize_deterministically_and_reject_labels():
    assert P.normalize_id(" 0784-12-3456 ", "alnum") == "0784123456"
    assert P.normalize_id("12.34/56", "digits") == "123456"
    assert P.normalize_id("r-12a", "exact") == "R-12A"
    for bad in (None, "", "   ", "UNKNOWN", "N/A"):
        assert P.normalize_id(bad, "alnum") is None


def test_f02_match_is_by_county_and_identifier_only_never_owner_or_address():
    c = cfg()
    idx = P.index_features(c, [feat("0784-12-3456"), feat("0784123457", OWNNAME="DOE JANE")])
    rows = [{"id": "a", "county": "Wake", "parcel": "0784123456", "owner_name": "SOMEONE ELSE", "address": "9 OTHER RD"},
            {"id": "b", "county": "Wake", "parcel": "9999999999", "owner_name": "SMITH JOHN", "address": "1 MAIN ST"},
            {"id": "c", "county": "Durham", "parcel": "0784123456"},
            {"id": "d", "county": "Wake", "parcel": ""}]
    got = {m.row_id: m.status for m in P.match_rows(c, rows, idx)}
    assert got == {"a": "MATCHED", "b": "UNMATCHED", "c": "UNMATCHED", "d": "NO_IDENTIFIER"}
    # row b's owner and address equal the feature's - still unmatched: names/addresses never attach data
    src = open(P.__file__).read()
    code = "\n".join(l for l in src.splitlines() if not l.strip().startswith("#"))
    match_fn = code[code.index("def match_rows"):code.index("def _coerce")]
    assert "owner" not in match_fn and "address" not in match_fn and "latitude" not in match_fn


def test_f03_two_features_for_one_key_are_ambiguous_and_nothing_is_written():
    c = cfg()
    idx = P.index_features(c, [feat("0784-12-3456"), feat("0784 12 3456")])
    [m] = P.match_rows(c, [{"id": "a", "county": "Wake", "parcel": "0784123456"}], idx)
    assert m.status == "AMBIGUOUS" and m.feature is None
    assert P.plan_update(c, {"id": "a"}, m, recorded_at="t") == ({}, {})


def test_f04_plan_maps_fields_drops_zero_and_sentinels_and_records_provenance():
    c = cfg()
    idx = P.index_features(c, [feat("0784123456", IMPROVVAL=0, OWNNAME="UNKNOWN")])
    [m] = P.match_rows(c, [{"id": "a", "county": "Wake", "parcel": "0784-12-3456"}], idx)
    fields, prov = P.plan_update(c, {"id": "a"}, m, recorded_at="2026-10-01T00:00:00+00:00")
    assert "improvement_value" not in fields and "owner_name" not in fields      # 0 and a sentinel are "not published"
    assert fields["land_value"] == 10000 and fields["acreage"] == 1.25 and fields["value_year"] == 2026
    assert 35.78 < fields["latitude"] < 35.79 and -78.64 < fields["longitude"] < -78.63
    for col, e in prov.items():
        assert e["source"] == "statewide_parcel" and e["source_id"] == "xx_parcels" and e["matched_parcel_id"] == "0784123456"
        assert e["layer_url"] == c.layer_url and e["licence"] and e["recorded_at"]
    assert prov["latitude"]["derived"].startswith("area-weighted centroid")
    FP.merge_field_provenance({}, prov)                                          # valid entries for the shared writer


def test_f05_provenance_precedence_never_clobbers_equal_or_stronger_values():
    row = {"land_value": 5, "field_provenance": {"land_value": {"source": "county_list"}}, "acreage": None}
    kept = FP.filter_by_provenance(row, {"land_value": 10000, "acreage": 2.0}, "statewide_parcel")
    assert kept == {"acreage": 2.0}
    row = {"land_value": 5, "field_provenance": {"land_value": {"source": "hand_research"}}}
    assert FP.filter_by_provenance(row, {"land_value": 1}, "statewide_parcel") == {}


def test_f06_gate_refuses_unverified_or_uncleared_sources():
    assert P.enrichment_allowed(cfg())[0]
    assert not P.enrichment_allowed(cfg(columns_verified=False))[0]
    for st in ("UNREVIEWED", "RESTRICTED", "BLOCKED"):
        ok, why = P.enrichment_allowed(cfg(publication_status=st))
        assert not ok and st in why


def test_f07_query_urls_ask_for_exact_ids_scoped_to_the_county_in_batches():
    c = cfg(batch_size=2)
    urls = P.query_urls(c, "Wake", ["1", "2", "3", "2", " "])
    assert len(urls) == 2
    q = parse_qs(urlsplit(urls[0]).query)
    assert q["where"][0] == "UPPER(CNTYNAME) = 'WAKE' AND (PARNO IN ('1','2'))"   # county name case-insensitive, ids exact
    assert q["outSR"] == ["4326"] and q["returnGeometry"] == ["true"] and q["f"] == ["json"]
    assert "O''BRIEN" in parse_qs(urlsplit(P.query_urls(c, "O'Brien", ["1"])[0]).query)["where"][0]


def test_f08_config_validation():
    with pytest.raises(ValueError):
        cfg(layer_url="http://example.gov/x/FeatureServer/1")
    with pytest.raises(ValueError):
        cfg(id_rule="fuzzy")
    with pytest.raises(ValueError):
        cfg(field_map={"bogus_column": "X"})
    with pytest.raises(ValueError):
        cfg(field_map={"owner_name": "PARNO"})


def test_f09_centroid_is_from_the_parcel_polygon_only():
    assert P.polygon_centroid(None) is None and P.polygon_centroid({"rings": [[[0, 0], [1, 1]]]}) is None
    lat, lng = P.polygon_centroid({"rings": [[[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]]})
    assert (lat, lng) == (1.0, 1.0)


def test_f10_coverage_reports_counts_with_denominators():
    cov = P.Coverage()
    for s in ("MATCHED", "UNMATCHED", "AMBIGUOUS", "NO_IDENTIFIER", "MATCHED"):
        cov.add(P.MatchResult("x", s))
    d = cov.as_dict()
    assert d["rows_considered"] == 5 and d["matched"] == 2 and d["ambiguous"] == 1
    assert not any(re.search(r"pct|percent", k) for k in d)


def test_f11_runner_end_to_end_with_an_injected_layer_and_gates(monkeypatch):
    from harvesters.enrichment import sources as S
    from harvesters.governance import states
    from scripts import enrich_statewide_parcels as R
    c = cfg(state="ZZ")
    monkeypatch.setitem(S.PARCEL_SOURCES, "ZZ", c)
    rows = [{"id": "a", "county": "Wake", "parcel": "0784-12-3456", "land_value": None, "field_provenance": None},
            {"id": "b", "county": "Wake", "parcel": "1111", "land_value": 7, "field_provenance": {"land_value": {"source": "county_list"}}}]
    calls, writes = [], {}

    def fetch(url):
        calls.append(url)
        return {"features": [feat("0784123456"), feat("1111")]}

    rep = R.run("ZZ", rows, fetch, write=lambda i, f: writes.setdefault(i, f), recorded_at="t")
    assert rep["rows_considered"] == 2 and rep["matched"] == 2 and rep["rows_written"] == 2
    assert writes["a"]["land_value"] == 10000 and "land_value" not in writes["b"]         # a county_list value is kept
    assert writes["a"]["field_provenance"]["land_value"]["source"] == "statewide_parcel"
    # a failed query attaches nothing
    rep = R.run("ZZ", rows, lambda u: {"error": {"code": 500}}, write=lambda i, f: 1 / 0, recorded_at="t")
    assert rep["failed_queries"] == 1 and rep["rows_written"] == 0
    # an uncleared source never queries
    monkeypatch.setitem(S.PARCEL_SOURCES, "ZZ", cfg(state="ZZ", publication_status="UNREVIEWED"))
    rep = R.run("ZZ", rows, lambda u: 1 / 0, recorded_at="t")
    assert "reuse not cleared" in rep["skipped"]
    # the CLI refuses an unactivated state before anything
    assert not states.is_activated("ZZ") and R.main(["--state", "ZZ"]) == 0


def test_f20_alternate_identifier_fields_match_one_feature_or_fail_closed():
    c = cfg(id_field="PROP_ID", alt_id_fields=("GEO_ID",), row_id_column="case_no", id_rule="digits",
            field_map={"market": "PARVAL", "acreage": "GISACRES"})
    a = feat("x", PROP_ID="123456", GEO_ID="0001-0002-0003")
    b = feat("y", PROP_ID="000100020003", GEO_ID="999")       # its PROP_ID equals a's GEO_ID digits
    same = feat("z", PROP_ID="555", GEO_ID="555")              # one feature reached through both fields
    idx = P.index_features(c, [a, b, same])
    rows = [{"id": "1", "county": "Wake", "case_no": "123456", "parcel": "24-TX-0001"},
            {"id": "2", "county": "Wake", "case_no": "0001 0002 0003"},
            {"id": "3", "county": "Wake", "case_no": "555"},
            {"id": "4", "county": "Wake", "case_no": None, "parcel": "123456"}]
    got = {m.row_id: m for m in P.match_rows(c, rows, idx)}
    assert got["1"].status == "MATCHED" and got["1"].feature["_matched_field"] == "PROP_ID"
    assert got["2"].status == "AMBIGUOUS"            # two different features through two attributes
    assert got["3"].status == "MATCHED"              # the same feature twice is one candidate
    assert got["4"].status == "NO_IDENTIFIER"        # the configured row column only - never the parcel instead
    fields, prov = P.plan_update(c, rows[0], got["1"], recorded_at="t")
    assert prov["market"]["matched_id_field"] == "PROP_ID" and prov["market"]["matched_row_column"] == "case_no"


def test_f21_identical_twins_without_objectid_stay_ambiguous():
    c = cfg()
    idx = P.index_features(c, [feat("0784123456"), feat("0784123456")])
    [m] = P.match_rows(c, [{"id": "a", "county": "Wake", "parcel": "0784123456"}], idx)
    assert m.status == "AMBIGUOUS"


def test_f22_query_asks_every_identifier_field_and_row_column_is_restricted():
    c = cfg(alt_id_fields=("GEO_ID",))
    [url] = P.query_urls(c, "Wake", ["1"])
    where = parse_qs(urlsplit(url).query)["where"][0]
    assert "PARNO IN ('1')" in where and "GEO_ID IN ('1')" in where and " OR " in where
    with pytest.raises(ValueError):
        cfg(row_id_column="owner_name")
