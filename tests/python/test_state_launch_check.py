"""The repeatable state-launch check (scripts/state_launch_check.py)."""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
import state_launch_check as SLC  # noqa: E402
from harvesters.governance import states  # noqa: E402


def test_every_production_state_is_wired_end_to_end():
    for code in sorted(states.PRODUCTION_STATES):
        res = SLC.check_state(code)
        failing = [k for k in SLC.REQUIRED if not res[k][0]]
        assert not failing, (code, failing, {k: res[k][1] for k in failing})


def test_a_registered_but_gated_state_is_blocked_and_says_why():
    res = SLC.check_state("UT")
    assert res["registered"][0] and not res["activated"][0]
    assert "parser_fixture_validated" in res["activated"][1]
    assert SLC.main(["--state", "UT"]) == 1


def test_advisory_items_never_block():
    assert set(SLC.ADVISORY).isdisjoint(SLC.REQUIRED)
    assert SLC.main(["--all"]) == 0


def test_playbook_documents_the_check():
    doc = (REPO / "docs/state-launch-playbook.md").read_text(encoding="utf-8")
    assert "scripts/state_launch_check.py" in doc
    for k in SLC.REQUIRED + SLC.ADVISORY:
        assert f"`{k}`" in doc, k
    for vendor in ("GovEase", "LGBS", "PBFCM", "MVBA", "CTSA"):
        assert vendor in doc
