"""Texas data-accuracy fixes (2026-11-08), all on synthetic fixtures.

TX-01  the vendor close-out and the county-list close-out no longer undo each
       other: only the row's own source reopens it, and a county list takes
       over a vendor's CLOSED row of the same identity (never an active one,
       never a recorded result).
TX-03  a JSON endpoint that answers with nothing is a transport failure, an
       HTML page in its place is named as such - never "bad JSON", never empty.
TX-05  a county page that times out is tried three times with backoff.
TX-07  the Texas publication step stamps the source decision on auction rows
       too (the vendor sync never wrote the column).
"""
from __future__ import annotations

import importlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
import requests

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

TC = importlib.import_module("texas_closeout")
SI = importlib.import_module("sync_state_inventory")
PG = importlib.import_module("publication_gate")
T = importlib.import_module("harvest_tx_county_sales")
CS = importlib.import_module("test_county_sources_2026_10_26")
from harvesters import texas_vendors as V  # noqa: E402
from harvesters.governance import county_source_registry as csr  # noqa: E402
from harvesters.governance import publication as pub  # noqa: E402

NOW = datetime(2026, 11, 8, 12, tzinfo=timezone.utc)
RETRIEVED = datetime(2026, 11, 8, 12, tzinfo=timezone.utc)


# ---------------------------------------------------------------- TX-01

def _row(id_, sid, status, source="auction", county="Harris", case_no="0000000000001"):
    return {"id": id_, "state": "TX", "source": source, "county": county, "case_no": case_no,
            "harvester_source": sid, "status": status, "sale_date": "2026-12-01"}


def _listing(sid, source="auction", county="Harris", account="0000000000001"):
    return {"harvester_source": sid, "source": source, "county": county, "account_number": account}


def test_a_county_list_never_reopens_a_vendors_closed_row():
    stored = [_row(1, "tx_lgbs", "closed")]
    county_units = {("tx_hctax", "Harris"): "COMPLETE"}
    p = TC.plan([_listing("tx_hctax")], stored, county_units, set(TC.SOURCE_IDS), max_share=None, now=NOW)
    assert p["reactivate"] == []
    # The row's own source listing it again still reopens it.
    p = TC.plan([_listing("tx_lgbs")], stored, {("tx_lgbs", "Harris"): "COMPLETE"}, set(TC.SOURCE_IDS), max_share=None, now=NOW)
    assert p["reactivate"] == [1]


def test_listing_sources_carries_the_listing_source_id():
    got = TC.listing_sources([_listing("tx_hctax"), _listing("tx_unknown"), {"harvester_source": "tx_lgbs"}])
    assert got == {("TX", "auction", "Harris", "0000000000001", "tx_hctax")}


def _harris_sync(stored_rows):
    reg = SI.registry_rows("TX")
    rows = [T.to_properties_row(r, RETRIEVED) for r in CS._harris_rows()][:1]
    units = {("tx_hctax", "Harris"): "COMPLETE"}
    return SI.plan("TX", rows, reg, units, stored_rows=stored_rows, keep_other_sources=True)


def test_county_list_takes_over_a_vendors_closed_row_of_the_same_identity():
    ident = ("auction", "Harris", "0000000000001")
    out, counts = _harris_sync({ident: {"harvester_source": "tx_lgbs", "status": "closed", "otc_provenance": {}}})
    assert len(out) == 1 and out[0]["harvester_source"] == "tx_hctax" and out[0]["status"] == "active"
    assert out[0]["delisted_at"] is None and counts["took_over_closed_row_of_other_source"] == 1
    assert "skipped_row_of_other_source" not in counts


@pytest.mark.parametrize("status", ["active", "sold", "redeemed", None])
def test_county_list_never_takes_over_an_active_vendor_row_or_a_result(status):
    ident = ("auction", "Harris", "0000000000001")
    prior = {"harvester_source": "tx_lgbs", "otc_provenance": {}}
    if status:
        prior["status"] = status
    out, counts = _harris_sync({ident: prior})
    assert out == [] and counts["skipped_row_of_other_source"] == 1


def test_closed_exact_row_is_not_taken_over_while_another_spelling_is_active():
    stored = {("auction", "Harris", "0000000000001"): {"harvester_source": "tx_lgbs", "status": "closed", "otc_provenance": {}},
              ("auction", "Harris", "0000000000-001"): {"harvester_source": "tx_pbfcm", "status": "active", "otc_provenance": {}}}
    out, counts = _harris_sync(stored)
    assert out == [] and counts["skipped_row_of_other_source"] == 1


