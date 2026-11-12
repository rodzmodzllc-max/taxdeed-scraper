// Investor sprint (owner, 2026-11-12: "When we're looking at the property
// cards, I want that to be like front and center ... let's work on the
// experienced investors getting up to a 10"). Proves, under the default
// Merged look:
//   1. each county's cards sit in a grid - no sideways scrolling - and the
//      Auctions / Liens looks do not scroll sideways off-screen on a desktop;
//   2. at 1368 x 777 the first card's picture and price are above the fold;
//      "In this list" is a slim strip, not a third of the screen;
//   3. a card title is the street address or "Parcel <n>" over "<County>, FL",
//      never the legal description, never the parcel number twice;
//   4. the card picture carries one small label (+ Tilt view) and one (i)
//      holding its credits - the parcel outline's full credit included;
//   5. plain language on cards, the strip and the record header;
//   6. "Open record" opens the record wide on a desktop, in two columns; a
//      phone keeps its full-screen sheet with the floating source bar;
//   7. statewide map bubbles never overlap and keep exact counts;
//   8. phone (390 x 844) and dark theme: no horizontal overflow, AA text.
// Standalone: BASE_URL=http://localhost:8952/index.html node tests/audit/investor-ten.mjs
import { chromium } from 'playwright';
import fs from 'node:fs';
import { investorRows, LEGAL } from './investor-fixture.mjs';

const BASE_URL = process.env.BASE_URL || 'http://localhost:8934/index.html';
const SANDBOX_CHROMIUM = '/opt/pw-browsers/chromium';
const browser = await chromium.launch(fs.existsSync(SANDBOX_CHROMIUM) ? { executablePath: SANDBOX_CHROMIUM } : {});
let failed = 0;
const check = (name, ok, info) => { console.log(`${ok ? 'PASS' : 'FAIL'} ${name}${ok ? '' : ' :: ' + JSON.stringify(info)}`); if (!ok) failed++; };
const DESK = { width: 1368, height: 777 }, TAB = { width: 820, height: 1180 }, PHONE = { width: 390, height: 844 };

