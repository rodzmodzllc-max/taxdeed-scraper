// Phone ledger bar (2026-10-29): below 1024px the fixed bottom bar is the
// ledger switch (Available / Auctions / Liens / Map); an open property stops
// above it, and one tap on it switches ledger from inside a property. On
// desktop the property modal starts under the sticky header, whose #hdrNav
// stays clickable.
import { chromium } from 'playwright';
import fs from 'fs';
const BASE = process.env.BASE_URL || 'http://localhost:8882/index.html';
const root = BASE.replace(/[^/]*$/, '');
const exe = '/opt/pw-browsers/chromium';
const b = await chromium.launch(fs.existsSync(exe) ? { executablePath: exe } : {});
let fail = 0;
const check = (name, ok, got) => { console.log((ok ? 'PASS ' : 'FAIL ') + name + (ok ? '' : ' -> ' + JSON.stringify(got))); if (!ok) fail++; };
const allErrs = [];
async function open(path, vp = { width: 390, height: 844 }, ctxOpts = {}) {
  const ctx = await b.newContext({ viewport: vp, ...ctxOpts });
  const pg = await ctx.newPage();
  pg.on('pageerror', e => allErrs.push(path + ': ' + e.message));
  pg.on('dialog', d => d.accept());
  await pg.goto(root + path, { waitUntil: 'networkidle' });
  await pg.waitForTimeout(1200);
  return pg;
}
// Every bar item is the element actually hit at its own centre.
const barUncovered = pg => pg.evaluate(() => [...document.querySelectorAll('#navBottom .nav-bottom-item')].every(el => {
  const r = el.getBoundingClientRect();
  if (!r.width || !r.height) return false;
  const hit = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
  return !!hit && hit.closest('.nav-bottom-item') === el;
}));
const barState = pg => pg.evaluate(() => [...document.querySelectorAll('#navBottom .nav-bottom-item')].map(el => ({
  ledger: el.dataset.navLedger || null, page: el.dataset.page || null, on: el.classList.contains('on'),
  current: el.getAttribute('aria-current'), label: el.getAttribute('aria-label') })));

// 1. The bar's entries, order and attributes.
{
  const pg = await open('index.html#/lands');
  const st = await barState(pg);
  check('barEntriesInOrder', JSON.stringify(st.map(s => s.ledger || s.page)) === JSON.stringify(['laft', 'auction', 'certificate', 'map']), st);
  check('barNoDataLedgerAttribute', await pg.locator('.nav-bottom-item[data-ledger]').count() === 0, null);
  check('barNoHomePropertiesWatchlist', await pg.locator('#navBottom [data-page="dashboard"], #navBottom [data-page="list"], #navBottom [data-page="watchlist"]').count() === 0, null);
  check('barAvailableLitOnLands', st[0].on && st[0].current === 'page' && !st[1].on && !st[2].on, st);
  check('barNamesShort', JSON.stringify(await pg.locator('#navBottom .nb-name').allTextContents()) === JSON.stringify(['Available', 'Auctions', 'Liens', 'Map']), await pg.locator('#navBottom .nb-name').allTextContents());
  const hdr = await pg.evaluate(() => ['laft', 'auction', 'certificate'].map(k => (document.getElementById('navCount' + k[0].toUpperCase() + k.slice(1)) || {}).textContent));
  const bar = await pg.locator('#navBottom .nb-count').allTextContents();
  check('barCountsMatchHeader', JSON.stringify(hdr) === JSON.stringify(bar), { hdr, bar });
  check('barAriaLabelFullNameAndCount', /^Liens & Certificates, \d+ propert(y|ies)$/.test(st[2].label), st[2].label);
  const h = await pg.evaluate(() => ({ v: getComputedStyle(document.documentElement).getPropertyValue('--nav-bottom-h').trim(), bar: document.getElementById('navBottom').offsetHeight,
    pad: parseFloat(getComputedStyle(document.body).paddingBottom) }));
  check('barHeightMeasured', h.v === h.bar + 'px' && h.pad >= h.bar, h);
  check('barItemsAtLeast44', await pg.evaluate(() => [...document.querySelectorAll('#navBottom .nav-bottom-item')].every(e => e.offsetWidth >= 44 && e.offsetHeight >= 44)), null);
  // Account sheet "Go to": Home first, and it opens Home.
  await pg.click('#accountBtn'); await pg.waitForTimeout(200);
  check('gotoHomeFirst', (await pg.locator('#accountGoto [data-goto]').first().getAttribute('data-goto')) === 'dashboard', null);
  await pg.click('#accountGoto [data-goto="dashboard"]'); await pg.waitForTimeout(700);
  check('gotoHomeOpensHome', await pg.evaluate(() => !document.getElementById('pageDashboard').hidden && location.hash === '#/dashboard'), await pg.evaluate(() => location.hash));
  check('barNothingLitOnHome', (await barState(pg)).every(s => !s.on), await barState(pg));
  await pg.context().close();
}

