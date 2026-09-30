"""harvesters/otc/adapters/arcgis.py - the generic ArcGIS layer adapter.

Fixtures only: no layer is configured anywhere in the repository and this
file never names a real endpoint. The hypothetical state used below is
registered for the duration of each test and unregistered again.
"""
from __future__ import annotations

import ast
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from harvesters.governance import states  # noqa: E402
from harvesters.governance.county_source_registry import CountySourceRow  # noqa: E402
from harvesters.governance.states import STATEWIDE_UNIT, PublishingUnit, StateConfig  # noqa: E402
from harvesters.otc import AmountKind, InventoryType, SourceAuthority  # noqa: E402
from harvesters.otc.adapters import ArcGisFieldMap, ArcGisLayerConfig, fetch_all  # noqa: E402
from harvesters.otc.adapters.arcgis import ArcGisError, parse_page, query_params, query_url  # noqa: E402
from harvesters.otc.gate import evaluate_source  # noqa: E402

T = datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)
LAYER = "https://gis.example.invalid/arcgis/rest/services/tax/FeatureServer/3"
ZZ = StateConfig(code="ZZ", name="Zetaland", publishing_units=(PublishingUnit.STATE.value, PublishingUnit.COUNTY.value),
                 production_inventory_types=frozenset({"STATE_HELD_TAX_LAND"}), lifecycle_inventory_type=None, production=False)


@pytest.fixture
def zz():
    with states.registered(ZZ):
        yield ZZ


def _cfg(**kw) -> ArcGisLayerConfig:
    base = dict(source_id="zz_state_land", state="ZZ", source_authority=SourceAuthority.GOVERNMENT_DIRECT,
                inventory_type=InventoryType.STATE_HELD_TAX_LAND, layer_url=LAYER,
                fields=ArcGisFieldMap(case_no="PARCEL_ID", parcel="PARCEL_ID", address="SITE_ADDR", amount="MIN_BID", status="STATUS"),
                county_field="COUNTY", amount_kind=AmountKind.MINIMUM_PURCHASE_AMOUNT, page_size=2)
    base.update(kw)
    return ArcGisLayerConfig(**base)


def _feat(pid, county="Alpha", amount=None, oid=1, **extra):
    a = {"PARCEL_ID": pid, "COUNTY": county, "SITE_ADDR": f"{oid} Main St", "MIN_BID": amount, "STATUS": "Available", "OBJECTID": oid}
    a.update(extra)
    return {"attributes": a}


def _page(features, more=False):
    return {"objectIdFieldName": "OBJECTID", "features": features, "exceededTransferLimit": more}


# ---------------------------------------------------------------- configuration


def test_c01_config_is_state_agnostic_but_requires_a_registered_state(zz):
    assert _cfg().state == "ZZ"
    with pytest.raises(ValueError, match="not a registered state"):
        _cfg(state="QQ")
    with pytest.raises(ValueError, match="two-letter"):
        _cfg(state="Zetaland")


def test_c02_config_rejects_bad_endpoint_county_and_paging(zz):
    with pytest.raises(ValueError, match="FeatureServer"):
        _cfg(layer_url="https://gis.example.invalid/arcgis/rest/services/tax/FeatureServer/3/query")
    with pytest.raises(ValueError, match="FeatureServer"):
        _cfg(layer_url="http://gis.example.invalid/arcgis/rest/services/tax/FeatureServer/3")
    with pytest.raises(ValueError, match="exactly one of county"):
        _cfg(county="Alpha")                       # both county and county_field
    with pytest.raises(ValueError, match="exactly one of county"):
        _cfg(county_field=None)                    # neither
    with pytest.raises(ValueError, match="positive"):
        _cfg(page_size=0)
    with pytest.raises(ValueError, match="where"):
        _cfg(where="  ")
    with pytest.raises(ValueError, match="go together"):
        _cfg(purchase_url="https://x.invalid/apply")
    assert _cfg(county="Alpha", county_field=None).county == "Alpha"


def test_c03_query_is_deterministic_geometry_free_and_ordered_by_identifier(zz):
    p = query_params(_cfg(), offset=4)
    assert p["returnGeometry"] == "false" and p["orderByFields"] == "PARCEL_ID" and p["f"] == "json"
    assert p["resultOffset"] == "4" and p["resultRecordCount"] == "2" and p["where"] == "1=1"
    assert p["outFields"].split(",") == ["PARCEL_ID", "SITE_ADDR", "MIN_BID", "STATUS", "COUNTY"]
    url = query_url(_cfg(where="STATUS = 'Available'"), offset=4)
    assert url.startswith(LAYER + "/query?") and "where=STATUS%20%3D%20%27Available%27" in url and "resultOffset=4" in url
    assert query_url(_cfg()) == query_url(_cfg())