async function open(route, viewport, opts = {}) {
  const ctx = await browser.newContext({ viewport });
  const pg = await ctx.newPage();
  pg.on('pageerror', e => { console.log('pageerror ' + e.message); failed++; });
  await pg.addInitScript(([rows, dark]) => {
    window.__stubExtraRows = rows;
    try { localStorage.removeItem('tdw_experience_v1'); if (dark) localStorage.setItem('tdw_theme', 'dark'); } catch {}
  }, [opts.rows || investorRows(), !!opts.dark]);
  if (opts.naip) {
    await pg.route('**/config.js', async r => { const res = await r.fetch(); await r.fulfill({ response: res, body: (await res.text()).replace('naipLiveImagery: false', 'naipLiveImagery: true') }); });
    await pg.route('https://imagery.nationalmap.gov/**', r => r.fulfill({ status: 200, contentType: 'image/png', body: Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==', 'base64') }));
  }
  await pg.goto(`${BASE_URL}?look=merged${opts.q || ''}#/${route}`, { waitUntil: 'networkidle' });
  await pg.waitForTimeout(opts.wait || 1800);
  return { ctx, pg };
}
const noSideways = pg => pg.evaluate(() => ({ doc: document.documentElement.scrollWidth, vw: window.innerWidth,
  stage: (() => { const s = document.getElementById('xpStage'); return s ? { sw: s.scrollWidth, cw: s.clientWidth } : null; })(),
  wide: [...document.querySelectorAll('#xpStage *')].filter(el => { const r = el.getBoundingClientRect(); return r.width && el.checkVisibility() && (r.right > window.innerWidth + 1 || r.left < -1) && !el.closest('[data-xt-keep="ruler"], .xpt-days, .fan-stage, .xt-grain, svg'); }).map(el => el.className && String(el.className.baseVal ?? el.className)).slice(0, 5) }));

// ---- 1 + 2: grid and above the fold (desktop)
{
  const { ctx, pg } = await open('lands', DESK);
  const g = await pg.evaluate(() => {
    const rails = [...document.querySelectorAll('#xpStage .xt-rail:not(.xt-rail-lazy)')];
    const r0 = rails[0], cards = [...r0.querySelectorAll('.xt-acard')];
    const tops = new Set(cards.slice(0, 4).map(c => Math.round(c.getBoundingClientRect().top)));
    return { rails: rails.length, sideways: rails.filter(r => r.scrollWidth > r.clientWidth + 1).length, cols: getComputedStyle(r0).gridTemplateColumns.split(' ').length,
      firstRowSame: tops.size === 1, overflowX: getComputedStyle(r0).overflowX };
  });
  check('gridNoSidewaysScroll_1368', g.rails >= 3 && g.sideways === 0 && g.overflowX !== 'auto' && g.overflowX !== 'scroll', g);
  check('gridFourAcross_1368', g.cols >= 3 && g.cols <= 4 && g.firstRowSame, g);
  const f = await pg.evaluate(() => {
    const c = document.querySelector('#xpStage .xt-acard'), vis = c.querySelector('.xt-acard-vis'), price = c.querySelector('.xt-fig-main .xt-num');
    const strip = document.querySelector('#detailPanel > .xp-panelsum');
    const sr = strip ? strip.getBoundingClientRect() : null;
    return { photoTop: Math.round(vis.getBoundingClientRect().top), photoBottom: Math.round(vis.getBoundingClientRect().bottom), priceBottom: Math.round(price.getBoundingClientRect().bottom), vh: innerHeight,
      strip: sr && { h: Math.round(sr.height), w: Math.round(sr.width), text: strip.textContent.replace(/\s+/g, ' ').trim() },
      stageW: Math.round(document.getElementById('xpStage').getBoundingClientRect().width) };
  });
  check('firstCardPhotoAndPriceAboveFold_1368x777', f.photoTop > 0 && f.photoBottom < f.vh && f.priceBottom <= f.vh, f);
  check('inThisListIsASlimStrip', !!f.strip && f.strip.h <= 64 && f.strip.w > 900 && f.stageW > 1100, f.strip);
  check('stripKeepsItsContent', !!f.strip && /How to acquire here/.test(f.strip.text) && /Open the first property/.test(f.strip.text) && /\d+ propert/.test(f.strip.text), f.strip && f.strip.text);
  const s = await noSideways(pg);
  check('landsNoHorizontalOverflow_1368', s.doc <= s.vw && s.wide.length === 0, s);
  await ctx.close();
}
for (const [vp, want] of [[TAB, 2], [PHONE, 1]]) {
  const { ctx, pg } = await open('lands', vp);
  const g = await pg.evaluate(() => { const r = document.querySelector('#xpStage .xt-rail:not(.xt-rail-lazy)'); return { cols: getComputedStyle(r).gridTemplateColumns.split(' ').length, sw: r.scrollWidth, cw: r.clientWidth, doc: document.documentElement.scrollWidth, vw: innerWidth }; });
  check(`gridColumns_${vp.width}`, g.cols === want && g.sw <= g.cw + 1 && g.doc <= g.vw, g);
  await ctx.close();
}
for (const route of ['auctions', 'certificates']) {
  const { ctx, pg } = await open(route, DESK);
  const s = await noSideways(pg);
  check(`${route}NoSidewaysOffScreen_1368`, s.doc <= s.vw && s.wide.length === 0 && (!s.stage || s.stage.sw <= s.stage.cw + 1), s);
  const strip = await pg.evaluate(() => { const b = document.querySelector('#detailPanel > .xp-panelsum'); return b ? { h: Math.round(b.getBoundingClientRect().height), w: Math.round(b.getBoundingClientRect().width) } : null; });
  check(`${route}SummaryIsAStrip`, !!strip && strip.h <= 90 && strip.w > 900, strip);
  await ctx.close();
}

// ---- 3 + 5: titles and plain language on the cards
{
  const { ctx, pg } = await open('lands', DESK);
  await pg.evaluate(async () => { for (const h of document.querySelectorAll('#xpStage [data-county-head]')) { h.scrollIntoView(); await new Promise(r => setTimeout(r, 120)); } window.scrollTo(0, 0); });
  await pg.waitForTimeout(400);
  const cards = await pg.evaluate(() => [...document.querySelectorAll('#xpStage .xt-acard')].map(c => ({ id: c.dataset.pid,
    title: c.querySelector('.xt-lot-t').textContent.trim(), where: (c.querySelector('.xt-lot-where') || {}).textContent || '',
    ids: (c.querySelector('.xt-ids') || {}).textContent || '', text: c.innerText })));
  const legalRe = /\bBEG\b|\bFT [NSEW]\b|\bINTER OF\b|\bTWP\b|\bRNG\b/;
  check('noLegalDescriptionTitle', cards.length >= 24 && !cards.some(c => legalRe.test(c.title)), cards.filter(c => legalRe.test(c.title)).map(c => c.title));
  const legal = cards.find(c => c.id === 'inv0-1'), noAddr = cards.find(c => c.id === 'inv0-2'), withAddr = cards.find(c => c.id === 'inv0-0');
  check('legalRowTitledByParcel', !!legal && legal.title === 'Parcel 17921-000-000' && legal.where.trim() === 'Alachua County, FL', legal);
  check('noAddressRowTitledByParcel', !!noAddr && noAddr.title === 'Parcel 17922-000-000' && noAddr.where.trim() === 'Alachua County, FL', noAddr);
  check('streetAddressIsTheTitle', !!withAddr && withAddr.title === '100 Fixture Alachua Rd' && /Parcel # 17920-000-000/.test(withAddr.ids), withAddr);
  const dup = cards.filter(c => { const m = c.text.match(/\d{5}-000-000/g) || []; return m.length > 1; });
  check('parcelNumberNeverTwiceOnACard', dup.length === 0, dup.map(c => c.id));
  check('caseNumberKept', !!legal && /Case INV-0-1/.test(legal.ids), legal && legal.ids);
  const all = cards.map(c => c.text).join('\n');
  check('plainLanguageOnCards', !/over the counter|path not yet verified|verified path|just value|outline source/i.test(all)
    && /Buy directly from the county, no auction/.test(all) && /County market value \(2025\)/i.test(all) && /How to buy: not yet confirmed/i.test(all), all.match(/over the counter|path not yet verified|verified path|just value|outline source/ig));
  const note = await pg.evaluate(() => { const w = document.querySelector('#xpStage .xt-acard .xt-val-info'); return w ? { btn: w.querySelector('.ib-btn').getAttribute('aria-label'), pop: w.querySelector('.ib-pop').textContent } : null; });
  check('marketValueExplained', !!note && /just value/.test(note.pop) && /not an appraisal/.test(note.pop) && /2025/.test(note.pop), note);
  const strip = await pg.evaluate(() => document.querySelector('#detailPanel > .xp-panelsum').textContent);
  check('stripPlainLanguage', /How to buy: not yet confirmed/.test(strip) && !/Not yet verified/.test(strip), strip.replace(/\s+/g, ' '));
  await ctx.close();
}

// ---- 4: one label on the picture; credits behind one (i)
{
  // ?boundary=ok: the stub's own fixture rows with coordinates carry an outline.
  const { ctx, pg } = await open('lands', DESK, { naip: true, q: '&boundary=ok' });
  await pg.evaluate(async () => { for (const h of document.querySelectorAll('#xpStage .prop-card-photo.naip-live')) { h.scrollIntoView({ block: 'center' }); await new Promise(r => setTimeout(r, 150)); } });
  await pg.waitForSelector('#xpStage .prop-card-photo.has-boundary', { timeout: 15000 }).catch(() => {});
  await pg.waitForTimeout(500);
  const pid = await pg.evaluate(() => { const h = document.querySelector('#xpStage .prop-card-photo.has-boundary'); if (h) h.scrollIntoView({ block: 'center' }); return h ? h.closest('[data-pid]').dataset.pid : 'none'; });
  await pg.waitForTimeout(300);
  const ph = await pg.evaluate(pid => {
    const h = document.querySelector(`#xpStage [data-pid="${pid}"] .prop-card-photo`) || document.querySelector('#xpStage .prop-card-photo.naip-live');
    const visibleText = [...h.querySelectorAll(':scope > *')].filter(el => el.checkVisibility() && el.textContent.trim() && !el.matches('.pc-info, .pc-tilt-btn')).map(el => el.textContent.trim());
    const pop = h.querySelector(':scope > .pc-photo-info .ib-pop');
    return { boundary: h.classList.contains('has-boundary'), labels: visibleText, oldButton: !!h.querySelector('.pc-outline-info'), attribShown: !!h.querySelector(':scope > .pb-attrib') && h.querySelector(':scope > .pb-attrib').checkVisibility(),
      infoButtons: h.querySelectorAll(':scope > .pc-info').length, credit: !!(pop && pop.querySelector('[data-pb-credit]')), popText: pop ? pop.textContent.slice(0, 200) : '' };
  }, pid);
  check('photoHasOneLabel', ph.labels.length === 1 && /^Aerial · USDA/.test(ph.labels[0]), ph);
  check('photoCreditsBehindOneInfo', ph.boundary && ph.infoButtons === 1 && !ph.oldButton && !ph.attribShown && ph.credit, { pid, ...ph });
  await pg.click(`#xpStage [data-pid="${pid}"] .pc-photo-info .ib-btn`).catch(() => {});
  const opened = await pg.evaluate(pid => { const p = document.querySelector(`#xpStage [data-pid="${pid}"] .pc-photo-info .ib-pop`); return !!p && p.checkVisibility() && /USDA NAIP/.test(p.textContent) && !!p.querySelector('[data-pb-credit]'); }, pid);
  check('photoInfoOpensToCredits', opened, opened);
  const stored = await pg.evaluate(() => { const h = document.querySelector('#xpStage [data-pid="inv0-4"] .prop-card-photo'); return h ? { cap: h.querySelector('.photo-caption').textContent, full: h.querySelector('.pc-photo-about b').textContent } : null; });
  check('storedAerialShortLabelFullCaptionKept', !!stored && stored.cap === 'Aerial · USDA · 2023' && stored.full === 'Aerial image · USDA NAIP · 2023', stored);
  await ctx.close();
}

// ---- 3 + 5 + 6: the record, wide on a desktop, sheet on a phone
{
  const { ctx, pg } = await open('lands', DESK);
  await pg.click('#xpStage [data-pid="inv0-1"] [data-xt="open"]');
  await pg.waitForTimeout(1200);
  const r = await pg.evaluate(() => {
    const m = document.getElementById('detailModal'), inner = document.getElementById('detailModalInner');
    const cols = inner.querySelector(':scope > .detail-cols'), left = cols && cols.querySelector('.detail-col-main'), right = cols && cols.querySelector('.detail-col-more');
    const lr = left && left.getBoundingClientRect(), rr = right && right.getBoundingClientRect();
    return { open: !m.hidden, w: Math.round(inner.getBoundingClientRect().width), sideBySide: !!(lr && rr && rr.left >= lr.right - 1 && Math.abs(rr.top - lr.top) < 40),
      leftHas: left ? [!!left.querySelector('.detail-first .detail-address'), !!left.querySelector('[data-section="acquire"]')] : null,
      rightSections: right ? right.querySelectorAll('[data-section]').length : 0, panelRecord: !!document.querySelector('#detailPanel .detail-address'),
      title: inner.querySelector('.detail-address').textContent.trim(), published: (inner.querySelector('.detail-addr-published') || {}).textContent || '',
      stamp: (inner.querySelector('.detail-first .pc-stamp') || {}).textContent || '', float: inner.querySelector('.detail-float') ? inner.querySelector('.detail-float').checkVisibility() : null };
  });
  check('recordOpensWideOnDesktop', r.open && r.w >= 1000 && r.w <= 1110 && !r.panelRecord, r);
  check('recordTwoColumns', r.sideBySide && r.leftHas && r.leftHas.every(Boolean) && r.rightSections >= 2, r);
  check('recordTitleNeverLegal', !/BEG|FT S/.test(r.title) && r.published.includes(LEGAL), { title: r.title, published: r.published });
  check('recordHeaderPlainStamp', /^How to buy: (not yet )?confirmed$/.test(r.stamp), r.stamp);
  check('noFloatingBarOnDesktop', r.float === false || r.float === null, r.float);
  await ctx.close();
}
{
  const { ctx, pg } = await open('lands', PHONE);
  await pg.click('#xpStage [data-pid="inv0-0"] [data-xt="open"]');
  await pg.waitForTimeout(1200);
  const r = await pg.evaluate(() => { const inner = document.getElementById('detailModalInner'); const f = inner.querySelector(':scope > .detail-float');
    return { w: Math.round(inner.getBoundingClientRect().width), wide: inner.classList.contains('detail-wide') || !!inner.querySelector('.detail-cols'), float: !!f && f.checkVisibility(), doc: document.documentElement.scrollWidth, vw: innerWidth }; });
  check('phoneKeepsFullScreenSheet', r.w >= 380 && !r.wide, r);
  check('phoneFloatingSourceBarKept', r.float, r);
  await ctx.close();
}

// ---- 7: statewide map bubbles
{
  // Rows across most Florida counties, so the dense middle of the state is crowded.
  const { ctx, pg } = await open('lands', DESK);
  const counties = await pg.evaluate(async () => { const t = await (await fetch('fl-counties.svg')).text(); return [...t.matchAll(/data-county="([^"]+)"/g)].map(m => m[1]); });
  await ctx.close();
  const now = new Date().toISOString();
  const rows = [];
  counties.forEach((county, c) => { const n = 1 + ((c * 7) % 23); for (let i = 0; i < n; i++) rows.push({ id: `map${c}-${i}`, source: 'laft', state: 'FL', county, case_no: `M-${c}-${i}`, parcel: `M${c}${i}`, address: `${i + 1} Map Fixture Rd`, bid: 900, status: 'available', lien_level: 'unscreened', lien_note: '', sale_date: null, url_auction: 'https://x', url_auction_kind: 'county', inventory_type: 'POST_SALE_FIXED_PRICE', source_authority: 'GOVERNMENT_PLATFORM', source_id: 'fl_laft_pioneer', list_url: 'https://x', purchase_amount: 900, purchase_amount_kind: 'OPENING_BID', publication_status: 'APPROVED_GRANDFATHERED', last_seen_at: now, updated_at: now }); });
  for (const vp of [DESK, PHONE]) {
    const o = await open('map', vp, { rows, wait: 2500 });
    const b = await o.pg.evaluate(() => {
      const bs = [...document.querySelectorAll('#exploreMapCanvas .cluster-bubble')].map(g => { const c = g.querySelector('circle:not(.bubble-hit)'); const r = c.getBoundingClientRect(); return { county: g.dataset.county, x: r.left + r.width / 2, y: r.top + r.height / 2, r: r.width / 2, n: Number(g.querySelector('text').textContent),
        tw: g.querySelector('text').getBoundingClientRect().width }; });
      let overlaps = 0; const bad = [];
      for (let i = 0; i < bs.length; i++) for (let j = i + 1; j < bs.length; j++) { const a = bs[i], c = bs[j]; if (Math.hypot(a.x - c.x, a.y - c.y) < a.r + c.r - 0.5) { overlaps++; if (bad.length < 4) bad.push([a.county, c.county]); } }
      return { count: bs.length, overlaps, bad, numbersFit: bs.filter(x => x.tw > x.r * 2 + 1).length, counts: Object.fromEntries(bs.map(x => [x.county, x.n])) };
    });
    const expected = {}; rows.forEach(r => { expected[r.county] = (expected[r.county] || 0) + 1; });
    // The fixture's own Florida rows add to a few counties; every bubble is at least our rows' count and matches the list.
    const listCounts = await o.pg.evaluate(() => { const m = {}; (window.__tdwMapLastRender && window.__tdwMapLastRender.rows || []).forEach(p => { m[p.county] = (m[p.county] || 0) + 1; }); return m; });
    const exact = Object.keys(b.counts).every(k => !Object.keys(listCounts).length || b.counts[k] === listCounts[k]);
    check(`mapBubblesDoNotOverlap_${vp.width}`, b.count >= 40 && b.overlaps === 0, b);
    check(`mapBubbleNumbersFit_${vp.width}`, b.numbersFit === 0, b.numbersFit);
    check(`mapBubbleCountsExact_${vp.width}`, exact && Object.keys(expected).every(k => (b.counts[k] || 0) >= expected[k]), { sample: Object.entries(b.counts).slice(0, 5), listSample: Object.entries(listCounts).slice(0, 5) });
    await o.ctx.close();
  }
}

// ---- 8: phone overflow and dark contrast
for (const route of ['lands', 'auctions', 'certificates', 'map']) {
  const { ctx, pg } = await open(route, PHONE, { dark: true });
  const s = await pg.evaluate(() => ({ doc: document.documentElement.scrollWidth, vw: innerWidth }));
  check(`phoneDarkNoHorizontalOverflow_${route}`, s.doc <= s.vw, s);
  await ctx.close();
}
const AUDIT = `(() => {
  const parse = c => { const m = c.match(/rgba?\\(([^)]+)\\)/); if (!m) return null; const p = m[1].split(/[ ,\\/]+/).filter(Boolean).map(Number); return { r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1 }; };
  const lum = c => { const f = v => { v /= 255; return v <= .03928 ? v / 12.92 : Math.pow((v + .055) / 1.055, 2.4); }; return .2126 * f(c.r) + .7152 * f(c.g) + .0722 * f(c.b); };
  const blend = (t, b) => ({ r: t.r * t.a + b.r * (1 - t.a), g: t.g * t.a + b.g * (1 - t.a), b: t.b * t.a + b.b * (1 - t.a), a: 1 });
  const bgOf = el => { const st = []; for (let e = el; e; e = e.parentElement) { const c = parse(getComputedStyle(e).backgroundColor); if (c && c.a > 0) { st.push(c); if (c.a >= 1) break; } } let base = { r: 255, g: 255, b: 255, a: 1 }; for (let i = st.length - 1; i >= 0; i--) base = blend(st[i], base); return base; };
  const out = [];
  for (const root of document.querySelectorAll('#xpStage, #detailPanel .xp-panelsum, .masthead, #detailModalInner')) for (const el of root.querySelectorAll('*')) {
    if (![...el.childNodes].some(n => n.nodeType === 3 && n.textContent.trim())) continue;
    const r = el.getBoundingClientRect(); if (!r.width || !r.height || r.bottom < 0 || r.top > innerHeight * 3) continue;
    const cs = getComputedStyle(el); if (cs.visibility === 'hidden' || +cs.opacity === 0 || !el.checkVisibility()) continue;
    if (el.closest('[aria-hidden="true"], .ib-pop, .xt-amt-pop, img, svg')) continue;
    const bg = bgOf(el), fg = blend(parse(cs.color), bg);
    const L1 = lum(fg), L2 = lum(bg), ratio = (Math.max(L1, L2) + .05) / (Math.min(L1, L2) + .05);
    const size = parseFloat(cs.fontSize), large = size >= 24 || (+cs.fontWeight >= 700 && size >= 18.66);
    if (ratio < (large ? 3 : 4.5)) out.push({ text: el.textContent.trim().slice(0, 30), ratio: +ratio.toFixed(2) });
  }
  return out;
})()`;
for (const dark of [false, true]) {
  const { ctx, pg } = await open('lands', DESK, { dark });
  const bad = await pg.evaluate(AUDIT);
  check(`contrastAA_${dark ? 'dark' : 'light'}_lands`, bad.length === 0, bad.slice(0, 6));
  await pg.click('#xpStage [data-pid="inv0-0"] [data-xt="open"]');
  await pg.waitForTimeout(1200);
  const badR = await pg.evaluate(AUDIT.replace("'#xpStage, #detailPanel .xp-panelsum, .masthead, #detailModalInner'", "'#detailModalInner .detail-first'"));
  check(`contrastAA_${dark ? 'dark' : 'light'}_recordHeader`, badR.length === 0, badR.slice(0, 6));
  await ctx.close();
}

await browser.close();
console.log(failed ? `FAILED ${failed}` : 'ALL PASS');
process.exit(failed ? 1 : 0);
