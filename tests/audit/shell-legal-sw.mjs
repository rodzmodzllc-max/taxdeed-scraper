// Shell / legal / service worker (audit F66, F70, F100, F101, F103).
// - Customers never see developer setup text or "[not configured]" on the
//   legal pages, in Contact support or on the plan screen (F66 / F103).
// - The service worker's offline fallback works when the host answers
//   "/x.html" with a 308 to "/x" the way Cloudflare Pages does (F70): a small
//   local server here reproduces those redirects.
// - Phone tap targets: header brand and the card "Record details" toggle
//   are at least 44px (F100).
// - The password-reset and Delete account fields use the app's input style
//   (F101).
import { chromium } from 'playwright';
import fs from 'fs';
import http from 'http';
import path from 'path';

const BASE = process.env.BASE_URL || 'http://localhost:8934/index.html';
const root = BASE.replace(/[^/]*$/, '');
const exe = '/opt/pw-browsers/chromium';
const b = await chromium.launch(fs.existsSync(exe) ? { executablePath: exe } : {});
let fail = 0;
const check = (name, ok, got) => { console.log((ok ? 'PASS ' : 'FAIL ') + name + (ok ? '' : ' -> ' + JSON.stringify(got))); if (!ok) fail++; };
const allErrs = [];
const baseCfgText = await (await fetch(root + 'config.js')).text();

async function open(url, { vp = { width: 1200, height: 900 }, cfg = null } = {}) {
  const ctx = await b.newContext({ viewport: vp, serviceWorkers: 'block' });
  const pg = await ctx.newPage();
  pg.on('pageerror', e => allErrs.push(url + ': ' + e.message));
  if (cfg !== null) await pg.route(/\/config\.js(\?|$)/, r => r.fulfill({ status: 200, contentType: 'application/javascript', body: cfg }));
  await pg.goto(url, { waitUntil: 'networkidle' });
  await pg.waitForTimeout(800);
  return pg;
}
const BAD = /\[not configured\]|config\.js|not complete for this deployment|production-configuration|supportEmail|billing\.planName/;

