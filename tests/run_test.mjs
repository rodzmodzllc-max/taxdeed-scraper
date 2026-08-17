// Regression test for the FL Tax Deed Watchlist front end.
//
// Runs the app against a mocked Supabase client (vendor/supabase-stub.js,
// fixture data seeded via futureDate() offsets so it never goes stale) and
// asserts the DOM behaves the way it's supposed to. Exits 1 on any mismatch
// so this can gate CI. Point PORT/BASE_URL at wherever the built serve dir
// is being hosted (see .github/workflows/playwright-test.yml).
//
// A few fields are inherently date-relative (calendar-formatted "Auction
// Mon D, YYYY" labels, the CSV export filename) - those are checked with a
// pattern instead of a frozen string so the test doesn't rot day to day.

import { chromium } from 'playwright';
import fs from 'node:fs';

const BASE_URL = process.env.BASE_URL || 'http://localhost:8934/index.html';
// This sandbox ships Chromium at a fixed path outside Playwright's normal
// cache; CI installs its own via `npx playwright install chromium` and
// should just use Playwright's default resolution.
const SANDBOX_CHROMIUM = '/opt/pw-browsers/chromium';
const launchOpts = fs.existsSync(SANDBOX_CHROMIUM) ? { executablePath: SANDBOX_CHROMIUM } : {};

// Console/page errors that are known pre-existing noise from this fixture
// setup (not real app bugs) - anything NOT matching one of these fails the
// build instead of being silently ignored.
const ALLOWED_ERROR_SUBSTRINGS = [
  'net::ERR_TUNNEL_CONNECTION_FAILED',                 // sandboxed egress proxy artifact
  'A bad HTTP response code (404) was received',       // no icons/ in the fixture serve dir
  'the server responded with a status of 404',         // same
  '<path> attribute d: Expected number',               // fl-counties.svg path-parsing quirk
];

const errors = [];
const browser = await chromium.launch(launchOpts);
const page = await browser.newPage({ viewport: { width: 390, height: 844 } });
page.on('pageerror', e => errors.push('pageerror: ' + e.message));
page.on('console', msg => { if (msg.type() === 'error') errors.push('console.error: ' + msg.text()); });

await page.goto(BASE_URL, { waitUntil: 'networkidle' });
await page.waitForTimeout(500);

const results = {};

results.appVisible = await page.locator('#app').isVisible();

// --- filter-dropdown <details> elements are collapsed by default on load ---
results.typeDropdownOpenOnLoad = await page.locator('#typeChips').first().evaluate(el => el.closest('details').open);
results.countyDropdownOpenOnLoad = await page.locator('#countyChips').first().evaluate(el => el.closest('details').open);

// --- county groups are also collapsed by default on load (native <details>,
// state.expandedCounties starts empty) ---
results.countyGroupOpenOnLoad = await page.locator('.county-group').first().evaluate(el => el.open);
results.countyGroupCount = await page.locator('.county-group').count();

// --- ledger tabs: default view is Auctions only (p1/p5-p12 live, p2 auction
// gone/expired so excluded); Lands Available (p3) and Certificates (p4) are
// separate tabs now, not stacked below on the same page. ---
results.ledgerTabCounts = await page.locator('#ledgerTabs .ledger-tab').allTextContents();
results.auctionTabOnByDefault = await page.locator('.ledger-tab[data-ledger="auction"]').evaluate(el => el.classList.contains('on'));
results.cardCount = await page.locator('.prop-card').count();

// --- county chips (in Advanced Filters) still carry a "(n)" count and sort busiest-first ---
results.countyChipLabels = await page.locator('#countyChips .chipx').allTextContents();

// --- filters toggle ---
await page.click('#filtersToggle');
await page.waitForTimeout(100);
results.filtersOpenAfterClick = await page.locator('#filtersPanel').evaluate(el => el.classList.contains('open'));

// --- county group header content: name, "Auction {date}" meta line (or the
// county_calendar-driven date for Brevard specifically), and "N/M active" count ---
results.brevardGroupMeta = await page.locator('.county-group[data-county="Brevard"] .county-meta').textContent();
results.brevardGroupCount = await page.locator('.county-group[data-county="Brevard"] .county-count').textContent();
results.alachuaGroupMeta = await page.locator('.county-group[data-county="Alachua"] .county-meta').textContent();

