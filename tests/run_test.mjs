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
  'net::ERR_TUNNEL_CONNECTION_FAILED', // sandboxed egress proxy artifact
  'A bad HTTP response code (404) was received', // no icons/ in the fixture serve dir
  'the server responded with a status of 404', // same
  '<path> attribute d: Expected number', // fl-counties.svg path-parsing quirk
  'net::ERR_CERT_AUTHORITY_INVALID', // sandboxed egress proxy's own CA on the esm.sh/fonts fetches - not the app
];

const errors = [];
const browser = await chromium.launch(launchOpts);
// Phase 67: fixture rows p5 and p12 carry coordinates, so a full property
// page for either renders the GIS card's OpenStreetMap <iframe>
// (osmEmbedUrl() in app.js). On a runner with real network access that is a
// live request to a third party for a fixture row, which this suite has
// never made: every page it opens serves a blank document for that host
// instead. (This is hygiene, not the fix for the CI timeout this branch
// hit - see the cold-load note by the #/certificates check further down.)
const THIRD_PARTY_EMBED = /:\/\/(www\.)?openstreetmap\.org\//;
async function newPage(opts) {
  const pg = await browser.newPage(opts);
  await pg.route(THIRD_PARTY_EMBED, route => route.fulfill({
    status: 200, contentType: 'text/html', body: '<!doctype html><title>embed stubbed by the suite</title>' }));
  return pg;
}
const page = await newPage({ viewport: { width: 390, height: 844 } });
page.on('pageerror', e => errors.push('pageerror: ' + e.message));
page.on('console', msg => { if (msg.type() === 'error') errors.push('console.error: ' + msg.text()); });
// The "hide" action now confirms before it does anything (a real user would
// click OK) - Playwright auto-dismisses unhandled dialogs, which silently
// no-ops every hide in this test and cascades into wrong counts everywhere
// downstream. Auto-accept so hide behaves the way a real click would.
page.on('dialog', dialog => dialog.accept());

await page.goto(BASE_URL + '#/auctions', { waitUntil: 'networkidle' });
await page.waitForTimeout(500);

const results = {};

results.appVisible = await page.locator('#app').isVisible();

// --- filter-dropdown <details> elements are collapsed by default on load ---
results.typeDropdownOpenOnLoad = await page.locator('#typeChips').first().evaluate(el => el.closest('details').open);
results.countyDropdownOpenOnLoad = await page.locator('#countyChips').first().evaluate(el => el.closest('details').open);

// --- county groups are also collapsed by default on load (native <details>,
// state.expandedCounties starts empty) ---
results.countyGroupOpenOnLoad = await page.locator('.county-group').first().evaluate(el => el.open);
// Auctions are grouped by county+date (see groupKeyOf in app.js), not just
// county - Duval/Escambia/Marion each have two live fixture properties on
// two different sale dates, so each contributes two groups here: Alachua(1)
// + Brevard(1) + Charlotte(1) + Duval(2) + Escambia(2) + Marion(2) = 9.
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
// county_calendar-driven date for Brevard specifically), and "N/M active" count.
// Brevard and Alachua each have exactly one live auction property in this
// fixture, so data-county still resolves to a single element for them. ---
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

// --- Phase 72: the Florida card CTA reads url_auction_kind off the row
// (migration 013) and says what the link opens. p1 = RealAuction sale-date
// preview (kind "sale"), p7 = a Collier per-notice page (kind "property"),
// p8 = a county information page (kind "info"), p9 = a URL with no kind
// (written before the column existed) - neutral "View listing", never a
// guessed kind. ---
const flCtaOf = async pid => {
  const a = page.locator(`.prop-card[data-pid="${pid}"] .cta-btn`).first();
  return { text: ((await a.textContent()) || '').replace(/\s+/g, ' ').trim(), kind: await a.getAttribute('data-auction-link') };
};
results.flCardCtaSale = await flCtaOf('p1');
results.flCardCtaSaleText = results.flCardCtaSale.text;
results.flCardCtaSale = { kind: results.flCardCtaSale.kind };
results.flCardCtaProperty = await flCtaOf('p7');
results.flCardCtaInfo = await flCtaOf('p8');
results.flCardCtaNoKind = await flCtaOf('p9');

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
// #bidMin is a range slider (Phase 2) - Playwright's page.fill() does not
// support input[type=range] ("Malformed value"), so the value has to be set
// directly and an 'input' event dispatched by hand to trigger the same
// listener bindBidRangeSliders() wires up in app.js. '0' (the slider's min)
// is the range-slider equivalent of the old empty-string "no filter" state.
const beforeBidFilter = await page.locator('.prop-card').count();
await page.locator('#bidMin').evaluate(el => {
  el.value = '10000';
  el.dispatchEvent(new Event('input', { bubbles: true }));
});
await page.waitForTimeout(150);
results.bidMinCardCountAfter = await page.locator('.prop-card').count();
results.bidMinBeforeCount = beforeBidFilter;
await page.locator('#bidMin').evaluate(el => {
  el.value = '0';
  el.dispatchEvent(new Event('input', { bubbles: true }));
});
await page.waitForTimeout(100);

// --- Phase 65: typed min/max price, synced with the sliders ---
// The old read-only $ labels under the sliders are real number fields now.
// Dragging a slider fills the field; typing moves the slider and filters as
// you type (debounced) with no Search button; Enter commits at once.
await page.locator('#bidMin').evaluate(el => {
  el.value = '10000';
  el.dispatchEvent(new Event('input', { bubbles: true }));
});
await page.waitForTimeout(100);
results.priceMinInputFollowsSlider = await page.locator('#bidMinInput').inputValue();
results.priceMaxInputBlankWhenUncapped = await page.locator('#bidMaxInput').inputValue();
// Typing a max of $9,000 with the min still at $10,000 is a crossing: the
// control the user did NOT touch (min) snaps down to match, same rule the
// sliders have had since Phase 63, so the filter can never be min > max.
await page.fill('#bidMaxInput', '9000');
await page.waitForTimeout(400); // > the 250ms field debounce
results.priceMinSnappedToTypedMax = await page.locator('#bidMinInput').inputValue();
// The slider's step is $10,000, so the browser rounds a typed $9,000 to the
// nearest notch - the FILTER keeps the exact typed value (the card count
// below proves that); the handle just sits within one step of it.
results.priceSliderMaxWithinStepOfTypedMax = await page.locator('#bidMax').evaluate(el => Math.abs(Number(el.value) - 9000) <= Number(el.step));
// Fixture bids: 2000, 3000, 4500, 5000, 5000, 6000, 7000, 8000, 9000 ... -
// a $9,000 cap on both ends leaves exactly the one $9,000 row.
results.priceCardCountAtTypedNineThousandBoth = await page.locator('.prop-card').count();
// Enter commits immediately (no debounce wait) and leaves the field.
await page.fill('#bidMinInput', '0');
await page.locator('#bidMinInput').press('Enter');
await page.waitForTimeout(50);
results.priceCardCountAfterEnterMinZero = await page.locator('.prop-card').count();
results.priceMinInputBlurredAfterEnter = await page.evaluate(() => document.activeElement && document.activeElement.id !== 'bidMinInput');
// Clearing the max field means "no cap" again - every fixture row is back.
await page.fill('#bidMaxInput', '');
await page.waitForTimeout(400);
results.priceCardCountAfterClearingMax = await page.locator('.prop-card').count();
results.priceSliderMaxBackToTrackEnd = await page.locator('#bidMax').inputValue();
results.priceSearchButtonAbsent = (await page.locator('#filtersPanel button:has-text("Search")').count()) === 0;

// --- sort by ---
await page.selectOption('#sortBy', 'bidDesc');
await page.waitForTimeout(150);
const firstMeta = await page.locator('.prop-card .card-stat-val.bid').first().textContent();
results.sortByBidDescFirst = firstMeta.trim();
// Phase 71: every deed/LAFT card headline bid is a whole dollar - no "."
// anywhere in the figure (certificate cards keep cents via bidDisplay()
// and are excluded by the :not(.cert-card) filter).
results.deedCardBidsWithCents = await page.evaluate(() =>
  [...document.querySelectorAll('.prop-card:not(.cert-card) .card-stat-val.bid')]
    .map(el => el.textContent.trim()).filter(t => t.startsWith('$') && t.includes('.')).length);
results.deedCardBidsChecked = await page.locator('.prop-card:not(.cert-card) .card-stat-val.bid').count();
// New yield-desk sort options exist and don't error out when applied (only
// one certificate fixture row exists, so there's nothing to prove about
// ordering here - see tests/vendor/supabase-stub.js - just that selecting
// either doesn't throw and the list still renders).
results.sortByHasInterestOption = (await page.locator('#sortBy option[value="interestDesc"]').count()) === 1;
results.sortByHasExpSoonOption = (await page.locator('#sortBy option[value="expSoonAsc"]').count()) === 1;
await page.selectOption('#sortBy', 'interestDesc');
await page.waitForTimeout(100);
results.cardCountAfterInterestSort = await page.locator('.prop-card').count();
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
// Theme, password, install and sign out moved out of the header into the
// account badge's menu, so it has to be opened before the toggle is
// clickable. The assertions below are unchanged.
const themeBefore = await page.locator('#themeLabel').textContent();
await page.click('#accountBtn');
await page.waitForTimeout(150);
await page.click('#themeBtn');
await page.waitForTimeout(150);
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
// County chips still live inside a collapsed <details> dropdown; open it
// first (this part of the panel is unrelated to the map and still applies).
await page.click('.filter-dropdown summary:has-text("County")');
await page.waitForTimeout(100);
results.countyDropdownOpenForMapTest = await page.locator('#countyChips').first().evaluate(el => el.closest('details').open);

// Phase 19 (reconciliation with origin/main's app-shell rebuild): the map
// is no longer a toggle nested inside this same County filter dropdown -
// origin/main's rebuild promoted it to its own full-page destination,
// reached via the bottom nav. #mapBtn no longer exists.
//
// Phase 53 (one map, not two): folded the dedicated Map page and explore.js's
// richer "Where these are" bubble map into one - nav Map became a virtual
// route into the Auctions page with that map view active.
//
// Phase 54 (Map is its own page again): Marc's explicit feedback rejected
// Phase 53's approach - switching to Map didn't feel like going anywhere
// (same masthead/ledger-tabs/toolbar, just the panel swapped), and Auctions
// needed to go back to being just the list. So Map is a real top-level page
// (#pageMap) again, but unlike the old pre-Phase-53 page it's explore.js's
// actual bubble map (real per-county counts, one-tap zoom+filter, a floating
// preview card, real geocoded pins once zoomed in) - just with its OWN
// toolbar (search, county select, ledger pills, a Watchlist-only pill) that
// is deliberately independent of the Auctions page's own filters (see
// mapFilter/computeMapRows() in app.js). TEST_OBSOLETE, not a regression,
// same as the Phase 19/53 rewrites above: verify the actual current
// behavior rather than asserting old selectors that no longer exist.
results.auctionsPageVisibleBeforeMapNav = await page.locator('#pageList').isVisible();
await page.click('.nav-bottom-item[data-page="map"]');
await page.waitForTimeout(400); // ensureMap() fetches + parses the basemap SVG
results.auctionsPageVisibleOnMapNav = await page.locator('#pageList').isVisible();
results.mapPageVisibleOnMapNav = await page.locator('#pageMap').isVisible();
results.navMapBtnOnAfterMapNav = await page.locator('.nav-bottom-item[data-page="map"]').evaluate(el => el.classList.contains('on'));
// Phase 67: the workspace layout dropped the Map page's subtitle ("...across
// Florida"), which was its only state cue. The toolbar title now carries the
// state, filled by applyLedgerChrome() from PAGE_STATE (never from a row's
// county). Whitespace-normalised: the h1 is "Map" + a span " · Florida".
// Unified navigation (2026-09-30): the title is "Map" over a context line
// (state from PAGE_STATE, ledger pill, county select) - renderMapContext().
results.mapPageTitle = ((await page.locator('#pageMap .map-page-title').textContent()) || '').trim();
results.mapContextFlorida = ((await page.locator('#mapContext').textContent()) || '').replace(/\s+/g, ' ').trim();
results.mapHashOnMapNav = await page.evaluate(() => location.hash);
results.mapPathCount = await page.locator('#exploreMapCanvas path[data-county]').count();
// Portfolio-wide (every ledger, not just whatever ledger tab Auctions
// happens to be on) - see computeMapRows()'s comment in app.js for why the
// Map page deliberately does not inherit the Auctions page's own filters.
results.mapClusterBubbleCount = await page.locator('#exploreMapCanvas .cluster-bubble').count();

// One tap on a county's bubble zooms in AND filters in the same gesture -
// through the Map page's OWN county select (#mapCountySelect), a wholly
// separate control from the Auctions page's #countyChips/state.counties now
// that Map is its own page (see applyCounty() in explore.js).
const alachuaBubble = page.locator('#exploreMapCanvas .cluster-bubble[data-county="Alachua"]');
await alachuaBubble.click({ force: true });
await page.waitForTimeout(500); // the zoom viewBox tween runs ~320ms
results.mapCountySelectValueAfterBubbleTap = await page.locator('#mapCountySelect').inputValue();
results.mapCanvasZoomedAfterTap = await page.locator('#exploreMapCanvas').evaluate(el => el.classList.contains('zoomed'));
results.exploreMapResetVisibleAfterTap = await page.locator('#exploreMapReset').isVisible();

// --- Phase 65: selected property <-> strip card <-> pin linkage ---
// Zoomed into Alachua, the strip lists that county's rows. Clicking a strip
// card selects the property everywhere at once: the card gets .sel, the
// preview opens on that property, and (when the row is geocoded) its pin
// gets .sel too. Hovering a strip card mirrors .hover onto its pin.
const stripCards = page.locator('#exploreStrip .strip-card');
results.stripCardCountForAlachua = await stripCards.count();
await stripCards.first().click();
await page.waitForTimeout(150);
results.stripCardSelCountAfterClick = await page.locator('#exploreStrip .strip-card.sel').count();
results.previewVisibleAfterStripClick = await page.locator('#explorePreview').isVisible();
results.previewTitleMatchesStripCard = await page.evaluate(() => {
  const card = document.querySelector('#exploreStrip .strip-card.sel');
  const title = document.querySelector('#explorePreview .preview-title');
  return !!card && !!title && card.querySelector('.strip-title').textContent.trim() === title.textContent.trim();
});
results.pinSelMatchesStripSel = await page.evaluate(() => {
  const card = document.querySelector('#exploreStrip .strip-card.sel');
  if (!card) return false;
  const pins = document.querySelectorAll(`#exploreMapCanvas .map-pin[data-pid="${card.dataset.pid}"]`);
  // No pin for an un-geocoded row is fine; a pin that exists must be .sel.
  return pins.length === 0 || Array.from(pins).every(g => g.classList.contains('sel'));
});
await stripCards.nth(1).hover();
await page.waitForTimeout(50);
results.stripHoverLinksToPinWhenPresent = await page.evaluate(() => {
  const hovered = document.querySelector('#exploreStrip .strip-card.hover');
  if (!hovered) return false;
  const pins = document.querySelectorAll(`#exploreMapCanvas .map-pin[data-pid="${hovered.dataset.pid}"]`);
  return pins.length === 0 || Array.from(pins).every(g => g.classList.contains('hover'));
});
// Clicking the selected card again deselects (toggle), closing the preview.
await page.locator('#exploreStrip .strip-card.sel').click();
await page.waitForTimeout(150);
results.previewHiddenAfterSecondStripClick = await page.locator('#explorePreview').isHidden();
// AVAILABLE commercialization: the Available row (p3, Bay) is not geocoded,
// so it has a strip card and NO pin (mapping unavailable is stated, never a
// guessed point); its preview leads with availability, purchase path and the
// amount kind - every one a stored field or its stated absence.
await page.selectOption('#mapCountySelect', 'Bay');
await page.waitForTimeout(400);
results.bayStripCardCount = await page.locator('#exploreStrip .strip-card').count();
results.bayPinCount = await page.locator('#exploreMapCanvas .pin').count();
await page.locator('#exploreStrip .strip-card').first().click();
await page.waitForTimeout(250);
results.bayPreviewText = ((await page.locator('#explorePreview').textContent()) || '').replace(/\s+/g, ' ');
results.bayPreviewHasAvailability = results.bayPreviewText.includes('Availability') && results.bayPreviewText.includes('Available over the counter');
// Acquisition sprint: the preview names the acquisition path, and an unverified one says so - never "no link".
// Acquisition-path sprint: an unverified Available row never reaches the map (acquisition gate), so the preview names a verified path.
results.bayPreviewHasPurchasePath = results.bayPreviewText.includes('How to acquire') && !results.bayPreviewText.includes('Not yet verified') && !results.bayPreviewText.includes('No online purchase link');
results.bayPreviewHasAmountKind = results.bayPreviewText.includes('Amount kind') && results.bayPreviewText.includes('Opening bid');
delete results.bayPreviewText;
await page.locator('#exploreStrip .strip-card').first().click();
await page.waitForTimeout(150);
results.stripCardSelCountAfterToggleOff = await page.locator('#exploreStrip .strip-card.sel').count();

// "Clear county filter" undoes both halves of that one gesture at once -
// the select back to "ALL", the map back out to statewide.
await page.click('#exploreMapReset');
await page.waitForTimeout(500);
results.mapCountySelectValueAfterMapReset = await page.locator('#mapCountySelect').inputValue();
results.mapCanvasZoomedAfterReset = await page.locator('#exploreMapCanvas').evaluate(el => el.classList.contains('zoomed'));

// The Map page's own toolbar - search, ledger pills, watchlist-only - all
// independent of the Auctions page's filters/ledger tabs.
await page.fill('#mapSearchInput', 'nonexistentxyz123');
await page.waitForTimeout(150);
results.mapBubbleCountAfterDeadSearch = await page.locator('#exploreMapCanvas .cluster-bubble').count();
await page.fill('#mapSearchInput', '');
await page.waitForTimeout(150);
await page.click('#mapLedgerPills [data-ledger="laft"]');
await page.waitForTimeout(150);
results.mapLaftPillOnAfterClick = await page.locator('#mapLedgerPills [data-ledger="laft"]').evaluate(el => el.classList.contains('on'));
results.mapAllPillOffAfterLedgerClick = await page.locator('#mapLedgerPills [data-ledger="all"]').evaluate(el => el.classList.contains('on'));
// Bay is the fixture's Lands Available county - switching the Map page's
// own ledger pill to "laft" should leave exactly that county on the map,
// same "structural" reasoning as the bubble-count comment above.
results.mapClusterBubbleCountLaftOnly = await page.locator('#exploreMapCanvas .cluster-bubble').count();
await page.click('#mapLedgerPills [data-ledger="all"]');
await page.waitForTimeout(150);

// --- Phase 55/56/57/60: three-way satellite/terrain basemap toggle ---
// tests/config.js deliberately carries neither googleMapsApiKey nor
// maptilerKey (see its own comment), so this exercises the "not configured
// yet" path for BOTH providers independently - the one every real deploy
// hits until a given provider's key is present. Neither provider's loader
// may be installed in this state: clicking either button with no key
// is just a DOM swap and a message, zero network/CSP surface, and clicking
// one must never touch the other provider's state.
results.mapStyleOutlineOnByDefault = await page.locator('#mapStyleOutline').evaluate(el => el.classList.contains('on'));
// Phase 61: each provider now has its own canvas (see satellite-map.js's
// header for the shared-canvas bug this replaced), so both must be hidden.
results.satelliteCanvasHiddenByDefault =
  await page.locator('#satelliteMapCanvasGoogle').isHidden() &&
  await page.locator('#satelliteMapCanvasMaptiler').isHidden();

await page.click('#mapStyleGoogle');
await page.waitForTimeout(150);
results.mapStyleGoogleOnAfterClick = await page.locator('#mapStyleGoogle').evaluate(el => el.classList.contains('on'));
results.outlineCanvasHiddenAfterGoogleClick = await page.locator('#exploreMapCanvas').isHidden();
results.satelliteCanvasVisibleAfterGoogleClick = await page.locator('#satelliteMapCanvasGoogle').isVisible();
// Scoped to Google's own canvas: with separate canvases per provider
// (Phase 61), each keeps its own setup message once shown, so a bare
// '.satellite-map-setup' locator matches both providers' (one hidden) once
// both have been clicked at least once in this test run.
results.satelliteSetupMessageShownWithNoGoogleKey = await page.locator('#satelliteMapCanvasGoogle .satellite-map-setup').isVisible();
results.googleMapsNotLoadedWithNoKey = await page.evaluate(() => typeof window.google === 'undefined' || !(window.google.maps && window.google.maps.importLibrary));

// Switching back restores the outline map exactly as it was - explore.js
// never re-measures (centroidsOk stays true across the hide/show, see
// satellite-map.js's header note), so this is really testing that hiding it
// didn't corrupt anything, not that it recomputed.
await page.click('#mapStyleOutline');
await page.waitForTimeout(150);
results.outlineCanvasVisibleAfterGoogleSwitchBack = await page.locator('#exploreMapCanvas').isVisible();
results.mapClusterBubbleCountAfterGoogleSwitchBack = await page.locator('#exploreMapCanvas .cluster-bubble').count();

// Same three checks again for the MapTiler button - independent provider,
// independent state, same "not configured yet" path.
await page.click('#mapStyleMaptiler');
await page.waitForTimeout(150);
results.mapStyleMaptilerOnAfterClick = await page.locator('#mapStyleMaptiler').evaluate(el => el.classList.contains('on'));
results.outlineCanvasHiddenAfterMaptilerClick = await page.locator('#exploreMapCanvas').isHidden();
results.satelliteCanvasVisibleAfterMaptilerClick = await page.locator('#satelliteMapCanvasMaptiler').isVisible();
results.satelliteSetupMessageShownWithNoMaptilerKey = await page.locator('#satelliteMapCanvasMaptiler .satellite-map-setup').isVisible();
results.maplibreGlNotLoadedWithNoKey = await page.evaluate(() => typeof window.maplibregl === 'undefined');

await page.click('#mapStyleOutline');
await page.waitForTimeout(150);
results.outlineCanvasVisibleAfterMaptilerSwitchBack = await page.locator('#exploreMapCanvas').isVisible();
results.mapClusterBubbleCountAfterMaptilerSwitchBack = await page.locator('#exploreMapCanvas .cluster-bubble').count();

// Phase 61 regression guard: Google and MapTiler used to share one canvas
// node, which meant activating one after the other had already claimed it
// silently orphaned the first (see satellite-map.js's header for the full
// bug). tests/config.js ships no keys, so this can't exercise real map
// instances, but it does exercise the exact click sequence that surfaced
// the bug (Google, then MapTiler, then back to Google) against the DOM-
// level contract: each provider must own a visible/hidden state completely
// independent of the other's.
await page.click('#mapStyleGoogle');
await page.waitForTimeout(150);
await page.click('#mapStyleMaptiler');
await page.waitForTimeout(150);
await page.click('#mapStyleGoogle');
await page.waitForTimeout(150);
results.googleCanvasVisibleAfterGoogleMaptilerGoogleSequence = await page.locator('#satelliteMapCanvasGoogle').isVisible();
results.maptilerCanvasHiddenAfterGoogleMaptilerGoogleSequence = await page.locator('#satelliteMapCanvasMaptiler').isHidden();
results.mapStyleGoogleOnAfterReturningFromMaptiler = await page.locator('#mapStyleGoogle').evaluate(el => el.classList.contains('on'));
await page.click('#mapStyleOutline');
await page.waitForTimeout(150);

// Return to the Auctions page - just the card list now, no embedded map and
// no List/Split view-toggle (Marc: "auctions shoild be just the list").
await page.click('.nav-bottom-item[data-page="list"]');
await page.waitForTimeout(200);
results.auctionsPageVisibleAfterReturnFromMap = await page.locator('#pageList').isVisible();
results.viewToggleGoneFromAuctions = await page.locator('#viewToggle').count();
results.exploreMapPanelGoneFromAuctions = await page.locator('#exploreMapPanel').count();

// --- reset button: also collapses every county group back to closed ---
await page.click('#resetBtn');
await page.waitForTimeout(150);
results.cardsAfterReset = await page.locator('.prop-card').count();
results.alachuaSelAfterReset = await page.locator('#exploreMapCanvas path[data-county="Alachua"]').evaluate(el => el.classList.contains('sel'));
results.countyGroupsClosedAfterReset = await page.locator('.county-group').evaluateAll(els => els.every(el => !el.open));
results.expandAllLabelAfterReset = await page.locator('#expandAllBtn').textContent();

// Re-expand everything - the hide/remove-btn test below needs a visible card.
await page.click('#expandAllBtn');
await page.waitForTimeout(150);

// --- restore hidden button visibility toggling via hide action ---
// The old #hiddenInfo counter text was replaced by the Hidden Properties
// feature's #hiddenListBtn (a "N hidden - view & recover" button that stays
// hidden until HIDDEN.size > 0, opening the recover modal on click).
const removeBtn = page.locator('.remove-btn').first();
await removeBtn.click();
await page.waitForTimeout(200);
results.cardsAfterHide = await page.locator('.prop-card').count();
results.hiddenListBtnVisible = await page.locator('#hiddenListBtn').isVisible();

// --- switch to Lands Available tab (fixture p3, Bay county) ---
// AVAILABLE commercialization: the Available-only filter row is hidden on Auctions.
results.availFiltersHiddenOnAuctions = await page.locator('#availableFilters').evaluate(el => el.hidden);
await page.click('.ledger-tab[data-ledger="laft"]');
await page.waitForTimeout(150);
results.availFiltersShownOnAvailable = await page.locator('#availableFilters').evaluate(el => !el.hidden);
// p14's source is RESTRICTED: withheld from the list and counted on the ledger page.
results.ledgerWithheldText = ((await page.locator('#ledgerWithheld').textContent()) || '').replace(/\s+/g, ' ').trim();
results.withheldRowNeverRendered = await page.locator('.prop-card[data-pid="p14"]').count();
results.laftTabOnAfterClick = await page.locator('.ledger-tab[data-ledger="laft"]').evaluate(el => el.classList.contains('on'));
results.auctionTabOffAfterLaftClick = await page.locator('.ledger-tab[data-ledger="auction"]').evaluate(el => el.classList.contains('on'));
results.laftCardCount = await page.locator('.prop-card').count();
// County is shown on the group header now, not a per-card tag.
results.laftCountyGroupName = (await page.locator('.county-group .county-name').first().textContent() || '').trim();
results.laftGroupMeta = (await page.locator('.county-group .county-meta').first().textContent() || '').trim();
// The acres branch. p3's lot is 43,560 sq ft - exactly an acre, and over the
// 20,000 threshold - so it must read "1.00 acres", not a six-digit square
// footage nobody can picture. It is also vacant land with no building, so its
// spec line has to carry the lot and NOTHING else: no "Built", no living
// area. That is the majority shape of this inventory, and the reason each
// fact renders independently rather than as one block.
await page.locator('.county-group[data-county="Bay"] summary.county-head').click();
await page.waitForTimeout(200);
results.laftSpecBits = await page.locator('.prop-card').first().locator('.prop-spec span').allTextContents();
results.laftValueLabel = (await page.locator('.prop-card').first().locator('.card-stat-label').nth(1).textContent() || '').trim();
// Phase 65: a Lands Available row's first line names the ledger and says it
// is a fixed-price listing, not a bidding event.
results.laftKicker = await page.locator('.prop-card').first().locator('.prop-kicker').evaluate(el => Array.from(el.children).map(c => c.textContent.trim()).join(' '));
// Three ledgers: an Available card leads with its PURCHASE PATH - p3 carries
// no purchase_url, so the line says so rather than pointing at the list page.
results.laftLedgerLine = await page.locator('.prop-card').first().locator('.prop-ledger-line > span').evaluateAll(els => els.map(el => Array.from(el.children).map(c => c.textContent.trim()).join(' ')));
// Available filters (each reads a stored field): purchase path, amount kind,
// availability status, acreage, recency. p3: no purchase_url, OPENING_BID,
// available_otc, 1.0 acre, last read 2026-08-11 (older than 14 days).
const availCounts = {};
await page.selectOption('#availPathFilter', 'none'); await page.waitForTimeout(150);
availCounts.pathNone = await page.locator('.prop-card').count();
await page.selectOption('#availPathFilter', 'online'); await page.waitForTimeout(150);
availCounts.pathOnline = await page.locator('.prop-card').count();
await page.selectOption('#availPathFilter', 'any');
await page.selectOption('#availAmountKindFilter', 'published'); await page.waitForTimeout(150);
availCounts.amountPublished = await page.locator('.prop-card').count();
await page.selectOption('#availAmountKindFilter', 'unpublished'); await page.waitForTimeout(150);
availCounts.amountUnpublished = await page.locator('.prop-card').count();
await page.selectOption('#availAmountKindFilter', 'any');
await page.selectOption('#availStatusFilter', 'available_otc'); await page.waitForTimeout(150);
availCounts.statusAvailable = await page.locator('.prop-card').count();
await page.selectOption('#availStatusFilter', 'closed'); await page.waitForTimeout(150);
availCounts.statusClosed = await page.locator('.prop-card').count();
await page.selectOption('#availStatusFilter', 'any');
await page.fill('#acreageMin', '0.5'); await page.waitForTimeout(150);
availCounts.acreageHalf = await page.locator('.prop-card').count();
await page.fill('#acreageMin', '2'); await page.waitForTimeout(150);
availCounts.acreageTwo = await page.locator('.prop-card').count();
await page.fill('#acreageMin', ''); await page.waitForTimeout(150);
await page.check('#availSeenRecently'); await page.waitForTimeout(150);
availCounts.seenRecently = await page.locator('.prop-card').count();
await page.uncheck('#availSeenRecently'); await page.waitForTimeout(150);
availCounts.afterReset = await page.locator('.prop-card').count();
results.availFilterCounts = availCounts;
// p3 is the one fixture row with homestead:true - the badge should show up
// right on the card, not just buried in the detail page, since it's exactly
// the kind of risk flag a bidder needs before clicking into anything.
results.laftHomesteadBadge = (await page.locator('.prop-card').first().locator('.lien-pill.homestead').textContent() || '').trim();
// The bare-land branch (p3) is checked later, in the detail-modal section -
// #detailModalInner picks up a permanent "prop-card" class the first time
// ANY detail page is opened (see openDetail's className assignment, never
// reset by closeDetail), which would otherwise inflate every .prop-card
// count assertion between here and there.

// --- switch to Certificates tab (fixture p4) ---
await page.click('.ledger-tab[data-ledger="certificate"]');
await page.waitForTimeout(150);
results.certCardCount = await page.locator('.cert-card').count();
results.certCardTitle = await page.locator('.cert-card .prop-address').first().textContent();
// Cert cards were pared down to a 3-box stat grid (Amount / Account # /
// Expires) - everything else (tax year, issued date, interest rate, the
// account-# copy button) moved to the full property page. Read the stat
// boxes by position instead of the old .prop-meta/.meta-bid text lines,
// which no longer exist on the card.
results.certCardAmount = (await page.locator('.cert-card .card-stat-grid .card-stat').nth(0).locator('.card-stat-val').textContent() || '').trim();
results.certCardAccount = (await page.locator('.cert-card .card-stat-grid .card-stat').nth(1).locator('.card-stat-val').textContent() || '').trim();
results.certCardExpires = (await page.locator('.cert-card .card-stat-grid .card-stat').nth(2).locator('.card-stat-val').textContent() || '').trim();
results.certCardCta = await page.locator('.cert-card .cta-btn').first().textContent();
results.certCardExpiresCountdown = await page.locator('.cert-card .countdown').count();
// Three ledgers (2026-09-30): the certificate card leads with the
// instrument's own status lines - list presence, redemption (never
// tracked, so "Not published"), and the underlying parcel with its
// records in the other ledgers (p4 shares parcel 111 with auction p1).
results.certStatusLines = await page.locator('.cert-card .cert-status-line').evaluateAll(els => els.map(e => e.textContent.replace(/\s+/g, ' ').trim()));

// --- "yield desk" additions: the stat grid grows from 3 to 6 boxes
// (Interest Rate / Est. Accrued Interest / TDA Eligibility appended after
// the original three), plus a redemption-status pill next to the
// expiration countdown. p4's issued_date (2023-06-01) is fixed and more
// than CERT_TDA_WAIT_YEARS in the past, so "Eligible now" never drifts.
// The accrued-interest dollar figure IS time-relative (simple interest
// accrues every day), so it's checked against an independently-computed
// expectation with a small tolerance rather than a frozen string - same
// pattern this suite already uses for other date-relative fields.
//
// No detail modal opens here - opening one anywhere before the .prop-card
// exact-count assertions further down (cardCountBackOnAuctionTab, the
// search/county-quick counts, archive counts) would permanently add
// #detailModalInner's own .prop-card class to the page and throw every one
// of them off by +1 (the exact bug the LAFT bare-land check hit last
// phase). The cert detail-page assertions live later in this file instead,
// grouped with that same relocated block. ---
results.certCardStatCount = await page.locator('.cert-card .card-stat-grid .card-stat').count();
results.certCardInterestRate = (await page.locator('.cert-card .card-stat-grid .card-stat').nth(3).locator('.card-stat-val').textContent() || '').trim();
results.certCardTdaEligibility = (await page.locator('.cert-card .card-stat-grid .card-stat').nth(5).locator('.card-stat-val').textContent() || '').trim();
results.certCardStatusPill = (await page.locator('.cert-card .pill').textContent() || '').trim();
const certAccruedText = (await page.locator('.cert-card .card-stat-grid .card-stat').nth(4).locator('.card-stat-val').textContent() || '').trim();
{
  // Mirrors accruedInterestEst(p4) in public/app.js exactly.
  const issuedMs = Date.UTC(2023, 5, 1);
  const years = Math.max(0, (Date.now() - issuedMs) / (365.25 * 86400000));
  const expected = 1234.56 * 0.18 * years;
  const got = Number(certAccruedText.replace(/[^0-9.]/g, ''));
  results.certCardAccruedInterestPlausible = Math.abs(got - expected) < 2 && certAccruedText.startsWith('$');
}

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
// "Nd ago" badge instead of the usual countdown.
//
// Archive is no longer a chip in the summary strip; it is a toggle inside
// Filters & Sort, so the panel has to be opened first. The behaviour it
// gates is unchanged, and #chipArchive still carries the count (it moved
// into the toggle's label), so every assertion below is as it was. ---
// The panel was already opened further up this file and never closed, so a
// bare click on #filtersToggle here would CLOSE it and every locator below
// would resolve to a hidden element. Ask for its state instead of assuming.
const ensureFiltersOpen = async () => {
  const open = await page.locator('#filtersPanel').evaluate(el => el.classList.contains('open'));
  if (!open) { await page.click('#filtersToggle'); await page.waitForTimeout(200); }
};
await ensureFiltersOpen();
results.archiveToggleInFilters = await page.locator('#archiveToggle').isVisible();
results.archiveChipNotInStrip = await page.locator('.summary-strip .chip[data-status="archive"]').count();
await page.click('#archiveToggle');
await page.waitForTimeout(250);
results.archiveChipCount = (await page.locator('#chipArchive').textContent()).trim();
results.pastDueCardVisibleArchiveView = await page.locator('.prop-card:has-text("Past Due Ln")').count();
results.archiveViewOtherCardsCount = await page.locator('.prop-card').count(); // should be 1 - archive is exclusive
results.archiveCardAgoBadge = (await page.locator('.prop-card:has-text("Past Due Ln") .countdown.past').textContent().catch(() => '')) || '';
// The page header has to say the list is showing past auctions only - with
// the always-visible Archive chip gone, this notice is the only thing on
// screen explaining why every current listing has vanished.
results.archiveModeNoteShown = await page.locator('#archiveModeNote').isVisible();
// ...and offer the way out of it.
await page.click('#exitArchiveBtn');
await page.waitForTimeout(200);
results.archiveNoteGoneAfterExit = await page.locator('#archiveModeNote').count();
results.archiveToggleUntickedAfterExit = await page.locator('#archiveToggle').isChecked();

// --- stale-data warning: every fixture's updated_at is days old relative to
// "today", so the newest-row calc should already be past STALE_DATA_HOURS ---
results.staleWarningClassPresent = await page.locator('#generatedAt.stale').count();
results.staleWarningText = (await page.locator('#generatedAt').textContent()) || '';

await page.click('.summary-strip .chip[data-status="live"]');
await page.waitForTimeout(150);

// ============================================================
// Phase 8: search, county quick-select, CSV export, card cleanup, detail
// modal. Fixture now has 9 live auction properties (p1, p5-p12; p2 is
// gone/expired) across Alachua, Brevard, Charlotte, Duval(x2), Escambia(x2),
// Marion(x2) - minus whichever one got hidden earlier.
// ============================================================

// --- card cleanup: cards were pared down to header + a quiet parcel-#
// reference line + a 2-box headline stat grid (Opening Bid / the county's
// own just value for a stated roll year, falling back to assessed value -
// these two are the actual "cost vs. worth" pitch of the listing) + 3
// reference links (Street View / Appraiser / Zillow) + an optional CTA + a
// small "view full property page" link. Potential equity (the old
// .spread-badge), the full title-status banner, owner/parcel copy buttons,
// and notes all moved to the detail modal only - .spread-badge no longer
// exists anywhere on a card, confirmed by asserting its count is now 0. ---
results.cardStatLabelsFirst = await page.locator('.prop-card').first().locator('.card-stat-label').allTextContents();
results.cardParcelLineFirst = (await page.locator('.prop-card').first().locator('.prop-parcel-line').textContent() || '').trim();
results.spreadBadgeCount = await page.locator('.spread-badge').count();
// --- Phase 65: kicker line, identifier row, facts row ---
// p1 (1 Main St): an open auction 3 days out -> "Auction · Sale <date>" with
// the within-14-days phase colour; parcel AND case on one row; facts row
// says plainly what is not known yet (no coordinates, flood never checked)
// and shows the market ÷ bid ratio (90,000 / 5,000 = 18.0×) that isTopPick()
// already screens on. Nothing on this row is invented - see cardFactsHtml().
{
  const first = page.locator('.prop-card').first();
  // The kicker/facts are sibling <span>s with no whitespace text between
  // them (CSS gap does the spacing), so join the pieces explicitly.
  const spanText = el => Array.from(el.children).map(c => c.textContent.trim()).join(' ');
  results.cardKickerFirst = await first.locator('.prop-kicker').evaluate(spanText);
  results.cardKickerPhaseClassFirst = await first.locator('.kicker-phase').evaluate(el => Array.from(el.classList).find(c => c.startsWith('phase-')));
  results.cardCaseLineFirst = (await first.locator('.prop-case-line').textContent() || '').trim();
  results.cardFactsFirst = await first.locator('.prop-facts > span').evaluateAll(els => els.map(el => Array.from(el.children).map(c => c.textContent.trim()).join(' ')));
  results.cardFactsMutedCountFirst = await first.locator('.prop-facts .muted').count();
  // Three ledgers: an auction card leads with its RESULT - p1's sale is
  // upcoming, so "Sale not yet held"; never an inferred outcome.
  results.cardLedgerLineFirst = await first.locator('.prop-ledger-line > span').evaluateAll(els => els.map(el => Array.from(el.children).map(c => c.textContent.trim()).join(' ')));
}

// --- county tax-roll facts on the card ---
// scripts/enrich_property_details.py fills these from Florida's statewide
// cadastral layer. The fixture carries three deliberately different states,
// because that is what production looks like.
//
// p1 is fully enriched WITH a building.
const p1Card = page.locator('.prop-card').first();
results.cardSpecBits = await p1Card.locator('.prop-spec span').allTextContents();
results.cardLastSale = (await p1Card.locator('.prop-lastsale').textContent() || '').replace(/\s+/g, ' ').trim();
// The legal description is a paragraph of surveyor's shorthand. On the card
// it is one clamped line - the full text lives in the title attribute and on
// the full property page.
results.cardLegalIsOneLine = await p1Card.locator('.prop-legal').evaluate(el =>
  getComputedStyle(el).whiteSpace === 'nowrap' && getComputedStyle(el).textOverflow === 'ellipsis');
results.cardLegalFullTextInTitle = ((await p1Card.locator('.prop-legal').getAttribute('title')) || '').startsWith('BEG 418 FT S');

// A row the enrichment script has NOT matched must still render the lean
// card it always was - no empty spec line, no orphan "Last sold" label.
// p5 (500 Elm Way, Charlotte) is deliberately left unenriched in the fixture.
const p5Card = page.locator('.prop-card:has-text("500 Elm Way")').first();
results.unenrichedCardExtras = await p5Card.evaluate(el => [
  el.querySelectorAll('.prop-spec').length,
  el.querySelectorAll('.prop-lastsale').length,
  el.querySelectorAll('.prop-legal').length
].join(','));

// --- collapse everything first, so the next search test genuinely proves a
// search auto-opens a matching county rather than finding it already open
// from earlier in this run ---
if ((await page.locator('#expandAllBtn').textContent()) === 'Collapse all') {
  await page.click('#expandAllBtn');
  await page.waitForTimeout(150);
}
// Duval renders as two county-groups now (one per sale date - see
// countyGroupCount above), so this can't be a single-element .evaluate()
// the way it could when every county was guaranteed exactly one group;
// .evaluateAll(...).some(...) degrades to the same boolean a single-match
// .evaluate() would have returned when there's only one match, and stays
// correct now that there are two.
results.duvalGroupClosedBeforeSearch = await page.locator('.county-group[data-county="Duval"]').evaluateAll(els => els.some(el => el.open));

// --- search: "Searchable" should isolate p7 (12 Searchable Blvd, Duval) and
// auto-expand its county group even though it was just collapsed ---
await page.fill('#searchInput', 'Searchable');
await page.waitForTimeout(200);
results.searchFilteredCardCount = await page.locator('.prop-card').count();
results.searchFilteredAddress = (await page.locator('.prop-card .prop-address').first().textContent() || '').trim();
results.searchAutoExpandsMatch = await page.locator('.county-group[data-county="Duval"]').evaluateAll(els => els.some(el => el.open));
await page.fill('#searchInput', '');
await page.waitForTimeout(150);
results.cardCountAfterClearingSearch = await page.locator('.prop-card').count();

// --- county quick-select dropdown: pick Duval (p6 + p7) - should auto-expand
// both of its date-groups (see the countyQuick change handler in app.js,
// which adds every groupKeyOf() for the picked county to expandedCounties,
// not just one) ---
await page.selectOption('#countyQuick', 'Duval');
await page.waitForTimeout(150);
results.cardCountAfterCountyQuickDuval = await page.locator('.prop-card').count();
results.duvalChipOnAfterQuickSelect = await page.locator('#countyChips .chipx[data-value="Duval"]').evaluate(el => el.classList.contains('on')).catch(() => null);
results.duvalGroupOpenAfterQuickSelect = await page.locator('.county-group[data-county="Duval"]').evaluateAll(els => els.some(el => el.open));
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

// The export's column list is a second, parallel copy of the card's field
// list, and the two can drift apart silently - a column added to the card
// and forgotten here exports a spreadsheet that is quietly missing the
// thing the user filtered on. So read the file back and check the tax-roll
// columns are there, in order, and that the enriched row's cells line up
// under them.
{
  const csvText = fs.readFileSync(await download.path(), 'utf8');
  const parseCsvLine = line => {
    const out = []; let cur = '', q = false;
    for (let i = 0; i < line.length; i++) {
      const c = line[i];
      if (q) { if (c === '\"') { if (line[i + 1] === '\"') { cur += '\"'; i++; } else q = false; } else cur += c; }
      else if (c === '\"') q = true;
      else if (c === ',') { out.push(cur); cur = ''; }
      else cur += c;
    }
    out.push(cur); return out;
  };
  const lines = csvText.split('\r\n').filter(Boolean);
  const hdr = parseCsvLine(lines[0]);
  const TAXROLL = ['Year Built', 'Living Area (sq ft)', 'Lot Size (sq ft)', 'Buildings',
                   'Land Value', 'Building / Improvement Value', 'Last Sale Price',
                   'Last Sale Year', 'Legal Description'];
  results.csvTaxRollColumns = TAXROLL.every(c => hdr.includes(c))
    && TAXROLL.map(c => hdr.indexOf(c)).every((n, i, a) => i === 0 || n === a[i - 1] + 1);
  // The just-value year travels as its own column rather than being baked
  // into the heading, so a sheet mixing roll years is still readable.
  results.csvValueYearColumn = hdr[hdr.indexOf('County Just Value') + 1] === 'Just Value Year';
  // Every data row must have exactly as many cells as the header - the
  // legal description contains commas, so an escaping slip shows up here.
  results.csvRowsWellFormed = lines.slice(1).every(l => parseCsvLine(l).length === hdr.length);
  // A blank-by-default column that only ever asserts a positive - "" (not
  // "No") for a row without a confirmed exemption on file.
  results.csvHomesteadColumn = hdr.includes('Homestead Exemption');
  const enriched = lines.slice(1).map(parseCsvLine)
    .find(c => c[hdr.indexOf('Address')] === '1 Main St');
  results.csvHomesteadBlankForP1 = !!enriched && enriched[hdr.indexOf('Homestead Exemption')] === '';
  // The two yield-desk columns are shared across all three ledgers' exports
  // (one cols array, filtered by row - see the note on the tax-roll columns
  // above about drift) - blank for a non-certificate row, not "N/A" or "0".
  results.csvAccruedInterestColumn = hdr.includes('Est. Accrued Interest');
  results.csvTdaEligibilityColumn = hdr.includes('TDA Eligibility Date');
  results.csvYieldColumnsBlankForP1 = !!enriched
    && enriched[hdr.indexOf('Est. Accrued Interest')] === ''
    && enriched[hdr.indexOf('TDA Eligibility Date')] === '';
  // Raw numbers, not the card's display strings: 43,560 sq ft reads as
  // "1.00 acres" on a card but has to stay sortable in a spreadsheet.
  const ENRICHED_KEYS = ['County Just Value', 'Just Value Year', 'Year Built', 'Living Area (sq ft)',
    'Lot Size (sq ft)', 'Buildings', 'Land Value', 'Building / Improvement Value',
    'Last Sale Price', 'Last Sale Year'];
  results.csvEnrichedCells = ENRICHED_KEYS.map(c => enriched ? enriched[hdr.indexOf(c)] : '?').join('|');
  results.csvLegalUnclamped = !!enriched
    && enriched[hdr.indexOf('Legal Description')].endsWith('S 50 FT TO POB');
}

// --- detail modal: needs a visible "View full property page" link, so
// make sure everything is expanded again first (county quick-select above
// only guarantees Duval). ---
await page.click('#expandAllBtn');
await page.waitForTimeout(150);
if ((await page.locator('#expandAllBtn').textContent()) === 'Expand all') {
  await page.click('#expandAllBtn');
  await page.waitForTimeout(150);
}
// County groups sort by nearest sale date first, not alphabetically by
// county, so the nearest-date card would normally be Brevard's p12 (2 days
// out) rather than Alachua's p1 - but the remove-btn hide test above this
// already hid that exact card (it always hides whichever card is currently
// first), so by the time we get here the first remaining card is p1
// (Alachua, 3 days out), which has all 6 link types set in the fixture.
const firstDetailBtn = page.locator('.detail-btn[data-action="viewdetails"]').first();
await firstDetailBtn.click();
await page.waitForTimeout(150);
results.detailModalVisibleAfterOpen = await page.locator('#detailModal').isVisible();
results.detailModalHasAddress = await page.locator('#detailModalInner .detail-address').count();
results.detailModalHasLinks = await page.locator('#detailModalInner .detail-links a').count();
// --- Phase 35: provenance block (data source + last-synced line). p1 has
// harvester_source set and every real url_* link populated, so this is the
// "everything present, nothing estimated" baseline - the TX phase near the
// end of this file covers the opposite (missing harvester link -> estimated
// suffix; the fixture there also covers the no-harvester_source omission
// case for a *different* field, since p1 always has one set). ---
results.detailProvenanceText = ((await page.locator('#detailModalInner .detail-provenance').textContent()) || '').trim();
results.detailLinksHaveNoEstimatedSuffix = !(await page.locator('#detailModalInner .detail-links').textContent()).includes('estimated search');

// --- Phase 66: "At a glance" summary + section nav on the full page ---
// p1: FL auction, real address, parcel + case, published bid, just value
// AND assessed on file, no photo (NULL), no coordinates, flood never
// checked -> exactly those three gaps listed, nothing invented.
results.oppCellLabels = await page.locator('#detailModalInner .opp-cell .opp-label').allTextContents();
// innerText, not textContent: the .opp-sub line is display:block, so the
// rendered text has a break between the value and its sub-line.
const oppText = n => page.locator('#detailModalInner .opp-cell').nth(n).locator('.opp-val').evaluate(el => el.innerText.replace(/\s+/g, ' ').trim());
results.oppWhatText = await oppText(0);
results.oppWhereText = await oppText(1);
results.oppWhenClass = await page.locator('#detailModalInner .opp-cell').nth(2).locator('.opp-val').evaluate(el => el.className);
results.oppBidText = await oppText(3);
results.oppValueText = await oppText(4);
results.oppGaps = await page.locator('#detailModalInner .opp-gaps li').allTextContents();
results.detailNavLabels = await page.locator('#detailModalInner .detail-nav button').allTextContents();
// Jumping to Risk & Legal scrolls the modal's own scroll box, and marks the pill.
const scrollBefore = await page.locator('#detailModalInner').evaluate(el => el.scrollTop);
await page.click('#detailModalInner .detail-nav button[data-target="risk"]');
await page.waitForTimeout(500);
results.detailNavJumpScrolled = (await page.locator('#detailModalInner').evaluate(el => el.scrollTop)) > scrollBefore;
results.detailNavJumpMarksPill = await page.locator('#detailModalInner .detail-nav button[data-target="risk"]').evaluate(el => el.classList.contains('on'));
results.showOnMapBtnText = ((await page.locator('#detailModalInner .show-on-map-btn').textContent()) || '').trim();
await page.locator('#detailModalInner').evaluate(el => { el.scrollTop = 0; });

// --- the tax-roll facts on the full property page ---
// The card carries the three-fact summary; the page carries the rest,
// including the whole legal description rather than one clamped line.
results.detailStatLabels = await page.locator('#detailModalInner .detail-stat-label').allTextContents();
results.detailStatValues = await page.evaluate(() => {
  // Phase 35: a stat label can now carry a trailing infoTip() "i" glyph
  // (e.g. "Building / Improvement Value i") - strip the .info-tip node
  // before reading label text so this keys on the same label text as
  // before, regardless of whether that particular label happens to have a
  // tooltip today.
  const labelOf = el => {
    const clone = el.querySelector('.detail-stat-label').cloneNode(true);
    const tip = clone.querySelector('.info-tip');
    if (tip) tip.remove();
    return clone.textContent.trim();
  };
  const out = {};
  document.querySelectorAll('#detailModalInner .detail-stat').forEach(el => {
    out[labelOf(el)] = el.querySelector('.detail-stat-val').textContent.trim();
  });
  return ['Year Built', 'Living Area', 'Lot Size', 'Buildings', 'Last Sale', 'Land Value', 'Building / Improvement Value'].map(k => out[k] || '-').join(' | ');
});
// Full text here, not the clamped card version.
results.detailLegalIsFull = ((await page.locator('#detailModalInner .detail-legal p').textContent()) || '').trim().endsWith('S 50 FT TO POB');
// "County Assessed Value" is always pushed, so the assessed figure is still
// named and distinguishable from the just value above it - the two are
// different numbers and the old page called one of them "Market Value".
results.detailNamesBothValues = await page.evaluate(() => {
  const labels = [...document.querySelectorAll('#detailModalInner .detail-stat-label')].map(e => e.textContent.trim());
  return labels.includes('2025 County Just Value') && labels.includes('County Assessed Value');
});
// p1 has no homestead exemption on file - the stat should not appear at
// all (not "No"), since absence of the field is "not confirmed", never a
// confirmed negative.
results.homesteadStatAbsentForP1 = !(await page.evaluate(() =>
  [...document.querySelectorAll('#detailModalInner .detail-stat-label')].some(e => e.textContent.trim() === 'Homestead Exemption')));
// Florida-law reminder that survives every property, not just risky ones -
// code/utility/IRS liens are never screened for by this app.
results.muniLienNoteVisible = await page.locator('#detailModalInner .muni-lien-note').count();

// --- Bid & profit calculator: the existing Fees/Walk-Away-Above math made
// visible and interactive, rather than a second parallel calculator. ---
results.calcDrawerPresent = await page.locator('#detailModalInner .calc-drawer').count();
await page.click('#detailModalInner .calc-drawer summary');
await page.waitForTimeout(150);
// With no repair/lien-buffer entered yet, the ceiling and net figures match
// what Walk Away Above and Gross Equity Spread already show elsewhere on
// the same page - the drawer doesn't invent a second set of numbers.
//
// Phase 20 regression coverage: "viewdetails" populates BOTH #detailModalInner
// (this full-screen modal) and #detailPanel (the desktop persistent panel,
// see the dedicated desktop-viewport check below) with their own copy of
// detailHtml(p) - including their own #calcNetResult/#calcMaxBidResult pair -
// at the same time, regardless of viewport. Every locator below is scoped to
// #detailModalInner so it unambiguously targets the copy inside the modal
// that's actually visible right now; before the Phase 20 fix (scoping the
// input handler's own DOM lookup to the edited drawer via
// drawer.querySelector instead of a bare document.getElementById), a bare
// '#calcMaxBidResult'/'#calcNetResult'/'.calc-drawer ...' locator here hit
// Playwright's strict-mode violation (two matching elements) - the exact
// crash Phase 19 reproduced - and even once scoped to avoid that violation,
// the modal's own result text never updated because the global listener was
// always writing into the OTHER (panel) copy. So this block, once scoped,
// fails against the unfixed app.js and passes against the fixed one.
results.calcInitialMaxBid = (await page.locator('#detailModalInner #calcMaxBidResult').textContent() || '').trim();
results.calcInitialNet = (await page.locator('#detailModalInner #calcNetResult').textContent() || '').trim();
await page.fill('#detailModalInner .calc-drawer input[data-calc-field="repair"]', '5000');
await page.fill('#detailModalInner .calc-drawer input[data-calc-field="muni"]', '1000');
await page.waitForTimeout(150);
results.calcNetAfterInput = (await page.locator('#detailModalInner #calcNetResult').textContent() || '').trim();
results.calcMaxBidAfterInput = (await page.locator('#detailModalInner #calcMaxBidResult').textContent() || '').trim();
// The repair estimate and lien buffer are the bidder's own numbers, not
// server state - closing and reopening the SAME property's page should
// find them still there (localStorage), not reset to blank.
//
// Phase 20: every "✕" close button below is scoped to #detailModalInner for
// the same reason the calculator locators above are - detailHtml(p) (data-
// action="closedetail" button included) renders into #detailPanel too the
// moment any property has ever been viewed, and that copy stays in the DOM
// (just CSS-hidden below the desktop breakpoint) for the rest of the page's
// life. A bare '[data-action="closedetail"]' selector is therefore
// ambiguous from here on - Playwright picks "the first" match in document
// order, which is #detailPanel's copy, then hangs forever waiting for an
// element CSS hides to become visible. This never affects a real user (a
// mouse click only ever targets the one element actually under the
// pointer); it's a pre-existing gap in the test's own selectors, only
// reachable once the calculator crash above it is fixed, so it's addressed
// here alongside that fix rather than left to block this regression test.
await page.click('#detailModalInner [data-action="closedetail"]');
await page.waitForTimeout(150);
await firstDetailBtn.click();
await page.waitForTimeout(150);
await page.click('#detailModalInner .calc-drawer summary');
await page.waitForTimeout(150);
results.calcInputPersistsAfterReopen = await page.locator('#detailModalInner .calc-drawer input[data-calc-field="repair"]').inputValue();

// Phase 20: explicit no-leakage check. The persistence check just above
// only proves the SAME property keeps its own repair estimate after being
// closed and reopened - it doesn't prove a DIFFERENT property stays clean.
// Every calc input is read/written through calcInputsFor(p.id) /
// saveCalcInput(pid, ...), a per-property localStorage key, so this is
// expected to already hold; this makes it an explicit, checked assertion
// instead of an unverified assumption.
await page.click('#detailModalInner [data-action="closedetail"]');
await page.waitForTimeout(150);
const secondDetailBtn = page.locator('.detail-btn[data-action="viewdetails"]').nth(1);
await secondDetailBtn.click();
await page.waitForTimeout(150);
await page.click('#detailModalInner .calc-drawer summary');
await page.waitForTimeout(150);
results.calcInputNoLeakToOtherProperty = await page.locator('#detailModalInner .calc-drawer input[data-calc-field="repair"]').inputValue();
await page.click('#detailModalInner [data-action="closedetail"]');
await page.waitForTimeout(150);
await firstDetailBtn.click();
await page.waitForTimeout(150);

// close via the close button
await page.click('#detailModalInner [data-action="closedetail"]');
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
// The title-search warning used to be a permanent badge in the header. It is
// now behind a Terms button in the footer, so this checks the button is there
// AND that the warning survived the move - which the old assertion could not
// tell you, since it only looked at whether a badge was on screen.
results.termsButtonVisible = await page.locator('#termsBtn').isVisible();
await page.click('#termsBtn');
await page.waitForTimeout(250);
results.termsModalOpens = await page.locator('#termsModal').isVisible();
results.termsCarryTitleWarning =
  /not a certified title search/i.test(await page.locator('#termsModal').textContent());
// Launch-readiness honesty pass: notes are readable by every approved member
// (noteHtml renders other authors' notes), so the Terms must say they are
// shared - they used to call them private.
results.termsSayNotesShared = /Team notes are shared/.test(await page.locator('#termsModal').textContent());
results.termsNoNotesPrivateClaim = !/notes[^.]*visible only to you/i.test(await page.locator('#termsModal').textContent());
await page.click('#termsCloseBtn');
await page.waitForTimeout(200);
results.termsModalCloses = await page.locator('#termsModal').isHidden();
results.cardStatGridCount = await page.locator('.prop-card .card-stat-grid').count();
results.lienPillFirstText = (await page.locator('.prop-card .lien-pill').first().textContent() || '').trim();
results.homesteadBadgeAbsentForP1 = await page.locator('.prop-card').first().locator('.lien-pill.homestead').count();
// Phase 20: scoped to #detailModalInner for the same reason as the
// calculator and closedetail locators above - by this point in the file a
// property has already been viewed, so detailHtml(p)'s own .info-tip
// elements exist in BOTH #detailModalInner and #detailPanel's copies at
// once, and a bare '.info-tip' selector was silently counting both (8
// instead of the real, single-render count of 4).
results.infoTipCount = await page.locator('#detailModalInner .info-tip').count();
// --- bare-land branch (p3, LAFT ledger): land_value equal to market means
// the derived Building/Improvement stat should read as bare land, not a
// misleading "$0". Safe to open a second property's detail page here -
// every exact .prop-card count assertion in this file runs before this
// point (see the note left where this check used to live, up on the LAFT
// tab, before it turned out to inflate cardCountBackOnAuctionTab and
// friends by counting the now-permanently-"prop-card"-classed
// #detailModalInner shell as a ninth card).
await page.click('.ledger-tab[data-ledger="laft"]');
await page.waitForTimeout(150);
// "Bay" was already expanded by the earlier LAFT-tab check and that state
// persists across ledger switches - a blind click on its summary would
// TOGGLE it closed again. Ask #expandAllBtn's own label instead of assuming.
if ((await page.locator('#expandAllBtn').textContent()) === 'Expand all') {
  await page.click('#expandAllBtn');
  await page.waitForTimeout(200);
}

// --- "junk land" quick filters: laft-only row, checked against the one
// LAFT fixture (p3), which land_value===market makes bare land (see the
// isBareLand branch this reuses) but is NOT a sliver (lot_sqft 43560 = 1
// full acre) - so hideBareLandOnly should remove it and hideSlivers should
// not. No new fixture row needed, and no detail modal opens here either. ---
results.junkLandRowVisibleOnLaft = await page.locator('#junkLandRow').isVisible();
// Scoped to #main, not bare .prop-card - #detailModalInner permanently
// gains the .prop-card class after the very first detail-modal open
// anywhere in this file (see the note further up), and by this point in
// the suite one has already happened. #main never contains that shell.
const mainCards = () => page.locator('#main .prop-card');
results.laftCountBeforeJunkFilters = await mainCards().count();
await page.click('#hideSliversOnly');
await page.waitForTimeout(150);
results.laftCountAfterHideSlivers = await mainCards().count();
await page.click('#hideSliversOnly');
await page.waitForTimeout(150);
await page.click('#hideBareLandOnly');
await page.waitForTimeout(150);
results.laftCountAfterHideBareLand = await mainCards().count();
await page.click('#hideBareLandOnly');
await page.waitForTimeout(150);
results.laftCountAfterUncheckingFilters = await mainCards().count();

await page.locator('.prop-card').first().locator('.detail-btn').first().click();
await page.waitForTimeout(300);
results.laftBareLandStat = await page.evaluate(() => {
  // Phase 35: same trailing-tooltip-glyph handling as detailStatValues above.
  const labelOf = e => {
    const clone = e.querySelector('.detail-stat-label').cloneNode(true);
    const tip = clone.querySelector('.info-tip');
    if (tip) tip.remove();
    return clone.textContent.trim();
  };
  const el = [...document.querySelectorAll('#detailModalInner .detail-stat')]
    .find(e => labelOf(e) === 'Building / Improvement Value');
  return el ? el.querySelector('.detail-stat-val').textContent.trim() : null;
});
await page.click('#detailModalInner [data-action="closedetail"]');
await page.waitForTimeout(150);
await page.click('.ledger-tab[data-ledger="auction"]');
await page.waitForTimeout(150);
results.linkIconPresent = (await page.locator('.prop-links a').first().innerHTML() || '').includes('link-icon');
// p1 (Alachua, clean/12x+ ratio potential) should be a top pick - confirm the
// upgraded pill-style banner renders with its ratio callout.
results.toppickBannerText = (await page.locator('.toppick-banner').first().textContent().catch(() => '')) || '';

// --- junk-land row is laft-only; the CSV export button and auction cards'
// equity-spread bar are per-ledger too. Auction ledger is active here. ---
results.junkLandRowHiddenOnAuction = await page.locator('#junkLandRow').isHidden();
results.exportBtnLabelAuction = (await page.locator('#exportCsvBtn').textContent() || '').trim();
// p1 (bid 5000, market 90000) clears the bidPublished/marketVal>0 guard, so
// its card should carry the bar; p2 (dropped/closed) shouldn't, since a
// closed auction's bid-vs-value comparison stopped being the point.
results.spreadBarPresentP1 = await page.locator('.prop-card:has-text("1 Main St") .spread-bar').count();

// --- Certificates: the full property page carries two more derived
// figures than the card (Est. Total Return needs the extra room), both
// with an explanation tooltip. Safe to open here - every exact .prop-card
// count assertion in this file has already run. ---
await page.click('.ledger-tab[data-ledger="certificate"]');
await page.waitForTimeout(150);
results.exportBtnLabelCertificate = (await page.locator('#exportCsvBtn').textContent() || '').trim();

// The certificate export is where the two yield columns actually carry a
// value - re-download here (filename is ledger-scoped: taxdeed-certificate-
// ...) and check p4's row instead of trusting the auction export above to
// prove both branches.
{
  const certDownloadPromise = page.waitForEvent('download');
  await page.click('#exportCsvBtn');
  const certDownload = await certDownloadPromise;
  const csvText = fs.readFileSync(await certDownload.path(), 'utf8');
  const parseCsvLine = line => {
    const out = []; let cur = '', q = false;
    for (let i = 0; i < line.length; i++) {
      const c = line[i];
      if (q) { if (c === '\"') { if (line[i + 1] === '\"') { cur += '\"'; i++; } else q = false; } else cur += c; }
      else if (c === '\"') q = true;
      else if (c === ',') { out.push(cur); cur = ''; }
      else cur += c;
    }
    out.push(cur); return out;
  };
  const lines = csvText.split('\r\n').filter(Boolean);
  const hdr = parseCsvLine(lines[0]);
  const row = parseCsvLine(lines[1]);
  const issuedMs = Date.UTC(2023, 5, 1);
  const years = Math.max(0, (Date.now() - issuedMs) / (365.25 * 86400000));
  const expected = 1234.56 * 0.18 * years;
  const got = Number(row[hdr.indexOf('Est. Accrued Interest')]);
  results.csvCertAccruedPlausible = Math.abs(got - expected) < 2;
  results.csvCertTdaDate = row[hdr.indexOf('TDA Eligibility Date')];
}

if ((await page.locator('#expandAllBtn').textContent()) === 'Expand all') {
  await page.click('#expandAllBtn');
  await page.waitForTimeout(200);
}
await page.locator('.cert-card').first().locator('.detail-btn').first().click();
await page.waitForTimeout(300);
const certDetailText = await page.locator('#detailModalInner').textContent();
results.certDetailHasAccrued = /Est\. Accrued Interest/.test(certDetailText);
results.certDetailHasTotalReturn = /Amount \+ est\. accrued interest/.test(certDetailText);
results.certDetailTdaEligibleNow = /TDA Eligibility[\s\S]{0,40}Eligible now/.test(certDetailText);
results.certDetailYieldInfoTips = await page.locator(
  '#detailModalInner .detail-stat:has-text("Est. Accrued Interest") .info-tip, ' +
  '#detailModalInner .detail-stat:has-text("TDA Eligibility") .info-tip'
).count();
await page.click('#detailModalInner [data-action="closedetail"]');
await page.waitForTimeout(150);
await page.click('.ledger-tab[data-ledger="laft"]');
await page.waitForTimeout(150);
results.exportBtnLabelLaft = (await page.locator('#exportCsvBtn').textContent() || '').trim();
results.laftPurchasePriceLabel = (await page.locator('.prop-card .card-stat-label').first().textContent() || '').trim();
results.laftCtaText = (await page.locator('.prop-card .cta-btn').first().textContent() || '').trim();
await page.click('.ledger-tab[data-ledger="auction"]');
await page.waitForTimeout(150);

// --- My Bid List: a small capped shortlist (⚐/⚑), separate from the
// uncapped ♥ Favorites - add from a card, open the modal, remove from
// inside the modal, close it. Nothing above this point touches bid_list,
// so it should still read 0/10 going in. ---
results.bidListChipTextInitial = (await page.locator('#bidListCount').textContent() || '').trim();
if ((await page.locator('#expandAllBtn').textContent()) === 'Expand all') {
  await page.click('#expandAllBtn');
  await page.waitForTimeout(150);
}
const firstBidBtn = page.locator('.prop-card .bid-btn').first();
await firstBidBtn.scrollIntoViewIfNeeded();
results.bidBtnIconBefore = (await firstBidBtn.textContent() || '').trim();
await firstBidBtn.click();
await page.waitForTimeout(150);
results.bidBtnIconAfterAdd = (await firstBidBtn.textContent() || '').trim();
results.bidListChipTextAfterAdd = (await page.locator('#bidListCount').textContent() || '').trim();

await page.click('#bidListToggle');
await page.waitForTimeout(200);
results.bidListModalVisible = await page.locator('#bidListModal').isVisible();
results.bidListModalCardCount = await page.locator('#bidListModal .prop-card').count();

await page.locator('#bidListModal .bid-btn').first().click();
await page.waitForTimeout(200);
results.bidListModalCardCountAfterRemove = await page.locator('#bidListModal .prop-card').count();
results.bidListChipTextAfterRemove = (await page.locator('#bidListCount').textContent() || '').trim();

await page.click('[data-action="closebidlist"]');
await page.waitForTimeout(150);
results.bidListModalHiddenAfterClose = await page.locator('#bidListModal').isHidden();

// ============================================================
// Each ledger is its own page: own URL, own colour, own header, own set of
// filters. These run last because two of them navigate.
// ============================================================

// Freshness is admin-only now. This account is a normal approved user
// (PROFILE_MODE "default"), so no county group may carry the badge - and
// there ARE county groups on screen, so this isn't passing on an empty page.
results.freshnessBadgesForNormalUser = await page.locator('.freshness-badge').count();
results.countyGroupsPresentForThatCheck = (await page.locator('.county-group').count()) > 0;

// The watchlist rename reaches the chip, not just the modal.
results.watchlistChipLabel = ((await page.locator('#bidListToggle').textContent()) || '').replace(/\s+/g, ' ').trim();

// Walk the three ledgers and record what makes each one a distinct page.
const ledgerPages = {};
for (const key of ['auction', 'laft', 'certificate']) {
  await page.click(`.ledger-tab[data-ledger="${key}"]`);
  await page.waitForTimeout(400);
  ledgerPages[key] = await page.evaluate(() => ({
    hash: location.hash,
    docLedger: document.documentElement.dataset.ledger,
    accent: getComputedStyle(document.documentElement).getPropertyValue('--accent').trim(),
    heading: (document.querySelector('.ledger-head h2') || {}).textContent || '',
    hasHow: !!document.querySelector('.ledger-how'),
    hasFacts: !!document.querySelector('.ledger-facts'),
    titled: document.title,
    typeHidden: !!(document.getElementById('typeDropdown') || {}).hidden,
    lienHidden: !!(document.getElementById('lienDropdown') || {}).hidden,
    assessedHidden: !!(document.getElementById('assessedField') || {}).hidden,
    archiveRowHidden: !!(document.getElementById('archiveToggleRow') || {}).hidden
  }));
  // The DOM property alone isn't proof of anything ON SCREEN - it's exactly
  // what missed the .filters-row[hidden]/author-CSS-specificity bug fixed in
  // the ledger-layout phase (see #junkLandRow's own fix). #archiveToggleRow
  // is a `.tog`, same "own display:flex beats the UA [hidden] rule on a
  // specificity tie" bug class, and had never been checked visually before -
  // read with Playwright's own visibility check, not page.evaluate, so a
  // regression here can't hide behind the property alone again.
  ledgerPages[key].archiveRowVisuallyHidden = await page.locator('#archiveToggleRow').isHidden();
}
results.ledgerHashes = ['auction', 'laft', 'certificate'].map(k => ledgerPages[k].hash);
results.ledgerDocAttr = ['auction', 'laft', 'certificate'].map(k => ledgerPages[k].docLedger);
results.ledgerHeadings = ['auction', 'laft', 'certificate'].map(k => ledgerPages[k].heading);
results.ledgerTitles = ['auction', 'laft', 'certificate'].map(k => ledgerPages[k].titled);
results.everyLedgerHasHowLine = ['auction', 'laft', 'certificate'].every(k => ledgerPages[k].hasHow);
results.everyLedgerHasFactsLine = ['auction', 'laft', 'certificate'].every(k => ledgerPages[k].hasFacts);
// Three different accents, not three copies of one - this is what actually
// makes the pages feel different, so assert they really do differ rather
// than only that the attribute changed.
results.ledgerAccentsAllDifferent =
  new Set(['auction', 'laft', 'certificate'].map(k => ledgerPages[k].accent)).size === 3;
// A certificate is a lien: no property type, no title screening, no assessed
// value. passes() already ignores those filters there, so the controls have
// to go too or they invite setting a filter that does nothing.
results.certHidesTypeLienAssessed = [
  ledgerPages.certificate.typeHidden,
  ledgerPages.certificate.lienHidden,
  ledgerPages.certificate.assessedHidden
];
results.auctionKeepsTypeLienAssessed = [
  ledgerPages.auction.typeHidden,
  ledgerPages.auction.lienHidden,
  ledgerPages.auction.assessedHidden
];
// Archive is auction-only - isPastDue() is false for everything else, so on
// the other two the toggle could only ever produce an empty page.
results.archiveRowHiddenPerLedger = ['auction', 'laft', 'certificate'].map(k => ledgerPages[k].archiveRowHidden);
results.archiveRowVisuallyHiddenPerLedger = ['auction', 'laft', 'certificate'].map(k => ledgerPages[k].archiveRowVisuallyHidden);

// --- the basemap is a map, not a silhouette ---
// fl-counties.svg used to be 67 county paths and nothing else, which is why
// Florida read as a grey smudge on a white page. It now ships the water, the
// three neighbouring states and the orientation labels. All of it is
// same-origin static geometry - if any of these counts go to zero, either
// the basemap was regenerated without them or something is fetching the old
// file.
// Earlier sections leave a county selected, which would reduce the rail to
// one row and prove nothing about ranking. #countyQuick is the Auctions
// page's own quick-select and doesn't touch the Map page's independent
// #mapCountySelect (already back to "ALL" from the earlier Map section's
// #exploreMapReset click) - reset here anyway so the Auctions page itself
// isn't left county-filtered for whatever runs after this section.
await page.selectOption('#countyQuick', 'ALL');
await page.waitForTimeout(300);
// Phase 54: Map is its own top-level page (#pageMap) again - the nav bar is
// still the only entry point into it, and it reaches the exact same
// explore.js view this section exercises.
await page.click('.nav-bottom-item[data-page="map"]');
await page.waitForTimeout(700);
results.basemapLayers = await page.evaluate(() => {
  const svg = document.querySelector('#exploreMapCanvas svg');
  if (!svg) return 'no svg';
  return [
    svg.querySelectorAll('.map-sea').length,
    svg.querySelectorAll('.neighbor-land').length,
    svg.querySelectorAll('.map-context text').length,
    svg.querySelectorAll('path[data-county]').length
  ].join(',');
});
// The projection is pinned to the fit's own 1000x960 basis, so the basemap
// can be reframed without moving a single pin. This is the frame it was
// reframed TO - if it changes again, projectLatLng has to be re-checked.
results.basemapViewBox = await page.getAttribute('#exploreMapCanvas svg', 'viewBox');

// --- the county rail ---
// Bubbles cannot be ranked by eye: an 8-property county and a 12-property
// one are circles of almost the same size. The rail is the ranking, and it
// fills the dead space Florida's nearly-square outline leaves beside a
// wide map.
// Deliberately structural rather than a fixed list of counties: whatever
// filters earlier sections have left set, the rail must hold exactly one row
// per county the map is drawing a bubble for, and the counts must agree with
// the bubbles. Pinning the actual county names here would just re-assert the
// fixture and would break every time an unrelated section changed a filter.
results.railMatchesBubbles = await page.evaluate(() => {
  const rail = [...document.querySelectorAll('#exploreMapRail .rail-row')]
    .map(r => r.querySelector('.rail-name').textContent.trim() + ':' + r.querySelector('.rail-n').textContent.trim())
    .sort();
  const bubbles = [...document.querySelectorAll('#exploreMapCanvas .cluster-bubble')]
    .map(g => g.dataset.county + ':' + g.querySelector('text').textContent.trim())
    .sort();
  return rail.length > 0 && JSON.stringify(rail) === JSON.stringify(bubbles);
});
results.railIsSortedDescending = await page.evaluate(() => {
  const n = [...document.querySelectorAll('#exploreMapRail .rail-n')].map(e => +e.textContent);
  return n.every((v, i) => i === 0 || n[i - 1] >= v);
});
// Zoomed into one county the rail would be a list of that one county, and
// the strip of property cards under the map is already the better list.
await page.click('.cluster-bubble circle');
await page.waitForTimeout(1100);
results.railHiddenWhenZoomed = await page.locator('#exploreMapRail').isHidden();
// Scoped to the explore canvas on purpose (harmless now that #mapHost's
// standalone-page clone of this same basemap is gone with Phase 53, but
// there is no reason for this query to stop being explicit about which
// map it means).
results.contextLabelsHiddenWhenZoomed = await page.evaluate(() => {
  const g = document.querySelector('#exploreMapCanvas .map-context');
  return !!g && getComputedStyle(g).display === 'none';
});
await page.click('#exploreZoomOut');
await page.waitForTimeout(1100);
await page.click('.nav-bottom-item[data-page="list"]');
await page.waitForTimeout(400);

// --- the header is the logo and the title, and nothing else ---
// The eyebrow ("FIELD LEDGER - N COUNTIES TRACKED"), the tagline and the
// "Data updated" line are all out of the masthead. Asserting they are absent
// FROM THE MASTHEAD specifically, not from the page - #generatedAt still
// exists, it moved into Terms & disclaimer.
results.mastheadLeftovers = await page.evaluate(() => {
  const m = document.querySelector('.masthead');
  if (!m) return 'no masthead';
  return ['#eyebrow', '.tagline', '#generatedAt'].filter(sel => m.querySelector(sel)).join(',');
});
// The header is one bar: the sticky .topbar, holding the brand and the
// account badge. The masthead below it is now just the dark ground the tabs
// and chips sit on - if the brand or the badge ever reappears in it, that is
// the old two-tier header creeping back.
results.topbarHasBrandAndAccount = await page.evaluate(() => {
  const t = document.querySelector('.topbar');
  return !!(t && t.querySelector('.brand-name') && t.querySelector('#accountBtn'));
});
results.mastheadHasNoBrandOrAccount = await page.evaluate(() => {
  const m = document.querySelector('.masthead');
  if (!m) return 'no masthead';
  return ['.brand-lockup', '.brand-name', '#accountBtn'].filter(sel => m.querySelector(sel)).join(',');
});
// The sync time is not deleted, just relocated to where provenance is
// discussed - and it still carries the stale warning when the data is behind.
results.generatedLivesInTerms = await page.evaluate(() =>
  !!document.querySelector('#termsModal #generatedAt'));

// --- card status edges replace the per-county freshness badge ---
// Every card carries exactly one status, never two - the precedence in
// cardStatus() (closed > stale > active) has to actually resolve, not stack.
results.cardsWithoutExactlyOneStatus = await page.evaluate(() =>
  [...document.querySelectorAll('.prop-card')].filter(el => {
    const n = ['status-active', 'status-stale', 'status-closed'].filter(c => el.classList.contains(c)).length;
    return n !== 1;
  }).length);
results.cardsOnScreenForThatCheck = (await page.locator('.prop-card').count()) > 0;
// Every fixture row's updated_at is weeks behind its fixed "today", so the
// whole list should read as not-synced-recently. If this ever comes back 0,
// isRowStale() has stopped working rather than the data having improved.
results.staleCardsPresent = (await page.locator('.prop-card.status-stale').count()) > 0;
// And there is a key for the colours where the list starts.
results.legendSwatchCount = await page.locator('.ledger-legend .lgd').count();

// A ledger URL is a real entry point, not just a label the app writes after
// the fact: a cold load on #/certificates must come up on Certificates.
// A real cold load - a fresh page - not a goto on the page above: that page
// is already on index.html, so a hash-only goto is a same-document
// navigation (the Phase 58 note further down explains why that never
// exercises a cold start). It also hung CI on this branch: the page above
// has opened a geocoded row's full page (p5 / p12 carry coordinates since
// Phase 67), whose GIS card attaches two lazy OpenStreetMap iframes and
// detaches them on the next render. On Playwright's headless-shell build
// the second, never-navigated frame never reports "networkidle", so
// Playwright drops the flag on the main frame while the frames exist and,
// with no further request to restart its idle timer, never restores it -
// the next same-document goto with waitUntil: 'networkidle' then waits the
// full 30 s (main never hit this: its fixture has no geocoded row). The
// full Chromium build the sandbox suite runs on does not reproduce it.
const certColdPage = await newPage({ viewport: { width: 390, height: 844 } });
await certColdPage.goto(BASE_URL + '#/certificates', { waitUntil: 'networkidle' });
await certColdPage.waitForTimeout(1200);
results.deepLinkLandsOnCertificates = await certColdPage.locator('.ledger-tab[data-ledger="certificate"]').evaluate(el => el.classList.contains('on'));
results.deepLinkHeading = ((await certColdPage.locator('.ledger-head h2').textContent()) || '').trim();
await certColdPage.close();

// The badge is now gone for EVERYONE, admin included - it was a number
// nobody acted on, repeated once per county down the page. Checking the
// admin view too, because that is the one place it survived last time.
await page.goto(BASE_URL + '?profile=admin' + '#/auctions', { waitUntil: 'networkidle' });
await page.waitForTimeout(1400);
results.freshnessBadgesForAdmin = await page.locator('.freshness-badge').count();

// --- Desktop-width layout check (>=1024px breakpoint) ---
// Everything above ran at the 390x844 mobile viewport, where the three
// ledgers deliberately look identical (a single-column list) - the whole
// point of the CSS in this phase only exists at desktop widths. Rather than
// trust the stylesheet by reading selectors, read the actual computed
// layout the browser produces, the same way the earlier flexbox
// min-size-0 bug was only caught by checking getComputedStyle for real
// instead of assuming the rule fired.
await page.setViewportSize({ width: 1280, height: 900 });
await page.goto(BASE_URL + '#/auctions', { waitUntil: 'networkidle' });
await page.waitForTimeout(600);
if ((await page.locator('#expandAllBtn').textContent()) === 'Expand all') {
  await page.click('#expandAllBtn');
  await page.waitForTimeout(200);
}
results.desktopAuctionListSingleColumn = await page.locator('.prop-list').first().evaluate(el =>
  getComputedStyle(el).gridTemplateColumns.trim().split(' ').length === 1);
await page.locator('.prop-card').first().locator('.detail-btn').first().click();
await page.waitForTimeout(300);
results.desktopAuctionModalDocksRight = await page.locator('#detailModal').evaluate(el =>
  getComputedStyle(el).justifyContent === 'flex-end');

// Close the full-screen modal BEFORE touching the panel below: while open,
// the modal is a fixed-position overlay that sits on top of #detailPanel in
// the stacking order, so its own subtree intercepts every pointer event
// over the panel (Playwright confirmed this concretely - a click on the
// panel's calc-drawer <summary> kept getting swallowed by #detailModalInner
// until the modal was closed first). This is normal overlay behavior, not a
// defect: a real user can't interact with anything the modal is covering
// either, they'd close it first too.
await page.click('#detailModalInner [data-action="closedetail"]');
await page.waitForTimeout(150);

// Phase 20: the SAME viewdetails click above also called selectProperty(p),
// which renders this property's own copy of detailHtml(p) - complete with
// its own #calcNetResult/#calcMaxBidResult pair - into #detailPanel, the
// persistent desktop panel that's visible at this >=1024px width (CSS-hides
// it below that width, but it's still present and populated in the DOM at
// every width - see the mobile-viewport calculator block above, which
// exercises the #detailModalInner copy). This checks the panel surface
// independently of the modal: its own calculator drawer opens, accepts its
// own repair/lien-buffer input, and its own result elements update -
// proving the Phase 20 fix (scoping the input handler's DOM lookup to the
// specific drawer being edited, via drawer.querySelector instead of a bare
// document.getElementById) works for BOTH places detailHtml(p) can be
// rendered at once, not just the modal.
results.detailPanelCalcDrawerPresent = await page.locator('#detailPanel .calc-drawer').count();
await page.click('#detailPanel .calc-drawer summary');
await page.waitForTimeout(150);
results.detailPanelCalcInitialMaxBid = (await page.locator('#detailPanel #calcMaxBidResult').textContent() || '').trim();
results.detailPanelCalcInitialNet = (await page.locator('#detailPanel #calcNetResult').textContent() || '').trim();
await page.fill('#detailPanel .calc-drawer input[data-calc-field="repair"]', '5000');
await page.fill('#detailPanel .calc-drawer input[data-calc-field="muni"]', '1000');
await page.waitForTimeout(150);
results.detailPanelCalcNetAfterInput = (await page.locator('#detailPanel #calcNetResult').textContent() || '').trim();
results.detailPanelCalcMaxBidAfterInput = (await page.locator('#detailPanel #calcMaxBidResult').textContent() || '').trim();

await page.click('.ledger-tab[data-ledger="laft"]');
await page.waitForTimeout(400);
if ((await page.locator('#expandAllBtn').textContent()) === 'Expand all') {
  await page.click('#expandAllBtn');
  await page.waitForTimeout(200);
}
results.desktopLaftListIsMultiColumn = await page.locator('.prop-list').first().evaluate(el =>
  getComputedStyle(el).gridTemplateColumns.trim().split(' ').length > 1);

await page.click('.ledger-tab[data-ledger="certificate"]');
await page.waitForTimeout(400);
if ((await page.locator('#expandAllBtn').textContent()) === 'Expand all') {
  await page.click('#expandAllBtn');
  await page.waitForTimeout(200);
}
results.desktopCertListSingleColumn = await page.locator('.prop-list').first().evaluate(el =>
  getComputedStyle(el).gridTemplateColumns.trim().split(' ').length === 1);
results.desktopCertCardIsRow = await page.locator('.cert-card').first().evaluate(el =>
  getComputedStyle(el).display === 'flex');

// ============================================================
// Phase 34: state-aware external links. fallbackZillowUrl()/
// fallbackStreetviewUrl() (app.js) used to hardcode "County, FL" for every
// property's search-link fallback regardless of its actual state - wrong
// for Texas. Fixture row "ptx1" (state: "TX", no url_zillow/url_streetview,
// no lat/long) forces both fallback builders to run for a real TX row, so
// this actually exercises the fix rather than just re-asserting the FL
// fixture (which would pass either way). Navigates to tx.html - a separate
// static entry point, not a route change - reusing the same mocked stub.
// ============================================================
const TX_BASE_URL = BASE_URL.replace(/index\.html$/, 'tx.html');
await page.goto(TX_BASE_URL + '#/auctions', { waitUntil: 'networkidle' });
await page.waitForTimeout(500);
// Auction cards are grouped by county+date inside collapsed <details>
// (state.expandedCounties starts empty, same as the FL phases above) -
// ptx1's card exists in the DOM but isn't click-visible until its group is
// expanded.
if ((await page.locator('#expandAllBtn').textContent()) === 'Expand all') {
  await page.click('#expandAllBtn');
  await page.waitForTimeout(200);
}
const txCard = page.locator('.prop-card[data-pid="ptx1"]');
results.txCardStreetviewHref = await txCard.locator('.prop-links a', { hasText: 'Google Maps search' }).getAttribute('href');
results.txCardZillowHref = await txCard.locator('.prop-links a', { hasText: 'Zillow' }).getAttribute('href');
// ptx1 has neither url_streetview nor url_zillow (both null in the
// fixture), so both are fallback/"estimated" links - the detail modal's
// link labels should say so, and its harvester_source ("tx_lgbs") should
// surface as the provenance line's data-source text.
await txCard.locator('.detail-btn').click();
await page.waitForTimeout(300);
results.txDetailLinksText = (await page.locator('#detailModalInner .detail-links').textContent()) || '';
results.txDetailProvenanceText = ((await page.locator('#detailModalInner .detail-provenance').textContent()) || '').trim();
// Launch-readiness honesty pass: the Texas page must not carry Florida fee or
// statute copy, or the Florida-only filter-match / quiet-title toggles.
{
  const txHtml = await page.content();
  results.txNoFloridaStatuteCopy = !/197\.502|197\.542|doc stamps|documentary stamps/i.test(await page.locator('footer, #termsModal').allTextContents().then(t => t.join(' ')));
  results.txNoFilterMatchToggle = (await page.locator('#topOnly').count()) === 0 && (await page.locator('#qtToggle').count()) === 0;
  results.txNoFilterMatchBanner = !/toppick-banner/.test(txHtml);
}

// Phase 36: fees(p) (app.js) used to apply Florida's statutory fee formula
// (doc stamps, recording fee, homestead surcharge under FS 197.502(6)(c))
// to every property regardless of state, including Texas rows - producing
// Florida-law dollar figures on Texas properties. Reusing the same open
// ptx1 detail modal above (bid: 5000, a published bid, so the old code
// would have shown a "Fees" stat and a calculator drawer here) to confirm
// both are now correctly absent for a non-FL row, and that the assessed-
// value stat is labeled through assessedSourceLabel() (Phase 14A) rather
// than the hardcoded FL label a second, unguarded call site used to push.
const txStatLabels = (await page.locator('#detailModalInner .detail-stat-label').allTextContents())
  .map(s => s.replace(/\s+/g, ' ').trim());
results.txDetailHasFeesStat = txStatLabels.some(l => l.startsWith('Fees'));
results.txDetailHasCalcDrawer = await page.locator('#detailModalInner .calc-drawer').count();
results.txDetailAssessedLabel = txStatLabels.find(l => l.includes('Assessed') || l.includes('CAD') || l.includes('Adjudged')) || '';

// ============================================================
// Phase 72: the auction link says what it is (url_auction_kind, read from
// the row - migration 013), and Texas rows only link where a verified URL
// exists. ptx1 is an LGBS auction row: no URL, "Auction link not published",
// no anchor, and the gap named in the summary's Missing list. ptx2 is a
// RealAuction row: the county's sale-date listing, labelled as such, with
// the exact host + MM/DD/YYYY AuctionDate the harvester fetched, and never
// worded as a property page. ptx5 has no URL (host not on the verified
// roster): no link. ptx4's sale date has passed: no current link. ptx3/ptx6
// are LGBS struck-off / future-sale rows: resale wording, no link.
// ============================================================
const txAuctionLinkOf = async scope => ({
  text: ((await scope.locator('.cta-btn, .auction-link-none, .detail-cta').first().textContent()) || '').replace(/\s+/g, ' ').trim(),
  kind: await scope.locator('[data-auction-link]').first().getAttribute('data-auction-link'),
  anchors: await scope.locator('a.cta-btn, a.detail-cta').count()
});
// Labels that carry a fixture-relative sale date are checked as their own
// RegExp-matched string; the kind/anchor pair stays an exact object.
const splitLinkText = key => { results[key + 'Text'] = results[key].text; results[key] = { kind: results[key].kind, anchors: results[key].anchors }; };
// The ptx1 modal is still open from the checks above.
results.txLgbsDetailLink = await txAuctionLinkOf(page.locator('#detailModalInner'));
results.txLgbsDetailGapsNameTheLink = ((await page.locator('#detailModalInner .opp-gaps').textContent()) || '').includes('Auction link not published');
// The full page's "When" cell carries the vendor's raw status verbatim.
results.txLgbsDetailWhen = ((await page.locator('#detailModalInner .opp-cell').nth(2).locator('.opp-val').textContent()) || '').replace(/\s+/g, ' ').trim();
await page.keyboard.press('Escape');
await page.waitForTimeout(300);
results.txLgbsCardLink = await txAuctionLinkOf(txCard);
results.txLgbsCardKicker = ((await txCard.locator('.kicker-phase').textContent()) || '').trim();
const txRaCard = page.locator('.prop-card[data-pid="ptx2"]');
results.txRaCardLink = await txAuctionLinkOf(txRaCard);
results.txRaCardHref = await txRaCard.locator('a.cta-btn').getAttribute('href');
results.txRaCardScopeNote = ((await txRaCard.locator('a.cta-btn').getAttribute('title')) || '').includes('not a page for this property alone');
results.txRaCardLabelNotPropertySpecific = !/property|bid on/i.test(results.txRaCardLink.text);
splitLinkText('txRaCardLink');
await txRaCard.locator('.detail-btn').click();
await page.waitForTimeout(300);
results.txRaDetailLink = await txAuctionLinkOf(page.locator('#detailModalInner'));
splitLinkText('txRaDetailLink');
results.txRaDetailHref = await page.locator('#detailModalInner a.detail-cta').getAttribute('href');
results.txRaDetailHrefMatchesCard = results.txRaDetailHref === results.txRaCardHref;
results.txRaDetailProvenanceText = ((await page.locator('#detailModalInner .detail-provenance, #detailModalInner .provenance-card').first().textContent()) || '').replace(/\s+/g, ' ').trim();
await page.keyboard.press('Escape');
await page.waitForTimeout(300);
results.txRaNoHostCardLink = await txAuctionLinkOf(page.locator('.prop-card[data-pid="ptx5"]'));
// The RPC row itself carries the kind and the raw status - the UI reads
// them, it does not derive them.
results.txRpcRowsExposeKindAndStatus = await page.evaluate(() => {
  const rows = (window.__tdwLastRender && window.__tdwLastRender.rows) || [];
  const ra = rows.find(r => r.id === 'ptx2'), lg = rows.find(r => r.id === 'ptx1');
  return !!ra && ra.url_auction_kind === 'sale' && !!lg && lg.tx_sale_status === 'Scheduled for Online Auction' && lg.url_auction == null;
});
// CSV on the Texas auctions ledger: the URL column says what it holds, the
// kind travels beside it, and LGBS rows export an empty URL, not a guess.
{
  const txDownloadPromise = page.waitForEvent('download');
  await page.click('#exportCsvBtn');
  const txDownload = await txDownloadPromise;
  const csvText = fs.readFileSync(await txDownload.path(), 'utf8');
  const parseCsvLine = line => {
    const out = []; let cur = '', q = false;
    for (let i = 0; i < line.length; i++) {
      const c = line[i];
      if (q) { if (c === '"') { if (line[i + 1] === '"') { cur += '"'; i++; } else q = false; } else cur += c; }
      else if (c === '"') q = true;
      else if (c === ',') { out.push(cur); cur = ''; }
      else cur += c;
    }
    out.push(cur); return out;
  };
  const lines = csvText.split('\r\n').filter(Boolean);
  const hdr = parseCsvLine(lines[0]);
  const iCase = hdr.indexOf('Case/Account #'), iUrl = hdr.indexOf('Auction Listing URL'), iKind = hdr.indexOf('Auction URL Type'), iStatus = hdr.indexOf('TX Sale Status');
  const rowsByCase = Object.fromEntries(lines.slice(1).map(parseCsvLine).map(c => [c[iCase], c]));
  results.txCsvHeadersPresent = iUrl > 0 && iKind === iUrl + 1 && iStatus > 0 && !hdr.includes('Auction/LAFT Listing');
  results.txCsvRealauctionRow = rowsByCase['9377-0051-0100'] ? [rowsByCase['9377-0051-0100'][iUrl] === results.txRaCardHref, rowsByCase['9377-0051-0100'][iKind]] : null;
  results.txCsvLgbsRow = rowsByCase['TX-1'] ? [rowsByCase['TX-1'][iUrl], rowsByCase['TX-1'][iKind], rowsByCase['TX-1'][iStatus]] : null;
}
// Struck-off / future-sale LGBS rows live on the laft ledger.
await page.click('.ledger-tab[data-ledger="laft"]');
await page.waitForTimeout(200);
if ((await page.locator('#expandAllBtn').count()) && (await page.locator('#expandAllBtn').textContent()) === 'Expand all') {
  await page.click('#expandAllBtn');
  await page.waitForTimeout(200);
}
results.txStruckOffKicker = ((await page.locator('.prop-card[data-pid="ptx3"] .kicker-phase').textContent()) || '').trim();
results.txStruckOffLink = await txAuctionLinkOf(page.locator('.prop-card[data-pid="ptx3"]'));
results.txFutureSaleKicker = ((await page.locator('.prop-card[data-pid="ptx6"] .kicker-phase').textContent()) || '').trim();
results.txFutureSaleLink = await txAuctionLinkOf(page.locator('.prop-card[data-pid="ptx6"]'));
await page.click('.ledger-tab[data-ledger="auction"]');
await page.waitForTimeout(200);
// A RealAuction row whose sale date has passed is excluded from the live
// list (isPastDue), so it is reached the way a saved link would reach it: a
// cold load of its own property page.
{
  const pastPage = await newPage({ viewport: { width: 390, height: 844 } });
  await pastPage.goto(TX_BASE_URL + '#/auctions/ptx4', { waitUntil: 'networkidle' });
  await pastPage.waitForTimeout(800);
  results.txRaPastDetailVisible = await pastPage.locator('#detailModal').isVisible();
  results.txRaPastDetailLink = await txAuctionLinkOf(pastPage.locator('#detailModalInner'));
  splitLinkText('txRaPastDetailLink');
  await pastPage.close();
}

// Phase 67: the same state cue on the Texas page, reached the way a user
// would - a cold load of tx.html#map (a fresh page, not a same-document
// hash change, per the Phase 58 note below) - so the Map page itself, its
// "Map · Texas" title and the 254-county Texas outline are all asserted on
// the deployed-shape entry point, not inferred from the Florida page.
const txMapPage = await newPage({ viewport: { width: 1280, height: 900 } });
await txMapPage.goto(TX_BASE_URL + '#map', { waitUntil: 'networkidle' });
await txMapPage.waitForTimeout(600);
results.txMapPageVisibleOnColdLoad = await txMapPage.locator('#pageMap').isVisible();
results.txMapContextTexas = ((await txMapPage.locator('#mapContext').textContent()) || '').replace(/\s+/g, ' ').trim();
results.txMapStateValue = await txMapPage.locator('#stateSelect').inputValue();
results.txMapPathCount = await txMapPage.locator('#exploreMapCanvas path[data-county]').count();
await txMapPage.close();

// ============================================================
// Phase 58: property deep-linking. openDetail() (app.js) writes
// "#/<ledger-slug>/<id>" via history.replaceState onto the SAME history
// entry pushBackLayer() already creates (never a second entry, so Android
// back-button behavior is untouched), so that coming back to the app -
// even after a full cold reload, e.g. a mobile OS evicting the
// backgrounded PWA tab after the user tapped an outbound target="_blank"
// link - reopens the exact same property card. Simulated with a brand-new
// page/context navigated straight at the captured URL: a page.goto() that
// only changes the current document's fragment is a same-document
// navigation in real browsers (same as clicking an in-page anchor) and
// would NOT exercise the cold-start reopen path at all, so this uses two
// separate browser.newPage() contexts (each gets its own isolated storage)
// rather than reusing the page above.
// ============================================================
const dlPage1 = await newPage({ viewport: { width: 390, height: 844 } });
dlPage1.on('dialog', d => d.accept());
await dlPage1.goto(BASE_URL + '#/auctions', { waitUntil: 'networkidle' });
await dlPage1.waitForTimeout(500);
await dlPage1.click('#expandAllBtn');
await dlPage1.waitForTimeout(150);
if ((await dlPage1.locator('#expandAllBtn').textContent()) === 'Expand all') {
  await dlPage1.click('#expandAllBtn');
  await dlPage1.waitForTimeout(150);
}
const dlPid = await dlPage1.locator('.prop-card[data-pid]').first().getAttribute('data-pid');
await dlPage1.locator('.detail-btn[data-action="viewdetails"]').first().click();
await dlPage1.waitForTimeout(300);
const dlHash = await dlPage1.evaluate(() => location.hash);
results.deepLinkHashHasPid = dlHash.includes('/' + dlPid);
const dlAddress1 = ((await dlPage1.locator('#detailModalInner .detail-address').textContent()) || '').trim();
await dlPage1.close();

const dlPage2 = await newPage({ viewport: { width: 390, height: 844 } });
dlPage2.on('dialog', d => d.accept());
await dlPage2.goto(BASE_URL + dlHash, { waitUntil: 'networkidle' });
await dlPage2.waitForTimeout(1000);
results.deepLinkModalVisibleOnColdStart = await dlPage2.locator('#detailModal').isVisible();
const dlAddress2 = ((await dlPage2.locator('#detailModalInner .detail-address').textContent()) || '').trim();
// Real content-equality check (not just "a modal appeared") - the cold
// start has to reopen the SAME property, not just any property.
results.deepLinkAddressMatchesAcrossColdStart = dlAddress1.length > 0 && dlAddress1 === dlAddress2;

// Back from a cold-started deep link should close the modal and land on
// the bare ledger hash - not leave the app, and not leave the pid behind.
await dlPage2.goBack();
await dlPage2.waitForTimeout(400);
results.deepLinkModalHiddenAfterBack = await dlPage2.locator('#detailModal').isVisible();
results.deepLinkHashClearedAfterBack = !(await dlPage2.evaluate(() => location.hash)).includes('/' + dlPid);
await dlPage2.close();

// --- Phase 66: photo states, card disclosure, and "Show on the Map page" ---
// A fresh page so this block owns its own state: nothing hidden, nothing
// filtered, no modal open. p6 (77 Pine Ct) is the fixture's one row WITH a
// photo (a labelled placard, not a real Street View still); p3 (3 Oak Ave,
// Lands Available) carries photo_url '' = checked, no coverage; p1 (1 Main
// St) has no photo_url at all = not checked yet.
const p66 = await newPage({ viewport: { width: 390, height: 844 } });
p66.on('pageerror', e => errors.push('pageerror: ' + e.message));
p66.on('console', msg => { if (msg.type() === 'error') errors.push('console.error: ' + msg.text()); });
await p66.goto(BASE_URL + '#/auctions', { waitUntil: 'networkidle' });
await p66.waitForTimeout(500);
if ((await p66.locator('#expandAllBtn').textContent()) === 'Expand all') { await p66.click('#expandAllBtn'); await p66.waitForTimeout(200); }
const p6Card = p66.locator('.prop-card:has-text("77 Pine Ct")').first();
results.photoCardHasPhoto = await p6Card.locator('.prop-card-photo.has-photo img').count();
results.photoCardCaption = ((await p6Card.locator('.photo-caption').textContent()) || '').trim();
// The banner is capped so the address and both headline figures still sit
// on the first phone screen under it.
results.photoCardBannerHeightCapped = await p6Card.locator('.prop-card-photo.has-photo').evaluate(el => el.getBoundingClientRect().height <= 170);
// Phase 67: the placeholder names both absences (photo state, then the
// location state) in two spans - read the photo one here.
results.photoNotCheckedText = ((await p66.locator('.prop-card:has-text("1 Main St") .prop-card-photo.no-photo .vis-main').first().textContent()) || '').trim();
results.placeholderLocationText = ((await p66.locator('.prop-card:has-text("1 Main St") .prop-card-photo.no-photo .vis-sub').first().textContent()) || '').trim();
results.cardMoreClosedByDefault = await p66.locator('.prop-card:has-text("1 Main St") details.card-more').first().evaluate(el => !el.open);
results.cardMoreSummaryText = ((await p66.locator('.prop-card:has-text("1 Main St") details.card-more summary').first().textContent()) || '').trim();
// No horizontal overflow at phone width, and the icon buttons have a real hit area.
results.noHorizontalOverflowMobile = await p66.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1);
results.iconBtnHitAreaMobile = await p66.locator('.prop-card .icon-btn').first().evaluate(el => { const r = el.getBoundingClientRect(); return r.width >= 32 && r.height >= 32; });
await p66.click('.ledger-tab[data-ledger="laft"]');
await p66.waitForTimeout(200);
if ((await p66.locator('#expandAllBtn').textContent()) === 'Expand all') { await p66.click('#expandAllBtn'); await p66.waitForTimeout(200); }
results.photoNoCoverageText = ((await p66.locator('.prop-card:has-text("3 Oak Ave") .prop-card-photo.no-photo .vis-main').first().textContent()) || '').trim();
await p66.click('.ledger-tab[data-ledger="auction"]');
await p66.waitForTimeout(200);
if ((await p66.locator('#expandAllBtn').textContent()) === 'Expand all') { await p66.click('#expandAllBtn'); await p66.waitForTimeout(200); }
// Full page -> "Show county on the Map page": modal closes, Map page opens
// filtered to Alachua, and p1 is the selected property there (strip card
// .sel + preview open on it). p1 has no coordinates, so no pin is expected.
await p66.locator('.prop-card:has-text("1 Main St") .detail-btn[data-action="viewdetails"]').first().click();
await p66.waitForTimeout(200);
await p66.click('#detailModalInner .show-on-map-btn');
await p66.waitForTimeout(900); // county zoom tween + redraw
results.showOnMapClosesModal = await p66.locator('#detailModal').isHidden();
results.showOnMapOpensMapPage = await p66.locator('#pageMap').isVisible();
results.showOnMapCountySelect = await p66.locator('#mapCountySelect').inputValue();
results.showOnMapCanvasZoomed = await p66.locator('#exploreMapCanvas').evaluate(el => el.classList.contains('zoomed'));
results.showOnMapPreviewVisible = await p66.locator('#explorePreview').isVisible();
results.showOnMapPreviewTitle = ((await p66.locator('#explorePreview .preview-title').textContent()) || '').trim();
results.showOnMapStripSelCount = await p66.locator('#exploreStrip .strip-card.sel').count();
await p66.close();

// --- Phase 67: the map workspace, pin selection, imagery hierarchy ---
// Desktop first: the Map page is [toolbar] over [stage | side panel]; the
// stage has real height and the outline map fills it; the strip is a
// vertical list in the panel; a geocoded row (p5, Charlotte) gets a real
// pin whose click selects it everywhere (pin .sel + halo, strip .sel, the
// preview with its coordinates) and tells the other basemaps
// (tdw:mapselection). Closing clears every one of those.
const p67d = await newPage({ viewport: { width: 1400, height: 900 } });
p67d.on('pageerror', e => errors.push('pageerror: ' + e.message));
p67d.on('console', msg => { if (msg.type() === 'error') errors.push('console.error: ' + msg.text()); });
await p67d.goto(BASE_URL + '#/auctions', { waitUntil: 'networkidle' });
await p67d.waitForTimeout(500);
await p67d.evaluate(() => { window.__selEvents = []; window.addEventListener('tdw:mapselection', e => window.__selEvents.push(e.detail)); });
await p67d.click('.nav-item[data-page="map"]');
await p67d.waitForTimeout(600);
results.mapToolbarHoldsBasemapToggle = await p67d.locator('#mapToolbar #mapStyleToggle').count();
results.mapWorkspaceTwoColumns = await p67d.locator('#mapWorkspace').evaluate(el => getComputedStyle(el).gridTemplateColumns.split(' ').length === 2);
results.mapStageTallDesktop = await p67d.locator('#mapStage .explore-map-stage').evaluate(el => el.getBoundingClientRect().height >= 500);
results.mapSvgFillsStageHeight = await p67d.locator('#exploreMapCanvas svg').evaluate(el => { const s = el.getBoundingClientRect().height, st = el.closest('.explore-map-stage').getBoundingClientRect().height; return s >= st * 0.95; });
results.mapSidePanelVisible = await p67d.locator('#mapSidePanel').isVisible();
results.mapImageryToggleHiddenOnOutline = await p67d.locator('#mapImageryToggle').isHidden();
results.mapOldCardHeadGone = await p67d.locator('#pageMap .explore-map-head').count();
await p67d.selectOption('#mapCountySelect', 'Charlotte');
await p67d.waitForTimeout(700);
results.charlottePinCount = await p67d.locator('#exploreMapCanvas .map-pin').count();
results.stripVerticalOnDesktop = await p67d.locator('#exploreStrip .strip-rail').evaluate(el => getComputedStyle(el).flexDirection === 'column');
results.stripInSidePanel = await p67d.locator('#mapSidePanel #exploreStrip').count();
await p67d.locator('#exploreMapCanvas .map-pin[data-pid="p5"]').click({ force: true });
await p67d.waitForTimeout(300);
results.pinClickPreviewTitle = ((await p67d.locator('#explorePreview .preview-title').textContent()) || '').trim();
results.pinClickPreviewInSidePanel = await p67d.locator('#mapSidePanel #explorePreview').count();
results.pinClickPinSel = await p67d.locator('#exploreMapCanvas .map-pin.sel').count();
results.pinClickHalo = await p67d.locator('#exploreMapCanvas .map-pin.sel .pin-halo').count();
results.pinClickStripSel = await p67d.locator('#exploreStrip .strip-card.sel[data-pid="p5"]').count();
results.previewKicker = ((await p67d.locator('#explorePreview .pv-kicker').textContent()) || '').trim();
results.previewCoords = ((await p67d.locator('#explorePreview .pv-coords').textContent()) || '').trim();
results.previewBid = ((await p67d.locator('#explorePreview .pv-val.bid').textContent()) || '').trim();
results.previewValueLabel = ((await p67d.locator('#explorePreview .pv-stat small').textContent()) || '').trim();
results.previewIds = await p67d.locator('#explorePreview .pv-ids dd').allTextContents();
results.previewFlood = ((await p67d.locator('#explorePreview .pv-risk span:nth-child(2)').textContent()) || '').trim();
results.previewMoreClosed = await p67d.locator('#explorePreview details.pv-more').evaluate(el => !el.open);
// Phase 72: the preview carries the same kind-driven auction link as the
// card and the full page (p5: a sale-date page, kind 'sale').
results.previewAuctionLinkText = ((await p67d.locator('#explorePreview .pv-auction a').textContent()) || '').trim();
results.previewAuctionLinkKind = await p67d.locator('#explorePreview .pv-auction a').getAttribute('data-auction-link');
results.previewAuctionLinkHref = await p67d.locator('#explorePreview .pv-auction a').getAttribute('href');
results.selectionEventPid = await p67d.evaluate(() => { const e = window.__selEvents; return e.length ? e[e.length - 1].pid : null; });
results.selectionEventHasCoords = await p67d.evaluate(() => { const e = window.__selEvents; const d = e[e.length - 1]; return !!d && typeof d.lat === 'number' && typeof d.lng === 'number'; });
// Close via the preview's own close button: pin highlight, strip highlight
// and the cross-basemap selection all clear together; the map stays zoomed.
await p67d.click('#explorePreview .preview-close');
await p67d.waitForTimeout(250);
results.previewHiddenAfterClose = await p67d.locator('#explorePreview').isHidden();
results.pinSelClearedAfterClose = await p67d.locator('#exploreMapCanvas .map-pin.sel').count();
results.stripSelClearedAfterClose = await p67d.locator('#exploreStrip .strip-card.sel').count();
results.selectionEventClearedPid = await p67d.evaluate(() => { const e = window.__selEvents; return e.length ? e[e.length - 1].pid : 'none'; });
results.stillZoomedAfterClose = await p67d.locator('#exploreMapCanvas').evaluate(el => el.classList.contains('zoomed'));
// Switching properties: Brevard's p12 is the other geocoded row.
await p67d.selectOption('#mapCountySelect', 'Brevard');
await p67d.waitForTimeout(700);
await p67d.locator('#exploreMapCanvas .map-pin[data-pid="p12"]').click({ force: true });
await p67d.waitForTimeout(300);
results.switchPreviewTitle = ((await p67d.locator('#explorePreview .preview-title').textContent()) || '').trim();
results.switchPinSelPid = await p67d.locator('#exploreMapCanvas .map-pin.sel').getAttribute('data-pid');
// Imagery ladder, no key configured: a geocoded card gets the county
// context mini-map (rung 3), built from the app's own basemap once it
// scrolls into view; an un-geocoded card gets the two-part placeholder.
await p67d.click('.nav-item[data-page="list"]');
await p67d.waitForTimeout(400);
if ((await p67d.locator('#expandAllBtn').textContent()) === 'Expand all') { await p67d.click('#expandAllBtn'); await p67d.waitForTimeout(200); }
const p5Vis = p67d.locator('.prop-card:has-text("500 Elm Way") .prop-card-photo');
results.geocodedCardVisualClass = await p5Vis.evaluate(el => el.classList.contains('minimap'));
await p5Vis.scrollIntoViewIfNeeded();
await p67d.waitForTimeout(600);
results.minimapHydrated = await p5Vis.locator('svg .mm-county').count();
results.minimapHasDot = await p5Vis.locator('svg .mm-dot').count();
results.minimapCaption = ((await p5Vis.locator('.photo-caption').textContent()) || '').trim();
results.minimapNeighborsDrawn = (await p5Vis.locator('svg .mm-neighbor').count()) > 0;
// The static-image URL builders (rung 2), checked without a key in the
// fixture: MapTiler is preferred, Google second, neither without coords.
// Coordinates are fixed to six decimals in the URL (26.934200), so the
// same row always yields the same URL - cacheable by the browser.
results.staticUrlMaptiler = await p67d.evaluate(() => { const r = window.__tdwImagery.staticImageUrl({ latitude: 26.9342, longitude: -82.0454 }, { maptilerKey: 'TESTKEY' }); return r && r.provider + '|' + /^https:\/\/api\.maptiler\.com\/maps\/hybrid\/static\/-82\.045400,26\.934200,17\/640x320\.png\?markers=-82\.045400,26\.934200,red&key=TESTKEY$/.test(r.url); });
results.staticUrlGoogle = await p67d.evaluate(() => { const r = window.__tdwImagery.staticImageUrl({ latitude: 26.9342, longitude: -82.0454 }, { googleMapsApiKey: 'GKEY' }); return r && r.provider + '|' + /^https:\/\/maps\.googleapis\.com\/maps\/api\/staticmap\?center=26\.934200,-82\.045400&zoom=17&size=640x320&scale=2&maptype=hybrid&markers=color:red%7C26\.934200,-82\.045400&key=GKEY$/.test(r.url); });
results.staticUrlPrefersMaptiler = await p67d.evaluate(() => window.__tdwImagery.staticImageUrl({ latitude: 1, longitude: 2 }, { googleMapsApiKey: 'G', maptilerKey: 'M' }).provider);
results.staticUrlNoCoords = await p67d.evaluate(() => window.__tdwImagery.staticImageUrl({ latitude: null, longitude: -82 }, { maptilerKey: 'M' }));
results.staticUrlNoKey = await p67d.evaluate(() => window.__tdwImagery.staticImageUrl({ latitude: 1, longitude: 2 }, {}));
await p67d.close();

// Phone: the stage is still large, the preview is a sheet over the stage's
// lower edge (not over the list under the map), collapsed by default with
// a Details button that expands it, and nothing overflows sideways.
const p67m = await newPage({ viewport: { width: 360, height: 780 } });
p67m.on('pageerror', e => errors.push('pageerror: ' + e.message));
p67m.on('console', msg => { if (msg.type() === 'error') errors.push('console.error: ' + msg.text()); });
await p67m.goto(BASE_URL + '#/auctions', { waitUntil: 'networkidle' });
await p67m.waitForTimeout(500);
await p67m.click('.nav-bottom-item[data-page="map"]');
await p67m.waitForTimeout(600);
results.mapStageTallMobile = await p67m.locator('#mapStage .explore-map-stage').evaluate(el => el.getBoundingClientRect().height >= 320);
results.mapNoOverflowMobile = await p67m.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1);
await p67m.selectOption('#mapCountySelect', 'Charlotte');
await p67m.waitForTimeout(700);
await p67m.locator('#exploreMapCanvas .map-pin[data-pid="p5"]').click({ force: true });
await p67m.waitForTimeout(300);
results.mobilePreviewInStage = await p67m.locator('#mapStage .explore-map-stage > #explorePreview').count();
results.mobilePreviewCollapsed = await p67m.locator('#explorePreview').evaluate(el => !el.classList.contains('expanded'));
results.mobilePreviewBodyHiddenCollapsed = await p67m.locator('#explorePreview .pv-body').isHidden();
results.mobilePreviewCoversLessThanHalfStage = await p67m.locator('#explorePreview').evaluate(el => el.getBoundingClientRect().height < el.closest('.explore-map-stage').getBoundingClientRect().height * 0.5);
await p67m.click('#explorePreview .pv-expand');
await p67m.waitForTimeout(200);
results.mobilePreviewExpanded = await p67m.locator('#explorePreview').evaluate(el => el.classList.contains('expanded'));
results.mobilePreviewBodyVisibleExpanded = await p67m.locator('#explorePreview .pv-body').isVisible();
results.mobileStripStillReachable = await p67m.locator('#exploreStrip .strip-card').first().isVisible();
results.mapNoOverflowMobileSelected = await p67m.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1);
await p67m.close();

// ==================== SaaS hardening (2026-09-29) ====================
// Account lifecycle, support/help, sale-event history, dataset health,
// watchlist change signals, and the customer-facing claim fixes. Each block
// uses its own page so the main page's state above is untouched.

// --- Sale event history on the full property page (Phase B tables via the
// stub): p1 has one scheduled event whose opening bid changed between two
// observations; p13 (past-due, reachable only by deep link) has a
// completed event and an older superseded one. Outcome is always "Not
// tracked" - the section must never say sold/redeemed/winner. ---
const evPage = await newPage({ viewport: { width: 1200, height: 900 } });
await evPage.goto(BASE_URL + '#/auctions/p1', { waitUntil: 'networkidle' });
await evPage.waitForTimeout(600);
results.eventSectionPresent = await evPage.locator('#detailModalInner [data-section="events"]').count();
results.eventItemsP1 = await evPage.locator('#detailModalInner .event-item').count();
results.eventLifecycleP1 = ((await evPage.locator('#detailModalInner .event-item .ev-life').first().textContent()) || '').trim();
results.eventOutcomeP1 = ((await evPage.locator('#detailModalInner .event-item .ev-outcome').first().textContent()) || '').replace(/\s+/g, ' ').trim();
results.eventBidChangeP1 = ((await evPage.locator('#detailModalInner .event-item .ev-meta').nth(1).textContent()) || '').trim();
results.eventNavPill = await evPage.locator('#detailModalInner .detail-nav button[data-target="events"]').count();
await evPage.close();
const evPage2 = await newPage({ viewport: { width: 1200, height: 900 } });
await evPage2.goto(BASE_URL + '#/auctions/p13', { waitUntil: 'networkidle' });
await evPage2.waitForTimeout(600);
results.eventItemsP13 = await evPage2.locator('#detailModalInner .event-item').evaluateAll(els => els.map(e => e.dataset.lifecycle));
results.eventLifecycleP13First = ((await evPage2.locator('#detailModalInner .event-item .ev-life').first().textContent()) || '').trim();
// The event entries themselves (not the explanatory note, which names the
// words it forbids) must never contain an outcome claim.
const evItemsText = (await evPage2.locator('#detailModalInner [data-section="events"] .event-item').allTextContents()).join(' ').toLowerCase();
// ("Purchaser identity and bidder count are not recorded" is the
// disclaimer every provenance line carries - it states the opposite.)
results.eventSectionNeverClaimsOutcome = !/\bsold\b|redeemed|winning bid|purchaser|struck off/.test(evItemsText.replace(/purchaser identity and bidder count are not recorded/g, ''));
results.eventSectionSaysNotPublished = (evItemsText.match(/outcome not published|outcome not yet verified/g) || []).length;
await evPage2.close();
// --- Production-readiness: an event whose result the SOURCE published
// (ev4 on p10: outcome struck_off with the vendor's own wording) is shown
// with that wording and the observation date - never for an event whose
// outcome is 'unknown' (p1 / p13 above stay "Not published by the source").
const evPage3 = await newPage({ viewport: { width: 1200, height: 900 } });
await evPage3.goto(BASE_URL + '#/auctions/p10', { waitUntil: 'networkidle' });
await evPage3.waitForTimeout(600);
results.eventOutcomeSourcePublished = ((await evPage3.locator('#detailModalInner .event-item .ev-outcome').first().textContent()) || '').replace(/\s+/g, ' ').trim();
results.eventNoteSaysSourceOnly = ((await evPage3.locator('#detailModalInner [data-section="events"] .event-note').textContent()) || '').includes('only when the source itself published one');
await evPage3.close();

// --- Dashboard: dataset health (five stub rows, one per derived state)
// and the watchlist change signals (first visit in a fresh browser). ---
const dashPage = await newPage({ viewport: { width: 1200, height: 900 } });
await dashPage.goto(BASE_URL + '#/auctions', { waitUntil: 'networkidle' });
await dashPage.waitForTimeout(500);
await dashPage.click('.nav-item[data-page="dashboard"]');
await dashPage.waitForTimeout(200);
results.dashHealthRows = await dashPage.locator('#dashSourceRows .health-row').evaluateAll(els => els.map(e => e.dataset.source + ':' + e.dataset.health));
results.dashHealthBadgeTexas = ((await dashPage.locator('#dashSourceRows .health-row[data-source="tx_sales"] .health-sub').textContent()) || '').includes('manual runs, no schedule');
results.dashHealthIncompleteNames = ((await dashPage.locator('#dashSourceRows .health-row[data-source="fl_certificates"] .health-sub').textContent()) || '').includes('incomplete: Baker, Gulf');
// Per-county freshness (county_source_registry + migration 021): FL rows
// with a recorded read only (Bradford, never attempted, is omitted; the
// Texas row belongs to tx.html), Current vs Stale by the last attempt.
results.dashUnitRows = await dashPage.locator('#dashUnitRows .unit-row').evaluateAll(els => els.map(e => e.dataset.county + ':' + e.dataset.fresh));
results.dashUnitStaleText = ((await dashPage.locator('#dashUnitRows .unit-row[data-county="Bay"] .health-sub').textContent()) || '').replace(/\s+/g, ' ').trim();
results.dashUnitCurrentText = ((await dashPage.locator('#dashUnitRows .unit-row[data-county="Alachua"] .health-sub').textContent()) || '').replace(/\s+/g, ' ').trim();
results.dashWatchFirstVisit = ((await dashPage.locator('#dashWatchChanges').textContent()) || '').includes('No earlier visit recorded in this browser yet');
results.dashWatchNoNotificationsClaim = ((await dashPage.locator('#dashWatchChanges').textContent()) || '').includes('No e-mail or push notifications exist yet');
// Three ledgers (2026-09-30): per-county freshness is grouped under one
// heading per ledger; the fixture's registry rows feed Available only, so
// the Auctions and Liens & Certificates groups say so rather than borrowing
// Available's rows - a failed read in one ledger never reads as another's.
results.dashUnitLedgerHeads = await dashPage.locator('#dashUnitRows .unit-head').evaluateAll(els => els.map(e => e.dataset.ledgerHead));
results.dashUnitRowsUnderAvailable = await dashPage.locator('#dashUnitRows .unit-head[data-ledger-head="laft"] ~ .unit-row').evaluateAll(els => els.map(e => e.dataset.county));
results.dashUnitEmptyGroups = await dashPage.locator('#dashUnitRows .unit-empty').count();
results.dashLedgerFreshAvailable = ((await dashPage.locator('#dashLedgerRows .dash-row[data-ledger-row="laft"] .dash-row-fresh:not(.dash-row-withheld)').textContent()) || '').trim();
results.dashLedgerWithheldAvailable = ((await dashPage.locator('#dashLedgerRows .dash-row[data-ledger-row="laft"] .dash-row-withheld').textContent()) || '').trim();
results.dashLedgerWithheldAuctionsAbsent = await dashPage.locator('#dashLedgerRows .dash-row[data-ledger-row="auction"] .dash-row-withheld').count();
results.dashUnitBayUnavailable = await dashPage.locator('#dashUnitRows .unit-row[data-county="Bay"]').getAttribute('data-unavailable');
results.dashLedgerFreshAuctionsAbsent = await dashPage.locator('#dashLedgerRows .dash-row[data-ledger-row="auction"] .dash-row-fresh').count();
results.dashLedgerRowTitles = await dashPage.locator('#dashLedgerRows .dash-row-name').evaluateAll(els => els.map(e => e.textContent.trim()));
// Unified navigation (2026-09-30): exactly four destinations - Dashboard,
// List, Map, Watchlist - in the rail and the bottom bar, no per-ledger
// entries; the ledger is picked inside the List page (#ledgerTabs) and the
// nav entry stays on "list" whichever ledger is showing.
results.navRailItems = await dashPage.locator('.nav-list .nav-item[data-page]').evaluateAll(els => els.map(e => e.dataset.page + ':' + e.textContent.replace(/\s+/g, ' ').trim()));
results.navBottomItems = await dashPage.locator('#navBottom .nav-bottom-item[data-page]').evaluateAll(els => els.map(e => e.dataset.page));
results.navLedgerEntriesGone = await dashPage.locator('.nav-item[data-ledger], .nav-bottom-item[data-ledger]').count();
results.navDashboardLit = await dashPage.locator('.nav-list .nav-item.on').evaluateAll(els => els.map(e => e.dataset.page));
results.navDashboardHash = await dashPage.evaluate(() => location.hash);
await dashPage.click('.nav-list .nav-item[data-page="list"]');
await dashPage.waitForTimeout(300);
results.navListClickShowsListPage = await dashPage.locator('#pageList').evaluate(el => !el.hidden);
results.navListClickLit = await dashPage.locator('.nav-list .nav-item.on').evaluateAll(els => els.map(e => e.dataset.page));
results.navListClickHash = await dashPage.evaluate(() => location.hash);
await dashPage.click('.ledger-tab[data-ledger="certificate"]');
await dashPage.waitForTimeout(300);
results.tabCertHash = await dashPage.evaluate(() => location.hash);
results.tabCertNavLit = await dashPage.locator('.nav-list .nav-item.on').evaluateAll(els => els.map(e => e.dataset.page));
results.tabCertHeading = ((await dashPage.locator('.ledger-head h2').textContent()) || '').trim();
await dashPage.click('.ledger-tab[data-ledger="laft"]');
await dashPage.waitForTimeout(300);
results.tabLaftHash = await dashPage.evaluate(() => location.hash);
results.tabLaftHeading = ((await dashPage.locator('.ledger-head h2').textContent()) || '').trim();
results.navListCountIsSum = await dashPage.evaluate(() => {
  const tabs = Array.from(document.querySelectorAll('#ledgerTabs .ledger-tab b')).map(b => Number(b.textContent));
  return Number(document.getElementById('navCountList').textContent) === tabs.reduce((a, b) => a + b, 0) && tabs.reduce((a, b) => a + b, 0) > 0;
});
// The List page no longer carries its own state tabs: the state is the
// header's #stateSelect (see the global state context block below).
results.listHasNoStateTabs = (await dashPage.locator('#regionTabs, a[data-state-link]').count()) === 0;
// Watchlist: a destination with its own hash, lit while open; closing it
// restores the page underneath and its hash.
await dashPage.click('.nav-list .nav-item[data-page="watchlist"]');
await dashPage.waitForTimeout(300);
results.navWatchlistOpen = await dashPage.locator('#bidListModal').evaluate(el => !el.hidden);
results.navWatchlistLit = await dashPage.locator('.nav-list .nav-item.on').evaluateAll(els => els.map(e => e.dataset.page));
results.navWatchlistHash = await dashPage.evaluate(() => location.hash);
await dashPage.click('#bidListModal [data-action="closebidlist"]');
await dashPage.waitForTimeout(400);
results.navWatchlistClosedLit = await dashPage.locator('.nav-list .nav-item.on').evaluateAll(els => els.map(e => e.dataset.page));
results.navWatchlistClosedHash = await dashPage.evaluate(() => location.hash);
results.navWatchlistClosedListVisible = await dashPage.locator('#pageList').evaluate(el => !el.hidden);
await dashPage.click('.ledger-tab[data-ledger="auction"]');
await dashPage.waitForTimeout(300);
// Shared property layer: the certificate (p4) and the auction row (p1) are
// the same Alachua parcel 111 - each full page lists the other, and a
// parcel with no match says so in words rather than showing nothing.
await dashPage.click('.ledger-tab[data-ledger="certificate"]');
await dashPage.waitForTimeout(300);
await dashPage.locator('.county-group summary.county-head').first().click();   // county groups start collapsed
await dashPage.waitForTimeout(200);
await dashPage.locator('.cert-card [data-action="viewdetails"]').first().click();
await dashPage.waitForTimeout(400);
// At this width the page renders the detail into the modal AND the desktop
// side panel; read the modal only so nothing is counted twice.
const detailScope = '#detailModalInner';
results.certDetailRelated = await dashPage.locator(`${detailScope} .related-record`).evaluateAll(els => els.map(e => e.dataset.source + ':' + e.dataset.pid + ':' + e.querySelector('.related-ledger').textContent.trim()));
results.certDetailStatusLines = await dashPage.locator(`${detailScope} .cert-status-line`).count();
// The "Open" button sits deep in the modal's scroll box; a DOM click reaches
// the same delegated data-action handler without depending on scroll position.
await dashPage.locator(`${detailScope} .related-open`).first().evaluate(el => el.click());
await dashPage.waitForTimeout(400);
results.relatedOpenLandsOnAuctionRow = ((await dashPage.locator(`${detailScope} .detail-address`).first().textContent()) || '').trim();
results.auctionDetailRelated = await dashPage.locator(`${detailScope} .related-record`).evaluateAll(els => els.map(e => e.dataset.source + ':' + e.dataset.pid));
await dashPage.close();
const noHealthPage = await newPage({ viewport: { width: 1200, height: 900 } });
await noHealthPage.goto(BASE_URL + '?health=none' + '#/auctions', { waitUntil: 'networkidle' });
await noHealthPage.waitForTimeout(500);
await noHealthPage.click('.nav-item[data-page="dashboard"]');
await noHealthPage.waitForTimeout(200);
results.dashHealthMissingTable = ((await noHealthPage.locator('#dashSourceRows').textContent()) || '').includes('not recorded yet');
results.dashHealthMissingTableNoBadges = await noHealthPage.locator('#dashSourceRows .health-badge').count();
await noHealthPage.close();
const noRegPage = await newPage({ viewport: { width: 1200, height: 900 } });
await noRegPage.goto(BASE_URL + '?registry=none' + '#/auctions', { waitUntil: 'networkidle' });
await noRegPage.waitForTimeout(500);
await noRegPage.click('.nav-item[data-page="dashboard"]');
await noRegPage.waitForTimeout(200);
results.dashUnitMissingColumns = ((await noRegPage.locator('#dashUnitRows').textContent()) || '').includes('not recorded yet');
results.dashUnitMissingColumnsNoRows = await noRegPage.locator('#dashUnitRows .unit-row').count();
await noRegPage.close();

// --- Watchlist change signals: seed the snapshot a previous visit would
// have written (p1 with a lower bid, and a row that no longer exists) and
// check the diff is reported from the rows the app actually loaded. ---
const wcPage = await newPage({ viewport: { width: 1200, height: 900 } });
const wcSaleDate = (() => { const d = new Date(); d.setDate(d.getDate() + 3); return d.toISOString().slice(0, 10); })();
await wcPage.addInitScript(snap => { localStorage.setItem('tdw_watch_snapshot_v1', JSON.stringify(snap)); }, {
  savedAt: '2026-09-20T12:00:00Z', state: 'FL',
  rows: { p1: { sale_date: wcSaleDate, bid: 4000, status: 'active', label: '1 Main St', county: 'Alachua' },
          gone1: { sale_date: null, bid: 100, status: 'active', label: 'Vanished Parcel', county: 'Baker' } }
});
await wcPage.goto(BASE_URL + '#/auctions', { waitUntil: 'networkidle' });
await wcPage.waitForTimeout(500);
await wcPage.click('.nav-item[data-page="dashboard"]');
await wcPage.waitForTimeout(200);
results.watchChangeItems = await wcPage.locator('#dashWatchChanges .watch-change').evaluateAll(els => els.map(e => e.dataset.pid));
results.watchChangeBidLine = ((await wcPage.locator('#dashWatchChanges .watch-change[data-pid="p1"] li').first().textContent()) || '').trim();
results.watchChangeGoneLine = ((await wcPage.locator('#dashWatchChanges .watch-change[data-pid="gone1"] li').first().textContent()) || '').trim();
results.watchChangeSnapshotRewritten = await wcPage.evaluate(() => { const s = JSON.parse(localStorage.getItem('tdw_watch_snapshot_v1')); return s.savedAt !== '2026-09-20T12:00:00Z' && !('gone1' in s.rows); });
await wcPage.close();

// --- Support and help modals. supportEmail is blank in tests/config.js, so
// the unconfigured path renders first; then a configured address is set on
// the live config object and the mailto links appear. ---
const spPage = await newPage({ viewport: { width: 1200, height: 900 } });
await spPage.goto(BASE_URL + '#/auctions', { waitUntil: 'networkidle' });
await spPage.waitForTimeout(500);
await spPage.click('#supportBtn');
await spPage.waitForTimeout(150);
results.supportModalVisible = await spPage.locator('#supportModal').isVisible();
results.supportUnconfiguredShown = await spPage.locator('#supportUnconfigured').count();
results.supportTopicsDisabled = await spPage.locator('#supportBody .support-topic[disabled]').count();
results.supportContextHasPage = ((await spPage.locator('#supportContext').textContent()) || '').includes('Page: FL');
results.supportTopicLabels = await spPage.locator('#supportBody .support-topic').evaluateAll(els => els.map(e => e.firstChild.textContent.trim()));
await spPage.click('#supportCloseBtn');
await spPage.waitForTimeout(100);
await spPage.click('#helpBtn');
await spPage.waitForTimeout(150);
results.helpModalVisible = await spPage.locator('#helpModal').isVisible();
const helpText = (await spPage.locator('#helpBody').textContent()) || '';
results.helpCoversRequiredTopics = ['Not published', 'Not checked', 'Not tracked', 'source of sale is authoritative', 'does not mean the property sold', 'not a title search', 'Before you bid'].every(t => helpText.includes(t));
results.helpHasNoEmoji = !/[\u{1F300}-\u{1FAFF}]/u.test(helpText);
await spPage.close();
// "Report a data problem" from a property page (deep link opens the modal
// at any width) with a configured address: the context names the property
// and every topic is a mailto: link to that address.
const spPage2 = await newPage({ viewport: { width: 1200, height: 900 } });
await spPage2.goto(BASE_URL + '#/auctions/p1', { waitUntil: 'networkidle' });
await spPage2.waitForTimeout(500);
await spPage2.evaluate(() => { window.TDW_CONFIG.supportEmail = 'help@example.test'; });
await spPage2.locator('#detailModalInner [data-action="support"][data-topic="data"]').click();
await spPage2.waitForTimeout(150);
results.supportFromPropertyHasContext = ((await spPage2.locator('#supportContext').textContent()) || '').includes('Property: Alachua County, FL');
results.supportMailtoLinks = await spPage2.locator('#supportBody a.support-topic').count();
results.supportMailtoHref = ((await spPage2.locator('#supportBody a.support-topic[data-topic="data"]').getAttribute('href')) || '').split('?')[0];
results.supportSourceReportButton = await spPage2.locator('#detailModalInner [data-action="support"][data-topic="source"]').count();
await spPage2.close();

// --- Forgot password (supported Supabase pattern): empty e-mail is refused
// locally; a real request goes to resetPasswordForEmail with redirectTo
// = this page; the confirmation never reveals whether the address exists;
// a provider error is shown as-is. ---
const fpPage = await newPage({ viewport: { width: 390, height: 844 } });
await fpPage.goto(BASE_URL + '?authtest=1' + '#/auctions', { waitUntil: 'networkidle' });
await fpPage.waitForTimeout(300);
await fpPage.click('#forgotPasswordBtn');
await fpPage.waitForTimeout(100);
results.forgotNeedsEmail = ((await fpPage.locator('#authMsg').textContent()) || '').includes('Enter your email above first');
await fpPage.fill('#email', 'someone@example.com');
await fpPage.click('#forgotPasswordBtn');
await fpPage.waitForTimeout(200);
results.forgotResetCall = await fpPage.evaluate(() => (window.__stubResetCalls || []).map(c => [c.email, c.redirectTo.endsWith('/index.html')]));
results.forgotMessage = ((await fpPage.locator('#authMsg').textContent()) || '').trim();
await fpPage.close();
const fpFailPage = await newPage({ viewport: { width: 390, height: 844 } });
await fpFailPage.goto(BASE_URL + '?authtest=1&resetfail=1' + '#/auctions', { waitUntil: 'networkidle' });
await fpFailPage.waitForTimeout(300);
await fpFailPage.fill('#email', 'someone@example.com');
await fpFailPage.click('#forgotPasswordBtn');
await fpFailPage.waitForTimeout(200);
results.forgotErrorShown = ((await fpFailPage.locator('#authMsg').textContent()) || '').trim();
await fpFailPage.close();

// --- Multi-state product branding (2026-10-02): the sign-in, sign-up and
// reset screens and the generic shell never claim a single state; the
// selected state's own wording appears only in that state's context; a
// registered state with no rows says so and is never called unsupported. ---
{
  const STATE_WORDS = /Florida|Texas|Louisiana|Michigan|Wyoming|South Carolina|Colorado|Wisconsin/;
  const gateText = pg => pg.evaluate(() => document.getElementById('authGate').innerText.replace(/\s+/g, ' '));
  results.brandGate = {};
  for (const file of ['index.html', 'tx.html', 'la.html', 'mi.html', 'wy.html']) {
    const bp = await newPage({ viewport: { width: 390, height: 844 } });
    await bp.goto(BASE_URL.replace(/index\.html$/, file) + '?authtest=1', { waitUntil: 'networkidle' });
    await bp.waitForTimeout(300);
    const login = await gateText(bp);
    const title = await bp.title();
    await bp.click('#authModeToggle');
    await bp.waitForTimeout(150);
    const signup = await gateText(bp);
    await bp.click('#authModeToggle');
    await bp.click('#forgotPasswordBtn');
    await bp.waitForTimeout(150);
    const reset = await gateText(bp);
    results.brandGate[file] = {
      tagline: ((await bp.locator('#authGate .auth-tagline').first().textContent()) || '').trim(),
      sub: /across supported states/.test(login),
      loginNoState: !STATE_WORDS.test(login),
      signupNoState: !STATE_WORDS.test(signup),
      resetNoState: !STATE_WORDS.test(reset),
      titleNoState: !STATE_WORDS.test(title)
    };
    await bp.close();
  }
  // Service-worker-controlled reload: once sw.js controls the page, a fresh
  // load of the sign-in screen is still the neutral product shell.
  const swp = await newPage({ viewport: { width: 390, height: 844 } });
  await swp.goto(BASE_URL + '?authtest=1' + '#/auctions', { waitUntil: 'networkidle' });
  const swReady = await swp.evaluate(() => Promise.race([navigator.serviceWorker.ready.then(() => true), new Promise(r => setTimeout(() => r(false), 4000))]));
  await swp.reload({ waitUntil: 'networkidle' });
  await swp.waitForTimeout(300);
  const swLogin = await gateText(swp);
  results.brandSwReload = {
    ready: swReady,
    controlled: await swp.evaluate(() => !!navigator.serviceWorker.controller),
    tagline: ((await swp.locator('#authGate .auth-tagline').first().textContent()) || '').trim(),
    noState: !STATE_WORDS.test(swLogin) && !STATE_WORDS.test(await swp.title()),
    cache: await swp.evaluate(async () => (await caches.keys()).filter(k => k.startsWith('tdw-shell-')))
  };
  await swp.close();
  // --- Boot resilience (2026-10-03: production showed a black page with no
  // request ever reaching Supabase). (1) When the esm.sh supabase-js import
  // fails, supabase-loader.js falls back to this site's own copy and the
  // sign-in screen still appears. (2) When the app script never runs, boot.js
  // replaces the blank page with a visible explanation. (3) A normal start
  // never shows that panel.
  {
    const fb = await newPage({ viewport: { width: 390, height: 844 } });
    await fb.route(/\/index\.html(\?.*)?$/, async route => {
      const res = await route.fetch();
      const body = (await res.text()).replace('./vendor/supabase-stub.js', './vendor/no-such-module.js');
      await route.fulfill({ response: res, body });
    });
    await fb.goto(BASE_URL + '?authtest=1#/auctions', { waitUntil: 'networkidle' });
    await fb.waitForTimeout(500);
    results.bootFallback = await fb.evaluate(() => ({
      authGate: !document.getElementById('authGate').hidden,
      source: window.__tdwSupabaseSource || null,
      noted: (window.__tdwBootErrors || []).some(e => /esm\.sh failed/.test(e)),
      panel: !!document.getElementById('bootFailure')
    }));
    await fb.close();
    const st = await newPage({ viewport: { width: 390, height: 844 } });
    await st.addInitScript(() => { window.__tdwBootTimeoutMs = 1200; });
    await st.route(/\/app\.js(\?.*)?$/, route => route.abort());
    await st.goto(BASE_URL + '#/auctions', { waitUntil: 'load' });
    await st.waitForTimeout(2000);
    results.bootStalled = await st.evaluate(() => ({
      panel: !!document.getElementById('bootFailure'),
      buttons: [...document.querySelectorAll('#bootFailure button')].map(b => b.textContent),
      mentionsAppJs: /Could not load .*app\.js/.test((document.getElementById('bootErrors') || {}).textContent || '')
    }));
    await st.close();
    const ok = await newPage({ viewport: { width: 390, height: 844 } });
    await ok.addInitScript(() => { window.__tdwBootTimeoutMs = 1200; });
    await ok.goto(BASE_URL + '#/auctions', { waitUntil: 'networkidle' });
    await ok.waitForTimeout(2000);
    results.bootNormalNoPanel = await ok.evaluate(() => !document.getElementById('bootFailure') && !document.getElementById('app').hidden);
    await ok.close();
  }
  // Generic shell (signed in): brand, nav and footer name no state; the
  // header's state selector is the state context and is excluded.
  const sh = await newPage({ viewport: { width: 1200, height: 900 } });
  await sh.goto(BASE_URL.replace(/index\.html$/, 'mi.html') + '#/auctions', { waitUntil: 'networkidle' });
  await sh.waitForTimeout(500);
  results.brandShell = await sh.evaluate(() => {
    const words = /Florida|Texas|Louisiana|Wyoming|South Carolina|Colorado|Wisconsin/;
    const parts = ['.nav-rail', '.bottom-nav', '.topbar .brand'].flatMap(sel => [...document.querySelectorAll(sel)]).map(e => e.innerText).join(' ');
    return { shellNoOtherState: !words.test(parts), dataSourcesHead: [...document.querySelectorAll('.dash-panel-head')].some(e => e.textContent.trim() === 'Data sources (all states)') };
  });
  results.brandShell.title = await sh.title();
  await sh.close();
  // A Michigan auction is a Michigan tax sale auction - never a Florida one.
  // (A fresh page: a goto that only changes the hash is a same-document navigation.)
  const mw = await newPage({ viewport: { width: 1200, height: 900 } });
  await mw.goto(BASE_URL.replace(/index\.html$/, 'mi.html') + '#/auctions/pmi1', { waitUntil: 'networkidle' });
  await mw.waitForTimeout(600);
  const what = ((await mw.locator('#detailModalInner').innerText().catch(() => '')) || '');
  results.brandMiWhat = { michigan: /Michigan tax sale auction/.test(what), noFlorida: !/Florida tax deed auction/.test(what) };
  await mw.close();
  // Selected-state context keeps its own wording.
  const fl = await newPage({ viewport: { width: 1200, height: 900 } });
  await fl.goto(BASE_URL + '#/lands', { waitUntil: 'networkidle' });
  await fl.waitForTimeout(500);
  results.brandFlContext = { title: await fl.title(), floridaCopy: /Florida/.test(await fl.locator('#main').innerText()) };
  await fl.close();
  const tx = await newPage({ viewport: { width: 1200, height: 900 } });
  await tx.goto(BASE_URL.replace(/index\.html$/, 'tx.html') + '#/lands', { waitUntil: 'networkidle' });
  await tx.waitForTimeout(500);
  results.brandTxContext = {
    title: await tx.title(),
    ledgerTab: await tx.evaluate(() => (document.querySelector('#ledgerTabs .on, #ledgerTabs [aria-selected="true"]') || {}).dataset?.ledger || null),
    hash: await tx.evaluate(() => location.hash)
  };
  // The global state selector navigates to the chosen state's page, keeping the ledger route.
  await Promise.all([tx.waitForNavigation({ waitUntil: 'networkidle' }), tx.selectOption('#stateSelect', 'WY')]);
  await tx.waitForTimeout(500);
  results.brandStateSwitch = { file: await tx.evaluate(() => location.pathname.split('/').pop()), hash: await tx.evaluate(() => location.hash), state: await tx.locator('#stateSelect').inputValue() };
  await tx.close();
  // A registered state with no rows at all: plain wording, still selectable.
  const em = await newPage({ viewport: { width: 1200, height: 900 } });
  await em.goto(BASE_URL.replace(/index\.html$/, 'wi.html') + '?emptystate=1#/auctions', { waitUntil: 'networkidle' });
  await em.waitForTimeout(500);
  const emptyText = ((await em.locator('#main .empty-state').first().textContent().catch(() => '')) || '').trim();
  results.brandEmptyState = {
    says: emptyText.startsWith('No properties currently available for this state.'),
    neverUnsupported: !/unsupported|not supported/i.test(await em.locator('body').innerText()),
    stillListed: (await em.locator('#stateSelect option[value="WI"]').count()) === 1,
    selected: await em.locator('#stateSelect').inputValue()
  };
  await em.close();
}

// --- AVAILABLE coverage (2026-10-02): an empty Available ledger names WHICH
// zero it is, from public/available-coverage.json; a state with Available
// rows never shows the line. Nothing here creates or hides a row. ---
{
  results.availCoverage = {};
  for (const [file, code] of [['mi.html', 'MI'], ['co.html', 'CO'], ['wy.html', 'WY'], ['index.html', 'FL']]) {
    const ac = await newPage({ viewport: { width: 1200, height: 900 } });
    await ac.goto(BASE_URL.replace(/index\.html$/, file) + '#/lands', { waitUntil: 'networkidle' });
    await ac.waitForTimeout(500);
    const line = ac.locator('#main .available-coverage');
    results.availCoverage[code] = {
      status: (await line.count()) ? await line.first().getAttribute('data-coverage') : null,
      text: (await line.count()) ? ((await line.first().textContent()) || '').replace(/\s+/g, ' ').trim() : '',
      cards: await ac.locator('#main .prop-card').count()
    };
    await ac.close();
  }
}

// --- Arriving from the reset link: PASSWORD_RECOVERY opens the new-password
// form, which calls updateUser({ password }). ---
const rcPage = await newPage({ viewport: { width: 390, height: 844 } });
await rcPage.goto(BASE_URL + '?recovery=1' + '#/auctions', { waitUntil: 'networkidle' });
await rcPage.waitForTimeout(600);
results.recoveryModalOpens = await rcPage.locator('#recoveryModal').isVisible();
await rcPage.fill('#rcNew', 'newpass123');
await rcPage.fill('#rcConfirm', 'different');
await rcPage.click('#rcSubmitBtn');
await rcPage.waitForTimeout(100);
results.recoveryMismatchRefused = ((await rcPage.locator('#rcMsg').textContent()) || '').includes("don't match");
await rcPage.fill('#rcConfirm', 'newpass123');
await rcPage.click('#rcSubmitBtn');
await rcPage.waitForTimeout(200);
results.recoveryUpdateCall = await rcPage.evaluate(() => (window.__stubUpdateUserCalls || []).map(c => c.password));
results.recoveryMessage = ((await rcPage.locator('#rcMsg').textContent()) || '').trim();
await rcPage.close();

// --- Delete my account: typed confirmation, the RPC, and the honest
// "not available yet" message when migration 015 is not applied. ---
const daPage = await newPage({ viewport: { width: 1200, height: 900 } });
await daPage.goto(BASE_URL + '#/auctions', { waitUntil: 'networkidle' });
await daPage.waitForTimeout(500);
await daPage.click('#accountBtn');
await daPage.waitForTimeout(100);
await daPage.click('#deleteAccountBtn');
await daPage.waitForTimeout(150);
results.deleteModalVisible = await daPage.locator('#deleteAccountModal').isVisible();
results.deleteModalStatesScope = (await daPage.locator('#deleteAccountModal').textContent() || '').includes('Not affected');
await daPage.fill('#daConfirm', 'nope');
await daPage.click('#daSubmitBtn');
await daPage.waitForTimeout(100);
results.deleteWrongWordRefused = ((await daPage.locator('#daMsg').textContent()) || '').includes('Type DELETE');
results.deleteNotCalledYet = await daPage.evaluate(() => window.__stubDeleteCalls || 0);
await daPage.fill('#daConfirm', 'DELETE');
await daPage.click('#daSubmitBtn');
await daPage.waitForTimeout(1200);
// The success path signs out and reloads; sessionStorage survives the
// reload, and the stub's auto-session means the gate never clears it.
results.deleteSignedOutReason = await daPage.evaluate(() => sessionStorage.getItem('tdw_signout_reason'));
await daPage.close();
const daMissingPage = await newPage({ viewport: { width: 1200, height: 900 } });
await daMissingPage.goto(BASE_URL + '?rpcmissing=1' + '#/auctions', { waitUntil: 'networkidle' });
await daMissingPage.waitForTimeout(500);
await daMissingPage.click('#accountBtn');
await daMissingPage.waitForTimeout(100);
await daMissingPage.click('#deleteAccountBtn');
await daMissingPage.waitForTimeout(150);
await daMissingPage.fill('#daConfirm', 'DELETE');
await daMissingPage.click('#daSubmitBtn');
await daMissingPage.waitForTimeout(300);
results.deleteMissingRpcMessage = ((await daMissingPage.locator('#daMsg').textContent()) || '').trim();
results.deleteMissingRpcNoSignOut = await daMissingPage.evaluate(() => sessionStorage.getItem('tdw_signout_reason'));
await daMissingPage.close();

// --- Claim fixes: the raw pipeline status word is no longer shown as a
// customer word; the notes editor says notes are shared; a Texas
// struck-off row is never called "Lands Available". ---
const clPage = await newPage({ viewport: { width: 1200, height: 900 } });
await clPage.goto(BASE_URL + '#/auctions/p1', { waitUntil: 'networkidle' });
await clPage.waitForTimeout(500);
results.detailStatusPill = ((await clPage.locator('#detailModalInner .prop-top-actions .pill').textContent()) || '').trim();
results.detailStatusPillClass = await clPage.locator('#detailModalInner .prop-top-actions .pill').evaluate(el => el.className);
results.notesVisibilityText = ((await clPage.locator('#detailModalInner .notes-visibility').textContent()) || '').trim();
results.tableHeaderValue = ((await clPage.locator('.data-table-wrap thead th').nth(3).textContent()) || '').trim();
await clPage.close();
const txClPage = await newPage({ viewport: { width: 1200, height: 900 } });
await txClPage.goto(TX_BASE_URL + '#/lands/ptx3', { waitUntil: 'networkidle' });
await txClPage.waitForTimeout(500);
results.txStruckOffDetailTag = ((await txClPage.locator('#detailModalInner .prop-county-tag').textContent()) || '').trim();
results.txStruckOffWhat = ((await txClPage.locator('#detailModalInner .opp-cell').first().textContent()) || '').replace(/\s+/g, ' ').trim();
results.txStruckOffNeverLandsAvailable = !((await txClPage.locator('#detailModalInner').textContent()) || '').includes('Lands Available for Taxes');
// Residual from the final review of PR #35: the county-group header on the
// Texas struck-off ledger used the Florida "Lands Available - fixed price,
// available now" line. It must describe the inventory without claiming it
// is purchasable today; the Florida page keeps the statutory wording.
const txGroupMeta = await txClPage.locator('.county-group .county-meta').allTextContents();
results.txStruckOffGroupMetaCount = txGroupMeta.length;
results.txStruckOffGroupMetaText = txGroupMeta[0] ? txGroupMeta[0].trim() : null;
results.txStruckOffGroupMetaNeverLandsAvailable = txGroupMeta.every(tx => !/Lands Available|available now/i.test(tx));
// --- Enrichment phase: Inventory & Purchase card on a Texas struck-off row
// (ptx3: STRUCK_OFF_HELD_IN_TRUST, no list/document/purchase URL, no
// purchase_amount, legacy bid). Every line is a stored column or an honest
// "not published"; the vendor list is never presented as a purchase path.
// Rows are located by their label, not by index: the card is grouped
// (Inventory / Property / Purchase path) and a group's rows depend on which
// columns the row carries.
const invVal = (page, label) => page.locator('#detailModalInner .inventory-card .kv-row')
  .filter({ has: page.locator('.kv-label', { hasText: new RegExp('^' + label.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '$') }) })
  .first().locator('.kv-val').evaluate(el => el.innerText.replace(/\s+/g, ' ').trim());
const invHref = (page, label) => page.locator('#detailModalInner .inventory-card .kv-row')
  .filter({ has: page.locator('.kv-label', { hasText: new RegExp('^' + label.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '$') }) })
  .first().locator('a').first().getAttribute('href');
results.txInventoryLabels = await txClPage.locator('#detailModalInner .inventory-card .kv-label').allTextContents();
results.txInventoryGroups = await txClPage.locator('#detailModalInner .inventory-card .kv-group-head').allTextContents();
results.txInventoryType = await invVal(txClPage, 'Inventory');
results.txInventoryStatus = await invVal(txClPage, 'Status');
results.txProvenanceHasNoTable = await txClPage.locator('#detailModalInner .provenance-card .prov-table').count();
results.txInventoryAmount = await invVal(txClPage, 'Amount');
results.txInventorySourceList = await invVal(txClPage, 'Source list');
results.txInventoryPurchase = await invVal(txClPage, 'Purchase link');
results.txInventoryAcquire = await invVal(txClPage, 'How to acquire');
results.txInventoryOwner = await invVal(txClPage, 'Owner of record');
results.txInventoryParcel = await invVal(txClPage, 'Parcel #');
results.txInventoryAnchors = await txClPage.locator('#detailModalInner .inventory-card a').count();
// Acquisition sprint: the gap is the UNVERIFIED process, never a missing hyperlink.
results.txInventoryGapNamesAcquisition = !((await txClPage.locator('#detailModalInner .opp-gaps').textContent()) || '').includes('Acquisition path not yet verified');   // verified county process (fixture)
results.txInventoryGapNeverNamesLink = !((await txClPage.locator('#detailModalInner .opp-gaps').textContent()) || '').includes('Purchase link not on file');
await txClPage.close();
// --- Enrichment phase: the same card on a Florida Lands Available row
// (p3: every 017/019 column the lifecycle + laft_source_fields write, no
// purchase_url). Opened by deep link (cold start, Phase 58) so this page
// is independent of the lands-list state above.
const flInvPage = await newPage({ viewport: { width: 1200, height: 900 } });
await flInvPage.goto(BASE_URL + '#/lands/p3', { waitUntil: 'networkidle' });
await flInvPage.waitForTimeout(500);
results.flInventoryLabels = await flInvPage.locator('#detailModalInner .inventory-card .kv-label').allTextContents();
// AVAILABLE commercialization: the provenance card says what the availability
// evidence is, when the row was last verified, the source date, where the
// purchase path comes from - and carries the published / derived / not
// published legend. p3's otc_provenance mode is "unknown" (nothing verified).
results.flAvailabilityEvidence = await flInvPage.locator('#detailModalInner .prov-available .prov-line').evaluateAll(els => els.map(e => e.querySelector('.prov-k').textContent.trim() + ' | ' + e.querySelector('.prov-v').textContent.replace(/\s+/g, ' ').trim()));
results.flProvLegendCount = await flInvPage.locator('#detailModalInner .prov-legend').count();
results.flPurchaseModeLine = await flInvPage.locator('#detailModalInner .prov-lines:not(.prov-available) .prov-line').evaluateAll(els => (els.map(e => e.querySelector('.prov-k').textContent.trim() + ' | ' + e.querySelector('.prov-v').textContent.trim()).find(t => t.startsWith('How to purchase')) || ''));
// Production-readiness: the normalized status row (migration 021) and the
// per-field / per-row provenance table on the same page.
results.flInventoryStatus = await invVal(flInvPage, 'Status');
results.flProvenanceRows = await flInvPage.locator('#detailModalInner .provenance-card .prov-row:not(.prov-head)').evaluateAll(els => els.map(e => e.dataset.field + '|' + e.querySelector('.prov-source').innerText.replace(/\s+/g, ' ').trim() + '|' + e.querySelector('.prov-method').innerText.trim() + '|' + e.querySelector('.prov-when').innerText.trim()));
results.flProvenanceLines = await flInvPage.locator('#detailModalInner .provenance-card .prov-line .prov-k').allTextContents();
results.flProvenancePurchaseLine = ((await flInvPage.locator('#detailModalInner .provenance-card .prov-line').filter({ hasText: 'Purchase path' }).locator('.prov-v').textContent()) || '').trim();
results.flProvenanceFresh = ((await flInvPage.locator('#detailModalInner .provenance-card .prov-fresh').textContent()) || '').trim();
results.flProvenanceNoScoreWords = !/confidence score|ai score|investment score|quality badge|probability|verified label/i.test(((await flInvPage.locator('#detailModalInner .provenance-card').textContent()) || '').replace(/Data Quality & Provenance|Report a data problem/g, ''));
results.flInventoryGroups = await flInvPage.locator('#detailModalInner .inventory-card .kv-group-head').allTextContents();
results.flInventoryType = await invVal(flInvPage, 'Inventory');
results.flInventoryPrice = await invVal(flInvPage, 'Price');
results.flInventoryCertificate = await invVal(flInvPage, 'Certificate #');
results.flInventoryAvailable = await invVal(flInvPage, 'Available for purchase');
results.flInventoryEscheat = await invVal(flInvPage, 'Escheats to county');
results.flInventorySourceListHref = await invHref(flInvPage, 'Source list');
results.flInventoryDocumentHref = await invHref(flInvPage, 'Source document');
results.flInventoryPurchase = await invVal(flInvPage, 'Purchase link');
results.flInventoryPublishedBy = await invVal(flInvPage, 'Published by');
results.flInventoryLastRead = await invVal(flInvPage, 'Last read from source');
results.flInventoryListAsOf = await invVal(flInvPage, 'List as of');
results.flInventoryDocDated = await invVal(flInvPage, 'Source document dated');
// Property group: stored columns or an explicit "not on file" - p3 carries
// parcel/owner/assessed/homestead and no legal description, taxable value
// or acreage.
results.flInventoryParcel = await invVal(flInvPage, 'Parcel #');
results.flInventoryLegal = await invVal(flInvPage, 'Legal description');
results.flInventoryOwner = await invVal(flInvPage, 'Name in which assessed');
results.flInventoryAssessed = await invVal(flInvPage, 'Assessed value');
results.flInventoryTaxable = await invVal(flInvPage, 'Taxable value');
results.flInventoryAcreage = await invVal(flInvPage, 'Acreage');
results.flInventoryLandUse = await invVal(flInvPage, 'Land use');
results.flInventoryHomestead = await invVal(flInvPage, 'Homestead');
results.flInventoryPurchaseActionCount = await flInvPage.locator('#detailModalInner .inventory-card a.purchase-action').count();
// Purchase-path rendering is kind-driven. The fixture ships no row with a
// purchase_url (no Florida county has a verified one), so the other states
// are exercised through the module's own renderer on synthetic rows: a
// PROPERTY-level kind is the one prominent action; an instructions kind is
// an ordinary link labelled as instructions; a URL with no recognised kind
// is never promoted to an action; no URL says so; a list page is never
// turned into a purchase link.
const purchaseUi = await flInvPage.evaluate(() => {
  const base = { source: 'laft', state: 'FL', county: 'Bay', case_no: 'C-9', parcel: '9', inventory_type: 'POST_SALE_FIXED_PRICE',
                 purchase_amount_kind: 'NOT_PUBLISHED', list_url: 'https://x', url_auction: 'https://x', url_auction_kind: 'county' };
  const render = p => {
    const d = document.createElement('div');
    d.innerHTML = window.__tdwInventoryCardHtml(p);
    const buy = d.querySelector('.kv-list[data-group="purchase"]');
    return {
      action: buy.querySelectorAll('a.purchase-action').length,
      anchors: [...buy.querySelectorAll('a')].map(a => [a.textContent.trim(), a.getAttribute('href')]),
      text: [...buy.querySelectorAll('.kv-row')].find(r => r.querySelector('.kv-label').textContent === 'Purchase link').querySelector('.kv-val').textContent.replace(/\s+/g, ' ').trim(),
      acquire: [...buy.querySelectorAll('.kv-row')].find(r => r.querySelector('.kv-label').textContent === 'How to acquire').querySelector('.kv-val').textContent.replace(/\s+/g, ' ').trim(),
      groups: [...d.querySelectorAll('.kv-group-head')].map(e => e.textContent),
      allAnchors: d.querySelectorAll('a').length
    };
  };
  return {
    property: render({ ...base, purchase_url: 'https://x/buy/C-9', purchase_url_kind: 'online_purchase' }),
    offer: render({ ...base, purchase_url: 'https://x/offer/C-9', purchase_url_kind: 'offer_form' }),
    instructions: render({ ...base, purchase_url: 'https://x/how-to-buy', purchase_url_kind: 'purchase_instructions' }),
    application: render({ ...base, purchase_url: 'https://x/apply', purchase_url_kind: 'application_form' }),
    unknownKind: render({ ...base, purchase_url: 'https://x/legacy', purchase_url_kind: null }),
    none: render({ ...base })
  };
});
results.purchasePathPropertyLevelShowsOneAction = purchaseUi.property.action === 1 && purchaseUi.offer.action === 1;
results.purchasePathPropertyLevelAnchor = purchaseUi.property.anchors[0];
results.purchasePathPropertyLevelCaption = /Property-level link published by the source/.test(purchaseUi.property.text) && !/instructions/i.test(purchaseUi.property.text);
results.purchasePathInstructionsAnchor = purchaseUi.instructions.anchors[0];
results.purchasePathInstructionsNeverAction = purchaseUi.instructions.action === 0 && purchaseUi.application.action === 0
  && /not a link for this specific property/.test(purchaseUi.instructions.text) && /Application \/ purchase instructions/.test(purchaseUi.application.text);
results.purchasePathUnknownKindNeverAction = purchaseUi.unknownKind.action === 0 && purchaseUi.unknownKind.anchors.length === 1 && /Application \/ purchase instructions/.test(purchaseUi.unknownKind.text);
results.purchasePathNoneText = purchaseUi.none.text;
results.purchasePathNoneHasNoAnchorInPurchaseGroup = purchaseUi.none.anchors.length === 0;
results.purchasePathListPageIsOnlySourceListLink = purchaseUi.none.allAnchors === 1;
results.inventoryCardGroups = purchaseUi.none.groups;
results.purchasePathNoneAcquire = purchaseUi.none.acquire;
results.flInventoryNavHasInventory = (await flInvPage.locator('#detailModalInner .detail-nav button').allTextContents()).includes('Inventory');
results.flInventoryNoAiBadge = !/score|confidence|AI /i.test((await flInvPage.locator('#detailModalInner .inventory-card').textContent()) || '');
await flInvPage.close();
const flLandsPage = await newPage({ viewport: { width: 1200, height: 900 } });
await flLandsPage.goto(BASE_URL + '#/lands', { waitUntil: 'networkidle' });
await flLandsPage.waitForTimeout(400);
results.flLandsGroupMetaText = ((await flLandsPage.locator('.county-group .county-meta').first().textContent()) || '').trim();
// Migration 017 amount semantics in hasPublishedBid(): purchase_amount_kind
// is authoritative when present; the legacy bid sentinel rule is unchanged
// for rows without it. Exercised through the module's test hook because the
// fixture deliberately adds no card for each branch.
results.bidKindNotPublishedWinsOverSentinel = await flLandsPage.evaluate(() => window.__tdwHasPublishedBid({ bid: 2000, purchase_amount: null, purchase_amount_kind: 'NOT_PUBLISHED' }));
results.bidKindPublishedAmountWinsOverZeroSentinel = await flLandsPage.evaluate(() => window.__tdwHasPublishedBid({ bid: 0, purchase_amount: 500, purchase_amount_kind: 'OPENING_BID' }));
results.bidLegacyZeroSentinelNotPublished = await flLandsPage.evaluate(() => window.__tdwHasPublishedBid({ bid: 0 }));
results.bidLegacyNullNotPublished = await flLandsPage.evaluate(() => window.__tdwHasPublishedBid({ bid: null }));
results.bidLegacyPositiveStillPublished = await flLandsPage.evaluate(() => window.__tdwHasPublishedBid({ bid: 2000 }));
results.bidTxVendorRowWithoutKindUsesLegacyRule = await flLandsPage.evaluate(() => window.__tdwHasPublishedBid({ bid: 4451.95, purchase_amount: null, purchase_amount_kind: null }));
await flLandsPage.close();

// ============================================================
// Available commercial release (2026-09-30, migration 023)
// ============================================================
// The decision page: eleven questions, each answered from a stored field or
// its honest absence. p3 has NO typed purchase path (the engine established
// nothing) - "How do I buy it?" must say so; p15 has a source-level
// county-instructions page with evidence and an observed date.
const decA = async (pg, id) => ((await pg.locator(`#detailModalInner .decision-card .dec-row[data-q="${id}"] .dec-a`).innerText()) || '').replace(/\s+/g, ' ').trim();
const decPage = await newPage({ viewport: { width: 1200, height: 900 } });
await decPage.goto(BASE_URL + '#/lands/p3', { waitUntil: 'networkidle' });
await decPage.waitForTimeout(700);
results.decQuestions = await decPage.locator('#detailModalInner .decision-card .dec-q').allTextContents();
results.decNavHasDecision = await decPage.locator('#detailModalInner .detail-nav button[data-target="decision"]').count();
results.decP3How = await decA(decPage, 'how');
results.decP3HowLinkCount = await decPage.locator('#detailModalInner .decision-card .dec-row[data-q="how"] a').count();
results.decP3Available = await decA(decPage, 'available');
results.decP3Where = await decA(decPage, 'where');
results.decP3Fresh = await decA(decPage, 'fresh');
results.decP3History = await decA(decPage, 'history');
results.decP3Related = await decA(decPage, 'related');
results.decP3Contact = await decA(decPage, 'contact');
results.decP3Why = await decA(decPage, 'why');
results.decP3Glance = ((await decPage.locator('#detailModalInner .opp-summary .opp-cell').filter({ hasText: 'How to acquire' }).locator('.opp-val').innerText()) || '').replace(/\s+/g, ' ').trim();
results.decP3GapNamesAcquisition = !(await decPage.locator('#detailModalInner .opp-gaps').innerText()).includes('Acquisition path not yet verified');   // p3 now carries a verified county process
results.decP3PathEvidenceLine = await decPage.locator('#detailModalInner .prov-available .prov-line').filter({ hasText: 'Path evidence' }).locator('.prov-v').innerText();
// No score / badge / recommendation vocabulary anywhere on the block.
results.decNoScoreWords = !/\b(score|badge|recommend|opportunity rating|confidence|AI)\b/i.test(await decPage.locator('#detailModalInner .decision-card').innerText());
await decPage.close();
const dec2 = await newPage({ viewport: { width: 1200, height: 900 } });
await dec2.goto(BASE_URL + '#/lands/p15', { waitUntil: 'networkidle' });
await dec2.waitForTimeout(700);
results.decP15What = await decA(dec2, 'what');
results.decP15Available = await decA(dec2, 'available');
results.decP15How = await decA(dec2, 'how');
// Acquisition sprint: the "how" row is the acquisition record - mode, the
// published steps in order, the documents; "contact" is the published office /
// address / phone / e-mail; "why" names the listing, its date and the
// deterministic identifier that ties the row to it.
results.decP15HowHrefs = await dec2.locator('#detailModalInner .decision-card .dec-row[data-q="how"] a').evaluateAll(els => els.map(e => e.getAttribute('href')));
results.decP15HowMode = ((await dec2.locator('#detailModalInner .decision-card .dec-row[data-q="how"] .acq-mode').textContent()) || '').trim();
results.decP15HowSteps = await dec2.locator('#detailModalInner .decision-card .dec-row[data-q="how"] .acq-steps li').allTextContents();
results.decP15Contact = await decA(dec2, 'contact');
results.decP15ContactLinks = await dec2.locator('#detailModalInner .decision-card .dec-row[data-q="contact"] a').evaluateAll(els => els.map(e => e.getAttribute('href')));
results.decP15Why = await decA(dec2, 'why');
results.decP15SourceDocHrefs = await dec2.locator('#detailModalInner .decision-card .dec-row[data-q="source"] a').evaluateAll(els => els.map(e => e.getAttribute('href')));
results.decP15Glance = ((await dec2.locator('#detailModalInner .opp-summary .opp-cell').filter({ hasText: 'How to acquire' }).locator('.opp-val').innerText()) || '').replace(/\s+/g, ' ').trim();
results.decP15InvAcquire = await invVal(dec2, 'How to acquire');
// Acquisition sprint 2: scope labels, the first step, and the last-verified
// line - including a verified county process whose county source could not
// be read at the last attempt (Bay's fixture unit is SOURCE_UNAVAILABLE):
// the process stays, dated, with a retry note; it is never withdrawn.
results.decP15Scope = await dec2.locator('#detailModalInner .decision-card .dec-row[data-q="how"] .acq-scope').getAttribute('data-scope');
results.decP15First = ((await dec2.locator('#detailModalInner .decision-card .dec-row[data-q="how"] .acq-first').textContent()) || '').trim();
results.decP15Verified = ((await dec2.locator('#detailModalInner .decision-card .dec-row[data-q="how"] .acq-verified').textContent()) || '').trim();
results.acqUnavailableKeepsPath = await dec2.evaluate(() => {
  const d = document.createElement('div');
  d.innerHTML = window.__tdwAcquisitionHtml({ source: 'laft', state: 'FL', county: 'Bay', source_id: 'fl_laft_pioneer', case_no: 'X-1',
    purchase_path_type: 'phone_mail', purchase_path_scope: 'source', purchase_path_evidence: 'e', purchase_path_observed_on: '2026-09-30',
    otc_provenance: { acquisition: { mode: 'phone', channels: ['phone'], phone: '(000) 000-0001', steps: ['Call the Tax Deed Division'] } } });
  return { mode: d.querySelector('.acq-mode').textContent, verified: d.querySelector('.acq-verified').textContent.replace(/\s+/g, ' ').trim(),
           notVerified: /Not yet verified/.test(d.textContent) };
});
results.acqPropertyScopeLabel = await dec2.evaluate(() => {
  const d = document.createElement('div');
  d.innerHTML = window.__tdwAcquisitionHtml({ source: 'laft', state: 'FL', county: 'Citrus', case_no: 'X-2', purchase_path_type: 'direct_property_url',
    purchase_path_scope: 'property', purchase_path_evidence: 'e', purchase_path_observed_on: '2026-09-30', purchase_url: 'https://clerk.example.gov/buy/X-2' });
  return d.querySelector('.acq-scope').textContent;
});
results.decP15Cost = await decA(dec2, 'cost');
results.decP15Where = await decA(dec2, 'where');
results.decP15Known = await decA(dec2, 'known');
results.decP15Unknown = await dec2.locator('#detailModalInner .decision-card .dec-row[data-q="unknown"] li').allTextContents();
results.decP15Source = await decA(dec2, 'source');
results.decP15Fresh = await decA(dec2, 'fresh');
// The append-only lifecycle history: first observed, removed, reactivated,
// last read - in date order, with the removal never worded as a sale.
results.decP15History = await dec2.locator('#detailModalInner .decision-card .dec-history li').evaluateAll(els => els.map(e => e.dataset.kind + '|' + e.querySelector('.dec-when').textContent.trim() + '|' + e.querySelector('.dec-what').firstChild.textContent.trim()));
results.decP15HistoryNote = ((await dec2.locator('#detailModalInner .decision-card .dec-row[data-q="history"] .dec-history-note').innerText()) || '').trim();
results.decP15PathEvidenceLine = await dec2.locator('#detailModalInner .prov-available .prov-line').filter({ hasText: 'Path evidence' }).locator('.prov-v').innerText();
results.decP15GapsNamePathKind = !/Purchase link not on file|Acquisition path not yet verified/.test(await dec2.locator('#detailModalInner .opp-gaps').innerText());
await dec2.close();
// The history table missing (migration 021 not applied on a deployment).
const dec3 = await newPage({ viewport: { width: 1200, height: 900 } });
await dec3.goto(BASE_URL + '?history=none#/lands/p15', { waitUntil: 'networkidle' });
await dec3.waitForTimeout(700);
results.decHistoryMissing = await decA(dec3, 'history');
await dec3.close();

// Acquisition-path sprint (2026-10-01): the acquisition path is ENRICHMENT.
// An Available row with no verified process (ptx6, Liberty TX) is still published and
// opens on HOW TO ACQUIRE with "Not yet verified" and its official source;
// a verified row (p3, ptx3) shows one truthful primary action, method,
// instructions, official source and last-verified date.
const acqPage = await newPage({ viewport: { width: 1200, height: 900 } });
await acqPage.goto(BASE_URL + '#/lands', { waitUntil: 'networkidle' });
await acqPage.waitForTimeout(600);
results.acqWithheldLineCount = await acqPage.locator('#ledgerWithheldAcq').count();
await acqPage.close();
const acqP16 = await newPage({ viewport: { width: 1200, height: 900 } });
await acqP16.goto(TX_BASE_URL + '#/lands/ptx6', { waitUntil: 'networkidle' });
await acqP16.waitForTimeout(600);
const acq16 = acqP16.locator('#detailModalInner .acquire-card');
results.acqP16State = await acq16.locator('.acq-block').getAttribute('data-acq-state');
results.acqP16Rows = await acq16.locator('.acq-dl dt').evaluateAll(els => els.map(dt => dt.textContent.trim() + ' | ' + dt.nextElementSibling.textContent.trim()));
results.acqP16SourceHref = await acq16.locator('.acq-dl dd a').first().getAttribute('href');
results.acqP16NoCta = await acq16.locator('.acq-cta').count();
results.acqP16PendingNotError = await acq16.locator('.acq-pending').evaluate(e => !e.closest('.bad, .warn, .err'));
await acqP16.close();
// A separate page: a hash-only goto is a same-document navigation and would
// never run the cold-start deep link (see CLAUDE.md, Phase 58).
const acqP3 = await newPage({ viewport: { width: 1200, height: 900 } });
await acqP3.goto(BASE_URL + '#/lands/p3', { waitUntil: 'networkidle' });
await acqP3.waitForTimeout(600);
const acqBlock = acqP3.locator('#detailModalInner .acquire-card');
results.acqP3Heads = await acqBlock.locator('.acq-h').allTextContents();
results.acqP3Cta = await acqBlock.locator('.acq-cta').evaluate(a => a.textContent.trim() + ' | ' + a.getAttribute('href'));
results.acqP3Labels = await acqBlock.locator('.acq-dl dt').allTextContents();
results.acqP3Availability = await acqBlock.locator('.acq-why-link a').evaluate(a => a.textContent.trim() + ' | ' + a.getAttribute('href'));
results.acqP3FirstSection = await acqP3.locator('#detailModalInner .detail-section').first().getAttribute('data-section');
results.acqP3NoScoreWords = !/\b(score|badge|recommend|rating|AI)\b/.test(await acqBlock.innerText());
await acqP3.close();
const acqTx = await newPage({ viewport: { width: 1200, height: 900 } });
await acqTx.goto(TX_BASE_URL + '#/lands/ptx3', { waitUntil: 'networkidle' });
await acqTx.waitForTimeout(600);
const acqTxBlock = acqTx.locator('#detailModalInner .acquire-card');
results.acqTxWhy = ((await acqTxBlock.locator('.acq-why-text').textContent()) || '').trim();
results.acqTxCta = await acqTxBlock.locator('.acq-cta').evaluate(a => a.textContent.trim() + ' | ' + a.getAttribute('href'));
results.acqTxAvailability = await acqTxBlock.locator('.acq-why-link a').evaluate(a => a.textContent.trim() + ' | ' + a.getAttribute('href'));
results.acqTxOfficial = await acqTxBlock.locator('.acq-dl dd a').first().evaluate(a => a.textContent.trim() + ' | ' + a.getAttribute('href'));
results.acqTxVerified = await acqTxBlock.locator('.acq-dl dt', { hasText: 'Last verified' }).locator('xpath=following-sibling::dd[1]').innerText();
await acqTx.close();

// Customer-value sprint: the Auction decision block (seven questions) on an
// upcoming auction whose parcel is ALSO under a certificate (p1 / p4), and
// on a past-due auction (p13) whose result the source never published;
// the Certificate decision block (six questions) on p4; the cross-ledger
// line says "currently" / "previously" from stored status only.
const aucDec = await newPage({ viewport: { width: 1200, height: 900 } });
await aucDec.goto(BASE_URL + '#/auctions/p1', { waitUntil: 'networkidle' });
await aucDec.waitForTimeout(600);
results.aucDecQuestions = await aucDec.locator('#detailModalInner .decision-card .dec-q').allTextContents();
results.aucDecP1When = await decA(aucDec, 'when');
results.aucDecP1Bid = await decA(aucDec, 'bid');
results.aucDecP1Related = await decA(aucDec, 'related');
results.aucDecP1Result = await decA(aucDec, 'result');
results.aucDecP1Source = await decA(aucDec, 'source');
results.aucRelatedWhen = await aucDec.locator('#detailModalInner .related-record').evaluateAll(els => els.map(e => e.dataset.source + ':' + e.dataset.when + ':' + e.querySelector('.related-when').textContent.trim()));
results.aucDecNoScoreWords = !/\b(score|badge|recommend|deal quality|rating|confidence)\b/i.test(await aucDec.locator('#detailModalInner .decision-card').innerText());
await aucDec.close();
const aucPast = await newPage({ viewport: { width: 1200, height: 900 } });
await aucPast.goto(BASE_URL + '#/auctions/p13', { waitUntil: 'networkidle' });
await aucPast.waitForTimeout(600);
results.aucDecP13Result = await decA(aucPast, 'result');
results.aucDecP13ResultNeverSold = !/\bsold\b|\bredeemed\b/i.test(await decA(aucPast, 'result').then(t => t.replace(/whether it sold, was redeemed, cancelled or postponed is not recorded/i, '')));
await aucPast.close();
const certDec = await newPage({ viewport: { width: 1200, height: 900 } });
await certDec.goto(BASE_URL + '#/certificates/p4', { waitUntil: 'networkidle' });
await certDec.waitForTimeout(600);
results.certDecQuestions = await certDec.locator('#detailModalInner .decision-card .dec-q').allTextContents();
results.certDecWhat = await decA(certDec, 'what');
results.certDecAmount = await decA(certDec, 'amount');
results.certDecTerms = await decA(certDec, 'terms');
results.certDecRedemption = await decA(certDec, 'redemption');
results.certDecRelated = await decA(certDec, 'related');
results.certDecNavHasDecision = await certDec.locator('#detailModalInner .detail-nav button[data-target="decision"]').count();
await certDec.close();
// The certificate export: the certificate's own published facts plus the
// two app-computed figures the card shows, and nothing internal.
const certExp = await newPage({ viewport: { width: 1200, height: 900 } });
await certExp.goto(BASE_URL + '#/certificates', { waitUntil: 'networkidle' });
await certExp.waitForTimeout(500);
const certDl = certExp.waitForEvent('download');
await certExp.click('#exportCsvBtn');
const certCsv = await certDl;
{
  const text = fs.readFileSync(await certCsv.path(), 'utf8');
  const header = text.split(/\r?\n/)[0].split(',');
  results.certCsvHeader = header;
  results.certCsvHeaderLacks = ['publication', 'provenance', 'basis', 'harvester_source', 'Lien Notes', 'Opening Bid', 'Fees', 'Year Built'].every(h => !header.some(c => c.toLowerCase().includes(h.toLowerCase())));
}
await certExp.close();

// --- Auction-outcome evidence sprint: every outcome state from the same
// rules the page uses (window.__tdwOutcome), on synthetic events; p13's
// real decision row ("Outcome not published", from its closed-feed
// observation); the auction export's outcome columns; the auction ->
// Available relationship only with BOTH facts verified. ---
const outPage = await newPage({ viewport: { width: 1200, height: 900 } });
await outPage.goto(BASE_URL + '#/auctions/p13', { waitUntil: 'networkidle' });
await outPage.waitForTimeout(600);
results.outcomeP13Result = await decA(outPage, 'result');
results.outcomeP13Kicker = await outPage.evaluate(() => window.__tdwAuctionOutcomeState({ id: 'p13', source: 'auction', sale_date: '2020-01-01' }).label);
results.outcomeStates = await outPage.evaluate(() => {
  const O = window.__tdwOutcome;
  const url = 'https://jackson.realtaxdeed.com/index.cfm?zaction=AUCTION&zmethod=PREVIEW&AuctionDate=09/29/2026';
  const closed = (raw, outcome, lifecycle) => ({ feed: 'closed', raw_status: raw, outcome, lifecycle, observed_at: '2026-09-30T15:00:00Z', evidence_url: url });
  const ev = (o) => Object.assign({ id: 'x', case_no: '2024 TD 0001', scheduled_sale_date: '2026-09-29', lifecycle: 'completed', outcome: 'unknown', outcome_raw: null, outcome_observed_at: null, winning_bid: null, event_url: url }, o);
  const st = (e, c) => O.eventOutcomeState(e, c, null);
  const sold = st(ev({ outcome: 'sold', outcome_raw: 'Auction Sold', outcome_observed_at: '2026-09-30T15:00:00Z', winning_bid: 12300 }), closed('Auction Sold', 'sold', 'completed'));
  const soldNoAmount = st(ev({ outcome: 'sold', outcome_raw: 'Auction Sold', outcome_observed_at: '2026-09-30T15:00:00Z' }), closed('Auction Sold', 'sold', 'completed'));
  return {
    sold: sold.label, soldProv: O.outcomeProvenanceText(sold, null).replace(/<[^>]+>/g, ''),
    soldNoAmount: O.outcomeProvenanceText(soldNoAmount, null).replace(/<[^>]+>/g, '').includes('Sale amount: not published'),
    struck: st(ev({ outcome: 'struck_off', outcome_raw: 'Struck Off' }), null).label,
    withdrawn: st(ev({ lifecycle: 'withdrawn', outcome_raw: 'Withdrawn' }), null).label,
    cancelled: st(ev({ lifecycle: 'cancelled', outcome_raw: 'Canceled per County' }), null).label,
    redeemed: st(ev({ outcome: 'redeemed', lifecycle: 'cancelled', outcome_raw: 'Redeemed' }), null).label,
    // a cancelled lifecycle WITHOUT the source's wording is not verified
    cancelledNoWording: st(ev({ lifecycle: 'cancelled' }), null).label,
    notPublished: st(ev({}), closed(null, 'unknown', 'completed')).label,
    notVerified: st(ev({}), null).label,
    unreviewedWording: st(ev({}), closed('Canceled per Bankruptcy', 'unknown', 'completed')),
    passedDateOnly: st(ev({ lifecycle: 'completed' }), null).verified,
    scheduled: st(ev({ scheduled_sale_date: '2999-01-01', lifecycle: 'scheduled' }), null).label
  };
});
results.outcomeRelation = await outPage.evaluate(() => {
  const O = window.__tdwOutcome;
  const auc = { id: 'a1', source: 'auction', state: 'FL', county: 'Jackson', parcel: '21-4N', case_no: '2024 TD 0001', sale_date: '2026-09-29' };
  const laft = { id: 'l1', source: 'laft', state: 'FL', county: 'Jackson', parcel: '21-4N', case_no: 'L-9', status: 'available' };
  const unsold = () => ({ key: 'struck_off', verified: true, raw: 'Struck Off' });
  const unknown = () => ({ key: 'outcome_not_verified', verified: false });
  return {
    both: O.relation(auc, [laft], unsold),
    auctionOnly: O.relation(auc, [], unsold),
    availableOnly: O.relation(auc, [laft], unknown),
    fromAvailable: O.relation(laft, [auc], p => p.source === 'auction' ? unsold() : null),
    availableNoAuctionResult: O.relation(laft, [auc], () => unknown())
  };
});
const aucOutDl = outPage.waitForEvent('download');
await outPage.goto(BASE_URL + '#/auctions', { waitUntil: 'networkidle' });
await outPage.waitForTimeout(400);
await outPage.click('#exportCsvBtn');
{
  const text = fs.readFileSync(await (await aucOutDl).path(), 'utf8');
  const header = text.split(/\r?\n/)[0].split(',');
  results.aucExportOutcomeCols = ['Auction Outcome', 'Outcome Source Wording', 'Outcome Observed', 'Outcome Evidence URL', 'Published Sale Amount'].every(c => header.includes(c));
  results.aucExportNoGovernance = !header.some(h => /publication|provenance|harvester|governance|bidder|purchaser|winning_bidder/i.test(h));
  results.aucExportNeverSoldWithoutEvidence = !/Sold - verified/.test(text);
}
await outPage.close();

// The three new Available filters (land use, coordinates on file, county
// value on file) - each on a stored field; reset clears them.
const filtPage = await newPage({ viewport: { width: 1200, height: 900 } });
await filtPage.goto(BASE_URL + '#/lands', { waitUntil: 'networkidle' });
await filtPage.waitForTimeout(500);
if ((await filtPage.locator('#expandAllBtn').textContent()) === 'Expand all') { await filtPage.click('#expandAllBtn'); await filtPage.waitForTimeout(150); }
if (!(await filtPage.locator('#filtersPanel').evaluate(el => el.classList.contains('open')))) { await filtPage.click('#filtersToggle'); await filtPage.waitForTimeout(250); }
const filtCards = () => filtPage.locator('#main .prop-card');
results.availLandUseOptions = await filtPage.locator('#availLandUseFilter option').allTextContents();
await filtPage.selectOption('#availLandUseFilter', 'Vacant residential'); await filtPage.waitForTimeout(200);
results.availAfterLandUse = await filtCards().count();
await filtPage.selectOption('#availLandUseFilter', 'any'); await filtPage.waitForTimeout(200);
await filtPage.check('#availGeocoded'); await filtPage.waitForTimeout(200);
results.availAfterGeocoded = await filtCards().count();
results.availGeocodedCardAddress = ((await filtCards().first().locator('.prop-address, .detail-address, h3').first().textContent()) || '').trim();
await filtPage.uncheck('#availGeocoded'); await filtPage.waitForTimeout(200);
await filtPage.check('#availValues'); await filtPage.waitForTimeout(200);
results.availAfterValues = await filtCards().count();
await filtPage.click('#resetBtn'); await filtPage.waitForTimeout(250);
results.availAfterResetAll = await filtCards().count();
results.availResetClearsNew = (await filtPage.locator('#availGeocoded').isChecked()) === false && (await filtPage.locator('#availValues').isChecked()) === false && (await filtPage.inputValue('#availLandUseFilter')) === 'any';
// The Available export: published fields only, no governance / provenance
// internals, the withheld row (p14) absent, the typed path present.
const availDl = filtPage.waitForEvent('download');
await filtPage.click('#exportCsvBtn');
const availCsv = await availDl;
results.availCsvFilename = availCsv.suggestedFilename();
{
  const text = fs.readFileSync(await availCsv.path(), 'utf8');
  const lines = text.split(/\r?\n/).filter(Boolean);
  const header = lines[0].split(',');
  results.availCsvHeaderHas = ['Purchase Path', 'Purchase Path Scope', 'Purchase Link', 'Availability Status', 'Latitude', 'Last Read From Source', 'Acquisition Path', 'Acquisition Steps (published by the source)', 'County Office', 'County Phone', 'County E-mail', 'County Address (in person)', 'County Mailing Address', 'Application / Instructions Document', 'Matched To Source By'].every(h => header.includes(h));
  results.availCsvHeaderLacks = ['publication_status', 'Publication Status', 'Provenance', 'Basis', 'harvester_source', 'Data Source'].every(h => !header.some(c => c.toLowerCase().includes(h.toLowerCase())));
  results.availCsvRowCount = lines.length - 1;
  results.availCsvNoWithheld = !text.includes('Restricted Rd');
  const p15Line = lines.find(l => l.includes('15 Manatee Ln')) || '';
  results.availCsvP15Path = p15Line.includes('County purchase-instructions page (published by the source)') && p15Line.includes('https://www.citrusclerk.example.gov/lands-available/how-to-purchase');
  results.availCsvP15Acquisition = p15Line.includes('Multi-step county process') && p15Line.includes('taxdeeds@example.gov') && p15Line.includes('case_no CI-7') && p15Line.includes('application.pdf');
}
await filtPage.close();

// The Map preview for an Available row leads with availability, then the
// purchase path, then freshness (last verified / source date).
// (bayPreviewText above already covers the Bay row; this checks the labels.)

// Admin publication governance panel: admins only; lists the state's
// registry sources with status / restrictions / latest decision; the form
// refuses RESTRICTED without a reason and an approval without evidence,
// then records an append-only review row.
// (2026-09-30: the panel lives in its own admin-only view - account menu
// "Source Publication Governance" or #/governance - never inline on the main
// workspace. The checks below open it the way an admin does, then exercise
// the unchanged panel.)
const adminPub = await newPage({ viewport: { width: 1200, height: 900 } });
await adminPub.goto(BASE_URL + '?profile=admin' + '#/auctions', { waitUntil: 'networkidle' });
await adminPub.waitForTimeout(900);
results.govWorkspace = {
  inlinePanelVisible: await adminPub.locator('#adminPublication').isVisible(),
  panelInsideView: await adminPub.evaluate(() => !!document.querySelector('#governanceModal #adminPublication')),
  panelOnWorkspace: await adminPub.evaluate(() => !!document.querySelector('#app > #adminPublication, main #adminPublication, .page #adminPublication')),
  approvalsVisible: await adminPub.locator('#adminApprovals').isVisible(),
  approvalRows: (await adminPub.locator('#adminApprovalsList > *').count()) > 0
};
await adminPub.click('#accountBtn'); await adminPub.waitForTimeout(200);
results.govMenu = {
  itemVisible: await adminPub.locator('#governanceMenuItem').isVisible(),
  itemText: ((await adminPub.locator('#governanceMenuItem').textContent()) || '').trim(),
  // the item sits in the existing account menu, after "Admin area", before Terms / Sign out
  order: await adminPub.locator('#accountMenu .account-item:not([hidden])').evaluateAll(els => els.map(e => e.id).filter(Boolean))
};
await adminPub.click('#governanceMenuItem'); await adminPub.waitForTimeout(700);
results.govOpened = {
  viewVisible: await adminPub.locator('#governanceModal').isVisible(),
  hash: await adminPub.evaluate(() => location.hash),
  menuClosed: await adminPub.locator('#accountMenu').isHidden(),
  title: ((await adminPub.locator('#governanceTitle').textContent()) || '').trim()
};
results.adminPubVisible = await adminPub.locator('#adminPublication').isVisible();
results.adminPubSources = await adminPub.locator('#adminPublicationList .admin-pub-row').evaluateAll(els => els.map(e => e.dataset.source + ':' + e.querySelector('.admin-pub-status').textContent.trim()));
results.adminPubBrowardMeta = ((await adminPub.locator('#adminPublicationList .admin-pub-row[data-source="fl_laft_broward_candidate"] .admin-pub-meta').textContent()) || '').replace(/\s+/g, ' ').trim();
results.adminPubPioneerReview = ((await adminPub.locator('#adminPublicationList .admin-pub-row[data-source="fl_laft_pioneer"] .admin-pub-review').innerText()) || '').replace(/\s+/g, ' ').trim();
const pdfForm = adminPub.locator('#adminPublicationList .admin-pub-form[data-source="fl_laft_pdfs"]');
await pdfForm.locator('select[name="publication_status"]').selectOption('RESTRICTED');
await pdfForm.locator('input[name="restrictions"]').fill('');
await pdfForm.locator('button[type="submit"]').click(); await adminPub.waitForTimeout(150);
results.adminPubRefusesRestrictedWithoutReason = ((await pdfForm.locator('.admin-pub-msg').textContent()) || '').trim();
results.adminPubInsertsAfterRefusal = await adminPub.evaluate(() => (window.__stubReviewInserts || []).length);
await pdfForm.locator('input[name="restrictions"]').fill('vendor terms forbid redistribution - under review');
await pdfForm.locator('input[name="decision_note"]').fill('pending counsel');
await pdfForm.locator('input[name="next_review"]').fill('2026-12-01');
await pdfForm.locator('button[type="submit"]').click(); await adminPub.waitForTimeout(400);
results.adminPubInserted = await adminPub.evaluate(() => (window.__stubReviewInserts || []).map(r => [r.state, r.source_id, r.publication_status, r.restrictions, r.decision_note, r.next_review, r.evidence]));
results.adminPubPdfsReviewAfter = ((await adminPub.locator('#adminPublicationList .admin-pub-row[data-source="fl_laft_pdfs"] .admin-pub-review').innerText()) || '').replace(/\s+/g, ' ').trim();
const htmlForm = adminPub.locator('#adminPublicationList .admin-pub-form[data-source="fl_laft_html"]');
await htmlForm.locator('select[name="publication_status"]').selectOption('APPROVED');
await htmlForm.locator('button[type="submit"]').click(); await adminPub.waitForTimeout(150);
results.adminPubRefusesApprovalWithoutEvidence = ((await htmlForm.locator('.admin-pub-msg').textContent()) || '').trim();
// Back closes the view (its own history layer) and returns to the workspace.
await adminPub.goBack(); await adminPub.waitForTimeout(400);
results.govClosedByBack = { hidden: await adminPub.locator('#governanceModal').isHidden(), hash: await adminPub.evaluate(() => location.hash) };
await adminPub.close();
// An admin can open the view straight from its route (cold start).
const govRoute = await newPage({ viewport: { width: 1200, height: 900 } });
await govRoute.goto(BASE_URL + '?profile=admin#/governance', { waitUntil: 'networkidle' });
await govRoute.waitForTimeout(900);
results.govAdminRoute = { visible: await govRoute.locator('#governanceModal').isVisible(), rows: await govRoute.locator('#adminPublicationList .admin-pub-row').count(), hash: await govRoute.evaluate(() => location.hash) };
await govRoute.close();
// Phone width: the account menu entry and the view both fit at 360px.
const govPhone = await newPage({ viewport: { width: 360, height: 780 } });
await govPhone.goto(BASE_URL + '?profile=admin' + '#/auctions', { waitUntil: 'networkidle' });
await govPhone.waitForTimeout(900);
await govPhone.click('#accountBtn'); await govPhone.waitForTimeout(200);
const phoneItem = await govPhone.locator('#governanceMenuItem').isVisible();
await govPhone.click('#governanceMenuItem'); await govPhone.waitForTimeout(700);
results.govPhone = {
  itemVisible: phoneItem,
  viewVisible: await govPhone.locator('#governanceModal').isVisible(),
  noHorizontalScroll: await govPhone.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
  formFits: await govPhone.evaluate(() => { const f = document.querySelector('#adminPublicationList .admin-pub-form'); return !!f && f.getBoundingClientRect().right <= window.innerWidth + 1; })
};
await govPhone.close();
// A non-admin never sees the panel; a deployment without the reviews table
// disables the form but still shows the registry state.
const nonAdmin = await newPage({ viewport: { width: 1200, height: 900 } });
await nonAdmin.goto(BASE_URL + '#/auctions', { waitUntil: 'networkidle' });
await nonAdmin.waitForTimeout(700);
results.adminPubHiddenForCustomer = await nonAdmin.locator('#adminPublication').isHidden();
await nonAdmin.click('#accountBtn'); await nonAdmin.waitForTimeout(200);
results.govCustomerMenu = { itemVisible: await nonAdmin.locator('#governanceMenuItem').isVisible(), accountMenuOpen: await nonAdmin.locator('#accountMenu').isVisible() };
await nonAdmin.keyboard.press('Escape'); await nonAdmin.waitForTimeout(200);
// Typing the route into an open app: refused - view stays closed, hash rewritten, nothing fetched.
await nonAdmin.evaluate(() => { location.hash = '#/governance'; }); await nonAdmin.waitForTimeout(500);
results.govCustomerTypedRoute = { viewHidden: await nonAdmin.locator('#governanceModal').isHidden(), hash: await nonAdmin.evaluate(() => location.hash), rows: await nonAdmin.locator('#adminPublicationList .admin-pub-row').count() };
await nonAdmin.close();
// Cold start at the route as a normal user: refused the same way.
const custRoute = await newPage({ viewport: { width: 1200, height: 900 } });
await custRoute.goto(BASE_URL + '#/governance', { waitUntil: 'networkidle' });
await custRoute.waitForTimeout(900);
results.govCustomerColdRoute = { viewHidden: await custRoute.locator('#governanceModal').isHidden(), hash: await custRoute.evaluate(() => location.hash), rows: await custRoute.locator('#adminPublicationList .admin-pub-row').count(), menuItemHidden: await custRoute.locator('#governanceMenuItem').isHidden() };
await custRoute.close();
const noReviews = await newPage({ viewport: { width: 1200, height: 900 } });
await noReviews.goto(BASE_URL + '?profile=admin&reviews=none#/governance', { waitUntil: 'networkidle' });
await noReviews.waitForTimeout(900);
results.adminPubNoTableReviewText = ((await noReviews.locator('#adminPublicationList .admin-pub-row[data-source="fl_laft_pdfs"] .admin-pub-review').innerText()) || '').replace(/\s+/g, ' ').trim();
results.adminPubNoTableFormDisabled = await noReviews.locator('#adminPublicationList .admin-pub-form[data-source="fl_laft_pdfs"] button[type="submit"]').isDisabled();
await noReviews.close();


// Every generated state page (scripts/build_state_page.py) carries the same
// governance navigation: admin menu entry + #/governance view; refused for a
// normal user; never inline on the workspace.
results.govStatePages = {};
for (const file of ['mi', 'wy', 'sc', 'co', 'wi']) {
  const url = BASE_URL.replace(/index\.html$/, `${file}.html`);
  const adm = await newPage({ viewport: { width: 1200, height: 900 } });
  await adm.goto(url + '?profile=admin#/governance', { waitUntil: 'networkidle' });
  await adm.waitForTimeout(800);
  const admView = await adm.locator('#governanceModal').isVisible();
  const admHash = await adm.evaluate(() => location.hash);
  const onWorkspace = await adm.evaluate(() => !document.querySelector('#governanceModal #adminPublication'));
  await adm.close();
  const usr = await newPage({ viewport: { width: 1200, height: 900 } });
  await usr.goto(url + '#/governance', { waitUntil: 'networkidle' });
  await usr.waitForTimeout(800);
  results.govStatePages[file] = { admView, admHash, onWorkspace,
    userView: await usr.locator('#governanceModal').isVisible(), userItem: await usr.locator('#governanceMenuItem').isVisible(),
    userHashRewritten: (await usr.evaluate(() => location.hash)) !== '#/governance' };
  await usr.close();
}

// ==================== Unified navigation (2026-09-30) ====================
// Routes, the Map page's state / ledger / county context, the scoped county
// select, the operating Dashboard, and the compatibility of every existing
// hash. Each cold start is its own newPage() (see the Phase 58 note above).
const navMap = await newPage({ viewport: { width: 1200, height: 900 } });
await navMap.goto(BASE_URL + '#/map?ledger=laft&county=Bay', { waitUntil: 'networkidle' });
await navMap.waitForTimeout(600);
results.navMapDeepVisible = await navMap.locator('#pageMap').evaluate(el => !el.hidden);
results.navMapDeepLit = await navMap.locator('.nav-list .nav-item.on').evaluateAll(els => els.map(e => e.dataset.page));
results.navMapDeepLaftPill = await navMap.locator('#mapLedgerPills [data-ledger="laft"]').evaluate(el => el.classList.contains('on'));
results.navMapDeepCounty = await navMap.locator('#mapCountySelect').inputValue();
results.navMapDeepContext = ((await navMap.locator('#mapContext').textContent()) || '').replace(/\s+/g, ' ').trim();
results.navMapDeepHash = await navMap.evaluate(() => location.hash);
results.navMapStateOptions = await navMap.locator('#stateSelect option').evaluateAll(els => els.map(e => e.value + ':' + e.textContent));
results.navMapStateValue = await navMap.locator('#stateSelect').inputValue();
results.navMapHasNoOwnStateSelect = (await navMap.locator('#pageMap select[aria-label="State"], #mapStateSelect').count()) === 0;
results.navMapAllLedgersLabel = ((await navMap.locator('#mapLedgerPills [data-ledger="all"]').textContent()) || '').trim();
results.navMapCertPillLabel = ((await navMap.locator('#mapLedgerPills [data-ledger="certificate"]').textContent()) || '').trim();
// The county select lists only counties with inventory in the selected
// ledger, with that ledger's count - and a county that has none in the
// newly chosen ledger falls back to All Counties.
results.navMapLaftCountyOptions = await navMap.locator('#mapCountySelect option').evaluateAll(els => els.map(e => e.textContent));
await navMap.click('#mapLedgerPills [data-ledger="certificate"]');
await navMap.waitForTimeout(300);
results.navMapCertCountyOptions = await navMap.locator('#mapCountySelect option').evaluateAll(els => els.map(e => e.textContent));
results.navMapCertCountyValue = await navMap.locator('#mapCountySelect').inputValue();
results.navMapCertContext = ((await navMap.locator('#mapContext').textContent()) || '').replace(/\s+/g, ' ').trim();
results.navMapCertHash = await navMap.evaluate(() => location.hash);
results.navMapCertBubbleCount = await navMap.locator('#exploreMapCanvas .cluster-bubble').count();
await navMap.click('#mapLedgerPills [data-ledger="all"]');
await navMap.waitForTimeout(300);
results.navMapAllCountyOptions = await navMap.locator('#mapCountySelect option').evaluateAll(els => els.map(e => e.textContent));
results.navMapAllHash = await navMap.evaluate(() => location.hash);
await navMap.fill('#mapSearchInput', 'Oak');
await navMap.waitForTimeout(300);
results.navMapSearchHash = await navMap.evaluate(() => location.hash);
// The ledger picked on the Map page does not leak into the List page's
// own ledger and back.
await navMap.click('.nav-list .nav-item[data-page="list"]');
await navMap.waitForTimeout(300);
results.navMapToListHash = await navMap.evaluate(() => location.hash);
results.navMapToListLit = await navMap.locator('.nav-list .nav-item.on').evaluateAll(els => els.map(e => e.dataset.page));
await navMap.click('.nav-list .nav-item[data-page="map"]');
await navMap.waitForTimeout(300);
results.navListToMapHashKeepsContext = await navMap.evaluate(() => location.hash);
await navMap.close();

// ============================================================
// Admin area (/admin, 2026-09-30). ?stubauth=1 switches the stub to its
// stand-in for Supabase Auth + row-level security (a server-held user table,
// a password check, a session, own-row profile reads - see the stub). The
// passwords typed here are the stub's FIXTURE passwords for fake accounts.
// admin.html decides only from the server's answer; the shell is hidden
// until then, and anyone else is sent to the normal application.
// ============================================================
{
  const ADMIN_URL = BASE_URL.replace(/index\.html$/, 'admin.html') + '?stubauth=1';
  const APP_URL = BASE_URL + '?stubauth=1';
  const signIn = async (pg, email, password) => {
    await pg.goto(APP_URL + '#/auctions', { waitUntil: 'networkidle' });
    await pg.fill('#email', email);
    await pg.fill('#password', password);
    await pg.click('#signInBtn');
    await pg.waitForTimeout(600);
  };
  const onAdminShell = async pg => pg.evaluate(() => /admin\.html/.test(location.pathname) && !document.getElementById('adminShell').hidden);
  const openAdmin = async pg => { await pg.goto(ADMIN_URL, { waitUntil: 'networkidle' }); await pg.waitForTimeout(600); };

  // No session at all: /admin sends you to the normal sign-in flow.
  const anon = await newPage({ viewport: { width: 1000, height: 800 } });
  await openAdmin(anon);
  results.adminAnonRedirected = await anon.evaluate(() => /index\.html$/.test(location.pathname));
  results.adminAnonShellShown = (await anon.locator('#adminShell').count()) > 0 && await anon.locator('#adminShell').isVisible();
  await anon.close();

  // 1. A normal user signs in normally and sees the normal application.
  const normal = await newPage({ viewport: { width: 1000, height: 800 } });
  await signIn(normal, 'normal@example.com', 'fixture-normal-pass');
  results.adminNormalAppVisible = await normal.locator('#app').isVisible();
  results.adminNormalMenuLinkHidden = await normal.locator('#adminAreaLink').isHidden();
  // 3. ... and cannot open /admin by typing it.
  await openAdmin(normal);
  results.adminNormalRedirected = await normal.evaluate(() => /index\.html$/.test(location.pathname));
  // 7. Client state cannot grant admin: every flag a page could set is ignored.
  await normal.goto(APP_URL + '#/auctions', { waitUntil: 'networkidle' });
  await normal.evaluate(() => {
    for (const store of [localStorage, sessionStorage]) {
      store.setItem('is_admin', 'true'); store.setItem('IS_ADMIN', 'true'); store.setItem('role', 'admin'); store.setItem('tdw-admin', '1');
    }
    window.IS_ADMIN = true;
  });
  await openAdmin(normal);
  results.adminTamperRedirected = await normal.evaluate(() => /index\.html$/.test(location.pathname));
  results.adminTamperShellShown = await onAdminShell(normal);
  await normal.close();

  // 9. Wrong admin credentials are rejected: an error, no session, no admin area.
  const bad = await newPage({ viewport: { width: 1000, height: 800 } });
  await signIn(bad, 'admin@example.com', 'not-the-password');
  results.adminBadCredsError = ((await bad.locator('#authMsg').textContent()) || '').trim().length > 0;
  results.adminBadCredsAppHidden = await bad.locator('#app').isHidden();
  await openAdmin(bad);
  results.adminBadCredsRedirected = await bad.evaluate(() => /index\.html$/.test(location.pathname));
  await bad.close();

  // 4-5. The admin signs in, sees the Admin link, and opens /admin.
  const adm = await newPage({ viewport: { width: 1000, height: 800 } });
  await signIn(adm, 'admin@example.com', 'fixture-admin-pass');
  results.adminAppVisible = await adm.locator('#app').isVisible();
  results.adminMenuLinkShown = await adm.locator('#adminAreaLink').isVisible() || !(await adm.locator('#adminAreaLink').evaluate(el => el.hidden));
  await openAdmin(adm);
  results.adminShellShown = await onAdminShell(adm);
  results.adminIdentityText = ((await adm.locator('#adminIdentity').textContent()) || '').trim();
  results.adminShellShowsNoEmail = !/@/.test((await adm.locator('#adminShell').textContent()) || '');
  // Admin source panel (all-sources enrichment engine): the unified inventory
  // with the three governance states kept apart, filterable by state / type.
  await adm.waitForSelector('#adminSourcesList tr[data-source]', { timeout: 5000 }).catch(() => {});
  results.adminSourcesRows = await adm.locator('#adminSourcesList tr[data-source]').count();
  results.adminSourcesGovernanceKinds = await adm.evaluate(() => [...new Set([...document.querySelectorAll('#adminSourcesList tr[data-governance]')].map(r => r.dataset.governance))].sort().join(','));
  results.adminSourcesStatusText = ((await adm.locator('#adminSourcesStatus').textContent()) || '').trim();
  await adm.selectOption('#adminSourcesGov', 'REVIEW_REQUIRED');
  results.adminSourcesReviewOnly = await adm.evaluate(() => [...document.querySelectorAll('#adminSourcesList tr[data-governance]')].every(r => r.dataset.governance === 'REVIEW_REQUIRED'));
  results.adminSourcesLgbsReason = await adm.evaluate(() => { const r = document.querySelector('#adminSourcesList tr[data-source="tx_lgbs_statewide_api"]'); return !!r && /lgbs-rights-audit/.test(r.textContent); });
  await adm.selectOption('#adminSourcesGov', '');
  await adm.selectOption('#adminSourcesState', 'LA');
  results.adminSourcesLaOnly = await adm.evaluate(() => { const rows = [...document.querySelectorAll('#adminSourcesList tr[data-source]')]; return rows.length > 0 && rows.every(r => r.firstElementChild.textContent === 'LA'); });
  await adm.selectOption('#adminSourcesState', '');
  await adm.selectOption('#adminSourcesType', 'PUBLIC_NOTICE');
  results.adminSourcesNoticeRows = await adm.locator('#adminSourcesList tr[data-source]').count();
  await adm.selectOption('#adminSourcesType', '');
  // 8. Signing out removes admin access: redirected now, and on a revisit.
  await adm.click('#adminSignOut');
  await adm.waitForTimeout(600);
  results.adminSignOutRedirected = await adm.evaluate(() => /index\.html$/.test(location.pathname));
  await openAdmin(adm);
  results.adminAfterSignOutRedirected = await adm.evaluate(() => /index\.html$/.test(location.pathname));
  await adm.close();
}

// ============================================================
// Public sign-up with mandatory admin approval (2026-09-30). One browser
// context = one "server": a sign-up in one tab is seen by the admin in
// another (the stub keeps its user table as the server's database - see
// the stub). Lifecycle A-E.
// ============================================================
{
  const ctx = await browser.newContext({ viewport: { width: 1000, height: 800 } });
  const APP_URL = BASE_URL + '?stubauth=1';
  const ADMIN_URL = BASE_URL.replace(/index\.html$/, 'admin.html') + '?stubauth=1';
  const openAdmin = async pg => { await pg.goto(ADMIN_URL, { waitUntil: 'networkidle' }); await pg.waitForTimeout(600); };
  const onAdminShell = async pg => pg.evaluate(() => /admin\.html/.test(location.pathname) && !document.getElementById('adminShell').hidden);
  const fillSignUp = async (pg, email, password) => {
    await pg.click('#authModeToggle');
    await pg.fill('#firstName', 'Pat'); await pg.fill('#lastName', 'Example'); await pg.fill('#company', 'Independent');
    await pg.fill('#address', '1 Main St'); await pg.fill('#phone', '555-0100');
    await pg.fill('#email', email); await pg.fill('#password', password); await pg.fill('#passwordConfirm', password);
    await pg.click('#signInBtn');
    await pg.waitForTimeout(700);
  };
  const signIn = async (pg, email, password) => {
    await pg.goto(APP_URL + '#/auctions', { waitUntil: 'networkidle' });
    await pg.fill('#email', email); await pg.fill('#password', password);
    await pg.click('#signInBtn'); await pg.waitForTimeout(700);
  };

  // A. Anonymous visitor: the sign-up form is offered; /admin is refused.
  const visitor = await ctx.newPage();
  await visitor.goto(APP_URL + '#/auctions', { waitUntil: 'networkidle' });
  await visitor.click('#authModeToggle');
  results.signupFormOffered = await visitor.locator('#passwordConfirm').isVisible() && await visitor.locator('#firstName').isVisible();
  results.signupButtonText = ((await visitor.locator('#signInBtn').textContent()) || '').trim();
  await openAdmin(visitor);
  results.signupAnonAdminRedirected = await visitor.evaluate(() => /index\.html$/.test(location.pathname));

  // B. A new user signs up: account created, profile pending (not admin),
  // the pending screen instead of the app, and /admin refused.
  await visitor.goto(APP_URL + '#/auctions', { waitUntil: 'networkidle' });
  await fillSignUp(visitor, 'newcomer@example.com', 'fixture-newcomer-pass');
  results.signupPendingShown = await visitor.locator('#pendingGate').isVisible();
  results.signupPendingText = ((await visitor.locator('#pendingGate .auth-lead').textContent()) || '').trim();
  results.signupAppHidden = await visitor.locator('#app').isHidden();
  results.signupAuthMsgNotSignupsDisabled = !/signups? not allowed/i.test((await visitor.locator('#authMsg').textContent()) || '');
  results.signupProfile = await visitor.evaluate(async () => {
    const { createClient } = await import('https://esm.sh/@supabase/supabase-js@2');
    const { data } = await createClient().from('profiles').select('approved,is_admin').maybeSingle();
    return data && { approved: data.approved, is_admin: data.is_admin };
  });
  results.signupNoLedgerRowsRendered = (await visitor.locator('#main .prop-card').count()) === 0;
  await openAdmin(visitor);
  results.signupPendingAdminRedirected = await visitor.evaluate(() => /index\.html$/.test(location.pathname));

  // E. Security: tampering grants nothing. The pending user tries to make
  // itself admin / approved through the API, and to approve itself with
  // is_admin smuggled in sign-up metadata - the server (RLS) changes nothing.
  await visitor.goto(APP_URL + '#/auctions', { waitUntil: 'networkidle' });
  results.signupSelfPromote = await visitor.evaluate(async () => {
    const { createClient } = await import('https://esm.sh/@supabase/supabase-js@2');
    const c = createClient();
    const { data: sess } = await c.auth.getSession();
    const id = sess.session.user.id;
    await c.from('profiles').update({ is_admin: true, approved: true }).eq('id', id);
    const { data } = await c.from('profiles').select('approved,is_admin').eq('id', id).maybeSingle();
    return { rowsChanged: (window.__stubProfileUpdates || []).slice(-1)[0].rows, after: data && { approved: data.approved, is_admin: data.is_admin } };
  });
  results.signupPendingSeesOnlyOwnRow = await visitor.evaluate(async () => {
    const { createClient } = await import('https://esm.sh/@supabase/supabase-js@2');
    const { data } = await createClient().from('profiles').select('id,email').eq('approved', false);
    return (data || []).map(r => r.email);
  });
  await visitor.evaluate(() => {
    for (const store of [localStorage, sessionStorage]) { store.setItem('is_admin', 'true'); store.setItem('approved', 'true'); store.setItem('role', 'admin'); }
    window.IS_ADMIN = true;
  });
  await visitor.goto(APP_URL + '&approved=1&admin=1' + '#/auctions', { waitUntil: 'networkidle' });
  await visitor.waitForTimeout(600);
  results.signupTamperStillPending = await visitor.locator('#pendingGate').isVisible() && await visitor.locator('#app').isHidden();
  await openAdmin(visitor);
  results.signupTamperAdminRedirected = await visitor.evaluate(() => /index\.html$/.test(location.pathname));
  const sneaky = await ctx.newPage();
  await sneaky.goto(APP_URL + '#/auctions', { waitUntil: 'networkidle' });
  results.signupMetadataIgnored = await sneaky.evaluate(async ([email, password]) => {
    const { createClient } = await import('https://esm.sh/@supabase/supabase-js@2');
    const c = createClient();
    await c.auth.signUp({ email, password, options: { data: { is_admin: true, approved: true } } });
    const { data } = await c.from('profiles').select('approved,is_admin').maybeSingle();
    return data && { approved: data.approved, is_admin: data.is_admin };
  }, ['sneaky@example.com', 'fixture-sneaky-pass']);
  await sneaky.close();

  // C. The admin signs in, is recognised from the server-read profile,
  // opens /admin, sees the pending accounts and approves one.
  const admin = await ctx.newPage();
  await signIn(admin, 'admin@example.com', 'fixture-admin-pass');
  results.signupAdminAppVisible = await admin.locator('#app').isVisible();
  await openAdmin(admin);
  results.signupAdminShellShown = await onAdminShell(admin);
  results.signupAdminIdentityNoEmail = !/@/.test((await admin.locator('#adminIdentity').textContent()) || '');
  results.signupAdminPendingList = await admin.locator('#adminPendingList .admin-approval-row').evaluateAll(els => els.map(e => e.querySelector('.admin-approval-name').textContent.trim()));
  results.signupAdminPendingStatus = ((await admin.locator('#adminPendingStatus').textContent()) || '').trim();
  const row = admin.locator('#adminPendingList .admin-approval-row', { hasText: 'newcomer@example.com' });
  await row.locator('.admin-approve-btn').click();
  await admin.waitForTimeout(500);
  results.signupAdminPendingAfterApprove = await admin.locator('#adminPendingList .admin-approval-row').evaluateAll(els => els.map(e => e.querySelector('.admin-approval-name').textContent.trim()));
  results.signupAdminApproveRowsChanged = await admin.evaluate(() => (window.__stubProfileUpdates || []).slice(-1)[0].rows);

  // D. The approved user signs in and uses the app; /admin is still refused.
  const member = await ctx.newPage();
  await signIn(member, 'newcomer@example.com', 'fixture-newcomer-pass');
  results.signupApprovedAppVisible = await member.locator('#app').isVisible();
  results.signupApprovedPendingHidden = await member.locator('#pendingGate').isHidden();
  results.signupApprovedLedgerRows = (await member.locator('#main .prop-card').count()) > 0;
  results.signupApprovedAdminLinkHidden = await member.locator('#adminAreaLink').evaluate(el => el.hidden);
  results.signupApprovedProfile = await member.evaluate(async () => {
    const { createClient } = await import('https://esm.sh/@supabase/supabase-js@2');
    const { data } = await createClient().from('profiles').select('approved,is_admin').maybeSingle();
    return data && { approved: data.approved, is_admin: data.is_admin };
  });
  await openAdmin(member);
  results.signupApprovedAdminRedirected = await member.evaluate(() => /index\.html$/.test(location.pathname));
  results.signupApprovedAdminShellShown = await onAdminShell(member);
  await ctx.close();

  // "Signups not allowed for this instance": the visitor gets a clear
  // message, not Supabase's raw wording, and no account or session.
  const closed = await newPage({ viewport: { width: 1000, height: 800 } });
  await closed.goto(APP_URL + '&signupdisabled=1' + '#/auctions', { waitUntil: 'networkidle' });
  await fillSignUp(closed, 'late@example.com', 'fixture-late-pass');
  results.signupDisabledMsg = ((await closed.locator('#authMsg').textContent()) || '').trim();
  results.signupDisabledNoSession = await closed.locator('#app').isHidden() && await closed.locator('#pendingGate').isHidden();
  await closed.close();
}

// ============================================================
// Louisiana (2026-09-30, state-expansion sprint): la.html is a third state
// page. Its one source is East Baton Rouge's DATED adjudicated-property list:
// the Available card and page say "list as of" the Parish's own date and
// never "available now"; the unit is a parish; no price, no purchase path.
// ============================================================
{
  const laPage = await newPage({ viewport: { width: 1200, height: 900 } });
  const LA_BASE_URL = BASE_URL.replace(/index\.html$/, 'la.html');
  await laPage.goto(LA_BASE_URL + '#/lands', { waitUntil: 'networkidle' });
  await laPage.waitForTimeout(500);
  if (await laPage.locator('#expandAllBtn').isVisible() && (await laPage.locator('#expandAllBtn').textContent()) === 'Expand all') {
    await laPage.click('#expandAllBtn');
    await laPage.waitForTimeout(200);
  }
  results.laBodyState = await laPage.evaluate(() => document.body.dataset.state);
  results.laTitle = await laPage.title();
  results.laStateSelect = { value: await laPage.locator('#stateSelect').inputValue(), options: await laPage.locator('#stateSelect option').evaluateAll(els => els.map(e => e.value)) };
  results.laNoStateTabs = (await laPage.locator('#regionTabs, #mapStateSelect').count()) === 0;
  const laCard = laPage.locator('.prop-card[data-pid="pla1"]');
  results.laCardCount = await laCard.count();
  const laCardText = ((await laCard.textContent()) || '').replace(/\s+/g, ' ');
  results.laCardSaysListAsOf = /list as of Feb 27, 2024/.test(laCardText);
  results.laCardSaysAvailableNow = /available now/i.test(laCardText.replace(/not verified available now/ig, ''));
  results.laCardSaysParish = /Location in East Baton Rouge Parish/.test(laCardText) && /East Baton Rouge, LA/.test(laCardText);
  results.laCardValueLabel = /2023 Fair Market Value \(tax roll\)/.test(laCardText) && !/Just Value/.test(laCardText);
  results.laCardNoUndefined = !/undefined/.test(laCardText);
  results.laCardSaysCounty = /East Baton Rouge County/.test(laCardText);
  await laCard.locator('.detail-btn').click();
  await laPage.waitForTimeout(300);
  const laDetail = ((await laPage.locator('#detailModalInner').textContent()) || '').replace(/\s+/g, ' ');
  results.laDetailNotVerifiedAvailable = /Not verified as available now - on the Parish's adjudicated-property list as of Feb 27, 2024/.test(laDetail);
  results.laDetailInventoryLabel = /Adjudicated to the parish after no one bought it at the tax sale \(Louisiana\)/.test(laDetail);
  results.laDetailCostNotPublished = /Not published by the source/.test(laDetail);
  results.laDetailNoFixedPrice = !/fixed price/i.test(laDetail);
  await laPage.close();
  // Property-enrichment sprint: the Parish Attorney's process and the assessor's land value,
  // each named with its source; the list stays dated.
  const la2 = await newPage({ viewport: { width: 1200, height: 900 } });
  await la2.goto(BASE_URL.replace(/index\.html$/, 'la.html') + '#/lands/pla2', { waitUntil: 'networkidle' });
  await la2.waitForTimeout(600);
  const la2d = ((await la2.locator('#detailModalInner').textContent()) || '').replace(/\s+/g, ' ');
  const landProv = ((await la2.locator('#detailModalInner .provenance-card .prov-row[data-field="land_value"]').textContent().catch(() => '')) || '').replace(/\s+/g, ' ');
  results.laEnriched = {
    office: /Office of the Parish Attorney/.test(la2d),
    confirmFirst: /remains adjudicated/.test(la2d),
    noVendor: !/CivicSource/i.test(la2d),
    stillDated: /Not verified as available now/.test(la2d),
    landSource: /Government parcel \/ tax-roll record - Tax Parcel \(data\.brla\.gov ei2c-krsr\)/.test(landProv),
    landMethod: /attached by an exact identifier match \(parcel # = assessment_num\)/.test(landProv),
    noUndefined: !/undefined/.test(la2d)
  };
  await la2.close();
}

// ============================================================
// Six-state expansion (2026-09-30): mi / wy / sc / co / wi pages. Each is its
// own page (body data-state), lists every production state in the one header
// selector, carries its own county basemap, and shows no Florida wording.
// The CO certificate row carries its statewide-parcel value and the Treasurer's
// verified acquisition steps; the MI auction row the county's published fields.
// ============================================================
{
  // Release visibility gate: rows from a REVIEW_REQUIRED source (LGBS) say so on
  // the property page and in their provenance - observed, never presented as an
  // approved source.
  {
    const txUrl = BASE_URL.replace(/index\.html$/, 'tx.html');
    const a = await newPage({ viewport: { width: 1200, height: 900 } });
    await a.goto(txUrl + '#/auctions/ptx1', { waitUntil: 'networkidle' });
    await a.waitForTimeout(600);
    const ar = ((await a.locator('#detailModalInner .dec-row[data-q="review"]').textContent().catch(() => '')) || '').replace(/\s+/g, ' ');
    results.txReviewAuction = { reviewRow: /Source under review/.test(ar), text: /not yet approved/.test(ar) };
    await a.close();
    const l = await newPage({ viewport: { width: 1200, height: 900 } });
    await l.goto(txUrl + '#/lands/ptx6', { waitUntil: 'networkidle' });
    await l.waitForTimeout(600);
    results.txReviewLaft = {
      reviewRow: (await l.locator('#detailModalInner .dec-row[data-q="review"] .prov-review').count()) === 1,
      provenanceLabel: /Source under review/.test(((await l.locator('#detailModalInner .prov-row[data-field="legal_desc"]').textContent().catch(() => '')) || ''))
    };
    await l.close();
  }
  const NEW_STATES = [['MI', 'mi', 'Michigan'], ['WY', 'wy', 'Wyoming'], ['SC', 'sc', 'South Carolina'], ['CO', 'co', 'Colorado'], ['WI', 'wi', 'Wisconsin'],
    ['MO', 'mo', 'Missouri'], ['OK', 'ok', 'Oklahoma'], ['PA', 'pa', 'Pennsylvania'], ['MN', 'mn', 'Minnesota']];
  results.xsPages = {};
  for (const [code, file, name] of NEW_STATES) {
    const pg = await newPage({ viewport: { width: 1200, height: 900 } });
    await pg.goto(BASE_URL.replace(/index\.html$/, `${file}.html`) + '#/auctions', { waitUntil: 'networkidle' });
    await pg.waitForTimeout(400);
    const body = ((await pg.locator('body').textContent()) || '').replace(/\s+/g, ' ');
    results.xsPages[code] = {
      state: await pg.evaluate(() => document.body.dataset.state),
      title: await pg.title(),
      select: await pg.locator('#stateSelect').inputValue(),
      options: await pg.locator('#stateSelect option').evaluateAll(els => els.map(e => e.value)),
      // The Dashboard's global Data sources panel names Florida's sources AS Florida's; only
      // unqualified Florida wording on a new state's page is a defect.
      floridaWording: /(?<!Florida )Lands Available for Taxes|Fla\. Stat|County Just Value/.test(body),
      basemapOk: (await pg.evaluate(async f => (await fetch(f)).ok, `${file}-counties.svg`))
    };
    if (code === 'MI') {
      const card = pg.locator('.prop-card[data-pid="pmi1"]');
      const t = ((await card.textContent()) || '').replace(/\s+/g, ' ');
      results.xsMiCard = { count: await card.count(), county: /Eaton( County)?, MI/.test(t), sev: /State Equalized Value/.test(t), noJustValue: !/Just Value/.test(t) };
    }
    if (code === 'SC') {
      // Release visibility gate: an auction row's verified county sale process is
      // shown as a SALE process ("How do I register and bid?"), county-level, with
      // the published contact - never as a purchase path.
      const cold = await newPage({ viewport: { width: 1200, height: 900 } });
      await cold.goto(BASE_URL.replace(/index\.html$/, 'sc.html') + '#/auctions/psc1', { waitUntil: 'networkidle' });
      await cold.waitForTimeout(600);
      const row = ((await cold.locator('#detailModalInner .dec-row[data-q="process"]').textContent().catch(() => '')) || '').replace(/\s+/g, ' ');
      results.xsScProcess = {
        question: /How do I register and bid\?/.test(row),
        mode: /In-person sale/.test(row),
        steps: /register as a bidder before the sale/.test(row),
        phone: (await cold.locator('#detailModalInner .dec-row[data-q="process"] a[href^="tel:"]').count()) === 1,
        countyLevel: /County-level guidance/.test(row),
        notPurchasePath: !/purchase path/i.test(row),
        page: /Tax Sale Fact Sheet and Disclaimer/.test(row),
        noReviewRow: (await cold.locator('#detailModalInner .dec-row[data-q="review"]').count()) === 0
      };
      await cold.close();
      const ex = await newPage({ viewport: { width: 1200, height: 900 }, acceptDownloads: true });
      await ex.goto(BASE_URL.replace(/index\.html$/, 'sc.html') + '#/auctions', { waitUntil: 'networkidle' });
      await ex.waitForTimeout(400);
      const dl = ex.waitForEvent('download');
      await ex.click('#exportCsvBtn');
      const csv = fs.readFileSync(await (await dl).path(), 'utf8');
      const [head, ...lines] = csv.split(/\r?\n/).filter(Boolean);
      const line = lines.find(l => l.includes('FIXTURE-SC-1')) || '';
      results.xsScExport = {
        processCol: head.includes('Sale Process (county-level)'), reviewCol: head.includes('Source Review Status'),
        processCell: line.includes('In-person sale'), phoneCell: line.includes('803-000-0000'), approvedCell: line.includes('Approved')
      };
      await ex.close();
    }
    if (code === 'CO') {
      // Deep link straight to the certificate - a REAL cold start in a fresh page
      // (a goto that only changes the hash is a same-document navigation).
      const cold = await newPage({ viewport: { width: 1200, height: 900 } });
      await cold.goto(BASE_URL.replace(/index\.html$/, 'co.html') + '#/certificates/pco1', { waitUntil: 'networkidle' });
      await cold.waitForTimeout(600);
      results.xsCoCardCount = (await cold.locator('[data-pid="pco1"]').count()) > 0;
      const d = ((await cold.locator('#detailModalInner').textContent()) || '').replace(/\s+/g, ' ');
      const coMarket = ((await cold.locator('#detailModalInner .provenance-card .prov-row[data-field="market"]').textContent().catch(() => '')) || '').replace(/\s+/g, ' ');
      results.xsCoMarketProvenance = {
        label: /Parcel Total Value \(Colorado Public Parcels\)/.test(coMarket) && !/Just value/i.test(coMarket),
        source: /Government parcel \/ tax-roll record - Colorado Public Parcels/.test(coMarket),
        method: /attached by an exact identifier match \(parcel # = account\)/.test(coMarket)
      };
      results.xsCoDetail = {
        treasurer: /Morgan County Treasurer/.test(d),
        steps: /Purchase the certificate from the Morgan County Treasurer for the amount shown/.test(d),
        noStreetView: !/Street View/.test(d),
        noUndefined: !/undefined/.test(d),
        sourceNamed: /Morgan County Treasurer - County Held Tax Lien Sale Certificates/.test(d)
      };
      await cold.close();
      // Five-state sprint: a Douglas County lien (CC BY-SA 4.0) names its source WITH the
      // attribution the licence requires, and shows the county's assignment steps.
      const dg = await newPage({ viewport: { width: 1200, height: 900 } });
      await dg.goto(BASE_URL.replace(/index\.html$/, 'co.html') + '#/certificates/pco2', { waitUntil: 'networkidle' });
      await dg.waitForTimeout(600);
      const dd = ((await dg.locator('#detailModalInner').textContent()) || '').replace(/\s+/g, ' ');
      results.xsCoDouglas = {
        attribution: /Douglas County, Colorado/.test(dd) && /CC BY-SA 4\.0/.test(dd),
        assignment: /Request for Assignment of County-Held Tax Lien/.test(dd),
        noStreetView: !/Street View/.test(dd), noUndefined: !/undefined/.test(dd)
      };
      await dg.close();
      // The Colorado Auctions ledger copy says why it is empty instead of showing last year's list.
      const ca = await newPage({ viewport: { width: 1200, height: 900 } });
      await ca.goto(BASE_URL.replace(/index\.html$/, 'co.html') + '#/auctions', { waitUntil: 'networkidle' });
      await ca.waitForTimeout(500);
      const cb = ((await ca.locator('body').textContent()) || '').replace(/\s+/g, ' ');
      results.xsCoAuctionCopy = /November 5, 2026/.test(cb) && /CC BY-SA 4\.0/.test(cb);
      await ca.close();
    }
    await pg.close();
  }
}

// ============================================================
// Global state context (2026-09-30): ONE state selector, in the shared
// header beside the account badge, built from STATE_META. The state is the
// page (index.html = FL, tx.html = TX) whose rows come from
// get_properties(p_state); choosing a state navigates there carrying the
// route. ?bidlist= seeds one account's watchlist with a Florida row (p1) and
// a Texas row (ptx1).
// ============================================================
{
  const gs = await newPage({ viewport: { width: 1200, height: 900 } });
  const WL = '?bidlist=p1,ptx1';
  const cardPids = pg => pg.locator('#main .prop-card').evaluateAll(els => els.map(e => e.dataset.pid));
  const snap = async pg => ({
    file: await pg.evaluate(() => location.pathname.split('/').pop()),
    hash: await pg.evaluate(() => location.hash),
    state: await pg.locator('#stateSelect').inputValue()
  });
  const go = async (pg, page) => { await pg.click(`.nav-list .nav-item[data-page="${page}"]`); await pg.waitForTimeout(350); };
  const switchState = async (pg, st) => {
    await Promise.all([pg.waitForNavigation({ waitUntil: 'networkidle' }), pg.selectOption('#stateSelect', st)]);
    await pg.waitForTimeout(600);
  };
  await gs.goto(BASE_URL + WL + '#/dashboard', { waitUntil: 'networkidle' });
  await gs.waitForTimeout(600);

  // A. Header: one selector, next to the account control, options from STATE_META.
  results.gsSelectInHeader = await gs.locator('.topbar .header-btns #stateSelect').count();
  results.gsSelectBesideAccount = await gs.evaluate(() => document.getElementById('stateSelect').closest('.state-switch').nextElementSibling.id);
  results.gsOptions = await gs.locator('#stateSelect option').evaluateAll(els => els.map(e => e.value + ':' + e.textContent));
  results.gsStateSelectCount = await gs.locator('select[aria-label="State"]').count();
  await gs.click('#accountBtn');
  await gs.waitForTimeout(200);
  results.gsAccountMenuOpens = await gs.locator('#accountMenu').isVisible();
  await gs.keyboard.press('Escape');
  await gs.click('#accountBtn').catch(() => {});
  await gs.waitForTimeout(150);
  if (await gs.locator('#accountMenu').isVisible()) await gs.click('#accountBtn');

  // F. Florida -> Dashboard / List / Map / Watchlist.
  const fl = {};
  fl.dash = await snap(gs);
  fl.dashAuctionTile = ((await gs.locator('[data-ledger-tile="auction"] .stat-tile-val').textContent()) || '').trim();
  fl.dashCountiesSub = ((await gs.locator('#pageDashboard .stat-tile:not(.stat-tile-btn) .stat-tile-sub').first().textContent()) || '').trim();
  await go(gs, 'list');
  fl.list = await snap(gs);
  const flPids = await cardPids(gs);
  fl.listOnlyFlorida = flPids.length > 0 && flPids.every(id => !id.startsWith('ptx'));
  await gs.click('.ledger-tab[data-ledger="laft"]');
  await gs.waitForTimeout(300);
  await go(gs, 'map');
  fl.map = await snap(gs);
  fl.mapPaths = await gs.locator('#exploreMapCanvas path[data-county]').count();
  await go(gs, 'watchlist');
  fl.watch = await snap(gs);
  fl.watchPids = await gs.locator('#bidListRows .prop-card').evaluateAll(els => els.map(e => e.dataset.pid));
  fl.watchElsewhere = ((await gs.locator('#bidListElsewhere').textContent()) || '').trim();
  await gs.click('[data-action="closebidlist"]');
  await gs.waitForTimeout(250);
  results.gsFlorida = fl;

  // Switch to Texas from the List page: the ledger (Available) comes along.
  await go(gs, 'list');
  await switchState(gs, 'TX');
  const tx = {};
  tx.list = await snap(gs);
  tx.listLedgerOn = await gs.locator('.ledger-tab.on').getAttribute('data-ledger');
  const txPids = await cardPids(gs);
  tx.listOnlyTexas = txPids.every(id => id.startsWith('ptx'));
  await gs.click('.ledger-tab[data-ledger="auction"]');
  await gs.waitForTimeout(300);
  const txAuctionPids = await cardPids(gs);
  tx.listAuctionOnlyTexas = txAuctionPids.length > 0 && txAuctionPids.every(id => id.startsWith('ptx'));
  await go(gs, 'dashboard');
  tx.dash = await snap(gs);
  tx.dashAuctionTile = ((await gs.locator('[data-ledger-tile="auction"] .stat-tile-val').textContent()) || '').trim();
  tx.dashCountiesSub = ((await gs.locator('#pageDashboard .stat-tile:not(.stat-tile-btn) .stat-tile-sub').first().textContent()) || '').trim();
  await go(gs, 'map');
  tx.map = await snap(gs);
  tx.mapPaths = await gs.locator('#exploreMapCanvas path[data-county]').count();
  await go(gs, 'watchlist');
  tx.watch = await snap(gs);
  tx.watchPids = await gs.locator('#bidListRows .prop-card').evaluateAll(els => els.map(e => e.dataset.pid));
  tx.watchElsewhere = ((await gs.locator('#bidListElsewhere').textContent()) || '').trim();
  tx.watchCount = ((await gs.locator('#navWatchlistCount').textContent()) || '').trim();
  tx.watchDeletes = await gs.evaluate(() => window.__stubBidListDeletes || 0);
  await gs.click('[data-action="closebidlist"]');
  await gs.waitForTimeout(250);
  results.gsTexas = tx;

  // G. Refresh keeps Texas (the state is the URL), on the page it was on.
  await gs.goto(TX_BASE_URL + WL + '#/map?ledger=auction&county=Harris', { waitUntil: 'networkidle' });
  await gs.waitForTimeout(600);
  const beforeReload = await snap(gs);
  results.gsTexasMapCounty = await gs.locator('#mapCountySelect').inputValue();
  await gs.reload({ waitUntil: 'networkidle' });
  await gs.waitForTimeout(600);
  const afterReload = await snap(gs);
  results.gsReloadKeepsTexas = afterReload.state === 'TX' && afterReload.file === 'tx.html' && afterReload.hash === beforeReload.hash;
  results.gsReloadMapVisible = await gs.locator('#pageMap').evaluate(el => !el.hidden);

  // D. Map follows the header: switching back to Florida on the Map page
  // lands on Florida's map with the same map route (a Texas county the
  // Florida map does not have falls back to All Counties).
  await switchState(gs, 'FL');
  results.gsMapBackToFlorida = await snap(gs);
  results.gsMapBackPaths = await gs.locator('#exploreMapCanvas path[data-county]').count();
  results.gsMapBackCounty = await gs.locator('#mapCountySelect').inputValue();
  await gs.close();

  // Property deep link: a Texas property URL opens in the Texas context; a
  // state switch from an open property drops the id (it belongs to Texas)
  // and keeps the ledger.
  const dl = await newPage({ viewport: { width: 1200, height: 900 } });
  await dl.goto(TX_BASE_URL + '#/auctions/ptx1', { waitUntil: 'networkidle' });
  await dl.waitForTimeout(700);
  results.gsDeepLinkTexas = { state: await dl.locator('#stateSelect').inputValue(), modal: await dl.locator('#detailModal').isVisible() };
  await Promise.all([dl.waitForNavigation({ waitUntil: 'networkidle' }), dl.selectOption('#stateSelect', 'FL')]);
  await dl.waitForTimeout(600);
  results.gsDeepLinkSwitch = { ...(await snap(dl)), modal: await dl.locator('#detailModal').isVisible() };
  await dl.close();

  // H. Phone: one compact header row - state selector and account badge both
  // on screen, selector first; the bottom bar keeps exactly four entries.
  const ph = await newPage({ viewport: { width: 360, height: 780 } });
  await ph.goto(TX_BASE_URL + '#/list', { waitUntil: 'networkidle' });
  await ph.waitForTimeout(600);
  results.gsPhone = await ph.evaluate(() => {
    const sel = document.getElementById('stateSelect').getBoundingClientRect();
    const acc = document.getElementById('accountBtn').getBoundingClientRect();
    const bar = document.querySelector('.topbar').getBoundingClientRect();
    return {
      bothVisible: sel.width > 0 && acc.width > 0,
      inViewport: sel.left >= 0 && acc.right <= window.innerWidth,
      sameRow: Math.abs((sel.top + sel.bottom) / 2 - (acc.top + acc.bottom) / 2) < 4,
      selectorFirst: sel.right <= acc.left,
      headerCompact: bar.height <= 64,
      noHorizontalScroll: document.documentElement.scrollWidth <= window.innerWidth,
      value: document.getElementById('stateSelect').value
    };
  });
  results.gsPhoneBottomNav = await ph.locator('.nav-bottom .nav-bottom-item').evaluateAll(els => els.map(e => e.dataset.page));
  await ph.close();
}

// Legacy deep links keep working: #map (old Map link), #/lands (ledger
// slug), #/dashboard, #/watchlist, #/list.
const navLegacy = await newPage({ viewport: { width: 1200, height: 900 } });
await navLegacy.goto(BASE_URL + '#map', { waitUntil: 'networkidle' });
await navLegacy.waitForTimeout(500);
results.navLegacyMapVisible = await navLegacy.locator('#pageMap').evaluate(el => !el.hidden);
results.navLegacyMapHash = await navLegacy.evaluate(() => location.hash);
await navLegacy.close();
const navLands = await newPage({ viewport: { width: 1200, height: 900 } });
await navLands.goto(BASE_URL + '#/lands', { waitUntil: 'networkidle' });
await navLands.waitForTimeout(500);
results.navLandsListVisible = await navLands.locator('#pageList').evaluate(el => !el.hidden);
results.navLandsHeading = ((await navLands.locator('.ledger-head h2').textContent()) || '').trim();
results.navLandsLit = await navLands.locator('.nav-list .nav-item.on').evaluateAll(els => els.map(e => e.dataset.page));
// Editing the address bar to another route switches pages without a reload.
await navLands.evaluate(() => { location.hash = '#/dashboard'; });
await navLands.waitForTimeout(400);
results.navHashEditDashboardVisible = await navLands.locator('#pageDashboard').evaluate(el => !el.hidden);
await navLands.evaluate(() => { location.hash = '#/certificates'; });
await navLands.waitForTimeout(400);
results.navHashEditCertHeading = ((await navLands.locator('.ledger-head h2').textContent()) || '').trim();
results.navHashEditCertListVisible = await navLands.locator('#pageList').evaluate(el => !el.hidden);
await navLands.close();
const navWl = await newPage({ viewport: { width: 1200, height: 900 } });
await navWl.goto(BASE_URL + '#/watchlist', { waitUntil: 'networkidle' });
await navWl.waitForTimeout(500);
results.navWatchlistDeepOpen = await navWl.locator('#bidListModal').evaluate(el => !el.hidden);
results.navWatchlistDeepLit = await navWl.locator('.nav-list .nav-item.on').evaluateAll(els => els.map(e => e.dataset.page));
await navWl.close();
const navList = await newPage({ viewport: { width: 1200, height: 900 } });
await navList.goto(BASE_URL + '#/list', { waitUntil: 'networkidle' });
await navList.waitForTimeout(500);
results.navListRouteVisible = await navList.locator('#pageList').evaluate(el => !el.hidden);
results.navListRouteHash = await navList.evaluate(() => location.hash);
await navList.close();

// Dashboard as an operating view: one tile per ledger (opens the List on
// that ledger), attention / recent / verified-path panels - counts only,
// "Not tracked" where the data holds none.
const navDash = await newPage({ viewport: { width: 1200, height: 900 } });
await navDash.goto(BASE_URL + '#/dashboard', { waitUntil: 'networkidle' });
await navDash.waitForTimeout(500);
results.navDashDeepVisible = await navDash.locator('#pageDashboard').evaluate(el => !el.hidden);
results.navDashTiles = await navDash.locator('#dashStats .stat-tile').evaluateAll(els => els.map(e => (e.dataset.ledgerTile || 'counties') + ':' + e.querySelector('.stat-tile-val').textContent.trim()));
results.navDashNoValueTile = await navDash.locator('#dashStats').evaluate(el => !/Sum of county values/.test(el.textContent));
results.navDashAttention = await navDash.locator('#dashAttentionRows .dash-row').evaluateAll(els => els.map(e => e.dataset.att + ':' + e.querySelector('.dash-row-vals').textContent.replace(/\s+/g, ' ').trim()));
results.navDashRecent = await navDash.locator('#dashRecentRows .dash-row').evaluateAll(els => els.map(e => e.dataset.recent + ':' + e.querySelector('.dash-row-vals').textContent.replace(/\s+/g, ' ').trim()));
results.navDashPaths = await navDash.locator('#dashPathRows .dash-row').evaluateAll(els => els.map(e => (e.dataset.path || e.dataset.pathType) + ':' + e.querySelector('.dash-row-vals').textContent.replace(/\s+/g, ' ').trim()));
results.navDashNoScoreWords = await navDash.locator('#pageDashboard').evaluate(el => !/\b(score|ranking|recommend|AI)\b/i.test(el.textContent));
results.navDashSubtitle = ((await navDash.locator('#dashSubtitle').textContent()) || '').trim();
await navDash.click('#dashStats [data-go-ledger="laft"]');
await navDash.waitForTimeout(300);
results.navDashTileOpensList = await navDash.locator('#pageList').evaluate(el => !el.hidden);
results.navDashTileHash = await navDash.evaluate(() => location.hash);
results.navDashTileHeading = ((await navDash.locator('.ledger-head h2').textContent()) || '').trim();
await navDash.close();

// Phone: the four-item bottom bar fits a 320px screen without scrolling.
const navPhone = await newPage({ viewport: { width: 320, height: 640 } });
await navPhone.goto(BASE_URL + '#/auctions', { waitUntil: 'networkidle' });
await navPhone.waitForTimeout(500);
results.navPhoneBottomItems = await navPhone.locator('#navBottom .nav-bottom-item').count();
results.navPhoneBottomFits = await navPhone.locator('#navBottom').evaluate(el => el.scrollWidth <= el.clientWidth && Array.from(el.children).every(c => c.getBoundingClientRect().right <= window.innerWidth + 1));
results.navPhoneBottomLabels = await navPhone.locator('#navBottom .nav-bottom-item').evaluateAll(els => els.map(e => e.textContent.trim()));
await navPhone.close();

// Watchlist: the same parcel watched in two ledgers (p1 auction + p4
// certificate share Alachua parcel 111) shows one card and a fold-in line,
// not two cards.
const navWl2 = await newPage({ viewport: { width: 1200, height: 900 } });
await navWl2.goto(BASE_URL + '#/auctions', { waitUntil: 'networkidle' });
await navWl2.waitForTimeout(500);
await navWl2.locator('.prop-card[data-pid="p1"] [data-action="bidlist"]').dispatchEvent('click');
await navWl2.waitForTimeout(300);
await navWl2.click('.ledger-tab[data-ledger="certificate"]');
await navWl2.waitForTimeout(300);
await navWl2.locator('.prop-card[data-pid="p4"] [data-action="bidlist"]').dispatchEvent('click');
await navWl2.waitForTimeout(300);
await navWl2.click('.nav-list .nav-item[data-page="watchlist"]');
await navWl2.waitForTimeout(400);
results.navWlCards = await navWl2.locator('#bidListRows .prop-card').evaluateAll(els => els.map(e => e.dataset.pid));
results.navWlRelated = await navWl2.locator('#bidListRows .bidlist-related li').evaluateAll(els => els.map(e => e.textContent.replace(/\s+/g, ' ').trim()));
results.navWlCount = ((await navWl2.locator('#navWatchlistCount').textContent()) || '').trim();
await navWl2.close();


// ============================================================
// Customer monitoring sprint (2026-10-01)
// ============================================================
// 1. Paged loading: PostgREST caps every call (RPCs included) at max-rows.
// With the cap forced to 2 the app must page each ledger and end up with the
// same rows it gets in one call.
async function ledgerCardCounts(url) {
  const pg = await newPage({ viewport: { width: 1200, height: 900 } });
  await pg.goto(url, { waitUntil: 'networkidle' });
  await pg.waitForTimeout(500);
  const out = {};
  for (const l of ['auction', 'laft', 'certificate']) {
    await pg.click(`.ledger-tab[data-ledger="${l}"]`);
    await pg.waitForTimeout(200);
    out[l] = (await pg.locator('#main .prop-card').evaluateAll(els => els.map(e => e.dataset.pid).sort())).join(',');
  }
  out.calls = await pg.evaluate(() => window.__stubGetPropertiesCalls || 0);
  await pg.close();
  return out;
}
{
  const full = await ledgerCardCounts(BASE_URL);
  const paged = await ledgerCardCounts(BASE_URL.replace('index.html', 'index.html?maxrows=2'));
  // Auctions holds 9 fixture rows, so with a cap of 2 it takes 5 pages.
  results.monPagedSameCards = full.auction === paged.auction && full.laft === paged.laft && full.certificate === paged.certificate && full.auction.split(',').length > 2;
  results.monPagedMoreCalls = paged.calls > full.calls;
}

// 2. Saved-search parity: the same shared cases scripts/saved_search_match.py
// is tested against, run through the browser's implementation.
const monPage = await newPage({ viewport: { width: 1200, height: 900 } });
monPage.on('pageerror', e => errors.push('pageerror: ' + e.message));
await monPage.goto(BASE_URL.replace('index.html', 'index.html?bidlist=p15,p3') + '#/lands', { waitUntil: 'networkidle' });
await monPage.waitForTimeout(600);
{
  const cases = JSON.parse(fs.readFileSync(new URL('./python/fixtures/saved_search_cases.json', import.meta.url), 'utf8'));
  results.monParityMismatches = await monPage.evaluate(c => c.cases.map((k, i) => (window.__tdwSavedSearchMatches(k.criteria, c.rows[k.row], c.now) === k.match ? null : i)).filter(x => x !== null), cases);
}
// 3. Server saved search: save, storage wording, apply.
results.monAlertsBadge = ((await monPage.locator('#alertsUnread').textContent()) || '').trim();
await monPage.click('#savedSearchesBtn');
await monPage.waitForTimeout(200);
results.monSsStorage = ((await monPage.locator('#savedSearchStorage').textContent()) || '').trim().slice(0, 28);
await monPage.fill('#saveSearchName', 'Available Florida');
await monPage.click('#saveSearchSubmit');
await monPage.waitForTimeout(300);
results.monSsItems = await monPage.locator('#savedSearchList .saved-search').count();
results.monSsCounts = ((await monPage.locator('#savedSearchList .saved-search .ss-counts').first().textContent()) || '').replace(/\s+/g, ' ').trim();
results.monSsAlertsToggle = await monPage.locator('#savedSearchList [data-ss-alerts]').count();
await monPage.click('#savedSearchesCloseBtn');
await monPage.click('.ledger-tab[data-ledger="auction"]');
await monPage.waitForTimeout(200);
await monPage.click('#savedSearchesBtn');
await monPage.waitForTimeout(200);
await monPage.locator('#savedSearchList [data-ss-apply]').first().click();
await monPage.waitForTimeout(300);
results.monSsAppliedLedger = await monPage.locator('#ledgerTabs .ledger-tab.on').first().getAttribute('data-ledger');
// 4. Monitoring filters on the Available ledger.
await monPage.click('#filtersToggle');
await monPage.waitForTimeout(150);
results.monFiltersRow = await monPage.locator('#monitorFilters select, #monitorFilters input').count();
await monPage.selectOption('#watchStatusFilter', 'watched');
await monPage.waitForTimeout(200);
results.monWatchedCards = await monPage.locator('#main .prop-card').evaluateAll(els => els.map(e => e.dataset.pid).sort());
await monPage.selectOption('#watchStatusFilter', 'any');
await monPage.selectOption('#acqStateFilter', 'verified');
await monPage.waitForTimeout(200);
results.monAcqVerifiedCards = await monPage.locator('#main .prop-card').evaluateAll(els => els.map(e => e.dataset.pid).sort());
await monPage.click('#resetBtn');
await monPage.waitForTimeout(200);
results.monResetClearsAcq = await monPage.locator('#acqStateFilter').inputValue();
// 5. Available export carries acquisition status / imagery / freshness.
{
  const dl = monPage.waitForEvent('download');
  await monPage.click('#exportCsvBtn');
  const header = fs.readFileSync(await (await dl).path(), 'utf8').split(/\r?\n/)[0].split(',');
  results.monCsvHas = ['Acquisition Status', 'Acquisition Last Verified', 'Imagery On File', 'Days Since Last Read', 'Taxable Value'].every(h => header.includes(h));
}
// 6. Property page: Watch & changes with server change history.
const monDetail = await newPage({ viewport: { width: 390, height: 844 } });
await monDetail.goto(BASE_URL.replace('index.html', 'index.html?bidlist=p15') + '#/lands/p15', { waitUntil: 'networkidle' });
await monDetail.waitForTimeout(700);
results.monDetailSection = await monDetail.locator('#detailModalInner [data-section="monitor"]').count();
results.monDetailStatus = ((await monDetail.locator('#detailModalInner .monitor-status').textContent()) || '').trim();
results.monDetailHistory = await monDetail.locator('#detailModalInner .change-history li').evaluateAll(els => els.map(e => e.dataset.kind));
results.monDetailNeverSold = await monDetail.locator('#detailModalInner [data-section="monitor"]').evaluate(el => /never as a sale/.test(el.textContent) && !/\bsold\b/i.test(el.textContent.replace(/never as a sale|not a sale/g, '')));
results.monDetailNavPill = await monDetail.locator('#detailModalInner .detail-nav [data-target="monitor"]').count();
// 7. Alerts inbox: two alerts, one unread; mark read clears the badge.
await monDetail.evaluate(() => { document.getElementById('detailModal').hidden = true; });
await monDetail.locator('#alertsMenuItem').evaluate(el => el.click());
await monDetail.waitForTimeout(200);
results.monAlertItems = await monDetail.locator('#alertList .alert-item').count();
results.monAlertEmailDisabled = await monDetail.locator('#prefEmail').isDisabled();
await monDetail.click('#alertsMarkRead');
await monDetail.waitForTimeout(200);
results.monAlertsBadgeAfterRead = await monDetail.locator('#alertsUnread').isHidden();
await monDetail.click('#alertsCloseBtn');
// 8. Watchlist modal lists server-detected changes for watched rows.
await monDetail.click('.nav-bottom-item[data-page="watchlist"]');
await monDetail.waitForTimeout(300);
results.monWatchServerChanges = await monDetail.locator('#watchServerChanges li').count();
// 9. Analytics: session_start + property_viewed; a search never sends its text.
await monDetail.goto(BASE_URL.replace('index.html', 'index.html?an=1') + '#/lands', { waitUntil: 'networkidle' });
await monDetail.waitForTimeout(600);
await monDetail.fill('#searchInput', 'Manatee');
await monDetail.waitForTimeout(1900);
{
  const evs = await monDetail.evaluate(() => window.__stubProductEvents || []);
  results.monAnalyticsEvents = Array.from(new Set(evs.map(e => e.event))).sort();
  results.monAnalyticsNoText = !JSON.stringify(evs).includes('Manatee');
}
await monDetail.close();
await monPage.close();
// 10. Without migration 024: browser-only saved searches, honest alerts and
// change-history wording, the NEW / CHANGED / NO LONGER MATCHING diff.
const monNone = await newPage({ viewport: { width: 1200, height: 900 } });
monNone.on('pageerror', e => errors.push('pageerror: ' + e.message));
await monNone.addInitScript(() => {
  if (sessionStorage.getItem('mon-seeded')) return;
  sessionStorage.setItem('mon-seeded', '1');
  localStorage.setItem('tdw_saved_searches_v1', JSON.stringify([{ id: 'ss-local-1', name: 'Local Available', state: 'FL', criteria: { ledger: 'laft', available_only: true }, alerts_enabled: false, last_viewed_at: '2026-09-01T00:00:00Z', last_match_ids: ['p15', 'gone-row'] }]));
  localStorage.setItem('tdw_ss_fp_ss-local-1', JSON.stringify({ p15: { f: 'stale-fingerprint', l: '15 Manatee Ln', c: 'Citrus' }, 'gone-row': { f: 'x', l: '9 Gone Rd', c: 'Bay' } }));
});
await monNone.goto(BASE_URL.replace('index.html', 'index.html?monitor=none') + '#/lands/p15', { waitUntil: 'networkidle' });
await monNone.waitForTimeout(700);
results.monNoneHistory = ((await monNone.locator('#detailModalInner [data-changes-for="p15"]').textContent()) || '').trim();
await monNone.evaluate(() => { document.getElementById('detailModal').hidden = true; });
await monNone.click('#savedSearchesBtn');
await monNone.waitForTimeout(200);
results.monNoneStorage = ((await monNone.locator('#savedSearchStorage').textContent()) || '').trim().slice(0, 30);
results.monNoneCounts = await monNone.locator('.saved-search[data-ss="ss-local-1"] .ss-count').evaluateAll(els => els.map(e => e.textContent.trim()));
results.monNoneRemovedWording = ((await monNone.locator('.saved-search[data-ss="ss-local-1"] .ss-removed').first().textContent()) || '').replace(/\s+/g, ' ').trim();
results.monNoneAlertsToggle = await monNone.locator('[data-ss-alerts]').count();
await monNone.click('[data-ss-seen="ss-local-1"]');
await monNone.waitForTimeout(200);
results.monNoneCountsAfterSeen = await monNone.locator('.saved-search[data-ss="ss-local-1"] .ss-count').evaluateAll(els => els.map(e => e.textContent.trim()));
await monNone.click('#savedSearchesCloseBtn');
await monNone.locator('#alertsMenuItem').evaluate(el => el.click());
await monNone.waitForTimeout(200);
results.monNoneAlerts = await monNone.locator('#alertsUnavailable').count();
await monNone.locator('#alertsCloseBtn').click();
await monNone.click('.nav-list .nav-item[data-page="dashboard"]');
await monNone.waitForTimeout(300);
results.monNoneRuns = await monNone.locator('#dashRunsUnavailable').count();
await monNone.close();
// 11. Dashboard: latest change-detection run per source.
const monDash = await newPage({ viewport: { width: 1200, height: 900 } });
await monDash.goto(BASE_URL + '#/dashboard', { waitUntil: 'networkidle' });
await monDash.waitForTimeout(700);
results.monDashRuns = await monDash.locator('#dashRunRows .run-row').evaluateAll(els => els.map(e => e.dataset.source + ':' + Array.from(e.querySelectorAll('.dash-row-vals span')).map(x => x.textContent.trim()).join(' / ')));
await monDash.close();

// Storage-optimization sprint: stored imagery is now WebP. A WebP produced by
// scripts/image_storage.py must render in the app page under its own CSP.
{
  const webp = fs.readFileSync(new URL('./python/fixtures/aerial_sample.webp', import.meta.url)).toString('base64');
  const imgPage = await newPage({ viewport: { width: 800, height: 600 } });
  await imgPage.goto(BASE_URL + '#/auctions', { waitUntil: 'networkidle' });
  results.webpImageRenders = await imgPage.evaluate(src => new Promise(res => {
    const img = new Image();
    img.onload = () => res(img.naturalWidth + 'x' + img.naturalHeight);
    img.onerror = () => res('error');
    img.src = 'data:image/webp;base64,' + src;
  }), webp);
  await imgPage.close();
}

// --- Collection vs customer publication (2026-10-02) ---
// A source awaiting customer-publication review is collected and synced; its
// rows carry publication_status. Admins always see them, labelled; every user
// sees them in publicationMode "preview"; customers in the default enforced
// mode do not (counted as withheld). Source review is never availability.
{
  const STATE_URL = st => BASE_URL.replace(/index\.html$/, st + '.html');
  async function ledgerFacts(pg) {
    const btn = pg.locator('#expandAllBtn');
    if (await btn.count() && (await btn.getAttribute('data-mode')) === 'expand') { await btn.click(); await pg.waitForTimeout(300); }
    return pg.evaluate(() => {
      const t = sel => { const e = document.querySelector(sel); return e ? e.textContent.replace(/\s+/g, ' ').trim() : null; };
      const cards = [...document.querySelectorAll('.prop-card')];
      return {
        cards: cards.length,
        reviewChips: [...document.querySelectorAll('.prop-card .source-review-chip')].map(e => e.textContent.trim()),
        programs: [...document.querySelectorAll('.prop-card .source-program')].map(e => e.textContent.trim()).sort(),
        pending: t('#ledgerReviewPending'),
        withheld: t('#ledgerWithheld')
      };
    });
  }
  const adminMi = await newPage({ viewport: { width: 1200, height: 900 } });
  await adminMi.goto(STATE_URL('mi') + '?profile=admin#/lands', { waitUntil: 'networkidle' });
  await adminMi.waitForTimeout(600);
  results.devVisAdminMiLands = await ledgerFacts(adminMi);
  await adminMi.close();

  const adminDetail = await newPage({ viewport: { width: 1200, height: 900 } });
  await adminDetail.goto(STATE_URL('mi') + '?profile=admin#/lands/pmi_dlba1', { waitUntil: 'networkidle' });
  await adminDetail.waitForTimeout(700);
  results.devVisAdminDetail = await adminDetail.evaluate(() => {
    const m = document.querySelector('#detailModalInner');
    const txt = m ? m.innerText.replace(/\s+/g, ' ') : '';
    const row = m && m.querySelector('.source-review-row');
    const banner = m && m.querySelector('#sourceReviewBanner');
    return {
      banner: banner ? banner.textContent.replace(/\s+/g, ' ').trim() : null,
      reviewRow: row ? row.textContent.replace(/\s+/g, ' ').trim() : null,
      identifier: txt.includes('99000001.'),
      program: txt.includes('Side Lot For Sale'),
      lastRead: /Last read from the source/.test(txt),
      neverApproved: !/Source publication review: Approved/.test(txt)
    };
  });
  await adminDetail.close();

  const adminDash = await newPage({ viewport: { width: 1200, height: 900 } });
  await adminDash.goto(STATE_URL('mi') + '?profile=admin#/dashboard', { waitUntil: 'networkidle' });
  await adminDash.waitForTimeout(600);
  results.devVisAdminDash = await adminDash.evaluate(() => {
    const panel = document.querySelector('#dashSourceReview');
    if (!panel) return null;
    const row = id => { const e = panel.querySelector(`[data-source-id="${id}"]`); return e ? e.textContent.replace(/\s+/g, ' ').trim() : null; };
    return { mode: (document.querySelector('#dashPublicationMode') || {}).textContent, lots: row('mi_detroit_landbank_lots'), programs: row('mi_detroit_landbank_programs') };
  });
  await adminDash.close();

  const custMi = await newPage({ viewport: { width: 1200, height: 900 } });
  await custMi.goto(STATE_URL('mi') + '#/lands', { waitUntil: 'networkidle' });
  await custMi.waitForTimeout(600);
  results.devVisCustomerMiLands = await ledgerFacts(custMi);
  results.devVisCustomerDashPanel = await custMi.evaluate(() => { location.hash = '#/dashboard'; return !!document.querySelector('#dashSourceReview'); });
  await custMi.close();

  // Customer preview: config.js with publicationMode "preview", default profile.
  const previewCfg = fs.readFileSync(new URL('./config.js', import.meta.url), 'utf8') + '\nwindow.TDW_CONFIG.publicationMode = "preview";\n';
  const prev = await newPage({ viewport: { width: 1200, height: 900 } });
  await prev.route(/\/config\.js(\?|$)/, route => route.fulfill({ status: 200, contentType: 'application/javascript', body: previewCfg }));
  await prev.goto(STATE_URL('sc') + '#/lands', { waitUntil: 'networkidle' });
  await prev.waitForTimeout(600);
  results.devVisPreviewScLands = await ledgerFacts(prev);
  await prev.close();

  // Detroit customer subset (2026-10-03). Fixture: pmi_dlbs1/2 = offered
  // structure + IN the ~50% selection; pmi_dlbs3/4 = offered structure, NOT
  // selected; pmi_dlba1 (Side Lot) / pmi_dlba2 (program) = no structure field.
  const listIds = pg => pg.evaluate(() => (window.__tdwLastRender ? window.__tdwLastRender.rows.map(r => String(r.id)) : []).filter(id => /^pmi_dlb|^pmi_oce|^psc_/.test(id)).sort());
  const detAdmin = await newPage({ viewport: { width: 1200, height: 900 } });
  await detAdmin.goto(STATE_URL('mi') + '?profile=admin#/lands', { waitUntil: 'networkidle' });
  await detAdmin.waitForTimeout(600);
  results.detroitSubsetAdmin = {
    ids: await listIds(detAdmin),
    reasons: await detAdmin.evaluate(() => Object.fromEntries((window.__tdwLastRender ? window.__tdwLastRender.rows : [])
      .filter(r => /^pmi_dlb/.test(String(r.id))).map(r => [r.id, window.__tdwDetroitSubset.status(r)]).sort())),
    chips: await detAdmin.evaluate(() => [...document.querySelectorAll('.prop-card .source-subset-chip')].map(e => e.dataset.subset).sort()),
    chipText: await detAdmin.evaluate(() => { const e = document.querySelector('.prop-card .source-subset-chip'); return e ? e.textContent.trim() : null; }),
    note: await detAdmin.evaluate(() => { const e = document.querySelector('#ledgerDetroitSubset'); return e ? e.textContent.replace(/\s+/g, ' ').trim() : null; }),
    statusesUntouched: await detAdmin.evaluate(() => (window.__tdwLastRender ? window.__tdwLastRender.rows : []).filter(r => /^pmi_dlb/.test(String(r.id))).every(r => r.status === 'active'))
  };
  await detAdmin.close();
  const detPrevCfg = fs.readFileSync(new URL('./config.js', import.meta.url), 'utf8') + '\nwindow.TDW_CONFIG.publicationMode = "preview";\n';
  const detPrev = await newPage({ viewport: { width: 1200, height: 900 } });
  await detPrev.route(/\/config\.js(\?|$)/, route => route.fulfill({ status: 200, contentType: 'application/javascript', body: detPrevCfg }));
  await detPrev.goto(STATE_URL('mi') + '#/lands', { waitUntil: 'networkidle' });
  await detPrev.waitForTimeout(600);
  results.detroitSubsetPreview = {
    ids: await listIds(detPrev),
    note: await detPrev.evaluate(() => { const e = document.querySelector('#ledgerDetroitSubset'); return e ? e.textContent.replace(/\s+/g, ' ').trim() : null; }),
    reviewChips: await detPrev.evaluate(() => [...document.querySelectorAll('.prop-card .source-review-chip')].length),
    subsetChips: await detPrev.evaluate(() => document.querySelectorAll('.source-subset-chip').length)
  };
  // Map -> Available, same session: only the customer subset reaches the map.
  await detPrev.evaluate(() => { location.hash = '#/map?ledger=laft&county=Wayne'; });
  await detPrev.waitForTimeout(900);
  results.detroitSubsetPreviewMap = await detPrev.evaluate(() => (window.__tdwMapLastRender ? window.__tdwMapLastRender.rows : [])
    .map(r => String(r.id)).filter(id => /^pmi_dlb/.test(id)).sort());
  await detPrev.close();
  // The JS rule and the Python rule (harvesters/otc/detroit_subset.py) give the
  // same answer for every shared vector.
  const detCases = JSON.parse(fs.readFileSync(new URL('./python/fixtures/detroit_subset_cases.json', import.meta.url), 'utf8'));
  const detVec = await newPage({ viewport: { width: 900, height: 700 } });
  await detVec.goto(STATE_URL('mi') + '?profile=admin#/lands', { waitUntil: 'networkidle' });
  results.detroitSubsetVectors = await detVec.evaluate(cases => {
    const bad = [];
    for (const c of cases) {
      const row = { source_id: c.source_id, parcel: c.parcel, inventory_status_raw: c.inventory_status_raw };
      const got = window.__tdwDetroitSubset.status(row);
      const h = window.__tdwDetroitSubset.fnv1a32(`${c.source_id}|${c.parcel}`);
      if (got !== c.expected || h !== c.hash) bad.push(c.parcel);
    }
    return { cases: cases.length, mismatches: bad };
  }, detCases);
  await detVec.close();
  // AVAILABLE is the default inventory: with no ledger in the URL the List lands
  // on Available where the state has Available rows (FL, LA), Auctions where it
  // has none (WY).
  const landing = async (file) => {
    const pg = await newPage({ viewport: { width: 1200, height: 900 } });
    await pg.goto(BASE_URL.replace(/index\.html$/, file), { waitUntil: 'networkidle' });
    await pg.waitForTimeout(500);
    const out = await pg.evaluate(() => ({
      hash: location.hash,
      activeTab: (() => { const t = document.querySelector('#ledgerTabs .ledger-tab.on'); return t ? t.dataset.ledger : null; })(),
      cards: document.querySelectorAll('.prop-card').length > 0,
      ledgers: [...new Set((window.__tdwLastRender ? window.__tdwLastRender.rows : []).map(r => r.source))]
    }));
    await pg.close();
    return out;
  };
  results.availDefaultLanding = { FL: await landing('index.html'), LA: await landing('la.html'), WY: await landing('wy.html') };
  // Acquisition-path semantics (2026-10-03): Horry SC's county-wide FLC bid-form
  // PDF is the county's process - never "Purchase or apply online", never a
  // property-level purchase link, and still offered as the process document.
  const horry = await newPage({ viewport: { width: 1200, height: 900 } });
  await horry.goto(STATE_URL('sc') + '?profile=admin#/lands/psc_horry1', { waitUntil: 'networkidle' });
  await horry.waitForTimeout(700);
  results.acqPathHorryDetail = await horry.evaluate(() => {
    const m = document.querySelector('#detailModalInner');
    const txt = m ? m.innerText.replace(/\s+/g, ' ') : '';
    const pdf = 'https://horrycountysc.gov/media/sinbmsz5/horrycountyflcguidelines.pdf';
    const links = m ? [...m.querySelectorAll('a')].filter(a => a.href === pdf).map(a => a.textContent.replace(/\s+/g, ' ').trim()) : [];
    const modes = m ? [...new Set([...m.querySelectorAll('.acq-mode')].map(e => e.dataset.mode))] : [];
    return {
      modes,
      saysOnline: /Purchase or apply online/.test(txt),
      saysPropertyLink: /Property-level link published by the source|a link the source published for this property/.test(txt),
      saysBid: txt.includes('Bid application required - purchase process not online'),
      pdfLinks: links,
      pathEvidence: /Application form to download \(published by the source\) · source-level/.test(txt)
    };
  });
  await horry.close();

  const custSc = await newPage({ viewport: { width: 1200, height: 900 } });
  await custSc.goto(STATE_URL('sc') + '#/lands', { waitUntil: 'networkidle' });
  await custSc.waitForTimeout(600);
  results.devVisCustomerScLands = await ledgerFacts(custSc);
  await custSc.close();
}

// --- Scale regression (2026-10-02): a 30,000+ row county ---
// ?bigcounty=30000 adds 30,000 SYNTHETIC geocoded Available rows in Wayne MI
// (stub). The List must page them (never 30,000 cards), the table too, search
// must still find one, and the Map must cluster them (never 30,000 pins) with
// every in-view row counted in a cluster or a pin.
{
  const big = await newPage({ viewport: { width: 1300, height: 900 } });
  big.on('pageerror', e => errors.push('pageerror(bigcounty): ' + e.message));
  await big.goto(BASE_URL.replace(/index\.html$/, 'mi.html') + '?profile=admin&bigcounty=30000#/lands', { waitUntil: 'networkidle' });
  await big.waitForFunction(() => document.querySelectorAll('.county-group').length > 0, null, { timeout: 60000 });
  results.scaleListInitial = await big.evaluate(() => ({
    cardsInDocument: document.querySelectorAll('.prop-card').length,
    wayneCount: (document.querySelector('.county-group[data-county="Wayne"] .county-count') || {}).textContent,
    groupMore: (document.querySelector('.county-group[data-county="Wayne"] .group-more') || {}).textContent,
    tableRows: document.querySelectorAll('#dataTableBody tr:not(.table-more-row)').length,
    tableMore: (document.getElementById('tableMoreBtn') || {}).textContent,
    domUnder15k: document.getElementsByTagName('*').length < 15000
  }));
  await big.evaluate(() => { document.querySelector('.county-group[data-county="Wayne"]').open = true; });
  await big.click('.county-group[data-county="Wayne"] .group-more');
  results.scaleListAfterMore = await big.evaluate(() => ({
    cards: document.querySelectorAll('.county-group[data-county="Wayne"] .prop-card').length,
    groupMore: (document.querySelector('.county-group[data-county="Wayne"] .group-more') || {}).textContent
  }));
  await big.fill('#searchInput', '90012345');
  await big.waitForTimeout(700);
  results.scaleSearch = await big.evaluate(() => [...document.querySelectorAll('.prop-card .prop-parcel-line, .prop-card')].length > 0 && document.querySelectorAll('.prop-card').length);
  await big.fill('#searchInput', '');
  await big.waitForTimeout(500);
  await big.evaluate(() => { location.hash = '#/map'; });
  await big.waitForTimeout(1200);
  await big.selectOption('#mapCountySelect', 'Wayne');
  await big.waitForTimeout(1500);
  results.scaleMapCounty = await big.evaluate(() => {
    const c = document.getElementById('exploreMapCanvas');
    const clusters = [...c.querySelectorAll('.pin-cluster')];
    const sum = clusters.reduce((a, g) => a + Number(g.dataset.count), 0);
    const pins = c.querySelectorAll('.map-pin').length;
    const strip = document.getElementById('exploreStrip');
    return { mode: c.dataset.pinMode, inView: Number(c.dataset.pinsInView), everyRowCounted: sum + pins === Number(c.dataset.pinsInView),
      nodesUnder500: clusters.length + pins < 500, strip: strip ? strip.dataset.listed + '/' + strip.dataset.total : null,
      stripCards: document.querySelectorAll('.strip-card').length };
  });
  await big.click('#exploreMapCanvas .pin-cluster');
  await big.waitForTimeout(1200);
  results.scaleMapClusterZoom = await big.evaluate(() => {
    const c = document.getElementById('exploreMapCanvas');
    return { fewerInView: Number(c.dataset.pinsInView) < 30001, back: (document.getElementById('exploreZoomOut') || {}).textContent };
  });
  await big.close();
}

await browser.close();

// ============================================================
// Assertions - EXPECTED is a locked-in snapshot of known-good behavior.
// A `RegExp` value means "must match this pattern" (used for the handful of
// fields that legitimately vary with the real calendar date); anything else
// is checked for strict equality (arrays/objects via JSON comparison).
// ============================================================


const EXPECTED = {
  // Boot resilience (2026-10-03).
  bootFallback: { authGate: true, source: "local", noted: true, panel: false },
  bootStalled: { panel: true, buttons: ["Reload", "Reset app cache and reload"], mentionsAppJs: true },
  bootNormalNoPanel: true,
  // Scale regression (2026-10-02): 30,002-row Wayne County.
  scaleListInitial: {"cardsInDocument": 50, "wayneCount": "30006/30006 active", "groupMore": "Show next 50 · showing 50 of 30,006", "tableRows": 200, "tableMore": "Show next 200 · showing 200 of 30,006", "domUnder15k": true},
  scaleListAfterMore: {"cards": 100, "groupMore": "Show next 50 · showing 100 of 30,006"},
  scaleSearch: 1,
  scaleMapCounty: {"mode": "clusters", "inView": 30005, "everyRowCounted": true, "nodesUnder500": true, "strip": "100/30006", "stripCards": 100},
  scaleMapClusterZoom: { fewerInView: true, back: '← All of Wayne' },
  // Detroit customer subset + Available as the default inventory (2026-10-03).
  detroitSubsetAdmin: {"ids": ["pmi_dlba1", "pmi_dlba2", "pmi_dlbs1", "pmi_dlbs2", "pmi_dlbs3", "pmi_dlbs4"], "reasons": {"pmi_dlba1": "not_structure", "pmi_dlba2": "not_structure", "pmi_dlbs1": "in_subset", "pmi_dlbs2": "in_subset", "pmi_dlbs3": "not_selected", "pmi_dlbs4": "not_selected"}, "chips": ["not_selected", "not_selected", "not_structure", "not_structure"], "chipText": "Not included in current Detroit customer subset", "note": "Detroit Land Bank: 6 collected · 4 with a verified structure in the source's own status · 2 in the customer subset (deterministic ~50%). You see every collected record; those outside the subset are labelled and stay collected. The subset still passes the publication gate: source review is separate.", "statusesUntouched": true},
  detroitSubsetPreview: {"ids": ["pmi_dlbs1", "pmi_dlbs2"], "note": "Detroit Land Bank: 6 collected · 4 with a verified structure in the source's own status · 2 in the customer subset (deterministic ~50%). Only the customer subset is shown here. The subset still passes the publication gate: source review is separate.", "reviewChips": 2, "subsetChips": 0},
  detroitSubsetPreviewMap: ["pmi_dlbs1", "pmi_dlbs2"],
  detroitSubsetVectors: {"cases": 50, "mismatches": []},
  availDefaultLanding: {"FL": {"hash": "#/lands", "activeTab": "laft", "cards": true, "ledgers": ["laft"]}, "LA": {"hash": "#/lands", "activeTab": "laft", "cards": true, "ledgers": ["laft"]}, "WY": {"hash": "#/auctions", "activeTab": "auction", "cards": false, "ledgers": []}},
  // Acquisition-path semantics (2026-10-03): Horry's county-wide bid-form PDF.
  acqPathHorryDetail: { modes: ['bid'], saysOnline: false, saysPropertyLink: false, saysBid: true,
    pdfLinks: ['Download bid form', 'County process page →', 'Application form to download (published by the source) →', 'Application / purchase instructions →'],
    pathEvidence: true },
  // Collection vs customer publication (2026-10-02).
  devVisAdminMiLands: {"cards": 6, "reviewChips": ["Source review: Unreviewed · not customer-published", "Source review: Unreviewed · not customer-published", "Source review: Unreviewed · not customer-published", "Source review: Unreviewed · not customer-published", "Source review: Unreviewed · not customer-published", "Source review: Unreviewed · not customer-published"], "programs": ["Marketed Structure For Sale", "Marketed Structure For Sale", "Marketed Structure For Sale", "Marketed Structure For Sale", "Own It Now", "Side Lot For Sale"], "pending": "6 records from sources awaiting customer-publication review are shown to you as an admin, each labelled \"Source review\". Customers in published mode do not see them.", "withheld": null},
  devVisAdminDetail: {"banner": "Source review: Unreviewed. This record comes from a source awaiting customer-publication review - shown to you as an admin. It is not customer-published. Its availability below is the source's own statement and is a separate fact.", "reviewRow": "Source publication review: Unreviewed Customer-visible: No (shown to you as an admin) Source program / status: Side Lot For Sale Detroit customer subset: Not included in current Detroit customer subset - no structure in the source's own status (vacant lot or program record) · structure evidence: none in the source's status", "identifier": true, "program": true, "lastRead": true, "neverApproved": true},
  devVisAdminDash: {"mode": "Customer mode: customers see approved sources only; you see every collected source, labelled. 2 sources awaiting customer-publication review in Michigan.", "lots": "mi_detroit_landbank_lots Available Source review: Unreviewed5 collected · 5 active · 1 countyCustomer-visible: 0Customer subset: 2 of 4 with a verified structureLast read Oct 3, 2026", "programs": "mi_detroit_landbank_programs Available Source review: Unreviewed1 collected · 1 active · 1 countyCustomer-visible: 0Customer subset: 0 of 0 with a verified structureLast read Oct 2, 2026"},
  devVisCustomerDashPanel: false,
  devVisCustomerMiLands: { cards: 0, reviewChips: [], programs: [], pending: null, withheld: '2 records withheld - source not approved for customer publication (restricted or not yet reviewed). Counted, not shown.' },
  devVisCustomerScLands: { cards: 0, reviewChips: [], programs: [], pending: null, withheld: '1 record withheld - source not approved for customer publication (restricted or not yet reviewed). Counted, not shown.' },
  devVisPreviewScLands: { cards: 1, reviewChips: ['Source review: Unreviewed · not customer-published'], programs: [], pending: '1 record from sources awaiting customer-publication review is shown in customer preview mode, each labelled "Source review". Customers in published mode do not see it.', withheld: null },
  // AVAILABLE coverage: the zero names its reason; Florida (rows present) shows none.
  availCoverage: {
    MI: { status: 'REVIEW_REQUIRED', text: 'Why this list is empty: Official program pages were found but are awaiting capture and publication review. Nothing is published from them yet. 4 candidate sources: Lenawee, Oceana, Wayne. Current list found, awaiting publication review: Lenawee.', cards: 0 },
    CO: { status: 'NO_QUALIFYING_PROGRAM', text: 'Why this list is empty: No qualifying government-held inventory - this state\'s post-sale instrument is a lien or an auction, not property held for purchase. Unsold parcels stay with the county as tax liens / certificates (see Liens & Certificates or Auctions).', cards: 0 },
    WY: { status: 'NO_QUALIFYING_PROGRAM', text: 'Why this list is empty: No qualifying government-held inventory - this state\'s post-sale instrument is a lien or an auction, not property held for purchase. Unsold parcels stay with the county as tax liens / certificates (see Liens & Certificates or Auctions).', cards: 0 },
    FL: { status: null, text: '', cards: 2 }
  },
  // Multi-state product branding (2026-10-02).
  brandGate: {"index.html": {"tagline": "Tax Sale Property Intelligence", "sub": true, "loginNoState": true, "signupNoState": true, "resetNoState": true, "titleNoState": true}, "tx.html": {"tagline": "Tax Sale Property Intelligence", "sub": true, "loginNoState": true, "signupNoState": true, "resetNoState": true, "titleNoState": true}, "la.html": {"tagline": "Tax Sale Property Intelligence", "sub": true, "loginNoState": true, "signupNoState": true, "resetNoState": true, "titleNoState": true}, "mi.html": {"tagline": "Tax Sale Property Intelligence", "sub": true, "loginNoState": true, "signupNoState": true, "resetNoState": true, "titleNoState": true}, "wy.html": {"tagline": "Tax Sale Property Intelligence", "sub": true, "loginNoState": true, "signupNoState": true, "resetNoState": true, "titleNoState": true}},
  brandSwReload: { ready: true, controlled: true, tagline: "Tax Sale Property Intelligence", noState: true, cache: ["tdw-shell-v75"] },
  brandShell: { shellNoOtherState: true, dataSourcesHead: true, title: "Auctions · Tax Acquisitions — Michigan" },
  brandMiWhat: { michigan: true, noFlorida: true },
  brandFlContext: { title: "Available · Tax Acquisitions — Florida", floridaCopy: true },
  brandTxContext: { title: "OTC Catalog — Struck-Off Inventory · Tax Acquisitions — Texas", ledgerTab: "laft", hash: "#/lands" },
  brandStateSwitch: { file: "wy.html", hash: "#/lands", state: "WY" },
  brandEmptyState: { says: true, neverUnsupported: true, stillListed: true, selected: "WI" },

  webpImageRenders: '160x120',
  // Customer monitoring sprint (2026-10-01)
  monPagedSameCards: true,
  monPagedMoreCalls: true,
  monParityMismatches: [],
  monAlertsBadge: '1',
  monSsStorage: 'Saved to your account. The s',
  monSsItems: 1,
  monSsCounts: '2 matching · 0 new · 0 changed · 0 no longer matching',
  monSsAlertsToggle: 1,
  monSsAppliedLedger: 'laft',
  monFiltersRow: 7,
  monWatchedCards: ['p15', 'p3'],
  monAcqVerifiedCards: ['p15', 'p3'],
  monResetClearsAcq: 'any',
  monCsvHas: true,
  monDetailSection: 1,
  monDetailStatus: 'On your watchlist.',
  monDetailHistory: ['acquisition_path_changed', 'removed'],
  monDetailNeverSold: true,
  monDetailNavPill: 1,
  monAlertItems: 2,
  monAlertEmailDisabled: true,
  monAlertsBadgeAfterRead: true,
  monWatchServerChanges: 2,
  monAnalyticsEvents: ['search_performed', 'session_start'],
  monAnalyticsNoText: true,
  monNoneHistory: 'Server change history is not enabled on this deployment yet (migration 024 has not been applied).',
  monNoneStorage: 'Saved in this browser only - t',
  monNoneCounts: ['2 matching', '1 new', '1 changed', '1 no longer matching'],
  monNoneRemovedWording: '9 Gone Rd · Bay · no longer in the current data - not a sale',
  monNoneAlertsToggle: 0,
  monNoneCountsAfterSeen: ['2 matching', '0 new', '0 changed', '0 no longer matching'],
  monNoneAlerts: 1,
  monNoneRuns: 1,
  monDashRuns: ['fl_realauction:812 observed / 14 new / 40 changed / 9 no longer listed', 'fl_laft_html:120 observed / 3 new / 5 changed / 2 no longer listed / 1 listed again'],
  acqWithheldLineCount: 0,
  acqP16State: 'none',
  acqP16Rows: ['Acquisition path | Not yet verified', 'Official availability source | Open official source →', 'How to acquire | See the official source for current instructions.'],
  acqP16SourceHref: 'https://taxsales.lgbs.com/',
  acqP16NoCta: 0,
  acqP16PendingNotError: true,
  acqP3Heads: ['Why this property is available', 'How to acquire'],
  acqP3Cta: 'Contact county to purchase | mailto:taxdeeds@bayclerk.example.gov',
  acqP3Labels: ['Method', 'Instructions', 'Handled by', 'Official source', 'Last verified', 'Applies to'],
  acqP3Availability: 'View official availability → | https://x/list.pdf',
  acqP3FirstSection: 'acquire',
  acqP3NoScoreWords: true,
  acqTxWhy: 'Struck off to the taxing units after a tax sale drew no sufficient bid (status published by the listing: "Struck off to Jurisdiction").',
  acqTxCta: 'View purchase instructions | https://www.galveston.example.gov/sheriff-sale-information',
  acqTxAvailability: 'View the tax-sale listing (delinquent-tax counsel) → | https://taxsales.lgbs.com/',
  acqTxOfficial: 'Sheriff Sale Information (fixture) → | https://www.galveston.example.gov/sheriff-sale-information',
  acqTxVerified: 'Oct 1, 2026',
  appVisible: true,
  typeDropdownOpenOnLoad: false,
  countyDropdownOpenOnLoad: false,
  countyGroupOpenOnLoad: false,
  countyGroupCount: 9,
  // Tab labels became page names ("Auctions", not "Tax Deeds / Auctions") and
  // each carries a leading icon span - now an inline aria-hidden <svg>, not
  // an emoji character, so it contributes no text and allTextContents()
  // returns the bare label.
  // Auctions is 9, not 11: the tab counts what the ledger will actually show,
  // so the past-due row (archive-only) and the gone row whose grace period has
  // expired are both excluded. Neither is reachable from this tab, and
  // advertising them made the number disagree with the list underneath it.
  ledgerTabCounts: ['Auctions 9', 'Available 2', 'Liens & Certificates 1'],
  auctionTabOnByDefault: true,

  // --- per-ledger pages ---
  freshnessBadgesForNormalUser: 0,
  countyGroupsPresentForThatCheck: true,
  // Gone for everyone now, admin included.
  freshnessBadgesForAdmin: 0,
  desktopAuctionListSingleColumn: true,
  desktopAuctionModalDocksRight: true,
  // Phase 20 regression coverage for the desktop persistent panel surface -
  // same fixture property and same math as the modal's calcInitial*/calc*AfterInput
  // checks above, read from #detailPanel's own result elements instead.
  // NOTE: this is a different fixture property than the mobile-viewport
  // modal check above (the desktop block navigates fresh to #/auctions and
  // opens whichever card sorts first there), so the dollar figures differ -
  // what matters, and is what this regression test actually verifies, is
  // that adding $5,000 repair + $1,000 lien buffer moves both results down
  // by exactly that $6,000 combined amount, which it does here.
  detailPanelCalcDrawerPresent: 1,
  detailPanelCalcInitialMaxBid: '$47,200',
  detailPanelCalcInitialNet: '+$106,893',
  detailPanelCalcNetAfterInput: '+$100,893',
  detailPanelCalcMaxBidAfterInput: '$41,200',
  // Single column, not multi: the explore-shell's "split" view (list + county
  // map, the default at >=1024px - see explore.js's storedMode()) narrows
  // #main's own column well below the 360px x2 the LAFT grid rule
  // (minmax(360px,1fr) auto-fill) needs to ever produce a second track at
  // this test's 1280px viewport. The multi-column CSS rule itself is
  // untouched; the map split view just leaves it no room to fire.
  desktopLaftListIsMultiColumn: false,
  desktopCertListSingleColumn: true,
  desktopCertCardIsRow: true,
  watchlistChipLabel: 'Watchlist 0/10',
  ledgerHashes: ['#/auctions', '#/lands', '#/certificates'],
  ledgerDocAttr: ['auction', 'laft', 'certificate'],
  ledgerHeadings: ['Auctions', 'Available', 'Liens & Certificates'],
  ledgerTitles: [
    'Auctions · Tax Acquisitions — Florida',
    'Available · Tax Acquisitions — Florida',
    'Liens & Certificates · Tax Acquisitions — Florida'
  ],
  everyLedgerHasHowLine: true,
  everyLedgerHasFactsLine: true,
  ledgerAccentsAllDifferent: true,
  certHidesTypeLienAssessed: [true, true, true],
  auctionKeepsTypeLienAssessed: [false, false, false],
  archiveRowHiddenPerLedger: [false, true, true],
  archiveRowVisuallyHiddenPerLedger: [false, true, true],
  // sea rect, 3 neighbouring states, 4 orientation labels, 67 counties
  basemapLayers: '1,3,4,67',
  basemapViewBox: '-120 -130 1170 1115',
  railMatchesBubbles: true,
  railIsSortedDescending: true,
  railHiddenWhenZoomed: true,
  contextLabelsHiddenWhenZoomed: true,
  mastheadLeftovers: '',
  topbarHasBrandAndAccount: true,
  mastheadHasNoBrandOrAccount: '',
  generatedLivesInTerms: true,
  cardsWithoutExactlyOneStatus: 0,
  cardsOnScreenForThatCheck: true,
  staleCardsPresent: true,
  legendSwatchCount: 3,
  deepLinkLandsOnCertificates: true,
  deepLinkHeading: 'Liens & Certificates',
  cardCount: 9,
  // All 67 counties now show (busiest-first, then alphabetical among the
  // zero-count ones) instead of only the ~8 with live scraped data - see
  // ALL_COUNTIES in app.js.
  countyChipLabels: ['Alachua (3)', 'Duval (2)', 'Escambia (2)', 'Marion (2)', 'Baker (1)', 'Bay (1)', 'Brevard (1)', 'Charlotte (1)', 'Citrus (1)', 'Bradford (0)', 'Broward (0)', 'Calhoun (0)', 'Clay (0)', 'Collier (0)', 'Columbia (0)', 'DeSoto (0)', 'Dixie (0)', 'Flagler (0)', 'Franklin (0)', 'Gadsden (0)', 'Gilchrist (0)', 'Glades (0)', 'Gulf (0)', 'Hamilton (0)', 'Hardee (0)', 'Hendry (0)', 'Hernando (0)', 'Highlands (0)', 'Hillsborough (0)', 'Holmes (0)', 'Indian River (0)', 'Jackson (0)', 'Jefferson (0)', 'Lafayette (0)', 'Lake (0)', 'Lee (0)', 'Leon (0)', 'Levy (0)', 'Liberty (0)', 'Madison (0)', 'Manatee (0)', 'Martin (0)', 'Miami-Dade (0)', 'Monroe (0)', 'Nassau (0)', 'Okaloosa (0)', 'Okeechobee (0)', 'Orange (0)', 'Osceola (0)', 'Palm Beach (0)', 'Pasco (0)', 'Pinellas (0)', 'Polk (0)', 'Putnam (0)', 'Santa Rosa (0)', 'Sarasota (0)', 'Seminole (0)', 'St. Johns (0)', 'St. Lucie (0)', 'Sumter (0)', 'Suwannee (0)', 'Taylor (0)', 'Union (0)', 'Volusia (0)', 'Wakulla (0)', 'Walton (0)', 'Washington (0)'],
  filtersOpenAfterClick: true,
  brevardGroupMeta: /^Auction [A-Z][a-z]{2} \d{1,2}, \d{4}$/,
  brevardGroupCount: '1/1 active',
  alachuaGroupMeta: /^Auction [A-Z][a-z]{2} \d{1,2}, \d{4}$/,
  expandAllLabelBeforeClick: 'Expand all',
  expandAllLabelAfterClick: 'Collapse all',
  allCountyGroupsOpenAfterExpandAll: true,
  brevardCardVisibleAfterExpandAll: true,
  // Phase 72: kind-driven FL card CTA
  flCardCtaSale: { kind: 'sale' },
  flCardCtaSaleText: /^View sale listing for [A-Z][a-z]{2} \d{1,2}, \d{4}$/,
  flCardCtaProperty: { text: 'View property listing', kind: 'property' },
  flCardCtaInfo: { text: 'View county tax-sale information', kind: 'info' },
  flCardCtaNoKind: { text: 'View listing', kind: 'unknown' },
  brevardBannerPill: 'Online',
  brevardBannerText: 'Deposit required in advance via the auction site.',
  charlotteBannerPill: 'Note',
  charlotteBannerText: 'Shared site with foreclosure sales - confirm you are on a TAXDEED auction.',
  bakerBannerCount: 0,
  brevardOpenAfterManualCollapse: false,
  brevardOpenAfterManualReopen: true,
  bidMinCardCountAfter: 2,
  bidMinBeforeCount: 9,
  priceMinInputFollowsSlider: '10000',
  priceMaxInputBlankWhenUncapped: '',
  priceMinSnappedToTypedMax: '9000',
  priceSliderMaxWithinStepOfTypedMax: true,
  priceCardCountAtTypedNineThousandBoth: 1,
  // Auction-ledger bids at or under $9,000: 5000, 8000, 3000, 6000, 4500,
  // 7000, 9000 (p3's $2,000 is Lands Available; p13 is past due; p2 closed).
  priceCardCountAfterEnterMinZero: 7,
  priceMinInputBlurredAfterEnter: true,
  priceCardCountAfterClearingMax: 9,
  priceSliderMaxBackToTrackEnd: '1000000',
  priceSearchButtonAbsent: true,
  // p1 (auction) + p4 (certificate); p13 is past due and computeMapRows()
  // excludes it, same as dashboardStats().
  stripCardCountForAlachua: 2,
  stripCardSelCountAfterClick: 1,
  previewVisibleAfterStripClick: true,
  previewTitleMatchesStripCard: true,
  pinSelMatchesStripSel: true,
  stripHoverLinksToPinWhenPresent: true,
  previewHiddenAfterSecondStripClick: true,
  stripCardSelCountAfterToggleOff: 0,
  // Phase 66: county + state lead the line on every card. p1's sale_date is
  // "today + 3", so the date itself moves.
  cardKickerFirst: /^Alachua, FL · Auction · Sale [A-Z][a-z]{2} \d{1,2}, \d{4}$/,
  cardKickerPhaseClassFirst: 'phase-soon',
  cardCaseLineFirst: 'Case A-1',
  cardFactsFirst: ['Location Not yet geocoded', 'Flood Not checked', 'Value ÷ bid 18.0×'],
  cardFactsMutedCountFirst: 2,
  laftKicker: 'Bay, FL · Available · Lands Available list · fixed price',
  laftLedgerLine: ['Purchase path No online purchase link on file', 'Amount Opening bid'],
  availFiltersHiddenOnAuctions: true,
  availFiltersShownOnAvailable: true,
  ledgerWithheldText: '1 record withheld - source not approved for customer publication (restricted or not yet reviewed). Counted, not shown.',
  withheldRowNeverRendered: 0,
  availFilterCounts: { pathNone: 1, pathOnline: 0, amountPublished: 1, amountUnpublished: 1, statusAvailable: 2, statusClosed: 0, acreageHalf: 1, acreageTwo: 0, seenRecently: 1, afterReset: 2 },   // p3 (Bay) + p15 (Citrus): p15 has an instructions link, no published amount, 0.3 ac, read 10 days ago
  flAvailabilityEvidence: [
    'Availability evidence | LIST_PRESENCE: on the county\'s Lands Available list at the last read (F.S. 197.502(7)) · observed Aug 11, 2026',
    'Last verified | Read from the source Aug 11, 2026',
    'Source date | List dated Aug 10, 2026',
    'Purchase link source | No online purchase link on file',
    "Path evidence | Phone or mail process (published by the source; no online path) \u00b7 source-level \u00b7 Clerk's Lands Available page: call or e-mail the Tax Deed department for the current amount (fixture) \u00b7 observed Sep 30, 2026"   // acquisition-path sprint: p3 carries a verified county process (the gate withholds untyped rows)
  ],
  flProvLegendCount: 1,
  flPurchaseModeLine: "How to purchase | Phone or mail process (published by the source; no online path)",
  dashLedgerWithheldAvailable: '1 withheld (source not approved for publication)',
  dashLedgerWithheldAuctionsAbsent: 0,
  dashUnitBayUnavailable: '1',
  bayStripCardCount: 1,
  bayPinCount: 0,
  bayPreviewHasAvailability: true,
  bayPreviewHasPurchasePath: true,
  bayPreviewHasAmountKind: true,   // p3's purchase_amount_kind is OPENING_BID (the list's own label)
  cardLedgerLineFirst: ['Auction result Sale not yet held'],
  // Phase 66: "At a glance" summary + section nav + photo states + show-on-map
  oppCellLabels: ['What', 'Where', 'When', 'Minimum bid', 'Value on file', 'Missing'],
  oppWhatText: 'Florida tax deed auction Source: Fl Realauction Alachua',
  oppWhereText: '1 Main St Alachua County, FL · Parcel 111 · Case A-1',
  oppWhenClass: 'opp-val warn', // p1 sells in 3 days - inside SOON_DAYS
  oppBidText: '$5,000.00 Value ÷ bid 18.0× (screening ratio, not a return)',
  oppValueText: '$90,000 2025 County Just Value · County Assessed Value $80,000',
  oppGaps: ['Image not checked yet', 'Not yet geocoded', 'Flood zone not checked'],
  detailNavLabels: ['Summary', 'Decision', 'Financial', 'Property', 'History', 'Sale events', 'Watch', 'Risk & Legal', 'Map', 'Sources', 'Data'],   // customer-value sprint: the Auction decision block
  detailNavJumpScrolled: true,
  detailNavJumpMarksPill: true,
  showOnMapBtnText: 'Show county on the Map page',
  photoCardHasPhoto: 1,
  photoCardCaption: 'Aerial image · USDA NAIP',
  photoCardBannerHeightCapped: true,
  photoNotCheckedText: 'Image not checked yet',
  photoNoCoverageText: 'Checked - no stored image for this address',
  cardMoreClosedByDefault: true,
  cardMoreSummaryText: 'More · last sale, legal description',
  noHorizontalOverflowMobile: true,
  iconBtnHitAreaMobile: true,
  showOnMapClosesModal: true,
  showOnMapOpensMapPage: true,
  showOnMapCountySelect: 'Alachua',
  showOnMapCanvasZoomed: true,
  showOnMapPreviewVisible: true,
  showOnMapPreviewTitle: '1 Main St',
  showOnMapStripSelCount: 1,
  // Phase 67: map workspace, pin selection, imagery hierarchy
  placeholderLocationText: 'Not yet geocoded',
  mapToolbarHoldsBasemapToggle: 1,
  mapWorkspaceTwoColumns: true,
  mapStageTallDesktop: true,
  mapSvgFillsStageHeight: true,
  mapSidePanelVisible: true,
  mapImageryToggleHiddenOnOutline: true,
  mapOldCardHeadGone: 0,
  charlottePinCount: 1,
  stripVerticalOnDesktop: true,
  stripInSidePanel: 1,
  pinClickPreviewTitle: '500 Elm Way',
  pinClickPreviewInSidePanel: 1,
  pinClickPinSel: 1,
  pinClickHalo: 1,
  pinClickStripSel: 1,
  previewKicker: /^Charlotte County, FL · Auction · Sale [A-Z][a-z]{2} \d{1,2}, \d{4}$/,
  previewCoords: '26.93420, -82.04540',
  previewBid: '$8,000.00',
  previewValueLabel: 'County Just Value',
  previewIds: ['444', 'D-1'],
  previewFlood: 'Not checked',
  previewMoreClosed: true,
  // Phase 72: the map preview's auction link (p5, kind 'sale')
  previewAuctionLinkText: /^View sale listing for [A-Z][a-z]{2} \d{1,2}, \d{4} ↗$/,
  previewAuctionLinkKind: 'sale',
  previewAuctionLinkHref: /^https:\/\/charlotte\.realforeclose\.com\/index\.cfm\?zaction=AUCTION&zmethod=PREVIEW&AuctionDate=\d{2}\/\d{2}\/\d{4}$/,
  selectionEventPid: 'p5',
  selectionEventHasCoords: true,
  previewHiddenAfterClose: true,
  pinSelClearedAfterClose: 0,
  stripSelClearedAfterClose: 0,
  selectionEventClearedPid: null,
  stillZoomedAfterClose: true,
  switchPreviewTitle: '42 Palm Ave',
  switchPinSelPid: 'p12',
  geocodedCardVisualClass: true,
  minimapHydrated: 1,
  minimapHasDot: 1,
  minimapCaption: 'Location in Charlotte County',
  minimapNeighborsDrawn: true,
  staticUrlMaptiler: 'maptiler|true',
  staticUrlGoogle: 'google|true',
  staticUrlPrefersMaptiler: 'maptiler',
  staticUrlNoCoords: null,
  staticUrlNoKey: null,
  mapStageTallMobile: true,
  mapNoOverflowMobile: true,
  mobilePreviewInStage: 1,
  mobilePreviewCollapsed: true,
  mobilePreviewBodyHiddenCollapsed: true,
  mobilePreviewCoversLessThanHalfStage: true,
  mobilePreviewExpanded: true,
  mobilePreviewBodyVisibleExpanded: true,
  mobileStripStillReachable: true,
  mapNoOverflowMobileSelected: true,
  sortByBidDescFirst: '$11,000', // Phase 65: whole-dollar bids drop the ".00" on the card (bidDisplayCard)
  deedCardBidsWithCents: 0,      // Phase 71: the card headline always rounds to a whole dollar
  deedCardBidsChecked: 9,
  sortByHasInterestOption: true,
  sortByHasExpSoonOption: true,
  cardCountAfterInterestSort: 9,
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
  // Phase 19: the map moved from a toggle inside this same County dropdown
  // to its own full-page destination (origin/main's app-shell rebuild).
  // Phase 53: that dedicated Map page was folded into a virtual route into
  // Auctions with explore.js's map view active (one map, not two).
  // Phase 54: Map is a real top-level page again (#pageMap), with its own
  // toolbar independent of the Auctions page's filters - see the Phase 54
  // comment above the test steps that produce these.
  auctionsPageVisibleBeforeMapNav: true,
  auctionsPageVisibleOnMapNav: false,
  mapPageVisibleOnMapNav: true,
  navMapBtnOnAfterMapNav: true,
  mapPageTitle: 'Map',
  navRailItems: ['dashboard:Dashboard', 'list:List 12', 'map:Map', 'watchlist:Watchlist 0/10'],
  navBottomItems: ['dashboard', 'list', 'map', 'watchlist'],
  navLedgerEntriesGone: 0,
  navDashboardLit: ['dashboard'],
  navDashboardHash: '#/dashboard',
  navListClickShowsListPage: true,
  navListClickLit: ['list'],
  navListClickHash: '#/auctions',
  tabCertHash: '#/certificates',
  tabCertNavLit: ['list'],
  tabCertHeading: 'Liens & Certificates',
  tabLaftHash: '#/lands',
  tabLaftHeading: 'Available',
  navListCountIsSum: true,
  listHasNoStateTabs: true,
  navWatchlistOpen: true,
  navWatchlistLit: ['watchlist'],
  navWatchlistHash: '#/watchlist',
  navWatchlistClosedLit: ['list'],
  navWatchlistClosedHash: '#/lands',
  navWatchlistClosedListVisible: true,
  navMapDeepVisible: true,
  navMapDeepLit: ['map'],
  navMapDeepLaftPill: true,
  navMapDeepCounty: 'Bay',
  navMapDeepContext: 'Ledger: Available · County: Bay County',
  navMapDeepHash: '#/map?ledger=laft&county=Bay',
  navMapStateOptions: ['FL:Florida', 'TX:Texas', 'LA:Louisiana', 'MI:Michigan', 'WY:Wyoming', 'SC:South Carolina', 'CO:Colorado', 'WI:Wisconsin', 'MO:Missouri', 'OK:Oklahoma', 'PA:Pennsylvania', 'MN:Minnesota'],
  navMapStateValue: 'FL',
  adminAnonRedirected: true,
  adminAnonShellShown: false,
  adminNormalAppVisible: true,
  adminNormalMenuLinkHidden: true,
  adminNormalRedirected: true,
  adminTamperRedirected: true,
  adminTamperShellShown: false,
  adminBadCredsError: true,
  adminBadCredsAppHidden: true,
  adminBadCredsRedirected: true,
  adminAppVisible: true,
  adminMenuLinkShown: true,
  adminShellShown: true,
  adminIdentityText: 'Admin',
  adminShellShowsNoEmail: true,
  adminSourcesRows: 347,
  adminSourcesGovernanceKinds: 'APPROVED,HARD_BLOCKED,REVIEW_REQUIRED',
  adminSourcesStatusText: '347 source(s): 221 approved, 111 review required, 15 hard blocked.',
  adminSourcesReviewOnly: true,
  adminSourcesLgbsReason: true,
  adminSourcesLaOnly: true,
  adminSourcesNoticeRows: 3,
  adminSignOutRedirected: true,
  adminAfterSignOutRedirected: true,
  signupFormOffered: true,
  signupButtonText: 'Create account',
  signupAnonAdminRedirected: true,
  signupPendingShown: true,
  signupPendingText: 'Account created \u2014 awaiting approval.',
  signupAppHidden: true,
  signupAuthMsgNotSignupsDisabled: true,
  signupProfile: { approved: false, is_admin: false },
  signupNoLedgerRowsRendered: true,
  signupPendingAdminRedirected: true,
  signupSelfPromote: { rowsChanged: 0, after: { approved: false, is_admin: false } },
  signupPendingSeesOnlyOwnRow: ['newcomer@example.com'],
  signupTamperStillPending: true,
  signupTamperAdminRedirected: true,
  signupMetadataIgnored: { approved: false, is_admin: false },
  signupAdminAppVisible: true,
  signupAdminShellShown: true,
  signupAdminIdentityNoEmail: true,
  signupAdminPendingList: ['newcomer@example.com', 'sneaky@example.com'],
  signupAdminPendingStatus: '2 accounts are waiting for approval.',
  signupAdminPendingAfterApprove: ['sneaky@example.com'],
  signupAdminApproveRowsChanged: 1,
  signupApprovedAppVisible: true,
  signupApprovedPendingHidden: true,
  signupApprovedLedgerRows: true,
  signupApprovedAdminLinkHidden: true,
  signupApprovedProfile: { approved: true, is_admin: false },
  signupApprovedAdminRedirected: true,
  signupApprovedAdminShellShown: false,
  signupDisabledMsg: 'New account registration is closed right now, so this account was not created. Please try again later or contact support.',
  signupDisabledNoSession: true,
  laBodyState: 'LA',
  laTitle: 'Available — Adjudicated Property · Tax Acquisitions — Louisiana',
  laStateSelect: { value: 'LA', options: ['FL', 'TX', 'LA', 'MI', 'WY', 'SC', 'CO', 'WI', 'MO', 'OK', 'PA', 'MN'] },
  xsPages: Object.fromEntries([['MI', 'Michigan'], ['WY', 'Wyoming'], ['SC', 'South Carolina'], ['CO', 'Colorado'], ['WI', 'Wisconsin'],
    ['MO', 'Missouri'], ['OK', 'Oklahoma'], ['PA', 'Pennsylvania'], ['MN', 'Minnesota']].map(([c, n]) => [c,
    { state: c, title: `Auctions · Tax Acquisitions — ${n}`, select: c, options: ['FL', 'TX', 'LA', 'MI', 'WY', 'SC', 'CO', 'WI', 'MO', 'OK', 'PA', 'MN'], floridaWording: false, basemapOk: true }])),
  xsMiCard: { count: 1, county: true, sev: true, noJustValue: true },
  xsCoCardCount: true,
  xsCoDetail: { treasurer: true, steps: true, noStreetView: true, noUndefined: true, sourceNamed: true },
  xsCoDouglas: { attribution: true, assignment: true, noStreetView: true, noUndefined: true },
  xsScProcess: { question: true, mode: true, steps: true, phone: true, countyLevel: true, notPurchasePath: true, page: true, noReviewRow: true },
  xsScExport: { processCol: true, reviewCol: true, processCell: true, phoneCell: true, approvedCell: true },
  txReviewAuction: { reviewRow: true, text: true },
  txReviewLaft: { reviewRow: true, provenanceLabel: true },
  xsCoAuctionCopy: true,
  xsCoMarketProvenance: { label: true, source: true, method: true },
  laEnriched: { office: true, confirmFirst: true, noVendor: true, stillDated: true, landSource: true, landMethod: true, noUndefined: true },
  laNoStateTabs: true,
  laCardCount: 1,
  laCardSaysListAsOf: true,
  laCardSaysAvailableNow: false,
  laCardSaysParish: true,
  laCardSaysCounty: false,
  laCardValueLabel: true,
  laCardNoUndefined: true,
  laDetailNotVerifiedAvailable: true,
  laDetailInventoryLabel: true,
  laDetailCostNotPublished: true,
  laDetailNoFixedPrice: true,
  gsSelectInHeader: 1,
  gsSelectBesideAccount: "account",
  gsOptions: ["FL:Florida", "TX:Texas", "LA:Louisiana", "MI:Michigan", "WY:Wyoming", "SC:South Carolina", "CO:Colorado", "WI:Wisconsin", "MO:Missouri", "OK:Oklahoma", "PA:Pennsylvania", "MN:Minnesota"],
  gsStateSelectCount: 1,
  gsAccountMenuOpens: true,
  gsFlorida: {"dash": {"file": "index.html", "hash": "#/dashboard", "state": "FL"}, "dashAuctionTile": "9", "dashCountiesSub": "Florida · 12 tracked incl. no-longer-listed", "list": {"file": "index.html", "hash": "#/lands", "state": "FL"}, "listOnlyFlorida": true, "map": {"file": "index.html", "hash": "#/map", "state": "FL"}, "mapPaths": 67, "watch": {"file": "index.html", "hash": "#/watchlist", "state": "FL"}, "watchPids": ["p1"], "watchElsewhere": "1 saved item is not in Florida's current listings (saved under another state, or no longer listed). Switch state in the header to see another state's items."},
  gsTexas: {"list": {"file": "tx.html", "hash": "#/lands", "state": "TX"}, "listLedgerOn": "laft", "listOnlyTexas": true, "listAuctionOnlyTexas": true, "dash": {"file": "tx.html", "hash": "#/dashboard", "state": "TX"}, "dashAuctionTile": "3", "dashCountiesSub": "Texas · 5 tracked incl. no-longer-listed", "map": {"file": "tx.html", "hash": "#/map", "state": "TX"}, "mapPaths": 254, "watch": {"file": "tx.html", "hash": "#/watchlist", "state": "TX"}, "watchPids": ["ptx1"], "watchElsewhere": "1 saved item is not in Texas's current listings (saved under another state, or no longer listed). Switch state in the header to see another state's items.", "watchCount": "2/10", "watchDeletes": 0},
  gsTexasMapCounty: "Harris",
  gsReloadKeepsTexas: true,
  gsReloadMapVisible: true,
  gsMapBackToFlorida: {"file": "index.html", "hash": "#/map?ledger=auction", "state": "FL"},
  gsMapBackPaths: 67,
  gsMapBackCounty: "ALL",
  gsDeepLinkTexas: {"state": "TX", "modal": true},
  gsDeepLinkSwitch: {"file": "index.html", "hash": "#/auctions", "state": "FL", "modal": false},
  gsPhone: {"bothVisible": true, "inViewport": true, "sameRow": true, "selectorFirst": true, "headerCompact": true, "noHorizontalScroll": true, "value": "TX"},
  gsPhoneBottomNav: ["dashboard", "list", "map", "watchlist"],
  navMapHasNoOwnStateSelect: true,
  navMapAllLedgersLabel: 'All Ledgers',
  navMapCertPillLabel: 'Liens & Certificates',
  navMapLaftCountyOptions: ['All Counties (2)', 'Bay (1)', 'Citrus (1)'],
  navMapCertCountyOptions: ['All Counties (1)', 'Alachua (1)'],
  navMapCertCountyValue: 'ALL',
  navMapCertContext: 'Ledger: Liens & Certificates · County: All counties',
  navMapCertHash: '#/map?ledger=certificate',
  navMapCertBubbleCount: 1,
  navMapAllCountyOptions: ['All Counties (8)', 'Alachua (2)', 'Bay (1)', 'Brevard (1)', 'Charlotte (1)', 'Citrus (1)', 'Duval (2)', 'Escambia (2)', 'Marion (2)'],
  navMapAllHash: '#/map',
  navMapSearchHash: '#/map?q=Oak',
  navMapToListHash: "#/lands",
  navMapToListLit: ['list'],
  navListToMapHashKeepsContext: '#/map?q=Oak',
  navLegacyMapVisible: true,
  navLegacyMapHash: '#/map',
  navLandsListVisible: true,
  navLandsHeading: 'Available',
  navLandsLit: ['list'],
  navHashEditDashboardVisible: true,
  navHashEditCertHeading: 'Liens & Certificates',
  navHashEditCertListVisible: true,
  navWatchlistDeepOpen: true,
  navWatchlistDeepLit: ['watchlist'],
  navListRouteVisible: true,
  navListRouteHash: "#/lands",
  navDashDeepVisible: true,
  navDashTiles: ['auction:9', 'laft:2', 'certificate:1', 'counties:8'],
  navDashNoValueTile: true,
  navDashAttention: ['soon:4 properties · 4 sale dates', 'watched-gone:None', 'stale:1 of 2', 'sources:1 unavailable at the last read · 1 in back-off'],
  navDashRecent: ['auction:First-recorded date not trackedPer-row read date not tracked', 'laft:0 first recorded in the last 7 days0 read from the source in the last 7 days', 'certificate:First-recorded date not trackedPer-row read date not tracked'],
  navDashPaths: ["verified:2 of 2", "phone_mail:1", "county_instructions:1", "unverified:0"],   // the Florida fixture rows both carry a verified path
  navDashNoScoreWords: true,
  navDashSubtitle: 'Florida: 12 active properties across 3 ledgers in 8 counties.',
  navDashTileOpensList: true,
  navDashTileHash: '#/lands',
  navDashTileHeading: 'Available',
  navPhoneBottomItems: 4,
  navPhoneBottomFits: true,
  navPhoneBottomLabels: ['Dashboard', 'List', 'Map', 'Watchlist'],
  navWlCards: ['p4'],
  navWlRelated: ['Currently listed in Auctions · also on your watchlist'],
  navWlCount: '2/10',
  mapContextFlorida: 'Ledger: All Ledgers · County: All counties',
  mapHashOnMapNav: '#/map',
  mapPathCount: 67,
  // Portfolio-wide (every ledger) rather than scoped to whatever the
  // Auctions page's ledger tab/filters currently show - see
  // computeMapRows()'s comment in app.js. 7 counties across all three
  // ledgers' fixture rows (not the 6 the old shared-with-Auctions map used
  // to show when this ran right after an auction-ledger-only filter pass).
  mapClusterBubbleCount: 8,
  mapCountySelectValueAfterBubbleTap: 'Alachua',
  mapCanvasZoomedAfterTap: true,
  exploreMapResetVisibleAfterTap: true,
  mapCountySelectValueAfterMapReset: 'ALL',
  mapCanvasZoomedAfterReset: false,
  mapBubbleCountAfterDeadSearch: 0,
  mapLaftPillOnAfterClick: true,
  mapAllPillOffAfterLedgerClick: false,
  // Bay is the fixture's one Lands Available county.
  mapClusterBubbleCountLaftOnly: 2,
  // Phase 55/56/57/60: the three-way Map/Google/MapTiler toggle, exercised
  // against tests/config.js's deliberately blank googleMapsApiKey and
  // maptilerKey - the "not set up yet" path every real deploy hits until a
  // given provider's key is present. See satellite-map.js.
  mapStyleOutlineOnByDefault: true,
  satelliteCanvasHiddenByDefault: true,
  mapStyleGoogleOnAfterClick: true,
  outlineCanvasHiddenAfterGoogleClick: true,
  satelliteCanvasVisibleAfterGoogleClick: true,
  satelliteSetupMessageShownWithNoGoogleKey: true,
  googleMapsNotLoadedWithNoKey: true,
  outlineCanvasVisibleAfterGoogleSwitchBack: true,
  mapClusterBubbleCountAfterGoogleSwitchBack: 8,
  mapStyleMaptilerOnAfterClick: true,
  outlineCanvasHiddenAfterMaptilerClick: true,
  satelliteCanvasVisibleAfterMaptilerClick: true,
  satelliteSetupMessageShownWithNoMaptilerKey: true,
  maplibreGlNotLoadedWithNoKey: true,
  outlineCanvasVisibleAfterMaptilerSwitchBack: true,
  mapClusterBubbleCountAfterMaptilerSwitchBack: 8,
  googleCanvasVisibleAfterGoogleMaptilerGoogleSequence: true,
  maptilerCanvasHiddenAfterGoogleMaptilerGoogleSequence: true,
  mapStyleGoogleOnAfterReturningFromMaptiler: true,
  auctionsPageVisibleAfterReturnFromMap: true,
  viewToggleGoneFromAuctions: 0,
  exploreMapPanelGoneFromAuctions: 0,
  cardsAfterReset: 9,
  alachuaSelAfterReset: false,
  countyGroupsClosedAfterReset: true,
  expandAllLabelAfterReset: 'Expand all',
  cardsAfterHide: 8,
  hiddenListBtnVisible: true,
  laftTabOnAfterClick: true,
  auctionTabOffAfterLaftClick: false,
  laftCardCount: 2,
  laftCountyGroupName: 'Bay',
  laftSpecBits: ['1.00 acres lot'],
  // A different roll year from p1's, so the label is genuinely per-row rather
  // than a constant with a year hardcoded into it.
  laftValueLabel: '2024 County Just Value',
  laftHomesteadBadge: 'Homestead',
  laftBareLandStat: 'None (bare land)',
  junkLandRowVisibleOnLaft: true,
  laftCountBeforeJunkFilters: 2,
  laftCountAfterHideSlivers: 2,
  laftCountAfterHideBareLand: 1,
  laftCountAfterUncheckingFilters: 2,
  laftGroupMeta: 'Lands Available - fixed price, available now',
  certCardCount: 1,
  certCardTitle: 'Certificate #CERT-42',
  certCardAmount: '$1,234.56',
  certCardAccount: 'ACC-999',
  certCardExpires: /^[A-Z][a-z]{2} \d{1,2}, \d{4}$/,
  certCardCta: 'View county-held liens list',
  certCardExpiresCountdown: 1,
  certCardStatCount: 6,
  certCardInterestRate: '18%',
  certCardTdaEligibility: 'Eligible now',
  certCardStatusPill: 'Listed',
  certCardAccruedInterestPlausible: true,
  cardCountBackOnAuctionTab: 8,
  pastDueCardVisibleDefault: 0,
  pastDueCardVisibleAllView: 0,
  pastDueCardVisibleGoneView: 0,
  archiveToggleInFilters: true,
  archiveChipNotInStrip: 0,
  archiveChipCount: '1',
  archiveModeNoteShown: true,
  archiveNoteGoneAfterExit: 0,
  archiveToggleUntickedAfterExit: false,
  pastDueCardVisibleArchiveView: 1,
  archiveViewOtherCardsCount: 1,
  // Day-granular diff between two Date.now() reads in the same test run, so
  // this stays "6d ago" regardless of what day the suite actually runs on.
  archiveCardAgoBadge: '6d ago',
  staleWarningClassPresent: 1,
  staleWarningText: '⚠ Data updated 9/20/2026, 12:00:00 AM - sync may be behind',
  // The value box is named for what the number actually is. It used to read
  // "Est. Market", which implied a live estimate this app has never had and
  // cannot legitimately obtain - the Zestimate API was retired in 2021. It is
  // the county appraiser's statutory just value, and value_year says which
  // roll year, so the label can say so exactly.
  cardStatLabelsFirst: ['Opening Bid', '2025 County Just Value'],
  // 16,456 sq ft is under the 20,000 threshold, so the lot stays in square
  // feet rather than being quoted as 0.38 acres.
  cardSpecBits: ['Built 1958', '1,840 sq ft', '16,456 sq ft lot'],
  cardLastSale: 'Last sold $41,500 in 2011',
  cardLegalIsOneLine: true,
  cardLegalFullTextInTitle: true,
  unenrichedCardExtras: '0,0,0',
  cardParcelLineFirst: 'Parcel # 111',
  spreadBadgeCount: 0,
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
  csvDownloadFilename: /^taxdeed-fl-auction-\d{4}-\d{2}-\d{2}\.csv$/,
  csvTaxRollColumns: true,
  csvValueYearColumn: true,
  csvRowsWellFormed: true,
  csvHomesteadColumn: true,
  csvAccruedInterestColumn: true,
  csvTdaEligibilityColumn: true,
  csvYieldColumnsBlankForP1: true,
  csvHomesteadBlankForP1: true,
  csvEnrichedCells: '90000|2025|1958|1840|16456|1|22000|68000|41500|2011',
  csvLegalUnclamped: true,
  detailStatLabels: [
    'Opening Bid', '2025 County Just Value', 'County Assessed Value', 'Land Value',
    // Phase 35: Building / Improvement Value, Walk Away Above, and Gross
    // Equity Spread all gained an infoTip() marking them as calculated
    // (not county-sourced) - same "label carries an info tooltip glyph"
    // convention "Fees i" already used below.
    'Building / Improvement Value i',
    'Fees i', 'Your ceiling (% setting) i', 'County value minus bid i',
    'Year Built', 'Living Area', 'Lot Size', 'Buildings', 'Last Sale'
  ],
  detailStatValues: '1958 | 1,840 sq ft | 16,456 sq ft | 1 | $41,500 in 2011 | $22,000 | $68,000',
  detailLegalIsFull: true,
  detailNamesBothValues: true,
  homesteadStatAbsentForP1: true,
  muniLienNoteVisible: 1,
  calcDrawerPresent: 1,
  calcInitialMaxBid: '$36,000',
  calcInitialNet: '+$84,935',
  calcNetAfterInput: '+$78,935',
  calcMaxBidAfterInput: '$30,000',
  calcInputPersistsAfterReopen: '5000',
  calcInputNoLeakToOtherProperty: '',
  detailModalVisibleAfterOpen: true,
  detailModalHasAddress: 1,
  detailModalHasLinks: 5,
  detailModalHiddenAfterCloseBtn: true,
  detailModalHiddenAfterBackdropClick: true,
  detailModalHiddenAfterEscape: true,
  topbarBrandVisible: true,
  termsButtonVisible: true,
  termsModalOpens: true,
  termsCarryTitleWarning: true,
  termsModalCloses: true,
  termsSayNotesShared: true,
  termsNoNotesPrivateClaim: true,
  cardStatGridCount: 8,
  lienPillFirstText: 'Lien notes: No flags noted',
  homesteadBadgeAbsentForP1: 0,
  // Phase 35 added 3 more (Building/Improvement Value, Walk Away Above,
  // Gross Equity Spread) alongside the pre-existing Fees/muni-lien/
  // accrued-interest/TDA-eligibility tips.
  infoTipCount: 7,
  linkIconPresent: true,
  toppickBannerText: 'Filter match 18.0× county value ÷ bid · no lien flags noted',
  junkLandRowHiddenOnAuction: true,
  exportBtnLabelAuction: '⬇ Export to Auction Sheet',
  spreadBarPresentP1: 1,
  exportBtnLabelCertificate: '⬇ Export Certificates (CSV)',
  csvCertAccruedPlausible: true,
  csvCertTdaDate: '2025-06-01',
  certDetailHasAccrued: true,
  certDetailHasTotalReturn: true,
  certDetailTdaEligibleNow: true,
  certDetailYieldInfoTips: 2,
  exportBtnLabelLaft: '⬇ Export OTC List (CSV)',
  laftPurchasePriceLabel: 'Purchase Price',
  laftCtaText: 'View county Lands Available list',
  bidListChipTextInitial: '0/10',
  bidBtnIconBefore: '⚐',
  bidBtnIconAfterAdd: '⚑',
  bidListChipTextAfterAdd: '1/10',
  bidListModalVisible: true,
  bidListModalCardCount: 1,
  bidListModalCardCountAfterRemove: 0,
  bidListChipTextAfterRemove: '0/10',
  bidListModalHiddenAfterClose: true,
  // Phase 34: regression coverage for the state-aware fallback link fix -
  // must read "...Harris County, TX..." (URL-encoded), never "...FL".
  txCardStreetviewHref: /Harris%20County%2C%20TX/,
  txCardZillowHref: /Harris%20County%2C%20TX/,
  // Phase 35: provenance/freshness/data-quality UX regression coverage.
  // Also confirms the stale-data warning renders as text (not just a card
  // border color) - p1's fixture updated_at (2026-08-10) is permanently
  // >36h in the past relative to any real "today" this suite runs on.
  detailProvenanceText: /Data source: Fl Realauction Alachua[\s\S]*Data may be stale[\s\S]*last synced/,
  detailLinksHaveNoEstimatedSuffix: true,
  txNoFloridaStatuteCopy: true,
  txNoFilterMatchToggle: true,
  txNoFilterMatchBanner: true,
  txDetailLinksText: /Google Maps search \(estimated search\)[\s\S]*Zillow \(estimated search\)/,
  txDetailProvenanceText: /Data source: LGBS \(taxsales\.lgbs\.com\)/,
  // Phase 36: fees(p) is Florida-only now (no verified TX fee formula
  // exists) - ptx1 has a published bid, so the pre-fix code would have
  // shown a real (wrong) "Fees" stat and calculator drawer here.
  txDetailHasFeesStat: false,
  txDetailHasCalcDrawer: 0,
  txDetailAssessedLabel: 'TX CAD/Listed Value',
  // Phase 72: Texas auction links come from the row's url_auction +
  // url_auction_kind (migration 013), never inferred in the browser.
  txLgbsDetailLink: { text: 'Auction link not published', kind: 'none', anchors: 0 },
  txLgbsDetailGapsNameTheLink: true,
  txLgbsDetailWhen: /^[A-Z][a-z]{2} \d{1,2}, \d{4} · in \d+d · Scheduled for Online Auction$/,
  txLgbsCardLink: { text: 'Auction link not published', kind: 'none', anchors: 0 },
  txLgbsCardKicker: / · online$/,
  txRaCardLink: { kind: 'sale', anchors: 1 },
  txRaCardLinkText: /^View sale listing for [A-Z][a-z]{2} \d{1,2}, \d{4}$/,
  txRaCardHref: /^https:\/\/nueces\.texas\.sheriffsaleauctions\.com\/index\.cfm\?zaction=AUCTION&zmethod=PREVIEW&AuctionDate=\d{2}\/\d{2}\/\d{4}$/,
  txRaCardScopeNote: true,
  txRaCardLabelNotPropertySpecific: true,
  txRaDetailLink: { kind: 'sale', anchors: 1 },
  txRaDetailLinkText: /^View sale listing for [A-Z][a-z]{2} \d{1,2}, \d{4}$/,
  txRaDetailHrefMatchesCard: true,
  txRaDetailProvenanceText: /Data source: RealAuction county sheriff-sale site/,
  txRaNoHostCardLink: { text: 'Auction link not published', kind: 'none', anchors: 0 },
  txRpcRowsExposeKindAndStatus: true,
  txCsvHeadersPresent: true,
  txCsvRealauctionRow: [true, 'sale'],
  txCsvLgbsRow: ['', '', 'Scheduled for Online Auction'],
  txStruckOffKicker: 'Struck off · resale inventory',
  txStruckOffLink: { text: 'Auction link not published', kind: 'none', anchors: 0 },
  txFutureSaleKicker: 'Future sale · not yet scheduled',
  txFutureSaleLink: { text: 'Auction link not published', kind: 'none', anchors: 0 },
  txRaPastDetailVisible: true,
  txRaPastDetailLink: { kind: 'none', anchors: 0 },
  txRaPastDetailLinkText: /^Sale listing no longer current · sale date [A-Z][a-z]{2} \d{1,2}, \d{4} has passed$/,
  // Phase 67: Map-page state cue on both entry points.
  txMapPageVisibleOnColdLoad: true,
  txMapContextTexas: 'Ledger: All Ledgers · County: All counties',
  txMapStateValue: 'TX',
  txMapPathCount: 254,
  // Phase 58: property deep-linking regression coverage.
  deepLinkHashHasPid: true,
  deepLinkModalVisibleOnColdStart: true,
  deepLinkAddressMatchesAcrossColdStart: true,
  deepLinkModalHiddenAfterBack: false,
  deepLinkHashClearedAfterBack: true,
  // SaaS hardening (2026-09-29).
  eventSectionPresent: 1,
  eventItemsP1: 1,
  eventLifecycleP1: 'Scheduled (as of the last observation)',
  eventOutcomeP1: "Outcome: Scheduled - the sale has not taken place",
  eventBidChangeP1: 'Opening bid observed: $4,500.00 → $5,000.00 (changed 1 time)',
  eventNavPill: 1,
  eventItemsP13: ['completed', 'superseded'],
  eventLifecycleP13First: 'Sale date passed - outcome not tracked',
  eventSectionNeverClaimsOutcome: true,
  eventSectionSaysNotPublished: 2,
  eventOutcomeSourcePublished: "Outcome: Unsold / struck off - verified Source: The auction source · Evidence: the source's own status for this sale (property-specific) · Source wording “Struck off to Jurisdiction” · Observed Sep 20, 2026 · Purchaser identity and bidder count are not recorded",
  eventNoteSaysSourceOnly: true,
  dashHealthRows: ['fl_deeds:HEALTHY', 'fl_certificates:INCOMPLETE', 'fl_laft:FAILED', 'db_backup:STALE', 'tx_sales:INCOMPLETE'],
  dashHealthBadgeTexas: true,
  dashHealthIncompleteNames: true,
  dashUnitRows: ['Alachua:current', 'Bay:stale', 'Citrus:current'],
  dashUnitLedgerHeads: ['auction', 'laft', 'certificate'],
  dashUnitRowsUnderAvailable: ['Alachua', 'Bay', 'Citrus'],
  dashUnitEmptyGroups: 2,
  dashLedgerFreshAvailable: '2 of 3 counties current',
  dashLedgerFreshAuctionsAbsent: 0,
  dashLedgerRowTitles: ['Auctions', 'Available', 'Liens & Certificates'],
  certDetailRelated: ['auction:p1:Auctions'],
  certDetailStatusLines: 4,
  relatedOpenLandsOnAuctionRow: '1 Main St',
  auctionDetailRelated: ['certificate:p4'],
  certStatusLines: ['Status On the county-held list', 'Issued Jun 1, 2023 · tax year 2022', 'Redemption Not published by the source', 'Property Parcel # 111 · 1 record in other ledgers'],
  dashUnitStaleText: 'last read 2h ago (failed) · last complete read 3d ago · 3 rows at that read · 3 consecutive failed attempts · source unavailable at the last attempt - inventory kept, nothing closed · no complete read in the last 36 hours · back-off: attempted at most once per 48 hours until a read succeeds',
  dashUnitCurrentText: 'last read 2h ago (complete) · last complete read 2h ago · 14 rows at that read',
  dashUnitMissingColumns: true,
  dashUnitMissingColumnsNoRows: 0,
  dashWatchFirstVisit: true,
  dashWatchNoNotificationsClaim: true,
  dashHealthMissingTable: true,
  dashHealthMissingTableNoBadges: 0,
  watchChangeItems: ['p1', 'gone1'],
  watchChangeBidLine: 'Opening bid: $4,000.00 → $5,000.00',
  watchChangeGoneLine: 'No longer in the current dataset - the listing left the source feed or list. Why is not recorded.',
  watchChangeSnapshotRewritten: true,
  supportModalVisible: true,
  supportUnconfiguredShown: 1,
  supportTopicsDisabled: 5,
  supportContextHasPage: true,
  supportFromPropertyHasContext: true,
  supportMailtoLinks: 5,
  supportMailtoHref: 'mailto:help%40example.test',
  supportSourceReportButton: 1,
  supportTopicLabels: ['Contact support', 'Report a data problem', 'Report a source problem', 'Account or billing question', 'Request account deletion'],
  helpModalVisible: true,
  helpCoversRequiredTopics: true,
  helpHasNoEmoji: true,
  forgotNeedsEmail: true,
  forgotResetCall: [['someone@example.com', true]],
  forgotMessage: 'If an account exists for that email, a password-reset link has been sent. Open it in this browser to set a new password.',
  forgotErrorShown: 'stub: reset refused',
  recoveryModalOpens: true,
  recoveryMismatchRefused: true,
  recoveryUpdateCall: ['newpass123'],
  recoveryMessage: 'Password updated. You are signed in.',
  deleteModalVisible: true,
  deleteModalStatesScope: true,
  deleteWrongWordRefused: true,
  deleteNotCalledYet: 0,
  deleteSignedOutReason: 'deleted',
  deleteMissingRpcMessage: 'Account deletion is not available on this deployment yet (migration 015 has not been applied). Use Contact support to request deletion.',
  deleteMissingRpcNoSignOut: null,
  detailStatusPill: 'Listed',
  detailStatusPillClass: 'pill active',
  notesVisibilityText: 'Shared with every approved member, with your email name - not private',
  tableHeaderValue: 'County value',
  txStruckOffDetailTag: 'Galveston County, TX · Struck-off inventory',
  txStruckOffWhat: 'WhatTexas struck-off / future-sale inventory (vendor listing)Source: LGBS (taxsales.lgbs.com)',
  txStruckOffNeverLandsAvailable: true,
  txStruckOffGroupMetaCount: 2,
  txStruckOffGroupMetaText: "Struck-off / future-sale inventory - no auction date; see each card's status",
  txStruckOffGroupMetaNeverLandsAvailable: true,
  flLandsGroupMetaText: 'Lands Available - fixed price, available now',
  // Migration 017 amount semantics (hasPublishedBid).
  bidKindNotPublishedWinsOverSentinel: false,
  bidKindPublishedAmountWinsOverZeroSentinel: true,
  bidLegacyZeroSentinelNotPublished: false,
  bidLegacyNullNotPublished: false,
  bidLegacyPositiveStillPublished: true,
  bidTxVendorRowWithoutKindUsesLegacyRule: true,
  // Enrichment phase: Inventory & Purchase card.
  txInventoryLabels: ['Status', 'Inventory', 'Amount', 'Source list', 'Published by', 'Last read from source', 'Parcel #', 'Legal description', 'Owner of record', 'Assessed value', 'Taxable value', 'Acreage', 'Land use', 'How to acquire', 'Purchase link'],
  txInventoryStatus: 'Struck off to the taxing unit (per the source) Source status "Struck off to Jurisdiction" · observed Sep 23, 2026',
  txProvenanceHasNoTable: 0,
  txInventoryGroups: ['Inventory', 'Property', 'Purchase path'],
  txInventoryType: 'Struck off to the taxing units, held in trust (Texas)',
  txInventoryAmount: '$4,451.95 Vendor minimum bid (legacy column)',
  txInventorySourceList: "Vendor list page \u2192",   // the registry listing the applier writes
  txInventoryPurchase: "Application / purchase instructions \u2192 Purchase instructions - the county's process page, not a link for this specific property",
  txInventoryOwner: 'Not on file',
  txInventoryParcel: '23-TX-0644',
  txInventoryAnchors: 2,
  txInventoryGapNamesAcquisition: true,
  txInventoryGapNeverNamesLink: true,
  txInventoryAcquire: "Multi-step county process Tax Assessor-Collector (fixture) - full process in \"How do I acquire it?\" above",
  flInventoryLabels: ['Status', 'Inventory', 'Price', 'Certificate #', 'Available for purchase', 'Escheats to county', 'Source list', 'Source document', 'List as of', 'Source document dated', 'Published by', 'Last read from source', 'Parcel #', 'Legal description', 'Name in which assessed', 'Assessed value', 'Taxable value', 'Acreage', 'Land use', 'Homestead', 'How to acquire', 'Purchase link'],
  flInventoryGroups: ['Inventory', 'Property', 'Purchase path'],
  flInventoryStatus: 'Available over the counter Basis: list presence · observed Aug 11, 2026',
  flProvenanceRows: [
    'acreage|Florida Department of Revenue (NAL tax roll)|Derived by our system - parcel match: FDOR alternate key|Recorded Aug 12, 2026',
    'assessed|Florida Department of Revenue (NAL tax roll)|Derived by our system - parcel match: FDOR parcel identifier|Recorded Aug 12, 2026',
    'legal_desc|County list (Lands Available) fl_laft_pioneer|Published by the source|List as of Aug 10, 2026'
  ],
  flProvenanceLines: ['Availability evidence', 'Last verified', 'Source date', 'Purchase link source', 'Path evidence', 'Read by', 'List read from', 'Retrieved', 'List date', 'Amount', 'Purchase path', 'How to purchase', 'Inventory type', 'Status wording'],   // the availability-evidence block leads; 'How to purchase' = the source-level mode,
  flProvenancePurchaseLine: "phone_mail (source-scope): Clerk's Lands Available page (fixture)",   // acquisition-path sprint: p3 carries a verified county process
  flProvenanceFresh: 'Last read from the source Aug 11, 2026 · list dated Aug 10, 2026',
  flProvenanceNoScoreWords: true,
  flInventoryType: 'Lands Available - fixed price, over the counter (F.S. 197.502(7))',
  flInventoryPrice: '$2,000.00 Opening bid',
  flInventoryCertificate: '2019-0042',
  flInventoryAvailable: 'Jun 15, 2026',
  flInventoryEscheat: 'Jul 1, 2029 Deadline stated by the county list (F.S. 197.502(8))',
  flInventorySourceListHref: 'https://x',
  flInventoryDocumentHref: 'https://x/list.pdf',
  flInventoryPurchase: 'No online purchase link on file - the county list page is not a purchase mechanism; purchase goes through the county under F.S. 197.502(7)',
  flInventoryPublishedBy: 'a platform contracted by the county fl_laft_pioneer',
  flInventoryLastRead: 'Aug 11, 2026',
  flInventoryListAsOf: 'Aug 10, 2026',
  flInventoryDocDated: 'Aug 10, 2026',
  flInventoryParcel: '333',
  flInventoryLegal: 'Not on file',
  flInventoryOwner: 'Bob',
  flInventoryAssessed: '$60,000.00 Tax year 2024',
  flInventoryTaxable: 'Not on file',
  flInventoryAcreage: '1.00 ac',   // p3 carries an FDOR acreage since the Available-filter fixture change
  flInventoryLandUse: 'Condo',
  flInventoryHomestead: 'Yes (per the list)',
  flInventoryPurchaseActionCount: 0,
  purchasePathPropertyLevelShowsOneAction: true,
  purchasePathPropertyLevelAnchor: ['Buy online →', 'https://x/buy/C-9'],
  purchasePathPropertyLevelCaption: true,
  purchasePathInstructionsAnchor: ['Application / purchase instructions →', 'https://x/how-to-buy'],
  purchasePathInstructionsNeverAction: true,
  purchasePathUnknownKindNeverAction: true,
  purchasePathNoneText: 'No online purchase link on file - the county list page is not a purchase mechanism; purchase goes through the county under F.S. 197.502(7)',
  purchasePathNoneHasNoAnchorInPurchaseGroup: true,
  purchasePathListPageIsOnlySourceListLink: true,
  inventoryCardGroups: ['Inventory', 'Property', 'Purchase path'],
  flInventoryNavHasInventory: true,
  flInventoryNoAiBadge: true,
  // ---- Available commercial release (2026-09-30, migration 023) ----
  decQuestions: ['What property is this?', 'Why is it in Available?', 'Is it currently verified as available?', 'How do I acquire it?', 'Who do I contact, and where do I go?', 'What source proves that, and when was it observed?', 'What does it cost?', 'Where is it?', 'What is known about it?', 'What is not known?', 'Where did the data come from?', 'How fresh is it?', 'What happened before?', 'Has this parcel appeared in another ledger?'],
  decNavHasDecision: 1,
  decP3How: "Phone the county First step: Call or e-mail the Tax Deed Department for the current purchase amount Call or e-mail the Tax Deed Department for the current purchase amount Pay the quoted amount at the Clerk's office County process: the county publishes this acquisition process for the properties on its list. It is not an approval for this parcel, and being listed does not prove the county will still sell it today. Acquisition process last verified Sep 30, 2026 \u00b7 County source not fully read at the last attempt; retry pending - this is the last verified process.",
  decP3Contact: "Office Clerk of Court - Tax Deed Department (fixture) Phone (850) 555-0100 E-mail taxdeeds@bayclerk.example.gov",
  decP3Why: "Lands Available - fixed price, over the counter (F.S. 197.502(7)) Property-specific: this parcel appears on the official county list. Basis: harvester constant (F.S. 197.502(7) Lands Available list) County list page \u2192 \u00b7 List document (PDF / file) \u2192 \u00b7 list dated Aug 10, 2026 Matched to the list by case no C-1 (parcel 333) \u00b7 read Aug 11, 2026",
  decP3Glance: "Phone the county Clerk of Court - Tax Deed Department (fixture)",
  decP3GapNamesAcquisition: true,
  purchasePathNoneAcquire: 'Not yet verified - no published acquisition process established from evidence',
  decP3HowLinkCount: 0,   // nothing verified = no link, ever
  decP3Available: 'Available over the counter basis: list presence · observed Aug 11, 2026 last verified: read from the source Aug 11, 2026 · county source unavailable at the last attempt - inventory kept, nothing closed',
  decP3Where: '3 Oak Ave Bay County, FL Not yet geocoded - no point is shown for this parcel',
  decP3Fresh: 'Source date: list dated Aug 10, 2026 · Observation date: Aug 11, 2026 · Last verified: read from the source Aug 11, 2026 County source: source unavailable at the last attempt - inventory kept, nothing closed · no complete read in the last 36 hours (last complete read 3d ago) · back-off: attempted at most once per 48 hours until a read succeeds · 3 rows at the last complete read',
  decP3History: 'Aug 11, 2026 Last read from the source (continued on the list) Append-only record. Absence from a list is recorded as a removal, never as a sale; a result appears only when the source published one.',
  decP3Related: 'No record for parcel 333 in the other ledgers in the current dataset',
  decP3PathEvidenceLine: "Phone or mail process (published by the source; no online path) \u00b7 source-level \u00b7 Clerk's Lands Available page: call or e-mail the Tax Deed department for the current amount (fixture) \u00b7 observed Sep 30, 2026",
  decNoScoreWords: true,
  decP15What: '15 Manatee Ln Citrus County, FL · Parcel 1515 · Case CI-7 · Vacant Lot',
  decP15Available: 'Available over the counter basis: list presence · observed Sep 20, 2026 last verified: read from the source Sep 20, 2026',
  decP15How: "Multi-step county process First step: Download and complete the application (fixture) Download and complete the application (fixture) E-mail taxdeeds@example.gov with the case number (fixture) Pay in certified funds at 1 Example Ave (fixture) Application / instructions document → · County purchase-instructions page (published by the source) → County process: the county publishes this acquisition process for the properties on its list. It is not an approval for this parcel, and being listed does not prove the county will still sell it today. Acquisition process last verified Sep 18, 2026",
  decP15HowHrefs: ['https://www.citrusclerk.example.gov/lands-available/application.pdf', 'https://www.citrusclerk.example.gov/lands-available/how-to-purchase'],
  decP15HowMode: 'Multi-step county process',
  decP15HowSteps: ['Download and complete the application (fixture)', 'E-mail taxdeeds@example.gov with the case number (fixture)', 'Pay in certified funds at 1 Example Ave (fixture)'],
  decP15Contact: 'Office Fixture County Clerk - Tax Deed Division (fixture) Address (in person) 1 Example Ave, Inverness, FL 00000 (fixture) Phone (000) 000-0000 E-mail taxdeeds@example.gov Payment Certified funds (fixture) Instructions published by the source: Complete the application and pay at the Tax Deed office (fixture wording).',
  decP15ContactLinks: ['tel:0000000000', 'mailto:taxdeeds@example.gov'],
  decP15Why: "Lands Available - fixed price, over the counter (F.S. 197.502(7)) Property-specific: this parcel appears on the official county list. Basis: harvester constant (F.S. 197.502(7) Lands Available list) County list page → · list dated Sep 19, 2026 Matched to the list by case no CI-7 (parcel 1515) · read Sep 20, 2026",
  decP15SourceDocHrefs: ['https://x/citrus-list', 'https://www.citrusclerk.example.gov/lands-available/how-to-purchase', 'https://www.citrusclerk.example.gov/lands-available/application.pdf'],
  decP15Glance: 'Multi-step county process Fixture County Clerk - Tax Deed Division (fixture)',
  decP15InvAcquire: 'Multi-step county process Fixture County Clerk - Tax Deed Division (fixture) - full process in "How do I acquire it?" above',
  availCsvP15Acquisition: true,
  decP15Scope: 'source',
  decP15First: 'First step: Download and complete the application (fixture)',
  decP15Verified: 'Acquisition process last verified Sep 18, 2026',
  acqUnavailableKeepsPath: { mode: 'Phone the county', verified: 'Acquisition process last verified Sep 30, 2026 · County source not fully read at the last attempt; retry pending - this is the last verified process.', notVerified: false },
  acqPropertyScopeLabel: 'Property-specific: the source published this instruction for this parcel.',
  decP15Cost: 'Not published by the source',
  decP15Where: '15 Manatee Ln Citrus County, FL 28.88860, -82.45200 · authoritative coordinates on file',
  decP15Known: '2025 County Just Value $26,000 · County Assessed Value $25,000 · 0.30 ac · Land use Vacant residential · Type Vacant Lot · Assessed to Lee Park',
  decP15Unknown: ['Purchase price not published', 'Image not checked yet', 'Flood zone not checked'],
  decP15Source: 'fl_laft_html · Source list → How to purchase Lands Available (fixture) (acquisition evidence) → · Application / instructions document → Field-by-field origin is in the Data Quality & Provenance card below.',
  decP15Fresh: 'Source date: list dated Sep 19, 2026 · Observation date: Sep 20, 2026 · Last verified: read from the source Sep 20, 2026 County source: current - last complete read 3h ago · 6 rows at the last complete read',
  decP15History: ['newly_observed|Jul 1, 2026|First observed on the list', 'removed|Aug 15, 2026|Removed from the list (closed - not a sale result)', 'reactivated|Sep 1, 2026|Back on the list (reactivated)', 'continued|Sep 20, 2026|Last read from the source (continued on the list)'],
  decP15HistoryNote: 'Append-only record. Absence from a list is recorded as a removal, never as a sale; a result appears only when the source published one.',
  decP15PathEvidenceLine: "County purchase-instructions page (published by the source) · source-level · Clerk's 'How to purchase Lands Available' page names the application and payment steps (data/purchase_path_evidence.csv, observed 2026-09-18) · observed Sep 18, 2026",
  decP15GapsNamePathKind: true,
  decHistoryMissing: 'Lifecycle history is not available on this deployment yet (migration 021 has not been applied).',
  availLandUseOptions: ['Any', 'Vacant residential'],   // only values Available rows carry
  availAfterLandUse: 1,
  availAfterGeocoded: 1,
  availGeocodedCardAddress: '15 Manatee Ln',
  availAfterValues: 2,
  availAfterResetAll: 2,
  availResetClearsNew: true,
  availCsvFilename: /^taxdeed-fl-laft-\d{4}-\d{2}-\d{2}\.csv$/,
  availCsvHeaderHas: true,
  availCsvHeaderLacks: true,
  availCsvRowCount: 2,
  availCsvNoWithheld: true,
  availCsvP15Path: true,
  govStatePages: Object.fromEntries(['mi', 'wy', 'sc', 'co', 'wi'].map(f => [f, { admView: true, admHash: '#/governance', onWorkspace: false, userView: false, userItem: false, userHashRewritten: true }])),
  govWorkspace: { inlinePanelVisible: false, panelInsideView: true, panelOnWorkspace: false, approvalsVisible: true, approvalRows: true },
  govMenu: { itemVisible: true, itemText: 'Source Publication Governance', order: ['editProfileBtn', 'changePasswordBtn', 'themeBtn', 'alertsMenuItem', 'helpBtnMenu', 'supportBtnMenu', 'adminAreaLink', 'governanceMenuItem', 'termsBtnMenu', 'signOutBtn', 'deleteAccountBtn'] },
  govOpened: { viewVisible: true, hash: '#/governance', menuClosed: true, title: 'Source Publication Governance' },
  govClosedByBack: { hidden: true, hash: '#/auctions' },
  govAdminRoute: { visible: true, rows: 5, hash: '#/governance' },
  govPhone: { itemVisible: true, viewVisible: true, noHorizontalScroll: true, formFits: true },
  govCustomerMenu: { itemVisible: false, accountMenuOpen: true },
  govCustomerTypedRoute: { viewHidden: true, hash: '#/auctions', rows: 0 },
  govCustomerColdRoute: {"viewHidden": true, "hash": "#/lands", "rows": 0, "menuItemHidden": true},
  adminPubVisible: true,
  adminPubSources: ['fl_laft_broward_candidate:RESTRICTED', 'fl_laft_html:APPROVED_GRANDFATHERED', 'fl_laft_pdfs:APPROVED_GRANDFATHERED', 'fl_laft_pioneer:APPROVED_GRANDFATHERED', 'fl_laft_realtdm:APPROVED_GRANDFATHERED'],
  adminPubBrowardMeta: 'Governance LEGAL_REVIEW_REQUIRED · Verification CANDIDATE · Restrictions: terms of use under legal review',
  adminPubPioneerReview: 'Latest decision: APPROVED_GRANDFATHERED · decided Sep 29, 2026 · next review Mar 1, 2027 · carried forward Evidence: served to customers before the gate existed',
  adminPubRefusesRestrictedWithoutReason: 'RESTRICTED needs a reason.',
  adminPubInsertsAfterRefusal: 0,
  adminPubInserted: [['FL', 'fl_laft_pdfs', 'RESTRICTED', 'vendor terms forbid redistribution - under review', 'pending counsel', '2026-12-01', null]],
  adminPubPdfsReviewAfter: /^Latest decision: RESTRICTED · decided [A-Z][a-z]{2} \d{1,2}, \d{4} · next review Dec 1, 2026 · pending counsel$/,
  adminPubRefusesApprovalWithoutEvidence: 'An approval needs evidence.',
  adminPubHiddenForCustomer: true,
  adminPubNoTableReviewText: 'Latest decision: Review history unavailable (migration 023 not applied)',
  adminPubNoTableFormDisabled: true,
  // ---- Customer-value / evidence sprint ----
  aucDecQuestions: ['What property?', 'When is the sale?', 'Opening / minimum bid, if published?', 'What property intelligence is available?', 'How do I register and bid?', 'What is the source?', 'Is an explicit auction result available?', 'Has this parcel appeared in another ledger?', 'What is not known?'],
  aucDecP1When: /^[A-Z][a-z]{2} \d{1,2}, \d{4} · in 3d$/,
  aucDecP1Bid: '$5,000.00 Value ÷ bid 18.0× - a screening ratio, not a return',
  aucDecP1Related: 'Currently in Liens & Certificates (certificate #CERT-42). Same state, county and parcel number; why a record moved between ledgers is not recorded.',
  aucDecP1Result: "Scheduled - the sale has not taken place",
  aucDecP1Source: /^Fl Realauction Alachua · View sale listing for [A-Z][a-z]{2} \d{1,2}, \d{4} → /,
  aucRelatedWhen: ['certificate:now:Currently listed'],
  aucDecNoScoreWords: true,
  aucDecP13Result: "Outcome not published Source: RealAuction county sale site (alachua.realtaxdeed.com) · sale-day page → · Evidence: the sale day's “Auctions Closed or Canceled” listing and its status line - one item per property (property-specific) · Matched by exact case number L-1 · Checked Sep 25, 2026 · The listing printed no result for this property · Purchaser identity and bidder count are not recorded",
  aucDecP13ResultNeverSold: true,
  outcomeP13Result: "Outcome not published Source: RealAuction county sale site (alachua.realtaxdeed.com) · sale-day page → · Evidence: the sale day's “Auctions Closed or Canceled” listing and its status line - one item per property (property-specific) · Matched by exact case number L-1 · Checked Sep 25, 2026 · The listing printed no result for this property · Purchaser identity and bidder count are not recorded",
  outcomeP13Kicker: "Outcome not published",
  outcomeStates: {"sold": "Sold - verified", "soldProv": "Source: RealAuction county sale site (jackson.realtaxdeed.com) · sale-day page → · Evidence: the sale day's “Auctions Closed or Canceled” listing and its status line - one item per property (property-specific) · Matched by exact case number 2024 TD 0001 · Source wording “Auction Sold” · Observed Sep 30, 2026 · Amount published by the source $12,300.00 · Purchaser identity and bidder count are not recorded", "soldNoAmount": true, "struck": "Unsold / struck off - verified", "withdrawn": "Withdrawn - verified", "cancelled": "Cancelled - verified", "redeemed": "Redeemed - verified", "cancelledNoWording": "Outcome not yet verified", "notPublished": "Outcome not published", "notVerified": "Outcome not yet verified", "unreviewedWording": {"ev": {"id": "x", "case_no": "2024 TD 0001", "scheduled_sale_date": "2026-09-29", "lifecycle": "completed", "outcome": "unknown", "outcome_raw": null, "outcome_observed_at": null, "winning_bid": null, "event_url": "https://jackson.realtaxdeed.com/index.cfm?zaction=AUCTION&zmethod=PREVIEW&AuctionDate=09/29/2026"}, "closed": {"feed": "closed", "raw_status": "Canceled per Bankruptcy", "outcome": "unknown", "lifecycle": "completed", "observed_at": "2026-09-30T15:00:00Z", "evidence_url": "https://jackson.realtaxdeed.com/index.cfm?zaction=AUCTION&zmethod=PREVIEW&AuctionDate=09/29/2026"}, "evidenceUrl": "https://jackson.realtaxdeed.com/index.cfm?zaction=AUCTION&zmethod=PREVIEW&AuctionDate=09/29/2026", "feed": "closed", "key": "outcome_not_verified", "verified": false, "label": "Outcome not yet verified", "note": "The source's status line for this sale reads \"Canceled per Bankruptcy\", which is not a reviewed result wording yet - so no outcome is claimed."}, "passedDateOnly": false, "scheduled": "Scheduled"},
  outcomeRelation: {"both": "Previously auctioned - verified unsold / struck off (source wording “Struck Off”) · Currently Available - independently verified on the county's Lands Available list (case L-9)", "auctionOnly": null, "availableOnly": null, "fromAvailable": "Previously auctioned - verified unsold / struck off (case 2024 TD 0001, source wording “Struck Off”) · Currently Available - independently verified on the county's Lands Available list", "availableNoAuctionResult": null},
  aucExportOutcomeCols: true,
  aucExportNoGovernance: true,
  aucExportNeverSoldWithoutEvidence: true,
  certDecQuestions: ['What certificate / lien?', 'Amount?', 'Interest / return terms, if published?', 'Redemption information, if published?', 'Source and freshness?', 'Same parcel in Auctions or Available?', 'What is not known?'],
  certDecWhat: 'Certificate #CERT-42 Alachua County, FL · tax year 2022 · account ACC-999 · parcel 111',
  certDecAmount: '$1,234.56',
  certDecTerms: /^Interest rate 18% \(as published\) · Issued Jun 1, 2023 · Certificate expires [A-Z][a-z]{2} \d{1,2}, \d{4} Published figures only; no return is estimated here\.$/,
  certDecRedemption: 'Not published by the source',
  certDecRelated: 'Currently in Auctions (case A-1). Same state, county and parcel number; why a record moved between ledgers is not recorded.',
  certDecNavHasDecision: 1,
  certCsvHeader: ['State', 'County', 'Certificate #', 'Account #', 'Parcel', 'Tax Year', 'Amount', 'Interest Rate (as published)', 'Issued Date', 'Expiration Date', 'Est. Accrued Interest', 'TDA Eligibility Date', 'Status (per the source)', 'Status Observed', 'Same Parcel In Other Ledgers', 'County-Held List URL', 'Source', 'Last Synced', 'Source Review Status'],
  certCsvHeaderLacks: true
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

// DUMP_RESULTS=<path>: write every collected value, so a new check's real
// value can be read and pinned rather than guessed.
if (process.env.DUMP_RESULTS) fs.writeFileSync(process.env.DUMP_RESULTS, JSON.stringify(results, null, 1));
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
