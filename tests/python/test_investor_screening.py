"""screening-v1: the research screen's rules, pinned in both implementations.

public/screening.js (what the browser runs) and harvesters/screening/rules.py
(the mirror for reports and any future server-side materialisation) must
return identical results for every vector in fixtures/screening_cases.json.
"""
import json
import pathlib
import re
import shutil
import subprocess

import pytest

from harvesters.screening import (
    CLASSIFICATIONS,
    DEFAULT_DISCOVERY,
    REASON_LABELS,
    SCREENING_VERSION,
    key_reasons,
    passes_buy_box,
    screen_property,
)

REPO = pathlib.Path(__file__).resolve().parents[2]
DATA = json.loads((REPO / "tests/python/fixtures/screening_cases.json").read_text(encoding="utf-8"))
CASES = DATA["cases"]
JS = (REPO / "public/screening.js").read_text(encoding="utf-8")


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_s01_expected_classification_and_reasons(case):
    r = screen_property(case["row"])
    assert r["classification"] == case["classification"]
    assert sorted(x["code"] for x in r["reasons"]) == sorted(case["codes"])
    assert r["version"] == SCREENING_VERSION
    assert r["promoted"] == (r["classification"] in DEFAULT_DISCOVERY or r["classification"] == "NOT_SCREENED")


@pytest.mark.parametrize("i", range(len(DATA["buy_box"])))
def test_s02_buy_box(i):
    c = DATA["buy_box"][i]
    assert passes_buy_box(c["row"], screen_property(c["row"]), c["box"]) is c["passes"]


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_s03_js_and_python_agree_exactly():
    out = subprocess.run(["node", str(REPO / "tests/python/screening_vectors.mjs")],
                         capture_output=True, text=True, check=True, cwd=REPO)
    js = json.loads(out.stdout)
    for case, got in zip(CASES, js["cases"]):
        assert got == screen_property(case["row"]), case["name"]
    for c, got in zip(DATA["buy_box"], js["buy_box"]):
        assert got is passes_buy_box(c["row"], screen_property(c["row"]), c["box"])


def test_s04_versions_and_vocabularies_match_the_js():
    assert f'SCREENING_VERSION = "{SCREENING_VERSION}"' in JS
    for code in REASON_LABELS:
        assert f"{code}:" in JS, code
    js_codes = set(re.findall(r"^  ([A-Z_]+): \"", JS.split("REASON_LABELS")[1].split("});")[0], re.M))
    assert js_codes == set(REASON_LABELS)
    for c in CLASSIFICATIONS:
        assert f'"{c}"' in JS


def test_s05_every_emitted_reason_has_a_label_and_evidence():
    for case in CASES:
        for r in screen_property(case["row"])["reasons"]:
            assert r["code"] in REASON_LABELS
            assert r["evidence"].strip()
            assert r["severity"] in {"limited", "risk", "review", "info"}


def test_s06_absent_evidence_never_produces_an_adverse_class():
    """A row carrying only identity and a value - no class, no size, no legal
    text - can be REVIEW or INSUFFICIENT_DATA, never LIMITED / HIGH_RISK."""
    for row in (
        {"source": "laft", "state": "TX", "parcel": "1", "assessed": 1000},
        {"source": "auction", "state": "FL", "parcel": "2"},
        {"source": "laft", "state": "LA", "parcel": "3", "market": 50},
        {"source": "auction", "state": "FL", "parcel": "4", "acreage": None, "legal_desc": ""},
    ):
        assert screen_property(row)["classification"] in {"REVIEW", "INSUFFICIENT_DATA"}


def test_s07_key_reasons_order_and_info_dropped():
    r = screen_property(CASES[2]["row"])  # tiny vacant: limited + review reasons
    ks = key_reasons(r)
    assert ks[0]["severity"] == "limited"
    assert all(k["severity"] != "info" for k in ks)


def test_s08_screening_writes_nothing():
    """The screen is a pure classifier: no network, no database client, no
    file writes in either implementation."""
    py = (REPO / "harvesters/screening/rules.py").read_text(encoding="utf-8")
    for banned in ("requests", "urllib", "supabase", "open(", "subprocess"):
        assert banned not in py
    for banned in ("fetch(", "supabase", "localStorage", "document."):
        assert banned not in JS


def test_s09_no_roi_language():
    """Screening metrics are ratios of published numbers - never a return."""
    for text in (JS, (REPO / "harvesters/screening/rules.py").read_text(encoding="utf-8")):
        code_only = "\n".join(l for l in text.splitlines() if not l.strip().startswith(("//", "#")))
        for banned in ("ROI", "profit", "Profit", "guaranteed", "Guaranteed", "return on"):
            assert banned not in code_only, banned