// --- expand all: makes every county group's cards actually visible/clickable
// (native <details> keeps cards in the DOM either way, but click actions
// require visibility, so this has to happen before any card-level click) ---
results.expandAllLabelBeforeClick = await page.locator('#expandAllBtn').textContent();
await page.click('#expandAllBtn');
await page.waitForTimeout(150);
results.expandAllLabelAfterClick = await page.locator('#expandAllBtn').textContent();
results.allCountyGroupsOpenAfterExpandAll = await page.locator('.county-group').evaluateAll(els => els.every(el => el.open));
results.brevardCardVisibleAfterExpandAll = await page.locator('.county-group[data-county="Brevard"] .prop-card').first().isVisible();

// --- county-info banner: short-tag shape (Brevard: "Online" + note) and the
// long-freeform-fmt shape with no note (Charlotte - must not dump the whole
// sentence into the small pill; falls back to a generic "Note" pill instead) ---
results.brevardBannerPill = (await page.locator('.county-group[data-county="Brevard"] .fmt-pill').textContent() || '').trim();
results.brevardBannerText = (await page.locator('.county-group[data-county="Brevard"] .county-info span:not(.fmt-pill)').textContent() || '').trim();
results.charlotteBannerPill = (await page.locator('.county-group[data-county="Charlotte"] .fmt-pill').textContent() || '').trim();
results.charlotteBannerText = (await page.locator('.county-group[data-county="Charlotte"] .county-info span:not(.fmt-pill)').textContent() || '').trim();
// Baker has no COUNTY_INFO entry at all - no banner should render for it.
results.bakerBannerCount = await page.locator('.county-group[data-county="Baker"] .county-info').count();

// --- collapse a single group by clicking its summary, then re-expand ---
const brevardSummary = page.locator('.county-group[data-county="Brevard"] summary.county-head');
await brevardSummary.click();
await page.waitForTimeout(100);
results.brevardOpenAfterManualCollapse = await page.locator('.county-group[data-county="Brevard"]').evaluate(el => el.open);
await brevardSummary.click();
await page.waitForTimeout(100);
results.brevardOpenAfterManualReopen = await page.locator('.county-group[data-county="Brevard"]').evaluate(el => el.open);

// --- bid min filter ---
const beforeBidFilter = await page.locator('.prop-card').count();
await page.fill('#bidMin', '10000');
await page.waitForTimeout(150);
results.bidMinCardCountAfter = await page.locator('.prop-card').count();
results.bidMinBeforeCount = beforeBidFilter;
await page.fill('#bidMin', '');
await page.waitForTimeout(100);

// --- sort by ---
await page.selectOption('#sortBy', 'bidDesc');
await page.waitForTimeout(150);
const firstMeta = await page.locator('.prop-card .card-stat-val.bid').first().textContent();
results.sortByBidDescFirst = firstMeta.trim();
await page.selectOption('#sortBy', 'county');

// --- status chips ---
await page.click('.chip[data-status="gone"]');
await page.waitForTimeout(150);
results.goneChipOn = await page.locator('.chip[data-status="gone"]').evaluate(el => el.classList.contains('on'));
results.cardsUnderGoneView = await page.locator('.prop-card').count();
await page.click('.chip[data-status="all"]');
await page.waitForTimeout(100);

// --- favorite click (mocked insert) - needs its county group expanded, done above ---
const heart = page.locator('.heart-btn').first();
const heartBefore = await heart.textContent();
await heart.click();
await page.waitForTimeout(200);
results.heartTextBefore = heartBefore;
results.heartTextAfter = await page.locator('.heart-btn').first().textContent();

// --- theme toggle ---
const themeBefore = await page.locator('#themeLabel').textContent();
await page.click('#themeBtn');
await page.waitForTimeout(100);
const themeAfter = await page.locator('#themeLabel').textContent();
const dataTheme = await page.evaluate(() => document.documentElement.getAttribute('data-theme'));
results.themeBefore = themeBefore;
results.themeAfter = themeAfter;
results.dataThemeAttr = dataTheme;

