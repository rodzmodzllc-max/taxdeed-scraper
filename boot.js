// Startup watchdog (2026-10-03). A classic script, loaded before the module
// scripts, so it runs even when app.js cannot.
//
// The page ships with #authGate, #pendingGate and #app all hidden, and app.js
// reveals one of them. If app.js fails to load or throws before it gets
// there, the visitor sees an empty dark page with no explanation (the
// production report that prompted this). This shows what went wrong instead,
// with a reload and a cache reset, once the startup has clearly stalled.
(function () {
  var errors = (window.__tdwBootErrors = window.__tdwBootErrors || []);
  function add(msg) { if (msg && errors.length < 20) errors.push(String(msg)); }
  window.addEventListener("error", function (e) {
    var t = e && e.target;
    if (t && t !== window && (t.src || t.href)) add("Could not load " + (t.src || t.href));
    else if (e && e.message) add(e.message + (e.filename ? " (" + e.filename.split("/").pop() + ":" + e.lineno + ")" : ""));
  }, true);
  window.addEventListener("unhandledrejection", function (e) {
    var r = e && e.reason;
    add(r && r.message ? r.message : r);
  });

  var IDS = ["authGate", "pendingGate", "app"];
  function started() {
    // No gate on this page (another page loaded this script): nothing to watch.
    var found = false;
    for (var i = 0; i < IDS.length; i++) {
      var el = document.getElementById(IDS[i]);
      if (el) { found = true; if (!el.hidden) return true; }
    }
    return !found;
  }

  function resetAndReload() {
    var jobs = [];
    try {
      if (navigator.serviceWorker && navigator.serviceWorker.getRegistrations) {
        jobs.push(navigator.serviceWorker.getRegistrations().then(function (rs) {
          return Promise.all(rs.map(function (r) { return r.unregister(); }));
        }));
      }
      if (window.caches && caches.keys) {
        jobs.push(caches.keys().then(function (ks) { return Promise.all(ks.map(function (k) { return caches.delete(k); })); }));
      }
    } catch (e) { /* reload regardless */ }
    Promise.all(jobs).then(reload, reload);
  }
  function reload() { location.reload(); }

  function showPanel() {
    if (document.getElementById("bootFailure")) return;
    var box = document.createElement("div");
    box.id = "bootFailure";
    box.setAttribute("role", "alert");
    box.style.cssText = "max-width:34rem;margin:12vh auto 0;padding:1.5rem;border-radius:12px;" +
      "background:#fff;color:#1b2333;font:15px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;" +
      "box-shadow:0 10px 30px rgba(0,0,0,.35)";
    var h = document.createElement("h2");
    h.textContent = "The app didn't finish loading";
    h.style.cssText = "margin:0 0 .5rem;font-size:1.2rem";
    var p = document.createElement("p");
    p.textContent = "Something stopped it before the sign-in screen appeared. Reloading usually fixes it; " +
      "if not, reset the app's saved files and reload.";
    p.style.margin = "0 0 1rem";
    box.appendChild(h);
    box.appendChild(p);
    var btns = document.createElement("div");
    btns.style.cssText = "display:flex;gap:.5rem;flex-wrap:wrap;margin-bottom:1rem";
    [["bootReload", "Reload", reload], ["bootReset", "Reset app cache and reload", resetAndReload]].forEach(function (b) {
      var btn = document.createElement("button");
      btn.id = b[0];
      btn.type = "button";
      btn.textContent = b[1];
      btn.style.cssText = "padding:.55rem .9rem;border-radius:8px;border:1px solid #b9c2d3;background:#f3f5f9;" +
        "color:#1b2333;font:inherit;cursor:pointer;min-height:40px";
      btn.addEventListener("click", b[2]);
      btns.appendChild(btn);
    });
    box.appendChild(btns);
    var d = document.createElement("details");
    var s = document.createElement("summary");
    s.textContent = "Technical details";
    var pre = document.createElement("pre");
    pre.id = "bootErrors";
    pre.style.cssText = "white-space:pre-wrap;font-size:12px;background:#f3f5f9;padding:.6rem;border-radius:6px;margin:.5rem 0 0";
    pre.textContent = (errors.length ? errors.join("\n") : "No error was reported - the startup script never ran or is still waiting on the network.") +
      "\n" + navigator.userAgent;
    d.appendChild(s);
    d.appendChild(pre);
    box.appendChild(d);
    document.body.appendChild(box);
  }

  var ms = typeof window.__tdwBootTimeoutMs === "number" ? window.__tdwBootTimeoutMs : 15000;
  setTimeout(function check() {
    if (!started()) showPanel();
  }, ms);
})();

// Phone showing the desktop layout (2026-10-06). When the browser's "Desktop
// site" setting is on (Chrome / Samsung Internet; an installed app inherits
// it), the browser ignores this page's mobile viewport and lays the page out
// about 980px wide, then shrinks it onto the phone - every font becomes tiny
// and nothing in the page's CSS can undo it. Detect exactly that case - a
// touch-only device whose screen is phone-sized while the page is laid out far
// wider - and say how to switch it off, in type sized for the shrunken page.
(function () {
  var KEY = "tdw_desktop_site_notice_hidden_v1";
  function detect() {
    var sw = Math.min(screen.width || 0, screen.height || 0);
    var coarse = window.matchMedia && matchMedia("(pointer: coarse)").matches && !matchMedia("(any-pointer: fine)").matches;
    var w = document.documentElement.clientWidth || window.innerWidth || 0;
    return !!(coarse && sw && sw <= 600 && w >= sw * 1.6);
  }
  window.__tdwDesktopSiteDetect = detect;
  function show() {
    try { if (localStorage.getItem(KEY)) return; } catch (e) { /* show anyway */ }
    if (!detect() || document.getElementById("desktopSiteNotice")) return;
    var sw = Math.min(screen.width, screen.height);
    var k = Math.max(1, (document.documentElement.clientWidth || window.innerWidth) / sw);
    var box = document.createElement("div");
    box.id = "desktopSiteNotice";
    box.setAttribute("role", "alert");
    box.style.cssText = "position:relative;z-index:2000;background:#26221d;color:#f4efe6;" +
      "font:" + Math.round(16 * k) + "px/1.4 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;padding:" + Math.round(14 * k) + "px " + Math.round(16 * k) + "px";
    var t = document.createElement("strong");
    t.textContent = "Text too small? Your browser is showing the desktop version.";
    t.style.display = "block";
    var p = document.createElement("span");
    p.textContent = " Turn off \u201cDesktop site\u201d: in Chrome, tap \u22ee then uncheck Desktop site (or Settings \u2192 Site settings \u2192 Desktop site). In Samsung Internet, tap \u2261 then Mobile version. An installed app follows Chrome's setting; reopen it afterwards.";
    p.style.display = "block";
    var b = document.createElement("button");
    b.type = "button";
    b.id = "desktopSiteNoticeClose";
    b.textContent = "Dismiss";
    b.style.cssText = "margin-top:" + Math.round(10 * k) + "px;font:inherit;padding:" + Math.round(8 * k) + "px " + Math.round(14 * k) + "px;" +
      "border:1px solid #f4efe6;background:transparent;color:inherit;border-radius:4px;cursor:pointer";
    b.addEventListener("click", function () { try { localStorage.setItem(KEY, "1"); } catch (e) { /* ignore */ } box.remove(); });
    box.appendChild(t); box.appendChild(p); box.appendChild(b);
    document.body.insertBefore(box, document.body.firstChild);
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", show);
  else show();
})();
