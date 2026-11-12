// Owner, 2026-11-11: the sign-in screen offers Google, Apple and Microsoft with
// their own marks, and the option is there as soon as a provider is switched on
// in Supabase. The app asks Supabase's public auth settings which providers are
// enabled; the buttons are exactly those, in the order Google, Apple, Microsoft.
// A provider that is off never shows (it would lead to a raw error page); when
// the answer cannot be read, the config.js list decides as before.
import { chromium } from 'playwright';
import fs from 'fs';
const BASE = (process.env.BASE_URL || 'http://localhost:8934/index.html').replace(/\/$/, '/index.html');
const exe = '/opt/pw-browsers/chromium';
const b = await chromium.launch(fs.existsSync(exe) ? { executablePath: exe } : {});
let fail = 0;
const check = (name, ok, got) => { console.log((ok ? 'PASS ' : 'FAIL ') + name + (ok ? '' : ' -> ' + JSON.stringify(got))); if (!ok) fail++; };
const errs = [];

async function gate(query, settings, vp) {
  const ctx = await b.newContext({ viewport: vp || { width: 1280, height: 900 }, serviceWorkers: 'block' });
  const pg = await ctx.newPage();
  pg.on('pageerror', e => errs.push(query + ': ' + e.message));
  let asked = 0, key = null;
  await pg.route('**/auth/v1/settings', route => { asked++; key = route.request().headers()['apikey'] || null;
    if (settings === 'fail') return route.abort();
    if (settings === 500) return route.fulfill({ status: 500, contentType: 'application/json', body: '{}' });
    return route.fulfill({ status: 200, contentType: 'application/json', headers: { 'access-control-allow-origin': '*' }, body: JSON.stringify({ external: settings }) }); });
  await pg.goto(BASE + '?stubauth=1' + query, { waitUntil: 'networkidle' });
  await pg.waitForTimeout(500);
  const got = await pg.evaluate(() => ({ gate: !document.getElementById('authGate').hidden,
    buttons: [...document.querySelectorAll('#authGate [data-oauth]')].map(x => x.getAttribute('data-oauth')),
    text: [...document.querySelectorAll('#authGate [data-oauth]')].map(x => x.textContent.trim()),
    marks: [...document.querySelectorAll('#authGate [data-oauth] svg')].map(s => [...s.querySelectorAll('path')].map(p => p.getAttribute('fill')).join(',')),
    heights: [...document.querySelectorAll('#authGate [data-oauth]')].map(x => Math.round(x.getBoundingClientRect().height)),
    blocks: document.querySelectorAll('#oauthBlock').length,
    beforeForm: !!document.getElementById('oauthBlock') && !!(document.getElementById('oauthBlock').compareDocumentPosition(document.getElementById('authForm')) & Node.DOCUMENT_POSITION_FOLLOWING),
    overflow: document.documentElement.scrollWidth > innerWidth + 1 }));
  return { ctx, pg, got, asked: () => asked, key: () => key };
}

// ---- Supabase has all three on, config.js lists none: all three appear, each with its own mark
{
  const r = await gate('&oauthdetect=1', { email: true, google: true, apple: true, azure: true, github: false });
  check('gateShown', r.got.gate, r.got);
  check('enabledProvidersAppearInOrder', r.got.buttons.join() === 'google,apple,azure' && r.got.blocks === 1 && r.got.beforeForm, r.got);
  check('buttonsNameTheProvider', r.got.text.join('|') === 'Continue with Google|Continue with Apple|Continue with Microsoft', r.got.text);
  check('eachButtonCarriesItsOwnMark', r.got.marks.length === 3 && r.got.marks[0] === '#4285F4,#34A853,#FBBC05,#EA4335' && r.got.marks[1] === 'currentColor' && r.got.marks[2] === '#F25022,#7FBA00,#00A4EF,#FFB900', r.got.marks);
  check('buttonsAreTapSized', r.got.heights.every(h => h >= 44), r.got.heights);
  check('askedWithThePublishableKey', r.asked() === 1 && r.key() === 'sb_publishable_fake', [r.asked(), r.key()]);
  await r.pg.click('[data-oauth="google"]'); await r.pg.waitForTimeout(200);
  const calls = await r.pg.evaluate(() => (window.__stubOAuthCalls || []).map(c => [c.provider, c.redirectTo.endsWith('/index.html')]));
  check('detectedButtonStartsSignIn', calls.length === 1 && calls[0][0] === 'google' && calls[0][1] === true, calls);
  await r.ctx.close();
}

// ---- only Google on: only Google, even though config.js lists all three
{
  const r = await gate('&oauthdetect=1&oauth=google,apple,azure', { email: true, google: true, apple: false });
  check('aProviderThatIsOffNeverShows', r.got.buttons.join() === 'google' && r.got.blocks === 1, r.got);
  await r.ctx.close();
}

// ---- none on: no block at all, the email form stands alone
{
  const r = await gate('&oauthdetect=1&oauth=google', { email: true });
  check('noProvidersNoBlock', r.got.buttons.length === 0 && r.got.blocks === 0, r.got);
  await r.ctx.close();
}

// ---- the answer cannot be read: the config.js list decides, as before
for (const how of ['fail', 500]) {
  const r = await gate('&oauthdetect=1&oauth=apple', how);
  check('unreadableAnswerKeepsConfigList_' + how, r.got.buttons.join() === 'apple', r.got);
  await r.ctx.close();
}

// ---- detection off (the fixture default): Supabase is not asked
{
  const r = await gate('&oauth=google,azure', { google: true, apple: true, azure: true });
  check('detectionOffIsNotAsked', r.asked() === 0 && r.got.buttons.join() === 'google,azure', [r.asked(), r.got.buttons]);
  await r.ctx.close();
}

// ---- phone: three buttons fit, nothing overflows
{
  const r = await gate('&oauthdetect=1', { google: true, apple: true, azure: true }, { width: 360, height: 780 });
  check('phoneButtonsFit', r.got.buttons.length === 3 && !r.got.overflow && r.got.heights.every(h => h >= 44), r.got);
  await r.pg.screenshot({ path: (process.env.SHOT_DIR || '.') + '/oauth-phone.png' }).catch(() => {});
  await r.ctx.close();
}

check('noPageErrors', errs.length === 0, errs);
await b.close();
console.log(fail ? fail + ' FAILED' : 'ALL PASS');
process.exit(fail ? 1 : 0);
