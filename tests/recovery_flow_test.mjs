// Password recovery, end to end against the REAL supabase-js (2026-10-09).
//
// tests/run_test.mjs drives the app through tests/vendor/supabase-stub.js,
// which fakes the PASSWORD_RECOVERY event. This suite instead loads the
// site's own vendored @supabase/supabase-js (supabase-js.umd.js, the same
// fallback production uses) and answers its HTTP calls with a fake Supabase
// Auth / REST server (Playwright request interception). So it proves the
// real library + the real app: the recovery fragment survives the app's
// start-up and hash router, PASSWORD_RECOVERY opens the form, the password
// update is authorised by the recovery token alone, a refresh mid-recovery
// keeps the flow, expired links and failures say something actionable, and
// no token or password appears in the page, the console or a message.
//
// No real Supabase project, no e-mail. Run against the CI serve directory:
//   BASE_URL=http://localhost:8934/index.html node tests/recovery_flow_test.mjs
import { chromium } from 'playwright';

const BASE = process.env.BASE_URL || 'http://localhost:8934/index.html';
const SB = 'https://fake-project.supabase.co';        // tests/config.js
const UID = '77777777-7777-4777-8777-777777777777';
const EMAIL = 'reset.test@example.com';
const NEW_PW = 'Fixture-New-Pass-2026';
const b64 = (o) => Buffer.from(JSON.stringify(o)).toString('base64url');
const now = Math.floor(Date.now() / 1000);
const TOKEN = `${b64({ alg: 'HS256', typ: 'JWT' })}.${b64({ sub: UID, role: 'authenticated', aud: 'authenticated', exp: now + 3600, iat: now, email: EMAIL, amr: [{ method: 'otp', timestamp: now }] })}.fixture-signature`;
const RECOVERY_HASH = `#access_token=${TOKEN}&expires_at=${now + 3600}&expires_in=3600&refresh_token=fixture-refresh&token_type=bearer&type=recovery`;
const user = { id: UID, aud: 'authenticated', role: 'authenticated', email: EMAIL, app_metadata: { provider: 'email' }, user_metadata: {}, created_at: '2026-10-01T00:00:00Z' };

const results = {};
const failures = [];
const check = (name, ok, detail = '') => { results[name] = !!ok; if (!ok) failures.push(`${name}${detail ? ': ' + detail : ''}`); };

const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH || undefined });

