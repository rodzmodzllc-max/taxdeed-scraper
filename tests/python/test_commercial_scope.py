"""Paid-beta source scope (harvesters/governance/commercial_scope.py).

The paid inventory is the smallest defensible set: a source is sold only with
an explicit APPROVED publication decision AND every readiness check ok. A
grandfathered or undecided source requires a publication decision; an
unreviewed collected source is tester preview only; a blocked source is never
shown. The tester preview never stands in for any of this.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from harvesters.governance import commercial_scope as cs  # noqa: E402


def test_c01_decisions_are_valid():
    assert cs.problems() == []


def test_c02_generated_json_is_current_and_mirrored():
    r = subprocess.run([sys.executable, "scripts/build_commercial_scope.py", "--check"], cwd=REPO, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert (REPO / "commercial-scope.json").read_text() == (REPO / "public" / "commercial-scope.json").read_text()


def test_c03_paid_beta_is_explicitly_approved_only():
    reg = cs.registry_publication()
    for sid in cs.paid_beta_source_ids():
        assert reg[sid][1] == "APPROVED", sid


def test_c04_scope_mapping():
    assert cs.scope_for("APPROVED", True) == "CUSTOMER_APPROVED"
    assert cs.scope_for("APPROVED_GRANDFATHERED", True) == "REQUIRES_PUBLICATION_DECISION"
    assert cs.scope_for("", True) == "REQUIRES_PUBLICATION_DECISION"
    assert cs.scope_for("UNREVIEWED", True) == "TESTER_PREVIEW"
    assert cs.scope_for("UNREVIEWED", False) == "UNREVIEWED"
    assert cs.scope_for("BLOCKED", True) == "BLOCKED"


def test_c05_validator_refuses_selling_an_unapproved_or_unready_source():
    rows = cs.load_decisions()
    bad = [dict(r) for r in rows]
    for r in bad:
        if r["source_id"] == "mo_stl_lra_inventory":
            r["paid_beta"] = "yes"
        if r["source_id"] == "wy_albany_tax_sale":
            r["paid_beta"] = "yes"
    errs = cs.problems(bad)
    assert any("mo_stl_lra_inventory" in e and "explicit APPROVED" in e for e in errs)
    assert any("wy_albany_tax_sale" in e and "lifecycle" in e for e in errs)


def test_c06_blocked_sources_are_never_tester_or_paid():
    for s in cs.classify():
        if s["commercial_scope"] == "BLOCKED":
            assert not s["tester_preview"] and not s["paid_beta"]


def test_c07_grandfathered_and_undecided_sources_are_withheld_from_paid_beta():
    for s in cs.classify():
        if s["publication_status"] in (None, "APPROVED_GRANDFATHERED"):
            assert s["commercial_scope"] == "REQUIRES_PUBLICATION_DECISION" and not s["paid_beta"], s["source_id"]


def test_c08_initial_paid_beta_set_is_the_recorded_one():
    assert cs.paid_beta_source_ids() == ["la_ebr_adjudicated", "mi_eaton_treasurer_sale", "mi_lenawee_tax_sale",
                                          "sc_york_tax_sale", "wi_green_tax_deed_sales"]
    data = json.loads((REPO / "public" / "commercial-scope.json").read_text())
    assert data["paid_beta_source_ids"] == cs.paid_beta_source_ids()
