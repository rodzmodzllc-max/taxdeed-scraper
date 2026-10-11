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
            "dashCountyRows", "tabCountAuction", "tabCountLaft", "tabCountCertificate",
            'id="dashStats"', 'id="bidListModal"']   # 2026-10-10: ledger tiles and the watchlist modal
    for page in PAGES:
        text = Path(page).read_text(encoding="utf-8")
        if 'id="navRail"' not in text:
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
    # Remediation (2026-10-10): the customer page carries one plain status per
    # source and county for everyone; the operator detail (attempt status, row
    # counts, incomplete units, back-off) lives in admin.js, server-gated.
    fn = APP[APP.index("function sourceHealthRowHtml(rec) {"):]
    fn = fn[:fn.index("\n}\n")]
    assert "IS_ADMIN" not in fn and "CUSTOMER_HEALTH_TEXT" in fn
    assert "units complete" not in APP and "consecutive failed attempt" not in APP
    assert "back-off: attempted at most once per 48 hours" not in APP
    assert "renderSourceReviewPanel" not in APP and "dashSourceReview" not in APP
    admin = (REPO / "public/admin.js").read_text(encoding="utf-8")
    for s in ("function healthRowHtml(rec)", "function unitRowHtml(u)", "async function loadInventory(st)",
              "back-off: attempted at most once per 48 hours", "units complete"):
        assert s in admin, s
    html = _page("admin.html")
    assert 'id="adminFreshnessList"' in html and 'id="adminInventoryList"' in html


def test_admin_detroit_subset_rule_matches_the_customer_page():
    admin = (REPO / "public/admin.js").read_text(encoding="utf-8")
    for line in ('const DETROIT_SOURCE_IDS = ["mi_detroit_landbank_lots", "mi_detroit_landbank_programs"];',
                 'const DETROIT_STRUCTURE_SOURCE_ID = "mi_detroit_landbank_lots";',
                 'const DETROIT_STRUCTURE_STATUSES = ["Marketed Structure For Sale"];',
                 "const DETROIT_SUBSET_PERCENT = 50;",
                 "return fnv1a32(`${p.source_id}|${parcel}`) % 100 < DETROIT_SUBSET_PERCENT ? \"in_subset\" : \"not_selected\";"):
        assert line in APP and line in admin, line


def test_service_worker_cache_is_bumped():
    sw = (REPO / "public/sw.js").read_text(encoding="utf-8")
    assert re.search(r'const CACHE = "tdw-shell-v1[2-9][0-9]"', sw), "cache not bumped"


def test_acquisition_card_and_dashboard_share_one_verified_rule():
    # A typed path is verified only with a source attached - the same rule
    # the dashboard's verified count uses (hasVerifiedPath).
    assert 'verified: tp.type !== "none_published" && !!p.source_id,' in APP
    assert "return !!p && !!p.source_id && acquisitionOf(p).verified;" in APP


def test_signin_preview_is_labelled_illustrative_and_carries_no_live_data():
    # The owner decision: the signed-out page shows illustrative content only.
    for page in ["index.html", "la.html", "tx.html"]:
        text = _page(page)
        assert "Illustrative example — not a live listing." in text, page
        # The preview block holds sample prices/addresses only - no record ids.
        block = text[text.index('<div class="auth-preview"'):text.index('<p class="auth-preview-note">')]
        assert "PARCEL" not in block and "CERT" not in block and "SALE " not in block, page


def test_no_decorative_symbols_in_filter_labels():
    for page in PAGES:
        text = Path(page).read_text(encoding="utf-8")
        for symbol in ("⏱", "🕐", "📁"):
            assert symbol not in text, (Path(page).name, symbol)


def test_customer_copy_has_no_internal_operational_phrases():
    # Customer-facing strings only: the admin diagnostics live in admin.html.
    for phrase in ("completeness not gated", "sync step outcome", "back-off: attempted"):
        for page in PAGES:
            assert phrase not in Path(page).read_text(encoding="utf-8"), (Path(page).name, phrase)
