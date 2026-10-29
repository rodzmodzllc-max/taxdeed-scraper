// Map peek card (2026-10-29): one compact preview shared by the Outline,
// Google and MapTiler basemaps (explore.js showPreview). Picture first (never
// blank), at most three facts with app.js's own labels, one tap to the
// property, the Watchlist button, never covering the selected pin, never
// scrolling the page, closed by Escape, a swipe down or a tap on empty map.
// Optional: SHOT_DIR=<dir> saves phone / desktop screenshots.
import { chromium } from 'playwright';
import fs from 'fs';
const BASE = process.env.BASE_URL || 'http://localhost:8881/index.html';
const SHOT_DIR = process.env.SHOT_DIR || '';
const exe = '/opt/pw-browsers/chromium';
const b = await chromium.launch(fs.existsSync(exe) ? { executablePath: exe } : {});
let fail = 0;
const check = (name, ok, got) => { console.log((ok ? 'PASS ' : 'FAIL ') + name + (ok ? '' : ' -> ' + JSON.stringify(got))); if (!ok) fail++; };
const PHONE = { width: 390, height: 844 }, DESK = { width: 1440, height: 900 };

async function openMap(vp, county) {
  const pg = await b.newPage({ viewport: vp });
  const errs = [];
  pg.on('pageerror', e => errs.push(e.message));
  await pg.goto(BASE + '#/map', { waitUntil: 'networkidle' });
  await pg.waitForTimeout(800);
  await pg.evaluate(() => { window.__sel = []; window.addEventListener('tdw:mapselection', e => window.__sel.push(e.detail)); });
  if (county) { await pg.selectOption('#mapCountySelect', county); await pg.waitForTimeout(900); }
  return { pg, errs };
}
const shot = async (pg, name) => { if (SHOT_DIR) { fs.mkdirSync(SHOT_DIR, { recursive: true }); await pg.screenshot({ path: `${SHOT_DIR}/${name}.png` }); } };
// The facts the card shows, against app.js's previewFacts() for the same row.
const factsMatch = pg => pg.evaluate(() => {
  const card = document.getElementById('explorePreview');
  const pid = card.dataset.pid;
  const r = window.__tdwMapLastRender;
  const p = r.rows.find(x => String(x.id) === pid);
  const f = r.previewFacts(p);
  const want = [];
  if (f.bid) want.push(f.bidLabel);
  if (f.phase) want.push('Status');
  if (f.value) want.push(f.valueLabel); else if (f.parcel) want.push(f.parcelLabel);
  const got = [...card.querySelectorAll('.mp-fact dt')].map(d => d.childNodes[0].textContent.trim());
  return { ok: got.length >= 1 && got.length <= 3 && JSON.stringify(got) === JSON.stringify(want.slice(0, 3)), got, want };
});
const rect = (pg, sel) => pg.evaluate(s => { const e = document.querySelector(s); if (!e) return null; const r = e.getBoundingClientRect(); return { top: r.top, left: r.left, right: r.right, bottom: r.bottom, width: r.width, height: r.height }; }, sel);
const overlap = (a, c) => !!a && !!c && !(a.right <= c.left || a.left >= c.right || a.bottom <= c.top || a.top >= c.bottom);

