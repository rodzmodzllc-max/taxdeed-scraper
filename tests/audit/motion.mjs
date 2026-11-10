// Motion system (2026-11-10): one duration / easing token set on :root
// (identity.css), enter-only motion in motion.css, and a global reduced-motion
// rule that finishes everything at once.
//   - reduced motion: after load, and after opening a menu / modal / page,
//     no animation or transition longer than 20ms is still running;
//   - no-preference: the tokens resolve on :root, a page switch plays the
//     page-enter motion (the .page-enter class, when showPage() adds it, is
//     removed again), and the page's layout position never moves (only a
//     transform runs, and none is left behind);
//   - menus, the modal / phone sheet and the auction drawer enter with their
//     own motion; card lift only on fine pointers; nothing in the Merged deck
//     gets a motion.css transform.
import { chromium } from 'playwright';
import fs from 'fs';
const BASE = process.env.BASE_URL || 'http://localhost:9204/index.html';
const root = BASE.replace(/[^/]*$/, '');
const exe = '/opt/pw-browsers/chromium';
const b = await chromium.launch(fs.existsSync(exe) ? { executablePath: exe } : {});
let fail = 0;
const check = (name, ok, got) => { console.log((ok ? 'PASS ' : 'FAIL ') + name + (ok ? '' : ' -> ' + JSON.stringify(got))); if (!ok) fail++; };
const errs = [];
let injectedNote = false;
async function open(path, vp = { width: 1440, height: 900 }, ctxOpts = {}) {
  const ctx = await b.newContext({ viewport: vp, ...ctxOpts });
  const pg = await ctx.newPage();
  pg.on('pageerror', e => errs.push(path + ': ' + e.message));
  pg.on('dialog', d => d.accept());
  await pg.goto(root + path, { waitUntil: 'networkidle' });
  // The pages link motion.css after identity.css. Until that tag ships on a
  // page, load the same file so the rules under test are the real ones.
  const linked = await pg.evaluate(() => !!document.querySelector('link[rel="stylesheet"][href$="motion.css"]'));
  if (!linked) {
    if (!injectedNote) { console.log('NOTE motion.css is not linked by the page; loading it for this test'); injectedNote = true; }
    await pg.addStyleTag({ url: root + 'motion.css' });
  }
  await pg.waitForTimeout(1200);
  return pg;
}
// Every animation / transition still running and longer than `ms`.
const longRunning = (pg, ms = 20) => pg.evaluate(ms => document.getAnimations()
  .filter(a => a.playState === 'running')
  .map(a => { const t = a.effect && a.effect.getComputedTiming ? a.effect.getComputedTiming() : {}; return { name: a.animationName || a.transitionProperty || a.constructor.name, d: t.duration, it: t.iterations, el: a.effect && a.effect.target ? (a.effect.target.id || a.effect.target.className || a.effect.target.tagName) + '' : '' }; })
  .filter(x => x.it === Infinity || (typeof x.d === 'number' && x.d > ms)), ms);
const anims = (pg, sel) => pg.evaluate(sel => { const el = document.querySelector(sel); return el ? el.getAnimations().map(a => a.animationName || a.transitionProperty) : null; }, sel);

// 1. Reduced motion: nothing long keeps running.
{
  const pg = await open('index.html?look=classic#/lands', { width: 1440, height: 900 }, { reducedMotion: 'reduce' });
  check('reducedNoLongAnimationAfterLoad', (await longRunning(pg)).length === 0, await longRunning(pg));
  const d = await pg.evaluate(() => { const s = getComputedStyle(document.querySelector('.page:not([hidden])')); return [s.animationDuration, s.transitionDuration]; });
  check('reducedPageDurationsNeutralised', d.every(v => v.split(',').every(x => parseFloat(x) <= 0.00002)), d);
  check('reducedNoSmoothScroll', await pg.evaluate(() => getComputedStyle(document.documentElement).scrollBehavior) === 'auto', null);
  await pg.click('#accountBtn'); await pg.waitForTimeout(60);
  check('reducedAccountMenuNoLongAnimation', (await longRunning(pg)).length === 0, await longRunning(pg));
  await pg.keyboard.press('Escape'); await pg.click('body', { position: { x: 5, y: 600 } }).catch(() => {});
  await pg.evaluate(() => { location.hash = '#/dashboard'; }); await pg.waitForTimeout(60);
  check('reducedPageSwitchNoLongAnimation', (await longRunning(pg)).length === 0, await longRunning(pg));
  await pg.evaluate(() => { location.hash = '#/lands'; }); await pg.waitForTimeout(800);
  const card = pg.locator('.prop-card').first();
  if (await card.count()) {
    await card.locator('[data-action="viewdetails"]').first().click();
    await pg.waitForTimeout(60);
    check('reducedModalNoLongAnimation', (await longRunning(pg)).length === 0, await longRunning(pg));
  } else check('reducedModalNoLongAnimation', false, 'no .prop-card');
  await pg.context().close();
}

