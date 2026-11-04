// Merged is the default look (owner, 2026-11-04: "Merge by default").
// The fixture config (tests/config.js) carries no defaultLook, so the rest of
// the suite keeps Classic; here config.js is served with the production
// setting appended, the way the live site has it.
import { chromium } from 'playwright';
import fs from 'fs';
const BASE = process.env.BASE_URL || 'http://localhost:8934/index.html';
const root = BASE.replace(/[^/]*$/, '');
const exe = '/opt/pw-browsers/chromium';
const b = await chromium.launch(fs.existsSync(exe) ? { executablePath: exe } : {});
let fail = 0;
const check = (name, ok, got) => { console.log((ok ? 'PASS ' : 'FAIL ') + name + (ok ? '' : ' -> ' + JSON.stringify(got))); if (!ok) fail++; };
const errors = [];

async function open(path, { stored, defaultLook = 'merged' } = {}) {
  const ctx = await b.newContext({ viewport: { width: 390, height: 844 } });
  await ctx.route('**/config.js', async route => {
    const res = await route.fetch();
    const body = (await res.text()) + (defaultLook ? `\nwindow.TDW_CONFIG.defaultLook = ${JSON.stringify(defaultLook)};\n` : '');
    await route.fulfill({ response: res, body });
  });
  if (stored) await ctx.addInitScript(v => { try { localStorage.setItem('tdw_experience_v1', v); } catch {} }, stored);
  const pg = await ctx.newPage();
  pg.on('pageerror', e => errors.push(path + ': ' + e.message));
  await pg.goto(root + path, { waitUntil: 'networkidle' });
  await pg.waitForTimeout(1500);
  return pg;
}
// html[data-look] is the chosen look; data-experience is the engine Merged
// uses for the ledger on screen (tactile for Auctions / Liens, terrain for
// Available), and data-experience-ready is set once that engine has drawn.
const look = async pg => {
  await pg.waitForFunction(() => document.documentElement.dataset.look !== 'merged' || !!document.documentElement.dataset.experienceReady, null, { timeout: 8000 }).catch(() => {});
  return pg.evaluate(() => ({ experience: document.documentElement.dataset.look || null, engine: document.documentElement.dataset.experience || null, ready: document.documentElement.dataset.experienceReady || null }));
};

// 1. A first visit with no choice lands in Merged, and the Merged stage draws.
{
  const pg = await open('index.html#/auctions');
  const r = await look(pg);
  check('firstVisitIsMerged', r.experience === 'merged', r);
  check('mergedStageDrawn', !!r.ready, r);
  await pg.context().close();
}
// 2. A visitor who picked Classic in the Look menu keeps it.
{
  const pg = await open('index.html#/auctions', { stored: 'classic' });
  const r = await look(pg);
  check('storedClassicKept', r.experience === 'classic' && !r.ready, r);
  await pg.context().close();
}
// 3. A ?look=classic link still wins over the default.
{
  const pg = await open('index.html?look=classic#/lands');
  const r = await look(pg);
  check('lookLinkWins', r.experience === 'classic', r);
  await pg.context().close();
}
// 4. An unknown default falls back to Classic (never a blank stage).
{
  const pg = await open('index.html#/auctions', { defaultLook: 'nonsense' });
  const r = await look(pg);
  check('unknownDefaultIsClassic', r.experience === 'classic', r);
  await pg.context().close();
}
// 5. Every ledger draws in Merged by default on other states too.
for (const path of ['tx.html#/auctions', 'index.html#/lands', 'index.html#/certificates']) {
  const pg = await open(path);
  const r = await look(pg);
  check('mergedDefault_' + path.replace(/[^a-z]/gi, ''), r.experience === 'merged' && !!r.ready, r);
  await pg.context().close();
}
check('noPageErrors', errors.length === 0, errors);
await b.close();
console.log(fail ? `FAILED ${fail}` : 'PASS: all merged-default checks');
process.exit(fail ? 1 : 0);
