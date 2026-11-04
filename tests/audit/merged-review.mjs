// Merged-work review fixes (2026-11-02):
//  1. picking another county in #mapCountySelect while a map card is open
//     keeps that county (it used to drop to All Counties / "#/map");
//  2. on short phones (375x667, 360x640) the map card's Open property /
//     Watchlist buttons sit above the fixed ledger bar;
//  3. an assessed value of 0 is "not published" on every surface (card,
//     Available "with values" filter, data gaps, property page);
//  4. the map card's fact labels wrap instead of being cut with "...".
import { chromium } from 'playwright';
import fs from 'fs';
const BASE = process.env.BASE_URL || 'http://localhost:8934/index.html';
const exe = '/opt/pw-browsers/chromium';
const b = await chromium.launch(fs.existsSync(exe) ? { executablePath: exe } : {});
let fail = 0;
const check = (name, ok, got) => { console.log((ok ? 'PASS ' : 'FAIL ') + name + (ok ? '' : ' -> ' + JSON.stringify(got))); if (!ok) fail++; };
const errs = [];
async function open(hash, vp, ctxOpts = {}, init, arg) {
  const ctx = await b.newContext({ viewport: vp, ...ctxOpts });
  const pg = await ctx.newPage();
  pg.on('pageerror', e => errs.push(hash + ': ' + e.message));
  if (init) await pg.addInitScript(init, arg);
  await pg.goto(BASE + hash, { waitUntil: 'networkidle' });
  await pg.waitForTimeout(900);
  return pg;
}
const rect = (pg, sel) => pg.evaluate(s => { const el = document.querySelector(s); if (!el) return null; const r = el.getBoundingClientRect(); return { top: r.top, bottom: r.bottom, left: r.left, right: r.right, h: r.height, w: r.width }; }, sel);

// ---- 1. County change while a map card is open (desktop) ----
{
  const pg = await open('#/map', { width: 1440, height: 900 });
  await pg.selectOption('#mapCountySelect', 'Brevard'); await pg.waitForTimeout(900);
  await pg.locator('#exploreMapCanvas .map-pin[data-pid="p12"]').click({ force: true }); await pg.waitForTimeout(500);
  check('cardOpenOnBrevard', await pg.evaluate(() => !document.getElementById('explorePreview').hidden && location.hash === '#/map?county=Brevard'), await pg.evaluate(() => location.hash));
  await pg.selectOption('#mapCountySelect', 'Bay'); await pg.waitForTimeout(1300);
  const st = await pg.evaluate(() => ({ hash: location.hash, select: document.getElementById('mapCountySelect').value, cardHidden: document.getElementById('explorePreview').hidden,
    zoomed: document.getElementById('exploreMapCanvas').classList.contains('zoomed'), title: (document.querySelector('.map-side-head h2, #mapSideTitle, .explore-map-title') || {}).textContent }));
  check('countyChangeKeepsNewCounty', st.select === 'Bay' && st.hash === '#/map?county=Bay', st);
  check('countyChangeClosesOldCard', st.cardHidden === true, st);
  check('countyChangeStaysZoomed', st.zoomed === true, st);
  // The back stack is intact: one Back closes the county zoom, nothing more.
  await pg.goBack(); await pg.waitForTimeout(900);
  check('backAfterCountyChangeLeavesCounty', await pg.evaluate(() => document.getElementById('mapCountySelect').value === 'ALL' && !document.getElementById('exploreMapCanvas').classList.contains('zoomed')), await pg.evaluate(() => [location.hash, document.getElementById('mapCountySelect').value]));
  await pg.context().close();
}

