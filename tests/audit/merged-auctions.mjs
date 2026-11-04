// Audit 2026-10-28, Merged look -> Auctions deck (experience-tactile.js).
// Proves: Next / Previous never move the page (F7, F63); fast taps each move
// one lot (F42, F64); a Watchlist tap on a placard leaves the page and the
// stage where they are (F44, F41); a lot picked from the grid lands clear of
// the sticky header (F7); lot tiles show a bid with cents exactly (F85); the
// sale-day rail keeps the chosen day on screen (F22, F43); a swipe moves the
// deck (F6, F21).
//   BASE_URL=http://localhost:8871/index.html node tests/audit/merged-auctions.mjs
import { chromium } from 'playwright';
import fs from 'node:fs';

const BASE = process.env.BASE_URL || 'http://localhost:8934/index.html';
const exe = fs.existsSync('/opt/pw-browsers/chromium') ? '/opt/pw-browsers/chromium' : undefined;
const browser = await chromium.launch(exe ? { executablePath: exe } : {});
let failed = 0;
const check = (name, ok, info) => { console.log(`${ok ? 'PASS' : 'FAIL'} ${name}${ok ? '' : ' ' + JSON.stringify(info)}`); if (!ok) failed++; };

// Thirty synthetic lots on one sale day; odd lots carry a whole-dollar bid.
const day = new Date(Date.now() + 9 * 864e5).toISOString().slice(0, 10);
const now = new Date().toISOString();
const lots = Array.from({ length: 30 }, (_, i) => ({ id: 'au' + i, source: 'auction', state: 'FL', county: 'Leon', case_no: 'AU-' + i, parcel: '55' + i, address: (i + 1) + ' Audit St',
  bid: i % 2 ? 2400 : 2386.16, status: 'active', sale_date: day, ledger_type: 'auctions', url_auction: 'https://leon.realtaxdeed.com/index.cfm?zaction=AUCTION&zmethod=PREVIEW&AuctionDate=' + day,
  url_auction_kind: 'sale', last_seen_at: now, updated_at: now, lien_level: 'unscreened', publication_status: 'APPROVED' }));
// Eight more sale days so the rail overflows a phone screen.
const extraDays = Array.from({ length: 8 }, (_, i) => {
  const d = new Date(Date.now() + (12 + i * 3) * 864e5).toISOString().slice(0, 10);
  return { ...lots[0], id: 'ad' + i, case_no: 'AD-' + i, parcel: '66' + i, address: (i + 1) + ' Rail St', sale_date: d };
});
const rows = lots.concat(extraDays);

async function open(vp) {
  const ctx = await browser.newContext({ viewport: vp, hasTouch: vp.width < 500, isMobile: vp.width < 500 });
  const pg = await ctx.newPage();
  pg.on('pageerror', e => { console.log('FAIL pageerror ' + e.message); failed++; });
  await pg.addInitScript(r => { window.__stubExtraRows = r; }, rows);
  await pg.goto(BASE + '?look=merged#/auctions', { waitUntil: 'networkidle' });
  await pg.waitForTimeout(2500);
  await pg.evaluate(d => document.querySelector(`.xpt-day[data-day="${d}"]`).click(), day);
  await pg.waitForTimeout(900);
  return { ctx, pg };
}
const deckState = pg => pg.evaluate(() => ({
  y: Math.round(scrollY),
  lot: Number(document.querySelector('.xpt-pager b').textContent),
  deckTop: Math.round(document.querySelector('.xpt-deck').getBoundingClientRect().top),
  nextTop: Math.round(document.querySelector('[data-xa="next"]').getBoundingClientRect().top)
}));
const tap = async (pg, sel, touch) => {
  const bb = await pg.locator(sel).first().boundingBox();
  const x = bb.x + bb.width / 2, y = bb.y + bb.height / 2;
  if (touch) await pg.touchscreen.tap(x, y); else await pg.mouse.click(x, y);
};

