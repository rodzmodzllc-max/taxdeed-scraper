"""County spellings of the same parcel number for the FDOR layer (2026-10-25).

Synthetic identifiers with each county's shape - never a real parcel."""
from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))


@pytest.fixture
def enrich(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://example.invalid")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "x")
    return importlib.import_module("enrich_property_details")


def test_county_respellings_move_separators_only(enrich):
    f = enrich.county_format_candidates
    assert f("Hernando", "R12-345-67-0000-0010-0040") == ["R12 345 67 0000 0010 0040"]
    assert f("Lake", "01-02-03-004000000500") == ["01-02-03-0040-000-00500"]
    assert f("Lake", "01-02-03-100000C00600") == ["01-02-03-1000-00C-00600"]
    assert f("Flagler", "1112131400000100000") == ["11-12-13-1400-00010-0000"]
    assert f("Martin", "01-02-03-004-005-00230.70000") == ["01-02-03-004-005-00230-7"]
    for county, p in [("Hernando", "R12-345"), ("Lake", "01-02-03-0040-000-00500"), ("Flagler", "11-12-13-1400-00010-0000"),
                      ("Martin", "01-02-03-004-005-00230-7"), ("Lake", ""), ("Flagler", None)]:
        assert f(county, p) == [], (county, p)


def test_rules_are_county_scoped(enrich):
    f = enrich.county_format_candidates
    for county in ("Pasco", "Santa Rosa", "Volusia", "Walton", "Alachua"):
        assert f(county, "R12-345-67-0000-0010-0040") == []
        assert f(county, "1112131400000100000") == []
        assert f(county, "01-02-03-004000000500") == []


def test_digits_and_letters_never_change(enrich):
    import re
    for county, p in [("Hernando", "R12-345-67-0000-00A0-0040"), ("Lake", "01-02-03-100000C00600"),
                      ("Flagler", "0711317060RP0B50000"), ("Martin", "01-02-03-004-005-00151.40000")]:
        for cand in enrich.county_format_candidates(county, p):
            keep = lambda s: re.sub(r"[^0-9A-Z]", "", s)
            assert keep(cand).rstrip("0") == keep(p).rstrip("0") if county == "Martin" else keep(cand) == keep(p)


def test_mobile_home_and_mineral_accounts_get_no_rule(enrich):
    for county, p in [("Santa Rosa", "121N270000001000000M"), ("Pasco", "18-24-20-0000-02300-0090M"),
                      ("Walton", "06-3N-A9-MINR0-001-0000")]:
        assert enrich.county_format_candidates(county, p) == []
        assert enrich.alt_key_candidate(county, p) is None


def test_alt_key_rules_for_marion_and_monroe(enrich):
    assert enrich.alt_key_candidate("Marion", "58343") == "58343"
    assert enrich.alt_key_candidate("Marion", "3366395") == "3366395"
    assert enrich.alt_key_candidate("Marion", "1234") is None
    assert enrich.alt_key_candidate("Marion", "12345-678-90") is None
    assert enrich.alt_key_candidate("Monroe", "1452874") == "1452874"
    assert enrich.alt_key_candidate("Monroe", "145287") is None
    # Hillsborough: LienHub's "A" + 10-digit folio -> the bare folio
    assert enrich.alt_key_candidate("Hillsborough", "A0012345678") == "0012345678"
    assert enrich.alt_key_candidate("Hillsborough", "0012345678") is None
    assert enrich.alt_key_candidate("Hillsborough", "A001234567") is None


def test_lookup_tries_county_spelling_after_generic_ones(enrich, monkeypatch):
    asked = []

    def fake(where):
        asked.append(where)
        return [{"attributes": {"PARCEL_ID": "x"}, "centroid": {"x": -82.4, "y": 28.5}}] if "R12 345" in where else []

    monkeypatch.setattr(enrich, "_query_layer", fake)
    monkeypatch.setattr(enrich, "_require_lookup_permission", lambda *a: None)
    attrs, centroid, cand = enrich.lookup_fdor("Hernando", "R12-345-67-0000-0010-0040")
    assert cand == "R12 345 67 0000 0010 0040" and centroid
    assert "R12 345" in asked[-1] and len(asked) > 1
