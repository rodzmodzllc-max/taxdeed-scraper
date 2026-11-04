"""Parcel-format rules added 2026-09-18 for Lake, Leon and Citrus.

Every expected value below is a PARCEL_ID shape the FDOR layer returned
live for that county (probe_fl_parcel_formats.py, Actions run 35406185583)
and then confirmed by an exact hit on every sampled row (run 35407266083). The
rules are additive: each returns None for any other shape, so no other
county gains a candidate (and a request) from them.

No network.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "enrich_property_details.py"


@pytest.fixture()
def enrich(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://example.test")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "not-a-real-key")
    spec = importlib.util.spec_from_file_location("_enrich_fmt", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_enrich_fmt"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize("stored,expected", [
    ("01-19-26-100000C00600", "01-19-26-1000-00C-00600"),  # neighbour: 01-19-26-1000-00C-01900
    ("08-22-25-100500002400", "08-22-25-1005-000-02400"),  # neighbour: 08-22-25-0003-000-00500
    ("23-24-25-000300002200", "23-24-25-0003-000-02200"),
    ("06-18-24-039000018740", "06-18-24-0390-000-18740"),
])
def test_lake_dashed_tail_splits_4_3_5(enrich, stored, expected):
    assert enrich._expand_lake_dashed_tail(stored) == expected
    assert expected in enrich.normalize_candidates(stored)


@pytest.mark.parametrize("stored,expected", [
    ("411137C0180", "411137  C0180"),  # neighbour: '411137  C0050'
    ("223516D0490", "223516  D0490"),  # neighbour: '223516  D0680'
    ("321715C0080", "321715  C0080"),
    ("110250CD0150", "110250 CD0150"),  # 13-wide field, one space for a 6-char tail
])
def test_leon_short_form_is_padded_to_13(enrich, stored, expected):
    assert enrich._pad_leon_block(stored) == expected
    assert len(expected) == 13
    assert expected in enrich.normalize_candidates(stored)


def test_leon_13_char_values_are_left_alone(enrich):
    assert enrich._pad_leon_block("2131206040000") is None
    assert enrich._pad_leon_block("41017000000F0") is None


@pytest.mark.parametrize("stored,expected", [
    ("19E17S35 2B0E0 0330", "19E17S35      2B0E0 0330"),      # neighbour: '19E17S25      3B000 0320'
    ("19E18S140040 00230 0270", "19E18S140040  00230 0270"),  # neighbour: '19E17S360010  00260 0040'
    ("17E19S27 10000 005S", "17E19S27      10000 005S"),
])
def test_citrus_section_block_is_left_justified_in_8(enrich, stored, expected):
    assert enrich._pad_citrus_section(stored) == expected
    assert expected in enrich.normalize_candidates(stored)


@pytest.mark.parametrize("stored", [
    "02684-000-000",             # Alachua
    "26-43-23-C3-02762.0130",    # Lee
    "01-3123-034-0860",          # Miami-Dade
    "102S301000019002",          # Escambia
    "383205430110",              # Volusia
    "33-29-15-07326-000-0200",   # Pinellas
    "410426-020240-000-00",      # Clay (six-digit STR rule)
    "3217270004-000-12600",      # Lake, older shape (ten-digit rule)
    "16263101100060000A0",       # Pasco 19-char dashless (no proven rule)
    "R27 222 19 1560 0000 0081", # Hernando
])
def test_other_counties_gain_no_candidate_from_the_new_rules(enrich, stored):
    for fn in (enrich._expand_lake_dashed_tail, enrich._pad_leon_block,
               enrich._pad_citrus_section):
        assert fn(stored) is None, (fn.__name__, stored)
