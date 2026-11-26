// MRV - Marc Research Value (owner, 2026-11-25), and no case number on the
// card face. The MRV is the median of the references on file: the county
// value, TAXACQ comparables (same county + land use, >= 5 with a value and a
// size) and licensed estimates (property_value_estimates, migration 045;
// stub ?mrv=demo). It is shown only with at least one reference besides the
// county value, and its (i) names the references - never an individual
// estimate's figure ("present a median price, not the exact Zestimates").
import { chromium } from 'playwright';
import fs from 'fs';
const BASE = process.env.BASE_URL || 'http://localhost:8934/index.html';
const root = BASE.replace(/[^/]*$/, '');
const exe = '/opt/pw-browsers/chromium';
const b = await chromium.launch(fs.existsSync(exe) ? { executablePath: exe } : {});
let fail = 0;
const check = (name, ok, got) => { console.log((ok ? 'PASS ' : 'FAIL ') + name + (ok ? '' : ' -> ' + JSON.stringify(got))); if (!ok) fail++; };
const errors = [];

async function open(path, extra) {
  const pg = await b.newPage({ viewport: { width: 1280, height: 900 } });
  pg.on('pageerror', e => errors.push(path + ': ' + e.message));
  await pg.route(/^https?:\/\/(?!localhost|127\.0\.0\.1)/, r => r.abort());
  if (extra) await pg.addInitScript(r => { window.__stubExtraRows = r; }, extra);
  await pg.goto(root + path, { waitUntil: 'networkidle' });
  await pg.waitForTimeout(2500);
  return pg;
}
const cardMrv = (pg, pid) => pg.evaluate(id => {
  const c = document.querySelector(`.xt-acard[data-pid="${id}"]`);
  const m = c && c.querySelector('.xt-mrv');
  return { card: !!c, mrv: m ? m.querySelector('.mrv-val').textContent : null, sub: m ? m.querySelector('.mrv-sub').textContent : null,
    bubble: m ? m.querySelector('.ib-pop').textContent : null, caseOnFace: c ? /\bCase\b/.test(c.innerText) : null };
}, pid);

// 1. A licensed estimate on file: the card shows the median, the bubble the references only.
{
  const pg = await open('index.html?look=merged&mrv=demo#/lands');
  const r = await cardMrv(pg, 'p3');
  check('mrvShownWithAnEstimate', r.mrv === '$65,500' && r.sub === 'median of 2', r);
  check('mrvBubbleNamesReferences', !!r.bubble && /References: County value.*RentCast/.test(r.bubble), r.bubble);
  check('mrvBubbleShowsNoIndividualFigure', !!r.bubble && !/\$\d/.test(r.bubble), r.bubble);
  check('caseNumberOffTheAvailableCard', r.caseOnFace === false, r);
  await pg.close();
}

// 2. No estimate and no comparables: no MRV (the county value is already on the card).
{
  const pg = await open('index.html?look=merged#/lands');
  const r = await cardMrv(pg, 'p3');
  check('noMrvWithTheCountyValueAlone', r.card && r.mrv === null, r);
  await pg.close();
}

// 3. TAXACQ comparables: six Available lots in one county with the same land
// use, each with a county value and an acreage, give the seventh an MRV.
{
  const now = new Date().toISOString();
  const lot = (i, extra) => Object.assign({ id: 'mc' + i, source: 'laft', ledger_type: 'buy', state: 'FL', county: 'Levy', case_no: 'MC-' + i,
    parcel: '01-' + i, address: (100 + i) + ' Comp Rd', status: 'available', prop_type: 'Vacant Residential', lien_level: 'unscreened', acreage: 1,
    source_id: 'fl_laft_pioneer', inventory_type: 'POST_SALE_FIXED_PRICE', source_authority: 'GOVERNMENT_PLATFORM', purchase_amount: 900, purchase_amount_kind: 'OPENING_BID', list_url: 'https://x',
    market: 10000 + i * 1000, bid: 900, publication_status: 'APPROVED_GRANDFATHERED', last_seen_at: now, updated_at: now, url_auction: 'https://x', url_auction_kind: 'county' }, extra || {});
  const rows = [0, 1, 2, 3, 4, 5].map(i => lot(i)).concat([lot(9, { acreage: 2, market: 30000 })]);
  const pg = await open('index.html?look=merged#/lands', rows);
  const r = await cardMrv(pg, 'mc9');
  // comps: per-acre values 10,000..15,000 -> median 12,500 x 2 acres = 25,000; county 30,000 -> median 27,500
  check('comparablesGiveAnMrv', r.mrv === '$27,500' && r.sub === 'median of 2', r);
  check('comparablesNamedWithTheirCount', !!r.bubble && /TAXACQ comparables \(6 similar properties in Levy County\)/.test(r.bubble), r.bubble);
  const few = await open('index.html?look=merged#/lands', rows.filter(x => !['mc0', 'mc1', 'mc2'].includes(x.id)));
  check('fewerThanFiveComparablesGiveNone', (await cardMrv(few, 'mc9')).mrv === null, await cardMrv(few, 'mc9'));
  await pg.close(); await few.close();
}

// 4. Auctions placard: plain-text MRV (the face is a button), no case number on the face.
{
  const pg = await open('index.html?look=merged&mrv=demo#/auctions');
  const days = await pg.evaluate(() => [...document.querySelectorAll('.xpt-day')].map(d => d.dataset.day));
  let seen = null, caseOnFace = false;
  for (const d of days) {
    await pg.evaluate(dd => document.querySelector(`.xpt-day[data-day="${dd}"]`).click(), d);
    await pg.waitForTimeout(400);
    const r = await pg.evaluate(() => ({ mrv: [...document.querySelectorAll('.xpt-deck .xpt-mrv')].map(e => e.textContent),
      caseOnFace: [...document.querySelectorAll('.xpt-placard .face.front')].some(f => /\bCase\b/.test(f.innerText)) }));
    if (r.mrv.length) seen = r.mrv[0];
    caseOnFace = caseOnFace || r.caseOnFace;
  }
  check('placardShowsTheMrv', seen === 'MRV $120,000 · median of 2', seen);
  check('caseNumberOffThePlacardFace', caseOnFace === false, caseOnFace);
  await pg.close();
}

// 5. The property page shows the MRV too.
{
  const pg = await open('index.html?look=merged&mrv=demo&tier=pro#/lands/p3');
  const r = await pg.evaluate(() => { const m = document.querySelector('#detailModalInner .detail-mrv'); return m ? m.querySelector('.mrv-val').textContent : null; });
  check('recordShowsTheMrv', r === '$65,500', r);
  await pg.close();
}

check('noPageErrors', errors.length === 0, errors);
await b.close();
process.exit(fail ? 1 : 0);