// ---- Phone: a geocoded row (p5, Charlotte), picked from its pin ----
{
  const { pg, errs } = await openMap(PHONE, 'Charlotte');
  const y0 = await pg.evaluate(() => window.scrollY);
  await pg.locator('#exploreMapCanvas .map-pin[data-pid="p5"]').click({ force: true });
  await pg.waitForTimeout(1000);
  check('phonePinTapNoPageScroll', (await pg.evaluate(() => window.scrollY)) === y0, await pg.evaluate(() => window.scrollY));
  check('phoneCardInStage', (await pg.locator('#mapStage .explore-map-stage > #explorePreview.mp').count()) === 1, null);
  const media = await rect(pg, '#explorePreview .mp-media');
  check('phoneMediaHasHeight', media && media.height > 60, media);
  check('phoneLocatorWhenNoImage', /^Pinned in Charlotte County$/.test(((await pg.locator('#explorePreview .mp-locator-text').textContent()) || '').trim()), null);
  const fm = await factsMatch(pg);
  check('phoneFactsAreAppLabels', fm.ok, fm);
  check('phoneThirdFactWaitsForWideScreen', await pg.evaluate(() => { const f = document.querySelectorAll('#explorePreview .mp-fact'); return f.length < 3 || getComputedStyle(f[2]).display === 'none'; }), null);
  const card = await rect(pg, '#explorePreview'), stage = await rect(pg, '#mapStage .explore-map-stage');
  check('phoneCardUnder45PctOfStage', card.height < stage.height * 0.45, { card: card.height, stage: stage.height });
  const open = await rect(pg, '#explorePreview .preview-open');
  check('phoneOpenVisibleWithoutScroll', open && open.bottom <= 844 && open.top >= 0 && open.height >= 44, open);
  check('phoneWatchTarget44', ((await rect(pg, '#explorePreview .mp-watch .bid-btn')) || {}).height >= 44, null);
  check('phoneCloseTarget44', ((await rect(pg, '#explorePreview .preview-close')) || {}).height >= 44, null);
  const pin = await rect(pg, '#exploreMapCanvas .map-pin.sel path');
  check('phonePinClearOfCard', pin && !overlap(pin, card), { pin, card });
  const sel = await pg.evaluate(() => window.__sel[window.__sel.length - 1]);
  check('phoneSelectionCarriesBottomInset', sel && sel.pid === 'p5' && sel.inset && sel.inset.bottom > 0 && !sel.inset.left, sel);
  check('phoneNoAuctionLinkRow', !/Auction link/i.test(await pg.locator('#explorePreview').textContent()), null);
  check('phoneNoOldFields', (await pg.locator('#explorePreview .pv-kicker, #explorePreview .pv-coords, #explorePreview .pv-ids, #explorePreview .pv-more, #explorePreview .pv-expand').count()) === 0, null);
  check('phoneDialogLabelled', (await pg.getAttribute('#explorePreview', 'aria-label')) === 'Property preview: 500 Elm Way', await pg.getAttribute('#explorePreview', 'aria-label'));
  check('phoneFootHiddenWhileOpen', await pg.locator('#mapStage .explore-map-foot').isHidden(), null);
  await shot(pg, 'after-phone-pin');
  // Watchlist button: the List cards' own button, toggled by app.js.
  const before = ((await pg.locator('#explorePreview .mp-watch .bid-btn').textContent()) || '').trim();
  await pg.click('#explorePreview .mp-watch .bid-btn');
  await pg.waitForTimeout(600);
  const after = ((await pg.locator('#explorePreview .mp-watch .bid-btn').textContent()) || '').trim();
  check('watchButtonToggles', before === '⚐ Watchlist' && after === '⚑ Watching', { before, after });
  check('watchToggleKeepsCardOpen', await pg.locator('#explorePreview').isVisible(), null);
  // Swipe down past 56px closes the sheet.
  const t = await rect(pg, '#explorePreview .preview-title');
  await pg.mouse.move(t.left + 10, t.top + 5);
  await pg.mouse.down();
  await pg.mouse.move(t.left + 10, t.top + 45, { steps: 4 });
  await pg.mouse.move(t.left + 10, t.top + 85, { steps: 4 });
  await pg.mouse.up();
  await pg.waitForTimeout(400);
  check('phoneSwipeDownCloses', await pg.locator('#explorePreview').isHidden(), null);
  check('phoneStageMpOpenCleared', !(await pg.locator('#mapStage .explore-map-stage').evaluate(e => e.classList.contains('mp-open'))), null);
  // A short drag snaps back.
  await pg.locator('#exploreMapCanvas .map-pin[data-pid="p5"]').click({ force: true });
  await pg.waitForTimeout(600);
  const t2 = await rect(pg, '#explorePreview .preview-title');
  await pg.mouse.move(t2.left + 10, t2.top + 5); await pg.mouse.down();
  await pg.mouse.move(t2.left + 10, t2.top + 30, { steps: 3 }); await pg.mouse.up();
  await pg.waitForTimeout(300);
  check('phoneShortDragSnapsBack', await pg.locator('#explorePreview').isVisible() && (await pg.locator('#explorePreview').evaluate(e => e.style.transform)) === '', null);
  // One tap on "Open property" opens the full page.
  await pg.click('#explorePreview .preview-open');
  await pg.waitForTimeout(500);
  check('phoneOpenOneTapOpensDetail', await pg.locator('#detailModal').isVisible(), null);
  check('phoneNoErrors', errs.length === 0, errs);
  await pg.close();
}

