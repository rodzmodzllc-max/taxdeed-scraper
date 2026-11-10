// Final screenshots of the UI overhaul (Merged look): every primary page,
// one property per ledger, the Buyer's Guide, a county page and the
// Watchlist, at 1440x900 and 390x844. OUT_DIR names the folder.
import { chromium } from 'playwright';
import fs from 'fs';
const BASE = process.env.BASE_URL || 'http://localhost:9301/index.html';
const OUT = process.env.OUT_DIR || 'docs/review/ui-overhaul';
fs.mkdirSync(OUT, { recursive: true });
const pages = [
  ['home', '#/dashboard'], ['available', '#/lands'], ['auctions', '#/auctions'], ['liens', '#/certificates'],
  ['map', '#/map'], ['property-available', '#/lands/p3'], ['property-auction', '#/auctions/p5'],
  ['property-lien', '#/certificates/p4'], ['buyers-guide', '#/guide'], ['county', '#/county/Alachua'], ['watchlist', '#/watchlist']
];
const b = await chromium.launch();
for (const vp of [{ width: 1440, height: 900 }, { width: 390, height: 844 }]) {
  for (const [name, hash] of pages) {
    const ctx = await b.newContext({ viewport: vp, reducedMotion: 'reduce' });
    const pg = await ctx.newPage();
    await pg.goto(BASE + '?look=merged' + hash, { waitUntil: 'networkidle' });
    await pg.waitForTimeout(1800);
    await pg.screenshot({ path: `${OUT}/${name}-${vp.width}.png` });
    await ctx.close();
  }
}
await b.close();
console.log('wrote', OUT);
