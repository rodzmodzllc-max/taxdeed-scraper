// Audit theme "guided-home-copy" (2026-11-03): Guided view copy per ledger /
// state (F25, F26, F71), Home's Available block (F27), per-state ledger copy
// naming the sources that supply the rows (F37, F57, F72, F73), the
// "Why is it in Available?" list noun (F74), plain-language property-type
// search (F19), "Open in the List" syncing the County controls (F61), the
// state picker's current-row probe (F62), Home's one search box (F97), the
// rules page title (F98), state switches dropping a county route (F18) and
// unknown deep links (F102).
import { chromium } from 'playwright';
import fs from 'fs';
const BASE = process.env.BASE_URL || 'http://localhost:8934/index.html';
const root = BASE.replace(/[^/]*$/, '');
const exe = '/opt/pw-browsers/chromium';
const b = await chromium.launch(fs.existsSync(exe) ? { executablePath: exe } : {});
let fail = 0;
const check = (name, ok, got) => { console.log((ok ? 'PASS ' : 'FAIL ') + name + (ok ? '' : ' -> ' + JSON.stringify(got))); if (!ok) fail++; };
const errs = [];
const recent = new Date(Date.now() - 6 * 3600e3).toISOString();
async function open(path, { vp = { width: 1400, height: 900 }, extra = null } = {}) {
  const ctx = await b.newContext({ viewport: vp });
  const pg = await ctx.newPage();
  pg.on('pageerror', e => errs.push(path + ': ' + e.message));
  pg.on('dialog', d => d.accept());
  if (extra) await pg.addInitScript(rows => { window.__stubExtraRows = rows; }, extra);
  await pg.goto(root + path, { waitUntil: 'networkidle' });
  await pg.waitForTimeout(1300);
  return pg;
}
// textContent: the Guided view folds later stages, whose tasks are still the page's copy.
const allText = (pg, sel) => pg.evaluate(s => { const e = document.querySelector(s); return e ? e.textContent.replace(/\s+/g, ' ') : ''; }, sel);
const text = (pg, sel) => pg.evaluate(s => { const e = document.querySelector(s); return e ? e.innerText : ''; }, sel);

// Real-shaped rows (production shapes, synthetic values).
const SAGUACHE = { id: 'xsag1', source: 'auction', state: 'CO', county: 'Saguache', case_no: 'SG-1', parcel: '0001', address: 'Parcel 0001',
  bid: 631.3, purchase_amount: 631.3, purchase_amount_kind: 'PUBLISHED_AMOUNT_KIND_UNSPECIFIED', status: 'active', sale_date: null,
  harvester_source: 'co_saguache_tax_sale', source_id: 'co_saguache_tax_sale', source_authority: 'GOVERNMENT_DIRECT',
  url_auction: 'https://www.arcgis.com/home/item.html?id=fixture', url_auction_kind: 'county', last_seen_at: recent,
  publication_status: 'APPROVED', ledger_type: 'auctions', lien_level: 'unscreened', lien_note: '', updated_at: recent };
const LGBS = { id: 'xtx1', source: 'laft', state: 'TX', county: 'Liberty', case_no: '000016000999', parcel: '21DC-TX-00999', address: 'TRACT 9, Liberty, TX',
  bid: 900, min_bid: 900, status: 'active', sale_date: null, harvester_source: 'tx_lgbs', source_id: 'tx_lgbs', source_authority: 'VENDOR_COUNSEL',
  tx_sale_status: 'Available for Future Sale', last_seen_at: recent, publication_status: 'APPROVED_GRANDFATHERED', ledger_type: 'buy',
  lien_level: 'unscreened', lien_note: '', updated_at: recent,
  otc_provenance: { source_match: { identifier: 'case_no', value: '000016000999', read_at: recent } } };