// One isolated browser context per scenario (fresh sessionStorage).
async function scenario({ approved = true, updateStatus = 200, updateBody = null, viewport } = {}) {
  const log = { userGets: 0, updates: [], resets: [], tokenSeenWrongly: false };
  const ctx = await browser.newContext(viewport ? { viewport, isMobile: true, hasTouch: true } : {});
  await ctx.route('**/*', async (route) => {
    const req = route.request();
    const url = req.url();
    if (url.startsWith('https://esm.sh/')) return route.abort();                        // force the same-origin library
    if (url.startsWith(SB)) {
      const p = new URL(url).pathname;
      const auth = req.headers()['authorization'] || '';
      if (p === '/auth/v1/user' && req.method() === 'GET') { log.userGets++; return route.fulfill({ json: user }); }
      if (p === '/auth/v1/user' && req.method() === 'PUT') {
        const body = JSON.parse(req.postData() || '{}');
        log.updates.push({ bearerIsRecoveryToken: auth === `Bearer ${TOKEN}`, keys: Object.keys(body).sort(), passwordMatches: body.password === NEW_PW });
        if (updateStatus !== 200) return route.fulfill({ status: updateStatus, json: updateBody || { code: 'unexpected_failure', msg: 'internal' } });
        return route.fulfill({ json: user });
      }
      if (p === '/auth/v1/recover') {
        const body = JSON.parse(req.postData() || '{}');
        log.resets.push({ email: body.email, redirectTo: new URL(url).searchParams.get('redirect_to') });
        return route.fulfill({ json: {} });
      }
      if (p.startsWith('/auth/v1/logout')) return route.fulfill({ status: 204, body: '' });
      if (p.startsWith('/auth/v1/token')) return route.fulfill({ status: 400, json: { code: 'invalid_grant', msg: 'no' } });
      if (p.startsWith('/rest/v1/profiles')) {
        log.profileReads = (log.profileReads || []).concat([new URL(url).search.slice(0, 80)]);
        const one = (req.headers()['accept'] || '').includes('vnd.pgrst.object');
        const row = { id: UID, approved, is_admin: false, email: EMAIL };
        return route.fulfill({ json: one ? row : [row] });
      }
      // Functions not in production (e.g. my_entitlement, migration 027): PostgREST's 404.
      if (p.startsWith('/rest/v1/rpc/my_entitlement')) return route.fulfill({ status: 404, json: { code: 'PGRST202', message: 'Could not find the function' } });
      return route.fulfill({ json: [] });
    }
    if (req.resourceType() === 'document' && /\.html(\?|#|$)/.test(url)) {
      // The CI serve copy maps supabase-js to the stub through an importmap;
      // drop it so this suite runs the real library.
      const r = await route.fetch();
      const html = (await r.text()).replace(/<script type="importmap">[\s\S]*?<\/script>/, '');
      return route.fulfill({ response: r, body: html });
    }
    return route.continue();
  });
  const page = await ctx.newPage();
  const consoleText = [];
  page.on('console', (m) => consoleText.push(m.text()));
  page.on('pageerror', (e) => consoleText.push('pageerror: ' + e.message));
  return { ctx, page, log, consoleText };
}

const visible = (page, sel) => page.locator(sel).isVisible();
const text = async (page, sel) => ((await page.locator(sel).textContent()) || '').trim();
const leaks = (s) => s.includes(TOKEN) || s.includes(NEW_PW) || s.includes('fixture-refresh');

// 1-5. Forgot password from the sign-in screen: correct method, allowlisted redirect, neutral reply.
{
  const { ctx, page, log } = await scenario();
  await page.goto(BASE, { waitUntil: 'load' });
  await page.locator('#authGate').waitFor({ state: 'visible', timeout: 15000 });
  check('forgotButtonOnSignIn', await visible(page, '#forgotPasswordBtn'));
  await page.fill('#email', 'nobody-registered@example.com');
  await page.click('#forgotPasswordBtn');
  await page.waitForTimeout(1500);
  check('resetRequestSent', log.resets.length === 1 && log.resets[0].email === 'nobody-registered@example.com', JSON.stringify(log.resets));
  const redirect = (log.resets[0] || {}).redirectTo || '';
  check('redirectIsCanonicalAllowlistedPage', redirect === new URL(BASE).origin + '/index.html', redirect);
  check('neutralMessage', (await text(page, '#authMsg')).startsWith('If an account exists for that email, a password-reset link has been sent.'));
  await ctx.close();
}

// 6-10. A valid recovery link reaches the form; mismatch, policy, success.
{
  const { ctx, page, log, consoleText } = await scenario();
  await page.goto(BASE + RECOVERY_HASH, { waitUntil: 'load' });
  await page.locator('#recoveryModal').waitFor({ state: 'visible', timeout: 15000 });
  check('recoveryFormOpensFromLink', true);
  check('tokenRemovedFromUrl', !(await page.evaluate(() => location.href)).includes('access_token'));
  check('minLengthMatchesSignUp', (await page.locator('#rcNew').getAttribute('minlength')) === '8');
  await page.fill('#rcNew', NEW_PW); await page.fill('#rcConfirm', NEW_PW + 'x');
  await page.click('#rcSubmitBtn');
  check('mismatchRefused', (await text(page, '#rcMsg')) === "Passwords don't match." && log.updates.length === 0);
  await page.evaluate(() => { document.getElementById('rcNew').removeAttribute('minlength'); document.getElementById('rcConfirm').removeAttribute('minlength'); });
  await page.fill('#rcNew', 'short1'); await page.fill('#rcConfirm', 'short1');
  await page.click('#rcSubmitBtn');
  check('policyRefusedClientSide', (await text(page, '#rcMsg')).includes('at least 8 characters') && log.updates.length === 0);
  await page.fill('#rcNew', NEW_PW); await page.fill('#rcConfirm', NEW_PW);
  await page.click('#rcSubmitBtn');
  await page.waitForTimeout(800);
  const u = log.updates[0] || {};
  check('updateAuthorisedByRecoveryTokenOnly', log.updates.length === 1 && u.bearerIsRecoveryToken && u.passwordMatches && !u.keys.includes('id') && !u.keys.includes('email'), JSON.stringify(log.updates));
  check('successMessage', (await text(page, '#rcMsg')).startsWith('Password updated.'));
  check('recoveryFlagCleared', (await page.evaluate(() => sessionStorage.getItem('tdw_recovery_pending'))) === null);
  await page.waitForTimeout(1800);
  check('formClosesAfterSuccess', !(await visible(page, '#recoveryModal')));
  await page.reload({ waitUntil: 'load' }); await page.waitForTimeout(2500);
  check('noReopenAfterSuccess', !(await visible(page, '#recoveryModal')));
  check('noSecretsInConsole', !consoleText.some(leaks), consoleText.filter(leaks).join(' | ').slice(0, 200));
  check('noSecretsInPage', !leaks(await page.content()));
  await ctx.close();
}

// 13. Refresh before saving keeps the recovery flow.
{
  const { ctx, page } = await scenario();
  await page.goto(BASE + RECOVERY_HASH, { waitUntil: 'load' });
  await page.locator('#recoveryModal').waitFor({ state: 'visible', timeout: 15000 });
  await page.reload({ waitUntil: 'load' });
  await page.locator('#recoveryModal').waitFor({ state: 'visible', timeout: 15000 }).catch(() => {});
  check('refreshKeepsRecoveryForm', await visible(page, '#recoveryModal'));
  await ctx.close();
}

// 12. A failed update never shows success; the server's raw text is not shown.
for (const [name, status, body, expect] of [
  ['weakPasswordExplained', 422, { code: 'weak_password', msg: 'Password should be at least 8 characters.', weak_password: { reasons: ['length'] } }, "doesn't meet the requirements"],
  ['expiredSessionExplained', 401, { code: 'session_not_found', msg: 'Session from session_id claim in JWT does not exist' }, 'reset link has expired'],
  ['serverErrorSafe', 500, { code: 'unexpected_failure', msg: 'internal database error at node 7' }, "couldn't update your password"],
]) {
  const { ctx, page } = await scenario({ updateStatus: status, updateBody: body });
  await page.goto(BASE + RECOVERY_HASH, { waitUntil: 'load' });
  await page.locator('#recoveryModal').waitFor({ state: 'visible', timeout: 15000 });
  await page.fill('#rcNew', NEW_PW); await page.fill('#rcConfirm', NEW_PW);
  await page.click('#rcSubmitBtn'); await page.waitForTimeout(1200);
  const msg = await text(page, '#rcMsg');
  check(name, msg.includes(expect) && !msg.startsWith('Password updated') && !msg.includes('node 7') && (await visible(page, '#recoveryModal')), msg);
  await ctx.close();
}

// 7. Expired / used / malformed links.
{
  const { ctx, page } = await scenario();
  await page.goto(BASE + '#error=access_denied&error_code=otp_expired&error_description=Email+link+is+invalid+or+has+expired', { waitUntil: 'load' });
  await page.locator('#authGate').waitFor({ state: 'visible', timeout: 15000 });
  const msg = await text(page, '#authMsg');
  check('expiredLinkOffersNewReset', msg.includes('expired or was already used') && msg.includes('Forgot password?'), msg);
  check('expiredLinkErrorRemovedFromUrl', !(await page.evaluate(() => location.hash)).includes('error'));
  await ctx.close();
}
{
  const { ctx, page } = await scenario();
  await page.goto(BASE + '#access_token=not-a-jwt&type=recovery', { waitUntil: 'load' });
  await page.waitForTimeout(3000);
  check('malformedLinkDoesNotOpenForm', !(await visible(page, '#recoveryModal')));
  await ctx.close();
}

// Recovery is independent of approval: a pending account can reset, then stays on the pending screen.
{
  const { ctx, page, log } = await scenario({ approved: false });
  await page.goto(BASE + RECOVERY_HASH, { waitUntil: 'load' });
  await page.locator('#recoveryModal').waitFor({ state: 'visible', timeout: 15000 });
  check('pendingUserCanReset', true);
  await page.waitForTimeout(2500);
  const gates = { app: await visible(page, '#app'), pending: await visible(page, '#pendingGate'), auth: await visible(page, '#authGate'), log: log.profileReads };
  check('pendingUserStillGated', !gates.app && gates.pending, JSON.stringify(gates));
  await ctx.close();
}

// 14. Phone width: the form fits and its controls are reachable.
{
  const { ctx, page } = await scenario({ viewport: { width: 390, height: 844 } });
  await page.goto(BASE + RECOVERY_HASH, { waitUntil: 'load' });
  await page.locator('#recoveryModal').waitFor({ state: 'visible', timeout: 15000 });
  const box = await page.locator('#rcSubmitBtn').boundingBox();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
  check('mobileFormFits', box && box.x >= 0 && box.x + box.width <= 390 && !overflow, JSON.stringify(box));
  await ctx.close();
}

await browser.close();
console.log(JSON.stringify(results, null, 1));
if (failures.length) { console.error('FAIL: ' + failures.join('\n')); process.exit(1); }
console.log(`PASS: all ${Object.keys(results).length} recovery checks`);
