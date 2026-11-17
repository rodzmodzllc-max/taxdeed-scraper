// Owner, 2026-11-17: "I want the users to tell me how much they would pay."
// The in-app survey (migration 042): reachable from the account menu and the
// trial banner, validates dollar amounts, saves one row, thanks the person.
import { chromium } from 'playwright';
import fs from 'fs';
const BASE = (process.env.BASE_URL || 'http://localhost:8934/index.html').replace(/\/$/, '/index.html');
const exe = '/opt/pw-browsers/chromium';
const b = await chromium.launch(fs.existsSync(exe) ? { executablePath: exe } : {});
let fail = 0;
const check = (name, ok, got) => { console.log((ok ? 'PASS ' : 'FAIL ') + name + (ok ? '' : ' -> ' + JSON.stringify(got))); if (!ok) fail++; };
const errs = [];
const ctx = await b.newContext({ viewport: { width: 1400, height: 900 }, serviceWorkers: 'block' });
const pg = await ctx.newPage();
pg.on('pageerror', e => errs.push(e.message));
await pg.goto(BASE + '?profile=trial#/auctions', { waitUntil: 'networkidle' });
await pg.waitForTimeout(1500);
check('menuItemPresent', await pg.locator('#accountMenu [data-pricing-survey]').count() === 1);
check('trialBannerButton', await pg.locator('#trialBanner [data-pricing-survey]').count() === 1);
// 3 days left in the fixture -> it opens by itself after 4 s.
await pg.waitForTimeout(4500);
check('autoOpensNearTrialEnd', await pg.locator('#pricingSurvey').count() === 1);
await pg.fill('#pricingSurvey input[name=bargain]', 'abc');
await pg.click('#pricingSurvey .pricing-send');
check('rejectsNonNumber', /dollar amount/.test(await pg.locator('#pricingSurvey .pricing-msg').textContent()));
await pg.fill('#pricingSurvey input[name=too_cheap]', '5');
await pg.fill('#pricingSurvey input[name=bargain]', '$25');
await pg.fill('#pricingSurvey input[name=getting_expensive]', '49');
await pg.fill('#pricingSurvey input[name=too_expensive]', '1,00');
await pg.check('#pricingSurvey input[value=all_states]');
await pg.check('#pricingSurvey input[value=available]');
await pg.click('#pricingSurvey .pricing-send');
await pg.waitForTimeout(500);
const saved = await pg.evaluate(() => window.__tdwPricingSaved || null);
check('savedRow', saved && saved.bargain === 25 && saved.too_cheap === 5 && saved.getting_expensive === 49 && saved.too_expensive === 100 && saved.plan === 'all_states' && JSON.stringify(saved.buys) === '["available"]' && saved.access_role === 'trial', saved);
check('thanksShown', /Thank you/.test(await pg.locator('#pricingSurvey').textContent()));
await pg.click('#pricingSurvey [data-pricing-close]');
check('closes', await pg.locator('#pricingSurvey').count() === 0);
// An approved account: menu item only, never opens by itself.
const p2 = await ctx.newPage();
p2.on('pageerror', e => errs.push(e.message));
await p2.goto(BASE + '#/auctions', { waitUntil: 'networkidle' });
await p2.waitForTimeout(5000);
check('approvedNoAutoOpen', await p2.locator('#pricingSurvey').count() === 0);
check('approvedHasMenuItem', await p2.locator('#accountMenu [data-pricing-survey]').count() === 1);
check('noPageErrors', errs.length === 0, errs);
await b.close();
console.log(fail ? `FAIL: ${fail} check(s)` : 'ALL PASS');
process.exit(fail ? 1 : 0);
