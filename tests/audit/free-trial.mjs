// Owner, 2026-11-17: "all accounts under free should not need approval - let
// them try the beginners tier for 7 days." Migration 041.
//  - an unapproved account inside its trial enters the app (no pending screen),
//    sees the Guided tier only, and a banner with the days left;
//  - once the trial has ended it gets the Free preview, which says so;
//  - an unapproved account with no trial date (041 not applied) still gets
//    the pending preview, as before.
import { chromium } from 'playwright';
import fs from 'fs';
const BASE = (process.env.BASE_URL || 'http://localhost:8934/index.html').replace(/\/$/, '/index.html');
const exe = '/opt/pw-browsers/chromium';
const b = await chromium.launch(fs.existsSync(exe) ? { executablePath: exe } : {});
let fail = 0;
const check = (name, ok, got) => { console.log((ok ? 'PASS ' : 'FAIL ') + name + (ok ? '' : ' -> ' + JSON.stringify(got))); if (!ok) fail++; };
const errs = [];
async function look(profile) {
  const ctx = await b.newContext({ viewport: { width: 1400, height: 900 }, serviceWorkers: 'block' });
  const pg = await ctx.newPage();
  pg.on('pageerror', e => errs.push(profile + ': ' + e.message));
  await pg.goto(BASE + '?profile=' + profile + '#/auctions', { waitUntil: 'networkidle' });
  await pg.waitForTimeout(1500);
  const r = await pg.evaluate(() => ({
    app: !document.getElementById('app').hidden,
    pending: !document.getElementById('pendingGate').hidden,
    banner: (document.getElementById('trialBanner') || {}).textContent || '',
    pvTitle: (document.getElementById('pvBannerTitle') || {}).textContent || '',
    tiers: window.__tdwTiers ? window.__tdwTiers() : null
  }));
  await ctx.close();
  return r;
}
const t = await look('trial');
check('trialEntersApp', t.app && !t.pending, t);
check('trialIsGuidedOnly', t.tiers && t.tiers.account === 'beginner' && JSON.stringify(t.tiers.selectable) === '["beginner"]' && t.tiers.role === 'trial', t.tiers);
check('trialBannerShowsDaysLeft', /7-day Guided trial - 3 days left/.test(t.banner), t.banner);
const e = await look('trialended');
check('endedTrialGetsFreePreview', !e.app && e.pending, e);
check('endedTrialPreviewSaysSo', /trial has ended/.test(e.pvTitle), e.pvTitle);
const p = await look('pending');
check('noTrialDateStillPending', !p.app && p.pending && /waiting for approval/.test(p.pvTitle), p);
check('noPageErrors', errs.length === 0, errs);
await b.close();
console.log(fail ? `FAIL: ${fail} check(s)` : 'ALL PASS');
process.exit(fail ? 1 : 0);