// ---- Phone: rows without coordinates, picked from the strip ----
{
  const { pg, errs } = await openMap(PHONE, 'Duval');
  const card6 = pg.locator('#exploreStrip .strip-card[data-pid="p6"]');
  await card6.scrollIntoViewIfNeeded();
  await pg.waitForTimeout(300);
  const y0 = await pg.evaluate(() => window.scrollY);
  await card6.click();
  await pg.waitForTimeout(800);
  check('phoneStripTapNoPageScroll', (await pg.evaluate(() => window.scrollY)) === y0, { y0, y: await pg.evaluate(() => window.scrollY) });
  const media = await rect(pg, '#explorePreview .mp-media .pv-visual.has-photo');
  check('phonePhotoNeverZero', media && media.height > 60 && media.width > 60, media);
  await pg.evaluate(() => window.scrollTo(0, 0));
  await pg.waitForTimeout(200);
  await shot(pg, 'after-phone-photo');
  // Next strip card, no photo, no coordinates: the county locator, "Listed in".
  const other = await pg.evaluate(() => [...document.querySelectorAll('#exploreStrip .strip-card')].map(c => c.dataset.pid).find(id => id !== 'p6'));
  await pg.evaluate(id => document.querySelector(`#exploreStrip .strip-card[data-pid="${id}"]`).click(), other);
  await pg.waitForTimeout(600);
  const lt = ((await pg.locator('#explorePreview .mp-locator-text').textContent()) || '').trim();
  check('phoneNoCoordsLocatorSaysListed', lt === 'Listed in Duval County', lt);
  check('phoneLocatorHasHeight', ((await rect(pg, '#explorePreview .mp-media')) || {}).height > 60, null);
  // Tap on empty Google / MapTiler map (the event satellite-map.js sends).
  await pg.evaluate(() => window.dispatchEvent(new CustomEvent('tdw:mapbackgroundtap')));
  await pg.waitForTimeout(200);
  check('backgroundTapCloses', await pg.locator('#explorePreview').isHidden(), null);
  check('backgroundTapClearsSelection', await pg.evaluate(() => window.__sel[window.__sel.length - 1].pid === null), null);
  check('phoneNoErrors2', errs.length === 0, errs);
  await pg.close();
}

