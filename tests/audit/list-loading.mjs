// Audit 2026-10-28, theme list-loading (fixes 2026-11-02): render paths, the
// list toolbar and the loading / failure states. One standalone Playwright
// file: PASS/FAIL lines, exit 1 on any failure.
//   BASE_URL=http://localhost:8873/index.html node tests/audit/list-loading.mjs
import { chromium } from 'playwright';
import fs from 'fs';
const BASE = process.env.BASE_URL || 'http://localhost:8934/index.html';
const root = BASE.replace(/[^/]*$/, '');
const exe = '/opt/pw-browsers/chromium';
const b = await chromium.launch(fs.existsSync(exe) ? { executablePath: exe } : {});
let fail = 0;
const check = (name, ok, got) => { console.log((ok ? 'PASS ' : 'FAIL ') + name + (ok ? '' : ' -> ' + JSON.stringify(got))); if (!ok) fail++; };
const errs = [];
async function open(path, opts = {}) {
  const ctx = await b.newContext({ viewport: opts.viewport || { width: 1280, height: 900 }, hasTouch: !!opts.touch, isMobile: !!opts.touch });
  const pg = await ctx.newPage();
  pg.on('pageerror', e => errs.push(path + ': ' + e.message));
  pg.on('dialog', d => d.accept());
  if (opts.init) await pg.addInitScript(opts.init);
  await pg.goto(root + path, { waitUntil: opts.wait || 'networkidle' });
  await pg.waitForTimeout(opts.settle ?? 1200);
  return pg;
}
const txt = async (pg, sel) => ((await pg.locator(sel).first().textContent().catch(() => '')) || '').replace(/\s+/g, ' ').trim();
const navCounts = pg => pg.evaluate(() => ['Laft', 'Auction', 'Certificate'].map(k => (document.getElementById('navCount' + k) || {}).textContent));
const goLedger = (pg, k) => pg.evaluate(k => { const el = document.querySelector(`#hdrNav [data-nav-ledger="${k}"], [data-nav-ledger="${k}"], #ledgerTabs .ledger-tab[data-ledger="${k}"]`); if (el) el.click(); }, k);
const setSelect = (pg, id, v) => pg.evaluate(([id, v]) => { const el = document.getElementById(id); el.value = v; el.dispatchEvent(new Event('change', { bubbles: true })); }, [id, v]);

// ---------------------------------------------------------------- F75: loading
{
  const pg = await open('index.html?ledgerdelay=buy:4000#/lands', { wait: 'commit', settle: 700 });
  check('f75TitleNamesRoutedLedgerWhileLoading', /^Available in Florida/.test(await txt(pg, '#listTitle')), await txt(pg, '#listTitle'));
  const c = await navCounts(pg);
  check('f75HeaderCountsNotZeroWhileLoading', c.every(x => x && x !== '0'), c);
  check('f75NoCountyChipWhileLoading', (await pg.locator('#filterChips [data-chip="counties"]').count()) === 0, null);
  check('f75FiltersBadgeHiddenWhileLoading', await pg.evaluate(() => { const b = document.getElementById('filtersBadge'); return !b || b.hidden || b.textContent === '0'; }), null);
  await pg.waitForTimeout(5000);
  check('f75CountsSettleToNumbers', (await navCounts(pg)).every(x => /^\d/.test(x)), await navCounts(pg));
  await pg.context().close();
}

// ---------------------------------------------------------------- F29: every ledger failed
{
  const pg = await open('index.html?failpage=buy:0,auctions:0,lien:0#/lands', { settle: 7000 });
  check('f29ErrorStateShown', (await pg.locator('#main .error-state').count()) === 1, null);
  check('f29TitleNamesRoutedLedger', /^Available in Florida/.test(await txt(pg, '#listTitle')), await txt(pg, '#listTitle'));
  const sub = await txt(pg, '#listSubtitle');
  check('f29NoLoadingLine', !/Loading/.test(sub) && /could not be loaded/.test(sub), sub);
  const c = await navCounts(pg);
  check('f29NoBareZeroCounts', c.every(x => x === '—'), c);
  check('f29NoPhantomCountyChip', (await pg.locator('#filterChips [data-chip="counties"]').count()) === 0, null);
  check('f29FiltersBadgeHidden', await pg.evaluate(() => { const b = document.getElementById('filtersBadge'); return !b || b.hidden; }), null);
  await pg.context().close();
}

