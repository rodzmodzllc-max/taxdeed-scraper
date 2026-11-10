// Audit 2026-10-28, theme record-text-links (fixed 2026-11-03):
//  F31 / F36 / F68 / F77  placeholder "addresses" (Parcel …, Account …, Case …,
//     NO SITUS, 0 UNKNOWN, No Address Assigned By City, SEC n TW) are never the
//     title and never a Zillow / Google Maps search; the unit word follows the
//     state (no "St. Louis City County");
//  F35  "St. Louis City" is never called a county;
//  F23  ArcGIS REST / item URLs are never "county auction site" / "official listing";
//  F24 / F39  an appraiser link with an empty key is dropped;
//  F40 / F67  http appraiser links are upgraded only on verified hosts, else labelled;
//  F53 / F58 / F83 / F89  no internal provenance strings / repo paths / raw
//     codes / harvester ids for customers;
//  F55  a bare numeric land use is labelled "<County / Parish / City> use code";
//  F90  the clean view folds "Not on file" additions into one line;
//  F91  the tier chosen on the page survives Back restoring ?tier=;
//  F92  a Watchlist toggle keeps the opened Research group and the scroll;
//  F93  one read date per Available page (the match date is "first matched");
//  F94  "because it appears on <source>", never "lists lists it".
import { chromium } from 'playwright';
import fs from 'fs';
const BASE = process.env.BASE_URL || 'http://localhost:8934/index.html';
const ROOT = BASE.replace(/[^/]*$/, '');
const exe = '/opt/pw-browsers/chromium';
const b = await chromium.launch(fs.existsSync(exe) ? { executablePath: exe } : {});
let fail = 0;
const check = (name, ok, got) => { console.log((ok ? 'PASS ' : 'FAIL ') + name + (ok ? '' : ' -> ' + JSON.stringify(got))); if (!ok) fail++; };
const errs = [];