// ---- 2. Short phones: the card's buttons stay above the ledger bar ----
for (const vp of [{ width: 375, height: 667 }, { width: 360, height: 640 }]) {
  const label = `phone${vp.width}x${vp.height}`;
  const pg = await open('#/map', vp, { hasTouch: true, isMobile: true });
  await pg.selectOption('#mapCountySelect', 'Charlotte'); await pg.waitForTimeout(900);
  const y0 = await pg.evaluate(() => window.scrollY);
  await pg.locator('#exploreMapCanvas .map-pin[data-pid="p5"]').click({ force: true }); await pg.waitForTimeout(900);
  const bar = await rect(pg, '#navBottom'), openBtn = await rect(pg, '#explorePreview .preview-open'), watch = await rect(pg, '#explorePreview .mp-watch .bid-btn'), card = await rect(pg, '#explorePreview'), stage = await rect(pg, '#mapStage');
  check(label + 'StageRunsUnderBar', stage && bar && stage.bottom > bar.top, { stage, bar });   // the case this fix is for
  check(label + 'OpenAboveBar', openBtn && bar && openBtn.bottom <= bar.top, { openBtn, bar });
  check(label + 'WatchlistAboveBar', watch && bar && watch.bottom <= bar.top, { watch, bar });
  check(label + 'CardInsideStage', card && stage && card.top >= stage.top && card.bottom <= stage.bottom, { card, stage });
  check(label + 'NoPageScroll', (await pg.evaluate(() => window.scrollY)) === y0, null);
  // The buttons are what a tap hits (nothing paints over them).
  check(label + 'OpenIsHit', await pg.evaluate(() => { const el = document.querySelector('#explorePreview .preview-open'); const r = el.getBoundingClientRect(); const h = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2); return !!h && (h === el || el.contains(h)); }), null);
  // The pin stays clear of the lifted card.
  const pin = await rect(pg, '#exploreMapCanvas .map-pin.sel path');
  check(label + 'PinClearOfCard', pin && card && (pin.bottom < card.top || pin.top > card.bottom), { pin, card });
  await pg.click('#explorePreview .preview-close'); await pg.waitForTimeout(600);
  check(label + 'LiftClearedOnClose', await pg.evaluate(() => document.getElementById('explorePreview').style.getPropertyValue('--mp-lift') === ''), null);
  await pg.context().close();
}
// A tall phone and the desktop are untouched (no lift when nothing is covered).
{
  const pg = await open('#/map', { width: 1440, height: 900 });
  await pg.selectOption('#mapCountySelect', 'Charlotte'); await pg.waitForTimeout(900);
  await pg.locator('#exploreMapCanvas .map-pin[data-pid="p5"]').click({ force: true }); await pg.waitForTimeout(600);
  check('desktopNoLift', await pg.evaluate(() => document.getElementById('explorePreview').style.getPropertyValue('--mp-lift') === ''), null);
  await pg.context().close();
}

// ---- 3. assessed = 0 is not a value, on every surface ----
{
  // Two Available rows shaped like fixture p3 (Citrus), one with assessed 0.
  const mk = (id, assessed, addr) => ({ id, source: 'laft', county: 'Citrus', case_no: 'ZERO-' + id, parcel: '17E18S' + id, address: addr, bid: 0, assessed, market: null, taxable_value: null,
    status: 'available', lien_level: 'unscreened', lien_note: '', sale_date: null, updated_at: '2026-10-30T00:00:00Z', inventory_type: 'POST_SALE_FIXED_PRICE', source_authority: 'GOVERNMENT_PLATFORM',
    source_id: 'fl_laft_pdfs', list_url: 'https://x', purchase_amount: null, purchase_amount_kind: 'NOT_PUBLISHED', last_seen_at: new Date().toISOString(), publication_status: 'APPROVED_GRANDFATHERED' });
  const pg = await open('#/lands', { width: 1440, height: 900 }, {}, r => { window.__stubExtraRows = r; }, [mk('zero1', 0, '1 Zero Assessed Rd'), mk('zero2', 12345, '2 Real Assessed Rd')]);
  const r = await pg.evaluate(() => {
    const all = (window.__tdwLastRender && window.__tdwLastRender.rows) || [];
    const z = all.find(p => p.id === 'zero1'), real = all.find(p => p.id === 'zero2');
    const f = window.__tdwMapLastRender && window.__tdwMapLastRender.previewFacts;
    return { haveRows: !!(z && real), previewZero: f ? f(z).value : 'no-previewFacts', previewReal: f ? f(real).value : 'no-previewFacts' };
  });
  check('zeroRowsLoaded', r.haveRows, r);
  check('previewFactsZeroAssessedNull', r.previewZero === null && /12,345|12\.3K/.test(String(r.previewReal)), r);
  // Card: no "$0" anywhere on the zero row's card; the real row shows its value.
  const cardText = async id => pg.evaluate(id => { const c = document.querySelector(`.prop-card[data-pid="${id}"]`); return c ? c.textContent : null; }, id);
  await pg.evaluate(() => document.querySelectorAll('details.card-more, details').forEach(d => { d.open = true; }));
  const zc = await cardText('zero1'), rc = await cardText('zero2');
  check('cardZeroAssessedNotShown', zc !== null && !/\$0(?![.,\d])/.test(zc), zc && zc.slice(0, 300));
  check('cardRealRowRendered', rc !== null, null);
  // Property page: "Assessed value" reads "Not on file", never "$0.00"; the data gaps name the missing value.
  await pg.evaluate(() => { const p = window.__tdwLastRender.rows.find(x => x.id === 'zero1'); window.__tdwMapLastRender.openDetail(p); });
  await pg.waitForTimeout(900);
  const readDetail = () => pg.evaluate(() => {
    const m = [document.getElementById('detailModal'), document.getElementById('detailPanel')].find(el => el && !el.hidden && el.textContent.trim());
    if (!m) return null;
    m.querySelectorAll('details').forEach(d => { d.open = true; });
    const kv = [...m.querySelectorAll('.kv-row')].filter(r => /^Assessed value$/.test((r.querySelector('.kv-label') || {}).textContent.trim())).map(r => r.querySelector('.kv-val').textContent.trim());
    const gaps = [...m.querySelectorAll('.dec-gaps li')].map(li => li.textContent.trim());
    return { text: m.textContent.replace(/\s+/g, ' '), kv, gaps, zeros: (m.textContent.match(/\$0(?![.,\d])|\$0\.00/g) || []).length };
  });
  const page = await readDetail();
  check('detailOpened', !!page, null);
  check('detailNoZeroDollar', page && page.zeros === 0, page && (page.text.match(/.{40}\$0.{40}/) || [])[0]);
  check('detailAssessedRowNotOnFile', page && page.kv.every(v => /^Not on file/.test(v)), page && page.kv);
  // Show every field: the complete record's Assessed row reads "Not on file", never "$0.00".
  await pg.keyboard.press('Escape'); await pg.waitForTimeout(400);
  await pg.evaluate(() => { try { sessionStorage.setItem('tdw_full_fields_v1', '1'); } catch {} const p = window.__tdwLastRender.rows.find(x => x.id === 'zero1'); window.__tdwMapLastRender.openDetail(p); });
  await pg.waitForTimeout(900);
  const full = await readDetail();
  check('fullRecordAssessedNotOnFile', full && full.kv.length === 1 && /^Not on file/.test(full.kv[0]) && full.zeros === 0, full && { kv: full.kv, zeros: full.zeros });
  const fullText = full && full.text;
  check('fullRecordNamesValueGap', full && full.gaps.includes('No county value on file'), full && full.gaps);
  await pg.keyboard.press('Escape'); await pg.waitForTimeout(500);
  // Available "with values" filter: the zero row is excluded, the real one kept.
  const vals = await pg.evaluate(() => {
    const el = document.getElementById('availValues');
    if (!el) return 'no-filter';
    el.checked = true; el.dispatchEvent(new Event('change', { bubbles: true }));
    const ids = (window.__tdwLastRender.rows || []).map(p => p.id);
    el.checked = false; el.dispatchEvent(new Event('change', { bubbles: true }));
    return { zero: ids.includes('zero1'), real: ids.includes('zero2') };
  });
  check('availValuesFilterExcludesZero', vals === 'no-filter' || (vals.zero === false && vals.real === true), vals);
  await pg.context().close();
}

