"""County research status ladder (2026-10-06): Python rule = app.js rule."""
import json
import re
from pathlib import Path

import pytest

from harvesters.sources import county_research as CR

REPO = Path(__file__).resolve().parents[2]
CASES = json.loads((REPO / "tests/python/fixtures/county_research_cases.json").read_text(encoding="utf-8"))["cases"]
APP = (REPO / "public/app.js").read_text(encoding="utf-8")


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["name"])
def test_vectors(case):
    out = CR.research_status(case["facts"])
    assert [s["step"] for s in out["steps"]] == list(CR.STEPS)
    assert [s["state"] for s in out["steps"]] == case["states"]
    assert out["reached"] == case["reached"]
    assert all(s["reason"] for s in out["steps"])


def test_never_verified_by_rows_alone():
    # Rows on file never make a county "researched": no source, no step past nothing.
    out = CR.research_status({"rows": 500, "rows_property_ok": 0})
    assert out["reached"] is None
    assert CR.label(out["reached"]) == "Not yet researched"


def test_no_score_in_output():
    # Statements about records, never a number standing in for quality.
    for case in CASES:
        out = CR.research_status(case["facts"])
        assert set(out) == {"steps", "reached"}
        for s in out["steps"]:
            assert set(s) == {"step", "state", "reason"}
            assert "%" not in s["reason"] and "score" not in s["reason"].lower()


def test_js_labels_mirror_python():
    body = re.search(r"var COUNTY_RESEARCH_STEP_LABELS = (?:COUNTY_RESEARCH_STEP_LABELS \|\| )?\{(.*?)\};", APP, re.S).group(1)
    assert dict(re.findall(r"(\w+):\s*\"([^\"]+)\"", body)) == CR.STEP_LABELS
    steps = re.search(r"var COUNTY_RESEARCH_STEPS = (?:COUNTY_RESEARCH_STEPS \|\| )?\[(.*?)\];", APP, re.S).group(1)
    assert tuple(re.findall(r"\"(\w+)\"", steps)) == CR.STEPS
