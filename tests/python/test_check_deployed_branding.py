"""scripts/check_deployed_branding.py reads the deployed sign-in shell the way
a signed-out visitor sees it (offline tests against the repository's pages)."""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

import check_deployed_branding as C  # noqa: E402


def test_repository_pages_pass_the_deployed_check():
    for page in C.PAGES:
        assert C.check_page((REPO / "public" / page).read_text(encoding="utf-8")) == [], page


def test_the_old_florida_shell_is_reported():
    old = ('<title>Tax Acquisitions — Florida</title><div id="authGate"><h1>Tax Acquisitions</h1>'
           '<p class="auth-tagline">Florida Tax Deed Intelligence &amp; Auction Tracking</p></div><div id="pendingGate"></div>')
    problems = C.check_page(old)
    assert any("title names a state" in p for p in problems)
    assert any("Florida Tax Deed Intelligence" in p for p in problems)
    assert any("lacks" in p for p in problems)


def test_comments_are_not_visible_text():
    html = ('<title>TAXACQ — Tax Acquisition Intelligence</title><div id="authGate"><!-- Florida note, TaxDeed-Scraper -->'
            '<h1>TAXACQ</h1><p class="auth-tagline">Tax Acquisition Intelligence</p></div><div id="pendingGate">')
    assert C.check_page(html) == []


def test_the_repository_name_as_product_name_is_reported():
    html = ('<title>TaxDeed-Scraper — Public Property Acquisition Intelligence</title>'
            '<meta name="apple-mobile-web-app-title" content="TaxDeed-Scraper"><div id="authGate"><h1>TaxDeed-Scraper</h1>'
            '<p class="auth-tagline">Public Property Acquisition Intelligence</p></div><div id="pendingGate">')
    problems = C.check_page(html)
    assert any("title lacks 'TAXACQ'" in p for p in problems)
    assert any("repository name" in p for p in problems)
    assert any("lacks 'Tax Acquisition Intelligence'" in p for p in problems)
    assert any("sign-in block lacks 'TAXACQ'" in p for p in problems)


def test_preview_host_follows_the_cloudflare_alias_rule():
    hosts = C.preview_hosts("fix/multistate-login-branding")
    assert "https://fix-multistate-login-brandin.rodz-taxdeeds.pages.dev" in hosts
