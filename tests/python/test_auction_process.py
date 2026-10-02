"""Auction sale-process engine + apply step (cross-state enrichment sprint,
2026-10-02): county-level, evidence-only, fill-blank sale dates, never a
lifecycle field, and the shipped evidence table is valid."""
import csv
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import apply_auction_process as A  # noqa: E402
import auction_process_engine as E  # noqa: E402

APP = (ROOT / "public" / "app.js").read_text(encoding="utf-8")


def _write(tmp_path, rows):
    p = tmp_path / "ev.csv"
    with open(p, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=E.COLUMNS)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in E.COLUMNS})
    return p


BASE = {"state": "FL", "source_id": "fl_realauction", "county": "Lee", "method": "online", "platform_url": "https://lee.realtaxdeed.com/",
        "deposit": "5% of the bid amount", "phone": "239-000-0000", "evidence_url": "https://www.leeclerk.org/tax-deeds",
        "evidence_type": "county_page", "source_title": "Tax Deed Sales", "observed_on": "2026-10-02", "review_state": "verified",
        "enabled": "yes", "steps": "Register on the sale site | Pay the deposit before bidding"}


def test_shipped_evidence_table_loads_and_every_enabled_row_is_verified():
    rows = E.load()
    assert rows, "the sprint ships verified county sale processes"
    for r in rows:
        if r.enabled:
            assert r.review_state == "verified" and r.evidence_url.startswith("https://") and re.match(r"^\d{4}-\d{2}-\d{2}$", r.observed_on)


def test_record_carries_only_published_fields_and_is_county_scope(tmp_path):
    [r] = E.load(_write(tmp_path, [BASE]))
    rec = E.record(r)
    assert rec["scope"] == "county" and rec["method"] == "online" and rec["method_label"] == "Online auction"
    assert rec["deposit"] == "5% of the bid amount" and rec["steps"] == ["Register on the sale site", "Pay the deposit before bidding"]
    assert "sale_time" not in rec and "payment_deadline" not in rec and "sale_date" not in rec      # not published -> absent
    assert set(rec) <= set(E.RECORD_KEYS)
    assert E.complete(rec)


def test_validation_refuses_unverified_enabled_rows_bad_dates_and_http(tmp_path):
    for bad in ({"review_state": "captured"}, {"evidence_url": "http://x.gov/"}, {"sale_date": "10/06/2026"},
                {"sale_date_applies": "yes"}, {"platform_url": "http://lee.realtaxdeed.com/"}, {"method": "lottery"}):
        with pytest.raises(ValueError):
            E.load(_write(tmp_path, [{**BASE, **bad}]))


def test_resolve_prefers_county_row_and_ignores_disabled(tmp_path):
    rows = E.load(_write(tmp_path, [{**BASE, "county": "*", "deposit": "state-wide"}, BASE, {**BASE, "county": "Polk", "enabled": "no"}]))
    assert E.resolve(rows, state="FL", source_id="fl_realauction", county="Lee").values["deposit"] == "5% of the bid amount"
    assert E.resolve(rows, state="FL", source_id="fl_realauction", county="Polk").values["deposit"] == "state-wide"
    assert E.resolve(rows, state="TX", source_id="tx_realauction", county="Lee") is None


def test_plan_row_writes_process_only_and_keeps_other_provenance(tmp_path):
    rows = E.load(_write(tmp_path, [BASE]))
    stored = {"source_match": {"identifier": "case_no", "value": "X"}, "auction_process": {"scope": "county", "deposit": "old"}}
    body, outcome = A.plan_row({"id": "1", "state": "FL", "county": "Lee", "source": "auction", "source_id": "fl_realauction",
                                "status": "active", "sale_date": "2026-10-20", "otc_provenance": stored}, rows, now="t")
    assert outcome == "process" and set(body) == {"otc_provenance"}
    assert body["otc_provenance"]["source_match"] == stored["source_match"]
    assert body["otc_provenance"]["auction_process"]["deposit"] == "5% of the bid amount"   # replaced, never mixed


def test_plan_row_never_touches_gone_rows_or_lifecycle_fields(tmp_path):
    rows = E.load(_write(tmp_path, [BASE]))
    assert A.plan_row({"state": "FL", "county": "Lee", "status": "closed"}, rows, now="t") == (None, "not_active")
    body, _ = A.plan_row({"state": "FL", "county": "Lee", "status": "active", "source_id": "fl_realauction"}, rows, now="t")
    assert not {"status", "last_seen_at", "bid", "min_bid", "owner_name", "inventory_status"} & set(body)


def test_sale_date_fills_a_blank_only_when_the_page_states_it_for_the_current_list(tmp_path):
    ev = {**BASE, "state": "MI", "source_id": "mi_lenawee_tax_sale", "county": "Lenawee", "sale_date": "2026-10-06", "sale_date_applies": "yes"}
    rows = E.load(_write(tmp_path, [ev]))
    row = {"id": "1", "state": "MI", "county": "Lenawee", "status": "active", "source_id": "mi_lenawee_tax_sale", "sale_date": None}
    body, outcome = A.plan_row(row, rows, now="2026-10-02T00:00:00+00:00")
    assert outcome == "process_and_sale_date" and body["sale_date"] == "2026-10-06"
    assert body["field_provenance"]["sale_date"]["evidence_url"] == BASE["evidence_url"]
    body2, _ = A.plan_row({**row, "sale_date": "2026-10-07"}, rows, now="t")                 # a stored date is never replaced
    assert "sale_date" not in body2


def test_a_future_sale_is_county_information_never_a_row_sale_date(tmp_path):
    ev = {**BASE, "state": "WY", "source_id": "wy_albany_tax_sale", "county": "Albany", "next_sale_date": "2027-08-13"}
    rows = E.load(_write(tmp_path, [ev]))
    body, outcome = A.plan_row({"id": "1", "state": "WY", "county": "Albany", "status": "active", "source_id": "wy_albany_tax_sale",
                                "sale_date": None}, rows, now="t")
    assert outcome == "process" and "sale_date" not in body
    assert body["otc_provenance"]["auction_process"]["next_sale_date"] == "2027-08-13"


def test_frontend_reads_the_same_record_keys():
    m = re.search(r"const AUCTION_PROCESS_KEYS = \[(.*?)\];", APP, re.S)
    assert m and set(re.findall(r'"(\w+)"', m.group(1))) == set(E.RECORD_KEYS)
    body = APP[APP.index("function auctionProcessHtml"):APP.index("function typedPurchasePath")]
    assert "purchase path" not in body.lower() and "County-level guidance" in body
