// Audit 2026-10-28, theme amounts-labels (F1 F3 F5 F14 F15 F16 F32 F33 F54
// F56 F81 F82 F104): amount / value / label helpers in app.js. F79 (GovEase /
// MVBA "Minimum bid") is NOT fixed here: harvesters/texas_vendors.py reads
// "Minimum Bid" / "Face Value" / "Starting Bid" into one min_bid without
// recording which column, so a source-id rule would call a Face Value a
// minimum bid - the harvester must record the column first. Rows below are
// production rows (read-only, owner names never selected), injected through
// the fixture stub's window.__stubExtraRows; p3 is the fixture's own row.
import { chromium } from 'playwright';
import fs from 'fs';
const BASE = process.env.BASE_URL || 'http://localhost:8934/index.html';
const exe = '/opt/pw-browsers/chromium';
const b = await chromium.launch(fs.existsSync(exe) ? { executablePath: exe } : {});
let fail = 0;
const check = (name, ok, got) => { console.log((ok ? 'PASS ' : 'FAIL ') + name + (ok ? '' : ' -> ' + JSON.stringify(got))); if (!ok) fail++; };
const errs = [];
const pageFor = st => BASE.replace(/index\.html$/, st === 'FL' ? 'index.html' : st.toLowerCase() + '.html');
const slug = s => s === 'laft' ? 'lands' : s === 'certificate' ? 'certificates' : 'auctions';

