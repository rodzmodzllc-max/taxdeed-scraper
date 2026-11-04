// Audit 2026-10-28, theme merged-liens-available: proves the fixes for
// F8 F9 F45 F46 F86 (Merged Liens slips / bundles), F11 (Louisiana $0 value),
// F48 F49 F65 (Merged Available county stories).
// Standalone: BASE_URL=http://localhost:8872/index.html node tests/audit/merged-liens-available.mjs
import { chromium } from 'playwright';
import fs from 'node:fs';

const BASE_URL = process.env.BASE_URL || 'http://localhost:8934/index.html';
const ROOT = BASE_URL.replace(/[^/]*$/, '');
const SANDBOX_CHROMIUM = '/opt/pw-browsers/chromium';
const browser = await chromium.launch(fs.existsSync(SANDBOX_CHROMIUM) ? { executablePath: SANDBOX_CHROMIUM } : {});
let failed = 0;
const check = (name, ok, info) => { console.log(`${ok ? 'PASS' : 'FAIL'} ${name}${ok ? '' : ' :: ' + JSON.stringify(info)}`); if (!ok) failed++; };

const now = new Date().toISOString();
const FL_COUNTIES = ['Alachua', 'Bay', 'Brevard', 'Citrus', 'Clay', 'Duval', 'Escambia', 'Hernando', 'Lake', 'Leon', 'Marion', 'Orange'];
// Certificates: 2025 bundle (6 slips, 6 counties), then 2024 / 2023 / 2022.
function certRows() {
  const out = [];
  const add = (year, i, county) => out.push({ id: `ac${year}-${i}`, source: 'certificate', state: 'FL', county, case_no: `${year}-${1000 + i}`, certificate_no: String(1000 + i), parcel: `P${year}${i}`, tax_year: String(year), bid: 500 + i * 37.25, interest_rate: 18, status: 'active', lien_level: 'unscreened', lien_note: '', url_auction: 'https://lienhub.com/county/alachua/countyheld/certificates', url_auction_kind: 'county', last_seen_at: now, updated_at: now });
  for (let i = 0; i < 6; i++) add(2025, i, FL_COUNTIES[i]);
  for (const y of [2024, 2023, 2022]) for (let i = 0; i < 4; i++) add(y, i, FL_COUNTIES[i]);
  // Production shape of a Sarasota Tax Collector certificate (case_no = "<year>-<cert #>", parcel = the account).
  out.push({ id: 'asar1', source: 'certificate', state: 'FL', county: 'Sarasota', parcel: '1149205634', case_no: '2019-9057', certificate_no: '9057', source_id: 'fl_sarasota_tc_certificates', harvester_source: 'fl_sarasota_tc_certificates', ledger_type: 'lien', status: 'active', address: 'Account 1149205634', bid: 718.98, assessed: 100, tax_year: '2019', interest_rate: 18, url_auction: 'https://www.sarasotataxcollector.gov/services/tax-services/property-tax/tax-cert-sale', inventory_status: 'certificate_listed', last_seen_at: now, updated_at: now, lien_level: 'unscreened', lien_note: '' });
  return out;
}
// Available: 12 counties x 10 lots, so later stories fill in lazily.
function laftRows() {
  const out = [];
  FL_COUNTIES.forEach((county, c) => { for (let i = 0; i < 10; i++) out.push({ id: `al${c}-${i}`, source: 'laft', state: 'FL', county, case_no: `AL-${c}-${i}`, parcel: `${c}${i}000${i}`, address: `${i + 1} ${county} Rd`, bid: 1500 + i, assessed: 20000 + i, market: 21000 + i, status: 'available', lien_level: 'unscreened', lien_note: '', sale_date: null, url_auction: 'https://x', url_auction_kind: 'county', inventory_type: 'POST_SALE_FIXED_PRICE', source_authority: 'GOVERNMENT_PLATFORM', source_id: 'fl_laft_pioneer', list_url: 'https://x', purchase_amount: 1500 + i, purchase_amount_kind: 'OPENING_BID', publication_status: 'APPROVED_GRANDFATHERED', last_seen_at: now, updated_at: now }); });
  return out;
}
// Production shape of an East Baton Rouge adjudicated row: market 0, assessed 440.
const LA_ROW = { id: 'ala1', state: 'LA', county: 'East Baton Rouge', parcel: '011-3641-0', case_no: '011-3641-0', source: 'laft', source_id: 'la_ebr_adjudicated', harvester_source: 'la_ebr_adjudicated', ledger_type: 'buy', status: 'active', address: '7452 DAN DR', bid: 0, market: 0, assessed: 440, tax_year: '2023', url_auction: 'https://data.brla.gov/d/shrr-fsqq', list_url: 'https://data.brla.gov/d/shrr-fsqq', inventory_type: 'ADJUDICATED_PROPERTY', purchase_amount: null, purchase_amount_kind: 'NOT_PUBLISHED', publication_status: 'APPROVED', last_seen_at: now, updated_at: now, list_as_of: '2026-05-06', inventory_status: 'active', lien_level: 'unscreened', lien_note: '' };

