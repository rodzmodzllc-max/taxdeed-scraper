// Owner, 2026-11-12: "We're going to create tiers, and as soon as you log in,
// we are going to fix all that ... if it's free, you should automatically be
// able to see blurred out items and not have the links." This audit pins the
// new-customer experience:
//   - tiers at login: pending -> Free preview; approved -> Full record with a
//     Guided switch; admins / testers also get Free preview;
//   - a pending account lands in the preview app, never the bare waiting card;
//   - preview rows carry no forbidden field, in the DOM or in the stubbed
//     get_preview_listings response; blurred cells are glyphs; no links;
//   - the Buyer's Guide opens; locked features explain themselves;
//   - without migration 039 (or when it fails) the page stays useful;
//   - the first-run welcome shows once and re-opens from the account menu;
//   - Sign in and Create account carry equal weight; sign-up says what happens;
//   - no horizontal overflow at 390 px; dark text contrast >= 4.5:1.
import { chromium } from 'playwright';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
const BASE = (process.env.BASE_URL || 'http://localhost:8934/index.html').replace(/\/$/, '/index.html');
const exe = '/opt/pw-browsers/chromium';
const b = await chromium.launch(fs.existsSync(exe) ? { executablePath: exe } : {});
let fail = 0;
const check = (name, ok, got) => { console.log((ok ? 'PASS ' : 'FAIL ') + name + (ok ? '' : ' -> ' + JSON.stringify(got))); if (!ok) fail++; };
const errs = [];
const DESK = { width: 1368, height: 777 }, PHONE = { width: 390, height: 844 };
const SAFE = ['preview_id', 'state', 'county', 'ledger_type', 'source', 'source_id', 'land_use', 'dor_use_code', 'acreage', 'lot_sqft', 'sale_month'];

// Every identifying value the fixture holds (addresses, owners, parcels,
// case / certificate numbers, links): none may reach a pending account's page.
const here = path.dirname(fileURLToPath(import.meta.url));
const STUB = fs.readFileSync(path.join(here, '..', 'vendor', 'supabase-stub.js'), 'utf8');
const SECRETS = [...new Set([...STUB.matchAll(/\b(address|owner_name|parcel|case_no|certificate_no|legal_desc|url_auction|url_appraiser|url_taxcoll|list_url|document_url|purchase_url|photo_url): "([^"]{5,})"/g)]
  .map(m => m[2]).filter(v => !/^https:\/\/x$/.test(v) && !/^\$\{/.test(v)))];

async function open(query, { vp = DESK, theme = null, init = null, ctx: reuse = null } = {}) {
  const ctx = reuse || await b.newContext({ viewport: vp, serviceWorkers: 'block' });
  if (!reuse && theme) await ctx.addInitScript(t => { try { localStorage.setItem('tdw_theme', t); } catch {} }, theme);
  if (!reuse && init) await ctx.addInitScript(init);
  const pg = await ctx.newPage();
  pg.on('pageerror', e => errs.push(query + ': ' + e.message));
  await pg.goto(BASE + query, { waitUntil: 'networkidle' });
  await pg.waitForTimeout(900);
  return { ctx, pg };
}
const overflow = pg => pg.evaluate(() => document.documentElement.scrollWidth - innerWidth);

// Contrast of each visible element's text against its effective background.
const contrast = (pg, sel) => pg.evaluate(sel => {
  const rgb = s => { const m = s.match(/rgba?\(([^)]+)\)/); if (!m) return null; const p = m[1].split(/[ ,/]+/).filter(Boolean).map(Number); return { r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1 }; };
  const lum = c => { const f = v => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); }; return 0.2126 * f(c.r) + 0.7152 * f(c.g) + 0.0722 * f(c.b); };
  const bgOf = el => { for (let e = el; e; e = e.parentElement) { const c = rgb(getComputedStyle(e).backgroundColor); if (c && c.a > 0.5) return c; } return { r: 255, g: 255, b: 255, a: 1 }; };
  const out = [];
  document.querySelectorAll(sel).forEach(el => {
    if (!el.offsetParent && getComputedStyle(el).position !== 'fixed') return;
    if (!el.textContent.trim() || el.closest('.tier-blur')) return;
    const fg = rgb(getComputedStyle(el).color), bg = bgOf(el);
    if (!fg) return;
    const L1 = lum(fg), L2 = lum(bg);
    out.push({ sel: el.className || el.tagName, text: el.textContent.trim().slice(0, 30), ratio: Math.round(((Math.max(L1, L2) + 0.05) / (Math.min(L1, L2) + 0.05)) * 100) / 100 });
  });
  return out;
}, sel);