// ---- 4. Map card fact labels wrap, never "..." ----
{
  for (const [label, vp, opts] of [['desk', { width: 1440, height: 900 }, {}], ['phone', { width: 390, height: 844 }, { hasTouch: true, isMobile: true }]]) {
    const pg = await open('#/map', vp, opts);
    await pg.selectOption('#mapCountySelect', 'Charlotte'); await pg.waitForTimeout(900);
    await pg.locator('#exploreMapCanvas .map-pin[data-pid="p5"]').click({ force: true }); await pg.waitForTimeout(600);
    const dts = await pg.evaluate(() => [...document.querySelectorAll('#explorePreview .mp-fact dt')].filter(d => d.offsetParent !== null).map(d => ({
      text: d.textContent.trim(), cut: d.scrollWidth > d.clientWidth + 1, nowrap: getComputedStyle(d).whiteSpace === 'nowrap', ellipsis: getComputedStyle(d).textOverflow === 'ellipsis' })));
    check(label + 'FactLabelsPresent', dts.length >= 2, dts);
    check(label + 'FactLabelsNotCut', dts.every(d => !d.cut && !d.nowrap && !d.ellipsis), dts);
    // Each figure sits under its own label (same column, label above).
    const pairs = await pg.evaluate(() => [...document.querySelectorAll('#explorePreview .mp-fact')].filter(f => f.offsetParent !== null).map(f => {
      const a = f.querySelector('dt').getBoundingClientRect(), b = f.querySelector('dd').getBoundingClientRect();
      return { labelAbove: a.bottom <= b.top + 1, sameColumn: Math.abs(a.left - b.left) < 2 }; }));
    check(label + 'FigureUnderOwnLabel', pairs.every(p => p.labelAbove && p.sameColumn), pairs);
    await pg.context().close();
  }
}

check('noPageErrors', errs.length === 0, errs);
await b.close();
console.log(fail ? `FAIL: ${fail} check(s)` : 'PASS: all merged-review checks');
process.exit(fail ? 1 : 0);
