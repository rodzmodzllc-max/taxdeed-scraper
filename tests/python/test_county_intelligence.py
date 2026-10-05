"""County intelligence, customer source health and the acquisition checklist
(2026-10-05).

* harvesters/sources/county_intel.py builds one record per county of every
  production state; public/county-intelligence.json is its generated copy.
* scripts/unit_freshness.customer_health() and app.js sourceHealthState() are
  one function in two languages, pinned by the shared vectors.
* The frontend's labels cover exactly the vocabularies the builder emits.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

from harvesters.governance import states as STATES  # noqa: E402
from harvesters.sources import county_intel as CI  # noqa: E402
import unit_freshness as UF  # noqa: E402

APP = (REPO / "public" / "app.js").read_text(encoding="utf-8")
DOC = json.loads((REPO / "public" / "county-intelligence.json").read_text(encoding="utf-8"))
CASES = json.loads((REPO / "tests" / "python" / "fixtures" / "source_health_cases.json").read_text(encoding="utf-8"))


def _js_object_keys(name: str) -> set[str]:
    m = re.search(r"const " + name + r" = \{(.*?)\n\};", APP, re.S)
    assert m, name
    return set(re.findall(r"^\s*([A-Z_]+):", m.group(1), re.M))


# ---- the generated file --------------------------------------------------
def test_generated_file_is_current():
    r = subprocess.run([sys.executable, "scripts/build_county_intelligence.py", "--check"], cwd=REPO, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def test_file_is_mirrored_and_deployed():
    root = REPO / "county-intelligence.json"
    if root.exists():
        assert root.read_text(encoding="utf-8") == (REPO / "public" / "county-intelligence.json").read_text(encoding="utf-8")
    wf = (REPO / ".github" / "workflows" / "sync-public-to-root.yml").read_text(encoding="utf-8")
    assert " county-intelligence.json " in wf


def test_every_production_state_and_no_problems():
    assert {s["state"] for s in DOC["states"]} == set(STATES.PRODUCTION_STATES)
    assert CI.problems(DOC) == []


def test_counties_are_basemap_names():
    centroids = json.loads((REPO / "public" / "county-centroids.json").read_text(encoding="utf-8"))
    for s in DOC["states"]:
        names = set(centroids[s["state"]])
        assert s["county_total"] >= len(names)
        for c in s["counties"]:
            assert c["county"] in names or any(src for l in c["ledgers"].values() for src in l["sources"]), (s["state"], c["county"])


def test_omitted_counties_are_unresearched_default():
    # A county the file omits is NOT_YET_RESEARCHED with no source anywhere.
    assert DOC["default_county"] == {"intel": "NOT_YET_RESEARCHED", "coverage": "NO_SOURCE_BACKED_INVENTORY"}
    for s in DOC["states"]:
        for c in s["counties"]:
            assert not (c["intel"] == "NOT_YET_RESEARCHED" and not any(l["sources"] for l in c["ledgers"].values()))


def test_value_free():
    keys: set[str] = set()

    def walk(x):
        if isinstance(x, dict):
            keys.update(x)
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    walk(DOC)
    # No property-level field: the file describes sources, never rows.
    assert not keys & {"owner_name", "parcel", "case_no", "purchase_amount", "address", "bid", "latitude", "longitude", "id"}


def test_runtime_states_never_in_file():
    for s in DOC["states"]:
        for c in s["counties"]:
            assert c["intel"] != "SOURCE_UNAVAILABLE"
            assert all(l["coverage"] != "SOURCE_UNAVAILABLE" for l in c["ledgers"].values())


# ---- the decisions ---------------------------------------------------------
def _src(production=True, approved=True, publication=None):
    return {"production": production, "customer_approved": approved,
            "publication": publication or ("APPROVED" if approved else "UNREVIEWED")}


def test_ledger_coverage_rules():
    assert CI.ledger_coverage([_src()], 0)[0] == "COVERED"
    assert CI.ledger_coverage([_src(approved=False)], 0)[0] == "PARTIALLY_COVERED"
    assert CI.ledger_coverage([_src(production=False)], 0)[0] == "RESEARCH_ONLY"
    assert CI.ledger_coverage([], 2)[0] == "RESEARCH_ONLY"
    assert CI.ledger_coverage([], 0)[0] == "NO_SOURCE_BACKED_INVENTORY"
    # A blocked vendor never makes a county covered or researched.
    assert CI.ledger_coverage([_src(approved=False, publication="BLOCKED")], 0)[0] == "NO_SOURCE_BACKED_INVENTORY"


def _ledgers(avail, auc="NO_SOURCE_BACKED_INVENTORY", cert="NO_SOURCE_BACKED_INVENTORY"):
    return {"AVAILABLE": {"coverage": avail}, "AUCTIONS": {"coverage": auc}, "LIENS_CERTIFICATES": {"coverage": cert}}


def test_intel_state_rules():
    assert CI.intel_state(_ledgers("COVERED"), True, True, 0)[0] == "VERIFIED"
    assert CI.intel_state(_ledgers("COVERED"), True, False, 0)[0] == "PARTIALLY_VERIFIED"
    assert CI.intel_state(_ledgers("COVERED"), False, True, 0)[0] == "PARTIALLY_VERIFIED"
    assert CI.intel_state(_ledgers("COVERED"), False, False, 0)[0] == "SOURCE_BACKED"
    assert CI.intel_state(_ledgers("NO_SOURCE_BACKED_INVENTORY", auc="COVERED"), False, False, 0)[0] == "SOURCE_BACKED"
    assert CI.intel_state(_ledgers("PARTIALLY_COVERED"), False, False, 0)[0] == "NEEDS_REVIEW"
    assert CI.intel_state(_ledgers("NO_SOURCE_BACKED_INVENTORY"), False, False, 3)[0] == "NEEDS_REVIEW"
    assert CI.intel_state(_ledgers("NO_SOURCE_BACKED_INVENTORY"), False, False, 0)[0] == "NOT_YET_RESEARCHED"


def test_verified_needs_verified_evidence_row():
    ev = CI._verified_evidence()
    for s in DOC["states"]:
        for c in s["counties"]:
            if c["intel"] != "VERIFIED":
                continue
            ids = [x["source_id"] for x in c["ledgers"]["AVAILABLE"]["sources"] if x["production"]]
            assert any(ev.get((s["state"], c["county"], sid)) for sid in ids), (s["state"], c["county"])


def test_known_production_examples():
    by = {(s["state"], c["county"]): c for s in DOC["states"] for c in s["counties"]}
    # East Baton Rouge: the approved adjudicated list with a verified process.
    ebr = by[("LA", "East Baton Rouge")]
    assert ebr["ledgers"]["AVAILABLE"]["coverage"] == "COVERED"
    assert ebr["acquisition"]["verified"]
    # Detroit Land Bank: collected, awaiting review - never COVERED.
    assert by[("MI", "Wayne")]["ledgers"]["AVAILABLE"]["coverage"] == "PARTIALLY_COVERED"


# ---- customer source health ------------------------------------------------
@pytest.mark.parametrize("case", CASES["cases"], ids=[c["name"] for c in CASES["cases"]])
def test_customer_health_vectors(case):
    now = datetime.fromisoformat(CASES["now"].replace("Z", "+00:00"))
    assert UF.customer_health(case["unit"], now=now, review=case["review"]) == {"state": case["state"], "checked_zero": case["checked_zero"]}


def test_health_labels_match_python_states():
    assert _js_object_keys("SOURCE_HEALTH_LABELS") == set(UF.CUSTOMER_HEALTH_STATES)


def test_manual_only_sources_mirrored():
    m = re.search(r"const MANUAL_ONLY_SOURCE_IDS = \[(.*?)\]", APP)
    assert set(re.findall(r'"([a-z_]+)"', m.group(1))) == set(UF.MANUAL_ONLY_SOURCES)


def test_checked_zero_never_unavailable():
    for c in CASES["cases"]:
        assert not (c["checked_zero"] and c["state"] == "SOURCE_UNAVAILABLE")


def test_frontend_labels_cover_vocabularies():
    assert _js_object_keys("COUNTY_INTEL_LABELS") == set(CI.INTEL_STATES)
    assert _js_object_keys("COUNTY_COVERAGE_LABELS") == set(CI.COVERAGE)


def test_registry_select_reads_error_category():
    assert "consecutive_failures,last_error_category" in APP


# ---- the acquisition checklist ---------------------------------------------
def test_checklist_has_fourteen_items():
    m = re.search(r"const ACQUIRE_CHECKLIST_KEYS = \[(.*?)\];", APP, re.S)
    keys = re.findall(r'"([a-z_]+)"', m.group(1))
    assert keys == ["status", "seller", "method", "amount", "amount_type", "form", "deposit", "documents",
                    "instructions", "listing", "contact", "deadlines", "verified", "not_published"]
    body = APP[APP.index("function acquireChecklist(p)"):APP.index("function acquireChecklistHtml(p)")]
    for k in keys:
        assert f'"{k}"' in body, k


def test_checklist_never_scores():
    body = APP[APP.index("function acquireChecklist(p)"):APP.index("window.__tdwAcquireChecklist")]
    assert not re.search(r"\b(score|rating|grade|deal)\b", body, re.I)