// ---- 1. Tier mapping ----
{
  const { ctx, pg } = await open('?profile=pending&look=merged');
  const t = await pg.evaluate(() => window.__tdwTiers());
  check('tier-pending-is-free-preview', t.account === 'free' && t.selectable.join() === 'free' && t.page === 'free', t);
  await ctx.close();
}
{
  const { ctx, pg } = await open('?look=merged#/lands/p15');
  await pg.waitForSelector('[data-tier-set]', { timeout: 10000 }).catch(() => {});
  const t = await pg.evaluate(() => ({ tiers: window.__tdwTiers(), sw: [...document.querySelectorAll('[data-tier-set]')].map(x => x.dataset.tierSet) }));
  check('tier-approved-tester-full-record-with-switch', t.tiers.account === 'pro' && t.tiers.page === 'pro' && t.sw.includes('beginner') && t.sw.includes('pro') && t.sw.includes('free'), t);
  await ctx.close();
}
{
  const { ctx, pg } = await open('?look=merged&entitlement=customer&tier=free');
  const t = await pg.evaluate(() => window.__tdwTiers());
  check('tier-approved-customer-guided-or-full-only', t.account === 'pro' && t.selectable.join() === 'beginner,pro' && t.page === 'pro', t);
  await ctx.close();
}
{
  const { ctx, pg } = await open('?look=merged&profile=admin#/lands/p15');
  await pg.waitForSelector('[data-tier-set]', { timeout: 10000 }).catch(() => {});
  const t = await pg.evaluate(() => window.__tdwTiers());
  check('tier-admin-all-three', t.account === 'pro' && t.selectable.join() === 'free,beginner,pro', t);
  const sw = pg.locator('[data-tier-set="free"]').first();
  if (await sw.count()) { await sw.click(); await pg.waitForTimeout(500); }
  const v = await pg.evaluate(() => ({ page: window.__tdwPageTier(), view: (document.querySelector('[data-tier-view]') || {}).dataset?.tierView || null }));
  check('tier-admin-switch-to-free-works', v.page === 'free' && v.view === 'free', v);
  await ctx.close();
}

