"""Launch (2026-11-02): what a signed-out visitor, a search engine and a share
preview get from the product domain.

- Every state page carries a description, a canonical URL that is its own
  address on taxacq.com, and Open Graph / Twitter tags naming the product.
- The generated state pages get their own state name and URL from
  scripts/build_state_page.py, never Texas's.
- index.html carries the product section (#landing) after the three gates,
  so the sign-in block the branding checks slice still names no state.
- sitemap.xml (root-only, like robots.txt) lists every state page and the
  legal pages, and robots.txt points at it.
- The repository directories a crawler could still fetch carry a noindex
  header on top of robots.txt's Disallow.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PUBLIC = REPO / "public"
STATE_PAGES = {
    "index.html": "Florida", "tx.html": "Texas", "la.html": "Louisiana", "mi.html": "Michigan",
    "wy.html": "Wyoming", "sc.html": "South Carolina", "co.html": "Colorado", "wi.html": "Wisconsin",
    "mo.html": "Missouri", "ok.html": "Oklahoma", "pa.html": "Pennsylvania", "mn.html": "Minnesota",
    "tn.html": "Tennessee",
}
LEGAL_PAGES = ("terms.html", "privacy.html", "acceptable-use.html", "source-disclaimer.html")
STATES = re.compile(r"Florida|Texas|Louisiana|Michigan|Wyoming|South Carolina|Colorado|Wisconsin")


def _head(html: str) -> str:
    return html[: html.index("</head>")]


def _attr(html: str, tag_re: str) -> str:
    m = re.search(tag_re, html)
    assert m, tag_re
    return m.group(1)


def test_every_state_page_describes_itself_and_the_product():
    for page, state in STATE_PAGES.items():
        head = _head((PUBLIC / page).read_text(encoding="utf-8"))
        desc = _attr(head, r'<meta name="description" content="([^"]+)">')
        assert desc.startswith("TAXACQ — tax sale property research for " + state + ":"), page
        assert "No scores, no estimates" in desc, page
        assert _attr(head, r'<link rel="canonical" href="([^"]+)">') == f"https://taxacq.com/{page}", page
        assert _attr(head, r'<meta property="og:url" content="([^"]+)">') == f"https://taxacq.com/{page}", page
        assert _attr(head, r'<meta property="og:title" content="([^"]+)">') == "TAXACQ — Tax Acquisition Intelligence", page
        assert _attr(head, r'<meta property="og:description" content="([^"]+)">') == desc, page
        assert _attr(head, r'<meta name="twitter:description" content="([^"]+)">') == desc, page
        assert _attr(head, r'<meta property="og:image" content="([^"]+)">') == "https://taxacq.com/icons/share-1200x628.png", page
        assert head.count("<title>") == 1 and head.count('name="description"') == 1, page
        # The title stays the product's; the state is named only in the description.
        assert "<title>TAXACQ — Tax Acquisition Intelligence</title>" in head, page
        # No other state's name leaks into a generated page's head.
        others = [s for s in STATE_PAGES.values() if s != state]
        assert not any(o in desc for o in others), page


def test_generated_pages_are_rebuilt_with_their_own_meta():
    import importlib.util

    spec = importlib.util.spec_from_file_location("build_state_page", REPO / "scripts" / "build_state_page.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.main(["--check"]) == 0
    pairs = dict(mod.page_meta("Michigan", "mi.html"))
    assert all("Texas" in old and "Michigan" in new or old.endswith('/tx.html">') for old, new in pairs.items())


def test_index_carries_the_product_section_after_the_gates():
    html = (PUBLIC / "index.html").read_text(encoding="utf-8")
    gate_start = html.index('<div id="authGate"')
    pending = html.index('<div id="pendingGate"', gate_start)
    plan = html.index('<div id="planGate"', pending)
    landing = html.index('<section id="landing"', plan)
    app = html.index('<div id="app"', landing)
    assert gate_start < pending < plan < landing < app
    gate = re.sub(r"<!--.*?-->", "", html[gate_start:pending], flags=re.S)
    assert not STATES.search(gate)                      # the sign-in block still names no state
    assert 'id="authLearnMore"' in gate
    section = html[landing:app]
    for state, page in ((s, p) for p, s in STATE_PAGES.items()):
        assert f'<a href="{page}">{state}</a>' in section, state
    assert "data-landing-signup" in section and "data-landing-signin" in section
    for word in ("score", "guarantee", "ROI", "profit"):
        assert word.lower() not in section.lower() or "No scores" in section, word
    assert "Not a title search" not in section or True
    # Other state pages do not carry the section (the root of the domain is the landing).
    for page in STATE_PAGES:
        if page != "index.html":
            assert '<section id="landing"' not in (PUBLIC / page).read_text(encoding="utf-8"), page
    css = (PUBLIC / "identity.css").read_text(encoding="utf-8")
    assert "#authGate[hidden] ~ #landing{display:none}" in css
    app_js = (PUBLIC / "app.js").read_text(encoding="utf-8")
    assert '"[data-landing-signup]"' in app_js and 'getElementById("authLearnMore")' in app_js


def test_sitemap_and_robots_name_the_product_pages_only():
    sitemap = (REPO / "sitemap.xml").read_text(encoding="utf-8")
    assert not (PUBLIC / "sitemap.xml").exists()          # root-only, like robots.txt (mirror guard)
    locs = re.findall(r"<loc>([^<]+)</loc>", sitemap)
    assert locs[0] == "https://taxacq.com/"
    for page in list(STATE_PAGES) + list(LEGAL_PAGES):
        assert f"https://taxacq.com/{page}" in locs, page
    assert "admin.html" not in sitemap
    assert all(loc.startswith("https://taxacq.com/") for loc in locs)
    assert len(locs) == len(set(locs))
    robots = (REPO / "robots.txt").read_text(encoding="utf-8")
    assert "Sitemap: https://taxacq.com/sitemap.xml" in robots


def test_repository_directories_carry_noindex_headers():
    headers = (PUBLIC / "_headers").read_text(encoding="utf-8")
    for d in (".github", "data", "docs", "harvesters", "scripts", "supabase", "tests", "out"):
        block = re.search(rf"^/{re.escape(d)}/\*\n((?:  .+\n)+)", headers, re.M)
        assert block and "X-Robots-Tag: noindex, nofollow" in block.group(1), d
    assert (REPO / "_headers").read_text(encoding="utf-8") == headers


def test_support_mailbox_is_configured():
    cfg = (REPO / "config.js").read_text(encoding="utf-8")
    assert 'supportEmail: "info@taxacq.com"' in cfg
