// Audit theme "home-declutter" (2026-11-09): customer Home shows customer
// value only (hero, ledger strip, Next up, Saved, Recent, county chips); the
// operating view is admin-only and folded; withheld counts never wear the
// Auctions colour; desk heads outrank their "All ..." links; a skip link
// leads every app page; hiding a property is undone from a toast; the boot
// failure card is on the brand; the county page keeps one line per source;
// the watchlist page is one column.
import { chromium } from 'playwright';
import fs from 'fs';
const BASE = process.env.BASE_URL || 'http://localhost:8934/index.html';
const root = BASE.replace(/[^/]*$/, '');
const exe = '/opt/pw-browsers/chromium';
const b = await chromium.launch(fs.existsSync(exe) ? { executablePath: exe } : {});
let fail = 0;
const check = (name, ok, got) => { console.log((ok ? 'PASS ' : 'FAIL ') + name + (ok ? '' : ' -> ' + JSON.stringify(got))); if (!ok) fail++; };
const errs = [];
async function open(path, { vp = { width: 1440, height: 900 }, init = null } = {}) {
  const ctx = await b.newContext({ viewport: vp });
  const pg = await ctx.newPage();
  pg.on('pageerror', e => errs.push(path + ': ' + e.message));
  if (init) await pg.addInitScript(init);
  await pg.goto(root + path, { waitUntil: 'networkidle' });
  await pg.waitForTimeout(1300);
  return pg;
}
const rgb = c => (c.match(/\d+(\.\d+)?/g) || []).slice(0, 3).map(Number);

// 1. A customer's Home carries no operator diagnostics.
{
  const pg = await open('index.html?look=merged#/dashboard');
  const r = await pg.evaluate(() => {
    const ops = document.getElementById('homeOps');
    const page = document.getElementById('pageDashboard');
    return {
      opsHidden: !ops || ops.hidden || ops.offsetParent === null,
      opsRows: document.querySelectorAll('#dashAttentionRows .dash-row, #dashSourceRows .health-row, #dashUnitRows .unit-row').length,
      text: page.innerText,
      order: ['homeHero', 'homeLedgers', 'homeDesk', 'homeSaved', 'homeRecentSection', 'homeCountyDesk']
        .map(id => document.getElementById(id)).filter(Boolean).map(e => e.getBoundingClientRect().top),
      statesCard: !!document.getElementById('homeStatesCard'),
      allStates: (document.getElementById('homeAllStates') || {}).textContent || ''
    };
  });
  check('customerHomeOpsHidden', r.opsHidden, r);
  check('customerHomeNoOpsRows', r.opsRows === 0, r.opsRows);
  check('customerHomeNoDataSources', !/Data sources|Operating view|Needs attention/.test(r.text), r.text.slice(0, 300));
  check('customerHomeNoHarvesterIds', !/\b(fl_realauction|fl_laft_html|fl_lienhub_certificates|tx_lgbs)\b/.test(r.text), null);
  check('homeSectionOrder', r.order.length === 6 && r.order.every((t, i) => i === 0 || t >= r.order[i - 1]), r.order);
  check('statesCardReplacedByLink', !r.statesCard && /^All \d+ states$/.test(r.allStates.trim()), r);

  // Withheld counts: soft ink, never the Auctions rust.
  const wh = await pg.evaluate(() => [...document.querySelectorAll('.home-ledger-withheld')].map(e => ({ c: getComputedStyle(e).color, t: e.title })));
  check('withheldPresent', wh.length > 0, wh);
  check('withheldNotRust', wh.every(w => { const [r0, g, bl] = (w.c.match(/\d+/g) || []).map(Number); return !(r0 > 140 && g < 110 && bl < 80); }), wh);
  check('withheldReasonInTitle', wh.every(w => w.t.length > 10), wh);

  // Desk heads are real headings, larger than their "All ..." links.
  const heads = await pg.evaluate(() => [...document.querySelectorAll('#homeDesk .home-desk-head, #homeCountyDesk .home-desk-head')].map(h => {
    const h2 = h.querySelector('h2'), a = h.querySelector('.link-btn');
    return { h2: h2 ? parseFloat(getComputedStyle(h2).fontSize) : 0, link: a ? parseFloat(getComputedStyle(a).fontSize) : 0, hasLink: !!a };
  }));
  check('deskHeadsOutrankLinks', heads.length >= 3 && heads.filter(h => h.hasLink).every(h => h.h2 > h.link), heads);

  // Ledger cards: no mid-word clamp.
  const clamp = await pg.evaluate(() => [...document.querySelectorAll('.home-ledger-blurb')].map(e => getComputedStyle(e).webkitLineClamp));
  check('ledgerBlurbNotClamped', clamp.every(c => c === 'none' || c === 'unset' || c === ''), clamp);

  // Skip link first in body.
  const skip = await pg.evaluate(() => { const f = document.body.firstElementChild; return { id: f && f.id, text: f && f.textContent.trim() }; });
  check('skipLinkFirst', skip.id === 'skipToListings' && skip.text === 'Skip to listings', skip);
  await pg.focus('#skipToListings');
  await pg.keyboard.press('Enter');
  await pg.waitForTimeout(400);
  const after = await pg.evaluate(() => ({ list: !document.getElementById('pageList').hidden, focus: document.activeElement && document.activeElement.id, hash: location.hash }));
  check('skipLinkGoesToListings', after.list && after.focus === 'listTitle' && after.hash !== '#main', after);
  await pg.context().close();
}