// Production-shaped rows (read-only SQL, 2026-11-03; owner names omitted).
const FL_ROWS = [
  { id: 'r-marion', state: 'FL', source: 'auction', county: 'Marion', case_no: '11622018', parcel: '59382', address: 'NO SITUS', bid: 1500, status: 'active', sale_date: '2026-12-09',
    url_appraiser: 'http://www.pa.marion.fl.us/PRC.aspx?key=&YR=2026&mName=False&mSitus=False', url_auction: 'https://marion.realtaxdeed.com/index.cfm?zaction=AUCTION&zmethod=PREVIEW&AuctionDate=12/09/2026', url_auction_kind: 'sale',
    source_id: 'fl_realauction', dor_use_code: '00', latitude: 29.4796719, longitude: -81.9670686, lien_level: 'unscreened', lien_note: '', last_seen_at: '2026-11-02T12:00:00Z', updated_at: '2026-11-02T12:00:00Z' },
  { id: 'r-marion-sec', state: 'FL', source: 'auction', county: 'Marion', case_no: '11622019', parcel: '59383', address: 'SEC 30 TW', bid: 1500, status: 'active', sale_date: '2026-12-09',
    url_appraiser: 'http://www.pa.marion.fl.us/PRC.aspx?key=59383&YR=2026&mName=False&mSitus=False', url_auction: 'https://marion.realtaxdeed.com/index.cfm?zaction=AUCTION&zmethod=PREVIEW&AuctionDate=12/09/2026', url_auction_kind: 'sale',
    source_id: 'fl_realauction', lien_level: 'unscreened', lien_note: '', last_seen_at: '2026-11-02T12:00:00Z', updated_at: '2026-11-02T12:00:00Z' },
  { id: 'r-brevard', state: 'FL', source: 'auction', county: 'Brevard', case_no: '260358', parcel: '2000576', address: '0 UNKNOWN', bid: 900, status: 'active', sale_date: '2026-12-10',
    url_appraiser: 'https://www.bcpao.us/PropertySearch/#/parcel/2000576', url_auction: 'https://brevard.realforeclose.com/index.cfm?zaction=AUCTION&zmethod=PREVIEW&AuctionDate=12/10/2026', url_auction_kind: 'sale',
    source_id: 'fl_realauction', lien_level: 'unscreened', lien_note: '', last_seen_at: '2026-11-02T12:00:00Z', updated_at: '2026-11-02T12:00:00Z' },
  { id: 'r-broward', state: 'FL', source: 'auction', county: 'Broward', case_no: '54248', parcel: '494125-CG-0040', address: '2251 NW 48 TERRACE', bid: 12000, status: 'active', sale_date: '2026-12-28', prop_type: 'Condo',
    url_appraiser: 'http://www.bcpa.net/RecInfo.asp?URL_Folio=494125CG0040', url_auction: 'https://broward.realtaxdeed.com/index.cfm?zaction=AUCTION&zmethod=PREVIEW&AuctionDate=12/28/2026', url_auction_kind: 'sale',
    source_id: 'fl_realauction', land_use: '00', dor_use_code: '04', year_built: 1977, latitude: 26.1547204, longitude: -80.216248, lien_level: 'unscreened', lien_note: '', last_seen_at: '2026-11-02T12:00:00Z', updated_at: '2026-11-02T12:00:00Z' },
  { id: 'r-escambia', state: 'FL', source: 'auction', county: 'Escambia', case_no: '2025-0100', parcel: '331S300401004015', address: '100 W MAIN ST', bid: 2000, status: 'active', sale_date: '2026-12-02',
    url_appraiser: 'http://www.escpa.org/cama/Detail_a.aspx?s=331S300401004015', url_auction: 'https://escambia.realtaxdeed.com/index.cfm?zaction=AUCTION&zmethod=PREVIEW&AuctionDate=12/02/2026', url_auction_kind: 'sale',
    source_id: 'fl_realauction', lien_level: 'unscreened', lien_note: '', last_seen_at: '2026-11-02T12:00:00Z', updated_at: '2026-11-02T12:00:00Z' },
  { id: 'r-pasco-case', state: 'FL', source: 'laft', county: 'Pasco', case_no: '2025XX000042TDAXXX', parcel: '12-34-56-0000-00100-0000', address: 'Case 2025XX000042TDAXXX', bid: 0, status: 'active', sale_date: null,
    source_id: 'fl_laft_pdfs', inventory_type: 'POST_SALE_FIXED_PRICE', purchase_amount: null, purchase_amount_kind: 'NOT_PUBLISHED', publication_status: 'APPROVED_GRANDFATHERED', list_url: 'https://www.pascoclerk.com/x', lien_level: 'unscreened', lien_note: '', last_seen_at: '2026-11-02T12:00:00Z', updated_at: '2026-11-02T12:00:00Z' },
  { id: 'r-alachua', state: 'FL', source: 'laft', county: 'Alachua', case_no: 'TD 2025-091', parcel: '07915-012-006', address: 'Parcel 07915-012-006', bid: 0, status: 'active', sale_date: null,
    url_auction: 'https://alachua.realtdm.com/public/cases/list', url_auction_kind: 'county', list_url: 'https://alachua.realtdm.com/public/cases/list', source_id: 'fl_laft_realtdm', inventory_type: 'POST_SALE_FIXED_PRICE',
    purchase_amount: 3100, purchase_amount_kind: 'FIXED_PURCHASE_PRICE', publication_status: 'APPROVED_GRANDFATHERED', dor_use_code: '01', latitude: 29.6910406, longitude: -82.3539137,
    inventory_status: 'available_otc', inventory_status_basis: "LIST_PRESENCE: on the county's Lands Available list at the last read (F.S. 197.502(7)) (fl_laft_realtdm)", inventory_status_observed_at: '2026-11-01T09:50:00Z',
    purchase_path_type: 'quoted_amount', purchase_path_scope: 'source', purchase_path_observed_on: '2026-10-01', purchase_path_evidence: "Clerk's List of Lands Available page (data/purchase_path_evidence.csv, observed 2026-10-01)",
    otc_provenance: { list_url: 'https://alachua.realtdm.com/public/cases/list', harvester: 'fl_laft_realtdm', source_id: 'fl_laft_realtdm', retrieved_at: '2026-11-01T09:49:03Z',
      purchase_url: "quoted_amount (source-scope): Clerk's List of Lands Available page: contact the Clerk's Tax Deed department for the current cost (data/purchase_path_evidence.csv, observed 2026-10-01)",
      source_match: { basis: 'row read from the source list / document by the harvester; identity as the sync upserts it', value: 'TD 2025-091', parcel: '07915-012-006', source: 'https://alachua.realtdm.com/public/cases/list', read_at: '2026-10-26T09:50:07Z', identifier: 'case_no' },
      inventory_type: 'harvester constant (F.S. 197.502(7) Lands Available list)', purchase_amount: 'source column/field: FIXED_PURCHASE_PRICE', purchase_path_mode: 'unknown',
      status_terminology: 'active = on the county list this run; closed = absent from a COMPLETE/EMPTY harvest',
      acquisition: { mode: 'multi_step', email: 'taxdeeds@alachuaclerk.example', phone: '(352) 374-3615', steps: ['Contact the Clerk for the current cost', 'Pay the full amount'], office: 'Alachua County Clerk - Tax Deed department', channels: ['email', 'phone'], observed_on: '2026-10-01', evidence_url: 'https://www.alachuaclerk.org/civil/taxlands.cfm' },
      purchase_evidence_url: 'https://www.alachuaclerk.org/civil/taxlands.cfm', purchase_evidence_type: 'county_page', purchase_evidence_title: 'List of Lands Available - Alachua County', purchase_path_observed_on: '2026-10-01' },
    lien_level: 'unscreened', lien_note: '', last_seen_at: '2026-11-01T09:50:00Z', updated_at: '2026-11-01T09:50:00Z' },
  { id: 'r-sarasota-cert', state: 'FL', source: 'certificate', county: 'Sarasota', case_no: '2025-1147200410', parcel: '1147200410', address: 'Account 1147200410', bid: 410, certificate_no: '12345', tax_year: 2025, status: 'active', sale_date: null,
    source_id: 'fl_sarasota_tc_certificates', lien_level: 'unscreened', lien_note: '', last_seen_at: '2026-11-02T12:00:00Z', updated_at: '2026-11-02T12:00:00Z' }
];
const MO_ROWS = [
  { id: 'r-stl', state: 'MO', source: 'laft', county: 'St. Louis City', case_no: '16529190000', parcel: '16529190000', address: '3739  S BROADWAY', bid: 0, status: 'active', sale_date: null,
    url_auction: 'https://www.stlouis-mo.gov/data/datasets/dataset.cfm?id=30', url_auction_kind: 'county', list_url: 'https://www.stlouis-mo.gov/data/datasets/dataset.cfm?id=30', document_url: 'https://static.stlouis-mo.gov/open-data/SLDC/REAL-ESTATE/LRA_INVENTORY.csv',
    source_id: 'mo_stl_lra_inventory', harvester_source: 'mo_stl_lra_inventory', inventory_type: 'POST_SALE', purchase_amount: null, purchase_amount_kind: 'NOT_PUBLISHED', publication_status: 'APPROVED', ledger_type: 'buy', land_use: 'Lot', latitude: 38.5866455, longitude: -90.2251537,
    inventory_status: 'available_otc', inventory_status_basis: "SOURCE_STATUS: the source's own availability status for this row (mo_stl_lra_inventory)", lien_level: 'unscreened', lien_note: '', last_seen_at: '2026-11-02T12:00:00Z', updated_at: '2026-11-02T12:00:00Z' },
  { id: 'r-kc', state: 'MO', source: 'laft', county: 'Jackson', case_no: 'JA27420140100000000', parcel: 'JA27420140100000000', address: 'NO ADDRESS ASSIGNED BY CITY', bid: 0, status: 'active', sale_date: null,
    url_auction: 'https://public-kclb.epropertyplus.com/landmgmtpub/app/base/landing', url_auction_kind: 'county', list_url: 'https://public-kclb.epropertyplus.com/landmgmtpub/app/base/landing',
    source_id: 'mo_kc_landbank', harvester_source: 'mo_kc_landbank', inventory_type: 'POST_SALE', purchase_amount: 2500, purchase_amount_kind: 'PUBLISHED_AMOUNT_KIND_UNSPECIFIED', publication_status: 'APPROVED', ledger_type: 'buy', land_use: 'Commercial Vacant', latitude: 39.0935507, longitude: -94.5057333,
    lien_level: 'unscreened', lien_note: '', last_seen_at: '2026-11-02T12:00:00Z', updated_at: '2026-11-02T12:00:00Z' },
  { id: 'r-kc2', state: 'MO', source: 'laft', county: 'Jackson', case_no: 'JA27420140100000001', parcel: 'JA27420140100000001', address: 'No Address Assigned By City, Kansas City, MO', bid: 0, status: 'active', sale_date: null,
    source_id: 'mo_kc_landbank', harvester_source: 'mo_kc_landbank', inventory_type: 'POST_SALE', purchase_amount: null, purchase_amount_kind: 'NOT_PUBLISHED', publication_status: 'APPROVED', ledger_type: 'buy',
    lien_level: 'unscreened', lien_note: '', last_seen_at: '2026-11-02T12:00:00Z', updated_at: '2026-11-02T12:00:00Z' }
];
const MI_ROWS = [
  { id: 'r-eaton', state: 'MI', source: 'auction', county: 'Eaton', case_no: '23-100-001-100-00', parcel: '23-100-001-100-00', address: 'Parcel 23-100-001-100-00', bid: 4000, status: 'active', sale_date: '2026-12-15',
    url_auction: 'https://www.arcgis.com/home/item.html?id=5b973732a9e84fdd94fa225f8160650d', url_auction_kind: 'county', list_url: 'https://www.arcgis.com/home/item.html?id=5b973732a9e84fdd94fa225f8160650d',
    source_id: 'mi_eaton_treasurer_sale', harvester_source: 'mi_eaton_treasurer_sale', publication_status: 'APPROVED', ledger_type: 'auctions', lien_level: 'unscreened', lien_note: '', last_seen_at: '2026-11-02T12:00:00Z', updated_at: '2026-11-02T12:00:00Z' },
  { id: 'r-wright', state: 'MI', source: 'laft', county: 'Wayne', case_no: '21001.', parcel: '21001.', address: 'Parcel 21001.', bid: 0, status: 'active', sale_date: null,
    url_auction: 'https://services2.arcgis.com/CiQCvRGImIxsaFnM/arcgis/rest/services/Tax_Forfeited_Parcels/FeatureServer/0', url_auction_kind: 'county', list_url: 'https://services2.arcgis.com/CiQCvRGImIxsaFnM/arcgis/rest/services/Tax_Forfeited_Parcels/FeatureServer/0',
    source_id: 'mi_detroit_landbank_lots', harvester_source: 'mi_detroit_landbank_lots', inventory_type: 'POST_SALE', purchase_amount: null, purchase_amount_kind: 'NOT_PUBLISHED', publication_status: 'APPROVED', ledger_type: 'buy',
    inventory_status_raw: 'Side Lot For Sale', lien_level: 'unscreened', lien_note: '', last_seen_at: '2026-11-02T12:00:00Z', updated_at: '2026-11-02T12:00:00Z' }
];