// --- group mini buttons (types none/all) ---
// Property Type chips now live inside a collapsed <details> dropdown; open it first.
await page.click('.filter-dropdown summary:has-text("Property Type")');
await page.waitForTimeout(100);
results.typeDropdownOpenForMiniBtnTest = await page.locator('#typeChips').first().evaluate(el => el.closest('details').open);
await page.click('.mini-btn[data-group="types"][data-mode="none"]');
await page.waitForTimeout(150);
results.cardsAfterTypesNone = await page.locator('.prop-card').count();
await page.click('.mini-btn[data-group="types"][data-mode="all"]');
await page.waitForTimeout(150);
results.cardsAfterTypesAll = await page.locator('.prop-card').count();

// --- county map ---
// County chips/map now live inside a collapsed <details> dropdown; open it first.
await page.click('.filter-dropdown summary:has-text("County")');
await page.waitForTimeout(100);
results.countyDropdownOpenForMapTest = await page.locator('#countyChips').first().evaluate(el => el.closest('details').open);
await page.click('#mapBtn');
await page.waitForTimeout(300);
results.mapWrapVisible = await page.locator('#mapWrap').isVisible();
results.mapPathCount = await page.locator('#mapHost path[data-county]').count();
results.mapHasDataCount = await page.locator('#mapHost path.has-data').count();
// click Alachua's path (has data in fixture) to toggle it off
const alachuaPath = page.locator('#mapHost path[data-county="Alachua"]');
const alachuaSelBefore = await alachuaPath.evaluate(el => el.classList.contains('sel'));
await alachuaPath.click({ force: true });
await page.waitForTimeout(150);
const alachuaSelAfter = await alachuaPath.evaluate(el => el.classList.contains('sel'));
const alachuaChipOnAfter = await page.locator('#countyChips .chipx[data-value="Alachua"]').evaluate(el => el.classList.contains('on'));
results.alachuaSelBefore = alachuaSelBefore;
results.alachuaSelAfter = alachuaSelAfter;
results.alachuaChipOnAfterMapClick = alachuaChipOnAfter;

// --- reset button: also collapses every county group back to closed ---
await page.click('#resetBtn');
await page.waitForTimeout(150);
results.cardsAfterReset = await page.locator('.prop-card').count();
results.alachuaSelAfterReset = await alachuaPath.evaluate(el => el.classList.contains('sel'));
results.countyGroupsClosedAfterReset = await page.locator('.county-group').evaluateAll(els => els.every(el => !el.open));
results.expandAllLabelAfterReset = await page.locator('#expandAllBtn').textContent();

// Re-expand everything - the hide/remove-btn test below needs a visible card.
await page.click('#expandAllBtn');
await page.waitForTimeout(150);

// --- restore hidden button visibility toggling via hide action ---
const removeBtn = page.locator('.remove-btn').first();
await removeBtn.click();
await page.waitForTimeout(200);
results.cardsAfterHide = await page.locator('.prop-card').count();
results.hiddenInfoVisible = await page.locator('#hiddenInfo').isVisible();

// --- switch to Lands Available tab (fixture p3, Bay county) ---
await page.click('.ledger-tab[data-ledger="laft"]');
await page.waitForTimeout(150);
results.laftTabOnAfterClick = await page.locator('.ledger-tab[data-ledger="laft"]').evaluate(el => el.classList.contains('on'));
results.auctionTabOffAfterLaftClick = await page.locator('.ledger-tab[data-ledger="auction"]').evaluate(el => el.classList.contains('on'));
results.laftCardCount = await page.locator('.prop-card').count();
// County is shown on the group header now, not a per-card tag.
results.laftCountyGroupName = (await page.locator('.county-group .county-name').first().textContent() || '').trim();
results.laftGroupMeta = (await page.locator('.county-group .county-meta').first().textContent() || '').trim();

// --- switch to Certificates tab (fixture p4) ---
await page.click('.ledger-tab[data-ledger="certificate"]');
await page.waitForTimeout(150);
results.certCardCount = await page.locator('.cert-card').count();
results.certCardTitle = await page.locator('.cert-card .prop-address').first().textContent();
results.certCardAccount = await page.locator('.cert-card .prop-meta span').first().textContent();
results.certCardAmount = (await page.locator('.cert-card .meta-bid').first().textContent()).trim();
results.certCardCta = await page.locator('.cert-card .cta-btn').first().textContent();
results.certCardExpiresCountdown = await page.locator('.cert-card .countdown').count();