// 2. An administrator sees the operating view, folded, with the admin link.
{
  const pg = await open('index.html?look=merged&profile=admin#/dashboard');
  const r = await pg.evaluate(() => {
    const ops = document.getElementById('homeOps');
    const det = ops && ops.querySelector('details.home-ops');
    return { shown: !!ops && !ops.hidden, folded: !!det && !det.open, link: !!(det && det.querySelector('a[href="admin.html#freshness"]')),
      rows: document.querySelectorAll('#dashAttentionRows .dash-row').length, runIds: [...document.querySelectorAll('#dashRunRows .run-source-id')].map(c => c.textContent) };
  });
  check('adminOpsShown', r.shown, r);
  check('adminOpsFolded', r.folded, r);
  check('adminOpsLink', r.link, r);
  check('adminOpsRowsBuilt', r.rows > 0, r);
  await pg.context().close();
}

// 3. Hiding a property: no dialog, an Undo toast that restores it.
{
  const pg = await open('index.html?look=classic#/auctions');
  let dialogs = 0;
  pg.on('dialog', d => { dialogs++; d.dismiss(); });
  const pid = await pg.evaluate(() => { const b = document.querySelector('#main [data-action="hide"][data-pid]'); return b ? b.dataset.pid : null; });
  if (pid) {
    await pg.evaluate(id => document.querySelector(`#main [data-action="hide"][data-pid="${id}"]`).click(), pid);
    await pg.waitForTimeout(500);
    const t = await pg.evaluate(() => { const x = document.querySelector('.tdw-toast'); return x ? { text: x.innerText, undo: !!x.querySelector('.tdw-toast-action') } : null; });
    check('hideNoDialog', dialogs === 0, dialogs);
    check('hideUndoToast', !!t && t.undo && /hidden/i.test(t.text), t);
    const gone = await pg.evaluate(id => !document.querySelector(`#main .prop-card[data-pid="${id}"]`), pid);
    check('hideHidesAtOnce', gone, pid);
    await pg.click('.tdw-toast .tdw-toast-action');
    await pg.waitForTimeout(600);
    const back = await pg.evaluate(id => !!document.querySelector(`#main .prop-card[data-pid="${id}"]`), pid);
    check('undoRestores', back, pid);
  } else check('hideButtonFound', false, null);
  await pg.context().close();
}

// 4. The boot failure card is on the brand.
{
  // A page whose app module never starts: block app.js so no screen is shown.
  const ctx = await b.newContext({ viewport: { width: 390, height: 844 } });
  await ctx.route('**/app.js*', r => r.abort());
  await ctx.addInitScript(() => { window.__tdwBootTimeoutMs = 400; });
  const pg = await ctx.newPage();
  await pg.goto(root + 'index.html', { waitUntil: 'load' });
  await pg.waitForSelector('#bootFailure', { timeout: 8000 }).catch(() => {});
  const r = await pg.evaluate(() => {
    const box = document.getElementById('bootFailure');
    if (!box) return null;
    const cs = getComputedStyle(box), btn = document.getElementById('bootReload');
    return { bg: cs.backgroundColor, border: cs.borderLeftColor, top: cs.borderTopColor, mark: (box.querySelector('.boot-mark') || {}).textContent,
      btn: btn ? getComputedStyle(btn).backgroundColor : null, overflow: document.documentElement.scrollWidth - innerWidth };
  });
  check('bootCardShown', !!r, r);
  if (r) {
    check('bootCardIvory', JSON.stringify(rgb(r.bg)) === JSON.stringify([248, 248, 245]), r.bg);
    check('bootCardMistBorder', JSON.stringify(rgb(r.border)) === JSON.stringify([216, 222, 214]), r.border);
    check('bootCardForestButton', JSON.stringify(rgb(r.btn)) === JSON.stringify([31, 58, 46]), r.btn);
    check('bootCardMark', r.mark === 'TA', r.mark);
    check('bootCardNoOverflow', r.overflow <= 0, r.overflow);
  }
  await ctx.close();
}

