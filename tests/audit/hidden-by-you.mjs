// Rows this account hid (the `hidden` table is private per user) are left out
// of every count, so the ledger and Home must say so (2026-11-07: the owner saw
// 177 FL Available rows, every other account 198, with nothing explaining it).
import { chromium } from 'playwright';
import fs from 'fs';
const BASE = process.env.BASE_URL || 'http://localhost:8934/index.html';
const root = BASE.replace(/[^/]*$/, '');
const exe = '/opt/pw-browsers/chromium';
const b = await chromium.launch(fs.existsSync(exe) ? { executablePath: exe } : {});
let fail = 0;
const check = (name, ok, got) => { console.log((ok ? 'PASS ' : 'FAIL ') + name + (ok ? '' : ' -> ' + JSON.stringify(got))); if (!ok) fail++; };
const errors = [];
const open = async (qs, hash) => {
  const pg = await b.newPage({ viewport: { width: 1280, height: 900 } });
  pg.on('pageerror', e => errors.push(e.message));
  await pg.goto(root + 'index.html?look=classic' + qs + hash, { waitUntil: 'networkidle' });
  await pg.waitForTimeout(1800);
  return pg;
};
let pg = await open('&hiddenrows=p3', '#/lands');
const line = await pg.evaluate(() => { const el = document.getElementById('ledgerHiddenByYou'); return el ? { text: el.textContent.replace(/\s+/g, ' ').trim(), ledger: el.dataset.hiddenLedger } : null; });
check('ledgerSaysHiddenByYou', !!line && /^1 hidden by you - not counted here\./.test(line.text) && line.ledger === 'laft', line);
await pg.click('#ledgerHiddenByYou [data-action="openhidden"]');
await pg.waitForTimeout(400);
check('viewOpensHiddenList', await pg.evaluate(() => !document.getElementById('hiddenModal').hidden && document.querySelectorAll('#hiddenListRows .hidden-row').length === 1), null);
await pg.close();
pg = await open('&hiddenrows=p3', '#/dashboard');
const home = await pg.evaluate(() => [...document.querySelectorAll('.home-ledger-hidden[data-hidden-ledger]')].map(e => [e.dataset.hiddenLedger, e.textContent.trim()]));
check('homeSaysHiddenByYou', home.length >= 1 && home.every(([k, t]) => k === 'laft' && t === '1 hidden by you'), home);
await pg.close();
pg = await open('', '#/lands');
check('noLineWithoutHiddenRows', await pg.evaluate(() => !document.getElementById('ledgerHiddenByYou') && !document.querySelector('[data-hidden-ledger]')), null);
await pg.close();
check('noPageErrors', errors.length === 0, errors);
await b.close();
process.exit(fail ? 1 : 0);