// --- switch back to Auctions tab - expandedCounties from before should still hold ---
await page.click('.ledger-tab[data-ledger="auction"]');
await page.waitForTimeout(150);
results.cardCountBackOnAuctionTab = await page.locator('.prop-card').count();

// --- past-due auction (p13, sale_date 6 days ago, status still "active") must
// never render, in any status view - it's excluded in passes() regardless of
// the statusView toggle, not just filtered out of the default "live" view ---
results.pastDueCardVisibleDefault = await page.locator('.prop-card:has-text("Past Due Ln")').count();
await page.click('.summary-strip .chip[data-status="all"]');
await page.waitForTimeout(150);
results.pastDueCardVisibleAllView = await page.locator('.prop-card:has-text("Past Due Ln")').count();
await page.click('.summary-strip .chip[data-status="gone"]');
await page.waitForTimeout(150);
results.pastDueCardVisibleGoneView = await page.locator('.prop-card:has-text("Past Due Ln")').count();

// --- Archive view: the inverse - shows ONLY the past-due auction, with a
// "Nd ago" badge instead of the usual countdown ---
await page.click('.summary-strip .chip[data-status="archive"]');
await page.waitForTimeout(150);
results.archiveChipCount = (await page.locator('#chipArchive').textContent()).trim();
results.pastDueCardVisibleArchiveView = await page.locator('.prop-card:has-text("Past Due Ln")').count();
results.archiveViewOtherCardsCount = await page.locator('.prop-card').count(); // should be 1 - archive is exclusive
results.archiveCardAgoBadge = (await page.locator('.prop-card:has-text("Past Due Ln") .countdown.past').textContent().catch(() => '')) || '';

// --- stale-data warning: every fixture's updated_at is days old relative to
// "today", so the newest-row calc should already be past STALE_DATA_HOURS ---
results.staleWarningClassPresent = await page.locator('#generatedAt.stale').count();
results.staleWarningText = (await page.locator('#generatedAt').textContent()) || '';

await page.click('.summary-strip .chip[data-status="live"]');
await page.waitForTimeout(150);

// ============================================================
// Phase 8: search, county quick-select, CSV export, spread badge,
// detail modal. Fixture now has 9 live auction properties (p1, p5-p12;
// p2 is gone/expired) across Alachua, Brevard, Charlotte, Duval(x2),
// Escambia(x2), Marion(x2) - minus whichever one got hidden earlier.
// ============================================================

// --- spread badge: p1 has bid 5000 / market 90000 -> should show ---
results.spreadBadgeCount = await page.locator('.spread-badge').count();
results.spreadBadgeFirstText = (await page.locator('.spread-badge').first().textContent() || '').trim();

// --- collapse everything first, so the next search test genuinely proves a
// search auto-opens a matching county rather than finding it already open
// from earlier in this run ---
if ((await page.locator('#expandAllBtn').textContent()) === 'Collapse all') {
  await page.click('#expandAllBtn');
  await page.waitForTimeout(150);
}
results.duvalGroupClosedBeforeSearch = await page.locator('.county-group[data-county="Duval"]').evaluate(el => el.open);

// --- search: "Searchable" should isolate p7 (12 Searchable Blvd, Duval) and
// auto-expand its county group even though it was just collapsed ---
await page.fill('#searchInput', 'Searchable');
await page.waitForTimeout(200);
results.searchFilteredCardCount = await page.locator('.prop-card').count();
results.searchFilteredAddress = (await page.locator('.prop-card .prop-address').first().textContent() || '').trim();
results.searchAutoExpandsMatch = await page.locator('.county-group[data-county="Duval"]').evaluate(el => el.open);
await page.fill('#searchInput', '');
await page.waitForTimeout(150);
results.cardCountAfterClearingSearch = await page.locator('.prop-card').count();

// --- county quick-select dropdown: pick Duval (p6 + p7) - should auto-expand it ---
await page.selectOption('#countyQuick', 'Duval');
await page.waitForTimeout(150);
results.cardCountAfterCountyQuickDuval = await page.locator('.prop-card').count();
results.duvalChipOnAfterQuickSelect = await page.locator('#countyChips .chipx[data-value="Duval"]').evaluate(el => el.classList.contains('on')).catch(() => null);
results.duvalGroupOpenAfterQuickSelect = await page.locator('.county-group[data-county="Duval"]').evaluate(el => el.open);
await page.selectOption('#countyQuick', 'ALL');
await page.waitForTimeout(150);
results.cardCountAfterCountyQuickAll = await page.locator('.prop-card').count();

