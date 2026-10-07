// scripts/check_live_browser.mjs - read-only browser check of a deployed host.
//
//   node scripts/check_live_browser.mjs https://taxacq.com https://rodz-taxdeeds.pages.dev
//
// For each base URL, a fresh Chromium context opens /index.html signed out and
// checks: the page lands on the same host over https (no redirect loop), the
// TAXACQ sign-in screen becomes visible, the app booted (no boot failure
// screen, no boot errors recorded), the service worker registers with scope
// "<origin>/" and controls the page after a reload, every same-origin
// request succeeded, and Chromium reported no mixed-content or CSP violation.
// Nothing is typed or submitted. Exit 1 if any host fails.
import { chromium } from "playwright";

const bases = process.argv.slice(2);
if (!bases.length) { console.error("usage: check_live_browser.mjs <base>..."); process.exit(2); }

const browser = await chromium.launch(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {});
let failed = 0;
for (const base of bases) {
  const origin = new URL(base).origin;
  const ctx = await browser.newContext();
  const page = await ctx.newPage();
  const consoleErrors = [];
  const badRequests = [];
  page.on("console", (m) => {
    const t = m.text();
    if (m.type() === "error" || /mixed content|content security policy/i.test(t)) consoleErrors.push(t.slice(0, 200));
  });
  page.on("requestfailed", (r) => { if (r.url().startsWith(origin)) badRequests.push(`${r.url()} ${r.failure()?.errorText}`); });
  page.on("response", (r) => { if (r.url().startsWith(origin) && r.status() >= 400) badRequests.push(`${r.url()} ${r.status()}`); });

  const results = [];
  const check = (ok, line) => { results.push([!!ok, line]); };
  try {
    const resp = await page.goto(`${base}/index.html`, { waitUntil: "load", timeout: 60000 });
    const landed = new URL(page.url());
    check(resp && resp.status() < 400 && landed.origin === origin && (landed.protocol === "https:" || landed.hostname === "localhost"),
      `loaded ${page.url()} (${resp && resp.status()})`);
    await page.waitForSelector("#authGate:not([hidden])", { timeout: 30000 }).catch(() => {});
    check(await page.isVisible("#authGate"), "sign-in screen (#authGate) visible");
    check(/TAXACQ/.test(await page.title()), `title "${await page.title()}"`);
    const boot = await page.evaluate(() => ({
      failure: !!document.querySelector("#bootFailure:not([hidden])"),
      errors: (window.__tdwBootErrors || []).length,
    }));
    check(!boot.failure && boot.errors === 0, `app booted (boot failure screen: ${boot.failure}, boot errors: ${boot.errors})`);
    const reg = await page.evaluate(async () => {
      if (!("serviceWorker" in navigator)) return { scope: null };
      const r = await Promise.race([navigator.serviceWorker.ready, new Promise((res) => setTimeout(() => res(null), 20000))]);
      return { scope: r ? r.scope : null, script: r && r.active ? r.active.scriptURL : null };
    });
    check(reg.scope === `${origin}/`, `service worker scope ${reg.scope} (script ${reg.script})`);
    await page.reload({ waitUntil: "load" });
    const controlled = await page.evaluate(() => !!navigator.serviceWorker.controller);
    check(controlled, `service worker controls the page after reload: ${controlled}`);
    const cache = await page.evaluate(async () => (await caches.keys()).filter((k) => k.startsWith("tdw-shell-")));
    check(cache.length >= 1, `shell cache ${cache.join(", ") || "none"}`);
    check(!badRequests.length, `same-origin requests ok${badRequests.length ? ": " + badRequests.slice(0, 5).join(" | ") : ""}`);
    check(!consoleErrors.some((t) => /mixed content|content security policy/i.test(t)),
      `no mixed-content / CSP violations${consoleErrors.length ? " (console errors: " + consoleErrors.slice(0, 5).join(" | ") + ")" : ""}`);
  } catch (e) {
    check(false, `${e.name}: ${String(e.message).slice(0, 200)}`);
  }
  console.log(`== ${base}`);
  for (const [ok, line] of results) console.log(`${ok ? "PASS" : "FAIL"}  ${line}`);
  if (results.some(([ok]) => !ok)) failed++;
  await ctx.close();
}
await browser.close();
console.log(failed ? `LIVE BROWSER CHECK: ${failed} host(s) failed` : "LIVE BROWSER CHECK OK");
process.exit(failed ? 1 : 0);
