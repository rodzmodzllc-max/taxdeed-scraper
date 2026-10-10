"""Unified navigation (2026-09-30): four primary destinations, ledgers inside
List and Map, data-driven states, compatibility routes. Static contracts on
the shipped frontend; the behaviour itself is exercised by tests/run_test.mjs."""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from harvesters.governance import states  # noqa: E402

APP = (REPO / "public/app.js").read_text(encoding="utf-8")
CODE = re.sub(r"^\s*//.*$", "", APP, flags=re.M)      # app.js without its line comments
INDEX = (REPO / "public/index.html").read_text(encoding="utf-8")
TX = (REPO / "public/tx.html").read_text(encoding="utf-8")


def _nav_pages(html: str, cls: str) -> list[str]:
    return re.findall(r'class="%s[^"]*" data-page="([a-z]+)"' % cls, html)


def test_n01_shell_navigation_pages_ledger_entries_and_actions_on_both_pages():
    # Shell redesign (2026-10-04). The rail routes four pages (Home =
    # dashboard, Search = list, Watchlist, Map), carries one entry per ledger
    # (data-nav-ledger, never data-page + data-ledger - a ledger is still not a
    # page of its own: it opens the List on that ledger), and three actions
    # (Saved Searches, States & Counties, About). The phone bar routes the
    # same four pages plus the account menu.
    for html in (INDEX, TX):
        # Identity redesign (2026-10-05): product navigation (Home, Search, the
        # ledgers, Map) and utility links (Saved Searches, Watchlist, County
        # Intelligence, About) are two lists - the same buttons.
        assert _nav_pages(html, "nav-item") == ["dashboard", "list", "map", "watchlist"]
        assert _nav_pages(html, "nav-bottom-item") == ["dashboard", "list", "map", "watchlist"]
        assert re.findall(r'class="nav-item nav-ledger" data-nav-ledger="([a-z]+)"', html) == ["laft", "auction", "certificate"]
        assert re.findall(r'class="nav-item" data-nav="([a-z]+)"', html) == ["saved", "states", "about"]
        assert 'id="navBottomAccount"' not in html and 'id="navSettingsBtn"' in html and 'aria-controls="accountMenu"' in html  # Remediation: one account entry per width (badge + rail foot)
        assert not re.search(r'class="nav-(bottom-)?item[^"]*" data-page="[a-z]+" data-ledger=', html)
        assert "Liens &amp; Certs<" not in html                      # the full ledger name only
        # The admin entry is hidden until the server profile says admin.
        assert '<a class="nav-item" id="navAdminLink" href="admin.html" hidden>' in html
    # Both pages ship the same navigation markup (a state's own ledger name is
    # written by app.js from ledgerCopy(key).nav).
    rail = lambda h: re.search(r'<div class="nav-list nav-primary">.*?</div>\n<div class="nav-list nav-secondary">.*?</div>\n', h, re.S).group(0)  # noqa: E731
    bottom = lambda h: re.search(r'<nav class="nav-bottom".*?</nav>', h, re.S).group(0)  # noqa: E731
    assert rail(INDEX) == rail(TX) and bottom(INDEX) == bottom(TX)
    assert "function syncLedgerNavNames()" in APP and "ledgerCopy(k).nav" in APP


def test_n02_ledger_selector_lives_inside_the_list_page_and_names_all_three_ledgers():
    # Texas's third slot keeps its own existing name (Redeemable Deeds - the
    # ledgerCopy() tx override); no Texas certificate ledger is invented.
    for html, cert_label in ((INDEX, "Liens &amp; Certificates"), (TX, "Redeemable Deeds")):
        page = html[html.index('id="pageList"'):html.index('id="pageMap"')]
        assert 'id="ledgerTabs"' in page and 'id="regionTabs"' not in page      # the state is the header's #stateSelect
        assert [m for m in re.findall(r'class="ledger-tab" data-ledger="([a-z]+)"', page)] == ["auction", "laft", "certificate"]
        assert 'id="tabCountCertificate"' not in page  # Remediation: the tab label carries no repeated count; the nav shows it once


def test_n03_map_page_carries_state_ledger_county_context_and_selectors():
    for html, cert_label in ((INDEX, "Liens &amp; Certificates"), (TX, "Redeemable Deeds")):
        page = html[html.index('id="pageMap"'):]
        assert 'id="mapCountySelect"' in page and 'id="mapLedgerPills"' in page
        assert 'id="mapStateSelect"' not in page and 'id="mapContextState"' not in page   # no competing state control / badge
        assert 'id="mapContextLedger"' not in page and 'id="mapContextCounty"' not in page  # Remediation: the toolbar controls are the one display
        assert "All Ledgers</button>" in page and cert_label + "</button>" in page
        assert 'id="mapPageState"' not in page                       # the "Map · Florida" label is gone
    # The pills are exactly: the aggregation plus the three backend ledgers.
    assert re.findall(r'#mapLedgerPills|data-ledger="(all|auction|laft|certificate)"', INDEX[INDEX.index('id="mapLedgerPills"'):INDEX.index('id="mapWatchlistOnly"')]) == ["all", "auction", "laft", "certificate"]


def test_n04_states_are_data_driven_and_pinned_to_the_backend_production_states():
    meta = re.search(r"const STATE_META = \{(.*?)\n\};", APP, re.S).group(1)
    codes = re.findall(r"^\s+([A-Z]{2}): \{", meta, re.M)
    assert set(codes) == set(states.PRODUCTION_STATES), (codes, sorted(states.PRODUCTION_STATES))
    for code in codes:
        assert re.search(r'%s: \{ name: "[A-Za-z ]+", page: "[a-z]+\.html"' % code, meta), code
    assert "const STATE_CODES = Object.keys(STATE_META);" in APP
    assert "STATE_CODES.map(st =>" in APP and "location.href = stateSwitchHref(st);" in APP
    # No hard-coded Florida anywhere in the header's state handling.
    block = CODE[CODE.index("function stateSwitchHash"):CODE.index("buildStateSelect();")]
    assert "Florida" not in block and '"FL"' not in block


