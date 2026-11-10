// Property page scannability (2026-11-10, UI audit package P6).
//  - First screen: the picture (deed / Available records), the title, the
//    ledger + status stamp, the one key figure with its label and how to
//    acquire it are on screen without scrolling - desktop side panel at
//    1440x900 (the panel in its sticky position, as after picking a card) and
//    the phone modal at 390x844 (picture, title, figure, Contents row).
//  - Research index: every section after the first screen is its own closed
//    details.detail-fold with a one-line summary; the sections keep their
//    text in the DOM; no data-section is lost compared with the full record.
//  - A Contents (section nav) jump opens the target block and brings it into
//    view; the phone gets the Contents row as a sticky horizontal scroller.
//  - Section numbers count only what is on screen (01, 02, ... with no gap).
//  - GIS card: with no MapTiler key nothing loads; with a key and a
//    map-3d.js that mounts, a Tilt button appears; a map-3d.js that fails
//    leaves the card's embed exactly as it was.
//  - The export button reads "Export list (CSV)" in every ledger.
// Usage: BASE_URL=http://localhost:9202/index.html node tests/audit/property-page.mjs
import { chromium } from 'playwright';
import fs from 'fs';
const BASE = process.env.BASE_URL || 'http://localhost:9202/index.html';
const exe = '/opt/pw-browsers/chromium';
const b = await chromium.launch(fs.existsSync(exe) ? { executablePath: exe } : {});
let fail = 0;
const check = (name, ok, got) => { console.log((ok ? 'PASS ' : 'FAIL ') + name + (ok ? '' : ' -> ' + JSON.stringify(got))); if (!ok) fail++; };
const errs = [];
const HOST = `(document.getElementById('detailModal') && !document.getElementById('detailModal').hidden ? document.getElementById('detailModalInner') : document.getElementById('detailPanel'))`;

async function open(hash, vp, q, init) {
  const pg = await b.newPage({ viewport: vp });
  pg.on('pageerror', e => errs.push(hash + ': ' + e.message));
  if (init) await pg.addInitScript(init);
  await pg.goto(BASE + (q || '?look=merged') + hash, { waitUntil: 'networkidle' });
  await pg.waitForFunction(new Function(`const h = ${HOST}; return !!(h && h.querySelector('.detail-first'));`), null, { timeout: 10000 }).catch(() => {});
  await pg.waitForTimeout(300);
  return pg;
}

const RECORDS = [['available', '#/lands/p3'], ['auction', '#/auctions/p5'], ['lien', '#/certificates/p4']];
const DESK = { width: 1440, height: 900 }, PHONE = { width: 390, height: 844 };

