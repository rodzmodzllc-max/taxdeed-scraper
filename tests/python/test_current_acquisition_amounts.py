"""Current acquisition amounts (2026-10-06): semantic type, time status, statements."""
import json
import re
from datetime import date
from pathlib import Path

import pytest

from harvesters.sources import amount_semantics as A

REPO = Path(__file__).resolve().parents[2]
CASES = json.loads((REPO / "tests/python/fixtures/amount_semantics_cases.json").read_text(encoding="utf-8"))
TODAY = date.fromisoformat(CASES["today"])
APP = (REPO / "public/app.js").read_text(encoding="utf-8")


@pytest.mark.parametrize("case", CASES["rows"], ids=lambda c: c["name"])
def test_row_vectors(case):
    assert A.semantic_type(case["row"]) == case["semantic"]
    assert A.temporal_status(case["row"], TODAY)[0] == case["temporal"]


@pytest.mark.parametrize("case", CASES["statements"], ids=lambda c: c["name"])
def test_statement_vectors(case):
    r = A.parse_statement_text(case["text"], rights_status=case["rights"], document_url="https://clerk.example.gov/s.pdf",
                               publisher="Clerk", observed_on="2026-10-01", today=TODAY)
    assert r["status"] == case["status"], r
    st = r["statement"]
    assert (st["total_due"] if st else None) == case["total"]
    if "valid_through" in case:
        assert st["valid_through"] == case["valid_through"]
    if "components" in case:
        assert st["components"] == case["components"]
    if "expired" in case:
        assert r["expired"] is case["expired"]
    if "displayable" in case:
        assert r["displayable"] is case["displayable"]


def test_no_semantic_type_is_a_price_unless_the_source_says_so():
    for kind in ("OPENING_BID", "ORIGINAL_OPENING_BID", "MINIMUM_PURCHASE_AMOUNT", "ESTIMATED_PURCHASE_PRICE",
                 "PUBLISHED_AMOUNT_KIND_UNSPECIFIED"):
        assert A.semantic_type({"purchase_amount": 1, "purchase_amount_kind": kind}) != "CURRENT_PURCHASE_PRICE", kind
    assert A.semantic_type({"purchase_amount": 1, "purchase_amount_kind": "FIXED_PURCHASE_PRICE"}) == "CURRENT_PURCHASE_PRICE"


def test_values_never_become_amounts_or_taxes():
    src = (REPO / "harvesters/sources/amount_semantics.py").read_text(encoding="utf-8")
    code = "\n".join(l for l in src.splitlines() if not l.strip().startswith("#") and '"""' not in l)
    for col in ("assessed", "market", "taxable_value", "just_value"):
        assert f'"{col}"' not in code, col


def test_components_are_never_summed_into_a_total():
    # Components without a printed total: no statement, never a computed one.
    r = A.parse_statement_text("Taxes $500.00\nInterest $45.12", rights_status="PERMITTED", document_url="", publisher="",
                               observed_on="", today=TODAY)
    assert r["status"] == "FAILED" and r["statement"] is None


def test_money_record_carries_provenance():
    row = {"source_id": "pa_fayette_repository", "purchase_amount": 500, "purchase_amount_kind": "OPENING_BID",
           "list_url": "https://www.fayettecountypa.org/930/Repository-Sale", "list_as_of": "2026-09-01",
           "last_seen_at": "2026-10-04T12:00:00Z"}
    m = A.money_record(row, TODAY)
    assert m["semantic_type"] == "OPENING_BID" and m["temporal"] == "CURRENT" and m["direct"] is True
    assert m["source_url"].startswith("https://") and m["source_date"] == "2026-09-01" and m["last_read"]


def _js_obj(name):
    return dict(re.findall(r"(\w+): \"([^\"]+)\"", re.search(r"var " + name + r" = \{(.*?)\n?\};", APP, re.S).group(1)))


def test_js_mirrors_python_labels_and_kinds():
    assert _js_obj("AMOUNT_SEMANTIC_LABELS") == A.SEMANTIC_LABELS
    assert _js_obj("AMOUNT_TEMPORAL_LABELS") == A.TEMPORAL_LABELS
    assert _js_obj("AMOUNT_KIND_SEMANTIC") == A.KIND_SEMANTIC
    assert re.search(r"var AMOUNT_FRESH_DAYS = (\d+);", APP).group(1) == str(A.FRESH_DAYS)
    assert re.search(r"var AMOUNT_LIST_STALE_DAYS = (\d+);", APP).group(1) == str(A.LIST_STALE_DAYS)
