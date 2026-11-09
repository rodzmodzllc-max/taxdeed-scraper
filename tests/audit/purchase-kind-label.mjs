// TN-2 (2026-11-09): an online_purchase page is "Buy online" only when it is a
// checkout. The Shelby Land Bank's per-property page carries the portal's own
// 'Apply For this Property' action (a portal account is needed; the source's
// terms are an offer, OFFER_NEGOTIATED), so it reads "Apply online". Rows are
// synthetic (FIXTURE identifiers, no real parcel or address).
import { chromium } from 'playwright';
import fs from 'fs';
const BASE = process.env.BASE_URL || 'http://localhost:8934/index.html';
const exe = '/opt/pw-browsers/chromium';
const b = await chromium.launch(fs.existsSync(exe) ? { executablePath: exe } : {});
let fail = 0;
const check = (name, ok, got) => { console.log((ok ? 'PASS ' : 'FAIL ') + name + (ok ? '' : ' -> ' + JSON.stringify(got))); if (!ok) fail++; };
const errs = [];

const tnRow = (extraProv) => ({
  id: '00000000-0000-4000-8000-00000000f001', source: 'laft', county: 'Shelby', case_no: 'FIXTURE0000001', parcel: 'FIXTURE0000001',
  state: 'TN', ledger_type: 'buy', status: 'active', harvester_source: 'tn_shelby_landbank', source_id: 'tn_shelby_landbank',
  purchase_url: 'https://public-sctn.epropertyplus.com/property/FIXTURE0000001', purchase_url_kind: 'online_purchase',
  purchase_path_type: 'direct_property_url', purchase_path_scope: 'property', publication_status: 'APPROVED',
  otc_provenance: Object.assign({ adapter: 'epropertyplus', source_id: 'tn_shelby_landbank', acquisition: { mode: 'online', channels: ['online'] } }, extraProv || {})
});
// A source with no offer terms and no application wording stays a checkout.
const plainRow = {
  id: '00000000-0000-4000-8000-00000000f002', source: 'laft', county: 'Alachua', case_no: 'FIXTURE-2', parcel: 'FIXTURE-2',
  state: 'FL', ledger_type: 'buy', status: 'active', harvester_source: 'fixture_checkout', source_id: 'fixture_checkout',
  purchase_url: 'https://example.gov/buy/FIXTURE-2', purchase_url_kind: 'online_purchase', otc_provenance: {}
};

const ctx = await b.newContext({ viewport: { width: 1400, height: 900 } });
const pg = await ctx.newPage();
pg.on('pageerror', e => errs.push(e.message));
await pg.goto(BASE.replace(/index\.html$/, 'tn.html'), { waitUntil: 'networkidle' });
await pg.waitForFunction(() => typeof window.__tdwPurchaseKindLabel === 'function', null, { timeout: 15000 });
await pg.waitForTimeout(800);   // available-terms.json

const r = await pg.evaluate(([prod, harvested, plain]) => ({
  prod: window.__tdwPurchaseKindLabel(prod),
  harvested: window.__tdwPurchaseKindLabel(harvested),
  plain: window.__tdwPurchaseKindLabel(plain),
  offer: window.__tdwPurchaseKindLabel(Object.assign({}, plain, { purchase_url_kind: 'offer_form' })),
  block: window.__tdwAcquireBlockHtml ? window.__tdwAcquireBlockHtml(harvested) : ''
}), [tnRow(), tnRow({ purchase_action_label: 'Apply For this Property', purchase_account_required: true }), plainRow]);

check('shelbyOfferTermsReadApplyOnline', r.prod === 'Apply online (an offer, not a checkout)', r.prod);
check('shelbyHarvestedRowNamesTheAccount', r.harvested === 'Apply online (an offer, not a checkout; portal account required)', r.harvested);
check('checkoutWithoutOfferTermsStaysBuyOnline', r.plain === 'Buy online', r.plain);
check('otherKindsUnchanged', r.offer === 'Offer form', r.offer);
check('shelbyAcquireBlockNeverSaysBuyOnline', !/Buy online/.test(r.block), r.block.slice(0, 200));
check('noPageErrors', errs.length === 0, errs);
await b.close();
process.exit(fail ? 1 : 0);