// F25: a Colorado lien sale is never a tax-deed auction; no "bidding starts there" for an unstated amount.
{
  const pg = await open('co.html?tier=beginner#/auctions/xsag1', { extra: [SAGUACHE] });
  const t = await text(pg, '.g-three');
  check('F25_coLienSaleNamed', /tax lien sale/i.test(t) && /lien, not the land/i.test(t), t);
  check('F25_coNotTaxDeedAuction', !/tax-deed auction/i.test(t), t);
  check('F25_coNoBiddingStartsForUnstated', !/Bidding starts there/.test(t) && /did not say whether this is the opening bid/.test(t), t);
  const g = await allText(pg, '.guided');
  check('F25_coLastStageCertificateNotDeed', /lien certificate/i.test(g) && !/receive the deed/i.test(g), g.slice(0, 400));
  await pg.context().close();
  const wy = await open('wy.html?tier=beginner#/auctions/pwy1');
  const tw = await text(wy, '.g-three');
  check('F25_wyLienSale', /tax lien sale/i.test(tw) && !/tax-deed auction/i.test(tw) && !/Bidding starts there/.test(tw), tw);
  await wy.context().close();
}

// F26: county-held certificates are sold by assignment - nobody bids.
{
  const pg = await open('co.html?tier=beginner#/certificates/pco2');
  const t = await text(pg, '.g-three');
  check('F26_certByAssignment', /assignment/i.test(t) && !/Bid at/i.test(t), t);
  const g = await allText(pg, '.guided');
  check('F26_noCertificateSaleBidding', !/Bid at the certificate sale/i.test(g) && !/tax collector/i.test(g) && /assignment/i.test(g), g.slice(0, 600));
  check('F26_noRateClaimed', /interest rate is not on file/i.test(t) && !/not published on the list/i.test(t), t);
  await pg.context().close();
}

