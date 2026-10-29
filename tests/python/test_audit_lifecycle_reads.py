"""Audit B13 (2026-10-29): the Louisiana lifecycle read failed with HTTP 500
on every loaded laft run since 2026-10-26.

`fetch_state_rows` paged the county filter ORDER BY id with the wide columns
(otc_provenance, field_provenance ...) in the select, so each page made
Postgres detoast and sort every Louisiana row (2.3 s a page when quiet; past
the 8 s statement timeout under load). It now reads the identities narrow and
the wide columns by primary key in small batches; the sync's wide stored-row
read uses smaller pages.
"""
import sys
from pathlib import Path
from urllib.parse import parse_qs

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import laft_lifecycle as L  # noqa: E402
import sync_state_inventory as SYNC  # noqa: E402

WIDE = ("otc_provenance", "field_provenance")


class RecordingApi(L.Api):
    def __init__(self, rows):
        self.rows = rows
        self.queries = []

    def get(self, query):
        self.queries.append(query)
        q = parse_qs(query)
        data = sorted(self.rows, key=lambda r: r["id"])
        idq = q.get("id", [""])[0]
        if idq.startswith("in."):
            wanted = {int(v.strip('"')) for v in idq[4:-1].split(",")}
            data = [r for r in data if r["id"] in wanted]
        elif idq.startswith("gt."):
            data = [r for r in data if r["id"] > int(idq[3:])]
        limit = int(q.get("limit", ["1000"])[0])
        cols = q["select"][0].split(",")
        return [{c: r.get(c) for c in cols} for r in data[:limit]]


def _rows(n):
    return [{"id": i, "county": "East Baton Rouge", "case_no": f"C{i}", "status": "active" if i % 3 else "closed",
             "otc_provenance": {"k": i}, "field_provenance": {}} for i in range(1, n + 1)]


def test_no_paged_county_read_selects_the_wide_columns():
    api = RecordingApi(_rows(2500))
    L.fetch_state_rows(api, "LA", ["East Baton Rouge"], ("otc_provenance",))
    county_reads = [qq for qq in api.queries if "county=in." in qq]
    assert county_reads
    for qq in county_reads:
        sel = parse_qs(qq)["select"][0].split(",")
        assert not set(sel) & set(WIDE), sel


def test_wide_columns_are_read_by_id_in_small_batches_and_nothing_is_lost():
    api = RecordingApi(_rows(2500))
    rows = L.fetch_state_rows(api, "LA", ["East Baton Rouge"], ("otc_provenance",))
    assert sorted(r["id"] for r in rows) == list(range(1, 2501))
    assert all(r["otc_provenance"] == {"k": r["id"]} for r in rows)
    by_id = [qq for qq in api.queries if "id=in." in qq]
    assert len(by_id) == 25
    assert all(len(parse_qs(qq)["id"][0][4:-1].split(",")) <= L.WIDE_BATCH for qq in by_id)


def test_sync_wide_stored_read_pages_small(monkeypatch):
    seen = {}

    def fake_read_all(base, table, headers, params, *, page=1000, fetch=None, **retry):   # attempts / backoff (audit B43)
        seen["page"] = page
        return []

    monkeypatch.setattr(SYNC.RP, "read_all", fake_read_all)
    SYNC.stored_provenance("https://x.supabase.co", "k", "LA", {"la_ebr_adjudicated"}, full_out={})
    assert seen["page"] <= 250


# ------------------------------------------------ B18 / B38: inventory status

from datetime import date, datetime, timezone  # noqa: E402

sys.path.insert(1, str(ROOT))
from harvesters.governance import inventory_status as IS  # noqa: E402
from harvesters.otc.adapters import expansion as EX  # noqa: E402
from harvesters.otc.adapters.tabular import TabularListAdapter, published_sale_date  # noqa: E402

TODAY = date(2026, 10, 28)


def test_tax_sale_info_auction_rows_get_a_status():
    row = {"state": "MI", "source": "auction", "status": "active", "sale_date": "2026-10-30",
           "source_id": "mi_tax_sale_info_auction", "otc_provenance": {"adapter": "tax_sale_info"}}
    assert IS.status_for_row(row, today=TODAY).status == "upcoming"
    assert IS.status_for_row({**row, "sale_date": "2026-10-01"}, today=TODAY).status == "unknown"
    assert IS.status_for_row({**row, "status": "closed"}, today=TODAY).status == "closed"   # absence is never a sale


def test_texas_vendor_auction_rows_get_a_status():
    for sid in ("tx_pbfcm", "tx_mvba", "tx_govease"):
        row = {"state": "TX", "source": "auction", "status": "active", "source_id": sid}
        assert IS.status_for_row({**row, "sale_date": "2026-11-03"}, today=TODAY).status == "upcoming"
        assert IS.status_for_row(row, today=TODAY).status == "active"            # no published date
        assert IS.status_for_row({**row, "status": "closed"}, today=TODAY).status == "closed"


# ------------------------------------- B22: SC sale dates the counties publish