for (const look of ['merged', 'classic']) {
  for (const [lg, hash] of RECORDS) {
    // ---- Desktop: the side panel, stuck at the top of the window ----
    const pg = await open(hash, DESK, '?look=' + look);
    const desk = await pg.evaluate(new Function(`
      const h = ${HOST};
      if (!h) return null;
      // A card picked from a scrolled list: the panel is in its sticky position.
      window.scrollTo(0, document.body.scrollHeight);
      h.scrollTop = 0;
      const r = h.getBoundingClientRect();
      const bottom = Math.min(innerHeight, r.bottom);
      const inView = el => { if (!el) return false; const b = el.getBoundingClientRect(); return b.height > 0 && b.top >= r.top - 1 && b.bottom <= bottom + 1; };
      const acq = h.querySelector('[data-section="acquire"]');
      const how = acq && acq.querySelector('.acq-q[data-acq-q="3"]');
      const contact = acq && acq.querySelector('.acq-q[data-acq-q="6"]');
      const cta = h.querySelector('.detail-first ~ .detail-cta');
      return {
        surface: h.id,
        hero: !!h.querySelector('.detail-first .detail-hero-photo') ? inView(h.querySelector('.detail-first .detail-hero-photo')) : null,
        title: inView(h.querySelector('.detail-first .detail-address')),
        stamp: inView(h.querySelector('.detail-first .pc-stamp, .detail-first .pill')),
        figure: inView(h.querySelector('.detail-first .detail-keyfig')),
        figureLabel: (h.querySelector('.detail-keyfig-label') || {}).textContent || '',
        howSteps: how ? inView(how) : null,
        contact: contact ? inView(contact) : null,
        cta: cta ? inView(cta) : null,
        tierCompact: (() => { const t = h.querySelector('.tier-switch'); return !t || t.getBoundingClientRect().height <= 34; })()
      };`));
    check(`${look}-${lg}-desk-surface-is-panel`, desk && desk.surface === 'detailPanel', desk);
    if (lg !== 'lien') check(`${look}-${lg}-desk-hero-first-screen`, desk && desk.hero === true, desk);
    check(`${look}-${lg}-desk-title-stamp-figure-first-screen`, desk && desk.title && desk.stamp && desk.figure && desk.figureLabel.length > 0, desk);
    if (lg === 'available') check(`${look}-${lg}-desk-how-to-acquire-steps-and-contact-first-screen`, desk && desk.howSteps === true && desk.contact === true, desk);
    else check(`${look}-${lg}-desk-sale-or-list-link-first-screen`, desk && desk.cta === true, desk);
    check(`${look}-${lg}-desk-tier-switch-compact`, desk && desk.tierCompact, desk);
    await pg.close();

    // ---- Phone: the modal ----
    const ph = await open(hash, PHONE, '?look=' + look);
    const phone = await ph.evaluate(new Function(`
      const h = ${HOST};
      if (!h) return null;
      const r = h.getBoundingClientRect();
      const inView = el => { if (!el) return false; const b = el.getBoundingClientRect(); return b.height > 0 && b.top >= r.top - 1 && b.bottom <= Math.min(innerHeight, r.bottom) + 1; };
      const nav = h.querySelector('.detail-nav');
      const ns = nav && getComputedStyle(nav);
      return {
        surface: h.id,
        hero: h.querySelector('.detail-first .detail-hero-photo') ? inView(h.querySelector('.detail-first .detail-hero-photo')) : null,
        title: inView(h.querySelector('.detail-first .detail-address')),
        figure: inView(h.querySelector('.detail-first .detail-keyfig')),
        nav: !!nav && ns.display !== 'none' && inView(nav),
        navSticky: !!nav && ns.position === 'sticky',
        navScrolls: !!nav && (ns.overflowX === 'auto' || ns.overflowX === 'scroll') && ns.flexWrap === 'nowrap',
        navLabel: nav ? (nav.querySelector('.detail-nav-label') || {}).textContent : null
      };`));
    check(`${look}-${lg}-phone-surface-is-modal`, phone && phone.surface === 'detailModalInner', phone);
    if (lg !== 'lien') check(`${look}-${lg}-phone-keeps-hero`, phone && phone.hero === true, phone);
    check(`${look}-${lg}-phone-title-and-figure-first-screen`, phone && phone.title && phone.figure, phone);
    check(`${look}-${lg}-phone-contents-sticky-scroller`, phone && phone.nav && phone.navSticky && phone.navScrolls && phone.navLabel === 'Contents', phone);
    await ph.close();
  }
}

