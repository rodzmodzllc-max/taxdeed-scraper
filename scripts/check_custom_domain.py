#!/usr/bin/env python3
"""Read-only check that the custom domain serves the same deployment as Pages.

  python3 scripts/check_custom_domain.py --domain https://taxacq.com \
      --reference https://rodz-taxdeeds.pages.dev --www https://www.taxacq.com

What it checks (HTTPS GETs only - no form is submitted, nothing is written):
  1. the domain answers over HTTPS with a certificate the system trusts
     (urllib verifies the chain and the host name), with no redirect loop;
  2. every shell file is served by the domain with status 200 and is
     byte-identical to the reference host (one deployment, two names);
  3. sw.js is served as JavaScript, and the Content-Security-Policy header is
     the same on both hosts;
  4. the page references no http:// script, style, image or frame (mixed
     content);
  5. www (when given) either redirects to the domain keeping path and query,
     or does not resolve - it never serves a second copy of the app;
  6. http:// on the domain is upgraded to https:// (advisory NOTE only: a
     Cloudflare zone setting).
Prints a line per check; exit 1 on any failure with --require.
"""
from __future__ import annotations

import argparse
import hashlib
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

SHELL_FILES = ("index.html", "tx.html", "la.html", "app.js", "sw.js", "boot.js", "supabase-loader.js",
               "config.js", "manifest.webmanifest", "styles.css", "identity.css", "explore.js")
MAX_HOPS = 8


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):  # report redirects instead of following them
        return None


_OPENER = urllib.request.build_opener(_NoRedirect, urllib.request.HTTPSHandler(context=ssl.create_default_context()))


def request(url: str):
    """One request (same shape as check_deployed_branding.py's), no redirect following.
    Returns (status, headers, body); TLS is verified by urllib."""
    req = urllib.request.Request(url, headers={"User-Agent": "taxdeed-branding-check", "Cache-Control": "no-cache"})
    try:
        with _OPENER.open(req, timeout=30) as r:
            return r.status, {k.lower(): v for k, v in r.getheaders()}, r.read()
    except urllib.error.HTTPError as e:
        return e.code, {k.lower(): v for k, v in e.headers.items()}, e.read()


def why(status: int, headers: dict, body: bytes) -> str:
    """For a non-200: who answered (Cloudflare challenge / WAF vs. the app)."""
    if status == 200:
        return ""
    bits = [f"server={headers.get('server', '?')}"]
    if headers.get("cf-mitigated"):
        bits.append(f"cf-mitigated={headers['cf-mitigated']}")
    m = re.search(rb"<title>([^<]{0,80})", body or b"", flags=re.I)
    if m:
        bits.append(f"title={m.group(1).decode('utf-8', 'replace').strip()!r}")
    return " [" + ", ".join(bits) + "]"


def follow(url: str):
    """Follow redirects by hand. Returns (final_url, status, headers, body, hops) or raises on a loop."""
    seen, hops = set(), []
    for _ in range(MAX_HOPS):
        if url in seen:
            raise RuntimeError(f"redirect loop at {url}")
        seen.add(url)
        status, headers, body = request(url)
        if status in (301, 302, 303, 307, 308) and headers.get("location"):
            nxt = urllib.parse.urljoin(url, headers["location"])
            hops.append((status, nxt))
            url = nxt
            continue
        return url, status, headers, body, hops
    raise RuntimeError(f"more than {MAX_HOPS} redirects")


def mixed_content(html: str) -> list[str]:
    html = re.sub(r"<!--.*?-->", " ", html, flags=re.S)
    return sorted(set(re.findall(r'(?:src|href|action|poster)\s*=\s*["\'](http://[^"\']+)', html, flags=re.I)))


def injected(domain_body: bytes, reference_body: bytes) -> str:
    """Name the <script> tags the domain serves that the reference does not
    (e.g. something an edge feature adds to the HTML)."""
    tags = lambda b: re.findall(r"<script\b[^>]*>[\s\S]{0,90}", b.decode("utf-8", "replace"), flags=re.I)
    ref = set(tags(reference_body))
    extra = [re.sub(r"\s+", " ", t)[:140] for t in tags(domain_body) if t not in ref]
    return (" [added scripts: " + " || ".join(extra) + "]") if extra else ""


