// Buyer's Guide page (2026-10-29): #/guide renders per state / ledger / county
// from buyers-guide.json, or from state-rules.json while that file is absent.
import { chromium } from 'playwright';
import fs from 'fs';
const BASE = process.env.BASE_URL || 'http://localhost:8934/index.html';
const root = BASE.replace(/[^/]*$/, '');
const exe = '/opt/pw-browsers/chromium';
const b = await chromium.launch(fs.existsSync(exe) ? { executablePath: exe } : {});
let fail = 0;
const check = (name, ok, got) => { console.log((ok ? 'PASS ' : 'FAIL ') + name + (ok ? '' : ' -> ' + JSON.stringify(got))); if (!ok) fail++; };
const open = async (path) => {
  const pg = await b.newPage({ viewport: { width: 390, height: 844 } });
  const errs = []; pg.on('pageerror', e => errs.push(e.message));
  await pg.goto(root + path, { waitUntil: 'networkidle' }); await pg.waitForTimeout(1500);
  return { pg, errs };
};
{
  const { pg, errs } = await open('index.html#/guide?ledger=AVAILABLE&county=Leon');
  const r = await pg.evaluate(() => ({ last: window.__tdwGuideLast, title: document.querySelector('.bg-title')?.textContent.trim(), hash: location.hash, doc: document.title,
    verifiedWithSource: [...document.querySelectorAll('.bg-q[data-bg-verified]')].every(d => !!d.querySelector('.bg-meta a[href^="https://"]')),
    openHasWhere: [...document.querySelectorAll('.bg-q:not([data-bg-verified])')].every(d => !!d.querySelector('.bg-where')) }));
  check('guideLeonTitle', r.title === 'Leon County', r.title);
  check('guideLeonCounts', r.last && r.last.total >= 4 && r.last.verified >= 1, r.last);
  check('guideVerifiedHaveSource', r.verifiedWithSource, r);
  check('guideOpenHaveWhereToLook', r.openHasWhere, r);
  check('guideTitleAndHash', /^Buyer's Guide/.test(r.doc) && r.hash.startsWith('#/guide'), r);
  await pg.click('[data-bg-ledger="AUCTIONS"]'); await pg.waitForTimeout(800);
  check('guideLedgerSwitchUpdatesHash', await pg.evaluate(() => location.hash.includes('ledger=AUCTIONS')), null);
  await pg.fill('[data-bg-search]', 'redeem'); await pg.waitForTimeout(200);
  check('guideSearchFilters', await pg.evaluate(() => [...document.querySelectorAll('.bg-q')].filter(d => !d.hidden).length >= 1 && [...document.querySelectorAll('.bg-q')].some(d => d.hidden)), null);
  check('guideNoErrors', errs.length === 0, errs);
  await pg.close();
}
{
  const { pg, errs } = await open('co.html#/guide?ledger=LIENS_CERTIFICATES');
  const r = await pg.evaluate(() => ({ eyebrow: document.querySelector('.bg-eyebrow')?.textContent, florida: /Florida/.test(document.querySelector('.bg-page')?.textContent || '') }));
  check('guideOtherStateNamesItself', /Colorado/.test(r.eyebrow) && !r.florida, r);
  check('guideOtherStateNoErrors', errs.length === 0, errs);
  await pg.close();
}
{
  const { pg } = await open('index.html#/lands');
  const has = await pg.evaluate(() => [...document.querySelectorAll('#accountGoto [data-goto="guide"]')].length === 1);
  check('guideInAccountMenu', has, has);
  await pg.close();
}
await b.close();
process.exit(fail ? 1 : 0);
