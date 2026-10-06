"""The custom domain taxacq.com (2026-10-06) is an allowed origin for the edge
functions the browser calls (self-signup, billing-checkout, billing-portal),
alongside the existing Pages hostnames, which keep working. Exact hosts only:
a look-alike or suffix domain is never allowed."""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
FILES = ["supabase/functions/self-signup/index.ts", "supabase/functions/_shared/billing_http.ts"]


def allowlist(path: str) -> re.Pattern:
    src = (REPO / path).read_text(encoding="utf-8")
    m = re.search(r"const ALLOWED_ORIGIN = /(.+)/;", src)
    assert m, path
    return re.compile(m.group(1))


def test_both_functions_share_one_allowlist():
    assert allowlist(FILES[0]).pattern == allowlist(FILES[1]).pattern


def test_custom_domain_and_existing_pages_hosts_are_allowed():
    for path in FILES:
        rx = allowlist(path)
        for ok in ("https://taxacq.com", "https://www.taxacq.com", "https://rodz-taxdeeds.pages.dev",
                   "https://fix-branch.rodz-taxdeeds.pages.dev", "http://localhost:8934", "http://127.0.0.1"):
            assert rx.fullmatch(ok), (path, ok)


def test_look_alike_and_insecure_origins_are_refused():
    for path in FILES:
        rx = allowlist(path)
        for bad in ("http://taxacq.com", "https://evil-taxacq.com", "https://taxacq.com.evil.com",
                    "https://api.taxacq.com", "https://taxacq.co", "https://taxacq.com:8443",
                    "https://www.taxacq.com/", "https://evil.com/?https://taxacq.com"):
            assert not rx.fullmatch(bad), (path, bad)
