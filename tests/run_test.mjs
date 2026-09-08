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
];

const errors = [];
const browser = await chromium.launch(launchOpts);
const page = await browser.newPage({ viewport: { width: 390, height: 844 } });
page.on('pageerror', e => errors.push('pageerror: ' + e.message));
page.on('console', msg => { if (msg.type() === 'error') errors.push('console.error: ' + msg.text()); });
// The "hide" action now confirms before it does anything (a real user would
// click OK) - Playwright auto-dismisses unhandled dialogs, which silently
// no-ops every hide in this test and cascades into wrong counts everywhere
// downstream. Auto-accept so hide behaves the way a real click would.
page.on('dialog', dialog => dialog.accept());

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

// --- sort by ---
await page.selectOption('#sortBy', 'bidDesc');
await page.waitForTimeout(150);
const firstMeta = await page.locator('.prop-card .card-stat-val.bid').first().textContent();
results.sortByBidDescFirst = firstMeta.trim();
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
// County chips/map now live inside a collapsed <details> dropdown; open it first.
await page.click('.filter-dropdown summary:has-text("County")');
await page.waitForTimeout(100);
results.countyDropdownOpenForMapTest = await page.locator('#countyChips').first().evaluate(el => el.closest('details').open);
await page.click('#mapBtn');
await page.waitForTimeout(300);
results.mapWrapVisible = await page.locator('#mapWrap').isVisible();
results.mapPathCount = await page.locator('#mapHost path[data-county]').count();
results.mapHasDataCount = await page.locator('#mapHost path.has-data').count();

// A first tap on any county (has-data or not) zooms in and names it in the
// banner - it must NOT touch the filter yet. That's the point of the
// two-step interaction: you always see which county you're about to
// filter to before committing to it (see zoomToCounty() in app.js).
const alachuaPath = page.locator('#mapHost path[data-county="Alachua"]');
const alachuaSelBefore = await alachuaPath.evaluate(el => el.classList.contains('sel'));
await alachuaPath.click({ force: true });
await page.waitForTimeout(500); // the zoom viewBox tween runs ~320ms
results.alachuaSelAfterFirstTap = await alachuaPath.evaluate(el => el.classList.contains('sel'));
results.alachuaChipOnAfterFirstTap = await page.locator('#countyChips .chipx[data-value="Alachua"]').evaluate(el => el.classList.contains('on'));
results.mapZoomBannerVisibleAfterTap = await page.locator('#mapZoomBanner').isVisible();
results.mapZoomNameTextAfterTap = await page.locator('#mapZoomName').textContent();
results.mapHintHiddenAfterTap = await page.locator('#mapHint').isHidden();

// A second tap on the SAME (now-zoomed) county actually toggles the filter.
await alachuaPath.click({ force: true });
await page.waitForTimeout(150);
const alachuaSelAfter = await alachuaPath.evaluate(el => el.classList.contains('sel'));
const alachuaChipOnAfter = await page.locator('#countyChips .chipx[data-value="Alachua"]').evaluate(el => el.classList.contains('on'));
results.alachuaSelBefore = alachuaSelBefore;
results.alachuaSelAfter = alachuaSelAfter;
results.alachuaChipOnAfterMapClick = alachuaChipOnAfter;

// "Full map" zoom-out button returns to the state-wide view.
await page.click('#mapZoomOutBtn');
await page.waitForTimeout(500);
results.mapZoomBannerHiddenAfterZoomOut = await page.locator('#mapZoomBanner').isHidden();
results.mapHintVisibleAfterZoomOut = await page.locator('#mapHint').isVisible();

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
// The old #hiddenInfo counter text was replaced by the Hidden Properties
// feature's #hiddenListBtn (a "N hidden - view & recover" button that stays
// hidden until HIDDEN.size > 0, opening the recover modal on click).
const removeBtn = page.locator('.remove-btn').first();
await removeBtn.click();
await page.waitForTimeout(200);
results.cardsAfterHide = await page.locator('.prop-card').count();
results.hiddenListBtnVisible = await page.locator('#hiddenListBtn').isVisible();

// --- switch to Lands Available tab (fixture p3, Bay county) ---
await page.click('.ledger-tab[data-ledger="laft"]');
await page.waitForTimeout(150);
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