// --- filter-dropdown <details> elements: toggle closed/open, badge reflects selection ---
const typeDetails = page.locator('#typeChips').first().locator('xpath=ancestor::details[1]');
results.typeDropdownOpenBeforeToggle = await typeDetails.evaluate(el => el.open);
await page.click('.filter-dropdown summary:has-text("Property Type")');
await page.waitForTimeout(100);
results.typeDropdownOpenAfterToggle = await typeDetails.evaluate(el => el.open);
if (!(await typeDetails.evaluate(el => el.open))) {
  await page.click('.filter-dropdown summary:has-text("Property Type")');
  await page.waitForTimeout(100);
}
results.typeCountBadgeTextBefore = (await page.locator('#typeCount').textContent() || '').trim();
await page.click('.mini-btn[data-group="types"][data-mode="none"]');
await page.waitForTimeout(150);
results.typeCountBadgeTextAfterNone = (await page.locator('#typeCount').textContent() || '').trim();
await page.click('.mini-btn[data-group="types"][data-mode="all"]');
await page.waitForTimeout(150);
results.typeCountBadgeTextAfterAll = (await page.locator('#typeCount').textContent() || '').trim();

// --- CSV export: verify download fires with expected filename pattern ---
const downloadPromise = page.waitForEvent('download');
await page.click('#exportCsvBtn');
const download = await downloadPromise;
results.csvDownloadFilename = download.suggestedFilename();

// --- detail modal: needs a visible "View Full Property Page" button, so
// make sure everything is expanded again first (county quick-select above
// only guarantees Duval). ---
await page.click('#expandAllBtn');
await page.waitForTimeout(150);
if ((await page.locator('#expandAllBtn').textContent()) === 'Expand all') {
  await page.click('#expandAllBtn');
  await page.waitForTimeout(150);
}
const firstDetailBtn = page.locator('.detail-btn[data-action="viewdetails"]').first();
await firstDetailBtn.click();
await page.waitForTimeout(150);
results.detailModalVisibleAfterOpen = await page.locator('#detailModal').isVisible();
results.detailModalHasAddress = await page.locator('#detailModalInner .detail-address').count();
results.detailModalHasLinks = await page.locator('#detailModalInner .detail-links a').count();

// close via the close button
await page.click('[data-action="closedetail"]');
await page.waitForTimeout(150);
results.detailModalHiddenAfterCloseBtn = await page.locator('#detailModal').isHidden();

// reopen, close via backdrop click
await firstDetailBtn.click();
await page.waitForTimeout(150);
await page.click('#detailModal', { position: { x: 5, y: 5 } });
await page.waitForTimeout(150);
results.detailModalHiddenAfterBackdropClick = await page.locator('#detailModal').isHidden();

// reopen, close via Escape key
await firstDetailBtn.click();
await page.waitForTimeout(150);
await page.keyboard.press('Escape');
await page.waitForTimeout(150);
results.detailModalHiddenAfterEscape = await page.locator('#detailModal').isHidden();

// --- redesign: brand mark / topbar, disclaimer badge, card stat grid,
// lien-status pill, info tooltip, top-pick badge, icon-prefixed links ---
results.topbarBrandVisible = await page.locator('.topbar .brand-mark').isVisible();
results.disclaimerBadgeVisible = await page.locator('.disclaimer-badge').isVisible();
results.cardStatGridCount = await page.locator('.prop-card .card-stat-grid').count();
results.lienPillFirstText = (await page.locator('.prop-card .lien-pill').first().textContent() || '').trim();
results.infoTipCount = await page.locator('.info-tip').count();
results.linkIconPresent = (await page.locator('.prop-links a').first().innerHTML() || '').includes('link-icon');
// p1 (Alachua, clean/12x+ ratio potential) should be a top pick - confirm the
// upgraded pill-style banner renders with its ratio callout.
results.toppickBannerText = (await page.locator('.toppick-banner').first().textContent().catch(() => '')) || '';

await browser.close();

// ============================================================
// Assertions - EXPECTED is a locked-in snapshot of known-good behavior.
// A `RegExp` value means "must match this pattern" (used for the handful of
// fields that legitimately vary with the real calendar date); anything else
// is checked for strict equality (arrays/objects via JSON comparison).
// ============================================================

