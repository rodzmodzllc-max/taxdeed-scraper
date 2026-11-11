// Owner, 2026-11-11: "On the mobile version the open record the open source
// link should stay floating so you can click as you scroll through the record
// and we still need to make sure the link takes you directly to that property
// link not the search page."
//  - phone: one bar at the foot of the record sheet carries the source link
//    and stays on screen at every scroll position;
//  - the link is the property's own page whenever the row carries one
//    (url_auction_kind = property, or a verified property-scope acquisition
//    page); a list / sale-day page is used only when nothing else is on file,
//    and then it says what to look for there;
//  - the Free preview (address and source withheld) gets no bar; desktop keeps
//    the page's own button.
import { chromium } from 'playwright';
import fs from 'fs';
const BASE = (process.env.BASE_URL || 'http://localhost:8934/index.html').replace(/\/$/, '/index.html');
const exe = '/opt/pw-browsers/chromium';
const b = await chromium.launch(fs.existsSync(exe) ? { executablePath: exe } : {});
let fail = 0;
const check = (name, ok, got) => { console.log((ok ? 'PASS ' : 'FAIL ') + name + (ok ? '' : ' -> ' + JSON.stringify(got))); if (!ok) fail++; };
const errs = [];
const pageFor = st => BASE.replace(/index\.html$/, st === 'FL' ? 'index.html' : st.toLowerCase() + '.html');
const PHONE = { width: 390, height: 844 }, DESK = { width: 1400, height: 900 };

// A land-bank row whose listing link is the portal's landing page and whose
// verified acquisition page is the property's own page (production shape).
const TN = { id: '4c2e11cd-e7cc-45d2-83f4-4d0642bcd03d', source: 'laft', county: 'Shelby', case_no: '03510000000270', parcel: '03510000000270', address: '0 RAYBURN', bid: 1000, assessed: 3000, market: null, status: 'active', state: 'TN', ledger_type: 'buy', harvester_source: 'tn_shelby_landbank', source_id: 'tn_shelby_landbank', land_use: 'Residential Vacant', url_auction: 'https://public-sctn.epropertyplus.com/landmgmtpub/app/base/landing', url_auction_kind: 'county', purchase_url: 'https://public-sctn.epropertyplus.com/property/03510000000270', purchase_url_kind: 'online_purchase', purchase_amount: 1000, purchase_amount_kind: 'PUBLISHED_AMOUNT_KIND_UNSPECIFIED', last_seen_at: '2026-11-02T12:46:59+00:00', publication_status: 'APPROVED', inventory_status: 'available_otc', purchase_path_type: 'direct_property_url', purchase_path_scope: 'property', purchase_path_observed_on: '2026-10-25', otc_provenance: { adapter: 'epropertyplus', source_id: 'tn_shelby_landbank', acquisition: { mode: 'online', channels: ['online'], observed_on: '2026-10-25' }, purchase_path_observed_on: '2026-10-25' } };
// An auction row whose listing link the database marks as a property page.
const PROP = { id: 'srcprop1', source: 'auction', state: 'FL', county: 'Leon', case_no: 'SP-1', parcel: '7781', address: '9 Direct Ln', bid: 2500, status: 'active', sale_date: new Date(Date.now() + 12 * 864e5).toISOString().slice(0, 10), ledger_type: 'auctions', url_auction: 'https://auctions.example.gov/item/7781', url_auction_kind: 'property', last_seen_at: new Date().toISOString(), updated_at: new Date().toISOString(), lien_level: 'unscreened', publication_status: 'APPROVED' };

async function open(url, vp, rows) {
  const ctx = await b.newContext({ viewport: vp, serviceWorkers: 'block' });
  const pg = await ctx.newPage();
  pg.on('pageerror', e => errs.push(url + ': ' + e.message));
  if (rows) await pg.addInitScript(rs => { window.__stubExtraRows = rs; }, rows);
  await pg.goto(url, { waitUntil: 'networkidle' });
  await pg.waitForSelector('#detailModalInner [data-section], #detailPanel [data-section], #detailModalInner .tier-free, #detailModalInner .tier-guided', { timeout: 10000 }).catch(() => {});
  await pg.waitForTimeout(500);
  return { ctx, pg };
}
const bar = pg => pg.evaluate(() => {
  const inner = document.getElementById('detailModalInner'), f = inner && inner.querySelector(':scope > .detail-float');
  if (!f) return null;
  const a = f.querySelector('a[data-float-link]'), ib = inner.getBoundingClientRect(), fb = f.getBoundingClientRect(), ab = a.getBoundingClientRect();
  const hit = document.elementFromPoint(ab.left + ab.width / 2, ab.top + ab.height / 2);
  const close = inner.querySelector('.detail-close'), cb = close ? close.getBoundingClientRect() : null;
  return { shown: getComputedStyle(f).display !== 'none', pos: getComputedStyle(f).position, scope: f.dataset.floatScope, href: a.getAttribute('href'), label: a.textContent.replace(/\s+/g, ' ').trim(),
    note: (f.querySelector('.detail-float-note') || {}).textContent || '', target: a.target, rel: a.rel,
    atFoot: Math.abs(fb.bottom - ib.bottom) <= 2 && fb.left <= ib.left + 2 && fb.right >= ib.right - 2, tappable: !!hit && a.contains(hit), tall: ab.height >= 44,
    clearOfClose: !cb || cb.bottom <= fb.top || cb.top >= fb.bottom, scrollTop: Math.round(inner.scrollTop), max: inner.scrollHeight - inner.clientHeight };
});
const scrollTo = (pg, frac) => pg.evaluate(fr => { const i = document.getElementById('detailModalInner'); i.scrollTop = Math.round((i.scrollHeight - i.clientHeight) * fr); }, frac);

