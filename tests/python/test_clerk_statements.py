"""Clerk purchase statement harvester (scripts/harvest_clerk_statements.py).

Offline: every statement here is SYNTHETIC text shaped like the OCR of the
Citrus "List of Lands" statement. Nothing contacts a clerk or a database.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import harvest_clerk_statements as h  # noqa: E402

TEXT = (ROOT / "tests/python/fixtures/clerk_statements/citrus_synthetic.txt").read_text(encoding="utf-8")


def test_verified_statement_reads_the_printed_total_and_date():
    p = h.parse_statement(TEXT, h.CITRUS)
    assert p.status == "VERIFIED"
    assert p.total_due == 27689.42
    assert p.valid_through == "2026-08-31"
    c = {k: v for k, v in p.components.items() if k != "printed_lines"}
    assert c == {"opening_bid": 2606.70, "interest": 811.44, "omitted_taxes": 24010.98, "doc_stamps": 192.10, "recording_fees": 68.20}
    # The OCR artefacts lost: the $-read-as-8 total and the doc-stamp rate.
    assert p.components["printed_lines"]["la_total"] == 27429.12


def test_total_is_the_clerks_never_our_sum():
    # The record carries the PRINTED total; the sum only gates acceptance.
    p = h.parse_statement(TEXT, h.CITRUS)
    rec = h.statement_record(p, county="Citrus", case_no="2099-0001TD", document_url="https://example.invalid/Home/Image/1",
                             observed_on="2026-09-29", publisher=h.CITRUS.publisher, docket_label="LOL 9/99/9999", statement_date="2026-07-15")
    assert rec["total_due"] == 27689.42 and rec["valid_through"] == "2026-08-31"
    assert rec["publisher"].startswith("Citrus County Clerk") and rec["document_url"].endswith("/Image/1")
    assert rec["observed_on"] == "2026-09-29" and rec["case_no"] == "2099-0001TD"


def test_misread_digit_is_never_a_figure():
    bad = TEXT.replace("$811.44", "$811.49")            # OCR misreads one digit
    p = h.parse_statement(bad, h.CITRUS)
    assert p.status == "OCR_UNVERIFIED" and p.total_due is None
    with pytest.raises(ValueError):
        h.statement_record(p, county="Citrus", case_no="x", document_url="u", observed_on="d", publisher="p", docket_label="l", statement_date=None)


def test_missing_line_or_total_is_not_verified():
    assert h.parse_statement(TEXT.replace("DEED RECORDING FEE", "DEED REC0RDING FEE"), h.CITRUS).status == "OCR_UNVERIFIED"
    # An older statement with no 'Total Due from Purchaser' line gives no figure.
    assert h.parse_statement(TEXT.replace("TOTAL DUE FROM PURCHASER", "T0TAL DUE"), h.CITRUS).status == "NO_TOTAL"
    assert h.parse_statement("RETURNED MAIL - nothing here", h.CITRUS).status == "NO_LABELS"


def test_no_double_count_omitted_years_use_the_total_line_only():
    # Per-year "Omitted Taxes" lines are inside "Total Omitted Taxes"; only
    # the total line is a component, so the years are never added twice.
    p = h.parse_statement(TEXT, h.CITRUS)
    assert p.components["omitted_taxes"] == 24010.98
    adds = [p.components[k] for k in ("opening_bid", "interest", "omitted_taxes", "doc_stamps", "recording_fees")]
    assert round(sum(adds), 2) == p.total_due


def test_ambiguous_ocr_is_refused():
    # Two different printed totals that each satisfy the chain -> refuse.
    amb = TEXT + "\nTOTAL DUE FROM PURCHASER         $27,689.42\nLESS PREPAID RECORDING FEES      $20.00\n"
    assert h.parse_statement(amb, h.CITRUS).status == "VERIFIED"   # duplicates of the same value are fine
    # Two readings that are each internally consistent but give different
    # totals (less $20 -> 27,689.42; less $30 -> 27,679.42): refused.
    amb2 = TEXT + "\nLESS PREPAID RECORDING FEES      $30.00\nTOTAL DUE FROM PURCHASER         $27,679.42\n"
    assert h.parse_statement(amb2, h.CITRUS).status == "AMBIGUOUS"


def test_expiry_and_history_ordering():
    assert h.is_expired("2026-08-31", date(2026, 10, 5)) is True
    assert h.is_expired("2099-12-31", date(2026, 10, 5)) is False
    assert h.is_expired(None, date(2026, 10, 5)) is None
    old = {"statement_date": "2026-03-01", "valid_through": "2026-03-31", "total_due": 26000.0}
    new = {"statement_date": "2026-07-15", "valid_through": "2026-08-31", "total_due": 27689.42}
    cur, hist = h.order_statements([old, new])
    assert cur is new and hist == [old]        # newer replaces, older kept


def test_only_verified_counties_are_read():
    assert set(h.CONFIGS) == {"Citrus"} and h.CITRUS.enabled
    for county in ("Duval", "Palm Beach", "Levy", "Bay", "Hernando"):
        assert county in h.NOT_VERIFIED and county not in h.CONFIGS


def test_report_is_value_free():
    res = {"observed_on": "2026-10-05", "counties": {"Citrus": {"status": "READ", "rows": 5, "with_statement_docs": 5,
           "statuses": {"VERIFIED": 3}, "current": 0, "expired": 3}},
           "statements": [{"county": "Citrus", "case_no": "2024-0075TD", "purchase_statement": {"total_due": 27689.42, "valid_through": "2026-08-31",
                           "components": {"opening_bid": 2606.7}}, "purchase_statement_history": []}]}
    out = h.report(res)
    assert "27689" not in out and "27,689" not in out and "2606" not in out
    assert "2024-0075TD" not in out and "9999-9999TD" in out


def test_harvester_writes_no_database():
    src = (ROOT / "scripts/harvest_clerk_statements.py").read_text(encoding="utf-8")
    for forbidden in ("SUPABASE", "service_role", "/rest/v1", ".patch(", ".post(", "upsert"):
        assert forbidden not in src


def test_an_older_verified_statement_is_never_current():
    old = {"statement_date": "2026-07-15", "valid_through": "2026-08-31", "total_due": 27689.42}
    # The docket's newest statement (2026-09-20) did not verify: nothing is current.
    cur, hist = h.current_and_history([old], "2026-09-20")
    assert cur is None and hist == [old]
    cur, hist = h.current_and_history([old], "2026-07-15")
    assert cur is old and hist == []
