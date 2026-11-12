// Merged look polish (2026-11-10, package P3-merged-polish): proves
//   - the desktop side panel carries a summary of the rows in view while no
//     property is selected (no view recorded, address bar untouched) and
//     opens a record on request;
//   - Available: the county bar is a light, slim picker; the figure's caveat
//     is folded behind a disclosure, never dropped;
//   - Auctions: Left / Right move the deck from the keyboard and focus stays
//     on the deck;
//   - Liens: the fanned bundle uses the stage width (slips wrap, tray beside
//     them) and the grouping toggle is a named control;
//   - every Merged text style passes WCAG AA in light and dark, focus rings
//     are visible, and the new motion is off under reduced motion.
// Standalone: BASE_URL=http://localhost:8872/index.html node tests/audit/merged-polish.mjs
import { chromium } from 'playwright';
import fs from 'node:fs';

const BASE_URL = process.env.BASE_URL || 'http://localhost:8934/index.html';
const SANDBOX_CHROMIUM = '/opt/pw-browsers/chromium';
const browser = await chromium.launch(fs.existsSync(SANDBOX_CHROMIUM) ? { executablePath: SANDBOX_CHROMIUM } : {});
let failed = 0;
const check = (name, ok, info) => { console.log(`${ok ? 'PASS' : 'FAIL'} ${name}${ok ? '' : ' :: ' + JSON.stringify(info)}`); if (!ok) failed++; };

const now = new Date().toISOString();
const FL = ['Alachua', 'Bay', 'Brevard', 'Citrus', 'Clay', 'Duval'];
function certRows() {
  const out = [];
  const add = (year, i, county) => out.push({ id: `pc${year}-${i}`, source: 'certificate', state: 'FL', county, case_no: `${year}-${1000 + i}`, certificate_no: String(1000 + i), parcel: `P${year}${i}`, tax_year: String(year), bid: 500 + i * 37.25, interest_rate: 18, status: 'active', lien_level: 'unscreened', lien_note: '', url_auction: 'https://lienhub.com/county/alachua/countyheld/certificates', url_auction_kind: 'county', last_seen_at: now, updated_at: now });
  for (let i = 0; i < 5; i++) add(2025, i, FL[i]);
  for (let i = 0; i < 3; i++) add(2024, i, FL[i]);
  return out;
}
function laftRows() {
  const out = [];
  FL.slice(0, 3).forEach((county, c) => { for (let i = 0; i < 4; i++) out.push({ id: `pl${c}-${i}`, source: 'laft', state: 'FL', county, case_no: `PL-${c}-${i}`, parcel: `${c}${i}000${i}`, address: `${i + 1}${c} ${county} Rd`, bid: 1500 + i * 250, assessed: 20000 + i, market: 21000 + i * 900, status: 'available', lien_level: 'unscreened', lien_note: '', sale_date: null, url_auction: 'https://x', url_auction_kind: 'county', inventory_type: 'POST_SALE_FIXED_PRICE', source_authority: 'GOVERNMENT_PLATFORM', source_id: 'fl_laft_pioneer', list_url: 'https://x', purchase_amount: 1500 + i * 250, purchase_amount_kind: 'OPENING_BID', publication_status: 'APPROVED_GRANDFATHERED', last_seen_at: now, updated_at: now }); });
  return out;
}
function auctionRows() {
  // Five lots on the soonest sale day, so the deck has somewhere to go.
  const d = new Date(); d.setDate(d.getDate() + 1); const day = d.toISOString().slice(0, 10);
  const out = [];
  for (let i = 0; i < 5; i++) out.push({ id: `pa${i}`, source: 'auction', state: 'FL', county: 'Duval', case_no: `2026-TD-${100 + i}`, parcel: `0${i}-2S-26E-${i}`, address: `${100 + i * 7} Riverside Ave`, bid: 4200 + i * 1375, assessed: 60000 + i * 4000, market: 80000 + i * 5000, status: 'active', sale_date: day, url_auction: 'https://duval.realtaxdeed.com/', url_auction_kind: 'sale', lien_level: 'unscreened', lien_note: '', last_seen_at: now, updated_at: now });
  return out;
}
const ROWS = { lands: laftRows, auctions: auctionRows, certificates: certRows };
const XP = { lands: 'terrain', auctions: 'tactile', certificates: 'merged' };