const ROW = {
  taylor: { id: '7d334e14-40d7-43bf-9bb0-8ca51b941283', source: 'laft', county: 'Taylor', case_no: '25-049', parcel: 'R05278-000', address: 'Parcel R05278-000', bid: 1043.22, assessed: null, market: null, status: 'active', lien_level: 'unscreened', state: 'FL', ledger_type: 'buy', harvester_source: 'fl_laft_html', source_id: 'fl_laft_html', purchase_amount: 1043.22, purchase_amount_kind: 'ORIGINAL_OPENING_BID', last_seen_at: '2026-11-02T11:39:36+00:00', publication_status: 'APPROVED_GRANDFATHERED', purchase_path_type: 'quoted_amount', purchase_path_scope: 'source', purchase_path_observed_on: '2026-09-30', inventory_status: 'available_otc', list_url: 'https://www.taylorclerk.com/lands-available', purchase_url: null, otc_provenance: { harvester: 'fl_laft_html', source_id: 'fl_laft_html', inventory_type: 'LANDS_AVAILABLE', purchase_amount: 'ORIGINAL_OPENING_BID', purchase_path_mode: 'offline', purchase_evidence_url: 'https://www.taylorclerk.com/lands-available', purchase_evidence_type: 'quoted_amount', purchase_evidence_title: 'List of Lands Available', purchase_instructions: 'The amounts listed are no longer the opening bid. You must contact the Clerk\'s Office to calculate the new amount.', purchase_path_observed_on: '2026-09-30', acquisition: { mode: 'contact', channels: ['phone'], phone: '(850) 838-3506', observed_on: '2026-09-30', steps: ['Contact the Clerk\'s Office to calculate the current amount (the amounts listed are no longer the opening bid)'] } } },
  coCert: { id: 'fe19236b-29fb-49d0-895b-760fd0d84e35', source: 'certificate', county: 'Douglas', case_no: '2019-03915', parcel: '223106202005', bid: 47.43, assessed: null, market: 431, status: 'active', state: 'CO', ledger_type: 'lien', harvester_source: 'co_douglas_county_held_liens', source_id: 'co_douglas_county_held_liens', certificate_no: '2019-03915', tax_year: '2018', issued_date: '2019-11-07', interest_rate: 10, purchase_amount: 47.43, purchase_amount_kind: 'PUBLISHED_AMOUNT_KIND_UNSPECIFIED', last_seen_at: '2026-11-02T12:21:54+00:00', publication_status: 'APPROVED', purchase_path_type: 'application_download', purchase_path_scope: 'source', otc_provenance: { amount: "attribute 'lien_balance' = PUBLISHED_AMOUNT_KIND_UNSPECIFIED", adapter: 'arcgis', source_id: 'co_douglas_county_held_liens' } },
  saguache: { id: '1410c3ef-ef63-4934-97ca-98aef2a808ec', source: 'auction', county: 'Saguache', case_no: 'R001141', parcel: 'R001141', address: null, bid: 47.46, assessed: null, market: null, status: 'active', sale_date: '2026-12-10', state: 'CO', ledger_type: 'auctions', harvester_source: 'co_saguache_tax_sale', source_id: 'co_saguache_tax_sale', acreage: 160, purchase_amount: 47.46, purchase_amount_kind: 'PUBLISHED_AMOUNT_KIND_UNSPECIFIED', last_seen_at: '2026-11-02T12:21:54+00:00', publication_status: 'APPROVED', otc_provenance: { amount: "attribute 'Total_Due' = PUBLISHED_AMOUNT_KIND_UNSPECIFIED", adapter: 'arcgis', source_id: 'co_saguache_tax_sale' } },
  saguacheValued: null, // filled below: the same row with a county value, so the "no ratio" rule is tested with a value on file
  ok: { id: '160e566e-d1b2-464c-8b01-f74b3351c220', source: 'laft', county: 'Oklahoma', case_no: '1640-09-637-2000', parcel: '1640-09-637-2000', address: '1234 NW 10TH ST', bid: 320, assessed: null, market: null, status: 'active', state: 'OK', ledger_type: 'buy', harvester_source: 'ok_oklahoma_county_owned', source_id: 'ok_oklahoma_county_owned', land_use: 'Undeveloped', acreage: 0.0037, legal_desc: 'LOT 1', purchase_amount: 320, purchase_amount_kind: 'PUBLISHED_AMOUNT_KIND_UNSPECIFIED', last_seen_at: '2026-11-02T12:43:10+00:00', publication_status: 'APPROVED', purchase_path_type: 'application_download', purchase_path_scope: 'source', purchase_path_observed_on: '2026-11-02', purchase_url: 'https://www.oklahomacounty.org/DocumentCenter/View/1/Bid-Form', purchase_url_kind: 'bid_form', inventory_status: 'available_otc', otc_provenance: { amount: "column 'Suggested Initial Bid Amount' = PUBLISHED_AMOUNT_KIND_UNSPECIFIED", adapter: 'tabular', source_id: 'ok_oklahoma_county_owned', acquisition: { mode: 'application', channels: ['application_download'], application_url: 'https://www.oklahomacounty.org/DocumentCenter/View/1/Bid-Form', observed_on: '2026-11-02' } } },
  la: { id: '01e67ce0-38eb-4421-bb28-6422c4fe13d9', source: 'laft', county: 'East Baton Rouge', case_no: '002-2060-4', parcel: '002-2060-4', address: '1 TEST ST', bid: 0, assessed: 2039, market: 0, land_value: 370, status: 'active', state: 'LA', ledger_type: 'buy', harvester_source: 'la_ebr_adjudicated', source_id: 'la_ebr_adjudicated', tax_year: '2017', value_year: null, lot_sqft: 4449, purchase_amount: null, purchase_amount_kind: 'NOT_PUBLISHED', last_seen_at: '2026-11-02T11:41:33+00:00', list_as_of: '2026-05-06', publication_status: 'APPROVED', inventory_type: 'ADJUDICATED_PROPERTY', purchase_path_type: 'county_instructions', purchase_path_scope: 'source', otc_provenance: { amount: 'NOT_PUBLISHED: the dataset carries no price', adapter: 'louisiana', source_id: 'la_ebr_adjudicated', market: 'FAIR MARKET VALUE column (tax roll)' } },
  laValued: null, // filled below: a closed LA row with a real value, old tax-sale year, roll year 2025
  mi: { id: '695d456d-8f96-4431-a801-ba6563e4d221', source: 'auction', county: 'St. Clair', case_no: '30-550-0120-000', parcel: '30-550-0120-000', address: '100 MAIN ST', bid: 100, min_bid: 100, assessed: 29100, market: null, status: 'active', sale_date: '2026-12-15', state: 'MI', ledger_type: 'auctions', harvester_source: 'mi_tax_sale_info_auction', source_id: 'mi_tax_sale_info_auction', purchase_amount: null, purchase_amount_kind: null, last_seen_at: '2026-10-30T10:27:23+00:00', publication_status: 'APPROVED', otc_provenance: { amount: "column 'Minimum Bid' as published", adapter: 'tax_sale_info', source_id: 'mi_tax_sale_info_auction', lot_number: '120' } },
  tn: { id: '4c2e11cd-e7cc-45d2-83f4-4d0642bcd03d', source: 'laft', county: 'Shelby', case_no: '03510000000270', parcel: '03510000000270', address: '0 RAYBURN', bid: 1000, assessed: 3000, market: null, status: 'active', state: 'TN', ledger_type: 'buy', harvester_source: 'tn_shelby_landbank', source_id: 'tn_shelby_landbank', land_use: 'Residential Vacant', tax_year: '2024', url_auction: 'https://public-sctn.epropertyplus.com/landmgmtpub/app/base/landing', purchase_url: 'https://public-sctn.epropertyplus.com/property/03510000000270', purchase_url_kind: 'online_purchase', purchase_amount: 1000, purchase_amount_kind: 'PUBLISHED_AMOUNT_KIND_UNSPECIFIED', last_seen_at: '2026-11-02T12:46:59+00:00', publication_status: 'APPROVED', inventory_status: 'available_otc', inventory_status_raw: 'FOR SALE', purchase_path_type: 'direct_property_url', purchase_path_scope: 'property', purchase_path_observed_on: '2026-10-25', otc_provenance: { amount: "field 'askingPrice' (Asking Price) = PUBLISHED_AMOUNT_KIND_UNSPECIFIED", adapter: 'epropertyplus', source_id: 'tn_shelby_landbank', acquisition: { mode: 'online', channels: ['online'], observed_on: '2026-10-25' }, purchase_path_observed_on: '2026-10-25' } }
};
ROW.saguacheValued = Object.assign({}, ROW.saguache, { id: '1410c3ef-0000-4934-97ca-98aef2a808ec', case_no: 'R001142', assessed: 9000 });
ROW.laValued = Object.assign({}, ROW.la, { id: '01e67ce0-0000-4421-bb28-6422c4fe13d9', case_no: '002-2060-5', market: 5000, value_year: 2025, tax_year: '2017' });

