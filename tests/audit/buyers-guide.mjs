// Buyer's Guide page (2026-10-29; destination redesign 2026-11-09; "up to a 10" sprint
// 2026-11-12): #/guide renders per state / ledger / county from buyers-guide.json as a guide -
// a short version built only from the file, the journey (Find > Check > Buy > After > Risks)
// with the answers open, the county picker in sight, and a next step back to the properties.
//
// 2026-11-12 changes to existing checks (the owner asked for the guide "up to a 10"):
//  - guideMeterIsCount / guideStepCounts -> guideNoCoverageCount: the "N of M answered" meter
//    and the per-step "n/m answered" counts read as missing items to a customer; removed.
//  - guideOneChipPerRow / guideChipVocabulary: answered rows carry no "Answered" badge any more;
//    only open rows (Not yet confirmed / Official page blocked) and partly answered rows do.
//  - guidePhoneChipStrip -> guidePhoneRailHidden; guideDesktopRail240 -> guideDesktopRailCompact:
//    the rail is a compact "On this page" list on desktop and hidden on phones.
//  - guideCalloutStateSurvives -> guideCalloutPickerInSight: the county callout is no longer a
//    collapsed bar, so there is no open state to keep.
//  - guideOpenIdsSurviveRerender -> guideClosedIdsSurviveRerender: answers are open by default;
//    the reader's folded ones are what is remembered.
//  - guideReducedMotion reads the answer-reveal animation (the meter bar is gone).
import { chromium } from 'playwright';
import fs from 'fs';
const BASE = process.env.BASE_URL || 'http://localhost:8934/index.html';
const root = BASE.replace(/[^/]*$/, '');
const exe = '/opt/pw-browsers/chromium';
const b = await chromium.launch(fs.existsSync(exe) ? { executablePath: exe } : {});
const GUIDE = JSON.parse(fs.readFileSync(new URL('../../public/buyers-guide.json', import.meta.url), 'utf8'));
let fail = 0;
const check = (name, ok, got) => { console.log((ok ? 'PASS ' : 'FAIL ') + name + (ok ? '' : ' -> ' + JSON.stringify(got))); if (!ok) fail++; };
const open = async (path, vp = { width: 390, height: 844 }, opts = {}, theme = null) => {
  const ctx = await b.newContext({ viewport: vp, ...opts });
  if (theme) await ctx.addInitScript(t => { try { localStorage.setItem('tdw_theme', t); } catch { /* */ } }, theme);
  const pg = await ctx.newPage();
  const errs = []; pg.on('pageerror', e => errs.push(e.message));
  await pg.goto(root + path, { waitUntil: 'networkidle' }); await pg.waitForTimeout(1500);
  pg.closeAll = () => ctx.close();
  return { pg, errs };
};
const PARTIAL_LABELS = ['Partly answered', 'Not yet confirmed', 'Official page blocked'];
const OPERATOR = /capture run|runner|HTTP \d{3}|CloudFront|Cloudflare|research network/i;
const ANSWERED = new Set(['VERIFIED', 'PARTIALLY_VERIFIED']);
const norm = t => String(t || '').replace(/\s+/g, ' ').trim();

// Every line of the short version must come from the file: the ledger summary, or the opening
// of a VERIFIED / PARTIALLY_VERIFIED answer (county or statewide) for that question.
function shortFromFile(rows, st, ledger, county) {
  const s = GUIDE.states[st];
  const L = s.ledgers[ledger] || {};
  const c = county && s.counties[county] && s.counties[county][ledger];
  return rows.every(r => {
    if (r.from === 'missing') return /Not yet confirmed/.test(r.text);
    if (r.from === 'summary') return norm(r.text) === norm(L.summary);
    const list = r.from === 'county' ? (c && c.answers) || [] : L.answers || [];
    const a = list.find(x => x.q === r.q);
    return !!a && ANSWERED.has(a.status) && norm(a.answer).startsWith(norm(r.text)) && norm(r.text).length > 10;
  });
}
const readShort = pg => pg.evaluate(() => [...document.querySelectorAll('.bg-short-row')].map(r => ({
  key: r.dataset.bgShort, from: r.dataset.bgShortFrom, q: r.dataset.bgShortQ,
  text: (r.querySelector('.bg-short-t') || r.querySelector('dd')).textContent,
  src: !!r.querySelector('.bg-short-src a[href^="https://"]'), more: !!r.querySelector('[data-bg-goto]') })));