async function open(url, viewport, rows) {
  const pg = await browser.newPage({ viewport });
  pg.on('pageerror', e => { console.log('pageerror ' + e.message); failed++; });
  await pg.addInitScript(SLIP_COV);
  await pg.addInitScript(r => { window.__stubExtraRows = r; try { localStorage.removeItem('tdw_experience_v1'); } catch {} }, rows);
  await pg.goto(url, { waitUntil: 'networkidle' });
  await pg.waitForTimeout(2200);
  return pg;
}

// Fraction of a slip's own tap area that is really its own on screen, read
// with the slip brought into view in its row (the fan is a sideways
// scroll-snap row: a slip beyond the screen edge is swiped to, not covered).
const slipCoverage = async pg => {
  const n = await pg.locator('#xpStage .fan-stage .fslip').count();
  const out = [];
  for (let i = 0; i < n; i++) {
    await pg.evaluate(i => document.querySelectorAll('#xpStage .fan-stage .fslip')[i].scrollIntoView({ inline: 'center', block: 'nearest' }), i);
    await pg.waitForTimeout(250);
    out.push(await pg.evaluate(i => slipCov(document.querySelectorAll('#xpStage .fan-stage .fslip')[i]), i));
  }
  return out;
};
const SLIP_COV = `window.slipCov = s => {
  const fb = s.querySelector('.fb'), fs = s.querySelector('.fs');
  const r = fb.getBoundingClientRect(); let hit = 0, tot = 0;
  for (let x = r.left + 2; x < r.right; x += 4) for (let y = r.top + 2; y < r.bottom; y += 4) { tot++; const e = document.elementFromPoint(x, y); if (e && fb.contains(e)) hit++; }
  const wr = fs ? fs.getBoundingClientRect() : null;
  const we = wr ? document.elementFromPoint(wr.left + wr.width / 2, wr.top + wr.height / 2) : null;
  const txt = fb.textContent.replace(/\s+/g, ' ').trim();
  return { pid: fb.dataset.pid, lifted: s.classList.contains('lifted'), cov: tot ? hit / tot : 0, watchOk: !fs || !!(we && fs.contains(we)), txt };
};`;