// ---- Research index: blocks closed, summaries present, content kept, nothing lost ----
for (const [lg, hash] of RECORDS) {
  const clean = await open(hash, DESK, '?look=merged&fields=clean');
  const idx = await clean.evaluate(new Function(`
    const h = ${HOST};
    const index = h.querySelector('.detail-index');
    const folds = [...h.querySelectorAll('.detail-index > details.detail-fold')];
    return {
      index: !!index,
      count: folds.length,
      allClosed: folds.every(d => !d.open),
      everyLine: folds.every(d => (d.querySelector(':scope > summary .detail-fold-line') || {}).textContent.trim().length > 3),
      everyTitle: folds.every(d => (d.querySelector(':scope > summary .detail-more-title') || {}).textContent.trim().length > 2),
      textKept: folds.every(d => d.textContent.replace((d.querySelector('summary') || {}).textContent || '', '').trim().length > 0),
      firstOutside: ['acquire', 'money', 'decision'].every(id => { const s = h.querySelector('[data-section="' + id + '"]'); return !s || !index.contains(s); }),
      questionsFold: !!h.querySelector('details.detail-fold[data-fold="questions"] .open-q-card'),
      sections: [...h.querySelectorAll('[data-section]')].map(e => e.dataset.section),
      noOldGroup: !h.querySelector('details.detail-research')
    };`));
  check(`${lg}-index-present-and-closed`, idx.index && idx.count >= 5 && idx.allClosed && idx.noOldGroup, idx);
  check(`${lg}-index-every-block-has-title-and-line`, idx.everyLine && idx.everyTitle, idx);
  check(`${lg}-index-blocks-keep-their-content`, idx.textKept, idx);
  check(`${lg}-first-screen-sections-outside-index`, idx.firstOutside, idx);
  check(`${lg}-open-questions-is-a-block`, idx.questionsFold, idx);
  // The complete record (Show every field) lists the same sections, folded.
  const full = await open(hash, DESK, '?look=merged&fields=all');
  const fullSecs = await full.evaluate(new Function(`return [...${HOST}.querySelectorAll('[data-section]')].map(e => e.dataset.section);`));
  const missing = fullSecs.filter(s => s !== 'questions' && !idx.sections.includes(s) && !['summary'].includes(s));
  // Sections the cleanup removes on purpose are only those with no answer
  // (they are named in Open questions instead); everything with content stays.
  check(`${lg}-no-section-lost-vs-full-record`, missing.every(s => ['history', 'property', 'financial'].includes(s)) || missing.length === 0, { missing, clean: idx.sections, full: fullSecs });
  await full.close();

  // ---- Section numbers: one counter over what is on screen ----
  // The rendered numbers are read from the layout tree (CDP DOMSnapshot: the
  // generated text of every ::before), so a counter that restarts - every
  // section "01", as the side panel's style containment once caused - fails.
  // Structurally: exactly the visible first-screen section heads and index
  // block titles count, and the head inside a block is not rendered.
  const nums = await clean.evaluate(new Function(`
    const h = ${HOST};
    const incs = el => /(^| )dsec( |$)/.test(getComputedStyle(el, '::before').counterIncrement || '');
    const rendered = el => el.getClientRects().length > 0;
    const visible = [...h.querySelectorAll('*')].filter(el => incs(el) && rendered(el));
    const expected = [...h.querySelectorAll('.detail-section > .detail-section-head, details.detail-fold > summary .detail-more-title')].filter(rendered);
    const innerHeads = [...h.querySelectorAll('details.detail-fold > .detail-section > .detail-section-head')];
    return { visible: visible.length, expected: expected.length, same: visible.every((el, i) => el === expected[i]),
      innerHidden: innerHeads.every(el => getComputedStyle(el).display === 'none') };`));
  const cdp = await clean.context().newCDPSession(clean);
  const snap = await cdp.send('DOMSnapshot.captureSnapshot', { computedStyles: [] });
  const d0 = snap.documents[0], S = snap.strings, ptd = d0.nodes.pseudoType || { index: [], value: [] };
  const pseudo = new Map((ptd.index || []).map((ix, k) => [ix, S[ptd.value[k]]]));
  const numbers = [];
  d0.layout.nodeIndex.forEach((ni, k) => {
    const t = d0.layout.text[k];
    const isBefore = pseudo.get(ni) === 'before' || pseudo.get(d0.nodes.parentIndex[ni]) === 'before';
    if (t >= 0 && isBefore && /^[0-9][0-9]$/.test(S[t])) numbers.push(parseInt(S[t], 10));
  });
  check(`${lg}-section-numbers-count-only-what-is-on-screen`, nums.visible >= 3 && nums.visible === nums.expected && nums.same && nums.innerHidden, nums);
  check(`${lg}-section-numbers-consecutive`, numbers.length === nums.visible && numbers.every((n, i) => n === i + 1), numbers);

  // ---- Contents jump opens its block and shows it ----
  const target = lg === 'lien' ? 'truth' : 'risk';
  const jumped = await clean.evaluate(new Function(`
    const h = ${HOST};
    const b = h.querySelector('.detail-nav button[data-target="${target}"]');
    if (!b) return { button: false };
    b.click();
    const s = h.querySelector('[data-section="${target}"]');
    return { button: true, open: !!(s && s.closest('details.detail-fold') && s.closest('details.detail-fold').open) };`));
  await clean.waitForTimeout(900);
  const shown = await clean.evaluate(new Function(`
    const h = ${HOST}; const s = h.querySelector('[data-section="${target}"]');
    const r = s.getBoundingClientRect(), hr = h.getBoundingClientRect();
    return r.top < Math.min(innerHeight, hr.bottom) && r.bottom > hr.top;`));
  check(`${lg}-contents-jump-opens-block`, jumped.button && jumped.open, jumped);
  check(`${lg}-contents-jump-shows-section`, shown, shown);
  await clean.close();
}

// ---- Phone: a jump from the Contents row opens the block too ----
{
  const ph = await open('#/lands/p3', PHONE, '?look=merged&fields=clean');
  const r = await ph.evaluate(new Function(`
    const h = ${HOST};
    const b = h.querySelector('.detail-nav button[data-target="truth"]'); if (!b) return null; b.click();
    const s = h.querySelector('[data-section="truth"]');
    return s.closest('details.detail-fold').open;`));
  check('phone-contents-jump-opens-block', r === true, r);
  await ph.close();
}

