#!/usr/bin/env python3
"""Read-only check of the DEPLOYED sign-in shell (2026-10-02).

Fetches every state page of a deployed copy of the app (production, or a
Cloudflare Pages branch preview) and checks what a signed-out visitor is
served: the sign-in / sign-up / reset block (#authGate) and the page title
must name the product, never one state. It also prints the deployed
service-worker cache name. Plain GETs, no credentials, nothing written.

    python3 scripts/check_deployed_branding.py --base https://rodz-taxdeeds.pages.dev
    python3 scripts/check_deployed_branding.py --preview-branch fix/x --require --wait 900

--require  exit 1 when a reachable deployment serves a state-branded shell
           (an unreachable preview is reported, not failed: Cloudflare may
           not build previews for every branch).
--wait N   keep re-checking for up to N seconds while the deployment still
           serves the old shell (a Pages build lands minutes after a push).
"""
from __future__ import annotations

import argparse
import re
import sys
import time
import urllib.error
import urllib.request

PRODUCTION = "https://rodz-taxdeeds.pages.dev"
PAGES = ["index.html", "tx.html", "la.html", "mi.html", "wy.html", "sc.html", "co.html", "wi.html", "mo.html", "ok.html", "pa.html", "mn.html"]
STATE_WORDS = re.compile(r"Florida|Texas|Louisiana|Michigan|Wyoming|South Carolina|Colorado|Wisconsin")
TAGLINE = "Public Property Acquisition Intelligence"   # identity redesign, 2026-10-05


def preview_hosts(branch: str) -> list[str]:
    """Cloudflare Pages branch alias: lowercased, non-alphanumerics -> '-',
    trimmed to 28 characters. Both the trimmed and untrimmed spellings are
    tried; only one can exist."""
    slug = re.sub(r"[^a-z0-9]+", "-", branch.lower()).strip("-")
    return [f"https://{s}.rodz-taxdeeds.pages.dev" for s in dict.fromkeys([slug[:28].rstrip("-"), slug])]


def fetch(url: str) -> str | None:
    req = urllib.request.Request(url, headers={"User-Agent": "taxdeed-branding-check", "Cache-Control": "no-cache"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.read().decode("utf-8", "replace")
    except (urllib.error.URLError, TimeoutError, OSError):
        return None


def visible(html: str) -> str:
    html = re.sub(r"<!--.*?-->", " ", html, flags=re.S)
    html = re.sub(r"<(script|style)\b.*?</\1>", " ", html, flags=re.S | re.I)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).replace("&amp;", "&")


def check_page(html: str) -> list[str]:
    problems = []
    title = re.search(r"<title>(.*?)</title>", html, re.S)
    if title and STATE_WORDS.search(title.group(1)):
        problems.append(f"title names a state: {title.group(1).strip()!r}")
    start = html.find('<div id="authGate"')
    if start < 0:
        return problems + ["no #authGate block"]
    end = html.find('<div id="pendingGate"', start)
    gate = visible(html[start:end if end > 0 else len(html)])
    hit = STATE_WORDS.search(gate)
    if hit:
        i = hit.start()
        problems.append(f"sign-in block names a state: {gate[max(0, i - 40):i + 60].strip()!r}")
    if TAGLINE not in gate:
        problems.append(f"sign-in block lacks {TAGLINE!r}")
    return problems


def check(base: str) -> tuple[bool, dict]:
    """(reachable, {page: problems}); also prints the service-worker cache."""
    report, reachable = {}, False
    for page in PAGES:
        html = fetch(f"{base}/{page}")
        if html is None:
            report[page] = ["unreachable"]
            continue
        reachable = True
        report[page] = check_page(html)
    sw = fetch(f"{base}/sw.js") or ""
    m = re.search(r'const CACHE = "([^"]+)"', sw)
    report["sw.js"] = [f"cache {m.group(1)}"] if m else ["no cache name found"]
    return reachable, report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--base", action="append", default=[])
    ap.add_argument("--preview-branch")
    ap.add_argument("--require", action="store_true")
    ap.add_argument("--wait", type=int, default=0)
    a = ap.parse_args(argv)
    bases = a.base + (preview_hosts(a.preview_branch) if a.preview_branch else [])
    if not bases:
        bases = [PRODUCTION]
    failed = False
    for base in bases:
        deadline = time.time() + a.wait
        while True:
            reachable, report = check(base)
            bad = {p: v for p, v in report.items() if p != "sw.js" and v and v != ["unreachable"]}
            if not reachable or not bad or time.time() >= deadline:
                break
            print(f"{base}: still serving a state-branded shell; re-checking in 30 s", flush=True)
            time.sleep(30)
        print(f"== {base}")
        if not reachable:
            print("   unreachable (no deployment at this address)")
            continue
        for page, problems in report.items():
            print(f"   {page}: {'; '.join(problems) if problems else 'neutral sign-in shell'}")
        if bad:
            failed = True
            print(f"   RESULT: state-branded sign-in shell on {len(bad)} page(s)")
        else:
            print("   RESULT: every page serves the neutral sign-in shell")
    return 1 if failed and a.require else 0


if __name__ == "__main__":
    sys.exit(main())