const EXPECTED = {
  appVisible: true,
  typeDropdownOpenOnLoad: false,
  countyDropdownOpenOnLoad: false,
  countyGroupOpenOnLoad: false,
  countyGroupCount: 6,
  ledgerTabCounts: ['Tax Deeds / Auctions 11', 'Lands Available / OTC 1', 'Certificates 1'],
  auctionTabOnByDefault: true,
  cardCount: 9,
  // All 67 counties now show (busiest-first, then alphabetical among the
  // zero-count ones) instead of only the ~8 with live scraped data - see
  // ALL_COUNTIES in app.js.
  countyChipLabels: ['Alachua (3)', 'Duval (2)', 'Escambia (2)', 'Marion (2)', 'Baker (1)', 'Bay (1)', 'Brevard (1)', 'Charlotte (1)', 'Bradford (0)', 'Broward (0)', 'Calhoun (0)', 'Citrus (0)', 'Clay (0)', 'Collier (0)', 'Columbia (0)', 'DeSoto (0)', 'Dixie (0)', 'Flagler (0)', 'Franklin (0)', 'Gadsden (0)', 'Gilchrist (0)', 'Glades (0)', 'Gulf (0)', 'Hamilton (0)', 'Hardee (0)', 'Hendry (0)', 'Hernando (0)', 'Highlands (0)', 'Hillsborough (0)', 'Holmes (0)', 'Indian River (0)', 'Jackson (0)', 'Jefferson (0)', 'Lafayette (0)', 'Lake (0)', 'Lee (0)', 'Leon (0)', 'Levy (0)', 'Liberty (0)', 'Madison (0)', 'Manatee (0)', 'Martin (0)', 'Miami-Dade (0)', 'Monroe (0)', 'Nassau (0)', 'Okaloosa (0)', 'Okeechobee (0)', 'Orange (0)', 'Osceola (0)', 'Palm Beach (0)', 'Pasco (0)', 'Pinellas (0)', 'Polk (0)', 'Putnam (0)', 'Santa Rosa (0)', 'Sarasota (0)', 'Seminole (0)', 'St. Johns (0)', 'St. Lucie (0)', 'Sumter (0)', 'Suwannee (0)', 'Taylor (0)', 'Union (0)', 'Volusia (0)', 'Wakulla (0)', 'Walton (0)', 'Washington (0)'],
  filtersOpenAfterClick: true,
  brevardGroupMeta: /^Auction [A-Z][a-z]{2} \d{1,2}, \d{4}$/,
  brevardGroupCount: '1/1 active',
  alachuaGroupMeta: /^Auction [A-Z][a-z]{2} \d{1,2}, \d{4}$/,
  expandAllLabelBeforeClick: 'Expand all',
  expandAllLabelAfterClick: 'Collapse all',
  allCountyGroupsOpenAfterExpandAll: true,
  brevardCardVisibleAfterExpandAll: true,
  brevardBannerPill: 'Online',
  brevardBannerText: 'Deposit required in advance via the auction site.',
  charlotteBannerPill: 'Note',
  charlotteBannerText: 'Shared site with foreclosure sales - confirm you are on a TAXDEED auction.',
  bakerBannerCount: 0,
  brevardOpenAfterManualCollapse: false,
  brevardOpenAfterManualReopen: true,
  bidMinCardCountAfter: 2,
  bidMinBeforeCount: 9,
  sortByBidDescFirst: '$11,000.00',
  goneChipOn: true,
  cardsUnderGoneView: 0,
  heartTextBefore: '♡',
  heartTextAfter: '♥',
  themeBefore: 'Auto',
  themeAfter: 'Light',
  dataThemeAttr: 'light',
  typeDropdownOpenForMiniBtnTest: true,
  cardsAfterTypesNone: 0,
  cardsAfterTypesAll: 9,
  countyDropdownOpenForMapTest: true,
  mapWrapVisible: true,
  mapPathCount: 67,
  mapHasDataCount: 8,
  alachuaSelBefore: true,
  alachuaSelAfter: false,
  alachuaChipOnAfterMapClick: false,
  cardsAfterReset: 9,
  alachuaSelAfterReset: true,
  countyGroupsClosedAfterReset: true,
  expandAllLabelAfterReset: 'Expand all',
  cardsAfterHide: 8,
  hiddenInfoVisible: true,
  laftTabOnAfterClick: true,
  auctionTabOffAfterLaftClick: false,
  laftCardCount: 1,
  laftCountyGroupName: 'Bay',
  laftGroupMeta: 'Lands Available - fixed price, available now',
  certCardCount: 1,
  certCardTitle: 'Certificate #CERT-42',
  certCardAccount: 'Account #ACC-999',
  certCardAmount: 'Amount $1,234.56',
  certCardCta: 'View on County-Held Liens List',
  certCardExpiresCountdown: 1,
  cardCountBackOnAuctionTab: 8,
  pastDueCardVisibleDefault: 0,
  pastDueCardVisibleAllView: 0,
  pastDueCardVisibleGoneView: 0,
  archiveChipCount: '1',
  pastDueCardVisibleArchiveView: 1,
  archiveViewOtherCardsCount: 1,
  // Day-granular diff between two Date.now() reads in the same test run, so
  // this stays "6d ago" regardless of what day the suite actually runs on.
  archiveCardAgoBadge: '6d ago',
  staleWarningClassPresent: 1,
  staleWarningText: '⚠ Data updated 8/12/2026, 12:00:00 AM - sync may be behind',
  spreadBadgeCount: 8,
  spreadBadgeFirstText: 'Potential equity +$85,000 (18.0× market/bid)',
  duvalGroupClosedBeforeSearch: false,
  searchFilteredCardCount: 1,
  searchFilteredAddress: '12 Searchable Blvd',
  searchAutoExpandsMatch: true,
  cardCountAfterClearingSearch: 8,
  cardCountAfterCountyQuickDuval: 2,
  duvalChipOnAfterQuickSelect: true,
  duvalGroupOpenAfterQuickSelect: true,
  cardCountAfterCountyQuickAll: 8,
  typeDropdownOpenBeforeToggle: true,
  typeDropdownOpenAfterToggle: false,
  typeCountBadgeTextBefore: '7/7',
  typeCountBadgeTextAfterNone: '0/7',
  typeCountBadgeTextAfterAll: '7/7',
  csvDownloadFilename: /^taxdeed-auction-\d{4}-\d{2}-\d{2}\.csv$/,
  detailModalVisibleAfterOpen: true,
  detailModalHasAddress: 1,
  detailModalHasLinks: 6,
  detailModalHiddenAfterCloseBtn: true,
  detailModalHiddenAfterBackdropClick: true,
  detailModalHiddenAfterEscape: true,
  topbarBrandVisible: true,
  disclaimerBadgeVisible: true,
  cardStatGridCount: 8,
  lienPillFirstText: 'Clear',
  infoTipCount: 9,
  linkIconPresent: true,
  toppickBannerText: '★ Top pick 18.0× market vs bid',
};

