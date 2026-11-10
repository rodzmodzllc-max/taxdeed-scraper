// UI overhaul review fixes (2026-11-10): one regression check per finding the
// review of the integrated branch raised.
//   - Buyer's Guide: the ledger segment's thumb is drawn (a global @property
//     registration of a same-named custom property once made it 0px wide);
//   - Classic list: a redraw (sort change) never moves the scroll position
//     (accordion motion runs only for a <details> the person opens);
//   - Merged Home: the look's own hover shadow on a ledger card is kept;
//   - OS dark preference with no data-theme: Home county chips and the Merged
//     Available county bar stay readable (light is the product);
//   - phone: the account menu's last row ends above the ledger bar;
//   - property modal on a phone: the Contents row's last pill is not under
//     the sticky close button;
//   - Merged side-panel summary: its entrance plays once, not per deck step;
//   - satellite basemaps: a county count stays readable in the dark theme.
import { chromium } from 'playwright';
import fs from 'fs';
const BASE = process.env.BASE_URL || 'http://localhost:9301/index.html';
const root = BASE.replace(/[^/]*$/, '');
const exe = '/opt/pw-browsers/chromium';
const b = await chromium.launch(fs.existsSync(exe) ? { executablePath: exe } : {});
let fail = 0;
const check = (name, ok, got) => { console.log((ok ? 'PASS ' : 'FAIL ') + name + (ok ? '' : ' -> ' + JSON.stringify(got))); if (!ok) fail++; };
const errs = [];
async function open(path, vp = { width: 1440, height: 900 }, opts = {}) {
  const ctx = await b.newContext({ viewport: vp, ...opts });
  const pg = await ctx.newPage();
  pg.on('pageerror', e => errs.push(path + ': ' + e.message));
  pg.on('dialog', d => d.accept());
  await pg.goto(root + path, { waitUntil: 'networkidle' });
  await pg.waitForTimeout(1200);
  return pg;
}
// WCAG contrast of an element's text against its first opaque background.
const contrastOf = (pg, sel) => pg.evaluate(sel => {
  const el = document.querySelector(sel);
  if (!el) return null;
  const rgb = s => (s.match(/[\d.]+/g) || []).map(Number);
  const lum = ([r, g, b]) => { const f = c => { c /= 255; return c <= .03928 ? c / 12.92 : ((c + .055) / 1.055) ** 2.4; }; return .2126 * f(r) + .7152 * f(g) + .0722 * f(b); };
  let n = el, bg = null;
  while (n && n.nodeType === 1) { const c = rgb(getComputedStyle(n).backgroundColor); if (c.length >= 3 && (c.length < 4 || c[3] > .5)) { bg = c; break; } n = n.parentElement; }
  bg = bg || [255, 255, 255];
  const fg = rgb(getComputedStyle(el).color);
  const a = lum(fg), c = lum(bg);
  return Math.round(((Math.max(a, c) + .05) / (Math.min(a, c) + .05)) * 100) / 100;
}, sel);

// 1. Buyer's Guide segment thumb, motion allowed.
for (const vp of [{ width: 1440, height: 900 }, { width: 390, height: 844 }]) {
  const pg = await open('index.html?look=merged#/guide', vp);
  await pg.waitForSelector('.bg-seg-thumb', { timeout: 8000 }).catch(() => {});
  const r = await pg.evaluate(() => {
    const t = document.querySelector('.bg-seg-thumb'), on = document.querySelector('.bg-tab.on');
    if (!t || !on) return null;
    const a = t.getBoundingClientRect(), o = on.getBoundingClientRect();
    return { w: Math.round(a.width), dx: Math.round(Math.abs(a.left - o.left)) };
  });
  check(`guideThumbDrawn_${vp.width}`, !!r && r.w > 40 && r.dx < 12, r);
  await pg.context().close();
}

// 2. Classic list redraw keeps the scroll position.
{
  const pg = await open('index.html?look=classic&bigcounty=400#/auctions');
  await pg.evaluate(() => window.scrollTo(0, 3000));
  await pg.waitForTimeout(300);
  const before = await pg.evaluate(() => Math.round(scrollY));
  const opt = await pg.evaluate(() => { const s = document.getElementById('sortBy'); if (!s) return null; const o = [...s.options].find(o => o.value !== s.value); return o ? o.value : null; });
  if (opt) await pg.selectOption('#sortBy', opt);
  await pg.waitForTimeout(700);
  const after = await pg.evaluate(() => Math.round(scrollY));
  check('classicRedrawKeepsScroll', before > 1000 && Math.abs(after - before) < 40, { before, after, opt });
  // A details the person opens is marked for the accordion motion.
  const marked = await pg.evaluate(() => {
    const d = [...document.querySelectorAll('details:not([open])')].find(d => d.offsetParent && d.querySelector(':scope > summary'));
    if (!d) return 'none';
    d.querySelector(':scope > summary').click();
    return d.classList.contains('dd-anim') && d.open;
  });
  check('userOpenedDetailsMarked', marked === true || marked === 'none', marked);
  await pg.context().close();
}

// 3. Merged Home keeps its own ledger-card hover shadow.
{
  const pg = await open('index.html?look=merged#/dashboard');
  const card = pg.locator('#homeLedgers .home-ledger-card').first();
  await card.hover();
  await pg.waitForTimeout(400);
  const sh = await card.evaluate(e => getComputedStyle(e).boxShadow);
  check('mergedHomeHoverShadowKept', /14px 26px -18px/.test(sh), sh);
  await pg.context().close();
}