for (const vp of [{ width: 390, height: 844 }, { width: 1440, height: 900 }]) {
  const tag = vp.width;
  const touch = vp.width < 500;
  const { ctx, pg } = await open(vp);

  // Deck low on the screen, as in the reports.
  await pg.evaluate(() => { const r = document.querySelector('.xpt-deck').getBoundingClientRect(); scrollBy(0, r.top - 250); });
  await pg.waitForTimeout(300);
  const s0 = await deckState(pg);
  await tap(pg, '#xpStage [data-xa="next"]', touch);
  await pg.waitForTimeout(800);
  const s1 = await deckState(pg);
  check(`nextKeepsPage_${tag}`, s1.y === s0.y && s1.deckTop === s0.deckTop && s1.nextTop === s0.nextTop && s1.lot === s0.lot + 1, { s0, s1 });
  await tap(pg, '#xpStage [data-xa="prev"]', touch);
  await pg.waitForTimeout(800);
  const s2 = await deckState(pg);
  check(`prevKeepsPage_${tag}`, s2.y === s0.y && s2.deckTop === s0.deckTop && s2.lot === s0.lot, { s0, s2 });

  // Three taps 80 ms apart move three lots, and the page stays put.
  for (let i = 0; i < 3; i++) { await tap(pg, '#xpStage [data-xa="next"]', touch); await pg.waitForTimeout(80); }
  await pg.waitForTimeout(900);
  const s3 = await deckState(pg);
  const top = await pg.evaluate(() => { const on = document.querySelector('.xpt-mini.on');
    return { pid: document.querySelector('.xpt-deck .xpt-placard').dataset.pid, onPid: on.dataset.pid, onNum: Number(on.querySelector('.numeral-s').textContent) }; });
  check(`rapidTapsEachMoveOneLot_${tag}`, s3.lot === s2.lot + 3 && top.pid === top.onPid && top.onNum === s3.lot && s3.y === s0.y, { s2, s3, top });

  // Watchlist on the back of a flipped placard: same page position, same
  // stage nodes, still flipped, button pressed.
  await pg.locator('.xpt-deck .xpt-placard .face.front').click();
  await pg.waitForTimeout(800);
  await pg.evaluate(() => { const b = document.querySelector('.xpt-deck .xpt-placard [data-action="bidlist"]'); scrollBy(0, b.getBoundingClientRect().top - (innerHeight - 250)); });
  await pg.waitForTimeout(300);
  await pg.evaluate(() => { window.__auditRoot = document.querySelector('#xpStage > .xpt'); window.__auditCard = document.querySelector('.xpt-deck .xpt-placard'); });
  const w0 = await pg.evaluate(() => ({ y: Math.round(scrollY), top: Math.round(document.querySelector('.xpt-deck .xpt-placard [data-action="bidlist"]').getBoundingClientRect().top) }));
  await tap(pg, '.xpt-deck .xpt-placard [data-action="bidlist"]', touch);
  await pg.waitForTimeout(1200);
  const w1 = await pg.evaluate(() => { const b = document.querySelector('.xpt-deck .xpt-placard [data-action="bidlist"]');
    return { y: Math.round(scrollY), top: Math.round(b.getBoundingClientRect().top), pressed: b.getAttribute('aria-pressed'),
      sameRoot: document.querySelector('#xpStage > .xpt') === window.__auditRoot, sameCard: document.querySelector('.xpt-deck .xpt-placard') === window.__auditCard,
      flipped: !!document.querySelector('.xpt-deck .xpt-placard.flipped'), tileRibbon: !!document.querySelector('.xpt-mini.on .rib') }; });
  check(`watchTapKeepsPage_${tag}`, w1.y === w0.y && w1.top === w0.top && w1.pressed === 'true' && w1.flipped, { w0, w1 });
  check(`watchTapPatchesInPlace_${tag}`, w1.sameRoot && w1.sameCard && w1.tileRibbon, w1);

  // A lot picked from the grid while the deck is above the screen lands
  // below the sticky header.
  await pg.evaluate(() => document.querySelector('.xpt-mini[data-pid="au20"]').scrollIntoView({ block: 'center' }));
  await pg.waitForTimeout(400);
  await tap(pg, '.xpt-mini[data-pid="au20"]', touch);
  await pg.waitForTimeout(1200);
  const pk = await pg.evaluate(() => {
    let hdr = 0;
    document.querySelectorAll('.topbar, .quick-controls, header').forEach(el => { const cs = getComputedStyle(el); const r = el.getBoundingClientRect();
      if ((cs.position === 'sticky' || cs.position === 'fixed') && r.height && r.top <= 1 && r.bottom < innerHeight / 2) hdr = Math.max(hdr, r.bottom); });
    const d = document.querySelector('.xpt-deck').getBoundingClientRect();
    return { pid: document.querySelector('.xpt-deck .xpt-placard').dataset.pid, deckTop: Math.round(d.top), hdr: Math.round(hdr), inView: d.top < innerHeight };
  });
  check(`pickLandsBelowHeader_${tag}`, pk.pid === 'au20' && pk.deckTop >= pk.hdr && pk.inView, pk);

  // Lot tiles: a bid with cents is shown exactly, a whole-dollar bid without
  // cents; the tile and the placard agree.
  const tiles = await pg.evaluate(() => ({ cents: document.querySelector('.xpt-mini[data-pid="au0"] .mini-fig').textContent, whole: document.querySelector('.xpt-mini[data-pid="au1"] .mini-fig').textContent }));
  check(`tileShowsExactBid_${tag}`, /\$2,386\.16/.test(tiles.cents) && /\$2,400(?!\.)/.test(tiles.whole) && !/\$2,386(?!\.)/.test(tiles.cents), tiles);

  // Swipe left on the top placard moves one lot.
  await pg.evaluate(() => scrollTo(0, 0));
  await pg.evaluate(() => { const r = document.querySelector('.xpt-deck').getBoundingClientRect(); scrollBy(0, r.top - 150); });
  await pg.waitForTimeout(300);
  const before = await deckState(pg);
  const box = await pg.locator('.xpt-deck .xpt-placard').boundingBox();
  await pg.mouse.move(box.x + box.width * 0.8, box.y + 200); await pg.mouse.down();
  for (let i = 1; i <= 10; i++) await pg.mouse.move(box.x + box.width * 0.8 - 18 * i, box.y + 202);
  await pg.mouse.up(); await pg.waitForTimeout(900);
  const after = await deckState(pg);
  check(`swipeMovesDeck_${tag}`, after.lot === before.lot + 1, { before, after });

  // The sale-day rail: slide it to the end, tap the last day; the chosen day
  // stays on screen.
  const rail = await pg.evaluate(async () => {
    const r = document.querySelector('.xpt-days'); r.scrollLeft = r.scrollWidth;
    await new Promise(res => setTimeout(res, 100));
    const days = r.querySelectorAll('.xpt-day'); days[days.length - 1].click();
    await new Promise(res => setTimeout(res, 600));
    const rr = document.querySelector('.xpt-days'), on = rr.querySelector('.xpt-day.on').getBoundingClientRect(), box = rr.getBoundingClientRect();
    return { visible: on.left >= box.left - 1 && on.right <= box.right + 1, overflow: rr.scrollWidth > rr.clientWidth };
  });
  check(`railKeepsChosenDay_${tag}`, rail.visible, rail);
  await ctx.close();
}

// Rows arriving a page at a time do not replay the entrance animation (F76).
{
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 } });
  const pg = await ctx.newPage();
  await pg.addInitScript(() => { window.__auditEnter = 0; new MutationObserver(() => { const r = document.querySelector('#xpStage > .xpt'); if (r && r.classList.contains('xpt-enter')) window.__auditEnter++; }).observe(document.documentElement, { childList: true, subtree: true }); });
  await pg.goto(BASE + '?look=merged&maxrows=2&pagedelay=700#/auctions', { waitUntil: 'networkidle' });
  await pg.waitForTimeout(6000);
  const n = await pg.evaluate(() => window.__auditEnter);
  check('entranceOncePerLedger', n <= 1, { enterDraws: n });
  await ctx.close();
}

await browser.close();
if (failed) { console.log(`FAILED ${failed}`); process.exit(1); }
console.log('ALL PASS');