{ // Leon County, Available, phone
  const { pg, errs } = await open('index.html#/guide?ledger=AVAILABLE&county=Leon');
  const r = await pg.evaluate((LABELS) => {
    const page = document.querySelector('.bg-page');
    const text = page ? page.innerText : '';
    const rows = [...document.querySelectorAll('.bg-q')];
    const ver = [...document.querySelectorAll('.bg-q[data-bg-verified]')];
    const open = [...document.querySelectorAll('.bg-q-open')];
    const quotes = [...document.querySelectorAll('.bg-quote')];
    const count = document.querySelector('.bg-count');
    return {
      last: window.__tdwGuideLast, hash: location.hash, doc: document.title,
      title: document.querySelector('.bg-title')?.textContent.trim(),
      eyebrow: document.querySelector('.bg-eyebrow')?.textContent.trim(),
      lede: document.querySelector('.bg-lede')?.textContent.trim() || '',
      legal: document.querySelector('.bg-legal')?.textContent || '',
      hero: !!document.querySelector('.bg-hero'),
      noCoverage: !document.querySelector('.bg-meter, .bg-step-c, .bg-jump-c') && !/\d+ of \d+ answered|\d+\/\d+ answered/i.test(text),
      noAnsweredBadge: ![...document.querySelectorAll('.bg-chip')].some(c => /^answered$/i.test(c.textContent.trim())) && !/\bANSWERED\b/.test(text.replace(/Partly answered/gi, '')),
      steps: [...document.querySelectorAll('.bg-step')].map(s => s.dataset.bgStep),
      railN: document.querySelectorAll('.bg-jump[data-bg-jump]:not([data-bg-jump="next"])').length,
      verifiedWithSource: ver.length > 0 && ver.every(d => !!d.querySelector('.bg-meta a[href^="https://"]')),
      verifiedAccent: ver.every(d => getComputedStyle(d).borderLeftWidth === '3px'),
      openHasWhere: open.length > 0 && open.every(d => !!d.querySelector('.bg-where')),
      answeredNoChip: ver.every(d => !d.querySelector('summary .bg-chip')),
      openOneChip: open.every(d => d.querySelectorAll('.bg-chip').length === 1),
      chipLabels: [...new Set([...document.querySelectorAll('.bg-chip')].map(c => c.textContent.trim()))],
      chipsKnown: [...document.querySelectorAll('.bg-chip')].every(c => LABELS.includes(c.textContent.trim())),
      noOpenBadge: !document.querySelector('.bg-q-badge') && !/\bOPEN\b/.test(text),
      noOldVocab: !/Not yet verified|Source restricted|Partly verified/.test(text),
      noRawUrl: !/https?:\/\//.test(text),
      quotesInDetails: quotes.length > 0 && quotes.every(q => q.closest('details.bg-src') && !q.closest('details.bg-src').open),
      srcSummary: [...document.querySelectorAll('details.bg-src > summary')].every(s => s.textContent.trim() === 'Official wording'),
      notItalic: quotes.every(q => getComputedStyle(q).fontStyle !== 'italic'),
      scopes: [...document.querySelectorAll('.bg-scope')].map(s => s.textContent.trim()),
      metaOrder: ver.every(d => { const m = d.querySelector('.bg-meta'); const t = m.innerHTML; const ia = t.indexOf('<a'), ic = t.indexOf('checked'); return ic < 0 || (ia >= 0 && ia < ic); }),
      todoMatch: [...document.querySelectorAll('.bg-todo')].every(g => { const n = +((g.querySelector('.bg-todo-h')?.textContent.match(/\((\d+)\)/) || [])[1]); return n === g.querySelectorAll('.bg-q-open').length; }),
      todoAfterAnswers: [...document.querySelectorAll('.bg-step')].every(s => { const kids = [...s.children]; const t = kids.findIndex(k => k.classList.contains('bg-todo')); const l = kids.findIndex(k => k.classList.contains('bg-list')); return t < 0 || l < 0 || l < t; }),
      countRole: count?.getAttribute('role') === 'status' && count?.getAttribute('aria-live') === 'polite',
      tabs: [...document.querySelectorAll('[data-bg-ledger]')].map(t => t.dataset.bgLedger),
      tabAria: [...document.querySelectorAll('[data-bg-ledger]')].map(t => t.getAttribute('aria-label')),
      shortVisible: getComputedStyle(document.querySelector('[data-bg-ledger="LIENS_CERTIFICATES"] .bg-tab-short')).display !== 'none',
      onTab: document.querySelector('.bg-tab.on')?.dataset.bgLedger,
      showing: document.querySelector('.bg-county-l')?.textContent.trim(),
      noCallout: !document.querySelector('[data-bg-callout]'),
      overflow: document.documentElement.scrollWidth > window.innerWidth + 1,
      railHidden: getComputedStyle(document.querySelector('.bg-rail')).display === 'none',
      allAnsweredOpen: [...document.querySelectorAll('details.bg-q')].every(d => d.open),
      buyOpen: [...document.querySelectorAll('#bgStep-buy details.bg-q')].length > 0 && [...document.querySelectorAll('#bgStep-buy details.bg-q')].every(d => d.open),
      priceOpen: !!document.querySelector('details.bg-q[data-bg-q="price"][open]'),
      expand: (() => { const x = document.querySelector('[data-bg-expand]'); return x ? { tag: x.tagName, aria: x.getAttribute('aria-expanded'), text: x.textContent.trim() } : null; })(),
      headings: [...page.querySelectorAll('h1,h2,h3,h4')].map(h => +h.tagName[1]),
    };
  }, PARTIAL_LABELS);
  check('guideHeroPresent', r.hero, r.hero);
  check('guideLeonTitle', r.title === 'Available property in Leon County', r.title);
  check('guideEyebrowNamesState', r.eyebrow === "Buyer's Guide · Florida", r.eyebrow);
  check('guideLedePresent', r.lede.length > 20, r.lede);
  check('guideNoCoverageCount', r.noCoverage, null);
  check('guideNoAnsweredBadge', r.noAnsweredBadge, r.chipLabels);
  check('guideNotLegalAdvice', /Not legal advice/.test(r.legal), r.legal);
  check('guideLeonCounts', r.last && r.last.total >= 4 && r.last.verified >= 1, r.last);
  check('guideJourneyOrder', r.steps.length >= 3 && r.steps.join(',') === ['find', 'check', 'buy', 'after', 'risks', 'more'].filter(s => r.steps.includes(s)).join(','), r.steps);
  check('guideRailMatchesSteps', r.railN === r.steps.length, [r.railN, r.steps.length]);
  check('guideVerifiedHaveSource', r.verifiedWithSource, null);
  check('guideVerifiedAccent', r.verifiedAccent, null);
  check('guideOpenHaveWhereToLook', r.openHasWhere, null);
  check('guideAnsweredRowsNoChip', r.answeredNoChip, null);
  check('guideOpenRowsOneChip', r.openOneChip, null);
  check('guideChipVocabulary', r.chipsKnown, r.chipLabels);
  check('guideNoOpenBadge', r.noOpenBadge, null);
  check('guideNoOldStatusWords', r.noOldVocab, null);
  check('guideNoRawUrlInText', r.noRawUrl, null);
  check('guideQuotesFoldedBehindDetails', r.quotesInDetails && r.srcSummary, null);
  check('guideQuotesNotItalic', r.notItalic, null);
  check('guideScopeChips', r.scopes.length > 0 && r.scopes.every(s => /^(County rule|Parish rule|State law · .+|Statewide)$/.test(s)), r.scopes);
  check('guideMetaLinkBeforeChecked', r.metaOrder, null);
  check('guideStillToConfirmCounts', r.todoMatch && r.todoAfterAnswers, null);
  check('guideCountLiveRegion', r.countRole, null);
  check('guideLedgerOrder', r.tabs.join(',') === 'AVAILABLE,AUCTIONS,LIENS_CERTIFICATES', r.tabs);
  check('guideTabsFullAriaLabel', r.tabAria.join('|') === 'Available|Auctions|Liens & Certificates', r.tabAria);
  check('guideShortTabLabelOnPhone', r.shortVisible, null);
  check('guideActiveTab', r.onTab === 'AVAILABLE', r.onTab);
  check('guideShowingPicker', r.showing === 'Showing:', r.showing);
  check('guideCountyViewNoCallout', r.noCallout, null);
  check('guidePhoneNoOverflow', !r.overflow, null);
  check('guidePhoneRailHidden', r.railHidden, null);
  check('guideCoreAnswersOpen', r.allAnsweredOpen && r.buyOpen && r.priceOpen, r);
  check('guideExpandControl', r.expand && r.expand.tag === 'BUTTON' && r.expand.aria === 'true' && r.expand.text === 'Collapse all', r.expand);
  check('guideHeadingsInOrder', r.headings[0] === 1 && r.headings.every((h, i) => i === 0 || h <= r.headings[i - 1] + 1), r.headings);
  check('guideTitleAndHash', /^Buyer's Guide/.test(r.doc) && r.hash.startsWith('#/guide'), r);
  check('guideNoOperatorWording', !OPERATOR.test(await pg.evaluate(() => document.querySelector('.bg-page').innerText)), null);

  // The short version: three lines, sourced only from the file.
  const sv = await readShort(pg);
  check('guideShortVersionThreeLines', sv.map(x => x.key).join(',') === 'what,cost,buy', sv);
  check('guideShortVersionFromFileOnly', shortFromFile(sv, 'FL', 'AVAILABLE', 'Leon'), sv);
  check('guideShortVersionCountyAnswer', sv.find(x => x.key === 'buy')?.from === 'county' && sv.find(x => x.key === 'buy')?.src, sv.find(x => x.key === 'buy'));
  await pg.click('.bg-short-row[data-bg-short="cost"] [data-bg-goto]'); await pg.waitForTimeout(600);
  check('guideShortVersionJumpsToAnswer', await pg.evaluate(() => { const d = document.querySelector('details.bg-q[data-bg-q="price"]'); const t = d.getBoundingClientRect().top; return d.open && t >= -2 && t < innerHeight && document.activeElement === d.querySelector('summary'); }), null);

  // Expand / Collapse all.
  await pg.click('[data-bg-expand]'); await pg.waitForTimeout(150);
  const col = await pg.evaluate(() => ({ none: [...document.querySelectorAll('details.bg-q')].every(d => !d.open), aria: document.querySelector('[data-bg-expand]').getAttribute('aria-expanded'), t: document.querySelector('[data-bg-expand]').textContent.trim() }));
  check('guideCollapseAll', col.none && col.aria === 'false' && col.t === 'Expand all', col);
  await pg.click('[data-bg-expand]'); await pg.waitForTimeout(150);
  check('guideExpandAll', await pg.evaluate(() => [...document.querySelectorAll('details.bg-q')].every(d => d.open) && document.querySelector('[data-bg-expand]').getAttribute('aria-expanded') === 'true'), null);

  // Reader state survives the app.js re-render.
  await pg.selectOption('[data-bg-county]', ''); await pg.waitForTimeout(800);
  const qid = await pg.evaluate(() => { const d = document.querySelector('details.bg-q'); d.open = false; return d.dataset.bgQ; });
  await pg.waitForTimeout(100);
  await pg.fill('[data-bg-search]', 'price'); await pg.waitForTimeout(150);
  await pg.click('[data-bg-ledger="AUCTIONS"]'); await pg.waitForTimeout(800);
  check('guideLedgerSwitchUpdatesHash', await pg.evaluate(() => location.hash.includes('ledger=AUCTIONS')), null);
  check('guideFocusReturnsToTab', await pg.evaluate(() => document.activeElement?.dataset.bgLedger === 'AUCTIONS'), null);
  check('guideSearchSurvivesRerender', await pg.evaluate(() => document.querySelector('[data-bg-search]').value === 'price'), null);
  check('guideSearchCountAnnounced', /match/.test(await pg.evaluate(() => document.querySelector('.bg-count').textContent)), null);
  await pg.fill('[data-bg-search]', ''); await pg.waitForTimeout(100);
  await pg.click('[data-bg-ledger="AVAILABLE"]'); await pg.waitForTimeout(800);
  check('guideClosedIdsSurviveRerender', await pg.evaluate(id => { const d = document.querySelector(`details.bg-q[data-bg-q="${id}"]`); return !!d && !d.open; }, qid), qid);
  await pg.fill('[data-bg-search]', 'redeem'); await pg.waitForTimeout(150);
  await pg.click('[data-bg-ledger="AUCTIONS"]'); await pg.waitForTimeout(800);
  check('guideSearchFilters', await pg.evaluate(() => [...document.querySelectorAll('.bg-q')].filter(d => !d.hidden).length >= 1 && [...document.querySelectorAll('.bg-q')].some(d => d.hidden)), null);
  await pg.fill('[data-bg-search]', 'zzqqxx'); await pg.waitForTimeout(150);
  check('guideEmptySearchState', await pg.evaluate(() => !document.querySelector('.bg-empty').hidden && /No question matches/.test(document.querySelector('.bg-count').textContent)), null);
  await pg.focus('[data-bg-search]'); await pg.keyboard.press('Escape'); await pg.waitForTimeout(100);
  check('guideEscapeClearsSearch', await pg.evaluate(() => document.querySelector('[data-bg-search]').value === '' && document.querySelector('.bg-empty').hidden && !document.querySelector('.bg-q[hidden]')), null);
  check('guideNoErrors', errs.length === 0, errs);
  await pg.closeAll();
}
{ // Florida statewide Auctions, desktop: rail, width, callout, short version, next step
  const { pg, errs } = await open('index.html?look=merged#/guide?ledger=AUCTIONS', { width: 1440, height: 900 });
  const r = await pg.evaluate(() => ({
    title: document.querySelector('.bg-title')?.textContent.trim(),
    pageW: document.querySelector('.bg-page').getBoundingClientRect().width,
    railW: document.querySelector('.bg-rail').getBoundingClientRect().width,
    railSticky: getComputedStyle(document.querySelector('.bg-rail')).position === 'sticky',
    railCol: getComputedStyle(document.querySelector('.bg-rail ol')).flexDirection,
    railLabel: document.querySelector('.bg-rail')?.getAttribute('aria-label'),
    railText: document.querySelector('.bg-rail')?.innerText || '',
    callout: !!document.querySelector('[data-bg-callout]'),
    calloutN: document.querySelectorAll('.bg-callout-list li').length,
    calloutDetails: !!document.querySelector('[data-bg-callout] details'),
    pickerVisible: (() => { const s = document.querySelector('[data-bg-callout-county]'); return !!s && s.checkVisibility(); })(),
    last: window.__tdwGuideLast,
    radius: getComputedStyle(document.querySelector('.bg-step')).borderTopLeftRadius,
    qFont: getComputedStyle(document.querySelector('.bg-q-text')).fontFamily,
    qWeight: getComputedStyle(document.querySelector('.bg-q-text')).fontWeight,
    thumbBg: getComputedStyle(document.querySelector('.bg-seg-thumb')).backgroundColor,
    transition: getComputedStyle(document.querySelector('.bg-seg-thumb')).transitionDuration,
    next: (() => { const n = document.querySelector('.bg-next'); const go = n && n.querySelector('[data-bg-list]'); return n ? { last: n === document.querySelector('.bg-page').lastElementChild, h: n.querySelector('h2')?.textContent, go: go ? go.textContent.trim() : null, count: go ? go.dataset.bgCount : null, others: [...n.querySelectorAll('[data-bg-ledger-go]')].map(x => x.dataset.bgLedgerGo) } : null; })(),
    header: document.getElementById('navCountAuction')?.textContent.trim() || document.getElementById('tabCountAuction')?.textContent.trim(),
  }));
  check('guideStatewideTitle', r.title === 'Auctions in Florida', r.title);
  check('guidePageWidth1120', r.pageW <= 1120 && r.pageW > 1000, r.pageW);
  check('guideDesktopRailCompact', r.railW >= 180 && r.railW <= 240 && r.railSticky && r.railCol === 'column' && r.railLabel === 'On this page' && !/\d+\/\d+/.test(r.railText), r);
  check('guideStatewideCallout', r.callout && r.calloutN === r.last.countyOnly && r.calloutN >= 1, r);
  check('guideCalloutPickerInSight', !r.calloutDetails && r.pickerVisible, r);
  check('guideMergedCardRadius', r.radius === '14px', r.radius);
  check('guideQuestionFont', /Montserrat/.test(r.qFont) && r.qWeight === '500', r);
  check('guideThumbLedgerColour', r.thumbBg === 'rgb(164, 81, 42)', r.thumbBg);
  check('guideThumbSlides', r.transition !== '0s', r.transition);
  const sv = await readShort(pg);
  check('guideShortVersionAuctionsFromFile', sv.length === 3 && shortFromFile(sv, 'FL', 'AUCTIONS', null) && sv[0].from === 'summary', sv);
  // The next step: this ledger's list with the header's own count; the other two guides.
  check('guideNextStepAtBottom', r.next && r.next.last && r.next.h === 'Next step' && r.next.others.join(',') === 'AVAILABLE,LIENS_CERTIFICATES', r.next);
  check('guideNextStepCountIsHeaderCount', r.next && /^\d+$/.test(r.header || '') && r.next.count === r.header && r.next.go.includes(`See the ${r.header} `) && /in Florida/.test(r.next.go), [r.next, r.header]);
  await pg.click('[data-bg-ledger-go="LIENS_CERTIFICATES"]'); await pg.waitForTimeout(800);
  check('guideNextStepOtherGuide', await pg.evaluate(() => location.hash.includes('ledger=LIENS_CERTIFICATES') && /Liens/.test(document.querySelector('.bg-title').textContent) && scrollY < 50), null);
  await pg.click('[data-bg-ledger="AUCTIONS"]'); await pg.waitForTimeout(800);
  await pg.click('[data-bg-list]'); await pg.waitForTimeout(800);
  check('guideNextStepOpensList', await pg.evaluate(() => /^#\/auctions/.test(location.hash) && !document.getElementById('pageList').hidden && document.getElementById('pageGuide').hidden), null);
  await pg.goto(root + 'index.html?look=merged#/guide?ledger=AUCTIONS', { waitUntil: 'networkidle' }); await pg.waitForTimeout(1200);
  const c = await pg.evaluate(() => document.querySelector('[data-bg-callout-county] option:nth-child(2)')?.value);
  await pg.selectOption('[data-bg-callout-county]', c); await pg.waitForTimeout(800);
  check('guideCalloutPickerOpensCounty', await pg.evaluate(c => decodeURIComponent(location.hash).includes('county=' + c) && document.activeElement?.matches('[data-bg-county]'), c), c);
  check('guideDesktopNoErrors', errs.length === 0, errs);
  await pg.closeAll();
}
{ // County deep link from the Available list ("How to acquire in X: Buyer's Guide ->")
  const { pg, errs } = await open('index.html?look=merged#/lands', { width: 1368, height: 777 });
  const link = await pg.evaluate(() => { const l = document.querySelector('.xt-guide-link[data-county]'); return l ? l.dataset.county : null; });
  if (link) await pg.click(`.xt-guide-link[data-county="${link}"]`);
  await pg.waitForTimeout(1200);
  const r = await pg.evaluate(() => ({ hash: decodeURIComponent(location.hash), shown: !document.getElementById('pageGuide').hidden, title: document.querySelector('.bg-title')?.textContent.trim(),
    picker: document.querySelector('[data-bg-county]')?.value, on: document.querySelector('.bg-page')?.dataset.bgCountyOn,
    countyRows: document.querySelectorAll('.bg-q[data-bg-scope="county"]').length, stateRows: document.querySelectorAll('.bg-q[data-bg-scope="state"]').length }));
  check('guideCountyDeepLinkOpensCounty', !!link && r.shown && r.hash.includes('county=' + link) && r.picker === link && r.on === link && r.title === `Available property in ${link} County`, [link, r]);
  check('guideCountyDeepLinkKeepsStatewide', r.stateRows > 0 && r.countyRows + r.stateRows > 3, r);
  check('guideCountyDeepLinkNoErrors', errs.length === 0, errs);
  await pg.closeAll();
}
{ // Statewide answers stay visible under a county's own answer (Citrus: a county how-to-buy)
  // and a county page not yet read does not hide the statewide answer (Bay).
  const { pg } = await open('index.html#/guide?ledger=AVAILABLE&county=Citrus', { width: 1368, height: 777 });
  const ci = await pg.evaluate(() => { const d = document.querySelector('details.bg-q[data-bg-q="how_to_buy"]'); return { scope: d?.dataset.bgScope, also: !!d?.querySelector('.bg-also .bg-answer'), alsoSrc: !!d?.querySelector('.bg-also .bg-meta a[href^="https://"]') }; });
  check('guideStatewideUnderCounty', ci.scope === 'county' && ci.also && ci.alsoSrc, ci);
  await pg.goto(root + 'index.html#/guide?ledger=AVAILABLE&county=Bay', { waitUntil: 'networkidle' }); await pg.waitForTimeout(1000);
  const bay = await pg.evaluate(() => { const d = document.querySelector('.bg-q[data-bg-q="how_to_buy"]'); return { tag: d?.tagName, scope: d?.dataset.bgScope, where: d?.querySelector('.bg-where')?.textContent || '' }; });
  check('guideCountyOpenKeepsStateAnswer', bay.tag === 'DETAILS' && bay.scope === 'state' && /Bay County: not yet confirmed/.test(bay.where), bay);
  await pg.closeAll();
}
{ // #/guide while a property record is open (phone modal and desktop panel); Back returns.
  for (const vp of [{ width: 390, height: 844 }, { width: 1368, height: 777 }]) {
    const { pg, errs } = await open('index.html?look=merged#/lands/p3', vp);
    const before = await pg.evaluate(() => ({ modal: !document.getElementById('detailModal').hidden, panel: !!document.querySelector('#detailPanel.prop-card') }));
    await pg.evaluate(() => { location.hash = '#/guide'; });
    await pg.waitForTimeout(1200);
    const r = await pg.evaluate(() => ({ hash: location.hash, guide: !document.getElementById('pageGuide').hidden, list: !document.getElementById('pageList').hidden, modal: !document.getElementById('detailModal').hidden, title: document.querySelector('#pageGuide .bg-title')?.textContent }));
    check(`guideHashWhileRecordOpen@${vp.width}`, (before.modal || before.panel) && r.hash.startsWith('#/guide') && r.guide && !r.list && !r.modal && !!r.title, [before, r]);
    await pg.goBack(); await pg.waitForTimeout(1000);
    const back = await pg.evaluate(() => ({ hash: location.hash, list: !document.getElementById('pageList').hidden, guide: !document.getElementById('pageGuide').hidden }));
    check(`guideBackFromHashGuide@${vp.width}`, back.list && !back.guide && /^#\/lands/.test(back.hash), back);
    check(`guideHashRecordNoErrors@${vp.width}`, errs.length === 0, errs);
    await pg.closeAll();
  }
}
{ // Phone + dark theme: no overflow, body text at least 4.5:1.
  for (const path of ['index.html?look=merged#/guide?ledger=AVAILABLE', 'index.html?look=merged#/guide?ledger=AUCTIONS&county=Leon']) {
    const { pg, errs } = await open(path, { width: 390, height: 844 }, {}, 'dark');
    const r = await pg.evaluate(() => {
      const rgb = s => { const m = s.match(/[\d.]+/g); return m ? m.slice(0, 4).map(Number) : [0, 0, 0, 1]; };
      const lum = ([r, g, b]) => { const f = v => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; }; return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b); };
      const bgOf = el => { const layers = []; for (let e = el; e; e = e.parentElement) { const c = rgb(getComputedStyle(e).backgroundColor); if (c[3] === undefined) c[3] = 1; if (c[3] > 0) { layers.push(c); if (c[3] >= 1) break; } } let out = [255, 255, 255]; for (const c of layers.reverse()) { const a = c[3] ?? 1; out = out.map((v, i) => v * (1 - a) + c[i] * a); } return out; };
      const bad = [];
      document.querySelectorAll('.bg-page p, .bg-page dt, .bg-page dd span, .bg-page summary, .bg-page a, .bg-page button, .bg-page li, .bg-page h1, .bg-page h2, .bg-page h3').forEach(el => {
        if (!el.checkVisibility() || !el.textContent.trim()) return;
        const fg = rgb(getComputedStyle(el).color), bg = bgOf(el);
        const L1 = lum(fg), L2 = lum(bg), ratio = (Math.max(L1, L2) + 0.05) / (Math.min(L1, L2) + 0.05);
        if (ratio < 4.5) bad.push(el.className + ':' + el.textContent.trim().slice(0, 30) + ':' + ratio.toFixed(2));
      });
      return { theme: document.documentElement.dataset.theme, overflow: document.documentElement.scrollWidth > innerWidth + 1, bad: bad.slice(0, 8), n: bad.length };
    });
    check(`guideDarkTheme@${path.slice(-25)}`, r.theme === 'dark', r.theme);
    check(`guideDarkPhoneNoOverflow@${path.slice(-25)}`, !r.overflow, r);
    check(`guideDarkContrast@${path.slice(-25)}`, r.n === 0, r.bad);
    check(`guideDarkNoErrors@${path.slice(-25)}`, errs.length === 0, errs);
    await pg.closeAll();
  }
}
{ // reduced motion: no transitions or animations
  const { pg } = await open('index.html#/guide?ledger=AUCTIONS', { width: 1440, height: 900 }, { reducedMotion: 'reduce' });
  const r = await pg.evaluate(() => ({ t: getComputedStyle(document.querySelector('.bg-seg-thumb')).transitionDuration, a: getComputedStyle(document.querySelector('details.bg-q[open]>.bg-a')).animationName }));
  // The app-wide reduced-motion rule (identity.css, motion system 2026-11-10) sets every
  // transition to .01ms so transitionend still fires; anything at or under that is instant.
  const instant = d => d.split(',').every(x => { x = x.trim(); const v = parseFloat(x); return x.endsWith('ms') ? v <= 0.01 : v <= 0.00001; });
  check('guideReducedMotion', instant(r.t) && r.a === 'none', r);
  await pg.closeAll();
}
{
  const { pg, errs } = await open('co.html#/guide?ledger=LIENS_CERTIFICATES');
  const r = await pg.evaluate(() => ({ eyebrow: (document.querySelector('.bg-eyebrow')?.textContent || '') + ' / ' + (document.querySelector('.bg-title')?.textContent || ''), florida: /Florida/.test(document.querySelector('.bg-page')?.textContent || '') }));
  check('guideOtherStateNamesItself', /Colorado/.test(r.eyebrow) && !r.florida, r);
  const sv = await readShort(pg);
  check('guideOtherStateShortFromFile', sv.length === 3 && shortFromFile(sv, 'CO', 'LIENS_CERTIFICATES', null), sv);
  check('guideOtherStateNoErrors', errs.length === 0, errs);
  await pg.closeAll();
}
{
  const { pg, errs } = await open('la.html#/guide?ledger=AVAILABLE');
  const r = await pg.evaluate(() => ({ opts: [...document.querySelectorAll('[data-bg-county] option')].slice(1).map(o => o.textContent), text: document.querySelector('.bg-page')?.innerText || '' }));
  check('guideParishUnit', r.opts.length > 0 && r.opts.every(o => /Parish$|City$/.test(o)), r.opts.slice(0, 3));
  check('guideLaNoErrors', errs.length === 0, errs);
  await pg.closeAll();
}
{ // A state whose short-version answers are missing says so (Wisconsin Available: none verified).
  const { pg } = await open('wi.html#/guide?ledger=AVAILABLE');
  const sv = await readShort(pg);
  check('guideShortVersionMissingSaysSo', sv.length === 3 && sv.filter(x => x.key !== 'what').every(x => x.from === 'missing' && /Not yet confirmed/.test(x.text)) && shortFromFile(sv, 'WI', 'AVAILABLE', null), sv);
  await pg.closeAll();
}
{
  const { pg } = await open('index.html#/lands');
  const has = await pg.evaluate(() => [...document.querySelectorAll('#accountGoto [data-goto="guide"]')].length === 1);
  check('guideInAccountMenu', has, has);
  await pg.closeAll();
}
await b.close();
process.exit(fail ? 1 : 0);
