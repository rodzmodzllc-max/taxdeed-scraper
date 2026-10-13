"""Three first-class ledgers, implementation sprint 1 (2026-10-13).

Regression tests for the per-ledger record contracts
(harvesters/ledgers/records.py), the per-ledger read-health reader
(harvesters/ledgers/health.py) and the places they are enforced: the state
inventory sync and its close-out, the inventory status writer and the Texas
sync. Pure: no network, no database.
"""
import json
import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(1, str(ROOT))
import inventory_status_writer as ISW  # noqa: E402
import sync_state_inventory as SY  # noqa: E402
from harvesters.governance import inventory_status as IS  # noqa: E402
from harvesters.governance import permissions as PERM  # noqa: E402
from harvesters.ledgers import Ledger, LEDGER_STATUSES, ledger_for_row  # noqa: E402
from harvesters.ledgers import domains  # noqa: E402
from harvesters.ledgers import health as LH  # noqa: E402
from harvesters.ledgers import records as LR  # noqa: E402

LOTS = "mi_detroit_landbank_lots"
PROGRAMS = "mi_detroit_landbank_programs"


def _auction(**kw):
    row = {"state": "FL", "source": "auction", "harvester_source": "fl_realauction", "county": "Alachua",
           "case_no": "2026-TD-001", "parcel": "12-34-56", "sale_date": "2026-11-02", "bid": 5400.0}
    row.update(kw)
    return row


def _available(**kw):
    row = {"state": "FL", "source": "laft", "harvester_source": "fl_laft_pdfs", "county": "Alachua",
           "case_no": "LAFT-9", "parcel": "12-34-56", "inventory_type": "POST_SALE_FIXED_PRICE"}
    row.update(kw)
    return row


def _certificate(**kw):
    row = {"state": "FL", "source": "certificate", "harvester_source": "fl_lienhub_certificates",
           "county": "Alachua", "case_no": "2024-0007", "certificate_no": "2024-0007", "parcel": "12-34-56",
           "bid": 812.5, "tax_year": 2024, "issued_date": "2025-06-01"}
    row.update(kw)
    return row


# ------------------------------------------------ 1. auction -> available

def test_an_auction_row_is_never_an_available_record():
    with pytest.raises(LR.LedgerViolation):
        LR.AvailableRecord(_auction())
    assert isinstance(LR.record_for_row(_auction()), LR.AuctionRecord)


def test_an_auction_row_with_available_fields_is_refused():
    probs = LR.problems(_auction(inventory_type="POST_SALE_FIXED_PRICE"))
    assert any("Available field inventory_type" in p for p in probs)


def test_an_auction_row_with_an_available_ledger_type_is_refused():
    assert any("contradicts" in p for p in LR.problems(_auction(ledger_type="buy")))


def test_an_auction_source_id_cannot_feed_available():
    row = _available(harvester_source="fl_realauction")
    assert any("does not feed AVAILABLE" in p for p in LR.problems(row))


# ------------------------------------------------ 2. available -> auction

def test_an_available_row_is_never_an_auction_record():
    with pytest.raises(LR.LedgerViolation):
        LR.AuctionRecord(_available())


def test_an_available_row_with_an_auction_status_is_refused():
    assert any("not a AVAILABLE status" in p or "is not a AVAILABLE status" in p
               for p in LR.problems(_available(inventory_status="auction_scheduled")))


@pytest.mark.parametrize("status,ledger_source,ok", [
    ("Struck off to Jurisdiction", "laft", True),
    ("Struck off to Jurisdiction", "auction", False),
    ("Scheduled for Auction", "auction", True),
    ("Scheduled for Auction", "laft", False),
    ("Available for Future Sale", "auction", False),
])
def test_lgbs_rows_follow_the_vendors_own_status(status, ledger_source, ok):
    row = {"state": "TX", "source": ledger_source, "harvester_source": "tx_lgbs", "county": "Bexar",
           "case_no": "ACCT-1", "parcel": "CAUSE-1", "tx_sale_status": status}
    assert (LR.problems(row) == []) is ok


# ------------------------------------------------ 3. certificates are never property sales

def test_a_certificate_row_never_carries_a_property_sale_result():
    for f in LR.RESULT_FIELDS:
        probs = LR.problems(_certificate(**{f: "x"}))
        assert any("never a property sale" in p for p in probs), f


