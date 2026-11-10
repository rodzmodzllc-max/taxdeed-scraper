// Property page screenshots (P6): one Available, one Auction, one Lien record in
// the Merged and Classic looks, desktop side panel (1440x900) and phone modal
// (390x844). The Merged pass also takes one long shot of the whole record.
// Usage: BASE_URL=http://localhost:9202/index.html OUT=<dir> PREFIX=after node tests/screenshots/property-page-shots.mjs
import { chromium } from 'playwright';
import fs from 'fs';
const BASE = process.env.BASE_URL || 'http://localhost:9202/index.html';
const OUT = process.env.OUT || 'docs/review/property-page';
const PREFIX = process.env.PREFIX || 'after';
fs.mkdirSync(OUT, { recursive: true });
const b = await chromium.launch();
const errs = [];
for (const [tag, vp] of [['desk', { width: 1440, height: 900 }], ['phone', { width: 390, height: 844 }]]) {
  for (const look of ['merged', 'classic']) {
    for (const [lg, h] of [['available', '#/lands/p3'], ['auction', '#/auctions/p5'], ['lien', '#/certificates/p4']]) {
      const pg = await b.newPage({ viewport: vp });
      pg.on('pageerror', e => errs.push(`${tag} ${look} ${lg}: ${e.message}`));
      await pg.goto(BASE + '?look=' + look + h, { waitUntil: 'networkidle' });
      await pg.waitForTimeout(1200);
      await pg.screenshot({ path: `${OUT}/${PREFIX}-${tag}-${look}-${lg}.png` });
      if (look === 'merged') {
        const sel = await pg.evaluate(() => (document.getElementById('detailModal') && !document.getElementById('detailModal').hidden) ? '#detailModalInner' : '#detailPanel');
        await pg.evaluate(s => document.querySelectorAll(s + ' details').forEach(d => { d.open = true; }), sel);
        const H = await pg.evaluate(s => document.querySelector(s).scrollHeight, sel);
        await pg.setViewportSize({ width: vp.width, height: Math.min(H + 200, 12000) });
        await pg.waitForTimeout(400);
        await pg.screenshot({ path: `${OUT}/${PREFIX}-${tag}-long-${lg}.png` });
      }
      await pg.close();
    }
  }
}
await b.close();
if (errs.length) { console.log('PAGE ERRORS:\n' + errs.join('\n')); process.exit(1); }
console.log('done');
