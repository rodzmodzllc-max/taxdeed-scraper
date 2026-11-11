// A lien certificate its own list has not confirmed in 7 days (or ever) is
// withheld from customers like an unconfirmed Available record (2026-11-11:
// LienHub has answered 403 to every read, so 1,518 Florida certificates were
// never read back). Display only; the ledger says why it is short.
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
let pg = await open('&unconfirmedliens=1', '#/certificates');
const on = await pg.evaluate(() => {
  const u = window.__tdwUnconfirmed();
  const why = document.querySelector('[data-unconfirmed-withheld]');
  const empty = document.querySelector('#main .unconfirmed-empty');
  return { cert: (u.bySource.certificate || {}).total || 0, laft: (u.bySource.laft || {}).total || 0,
    shown: !!document.querySelector('[data-pid="p4"], [data-id="p4"]'),
    why: why ? why.textContent : null, empty: empty ? empty.textContent : null,
    county: u.countyText('Alachua', 'certificate') };
});
check('lienWithheldCounted', on.cert === 1 && on.laft === 0, on);
check('lienNotShown', !on.shown, on);
check('ledgerSaysWhy', !!on.why && /1 lien certificate is withheld because its source could not be read to confirm it is still offered\. This is not a statement that there are no certificates\./.test(on.why), on.why);
check('emptyStateSaysWhy', !!on.empty && /lien certificate/.test(on.empty) && !/Available record/.test(on.empty), on.empty);
check('countyText', /^1 lien certificate in Alachua withheld: .* still offered\. This is not a statement that Alachua has no certificates\.$/.test(on.county), on.county);
await pg.close();
pg = await open('', '#/certificates');
const off = await pg.evaluate(() => ({ cert: ((window.__tdwUnconfirmed().bySource || {}).certificate || {}).total || 0,
  why: !!document.querySelector('[data-unconfirmed-withheld]') }));
check('gateOffShowsRow', off.cert === 0 && !off.why, off);
await pg.close();
check('noPageErrors', errors.length === 0, errors);
await b.close();
process.exit(fail ? 1 : 0);