@pytest.mark.parametrize("status", ["sold", "redeemed", "struck_off", "auction_scheduled", "available_otc"])
def test_a_certificate_row_cannot_take_a_property_status(status):
    assert not LR.status_allowed(Ledger.LIENS_CERTIFICATES, status)
    assert LR.problems(_certificate(inventory_status=status))


def test_certificate_results_are_instrument_results():
    for s in LR.RESULT_STATUSES_BY_LEDGER[Ledger.LIENS_CERTIFICATES]:
        assert s.startswith("certificate_")
        assert s in LEDGER_STATUSES[Ledger.LIENS_CERTIFICATES]


def test_status_writer_refuses_a_status_outside_the_rows_ledger(monkeypatch):
    sold = IS.StatusObservation(status="sold", basis="SOURCE_STATUS", raw="Sold", note="test")
    monkeypatch.setattr(ISW.IS, "status_for_row", lambda r, **k: sold)
    rows = [dict(_certificate(), id="c1"), dict(_auction(), id="a1")]
    changes, counts = ISW.plan(rows, today=date(2026, 10, 13))
    assert counts["refused_outside_ledger"] == 1
    assert [c["id"] for c in changes] == ["a1"]


def test_certificate_customer_view_never_shows_the_owner_as_holder():
    v = LR.customer_view(_certificate(owner_name="ASSESSED OWNER"))
    assert v["holder"] == LR.NOT_PUBLISHED
    assert "not ownership" in v["instrument"]
    assert v["redemption"] == LR.OUTCOME_NOT_PUBLISHED
    assert v["face_amount"] == 812.5


# ------------------------------------------------ 4. one property, several ledgers

def test_one_property_in_three_ledgers_keeps_three_identities():
    rows = [_auction(), _available(), _certificate()]
    keys = {LR.property_key(r) for r in rows}
    assert keys == {("FL", "alachua", "123456")}
    ids = {LR.record_for_row(r).identity for r in rows}
    assert len(ids) == 3
    assert {i[1] for i in ids} == {"auction", "laft", "certificate"}


def test_texas_cause_number_is_not_the_property_key():
    a = {"state": "TX", "source": "auction", "harvester_source": "tx_lgbs", "county": "Bexar",
         "case_no": "04123-001-0040", "parcel": "2019-TD-1234", "tx_sale_status": "Scheduled for Auction"}
    b = dict(a, case_no="04123-001-0050")           # same cause, another account
    assert LR.property_key(a) != LR.property_key(b)
    assert LR.property_key(a) == ("TX", "bexar", "041230010040")


def test_no_parcel_means_no_cross_ledger_match():
    assert LR.property_key(_available(parcel="")) is None


def test_texas_sync_dedups_within_a_ledger_only():
    src = (ROOT / "scripts/sync-texas-to-supabase.py").read_text(encoding="utf-8")
    assert "deduped[(source, county, case_no)] = projected_row" in src
    assert "deduped[(county, case_no)]" not in src
    assert "LEDGER_RECORDS.problems(row)" in src


# ------------------------------------------------ 5. auction history preserved

def test_auction_events_writer_reads_auction_rows_only():
    src = (ROOT / "scripts/auction_events_writer.py").read_text(encoding="utf-8")
    assert 'r.get("source") != "auction"' in src


def test_an_available_read_never_closes_an_auction_row(tmp_path):
    p = tmp_path / "s.json"
    p.write_text(json.dumps([{"county": "Wayne", "source_id": LOTS, "status": "COMPLETE", "row_count": 1}]))
    units = SY.units_for(p)
    stored = [{"id": "auc", "state": "MI", "status": "active", "harvester_source": LOTS, "source": "auction",
               "county": "Wayne", "case_no": "A-1"},
              {"id": "lot", "state": "MI", "status": "active", "harvester_source": LOTS, "source": "laft",
               "county": "Wayne", "case_no": "L-GONE"}]
    closes = SY.plan_close("MI", [], stored, units, {LOTS})
    assert [c["id"] for c in closes] == ["lot"]


def test_auction_view_keeps_history_pointer_and_unpublished_result():
    v = LR.customer_view(_auction())
    assert v["history"].startswith("auction_events")
    assert v["result"] == LR.OUTCOME_NOT_PUBLISHED


# ------------------------------------------------ 6. no fabricated purchase URL

def test_list_page_is_never_a_purchase_link():
    row = _available(purchase_url="https://county.example/laft.pdf", list_url="https://county.example/laft.pdf")
    assert LR.customer_view(row)["purchase_link"] == LR.NO_PURCHASE_LINK