def check(domain: str, reference: str, www: str | None) -> list[tuple[bool, str]]:
    out: list[tuple[bool, str]] = []
    host = urllib.parse.urlsplit(domain).hostname

    try:
        final, status, headers, body, hops = follow(domain + "/")
        same_host = urllib.parse.urlsplit(final).hostname == host and final.startswith("https://")
        out.append((status == 200 and same_host,
                    f"HTTPS {domain}/ -> {status} at {final} after {len(hops)} redirect(s); certificate verified"
                    + why(status, headers, body)))
        html = body.decode("utf-8", "replace")
        out.append(("TAXACQ" in html, "TAXACQ branding in the served page"))
        out.append(('id="authGate"' in html, "sign-in screen (#authGate) present in the served page"))
        mixed = mixed_content(html)
        out.append((not mixed, "no http:// references (mixed content)" + (f": {mixed}" if mixed else "")))
        csp_domain = headers.get("content-security-policy", "")
    except Exception as e:  # noqa: BLE001 - every failure is a reported check
        out.append((False, f"HTTPS {domain}/ failed: {type(e).__name__}: {e}"))
        return out

    try:
        _, rstatus, rheaders, _, _ = follow(reference + "/")
        out.append((rstatus == 200, f"reference {reference}/ -> {rstatus}"))
        out.append((bool(csp_domain) and csp_domain == rheaders.get("content-security-policy", ""),
                    "Content-Security-Policy identical on both hosts"))
    except Exception as e:  # noqa: BLE001
        out.append((False, f"reference {reference}/ failed: {type(e).__name__}: {e}"))

    for name in SHELL_FILES:
        try:
            _, s1, h1, b1, _ = follow(f"{domain}/{name}")
            _, s2, _, b2, _ = follow(f"{reference}/{name}")
            same = s1 == 200 and s2 == 200 and hashlib.sha256(b1).digest() == hashlib.sha256(b2).digest()
            out.append((same, f"{name}: domain {s1}, reference {s2}, {'identical' if same else 'DIFFERENT'}"
                        + why(s1, h1, b1) + (injected(b1, b2) if not same and name.endswith(".html") else "")))
            if name == "sw.js":
                ctype = h1.get("content-type", "")
                out.append(("javascript" in ctype, f"sw.js content-type {ctype!r}"))
                m = re.search(rb'const CACHE = "([^"]+)"', b1)
                out.append((bool(m), f"sw.js cache {m.group(1).decode() if m else 'not found'}"))
        except Exception as e:  # noqa: BLE001
            out.append((False, f"{name}: {type(e).__name__}: {e}"))

    try:
        final, status, _, _, hops = follow(f"http://{host}/tx.html?check=1")
        upgraded = final.startswith("https://") and urllib.parse.urlsplit(final).hostname == host
        # Advisory: plain http is a Cloudflare zone setting ("Always Use HTTPS"), not this repository.
        out.append((None if not upgraded else True,
                    f"http://{host}/ {'upgrades to' if upgraded else 'is served without upgrade at'} {final} ({status})"))
    except Exception as e:  # noqa: BLE001
        out.append((None, f"http://{host}/: {type(e).__name__}: {e}"))

    if www:
        try:
            final, status, _, _, hops = follow(f"{www}/tx.html?check=1")
            fu = urllib.parse.urlsplit(final)
            if fu.hostname == host:
                out.append((fu.path in ("/tx.html", "/tx") and "check=1" in fu.query,
                            f"{www} redirects to {final} (path/query kept)"))
            else:
                _, wst, wh, wb, _ = follow(f"{www}/")
                out.append((False, f"{www} answers itself at {final} ({status}) instead of redirecting"
                            + why(wst, wh, wb)))
        except Exception as e:  # noqa: BLE001
            out.append((True, f"{www} not served ({type(e).__name__}); no second copy of the app"))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--domain", default="https://taxacq.com")
    ap.add_argument("--reference", default="https://rodz-taxdeeds.pages.dev")
    ap.add_argument("--www")
    ap.add_argument("--require", action="store_true")
    ap.add_argument("--wait", type=int, default=0, help="seconds to keep re-checking while files differ")
    a = ap.parse_args(argv)
    deadline = time.time() + a.wait
    while True:
        results = check(a.domain.rstrip("/"), a.reference.rstrip("/"), a.www.rstrip("/") if a.www else None)
        if all(ok is not False for ok, _ in results) or time.time() >= deadline:
            break
        print("domain not yet serving the same build; re-checking in 30 s", flush=True)
        time.sleep(30)
    for ok, line in results:
        print(f"{'PASS' if ok else 'NOTE' if ok is None else 'FAIL'}  {line}")
    failed = [line for ok, line in results if ok is False]
    print("CUSTOM DOMAIN OK" if not failed else f"CUSTOM DOMAIN: {len(failed)} check(s) failed")
    return 1 if failed and a.require else 0


if __name__ == "__main__":
    sys.exit(main())
