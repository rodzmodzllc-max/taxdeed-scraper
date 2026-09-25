"""Phase 72 - auction-link provenance (url_auction_kind, tx_sale_status).

The 2026-09-24 read-only audit found every Texas row with every url_* column
empty, while harvest_realauction() built and fetched the county's sale-date
preview page for every row and threw it away; and found that url_auction had
never said WHAT it points at (a sale-event page, a county list, a property
notice), so the UI over-labelled all of them.

Contract under test:
  - migration 013 adds url_auction_kind (checked vocabulary) and tx_sale_status,
    grants them, appends both to get_properties(), backfills existing kinds by
    the writers' own behaviour, and writes the Texas RealAuction sale URL from
    the harvester's own county roster - never for LGBS rows;
  - harvest_realauction() stores the preview URL it fetched, kind 'sale';
  - harvest_lgbs() keeps the vendor's raw status verbatim and stores no URL;
  - sync-texas-to-supabase.py sends url_auction + url_auction_kind only
    together and only when present, sends tx_sale_status only when present,
    and batches by exact key set; an LGBS row can never receive a link.

No network and no database: every fetch is replaced.
"""
from __future__ import annotations

import csv
import importlib
import importlib.util
import json
import pathlib
import sys
import time
import urllib.request

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

MIGRATION = REPO / "scripts" / "migrations" / "013_auction_link_kind_and_tx_sale_status.sql"
SQL = MIGRATION.read_text(encoding="utf-8")
ROSTER = REPO / "data" / "tx_realauction_counties.csv"


def sql_only() -> str:
    return "\n".join(l for l in SQL.splitlines() if not l.strip().startswith("--"))


# ---------------------------------------------------------------------------
# Migration 013
# ---------------------------------------------------------------------------

def test_m01_adds_both_columns_nullable():
    s = sql_only()
    assert "add column if not exists url_auction_kind text" in s
    assert "add column if not exists tx_sale_status text" in s
    assert "not null" not in s.split("alter table public.properties")[1].split("alter table", 1)[0]


def test_m02_kind_vocabulary_is_checked_and_null_allowed():
    s = sql_only()
    assert "check (url_auction_kind is null or url_auction_kind in ('property', 'sale', 'county', 'info'))" in s


def test_m03_both_columns_are_granted_before_the_function_is_recreated():
    s = sql_only()
    grant = s.index("grant select (url_auction_kind, tx_sale_status) on public.properties to authenticated")
    create = s.index("create function public.get_properties(")
    assert grant < create


def test_m04_function_is_dropped_by_exact_signature_then_recreated_with_both_columns():
    s = sql_only()
    drop = s.index("drop function if exists public.get_properties(text, text, text, integer, integer)")
    create = s.index("create function public.get_properties(")
    assert drop < create
    returns = s.split("returns table (")[1].split(")\nlanguage sql")[0]
    assert "url_auction_kind text" in returns and "tx_sale_status text" in returns
    select = s.split("as $function$")[1].split("from public.properties")[0]
    assert "url_auction_kind, tx_sale_status" in select


def test_m05_where_order_limit_offset_unchanged_and_execute_regranted():
    s = sql_only()
    assert "where state = p_state" in s
    assert "and (p_ledger_type is null or ledger_type = p_ledger_type)" in s
    assert "and (p_status is null or status = p_status)" in s
    assert "order by county, case_no" in s
    assert "grant execute on function public.get_properties(text, text, text, integer, integer)" in s
    assert "to anon, authenticated, service_role" in s


def test_m06_backfill_never_touches_lgbs_and_never_invents_a_url_for_it():
    s = sql_only()
    assert "tx_lgbs" not in s
    assert "lgbs.com" not in s


def test_m07_existing_kind_backfill_is_by_url_meaning_and_only_where_a_url_exists():
    s = sql_only()
    assert "when url_auction ~* 'zaction=auction&zmethod=preview&auctiondate=' then 'sale'" in s
    assert "notices\\.collierclerk\\.com/notice/' then 'property'" in s
    assert "else 'county'" in s
    assert "where nullif(url_auction, '') is not null\n  and url_auction_kind is null" in s


