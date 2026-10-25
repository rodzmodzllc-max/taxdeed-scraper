"""Layer queries survive a host that rejects some GET query strings, and one
failed batch no longer discards a whole county.

Found 2026-10-25: Detroit's parcel layer answered HTTP 404 to 2 of 10 GET
batches, every time, and 10 of 10 as POST. The factory stopped at the first
failed batch, so 30,549 Wayne County rows got nothing."""
from __future__ import annotations

import dataclasses
import io
import urllib.error
from urllib.parse import parse_qs

import pytest

from harvesters.enrichment import geocode as G
from harvesters.enrichment import parcels as P
from scripts import enrich_statewide_parcels as R

SQUARE = {"rings": [[[-105.0, 40.0], [-104.99, 40.0], [-104.99, 40.01], [-105.0, 40.01], [-105.0, 40.0]]]}


@pytest.fixture(autouse=True)
def _fixture_layers_hold_permission(monkeypatch):
    from permission_fixtures import allow_fixture_layers
    allow_fixture_layers(monkeypatch, P, {"xx_parcels"})


def cfg(**kw):
    base = dict(source_id="xx_parcels", state="NC", agency="Agency", dataset="Parcels",
                landing_url="https://example.gov/parcels", layer_url="https://example.gov/arcgis/rest/services/P/FeatureServer/1",
                id_field="PARNO", id_rule="exact", field_map={"land_value": "LANDVAL"},
                licence="free to use by anyone without restriction", publication_status="APPROVED",
                centroid=False, columns_verified=True, batch_size=2)
    base.update(kw)
    return P.ParcelSourceConfig(**base)


def asked(url: str) -> set[str]:
    where = parse_qs(url.split("?", 1)[1])["where"][0]
    return {x.strip().strip("'") for x in where.split("(", 1)[1].rstrip(")").split(",")}


# --- POST form -----------------------------------------------------------------
def test_post_form_only_for_arcgis_query_urls():
    url = P.query_urls(cfg(), "Wake", ["A1"])[0]
    endpoint, body = P.post_form(url)
    assert endpoint == "https://example.gov/arcgis/rest/services/P/FeatureServer/1/query"
    assert parse_qs(body.decode())["where"] == ["PARNO IN ('A1')"]
    soc = P.query_urls(cfg(transport="socrata", layer_url="https://data.example.gov/resource/abcd-1234.json"), "Wake", ["A1"])[0]
    assert P.post_form(soc) is None
    assert P.post_form("https://example.gov/arcgis/rest/services/P/FeatureServer/1?f=json") is None


def test_query_batches_carry_their_keys_and_query_urls_is_unchanged():
    c = cfg()
    batches = P.query_batches(c, "Wake", ["B2", " A1 ", "C3", "", None, "A1"])
    assert [sorted(k) for _, k in batches] == [["A1", "B2"], ["C3"]]
    assert [u for u, _ in batches] == P.query_urls(c, "Wake", ["B2", "A1", "C3"])
    for url, keys in batches:
        assert asked(url) == set(keys)
    num = cfg(id_rule="numeric", id_query="number")
    assert P.batch_key(num, "00123") == "123" and P.batch_key(num, "abc") is None and P.batch_key(c, "  ") is None


# --- query_json: POST, retries ---------------------------------------------------
def _http_error(code):
    return urllib.error.HTTPError("https://x", code, "err", {}, io.BytesIO(b""))


def test_query_json_posts_arcgis_queries_and_retries_transient_failures():
    url = P.query_urls(cfg(), "Wake", ["A1"])[0]
    calls, sleeps = [], []
    answers = [_http_error(503), urllib.error.URLError("reset"), {"features": []}]

    def http(u, **kw):
        calls.append((u, kw.get("method"), kw.get("body")))
        a = answers.pop(0)
        if isinstance(a, Exception):
            raise a
        return a

    assert R.query_json(url, http=http, sleep=sleeps.append) == {"features": []}
    assert len(calls) == 3 and all(m == "POST" and u.endswith("/query") and b for u, m, b in calls)
    assert sleeps == [2.0, 4.0]