// F25 (review): Morgan CO sells an OPTION for a Treasurer's deed - never "receive the deed".
{
  const MORGAN = Object.assign({}, SAGUACHE, { id: 'xmor1', county: 'Morgan', case_no: 'MO-1', harvester_source: 'co_morgan_treasurer_deed_auctions',
    source_id: 'co_morgan_treasurer_deed_auctions', sale_date: '2027-03-01' });
  const pg = await open('co.html?tier=beginner#/auctions/xmor1', { extra: [MORGAN] });
  const t = await text(pg, '.g-three');
  check('F25_morganOptionNamed', /option for a Treasurer's deed/i.test(t) && /not the deed/i.test(t), t);
  const g = await allText(pg, '.guided');
  check('F25_morganLastStageOption', /receive the option/i.test(g) && !/receive the deed/i.test(g) && !/get the deed/i.test(g), g.slice(-600));
  await pg.context().close();
}

// SC redemption law is not verified here - copy never states it as fact.
{
  const sc = await open('sc.html#/auctions');
  const t = await sc.evaluate(() => document.body.textContent.replace(/\s+/g, ' '));
  check('SC_redemptionNotAsserted', !/former owner keeps a redemption period/i.test(t) && /redemption law has not been verified/i.test(t), t.slice(0, 500));
  await sc.context().close();
}

// F71: a Texas future-sale row is a fact about the LIST, never "It is for sale".
{
  const pg = await open('tx.html?tier=beginner#/lands/xtx1', { extra: [LGBS] });
  const g = await text(pg, '.guided');
  check('F71_txNotForSale', !/It is for sale/.test(g) && /On the source's list/.test(g), g.slice(0, 500));
  check('F71_txCarriesVendorStatus', /Future sale/i.test(g), g.slice(0, 500));
  await pg.context().close();
}

// F27: Home's Available block is never "Available now"; rows carry their phase.
for (const [page, re] of [['tx.html', /Future sale/i], ['la.html', /Dated list|dated|not verified/i]]) {
  const pg = await open(page + '#/dashboard', { extra: page === 'tx.html' ? [LGBS] : null });
  const h = await text(pg, '#homeAvailableNow h2');
  check('F27_headNotAvailableNow_' + page, !!h && !/available now/i.test(h), h);
  const rows = await text(pg, '#homeAvailableNow');
  check('F27_rowPhase_' + page, re.test(rows), rows.slice(0, 400));
  await pg.context().close();
}

// F72: Texas ledger copy - no "on-demand", no blanket court-ordered minimum bid.
for (const slug of ['auctions', 'lands']) {
  const pg = await open('tx.html#/' + slug);
  const t = await text(pg, '#pageList');
  check('F72_txNoOnDemand_' + slug, !/on-demand|not yet on an automatic schedule/i.test(t), t.slice(0, 300));
  check('F72_txNoCourtOrderedMin_' + slug, !/court-ordered minimum bid/i.test(t), null);
  check('F72_txNoLgbsOnly_' + slug, !/Rows here come from LGBS|Current Texas sources: LGBS/i.test(t), null);
  await pg.context().close();
}

// F37 / F57 / F73: the copy names the sources that supply each ledger.
{
  const co = await open('co.html#/auctions', { extra: [SAGUACHE] });
  const t = await text(co, '#pageList');
  check('F73_coAuctionsNamesSaguache', /Saguache/.test(t) && /Morgan/.test(t), t.slice(0, 600));
  check('F37_coNoUnreviewedMorgan', !/collected but unreviewed/i.test(await co.evaluate(() => document.body.innerText)), null);
  check('F57_coFooterNamesDouglas', /Douglas/.test(await text(co, 'footer')), await text(co, 'footer'));
  await co.context().close();
  const wi = await open('wi.html#/auctions');
  const tw = await wi.evaluate(() => document.body.innerText);
  check('F73_wiNamesDane', /Dane County/.test(await text(wi, '#pageList')), (await text(wi, '#pageList')).slice(0, 400));
  check('F57_wiFooterNamesDane', /Dane County/.test(await text(wi, 'footer')), await text(wi, 'footer'));
  check('F57_wiNotGreenOnly', !/Wisconsin coverage is Green County's/.test(tw), null);
  await wi.context().close();
  const sc = await open('sc.html#/lands');
  check('F73_scLaftNoAwaitReview', !/await customer-publication review/i.test(await text(sc, '#pageList')), null);
  await sc.context().close();
  const sca = await open('sc.html#/auctions');
  check('F73_scAuctionNamesOconee', /Oconee/.test(await text(sca, '#pageList')), (await text(sca, '#pageList')).slice(0, 400));
  await sca.context().close();
}

// F74: a vendor listing is not "the official county list"; a Parish list is the Parish's.
{
  const tx = await open('tx.html?tier=pro&fields=all#/lands/xtx1', { extra: [LGBS] });
  const w = await text(tx, '.dec-row[data-q="why"]');
  check('F74_txVendorListing', /vendor's listing/.test(w) && !/official county list/.test(w), w);
  await tx.context().close();
  const la = await open('la.html?tier=pro&fields=all#/lands/pla1');
  const wl = await text(la, '.dec-row[data-q="why"]');
  check('F74_laParishList', /official parish list/.test(wl) && !/county list/.test(wl) && !/county \/ clerk/.test(wl), wl);
  await la.context().close();
}

// F19: property-type words become a type filter.
{
  const pg = await open('index.html#/auctions');
  await pg.fill('#globalSearchInput', 'vacant lot under 10000');
  await pg.waitForTimeout(500);
  const dd = await text(pg, '.global-search');
  check('F19_dropdownReadsType', /Property type Vacant Lot/.test(dd) && !/No Florida property/.test(dd), dd.slice(0, 300));
  await pg.press('#globalSearchInput', 'Enter');
  await pg.waitForTimeout(900);
  const main = await text(pg, '#main');
  check('F19_vacantLotsListed', /12 Searchable Blvd/.test(main), main.slice(0, 400));
  // Place and street words are not type words.
  const parsed = await pg.evaluate(() => ['land o lakes', 'land bank', 'commercial blvd', 'lots 4-6', 'office'].map(q => {
    const n = window.__tdwParseNaturalQuery(q, []); return [q, n.type]; }));
  check('F19_placeWordsNotTypes', parsed.every(([, t]) => !t), parsed);
  await pg.context().close();
}
// F19 (review): no type filter outside Florida - the customer's own word stays the text.
{
  const TXRES = Object.assign({}, LGBS, { id: 'xtx2', case_no: '000016000777', parcel: '21DC-TX-00777', address: 'TRACT 7, Liberty, TX', prop_type: 'Residential' });
  const pg = await open('tx.html#/lands', { extra: [LGBS, TXRES] });
  const n = await pg.evaluate(() => window.__tdwParseNaturalQuery('residential sunrise', ['Liberty']));
  check('F19_txNoTypeBucket', !n.type && n.text === 'residential sunrise', n);
  await pg.fill('#globalSearchInput', 'residential'); await pg.waitForTimeout(400); await pg.press('#globalSearchInput', 'Enter');
  await pg.waitForTimeout(700);
  const m = await text(pg, '#main');
  check('F19_txOwnWordMatchesPropType', /TRACT 7/.test(m) && !/TRACT 9/.test(m), m.slice(0, 400));
  // A short fragment never pulls in a whole type class.
  await pg.fill('#globalSearchInput', 'res'); await pg.waitForTimeout(400); await pg.press('#globalSearchInput', 'Enter');
  await pg.waitForTimeout(700);
  check('F19_shortFragmentNoTypeMatch', !/TRACT 7/.test(await text(pg, '#main')), (await text(pg, '#main')).slice(0, 300));
  await pg.context().close();
}
// F19 (review): a structured query naming no type keeps the customer's type chips.
{
  const pg = await open('index.html#/auctions');
  const before = await pg.evaluate(() => { const c = document.querySelectorAll('#typeChips .chip.on, #typeChips [aria-pressed="true"]').length; return c; });
  await pg.evaluate(() => { const el = document.querySelector('#typeChips .chipx'); if (el) el.click(); });
  await pg.waitForTimeout(300);
  const narrowed = await pg.evaluate(() => document.querySelectorAll('#typeChips .chip.on, #typeChips [aria-pressed="true"]').length);
  await pg.fill('#globalSearchInput', 'auctions under 10000');
  await pg.waitForTimeout(500);
  await pg.press('#globalSearchInput', 'Enter');
  await pg.waitForTimeout(900);
  const after = await pg.evaluate(() => document.querySelectorAll('#typeChips .chip.on, #typeChips [aria-pressed="true"]').length);
  check('F19_typeChipsKept', narrowed !== before && after === narrowed, { before, narrowed, after });
  await pg.context().close();
}

// F61: Home's sale-day entry selects the county in the controls and that day only.
{
  const pg = await open('index.html#/dashboard');
  const ev = pg.locator('#homeUpcomingSales .desk-event').first();
  const county = await ev.getAttribute('data-county');
  const date = await ev.getAttribute('data-date');
  await ev.click();
  await pg.waitForTimeout(900);
  const r = await pg.evaluate(() => ({ quick: document.getElementById('countyQuick') && document.getElementById('countyQuick').value,
    from: (document.getElementById('saleFromFilter') || {}).value, hash: location.hash }));
  check('F61_countyQuickFollows', r.quick === county, { r, county });
  check('F61_saleDayOnly', !!date && r.from === date, { r, date });
  // (review) the sale-day range belongs to the Auctions ledger: switching ledger drops it.
  await pg.evaluate(() => { document.querySelector('[data-nav-ledger="laft"], #hdrNav [data-ledger="laft"], #ledgerTabs [data-ledger="laft"]').click(); });
  await pg.waitForTimeout(700);
  const r2 = await pg.evaluate(() => (document.getElementById('saleFromFilter') || {}).value);
  check('F61_rangeDroppedOnLedgerChange', r2 === '', r2);
  // (review) an entry with no date never wipes a range the customer set.
  await pg.evaluate(() => {
    const f = document.getElementById('saleFromFilter'); f.value = '2027-01-01'; f.dispatchEvent(new Event('change', { bubbles: true }));
    const b = document.createElement('button'); b.dataset.action = 'dossierlist'; b.dataset.county = 'Duval'; b.dataset.ledger = 'auction'; document.body.appendChild(b); b.click(); b.remove();
  });
  await pg.waitForTimeout(700);
  const r3 = await pg.evaluate(() => (document.getElementById('saleFromFilter') || {}).value);
  check('F61_noDateKeepsUserRange', r3 === '2027-01-01', r3);
  await pg.context().close();
}

// F62: the state picker asks only for CURRENT rows.
{
  const pg = await open('index.html#/dashboard');
  await pg.evaluate(() => { window.__stubProbeLog = []; });
  const card = pg.locator('#homeStatesCard');
  if (await card.count()) { await card.click(); await pg.waitForTimeout(1500); }
  const log = await pg.evaluate(() => window.__stubProbeLog || []);
  const auc = log.filter(l => l.filters.some(f => f[0] === 'source' && f[1] === 'auction'));
  check('F62_probeExcludesClosed', auc.length > 0 && auc.every(l => /status\.is\.null,status\.not\.in\.\(dropped,sold,notfound,closed\)/.test(l.or)), log.slice(0, 2));
  check('F62_probeAuctionSaleNotPast', auc.length > 0 && auc.every(l => /sale_date\.is\.null,sale_date\.gte\./.test(l.or)), auc.slice(0, 2));
  await pg.context().close();
}

// F97: one search box on Home (desktop).
{
  const pg = await open('index.html#/dashboard');
  const d = await pg.evaluate(() => { const e = document.getElementById('globalSearch'); return e ? { hidden: e.hidden, display: getComputedStyle(e).display } : null; });
  check('F97_headerSearchHiddenOnHome', !d || (d.hidden && d.display === 'none'), d);
  await pg.context().close();
}

// F98: the rules page's tab title.
{
  const pg = await open('index.html#/rules');
  const t = await pg.title();
  check('F98_rulesTitle', /^State rules/.test(t), t);
  await pg.context().close();
}

// F18 / F102: unknown county names and state switches.
{
  const pg = await open('index.html#/county/Nowhere');
  const r = await pg.evaluate(() => ({ hash: location.hash, note: (document.querySelector('.cty-notfound') || {}).textContent || '' }));
  check('F102_unknownCountyFallsBackToIndex', r.hash === '#/counties' && /Nowhere/.test(r.note), r);
  await pg.goto(root + 'index.html#/county/Harris', { waitUntil: 'networkidle' });
  await pg.reload({ waitUntil: 'networkidle' }); await pg.waitForTimeout(1300);
  check('F18_otherStatesCountyNotAPage', await pg.evaluate(() => location.hash === '#/counties' && !/Harris County/.test((document.querySelector('#pageCounty h1') || {}).textContent || '')), await pg.evaluate(() => location.hash));
  await pg.context().close();
  const rl = await open('index.html#/rules?county=Nowhere');
  const rr = await rl.evaluate(() => ({ hash: location.hash, note: (document.querySelector('.cty-notfound') || {}).textContent || '' }));
  check('F18_unknownRulesCountyStatewide', rr.hash === '#/rules' && /statewide/.test(rr.note), rr);
  await rl.context().close();
  const real = await open('index.html#/county/Duval');
  check('F18_realCountyStillOpens', await real.evaluate(() => location.hash === '#/county/Duval' && !document.querySelector('.cty-notfound')), await real.evaluate(() => location.hash));
  await real.context().close();
  const tx = await open('tx.html#/county/Angelina');
  check('F18_txCountyOpens', await tx.evaluate(() => location.hash === '#/county/Angelina'), await tx.evaluate(() => location.hash));
  const sel = tx.locator('#stateSelect');
  if (await sel.count()) {
    await Promise.all([tx.waitForNavigation({ waitUntil: 'networkidle' }).catch(() => null), sel.selectOption('FL')]);
    await tx.waitForTimeout(1300);
    const u = tx.url();
    check('F18_stateSwitchDropsCounty', /index\.html/.test(u) && /#\/counties$/.test(u) && !(await tx.locator('.cty-notfound').count()), u);
  } else check('F18_stateSelectPresent', false, null);
  await tx.context().close();
  const bad = await open('index.html#/auctions/doesnotexist');
  await bad.waitForTimeout(1500);
  const toast = await bad.evaluate(() => (document.getElementById('errToast') || {}).textContent || '');
  check('F102_unknownRecordSaysSo', /no longer listed/.test(toast), toast);
  await bad.context().close();
  // (review) a ledger that failed to load is never "no longer listed".
  const fl = await open('index.html?failpage=lien:0#/auctions/doesnotexist');
  await fl.waitForTimeout(4000);
  const t2 = await fl.evaluate(() => (document.getElementById('errToast') || {}).textContent || '');
  check('F102_failedLoadNotNoLongerListed', !/no longer listed/.test(t2) && /could not be opened/.test(t2), t2);
  await fl.context().close();
}

check('noPageErrors', errs.length === 0, errs.slice(0, 5));
await b.close();
console.log(fail ? `FAIL: ${fail} check(s)` : 'PASS: all guided-home-copy checks');
process.exit(fail ? 1 : 0);