async function open(page, hash, vp, rows, ctxOpts = {}) {
  const ctx = await b.newContext({ viewport: vp || { width: 1400, height: 900 }, ...ctxOpts });
  const pg = await ctx.newPage();
  pg.on('pageerror', e => errs.push(hash + ': ' + e.message));
  if (rows) await pg.addInitScript(r => { window.__stubExtraRows = r; window.__tdwFullFieldsDefault = true; }, rows);
  await pg.goto(ROOT + page + hash, { waitUntil: 'networkidle' });
  await pg.waitForTimeout(1200);
  return pg;
}
// The property page is the modal (phone) or the side panel (desktop).
const HOST = `(() => { const m = document.getElementById('detailModal'); return m && !m.hidden ? document.getElementById('detailModalInner') : document.getElementById('detailPanel'); })()`;
const hostSel = pg => pg.evaluate(() => { const m = document.getElementById('detailModal'); return m && !m.hidden ? '#detailModalInner' : '#detailPanel'; });
const openAllDetails = pg => pg.evaluate(() => { const m = document.getElementById('detailModal'); const h = m && !m.hidden ? document.getElementById('detailModalInner') : document.getElementById('detailPanel'); h.querySelectorAll('details').forEach(d => d.open = true); });
const detailText = pg => pg.evaluate(`(${HOST} || {}).innerText || ''`);
const detailHrefs = pg => pg.evaluate(`Array.from((${HOST} || document.createElement('div')).querySelectorAll('a[href]')).map(a => ({ t: a.textContent.replace(/\\s*→\\s*$/, '').trim(), h: a.getAttribute('href') }))`);
const detailTitle = pg => pg.evaluate(`((${HOST} || document.createElement('div')).querySelector('.detail-address') || {}).textContent || ''`);
const detailHtml = pg => pg.evaluate(`(${HOST} || {}).innerHTML || ''`);

