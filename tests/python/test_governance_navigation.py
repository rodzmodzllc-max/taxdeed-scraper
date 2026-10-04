"""Source Publication Governance moved off the main workspace into its own
admin-only view (2026-09-30): account menu "Source Publication Governance"
or #/governance. A navigation / layout change only - the panel, the
refreshAdminPublication() logic, the publication gate, the registry and RLS
are untouched (pinned below)."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
APP = (REPO / "public/app.js").read_text(encoding="utf-8")
# Every state page: the hand-written ones and the ones scripts/build_state_page.py
# generates from tx.html (six-state expansion).
PAGES = [p for p in ("index.html", "tx.html", "la.html", "mi.html", "wy.html", "sc.html", "co.html", "wi.html", "mo.html", "ok.html", "pa.html", "mn.html")
         if (REPO / "public" / p).exists()]


def _between(text: str, start: str, end: str) -> str:
    i = text.index(start)
    return text[i:text.index(end, i)]


def test_v01_the_panel_is_inside_its_own_view_not_on_the_workspace():
    for page in PAGES:
        html = (REPO / "public" / page).read_text(encoding="utf-8")
        assert html.count('id="adminPublication"') == 1, page
        view = _between(html, '<div class="detail-modal" id="governanceModal" hidden>', "<!-- ============ terms & disclaimer")
        # The existing panel, unchanged, lives inside the view...
        assert '<div class="admin-approvals admin-publication" id="adminPublication" hidden>' in view, page
        assert '<div class="admin-pub-list" id="adminPublicationList"></div>' in view, page
        # ...and the workspace keeps the operational approvals panel only.
        workspace = html[:html.index('id="governanceModal"')]
        assert 'id="adminApprovals"' in workspace and 'id="adminPublication"' not in workspace, page


def test_v02_the_account_menu_carries_one_admin_only_entry():
    for page in PAGES:
        html = (REPO / "public" / page).read_text(encoding="utf-8")
        menu = _between(html, '<div class="account-menu" id="accountMenu"', 'id="deleteAccountBtn"')
        item = '<button class="account-item" id="governanceMenuItem" type="button" role="menuitem" hidden>Source Publication Governance</button>'
        assert menu.count(item) == 1, page
        # after "Admin area", before Terms / Sign out
        assert menu.index('id="adminAreaLink"') < menu.index('id="governanceMenuItem"') < menu.index('id="signOutBtn"'), page
    # Shown only for the server-read admin flag, next to the Admin area link.
    block = _between(APP, 'const adminLink = document.getElementById("adminAreaLink");', "if (profile && profile.approved)")
    assert 'govItem.hidden = !IS_ADMIN' in block


def test_v03_the_view_refuses_non_admins_and_loads_only_when_opened():
    fn = _between(APP, "async function openGovernance(", "\n}\n")
    assert fn.index("if (!IS_ADMIN)") < fn.index("governanceUi.open(") < fn.index("refreshAdminPublication()")
    assert "pageHash(page)" in fn                          # a refused #/governance is rewritten to the current page
    # Not loaded onto the workspace at startup any more; approvals still are.
    start = _between(APP, "async function showApp()", "\n}\n")
    assert "refreshAdminPublication()" not in start and "if (IS_ADMIN) refreshAdminApprovals();" in start
    assert "if (wantsGovernance) openGovernance();" in start
    # The route is honoured on hashchange too.
    assert "if (isGovernanceHash()) { openGovernance(); return; }" in APP
    # Defence in depth inside the unchanged loader: nothing rendered for a non-admin.
    loader = _between(APP, "async function refreshAdminPublication()", "\n}\n")
    assert "if (!IS_ADMIN) { wrap.hidden = true; list.innerHTML = \"\"; return; }" in loader


def test_v04_governance_logic_and_data_access_are_unchanged():
    loader = _between(APP, "async function refreshAdminPublication()", "\n}\n")
    # Same reads, same append-only insert, same validation messages.
    assert 'sb.from("county_source_registry").select("state,county,source_id,publication_status,restrictions,governance_status,verification_status")' in loader
    assert 'sb.from("source_publication_reviews").select("*")' in loader
    assert '"RESTRICTED needs a reason."' in loader and '"An approval needs evidence."' in loader
    assert 'sb.from("source_publication_reviews").insert(' in loader


def test_v05_the_change_touches_no_schema_policy_registry_or_pipeline_file():
    # Scoped to the governance-navigation commit itself (a branch that also
    # carries other work - e.g. the six-state expansion - legitimately touches
    # harvesters / data; that is not this change).
    sha = subprocess.run(["git", "log", "--format=%H", "-1", "--fixed-strings",
                          "--grep=Move Source Publication Governance off the main workspace"],
                         capture_output=True, text=True, cwd=REPO).stdout.strip()
    if not sha:
        return
    changed = subprocess.run(["git", "show", "--name-only", "--format=", sha], capture_output=True, text=True, cwd=REPO).stdout.split()
    forbidden = re.compile(r"(^supabase/|^scripts/migrations/|schema.*\.sql$|^harvesters/|^data/|^scripts/|\.github/workflows/)")
    assert changed and [f for f in changed if forbidden.search(f)] == [], changed


def test_v06_generated_state_pages_are_in_sync_with_their_generator():
    gen = REPO / "scripts/build_state_page.py"
    if not gen.exists():
        return
    r = subprocess.run(["python3", str(gen), "--check"], capture_output=True, text=True, cwd=REPO)
    assert r.returncode == 0, r.stdout + r.stderr
    for page in PAGES:
        assert (REPO / page).read_text(encoding="utf-8") == (REPO / "public" / page).read_text(encoding="utf-8"), page