def test_two_runs_reach_a_fixed_point():
    """Vendor pass then county pass, twice: the row is the county list's, active,
    and no pass closes or reopens it again (it used to flip every run)."""
    db = {1: _row(1, "tx_lgbs", "active")}
    vendor_units = {("tx_lgbs", "Harris"): "COMPLETE"}
    county_units = {("tx_hctax", "Harris"): "COMPLETE"}
    history = []
    for _ in range(2):
        # Vendor pass: LGBS no longer lists the account.
        p = TC.plan([], list(db.values()), vendor_units, set(TC.SOURCE_IDS), max_share=None, now=NOW)
        for c in p["close"]:
            db[c["id"]]["status"] = "closed"
        for i in p["reactivate"]:
            db[i]["status"] = "active"
        history.append(("vendor", len(p["close"]), len(p["reactivate"])))
        # County sync: takes over the closed vendor row (the same identity key).
        r = db[1]
        out, _ = _harris_sync({(r["source"], r["county"], r["case_no"]): dict(r)})
        for w in out:
            db[1].update(harvester_source=w["harvester_source"], status=w["status"])
        # County close-out.
        p = TC.plan([_listing("tx_hctax")], list(db.values()), county_units, set(TC.SOURCE_IDS), max_share=None, now=NOW)
        for c in p["close"]:
            db[c["id"]]["status"] = "closed"
        for i in p["reactivate"]:
            db[i]["status"] = "active"
        history.append(("county", len(p["close"]), len(p["reactivate"])))
    assert db[1]["harvester_source"] == "tx_hctax" and db[1]["status"] == "active"
    assert history == [("vendor", 1, 0), ("county", 0, 0), ("vendor", 0, 0), ("county", 0, 0)]


# ---------------------------------------------------------------- TX-03

@pytest.mark.parametrize("body,expected", [(b"", "TRANSPORT_EMPTY_BODY"), (b"  \n", "TRANSPORT_EMPTY_BODY"),
                                           (b"<html><title>x</title></html>", "NON_JSON_HTML"), (b"{oops", "BAD_JSON")])
def test_non_json_category(body, expected):
    assert V.non_json_category(body) == expected


class _Fetcher:
    def __init__(self, body):
        self.body, self.requests = body, 0

    def request(self, url, data=None, *, accept="*/*", headers=None):
        self.requests += 1
        return b"<html></html>" if url.endswith("/") else self.body


def test_empty_auction_index_is_a_transport_failure_and_reads_nothing():
    book = V.UnitBook()
    rows, info = V.harvest_mvba_online(_Fetcher(b""), book)
    assert rows == [] and info["error"] == "TRANSPORT_EMPTY_BODY" and info["non_json"]["bytes"] == 0
    assert book.units == {}


# ---------------------------------------------------------------- TX-05

def test_county_page_timeouts_are_retried_with_backoff():
    calls, waits = [], []

    def fn(session):
        calls.append(1)
        if len(calls) < 3:
            raise requests.ConnectTimeout("connect timeout")
        return [], {}, "https://example.invalid/"

    assert T.fetch_with_retry(fn, None, sleep=waits.append)[2] == "https://example.invalid/"
    assert len(calls) == 3 and waits == [T.RETRY_DELAY_S, T.RETRY_DELAY_S * 3]


def test_county_page_gives_up_after_three_attempts_and_never_retries_other_errors():
    calls = []

    def timeout(session):
        calls.append(1)
        raise requests.ConnectTimeout("connect timeout")

    with pytest.raises(requests.ConnectTimeout):
        T.fetch_with_retry(timeout, None, sleep=lambda s: None)
    assert len(calls) == T.FETCH_ATTEMPTS == 3

    def http_error(session):
        calls.append(1)
        raise requests.HTTPError("403")

    calls.clear()
    with pytest.raises(requests.HTTPError):
        T.fetch_with_retry(http_error, None, sleep=lambda s: None)
    assert len(calls) == 1


# ---------------------------------------------------------------- TX-07

def _decisions():
    return pub.decisions_by_source(csr.load_registry(csr.REGISTRY_PATH))


def test_auction_rows_receive_their_source_decision_only_when_asked():
    rows = [{"id": "a", "state": "TX", "source": "auction", "harvester_source": "tx_lgbs", "source_id": "tx_lgbs",
             "publication_status": None},
            {"id": "b", "state": "TX", "source": "auction", "harvester_source": "tx_pbfcm", "source_id": "tx_pbfcm",
             "publication_status": "APPROVED"},
            {"id": "c", "state": "TX", "source": "laft", "harvester_source": "tx_lgbs", "source_id": "tx_lgbs",
             "publication_status": "APPROVED_GRANDFATHERED"},
            {"id": "d", "state": "TX", "source": "certificate", "harvester_source": "tx_lgbs", "source_id": "tx_lgbs",
             "publication_status": None}]
    d = _decisions()
    default, _ = PG.plan(rows, d)
    assert default == {}                                    # laft only: unchanged behaviour
    groups, counts = PG.plan(rows, d, ledgers=("laft", "auction"))
    assert groups == {"APPROVED_GRANDFATHERED": ["a", "b"]} and counts["unchanged"] == 1


def test_parse_ledgers():
    assert PG.parse_ledgers(None) == ("laft",)
    assert PG.parse_ledgers("laft,auction") == ("laft", "auction")
    with pytest.raises(ValueError):
        PG.parse_ledgers("laft,certificate")


def test_texas_step_propagates_to_auction_rows():
    wf = (REPO / ".github" / "workflows" / "harvest-and-sync.yml").read_text(encoding="utf-8")
    assert "publication_gate.py --state TX --ledgers laft,auction" in wf


def test_fetch_rows_filters_both_ledgers(monkeypatch):
    seen = {}

    def read_all(root, table, headers, params, **kw):
        seen.update(params)
        return []

    monkeypatch.setattr(PG.RP, "read_all", read_all)
    api = PG.Api("https://x.supabase.co", "k", dry_run=True)
    PG.fetch_rows(api, "TX", ledgers=("laft", "auction"))
    assert seen["source"] == "in.(laft,auction)"
    PG.fetch_rows(api, "TX")
    assert seen["source"] == "eq.laft"