// ---- phone, a sale-day listing (no property page on file): the bar floats and says what to look for
{
  const { ctx, pg } = await open(BASE + '?look=merged#/auctions/p5', PHONE);
  const top = await bar(pg);
  check('phoneBarShownSticky', !!top && top.shown && top.pos === 'sticky' && top.atFoot && top.tappable && top.tall && top.clearOfClose, top);
  check('phoneBarOpensInNewTab', !!top && top.target === '_blank' && /noopener/.test(top.rel), top);
  check('listScopeNamedAsAListWithWhatToFind', !!top && top.scope === 'list' && /^View sale listing for /.test(top.label) && /not a page for this property/.test(top.note) && /case D-1/.test(top.note), top);
  const seen = [];
  for (const fr of [0.25, 0.5, 0.75, 1]) { await scrollTo(pg, fr); await pg.waitForTimeout(150); seen.push(await bar(pg)); }
  check('phoneBarStaysWhileScrolling', seen.every(s => s && s.atFoot && s.tappable) && seen[3].scrollTop >= seen[3].max - 2 && seen[1].scrollTop > 300, seen.map(s => s && [s.scrollTop, s.atFoot, s.tappable]));
  // At the very end the bar is in the page flow: nothing of the record is left under it.
  const last = await pg.evaluate(() => { const i = document.getElementById('detailModalInner'), f = i.querySelector(':scope > .detail-float'); const prev = f.previousElementSibling; let e = prev; while (e && !e.offsetParent) e = e.previousElementSibling; return e ? e.getBoundingClientRect().bottom <= f.getBoundingClientRect().top + 1 : true; });
  check('recordEndNotCoveredByBar', last, last);
  await ctx.close();
}

// ---- the property's own page wins over the portal's landing page
{
  const { ctx, pg } = await open(pageFor('TN') + '?look=merged#/lands/' + TN.id, PHONE, [TN]);
  const got = await bar(pg);
  check('propertyPageWinsOverLanding', !!got && got.shown && got.atFoot && got.tappable && got.scope === 'property' && got.href === TN.purchase_url && got.note === '' && /this property/i.test(got.label), got);
  const cta = await pg.evaluate(() => Array.from(document.querySelectorAll('#detailModalInner a.detail-cta')).map(a => a.getAttribute('href')));
  check('recordButtonNeverTheLandingPage', cta.length > 0 && cta.every(h => h === TN.purchase_url), cta);
  await ctx.close();
}

// ---- a listing link the database marks as a property page
{
  const { ctx, pg } = await open(BASE + '?look=merged#/auctions/' + PROP.id, PHONE, [PROP]);
  const got = await bar(pg);
  check('propertyKindListingUsed', !!got && got.scope === 'property' && got.href === PROP.url_auction && got.label.startsWith('View property listing') && got.note === '', got);
  await ctx.close();
}

// ---- the helper never builds a URL: every answer is a link the row carries
{
  const { ctx, pg } = await open(BASE + '?look=merged#/auctions', DESK, [PROP]);
  const got = await pg.evaluate(() => (window.__tdwLastRender.rows || []).map(r => { const s = window.__tdwRecordSourceLink(r.id); const own = [r.url_auction, r.purchase_url, r.document_url, r.list_url].concat(r.otc_provenance ? [r.otc_provenance.document_url, r.otc_provenance.list_url, r.otc_provenance.purchase_evidence_url] : []).filter(Boolean); return s ? own.includes(s.href) : true; }));
  check('sourceLinkIsAlwaysALinkOnTheRow', got.length > 0 && got.every(Boolean), got);
  await ctx.close();
}

// ---- Free preview: address and source are withheld, so no bar
{
  const { ctx, pg } = await open(BASE + '?look=merged&tier=free#/auctions/p5', PHONE);
  const got = await pg.evaluate(() => ({ free: !!document.querySelector('#detailModalInner .tier-free'), bar: !!document.querySelector('#detailModalInner .detail-float'), links: document.querySelectorAll('#detailModalInner a[data-float-link]').length }));
  check('freePreviewHasNoSourceBar', got.free && !got.bar && got.links === 0, got);
  await ctx.close();
}

// ---- desktop: no floating bar (the page's own button and the side panel are in reach)
{
  const { ctx, pg } = await open(BASE + '?look=merged#/auctions/p5', DESK);
  const got = await pg.evaluate(() => Array.from(document.querySelectorAll('.detail-float')).map(f => getComputedStyle(f).display));
  check('desktopHasNoFloatingBar', got.every(d => d === 'none'), got);
  await ctx.close();
}

check('noPageErrors', errs.length === 0, errs);
await b.close();
console.log(fail ? fail + ' FAILED' : 'ALL PASS');
process.exit(fail ? 1 : 0);