for (const vp of [{ width: 1366, height: 900 }, { width: 390, height: 844 }]) {
  const tag = vp.width < 500 ? 'phone' : 'desk';
  const pg = await open(BASE_URL + '?look=merged#/certificates', vp, certRows());
  // F86: plural of the unit word.
  const subs = await pg.$$eval('#xpStage .band-sub', els => els.map(e => e.textContent.trim()));
  check(`F86 bundle sub-lines say counties (${tag})`, subs.length > 0 && subs.every(s => !/countys|parishs/.test(s)) && subs.some(s => /counties/.test(s)), subs);

  // F8: every slip of the fan is readable and tappable, its Watch reachable.
  await pg.locator('#xpStage .fan-stage').scrollIntoViewIfNeeded();
  const cov = await slipCoverage(pg);
  check(`F8 five slips fanned (${tag})`, cov.length === 5, cov.length);
  check(`F8 every slip >= 60% tappable (${tag})`, cov.every(c => c.cov >= 0.6), cov.map(c => +c.cov.toFixed(2)));
  check(`F8 every Watch strip reachable (${tag})`, cov.every(c => c.watchOk), cov.map(c => c.watchOk));
  const row = await pg.evaluate(() => { const f = document.querySelector('#xpStage .fan-stage'); const cs = getComputedStyle(f); return { ox: cs.overflowX, snap: cs.scrollSnapType, sw: f.scrollWidth, cw: f.clientWidth }; });
  check(`F8 fan is a sideways snap row (${tag})`, /auto|scroll/.test(row.ox) && /x/.test(row.snap) && (tag === 'desk' || row.sw > row.cw), row);
  check(`F8 lifted slip shows its cert number and amount (${tag})`, cov.filter(c => c.lifted).every(c => /\d{4}/.test(c.txt) && /\$/.test(c.txt)), cov.filter(c => c.lifted));

  // F45: a slip tap updates in place.
  await pg.evaluate(() => { window.__fslips = [...document.querySelectorAll('#xpStage .fslip')]; window.__tray = document.querySelector('#xpStage .tray'); });
  const second = cov.find(c => !c.lifted);
  await pg.locator(`#xpStage .fslip .fb[data-pid="${second.pid}"]`).click();
  await pg.waitForTimeout(60);
  const after = await pg.evaluate(pid => {
    const nodes = [...document.querySelectorAll('#xpStage .fslip')];
    const tray = document.querySelector('#xpStage .tray');
    return { same: nodes.length === window.__fslips.length && nodes.every((n, i) => n === window.__fslips[i]), sameTray: tray === window.__tray, trayOpacity: +getComputedStyle(tray).opacity,
      lifted: (document.querySelector('#xpStage .fslip.lifted .fb') || { dataset: {} }).dataset.pid === pid, trayCert: tray.querySelector('.tray-cert').textContent };
  }, second.pid);
  check(`F45 slip nodes kept on a slip tap (${tag})`, after.same && after.sameTray, after);
  check(`F45 tray never blinks out (${tag})`, after.trayOpacity > 0.9, after.trayOpacity);
  check(`F45 tapped slip is lifted and tray names it (${tag})`, after.lifted && after.trayCert.includes(second.txt.match(/\d{4}/)[0]), after);

  // F9: fanning a lower bundle keeps it on screen.
  const pile = pg.locator('#xpStage .pile').nth(1);
  await pile.scrollIntoViewIfNeeded();
  const key = await pile.getAttribute('data-key');
  const before = await pile.evaluate(e => e.getBoundingClientRect().top);
  await pile.click();
  await pg.waitForTimeout(400);
  const fan = await pg.evaluate(k => { const f = document.querySelector('#xpStage .xpm-bundle.fanned'); const r = f.querySelector('.fan-stage').getBoundingClientRect(); return { key: f.querySelector('.fold-back').dataset.key, top: r.top, bottom: r.bottom, vh: innerHeight }; }, key);
  check(`F9 fanned bundle stays on screen (${tag})`, fan.key === key && fan.top >= -1 && fan.top < fan.vh - 100 && Math.abs(fan.top - before) < 60, { before, fan });

  // F46: Sarasota tray shows the account as the parcel, not the year-cert.
  await pg.click('#xpStage [data-xa="bundleby"][data-by="county"]');
  await pg.waitForTimeout(300);
  await pg.locator('#xpStage .pile[data-key="Sarasota"]').scrollIntoViewIfNeeded();
  await pg.click('#xpStage .pile[data-key="Sarasota"]');
  await pg.waitForTimeout(400);
  const facts = await pg.$$eval('#xpStage .tray .fact', els => els.map(e => [e.querySelector('.k').textContent, e.querySelector('.v').textContent]));
  check(`F46 Sarasota tray shows parcel 1149205634 (${tag})`, facts.some(f => f[1] === '1149205634') && !facts.some(f => f[0] === 'Account' && f[1] === '2019-9057'), facts);
  await pg.close();
}

