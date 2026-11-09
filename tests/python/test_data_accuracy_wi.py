"""Wisconsin data-accuracy fixes (2026-11-09). Synthetic fixtures only.

WI-2  a parcel Dane lists twice keeps its LATEST offering (Bid Due / bid);
WI-3  an unchanged row-level path keeps its stored observed date, so the
      sync stops rewriting the row (and alerting watchers) every day;
WI-4  a source read from several tables records ONE unit verdict: the worst
      read and the unit's distinct listings (not the last table's count);
WI-6  an unscoped Census geocode writes its coordinate provenance too.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(1, str(REPO / "scripts"))

from harvesters.otc.adapters import expansion as EX  # noqa: E402
from harvesters.otc.adapters.tabular import TabularListAdapter  # noqa: E402
import harvest_expansion as HX  # noqa: E402
import sync_state_inventory as SY  # noqa: E402

T = datetime(2026, 11, 7, 11, 0, tzinfo=timezone.utc)

ROW = ('<tr><td>SYNTHETIC (TOWN)</td><td>{parcel}</td><td>{due} 1:00 PM</td><td>${bid}</td>'
       '<td><a href="/TaxDeedAuction/Detail/{n}">View Parcel Details</a> '
       '<a href="/TaxDeedAuction/BidForm/{n}">Bid Form</a></td></tr>')
SOLD = ('<tr><td>SYNTHETIC (TOWN)</td><td>{parcel}</td><td>{due} 1:00 PM</td><td>$900.00 SOLD - $1500.00</td>'
        '<td><a href="/TaxDeedAuction/Detail/{n}">View Parcel Details</a></td></tr>')
HEAD = '<thead><tr><th>Address</th><th>Parcel Number</th><th>Bid Due</th><th>Minimum Bid</th><th></th></tr></thead>'


def dane_page(current, sold=()):
    cur = "".join(ROW.format(parcel=p, due=d, bid=b, n=i) for i, (p, d, b) in enumerate(current, 1))
    sld = "".join(SOLD.format(parcel=p, due=d, n=100 + i) for i, (p, d) in enumerate(sold, 1))
    return (f'<html><body><table id="tblAuction" class="table">{HEAD}<tbody>{cur}</tbody></table>'
            f'<table id="tblAuctionSold" class="table">{HEAD}<tbody>{sld}</tbody></table></body></html>')


# ---------------------------------------------------------------- WI-2
def test_wi2_a_repeat_within_one_table_keeps_the_latest_offering():
    html = dane_page([("0000-000-0009-0", "6/2/2026", "4000.00"),       # the older offering, listed first
                      ("0000-000-0001-0", "10/6/2026", "12500.00"),
                      ("0000-000-0009-0", "10/6/2026", "3000.00")])     # the re-offering
    recs = TabularListAdapter(EX.WI_DANE_AVAILABLE).parse_html_table(html, retrieved_at=T)
    out, dropped = HX.dedupe(recs, latest_sale=True)
    assert dropped == 1
    assert [r.case_no for r in out] == ["0000-000-0009-0", "0000-000-0001-0"]   # first-listing position kept
    assert (out[0].sale_date, out[0].amount) == (date(2026, 10, 6), 3000.0)


def test_wi2_identical_or_undated_repeats_and_cross_table_dedupe_keep_the_first():
    a = SimpleNamespace(county="C", record_source="auction", case_no="1", sale_date=None, tag="first")
    b = SimpleNamespace(county="C", record_source="auction", case_no="1", sale_date=None, tag="second")
    assert [r.tag for r in HX.dedupe([a, b], latest_sale=True)[0]] == ["first"]
    old = SimpleNamespace(county="C", record_source="auction", case_no="2", sale_date=date(2026, 6, 2), tag="old")
    new = SimpleNamespace(county="C", record_source="auction", case_no="2", sale_date=date(2026, 10, 6), tag="new")
    # An earlier-dated repeat never displaces the kept row.
    assert [r.tag for r in HX.dedupe([new, old], latest_sale=True)[0]] == ["new"]
    # Across tables (the default) the first listing wins: current list before previous sales.
    assert [r.tag for r in HX.dedupe([old, new])[0]] == ["old"]


# ---------------------------------------------------------------- WI-4
def _cfg(sid):
    return SimpleNamespace(source_id=sid, county="Dane")


def test_wi4_tables_of_one_source_record_one_unit_verdict():
    cur, sold = _cfg("s"), _cfg("s")
    combined = HX.combine_unit_results([(cur, "COMPLETE", 16, None, None, None, "u1"),
                                        (sold, "COMPLETE", 135, None, None, None, "u2")],
                                       {("Dane", "s"): 151}, "Dane")
    assert [(c[1], c[2], c[6]) for c in combined] == [("COMPLETE", 151, "u1")]
    # Green WI: the current list read EMPTY, previous sales COMPLETE.
    g = HX.combine_unit_results([(_cfg("g"), "COMPLETE", 0, None, None, "empty_statement", "u"),
                                 (_cfg("g"), "COMPLETE", 9, None, None, None, "u")], {("Dane", "g"): 9}, "Dane")
    assert [(c[1], c[2]) for c in g] == [("COMPLETE", 9)]
    # One failed table makes the unit FAILED, whatever the other read.
    f = HX.combine_unit_results([(_cfg("s"), "COMPLETE", 16, None, None, None, "u1"),
                                 (_cfg("s"), "FAILED", 0, "TRANSPORT_CONNECTION", "ConnectionError", None, "u2")],
                                {("Dane", "s"): 16}, "Dane")
    assert [(c[1], c[3]) for c in f] == [("FAILED", "TRANSPORT_CONNECTION")]
    # Different sources of one county stay separate entries.
    two = HX.combine_unit_results([(_cfg("a"), "COMPLETE", 3, None, None, None, "u"),
                                   (_cfg("b"), "FAILED", 0, "UNKNOWN", "x", None, "u")], {("Dane", "a"): 3}, "Dane")
    assert [(c[0].source_id, c[1]) for c in two] == [("a", "COMPLETE"), ("b", "FAILED")]


def test_wi4_the_harvest_status_file_counts_every_table_of_dane(tmp_path):
    html = dane_page([("0000-000-0001-0", "10/6/2026", "12500.00"), ("0000-000-0002-0", "10/6/2026", "800.00"),
                      ("0000-000-0002-0", "6/2/2026", "900.00")],
                     sold=[("0000-000-0003-0", "10/14/2025"), ("0000-000-0004-0", "10/14/2025")])
    fx = tmp_path / "dane.html"
    fx.write_text(html, encoding="utf-8")
    assert HX.main(["--state", "WI", "--fixture", f"wi_dane_tax_deed_auction={fx}", "--out-dir", str(tmp_path)]) == 0
    status = json.loads((tmp_path / "harvest_wi_status.json").read_text())
    entries = status["counties"] if isinstance(status, dict) else status
    dane = [e for e in entries if e["county"] == "Dane" and e.get("source_id") == "wi_dane_tax_deed_auction"]
    assert len(dane) == 1 and dane[0]["status"] == "COMPLETE" and dane[0]["row_count"] == 4
    rows = json.loads((tmp_path / "harvest_wi.json").read_text())
    rep = [r for r in rows if r.get("case_no") == "0000-000-0002-0"]
    assert len(rep) == 1 and str(rep[0].get("sale_date")) == "2026-10-06"


# ---------------------------------------------------------------- WI-3
def _path_row(observed, url="https://treasurer.danecounty.gov/TaxDeedAuction/BidForm/1"):
    return {"purchase_path_type": "direct_property_url", "purchase_path_scope": "property",
            "purchase_url": url, "purchase_url_kind": "bid_form",
            "purchase_path_evidence": "bid_form link published by the source on the list row",
            "purchase_path_observed_on": observed,
            "otc_provenance": {"adapter": "tabular", "purchase_path_observed_on": observed,
                               "acquisition": {"mode": "bid", "observed_on": observed}}}


def test_wi3_an_unchanged_path_keeps_its_stored_observed_date():
    row, stored = _path_row("2026-11-07"), _path_row("2026-11-06")
    assert SY.keep_stored_path_date(row, stored) is True
    assert row["purchase_path_observed_on"] == "2026-11-06"
    assert row["otc_provenance"]["purchase_path_observed_on"] == "2026-11-06"
    assert row["otc_provenance"]["acquisition"]["observed_on"] == "2026-11-06"


def test_wi3_a_changed_path_or_a_stored_row_without_a_date_takes_the_new_date():
    row = _path_row("2026-11-07", url="https://treasurer.danecounty.gov/TaxDeedAuction/BidForm/2")
    assert SY.keep_stored_path_date(row, _path_row("2026-11-06")) is False
    assert row["purchase_path_observed_on"] == "2026-11-07"
    row = _path_row("2026-11-07")
    assert SY.keep_stored_path_date(row, dict(_path_row("2026-11-06"), purchase_path_observed_on=None)) is False
    assert row["purchase_path_observed_on"] == "2026-11-07"
    assert SY.keep_stored_path_date(_path_row("2026-11-07"), None) is False


def test_wi3_the_sync_plan_keeps_the_stored_date_of_an_unchanged_path():
    def adapter_row(observed):
        row = {"state": "WI", "source": "auction", "source_id": "wi_dane_tax_deed_auction", "county": "Dane",
               "case_no": "SYN-1", "parcel": "SYN-1", "status": "active", "sale_date": "2026-12-01"}
        row.update(_path_row(observed))
        return row
    stored = dict(_path_row("2026-11-06"), harvester_source="wi_dane_tax_deed_auction", status="active")
    out, counts = SY.plan("WI", [adapter_row("2026-11-07")], SY.registry_rows("WI"), {"Dane": "COMPLETE"},
                          observed_at="2026-11-07T11:00:00+00:00", stored_rows={("auction", "Dane", "SYN-1"): stored})
    (row,) = out
    assert row["purchase_path_observed_on"] == "2026-11-06"
    assert row["otc_provenance"]["purchase_path_observed_on"] == "2026-11-06"
    assert counts.get("path_date_kept_unchanged_path") == 1


# ---------------------------------------------------------------- WI-6
@pytest.fixture
def geo(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://example.test")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "not-a-real-key")
    monkeypatch.delenv("GEOCODE_SOURCE_ID", raising=False)
    monkeypatch.delenv("GEOCODE_DRY_RUN", raising=False)
    monkeypatch.delenv("GEOCODE_CHECKPOINT", raising=False)
    monkeypatch.setattr("time.sleep", lambda *_: None)
    spec = importlib.util.spec_from_file_location("_wi_geo", REPO / "scripts/geocode_properties.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _Resp:
    def __init__(self, data):
        self._d, self.status_code, self.text = data, 200, ""

    def json(self):
        return self._d

    def raise_for_status(self):
        return None


def test_wi6_an_unscoped_geocode_writes_merged_coordinate_provenance(geo, monkeypatch):
    rows = [{"id": "w1", "address": "10 FIXTURE ST, MADISON", "county": "Dane", "state": "WI",
             "field_provenance": {"address": {"source": "county_list"}}}]
    census = [{"coordinates": {"x": -89.4, "y": 43.07}, "matchedAddress": "10 FIXTURE ST, MADISON, WI, 53703",
               "addressComponents": {"state": "WI"}, "geographies": {"Counties": [{"BASENAME": "Dane", "NAME": "Dane County"}]}}]
    fetches, patches = [], []

    def fake_get(url, params=None, headers=None, timeout=None):
        if "/rest/v1/properties" in url:
            fetches.append(dict(params or {}))
            return _Resp(rows if len(fetches) == 1 else [])
        return _Resp({"result": {"addressMatches": census}})

    def fake_patch(url, headers=None, json=None, timeout=None):
        patches.append(json)
        return _Resp({})
    monkeypatch.setattr(geo.requests, "get", fake_get)
    monkeypatch.setattr(geo.requests, "patch", fake_patch)
    geo.main()
    assert "field_provenance" in fetches[0]["select"].split(",")
    (body,) = patches
    assert (body["latitude"], body["longitude"]) == (43.07, -89.4)
    prov = body["field_provenance"]
    assert prov["address"] == {"source": "county_list"}                       # stored entries kept
    for col in ("latitude", "longitude"):
        assert prov[col]["source"] == "census_geocoder" and prov[col]["method"] == "DETERMINISTIC_GEOCODE"
        assert "house number not checked" in prov[col]["evidence"]
    from harvesters.sources import coordinates as C
    assert C.coordinate_provenance({"latitude": 1, "longitude": 1, "field_provenance": prov})["method"] == "DETERMINISTIC_GEOCODE"
