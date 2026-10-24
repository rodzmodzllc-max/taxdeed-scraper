"""Shared assertion for the Florida PowerShell pipeline's governance coupling.

Until 2026-10-12 four tests pinned "no .ps1 file references governance" - the
documented gap (Phase 10A Step 9 / Phase 22B) that the Florida harvesters and
syncs never consulted the governance package. The source-permission gate closed
that gap. These tests now pin the stricter replacement rule:

  * exactly the six Florida scripts that request or write data carry the
    permission guard (GUARDED below), and no other .ps1 mentions governance;
  * in each, every mention of governance lies inside the guard block;
  * the guard is the first executable code after `$ErrorActionPreference`, so it
    runs before any request (Invoke-*, curl) or write;
  * the guard calls scripts/source_permission_check.py with named source(s),
    operation(s) and state, and exits 3 when Python is missing or the check fails.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
START = "# --- Source permission gate (2026-10-12) "
END = "# --- end source permission gate "

GUARDED = {
    "harvest_all_counties.ps1": ("fetch", "parse"),
    "harvest_okaloosa_bid4assets.ps1": ("fetch", "parse"),
    "harvest_lienhub_certificates.ps1": ("fetch", "parse"),
    "sync-harvest-to-supabase.ps1": ("store",),
    "sync-certificates-to-supabase.ps1": ("store",),
    "sync-laft-to-supabase.ps1": ("store",),
}


def guard_block(text: str) -> str:
    s, e = text.index(START), text.index(END)
    return text[s:e]


def guard_args(text: str) -> list[str]:
    block = guard_block(text)
    m = re.search(r'"source_permission_check\.py"\)\s+(.+)$', block, flags=re.M)
    assert m, "guard does not call scripts/source_permission_check.py"
    return m.group(1).split()


def assert_ps1_governance_only_through_guard() -> None:
    mentioning = set()
    for ps1 in sorted((ROOT / "scripts").glob("*.ps1")):
        text = ps1.read_text(encoding="utf-8", errors="ignore")
        if "governance" in text.lower() or "source_permission_check" in text:
            mentioning.add(ps1.name)
    assert mentioning == set(GUARDED), f"governance-referencing .ps1 files {sorted(mentioning)} != guarded {sorted(GUARDED)}"
    for name, ops in GUARDED.items():
        text = (ROOT / "scripts" / name).read_text(encoding="utf-8")
        block = guard_block(text)
        outside = text.replace(block, "")
        assert "governance" not in outside.lower(), f"{name}: governance referenced outside the permission guard"
        # The guard is the first thing after $ErrorActionPreference.
        lines = [l for l in text.split("\n") if l.strip()]
        assert lines[0].startswith("$ErrorActionPreference"), name
        assert lines[1].startswith(START), f"{name}: the permission guard is not the first statement"
        # Nothing that makes a request or a write precedes the guard.
        before = text[: text.index(START)]
        assert not re.search(r"Invoke-(WebRequest|RestMethod)|\bcurl\b", before), name
        args = guard_args(text)
        assert args.count("--operation") == len(ops) and all(o in args for o in ops), f"{name}: operations {args}"
        assert "--state" in args and args[args.index("--state") + 1] == "FL", name
        assert "--source" in args, name
        # Fail closed: exit 3 on a missing Python and on any non-zero check.
        # One exit for a missing Python, one per check (a harvester that also
        # reads its county-level denials checks twice).
        checks = block.count("if (0 -ne $LASTEXITCODE) {")
        assert sum(1 for l in block.split("\n") if l.strip() == "exit 3") == 1 + checks >= 2, \
            f"{name}: guard must exit 3 on missing Python and on denial"
        assert "if (0 -ne $LASTEXITCODE) {" in block, name
