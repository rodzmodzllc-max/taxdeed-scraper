// Available list head (owner, 2026-11-04, marked-up phone screenshot):
// - the ledger question opens the Buyer's Guide;
// - the title carries no count; "N properties" sits on its own line just
//   above the county bar;
// - the bar names the county in view with its own count;
// - the county dropdown lists counties with properties A-Z, no numbers, then
//   every county with none A-Z, italic and marked "no properties";
// - every county head shows the state outline with that county shaded.
import { chromium } from 'playwright';
import fs from 'fs';
const BASE = process.env.BASE_URL || 'http://localhost:8934/index.html';
const root = BASE.replace(/[^/]*$/, '');
const exe = '/opt/pw-browsers/chromium';
const b = await chromium.launch(fs.existsSync(exe) ? { executablePath: exe } : {});
let fail = 0;
const check = (name, ok, got) => { console.log((ok ? 'PASS ' : 'FAIL ') + name + (ok ? '' : ' -> ' + JSON.stringify(got))); if (!ok) fail++; };
const errors = [];
const open = async (path, look) => {
  const pg = await b.newPage({ viewport: { width: 390, height: 844 } });
  pg.on('pageerror', e => errors.push(path + ': ' + e.message));
  await pg.goto(root + path.replace('#', `?look=${look}#`), { waitUntil: 'networkidle' });
  await pg.waitForTimeout(1800);
  return pg;
};
for (const look of ['classic', 'merged']) {
  const pg = await open('index.html#/lands', look);
  const head = await pg.evaluate(() => {
    const t = document.getElementById('listTitle'), tot = document.getElementById('listTotal'), bar = document.getElementById('countyNowBar');
    return { title: t.textContent.trim(), titleDigits: /\d/.test(t.textContent),
      total: tot && !tot.hidden ? tot.textContent.replace(/\s+/g, ' ').trim() : null,
      totalBeforeBar: !!(tot && bar && (tot.compareDocumentPosition(bar) & Node.DOCUMENT_POSITION_FOLLOWING)),
      guide: !!document.querySelector('#listSubtitle .list-guide-link[data-action="buyersguide"]') };
  });
  check(look + '_titleHasNoCount', head.title === 'Available in Florida' && !head.titleDigits, head);
  check(look + '_totalAboveBar', head.total === '2 properties' && head.totalBeforeBar, head);
  check(look + '_questionIsGuideLink', head.guide, head);
  const opts = await pg.evaluate(() => [...document.querySelectorAll('#countyQuick option')].map(o => ({ t: o.textContent, empty: o.classList.contains('cq-empty'), italic: getComputedStyle(o).fontStyle })));
  const withRows = opts.slice(1).filter(o => !o.empty).map(o => o.t), without = opts.slice(1).filter(o => o.empty);
  check(look + '_dropdownWithFirstAZ', JSON.stringify(withRows) === JSON.stringify(['Bay', 'Citrus']) && opts.slice(1, 3).every(o => !o.empty), withRows);
  check(look + '_dropdownNoNumbers', opts.every(o => !/\d/.test(o.t)), opts.filter(o => /\d/.test(o.t)));
  check(look + '_dropdownEmptyMarked', without.length === 65 && without.every(o => / · no properties$/.test(o.t) && o.italic === 'italic')
    && JSON.stringify(without.map(o => o.t)) === JSON.stringify(without.map(o => o.t).slice().sort((a, b) => a.localeCompare(b))), without.slice(0, 3));
  // The locator draws lazily as its head nears the screen: bring each one in.
  const scope = look === 'classic' ? '#main' : '#xpStage';
  for (let i = 0; i < 2; i++) {
    await pg.evaluate(([sc, i]) => document.querySelectorAll(sc + ' [data-county-head]')[i].scrollIntoView({ block: 'center' }), [scope, i]);
    await pg.waitForTimeout(500);
  }
  await pg.waitForFunction(sc => [...document.querySelectorAll(sc + ' [data-county-head] .county-locator')].every(l => l.querySelector('svg .mm-county')), scope, { timeout: 8000 }).catch(() => {});
  const loc = await pg.evaluate(sc => [...document.querySelectorAll(sc + ' [data-county-head]')].map(h => { const l = h.querySelector('.county-locator'); return { c: h.dataset.countyHead, svg: !!(l && l.querySelector('svg .mm-county')), neighbours: l ? l.querySelectorAll('.mm-neighbor').length : 0, w: l ? Math.round(l.getBoundingClientRect().width) : 0 }; }), scope);
  check(look + '_countyHeadLocator', loc.length === 2 && loc.every(x => x.svg && x.neighbours >= 60 && x.w >= 40), loc);
  // Scroll the bar under the header: it names the county in view and its count.
  await pg.evaluate(() => { const h = document.querySelectorAll('[data-county-head]')[1]; window.scrollTo(0, h.getBoundingClientRect().top + window.scrollY - 120); });
  await pg.waitForTimeout(700);
  const bar = await pg.evaluate(() => ({ name: document.querySelector('#countyNowBar [data-cnb-name]').textContent.trim(), count: document.querySelector('#countyNowBar [data-cnb-count]').textContent.trim() }));
  check(look + '_barCountyCount', /^(Bay|Citrus) County$/.test(bar.name) && bar.count === '1 property', bar);
  if (look === 'classic') {
    await pg.evaluate(() => window.scrollTo(0, 0));
    await pg.click('#listSubtitle .list-guide-link');
    await pg.waitForTimeout(1200);
    const g = await pg.evaluate(() => ({ hash: location.hash, shown: !document.getElementById('pageGuide').hidden }));
    check('guideLinkOpensGuide', g.hash === '#/guide?ledger=AVAILABLE' && g.shown, g);
    // Auctions keeps its title count; its dropdown follows its own counties.
    await pg.evaluate(() => { location.hash = '#/auctions'; });
    await pg.waitForTimeout(1200);
    const a = await pg.evaluate(() => ({ title: document.getElementById('listTitle').textContent, total: document.getElementById('listTotal').hidden,
      first: [...document.querySelectorAll('#countyQuick option')].slice(1).filter(o => !o.classList.contains('cq-empty')).map(o => o.textContent) }));
    check('auctionsKeepsTitleCount', /\d/.test(a.title) && a.total, a);
    check('auctionsDropdownOwnCounties', a.first.length > 0 && !a.first.includes('Bay') && JSON.stringify(a.first) === JSON.stringify(a.first.slice().sort((x, y) => x.localeCompare(y))), a.first);
  }
  await pg.close();
}
// 2026-11-10 (owner): the line under "Available in <state>" is one Buyer's Guide
// link, and a county head carries a Buyer's Guide link for that county instead
// of the "How to acquire" steps.
{
  const pg = await open('index.html#/lands', 'merged');
  const r = await pg.evaluate(() => {
    const sub = document.getElementById('listSubtitle');
    const heads = [...document.querySelectorAll('#xpStage [data-county-head]')];
    return { sub: sub.textContent.replace(/\s+/g, ' ').trim(), subLinks: sub.querySelectorAll('.list-guide-link').length,
      heads: heads.length, headLinks: heads.filter(h => h.querySelector('.xt-guide-link[data-action="buyersguide"]')).length,
      headSteps: heads.filter(h => h.querySelector('.xt-trail')).length, first: heads[0] ? heads[0].querySelector('.xt-guide-link') && heads[0].querySelector('.xt-guide-link').dataset.county : null,
      county: heads[0] ? heads[0].dataset.countyHead : null };
  });
  check('availableSubtitleIsTheGuideLinkOnly', r.subLinks === 1 && /^Buyer's Guide: how to acquire Available property/.test(r.sub) && !/What can I acquire now|over the counter|count/i.test(r.sub), r);
  check('countyHeadsCarryGuideLinkNotSteps', r.heads > 0 && r.headLinks > 0 && r.headSteps === 0 && r.first === r.county, r);
  await pg.click('#xpStage [data-county-head] .xt-guide-link');
  await pg.waitForTimeout(1200);
  const g = await pg.evaluate(() => { const pr = document.querySelector('#pageGuide .bg-process'); return { hash: decodeURIComponent(location.hash), shown: !document.getElementById('pageGuide').hidden,
    process: pr ? pr.dataset.bgProcess : null, title: pr ? pr.querySelector('.bg-process-t').textContent : null, steps: pr ? pr.querySelectorAll('.bg-process-steps li').length : 0, foot: pr && pr.querySelector('.bg-process-f') ? pr.querySelector('.bg-process-f').textContent : '' }; });
  check('countyHeadLinkOpensThatCountysGuide', g.shown && /^#\/guide\?/.test(g.hash) && /ledger=AVAILABLE/.test(g.hash) && g.hash.includes('county=' + r.county), { g, county: r.county });
  // The county's own process is in the guide (same for every property there), not on each card.
  check('guideShowsTheCountysProcess', !!g.process && g.title === 'How to acquire in ' + r.county + ' County' && (g.process === 'unverified' || (/same for every Available property/.test(g.foot))), g);
  await pg.close();
}
// Without the guide the question stays plain text.
{
  const ctx = await b.newContext({ viewport: { width: 390, height: 844 } });
  await ctx.route('**/config.js', async route => { const res = await route.fetch(); await route.fulfill({ response: res, body: (await res.text()) + '\nwindow.TDW_CONFIG.buyersGuideAccess = "admin";\n' }); });
  const pg = await ctx.newPage();
  pg.on('pageerror', e => errors.push('noguide: ' + e.message));
  await pg.goto(root + 'index.html#/lands', { waitUntil: 'networkidle' });
  await pg.waitForTimeout(1500);
  const r = await pg.evaluate(() => ({ link: !!document.querySelector('#listSubtitle .list-guide-link'), text: document.getElementById('listSubtitle').textContent }));
  check('noGuideAccessNoGuideLine', !r.link && !/What can I acquire now\?|Buyer's Guide/.test(r.text), r);   // 2026-11-10: Available's line is the guide link or nothing
  await ctx.close();
}
check('noPageErrors', errors.length === 0, errors);
await b.close();
console.log(fail ? `FAILED ${fail}` : 'PASS: all available-head checks');
process.exit(fail ? 1 : 0);