// ---- 2-7. Pending lands in the preview app ----
{
  const { ctx, pg } = await open('?profile=pending&look=merged');
  const s = await pg.evaluate(() => ({
    pending: !document.getElementById('pendingGate').hidden, app: !document.getElementById('app').hidden,
    shell: !!document.getElementById('previewShell'), oldCard: !!document.querySelector('#pendingGate > .auth-card'),
    banner: (document.getElementById('pvBannerTitle') || {}).textContent || '',
    unlocks: document.querySelectorAll('.pv-unlocks li').length,
    details: !!document.getElementById('pendingDetails') && !document.getElementById('pvDetailsPanel').hidden,
    tabs: [...document.querySelectorAll('#pvTabs [data-pv-tab]')].map(x => x.dataset.pvTab),
    cards: document.querySelectorAll('#pvListRoot .pv-card').length,
    listCalls: window.__stubGetPropertiesCalls || 0
  }));
  check('pending-lands-in-preview-not-bare-card', s.pending && !s.app && s.shell && !s.oldCard, s);
  check('pending-banner-copy', s.banner === "Your account is waiting for approval. Here's a preview of what's inside." && s.unlocks === 4, s);
  check('pending-details-form-reachable-from-banner', s.details, s);
  check('pending-tabs-ledgers-and-guide', s.tabs.join() === 'laft,auction,certificate,guide', s.tabs);
  check('pending-shows-real-preview-rows', s.cards > 0, s.cards);
  check('pending-never-reads-full-listings', s.listCalls === 0, s.listCalls);

  // every ledger: DOM and RPC carry no forbidden value
  const leaks = [];
  for (const tab of ['laft', 'auction', 'certificate']) {
    await pg.click(`#pvTabs [data-pv-tab="${tab}"]`); await pg.waitForTimeout(400);
    const dom = await pg.evaluate(() => ({ html: document.getElementById('previewShell').outerHTML.replace(/<div id="pvGuideRoot"[\s\S]*?<\/main>/, '</main>'),
      text: document.getElementById('pvListRoot').innerText, links: document.querySelectorAll('#pvListRoot a[href]').length,
      money: /\$\s?\d/.test(document.getElementById('pvListRoot').innerText) }));
    SECRETS.forEach(v => { if (dom.html.includes(v)) leaks.push(tab + ': ' + v); });
    check(`preview-${tab}-no-links`, dom.links === 0, dom.links);
    check(`preview-${tab}-no-money`, !dom.money, dom.text.slice(0, 200));
  }
  check('preview-dom-holds-no-identifying-value', leaks.length === 0 && SECRETS.length > 10, { leaks, secrets: SECRETS.length });
  const rpc = await pg.evaluate(() => (window.__stubPreviewLog || []).map(x => x.res));
  const keys = new Set(), rpcLeaks = [];
  rpc.forEach(r => (r.data || []).forEach(row => { Object.keys(row).forEach(k => keys.add(k)); const j = JSON.stringify(row); SECRETS.forEach(v => { if (j.includes(v)) rpcLeaks.push(v); }); }));
  check('preview-rpc-returns-safe-columns-only', rpc.length >= 3 && [...keys].every(k => SAFE.includes(k)) && keys.size === SAFE.length, [...keys]);
  check('preview-rpc-holds-no-identifying-value', rpcLeaks.length === 0, rpcLeaks);
  check('preview-rpc-capped-at-60', (await pg.evaluate(() => (window.__stubPreviewLog || []).every(x => x.args.p_limit <= 60))), null);
  const ids = await pg.evaluate(() => (window.__stubPreviewLog || []).flatMap(x => (x.res.data || []).map(r => r.preview_id)));
  check('preview-ids-are-opaque', ids.length > 0 && ids.every(id => !/^p[a-z0-9]{0,4}$/.test(id) && id.length >= 24), ids.slice(0, 3));

  // blurred cells are glyphs
  await pg.click('#pvTabs [data-pv-tab="auction"]'); await pg.waitForTimeout(300);
  const blurs = await pg.evaluate(() => [...document.querySelectorAll('#pvListRoot .tier-blur')].map(x => x.textContent));
  check('preview-blurred-cells-are-glyphs', blurs.length > 0 && blurs.every(t => /^[█$,\s]+$/.test(t)), blurs.slice(0, 4));
  const month = await pg.evaluate(() => [...document.querySelectorAll('#pvListRoot .pv-facts span')].map(x => x.textContent).filter(t => /^Sale in /.test(t)));
  check('preview-auctions-show-sale-month-only', month.length > 0 && month.every(t => /^Sale in [A-Z][a-z]+ \d{4}$/.test(t)), month);

  // opening a record: the Free preview record with the approval call to action
  await pg.locator('#pvListRoot .pv-card-btn').first().click(); await pg.waitForTimeout(500);
  const d = await pg.evaluate(() => {
    const m = document.getElementById('previewDetail');
    return { open: !m.hidden, view: (m.querySelector('[data-tier-view]') || {}).dataset?.tierView || null, unlock: (m.querySelector('[data-unlock="approval"] b') || {}).textContent || '',
      links: m.querySelectorAll('a[href]').length, glyphs: [...m.querySelectorAll('.tier-blur')].every(x => /^[█$,\s]+$/.test(x.textContent)), img: m.querySelectorAll('img').length,
      html: m.innerHTML };
  });
  const dLeaks = SECRETS.filter(v => d.html.includes(v));
  check('preview-record-is-free-view-with-unlock-cta', d.open && d.view === 'free' && d.unlock === 'Unlocks when your account is approved', d);
  check('preview-record-no-links-no-photo-no-values', d.links === 0 && d.glyphs && d.img === 0 && dLeaks.length === 0, { links: d.links, img: d.img, dLeaks });
  await pg.keyboard.press('Escape'); await pg.waitForTimeout(200);
  check('preview-record-closes-on-escape', await pg.evaluate(() => document.getElementById('previewDetail').hidden), null);

  // locked features explained
  const locks = await pg.evaluate(() => [...document.querySelectorAll('.pv-lock')].map(x => [x.dataset.pvLocked, x.getAttribute('aria-disabled')]));
  await pg.evaluate(() => document.querySelector('[data-pv-locked="watchlist"]').click()); await pg.waitForTimeout(150);
  const note = await pg.textContent('#pvLockedNote');
  check('locked-watchlist-notes-export-explained', locks.map(x => x.join(':')).join() === 'watchlist:true,notes:true,export:true' && /opens when your account is approved/.test(note), { locks, note });

  // Buyer's Guide reachable
  await pg.click('#pvTabs [data-pv-tab="guide"]'); await pg.waitForTimeout(1200);
  const g = await pg.evaluate(() => ({ visible: !document.getElementById('pvGuideRoot').hidden, page: !!document.querySelector('#pvGuideRoot .bg-page'), text: (document.getElementById('pvGuideRoot').innerText || '').length, list: document.getElementById('pvListRoot').hidden }));
  check('buyers-guide-readable-in-preview', g.visible && g.page && g.text > 200 && g.list, g);
  await ctx.close();
}