// ---- Desktop: card bottom-left over the stage, list still visible ----
{
  const { pg, errs } = await openMap(DESK, 'Charlotte');
  await pg.locator('#exploreMapCanvas .map-pin[data-pid="p5"]').click({ force: true });
  await pg.waitForTimeout(1000);
  check('deskCardInStageNotPanel', (await pg.locator('#mapStage #explorePreview').count()) === 1 && (await pg.locator('#mapSidePanel #explorePreview').count()) === 0, null);
  const card = await rect(pg, '#explorePreview');
  check('deskCardCompact', card.width <= 345 && card.height < 420, card);
  const firstStrip = await rect(pg, '#exploreStrip .strip-card');
  const panel = await rect(pg, '#mapSidePanel');
  check('deskStripVisibleWithCard', firstStrip && firstStrip.top >= panel.top && firstStrip.bottom <= panel.bottom, { firstStrip, panel });
  const media = await rect(pg, '#explorePreview .mp-media');
  check('deskMediaHasHeight', media && media.height > 60, media);
  const fm = await factsMatch(pg);
  check('deskFactsAreAppLabels', fm.ok && fm.got.length === 3, fm);
  const pin = await rect(pg, '#exploreMapCanvas .map-pin.sel path');
  check('deskPinClearOfCard', pin && !overlap(pin, await rect(pg, '#explorePreview')), pin);
  const sel = await pg.evaluate(() => window.__sel[window.__sel.length - 1]);
  check('deskSelectionCarriesSideInset', sel && sel.pid === 'p5' && sel.inset && (sel.inset.left > 0 || sel.inset.right > 0 || sel.inset.top > 0) && !sel.inset.bottom, sel);
  await shot(pg, 'after-desktop-pin');
  await pg.keyboard.press('Escape');
  await pg.waitForTimeout(300);
  check('deskEscapeCloses', await pg.locator('#explorePreview').isHidden(), null);
  check('deskEscapeKeepsCounty', await pg.locator('#exploreMapCanvas').evaluate(e => e.classList.contains('zoomed')), null);
  // Keyboard selection moves focus into the card; arrows step the county list.
  await pg.selectOption('#mapCountySelect', 'Duval');
  await pg.waitForTimeout(900);
  await pg.focus('#exploreStrip .strip-card[data-pid="p6"]');
  await pg.keyboard.press('Enter');
  await pg.waitForTimeout(500);
  check('keyboardSelectFocusesOpen', await pg.evaluate(() => document.activeElement && document.activeElement.classList.contains('preview-open')), await pg.evaluate(() => document.activeElement && document.activeElement.className));
  check('deskPhotoShown', ((await rect(pg, '#explorePreview .mp-media .pv-visual.has-photo')) || {}).height > 100, null);
  check('deskImageryCaptionVisible', await pg.locator('#explorePreview .mp-media .photo-caption').isVisible(), null);
  const pos1 = ((await pg.locator('#explorePreview .mp-pager-pos').textContent()) || '').trim();
  await shot(pg, 'after-desktop-photo');
  await pg.keyboard.press('ArrowRight');
  await pg.waitForTimeout(500);
  const pos2 = ((await pg.locator('#explorePreview .mp-pager-pos').textContent()) || '').trim();
  check('pagerArrowSteps', pos1 === '1 of 2' && pos2 === '2 of 2', { pos1, pos2 });
  check('pagerStepSelectsStrip', (await pg.locator('#exploreStrip .strip-card.sel').getAttribute('data-pid')) !== 'p6', null);
  // Certificates: no auction wording, the account as the identifier.
  await pg.selectOption('#mapCountySelect', 'ALL');
  await pg.waitForTimeout(600);
  const cert = await pg.evaluate(() => { const c = window.__tdwMapLastRender.rows.find(p => p.source === 'certificate'); return c ? { id: c.id, county: c.county } : null; });
  if (cert) {
    await pg.selectOption('#mapCountySelect', cert.county);
    await pg.waitForTimeout(900);
    await pg.evaluate(id => document.querySelector(`#exploreStrip .strip-card[data-pid="${id}"]`).click(), cert.id);
    await pg.waitForTimeout(500);
    const txt = (await pg.locator('#explorePreview').textContent()) || '';
    check('certificateNoAuctionLink', !/Auction link/i.test(txt) && /Certificate/.test(await pg.locator('#explorePreview .mp-ledger').textContent()), txt.replace(/\s+/g, ' '));
    const cfm = await factsMatch(pg);
    check('certificateFactsAreAppLabels', cfm.ok, cfm);
  } else check('certificateRowPresent', false, null);
  // Google with no key: the setup message no longer points "on the left".
  await pg.click('#mapStyleGoogle');
  await pg.waitForTimeout(300);
  const setup = ((await pg.locator('#satelliteMapCanvasGoogle .satellite-map-setup').textContent()) || '');
  check('satSetupCopyFixed', /The Outline map still works/.test(setup) && !/on the left/.test(setup), setup);
  // Satellite pin markup: a 44px hit box holding the visible teardrop.
  const hit = await pg.evaluate(() => {
    const el = document.createElement('div'); el.className = 'sat-pin sel'; el.innerHTML = '<span class="sat-pin-mark"></span>';
    document.body.appendChild(el);
    const r = el.getBoundingClientRect(), m = el.firstChild.getBoundingClientRect();
    const tf = getComputedStyle(el.firstChild).transform;
    el.remove();
    return { w: r.width, h: r.height, mark: m.width, scaled: tf !== 'none' };
  });
  check('satPinHit44', hit.w >= 44 && hit.h >= 44 && hit.mark > 16 && hit.scaled, hit);
  check('deskNoErrors', errs.length === 0, errs);
  await pg.close();
}