def test_m08_texas_sale_url_backfill_is_scoped_to_realauction_rows_with_a_sale_date_and_no_url():
    s = sql_only()
    assert "p.harvester_source = 'tx_realauction'" in s
    assert "p.sale_date is not null" in s
    assert "nullif(p.url_auction, '') is null" in s
    assert "url_auction_kind = 'sale'" in s
    assert "to_char(p.sale_date, 'MM/DD/YYYY')" in s
    assert "/index.cfm?zaction=AUCTION&zmethod=PREVIEW&AuctionDate=" in s


def test_m09_texas_host_roster_in_migration_matches_the_harvester_csv_exactly():
    with open(ROSTER, newline="", encoding="utf-8") as f:
        roster = {(r["County"], r["Host"]) for r in csv.DictReader(f)}
    assert len(roster) == 24
    values = sql_only().split("with tx_hosts(county, host) as (")[1].split(")\nupdate public.properties p")[0]
    in_sql = set()
    for line in values.splitlines():
        line = line.strip().rstrip(",")
        if line.startswith("('"):
            county, host = [x.strip().strip("'") for x in line.strip("()").split(",")]
            in_sql.add((county, host))
    assert in_sql == roster


def test_m10_tx_sale_status_is_not_backfilled_and_the_reason_is_recorded():
    assert "tx_sale_status is NOT backfilled" in SQL
    s = sql_only()
    assert "set tx_sale_status" not in s


def test_m11_transactional_and_non_destructive():
    s = sql_only()
    assert s.strip().startswith("begin;") and s.strip().endswith("commit;")
    for bad in ("drop table", "drop column", "truncate", "delete from"):
        assert bad not in s


# ---------------------------------------------------------------------------
# harvest_realauction(): the sale-event page it fetched, kind 'sale'
# ---------------------------------------------------------------------------

CAL_HTML = "<td class='CALSELT' dayid='10/06/2026'>6</td>"
ITEM = (
    "AITEM_1 Sale Type:@F CAD_DTA\\\">@ "
    "Cause Number:@F CAD_DTA\\\">2021DCV-4034-H (5)@ "
    "Account Number:@F CAD_DTA\\\">9377-0051-0100@ "
    "Adjudged Value:@F CAD_DTA\\\">$25,000.00@ "
    "Est. Min. Bid:@F CAD_DTA\\\">$21,800.00@ "
    "Property Address:@F CAD_DTA\\\">4013 TILDEN ST@"
)


class _Resp:
    def __init__(self, text):
        self._b = text.encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self._b


class _FakeOpener:
    def __init__(self, log):
        self.log = log

    def open(self, req, timeout=25):
        url = req.full_url
        self.log.append(url)
        if "zmethod=calendar" in url:
            return _Resp(CAL_HTML)
        if "zmethod=PREVIEW" in url:
            return _Resp("<html>preview</html>")
        if "Zmethod=UPDATE" in url:
            return _Resp(ITEM if "PageDir=0" in url else "")
        raise AssertionError(f"unexpected fetch {url}")


def test_r01_realauction_row_carries_the_fetched_preview_url_as_a_sale_link(monkeypatch, tmp_path):
    th = importlib.import_module("harvesters.texas_harvester")
    roster = tmp_path / "roster.csv"
    roster.write_text("County,Host\nNueces,nueces.texas.sheriffsaleauctions.com\n")
    monkeypatch.setattr(th, "REALAUCTION_COUNTIES_CSV", roster)
    fetched: list[str] = []
    monkeypatch.setattr(urllib.request, "build_opener", lambda *handlers: _FakeOpener(fetched))
    monkeypatch.setattr(time, "sleep", lambda *_: None)

    rows = th.harvest_realauction()

    assert len(rows) == 1
    row = rows[0]
    expected = "https://nueces.texas.sheriffsaleauctions.com/index.cfm?zaction=AUCTION&zmethod=PREVIEW&AuctionDate=10/06/2026"
    assert row.auction_url == expected
    assert row.auction_url_kind == "sale"
    assert row.auction_date == "2026-10-06"
    assert row.account_number == "9377-0051-0100" and row.cause_number == "2021DCV-4034-H (5)"
    assert row.sale_status is None
    # The URL stored is one the harvester really requested, not composed after the fact.
    assert expected in fetched


# ---------------------------------------------------------------------------
# harvest_lgbs(): raw status kept verbatim, no URL ever
# ---------------------------------------------------------------------------

