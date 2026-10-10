"""Front-end coherence remediation (2026-10-10): static regression pins.

Each test pins one corrected defect so it cannot quietly return. The
behaviour itself is exercised in tests/run_test.mjs (browser suite); these
checks read the shipped files, so they run in the Python job without a
browser.
"""
import glob
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
APP = (REPO / "public/app.js").read_text(encoding="utf-8")
PAGES = sorted(glob.glob(str(REPO / "public/*.html")))


def _page(name):
    return (REPO / "public" / name).read_text(encoding="utf-8")


def test_bare_url_lands_on_home_not_the_list():
    # showApp's dispatch: an unknown or missing route opens Home.
    assert 'else showPage("dashboard");' in APP
    assert 'else { showPage("list"); if (route && route.page === "watchlist")' not in APP


def test_document_title_follows_the_page_and_is_set_on_every_page_change():
    assert "function applyPageTitle(" in APP
    show = APP[APP.index("function showPage(name) {"):]
    show = show[:show.index("\n}\n")]
    assert "applyPageTitle();" in show
    # The List-only title line is gone from setLedger.
    assert 'document.title = (cfg.title ? cfg.title + " · " : "")' not in APP


def test_one_detail_surface_per_width_on_the_list():
    assert "function detailPanelOnList(" in APP
    open_detail = APP[APP.index("function openDetail(p) {"):]
    assert "if (modal.hidden && detailPanelOnList()) { selectProperty(p); return; }" in open_detail[:900]
    # "View full property page" opens one surface, not the modal and the panel.
    viewdetails = APP[APP.index('} else if (action === "viewdetails") {'):]
    viewdetails = viewdetails[:viewdetails.index("} else if")]
    assert "selectProperty(p)" not in viewdetails


def test_side_panel_hydrates_the_same_history_as_the_modal():
    select = APP[APP.index("function selectProperty(p) {"):]
    select = select[:select.index("\n}\n")]
    assert "hydrateEventHistory(panel, p)" in select
    assert "hydrateInventoryHistory(panel, p)" in select


def test_source_is_named_from_source_id_and_verified_path_needs_a_source():
    assert "function sourceNameFor(p)" in APP
    assert 'harvesterSourceLabel(p) || "Source not recorded"' not in APP
    assert "function hasVerifiedPath(p)" in APP
    assert "const typed = laft.filter(hasVerifiedPath);" in APP


def test_password_minimum_is_one_constant_everywhere():
    assert "var MIN_PASSWORD_LENGTH = 8;" in APP
    assert "if (next.length < MIN_PASSWORD_LENGTH) {" in APP
    assert "if (next.length < 6)" not in APP
    for page in PAGES:
        text = Path(page).read_text(encoding="utf-8")
        assert "min 6 characters" not in text, page
        assert 'minlength="6"' not in text, page


def test_removed_duplicate_controls_stay_removed():
    gone = ["statePickerBtn", "dashSettingsBtn", "navBottomAccount", "listMapBtn", 'id="mapContext"',
            'id="searchInput"', 'id="mapSearchInput"', "dashLedgerRows", "dashUpcomingRows", "dashRecentRows",
            "dashCountyRows", "tabCountAuction", "tabCountLaft", "tabCountCertificate"]
    for page in PAGES:
        text = Path(page).read_text(encoding="utf-8")
        if "dashStats" not in text:
            continue  # legal and admin pages have no app shell
        for marker in gone:
            assert marker not in text, (Path(page).name, marker)


def test_home_has_one_search_and_the_header_search_is_hidden_there():
    assert 'id="homeSearchInput"' in _page("index.html")
    assert 'if (gsWrap) gsWrap.hidden = name === "dashboard";' in APP
    # One canonical placeholder for every search box.
    for page in PAGES:
        text = Path(page).read_text(encoding="utf-8")
        assert "Search address, parcel, APN, county or case number" not in text, page
        assert "Search address, parcel, county, APN or case number" not in text, page


def test_customer_health_wording_hides_operator_diagnostics():
    fn = APP[APP.index("function sourceHealthRowHtml(rec) {"):]
    fn = fn[:fn.index("  const units")]
    # The customer branch returns before the diagnostic strings are built.
    assert "if (!IS_ADMIN) {" in fn
    assert "CUSTOMER_HEALTH_TEXT" in APP
    assert "back-off: attempted at most once per 48 hours" not in APP[APP.index("function unitFreshnessText"):][:900]


def test_service_worker_cache_is_bumped():
    sw = (REPO / "public/sw.js").read_text(encoding="utf-8")
    assert re.search(r'const CACHE = "tdw-shell-v11[5-9]"', sw), "cache not bumped"


def test_acquisition_card_and_dashboard_share_one_verified_rule():
    # A typed path is verified only with a source attached - the same rule
    # the dashboard's verified count uses (hasVerifiedPath).
    assert 'verified: tp.type !== "none_published" && !!p.source_id,' in APP
    assert "return !!p && !!p.source_id && acquisitionOf(p).verified;" in APP
