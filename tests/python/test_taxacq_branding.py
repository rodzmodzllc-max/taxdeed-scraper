"""TAXACQ is the customer-facing product name (2026-10-06).

Customer-facing surfaces - page titles, the sign-in / pending / plan screens,
the navigation brand, the About heading, the PWA manifest, the legal pages,
the admin page, the tab title and support subject app.js writes, and the
digest e-mail - name the product TAXACQ ("Tax Acquisition Intelligence") and
never present the repository's technical name as the product. The technical
identifiers (repository, packages, User-Agent strings, cache prefix, source
ids, production domain) are deliberately unchanged, and so are the names of
the authoritative sources the product cites.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PUBLIC = REPO / "public"
OLD = re.compile(r"tax\s*-?\s*deed\s*-?\s*scraper", re.I)
STATE_PAGES = ["index.html", "tx.html", "la.html", "mi.html", "wy.html", "sc.html", "co.html", "wi.html",
               "mo.html", "ok.html", "pa.html", "mn.html"]
OTHER_PAGES = ["admin.html", "terms.html", "privacy.html", "acceptable-use.html", "source-disclaimer.html"]


def visible(html: str) -> str:
    """What a browser shows (and what a screen reader reads): text and attribute values, comments stripped."""
    html = re.sub(r"<!--.*?-->", " ", html, flags=re.S)
    html = re.sub(r"<(script|style)\b.*?</\1>", " ", html, flags=re.S | re.I)
    attrs = " ".join(re.findall(r'(?:content|alt|title|aria-label|placeholder)="([^"]*)"', html))
    return re.sub(r"<[^>]+>", " ", html) + " " + attrs


def js_strings_outside_comments(src: str) -> str:
    """Every non-comment line (a comment never reaches the screen)."""
    out = []
    for line in src.splitlines():
        s = line.strip()
        if s.startswith("//") or s.startswith("*") or s.startswith("/*"):
            continue
        out.append(re.sub(r"\s//\s.*$", "", line))
    return "\n".join(out)


def test_state_pages_name_the_product_taxacq():
    for page in STATE_PAGES:
        html = (PUBLIC / page).read_text(encoding="utf-8")
        assert "<title>TAXACQ — Tax Acquisition Intelligence</title>" in html, page
        assert html.count("<h1>TAXACQ</h1>") == 3, page            # sign-in, pending approval, plan screens
        assert '<span class="brand-title">TAXACQ</span><span class="brand-sub">Tax Acquisition Intelligence</span>' in html, page
        assert '<span class="brand-name">TAXACQ</span>' in html, page
        assert '<meta name="apple-mobile-web-app-title" content="TAXACQ">' in html, page
        assert '<p class="auth-tagline">Tax Acquisition Intelligence</p>' in html, page
        assert "Find the property. Understand the record. Know how to acquire it." in html, page
        assert '<h3 id="whyHeading">Why TAXACQ</h3>' in html, page


def test_no_customer_facing_page_shows_the_repository_name():
    for page in STATE_PAGES + OTHER_PAGES:
        text = visible((PUBLIC / page).read_text(encoding="utf-8"))
        assert not OLD.search(text), page
        assert "Tax Acquisitions" not in text, page                 # the earlier interim name
    for page in OTHER_PAGES:
        assert "TAXACQ" in visible((PUBLIC / page).read_text(encoding="utf-8")), page


def test_the_brand_is_shown_once_not_paired_with_the_old_name():
    for page in STATE_PAGES:
        gate = (PUBLIC / page).read_text(encoding="utf-8")
        start = gate.find('<div id="authGate"')
        gate = visible(gate[start:gate.find('<div id="pendingGate"', start)])
        assert "TAXACQ" in gate and not OLD.search(gate), page


def test_manifest_and_app_script_use_taxacq():
    manifest = json.loads((PUBLIC / "manifest.webmanifest").read_text(encoding="utf-8"))
    assert manifest["name"] == "TAXACQ — Tax Acquisition Intelligence"
    assert manifest["short_name"] == "TAXACQ"
    assert not OLD.search(json.dumps(manifest))
    app = (PUBLIC / "app.js").read_text(encoding="utf-8")
    code = js_strings_outside_comments(app)
    assert '" · TAXACQ — " + STATE_INFO.name' in code          # tab title after sign-in
    assert "`[TAXACQ] ${title}`" in code                    # support e-mail subject
    for name in ("app.js", "explore.js", "satellite-map.js", "boot.js", "admin.js", "legal.js"):
        assert not OLD.search(js_strings_outside_comments((PUBLIC / name).read_text(encoding="utf-8"))), name
    digest = (REPO / "supabase" / "functions" / "send-digest" / "index.ts").read_text(encoding="utf-8")
    assert "your favorites in TAXACQ." in digest and not OLD.search(digest)


def test_root_copies_carry_the_same_brand():
    for name in STATE_PAGES + OTHER_PAGES + ["manifest.webmanifest", "app.js", "identity.css", "sw.js"]:
        assert (REPO / name).read_text(encoding="utf-8") == (PUBLIC / name).read_text(encoding="utf-8"), name


def test_authoritative_source_names_are_not_rebranded():
    app = (PUBLIC / "app.js").read_text(encoding="utf-8")
    assert "Florida Department of Revenue" in app
    assert "TAXACQ" not in (PUBLIC / "acquisition-evidence.json").read_text(encoding="utf-8")
    assert "TAXACQ" not in (PUBLIC / "source-inventory.json").read_text(encoding="utf-8")
    assert "TAXACQ" not in (PUBLIC / "county-intelligence.json").read_text(encoding="utf-8")


def test_internal_technical_identifiers_are_unchanged():
    # Repository, outbound User-Agent strings, service-worker cache prefix,
    # Python packages and the production domain keep their technical names.
    assert 'USER_AGENT = "taxdeed-scraper/1.0 (+https://github.com/rodzmodzllc-max/taxdeed-scraper' in (
        REPO / "scripts" / "harvest_expansion.py").read_text(encoding="utf-8")
    assert 'const CACHE = "tdw-shell-' in (PUBLIC / "sw.js").read_text(encoding="utf-8")
    for pkg in ("harvesters", "harvesters/sources", "harvesters/enrichment", "harvesters/imagery"):
        assert (REPO / pkg / "__init__.py").exists() or (REPO / pkg).is_dir(), pkg
    assert 'PRODUCTION = "https://rodz-taxdeeds.pages.dev"' in (
        REPO / "scripts" / "check_deployed_branding.py").read_text(encoding="utf-8")
    assert "rodz-taxdeeds" in (REPO / "supabase" / "functions" / "self-signup" / "index.ts").read_text(encoding="utf-8")
    assert "rodzmodzllc-max/taxdeed-scraper" in (REPO / "CLAUDE.md").read_text(encoding="utf-8")
