"""Multi-state product branding (2026-10-02): the sign-in / sign-up / reset
screen and the static page title of every state page name the product, never
one state; generated state pages are current; a registered state with no rows
is described as having none, never as unsupported."""
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
STATES = re.compile(r"Florida|Texas|Louisiana|Michigan|Wyoming|South Carolina|Colorado|Wisconsin")
PAGES = ["index.html", "tx.html", "la.html", "mi.html", "wy.html", "sc.html", "co.html", "wi.html", "mo.html", "ok.html", "pa.html", "mn.html"]


def _gate(html: str) -> str:
    start = html.index('<div id="authGate"')
    return html[start:html.index('<div id="pendingGate"', start)]


def test_auth_gate_and_static_title_name_no_state():
    for page in PAGES:
        html = (REPO / "public" / page).read_text(encoding="utf-8")
        gate = re.sub(r"<!--.*?-->", "", _gate(html), flags=re.S)
        assert not STATES.search(gate), page
        assert '<p class="auth-tagline">Tax Sale Property Intelligence</p>' in gate, page
        assert "across supported states" in gate, page
        title = re.search(r"<title>(.*?)</title>", html).group(1)
        assert title == "Tax Acquisitions — Tax Sale Property Intelligence", page
        assert '<div class="dash-panel-head">Data sources (all states)</div>' in html, page
        for stale in ("Florida Tax Deed Intelligence", "Texas Tax Sale Intelligence", "Adjudicated Property Tracking", "County Tax Sale Tracking"):
            assert stale not in html, (page, stale)


def test_root_mirrors_match_public():
    for page in PAGES:
        assert (REPO / page).read_text(encoding="utf-8") == (REPO / "public" / page).read_text(encoding="utf-8"), page


def test_generated_state_pages_are_current():
    r = subprocess.run([sys.executable, str(REPO / "scripts/build_state_page.py"), "--check"], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def test_app_names_each_states_auction_by_its_own_state_and_never_says_unsupported():
    app = (REPO / "public/app.js").read_text(encoding="utf-8")
    assert '`${region === "TX" ? "Texas" : "Florida"} tax deed auction`' not in app
    assert "tax sale auction" in app
    assert "No properties currently available for this state." in app
    strings = re.findall(r'"[^"\n]*"|`[^`]*`', app)
    # The one exception is the developer console warning for a <body data-state>
    # with no STATE_META row at all - an unregistered state, never shown to a customer.
    assert not [s for s in strings if re.search(r"unsupported|not supported", s, re.I) and "<body data-state=" not in s]
