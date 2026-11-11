// List cards: the tilted MapTiler view on hover or tap (2026-11-10, owner).
//  - With no MapTiler key no card gets a "Tilt view" button and nothing loads.
//  - With a key, a card whose record has coordinates gets the button; a card
//    without coordinates does not.
//  - Pressing it mounts ONE non-interactive map in that card's picture, asked
//    for with tilt, the fly-in from the United States and the credit overlay;
//    the card's own click is not triggered.
//  - Pressing the map's "Photo" button puts the aerial picture back.
//  - A second card's button releases the first card's map (one at a time).
//  - A mouse resting on a picture starts the view; leaving ends it.
//  - map-3d.js usFitZoom fits the country to the map's width.
// Usage: BASE_URL=http://localhost:9202/index.html node tests/audit/card-tilt.mjs
import { chromium } from 'playwright';
import fs from 'fs';
const BASE = process.env.BASE_URL || 'http://localhost:9202/index.html';
const exe = '/opt/pw-browsers/chromium';
const b = await chromium.launch(fs.existsSync(exe) ? { executablePath: exe } : {});
let fail = 0;
const check = (name, ok, got) => { console.log((ok ? 'PASS ' : 'FAIL ') + name + (ok ? '' : ' -> ' + JSON.stringify(got))); if (!ok) fail++; };
const errs = [];
const DESK = { width: 1440, height: 900 };

const STUB = `export async function mountGisMap(el, o) {
  window.__cardMounts = (window.__cardMounts || []).concat([{ pid: String(o.propertyId), tilt: o.tilt, flyIn: o.flyIn, interactive: o.interactive, creditOverlay: o.creditOverlay, fetcher: typeof o.boundaryFetcher }]);
  const before = el.innerHTML; el.innerHTML = '<div class="m3d-gis-canvas">map</div>'; el.classList.add('m3d-gis');
  return { status: 'ready', outline: false, tilted: true, map: { easeTo() {} }, destroy: () => { window.__cardDestroys = (window.__cardDestroys || 0) + 1; el.innerHTML = before; el.classList.remove('m3d-gis'); } };
}`;

async function page(withKey) {
  const ctx = await b.newContext({ viewport: DESK, serviceWorkers: 'block' });
  const pg = await ctx.newPage();
  pg.on('pageerror', e => errs.push((withKey ? 'key: ' : 'nokey: ') + e.message));
  if (withKey) {
    await pg.route('**/config.js', async route => {
      const res = await route.fetch();
      const body = (await res.text()) + '\n;window.TDW_CONFIG = Object.assign(window.TDW_CONFIG || {}, { maptilerKey: "test-key" });';
      await route.fulfill({ response: res, body, headers: Object.assign({}, res.headers(), { 'content-type': 'application/javascript' }) });
    });
    await pg.route('**/map-3d.js', route => route.fulfill({ status: 200, contentType: 'application/javascript', body: STUB }));
  }
  await pg.goto(BASE + '?look=classic#/auctions', { waitUntil: 'networkidle' });
  await pg.waitForTimeout(600);
  await pg.evaluate(() => document.querySelectorAll('#main details').forEach(d => { d.open = true; }));
  await pg.waitForTimeout(300);
  return { ctx, pg };
}

// ---- no key: no button, nothing asked for
{
  const { ctx, pg } = await page(false);
  const st = await pg.evaluate(() => ({ photos: document.querySelectorAll('#main .prop-card-photo').length, btns: document.querySelectorAll('.pc-tilt-btn').length }));
  check('no-key-no-button', st.photos > 0 && st.btns === 0, st);
  await ctx.close();
}

