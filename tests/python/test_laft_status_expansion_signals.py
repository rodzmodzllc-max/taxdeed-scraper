"""The recorder must accept every EMPTY signal the expansion runner emits.

Regression for the 2026-10-11 scheduled CO job (run 38160112800): with the
per-source status, Douglas County recorded its COMPLETE liens list AND its
tax-sale list, which the ArcGIS cycle guard reads EMPTY with signal
``past_cycle`` - a signal ``laft_status.EMPTY_SIGNALS`` did not know, so
``StatusRecorder.empty()`` raised and the whole state's harvest failed before
the sync. Before the per-source status, a county with any rows was recorded
COMPLETE and the signal never reached the recorder.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import laft_status as ls  # noqa: E402

RUNNER = ROOT / "scripts" / "harvest_expansion.py"


def runner_empty_signals() -> set[str]:
    """Every string literal the expansion runner returns as an EMPTY signal,
    plus the default it passes to the recorder."""
    text = RUNNER.read_text(encoding="utf-8")
    out = set(re.findall(r'"EMPTY",\s*\[\],\s*None,\s*None,\s*"([a-z_]+)"', text))
    out |= set(re.findall(r'recorder\.empty\([^)]*?or\s+"([a-z_]+)"', text))
    return out


def test_runner_emits_known_signals():
    sigs = runner_empty_signals()
    assert {"past_cycle", "no_list_past_redemption", "no_offered_status", "empty_layer", "empty_marker"} <= sigs
    unknown = sorted(sigs - set(ls.EMPTY_SIGNALS))
    assert not unknown, f"expansion runner emits EMPTY signal(s) the recorder refuses: {unknown}"


def test_recorder_accepts_each_runner_signal(tmp_path):
    for sig in sorted(runner_empty_signals()):
        rec = ls.StatusRecorder("expansion_test", parser_version=1, path=tmp_path / f"{sig}.json", state="CO")
        entry = rec.empty("Douglas", sig, source_url="https://example.invalid/layer", source_id=f"src_{sig}")
        assert entry.status == "EMPTY" and entry.empty_signal == sig and entry.row_count == 0
        assert entry.empty_marker_observed is (sig == "empty_marker")


def test_douglas_shape_records_both_sources(tmp_path):
    """One county, one COMPLETE source and one EMPTY past_cycle source: two
    entries, no exception, and the county-level read is the worst of the two
    (EMPTY never stands in for the COMPLETE read, nor the reverse)."""
    rec = ls.StatusRecorder("expansion", parser_version=1, path=tmp_path / "co.json", state="CO")
    rec.complete("Douglas", 138, source_url="https://example.invalid/liens", source_id="co_douglas_county_held_liens")
    rec.empty("Douglas", "past_cycle", source_url="https://example.invalid/sale", source_id="co_douglas_tax_sale_list")
    by_source = {e.source_id: e.status for e in rec.entries if e.county == "Douglas"}
    assert by_source == {"co_douglas_county_held_liens": "COMPLETE", "co_douglas_tax_sale_list": "EMPTY"}
    rec.write()
    loaded = ls.load_status(tmp_path / "co.json")
    assert sorted((e["source_id"], e["status"], e.get("empty_signal")) for e in loaded) == [
        ("co_douglas_county_held_liens", "COMPLETE", None),
        ("co_douglas_tax_sale_list", "EMPTY", "past_cycle"),
    ]