// --- the tax-roll facts on the full property page ---
// The card carries the three-fact summary; the page carries the rest,
// including the whole legal description rather than one clamped line.
results.detailStatLabels = await page.locator('#detailModalInner .detail-stat-label').allTextContents();
results.detailStatValues = await page.evaluate(() => {
  const out = {};
  document.querySelectorAll('#detailModalInner .detail-stat').forEach(el => {
    out[el.querySelector('.detail-stat-label').textContent.trim()] =
      el.querySelector('.detail-stat-val').textContent.trim();
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
results.calcInitialMaxBid = (await page.locator('#calcMaxBidResult').textContent() || '').trim();
results.calcInitialNet = (await page.locator('#calcNetResult').textContent() || '').trim();
await page.fill('.calc-drawer input[data-calc-field="repair"]', '5000');
await page.fill('.calc-drawer input[data-calc-field="muni"]', '1000');
await page.waitForTimeout(150);
results.calcNetAfterInput = (await page.locator('#calcNetResult').textContent() || '').trim();
results.calcMaxBidAfterInput = (await page.locator('#calcMaxBidResult').textContent() || '').trim();
// The repair estimate and lien buffer are the bidder's own numbers, not
// server state - closing and reopening the SAME property's page should
// find them still there (localStorage), not reset to blank.
await page.click('[data-action="closedetail"]');
await page.waitForTimeout(150);
await firstDetailBtn.click();
await page.waitForTimeout(150);
await page.click('#detailModalInner .calc-drawer summary');
await page.waitForTimeout(150);
results.calcInputPersistsAfterReopen = await page.locator('.calc-drawer input[data-calc-field="repair"]').inputValue();

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
await page.click('#termsCloseBtn');
await page.waitForTimeout(200);
results.termsModalCloses = await page.locator('#termsModal').isHidden();
results.cardStatGridCount = await page.locator('.prop-card .card-stat-grid').count();
results.lienPillFirstText = (await page.locator('.prop-card .lien-pill').first().textContent() || '').trim();
results.homesteadBadgeAbsentForP1 = await page.locator('.prop-card').first().locator('.lien-pill.homestead').count();
results.infoTipCount = await page.locator('.info-tip').count();
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
  const el = [...document.querySelectorAll('#detailModalInner .detail-stat')]
    .find(e => e.querySelector('.detail-stat-label').textContent.trim() === 'Building / Improvement Value');
  return el ? el.querySelector('.detail-stat-val').textContent.trim() : null;
});
await page.click('[data-action="closedetail"]');
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
results.certDetailHasTotalReturn = /Est\. Total Return/.test(certDetailText);
results.certDetailTdaEligibleNow = /TDA Eligibility[\s\S]{0,40}Eligible now/.test(certDetailText);
results.certDetailYieldInfoTips = await page.locator(
  '#detailModalInner .detail-stat:has-text("Est. Accrued Interest") .info-tip, ' +
  '#detailModalInner .detail-stat:has-text("TDA Eligibility") .info-tip'
).count();
await page.click('[data-action="closedetail"]');
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
// one row and prove nothing about ranking.
await page.selectOption('#countyQuick', 'ALL');
await page.waitForTimeout(300);
await page.click('#viewToggle button[data-mode="map"]');
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
// Scoped to the explore canvas on purpose: the filter panel inlines the
// SAME basemap into #mapHost, so an unscoped query finds that copy first -
// which is not zoomed, and the check would pass or fail on the wrong map.
results.contextLabelsHiddenWhenZoomed = await page.evaluate(() => {
  const g = document.querySelector('#exploreMapCanvas .map-context');
  return !!g && getComputedStyle(g).display === 'none';
});
await page.click('#exploreZoomOut');
await page.waitForTimeout(1100);
await page.click('#viewToggle button[data-mode="list"]');
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
await page.goto(BASE_URL + '#/certificates', { waitUntil: 'networkidle' });
await page.waitForTimeout(1200);
results.deepLinkLandsOnCertificates = await page.locator('.ledger-tab[data-ledger="certificate"]').evaluate(el => el.classList.contains('on'));
results.deepLinkHeading = ((await page.locator('.ledger-head h2').textContent()) || '').trim();

// The badge is now gone for EVERYONE, admin included - it was a number
// nobody acted on, repeated once per county down the page. Checking the
// admin view too, because that is the one place it survived last time.
await page.goto(BASE_URL + '?profile=admin', { waitUntil: 'networkidle' });
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
await page.click('[data-action="closedetail"]');
await page.waitForTimeout(150);

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
  countyGroupCount: 9,
  // Tab labels became page names ("Auctions", not "Tax Deeds / Auctions") and
  // each carries a leading icon span, which allTextContents() concatenates.
  // Auctions is 9, not 11: the tab counts what the ledger will actually show,
  // so the past-due row (archive-only) and the gone row whose grace period has
  // expired are both excluded. Neither is reachable from this tab, and
  // advertising them made the number disagree with the list underneath it.
  ledgerTabCounts: ['\u2696\uFE0FAuctions 9', '\uD83C\uDFDE\uFE0FLands Available 1', '\uD83D\uDCDCCertificates 1'],
  auctionTabOnByDefault: true,

  // --- per-ledger pages ---
  freshnessBadgesForNormalUser: 0,
  countyGroupsPresentForThatCheck: true,
  // Gone for everyone now, admin included.
  freshnessBadgesForAdmin: 0,
  desktopAuctionListSingleColumn: true,
  desktopAuctionModalDocksRight: true,
  desktopLaftListIsMultiColumn: true,
  desktopCertListSingleColumn: true,
  desktopCertCardIsRow: true,
  watchlistChipLabel: '⚑ Watchlist 0/10',
  ledgerHashes: ['#/auctions', '#/lands', '#/certificates'],
  ledgerDocAttr: ['auction', 'laft', 'certificate'],
  ledgerHeadings: ['Auctions & Bidding', 'Lands Available for Taxes', 'Tax Certificates'],
  ledgerTitles: [
    'Auctions & Bidding · FL Tax Deed Watchlist',
    'Lands Available for Taxes · FL Tax Deed Watchlist',
    'Tax Certificates · FL Tax Deed Watchlist'
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
  deepLinkHeading: 'Tax Certificates',
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
  mapWrapVisible: true,
  mapPathCount: 67,
  mapHasDataCount: 8,
  alachuaSelBefore: true,
  alachuaSelAfterFirstTap: true,
  alachuaChipOnAfterFirstTap: true,
  mapZoomBannerVisibleAfterTap: true,
  mapZoomNameTextAfterTap: 'Alachua County · Gainesville',
  mapHintHiddenAfterTap: true,
  alachuaSelAfter: false,
  alachuaChipOnAfterMapClick: false,
  mapZoomBannerHiddenAfterZoomOut: true,
  mapHintVisibleAfterZoomOut: true,
  cardsAfterReset: 9,
  alachuaSelAfterReset: true,
  countyGroupsClosedAfterReset: true,
  expandAllLabelAfterReset: 'Expand all',
  cardsAfterHide: 8,
  hiddenListBtnVisible: true,
  laftTabOnAfterClick: true,
  auctionTabOffAfterLaftClick: false,
  laftCardCount: 1,
  laftCountyGroupName: 'Bay',
  laftSpecBits: ['1.00 acres lot'],
  // A different roll year from p1's, so the label is genuinely per-row rather
  // than a constant with a year hardcoded into it.
  laftValueLabel: '2024 County Just Value',
  laftHomesteadBadge: 'Homestead',
  laftBareLandStat: 'None (bare land)',
  junkLandRowVisibleOnLaft: true,
  laftCountBeforeJunkFilters: 1,
  laftCountAfterHideSlivers: 1,
  laftCountAfterHideBareLand: 0,
  laftCountAfterUncheckingFilters: 1,
  laftGroupMeta: 'Lands Available - fixed price, available now',
  certCardCount: 1,
  certCardTitle: 'Certificate #CERT-42',
  certCardAmount: '$1,234.56',
  certCardAccount: 'ACC-999',
  certCardExpires: /^[A-Z][a-z]{2} \d{1,2}, \d{4}$/,
  certCardCta: 'View on County-Held Liens List',
  certCardExpiresCountdown: 1,
  certCardStatCount: 6,
  certCardInterestRate: '18%',
  certCardTdaEligibility: 'Eligible now',
  certCardStatusPill: 'Active',
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
  staleWarningText: '⚠ Data updated 8/12/2026, 12:00:00 AM - sync may be behind',
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
  csvDownloadFilename: /^taxdeed-auction-\d{4}-\d{2}-\d{2}\.csv$/,
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
    'Building / Improvement Value',
    // "Fees i" - the label carries an info tooltip glyph.
    'Fees i', 'Walk Away Above', 'Gross Equity Spread',
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
  detailModalVisibleAfterOpen: true,
  detailModalHasAddress: 1,
  detailModalHasLinks: 6,
  detailModalHiddenAfterCloseBtn: true,
  detailModalHiddenAfterBackdropClick: true,
  detailModalHiddenAfterEscape: true,
  topbarBrandVisible: true,
  termsButtonVisible: true,
  termsModalOpens: true,
  termsCarryTitleWarning: true,
  termsModalCloses: true,
  cardStatGridCount: 8,
  lienPillFirstText: 'Clear',
  homesteadBadgeAbsentForP1: 0,
  infoTipCount: 4,
  linkIconPresent: true,
  toppickBannerText: '★ Top pick 18.0× market vs bid',
  junkLandRowHiddenOnAuction: true,
  exportBtnLabelAuction: '⬇ Export to Auction Sheet',
  spreadBarPresentP1: 1,
  exportBtnLabelCertificate: '⬇ Export Yield Ledger (CSV)',
  csvCertAccruedPlausible: true,
  csvCertTdaDate: '2025-06-01',
  certDetailHasAccrued: true,
  certDetailHasTotalReturn: true,
  certDetailTdaEligibleNow: true,
  certDetailYieldInfoTips: 2,
  exportBtnLabelLaft: '⬇ Export OTC List (CSV)',
  laftPurchasePriceLabel: 'Purchase Price',
  laftCtaText: 'View Clerk Docket / Listing',
  bidListChipTextInitial: '0/10',
  bidBtnIconBefore: '⚐',
  bidBtnIconAfterAdd: '⚑',
  bidListChipTextAfterAdd: '1/10',
  bidListModalVisible: true,
  bidListModalCardCount: 1,
  bidListModalCardCountAfterRemove: 0,
  bidListChipTextAfterRemove: '0/10',
  bidListModalHiddenAfterClose: true,
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
