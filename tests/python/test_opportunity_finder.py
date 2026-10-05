"""Opportunity finder + auction command center (2026-10-05): static contracts
on the shipped frontend. Behaviour is exercised by tests/run_test.mjs
(finder*, commandCenter*)."""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
APP = (REPO / "public/app.js").read_text(encoding="utf-8")
EVIDENCE_SORTS = ("pathFirst", "amountFirst", "readRecent")


def _block(start: str, end: str) -> str:
    return APP[APP.index(start):APP.index(end)]


def test_evidence_sorts_are_single_criterion_comparators_with_options_on_every_page():
    for name in EVIDENCE_SORTS:
        assert f'{name}: (a, b) => evidenceSortKey("{name}", a) - evidenceSortKey("{name}", b)' in APP
    pages = sorted(p for p in (REPO / "public").glob("*.html") if 'id="sortBy"' in p.read_text(encoding="utf-8"))
    assert len(pages) >= 3
    for page in pages:
        html = page.read_text(encoding="utf-8")
        for sel in ("sortBy", "sortSecondary"):
            seg = html[html.index(f'id="{sel}"'):]
            seg = seg[:seg.index("</select>")]
            for name in EVIDENCE_SORTS:
                assert f'value="{name}"' in seg, (page.name, sel, name)


def test_sort_key_cache_is_a_var_and_reset_per_sort():
    # render() reaches sortRows() during module init: a let/const here would be
    # in its temporal dead zone.
    assert "var SORT_KEY_CACHE = new Map();" in APP
    sort_rows = _block("function sortRows(rows) {", "// ==================== county grouping")
    assert "SORT_KEY_CACHE = new Map();" in sort_rows


def test_badges_are_facts_with_no_score_or_weighting():
    block = _block("// ==================== opportunity finder: record evidence", "function card(p, showCounty) {")
    keys = re.findall(r'key: "([a-z]+)"', block)
    assert keys == ["path", "official", "amount", "fresh", "dated"]
    code = re.sub(r"^\s*//.*$", "", block, flags=re.M)
    assert not re.search(r"\b(score|rank|weight|grade|rating|recommend)\w*", code, re.I)
    # A verified path comes from acquisitionOf(), never from the list page.
    assert "acquisitionOf(p)" in block and "a.mode !== \"none\"" in block
    # An expired clerk statement is never a published amount.
    assert 'ai.state !== "official_expired"' in block
    # Shown on both card kinds.
    assert APP.count("${recordBadgesHtml(p)}") == 2


def test_command_center_uses_only_row_fields_and_invents_no_sale_terms():
    block = _block("var COMMAND_CENTER_DAYS", "function section(container, title, sub, rows, kind) {")
    # The only link is what the rows publish.
    assert "auctionLinkInfo(p)" in block and 'l.kind === "sale" || l.kind === "county"' in block
    code = re.sub(r"^\s*//.*$", "", block, flags=re.M)
    assert not re.search(r"deposit|registration|bidder", code, re.I)
    assert 'data-action="countyintel"' in block and 'data-action="dossierlist"' in block
