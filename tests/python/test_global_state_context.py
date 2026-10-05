"""Global state context (2026-09-30): one state selector in the shared header.

What these pin (the browser behaviour - Florida -> Texas across Dashboard,
List, Map and Watchlist, refresh, deep links, phone layout - is exercised by
tests/run_test.mjs's gs* checks):

  * both state pages ship exactly one state control, #stateSelect, inside the
    header next to the account badge - no List region tabs, no Map state
    select, no "State:" badge on the Map context line;
  * its options come from STATE_META (the table tests/python/
    test_unified_navigation.py pins to states.PRODUCTION_STATES), never a
    second hard-coded list;
  * the state is one value, PAGE_STATE, and the data really follows it: the
    rows come from get_properties(p_state: PAGE_STATE);
  * a switch carries the route but not a property id, and the watchlist is
    filtered, never mutated, by the state.
"""
from __future__ import annotations

import re
from pathlib import Path

from harvesters.governance import states

REPO = Path(__file__).resolve().parents[2]
APP = (REPO / "public/app.js").read_text(encoding="utf-8")
PAGES = {name: (REPO / "public" / name).read_text(encoding="utf-8") for name in ("index.html", "tx.html")}


def test_g01_one_state_control_in_the_header_beside_the_account_badge():
    for name, html in PAGES.items():
        header = html[html.index('<div class="topbar">'):html.index('<div class="account-menu"')]
        assert re.search(r'<label class="state-switch"[^>]*>\s*<select id="stateSelect" aria-label="State"></select>\s*</label>\s*<div class="account" id="account">', header), name
        assert html.count('aria-label="State"') == 1, name                     # nothing competes with it
        for gone in ('id="regionTabs"', "data-state-link", 'id="mapStateSelect"', 'id="mapContextState"'):
            assert gone not in html, (name, gone)
        # The bottom bar stays four destinations; the state is not a fifth.
        bottom = re.search(r'<nav class="nav-bottom".*?</nav>', html, re.S).group(0)
        assert re.findall(r'data-page="([a-z]+)"', bottom) == ["dashboard", "list", "map", "watchlist"], name


def test_g02_options_come_from_the_one_state_registry():
    block = APP[APP.index("function buildStateSelect"):APP.index("buildStateSelect();")]
    assert "STATE_CODES.map(st =>" in block and "STATE_META[st].name" in block
    assert "Florida" not in block and "Texas" not in block and '"FL"' not in block
    meta = re.search(r"const STATE_META = \{(.*?)\n\};", APP, re.S).group(1)
    assert set(re.findall(r"^\s+([A-Z]{2}): \{", meta, re.M)) == set(states.PRODUCTION_STATES)
    # One state variable: PAGE_STATE, set once from the page; no other state store.
    assert APP.count("const PAGE_STATE = ") == 1
    assert "localStorage.setItem(\"tdw-state" not in APP and "sessionStorage.setItem(\"tdw-state" not in APP


def test_g03_the_data_follows_the_selected_state_not_just_a_label():
    assert 'sb.rpc(LIST_RPC, { p_state: PAGE_STATE, p_ledger_type: ledgerType, p_limit: PROPERTY_PAGE_SIZE, p_offset: offset })' in APP          # paged per ledger, always the page's state
    assert "if (regionOf(p) !== PAGE_STATE) return false;" in APP                 # List / Map guard
    # The Map context line no longer repeats the state.
    ctx = APP[APP.index("function renderMapContext"):APP.index("function renderMapContext") + 600]
    assert "mapContextState" not in ctx and "STATE_INFO.name" not in ctx


def test_g04_a_switch_carries_the_route_but_never_a_property_id():
    block = APP[APP.index("function stateSwitchHash"):APP.index("function syncStateLinks")]
    assert 'if (r && r.page === "list" && r.pid) return "#/" + (LEDGERS[r.ledger] || LEDGERS.auction).slug;' in block
    assert 'return location.hash || "";' in block
    assert "location.href = stateSwitchHref(st);" in APP
    assert 'if (!STATE_META[st] || st === PAGE_STATE) return;' in APP


def test_g05_watchlist_is_filtered_by_state_never_mutated():
    block = APP[APP.index("function renderBidListModal"):APP.index("function openBidList")]
    # 2026-10-05: saved items not in this state's data are named (when this browser saw them here) or counted
    assert "const missingIds = BIDLIST_ORDER.filter(id => !ALL.some(p => p.id === id));" in block
    assert 'id="savedMissing"' in block
    assert 'id="bidListElsewhere"' in block
    for write in (".delete(", ".insert(", ".update(", "BIDLIST.delete(", "BIDLIST_ORDER.splice("):
        assert write not in block, write
