// Office replies, second round (2026-11-05): the Volusia County Clerk allows
// links only to the entry pages its own links go to (app02.clerk.org/or_td/ or
// /or_m/) - never a deep link (data/office_replies.csv). A Volusia Lands
// Available row whose list / document URLs are deep links on app02.clerk.org
// must render no such deep link anywhere: each becomes the entry page.
import { chromium } from 'playwright';
import fs from 'fs';
const BASE = process.env.BASE_URL || 'http://localhost:8934/index.html';
const exe = '/opt/pw-browsers/chromium';
const b = await chromium.launch(fs.existsSync(exe) ? { executablePath: exe } : {});
let fail = 0;
const check = (name, ok, got) => { console.log((ok ? 'PASS ' : 'FAIL ') + name + (ok ? '' : ' -> ' + JSON.stringify(got))); if (!ok) fail++; };
const errs = [];

const ROW = {
  id: '9a1c0f00-5e1d-4c6b-9e0a-0000000c1e2a', source: 'laft', county: 'Volusia', case_no: 'VOL-TEST-1', parcel: '123456789012',
  address: 'Parcel 123456789012', bid: 1500, status: 'active', state: 'FL', ledger_type: 'buy',
  harvester_source: 'fl_laft_pdfs', source_id: 'fl_laft_pdfs', last_seen_at: new Date().toISOString(),
  publication_status: 'APPROVED_GRANDFATHERED', inventory_status: 'available_otc',
  list_url: 'https://app02.clerk.org/cm_rpt/?id=lat',
  document_url: 'https://app02.clerk.org/cm_rpt/lands/LandsAvailableForTaxes.pdf',
  otc_provenance: { harvester: 'fl_laft_pdfs', source_id: 'fl_laft_pdfs', list_url: 'https://app02.clerk.org/cm_rpt/?id=lat',
    document_url: 'https://app02.clerk.org/cm_rpt/lands/LandsAvailableForTaxes.pdf' }
};

const ctx = await b.newContext({ viewport: { width: 1400, height: 900 } });
const pg = await ctx.newPage();
pg.on('pageerror', e => errs.push(e.message));
await pg.addInitScript(rs => { window.__stubExtraRows = rs; }, [ROW]);
await pg.goto(BASE + '?fields=all#/lands/' + ROW.id, { waitUntil: 'networkidle' });
await pg.waitForSelector('#detailPanel [data-section], #detailModalInner [data-section]', { timeout: 10000 }).catch(() => {});
await pg.evaluate(() => document.querySelectorAll('details').forEach(d => { d.open = true; }));
await pg.waitForTimeout(500);
const hrefs = await pg.evaluate(() => [...document.querySelectorAll('a[href]')].map(a => a.getAttribute('href')).filter(h => /app02\.clerk\.org/i.test(h)));
check('volusiaHasClerkLink', hrefs.length > 0, hrefs);
check('volusiaNoDeepLink', hrefs.every(h => /^https:\/\/app02\.clerk\.org\/or_(td|m)\/?$/i.test(h)), hrefs);
// A link added later (any surface) is rewritten too.
const late = await pg.evaluate(async () => {
  const a = document.createElement('a');
  a.href = 'https://app02.clerk.org/or_td/Search.aspx?case=1';
  document.body.appendChild(a);
  await new Promise(r => setTimeout(r, 50));
  const out = a.getAttribute('href');
  const e = document.createElement('a');
  e.href = 'https://app02.clerk.org/or_m/';
  document.body.appendChild(e);
  await new Promise(r => setTimeout(r, 50));
  return [out, e.getAttribute('href')];
});
check('lateDeepLinkRewritten', late[0] === 'https://app02.clerk.org/or_td/', late);
check('entryPageKept', late[1] === 'https://app02.clerk.org/or_m/', late);
check('noPageErrors', errs.length === 0, errs);
await b.close();
console.log(fail ? `${fail} FAILED` : 'ALL PASS');
process.exit(fail ? 1 : 0);