def test_document_page_and_http_are_never_purchase_links():
    assert LR.AvailableRecord(_available(purchase_url="https://c.example/d.pdf",
                                         document_url="https://c.example/d.pdf")).purchase_link is None
    assert LR.AvailableRecord(_available(purchase_url="http://c.example/buy")).purchase_link is None
    assert LR.customer_view(_available())["purchase_link"] == LR.NO_PURCHASE_LINK


def test_a_verified_link_is_kept():
    assert LR.customer_view(_available(purchase_url="https://c.example/apply/9"))["purchase_link"] == \
        "https://c.example/apply/9"


# ------------------------------------------------ 7. missing price reads "Not published"

def test_missing_amount_reads_not_published():
    v = LR.customer_view(_available())
    assert v["amount"] == LR.NOT_PUBLISHED
    assert v["application_instructions"] == LR.NOT_PUBLISHED


@pytest.mark.parametrize("kind", sorted(LR.NO_FIGURE_KINDS))
def test_no_figure_kinds_carry_no_amount(kind):
    row = _available(purchase_amount_kind=kind, bid=900)
    assert LR.AvailableRecord(row).amount is None
    assert LR.customer_view(row)["amount"] == LR.NOT_PUBLISHED
    assert LR.problems(_available(purchase_amount_kind=kind, purchase_amount=900))


def test_amount_without_kind_is_refused():
    assert any("kind is never assumed" in p for p in LR.problems(_available(purchase_amount=500)))


def test_opening_bid_is_never_labelled_a_price():
    v = LR.customer_view(_available(purchase_amount=500, purchase_amount_kind="OPENING_BID"))
    assert v["amount_label"] == "Opening bid"


# ------------------------------------------------ 8. opening bid is never a winning bid

def test_opening_bid_is_not_a_winning_bid():
    rec = LR.AuctionRecord(_auction())
    assert rec.opening_bid == 5400.0
    assert rec.winning_bid is None
    assert LR.customer_view(_auction())["winning_bid"] == LR.NOT_PUBLISHED


def test_winning_bid_only_from_a_published_sale():
    row = _auction(inventory_status="sold", inventory_status_basis="SOURCE_STATUS", result_amount=9100)
    assert LR.AuctionRecord(row).winning_bid == 9100
    assert LR.problems(_auction(inventory_status="auction_scheduled", result_amount=9100))


def test_not_published_kind_hides_the_legacy_bid():
    assert LR.AuctionRecord(_auction(purchase_amount_kind="NOT_PUBLISHED")).opening_bid is None


# ------------------------------------------------ 9. failure states

@pytest.mark.parametrize("entry,expected", [
    ({"status": "EMPTY", "row_count": 0, "empty_signal": "no properties"}, "EMPTY"),
    ({"status": "EMPTY", "row_count": 0}, "INCOMPLETE"),
    ({"status": "EMPTY", "row_count": 3, "empty_signal": "x"}, "INCOMPLETE"),
    ({"status": "EMPTY", "row_count": 0, "empty_signal": "x", "transport_ok": False}, "INCOMPLETE"),
    ({"status": "COMPLETE", "row_count": 4}, "COMPLETE"),
    ({"status": "COMPLETE", "row_count": 4, "parse_ok": False}, "INCOMPLETE"),
    ({"status": "FAILED", "error_category": "TRANSPORT_TIMEOUT"}, "SOURCE_UNAVAILABLE"),
    ({"status": "FAILED", "error_category": "PARSE_FORMAT_CHANGE"}, "FAILED"),
    ({"status": "INCOMPLETE"}, "INCOMPLETE"),
    ({"status": "???"}, "NOT_RUN"),
])
def test_reader_status(entry, expected):
    assert LH.reader_status(entry) == expected


@pytest.mark.parametrize("status", ["INCOMPLETE", "FAILED", "SOURCE_UNAVAILABLE", "NOT_RUN", None])
def test_nothing_closes_without_a_complete_read(status):
    for ledger in Ledger:
        assert not LH.closeable(ledger, status)


def test_a_false_empty_closes_nothing(tmp_path):
    p = tmp_path / "s.json"
    p.write_text(json.dumps([{"county": "Wayne", "source_id": LOTS, "status": "EMPTY", "row_count": 0}]))
    stored = [{"id": "lot", "state": "MI", "status": "active", "harvester_source": LOTS, "source": "laft",
               "county": "Wayne", "case_no": "L-1"}]
    assert SY.plan_close("MI", [], stored, SY.units_for(p), {LOTS}) == []


