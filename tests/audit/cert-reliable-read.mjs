// Owner, 2026-11-17: "Remove lien and certificates if it's not a reliable read
// and let's focus on the other two ledgers until it grows."
//  - a certificate its own source has not confirmed in 7 days (or ever - the
//    LienHub rows) is not shown to a customer;
//  - one read recently (Sarasota, the Colorado lists) is;
//  - an administrator still sees the unconfirmed one.
import { chromium } from 'playwright';
import fs from 'fs';
const BASE = (process.env.BASE_URL || 'http://localhost:8934/index.html').replace(/\/$/, '/index.html');
const exe = '/opt/pw-browsers/chromium';
const b = await chromium.launch(fs.existsSync(exe) ? { executablePath: exe } : {});
let fail = 0;
const check = (name, ok, got) => { console.log((ok ? 'PASS ' : 'FAIL ') + name + (ok ? '' : ' -> ' + JSON.stringify(got))); if (!ok) fail++; };
const errs = [];
const now = new Date().toISOString();
const cert = (id, seen) => ({ id, source: 'certificate', state: 'FL', county: 'Alachua', case_no: id.toUpperCase(), certificate_no: id.toUpperCase(), tax_year: '2025', parcel: id + '-P', bid: 50, interest_rate: 18, status: 'active', ledger_type: 'lien', issued_date: '2026-06-01', url_auction: 'https://lienhub.com/county/alachua/countyheld/certificates', url_auction_kind: 'county', last_seen_at: seen, updated_at: now, lien_level: 'unscreened', publication_status: 'APPROVED_GRANDFATHERED' });
const ROWS = [cert('certnever', null), cert('certfresh', now), cert('certold', new Date(Date.now() - 20 * 864e5).toISOString())];
async function seen(extra) {
  const ctx = await b.newContext({ viewport: { width: 1400, height: 900 }, serviceWorkers: 'block' });
  const pg = await ctx.newPage();
  pg.on('pageerror', e => errs.push(e.message));
  await pg.addInitScript(rs => { window.__stubExtraRows = rs; }, ROWS);
  await pg.goto(BASE + '?unconfirmed=1' + extra + '#/certificates', { waitUntil: 'networkidle' });
  await pg.waitForTimeout(1500);
  const r = await pg.evaluate(ids => Object.fromEntries(ids.map(id => [id, !!window.__tdwRecordSourceLink(id)])), ROWS.map(x => x.id));
  await ctx.close();
  return r;
}
const cust = await seen('');
check('customerSeesFreshCertificate', cust.certfresh === true, cust);
check('customerDoesNotSeeNeverConfirmed', cust.certnever === false, cust);
check('customerDoesNotSeeStale', cust.certold === false, cust);
const adm = await seen('&profile=admin');
check('adminStillSeesUnconfirmed', adm.certnever === true && adm.certold === true && adm.certfresh === true, adm);
check('noPageErrors', errs.length === 0, errs);
await b.close();
console.log(fail ? `FAIL: ${fail} check(s)` : 'ALL PASS');
process.exit(fail ? 1 : 0);