def test_query_json_does_not_retry_a_client_error_and_gives_up_after_attempts():
    url = P.query_urls(cfg(), "Wake", ["A1"])[0]
    n = []

    def not_found(u, **kw):
        n.append(1)
        raise _http_error(404)

    with pytest.raises(urllib.error.HTTPError):
        R.query_json(url, http=not_found, sleep=lambda s: None)
    assert len(n) == 1

    def down(u, **kw):
        n.append(1)
        raise urllib.error.URLError("down")

    n.clear()
    with pytest.raises(urllib.error.URLError):
        R.query_json(url, http=down, sleep=lambda s: None)
    assert len(n) == 3


def test_query_json_gets_a_non_arcgis_url():
    seen = []
    R.query_json("https://data.example.gov/resource/abcd-1234.json?%24where=x", http=lambda u, **kw: seen.append(kw) or [])
    assert seen == [{}]


# --- one failed batch withholds only its own rows ------------------------------------
def test_runner_withholds_only_the_rows_of_a_failed_batch(monkeypatch):
    from harvesters.enrichment import sources as S
    c = cfg(state="ZZ")
    monkeypatch.setitem(S.PARCEL_SOURCES, "ZZ", c)
    rows = [{"id": i, "county": "Wake", "parcel": p, "land_value": None, "field_provenance": None}
            for i, p in (("a", "A1"), ("b", "B2"), ("c", "C3"), ("d", "D4"), ("e", "E5"))]

    def fetch(url):
        keys = asked(url)
        if "C3" in keys:                      # the second batch (C3, D4) fails
            raise urllib.error.HTTPError(url, 404, "nf", {}, io.BytesIO(b""))
        return {"features": [{"attributes": {"PARNO": k, "LANDVAL": 100}} for k in keys]}

    outcomes, writes = {}, {}
    rep = R.run("ZZ", rows, fetch, write=lambda i, f: writes.setdefault(i, f), recorded_at="t", outcomes=outcomes)
    assert rep["failed_queries"] == 1 and rep["matched"] == 3 and rep["rows_considered"] == 5
    assert set(writes) == {"a", "b", "e"}
    assert outcomes == {"a": "MATCHED", "b": "MATCHED", "c": "SOURCE_UNAVAILABLE", "d": "SOURCE_UNAVAILABLE", "e": "MATCHED"}
    # an error object is a failed batch too
    rep = R.run("ZZ", rows, lambda u: {"error": {"code": 500}}, write=lambda i, f: 1 / 0, recorded_at="t")
    assert rep["failed_queries"] == 3 and rep["rows_written"] == 0 and rep["matched"] == 0


def test_geocode_lookup_withholds_only_the_rows_of_a_failed_batch():
    src = next(s for s in G.coordinate_sources() if s.source_id == "co_oit_public_parcels")
    src = dataclasses.replace(src, parcel_cfg=dataclasses.replace(src.parcel_cfg, batch_size=1))
    rows = [{"id": i, "state": "CO", "county": "Morgan", "ledger_type": "lien", "parcel": p, "source": "certificate"}
            for i, p in (("a", "R001"), ("b", "R002"), ("c", "R003"))]

    def fetch(url):
        if "R002" in url:
            raise urllib.error.URLError("down")
        if "R003" in url:
            raise ValueError("not json")
        return {"features": [{"attributes": {"account": "R001", "countyName": "MORGAN"}, "geometry": SQUARE}]}

    out = G.lookup_parcel_layer(src, rows, fetch)
    assert out["a"].status == "MATCHED"
    assert out["b"].status == "SOURCE_UNAVAILABLE" and out["c"].status == "PARSER_FAILURE"


def test_every_layer_caller_uses_the_one_query_function():
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[2]
    assert "ESP.query_json(url)" in (root / "scripts/enrich_available.py").read_text()
    assert "ESP.query_json(url)" in (root / "scripts/geocode_authoritative.py").read_text()
    assert "return query_json(url)" in (root / "scripts/enrich_statewide_parcels.py").read_text()
