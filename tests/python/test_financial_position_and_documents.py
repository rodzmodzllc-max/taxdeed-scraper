"""Financial position and acquisition documents (2026-10-05).

The Python rules are the reference. ``public/app.js`` mirrors them, and
``tests/run_test.mjs`` runs the same vectors in the browser.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from harvesters.sources import acquisition_documents as ad
from harvesters.sources import available_terms
from harvesters.sources import financial_position as fp

REPO = Path(__file__).resolve().parents[2]
APP = (REPO / "public/app.js").read_text(encoding="utf-8")
FP_CASES = json.loads((REPO / "tests/python/fixtures/financial_position_cases.json").read_text())["cases"]
DOC_CASES = json.loads((REPO / "tests/python/fixtures/acquisition_documents_cases.json").read_text())["cases"]


def _js_object_keys(name: str) -> set[str]:
    body = re.search(r"var %s = \{(.*?)\};" % name, APP, re.S).group(1)
    return set(re.findall(r"(?:^|[\s,{])([a-z_A-Z]+):", body))


def test_vectors_match_the_python_rules():
    for c in FP_CASES:
        assert fp.position(c["amount"], c["terms"], c["statement"]) == c["expected"], c["name"]
    for c in DOC_CASES:
        assert ad.classify(c["url"], c["role"], c.get("kind")) == c["expected"], c["name"]


def test_a_current_statement_is_the_total_and_its_parts_are_never_added_again():
    c = next(c for c in FP_CASES if c["name"] == "fl_current_statement_no_double_count")
    out = c["expected"]
    assert out["total"]["amount"] == c["statement"]["total"] == out["acquisition"]["value"]
    parts = sum(l["amount"] for g in ("taxes", "interest", "fees", "other") for l in out[g])
    assert round(parts, 2) == c["statement"]["total"]          # the parts ARE the total
    assert all(l["status"] == "included" for g in ("taxes", "interest", "fees", "other") for l in out[g])
    assert out["known_tax_obligation"] == round(2100.5 + 980.12, 2)   # taxes + interest only, never fees


def test_an_opening_bid_is_never_a_total_and_additions_carry_no_invented_amount():
    for name in ("fl_opening_bid_no_statement", "realtdm_base_price"):
        out = next(c for c in FP_CASES if c["name"] == name)["expected"]
        assert out["total"]["amount"] is None and out["acquisition"]["authoritative"] is False
        added = [l for g in ("taxes", "interest", "fees") for l in out[g] if l["status"] == "added_not_published"]
        assert added and all(l["amount"] is None for l in added)
        assert out["known_tax_obligation"] is None


def test_costs_and_deposits_are_separate_and_never_in_a_total():
    la = next(c for c in FP_CASES if c["name"] == "la_offer_negotiated_advanced_costs")["expected"]
    assert la["application_costs"]["in_price"] == "no" and la["total"]["amount"] is None
    tx = next(c for c in FP_CASES if c["name"] == "tx_minimum_bid_deposit_unknown")["expected"]
    assert tx["deposit"]["in_price"] == "unknown" and tx["acquisition"]["value"] == 4500 and tx["total"]["amount"] is None


def test_no_value_column_ever_reaches_the_financial_position():
    src = (REPO / "harvesters/sources/financial_position.py").read_text()
    code = re.sub(r'"""[\s\S]*?"""', "", src)
    for col in ("assessed", "market", "taxable_value", "land_value"):
        assert col not in code, col
    block = APP[APP.index("function financialPositionCore"):APP.index("function financialPositionHtml")]
    for col in ("assessed", "market", "taxable_value", "land_value", "marketOf"):
        assert col not in block, col


def test_every_terms_addition_key_has_a_group_and_label_in_both_languages():
    for k in available_terms.ADDITION_KEYS:
        assert k in fp.LABELS
    assert _js_object_keys("FP_LABELS") == set(fp.LABELS)
    assert _js_object_keys("ACQ_DOC_LABELS") == set(ad.CLASSES)


def test_a_pdf_is_never_a_purchase_link():
    for role, kind in (("purchase_url", "online_purchase"), ("path_url", "direct_property_url"), ("path_url", "application_page")):
        assert ad.classify("https://x.gov/a.pdf", role, kind) == "FORM"
        assert ad.classify("https://x.gov/DocumentCenter/View/1/Form", role, kind) == "FORM"
    assert ad.classify("http://x.gov/list", "list_url") is None


def test_detail_page_places_money_after_acquire_and_documents_after_source_truth():
    i = APP.index("${acquireBlockHtml(p)}\n    ${financialPositionHtml(p)}")
    j = APP.index("${sourceTruthHtml(p)}\n    ${acquisitionDocumentsHtml(p)}")
    assert 0 < i < j