async function open(route, viewport, opts = {}) {
  const pg = await browser.newPage({ viewport, reducedMotion: opts.reduced ? 'reduce' : 'no-preference' });
  pg.on('pageerror', e => { console.log('pageerror ' + e.message); failed++; });
  await pg.addInitScript(r => { window.__stubExtraRows = r; try { localStorage.removeItem('tdw_experience_v1'); } catch {} }, ROWS[route]());
  await pg.goto(`${BASE_URL}?look=merged#/${route}`, { waitUntil: 'networkidle' });
  if (opts.dark) await pg.evaluate(() => document.documentElement.setAttribute('data-theme', 'dark'));
  await pg.waitForTimeout(2000);
  return pg;
}

// ---- 1. desktop side panel summary
for (const route of Object.keys(ROWS)) {
  const pg = await open(route, { width: 1440, height: 900 });
  const s = await pg.evaluate(() => {
    const box = document.querySelector('#detailPanel > .xp-panelsum');
    return { has: !!box, xp: box && box.dataset.xp, text: box ? box.textContent.replace(/\s+/g, ' ').trim() : '', visible30: !!box && box.getBoundingClientRect().height > 30 && box.getBoundingClientRect().height <= 90, hash: location.hash, empty: !!document.querySelector('#detailPanel > .detail-panel-empty') };
  });
  // Investor sprint (owner, 2026-11-12: cards "front and center"): the
  // summary is a slim strip above the cards (visible > 30px, not > 80px), and
  // "Open the ..." opens the record wide (#detailModal), never in the panel.
  check(`panelSummaryShown_${route}`, s.has && s.visible30 && s.xp === XP[route], s);
  check(`panelSummaryKeepsEmptyState_${route}`, s.empty && !/\/[^/]+\/./.test(s.hash.replace(/^#\//, '/')), s.hash);
  check(`panelSummaryNamesTheList_${route}`, /^In this list/.test(s.text) && /Open the/.test(s.text), s.text.slice(0, 160));
  await pg.click('#detailPanel .xp-panelsum [data-xps-open]');
  await pg.waitForTimeout(500);
  const o = await pg.evaluate(() => ({ modal: !document.getElementById('detailModal').hidden && !!document.querySelector('#detailModalInner.detail-wide .detail-address'), panelRecord: !!document.querySelector('#detailPanel .detail-address'), sum: !!document.querySelector('#detailPanel > .xp-panelsum'), hash: location.hash }));
  check(`panelSummaryOpensARecord_${route}`, o.modal && !o.panelRecord && o.sum, o);
  await pg.close();
}
{
  const pg = await open('lands', { width: 390, height: 844 });
  const v = await pg.evaluate(() => { const b = document.querySelector('#detailPanel > .xp-panelsum'); return !!b && b.getBoundingClientRect().height > 0; });
  check('panelSummaryNotOnPhone', !v, v);
  await pg.close();
}

// ---- 2. Available: slim light county bar, folded caveat
for (const vp of [{ width: 1440, height: 900 }, { width: 390, height: 844 }]) {
  const pg = await open('lands', vp);
  const bar = await pg.evaluate(() => {
    const b = document.querySelector('#countyNowBar'); const row = b.querySelector('.cnb-row');
    const m = getComputedStyle(b).backgroundColor.match(/\d+(\.\d+)?/g).map(Number);
    return { h: Math.round(row.getBoundingClientRect().height), bg: m, steps: [...b.querySelectorAll('.cnb-step')].map(s => Math.round(s.getBoundingClientRect().height)) };
  });
  check(`countyBarLight_${vp.width}`, bar.bg[0] > 230 && bar.bg[1] > 230, bar.bg);
  check(`countyBarSlim_${vp.width}`, bar.h <= (vp.width < 500 ? 64 : 48) && bar.steps.every(h => h >= 44), bar);
  // 2026-11-10 (owner): the caveat is a "+" beside the price; hover or press shows it in full.
  const note = await pg.evaluate(() => {
    const w = document.querySelector('#xpStage .xt-acard .xt-fig-main .xt-amt-plus');
    if (!w) return null;
    const pop = w.querySelector('.xt-amt-pop'), btn = w.querySelector('.xt-amt-btn');
    return { plus: btn.textContent.trim(), label: btn.getAttribute('aria-label'), expanded: btn.getAttribute('aria-expanded'), text: pop.textContent.replace(/\s+/g, ' '), popVisible: pop.checkVisibility(),
      oldLine: !!document.querySelector('#xpStage .xt-acard details.xt-amt-note'), besidePrice: !!w.previousElementSibling && w.previousElementSibling.classList.contains('xt-num') };
  });
  check(`amountCaveatFolded_${vp.width}`, !!note && note.plus === '+' && note.besidePrice && !note.oldLine && note.expanded === 'false' && !note.popVisible && /Not the price to buy now/.test(note.label), note);
  check(`amountCaveatKeptInFull_${vp.width}`, !!note && /Not the price to buy now/.test(note.text) && /Request the current Lands Available statement from the clerk/.test(note.text), note && note.text);
  await pg.locator('#xpStage .xt-acard .xt-amt-btn').first().click();
  const opened = await pg.evaluate(() => { const w = document.querySelector('#xpStage .xt-acard .xt-amt-plus'); return w.classList.contains('open') && w.querySelector('.xt-amt-btn').getAttribute('aria-expanded') === 'true' && w.querySelector('.xt-amt-pop').checkVisibility(); });
  check(`amountCaveatOpens_${vp.width}`, opened, opened);
  const order = await pg.evaluate(() => { const c = document.querySelector('#xpStage .xt-acard'); const t = c.querySelector('.xt-lot-t').getBoundingClientRect().top, k = c.querySelector('.xt-lot-k').getBoundingClientRect().top, f = c.querySelector('.xt-fig-main').getBoundingClientRect().top; return { t, k, f }; });
  check(`cardLeadsWithAddress_${vp.width}`, order.t < order.k && order.k < order.f, order);
  // The record's own status stamp (app.js cardStamp, as on the Classic card).
  const stamp = await pg.evaluate(() => { const s = document.querySelector('#xpStage .xt-acard .xt-stamp'); return s ? s.textContent.trim() : null; });
  // Plain language (owner, 2026-11-12): "How to buy: confirmed / not yet confirmed".
  check(`cardStampFromRecord_${vp.width}`, /^(How to buy: confirmed|How to buy: not yet confirmed|Dated list|No longer listed)$/.test(stamp || ''), stamp);
  await pg.close();
}

// ---- 3. Auctions: arrow keys move the deck
for (const vp of [{ width: 1440, height: 900 }, { width: 390, height: 844 }]) {
  const pg = await open('auctions', vp);
  const lotOf = () => pg.evaluate(() => document.querySelector('#xpStage .xpt-deck-ctl .xpt-pager b').textContent.trim());
  await pg.keyboard.press('Tab');
  await pg.evaluate(() => document.querySelector('#xpStage .xpt-deck .xpt-placard .face.front').focus());
  const before = await lotOf();
  await pg.keyboard.press('ArrowRight');
  await pg.waitForTimeout(700);
  const after = await lotOf();
  const focusIn = await pg.evaluate(() => !!document.activeElement.closest('#xpStage .xpt-deck'));
  check(`deckArrowRight_${vp.width}`, before === '1' && after === '2', { before, after });
  check(`deckKeepsFocus_${vp.width}`, focusIn, focusIn);
  await pg.keyboard.press('ArrowLeft');
  await pg.waitForTimeout(700);
  check(`deckArrowLeft_${vp.width}`, (await lotOf()) === '1', await lotOf());
  const ring = await pg.evaluate(() => { const f = document.activeElement; const cs = getComputedStyle(f); return { tag: f.className, style: cs.outlineStyle, w: parseFloat(cs.outlineWidth) }; });
  check(`placardFocusRing_${vp.width}`, ring.style !== 'none' && ring.w >= 2, ring);
  const plate = await pg.evaluate(() => { const face = document.querySelector('#xpStage .xpt-deck .xpt-placard .face.front'); const fr = face.getBoundingClientRect(); const figs = face.querySelector('.figs').getBoundingClientRect(); const foot = face.querySelector('.xpt-cfoot, .xpt-offlist'); const end = foot ? foot.getBoundingClientRect().bottom : figs.bottom; return { gap: Math.round(fr.bottom - end) }; });
  check(`placardHasNoDeadFoot_${vp.width}`, plate.gap <= 40, plate);
  await pg.close();
}

// ---- 4. Liens: the fan uses the stage width; the toggle is named
{
  const pg = await open('certificates', { width: 1440, height: 900 });
  const l = await pg.evaluate(() => {
    const st = document.querySelector('#xpStage .fan-stage'); const tray = document.querySelector('#xpStage .tray').getBoundingClientRect();
    const slips = [...st.querySelectorAll('.fslip')].map(s => s.getBoundingClientRect());
    const grp = document.querySelector('#xpStage .xpm-sorts'); const lbl = document.getElementById(grp.getAttribute('aria-labelledby'));
    return { wrap: getComputedStyle(st).flexWrap, trayLeft: tray.left, slipsRight: Math.max(...slips.map(r => r.right)), trayTop: tray.top, stageTop: st.getBoundingClientRect().top, rows: new Set(slips.map(r => Math.round(r.top / 10))).size, label: lbl && lbl.textContent.trim(), slipW: Math.round(slips[0].width) };
  });
  check('liensSlipsWrap', l.wrap === 'wrap' && l.rows >= 2, l);
  check('liensTrayBesideSlips', l.trayLeft >= l.slipsRight - 1 && Math.abs(l.trayTop - l.stageTop) < 80, l);
  check('liensSlipScaled', l.slipW >= 160, l.slipW);
  check('liensGroupToggleNamed', l.label === 'Group slips', l.label);
  await pg.close();
  const ph = await open('certificates', { width: 390, height: 844 });
  const p = await ph.evaluate(() => { const st = document.querySelector('#xpStage .fan-stage'); const tray = document.querySelector('#xpStage .tray').getBoundingClientRect(); return { wrap: getComputedStyle(st).flexWrap, below: tray.top > st.getBoundingClientRect().bottom - 2 }; });
  check('liensPhoneRowAndTrayBelow', p.wrap === 'nowrap' && p.below, p);
  await ph.close();
}

// ---- 5. AA contrast in light and dark; reduced motion
const AUDIT = `(() => {
  const parse = c => { const m = c.match(/rgba?\\(([^)]+)\\)/); if (!m) return null; const p = m[1].split(/[ ,\\/]+/).filter(Boolean).map(Number); return { r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1 }; };
  const lum = c => { const f = v => { v /= 255; return v <= .03928 ? v / 12.92 : Math.pow((v + .055) / 1.055, 2.4); }; return .2126 * f(c.r) + .7152 * f(c.g) + .0722 * f(c.b); };
  const blend = (t, b) => ({ r: t.r * t.a + b.r * (1 - t.a), g: t.g * t.a + b.g * (1 - t.a), b: t.b * t.a + b.b * (1 - t.a), a: 1 });
  const bgOf = el => { const st = []; for (let e = el; e; e = e.parentElement) { const c = parse(getComputedStyle(e).backgroundColor); if (c && c.a > 0) { st.push(c); if (c.a >= 1) break; } } let base = { r: 255, g: 255, b: 255, a: 1 }; for (let i = st.length - 1; i >= 0; i--) base = blend(st[i], base); return base; };
  const out = [];
  for (const root of document.querySelectorAll('#xpStage, #detailPanel .xp-panelsum, #countyNowBar')) for (const el of root.querySelectorAll('*')) {
    if (![...el.childNodes].some(n => n.nodeType === 3 && n.textContent.trim())) continue;
    const r = el.getBoundingClientRect(); if (!r.width || !r.height) continue;
    const cs = getComputedStyle(el); if (cs.visibility === 'hidden' || +cs.opacity === 0) continue;
    if (el.closest('[aria-hidden="true"]')) continue;
    const bg = bgOf(el), fg = blend(parse(cs.color), bg);
    const L1 = lum(fg), L2 = lum(bg), ratio = (Math.max(L1, L2) + .05) / (Math.min(L1, L2) + .05);
    const size = parseFloat(cs.fontSize), large = size >= 24 || (+cs.fontWeight >= 700 && size >= 18.66);
    if (ratio < (large ? 3 : 4.5)) out.push({ text: el.textContent.trim().slice(0, 30), ratio: +ratio.toFixed(2) });
  }
  return out;
})()`;
for (const dark of [false, true]) for (const route of Object.keys(ROWS)) {
  const pg = await open(route, { width: 1440, height: 900 }, { dark });
  const bad = await pg.evaluate(AUDIT);
  check(`contrastAA_${dark ? 'dark' : 'light'}_${route}`, bad.length === 0, bad.slice(0, 6));
  await pg.close();
}
{
  const pg = await open('lands', { width: 1440, height: 900 }, { reduced: true });
  const a = await pg.evaluate(() => { const b = document.querySelector('#detailPanel > .xp-panelsum'); return b ? getComputedStyle(b).animationName : null; });
  check('panelSummaryStillUnderReducedMotion', a === 'none', a);
  await pg.close();
}

await browser.close();
console.log(failed ? `FAILED ${failed}` : 'ALL PASS');
process.exit(failed ? 1 : 0);