// 2. Deep in a long list: every bar item is reachable; switching works; the
//    same ledger keeps the reader's place.
{
  const pg = await open('mi.html?profile=admin&bigcounty=600#/lands');
  await pg.evaluate(() => window.scrollTo(0, 3000)); await pg.waitForTimeout(300);
  check('barUncoveredDeepInList', await barUncovered(pg), await barState(pg));
  await pg.click('#navBottom .nav-bottom-item[data-nav-ledger="laft"]'); await pg.waitForTimeout(400);
  check('sameLedgerKeepsScroll', await pg.evaluate(() => Math.abs(window.scrollY - 3000) < 5 && location.hash === '#/lands'), await pg.evaluate(() => [window.scrollY, location.hash]));
  for (const k of ['auction', 'certificate', 'laft']) {
    await pg.evaluate(() => window.scrollTo(0, 2500)); await pg.waitForTimeout(150);
    check('barUncoveredOn_' + k, await barUncovered(pg), null);
    await pg.click(`#navBottom .nav-bottom-item[data-nav-ledger="${k}"]`); await pg.waitForTimeout(500);
    const r = await pg.evaluate(k => {
      const on = [...document.querySelectorAll('#navBottom .nav-bottom-item.on')].map(e => e.dataset.navLedger || e.dataset.page);
      const me = document.querySelector(`#navBottom [data-nav-ledger="${k}"]`);
      return { hash: location.hash, on, current: me.getAttribute('aria-current'), focused: document.activeElement === me, tab: document.querySelector('#ledgerTabs .ledger-tab.on')?.dataset.ledger };
    }, k);
    const slug = { auction: '#/auctions', certificate: '#/certificates', laft: '#/lands' }[k];
    check('barSwitchTo_' + k, r.hash === slug && JSON.stringify(r.on) === JSON.stringify([k]) && r.current === 'page' && r.tab === k, r);
    check('barFocusAfterSwitch_' + k, r.focused, r);
  }
  await pg.context().close();
}

// 3. A property open on a phone: the bar is not covered, and one tap on
//    Liens closes it and lands on the certificates list.
{
  const pg = await open('index.html#/lands');
  await pg.evaluate(() => document.querySelector('#main [data-action="viewdetails"]').click()); await pg.waitForTimeout(600);
  check('phoneModalOpen', await pg.locator('#detailModal').isVisible(), null);
  check('barUncoveredWithPropertyOpen', await barUncovered(pg), null);
  const geo = await pg.evaluate(() => ({ modalBottom: document.getElementById('detailModal').getBoundingClientRect().bottom, barTop: document.getElementById('navBottom').getBoundingClientRect().top,
    sheetTop: document.getElementById('detailModalInner').getBoundingClientRect().top }));
  check('phoneModalStopsAtBar', Math.abs(geo.modalBottom - geo.barTop) <= 1 && geo.sheetTop >= 60, geo);
  await pg.click('#navBottom .nav-bottom-item[data-nav-ledger="certificate"]');
  await pg.waitForTimeout(900);
  const r = await pg.evaluate(() => ({ hidden: document.getElementById('detailModal').hidden, hash: location.hash, on: document.querySelector('#navBottom .nav-bottom-item.on')?.dataset.navLedger, list: !document.getElementById('pageList').hidden }));
  check('oneTapSwitchFromProperty', r.hidden && r.hash === '#/certificates' && r.on === 'certificate' && r.list, r);
  // The crumb's ledger link: the history layer lands first, then the page
  // changes (no race popping the new state).
  await pg.evaluate(() => document.querySelector('#main [data-action="viewdetails"]').click()); await pg.waitForTimeout(500);
  await pg.evaluate(() => document.querySelector('#detailModalInner .crumb[data-action="crumbledger"]').click());
  await pg.waitForTimeout(1000);
  const c = await pg.evaluate(() => ({ hidden: document.getElementById('detailModal').hidden, hash: location.hash, list: !document.getElementById('pageList').hidden }));
  check('crumbLedgerAfterSelfBack', c.hidden && c.hash === '#/certificates' && c.list, c);
  // A toast sits above the bar.
  const t = await pg.evaluate(() => { const d = document.createElement('div'); d.className = 'err-toast show'; d.textContent = 'x'; document.body.appendChild(d);
    const r = d.getBoundingClientRect().bottom, top = document.getElementById('navBottom').getBoundingClientRect().top; d.remove(); return { r, top }; });
  check('toastAboveBar', t.r <= t.top, t);
  await pg.context().close();
}

