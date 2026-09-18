"""Tests for the pure parsing part of scripts/probe_enrichment_sources.py.

Only extract_alt_keys() is exercised: it must read the appraiser key out of
the JSON-escaped RealAuction listing text exactly as the harvester's Get-Field
does, for the two counties whose skins publish no parcel number. Fixtures are
the real first blocks captured in Actions run 35402576827 (2026-09-18).
No network.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "probe_enrichment_sources.py"

CITRUS_BLOCK = (
    r'@Htabindex=\"0\" @CAD_LBL\" scope=\"row\">Opening Bid:@F tabindex=\"0\" @CAD_DTA\">$23,370.65@G'
    r'@Htabindex=\"0\" @CAD_LBL\" scope=\"row\">Alternate Key:@F tabindex=\"0\" @CAD_DTA\"> '
    r'<a href=\"http://www.citruspa.org/_Web/datalets/datalet.aspx?mode=profileall&UseSearch=no&pin=1028868&jur=19&LMparent=20\" '
    r'onClick = \"return showExitPopup();\" target=\"_blank\">1028868</a> @G'
    r'@Htabindex=\"0\" @CAD_LBL\" scope=\"row\">Property Address:@F tabindex=\"0\" @CAD_DTA\">9050 N RAINELLE AVE@G'
)
HERNANDO_BLOCK = (
    r'@Htabindex=\"0\" @CAD_LBL\" scope=\"row\">Parcel Key:@F tabindex=\"0\" @CAD_DTA\"> '
    r'<a href=\"https://propsearch.hernandocountypa-florida.us/parcel/00190947\" onClick = \"return showExitPopup();\" '
    r'target=\"_blank\">00190947</a>@G@Htabindex=\"0\" @CAD_LBL\" scope=\"row\">Property Address:@F tabindex=\"0\" @CAD_DTA\">MOSS ST@G'
)
ALACHUA_BLOCK = (
    r'@Htabindex=\"0\" @CAD_LBL\" scope=\"row\">Parcel ID:@F tabindex=\"0\" @CAD_DTA\"> '
    r'<a href=\"https://qpublic.schneidercorp.com/x\" target=\"_blank\">02684-000-000</a>@G'
)


@pytest.fixture()
def probe(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://example.test")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "not-a-real-key")
    spec = importlib.util.spec_from_file_location("_probe_src", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_probe_src"] = mod
    spec.loader.exec_module(mod)
    return mod


def _listing(*blocks):
    return "preamble" + "".join("AITEM_" + b for b in blocks)


def test_citrus_alternate_key_is_read_from_anchor_text(probe):
    assert probe.extract_alt_keys(_listing(CITRUS_BLOCK), ("Alternate Key",)) == ["1028868"]


def test_hernando_parcel_key_keeps_leading_zeros(probe):
    assert probe.extract_alt_keys(_listing(HERNANDO_BLOCK), ("Parcel Key",)) == ["00190947"]


def test_one_key_per_block_in_page_order(probe):
    text = _listing(HERNANDO_BLOCK, HERNANDO_BLOCK.replace("00190947", "00200001"))
    assert probe.extract_alt_keys(text, ("Parcel Key",)) == ["00190947", "00200001"]


def test_control_county_without_the_label_yields_nothing(probe):
    assert probe.extract_alt_keys(_listing(ALACHUA_BLOCK), ("Alternate Key", "Parcel Key")) == []


def test_live_key_counties_are_the_two_confirmed_ones(probe):
    assert set(probe.FL_LIVE_KEY_COUNTIES) == {"Citrus", "Hernando"}
    assert probe.FL_LIVE_KEY_COUNTIES["Citrus"]["co_no"] == 19
    assert probe.FL_LIVE_KEY_COUNTIES["Hernando"]["co_no"] == 37
    assert set(probe.FL_LIVE_KEY_COUNTIES) & set(probe.FL_COUNTIES) == set()


def test_module_import_has_no_side_effects(probe):
    assert not (REPO / "tests" / "python" / "out").exists()


def test_get_merges_caller_headers_over_the_probe_user_agent(probe, monkeypatch):
    # The Supabase read passes apikey/Authorization headers; the first live run
    # died with "got multiple values for keyword argument 'headers'".
    seen = {}

    def fake_get(url, **kw):
        seen.update(kw)
        return object()

    monkeypatch.setattr(probe.requests, "get", fake_get)
    probe._get("https://example.test/x", headers={"apikey": "k"}, params={"a": "1"})
    assert seen["headers"]["apikey"] == "k"
    assert seen["headers"]["User-Agent"] == probe.UA["User-Agent"]
    assert seen["params"] == {"a": "1"}
    assert seen["timeout"] == probe.TIMEOUT


def test_get_without_caller_headers_keeps_the_user_agent(probe, monkeypatch):
    seen = {}
    monkeypatch.setattr(probe.requests, "get", lambda url, **kw: seen.update(kw))
    probe._get("https://example.test/y")
    assert seen["headers"] == probe.UA