// ---- 8. Without migration 039 / when it fails ----
for (const [mode, note] of [['absent', 'coming'], ['error', 'unavailable']]) {
  const { ctx, pg } = await open(`?profile=pending&look=merged&previewrpc=${mode}`);
  const s = await pg.evaluate(() => ({ pending: !document.getElementById('pendingGate').hidden, banner: !!document.getElementById('pvBannerTitle'),
    note: (document.querySelector('#pvListRoot [data-pv-note]') || {}).dataset?.pvNote || null, text: document.getElementById('pvListRoot').innerText,
    details: !!document.getElementById('pendingDetails'), retry: !!document.querySelector('#pvListRoot [data-pv-retry]') }));
  check(`rpc-${mode}-keeps-banner-details-and-note`, s.pending && s.banner && s.details && s.note === note && !/error|PGRST|schema cache|timeout/i.test(s.text) && s.retry === (mode === 'error'), s);
  await pg.click('#pvListRoot [data-pv-tab="guide"]'); await pg.waitForTimeout(1200);
  check(`rpc-${mode}-guide-still-opens`, await pg.evaluate(() => !!document.querySelector('#pvGuideRoot .bg-page')), null);
  await ctx.close();
}

// ---- 9. First-run welcome ----
{
  const ctx = await b.newContext({ viewport: DESK, serviceWorkers: 'block' });
  const r1 = await open('?look=merged&newuser=1', { ctx });
  const first = await r1.pg.evaluate(() => ({ shown: !!document.getElementById('welcomeIntro'), steps: document.querySelectorAll('#welcomeIntro .welcome-steps li').length,
    focus: document.activeElement && document.activeElement.className }));
  check('welcome-shown-to-new-approved-account', first.shown && first.steps === 3 && first.focus === 'welcome-go', first);
  await r1.pg.click('#welcomeIntro .welcome-go'); await r1.pg.waitForTimeout(200);
  check('welcome-dismisses', await r1.pg.evaluate(() => !document.getElementById('welcomeIntro') && localStorage.getItem('tdw_welcome_v1:full:u1') === '1'), null);
  await r1.pg.close();
  const r2 = await open('?look=merged&newuser=1', { ctx });
  check('welcome-shown-once', await r2.pg.evaluate(() => !document.getElementById('welcomeIntro')), null);
  await r2.pg.click('#accountBtn'); await r2.pg.waitForTimeout(200);
  await r2.pg.click('#accountMenu [data-welcome-open]'); await r2.pg.waitForTimeout(300);
  check('welcome-reopens-from-account-menu', await r2.pg.evaluate(() => !!document.getElementById('welcomeIntro')), null);
  await r2.pg.keyboard.press('Escape'); await r2.pg.waitForTimeout(150);
  check('welcome-closes-on-escape', await r2.pg.evaluate(() => !document.getElementById('welcomeIntro')), null);
  await ctx.close();
  const { ctx: c3, pg: p3 } = await open('?look=merged');
  check('welcome-not-forced-on-established-account', await p3.evaluate(() => !document.getElementById('welcomeIntro') && !!document.querySelector('#accountMenu [data-welcome-open]')), null);
  await c3.close();
  // pending: the lighter inline card
  const pctx = await b.newContext({ viewport: DESK, serviceWorkers: 'block' });
  const q1 = await open('?profile=pending&look=merged', { ctx: pctx });
  check('welcome-light-card-for-pending', await q1.pg.evaluate(() => document.querySelectorAll('#welcomeCard .welcome-steps li').length === 3), null);
  await q1.pg.click('#welcomeCard [data-welcome-dismiss]'); await q1.pg.waitForTimeout(150);
  await q1.pg.close();
  const q2 = await open('?profile=pending&look=merged', { ctx: pctx });
  const gone = await q2.pg.evaluate(() => !document.getElementById('welcomeCard'));
  await q2.pg.click('#pvAccountBtn'); await q2.pg.waitForTimeout(100);
  await q2.pg.click('#pvMenu [data-pv-act="welcome"]'); await q2.pg.waitForTimeout(200);
  check('welcome-light-card-once-and-reopenable', gone && await q2.pg.evaluate(() => !!document.getElementById('welcomeCard')), gone);
  await pctx.close();
}