// 4. Desktop: a modal opened from the Watchlist page starts under the
//    header; one click on a header ledger switches.
{
  const pg = await open('index.html?bidlist=p1#/watchlist', { width: 1440, height: 900 });
  check('desktopBarHidden', await pg.evaluate(() => getComputedStyle(document.getElementById('navBottom')).display === 'none' && getComputedStyle(document.documentElement).getPropertyValue('--nav-bottom-h').trim() === '0px'), null);
  await pg.evaluate(() => document.querySelector('#pageWatchlist [data-action="viewdetails"]').click()); await pg.waitForTimeout(600);
  const hit = await pg.evaluate(() => [...document.querySelectorAll('#hdrNav .nav-item')].every(el => { const r = el.getBoundingClientRect(); const h = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2); return !!h && h.closest('.nav-item') === el; }));
  check('desktopHeaderClickableWithModal', hit, null);
  const top = await pg.evaluate(() => ({ m: document.getElementById('detailModal').getBoundingClientRect().top, h: document.querySelector('.topbar').getBoundingClientRect().bottom }));
  check('desktopModalStartsUnderHeader', Math.abs(top.m - top.h) <= 2, top);
  await pg.click('#hdrNav .nav-item[data-nav-ledger="auction"]'); await pg.waitForTimeout(900);
  const r = await pg.evaluate(() => ({ hidden: document.getElementById('detailModal').hidden, hash: location.hash, on: document.querySelector('#hdrNav .nav-item.on')?.dataset.navLedger }));
  check('desktopOneClickSwitchFromModal', r.hidden && r.hash === '#/auctions' && r.on === 'auction', r);
  // The account menu paints above an open modal.
  await pg.evaluate(() => document.querySelector('#main [data-action="viewdetails"], #detailPanel') && 0);
  await pg.context().close();
}
{
  const pg = await open('index.html?bidlist=p1#/watchlist', { width: 1280, height: 800 });
  await pg.evaluate(() => document.querySelector('#pageWatchlist [data-action="viewdetails"]').click()); await pg.waitForTimeout(600);
  await pg.click('#accountBtn'); await pg.waitForTimeout(250);
  const ok = await pg.evaluate(() => { const it = document.querySelector('#accountMenu .account-item:not([hidden])'); if (!it) return 'no item'; const r = it.getBoundingClientRect(); const h = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2); return !!h && !!h.closest('#accountMenu'); });
  check('desktopAccountMenuAboveModal', ok === true, ok);
  await pg.context().close();
}

// 5. Looks: the last deck / list control clears the bar at the end.
for (const look of ['merged', 'tactile', 'terrain', 'classic']) {
  const pg = await open(`mi.html?profile=admin&bigcounty=600&look=${look}#/lands`);
  await pg.waitForTimeout(800);
  await pg.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight)); await pg.waitForTimeout(500);
  const r = await pg.evaluate(() => {
    const barTop = document.getElementById('navBottom').getBoundingClientRect().top;
    const ctrls = [...document.querySelectorAll('.xpm-more, .group-more, #xpStage button, #main button')].filter(e => { const r = e.getBoundingClientRect(); return r.width && r.height && r.bottom > 0 && r.top < innerHeight; });
    const last = ctrls.reduce((m, e) => Math.max(m, e.getBoundingClientRect().bottom), 0);
    return { barTop, last, n: ctrls.length };
  });
  check('lastControlClearsBar_' + look, r.n > 0 && r.last <= r.barTop + 0.5, r);
  await pg.context().close();
}

// 6. Keyboard: Tab reaches each bar item, Enter activates, focus is visible.
{
  const pg = await open('index.html#/lands');
  await pg.focus('#navBottom .nav-bottom-item[data-nav-ledger="laft"]');
  await pg.keyboard.press('Tab');
  const f1 = await pg.evaluate(() => document.activeElement.dataset.navLedger);
  await pg.keyboard.press('Tab');
  const f2 = await pg.evaluate(() => document.activeElement.dataset.navLedger);
  await pg.keyboard.press('Tab');
  const f3 = await pg.evaluate(() => document.activeElement.dataset.page);
  check('tabReachesEachBarItem', f1 === 'auction' && f2 === 'certificate' && f3 === 'map', [f1, f2, f3]);
  await pg.keyboard.press('Shift+Tab');
  const outline = await pg.evaluate(() => getComputedStyle(document.activeElement).outlineStyle);
  check('focusVisibleOutline', outline !== 'none', outline);
  await pg.keyboard.press('Enter'); await pg.waitForTimeout(500);
  check('enterActivatesBarItem', await pg.evaluate(() => location.hash === '#/certificates'), await pg.evaluate(() => location.hash));
  await pg.context().close();
}