async function open(row, q = '?fields=all', extra) {
  const ctx = await b.newContext({ viewport: { width: 1400, height: 900 } });
  const pg = await ctx.newPage();
  pg.on('pageerror', e => errs.push(row.id + ': ' + e.message));
  await pg.addInitScript(rs => { window.__stubExtraRows = rs; }, [row].concat(extra || []));
  await pg.goto(pageFor(row.state) + q + '#/' + slug(row.source) + '/' + row.id, { waitUntil: 'networkidle' });
  await pg.waitForSelector('#detailPanel [data-section], #detailModalInner [data-section]', { timeout: 10000 }).catch(() => {});
  await pg.waitForTimeout(500);
  return pg;
}
// The page's own text with every <details> opened (innerText skips closed ones).
const pageText = pg => pg.evaluate(() => { document.querySelectorAll('details').forEach(d => { d.open = true; }); const el = document.getElementById('detailPanel'); return el ? el.innerText : ''; });
const cardText = (pg, id) => pg.evaluate(id => { const el = document.querySelector(`.prop-card[data-pid="${id}"]`); if (!el) return ''; el.querySelectorAll('details').forEach(d => { d.open = true; }); return el.innerText; }, id);
const q = (pg, sel) => pg.evaluate(s => { const el = document.querySelector(s); return el ? el.textContent.replace(/\s+/g, ' ').trim() : null; }, sel);
// The Merged look's card text for one injected row: the value line must name
// the source's assessed label only, never Florida's "just value".
async function mergedHasNoJustValue(row) {
  const ctx = await b.newContext({ viewport: { width: 1400, height: 900 } });
  const pg = await ctx.newPage();
  pg.on('pageerror', e => errs.push('merged ' + row.id + ': ' + e.message));
  await pg.addInitScript(rs => { window.__stubExtraRows = rs; }, [row]);
  await pg.goto(pageFor(row.state) + '?look=merged#/' + slug(row.source), { waitUntil: 'networkidle' });
  await pg.waitForSelector('html[data-experience-ready="merged"]', { timeout: 15000 }).catch(() => {});
  await pg.waitForTimeout(800);
  const txt = await pg.evaluate(() => { document.querySelectorAll('#xpStage details').forEach(d => { d.open = true; }); const el = document.getElementById('xpStage'); return el ? el.innerText : ''; });
  await ctx.close();
  const ok = !/just value/i.test(txt) && /no market value on file/i.test(txt);
  if (!ok) console.log('   merged text:', JSON.stringify(txt.slice(0, 400)));
  return ok;
}
const statVal = (pg, label) => pg.evaluate(l => { const st = Array.from(document.querySelectorAll('#detailPanel .detail-stat')).find(s => (s.querySelector('.detail-stat-label') || {}).textContent.replace(/\s+/g, ' ').trim().startsWith(l)); return st ? st.querySelector('.detail-stat-val').textContent.trim() : null; }, label);

