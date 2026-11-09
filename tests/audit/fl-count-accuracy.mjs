// Florida customer-count accuracy (2026-11-09, FL-AVAIL-2/3/4/5/7):
// - an admin sees the Available rows their source has not confirmed, but the
//   admin's totals leave them out (the customer number minus only the admin's
//   own hidden rows) and one line says so;
// - the ledger tab names what it leaves out for this viewer;
// - the ledger status strip and the State rules page count current listings
//   only, never closed rows or this viewer's hidden rows;
// - the hidden badge says it counts every ledger, closed rows included.
import { chromium } from 'playwright';
import fs from 'fs';
const BASE = process.env.BASE_URL || 'http://localhost:8934/index.html';
const root = BASE.replace(/[^/]*$/, '');
const exe = '/opt/pw-browsers/chromium';
const b = await chromium.launch(fs.existsSync(exe) ? { executablePath: exe } : {});
let fail = 0;
const check = (name, ok, got) => { console.log((ok ? 'PASS ' : 'FAIL ') + name + (ok ? '' : ' -> ' + JSON.stringify(got))); if (!ok) fail++; };
const errors = [];
const open = async (qs, hash) => {
  const pg = await b.newPage({ viewport: { width: 1280, height: 900 } });
  pg.on('pageerror', e => errors.push(e.message));
  await pg.goto(root + 'index.html?look=classic' + qs + hash, { waitUntil: 'networkidle' });
  await pg.waitForTimeout(1800);
  return pg;
};
const listFacts = pg => pg.evaluate(() => {
  const tab = document.getElementById('navCountLaft');
  const cards = [...document.querySelectorAll('#main .prop-card')].map(c => c.dataset.pid);
  const line = document.getElementById('ledgerUnconfirmedAdmin');
  const strip = document.querySelector('.ledger-status[data-ledger-status="laft"]');
  const total = strip && strip.querySelector('[data-ls-total]');
  const title = (document.getElementById('listTotal') || {}).textContent || (document.getElementById('listCount') || {}).textContent || '';
  return { tab: tab ? tab.textContent.trim() : null, tabTitle: tab ? tab.title : null, cards,
    line: line ? { n: line.dataset.unconfirmedAdmin, text: line.textContent.trim() } : null,
    lsTotal: total ? total.dataset.lsTotal : null, title: title.replace(/\D/g, '') };
});

// Customer (tester) and admin, both with Bay p3 and Citrus p15 unconfirmed.
let pg = await open('&unconfirmed=1', '#/lands');
const cust = await listFacts(pg);
await pg.close();
pg = await open('&unconfirmed=1&profile=admin', '#/lands');
const adm = await listFacts(pg);
await pg.close();
check('adminSeesUnconfirmedRows', adm.cards.includes('p3') && adm.cards.includes('p15'), adm.cards);
check('customerDoesNotSeeThem', !cust.cards.includes('p3') && !cust.cards.includes('p15'), cust.cards);
check('adminLineCountsThem', !!adm.line && adm.line.n === '2' && /^2 not confirmed by the source - shown to you, withheld from customers and not counted here\.$/.test(adm.line.text), adm.line);
check('noAdminLineForCustomer', cust.line === null, cust.line);
const admCounted = adm.cards.filter(id => id !== 'p3' && id !== 'p15').length;
check('adminTabLeavesThemOut', adm.tab === String(admCounted), { tab: adm.tab, admCounted });
check('adminTitleLeavesThemOut', adm.title === String(admCounted), { title: adm.title, admCounted });
check('adminTabSaysWhy', /not confirmed by the source/.test(adm.tabTitle || ''), adm.tabTitle);
check('customerTabEqualsCards', cust.tab === String(cust.cards.length), cust);

// Hidden by you: the tab names it; the badge says it covers every ledger.
pg = await open('&hiddenrows=p3', '#/lands');
const hid = await listFacts(pg);
const badge = await pg.evaluate(() => {
  const btn = document.getElementById('hiddenListBtn');
  return btn ? { text: btn.textContent.replace(/\s+/g, ' ').trim(), all: btn.dataset.hiddenAll, cur: btn.dataset.hiddenCurrent } : null;
});
await pg.close();
check('tabSaysHiddenByYou', /^Not counted: 1 hidden by you$/.test(hid.tabTitle || ''), hid.tabTitle);
check('hiddenRowNotInTab', !hid.cards.includes('p3') && hid.tab === String(hid.cards.length), hid);
check('badgeSaysAllLedgers', !!badge && /\(all ledgers, incl\. closed\)/.test(badge.text) && badge.all === '1' && badge.cur === '1', badge);

// The State rules page counts current listings only: never this viewer's
// hidden rows (p3 hidden) nor a closed row still in its grace window (p3
// closed) - before 2026-11-09 it counted every loaded row of the ledger.
const rulesCount = pg => pg.evaluate(() => {
  const el = document.querySelector('#rulesLedgerAVAILABLE .ledger-status[data-ledger-status="laft"]');
  const c = el && el.querySelector('[data-ls-count]');
  return c ? c.dataset.lsCount : null;
});
pg = await open('&hiddenrows=p3', '#/rules');
const rulesHidden = await rulesCount(pg);
await pg.close();
check('rulesPageLeavesHiddenOut', rulesHidden === hid.tab && rulesHidden === '1', { rulesHidden, tab: hid.tab });
pg = await open('&closedrows=p3', '#/rules');
const rulesClosed = await rulesCount(pg);
await pg.close();
check('rulesPageLeavesClosedOut', rulesClosed === '1', rulesClosed);

// County figures (search county results, the Map county select) follow the
// same rule: a closed row in its grace window adds nothing to its county.
const countyFacts = async qs => {
  const p2 = await open(qs, '#/map');
  const r = await p2.evaluate(() => {
    const g = window.__tdwSearchGroups('Bay');
    const bay = (g.counties || []).find(c => c.county === 'Bay');
    const opt = [...document.querySelectorAll('#mapCountySelect option')].find(o => /^Bay\b/.test(o.textContent.trim()));
    return { search: bay ? bay.total : null, map: opt ? opt.textContent.trim() : null };
  });
  await p2.close();
  return r;
};
const bayOpen = await countyFacts('');
const bayClosed = await countyFacts('&closedrows=p3');
check('searchCountyLeavesClosedOut', typeof bayOpen.search === 'number' && bayClosed.search === bayOpen.search - 1, { bayOpen, bayClosed });
check('mapCountyLeavesClosedOut', !!bayOpen.map && bayOpen.map !== bayClosed.map, { bayOpen, bayClosed });

check('noPageErrors', errors.length === 0, errors);
await b.close();
process.exit(fail ? 1 : 0);
