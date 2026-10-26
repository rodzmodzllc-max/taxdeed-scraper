"""LGBS records' own links (2026-10-25).

19 active Texas auction rows from tx_lgbs carried no link at all
(purchase_url, url_auction, document_url, list_url all NULL): harvest_lgbs()
dropped the two link fields the feed publishes per record - `county_sale_list`
(the county sale-list document; on every record with a sale date) and
`property_loc` (the record's online sale site) - and the sync had no column to
send them to. Both are now kept verbatim or not at all; nothing is composed.

Synthetic hosts and values only; no network.
"""
from __future__ import annotations

import importlib
import importlib.util
import json
import sys
import time
import urllib.request
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

SALE_LIST = "https://lists.example-counsel.test/County_Sale_list_SAMPLE_COUNTY_0001.pdf"
SALE_SITE = "https://sample.texas.example-auctions.test/index.cfm?RDR=1"


def _lgbs(**kw):
    rec = {"uid": "u1", "state": "TX", "status": "Scheduled for Auction", "county": "SAMPLE COUNTY",
           "account_nbr": "000111", "cause_nbr": "C-1", "sale_date_only": "2026-11-03", "minimum_bid": "1000",
           "value": "5000", "sale_notes": "LOT 1", "prop_address_one": "1 FIXTURE ST", "prop_city": "SAMPLE",
           "prop_zipcode": "75000", "geometry": {"coordinates": [-95.0, 30.0]}}
    rec.update(kw)
    return rec


class _Resp:
    def __init__(self, payload):
        self._b = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self._b


def _harvest(monkeypatch, records):
    th = importlib.import_module("harvesters.texas_harvester")
    payload = {"count": len(records), "next": None, "previous": None, "results": records}
    monkeypatch.setattr(urllib.request, "urlopen", lambda url, timeout=30, **k: _Resp(payload))
    monkeypatch.setattr(time, "sleep", lambda *_: None)
    return th.harvest_lgbs()


@pytest.mark.parametrize("status", ["Scheduled for Auction", "Scheduled for Online Auction"])
def test_record_keeps_its_published_sale_list_and_sale_site_verbatim(monkeypatch, status):
    r = _harvest(monkeypatch, [_lgbs(status=status, county_sale_list=SALE_LIST, property_loc=SALE_SITE)])[0]
    assert r.source == "auction" and r.sale_list_url == SALE_LIST
    assert r.auction_url == SALE_SITE and r.auction_url_kind == "county"


@pytest.mark.parametrize("loc", [
    "https://www.govease.com/auctions",                           # blocked vendor
    "https://liveauctions.govease.com/x/1/browsestandard",        # blocked vendor subdomain
    "https://auctionhouse.example.test",                          # bare homepage
    "https://auctionhouse.example.test/",                         # bare homepage
    "http://sample.texas.example-auctions.test/index.cfm?RDR=1",  # not https - never upgraded
    "not a url",
])
def test_sale_site_refused_when_blocked_bare_or_not_https(monkeypatch, loc):
    r = _harvest(monkeypatch, [_lgbs(county_sale_list=SALE_LIST, property_loc=loc)])[0]
    assert r.auction_url is None and r.auction_url_kind is None
    assert r.sale_list_url == SALE_LIST                    # the document is independent of the site


def test_record_without_links_gets_none(monkeypatch):
    r = _harvest(monkeypatch, [_lgbs(status="Available for Future Sale", sale_date_only=None)])[0]
    assert (r.auction_url, r.auction_url_kind, r.sale_list_url) == (None, None, None)
    r2 = _harvest(monkeypatch, [_lgbs(county_sale_list="http://lists.example-counsel.test/a.pdf")])[0]
    assert r2.sale_list_url is None


def test_blocked_hosts_are_the_vendor_part_of_the_purchase_path_refusals():
    th = importlib.import_module("harvesters.texas_harvester")
    import laft_purchase_paths as LPP
    assert set(th.LGBS_LINK_BLOCKED_HOSTS) == {"govease.com", "pbfcm.com", "mvbalaw.com", "ctsa.com"}
    assert set(th.LGBS_LINK_BLOCKED_HOSTS) <= set(LPP.UNTRUSTED_HOST_SUFFIXES)


def test_harvester_and_sync_compose_no_url():
    for path in ("harvesters/texas_harvester.py", "scripts/sync-texas-to-supabase.py"):
        src = (REPO / path).read_text(encoding="utf-8")
        assert "County_Sale_list" not in src and "taxsalesib" not in src, path


def _sync(monkeypatch, tmp_path, fixture):
    out = tmp_path / "out"
    out.mkdir()
    (out / "harvest_texas.json").write_text(json.dumps(fixture))
    spec = importlib.util.spec_from_file_location("sync_tx_links", str(REPO / "scripts" / "sync-texas-to-supabase.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "HERE", tmp_path)
    monkeypatch.setattr(mod, "JSON_PATH", out / "harvest_texas.json")
    monkeypatch.setenv("SUPABASE_URL", "http://example.invalid")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "test-fixture-not-a-real-key")
    posted = []

    class _R:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b""

    def _fake(req, timeout=60):
        posted.append(json.loads(req.data))
        return _R()

    monkeypatch.setattr(mod.urllib.request, "urlopen", _fake)
    mod.main()
    return [r for batch in posted for r in batch]


def test_sync_sends_sale_list_as_document_url_and_site_as_url_auction_only_when_present(monkeypatch, tmp_path):
    base = {"state": "TX", "auction_date": "2026-11-03", "min_bid": 100.0, "cad_market_value": 1000.0, "legal_description": None,
            "address": "1 A St", "latitude": None, "longitude": None, "harvester_source": "tx_lgbs", "source": "auction",
            "sale_status": "Scheduled for Auction"}
    fixture = [
        dict(base, account_number="L-1", county="Harris", cause_number="C-1", auction_url=SALE_SITE, auction_url_kind="county",
             sale_list_url=SALE_LIST),
        dict(base, account_number="L-2", county="Harris", cause_number="C-2", auction_url=None, auction_url_kind=None,
             sale_list_url=SALE_LIST),
        dict(base, account_number="L-3", county="Harris", cause_number="C-3", auction_url=None, auction_url_kind=None,
             sale_list_url=None),
        dict(base, account_number="L-4", county="Harris", cause_number="C-4", auction_url=None, auction_url_kind=None,
             sale_list_url="http://lists.example-counsel.test/a.pdf"),
    ]
    rows = {r["case_no"]: r for r in _sync(monkeypatch, tmp_path, fixture)}
    assert rows["L-1"]["document_url"] == SALE_LIST and rows["L-1"]["url_auction"] == SALE_SITE
    assert rows["L-1"]["url_auction_kind"] == "county"
    assert rows["L-2"]["document_url"] == SALE_LIST and "url_auction" not in rows["L-2"]
    for k in ("L-3", "L-4"):
        assert "document_url" not in rows[k] and "url_auction" not in rows[k]   # never an explicit null
