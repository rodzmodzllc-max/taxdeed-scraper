"""Phase 16 (Production Deployment Hygiene & Frontend Mirror-Sync Gate)
tests.

Phase 15 found the root-level `app.js` (the file `.github/workflows/
sync-public-to-root.yml`'s own header comment says Cloudflare Pages
actually deploys from) was several days stale relative to `public/app.js`
within this checkout. Phase 16's investigation found the real
`sync-public-to-root.yml` mechanism itself is not broken - verified
directly against the actual upstream repository (`origin/main`), where
every deployed-bundle file's root copy and `public/` copy are byte-
identical across the commit history. The drift Phase 15 found was local
to this checkout: `public/app.js` had been edited without the mirror
step ever running against those particular edits (the mirror workflow
only runs on an actual GitHub push, so a checkout whose commits are
never pushed can drift indefinitely between the two copies even though
the real mechanism is sound).

This file guards the narrow, provable part of that problem: that
whichever checkout this test suite runs in keeps every deployed-bundle
file's root copy and `public/` copy byte-identical, so this exact class
of local drift is caught immediately rather than silently accumulating
again. It cannot detect - and does not claim to detect - divergence
between this checkout and a remote `origin/main` it may not have access
to; that is a git-remote question, not a repository-content one, and is
explicitly out of scope for a test that only reads local files.

No source is contacted, no production Supabase project is touched, no
network call is made - this file only reads local repository files.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# Exactly the FILES list from .github/workflows/sync-public-to-root.yml,
# kept in sync with that file deliberately (not derived from it
# automatically) so a change to one is a visible, reviewable prompt to
# check the other - the same discipline that workflow's own comments
# already ask of a human editor ("Update this list if the deployed file
# set ever changes - and the guard step below will fail the build if you
# forget"). This test is that same guard, run locally instead of in CI.
DEPLOYED_BUNDLE_FILES = (
    "_headers",
    "app.js",
    # Added Phase 54/55 (map page rebuild + satellite basemap toggle). Both
    # went into sync-public-to-root.yml's FILES list at the time but not into
    # this one, which turned main red on every push until it was noticed -
    # which is the exact drift the companion test below exists to catch.
    "county-centroids.json",
    "satellite-map.js",
    "explore.css",
    "explore.js",
    "fl-cities.json",
    "fl-zips.json",
    "index.html",
    "manifest.webmanifest",
    "styles.css",
    "sw.js",
    "tx.html",
    "tx-counties.svg",
)


def test_every_deployed_bundle_file_matches_between_root_and_public():
    """Regression guard for the exact defect Phase 15 found and Phase 16
    root-caused: a deployed-bundle file edited under public/ without its
    root-level mirror copy being updated to match. Cloudflare Pages
    deploys from the repository root (per sync-public-to-root.yml's own
    header comment); a checkout where these two diverge means whatever
    the root copy says is what's actually live, not whatever public/
    says - exactly the trap this phase fell into."""
    mismatches = []
    for name in DEPLOYED_BUNDLE_FILES:
        root_path = REPO_ROOT / name
        public_path = REPO_ROOT / "public" / name
        if not root_path.exists() or not public_path.exists():
            mismatches.append(f"{name}: missing at {'root' if not root_path.exists() else 'public/'}")
            continue
        if root_path.read_bytes() != public_path.read_bytes():
            mismatches.append(f"{name}: root and public/ copies differ")
    assert not mismatches, (
        "Deployed-bundle file(s) out of sync between root and public/ - "
        "Cloudflare Pages serves the ROOT copy, so this checkout's root "
        "copy is stale relative to the intended (public/) source: "
        + "; ".join(mismatches)
    )


def test_deployed_bundle_files_list_matches_the_ci_workflows_own_list():
    """Guards DEPLOYED_BUNDLE_FILES itself against drifting from the real
    source of truth - the FILES list inside
    .github/workflows/sync-public-to-root.yml - so this test can't give a
    false sense of coverage after a file is added to the deployed bundle
    but only taught to one of the two lists."""
    workflow = (REPO_ROOT / ".github" / "workflows" / "sync-public-to-root.yml").read_text()
    line = next(l for l in workflow.splitlines() if l.strip().startswith('FILES="'))
    workflow_files = tuple(line.split('"')[1].split())
    assert set(workflow_files) == set(DEPLOYED_BUNDLE_FILES), (
        f"DEPLOYED_BUNDLE_FILES {sorted(DEPLOYED_BUNDLE_FILES)} no longer matches "
        f"sync-public-to-root.yml's own FILES list {sorted(workflow_files)} - "
        "update whichever one is behind"
    )


def test_public_icons_directory_matches_root_icons_directory():
    """The FILES list only names flat files; icons/ is mirrored wholesale
    by the workflow's own separate rsync step - covered here the same
    way, by content rather than by trusting the workflow ran."""
    root_icons = REPO_ROOT / "icons"
    public_icons = REPO_ROOT / "public" / "icons"
    if not public_icons.is_dir():
        return  # nothing to compare if this checkout has no icons/ at all
    assert root_icons.is_dir(), "public/icons exists but root icons/ is missing"
    public_names = {p.name for p in public_icons.iterdir() if p.is_file()}
    root_names = {p.name for p in root_icons.iterdir() if p.is_file()}
    assert public_names == root_names, (
        f"icon file sets differ: public/ has {sorted(public_names)}, "
        f"root has {sorted(root_names)}"
    )
    for name in public_names:
        assert (root_icons / name).read_bytes() == (public_icons / name).read_bytes(), (
            f"icons/{name} differs between root and public/"
        )