// ---------------------------------------------------------------- F30: the active ledger's first page failed
{
  const pg = await open('index.html?failpage=buy:0#/lands', { settle: 6000 });
  check('f30LoadIssueBannerShown', (await pg.locator('#loadIssue').count()) === 1, null);
  check('f30TitleCarriesNoZero', (await pg.locator('#listCount').count()) === 0, await txt(pg, '#listTitle'));
  const empty = await txt(pg, '#main .empty-state');
  check('f30NoEmptyInventoryClaim', !/No Lands Available listings match|No available properties currently listed/.test(empty) && /could not be loaded/.test(empty), empty);
  check('f30EmptyStateMarkedLoadFailed', (await pg.locator('#main .empty-state[data-load-failed]').count()) === 1, null);
  const c = await navCounts(pg);
  check('f30FailedLedgerCountIsDash', c[0] === '—' && /^\d/.test(c[1]), c);
  await pg.context().close();
}

// ---------------------------------------------------------------- F13: sort reorders the groups
{
  const pg = await open('index.html#/auctions');
  const bids = async () => pg.evaluate(() => [...document.querySelectorAll('.prop-card .card-stat-val.bid')].map(e => Number(e.textContent.replace(/[^0-9.]/g, ''))));
  const before = await bids();
  await setSelect(pg, 'sortBy', 'bidDesc'); await pg.waitForTimeout(300);
  const desc = await bids();
  check('f13BidDescOrdersWholeList', desc.length === before.length && desc.every((v, i) => i === 0 || desc[i - 1] >= v), desc);
  await setSelect(pg, 'sortBy', 'bidAsc'); await pg.waitForTimeout(300);
  const asc = await bids();
  check('f13BidAscOrdersWholeList', asc.every((v, i) => i === 0 || asc[i - 1] <= v), asc);
  await setSelect(pg, 'sortBy', 'dateDesc'); await pg.waitForTimeout(300);
  const dates = await pg.evaluate(() => [...document.querySelectorAll('#main .date-divider')].map(d => d.dataset.date || ''));
  check('f13DateDescReversesDateClusters', dates.length > 1 && dates.every((d, i) => i === 0 || dates[i - 1] >= d), dates);
  await setSelect(pg, 'sortBy', 'county'); await pg.waitForTimeout(300);
  const back = await pg.evaluate(() => [...document.querySelectorAll('#main .date-divider')].map(d => d.dataset.date || ''));
  check('f13CountyDefaultSoonestFirst', back.every((d, i) => i === 0 || back[i - 1] <= d), back);
  await pg.context().close();
}

