// Screenshots for docs/review/ledger-bar/ (phone + desktop). Usage:
//   BASE_URL=http://localhost:8882/index.html OUT=docs/review/ledger-bar PREFIX=after node tests/screenshots/ledger-bar-shots.mjs
import { chromium } from 'playwright';
import fs from 'fs';
const BASE = process.env.BASE_URL || 'http://localhost:8882/index.html';
const OUT = process.env.OUT || 'docs/review/ledger-bar';
const PREFIX = process.env.PREFIX || 'after';
const root = BASE.replace(/[^/]*$/, '');
const exe = '/opt/pw-browsers/chromium';
fs.mkdirSync(OUT, { recursive: true });
const b = await chromium.launch(fs.existsSync(exe) ? { executablePath: exe } : {});
const shot = async (pg, name) => pg.screenshot({ path: `${OUT}/${PREFIX}-${name}.png`, type: 'png' });
async function open(path, vp) {
  const pg = await b.newPage({ viewport: vp, deviceScaleFactor: 1 });
  await pg.goto(root + path, { waitUntil: 'networkidle' });
  await pg.waitForTimeout(1200);
  return pg;
}
// Phone, deep in a long Available list.
{
  const pg = await open('mi.html?profile=admin&bigcounty=600#/lands', { width: 390, height: 844 });
  await pg.evaluate(() => window.scrollTo(0, 3000)); await pg.waitForTimeout(400);
  await shot(pg, 'phone-list-deep');
  // A property open.
  await pg.evaluate(() => window.scrollTo(0, 0)); await pg.waitForTimeout(200);
  await pg.evaluate(() => document.querySelector('#main [data-action="viewdetails"]').click());
  await pg.waitForTimeout(700);
  await shot(pg, 'phone-property-open');
  await pg.close();
}
// Phone, Merged look, scrolled to the end of the deck.
{
  const pg = await open('mi.html?profile=admin&bigcounty=600&look=merged#/lands', { width: 390, height: 844 });
  await pg.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight)); await pg.waitForTimeout(500);
  await shot(pg, 'phone-merged-end');
  await pg.close();
}
// Phone on the Map page, filtered to Auctions.
{
  const pg = await open('index.html#/lands', { width: 390, height: 844 });
  await pg.click('#navBottom .nav-bottom-item[data-page="map"]'); await pg.waitForTimeout(700);
  await pg.click('#mapLedgerPills [data-ledger="auction"]').catch(() => {}); await pg.waitForTimeout(400);
  await shot(pg, 'phone-map');
  await pg.close();
}
// Phone on Auctions (FL) at 360px.
{
  const pg = await open('index.html#/auctions', { width: 360, height: 780 });
  await pg.evaluate(() => window.scrollTo(0, 900)); await pg.waitForTimeout(300);
  await shot(pg, 'phone360-auctions');
  await pg.close();
}
// Phone, Texas (Redeemable Deeds).
{
  const pg = await open('tx.html#/certificates', { width: 390, height: 844 });
  await shot(pg, 'phone-tx');
  await pg.close();
}
// Desktop with a property modal opened from the Watchlist page.
{
  const pg = await open('index.html?bidlist=p1#/watchlist', { width: 1440, height: 900 });
  await pg.evaluate(() => document.querySelector('#pageWatchlist [data-action="viewdetails"]').click());
  await pg.waitForTimeout(700);
  await shot(pg, 'desktop-property-modal');
  await pg.close();
}
{
  const pg = await open('index.html#/lands', { width: 1280, height: 800 });
  await pg.evaluate(() => window.scrollTo(0, 1200)); await pg.waitForTimeout(300);
  await shot(pg, 'desktop1280-list');
  await pg.close();
}
await b.close();
console.log('shots written to ' + OUT);