def _sc_row_html(id_label, ids, extra_cols):
    head = "".join(f"<th>{c}</th>" for c in (id_label, *extra_cols))
    body = "".join("<tr>" + f"<td>{i}</td>" + "".join("<td>x</td>" for _ in extra_cols) + "</tr>" for i in ids)
    return f"<table><tr>{head}</tr>{body}</table>"


def test_oconee_rows_carry_the_county_published_sale_date():
    html = _sc_row_html("Map Number", ["123-45-67-890", "123-45-67-891"], ("Item Number", "Owner Name", "Description",
                                                                            "Total Tax Due"))
    recs = TabularListAdapter(EX.SC_OCONEE).parse_html_table(html, retrieved_at=datetime(2026, 10, 29, tzinfo=timezone.utc))
    assert len(recs) == 2
    assert {r.sale_date for r in recs} == {date(2026, 11, 9)}
    assert all("published sale date" in r.provenance["sale_date"] for r in recs)


def test_horry_config_publishes_its_december_sale_date():
    assert published_sale_date(EX.SC_HORRY_TAX_SALE, datetime(2026, 10, 29, tzinfo=timezone.utc)) == date(2026, 12, 1)


def test_a_stale_published_sale_date_never_dates_a_later_list():
    assert published_sale_date(EX.SC_OCONEE, datetime(2027, 3, 1, tzinfo=timezone.utc)) is None


# ------------------------------------- B39: a source's repeats are one listing

import json  # noqa: E402

import harvest_expansion as HX  # noqa: E402


def test_status_row_count_is_the_distinct_listings_of_a_source(tmp_path):
    cols = ("Tax Deed #", "Auction Date", "Property Tax Acct #", "Tax Lien Sale Cert #", "Property Description and Address")
    rows = [(f"202600{i}", "11/18/2026", f"R00{i}", f"2023-0{i}", "SYNTHETIC") for i in range(1, 8)]
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows * 15)   # 105 rows, 7 distinct
    page = tmp_path / "morgan.html"
    page.write_text("<table><tr>" + "".join(f"<th>{c}</th>" for c in cols) + "</tr>" + body + "</table>")
    out = tmp_path / "out"
    assert HX.main(["--state", "CO", "--out-dir", str(out), "--fixture", f"co_morgan_treasurer_deed_auctions={page}"]) == 0
    status = json.loads((out / "harvest_co_status.json").read_text())
    entries = status.get("counties") if isinstance(status, dict) else status
    entries = list(entries.values()) if isinstance(entries, dict) else entries
    counts = [e.get("row_count") for e in entries if e.get("source_id") == "co_morgan_treasurer_deed_auctions"]
    assert counts == [7]
    assert len(json.loads((out / "co_properties_rows.json").read_text())) == 7


# --------------------- F38: Dane parcels still on the available table after Bid Due

def test_dane_row_still_listed_after_its_bid_due_reads_active():
    row = {"state": "WI", "source": "auction", "status": "active", "sale_date": "2026-10-06",
           "source_id": "wi_dane_tax_deed_auction", "otc_provenance": {"adapter": "tabular"}}
    assert IS.status_for_row(row, today=TODAY).status == "active"
    # Off the table it is closed; with the county's SOLD wording, sold.
    assert IS.status_for_row({**row, "status": "closed"}, today=TODAY).status == "closed"
    # Every other list keeps 'unknown' for a passed sale day.
    other = {**row, "source_id": "mi_lenawee_tax_sale", "otc_provenance": {"adapter": "arcgis"}}
    assert IS.status_for_row(other, today=TODAY).status == "unknown"


# ------------------- F78: a verified result observed after the Waiting read wins

import auction_outcome_status as AOS  # noqa: E402
import auction_outcomes as AO  # noqa: E402


def test_result_observed_after_the_waiting_read_moves_the_row():
    harvested = {"Orange": {AO.norm_id("2024 TD 8")}}
    prop = {"id": "p1", "status": "active", "sale_date": "2026-11-19", "county": "Orange", "case_no": "2024 TD 8"}
    ev = {"id": "e1", "property_id": "p1", "scheduled_sale_date": "2026-11-19", "outcome": "redeemed",
          "lifecycle": "cancelled", "outcome_raw": "Redeemed", "outcome_observed_at": "2026-10-28T16:43:37+00:00"}
    read = datetime(2026, 10, 28, 16, 36, 13, tzinfo=timezone.utc)
    changes, counts = AOS.plan([ev], [prop], harvested=harvested, harvest_read_at=read)
    assert changes == [("p1", "active", "closed")] and counts["result_after_waiting_read"] == 1
    # A result observed BEFORE this run's Waiting read is older than the listing: the row stays.
    old = {**ev, "outcome_observed_at": "2026-10-28T10:00:00+00:00"}
    changes, counts = AOS.plan([old], [prop], harvested=harvested, harvest_read_at=read)
    assert changes == [] and counts["still_on_waiting_list"] == 1
    # No harvest time known: fail closed, as before.
    assert AOS.plan([ev], [prop], harvested=harvested)[0] == []