// ---- A pin that starts under the card: desktop moves the card, a phone
// nudges the map; closing undoes the nudge. One extra geocoded Charlotte row
// at the south-west edge of the county's frame, where the card sits.
{
  const now = new Date().toISOString();
  const d = new Date(Date.now() + 9 * 864e5).toISOString().slice(0, 10);
  const extra = [{ id: 'mpk1', source: 'auction', state: 'FL', county: 'Charlotte', case_no: 'MPK-1', parcel: '9911', address: '1 Gulf Blvd', bid: 4200, status: 'active', sale_date: d, ledger_type: 'auctions', url_auction: 'https://x', url_auction_kind: 'sale', last_seen_at: now, updated_at: now, lien_level: 'unscreened', publication_status: 'APPROVED', latitude: 26.66, longitude: -82.258 }];
  for (const [label, vp] of [['desk', DESK], ['phone', PHONE]]) {
    const pg = await b.newPage({ viewport: vp });
    const errs = []; pg.on('pageerror', e => errs.push(e.message));
    await pg.addInitScript(r => { window.__stubExtraRows = r; }, extra);
    await pg.goto(BASE + '#/map', { waitUntil: 'networkidle' }); await pg.waitForTimeout(800);
    await pg.selectOption('#mapCountySelect', 'Charlotte'); await pg.waitForTimeout(900);
    const vb0 = await pg.evaluate(() => document.querySelector('#exploreMapCanvas svg').getAttribute('viewBox'));
    await pg.locator('#exploreMapCanvas .map-pin[data-pid="mpk1"]').click({ force: true });
    await pg.waitForTimeout(1100);
    const pin = await rect(pg, '#exploreMapCanvas .map-pin.sel path'), card = await rect(pg, '#explorePreview');
    check(label + 'CornerPinClearOfCard', pin && !overlap(pin, card), { pin, card });
    const how = await pg.evaluate(() => { const c = document.getElementById('explorePreview'); return c.classList.contains('mp-right') ? 'right' : c.classList.contains('mp-top') ? 'top' : 'nudge'; });
    if (label === 'desk') check('deskCardMovesBeforeMap', how !== 'nudge', how);
    else check('phoneMapNudged', (await pg.evaluate(() => document.querySelector('#exploreMapCanvas svg').getAttribute('viewBox'))) !== vb0, null);
    await shot(pg, label === 'desk' ? 'after-desktop-corner-pin' : 'after-phone-corner-pin');
    await pg.click('#explorePreview .preview-close');
    await pg.waitForTimeout(800);
    check(label + 'CloseRestoresView', (await pg.evaluate(() => document.querySelector('#exploreMapCanvas svg').getAttribute('viewBox'))).split(' ').map(Number).every((v, i) => Math.abs(v - vb0.split(' ').map(Number)[i]) < 0.5), null);
    check(label + 'CornerNoErrors', errs.length === 0, errs);
    await pg.close();
  }
}

// ---- Dead provider popups are gone ----
{
  const pg = await b.newPage();
  const src = await (await pg.request.get(BASE.replace(/[^/]*$/, '') + 'satellite-map.js')).text();
  check('providerPopupsRemoved', !/showGooglePopup|showMaptilerPopup|InfoWindow|\.Popup\(/.test(src), null);
  check('satZoomRuleNo16Jump', /z < 12 \? 15 : z/.test(src) && /padding: ZERO_PAD/.test(src), null);
  await pg.close();
}

await b.close();
process.exit(fail ? 1 : 0);
