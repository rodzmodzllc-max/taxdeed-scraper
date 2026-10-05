"""Available amount semantics (2026-10-05, customer report Citrus 2024-0075TD).

The behaviour itself is exercised in the browser (tests/run_test.mjs,
`amountSemantics` / `acqP3*`). These checks pin the facts it rests on:
- the 54-row Florida composition the Playwright check renders;
- the frontend's addition list never re-adds what F.S. 197.502(6) puts inside
  the opening bid, and assumes no tax-year count;
- the county evidence rows the wording cites really say it;
- the statement capture never prints a personal token.
"""
from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APP = (ROOT / "public" / "app.js").read_text(encoding="utf-8")
FIX = json.loads((ROOT / "tests" / "python" / "fixtures" / "fl_available_partial_rows.json").read_text(encoding="utf-8"))


def _js_block(name: str) -> str:
    i = APP.index(f"var {name} = [")
    return APP[i:APP.index("];", i)]


def test_fl54_composition():
    assert sum(g["n"] for g in FIX["groups"]) == 54
    kinds = {g["kind"] for g in FIX["groups"]}
    assert kinds == {"OPENING_BID", "ORIGINAL_OPENING_BID", "MINIMUM_PURCHASE_AMOUNT"}
    partial = _js_block("PARTIAL_AMOUNT_KINDS")
    for k in kinds:
        assert f'"{k}"' in partial
    # Every one of the 54 rows' sources has source-aware terms that add items
    # on top of the opening bid and say what it already includes.
    sys.path.insert(0, str(ROOT))
    from harvesters.sources import available_terms as T
    terms = T.load()
    for g in FIX["groups"]:
        rows = [t for t in terms if t["state"] == "FL" and t["source_id"] == g["source_id"] and t["county"] in ("", g["county"])]
        assert rows, g
        best = max(rows, key=lambda t: bool(t["county"]))
        assert best["basis"] == "OPENING_BID_PLUS_ADDITIONS", g
        assert best["additions"] == "interest|omitted_taxes|doc_stamps|recording_fees" and best["included_in_figure"]


def test_additions_never_double_count():
    sys.path.insert(0, str(ROOT))
    from harvesters.sources import available_terms as T
    assert T.ADDITION_KEYS == ("interest", "omitted_taxes", "doc_stamps", "recording_fees")
    # What F.S. 197.502(6) already puts inside the opening bid is never an addition key.
    for inside in ("delinquent", "certificate", "current_taxes", "application_fee", "deposit", "homestead"):
        assert not any(inside in k for k in T.ADDITION_KEYS)
    # The known amount sums only the ADDITION keys the terms name, never every component.
    body = APP[APP.index("function acquisitionCostBreakdown(p)"):APP.index("function acquisitionForms(p)")]
    assert "ADDITION_LABELS[k]" in body and "Object.values(comps)" not in body
    js_keys = re.findall(r"^  ([a-z_]+): ", APP[APP.index("var ADDITION_LABELS = {"):APP.index("};", APP.index("var ADDITION_LABELS = {"))], re.M)
    assert tuple(js_keys) == T.ADDITION_KEYS


def test_no_tax_year_count_assumed():
    rows = (ROOT / "data" / "available_financial_terms.csv").read_text(encoding="utf-8")
    assert not re.search(r"two[- ]year|2 years", rows, re.I)
    block = APP[APP.index("var ADDITION_LABELS = {"):APP.index("function acquisitionCostBreakdown(p)")]
    assert not re.search(r"two[- ]year|2 years", block, re.I)


def test_opening_bid_never_called_purchase_price():
    labels = APP[APP.index("const AMOUNT_KIND_LABELS = {"):APP.index("};", APP.index("const AMOUNT_KIND_LABELS = {"))]
    assert 'OPENING_BID: "Opening bid"' in labels
    assert 'MINIMUM_PURCHASE_AMOUNT: "Minimum purchase amount"' in labels
    # The PR #82 regression: the old fallback that called any unlabelled
    # figure "Purchase price" is gone; only FIXED_PURCHASE_PRICE maps to it.
    info = APP[APP.index("function amountInfo(p)"):APP.index("function availableAmountLabel(p)")]
    assert info.count('label: "Purchase price"') == 1
    assert 'kind === "FIXED_PURCHASE_PRICE"' in info.split('label: "Purchase price"')[0].rsplit("\n", 1)[-1]


def test_fixed_price_wording_removed_from_customer_copy():
    for phrase in ("Lands Available - fixed price", "buy from the Clerk at a fixed price", "Lands Available list · fixed price"):
        assert phrase not in APP


def test_county_evidence_backs_the_wording():
    rows = {r["county"]: r for r in csv.DictReader(open(ROOT / "data" / "purchase_path_evidence.csv", encoding="utf-8"))
            if r["state"] == "FL"}
    duval = rows["Duval"]["instructions"]
    assert "the opening bid, subsequent omitted taxes, and any accrued interest" in duval
    assert "Documentary stamps and recording fees are also assessed" in duval
    assert "plus omitted years taxes" in rows["Orange"]["instructions"]


def test_capture_never_prints_personal_tokens():
    sys.path.insert(0, str(ROOT / "scripts"))
    import capture_pioneer_statements as cap  # noqa: E402
    out = cap.vocab_only("<td>LIST OF LANDS 12/01/2024</td><td>Jane Q Public 123 Main St Inverness</td>")
    assert "Jane" not in out and "Main" not in out and "Inverness" not in out and "123" not in out
    assert out.startswith("LIST OF LANDS 99/99/9999")
    assert cap.shape_after("Opening Bid $ 2,606.70", "Opening Bid") == "$ 9,999.99"
