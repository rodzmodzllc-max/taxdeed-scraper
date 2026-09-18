"""Tests for Phase 60 - the slash -> dash parcel normalization rule.

Why this rule exists, and why it is narrow:

St. Lucie's parcel format was already cracked. Its auction rows enriched at
28 of 29 while its LienHub certificate rows sat at 0 of 16 - the same county,
the same statewide layer, the same CO_NO. The only difference was the
separator in front of the final check digit: we store
"2403-602-0056-000/8" and the layer holds "2403-602-0056-000-8". The source
itself is inconsistent about it ("2402-503-0089-000-1" is already stored
with a dash), which is what makes this a formatting artefact rather than a
different identifier. Confirmed live 8 of 8 against real unenriched St.
Lucie parcels on 2026-09-18, every one returning a real situs address and
just value.

The tests below are mostly about what must NOT happen, in the same spirit as
the Phase 52 separator tests:

  * A parcel with no "/" must gain no candidate. Every extra candidate is one
    more request per row, per county, per run against a free public API, and
    only 20 rows statewide contain a slash at all.
  * The as-is form must still be tried first, so counties that already match
    exactly never pay for this.
  * The rule must not silently become a general "replace every separator"
    rule - the reverse (dash -> slash) is deliberately absent, no county has
    been observed needing it.

No network and no database anywhere in this file.
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
    spec = importlib.util.spec_from_file_location("_p60_enrich", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_p60_enrich"] = mod
    spec.loader.exec_module(mod)
    return mod


# The eight real unenriched St. Lucie parcels the rule was confirmed against
# live on 2026-09-18, with the layer PARCEL_ID each one resolved to.
CONFIRMED_LIVE = (
    ("4401-504-0043-000/3", "4401-504-0043-000-3"),
    ("1423-130-0006-000/4", "1423-130-0006-000-4"),
    ("2419-131-0002-000/9", "2419-131-0002-000-9"),
    ("2405-817-0036-000/8", "2405-817-0036-000-8"),
    ("2403-602-0056-000/8", "2403-602-0056-000-8"),
    ("2410-601-0121-010/7", "2410-601-0121-010-7"),
    ("3209-131-0017-000/5", "3209-131-0017-000-5"),
    ("2408-242-0002-000/6", "2408-242-0002-000-6"),
)


@pytest.mark.parametrize("stored,expected", CONFIRMED_LIVE)
def test_p60_01_slash_form_yields_the_dashed_candidate(enrich, stored, expected):
    """Each parcel confirmed live must actually be produced by the rule."""
    assert expected in enrich.normalize_candidates(stored), stored


def test_p60_02_as_is_form_is_still_tried_first(enrich):
    """A county that already matches exactly must not pay an extra request."""
    assert enrich.normalize_candidates("2402-503-0089-000-1")[0] == "2402-503-0089-000-1"


def test_p60_03_parcels_without_a_slash_gain_no_candidate(enrich):
    """The rule must be free for the other 66 counties. For a parcel with no
    slash the substitution equals the parcel itself, which the dedupe set
    already dropped - so the candidate count must be unchanged."""
    for stored in ("00310-012-000", "12734 001 000", "3030520754130",
                   "A0031920000", "722000004331", "R08-422-18-0000-0010-0000"):
        candidates = enrich.normalize_candidates(stored)
        assert not any("/" in c for c in candidates), stored
        assert len(candidates) == len(set(candidates)), stored


def test_p60_04_the_reverse_rule_is_not_added(enrich):
    """dash -> slash is deliberately NOT a candidate: no county has been
    observed needing it, and an unproven candidate costs a request per row."""
    candidates = enrich.normalize_candidates("2402-503-0089-000-1")
    assert not any("/" in c for c in candidates)


def test_p60_05_candidate_list_stays_deduplicated(enrich):
    for stored, _ in CONFIRMED_LIVE:
        candidates = enrich.normalize_candidates(stored)
        assert len(candidates) == len(set(candidates)), stored


def test_p60_06_alnum_only_form_did_not_already_cover_this(enrich):
    """Guards the claim that this rule is genuinely new. The alnum-only
    candidate strips the slash too, but it also strips every dash, giving a
    form the layer does not hold - which is why St. Lucie's certificate rows
    missed under the pre-Phase-60 candidate set."""
    candidates = enrich.normalize_candidates("2403-602-0056-000/8")
    assert "240360200560008" in candidates      # the alnum-only form
    assert "2403-602-0056-000-8" in candidates   # the form that actually matches
    assert candidates.index("2403-602-0056-000-8") < candidates.index("240360200560008")