// ---------------------------------------------------------------- F12: the vendor's sale-list document
{
  const far = new Date(Date.now() + 20 * 86400000).toISOString().slice(0, 10);
  const pg = await open('tx.html#/auctions', { init: `window.__stubExtraRows = [
    { id: "ptxdoc1", source: "auction", state: "TX", county: "Bell", case_no: "TXDOC-1", parcel: "C-1", address: "10 Doc St", bid: 4000, status: "active", lien_level: "unscreened", lien_note: "", prop_type: "House", sale_date: "${far}", harvester_source: "tx_mvba", source_id: "tx_mvba", url_auction: null, url_auction_kind: null, document_url: "https://mvbalaw.com/wp-content/TaxUploads/1126_Bell.pdf", updated_at: "2026-10-28T00:00:00Z", ledger_type: "auctions" },
    { id: "ptxdoc2", source: "auction", state: "TX", county: "Bell", case_no: "TXDOC-2", parcel: "C-2", address: "11 Doc St", bid: 4000, status: "active", lien_level: "unscreened", lien_note: "", prop_type: "House", sale_date: "${far}", harvester_source: "tx_mvba", source_id: "tx_mvba", url_auction: null, url_auction_kind: null, document_url: "http://mvbalaw.com/insecure.pdf", updated_at: "2026-10-28T00:00:00Z", ledger_type: "auctions" }
  ];` });
  const c1 = pg.locator('.prop-card[data-pid="ptxdoc1"], [data-pid="ptxdoc1"].prop-card').first();
  const a1 = c1.locator('a[data-auction-link="document"]');
  check('f12DocumentLinkRendered', (await a1.count()) === 1, await c1.innerHTML().catch(() => null));
  check('f12DocumentLinkLabel', (await a1.textContent().catch(() => '') || '').includes('View the published sale list (PDF)'), await a1.textContent().catch(() => null));
  check('f12DocumentLinkHref', (await a1.getAttribute('href').catch(() => '')) === 'https://mvbalaw.com/wp-content/TaxUploads/1126_Bell.pdf', null);
  check('f12NoNotPublishedWhenDocumentExists', !((await c1.textContent()) || '').includes('Auction link not published'), null);
  const c2 = pg.locator('[data-pid="ptxdoc2"].prop-card').first();
  check('f12HttpDocumentNeverLinked', (await c2.locator('a[data-auction-link]').count()) === 0 && ((await c2.textContent()) || '').includes('Auction link not published'), null);
  // The Guided page never calls the sale-list document a "County auction
  // site" (register step: no link; the document keeps its own name).
  await pg.goto(root + 'tx.html?profile=admin&tier=beginner#/auctions', { waitUntil: 'networkidle' }); await pg.waitForTimeout(1500);
  await pg.locator('[data-pid="ptxdoc1"].prop-card .detail-btn[data-action="viewdetails"]').first().click(); await pg.waitForTimeout(800);
  const gl = await pg.evaluate(() => [...document.querySelectorAll('.g-task-link')].map(a => ({ href: a.getAttribute('href'), t: a.textContent.trim() })));
  const gtasks = await pg.locator('.g-task').count();
  check('f12GuidedNeverCallsDocumentAnAuctionSite', gtasks > 0 && gl.every(l => !(/1126_Bell\.pdf/.test(l.href) && /County auction site/.test(l.t))), { gtasks, gl });
  await pg.context().close();
}

// ---------------------------------------------------------------- F50: a county with no rows stays selected
{
  const pg = await open('index.html#/auctions');
  await setSelect(pg, 'countyQuick', 'Clay'); await pg.waitForTimeout(400);
  check('f50SelectKeepsCounty', (await pg.locator('#countyQuick').inputValue()) === 'Clay', await pg.locator('#countyQuick').inputValue());
  check('f50ChipNamesCounty', (await txt(pg, '#filterChips [data-chip="counties"]')).includes('County: Clay'), await txt(pg, '#filterChips'));
  check('f50ListNarrowedToEmptyCounty', (await pg.locator('#main .prop-card').count()) === 0 && (await pg.locator('#main .empty-state').count()) === 1, await pg.locator('#main .prop-card').count());
  await setSelect(pg, 'countyQuick', 'ALL'); await pg.waitForTimeout(400);
  check('f50AllCountiesRestores', (await pg.locator('#main .prop-card').count()) > 0, null);
  await pg.context().close();
}

