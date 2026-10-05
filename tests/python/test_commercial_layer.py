"""Paid-beta commercial layer - static contract tests (no network, no Stripe).

The behaviour is tested elsewhere: tests/billing/billing_core.test.mjs (webhook
signature, idempotency, lifecycle, entitlement), test_migration_027_* (the SQL
mirror, RLS, grants), tests/run_test.mjs (access / plan / billing / legal UI).
These pin the safety rules around them.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
FN = REPO / "supabase" / "functions"
LEGAL_PAGES = ("terms.html", "privacy.html", "acceptable-use.html", "source-disclaimer.html")
SECRET_PATTERNS = re.compile(r"\b(sk_live_[0-9A-Za-z]{8,}|sk_test_[0-9A-Za-z]{8,}|rk_live_[0-9A-Za-z]{8,}|whsec_[0-9A-Za-z]{16,})")


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def test_k01_webhook_verifies_before_it_reads_and_keeps_the_secret_server_side():
    src = read(FN / "stripe-webhook" / "index.ts")
    assert "processWebhook(" in src and "JSON.parse" not in src          # parsing happens only after verification, in the core
    assert 'Deno.env.get("STRIPE_WEBHOOK_SECRET")' in src
    core = read(FN / "_shared" / "billing_core.js")
    body = core.split("export async function processWebhook", 1)[1]
    assert body.index("verifyStripeSignature") < body.index("JSON.parse")
    assert body.index("claimEvent") < body.index("planEvent(event")      # idempotency before any write


def test_k02_checkout_takes_price_and_account_from_the_server_only():
    src = read(FN / "billing-checkout" / "index.ts")
    assert 'Deno.env.get("STRIPE_PRICE_ID")' in src
    assert "await caller(req)" in src and "req.json()" not in src and "await req.text()" not in src
    portal = read(FN / "billing-portal" / "index.ts")
    assert "await caller(req)" in portal and "req.json()" not in portal


def test_k03_no_stripe_secret_anywhere_in_the_repository():
    hits = []
    for p in REPO.rglob("*"):
        if p.is_file() and ".git" not in p.parts and "node_modules" not in p.parts and p.suffix in {".js", ".ts", ".json", ".html", ".py", ".sql", ".yml", ".yaml", ".md", ".csv", ".toml"}:
            if SECRET_PATTERNS.search(read(p)):
                hits.append(str(p.relative_to(REPO)))
    assert hits == []


def test_k04_billing_ships_switched_off_and_without_keys():
    cfg = read(REPO / "config.js")
    block = cfg.split("billing: {", 1)[1].split("}", 1)[0]
    assert "enabled: false" in block and 'planName: ""' in block and 'priceDisplay: ""' in block
    assert "stripe" not in block.lower().replace("checkoutfunction", "").replace("portalfunction", "")
    assert 'publicationMode: "preview"' in cfg                            # the tester preview stays on
    legal = cfg.split("legal: {", 1)[1].split("}", 1)[0]
    assert all(f'{k}: ""' in legal for k in ("operatorName", "governingLaw", "effectiveDate", "contactEmail"))


def test_k05_legal_pages_are_deployed_and_never_invent_business_details():
    files = read(REPO / ".github" / "workflows" / "sync-public-to-root.yml")
    for page in LEGAL_PAGES:
        src = read(REPO / "public" / page)
        assert read(REPO / page) == src, f"{page} root mirror"
        assert page in files
        assert 'src="config.js"' in src and 'src="legal.js"' in src
        assert 'data-legal="operatorName"' in src and 'id="legalUnconfigured"' in src
        assert "LLC" not in src and "Inc." not in src                       # no invented operator
    terms = read(REPO / "public" / "terms.html")
    for topic in ("Subscription and payment", "Cancellation", "No guarantee of availability or acquisition", "Not advice", "Service availability"):
        assert topic in terms
    assert "investment, financial, legal, tax" in terms
    aup = read(REPO / "public" / "acceptable-use.html")
    for rule in ("Share your sign-in", "Scrape, crawl", "Circumvent", "unlawful"):
        assert rule in aup
    disc = read(REPO / "public" / "source-disclaimer.html")
    assert "We do not claim that every source permits commercial reuse" in disc


def test_k06_legal_js_reports_missing_configuration_instead_of_inventing_it():
    src = read(REPO / "public" / "legal.js")
    assert "[not configured]" in src and "data-legal-missing" in src


def test_k07_every_app_page_links_the_legal_documents_and_offers_plan_and_billing():
    for p in sorted((REPO / "public").glob("*.html")):
        src = read(p)
        if 'id="pendingGate"' not in src:
            continue
        assert 'id="planGate" hidden' in src, p.name
        assert 'id="billingBtnMenu"' in src and 'id="billingModal"' in src, p.name
        assert src.count('class="auth-legal-links"') >= 3, p.name            # sign-in, pending, plan


def test_k08_migration_024_is_not_a_billing_dependency():
    for p in list(FN.rglob("*.ts")) + list(FN.rglob("*.js")) + [REPO / "scripts" / "migrations" / "027_commercial_billing_entitlements.sql"]:
        src = read(p)
        for t in ("saved_searches", "user_alerts", "alert_preferences", "product_events"):
            assert t not in src, f"{p.name} depends on 024's {t}"


def test_k09_paid_customers_never_get_the_tester_preview():
    app = read(REPO / "public" / "app.js")
    body = app.split("function isPublishable(p) {", 1)[1].split("\n}", 1)[0]
    assert body.index('viewerScope() === "paid"') < body.index('viewerScope() === "preview"')
    assert 'if (ACCESS.role === "customer") return "paid";' in app
