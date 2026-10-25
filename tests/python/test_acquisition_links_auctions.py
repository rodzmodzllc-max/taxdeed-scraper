"""Acquisition links for AUCTIONS and LIENS rows (2026-10-25).

Owner's rule: every property shown carries a path of acquisition - a link to
THAT property where the source publishes one, never a composed URL.

- York SC: the layer publishes its own per-parcel link (`URL`, York County's
  One Map parcel report for the row's TAXMAPID). The ArcGIS adapter keeps it
  only when it is https, on the configured host and carries the row's own
  identifier; it becomes url_auction kind 'property' and the list page stays
  in list_url. A rejected link falls back to the list page ('county').
- The publication gate accepts kind 'property' as a record-scoped path.
- RealAuction (FL / TX): url_auction stays the sale-day page the harvester
  itself fetches for the row's own AuctionDate (kind 'sale').
- Albany WY and LienHub: nothing is invented (no per-record link published /
  source unreadable) - pinned so a later change has to be deliberate.

Every fixture below is SYNTHETIC.
"""
from __future__ import annotations

import sys
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from harvesters.governance import publication_state as PS  # noqa: E402
from harvesters.otc.adapters import arcgis as A  # noqa: E402
from harvesters.otc.adapters import expansion as X  # noqa: E402
from test_publication_state_gate import ctx, row  # noqa: E402

NOW = datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc)
YORK_HOST = "maps.yorkcountygov.com"


def _link(taxmapid: str, host: str = YORK_HOST) -> str:
    return f"https://{host}/omlink/index.html?search=parcel&id={taxmapid}"


def _payload(*features: dict) -> dict:
    return {"objectIdFieldName": "OBJECTID",
            "features": [{"attributes": {"OBJECTID": i + 1, **f}} for i, f in enumerate(features)]}


# ---------------------------------------------------------------- York config

def test_york_reads_the_layers_own_per_parcel_link():
    assert X.SC_YORK.fields.record_url == "URL"
    assert X.SC_YORK.record_url_host == YORK_HOST
    assert "URL" in A._out_fields(X.SC_YORK)


def test_record_url_and_host_go_together():
    with pytest.raises(ValueError, match="record_url_host"):
        replace(X.SC_YORK, record_url_host=None)


# ------------------------------------------------------ record_link_problem

@pytest.mark.parametrize("url,why", [
    (_link("1234567890"), None),
    (_link("1234567890") + "#x", None),
    ("https://maps.yorkcountygov.com/parcel/1234567890", None),
    (None, "empty"),
    ("", "empty"),
    (_link("1234567890").replace("https://", "http://"), "not_https"),
    (_link("1234567890", host="evil.example.com"), "other_host"),
    ("https://user@maps.yorkcountygov.com/omlink/index.html?id=1234567890", "other_host"),
    (_link("9999999999"), "identifier_absent"),
    (_link("12345678901"), "identifier_absent"),          # a longer id is not this record
    ("https://maps.yorkcountygov.com/omlink/index.html", "identifier_absent"),
])
def test_record_link_problem(url, why):
    assert A.record_link_problem(url, YORK_HOST, ("1234567890", None)) == why


# ---------------------------------------------------------------- York parse

def test_york_row_carries_its_own_parcel_link_as_property():
    page = A.parse_page(X.SC_YORK, _payload({"TAXMAPID": "1234567890", "URL": _link("1234567890")}), retrieved_at=NOW)
    rec = page.records[0]
    assert rec.record_url == _link("1234567890")
    r = rec.to_properties_row()
    assert r["url_auction"] == _link("1234567890") and r["url_auction_kind"] == "property"
    assert r["list_url"] == X.SC_YORK.list_url
    assert "record_url" in r["otc_provenance"] and "record_url_rejected" not in r["otc_provenance"]
    assert rec.to_harvest_row()["record_url"] == _link("1234567890")


@pytest.mark.parametrize("url,why", [
    (None, "empty"),
    (_link("1234567890", host="evil.example.com"), "other_host"),
    (_link("5555555555"), "identifier_absent"),
])
def test_york_rejected_link_falls_back_to_the_list_page(url, why):
    page = A.parse_page(X.SC_YORK, _payload({"TAXMAPID": "1234567890", "URL": url}), retrieved_at=NOW)
    rec = page.records[0]
    assert rec.record_url is None
    r = rec.to_properties_row()
    assert r["url_auction"] == X.SC_YORK.list_url and r["url_auction_kind"] == "county"
    assert r["otc_provenance"]["record_url_rejected"] == why


def test_a_bad_link_never_fails_the_read():
    page = A.parse_page(X.SC_YORK, _payload({"TAXMAPID": "1", "URL": _link("1")}, {"TAXMAPID": "2", "URL": "not a url"}),
                        retrieved_at=NOW)
    assert [r.to_properties_row()["url_auction_kind"] for r in page.records] == ["property", "county"]


def test_record_url_must_not_be_the_list_page():
    rec = A.parse_page(X.SC_YORK, _payload({"TAXMAPID": "1", "URL": _link("1")}), retrieved_at=NOW).records[0]
    rec.record_url = rec.list_url
    assert "the list page is not a per-record link" in rec.validate()


# ------------------------------------------------------------ publication gate

def test_property_link_is_a_record_scoped_auction_path():
    d = PS.decide(row(url_auction=_link("111"), url_auction_kind="property"), ctx())
    assert d.state == "CUSTOMER_PUBLISHED"
    assert d.path.scope == "record" and d.path.path_type == "auction_bidding"
    assert d.path.destination_url == _link("111")


def test_info_kind_is_still_not_a_path():
    d = PS.decide(row(url_auction=_link("111"), url_auction_kind="info"), ctx())
    assert d.state == "ADMIN_ONLY_NO_PATH" and d.reasons == ["PATH_UNTRUSTED"]


# ----------------------------------------------- what stays as it is, pinned

def test_realauction_rows_keep_the_sale_day_page_they_were_read_from():
    ps1 = (ROOT / "scripts/harvest_all_counties.ps1").read_text(encoding="utf-8")
    # The same PREVIEW URL the harvester fetches for the row's own date (warm-up + Referer) ...
    assert ps1.count('"https://$hostName/index.cfm?zaction=AUCTION&zmethod=PREVIEW&AuctionDate=$date"') >= 2
    assert 'auction_url = "https://$hostName/index.cfm?zaction=AUCTION&zmethod=PREVIEW&AuctionDate=$date"' in ps1
    # ... stored as a sale-event link.
    sync = (ROOT / "scripts/sync-harvest-to-supabase.ps1").read_text(encoding="utf-8")
    assert "zaction=auction&zmethod=preview&auctiondate=" in sync and '"sale"' in sync


def test_albany_and_lienhub_get_no_invented_link():
    assert X.WY_ALBANY.fields.record_url is None and X.WY_ALBANY.record_url_host is None
    lienhub = (ROOT / "scripts/harvest_lienhub_certificates.ps1").read_text(encoding="utf-8")
    assert "url_auction     = $base" in lienhub