def test_n05_router_routes_four_pages_and_keeps_every_existing_hash_working():
    block = APP[APP.index("function routeFromHash"):APP.index("function pidFromHash")]
    assert 'if (h === "#map") return { page: "map", params: {} };' in block                       # legacy Map link
    assert 'if (SLUG_TO_LEDGER[seg]) return { page: "list", ledger: SLUG_TO_LEDGER[seg], pid: sub, params };' in block  # #/auctions|lands|certificates[/pid]
    assert 'if (seg === "list")' in block and 'seg === "dashboard" || seg === "map" || seg === "watchlist"' in block
    # County Intelligence (2026-10-06) is a fourth shell page; the three original pages are unchanged.
    assert 'const SHELL_PAGES = { dashboard: "pageDashboard", list: "pageList", map: "pageMap", county: "pageCounty", research: "pageResearch" };' in APP
    assert 'if (seg === "counties")' in block and 'if (seg === "county")' in block and 'if (seg === "research")' in block
    assert 'if (name === "auctions") name = "list";' in APP and 'if (name === "watchlist") { openBidList(); return; }' in APP
    # Map context is hash state, not routes per combination.
    assert 'q.set("ledger", mapFilter.ledger)' in APP and 'q.set("county", mapFilter.county)' in APP and 'q.set("q", mapFilter.search)' in APP
    assert 'return "#/map" + (qs ? "?" + qs : "");' in APP
    # replaceState only: page moves never enter the Android-back stack.
    router = CODE[CODE.index("function pageHash"):CODE.index("function syncStateLinks")]
    assert "pushState" not in router and "replaceState" in router
    # A state switch (the header select) carries the route across, minus a property id.
    assert 'return STATE_META[st] ? STATE_META[st].page + (location.search || "") + stateSwitchHash() : null;' in APP


def test_n06_map_county_select_is_scoped_to_state_and_ledger_and_counts_the_selected_ledger():
    block = APP[APP.index("function mapCountyCandidates"):APP.index("function renderMapContext")]
    assert "regionOf(p) === PAGE_STATE" in block
    assert '(mapFilter.ledger === "all" || p.source === mapFilter.ledger)' in block
    assert 'if (mapFilter.county !== "ALL" && !counts.has(mapFilter.county)) mapFilter.county = "ALL";' in block
    assert "countyCounts()" not in block                                # never the portfolio-wide count
    # The rows the map draws use the same ledger test.
    rows = APP[APP.index("function computeMapRows"):APP.index("function mapCountyCandidates")]
    assert 'if (mapFilter.ledger !== "all" && p.source !== mapFilter.ledger) return false;' in rows


def test_n07_list_and_map_share_one_ledger_definition_from_the_backend_source_column():
    # One table of ledgers (LEDGERS / LEDGER_ORDER) keyed by properties.source.
    assert 'const LEDGER_ORDER = ["auction", "laft", "certificate"];' in APP
    assert APP.count("const LEDGERS = {") == 1
    from harvesters.ledgers import LEDGER_BY_SOURCE  # noqa: E402  (properties.source -> ledger)
    assert set(LEDGER_BY_SOURCE) == {"auction", "laft", "certificate"}


def test_n08_dashboard_is_an_operating_view_with_no_score_and_honest_not_tracked_wording():
    block = APP[APP.index("function dashboardOps"):APP.index("// ---- desktop data table ----")]
    # Remediation (2026-10-10): the Recent, By County, By Ledger and Upcoming
    # panels repeated figures shown on Home; they are gone from the page.
    for panel in ("dashAttentionRows", "dashPathRows", "dashSourceRows", "dashUnitRows", "dashWatchChanges"):
        assert panel in block, panel
        assert f'id="{panel}"' in INDEX and f'id="{panel}"' in TX, panel
    for gone in ("dashRecentRows", "dashCountyRows", "dashLedgerRows", "dashUpcomingRows"):
        assert f'id="{gone}"' not in INDEX and f'id="{gone}"' not in TX, gone
    assert "First-recorded date not tracked" in block and "Per-row read date not tracked" in block
    assert "Not recorded on this deployment" in block
    assert "Not yet verified - no purchase path established from evidence" in block
    assert "Sum of county values" not in block
    assert not re.search(r"\b(score|rank|recommend|estimate)\w*", block, re.I)
    assert 'data-go-ledger="${esc(key)}"' in block and 'showPage("list"); setLedger(btn.dataset.goLedger);' in block


def test_n09_watchlist_folds_the_same_parcel_across_ledgers_and_is_a_destination():
    block = APP[APP.index("function renderBidListModal"):APP.index("function openBidList")]
    assert "relatedRecordsFor(p)" in block and "folded.add(o.id)" in block and "bidlist-related" in block
    opener = APP[APP.index("function openBidList"):APP.index("function closeBidList")]
    assert 'history.replaceState(history.state, "", "#/watchlist");' in opener


def test_n10_service_worker_bumped_and_root_mirror_matches_public():
    assert (REPO / "public/sw.js").read_text(encoding="utf-8").count('const CACHE = "tdw-shell-v115"') == 1
    for f in ("app.js", "styles.css", "sw.js", "index.html", "tx.html", "explore.css"):
        assert (REPO / f).read_bytes() == (REPO / "public" / f).read_bytes(), f