// 7. Map page: Map lit, pills in List order, the map's filter marked on the
//    bar, and a bar ledger tap opens the List.
{
  const pg = await open('index.html#/lands');
  await pg.click('#navBottom .nav-bottom-item[data-page="map"]'); await pg.waitForTimeout(800);
  const st = await barState(pg);
  check('mapLitOnMapPage', st[3].on && st.slice(0, 3).every(s => !s.on), st);
  check('mapPillsInListOrder', JSON.stringify(await pg.locator('#mapLedgerPills [data-ledger]').evaluateAll(els => els.map(e => e.dataset.ledger))) === JSON.stringify(['all', 'laft', 'auction', 'certificate']), null);
  await pg.click('#mapLedgerPills [data-ledger="auction"]'); await pg.waitForTimeout(400);
  check('mapFilterMarkedOnBar', await pg.evaluate(() => [...document.querySelectorAll('#navBottom .map-filter')].map(e => e.dataset.navLedger).join() === 'auction'), null);
  await pg.click('#navBottom .nav-bottom-item[data-nav-ledger="certificate"]'); await pg.waitForTimeout(600);
  check('barFromMapOpensList', await pg.evaluate(() => location.hash === '#/certificates' && !document.getElementById('pageList').hidden && !document.querySelector('#navBottom .map-filter')), await pg.evaluate(() => location.hash));
  await pg.context().close();
}

// 8. Widths: no horizontal overflow, the bar fits (Texas's two-line name too).
for (const [w, h, page] of [[320, 640, 'index.html#/auctions'], [360, 780, 'index.html#/auctions'], [390, 844, 'tx.html#/certificates'], [768, 1024, 'index.html#/lands'], [844, 390, 'index.html#/lands']]) {
  const pg = await open(page, { width: w, height: h });
  const r = await pg.evaluate(() => {
    const bar = document.getElementById('navBottom');
    return { noScroll: document.documentElement.scrollWidth <= innerWidth, fits: bar.scrollWidth <= bar.clientWidth && [...bar.children].every(c => c.getBoundingClientRect().right <= innerWidth + 1),
      h: bar.offsetHeight, v: getComputedStyle(document.documentElement).getPropertyValue('--nav-bottom-h').trim(),
      names: [...bar.querySelectorAll('.nb-name')].every(n => n.scrollHeight <= n.clientHeight + 1) };
  });
  check(`fits_${w}x${h}`, r.noScroll && r.fits && r.h <= 80 && r.v === r.h + 'px' && r.names, r);
  if (page.startsWith('tx')) check('txFullNameInLabel', /^Redeemable Deeds, /.test(await pg.locator('#navBottom [data-nav-ledger="certificate"]').getAttribute('aria-label')), null);
  await pg.context().close();
}

// 9. Reduced motion, print, the boot-failure screen, the on-screen keyboard.
{
  const pg = await open('index.html#/lands', { width: 390, height: 844 }, { reducedMotion: 'reduce' });
  check('reducedMotionNoTransition', await pg.evaluate(() => [...document.querySelectorAll('#navBottom .nav-bottom-item')].every(e => getComputedStyle(e).transitionDuration.split(',').every(d => parseFloat(d) === 0))), null);
  await pg.emulateMedia({ media: 'print' });
  check('printHidesBar', await pg.evaluate(() => getComputedStyle(document.getElementById('navBottom')).display === 'none'), null);
  await pg.emulateMedia({ media: 'screen' });
  await pg.evaluate(() => { const d = document.createElement('div'); d.id = 'bootFailure'; document.body.appendChild(d); });
  check('bootFailureHidesBar', await pg.evaluate(() => getComputedStyle(document.getElementById('navBottom')).display === 'none'), null);
  await pg.context().close();
}
{
  const pg = await open('index.html#/lands', { width: 390, height: 844 }, { hasTouch: true, isMobile: true });
  await pg.click('#hdrSearchBtn'); await pg.waitForTimeout(250);
  check('keyboardUpHidesBar', await pg.evaluate(() => document.activeElement.id === 'globalSearchInput' && getComputedStyle(document.getElementById('navBottom')).display === 'none'), null);
  await pg.evaluate(() => document.activeElement.blur()); await pg.waitForTimeout(250);
  check('keyboardDownShowsBar', await pg.evaluate(() => getComputedStyle(document.getElementById('navBottom')).display !== 'none'), null);
  await pg.context().close();
}
{
  // A fine pointer (a narrow desktop window) never hides the bar on focus.
  const pg = await open('index.html#/lands', { width: 390, height: 844 });
  await pg.click('#hdrSearchBtn'); await pg.waitForTimeout(250);
  check('finePointerKeepsBarOnFocus', await pg.evaluate(() => getComputedStyle(document.getElementById('navBottom')).display !== 'none'), null);
  await pg.context().close();
}
check('noPageErrors', allErrs.length === 0, allErrs);
await b.close();
console.log(fail ? `FAIL: ${fail} check(s)` : 'PASS: all ledger-bar checks');
process.exit(fail ? 1 : 0);
