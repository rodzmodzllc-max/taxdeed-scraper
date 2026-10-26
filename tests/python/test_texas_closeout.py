"""Texas close-out (2026-10-26): rows LGBS / Texas RealAuction no longer list
are closed only after a COMPLETE / EMPTY read of their own (source, county);
re-listed rows are reopened; the harvester records per-county read status
(LGBS: the feed's own count; RealAuction: the site's own pager)."""
from __future__ import annotations

import importlib
import json
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

TC = importlib.import_module("texas_closeout")
TH = importlib.import_module("harvesters.texas_harvester")
importlib.import_module("harvesters.tls_chain")  # captures the real urlopen before a test replaces it
from harvesters.ledgers import health as LH  # noqa: E402

ALL = {"tx_lgbs", "tx_realauction"}
NOW = datetime(2026, 10, 26, 12, tzinfo=timezone.utc)


def h(source, county, account, sid="tx_lgbs"):
    return {"source": source, "county": county, "account_number": account, "harvester_source": sid}


def s(id_, source, county, case_no, sid="tx_lgbs", status="active", sale_date=None):
    return {"id": id_, "state": "TX", "source": source, "county": county, "case_no": case_no,
            "harvester_source": sid, "status": status, "sale_date": sale_date}


def units(*entries):
    return LH.ledger_units([dict(e) for e in entries])


def complete(sid, county, n=1):
    return {"source_id": sid, "county": county, "status": "COMPLETE", "row_count": n, "transport_ok": True, "parse_ok": True}


def empty(sid, county, signal="complete statewide feed walk lists no record for this county"):
    return {"source_id": sid, "county": county, "status": "EMPTY", "row_count": 0, "empty_signal": signal,
            "transport_ok": True, "parse_ok": True}


def plan(harvest, stored, u, **kw):
    kw.setdefault("max_share", None)
    return TC.plan(harvest, stored, u, ALL, now=NOW, **kw)


# ---------------------------------------------------------------- close-out

def test_complete_read_closes_only_absent_rows():
    harvest = [h("laft", "Harris", "A1")]
    stored = [s(1, "laft", "Harris", "A1"), s(2, "laft", "Harris", "A2")]
    p = plan(harvest, stored, units(complete("tx_lgbs", "Harris")))
    assert [c["id"] for c in p["close"]] == [2]
    c = p["close"][0]
    assert c["status"] == "closed" and c["delisted_at"]
    assert "sold" not in json.dumps(p)


def test_empty_read_with_signal_closes_every_active_row_of_that_county():
    stored = [s(1, "laft", "Brooks", "B1"), s(2, "auction", "Brooks", "B2")]
    p = plan([], stored, units(empty("tx_lgbs", "Brooks")))
    assert sorted(c["id"] for c in p["close"]) == [1, 2]


def test_empty_without_a_signal_or_with_rows_closes_nothing():
    stored = [s(1, "laft", "Brooks", "B1")]
    no_signal = {**empty("tx_lgbs", "Brooks"), "empty_signal": None}
    assert plan([], stored, units(no_signal))["close"] == []
    with_rows = {**empty("tx_lgbs", "Brooks"), "row_count": 3}
    assert plan([], stored, units(with_rows))["close"] == []


@pytest.mark.parametrize("entry", [
    {"source_id": "tx_lgbs", "county": "Harris", "status": "INCOMPLETE", "row_count": 0},
    {"source_id": "tx_lgbs", "county": "Harris", "status": "FAILED", "error_category": "TRANSPORT_PAGE_FAILED"},
    {"source_id": "tx_lgbs", "county": "Harris", "status": "FAILED"},
    {"source_id": "tx_lgbs", "county": "Harris", "status": "COMPLETE", "transport_ok": False},
    {"source_id": "tx_lgbs", "county": "Harris", "status": "SOMETHING"},
])
def test_failed_incomplete_or_unknown_read_closes_nothing(entry):
    stored = [s(1, "laft", "Harris", "A1"), s(2, "auction", "Harris", "A2")]
    assert plan([], stored, units(entry))["close"] == []


def test_missing_status_closes_nothing():
    stored = [s(1, "laft", "Harris", "A1")]
    assert plan([], stored, {})["close"] == []
    assert TC.units_from(REPO / "out" / "does-not-exist.json") == {}