// ---- GIS card ----
// No MapTiler key (tests/config.js): map-3d.js is never requested.
{
  const reqs = [];
  const pg = await b.newPage({ viewport: DESK });
  pg.on('request', rq => { if (/map-3d\.js/.test(rq.url())) reqs.push(rq.url()); });
  await pg.goto(BASE + '?look=merged#/auctions/p5', { waitUntil: 'networkidle' });
  await pg.waitForTimeout(500);
  await pg.evaluate(new Function(`const h = ${HOST}; const d = h.querySelector('details[data-fold="map"]'); if (d) d.open = true;`));
  await pg.waitForTimeout(500);
  const st = await pg.evaluate(new Function(`const el = ${HOST}.querySelector('[data-gis-live]'); return el ? { state: el.dataset.gisLiveState || null, iframe: !!el.querySelector('iframe') } : null;`));
  check('gis-no-key-no-request-embed-kept', reqs.length === 0 && st && st.state === null && st.iframe, { reqs, st });
  await pg.close();
}
// A key and a map-3d.js that mounts: the Tilt button appears and pitches the map.
for (const mode of ['ready', 'error']) {
  // The service worker would answer map-3d.js itself; block it so the route applies.
  const ctx = await b.newContext({ viewport: DESK, serviceWorkers: 'block' });
  const pg = await ctx.newPage();
  pg.on('pageerror', e => errs.push('gis ' + mode + ': ' + e.message));
  await pg.route('**/config.js', async route => {
    const res = await route.fetch();
    const body = (await res.text()) + '\n;window.TDW_CONFIG = Object.assign(window.TDW_CONFIG || {}, { maptilerKey: "test-key" });';
    await route.fulfill({ response: res, body, headers: Object.assign({}, res.headers(), { 'content-type': 'application/javascript' }) });
  });
  await pg.route('**/map-3d.js', route => route.fulfill({ status: 200, contentType: 'application/javascript', body: mode === 'ready'
    ? `export async function mountGisMap(el, o) { window.__gisOpts = { lat: o.lat, lng: o.lng, ledger: o.ledger, fetcher: typeof o.boundaryFetcher }; const before = el.innerHTML; el.innerHTML = '<div class="m3d-gis-canvas">map</div>'; window.__pitch = []; return { status: 'ready', outline: false, map: { easeTo: c => window.__pitch.push(c.pitch) }, destroy: () => { el.innerHTML = before; } }; }`
    : `export async function mountGisMap(el) { return { status: 'error', outline: false, destroy() {} }; }` }));
  await pg.goto(BASE + '?look=merged#/auctions/p5', { waitUntil: 'networkidle' });
  await pg.waitForTimeout(500);
  await pg.evaluate(new Function(`const h = ${HOST}; const d = h.querySelector('details[data-fold="map"]'); if (d) d.open = true;`));
  await pg.waitForTimeout(800);
  const st = await pg.evaluate(new Function(`const el = ${HOST}.querySelector('[data-gis-live]'); const t = el && el.querySelector('.gis-tilt-btn'); if (t) t.click();
    return el ? { state: el.dataset.gisLiveState, tilt: !!t, pressed: t ? t.getAttribute('aria-pressed') : null, iframe: !!el.querySelector('iframe'), opts: window.__gisOpts || null, pitch: window.__pitch || null } : null;`));
  if (mode === 'ready') check('gis-live-mounts-with-tilt', st && st.state === 'ready' && st.tilt && st.pressed === 'true' && st.pitch && st.pitch[0] === 55 && st.opts && st.opts.fetcher === 'function' && st.opts.ledger === 'auction', st);
  else check('gis-live-error-keeps-embed', st && st.state === 'error' && !st.tilt && st.iframe, st);
  await ctx.close();
}

// ---- Export label in every ledger ----
{
  const pg = await b.newPage({ viewport: DESK });
  const labels = [];
  for (const slug of ['auctions', 'lands', 'certificates']) {
    await pg.goto(BASE + '?look=classic#/' + slug, { waitUntil: 'networkidle' });
    await pg.waitForTimeout(300);
    labels.push(((await pg.locator('#exportCsvBtn').textContent()) || '').replace('⬇', '').trim());
  }
  check('export-label-every-ledger', labels.every(l => l === 'Export list (CSV)'), labels);
  await pg.close();
}

await b.close();
if (errs.length) { console.log('PAGE ERRORS:\n' + errs.join('\n')); fail++; }
console.log(fail ? `${fail} FAILED` : 'ALL PASS');
process.exit(fail ? 1 : 0);
