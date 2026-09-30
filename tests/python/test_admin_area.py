"""Admin area (/admin) - 2026-09-30.

What these pin (the browser behaviour itself is exercised by
tests/run_test.mjs's admin* checks against the stub's server model):

  * admin.js decides admin access ONLY from the server's answer - the
    signed-in user's own profiles.is_admin read under row-level security -
    and fails closed; it never reads browser storage for a role, never
    compares or stores a password;
  * the shell is hidden until that answer arrives and shows the identity as
    "Admin", never an e-mail address;
  * nothing credential-like is committed: .env.example carries names only,
    no source / test / fixture / doc holds a password literal for a real
    account, and when ADMIN_PASSWORD is present in the environment (a
    person's local run) its value appears in no tracked file.
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ADMIN_JS = (REPO / "public/admin.js").read_text(encoding="utf-8")
ADMIN_HTML = (REPO / "public/admin.html").read_text(encoding="utf-8")


def _code(js: str) -> str:
    """The script without // comments (so prose about storage or passwords
    in the header does not count as code)."""
    return "\n".join(line.split("//", 1)[0] if not line.lstrip().startswith("//") else "" for line in js.splitlines())


def test_a01_admin_access_is_decided_by_the_servers_row_level_security_answer_only():
    code = _code(ADMIN_JS)
    assert 'sb.from("profiles").select("is_admin").eq("id", user.id).maybeSingle()' in code
    assert "data.is_admin === true" in code and "!error" in code              # strict, fails closed on an error
    assert "sb.auth.getSession()" in code
    # No client-side role source of any kind.
    for forbidden in ("localStorage", "getItem(", "IS_ADMIN", "window.__", "document.cookie", "atob(", "jwt", "app_metadata"):
        assert forbidden not in code, forbidden
    # No password handling at all on this page.
    assert "password" not in code.lower() and "signInWithPassword" not in code
    # Refusal sends everyone else to the normal application, without keeping /admin in history.
    assert 'const APP_URL = "index.html";' in code and "location.replace(APP_URL)" in code
    assert "if (!user || !admin) { leave(); return; }" in code
    assert 'if (event === "SIGNED_OUT") leave();' in code
    assert "gate().catch(() => leave());" in code


def test_a02_the_shell_is_hidden_until_verified_and_names_only_admin():
    assert '<main class="admin-shell" id="adminShell" hidden>' in ADMIN_HTML
    assert '<meta name="robots" content="noindex, nofollow">' in ADMIN_HTML
    assert '<script type="module" src="admin.js"></script>' in ADMIN_HTML
    # Only the two external scripts; no inline script (the site's CSP forbids them anyway).
    assert re.findall(r"<script[^>]*>", ADMIN_HTML) == ['<script src="config.js">', '<script type="module" src="admin.js">']
    assert "@" not in ADMIN_HTML                                               # no e-mail address anywhere
    assert 'document.getElementById("adminIdentity").textContent = "Admin";' in ADMIN_JS
    # No governance / database / activation control on this page.
    for word in ("<form", "<input", "delete", "activate", "publication_status"):
        assert word not in ADMIN_HTML.lower(), word


def test_a03_the_app_shows_the_admin_link_only_from_the_server_read_profile():
    app = (REPO / "public/app.js").read_text(encoding="utf-8")
    assert 'IS_ADMIN = !!(profile && profile.is_admin);\n  // The account menu\'s "Admin area" link' in app
    assert 'if (adminLink) adminLink.hidden = !IS_ADMIN;' in app
    for page in ("public/index.html", "public/tx.html"):
        html = (REPO / page).read_text(encoding="utf-8")
        assert '<a class="account-item" id="adminAreaLink" href="admin.html" role="menuitem" hidden>Admin area</a>' in html, page
    # The normal sign-in is untouched: still Supabase Auth's own password grant.
    assert "await sb.auth.signInWithPassword({ email, password });" in app


def test_a04_deployment_wiring():
    headers = (REPO / "public/_headers").read_text(encoding="utf-8")
    assert "/admin\n  X-Robots-Tag: noindex, nofollow" in headers and "/admin.html\n  X-Robots-Tag: noindex, nofollow" in headers
    sync = (REPO / ".github/workflows/sync-public-to-root.yml").read_text(encoding="utf-8")
    assert "admin.html admin.js" in sync
    pw = (REPO / ".github/workflows/playwright-test.yml").read_text(encoding="utf-8")
    assert "/tmp/serve/admin.html" in pw and "grep -q 'importmap' /tmp/serve/admin.html" in pw
    for f in ("admin.html", "admin.js"):
        assert (REPO / f).read_text(encoding="utf-8") == (REPO / "public" / f).read_text(encoding="utf-8"), f


def test_c01_env_example_names_variables_and_carries_no_value():
    lines = [l for l in (REPO / ".env.example").read_text(encoding="utf-8").splitlines() if l.strip() and not l.startswith("#")]
    assert lines == ["ADMIN_EMAIL=", "ADMIN_PASSWORD=", "NORMAL_EMAIL=", "NORMAL_PASSWORD="]
    gi = (REPO / ".gitignore").read_text(encoding="utf-8")
    assert ".env\n.env.*\n!.env.example" in gi


def _tracked_text_files():
    out = subprocess.run(["git", "ls-files"], cwd=REPO, capture_output=True, text=True, check=True).stdout.split()
    for name in out:
        p = REPO / name
        if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".ico", ".pdf", ".xlsx", ".zip", ".gz", ".dbf", ".shp") or not p.is_file():
            continue
        try:
            yield name, p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue


def test_c02_no_admin_credential_is_committed():
    # No password literal is ever compared or assigned for a real account.
    pattern = re.compile(r"(password|passwd|ADMIN_PASSWORD)\s*(===|==|=|:)\s*[\"'][^\"'\s]{6,}[\"']", re.I)
    allowed = {"tests/vendor/supabase-stub.js"}      # fixture passwords of fake example.com accounts
    for name, text in _tracked_text_files():
        if name in allowed:
            continue
        assert not pattern.search(text), name
    stub = (REPO / "tests/vendor/supabase-stub.js").read_text(encoding="utf-8")
    assert set(re.findall(r'password: "([^"]+)"', stub)) == {"fixture-normal-pass", "fixture-admin-pass"}
    assert set(re.findall(r'email: "([^"]+)", password:', stub)) == {"normal@example.com", "admin@example.com"}
    # When a person runs this with the real value in their environment, it must appear nowhere.
    secret = os.environ.get("ADMIN_PASSWORD")
    if secret:
        for name, text in _tracked_text_files():
            assert secret not in text, name


def test_c03_the_live_check_never_prints_a_credential():
    src = (REPO / "scripts/admin_auth_smoke.py").read_text(encoding="utf-8")
    prints = re.findall(r"print\((.*)\)", src)
    for p in prints:
        for name in ("admin_email", "admin_password", "normal_email", "normal_password", "access_token", "session"):
            assert name not in p, p
    assert 'os.environ.get("ADMIN_PASSWORD")' in src and "/auth/v1/token?grant_type=password" in src


# --- Public sign-up with mandatory admin approval (2026-09-30) ---------------

APP_JS = (REPO / "public/app.js").read_text(encoding="utf-8")
APPROVE_UPDATE = '.update({ approved: true, approved_at: new Date().toISOString() })'
PENDING_SELECT = 'sb.from("profiles").select("id,email,requested_at").eq("approved", false).order("requested_at")'


def test_s01_the_admin_area_uses_the_existing_approval_mechanism():
    """/admin lists and approves pending accounts with the very same query and
    update as the application's own admin panel - the server's profiles row
    under the admin RLS policy - and nothing else."""
    code = _code(ADMIN_JS)
    for text in (APP_JS, code):
        assert PENDING_SELECT in text and APPROVE_UPDATE in text
    # Approving is the only write; there is no reject / delete / role change.
    assert code.count(".update(") == 1 and ".delete(" not in code and ".insert(" not in code and ".upsert(" not in code
    assert "is_admin: true" not in code and "is_admin:true" not in code
    # The pending list loads only after the server said admin.
    gate_body = code.split("async function gate()", 1)[1].split("\n}\n", 1)[0]
    assert gate_body.index("if (!user || !admin) { leave(); return; }") < gate_body.index("await refreshPending();")
    assert 'id="adminPendingList"' in ADMIN_HTML and 'id="adminPendingStatus"' in ADMIN_HTML


def test_s02_sign_up_never_asks_for_approval_or_a_role():
    """The client sends profile details only; approved / is_admin are the
    database's defaults (handle_new_user inserts id + email)."""
    call = APP_JS.split("await sb.auth.signUp({", 1)[1].split("});", 1)[0]
    assert "first_name: firstName" in call
    for word in ("approved", "is_admin", "role"):
        assert word not in call, word


def test_s03_signups_disabled_error_gets_a_clear_message():
    assert "function signUpErrorText(error)" in APP_JS
    assert "/signups? not allowed/i.test(msg)" in APP_JS
    assert 'authMsg.textContent = signUpErrorText(error);' in APP_JS
    assert "New accounts stay pending until an administrator approves them." in APP_JS
    # A new account without approval sees the pending screen, never the app.
    assert "if (profile && profile.approved) showApp();\n  else showPending();" in APP_JS


def test_s04_docs_name_the_manual_dashboard_setting():
    admin = (REPO / "docs/admin.md").read_text(encoding="utf-8")
    prod = (REPO / "docs/production-configuration.md").read_text(encoding="utf-8")
    for text in (admin, prod):
        assert "Allow new users to sign up" in text
    assert "Signups not allowed for this instance" in admin