// ---------------------------------------------------------------- F51: source filter scoped to the ledger
{
  const pg = await open('index.html#/auctions');
  const opts = async () => pg.evaluate(() => [...document.querySelectorAll('#sourceFilter option')].slice(1).map(o => ({ v: o.value, t: o.textContent })));
  const o = await opts();
  check('f51NoRawIdsAsLabels', o.length > 0 && o.every(x => !/^[a-z]{2}_[a-z0-9_]+ \(/.test(x.t)), o);
  check('f51NoAvailableSourcesOnAuctions', o.every(x => !/laft|lienhub|certificate/i.test(x.v)), o.map(x => x.v));
  let allNonEmpty = true;
  for (const x of o) { await setSelect(pg, 'sourceFilter', x.v); await pg.waitForTimeout(250); if ((await pg.locator('#main .prop-card').count()) === 0) allNonEmpty = false; }
  check('f51EveryOfferedSourceHasRows', allNonEmpty, o.map(x => x.v));
  await setSelect(pg, 'sourceFilter', 'any'); await pg.waitForTimeout(250);
  await goLedger(pg, 'laft'); await pg.waitForTimeout(500);
  const o2 = await opts();
  check('f51RebuiltOnLedgerChange', o2.length > 0 && o2.every(x => /laft/i.test(x.v)) && JSON.stringify(o2) !== JSON.stringify(o), o2.map(x => x.v));
  await pg.context().close();
}

// ---------------------------------------------------------------- F52: acquisition method is Available-only
{
  const pg = await open('index.html#/lands');
  check('f52VisibleOnAvailable', await pg.evaluate(() => !document.getElementById('acqModeFilter').closest('.field').hidden), null);
  await setSelect(pg, 'acqModeFilter', 'unverified'); await pg.waitForTimeout(300);
  await goLedger(pg, 'auction'); await pg.waitForTimeout(500);
  check('f52HiddenOnAuctions', await pg.evaluate(() => document.getElementById('acqModeFilter').closest('.field').hidden), null);
  check('f52ResetWhenLeavingAvailable', (await pg.locator('#acqModeFilter').inputValue()) === 'any' && (await pg.locator('#main .prop-card').count()) > 0, await pg.locator('#main .prop-card').count());
  check('f52NoAcqModeChipOnAuctions', (await pg.locator('#filterChips [data-chip="ctl:acqModeFilter"]').count()) === 0, null);
  await goLedger(pg, 'certificate'); await pg.waitForTimeout(400);
  check('f52HiddenOnLiens', await pg.evaluate(() => document.getElementById('acqModeFilter').closest('.field').hidden), null);
  await pg.context().close();
}

// ---------------------------------------------------------------- F87: TX Min Bid carries Texas values only
{
  const pg = await open('mi.html#/auctions');
  await pg.evaluate(() => { const t = document.getElementById('filtersToggle'); if (t && !document.getElementById('filtersPanel').classList.contains('open')) t.click(); });
  const dl = pg.waitForEvent('download');
  await pg.evaluate(() => document.getElementById('exportCsvBtn').click());
  const csv = fs.readFileSync(await (await dl).path(), 'utf8');
  const lines = csv.split(/\r?\n/).filter(Boolean);
  const header = lines[0].split(','); const i = header.indexOf('"TX Min Bid"') >= 0 ? header.indexOf('"TX Min Bid"') : header.indexOf('TX Min Bid');
  const col = lines.slice(1).map(l => (l.split(',')[i] || '').replace(/"/g, ''));
  check('f87MichiganExportHasNoTxMinBidValue', i >= 0 && col.every(v => v === ''), { i, col });
  await pg.context().close();
}

// ---------------------------------------------------------------- F88: one name for the Texas liens ledger
{
  const pg = await open('tx.html#/certificates');
  const title = await txt(pg, '#listTitle'), sub = await txt(pg, '#listSubtitle'), empty = await txt(pg, '#main .empty-state');
  check('f88NoCountyHeldCertificatesOnTexas', !/County-held certificates/.test(sub), sub);
  check('f88EmptyTextUsesLedgerName', !/No liens or certificates/.test(empty), empty);
  const strip = await txt(pg, '#main .ledger-status .ls-item:first-child');
  check('f88OfferedHereStatedOnce', !/not verified.*not verified/i.test(strip), strip);
  check('f88TitleIsRedeemableDeeds', /^Redeemable Deeds in Texas/.test(title), title);
  await pg.context().close();
  const fl = await open('index.html#/certificates');
  check('f88FloridaKeepsCountyHeldCertificates', /County-held certificates/.test(await txt(fl, '#listSubtitle')), await txt(fl, '#listSubtitle'));
  await fl.context().close();
}

// ---------------------------------------------------------------- F99: singular units on Home
{
  const pg = await open('index.html#/dashboard');
  const unit = await txt(pg, '.home-ledger-card[data-ledger="certificate"] .home-ledger-unit');
  const cnt = await txt(pg, '.home-ledger-card[data-ledger="certificate"] .home-ledger-count');
  check('f99OneCertificateSingular', cnt === '1' && /^certificate across 1 county/.test(unit), { cnt, unit });
  await pg.context().close();
}

// ---------------------------------------------------------------- F10 / F20: phone keeps its scroll position
for (const look of ['classic', 'merged']) {
  const pg = await open(`mi.html?profile=admin&bigcounty=120&look=${look}#/lands`, { viewport: { width: 390, height: 844 }, touch: true, settle: 1800 });
  await pg.evaluate(() => window.scrollTo(0, Math.max(0, document.documentElement.scrollHeight - window.innerHeight - 200))); await pg.waitForTimeout(300);
  const y0 = await pg.evaluate(() => window.scrollY);
  const btn = pg.locator('[data-action="bidlist"][data-pid]').filter({ visible: true }).first();
  await btn.evaluate(el => el.scrollIntoView({ block: 'center' })); await pg.waitForTimeout(200);
  const y1 = await pg.evaluate(() => window.scrollY);
  const pid = await btn.getAttribute('data-pid');
  await btn.tap(); await pg.waitForTimeout(600);
  const y2 = await pg.evaluate(() => window.scrollY);
  check(`f10WatchTapKeepsScroll_${look}`, y0 > 400 && Math.abs(y2 - y1) < 60, { y0, y1, y2 });   // y0 floor 400 (was 500): county heads are shorter since 2026-11-10
  check(`f47WatchButtonFlippedInPlace_${look}`, await pg.evaluate(pid => [...document.querySelectorAll(`[data-action="bidlist"][data-pid="${pid}"]`)].every(b => b.classList.contains('on')), pid), pid);
  await pg.context().close();
  // Background pages arriving while scrolled down.
  const pg2 = await open(`mi.html?profile=admin&bigcounty=120&look=${look}&maxrows=15&ledgerdelay=buy:600#/lands`, { viewport: { width: 390, height: 844 }, touch: true, wait: 'commit', settle: 1500 });
  await pg2.evaluate(() => window.scrollTo(0, Math.min(1200, document.documentElement.scrollHeight - window.innerHeight))); await pg2.waitForTimeout(100);
  const ys = [];
  for (let i = 0; i < 6; i++) { await pg2.waitForTimeout(350); ys.push(await pg2.evaluate(() => window.scrollY)); }
  check(`f20PagesArrivingKeepScroll_${look}`, ys[0] > 300 && ys.every(y => Math.abs(y - ys[0]) < 60), ys);
  await pg2.context().close();
}

// ---------------------------------------------------------------- F47: a Watch tap does not rebuild the list
{
  const rows = Array.from({ length: 700 }, (_, i) => `{ id: "pcert${i}", source: "certificate", state: "FL", county: "${['Alachua', 'Bay', 'Duval', 'Lee', 'Polk'][i % 5]}", case_no: "CC-${i}", certificate_no: "C-${i}", tax_year: "2023", parcel: "${1000 + i}", bid: ${500 + i}, interest_rate: 18, issued_date: "2024-06-01", expiration_date: "2031-06-01", url_auction: "https://lienhub.com/x", url_auction_kind: "county", status: "active", updated_at: "2026-10-01T00:00:00Z", ledger_type: "lien" }`);
  const pg = await open('index.html#/certificates', { init: `window.__stubExtraRows = [${rows.join(',')}];`, settle: 2500 });
  const n = Number(((await txt(pg, '#navCountCertificate')) || '').replace(/[^0-9]/g, ''));
  check('f47FixtureVolumeLoaded', n >= 300, n);
  await pg.evaluate(() => { window.__renders = 0; window.addEventListener('tdw:rendered', () => window.__renders++); document.querySelector('#main [data-action="bidlist"]').dataset.marker = 'kept'; });
  const t = await pg.evaluate(() => new Promise(res => {
    const btn = document.querySelector('#main [data-action="bidlist"]');
    const t0 = performance.now(); btn.click();
    requestAnimationFrame(() => requestAnimationFrame(() => res(performance.now() - t0)));
  }));
  await pg.waitForTimeout(400);
  const after = await pg.evaluate(() => ({ renders: window.__renders, kept: !!document.querySelector('#main [data-action="bidlist"][data-marker="kept"]'), on: document.querySelector('#main [data-action="bidlist"]').classList.contains('on'), count: (document.getElementById('navWatchlistCount') || {}).textContent }));
  check('f47NoFullRenderOnWatchTap', after.renders === 0, after);
  check('f47ButtonOnAndCountUpdated', after.on && /^1\//.test(after.count || ''), after);
  check('f47PaintUnder300ms', t < 300, t);
  await pg.context().close();
}

// ---------------------------------------------------------------- review: in-place Watch keeps the sale-day strip current
{
  const pg = await open('index.html#/auctions');
  const info = await pg.evaluate(() => {
    const btn = document.querySelector('#main .prop-card [data-action="bidlist"][data-pid].bid-btn:not(.on)');
    if (!btn) return null;
    let el = btn.closest('.prop-card'), date = null;
    const divs = [...document.querySelectorAll('#main .date-divider')];
    for (const d of divs) if (d.compareDocumentPosition(el) & Node.DOCUMENT_POSITION_FOLLOWING) date = d.dataset.date;
    return { pid: btn.dataset.pid, date };
  });
  const chip = info && info.date ? pg.locator(`#saleStrip .ss-day[data-date="${info.date}"]`) : null;
  if (chip && await chip.count()) { await chip.click(); await pg.waitForTimeout(200); }
  const dots0 = await pg.locator('#saleStrip .ss-watch').count();
  await pg.evaluate(() => { window.__renders = 0; window.addEventListener('tdw:rendered', () => window.__renders++); });
  await pg.evaluate(pid => document.querySelector(`#main [data-action="bidlist"][data-pid="${pid}"]`).click(), info && info.pid);
  await pg.waitForTimeout(500);
  const after = await pg.evaluate(() => ({ renders: window.__renders, dots: document.querySelectorAll('#saleStrip .ss-watch').length, panel: (document.querySelector('#saleStrip .ss-panel') || {}).textContent || '' }));
  check('reviewStripDotAfterWatchTap', !!chip && after.renders === 0 && after.dots === dots0 + 1, { info, dots0, after });
  check('reviewStripWatchedFactAfterWatchTap', /1 watched/.test(after.panel), after.panel.replace(/\s+/g, ' ').slice(0, 200));
  // A second tap removes it again: the dot and the fact go.
  await pg.evaluate(pid => document.querySelector(`#main [data-action="bidlist"][data-pid="${pid}"]`).click(), info && info.pid);
  await pg.waitForTimeout(500);
  const back = await pg.evaluate(() => ({ dots: document.querySelectorAll('#saleStrip .ss-watch').length, panel: (document.querySelector('#saleStrip .ss-panel') || {}).textContent || '' }));
  check('reviewStripClearedAfterUnwatch', back.dots === dots0 && !/1 watched/.test(back.panel), back.dots);
  // The Watchlist page's Remove / Cancel rows are not toggles.
  await pg.evaluate(pid => document.querySelector(`#main [data-action="bidlist"][data-pid="${pid}"]`).click(), info && info.pid);
  await pg.waitForTimeout(400);
  // A Watchlist-page Remove row for that watched property (the page builds one
  // for a saved item no longer listed), then another card's Watch tap.
  await pg.evaluate(pid => { const r = document.createElement('button'); r.className = 'reset-btn'; r.dataset.action = 'bidlist'; r.dataset.pid = pid; r.type = 'button'; r.textContent = 'Remove'; r.id = 'reviewRemoveRow'; document.body.appendChild(r); r.addEventListener('click', e => e.stopPropagation(), true); }, info && info.pid);
  await pg.evaluate(() => { const b = [...document.querySelectorAll('#main .bid-btn[data-action="bidlist"]:not(.on)')][0]; if (b) b.click(); });
  await pg.waitForTimeout(400);
  const stray = await pg.evaluate(() => ({ removeRows: document.querySelectorAll('.reset-btn[data-action="bidlist"]').length, stray: document.querySelectorAll('.reset-btn[data-action="bidlist"].on, .reset-btn[data-action="bidlist"].pending').length }));
  check('reviewRemoveRowsNeverToggled', stray.removeRows > 0 && stray.stray === 0, stray);
  await pg.context().close();
}

// ---------------------------------------------------------------- review: "Then by" alone keeps the default groups
{
  const pg = await open('index.html#/auctions');
  const order = () => pg.evaluate(() => [...document.querySelectorAll('#main .county-group, #main [data-county-group], #main .group-head')].map(g => g.dataset.county || g.textContent.trim().slice(0, 30)));
  const dates = () => pg.evaluate(() => [...document.querySelectorAll('#main .date-divider')].map(d => d.dataset.date || ''));
  const d0 = await dates();
  await setSelect(pg, 'sortSecondary', 'bidDesc'); await pg.waitForTimeout(300);
  const d1 = await dates();
  check('reviewThenByKeepsDateClusters', d1.length > 1 && JSON.stringify(d1) === JSON.stringify(d0) && d1.every((d, i) => i === 0 || d1[i - 1] <= d), { d0, d1 });
  await pg.context().close();
}

// ---------------------------------------------------------------- review: a source picked on another ledger is reset
{
  const pg = await open('index.html#/lands');
  const v = await pg.evaluate(() => { const o = [...document.querySelectorAll('#sourceFilter option')].find(o => o.value !== 'any'); return o && o.value; });
  await setSelect(pg, 'sourceFilter', v); await pg.waitForTimeout(300);
  await goLedger(pg, 'auction'); await pg.waitForTimeout(600);
  const r = await pg.evaluate(() => ({ sel: document.getElementById('sourceFilter').value, cards: document.querySelectorAll('#main .prop-card').length, chips: (document.getElementById('filterChips') || {}).textContent || '' }));
  check('reviewSourceResetOnLedgerChange', !!v && r.sel === 'any' && r.cards > 0 && !/Source:/.test(r.chips), { v, r });
  await pg.context().close();
}

// ---------------------------------------------------------------- F28: same-parcel lookups through the index, map work gated
{
  const pg = await open('mi.html?profile=admin&bigcounty=6000#/lands', { settle: 3000 });
  await pg.click('#navRail [data-page="map"], #hdrNav [data-page="map"]').catch(() => pg.evaluate(() => (document.querySelector('[data-page="map"]') || {}).click()));
  await pg.waitForTimeout(1500);
  await pg.evaluate(() => (document.querySelector('#navRail [data-nav-ledger="laft"], #hdrNav [data-nav-ledger="laft"], [data-nav-ledger="laft"]') || {}).click());
  await pg.waitForTimeout(800);
  const ms = await pg.evaluate(() => { const el = document.getElementById('countyQuick'); const t0 = performance.now(); el.value = 'Wayne'; el.dispatchEvent(new Event('change', { bubbles: true })); return performance.now() - t0; });
  check('f28CountyPickOnListUnder400ms', ms < 400, ms);
  const ms2 = await pg.evaluate(() => { const el = document.getElementById('sortBy'); const t0 = performance.now(); el.value = 'address'; el.dispatchEvent(new Event('change', { bubbles: true })); return performance.now() - t0; });
  check('f28SortOnListUnder400ms', ms2 < 400, ms2);
  await pg.evaluate(() => (document.querySelector('[data-page="map"]') || {}).click()); await pg.waitForTimeout(2000);
  const strip = await pg.evaluate(() => { const s = document.getElementById('exploreStrip'); return s ? { hidden: s.hidden, total: s.dataset.total } : null; });
  check('f28MapStripDrawnWhenShown', !!strip && !strip.hidden && Number(strip.total) > 0, strip);
  await pg.context().close();
}

await b.close();
if (errs.length) console.log('page errors: ' + JSON.stringify(errs));
check('noPageErrors', errs.length === 0, errs);
console.log(fail ? `${fail} FAILED` : 'ALL PASSED');
process.exit(fail ? 1 : 0);