// 1. Legal pages with nothing configured (today's production config).
for (const f of ['terms', 'privacy', 'acceptable-use', 'source-disclaimer']) {
  const pg = await open(root + f + '.html');
  const text = await pg.evaluate(() => document.body.innerText);
  check('legalNoPlaceholder_' + f, !BAD.test(text), (text.match(BAD) || [])[0]);
  check('legalNoDanglingSeparator_' + f, !/(^|\n)\s*·|·\s*($|\n)|Operator:\s*(·|$)|Effective:\s*$/m.test(text), text.slice(0, 200));
  check('legalNoEmptyClause_' + f, !/\bby \.|\bat \.|\bto \.|\(\s*\)|operated by \(/.test(text), null);
  const missing = await pg.evaluate(() => document.documentElement.getAttribute('data-legal-missing'));
  check('legalMissingStillRecorded_' + f, !!missing && missing.includes('operatorName'), missing);
  if (f === 'privacy') check('privacyNeutralOperatorWording', text.includes('what information the operator of the TAXACQ service collects'), null);
  if (f === 'terms') check('termsSentenceIntact', text.includes('These terms govern your use of the TAXACQ service (the "Service"). By creating an account'), null);
  await pg.context().close();
}

// 2. Legal pages with every value configured show them all.
{
  const cfg = baseCfgText + '\nwindow.TDW_CONFIG.legal = { operatorName: "Fixture Operator LLC", governingLaw: "Fixture law", effectiveDate: "2026-10-05", contactEmail: "fixture@example.com" };\nwindow.TDW_CONFIG.billing = { priceDisplay: "TEST PRICE / month" };\n';
  const pg = await open(root + 'terms.html', { cfg });
  const text = await pg.evaluate(() => document.body.innerText);
  check('legalConfiguredMeta', text.includes('Operator: Fixture Operator LLC · Effective: 2026-10-05'), text.slice(0, 200));
  check('legalConfiguredClauses', ['operated by Fixture Operator LLC', 'governed by Fixture law', '(TEST PRICE / month)', 'Tell us promptly at fixture@example.com'].every(s => text.includes(s)), null);
  check('legalConfiguredContactLink', (await pg.locator('[data-legal="contactEmail"] a').first().getAttribute('href')) === 'mailto:fixture@example.com', null);
  check('legalConfiguredNothingMissing', (await pg.evaluate(() => document.documentElement.getAttribute('data-legal-missing'))) === '', null);
  await pg.context().close();
}

// 3. Contact support (customer) and the plan screen: no setup text.
{
  const pg = await open(BASE + '#/auctions');
  await pg.click('#supportBtn'); await pg.waitForTimeout(150);
  const t = await pg.locator('#supportModal').innerText();
  check('supportUnconfiguredStillExplained', await pg.locator('#supportUnconfigured').isVisible(), null);
  check('supportCustomerNoSetupText', !BAD.test(t), (t.match(BAD) || [])[0]);
  await pg.context().close();
}
{
  const pg = await open(BASE + '?profile=admin#/auctions');
  await pg.click('#supportBtn'); await pg.waitForTimeout(150);
  check('supportAdminSeesSetupNote', await pg.locator('#supportUnconfigured .support-admin-note').count() === 1, null);
  await pg.context().close();
}
{
  const cfg = baseCfgText + '\nwindow.TDW_CONFIG.publicationMode = "preview";\nwindow.TDW_CONFIG.billing = { enabled: true, planName: "", priceDisplay: "" };\n';
  const pg = await open(BASE + '?entitlement=inactive#/list', { cfg });
  const t = ((await pg.locator('#planUnconfigured').textContent()) || '').replace(/\s+/g, ' ').trim();
  check('planCustomerNoSetupText', t === 'Subscriptions are not open yet.', t);
  await pg.context().close();
}

// 4. Phone tap targets (F100).
{
  const pg = await open(BASE + '#/auctions', { vp: { width: 390, height: 844 } });
  const brand = await pg.evaluate(() => { const r = document.getElementById('hdrHomeBtn')?.getBoundingClientRect(); return r ? { w: r.width, h: r.height } : null; });
  check('hdrHomeBtnAtLeast44', !!brand && brand.w >= 44 && brand.h >= 44, brand);
  const sums = await pg.evaluate(() => [...document.querySelectorAll('.card-details > summary')].map(s => s.getBoundingClientRect().height).filter(h => h > 0));
  check('recordDetailsSummaryAtLeast44', sums.length > 0 && sums.every(h => h >= 44), sums.slice(0, 5));
  await pg.context().close();
}

// 5. Reset-password and Delete account fields are styled (F101).
{
  const pg = await open(BASE + '?recovery=1#/auctions', { vp: { width: 390, height: 844 } });
  check('recoveryModalOpens', await pg.locator('#recoveryModal').isVisible(), null);
  const m = await pg.evaluate(() => ['rcNew', 'rcConfirm', 'rcSubmitBtn'].map(id => { const el = document.getElementById(id); const r = el.getBoundingClientRect(); const cs = getComputedStyle(el); return { id, h: r.height, w: r.width, bg: cs.backgroundColor, fw: cs.fontWeight }; }));
  const modalW = await pg.evaluate(() => document.getElementById('rcNew').closest('form').getBoundingClientRect().width);
  check('recoveryInputsTouchSized', m.slice(0, 2).every(x => x.h >= 40 && x.w >= modalW - 4), m);
  check('recoveryButtonPrimary', m[2].h >= 40 && m[2].w >= modalW - 4 && Number(m[2].fw) >= 700, m[2]);
  await pg.context().close();
}
{
  const pg = await open(BASE + '#/auctions', { vp: { width: 390, height: 844 } });
  await pg.evaluate(() => document.getElementById('deleteAccountBtn').click()); await pg.waitForTimeout(200);
  const h = await pg.evaluate(() => document.getElementById('daConfirm').getBoundingClientRect().height);
  check('deleteAccountInputTouchSized', h >= 40, h);
  await pg.context().close();
}

// 6. Service worker offline fallback behind 308 "pretty URL" redirects (F70).
{
  const dir = process.env.SERVE_DIR || '/tmp/serve'; // CI's serve dir (playwright-test.yml)
  if (!dir || !fs.existsSync(dir)) {
    console.log('FAIL swOfflineFallback -> set SERVE_DIR to the served directory');
    fail++;
  } else {
    const types = { '.html': 'text/html', '.js': 'application/javascript', '.css': 'text/css', '.json': 'application/json', '.svg': 'image/svg+xml', '.png': 'image/png', '.webmanifest': 'application/manifest+json' };
    const srv = http.createServer((req, res) => {
      const u = new URL(req.url, 'http://x');
      let p = u.pathname;
      // Cloudflare Pages: /index.html -> /, /x.html -> /x (308).
      if (p === '/index.html') { res.writeHead(308, { Location: '/' }); return res.end(); }
      if (/^\/[\w-]+\.html$/.test(p)) { res.writeHead(308, { Location: p.replace(/\.html$/, '') }); return res.end(); }
      if (p === '/') p = '/index.html';
      else if (/^\/[\w-]+$/.test(p) && fs.existsSync(path.join(dir, p + '.html'))) p += '.html';
      const f = path.join(dir, p);
      if (!f.startsWith(dir) || !fs.existsSync(f) || fs.statSync(f).isDirectory()) { res.writeHead(404); return res.end(); }
      res.writeHead(200, { 'Content-Type': types[path.extname(f)] || 'application/octet-stream' });
      fs.createReadStream(f).pipe(res);
    });
    await new Promise(r => srv.listen(0, '127.0.0.1', r));
    const origin = 'http://127.0.0.1:' + srv.address().port;
    const ctx = await b.newContext({ viewport: { width: 1200, height: 900 } });
    const pg = await ctx.newPage();
    await pg.goto(origin + '/tx', { waitUntil: 'networkidle' });
    await pg.evaluate(() => navigator.serviceWorker.ready.then(() => true));
    await pg.waitForTimeout(1500);
    const cached = await pg.evaluate(async () => {
      const out = {};
      for (const k of await caches.keys()) {
        const c = await caches.open(k);
        for (const u of ['/tx.html', '/index.html']) { const r = await c.match(u); if (r) out[u] = { redirected: r.redirected, status: r.status }; }
      }
      return out;
    });
    check('swCachedShellsNotRedirected', cached['/tx.html'] && cached['/index.html'] && !cached['/tx.html'].redirected && !cached['/index.html'].redirected, cached);
    await ctx.setOffline(true);
    for (const [route, page] of [['/tx', 'tx'], ['/', 'index']]) {
      let ok = false, err = null;
      try {
        const resp = await pg.goto(origin + route, { waitUntil: 'domcontentloaded' });
        ok = !!resp && resp.status() === 200 && (await pg.locator('#authGate, #app').count()) > 0;
      } catch (e) { err = e.message.split('\n')[0]; }
      check('swOfflineFallbackServes_' + page, ok, err);
    }
    await ctx.close();
    srv.close();
  }
}

check('noPageErrors', allErrs.length === 0, allErrs.slice(0, 5));
await b.close();
process.exit(fail ? 1 : 0);