// ---- with a key
{
  const { ctx, pg } = await page(true);
  const st = await pg.evaluate(() => {
    const hosts = [...document.querySelectorAll('#main .prop-card[data-pid] .prop-card-photo')];
    const withBtn = hosts.filter(h => h.querySelector(':scope > .pc-tilt-btn')).map(h => h.closest('[data-pid]').dataset.pid);
    const without = hosts.filter(h => !h.querySelector(':scope > .pc-tilt-btn')).map(h => h.closest('[data-pid]').dataset.pid);
    return { withBtn, without, label: (document.querySelector('.pc-tilt-btn') || {}).textContent };
  });
  check('button-only-on-cards-with-coordinates', st.withBtn.includes('p5') && st.without.length > 0 && st.label === 'Tilt view', st);

  // Press: one map, the right options, the card's own click not triggered.
  const before = await pg.evaluate(() => ({ modal: !document.getElementById('detailModal').hidden, panel: document.getElementById('detailPanel').innerText.length }));
  await pg.locator('#main .prop-card[data-pid="p5"] .prop-card-photo > .pc-tilt-btn').click();
  await pg.waitForTimeout(500);
  const on = await pg.evaluate(() => {
    const h = document.querySelector('#main .prop-card[data-pid="p5"] .prop-card-photo');
    const btn = h.querySelector('.pc-tilt-btn');
    return { state: h.dataset.cardLive, canvas: !!h.querySelector('.m3d-gis-canvas'), btn: btn && btn.textContent, pressed: btn && btn.getAttribute('aria-pressed'),
      mounts: window.__cardMounts || [], live: window.__tdwCardLive(), modal: !document.getElementById('detailModal').hidden, panel: document.getElementById('detailPanel').innerText.length };
  });
  const m = on.mounts[0] || {};
  check('press-mounts-one-tilted-fly-in-map', on.state === 'ready' && on.canvas && on.btn === 'Photo' && on.pressed === 'true' && on.mounts.length === 1
    && m.pid === 'p5' && m.tilt === true && m.flyIn === true && m.interactive === false && m.creditOverlay === true && m.fetcher === 'function' && on.live.ready && on.live.sticky, on);
  check('press-does-not-open-the-property', on.modal === before.modal && on.panel === before.panel, { before, on: { modal: on.modal, panel: on.panel } });

  // Photo: the aerial comes back, the map is released.
  await pg.locator('#main .prop-card[data-pid="p5"] .prop-card-photo > .pc-tilt-btn').click();
  await pg.waitForTimeout(300);
  const off = await pg.evaluate(() => {
    const h = document.querySelector('#main .prop-card[data-pid="p5"] .prop-card-photo');
    const btn = h.querySelector('.pc-tilt-btn');
    return { state: h.dataset.cardLive || null, canvas: !!h.querySelector('.m3d-gis-canvas'), btn: btn && btn.textContent, destroys: window.__cardDestroys || 0, live: window.__tdwCardLive() };
  });
  check('photo-button-restores-the-picture', off.state === null && !off.canvas && off.btn === 'Tilt view' && off.destroys === 1 && !off.live.host, off);

  // A second card releases the first: one live card map at a time.
  const pids = st.withBtn.slice(0, 2);
  if (pids.length === 2) {
    for (const pid of pids) { await pg.locator(`#main .prop-card[data-pid="${pid}"] .prop-card-photo > .pc-tilt-btn`).click(); await pg.waitForTimeout(350); }
    const two = await pg.evaluate(() => ({ canvases: document.querySelectorAll('#main .prop-card-photo .m3d-gis-canvas').length, destroys: window.__cardDestroys || 0 }));
    check('one-card-map-at-a-time', two.canvases === 1 && two.destroys === 2, two);
    await pg.evaluate(() => { const bt = document.querySelector('#main .prop-card-photo.m3d-gis .pc-tilt-btn'); if (bt) bt.click(); });
    await pg.waitForTimeout(250);
  } else check('one-card-map-at-a-time', false, { note: 'fixture has fewer than two cards with coordinates', pids });

  // Hover (a mouse): resting on the picture starts it, leaving ends it.
  const host = pg.locator('#main .prop-card[data-pid="p5"] .prop-card-photo');
  await host.scrollIntoViewIfNeeded();
  const n0 = await pg.evaluate(() => (window.__cardMounts || []).length);
  // Start from outside: the last button press left the pointer on a picture.
  await pg.mouse.move(5, 5);
  await pg.waitForTimeout(200);
  const box = await host.boundingBox();
  await pg.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await pg.waitForTimeout(900);
  const hov = await pg.evaluate(() => ({ canvas: !!document.querySelector('#main .prop-card[data-pid="p5"] .prop-card-photo .m3d-gis-canvas'), n: (window.__cardMounts || []).length, live: window.__tdwCardLive() }));
  await pg.mouse.move(5, 5);
  await pg.waitForTimeout(400);
  const left = await pg.evaluate(() => ({ canvas: !!document.querySelector('#main .prop-card[data-pid="p5"] .prop-card-photo .m3d-gis-canvas'), live: window.__tdwCardLive() }));
  check('hover-starts-and-leaving-ends', hov.canvas && hov.n === n0 + 1 && !hov.live.sticky && !left.canvas && !left.live.host, { hov, left, n0 });
  await ctx.close();
}

// ---- the real module: the country fits the map's width
{
  const pg = await b.newPage({ viewport: DESK });
  await pg.goto(BASE, { waitUntil: 'domcontentloaded' });
  const z = await pg.evaluate(async () => { const m = await import('./map-3d.js'); return { a: m.usFitZoom(300), c: m.usFitZoom(1200), bad: m.usFitZoom(0), center: m.US_CENTER, ms: m.FLY_IN_MS }; });
  check('us-fit-zoom', z.a > 1.5 && z.a < 2.2 && z.c > z.a && z.c <= 4 && z.bad >= 1 && z.center[0] < -90 && z.center[1] > 35 && z.ms >= 3000, z);
  await pg.close();
}

await b.close();
if (errs.length) { console.log('PAGE ERRORS:\n' + errs.join('\n')); fail++; }
console.log(fail ? `${fail} FAILED` : 'ALL PASS');
process.exit(fail ? 1 : 0);
