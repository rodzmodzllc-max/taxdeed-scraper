// Before / after screenshots for the TAXACQ brand pass (docs/review/brand/). Usage:
//   BASE_URL=http://localhost:8491/index.html OUT=docs/review/brand PREFIX=after node tests/screenshots/brand-shots.mjs
import { chromium } from 'playwright';
import fs from 'fs';
const BASE = process.env.BASE_URL || 'http://localhost:8491/index.html';
const OUT = process.env.OUT || 'docs/review/brand';
const PREFIX = process.env.PREFIX || 'after';
const ONLY = process.env.ONLY ? new RegExp(process.env.ONLY) : null;
const root = BASE.replace(/[^/]*$/, '');
const exe = '/opt/pw-browsers/chromium';
fs.mkdirSync(OUT, { recursive: true });
const b = await chromium.launch(fs.existsSync(exe) ? { executablePath: exe } : {});
const PHONE = { width: 390, height: 844 };
const DESK = { width: 1440, height: 900 };
const errors = [];

async function shot(name, path, vp, act) {
  if (ONLY && !ONLY.test(name)) return;
  const pg = await b.newPage({ viewport: vp, deviceScaleFactor: 1 });
  pg.on('pageerror', e => errors.push(`${name}: ${e.message}`));
  await pg.goto(root + path, { waitUntil: 'networkidle' });
  await pg.waitForTimeout(1300);
  if (act) { await act(pg); await pg.waitForTimeout(800); }
  await pg.screenshot({ path: `${OUT}/${PREFIX}-${name}.png`, type: 'png' });
  await pg.close();
}
const openFirst = async pg => {
  await pg.evaluate(() => { const el = document.querySelector('#main [data-action="viewdetails"]'); if (el) el.click(); });
};

for (const [tag, vp] of [['phone', PHONE], ['desk', DESK]]) {
  await shot(`${tag}-signin`, 'index.html?authtest=1', vp);
  await shot(`${tag}-home`, 'index.html#/dashboard', vp);
  for (const [lg, slug] of [['available', 'lands'], ['auctions', 'auctions'], ['liens', 'certificates']]) {
    await shot(`${tag}-classic-${lg}`, `index.html?look=classic#/${slug}`, vp);
    await shot(`${tag}-merged-${lg}`, `index.html?look=merged#/${slug}`, vp);
  }
  await shot(`${tag}-property`, 'index.html?look=classic#/auctions', vp, openFirst);
  await shot(`${tag}-map`, 'index.html#/map', vp);
  await shot(`${tag}-guide`, 'index.html#/guide', vp);
}
await b.close();
if (errors.length) { console.log('PAGE ERRORS:\n' + errors.join('\n')); process.exit(1); }
console.log('done');