# ---------------------------------------------------------------- parsing


def test_p01_features_become_records_with_endpoint_and_object_id_provenance(zz):
    page = parse_page(_cfg(), _page([_feat("P-1", amount=1500, oid=11), _feat("P-2", county="Beta", oid=12)]), retrieved_at=T)
    assert page.feature_count == 2 and not page.exceeded_transfer_limit and page.object_id_field == "OBJECTID"
    a, b = page.records
    assert (a.state, a.county, a.case_no, a.parcel) == ("ZZ", "Alpha", "P-1", "P-1")
    assert a.amount == 1500.0 and a.amount_kind is AmountKind.MINIMUM_PURCHASE_AMOUNT
    assert b.county == "Beta" and b.amount is None and b.amount_kind is AmountKind.NOT_PUBLISHED
    assert a.inventory_type is InventoryType.STATE_HELD_TAX_LAND and a.source_status_text == "Available"
    assert a.provenance["layer_url"] == LAYER and a.provenance["object_id"] == 11 and a.provenance["id_field"] == "PARCEL_ID"
    assert a.provenance["query_where"] == "1=1" and a.provenance["adapter"] == "arcgis"
    assert a.provenance["amount"] == "attribute 'MIN_BID' = MINIMUM_PURCHASE_AMOUNT" and b.provenance["amount"] == "no amount attribute value"
    assert a.validate() == [] and b.validate() == []
    assert a.list_as_of is None and a.source_published_at is None   # never stamped from retrieval


def test_p02_fixed_county_config_uses_it_for_every_feature(zz):
    page = parse_page(_cfg(county="Gamma", county_field=None), _page([_feat("P-1", county="IGNORED")]), retrieved_at=T)
    assert page.records[0].county == "Gamma"


def test_p03_error_payload_and_malformed_shapes_raise_never_zero(zz):
    cfg = _cfg()
    with pytest.raises(ArcGisError) as e:
        parse_page(cfg, {"error": {"code": 400, "message": "Invalid query"}}, retrieved_at=T)
    assert e.value.category == "SOURCE_ERROR" and "400" in e.value.detail
    for bad in ([], "html", {"rows": []}, {"features": "nope"}, {"features": [{"geometry": {}}]}):
        with pytest.raises(ArcGisError) as e:
            parse_page(cfg, bad, retrieved_at=T)
        assert e.value.category == "PARSE_FORMAT_CHANGE"
    with pytest.raises(ArcGisError, match="no 'PARCEL_ID' value"):
        parse_page(cfg, _page([_feat(None)]), retrieved_at=T)
    with pytest.raises(ArcGisError, match="no 'COUNTY' value"):
        parse_page(cfg, _page([_feat("P-1", county=None)]), retrieved_at=T)


def test_p04_an_amount_without_a_declared_kind_is_unspecified_not_invented(zz):
    page = parse_page(_cfg(amount_kind=AmountKind.NOT_PUBLISHED), _page([_feat("P-1", amount="$2,000.00")]), retrieved_at=T)
    assert page.records[0].amount == 2000.0 and page.records[0].amount_kind is AmountKind.PUBLISHED_AMOUNT_KIND_UNSPECIFIED
    page = parse_page(_cfg(), _page([_feat("P-1", amount=-5), _feat("P-2", amount="TBD")]), retrieved_at=T)
    assert all(r.amount is None and r.amount_kind is AmountKind.NOT_PUBLISHED for r in page.records)


# ---------------------------------------------------------------- fetch_all


class _Fetch:
    def __init__(self, pages):
        self.pages = list(pages)
        self.urls: list[str] = []

    def __call__(self, url):
        self.urls.append(url)
        item = self.pages.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def test_f01_pagination_follows_exceeded_transfer_limit_and_is_complete(zz):
    f = _Fetch([_page([_feat("P-1", oid=1), _feat("P-2", oid=2)], more=True),
                _page([_feat("P-3", oid=3), _feat("P-4", oid=4)], more=True),
                _page([_feat("P-5", oid=5)])])
    res = fetch_all(_cfg(), f, retrieved_at=T)
    assert res.outcome == "COMPLETE" and res.ok and res.pages == 3 and [r.case_no for r in res.records] == ["P-1", "P-2", "P-3", "P-4", "P-5"]
    assert ["resultOffset=0" in f.urls[0], "resultOffset=2" in f.urls[1], "resultOffset=4" in f.urls[2]] == [True, True, True]


def test_f02_zero_features_is_empty_only_when_the_layer_said_so(zz):
    res = fetch_all(_cfg(), _Fetch([_page([])]), retrieved_at=T)
    assert res.outcome == "EMPTY" and res.ok and res.records == [] and res.pages == 1