// ---- F3: Shelby TN asking price named as the source's terms name it ----
{
  const pg = await open(ROW.tn);
  const card = await cardText(pg, ROW.tn.id);
  check('f3CardAskingPrice', /Asking price \(Land Bank portal\)/i.test(card) && !/Amount type not published/i.test(card), card.slice(0, 300));
  const acq = await q(pg, '#detailPanel .fp-acq-label');
  check('f3FinancialPositionAskingPrice', /Asking price \(Land Bank portal\)/.test(acq || ''), acq);
  const txt = await pageText(pg);
  check('f3NoGenericUnspecifiedNote', !/Amount type not published/.test(txt) && /asking price before an offer/i.test(txt), txt.match(/.{0,60}Amount type not published.{0,60}/)?.[0]);
  // ---- F33: no "county value minus bid" on an asking price; the ceiling needs a county value (TN has assessed 3,000) ----
  check('f33TnNoSpreadOnAskingPrice', (await statVal(pg, 'County value minus bid')) === null, await statVal(pg, 'County value minus bid'));
  check('f33TnCeilingWithCountyValue', (await statVal(pg, 'Your ceiling')) !== null, null);
  // ---- F56 / F81: no Florida "just value" wording outside Florida (Merged look, built from previewFacts) ----
  check('f81TnNoJustValueWording', await mergedHasNoJustValue(ROW.tn), null);
  // ---- F32: one consistent answer about the form and the two verification scopes ----
  check('f32FormNotDenied', !/No form is published by the source/.test(txt) && /has not been read yet/.test(txt), txt.match(/.{0,80}form.{0,80}/i)?.[0]);
  check('f32ScopesNamed', /listing link is verified; the county-level process/.test(txt), null);
  await pg.context().close();
}

// ---- F5: an amount of unstated kind is never labelled a bid, and no ratio is computed from it ----
{
  const pg = await open(ROW.saguacheValued, '?fields=all', [ROW.saguache]);
  const qText = await q(pg, '#detailPanel .dec-row[data-q="bid"] .dec-q');
  const aText = await q(pg, '#detailPanel .dec-row[data-q="bid"] .dec-a');
  check('f5DecisionLabelNotABid', /Published amount \(kind not stated\)/.test(qText || '') && !/Opening \/ minimum bid/.test(qText || ''), qText);
  check('f5NoRatioFromUnstatedKind', /\$47\.46/.test(aText || '') && !/Value ÷ bid/.test(aText || ''), aText);
  check('f5NoSpreadStat', (await statVal(pg, 'County value minus bid')) === null, null);
  const opp = await pg.evaluate(() => (document.querySelector('#detailPanel .opp-grid, #detailPanel [data-section="summary"]') || document.getElementById('detailPanel')).innerText);
  check('f5NoRatioInSummary', !/Value ÷ bid/.test(opp), opp.match(/.{0,40}Value ÷ bid.{0,40}/)?.[0]);
  const card = await cardText(pg, ROW.saguacheValued.id);
  check('f5CardNoRatio', !/Value ÷ bid/.test(card) && /Published amount \(kind not stated\)/i.test(card), card.slice(0, 200));
  // Guided tier: the figure is not where bidding starts.
  const g = await open(ROW.saguache, '?fields=all&tier=beginner');
  const gt = await pageText(g);
  check('f5GuidedNotBiddingStart', !/Bidding starts there/.test(gt) && /not a bid or a price/.test(gt), gt.match(/What it costs.{0,160}/s)?.[0]);
  await g.context().close();
  await pg.context().close();
}