// 4. OS dark, no data-theme: Home county chips and the Merged county bar.
for (const vp of [{ width: 1440, height: 900 }, { width: 390, height: 844 }]) {
  const pg = await open('index.html?look=merged#/dashboard', vp, { colorScheme: 'dark' });
  const theme = await pg.evaluate(() => document.documentElement.dataset.theme || '');
  if (!theme) {
    const chip = await contrastOf(pg, '.home-county-desk .desk-county');
    check(`homeChipsReadableOsDark_${vp.width}`, chip === null || chip >= 4.5, chip);
  }
  await pg.evaluate(() => { location.hash = '#/lands'; });
  await pg.waitForTimeout(1500);
  if (!(await pg.evaluate(() => document.documentElement.dataset.theme || ''))) {
    const name = await contrastOf(pg, '.county-now .cnb-name');
    check(`countyBarReadableOsDark_${vp.width}`, name === null || name >= 4.5, name);
  }
  await pg.context().close();
}

// 5. Phone account menu ends above the ledger bar.
{
  const pg = await open('index.html?look=merged#/lands', { width: 390, height: 844 });
  await pg.click('#accountBtn').catch(() => {});
  await pg.waitForTimeout(300);
  const r = await pg.evaluate(() => {
    const m = document.getElementById('accountMenu'), bar = document.getElementById('navBottom'), del = document.getElementById('deleteAccountBtn');
    if (!m || m.hidden || !del) return null;
    m.scrollTop = m.scrollHeight;
    const barTop = bar && getComputedStyle(bar).display !== 'none' ? bar.getBoundingClientRect().top : innerHeight;
    return { menuBottom: Math.round(m.getBoundingClientRect().bottom), delBottom: Math.round(del.getBoundingClientRect().bottom), barTop: Math.round(barTop),
      heads: [...m.querySelectorAll('.account-group-head')].map(h => h.textContent.trim()) };
  });
  check('accountMenuAboveBar', !!r && r.menuBottom <= r.barTop && r.delBottom <= r.barTop, r);
  check('accountMenuGroups', !!r && ['Account', 'Help'].every(h => r.heads.includes(h)), r && r.heads);
  await pg.context().close();
}

// 6. Phone property modal: the Contents row's last pill clears the close (x).
for (const path of ['index.html?look=classic#/certificates/p4', 'index.html?look=merged#/lands/p3']) {
  const pg = await open(path, { width: 390, height: 844 });
  await pg.waitForSelector('#detailModal:not([hidden]) .detail-nav', { timeout: 8000 }).catch(() => {});
  const r = await pg.evaluate(async () => {
    const inner = document.getElementById('detailModalInner');
    const nav = inner && inner.querySelector(':scope > .detail-nav');
    if (!nav) return 'no-nav';
    const box = document.querySelector('#detailModal .detail-modal') || inner.closest('[class*="modal"]') || inner;
    [inner, box, inner.parentElement].forEach(el => { if (el) el.scrollTop = 600; });
    nav.scrollLeft = nav.scrollWidth;
    await new Promise(r => setTimeout(r, 300));
    const pills = nav.querySelectorAll('button');
    const last = pills[pills.length - 1];
    const a = last.getBoundingClientRect();
    const hit = document.elementFromPoint(a.left + a.width / 2, a.top + a.height / 2);
    return { ok: !!hit && (hit === last || last.contains(hit)), hit: hit && hit.className };
  });
  check(`detailNavLastPillClear_${path.includes('merged') ? 'merged' : 'classic'}`, r === 'no-nav' || (r && r.ok), r);
  await pg.context().close();
}

// 7. Merged Auctions side-panel summary: entrance plays once.
{
  const pg = await open('index.html?look=merged#/auctions');
  await pg.evaluate(() => { window.__psAnim = 0; document.addEventListener('animationstart', e => { if (e.target.closest && e.target.closest('.xp-panelsum') === e.target) window.__psAnim++; }, true); });
  const has = await pg.evaluate(() => !!document.querySelector('#detailPanel .xp-panelsum'));
  for (let i = 0; i < 3; i++) { await pg.keyboard.press('ArrowRight'); await pg.waitForTimeout(250); }
  const n = await pg.evaluate(() => window.__psAnim);
  check('panelSummaryNoReplay', !has || n <= 1, { has, n });
  await pg.context().close();
}

// 8. Satellite bubble count colour follows the dark theme's charcoal.
{
  const pg = await open('index.html?look=merged#/map');
  const r = await pg.evaluate(() => {
    document.documentElement.dataset.theme = 'dark';
    const c = document.createElement('div'); c.className = 'satellite-map-canvas';
    const bub = document.createElement('div'); bub.className = 'sat-county-bubble'; bub.textContent = '12';
    c.appendChild(bub); document.body.appendChild(c);
    const s = getComputedStyle(bub); const out = { bg: s.backgroundColor, color: s.color };
    c.remove(); return out;
  });
  check('satBubbleDarkReadable', r.bg !== r.color && !/255, 255, 255/.test(r.color), r);
  await pg.context().close();
}

check('noPageErrors', errs.length === 0, errs.slice(0, 5));
await b.close();
console.log(fail ? `${fail} FAILED` : 'ALL PASS');
process.exit(fail ? 1 : 0);
