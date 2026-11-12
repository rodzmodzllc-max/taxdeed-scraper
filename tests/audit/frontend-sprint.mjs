// Front-end sprint (2026-11-11).
//  - Auctions and Liens carry the same Buyer's Guide link under the title as
//    Available; the question text and the county count are gone; Liens keeps
//    its program line. The link opens that ledger's guide.
//  - "A new version is ready": never on a first load; when shown it has a
//    Refresh button and can be dismissed.
//  - A cold start on #/guide shows the guide and never falls back to the list.
//  - The aerial picture's outline credit on the property page is folded to one
//    line with the full credit inside (folded, never dropped).
//  - The Map page's preview picture gets the Tilt view button when a MapTiler
//    key is configured, and not without one.
// Usage: BASE_URL=http://localhost:9202/index.html node tests/audit/frontend-sprint.mjs
import { chromium } from 'playwright';
import fs from 'fs';
const BASE = process.env.BASE_URL || 'http://localhost:9202/index.html';
const exe = '/opt/pw-browsers/chromium';
const b = await chromium.launch(fs.existsSync(exe) ? { executablePath: exe } : {});
let fail = 0;
const check = (name, ok, got) => { console.log((ok ? 'PASS ' : 'FAIL ') + name + (ok ? '' : ' -> ' + JSON.stringify(got))); if (!ok) fail++; };
const errs = [];
const DESK = { width: 1440, height: 900 };
const HOST = `(document.getElementById('detailModal') && !document.getElementById('detailModal').hidden ? document.getElementById('detailModalInner') : document.getElementById('detailPanel'))`;

async function ctxPage(opts = {}) {
  const ctx = await b.newContext({ viewport: opts.viewport || DESK, serviceWorkers: 'block' });
  const pg = await ctx.newPage();
  pg.on('pageerror', e => errs.push((opts.tag || 'page') + ': ' + e.message));
  if (opts.key) await pg.route('**/config.js', async route => {
    const res = await route.fetch();
    const body = (await res.text()) + '\n;window.TDW_CONFIG = Object.assign(window.TDW_CONFIG || {}, { maptilerKey: "test-key" });';
    await route.fulfill({ response: res, body, headers: Object.assign({}, res.headers(), { 'content-type': 'application/javascript' }) });
  });
  return { ctx, pg };
}