// ---- F31 / F68 / F77 / F24 / F39 / F40 / F55 / F67: Florida auction rows ----
for (const [id, want] of [['r-marion', 'NO SITUS'], ['r-marion-sec', 'SEC 30 TW'], ['r-brevard', '0 UNKNOWN']]) {
  const pg = await open('index.html', '?fields=all#/auctions/' + id, { width: 390, height: 844 }, FL_ROWS);
  const title = await detailTitle(pg), hrefs = await detailHrefs(pg);
  check(id + 'TitleIsLot', /^Parcel #/.test(title.trim()) && !title.includes(want), title);
  check(id + 'NoPlaceholderSearch', !hrefs.some(x => /zillow\.com|google\.com\/maps/.test(x.h) && decodeURIComponent(x.h).includes(want)), hrefs.filter(x => /zillow|google/.test(x.h)));
  check(id + 'NoZillowTile', !hrefs.some(x => /zillow\.com/.test(x.h)), hrefs.filter(x => /zillow/.test(x.h)));
  const appr = hrefs.filter(x => /^Appraiser/.test(x.t));
  if (id === 'r-marion') check('marionEmptyKeyAppraiserDropped', !appr.some(x => /key=&/.test(x.h)) && appr.every(x => !/pa\.marion\.fl\.us/.test(x.h)), appr);
  if (id === 'r-marion-sec') check('marionKeyedAppraiserHttps', appr.length === 1 && appr[0].h === 'https://www.pa.marion.fl.us/PRC.aspx?key=59383&YR=2026&mName=False&mSitus=False' && appr[0].t === 'Appraiser', appr);
  if (id === 'r-brevard') check('brevardHttpsAppraiserKept', appr.length === 1 && appr[0].h.startsWith('https://www.bcpao.us/'), appr);
  await pg.context().close();
}
{
  const pg = await open('index.html', '?fields=all#/auctions/r-broward', { width: 1400, height: 900 }, FL_ROWS);
  const txt = await detailText(pg), hrefs = await detailHrefs(pg);
  check('browardLandUseLabelled', /County use code 00/.test(txt) && !/Land use 00\b/.test(txt), txt.match(/.{0,30}use code.{0,20}|.{0,20}Land use.{0,20}/g));
  const appr = hrefs.filter(x => /^Appraiser/.test(x.t));
  check('browardAppraiserUpgradedHttps', appr.length === 1 && appr[0].h === 'https://www.bcpa.net/RecInfo.asp?URL_Folio=494125CG0040' && appr[0].t === 'Appraiser', appr);
  await pg.context().close();
}
{
  // Escambia's record page did not answer over https (checked 2026-11-03): the link stays http, labelled.
  const pg = await open('index.html', '?fields=all#/auctions/r-escambia', { width: 1400, height: 900 }, FL_ROWS);
  const appr = (await detailHrefs(pg)).filter(x => /^Appraiser/.test(x.t));
  check('escambiaHttpAppraiserLabelled', appr.length === 1 && appr[0].h.startsWith('http://www.escpa.org/') && /not https/.test(appr[0].t), appr);
  await pg.context().close();
}

// ---- F31 / F53 / F58 / F93: Florida Available rows ----
{
  const pg = await open('index.html', '?fields=all#/lands/r-pasco-case', { width: 1400, height: 900 }, FL_ROWS);
  const title = await detailTitle(pg), hrefs = await detailHrefs(pg);
  check('pascoCaseTitleIsLot', /^Parcel #/.test(title.trim()) && !/Case 2025XX/.test(title), title);
  check('pascoCaseNoSearchLinks', !hrefs.some(x => /zillow\.com|google\.com\/maps/.test(x.h)), hrefs.filter(x => /zillow|google/.test(x.h)));
  await pg.context().close();
}
{
  const pg = await open('index.html', '?fields=all#/lands/r-alachua', { width: 1400, height: 900 }, FL_ROWS);
  await openAllDetails(pg);
  const txt = await detailText(pg), html = await detailHtml(pg);
  check('alachuaNoHarvesterConstant', !/harvester constant/i.test(txt), txt.match(/.{0,40}harvester constant.{0,40}/g));
  check('alachuaBasisInPlainWords', /Classified from the county's F\.S\. 197\.502\(7\) Lands Available list/.test(txt), txt.match(/Classified[^\n]{0,80}/g));
  check('alachuaNoRepoPaths', !/purchase_path_evidence\.csv|data\/|scripts\/|harvesters\//.test(txt), txt.match(/.{0,40}(\.csv|scripts\/|data\/).{0,40}/g));
  check('alachuaNoRawBasisCode', !/LIST_PRESENCE:/.test(txt) && /List presence - on the county's Lands Available list/.test(txt), txt.match(/.{0,20}(LIST_PRESENCE|List presence).{0,60}/g));
  check('alachuaNoHarvesterId', !/\(fl_laft_realtdm\)|Read by fl_laft_realtdm/.test(txt), txt.match(/.{0,30}fl_laft_realtdm.{0,30}/g));
  check('alachuaNoInternalStatusWording', !/COMPLETE\/EMPTY harvest/.test(txt), txt.match(/.{0,40}COMPLETE\/EMPTY.{0,20}/g));
  check('alachuaNoMigrationNote', !/migration 031/.test(txt), txt.match(/.{0,40}migration 031.{0,20}/g));
  check('alachuaOneReadDate', /listing last read Nov 1, 2026/.test(txt) && !/listing read Oct 26, 2026/.test(txt), txt.match(/.{0,30}(listing read|listing last read|first matched).{0,20}/g));
  check('alachuaMatchIsFirstMatched', /first matched Oct 26, 2026/.test(txt), txt.match(/.{0,40}first matched.{0,20}/g));
  check('alachuaWhySentence', /because it appears on/.test(txt) && !/lists it\./.test(txt), txt.match(/because[^\n]{0,80}/g));
  check('alachuaParcelAddressNoZillow', !/zillow\.com/.test(html), (html.match(/https:\/\/www\.zillow[^"]*/g) || []));
  await pg.context().close();
}

// ---- F89 / F90 / F92 / F94 on the fixture (p3, Bay) ----
{
  const pg = await open('index.html', '?fields=all#/lands/p3', { width: 1400, height: 900 }, null);
  await openAllDetails(pg);
  const txt = await detailText(pg);
  check('p3DiligenceSourceLabel', /Recorded from Florida Department of Revenue \(NAL tax roll\)/.test(txt) && !/fdor nal/.test(txt), txt.match(/Recorded from[^\n]{0,60}/g));
  // The provenance lines (rendered once the full provenance is on the row -
  // the fixture's p3 is one the stub's provenance RPC knows).
  check('p3ReadByName', /Read by\s*Clerk's Lands Available|Read by\s*[A-Z]/.test(txt) && !/Read by\s*fl_laft_pioneer/.test(txt), txt.match(/Read by[^\n]{0,60}/g));
  check('p3NoInternalStatusWording', !/COMPLETE\/EMPTY harvest/.test(txt), txt.match(/.{0,40}COMPLETE\/EMPTY.{0,20}/g));
  check('p3InventoryTypePlain', !/harvester constant/.test(txt), txt.match(/.{0,30}harvester constant.{0,30}/g));
  check('p3GateNoMigrationForCustomer', /Customer-publication gate:\s*Not enforced on this deployment/.test(txt) && !/migration 031/.test(txt), txt.match(/Customer-publication gate[^\n]{0,90}/g));
  await pg.context().close();
}
{
  // The clean (default) view: the four "Not on file" additions are one line.
  const pg = await open('index.html', '?fields=clean#/lands/p3', { width: 1400, height: 900 }, null);
  const adds = await pg.evaluate(`Array.from(${HOST}.querySelectorAll('.acq-adds li')).map(li => li.textContent.replace(/\\s+/g, ' ').trim())`);
  check('p3CleanAddsFolded', adds.length === 1 && /Added on top - amounts not on file/.test(adds[0]) && /Recording fees/.test(adds[0]), adds);
  const full = await (await open('index.html', '?fields=all#/lands/p3', { width: 1400, height: 900 }, null)).evaluate(`${HOST}.querySelectorAll('.acq-adds li').length`);
  check('p3FullAddsKept', full >= 4, full);
  await pg.context().close();
}
for (const [label, vp] of [['phone', { width: 390, height: 844 }], ['desktop', { width: 1400, height: 900 }]]) {
  const pg = await open('index.html', '#/lands/p3', vp, null);
  const host = await hostSel(pg);
  const before = await pg.evaluate(h => { const d = document.querySelector(h + ' details.detail-fold[data-fold="risk"]'); d.open = true; const sc = document.querySelector(h); sc.scrollTop = 300; return sc.scrollTop; }, host);
  await pg.waitForTimeout(200);
  // Clicked in place (a locator click would first scroll the button into view, moving the panel's own scroll).
  await pg.evaluate(h => document.querySelector(h + ' [data-action="bidlist"]').click(), host);
  await pg.waitForTimeout(900);
  const st = await pg.evaluate(h => ({ open: !!(document.querySelector(h + ' details.detail-fold[data-fold="risk"]') || {}).open, top: document.querySelector(h).scrollTop, watched: !!document.querySelector(h + ' [data-action="bidlist"].on, ' + h + ' [data-action="bidlist"][aria-pressed="true"]') }), host);
  check('f92ResearchStaysOpen_' + label, st.open === true, st);
  if (before > 0) check('f92ScrollKept_' + label, st.top > 0, { before, st }); else console.log('SKIP f92ScrollKept_' + label + ' (surface is not its own scroll box)');
  await pg.context().close();
}

// ---- F91: the tier chosen on the page survives Back (admin / tester only) ----
{
  // Opened by deep link (a cold start at the property), as the audit's repro did via a card.
  const pg = await open('index.html', '?profile=admin&tier=beginner#/auctions/p1', { width: 390, height: 844 }, null);
  check('f91GuidedFirst', (await pg.evaluate(() => window.__tdwPageTier())) === 'beginner', await pg.evaluate(() => window.__tdwPageTier()));
  await pg.locator('#detailModalInner [data-tier-set="pro"]').first().click();
  await pg.waitForTimeout(600);
  await pg.goBack();
  await pg.waitForTimeout(900);
  const after = await pg.evaluate(() => ({ tier: window.__tdwPageTier(), url: location.search, modalHidden: document.getElementById('detailModal').hidden }));
  check('f91ChoiceSticksAfterBack', after.tier === 'pro', after);
  await pg.evaluate(() => { location.hash = '#/auctions/p1'; });
  await pg.waitForTimeout(900);
  if (await pg.evaluate(() => document.getElementById('detailModal').hidden)) { await pg.locator('#main .prop-card[data-pid] .detail-btn, #main .prop-card[data-pid] .prop-title, #main .prop-card[data-pid] h3').first().click(); await pg.waitForTimeout(900); }
  check('f91NextPropertyOpensFull', (await pg.evaluate(() => window.__tdwPageTier())) === 'pro' && (await pg.locator('#detailModalInner .tier-btn.on').textContent()).trim() === 'Full record', await pg.evaluate(() => window.__tdwPageTier()));
  // A fresh load that names ?tier= is an explicit choice and wins again.
  await pg.goto(ROOT + 'index.html?profile=admin&tier=free#/auctions/p1', { waitUntil: 'networkidle' });
  await pg.waitForTimeout(1200);
  check('f91FreshTierLinkWins', (await pg.evaluate(() => window.__tdwPageTier())) === 'free', await pg.evaluate(() => window.__tdwPageTier()));
  await pg.context().close();
}

// ---- F35 / F36 / F68: Missouri ----
{
  const pg = await open('mo.html', '?fields=all#/lands/r-stl', { width: 1400, height: 900 }, MO_ROWS);
  const txt = await detailText(pg), hrefs = await detailHrefs(pg);
  check('stlNeverCalledCounty', !/St\. Louis City County/.test(txt) && /St\. Louis City, MO/.test(txt), txt.match(/.{0,20}St\. Louis City.{0,20}/g));
  const z = hrefs.find(x => /zillow\.com/.test(x.h));
  check('stlZillowUnit', !!z && decodeURIComponent(z.h).includes('S BROADWAY, St. Louis City, MO') && !decodeURIComponent(z.h).includes('City County'), z);
  check('stlNoRawSourceId', !/\(mo_stl_lra_inventory\)/.test(txt), txt.match(/.{0,30}mo_stl_lra_inventory.{0,10}/g));
  await pg.context().close();
  const cards = await open('mo.html', '#/lands', { width: 1400, height: 900 }, MO_ROWS);
  const listTxt = await cards.evaluate(() => document.getElementById('main').innerText);
  check('stlListNeverCalledCounty', !/St\. Louis City County/.test(listTxt), listTxt.match(/.{0,20}St\. Louis City County.{0,10}/g));
  await cards.context().close();
  // The Merged look (experience-terrain.js draws Available) names the unit the same way.
  const merged = await open('mo.html', '?look=merged#/lands', { width: 1400, height: 900 }, MO_ROWS);
  await merged.waitForTimeout(1500);
  const mergedTxt = await merged.evaluate(() => (document.getElementById('xpStage') || {}).innerText || '');
  check('stlMergedDrawn', /St\. Louis City/.test(mergedTxt), mergedTxt.slice(0, 200));
  check('stlMergedNeverCalledCounty', !/St\. Louis City County/.test(mergedTxt), mergedTxt.match(/.{0,20}St\. Louis City County.{0,10}/g));
  await merged.context().close();
}
for (const id of ['r-kc', 'r-kc2']) {
  const pg = await open('mo.html', '?fields=all#/lands/' + id, { width: 1400, height: 900 }, MO_ROWS);
  const title = await detailTitle(pg), hrefs = await detailHrefs(pg);
  check(id + 'TitleIsLot', /^Parcel #/.test(title.trim()) && !/No Address Assigned/i.test(title), title);
  check(id + 'NoZillow', !hrefs.some(x => /zillow\.com/.test(x.h)), hrefs.filter(x => /zillow/.test(x.h)));
  check(id + 'NoPlaceholderMapsSearch', !hrefs.some(x => /google\.com\/maps/.test(x.h) && /Address%20Assigned|Address Assigned/i.test(x.h)), hrefs.filter(x => /google/.test(x.h)));
  await pg.context().close();
}

// ---- F23: ArcGIS REST / item URLs are never a site or listing ----
for (const [id, hash] of [['r-eaton', '#/auctions/r-eaton'], ['r-wright', '#/lands/r-wright']]) {
  const pg = await open('mi.html', '?fields=all' + hash, { width: 1400, height: 900 }, MI_ROWS);
  const hrefs = await detailHrefs(pg), txt = await detailText(pg);
  check(id + 'NoArcgisLinks', !hrefs.some(x => /arcgis\.com|FeatureServer/.test(x.h)), hrefs.filter(x => /arcgis|FeatureServer/.test(x.h)));
  if (id === 'r-eaton') check('eatonSaysNoCountyPage', /No county listing page on file/.test(txt), txt.match(/.{0,40}listing page.{0,40}/g));
  check(id + 'NoOfficialListingLabel', !hrefs.some(x => /county auction site|official listing|source listing|County list page|official availability/i.test(x.t)), hrefs.filter(x => /listing|auction site|list page|availability/i.test(x.t)));
  await pg.context().close();
  const cards = await open('mi.html', hash.replace(/\/[^/]*$/, ''), { width: 1400, height: 900 }, MI_ROWS);
  // The cards only: the ledger strip's "Official reference" is a state-rule citation, not a listing link.
  const cardHrefs = await cards.evaluate(() => Array.from(document.querySelectorAll('#main .prop-card a[href]')).map(a => a.getAttribute('href')));
  check(id + 'CardNoArcgisLinks', !cardHrefs.some(h => /arcgis\.com|FeatureServer/.test(h)), cardHrefs.filter(h => /arcgis|FeatureServer/.test(h)));
  await cards.context().close();
}

// ---- F31: a Sarasota certificate's "Account <id>" is never a search ----
{
  const pg = await open('index.html', '?fields=all#/certificates/r-sarasota-cert', { width: 1400, height: 900 }, FL_ROWS);
  const hrefs = await detailHrefs(pg);
  check('sarasotaAccountNoSearch', !hrefs.some(x => /zillow\.com|google\.com\/maps/.test(x.h) && /Account(%20| )1147200410/.test(x.h)), hrefs.filter(x => /zillow|google/.test(x.h)));
  await pg.context().close();
}

// ---- F83 / F93: Louisiana's basis never cites the retired dataset id; one read date ----
{
  const LA_ROWS = [{ id: 'r-la', state: 'LA', source: 'laft', county: 'East Baton Rouge', case_no: '0123456', parcel: '0123456', address: '1200 FIXTURE ST', bid: 0, status: 'active', sale_date: null,
    source_id: 'la_ebr_adjudicated', harvester_source: 'la_ebr_adjudicated', source_authority: 'GOVERNMENT_DIRECT', inventory_type: 'ADJUDICATED_PROPERTY', purchase_amount: null, purchase_amount_kind: 'NOT_PUBLISHED',
    list_as_of: '2026-05-06', publication_status: 'APPROVED', ledger_type: 'buy', lien_level: 'unscreened', lien_note: '', land_use: '1100',
    otc_provenance: { source_id: 'la_ebr_adjudicated', harvester: 'la_ebr_adjudicated', inventory_type: 'Adjudicated property (dataset a4h4-zi7e description, read live 2026-09-30)',
      source_match: { identifier: 'case_no', value: '0123456', read_at: '2026-10-26T08:00:00Z' } },
    last_seen_at: '2026-10-28T08:00:00Z', updated_at: '2026-10-28T08:00:00Z' }];
  const pg = await open('la.html', '?fields=all#/lands/r-la', { width: 1400, height: 900 }, LA_ROWS);
  await openAllDetails(pg);
  const txt = await detailText(pg);
  check('laNoRetiredDatasetId', txt.length > 200 && !/a4h4|read live/i.test(txt), txt.match(/.{0,50}(a4h4|read live).{0,50}/gi));
  check('laUseCodeIsParish', /Parish use code 1100/.test(txt) && !/County use code/.test(txt), txt.match(/.{0,30}use code.{0,20}/g));
  check('laNoStaleListingRead', !/listing read Oct 26, 2026/.test(txt), txt.match(/.{0,40}listing (last )?read.{0,30}/g));
  await pg.context().close();
}

// ---- Review follow-ups: a street name that starts with PIN / CASE is an address ----
{
  const ROWS = [{ id: 'r-pinoak', state: 'FL', source: 'auction', county: 'Marion', case_no: '11622099', parcel: '59399', address: 'PIN OAK DR', bid: 1500, status: 'active', sale_date: '2026-12-09',
    url_auction: 'https://marion.realtaxdeed.com/index.cfm?zaction=AUCTION&zmethod=PREVIEW&AuctionDate=12/09/2026', url_auction_kind: 'sale', source_id: 'fl_realauction', lien_level: 'unscreened', lien_note: '',
    last_seen_at: '2026-11-02T12:00:00Z', updated_at: '2026-11-02T12:00:00Z' }];
  const pg = await open('index.html', '?fields=all#/auctions/r-pinoak', { width: 1400, height: 900 }, ROWS);
  const title = await detailTitle(pg);
  check('pinOakIsAnAddress', /PIN OAK DR/.test(title), title);
  const hrefs = await detailHrefs(pg);
  check('pinOakHasSearch', hrefs.some(x => /zillow\.com|google\.com\/maps/.test(x.h) && /PIN(%20|\+| )OAK/i.test(x.h)), hrefs.filter(x => /zillow|google/.test(x.h)));
  await pg.context().close();
}

// ---- Review follow-ups: evidence text keeps URLs whole and drops "by <path>" ----
{
  const src = fs.readFileSync(new URL('../../public/app.js', import.meta.url), 'utf8');
  const fn = src.slice(src.indexOf('function customerEvidenceText(s) {'), src.indexOf('// A bare numeric land use'));
  const customerEvidenceText = new Function('isOperatorView', fn + '; return customerEvidenceText;')(() => false);
  const a = customerEvidenceText('Struck-off list (read 2026-10-26 by scripts/harvest_tx_county_sales.py)');
  check('evidenceNoDanglingBy', a === 'Struck-off list (read 2026-10-26)', a);
  const u = 'https://www.dallascounty.org/Assets/uploads/docs/public-works/resale.pdf';
  const c = customerEvidenceText('Published at ' + u + ' (data/purchase_path_evidence.csv)');
  check('evidenceUrlKeptWhole', c === 'Published at ' + u, c);
}

// ---- Review follow-ups: a tier switch starts the new view at the top ----
{
  const pg = await open('index.html', '?profile=admin&tier=pro#/auctions/p1', { width: 390, height: 844 }, null);
  const top0 = await pg.evaluate(() => { const i = document.getElementById('detailModalInner'); i.scrollTop = 600; return i.scrollTop; });
  await pg.evaluate(() => document.querySelector('#detailModalInner [data-tier-set="beginner"]').click());
  await pg.waitForTimeout(700);
  const st = await pg.evaluate(() => ({ top: document.getElementById('detailModalInner').scrollTop, tier: window.__tdwPageTier() }));
  check('tierSwitchStartsAtTop', top0 > 0 && st.top === 0 && st.tier === 'beginner', { top0, st });
  await pg.context().close();
}

check('noPageErrors', errs.length === 0, errs);
await b.close();
console.log(fail ? `FAIL: ${fail} check(s) failed` : 'PASS: all record-text-links checks passed');
process.exit(fail ? 1 : 0);