def _lgbs_payload(status):
    return {
        "count": 1, "next": None, "previous": None,
        "results": [{
            "state": "TX", "status": status, "county": "GALVESTON COUNTY",
            "account_nbr": "129500040015000", "cause_nbr": "23-TX-0644",
            "sale_date_only": None, "minimum_bid": "4451.95", "value": "12000",
            "sale_notes": "LOT 1", "prop_address_one": "VACANT LOT", "prop_city": "HITCHCOCK",
            "prop_zipcode": "77563", "geometry": {"coordinates": [-95.0, 29.3]},
        }],
    }


@pytest.mark.parametrize("status,ledger", [
    ("Scheduled for Online Auction", "auction"),
    ("Scheduled for Auction", "auction"),
    ("Available for Future Sale", "laft"),
    ("Struck off to Jurisdiction", "laft"),
])
def test_l01_lgbs_keeps_raw_status_and_writes_no_link(monkeypatch, status, ledger):
    th = importlib.import_module("harvesters.texas_harvester")
    monkeypatch.setattr(urllib.request, "urlopen", lambda url, timeout=30: _Resp(json.dumps(_lgbs_payload(status))))
    monkeypatch.setattr(time, "sleep", lambda *_: None)
    rows = th.harvest_lgbs()
    assert len(rows) == 1
    assert rows[0].sale_status == status
    assert rows[0].source == ledger
    assert rows[0].auction_url is None and rows[0].auction_url_kind is None


def test_l02_lineage_map_covers_the_three_new_fields_and_says_lgbs_has_no_url():
    from dataclasses import fields
    th = importlib.import_module("harvesters.texas_harvester")
    # state/harvester_source are constants, not source fields - the existing
    # provenance test excludes them the same way.
    names = {f.name for f in fields(th.TexasSaleRow)} - {"state", "harvester_source"}
    for source in ("tx_lgbs", "tx_realauction"):
        assert names <= set(th.FIELD_LINEAGE_MAP[source])
    assert th.FIELD_LINEAGE_MAP["tx_lgbs"]["auction_url"] is None
    assert th.FIELD_LINEAGE_MAP["tx_lgbs"]["auction_url_kind"] is None
    assert "status" in th.FIELD_LINEAGE_MAP["tx_lgbs"]["sale_status"]
    assert "'sale'" in th.FIELD_LINEAGE_MAP["tx_realauction"]["auction_url_kind"]


# ---------------------------------------------------------------------------
# sync-texas-to-supabase.py: keys only when present, batches by key set
# ---------------------------------------------------------------------------

def _run_sync(monkeypatch, tmp_path, fixture):
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    (out_dir / "harvest_texas.json").write_text(json.dumps(fixture))
    spec = importlib.util.spec_from_file_location("sync_p72", str(REPO / "scripts" / "sync-texas-to-supabase.py"))
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "HERE", tmp_path)
    monkeypatch.setattr(mod, "JSON_PATH", out_dir / "harvest_texas.json")
    monkeypatch.setenv("SUPABASE_URL", "http://example.invalid")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "test-fixture-not-a-real-key")
    posted: list[list[dict]] = []

    class _R:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b""

    def _fake_urlopen(req, timeout=60):
        posted.append(json.loads(req.data))
        return _R()

    monkeypatch.setattr(mod.urllib.request, "urlopen", _fake_urlopen)
    mod.main()
    return posted


BASE = {"state": "TX", "auction_date": "2026-10-06", "min_bid": 100.0, "cad_market_value": 1000.0,
        "legal_description": None, "address": "1 A St", "latitude": None, "longitude": None}