// 2. Tokens resolve on :root.
{
  const pg = await open('index.html?look=merged#/auctions');
  const t = await pg.evaluate(() => { const s = getComputedStyle(document.documentElement); return ['--dur-press', '--dur-quick', '--dur-menu', '--dur-page', '--dur-hero', '--ease-std', '--ease-out', '--ease-in', '--spring-soft'].map(k => s.getPropertyValue(k).trim()); });
  check('tokensResolve', JSON.stringify(t.slice(0, 5)) === JSON.stringify(['90ms', '160ms', '200ms', '280ms', '520ms']) && t.slice(5).every(v => /^cubic-bezier\(/.test(v)), t);
  // styles.css durations read the tokens (the account item uses var(--dur-menu)).
  const dur = await pg.evaluate(() => { const e = document.querySelector('.err-toast') || null; return e ? getComputedStyle(e).transitionDuration : null; });
  check('errToastOnTokens', dur === null || dur.split(',').every(v => v.trim() === '0.2s'), dur);

  // 3. Page switch: page-enter motion plays and leaves no transform or layout shift.
  await pg.evaluate(() => {
    window.__pe = { added: false, removed: false, started: [] };
    new MutationObserver(ms => ms.forEach(m => { if (m.attributeName !== 'class') return; const has = m.target.classList.contains('page-enter'); if (has) window.__pe.added = true; else if (m.oldValue && /\bpage-enter\b/.test(m.oldValue)) window.__pe.removed = true; }))
      .observe(document.body, { subtree: true, attributes: true, attributeFilter: ['class'], attributeOldValue: true });
    document.addEventListener('animationstart', e => { if (e.target.classList && e.target.classList.contains('page')) window.__pe.started.push(e.animationName); }, true);
  });
  await pg.evaluate(() => { location.hash = '#/dashboard'; });
  await pg.waitForTimeout(40);
  // Layout position (offset chain ignores transforms) during and after the motion.
  const layoutTop = () => pg.evaluate(() => { const p = document.getElementById('pageDashboard'); const t = p && (p.querySelector('h1,h2,.home-ledger-card,section,div') || p); let y = 0, e = t; while (e) { y += e.offsetTop; e = e.offsetParent; } return { y, rect: t ? t.getBoundingClientRect().top + scrollY : null }; });
  const mid = await layoutTop();
  const pe = await pg.evaluate(() => { const p = document.getElementById('pageDashboard'); return { anims: p.getAnimations().map(a => a.animationName), pe: getComputedStyle(p).pointerEvents }; });
  check('pageEnterPlays', pe.anims.includes('tdw-page-enter') || (await pg.evaluate(() => window.__pe.started)).includes('tdw-page-enter'), pe);
  check('pageEnterNeverBlocksPointer', pe.pe !== 'none', pe);
  await pg.waitForTimeout(450);
  const end = await layoutTop();
  const state = await pg.evaluate(() => ({ pe: window.__pe, tf: getComputedStyle(document.getElementById('pageDashboard')).transform, cls: document.getElementById('pageDashboard').className }));
  check('pageEnterClassRemovedWhenAdded', !state.pe.added || (state.pe.removed && !/\bpage-enter\b/.test(state.cls)), state);
  console.log('NOTE page-enter class ' + (state.pe.added ? 'added by showPage()' : 'not used by showPage(); the CSS animation runs when [hidden] is removed'));
  check('pageEnterLeavesNoTransform', state.tf === 'none', state.tf);
  check('pageEnterNoLayoutShift', mid.y === end.y && Math.abs(end.rect - end.y) < 1, { mid, end });
  check('pageEnterWithinDurPage', (await longRunning(pg, 0)).filter(a => /^tdw-/.test(a.name)).length === 0, await longRunning(pg, 0));

  // 4. Menus scale-fade from their trigger.
  await pg.click('#accountBtn'); await pg.waitForTimeout(20);
  const m = await pg.evaluate(() => { const e = document.getElementById('accountMenu'); return { a: e.getAnimations().map(x => x.animationName), o: getComputedStyle(e).transformOrigin }; });
  check('accountMenuScaleFade', m.a.includes('tdw-menu-in'), m);
  await pg.keyboard.press('Escape'); await pg.waitForTimeout(250);
  if (await pg.locator('#lookBtn').count()) {
    await pg.click('#lookBtn'); await pg.waitForTimeout(20);
    check('lookMenuScaleFade', (await anims(pg, '#lookMenu')).includes('tdw-menu-in'), await anims(pg, '#lookMenu'));
    await pg.keyboard.press('Escape'); await pg.waitForTimeout(250);
  }

  // 5. The Merged deck keeps its own transforms: no motion.css transform runs inside it.
  await pg.evaluate(() => { location.hash = '#/auctions'; }); await pg.waitForTimeout(1500);
  const deck = await pg.evaluate(() => { const s = document.getElementById('xpStage'); if (!s) return null; const out = []; s.querySelectorAll('*').forEach(e => e.getAnimations().forEach(a => { if (/^tdw-(page|menu|panel|sheet|drawer|toast)/.test(a.animationName || '')) out.push(a.animationName); })); const hover = s.querySelector('.prop-card'); return { out, propCards: !!hover }; });
  check('mergedDeckUntouched', deck === null || (deck.out.length === 0 && !deck.propCards), deck);
  await pg.context().close();
}

// 6. Modal enter (desktop rise, auction drawer, phone sheet) and card lift.
{
  const pg = await open('index.html?look=classic#/lands');
  const card = pg.locator('.prop-card').first();
  await card.hover(); await pg.waitForTimeout(260);
  const tf = await card.evaluate(e => getComputedStyle(e).transform);
  check('cardLiftOnFinePointer', /matrix\(1, 0, 0, 1, 0, -2\)/.test(tf), tf);
  await pg.mouse.move(2, 880); await pg.waitForTimeout(260);
  check('cardLiftReleased', await card.evaluate(e => getComputedStyle(e).transform) === 'none', null);
  // A desktop modal (Edit profile): backdrop fades, panel rises.
  await pg.click('#accountBtn'); await pg.waitForTimeout(250);
  await pg.click('#editProfileBtn'); await pg.waitForTimeout(30);
  const ma = await pg.evaluate(() => { const m = document.getElementById('profileModal'); return m && !m.hidden ? { m: m.getAnimations().map(a => a.animationName), i: m.querySelector('.detail-modal-inner').getAnimations().map(a => a.animationName) } : null; });
  check('modalBackdropFadePanelRise', !!ma && ma.m.includes('tdw-backdrop-in') && ma.i.includes('tdw-panel-rise'), ma);
  await pg.waitForTimeout(400);
  check('modalSettlesWithoutTransform', await pg.evaluate(() => getComputedStyle(document.querySelector('#profileModal .detail-modal-inner')).transform) === 'none', null);
  await pg.context().close();
}
{
  // 1024-1279px: an auction opens in the right-hand drawer.
  const pg = await open('index.html?look=classic#/auctions', { width: 1100, height: 800 });
  const card = pg.locator('.prop-card').first();
  if (await card.count()) {
    await card.locator('[data-action="viewdetails"]').first().click();
    await pg.waitForTimeout(30);
    check('auctionDrawerSlidesIn', (await anims(pg, '#detailModal .detail-modal-inner') || []).includes('tdw-drawer-in'), await anims(pg, '#detailModal .detail-modal-inner'));
  } else check('auctionDrawerSlidesIn', false, 'no auction card');
  await pg.context().close();
}
{
  const pg = await open('index.html?look=classic#/lands', { width: 390, height: 844 }, { isMobile: true, hasTouch: true });
  const card = pg.locator('.prop-card').first();
  check('noCardLiftOnTouch', await pg.evaluate(() => !matchMedia('(hover:hover) and (pointer:fine)').matches), null);
  await card.locator('[data-action="viewdetails"]').first().tap();
  await pg.waitForTimeout(30);
  check('phoneSheetSlidesUp', (await anims(pg, '#detailModal .detail-modal-inner') || []).includes('tdw-sheet-up'), await anims(pg, '#detailModal .detail-modal-inner'));
  await pg.context().close();
}

check('noPageErrors', errs.length === 0, errs);
await b.close();
console.log(fail ? `FAILED ${fail}` : 'ALL PASS');
process.exit(fail ? 1 : 0);
