// Buyer's Guide screenshots (front-end sprint 2026-11-12): desktop 1368x777 and phone
// 390x844, light and dark (the app's own theme, localStorage.tdw_theme). Usage:
//   BASE_URL=http://localhost:8951/index.html OUT=<dir> TAG=after node tests/screenshots/guide-shots.mjs
import { chromium } from 'playwright';
import fs from 'fs';
import path from 'path';
const BASE = process.env.BASE_URL || 'http://localhost:8934/index.html';
const OUT = process.env.OUT || 'screenshots';
const TAG = process.env.TAG || 'shot';
fs.mkdirSync(OUT, { recursive: true });
const exe = '/opt/pw-browsers/chromium';
const b = await chromium.launch(fs.existsSync(exe) ? { executablePath: exe } : {});
const views = { desktop: { width: 1368, height: 777 }, phone: { width: 390, height: 844 } };
const routes = { statewide: '#/guide?ledger=AVAILABLE', leon: '#/guide?ledger=AVAILABLE&county=Leon', auctions: '#/guide?ledger=AUCTIONS' };
for (const [vn, vp] of Object.entries(views)) {
  for (const theme of ['light', 'dark']) {
    const ctx = await b.newContext({ viewport: vp });
    await ctx.addInitScript(t => { try { localStorage.setItem('tdw_theme', t); } catch { /* */ } }, theme);
    const pg = await ctx.newPage();
    for (const [rn, hash] of Object.entries(routes)) {
      await pg.goto(BASE + '?look=merged' + hash, { waitUntil: 'networkidle' });
      await pg.waitForTimeout(1500);
      await pg.screenshot({ path: path.join(OUT, `${TAG}-${vn}-${theme}-${rn}.png`) });
      await pg.screenshot({ path: path.join(OUT, `${TAG}-${vn}-${theme}-${rn}-full.png`), fullPage: true });
    }
    await ctx.close();
  }
}
await b.close();
console.log('saved to ' + OUT);