def test_f03_transport_failure_is_failed_with_no_records(zz):
    res = fetch_all(_cfg(), _Fetch([ConnectionError("proxy 403")]), retrieved_at=T)
    assert res.outcome == "FAILED" and not res.ok and res.records == [] and res.error_category == "TRANSPORT" and "403" in res.error_detail


def test_f04_a_failure_on_a_later_page_discards_the_earlier_pages(zz):
    f = _Fetch([_page([_feat("P-1")], more=True), {"error": {"code": 500, "message": "boom"}}])
    res = fetch_all(_cfg(), f, retrieved_at=T)
    assert res.outcome == "FAILED" and res.records == [] and res.error_category == "SOURCE_ERROR" and res.pages == 1
    f = _Fetch([_page([_feat("P-1")], more=True), "<html>maintenance</html>"])
    res = fetch_all(_cfg(), f, retrieved_at=T)
    assert res.outcome == "FAILED" and res.records == [] and res.error_category == "PARSE_FORMAT_CHANGE"


def test_f05_page_cap_and_unstable_paging_fail_closed(zz):
    endless = _Fetch([_page([_feat(f"P-{i}", oid=i)], more=True) for i in range(10)])
    res = fetch_all(_cfg(page_size=1, max_pages=3), endless, retrieved_at=T)
    assert res.outcome == "FAILED" and res.error_category == "PARSE_TRUNCATED" and res.records == [] and res.pages == 3
    dup = _Fetch([_page([_feat("P-1")], more=True), _page([_feat("P-1")])])
    res = fetch_all(_cfg(), dup, retrieved_at=T)
    assert res.outcome == "FAILED" and "twice" in res.error_detail and res.records == []


# ---------------------------------------------------------------- governance


def test_g01_module_never_fetches_and_nothing_is_configured():
    src = (REPO / "harvesters/otc/adapters/arcgis.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [a.name for a in node.names] + ([node.module] if isinstance(node, ast.ImportFrom) and node.module else [])
            for n in names:
                assert not n.startswith(("requests", "urllib", "http", "playwright", "socket")), n
    # No live endpoint anywhere in the generic adapters: every https URL in them is a doc example.
    # The state adapters (alabama.py, arkansas.py, louisiana.py, arizona.py) name their agencies'
    # pages in their evidence ledgers; their own tests pin those hosts exactly and nothing else.
    for path in (REPO / "harvesters/otc/adapters").glob("*.py"):
        # expansion.py (2026-09-30) is the owner-approved six-state configuration: its
        # hosts are pinned by tests/python/test_six_state_expansion.py.
        if path.name in ("alabama.py", "arkansas.py", "louisiana.py", "arizona.py", "expansion.py"):
            continue
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"https?://[^\s\"']*(\.gov|arcgis\.com)", text) and "mississippi" not in text.lower(), path.name


def test_g02_records_from_the_adapter_are_storable_only_while_the_constraint_allows_them(zz, monkeypatch):
    rec = parse_page(_cfg(), _page([_feat("P-1", amount=10)]), retrieved_at=T).records[0]
    assert rec.validate() == []
    # Migration 020 (applied 2026-09-30) made STATE_HELD_TAX_LAND storable.
    assert rec.to_properties_row()["inventory_type"] == "STATE_HELD_TAX_LAND"
    import harvesters.otc.model as model
    monkeypatch.setattr(model, "DB_SUPPORTED_INVENTORY_TYPES", model.DB_SUPPORTED_INVENTORY_TYPES - {"STATE_HELD_TAX_LAND"})
    with pytest.raises(ValueError, match="STATE_HELD_TAX_LAND is not storable"):
        rec.to_properties_row()


def test_g03_gate_still_refuses_a_search_evidence_state_level_source(zz):
    # A statewide ArcGIS layer found only in a search index: the registry
    # row validates structurally, and the run gate still says no.
    row = CountySourceRow(state="ZZ", county=STATEWIDE_UNIT, source_id="zz_state_land", harvester="", inventory_type="STATE_HELD_TAX_LAND",
                          source_authority="GOVERNMENT_DIRECT", canonical_url=LAYER, document_url="", purchase_url="", purchase_url_kind="",
                          access_method="JSON_ENDPOINT", machine_format="JSON", verification_status="SEARCH_EVIDENCE_ONLY",
                          governance_status="TERMS_NOT_VERIFIED", last_checked="2026-09-29", completeness_status="UNKNOWN",
                          evidence_ref="fixture", notes="", publishing_unit="STATE")
    d = evaluate_source(row)
    assert d.allowed is False and d.layer == "state_activation"    # refused before the row is even read