def test_s01_realauction_rows_send_url_and_kind_together_and_lgbs_rows_send_neither(monkeypatch, tmp_path):
    fixture = [
        dict(BASE, account_number="RA-1", county="Nueces", cause_number="C-1", source="auction",
             harvester_source="tx_realauction",
             auction_url="https://nueces.texas.sheriffsaleauctions.com/index.cfm?zaction=AUCTION&zmethod=PREVIEW&AuctionDate=10/06/2026",
             auction_url_kind="sale", sale_status=None),
        dict(BASE, account_number="LG-1", county="Galveston", cause_number="C-2", source="laft",
             harvester_source="tx_lgbs", auction_url=None, auction_url_kind=None,
             sale_status="Struck off to Jurisdiction", auction_date=None),
        dict(BASE, account_number="LG-2", county="Galveston", cause_number="C-3", source="auction",
             harvester_source="tx_lgbs", auction_url=None, auction_url_kind=None, sale_status=None),
    ]
    posted = _run_sync(monkeypatch, tmp_path, fixture)
    rows = {r["case_no"]: r for batch in posted for r in batch}
    assert set(rows) == {"RA-1", "LG-1", "LG-2"}
    assert rows["RA-1"]["url_auction"].endswith("AuctionDate=10/06/2026")
    assert rows["RA-1"]["url_auction_kind"] == "sale"
    assert "tx_sale_status" not in rows["RA-1"]
    assert "url_auction" not in rows["LG-1"] and "url_auction_kind" not in rows["LG-1"]
    assert rows["LG-1"]["tx_sale_status"] == "Struck off to Jurisdiction"
    assert "url_auction" not in rows["LG-2"] and "tx_sale_status" not in rows["LG-2"]
    # Every POST body is homogeneous (PGRST102 rule): all objects share one key set.
    for batch in posted:
        assert len({tuple(sorted(r)) for r in batch}) == 1
    assert len(posted) == 3


def test_s02_a_url_without_a_valid_kind_is_not_sent(monkeypatch, tmp_path):
    fixture = [dict(BASE, account_number="RA-2", county="Nueces", cause_number="C-9", source="auction",
                    harvester_source="tx_realauction", auction_url="https://example.invalid/x",
                    auction_url_kind="homepage", sale_status=None)]
    posted = _run_sync(monkeypatch, tmp_path, fixture)
    row = posted[0][0]
    assert "url_auction" not in row and "url_auction_kind" not in row


def test_s03_sync_never_composes_a_url_itself():
    src = (REPO / "scripts" / "sync-texas-to-supabase.py").read_text(encoding="utf-8")
    assert "sheriffsaleauctions" not in src and "lgbs.com" not in src and "zmethod=PREVIEW" not in src


def test_s04_every_florida_url_auction_writer_also_writes_the_kind():
    for name in ("sync-harvest-to-supabase.ps1", "sync-laft-to-supabase.ps1", "sync-certificates-to-supabase.ps1"):
        src = (REPO / "scripts" / name).read_text(encoding="utf-8")
        assert "url_auction_kind" in src, name
    deeds = (REPO / "scripts" / "sync-harvest-to-supabase.ps1").read_text(encoding="utf-8")
    assert "zaction=auction&zmethod=preview&auctiondate=" in deeds and '"sale"' in deeds
    for name in ("sync-laft-to-supabase.ps1", "sync-certificates-to-supabase.ps1"):
        assert '"county"' in (REPO / "scripts" / name).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Frontend contract: the kind is read from the row, never inferred
# ---------------------------------------------------------------------------

def test_f01_frontend_reads_the_kind_from_the_row_and_never_infers_it():
    app = (REPO / "public" / "app.js").read_text(encoding="utf-8")
    fn = app.split("function auctionLinkInfo(p)")[1].split("\nfunction auctionLinkHtml")[0]
    assert "p.url_auction_kind" in fn
    # The kind comes from the row. Nothing here looks at the vendor, the
    # state, the county name or the URL's shape to decide it.
    for inferred_from in ("harvester_source", "regionOf(", "PAGE_STATE", "p.county", "url_auction.includes", "url_auction.match", ".test(p.url_auction", "sheriffsaleauctions", "realforeclose", "lgbs"):
        assert inferred_from not in fn, inferred_from
    assert '"Auction link not published"' in fn
    assert "View sale listing for" in fn
    for banned in ("Bid on Property", "Buy Property", "Property Auction", "Bid on County Auction Site"):
        assert banned not in app


def test_f02_csv_says_what_the_url_is():
    app = (REPO / "public" / "app.js").read_text(encoding="utf-8")
    cols = app.split("const cols = [")[1].split("\n  ];")[0]
    cols = "\n".join(l for l in cols.splitlines() if not l.strip().startswith("//"))
    assert '["Auction Listing URL", p => p.url_auction || ""]' in cols
    assert '["Auction URL Type", p => p.url_auction ? (p.url_auction_kind || "") : ""]' in cols
    assert '["TX Sale Status", p => p.tx_sale_status || ""]' in cols
    assert "Auction/LAFT Listing" not in cols
