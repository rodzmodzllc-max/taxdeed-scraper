// Buyer's Guide page (2026-10-29; destination redesign 2026-11-09): #/guide renders per
// state / ledger / county from buyers-guide.json as a journey (Find > Check > Buy > After >
// Risks) with a ledger-coloured hero, one status vocabulary and no operator wording.
import { chromium } from 'playwright';
import fs from 'fs';
const BASE = process.env.BASE_URL || 'http://localhost:8934/index.html';
const root = BASE.replace(/[^/]*$/, '');
const exe = '/opt/pw-browsers/chromium';
const b = await chromium.launch(fs.existsSync(exe) ? { executablePath: exe } : {});
let fail = 0;
const check = (name, ok, got) => { console.log((ok ? 'PASS ' : 'FAIL ') + name + (ok ? '' : ' -> ' + JSON.stringify(got))); if (!ok) fail++; };
const open = async (path, vp = { width: 390, height: 844 }, opts = {}) => {
  const pg = await b.newPage({ viewport: vp, ...opts });
  const errs = []; pg.on('pageerror', e => errs.push(e.message));
  await pg.goto(root + path, { waitUntil: 'networkidle' }); await pg.waitForTimeout(1500);
  return { pg, errs };
};
const LABELS = ['Answered', 'Partly answered', 'Not yet confirmed', 'Official page blocked'];
const OPERATOR = /capture run|runner|HTTP \d{3}|CloudFront|Cloudflare|research network/i;

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
      meter: document.querySelector('.bg-meter-t')?.textContent.trim() || '',
      legal: document.querySelector('.bg-legal')?.textContent || '',
      hero: !!document.querySelector('.bg-hero'),
      steps: [...document.querySelectorAll('.bg-step')].map(s => s.dataset.bgStep),
      stepCounts: [...document.querySelectorAll('.bg-step-c')].every(s => /^\d+\/\d+ answered$/.test(s.textContent.trim())),
      railN: document.querySelectorAll('[data-bg-jump]').length,
      verifiedWithSource: ver.length > 0 && ver.every(d => !!d.querySelector('.bg-meta a[href^="https://"]')),
      verifiedAccent: ver.every(d => getComputedStyle(d).borderLeftWidth === '3px'),
      openHasWhere: open.length > 0 && open.every(d => !!d.querySelector('.bg-where')),
      oneChipEach: rows.every(d => d.querySelectorAll('.bg-chip').length === 1),
      chipLabels: [...new Set([...document.querySelectorAll('.bg-chip')].map(c => c.textContent.trim()))],
      chipsKnown: [...document.querySelectorAll('.bg-chip')].every(c => LABELS.includes(c.textContent.trim())),
      noOpenBadge: !document.querySelector('.bg-q-badge') && !/\bOPEN\b/.test(text),
      noOldVocab: !/Not yet verified|Source restricted|Partly verified/.test(text),
      noRawUrl: !/https?:\/\//.test(text),
      quotesInDetails: quotes.length > 0 && quotes.every(q => q.closest('details.bg-src')),
      srcSummary: [...document.querySelectorAll('details.bg-src > summary')].every(s => s.textContent.trim() === 'Official wording'),
      notItalic: quotes.every(q => getComputedStyle(q).fontStyle !== 'italic'),
      scopes: [...document.querySelectorAll('.bg-scope')].map(s => s.textContent.trim()),
      metaOrder: ver.every(d => { const m = d.querySelector('.bg-meta'); const t = m.innerHTML; const ia = t.indexOf('<a'), ic = t.indexOf('Checked'); return ic < 0 || (ia >= 0 && ia < ic); }),
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
      railHorizontal: getComputedStyle(document.querySelector('.bg-rail ol')).flexDirection === 'row' && getComputedStyle(document.querySelector('.bg-rail')).position === 'sticky',
    };
  }, LABELS);
  check('guideHeroPresent', r.hero, r.hero);
  check('guideLeonTitle', r.title === 'Available property in Leon County', r.title);
  check('guideEyebrowNamesState', r.eyebrow === "Buyer's Guide · Florida", r.eyebrow);
  check('guideLedeIsSummary', r.lede.length > 20, r.lede);
  check('guideMeterIsCount', /^\d+ of \d+ answered from official pages$/.test(r.meter), r.meter);
  check('guideNotLegalAdvice', /Not legal advice/.test(r.legal), r.legal);
  check('guideLeonCounts', r.last && r.last.total >= 4 && r.last.verified >= 1, r.last);
  check('guideJourneyOrder', r.steps.length >= 3 && r.steps.join(',') === ['find', 'check', 'buy', 'after', 'risks', 'more'].filter(s => r.steps.includes(s)).join(','), r.steps);
  check('guideStepCounts', r.stepCounts, null);
  check('guideRailMatchesSteps', r.railN === r.steps.length, [r.railN, r.steps.length]);
  check('guideVerifiedHaveSource', r.verifiedWithSource, null);
  check('guideVerifiedAccent', r.verifiedAccent, null);
  check('guideOpenHaveWhereToLook', r.openHasWhere, null);
  check('guideOneChipPerRow', r.oneChipEach, null);
  check('guideChipVocabulary', r.chipsKnown, r.chipLabels);
  check('guideNoOpenBadge', r.noOpenBadge, null);
  check('guideNoOldStatusWords', r.noOldVocab, null);
  check('guideNoRawUrlInText', r.noRawUrl, null);
  check('guideQuotesBehindDetails', r.quotesInDetails && r.srcSummary, null);
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
  check('guidePhoneChipStrip', r.railHorizontal, null);
  check('guideTitleAndHash', /^Buyer's Guide/.test(r.doc) && r.hash.startsWith('#/guide'), r);
  check('guideNoOperatorWording', !OPERATOR.test(await pg.evaluate(() => document.querySelector('.bg-page').innerText)), null);

  // Reader state survives the app.js re-render.
  const qid = await pg.evaluate(() => { const d = document.querySelector('details.bg-q'); d.open = true; return d.dataset.bgQ; });
  await pg.waitForTimeout(100);
  await pg.fill('[data-bg-search]', 'price'); await pg.waitForTimeout(150);
  await pg.click('[data-bg-ledger="AUCTIONS"]'); await pg.waitForTimeout(800);
  check('guideLedgerSwitchUpdatesHash', await pg.evaluate(() => location.hash.includes('ledger=AUCTIONS')), null);
  check('guideFocusReturnsToTab', await pg.evaluate(() => document.activeElement?.dataset.bgLedger === 'AUCTIONS'), null);
  check('guideSearchSurvivesRerender', await pg.evaluate(() => document.querySelector('[data-bg-search]').value === 'price'), null);
  check('guideSearchCountAnnounced', /match/.test(await pg.evaluate(() => document.querySelector('.bg-count').textContent)), null);
  await pg.fill('[data-bg-search]', ''); await pg.waitForTimeout(100);
  await pg.click('[data-bg-ledger="AVAILABLE"]'); await pg.waitForTimeout(800);
  check('guideOpenIdsSurviveRerender', await pg.evaluate(id => !!document.querySelector(`details.bg-q[data-bg-q="${id}"]`)?.open, qid), qid);
  await pg.fill('[data-bg-search]', 'redeem'); await pg.waitForTimeout(150);
  await pg.click('[data-bg-ledger="AUCTIONS"]'); await pg.waitForTimeout(800);
  check('guideSearchFilters', await pg.evaluate(() => [...document.querySelectorAll('.bg-q')].filter(d => !d.hidden).length >= 1 && [...document.querySelectorAll('.bg-q')].some(d => d.hidden)), null);
  await pg.fill('[data-bg-search]', 'zzqqxx'); await pg.waitForTimeout(150);
  check('guideEmptySearchState', await pg.evaluate(() => !document.querySelector('.bg-empty').hidden && /No question matches/.test(document.querySelector('.bg-count').textContent)), null);
  await pg.focus('[data-bg-search]'); await pg.keyboard.press('Escape'); await pg.waitForTimeout(100);
  check('guideEscapeClearsSearch', await pg.evaluate(() => document.querySelector('[data-bg-search]').value === '' && document.querySelector('.bg-empty').hidden && !document.querySelector('.bg-q[hidden]')), null);
  check('guideNoErrors', errs.length === 0, errs);
  await pg.close();
}
{ // Florida statewide Auctions, desktop: rail, width, callout
  const { pg, errs } = await open('index.html?look=merged#/guide?ledger=AUCTIONS', { width: 1440, height: 900 });
  const r = await pg.evaluate(() => ({
    title: document.querySelector('.bg-title')?.textContent.trim(),
    pageW: document.querySelector('.bg-page').getBoundingClientRect().width,
    railW: document.querySelector('.bg-rail').getBoundingClientRect().width,
    railSticky: getComputedStyle(document.querySelector('.bg-rail')).position === 'sticky',
    railCol: getComputedStyle(document.querySelector('.bg-rail ol')).flexDirection,
    callout: !!document.querySelector('[data-bg-callout]'),
    calloutN: document.querySelectorAll('.bg-callout-list li').length,
    last: window.__tdwGuideLast,
    radius: getComputedStyle(document.querySelector('.bg-step')).borderTopLeftRadius,
    qFont: getComputedStyle(document.querySelector('.bg-q-text')).fontFamily,
    qWeight: getComputedStyle(document.querySelector('.bg-q-text')).fontWeight,
    thumbBg: getComputedStyle(document.querySelector('.bg-seg-thumb')).backgroundColor,
    transition: getComputedStyle(document.querySelector('.bg-seg-thumb')).transitionDuration,
  }));
  check('guideStatewideTitle', r.title === 'Auctions in Florida', r.title);
  check('guidePageWidth1120', r.pageW <= 1120 && r.pageW > 1000, r.pageW);
  check('guideDesktopRail240', Math.round(r.railW) === 240 && r.railSticky && r.railCol === 'column', r);
  check('guideStatewideCallout', r.callout && r.calloutN === r.last.countyOnly && r.calloutN >= 1, r);
  check('guideMergedCardRadius', r.radius === '14px', r.radius);
  check('guideQuestionFont', /Montserrat/.test(r.qFont) && r.qWeight === '500', r);
  check('guideThumbLedgerColour', r.thumbBg === 'rgb(164, 81, 42)', r.thumbBg);
  check('guideThumbSlides', r.transition !== '0s', r.transition);
  await pg.click('[data-bg-callout] summary'); await pg.waitForTimeout(100);
  await pg.click('[data-bg-ledger="AVAILABLE"]'); await pg.waitForTimeout(600);
  await pg.click('[data-bg-ledger="AUCTIONS"]'); await pg.waitForTimeout(600);
  check('guideCalloutStateSurvives', await pg.evaluate(() => !!document.querySelector('[data-bg-callout] details')?.open), null);
  const c = await pg.evaluate(() => document.querySelector('[data-bg-callout-county] option:nth-child(2)')?.value);
  await pg.selectOption('[data-bg-callout-county]', c); await pg.waitForTimeout(800);
  check('guideCalloutPickerOpensCounty', await pg.evaluate(c => decodeURIComponent(location.hash).includes('county=' + c) && document.activeElement?.matches('[data-bg-county]'), c), c);
  check('guideDesktopNoErrors', errs.length === 0, errs);
  await pg.close();
}
{ // reduced motion: no transitions or animations
  const { pg } = await open('index.html#/guide?ledger=AUCTIONS', { width: 1440, height: 900 }, { reducedMotion: 'reduce' });
  const r = await pg.evaluate(() => ({ t: getComputedStyle(document.querySelector('.bg-seg-thumb')).transitionDuration, a: getComputedStyle(document.querySelector('.bg-meter-bar>span')).animationName }));
  // The app-wide reduced-motion rule (identity.css, motion system 2026-11-10) sets every
  // transition to .01ms so transitionend still fires; anything at or under that is instant.
  const instant = d => d.split(',').every(x => { x = x.trim(); const v = parseFloat(x); return x.endsWith('ms') ? v <= 0.01 : v <= 0.00001; });
  check('guideReducedMotion', instant(r.t) && r.a === 'none', r);
  await pg.close();
}
{
  const { pg, errs } = await open('co.html#/guide?ledger=LIENS_CERTIFICATES');
  const r = await pg.evaluate(() => ({ eyebrow: (document.querySelector('.bg-eyebrow')?.textContent || '') + ' / ' + (document.querySelector('.bg-title')?.textContent || ''), florida: /Florida/.test(document.querySelector('.bg-page')?.textContent || '') }));
  check('guideOtherStateNamesItself', /Colorado/.test(r.eyebrow) && !r.florida, r);
  check('guideOtherStateNoErrors', errs.length === 0, errs);
  await pg.close();
}
{
  const { pg, errs } = await open('la.html#/guide?ledger=AVAILABLE');
  const r = await pg.evaluate(() => ({ opts: [...document.querySelectorAll('[data-bg-county] option')].slice(1).map(o => o.textContent), text: document.querySelector('.bg-page')?.innerText || '' }));
  check('guideParishUnit', r.opts.length > 0 && r.opts.every(o => /Parish$|City$/.test(o)), r.opts.slice(0, 3));
  check('guideLaNoErrors', errs.length === 0, errs);
  await pg.close();
}
{
  const { pg } = await open('index.html#/lands');
  const has = await pg.evaluate(() => [...document.querySelectorAll('#accountGoto [data-goto="guide"]')].length === 1);
  check('guideInAccountMenu', has, has);
  await pg.close();
}
await b.close();
process.exit(fail ? 1 : 0);