// ---- subtitles
for (const [hash, ledger, re, extra] of [['#/auctions', 'AUCTIONS', /^Buyer's Guide: how tax-sale auctions work →/, null],
  ['#/certificates', 'LIENS_CERTIFICATES', /^Buyer's Guide: how liens and certificates work →/, /County-held certificates/]]) {
  const { ctx, pg } = await ctxPage({ tag: 'sub ' + hash });
  await pg.goto(BASE + '?look=merged' + hash, { waitUntil: 'networkidle' });
  await pg.waitForTimeout(900);
  const r = await pg.evaluate(() => { const s = document.getElementById('listSubtitle'); const l = s.querySelector('.list-guide-link'); return { text: s.textContent.replace(/\s+/g, ' ').trim(), links: s.querySelectorAll('.list-guide-link').length, ledger: l ? l.dataset.guideLedger : null }; });
  check('guideLinkUnderTitle ' + hash, r.links === 1 && re.test(r.text) && r.ledger === ledger && !/What is coming up|What tax lien|\d+ count/i.test(r.text) && (!extra || extra.test(r.text)), r);
  await pg.click('#listSubtitle .list-guide-link');
  await pg.waitForTimeout(1200);
  const g = await pg.evaluate(() => ({ hash: decodeURIComponent(location.hash), shown: !document.getElementById('pageGuide').hidden }));
  check('guideLinkOpensLedgerGuide ' + hash, g.shown && g.hash.includes('ledger=' + ledger), g);
  await ctx.close();
}

// ---- a look that draws the ledger: Classic's hidden cards are not built; they appear at once when Classic shows
{
  const { ctx, pg } = await ctxPage({ tag: 'defer' });
  await pg.goto(BASE + '?look=merged#/lands', { waitUntil: 'networkidle' });
  await pg.waitForTimeout(1000);
  const snap = () => pg.evaluate(() => ({ engine: document.documentElement.dataset.experience, ready: document.documentElement.dataset.experienceReady || null,
    mainCards: document.querySelectorAll('#main .prop-card').length, stageCards: document.querySelectorAll('#xpStage [data-pid]').length, deferred: window.__tdwDeferredCards(),
    mainShown: getComputedStyle(document.getElementById('main')).display !== 'none' }));
  await pg.click('[data-nav-ledger="auction"]'); await pg.waitForTimeout(900);
  await pg.click('[data-nav-ledger="laft"]'); await pg.waitForTimeout(900);
  await pg.click('[data-nav-ledger="auction"]'); await pg.waitForTimeout(900);
  const look = await snap();
  check('lookDrawsAndClassicCardsAreDeferred', look.engine === 'tactile' && look.ready === 'tactile' && !look.mainShown && look.stageCards > 0 && look.mainCards === 0 && look.deferred > 0, look);
  // The look hands the display back (as it does for an empty or failed ledger).
  await pg.evaluate(() => { delete document.documentElement.dataset.experienceReady; });
  await pg.waitForTimeout(250);
  const back = await snap();
  check('classicIsCompleteTheMomentItShows', back.mainShown && back.mainCards > 0 && back.deferred === 0, back);
  // Picking Classic outright.
  await pg.goto(BASE + '?look=merged#/auctions', { waitUntil: 'networkidle' }); await pg.waitForTimeout(900);
  await pg.click('[data-nav-ledger="laft"]'); await pg.waitForTimeout(700);
  await pg.click('[data-nav-ledger="auction"]'); await pg.waitForTimeout(700);
  await pg.evaluate(() => { const bt = document.querySelector('#lookMenu [data-look="classic"]'); if (bt) bt.click(); });
  await pg.waitForTimeout(900);
  const classic = await snap();
  check('pickingClassicBuildsItsCards', classic.engine === 'classic' && classic.mainShown && classic.mainCards > 0 && classic.deferred === 0, classic);
  await ctx.close();
}

// ---- Merged: the other ledgers' modules arrive while idle, so the FIRST switch builds no Classic cards either
{
  const { ctx, pg } = await ctxPage({ tag: 'preload' });
  await pg.goto(BASE + '?look=merged#/lands', { waitUntil: 'networkidle' });
  await pg.waitForFunction(() => performance.getEntriesByType('resource').some(r => /experience-tactile\.js/.test(r.name)), null, { timeout: 15000 }).catch(() => {});
  await pg.waitForTimeout(600);
  const before = await pg.evaluate(() => ({ mods: ['terrain', 'tactile', 'merged'].filter(n => performance.getEntriesByType('resource').some(r => r.name.includes('experience-' + n + '.js'))),
    engine: document.documentElement.dataset.experience, ready: document.documentElement.dataset.experienceReady || null, stage: document.getElementById('xpStage').dataset.xp || null }));
  check('otherLookModulesPreloadedAndIdle', before.mods.length === 3 && before.engine === 'terrain' && before.ready === 'terrain', before);
  let built = 0;
  await pg.exposeFunction('__noteMainCards', n => { built = Math.max(built, n); });
  await pg.evaluate(() => { new MutationObserver(() => window.__noteMainCards(document.querySelectorAll('#main .prop-card').length)).observe(document.getElementById('main'), { childList: true, subtree: true }); });
  await pg.click('[data-nav-ledger="auction"]'); await pg.waitForTimeout(1200);
  const after = await pg.evaluate(() => ({ engine: document.documentElement.dataset.experience, ready: document.documentElement.dataset.experienceReady || null, stageCards: document.querySelectorAll('#xpStage [data-pid]').length }));
  check('firstSwitchBuildsNoClassicCards', built === 0 && after.ready === 'tactile' && after.stageCards > 0, { built, after });
  await ctx.close();
}

// ---- Terrain card: the picture caption and the outline credit do not cover each other
{
  const { ctx, pg } = await ctxPage({ tag: 'caption' });
  await pg.route('**/config.js', async route => { const r = await route.fetch(); await route.fulfill({ response: r, body: (await r.text()).replace('naipLiveImagery: false', 'naipLiveImagery: true') }); });
  await pg.route('https://imagery.nationalmap.gov/**', route => route.fulfill({ status: 200, contentType: 'image/png', body: Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==', 'base64') }));
  await pg.addInitScript(rs => { window.__stubExtraRows = rs; }, [{ id: 'capt1', source: 'laft', state: 'FL', county: 'Bay', case_no: 'CAP-1', parcel: '17920-000-000', address: '1 Caption Way', bid: 1200, purchase_amount: 1200, purchase_amount_kind: 'ORIGINAL_OPENING_BID', status: 'active', ledger_type: 'buy', latitude: 30.163, longitude: -85.6518, lien_level: 'unscreened', publication_status: 'APPROVED', inventory_status: 'available_otc', last_seen_at: new Date().toISOString(), updated_at: new Date().toISOString() }]);
  await pg.goto(BASE + '?look=merged&boundary=ok#/lands', { waitUntil: 'networkidle' });
  await pg.waitForSelector('#xpStage .prop-card-photo > .pb-attrib', { timeout: 15000 }).catch(() => {});
  await pg.waitForTimeout(500);
  const got = await pg.evaluate(() => Array.from(document.querySelectorAll('#xpStage .prop-card-photo')).map(h => {
    const c = h.querySelector(':scope > .photo-caption'), a = h.querySelector(':scope > .pb-attrib');
    if (!c || !a || !c.offsetParent || !a.offsetParent) return null;
    const cb = c.getBoundingClientRect(), ab = a.getBoundingClientRect(), hb = h.getBoundingClientRect();
    return { apart: cb.bottom <= ab.top + 1 || ab.bottom <= cb.top + 1 || cb.right <= ab.left + 1 || ab.right <= cb.left + 1, inside: cb.top >= hb.top - 1 && ab.bottom <= hb.bottom + 1 };
  }).filter(Boolean));
  check('terrainCaptionClearsOutlineCredit', got.length > 0 && got.every(g => g.apart && g.inside), got);
  await ctx.close();
}

// ---- update prompt
{
  const { ctx, pg } = await ctxPage({ tag: 'update' });
  await pg.goto(BASE + '?look=merged#/lands', { waitUntil: 'networkidle' });
  await pg.waitForTimeout(700);
  const none = await pg.evaluate(() => !!document.getElementById('updateReady'));
  check('noUpdatePromptOnAFirstLoad', none === false, none);
  const shown = await pg.evaluate(() => { window.__tdwShowUpdateReady(); window.__tdwShowUpdateReady(); const bar = document.getElementById('updateReady');
    return { bars: document.querySelectorAll('#updateReady').length, role: bar.getAttribute('role'), text: bar.textContent.replace(/\s+/g, ' ').trim(), go: !!bar.querySelector('.update-ready-go'), vis: bar.checkVisibility() }; });
  check('updatePromptHasRefresh', shown.bars === 1 && shown.role === 'status' && /new version of TAXACQ is ready/i.test(shown.text) && shown.go && shown.vis, shown);
  await pg.click('#updateReady .update-ready-x');
  check('updatePromptDismisses', await pg.evaluate(() => !document.getElementById('updateReady')), null);
  await ctx.close();
}

// ---- guide on a cold start
{
  const { ctx, pg } = await ctxPage({ tag: 'guide' });
  await pg.goto(BASE + '?look=merged#/guide?ledger=AVAILABLE', { waitUntil: 'commit' });
  const seen = [];
  for (let i = 0; i < 60; i++) {
    const v = await pg.evaluate(() => { const app = document.getElementById('app'); if (!app || app.hidden) return 'signin'; const p = document.querySelector('.page:not([hidden])'); return p ? p.id : '-'; }).catch(() => 'nav');
    if (seen[seen.length - 1] !== v) seen.push(v);
    await pg.waitForTimeout(50);
  }
  const i = seen.indexOf('pageGuide');
  check('guideColdStartShowsGuideAndStays', i >= 0 && !seen.slice(i).includes('pageList') && seen[seen.length - 1] === 'pageGuide', seen);
  const body = await pg.evaluate(() => ({ title: (document.querySelector('#pageGuide .bg-title') || {}).textContent, steps: document.querySelectorAll('#pageGuide .bg-jump').length }));
  check('guideColdStartIsDrawn', /Available property in Florida/.test(body.title || '') && body.steps > 0, body);
  await ctx.close();
}

// ---- the aerial picture's outline credit is folded (no MapTiler key: the picture stays the aerial)
{
  const { ctx, pg } = await ctxPage({ tag: 'credit' });
  // The live aerial, as tests/run_test.mjs boundaryPage() sets it up; the imagery host is answered locally.
  const PNG = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==', 'base64');
  await pg.route('**/config.js', async route => { const r = await route.fetch(); await route.fulfill({ response: r, body: (await r.text()).replace('naipLiveImagery: false', 'naipLiveImagery: true') }); });
  await pg.route('https://imagery.nationalmap.gov/**', route => route.fulfill({ status: 200, contentType: 'image/png', body: PNG }));
  await pg.goto(BASE + '?look=merged&boundary=ok#/auctions/p5', { waitUntil: 'networkidle' });
  await pg.waitForTimeout(1200);
  const r = await pg.evaluate(new Function(`const h = ${HOST}; const hero = h.querySelector('.detail-hero-photo'); const f = hero && hero.nextElementSibling;
    return { hero: !!hero, outline: !!(hero && hero.querySelector('.parcel-boundary')), tag: f ? f.tagName : null, cls: f ? String(f.className) : null, open: f ? f.open : null,
      label: f && f.querySelector('summary') ? f.querySelector('summary').getAttribute('aria-label') : null, text: f ? f.textContent.replace(/\\s+/g, ' ').trim().slice(0, 40) : null,
      full: f && f.querySelector('.pb-credit') ? f.querySelector('.pb-credit').textContent.length : 0, shown: f && f.querySelector('.pb-credit') ? f.querySelector('.pb-credit').checkVisibility() : null };`));
  check('aerialOutlineCreditFolded', r.hero && r.outline && r.tag === 'DETAILS' && /pb-credit-fold/.test(r.cls) && r.open === false && /source, licence and terms/.test(r.label || '')
    && /^Parcel outline: /.test(r.text || '') && r.full > 80 && r.shown === false, r);
  await ctx.close();
}

// ---- Map preview picture: Tilt view only with a key (an admin stays on the outline map, which needs no map library)
for (const key of [false, true]) {
  const { ctx, pg } = await ctxPage({ tag: 'peek ' + key, key });
  await pg.goto(BASE + '?look=merged&profile=admin#/map', { waitUntil: 'networkidle' });
  await pg.waitForTimeout(900);
  const picked = await pg.evaluate(() => { const s = document.getElementById('mapCountySelect'); const o = [...s.options].find(x => x.value === 'Charlotte'); if (!o) return false; s.value = 'Charlotte'; s.dispatchEvent(new Event('change', { bubbles: true })); return true; });
  await pg.waitForTimeout(1500);
  const card = pg.locator('#mapWorkspace .strip-card[data-pid]').first();
  if (picked && await card.count()) { await card.click(); await pg.waitForTimeout(1200); }
  const r = await pg.evaluate(() => { const p = document.getElementById('explorePreview'); const v = p && p.querySelector('.pv-visual'); const t = v && v.querySelector(':scope > .pc-tilt-btn'); const c = p && p.querySelector('.preview-close'); const mid = e => { const r = e.getBoundingClientRect(); return document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2); };
    return { style: [...document.querySelectorAll('#mapStyleToggle .on')].map(x => x.id), peek: !!p && !p.hidden, visual: !!v, btn: !!t, pid: p ? p.dataset.pid : null,
      closeFree: c ? (m => m === c || c.contains(m))(mid(c)) : null, tiltFree: t ? (m => m === t)(mid(t)) : null }; });
  if (!r.visual) check('previewTilt ' + (key ? 'withKey' : 'noKey') + ' (fixture has a preview picture)', false, { picked, r });
  else check('previewTilt ' + (key ? 'withKey' : 'noKey'), r.btn === key, r);
  // The Tilt view button never covers the preview's close button (it did on 2026-11-11).
  if (key) check('previewTiltLeavesCloseButtonFree', r.closeFree === true && r.tiltFree === true, r);
  await ctx.close();
}

await b.close();
if (errs.length) { console.log('PAGE ERRORS:\n' + errs.join('\n')); fail++; }
console.log(fail ? `${fail} FAILED` : 'ALL PASS');
process.exit(fail ? 1 : 0);