// ---- 10. Sign-in / sign-up ----
{
  const { ctx, pg } = await open('?stubauth=1&look=merged');
  const t = await pg.evaluate(() => {
    const bs = [...document.querySelectorAll('#authModeTabs [data-auth-tab]')];
    return { n: bs.length, labels: bs.map(x => x.textContent), boxes: bs.map(x => { const r = x.getBoundingClientRect(); return [Math.round(r.width), Math.round(r.height)]; }),
      pressed: bs.map(x => x.getAttribute('aria-pressed')), beforeForm: !!document.getElementById('authModeTabs') && !!(document.getElementById('authModeTabs').compareDocumentPosition(document.getElementById('authForm')) & Node.DOCUMENT_POSITION_FOLLOWING),
      toggle: !!document.getElementById('authModeToggle') };
  });
  check('signup-as-prominent-as-signin', t.n === 2 && t.labels.join('|') === 'Sign in|Create account' && Math.abs(t.boxes[0][0] - t.boxes[1][0]) <= 2 && t.boxes[0][1] === t.boxes[1][1] && t.boxes[0][1] >= 44 && t.beforeForm && t.toggle, t);
  await pg.click('[data-auth-tab="signup"]'); await pg.waitForTimeout(200);
  const s = await pg.evaluate(() => ({ mode: document.getElementById('signInBtn').textContent, first: !document.getElementById('firstName').hidden,
    note: (document.getElementById('authSignupNote') || {}).hidden === false ? document.getElementById('authSignupNote').textContent : null,
    pressed: document.querySelector('[data-auth-tab="signup"]').getAttribute('aria-pressed'),
    side: (() => { const a = document.getElementById('firstName').getBoundingClientRect(), c = document.getElementById('lastName').getBoundingClientRect(); return Math.abs(a.top - c.top) < 2; })() }));
  check('signup-mode-says-instant-preview-then-approval', s.mode === 'Create account' && s.first && s.pressed === 'true' && /instant preview/.test(s.note || '') && /approved/.test(s.note || ''), s);
  check('signup-form-short-names-side-by-side', s.side, s);
  await pg.click('#authModeToggle'); await pg.waitForTimeout(150);
  check('legacy-toggle-still-switches-and-syncs-tabs', await pg.evaluate(() => document.getElementById('signInBtn').textContent === 'Sign in' && document.querySelector('[data-auth-tab="signin"]').getAttribute('aria-pressed') === 'true'), null);
  await ctx.close();
  const o = await open('?stubauth=1&look=merged&oauth=google');
  check('google-button-kept-with-preview-note', await o.pg.evaluate(() => !!document.querySelector('#authGate [data-oauth="google"]') && /instant preview/.test((document.querySelector('.oauth-note') || {}).textContent || '')), null);
  await o.ctx.close();
}

