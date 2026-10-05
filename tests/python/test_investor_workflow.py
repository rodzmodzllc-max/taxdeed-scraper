"""Understood search, saved-search duplicate, research queue, coverage
explorer and the About section (2026-10-05) - static checks; the behaviour
is exercised by tests/run_test.mjs."""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
APP = (REPO / "public" / "app.js").read_text(encoding="utf-8")
M024 = (REPO / "scripts" / "migrations" / "024_customer_monitoring_foundation.sql").read_text(encoding="utf-8")


def _body(start: str, end: str) -> str:
    return APP[APP.index(start):APP.index(end, APP.index(start))]


def test_new_usage_events_are_allowed_by_024():
    # An event 024's CHECK refuses would switch tracking off for the session.
    for ev in re.findall(r'track\("([a-z_]+)"', APP):
        assert f"'{ev}'" in M024, ev


def test_parser_is_rules_only():
    body = _body("function parseNaturalQuery(", "function nqStructured(")
    assert "fetch(" not in body and "sb." not in body
    assert not re.search(r"\b(llm|openai|anthropic|model)\b", body, re.I)


def test_understood_search_uses_the_lists_own_filters():
    body = _body("function applyNaturalQuery(", "(function bindGlobalSearch()")
    assert "bindBidRangeSliders.apply" in body
    assert 'state.acqState = nq.verified ? "verified" : "any"' in body
    assert "state.counties = new Set(" in body


def test_numbered_query_stays_plain():
    assert "out.plain = true" in _body("function parseNaturalQuery(", "function nqStructured(")


def test_research_queue_never_ranks():
    body = _body("function researchItemsFor(", "function renderBidListModal(")
    assert ".sort(" not in body
    assert not re.search(r"\b(score|rating|priority)\b", body, re.I)


def test_coverage_explorer_never_claims_nothing_for_sale():
    body = _body("function coverageExplorerHtml(", "function renderStatePicker(")
    assert "not a statement that nothing is for sale" in body


def test_why_section_on_every_state_page():
    for page in sorted((REPO / "public").glob("*.html")):
        text = page.read_text(encoding="utf-8")
        if 'id="helpModal"' not in text:
            continue
        assert 'id="whyList"' in text, page.name
        lower = text.lower()
        for name in ("handson", "hands-on tax", "parcel fair", "taxsale.com"):
            assert name not in lower, (page.name, name)


def test_duplicate_saved_search_keeps_criteria():
    body = _body("} else if (t.dataset.ssDuplicate) {", "} else if (t.dataset.ssDelete) {")
    assert "JSON.parse(JSON.stringify(s.criteria" in body