// ---- F104: Tax-Sale.info Michigan amounts are the source's "Minimum Bid" (and a real bid keeps its ratio) ----
{
  const pg = await open(ROW.mi);
  const card = await cardText(pg, ROW.mi.id);
  check('f104CardMinimumBid', /Minimum bid/i.test(card) && !/Opening bid/i.test(card), card.slice(0, 200));
  const qText = await q(pg, '#detailPanel .dec-row[data-q="bid"] .dec-q');
  check('f104DecisionMinimumBid', /^Minimum bid, if published\?/.test(qText || ''), qText);
  check('f104RealBidKeepsRatio', /Value ÷ bid/.test((await q(pg, '#detailPanel .dec-row[data-q="bid"] .dec-a')) || ''), null);
  check('f33RealBidKeepsSpread', (await statVal(pg, 'County value minus bid')) !== null, null);
  check('f56MiNoJustValueWording', await mergedHasNoJustValue(ROW.mi), null);
  await pg.context().close();
}

// ---- F33: no "$0" ceiling without a county value; F82: a tiny lot in square feet ----
{
  const pg = await open(ROW.ok);
  check('f33OkNoCeilingWithoutValue', (await statVal(pg, 'Your ceiling')) === null, await statVal(pg, 'Your ceiling'));
  check('f33OkNoSpread', (await statVal(pg, 'County value minus bid')) === null, null);
  check('f82PageAcreageSqft', (await statVal(pg, 'Acreage')) === '161 sq ft', await statVal(pg, 'Acreage'));
  const card = await cardText(pg, ROW.ok.id);
  check('f82CardLotSqft', /161 sq ft/.test(card) && !/0\.00 acres/.test(card), card.match(/.{0,30}(acres|sq ft).{0,10}/)?.[0]);
  await pg.context().close();
  const s = await open(ROW.saguache);
  check('f82LargeLotStillAcres', (await statVal(s, 'Acreage')) === '160.00 ac', await statVal(s, 'Acreage'));
  await s.context().close();
}

// ---- F16: the Florida TDA rule only on Florida certificates ----
{
  const pg = await open(ROW.coCert);
  const txt = await pageText(pg);
  check('f16CoCertNoTda', !/TDA Eligibility/i.test(txt) && !/Eligible now/.test(txt), txt.match(/.{0,40}TDA.{0,40}/)?.[0]);
  await pg.evaluate(() => { const c = document.querySelector('[data-action="closedetail"]'); if (c) c.click(); });
  await pg.waitForTimeout(300);
  const card = await cardText(pg, ROW.coCert.id);
  check('f16CoCardNoTda', card.length > 0 && !/TDA/i.test(card), card.slice(0, 200));
  await pg.context().close();
  // Florida fixture certificate keeps it.
  const ctx = await b.newContext({ viewport: { width: 1400, height: 900 } });
  const fl = await ctx.newPage();
  await fl.goto(BASE + '#/certificates', { waitUntil: 'networkidle' }); await fl.waitForTimeout(800);
  const flCard = await fl.evaluate(() => { const el = document.querySelector('.prop-card'); if (!el) return ''; el.querySelectorAll('details').forEach(d => { d.open = true; }); return el.innerText; });
  check('f16FlCertKeepsTda', /TDA Eligibility/i.test(flCard), flCard.slice(0, 200));
  await ctx.close();
}