// ---- 11. Phone overflow ----
for (const [name, q, act] of [['pending', '?profile=pending&look=merged', null], ['pending-guide', '?profile=pending&look=merged', '#pvTabs [data-pv-tab="guide"]'],
  ['pending-record', '?profile=pending&look=merged', '#pvListRoot .pv-card-btn'], ['signin', '?stubauth=1&look=merged', null],
  ['signup', '?stubauth=1&look=merged', '[data-auth-tab="signup"]'], ['welcome', '?look=merged&newuser=1', null]]) {
  for (const theme of ['light', 'dark']) {
    const { ctx, pg } = await open(q, { vp: PHONE, theme });
    if (act) { await pg.locator(act).first().click(); await pg.waitForTimeout(900); }
    check(`phone-${name}-${theme}-no-overflow`, (await overflow(pg)) <= 0, await overflow(pg));
    await ctx.close();
  }
}

// ---- 12. Dark contrast ----
{
  const { ctx, pg } = await open('?profile=pending&look=merged', { theme: 'dark' });
  const sel = '.pv-banner-title,.pv-banner-sub,.pv-unlocks b,.pv-unlocks li,.pv-tab,.pv-count,.pv-kind,.pv-place,.pv-facts span,.pv-blur-k,.pv-card-btn,.pv-lock,.pv-lock-desc,.pv-locked h2,.pv-tier-chip,.pv-details-toggle,.welcome-card b,.welcome-steps li > span:last-child > span,.pending-details-lead,#pendingDetails .auth-field > span,.pv-account-btn';
  let r = await contrast(pg, sel);
  await pg.locator('#pvListRoot .pv-card-btn').first().click(); await pg.waitForTimeout(400);
  r = r.concat(await contrast(pg, '.pv-detail-inner .tier-kicker,.pv-detail-inner .detail-address,.pv-detail-inner .tier-facts span,.pv-detail-inner dt,.pv-detail-inner .tier-unlock b,.pv-detail-inner .tier-unlock li,.pv-detail-inner .tier-unlock-btn'));
  const low = r.filter(x => x.ratio < 4.5);
  check('dark-preview-contrast-4.5', r.length > 15 && low.length === 0, low.length ? low : r.length);
  await ctx.close();
  const a = await open('?stubauth=1&look=merged', { theme: 'dark' });
  await a.pg.click('[data-auth-tab="signup"]'); await a.pg.waitForTimeout(150);
  const ra = await contrast(a.pg, '.auth-tab,.auth-signup-note,.auth-signup-note b,#signInBtn,#authLead');
  check('dark-auth-tabs-contrast-4.5', ra.length >= 5 && ra.every(x => x.ratio >= 4.5), ra);
  await a.ctx.close();
  const w = await open('?look=merged&newuser=1', { theme: 'dark' });
  const rw = await contrast(w.pg, '.welcome-dialog h2,.welcome-eyebrow,.welcome-steps b,.welcome-steps li > span:last-child > span,.welcome-note,.welcome-go');
  check('dark-welcome-contrast-4.5', rw.length >= 6 && rw.every(x => x.ratio >= 4.5), rw.filter(x => x.ratio < 4.5));
  await w.ctx.close();
  const l = await open('?profile=pending&look=merged');
  const rl = (await contrast(l.pg, sel)).filter(x => x.ratio < 4.5);
  check('light-preview-contrast-4.5', rl.length === 0, rl);
  await l.ctx.close();
}

check('no-page-errors', errs.length === 0, errs);
await b.close();
console.log(fail ? `${fail} FAILED` : 'ALL PASS');
process.exit(fail ? 1 : 0);