const mismatches = [];
for (const [key, expected] of Object.entries(EXPECTED)) {
  const actual = results[key];
  const ok = expected instanceof RegExp
    ? typeof actual === 'string' && expected.test(actual)
    : JSON.stringify(actual) === JSON.stringify(expected);
  if (!ok) {
    mismatches.push(`  ${key}: expected ${expected instanceof RegExp ? expected : JSON.stringify(expected)}, got ${JSON.stringify(actual)}`);
  }
}

const missingKeys = Object.keys(EXPECTED).filter(k => !(k in results));
const unexpectedErrors = errors.filter(e => !ALLOWED_ERROR_SUBSTRINGS.some(a => e.includes(a)));

if (mismatches.length || missingKeys.length || unexpectedErrors.length) {
  console.error('FAIL: regression test found ' + (mismatches.length + missingKeys.length + unexpectedErrors.length) + ' problem(s)\n');
  if (mismatches.length) {
    console.error('Value mismatches:');
    console.error(mismatches.join('\n'));
  }
  if (missingKeys.length) {
    console.error('Missing result keys (selector likely broke): ' + missingKeys.join(', '));
  }
  if (unexpectedErrors.length) {
    console.error('Unexpected browser console/page errors:');
    console.error(unexpectedErrors.map(e => '  ' + e).join('\n'));
  }
  process.exit(1);
} else {
  console.log(`PASS: all ${Object.keys(EXPECTED).length} checks matched, ${errors.length} console error(s) all allowlisted.`);
  process.exit(0);
}