// F11: Louisiana market 0 is never a "$0" value.
for (const vp of [{ width: 1366, height: 900 }, { width: 390, height: 844 }]) {
  const pg = await open(ROOT + 'la.html?look=merged#/lands', vp, [LA_ROW]);
  const card = await pg.evaluate(() => { const c = document.querySelector('#xpStage .xt-acard[data-pid="ala1"]'); return c ? c.querySelector('.xt-figs').textContent.replace(/\s+/g, ' ').trim() : null; });
  check(`F11 LA card never shows a $0 value (${vp.width})`, !!card && !/\$0\b/.test(card) && !/Fair Market Value/i.test(card) && /\$440/.test(card), card);
  await pg.close();
}

// F65 / F49: the county card rail is a horizontal, snapping strip at every width.
for (const vp of [{ width: 390, height: 844 }, { width: 1440, height: 900 }, { width: 1455, height: 900 }, { width: 1420, height: 900 }]) {
  const pg = await open(BASE_URL + '?look=merged#/lands', vp, laftRows());
  const r = await pg.evaluate(() => { const rail = document.querySelector('#xpStage .xt-rail:not(.xt-rail-lazy)'); const cs = getComputedStyle(rail); const vis = rail.querySelector('.xt-acard-vis'); const card = rail.querySelector('.xt-acard');
    return { dir: cs.flexDirection, snap: cs.scrollSnapType, sw: rail.scrollWidth, cw: rail.clientWidth, visH: vis.getBoundingClientRect().height, cardW: card.getBoundingClientRect().width, h: rail.getBoundingClientRect().height }; });
  check(`F65/F49 rail is a horizontal snap strip at ${vp.width}`, r.dir === 'row' && /x/.test(r.snap) && r.sw > r.cw + 40, r);
  check(`F65/F49 card picture height bounded at ${vp.width}`, r.visH <= 260 && r.cardW < r.cw, r);
  if (vp.width === 390) {
    const rail = pg.locator('#xpStage .xt-rail:not(.xt-rail-lazy)').first();
    await rail.scrollIntoViewIfNeeded();
    const b = await rail.boundingBox();
    // A touch-like horizontal drag (wheel with deltaX stands in for a finger swipe).
    await pg.mouse.move(b.x + b.width / 2, b.y + 100);
    await pg.mouse.wheel(300, 0);
    await pg.waitForTimeout(700);
    const sl = await rail.evaluate(e => e.scrollLeft);
    check('F65 phone rail slides sideways', sl > 100, sl);
  }
  await pg.close();
}

// F48: picking a far county from the "Now showing" list lands on that county.
for (const vp of [{ width: 1600, height: 900 }, { width: 390, height: 844 }]) {
  const pg = await open(BASE_URL + '?look=merged#/lands', vp, laftRows());
  for (const target of ['Marion', 'Orange']) {
    await pg.evaluate(() => window.scrollTo(0, 0));
    await pg.waitForTimeout(400);
    await pg.click('#countyNowBar .cnb-mid');
    await pg.waitForTimeout(200);
    await pg.click(`#countyNowBar [data-cnb-pick="${target}"]`);
    await pg.waitForTimeout(2600);
    const r = await pg.evaluate(t => { const h = document.querySelector(`#xpStage [data-county-head="${t}"]`); const bar = document.querySelector('#countyNowBar [data-cnb-name]'); const row = document.querySelector('#countyNowBar .cnb-row');
      return { top: Math.round(h.getBoundingClientRect().top), barBottom: Math.round(row.getBoundingClientRect().bottom), name: bar.textContent.trim() }; }, target);
    check(`F48 jump to ${target} lands on its head (${vp.width})`, r.name.startsWith(target) && r.top >= r.barBottom - 30 && r.top <= r.barBottom + 80, r);
  }
  await pg.close();
}

await browser.close();
console.log(failed ? `FAILED ${failed}` : 'ALL PASS');
process.exit(failed ? 1 : 0);