def test_another_sources_read_never_closes_a_row():
    """RealAuction's COMPLETE read of Dallas never closes an LGBS row there,
    and an LGBS read never closes a RealAuction row."""
    stored = [s(1, "auction", "Dallas", "D1", sid="tx_lgbs"), s(2, "auction", "Dallas", "D2", sid="tx_realauction")]
    p = plan([], stored, units(complete("tx_realauction", "Dallas")))
    assert [c["id"] for c in p["close"]] == [2]
    p = plan([], stored, units(complete("tx_lgbs", "Dallas")))
    assert [c["id"] for c in p["close"]] == [1]


def test_a_row_of_a_ledger_the_source_does_not_feed_is_never_closed():
    """tx_realauction feeds Auctions only: a stored Available or certificate
    row carrying its id is untouched; so is a row of another state."""
    stored = [s(1, "laft", "Dallas", "D1", sid="tx_realauction"),
              s(2, "certificate", "Dallas", "D2", sid="tx_lgbs"),
              {**s(3, "auction", "Dallas", "D3", sid="tx_realauction"), "state": "FL"}]
    u = units(complete("tx_realauction", "Dallas"), complete("tx_lgbs", "Dallas"))
    assert plan([], stored, u)["close"] == []


def test_a_listing_that_moved_ledger_closes_the_old_ledger_row_only():
    """LGBS moved an account from struck-off (Available) to a scheduled sale:
    the Available row closes, the Auctions row stays."""
    harvest = [h("auction", "Bexar", "X1")]
    stored = [s(1, "laft", "Bexar", "X1"), s(2, "auction", "Bexar", "X1")]
    p = plan(harvest, stored, units(complete("tx_lgbs", "Bexar")))
    assert [c["id"] for c in p["close"]] == [1]


def test_a_row_listed_by_either_vendor_is_kept():
    harvest = [h("auction", "Dallas", "D1", sid="tx_realauction")]
    stored = [s(1, "auction", "Dallas", "D1", sid="tx_lgbs")]
    assert plan(harvest, stored, units(complete("tx_lgbs", "Dallas")))["close"] == []


def test_closed_rows_are_not_closed_again():
    stored = [s(1, "laft", "Harris", "A1", status="closed")]
    assert plan([], stored, units(complete("tx_lgbs", "Harris")))["close"] == []


def test_a_source_without_store_permission_is_never_written():
    stored = [s(1, "laft", "Harris", "A1"), s(2, "laft", "Harris", "A2", status="closed")]
    p = TC.plan([h("laft", "Harris", "A2")], stored, units(complete("tx_lgbs", "Harris")), {"tx_realauction"},
                max_share=None, now=NOW)
    assert p["close"] == [] and p["reactivate"] == []


# ---------------------------------------------------------------- reactivation

def test_a_relisted_closed_row_is_reactivated_even_on_an_incomplete_read():
    harvest = [h("laft", "Harris", "A1")]
    stored = [s(1, "laft", "Harris", "A1", status="closed"), s(2, "laft", "Harris", "A2", status="closed")]
    p = plan(harvest, stored, units({"source_id": "tx_lgbs", "county": "Harris", "status": "INCOMPLETE"}))
    assert p["reactivate"] == [1] and p["close"] == []


def test_a_recorded_result_is_never_reopened_by_a_listing():
    harvest = [h("auction", "Harris", "A1")]
    stored = [s(1, "auction", "Harris", "A1", status="sold")]
    assert plan(harvest, stored, {})["reactivate"] == []


def test_relisting_under_another_ledger_does_not_reopen_the_old_ledger_row():
    harvest = [h("auction", "Harris", "A1")]
    stored = [s(1, "laft", "Harris", "A1", status="closed")]
    assert plan(harvest, stored, {})["reactivate"] == []


# ---------------------------------------------------------------- large-close guard

def test_a_read_that_would_close_most_of_a_feed_is_refused():
    stored = [s(i, "laft", "Harris", f"A{i}") for i in range(10)]
    p = TC.plan([h("laft", "Harris", "A0")], stored, units(complete("tx_lgbs", "Harris")), ALL, now=NOW)
    assert p["close"] == [] and p["refused_sources"] == {"tx_lgbs": 9}
    assert p["kept"]["absent, refused (large close)"] == 9