// ---- F54: a superseded figure is the LAST published amount, not the current one ----
{
  const pg = await open(ROW.taylor);
  const head = await q(pg, '#detailPanel .fp-acq-label');
  const temporal = await pg.evaluate(() => (document.querySelector('#detailPanel .fp-acq') || {}).dataset?.fpTemporal);
  check('f54HistoricalNotCurrent', /^Last published amount · Original opening bid/i.test(head || '') && temporal === 'HISTORICAL', [head, temporal]);
  await pg.context().close();
  const ok = await open(ROW.ok);
  check('f54CurrentStaysCurrent', /^Current acquisition amount/.test((await q(ok, '#detailPanel .fp-acq-label')) || ''), await q(ok, '#detailPanel .fp-acq-label'));
  await ok.context().close();
}

// ---- F14: the clean Full record keeps "Already inside the listed figure" as included ----
{
  const ctx = await b.newContext({ viewport: { width: 1400, height: 900 } });
  const pg = await ctx.newPage();
  pg.on('pageerror', e => errs.push('p3: ' + e.message));
  await pg.goto(BASE + '?fields=clean#/lands/p3', { waitUntil: 'networkidle' });
  await pg.waitForSelector('#detailPanel [data-section="money"]', { timeout: 10000 }).catch(() => {});
  const st = await pg.evaluate(() => {
    const sec = document.querySelector('#detailPanel [data-section="money"]'); if (!sec) return null;
    sec.querySelectorAll('details').forEach(d => { d.open = true; });
    const lis = Array.from(sec.querySelectorAll('.fp-lines li')).map(li => [li.dataset.fpStatus, li.textContent.replace(/\s+/g, ' ').trim()]);
    return lis;
  });
  const included = (st || []).find(([s]) => s === 'included');
  const fold = (st || []).find(([s]) => s === 'amounts_not_on_file');
  check('f14IncludedLineStays', !!included && /Included in the total \/ figure/.test(included[1]), st);
  check('f14FoldOnlyAddedItems', !!fold && !/Already inside/.test(fold[1]) && /Added on top - amounts not on file/.test(fold[1]), fold);
  await ctx.close();
}

// ---- F1 / F15: a 0 market value is never shown; the LA label carries the roll year, not the old tax-sale year ----
{
  const pg = await open(ROW.la);
  const txt = await pageText(pg);
  check('f15NoZeroValue', !/\$0\b/.test(txt) && !/Fair Market Value/.test(txt), txt.match(/.{0,60}(\$0\b|Fair Market).{0,60}/)?.[0]);
  check('f15BuildingValueNotBareLand', (await statVal(pg, 'Building / Improvement Value')) === null, await statVal(pg, 'Building / Improvement Value'));
  await pg.context().close();
  const v = await open(ROW.laValued);
  const label = await v.evaluate(() => { const st = Array.from(document.querySelectorAll('#detailPanel .detail-stat')).find(s => /Fair Market Value/.test(s.textContent)); return st ? st.querySelector('.detail-stat-label').textContent.replace(/\s+/g, ' ').trim() : null; });
  check('f1LaLabelRollYear', label === '2025 Fair Market Value (tax roll)', label);
  await v.context().close();
  const bare = Object.assign({}, ROW.laValued, { id: '01e67ce0-1111-4421-bb28-6422c4fe13d9', case_no: '002-2060-6', value_year: null });
  const w = await open(bare);
  const label2 = await w.evaluate(() => { const st = Array.from(document.querySelectorAll('#detailPanel .detail-stat')).find(s => /Fair Market Value/.test(s.textContent)); return st ? st.querySelector('.detail-stat-label').textContent.replace(/\s+/g, ' ').trim() : null; });
  check('f1LaLabelNoStaleTaxYear', label2 === 'Fair Market Value (tax roll)', label2);
  await w.context().close();
}

check('noPageErrors', errs.length === 0, errs);
await b.close();
console.log(fail ? `FAIL: ${fail} check(s) failed` : 'PASS: all amounts-labels checks matched');
process.exit(fail ? 1 : 0);