// 5. County page: one line per source per ledger section; no overflow.
for (const vp of [{ width: 1440, height: 900 }, { width: 390, height: 844 }]) {
  const pg = await open('index.html?look=merged#/county/Escambia', { vp });
  await pg.waitForSelector('.cty[data-county]', { timeout: 6000 }).catch(() => {});
  const r = await pg.evaluate(() => ({
    lines: [...document.querySelectorAll('.cty-section:not([data-county-section="truth"]) .cty-src')].map(li => ({ meta: !!li.querySelector('.cty-src-meta, .cty-src-health'), name: !!li.querySelector('.cty-src-name') })),
    truthRows: document.querySelectorAll('[data-county-section="truth"] tbody tr').length,
    kicker: !!document.querySelector('.cty .cty-head .cty-kicker'),
    bars: document.querySelectorAll('[data-county-section="property"] .cty-bar').length,
    overflow: document.documentElement.scrollWidth - innerWidth
  }));
  check('countySourceOneLine_' + vp.width, r.lines.length > 0 && r.lines.every(l => l.name && !l.meta), r.lines);
  check('countySourceTruthKept_' + vp.width, r.truthRows > 0, r.truthRows);
  check('countyNoDuplicateEyebrow_' + vp.width, !r.kicker, r);
  check('countyCoverageBars_' + vp.width, r.bars > 0, r.bars);
  check('countyNoOverflow_' + vp.width, r.overflow <= 0, r.overflow);
  await pg.context().close();
}

// 6. County index: status chips, quiet zeros with labels, segmented toggle.
{
  const pg = await open('index.html?look=merged#/counties');
  await pg.waitForSelector('.cty-rows .cty-row', { timeout: 6000 }).catch(() => {});
  const r = await pg.evaluate(() => ({
    chips: document.querySelectorAll('.cty-row .cty-status-chip').length,
    zeroLabels: [...document.querySelectorAll('.cty-row-counts .is-zero')].every(z => /^0 /.test(z.getAttribute('aria-label') || '')),
    seg: [...document.querySelectorAll('.cty-seg button')].map(b => b.getAttribute('aria-pressed') + ':' + b.textContent.trim())
  }));
  check('countyIndexChips', r.chips > 0, r);
  check('countyIndexZeroLabels', r.zeroLabels, r);
  check('countyIndexSegmented', r.seg.length === 2 && r.seg[0].startsWith('true:On file') && r.seg[1].startsWith('false:All'), r.seg);
  await pg.context().close();
}

// 7. Watchlist page: one column, no emoji, count pill.
{
  const pg = await open('index.html?look=merged#/auctions');
  const ids = await pg.evaluate(() => [...document.querySelectorAll('#main [data-action="bidlist"][data-pid]')].slice(0, 2).map(b => b.dataset.pid));
  for (const id of ids) { await pg.evaluate(i => document.querySelector(`#main [data-action="bidlist"][data-pid="${i}"]`).click(), id); await pg.waitForTimeout(400); }
  const toast = await pg.evaluate(() => [...document.querySelectorAll('.tdw-toast')].map(t => t.dataset.tone + ':' + t.innerText));
  check('watchAddOkToast', toast.some(t => /^ok:Added to your watchlist/.test(t)), toast);
  await pg.evaluate(() => { location.hash = '#/watchlist'; });
  await pg.waitForTimeout(800);
  const r = await pg.evaluate(() => {
    const cards = [...document.querySelectorAll('#bidListRows > .prop-card')];
    const lefts = new Set(cards.map(c => Math.round(c.getBoundingClientRect().left)));
    const title = document.getElementById('watchlistTitle');
    return { n: cards.length, cols: lefts.size, title: title ? title.textContent : '', pill: !!document.querySelector('#watchlistTitle .wl-count-pill') };
  });
  check('watchlistOneColumn', r.n >= 2 && r.cols === 1, r);
  check('watchlistNoEmoji', !/[⚑⚐♡⏳]/.test(r.title), r.title);
  check('watchlistCountPill', r.pill, r);
  await pg.context().close();
}

// 8. Texas ledger titles.
{
  const pg = await open('tx.html?look=classic#/lands');
  const t = await pg.title();
  check('txAvailableTitle', /Available — Struck-off property/.test(t), t);
  await pg.context().close();
}

check('noPageErrors', errs.length === 0, errs.slice(0, 5));
await b.close();
console.log(fail ? `${fail} FAILED` : 'ALL PASS');
process.exit(fail ? 1 : 0);
