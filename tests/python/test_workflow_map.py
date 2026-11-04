"""Shared List / Map filters and the acquisition-method filter (2026-10-05)."""
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
APP = (REPO / "public/app.js").read_text(encoding="utf-8")


def _labels():
    block = re.search(r"const ACQUISITION_MODE_LABELS = \{(.*?)\n\};", APP, re.S).group(1)
    return set(re.findall(r"(\w+):\s*\"", block))


def test_acquisition_method_options_are_engine_modes():
    sel = re.search(r'<select id="acqModeFilter"[^>]*>(.*?)</select>', APP, re.S).group(1)
    values = set(re.findall(r'value="(\w+)"', sel))
    modes = _labels()
    assert values - {"any", "unverified"} <= modes, values - modes
    # "none" is a stated absence, not a method a customer can choose to follow.
    assert "none" not in values


def test_acquisition_method_filter_reads_the_verified_record():
    body = re.search(r'if \(state\.acqMode !== "any"\) \{(.*?)\n  \}', APP, re.S).group(1)
    assert "acquisitionOf(p)" in body and 'p.source !== "laft"' in body
    assert "a.verified" in body


def test_map_applies_list_filters_by_default_and_hash_carries_it():
    assert "listFilters: true" in APP
    rows = re.search(r"function computeMapRows\(\) \{(.*?)\n\}", APP, re.S).group(1)
    assert "mapFilter.listFilters" in rows and "passes(p)" in rows and 'state.statusView !== "archive"' in rows
    assert 'q.set("lf", "0")' in APP and 'params.lf !== "0"' in APP


def test_acquisition_method_not_in_saved_search_vocabulary():
    py = (REPO / "scripts/saved_search_match.py").read_text(encoding="utf-8")
    assert "acq_mode" not in py and "acqMode" not in py