# ------------------------------------------------ 10. one ledger's failure never closes another's rows

def test_ledger_units_are_scoped_to_the_ledger():
    entries = [{"county": "Bexar", "source_id": "tx_realauction", "status": "COMPLETE", "row_count": 2},
               {"county": "Bexar", "source_id": "fl_lienhub_certificates", "status": "FAILED"}]
    assert LH.ledger_units(entries, Ledger.AUCTIONS) == {("tx_realauction", "Bexar"): "COMPLETE"}
    assert LH.ledger_units(entries, Ledger.LIENS_CERTIFICATES) == {("fl_lienhub_certificates", "Bexar"): "FAILED"}


def test_a_sibling_sources_complete_read_never_stands_in(tmp_path):
    # Only the lots source read; the programs source has no entry. Before,
    # the bare-county fallback was the worst of every entry (here COMPLETE),
    # so the programs rows could be closed by the lots read.
    p = tmp_path / "s.json"
    p.write_text(json.dumps([{"county": "Wayne", "source_id": LOTS, "status": "COMPLETE", "row_count": 1}]))
    units = SY.units_for(p)
    assert SY.unit_status(units, PROGRAMS, "Wayne") is None
    stored = [{"id": "prog", "state": "MI", "status": "active", "harvester_source": PROGRAMS, "source": "laft",
               "county": "Wayne", "case_no": "P-1"}]
    assert SY.plan_close("MI", [], stored, units, {LOTS, PROGRAMS}) == []


def test_source_less_files_keep_their_county_fallback(tmp_path):
    p = tmp_path / "s.json"
    p.write_text(json.dumps([{"county": "Wayne", "status": "COMPLETE", "row_count": 1}]))
    assert SY.unit_status(SY.units_for(p), LOTS, "Wayne") == "COMPLETE"


def test_domains_stay_isolated():
    domains.assert_isolated()


# ------------------------------------------------ 11. sync refuses misclassified rows

def test_sync_refuses_a_row_with_another_ledgers_fields(tmp_path):
    p = tmp_path / "s.json"
    p.write_text(json.dumps([{"county": "Wayne", "source_id": LOTS, "status": "COMPLETE", "row_count": 2}]))
    good = {"state": "MI", "source": "laft", "source_id": LOTS, "county": "Wayne", "case_no": "L1", "parcel": "L1",
            "status": "active"}
    bad = dict(good, case_no="L2", parcel="L2", issued_date="2025-01-01")
    sent, counts = SY.plan("MI", [good, bad], SY.registry_rows("MI"), SY.units_for(p))
    assert [r["case_no"] for r in sent] == ["L1"]
    assert counts["refused_ledger_contract"] == 1


# ------------------------------------------------ 12. permission gates unchanged

def test_blocked_vendors_feed_no_ledger_and_stay_denied():
    from harvesters.ledgers import ledgers_for_source_id
    for sid in ("tx_govease", "tx_pbfcm", "tx_mvba", "tx_ctsa"):
        assert ledgers_for_source_id(sid) == frozenset()
        assert not PERM.authorize(sid, "fetch", state="TX").allowed
    row = {"state": "TX", "source": "auction", "harvester_source": "tx_govease", "county": "Bexar", "case_no": "1"}
    assert ledger_for_row(row) is Ledger.AUCTIONS
    assert LR.problems(row) == []    # the vendor gate, not the ledger contract, refuses it


# ------------------------------------------------ 13. customer wording and contracts intact

def test_missing_value_wordings_match_the_frontend():
    js = (ROOT / "public/app.js").read_text(encoding="utf-8")
    assert LR.NO_PURCHASE_LINK in js
    assert f'"{LR.NOT_PUBLISHED}"' in js


def test_every_view_names_its_ledger_and_provenance():
    for row in (_auction(), _available(), _certificate()):
        v = LR.customer_view(dict(row, field_provenance={"parcel": {"source": "county_list"}}))
        assert v["ledger"] == LR.record_for_row(row).ledger.value
        assert v["provenance"]["fields_with_origin"] == ["parcel"]
        assert set(v["freshness"]) == {"last_read", "first_seen", "delisted_at", "list_as_of"}


def test_clean_rows_have_no_problems():
    for row in (_auction(), _available(), _certificate()):
        assert LR.problems(row) == []
    assert LR.problems({"county": "X"})          # unclassifiable is a problem, never a guess