def test_past_sale_rows_do_not_count_toward_the_guard():
    """Every row of a passed sale day leaves the waiting list at once - that
    is expected, not a lost feed."""
    stored = [s(i, "auction", "Dallas", f"D{i}", sid="tx_realauction", sale_date="2026-10-06") for i in range(10)]
    stored.append(s(99, "auction", "Dallas", "D99", sid="tx_realauction", sale_date="2026-11-03"))
    harvest = [h("auction", "Dallas", "D99", sid="tx_realauction")]
    p = TC.plan(harvest, stored, units(complete("tx_realauction", "Dallas")), ALL, now=NOW)
    assert len(p["close"]) == 10 and p["refused_sources"] == {}


# ---------------------------------------------------------------- writes

def test_patches_are_chunked_and_state_filtered():
    sent = []
    n = TC.patch_ids("https://x.supabase.co", "k", list(range(250)), {"status": "closed"},
                     send=lambda url, body, key: sent.append((url, body)))
    assert n == 250 and len(sent) == 3
    assert all("state=eq.TX" in u and "id=in.(" in u for u, _ in sent)


def test_dry_run_writes_nothing(monkeypatch, tmp_path):
    harvest = tmp_path / "h.json"
    harvest.write_text(json.dumps([h("laft", "Harris", "A1")]))
    status = tmp_path / "s.json"
    status.write_text(json.dumps({"sources": {}, "counties": [complete("tx_lgbs", "Harris")]}))
    monkeypatch.setenv("SUPABASE_URL", "https://x.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "k")
    monkeypatch.setattr(TC, "store_permitted", lambda: set(ALL))
    monkeypatch.setattr(TC, "stored_rows", lambda b, k: [s(1, "laft", "Harris", "A1"), s(2, "laft", "Harris", "A2"),
                                                       s(3, "laft", "Harris", "A3")])
    monkeypatch.setattr(TC, "_send", lambda *a: (_ for _ in ()).throw(AssertionError("wrote in a dry run")))
    assert TC.main(["--harvest", str(harvest), "--status", str(status), "--dry-run"]) == 0


def test_live_run_closes_and_reopens(monkeypatch, tmp_path, capsys):
    harvest = tmp_path / "h.json"
    harvest.write_text(json.dumps([h("laft", "Harris", f"A{i}") for i in range(1, 9)]))
    status = tmp_path / "s.json"
    status.write_text(json.dumps({"counties": [complete("tx_lgbs", "Harris", 8)]}))
    monkeypatch.setenv("SUPABASE_URL", "https://x.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "k")
    monkeypatch.setattr(TC, "store_permitted", lambda: set(ALL))
    stored = [s(i, "laft", "Harris", f"A{i}") for i in range(1, 8)] + [s(8, "laft", "Harris", "A8", status="closed"),
                                                                      s(9, "laft", "Harris", "A9")]
    monkeypatch.setattr(TC, "stored_rows", lambda b, k: stored)
    sent = []
    monkeypatch.setattr(TC, "_send", lambda url, body, key: sent.append((url, body)))
    assert TC.main(["--harvest", str(harvest), "--status", str(status)]) == 0
    assert any("id=in.(9)" in u and b["status"] == "closed" and b["delisted_at"] for u, b in sent)
    assert any("id=in.(8)" in u and b == {"status": "active", "delisted_at": None} for u, b in sent)
    out = capsys.readouterr().out
    assert "closed 1, reactivated 1" in out


def test_permission_denied_exits_3(monkeypatch):
    monkeypatch.setattr(TC, "store_permitted", lambda: set())
    assert TC.main(["--harvest", "/nonexistent", "--status", "/nonexistent"]) == TC.PERMISSION_DENIED_EXIT


def test_every_texas_source_holds_the_store_permission_the_closeout_needs():
    """LGBS, Texas RealAuction, the vendors the owner unblocked on 2026-10-26 and the eight
    county-published lists of the same day."""
    assert TC.store_permitted() == set(TC.SOURCE_IDS)
    assert set(TC.VENDOR_SOURCE_IDS) == ALL | {"tx_pbfcm", "tx_mvba", "tx_govease"}


def test_closeout_reuses_the_shared_close_rule():
    src = (REPO / "scripts" / "texas_closeout.py").read_text()
    assert "SI.plan_close(" in src and "LH.ledger_units(" in src
    assert '"sold"' not in src.split("REACTIVATABLE =")[1].split("\n")[0]


# ---------------------------------------------------------------- LGBS per-county status

def lgbs_stats(**kw):
    base = {"complete": True, "limited": False, "count_matches": True, "unattributed": 0, "truncated_at_page": None,
            "raw_rows_seen": 3, "source_count": 3, "rows_per_county": {"Harris": 2, "Bexar": 1}}
    return {**base, **kw}


def test_lgbs_verified_walk_marks_listed_counties_complete_and_the_rest_empty():
    entries = {e["county"]: e for e in TH.lgbs_county_entries(lgbs_stats(), ["Harris", "Bexar", "Brooks"])}
    assert entries["Harris"]["status"] == "COMPLETE" and entries["Harris"]["row_count"] == 2
    assert entries["Brooks"]["status"] == "EMPTY" and entries["Brooks"]["empty_signal"]
    u = LH.ledger_units(list(entries.values()))
    assert u[("tx_lgbs", "Brooks")] == "EMPTY" and u[("tx_lgbs", "Harris")] == "COMPLETE"


@pytest.mark.parametrize("kw,expect", [
    ({"count_matches": False}, "INCOMPLETE"),
    ({"unattributed": 2}, "INCOMPLETE"),
    ({"limited": True}, "INCOMPLETE"),
    ({"complete": False, "truncated_at_page": 6}, "SOURCE_UNAVAILABLE"),
])
def test_lgbs_unverified_walk_closes_nothing(kw, expect):
    entries = TH.lgbs_county_entries(lgbs_stats(**kw), ["Harris", "Bexar", "Brooks"])
    u = LH.ledger_units(entries)
    assert set(u.values()) == {expect}
    assert not any(LH.closeable(LH.Ledger.AVAILABLE, v) for v in u.values())


def test_texas_county_roster_has_254_counties():
    names = TH.texas_counties()
    assert len(names) == 254 and "Harris" in names and "McLennan" in names


class _Resp:
    def __init__(self, text):
        self._b = text.encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self._b


def _rec(i, county="HARRIS COUNTY", status="Struck off to Jurisdiction", state="TX", with_id=True):
    r = {"state": state, "status": status, "county": county, "account_nbr": f"ACC{i}", "cause_nbr": f"C-{i}"}
    if with_id:
        r["id"] = i
    return r


def _lgbs(monkeypatch, pages):
    it = iter(pages)
    monkeypatch.setattr(urllib.request, "urlopen", lambda url, timeout=30: _Resp(json.dumps(next(it))))
    monkeypatch.setattr(time, "sleep", lambda *_: None)
    st: dict = {}
    rows = TH.harvest_lgbs(stats=st)
    return rows, st


def test_lgbs_walk_counts_against_the_feeds_own_total(monkeypatch):
    pages = [{"count": 4, "next": "http://taxsales.lgbs.com/api/property_sales/?offset=2",
              "results": [_rec(1), _rec(2, state="PA", county="PHILADELPHIA COUNTY")]},
             {"count": 4, "next": None, "results": [_rec(3), _rec(4, status="Cancelled")]}]
    rows, st = _lgbs(monkeypatch, pages)
    assert len(rows) == 2 and st["count_matches"] is True and st["rows_per_county"] == {"Harris": 2}


def test_lgbs_short_read_or_moved_total_is_not_verified(monkeypatch):
    rows, st = _lgbs(monkeypatch, [{"count": 5, "next": None, "results": [_rec(1), _rec(2)]}])
    assert st["count_matches"] is False
    pages = [{"count": 2, "next": "https://x/?offset=1", "results": [_rec(1)]},
             {"count": 3, "next": None, "results": [_rec(2)]}]
    rows, st = _lgbs(monkeypatch, pages)
    assert st["count_matches"] is False


def test_lgbs_repeated_record_id_is_not_verified(monkeypatch):
    pages = [{"count": 2, "next": "https://x/?offset=1", "results": [_rec(1)]},
             {"count": 2, "next": None, "results": [_rec(1)]}]
    rows, st = _lgbs(monkeypatch, pages)
    assert st["count_matches"] is False


def test_lgbs_unattributable_record_is_counted(monkeypatch):
    bad = _rec(2)
    bad["account_nbr"] = ""
    rows, st = _lgbs(monkeypatch, [{"count": 2, "next": None, "results": [_rec(1), bad]}])
    assert st["unattributed"] == 1
    assert {e["status"] for e in TH.lgbs_county_entries(st, ["Harris"])} == {"INCOMPLETE"}


# ---------------------------------------------------------------- RealAuction pager + per-county status

def _item(acc):
    return ("AITEM_1 Sale Type:@F CAD_DTA\\\">@ Cause Number:@F CAD_DTA\\\">TX-1 (1)@ "
            f"Account Number:@F CAD_DTA\\\">{acc}@ Adjudged Value:@F CAD_DTA\\\">$1.00@ "
            "Est. Min. Bid:@F CAD_DTA\\\">$2.00@ Property Address:@F CAD_DTA\\\">1 MAIN ST@")


def _page(accs):
    """The listing response as the site sends it: a JSON object whose HTML
    keeps its quotes escaped (\\") - the shape _realauction_get_field reads."""
    body = '{"retHTML":"' + "".join(_item(a) for a in accs) + '","rlist":"' + ",".join("1" for _ in accs) + '"}'
    json.loads(body)  # valid JSON
    return body


EMPTY_PAGE = json.dumps({"retHTML": "", "rlist": ""})
CAL_WITH_SALE = "<div class='CALBOX CALSELT' dayid='11/03/2026'>3</div>"
CAL_NO_SALE = "<div class='CALBOX'>4</div>"


class _Opener:
    def __init__(self, handler):
        self.handler = handler
        self.log = []

    def open(self, req, timeout=25):
        self.log.append(req.full_url)
        body = self.handler(req.full_url)
        if body is None:
            raise urllib.error.URLError("down")
        return _Resp(body)


def _run_ra(monkeypatch, tmp_path, handler):
    roster = tmp_path / "roster.csv"
    roster.write_text("County,Host\nDallas,dallas.texas.sheriffsaleauctions.com\n")
    monkeypatch.setattr(TH, "REALAUCTION_COUNTIES_CSV", roster)
    opener = _Opener(handler)
    monkeypatch.setattr(urllib.request, "build_opener", lambda *a: opener)
    monkeypatch.setattr(time, "sleep", lambda *_: None)
    st: dict = {}
    rows = TH.harvest_realauction(stats=st)
    return rows, st["county_entries"][0], opener.log


import urllib.error  # noqa: E402


def test_realauction_follows_the_sites_own_pager_past_ten_items(monkeypatch, tmp_path):
    first = [f"A{i}" for i in range(10)]
    second = ["B1", "B2", "B3"]

    def handler(url):
        if "zmethod=calendar" in url:
            return CAL_WITH_SALE
        if "zmethod=PREVIEW" in url:
            return "<html></html>"
        if "PageDir=0&doR=1" in url:
            return _page(first)
        # Like the live server: bypassPage=1 ignores PageDir and sends page one.
        if "bypassPage=1" in url:
            return _page(first)
        if "PageDir=1&doR=0&bypassPage=0" in url:
            return _page(second)
        raise AssertionError(url)

    rows, entry, log = _run_ra(monkeypatch, tmp_path, handler)
    assert len(rows) == 13
    assert entry["status"] == "COMPLETE" and entry["row_count"] == 13
    assert not any("PageDir=2" in u or ("PageDir=1&doR=1" in u) for u in log)


def test_realauction_pager_that_repeats_a_full_page_is_incomplete(monkeypatch, tmp_path):
    first = [f"A{i}" for i in range(10)]

    def handler(url):
        if "zmethod=calendar" in url:
            return CAL_WITH_SALE
        if "zmethod=PREVIEW" in url:
            return "<html></html>"
        return _page(first)

    rows, entry, _ = _run_ra(monkeypatch, tmp_path, handler)
    assert len(rows) == 10 and entry["status"] == "INCOMPLETE"


def test_realauction_no_sale_days_on_a_real_calendar_is_empty(monkeypatch, tmp_path):
    rows, entry, _ = _run_ra(monkeypatch, tmp_path, lambda url: CAL_NO_SALE)
    assert rows == [] and entry["status"] == "EMPTY" and entry["empty_signal"]
    assert LH.ledger_units([entry])[("tx_realauction", "Dallas")] == "EMPTY"


def test_realauction_empty_waiting_list_is_empty(monkeypatch, tmp_path):
    def handler(url):
        if "zmethod=calendar" in url:
            return CAL_WITH_SALE
        if "zmethod=PREVIEW" in url:
            return "<html></html>"
        return EMPTY_PAGE

    rows, entry, _ = _run_ra(monkeypatch, tmp_path, handler)
    assert rows == [] and entry["status"] == "EMPTY"


@pytest.mark.parametrize("bad", ["calendar", "preview", "page"])
def test_realauction_failed_request_is_failed(monkeypatch, tmp_path, bad):
    def handler(url):
        if "zmethod=calendar" in url:
            return None if bad == "calendar" else CAL_WITH_SALE
        if "zmethod=PREVIEW" in url:
            return None if bad == "preview" else "<html></html>"
        return None if bad == "page" else _page(["A1"])

    rows, entry, _ = _run_ra(monkeypatch, tmp_path, handler)
    assert entry["status"] == "FAILED" and not LH.closeable(LH.Ledger.AUCTIONS, LH.reader_status(entry))


@pytest.mark.parametrize("body", ["<html>login</html>", "not json"])
def test_realauction_non_listing_body_is_incomplete(monkeypatch, tmp_path, body):
    def handler(url):
        if "zmethod=calendar" in url:
            return CAL_WITH_SALE
        if "zmethod=PREVIEW" in url:
            return "<html></html>"
        return body

    rows, entry, _ = _run_ra(monkeypatch, tmp_path, handler)
    assert entry["status"] == "INCOMPLETE"


def test_realauction_non_calendar_page_is_not_an_empty_calendar(monkeypatch, tmp_path):
    rows, entry, _ = _run_ra(monkeypatch, tmp_path, lambda url: "<html>Please log in</html>")
    assert entry["status"] == "INCOMPLETE"


def test_realauction_item_without_account_is_incomplete(monkeypatch, tmp_path):
    def handler(url):
        if "zmethod=calendar" in url:
            return CAL_WITH_SALE
        if "zmethod=PREVIEW" in url:
            return "<html></html>"
        return _page(["A1", ""])

    rows, entry, _ = _run_ra(monkeypatch, tmp_path, handler)
    assert len(rows) == 1 and entry["status"] == "INCOMPLETE"


# ---------------------------------------------------------------- workflow wiring

def test_workflow_runs_the_closeout_after_the_stamp_and_before_inventory_status():
    wf = (REPO / ".github" / "workflows" / "harvest-and-sync.yml").read_text()
    job = wf[wf.index("\n  texas:"):wf.index("\n  backup:")]
    i_stamp = job.index("stamp_seen.py --state TX")
    i_close = job.index("python3 scripts/texas_closeout.py")
    i_inv = job.index("inventory_status_writer.py --state TX")
    assert i_stamp < i_close < i_inv
    step = job[job.rindex("- name:", 0, i_close):i_close]
    assert "continue-on-error: true" in step and "steps.sync.outcome == 'success'" in step


def test_harvester_writes_per_county_entries_into_the_status_file():
    src = (REPO / "harvesters" / "texas_harvester.py").read_text()
    body = src[src.index("def main() -> None:"):]
    assert '"counties": county_entries' in body and "lgbs_county_entries(" in body


def test_every_texas_county_name_normalizes_to_the_rosters_spelling():
    """An LGBS county the roster spells differently would get no EMPTY entry
    and its rows could never close (and would not match the basemap)."""
    for name in TH.texas_counties():
        assert TH._lgbs_normalize_county(name.upper() + " COUNTY") == name
    assert TH._lgbs_normalize_county("DE WITT COUNTY") == "DeWitt"
