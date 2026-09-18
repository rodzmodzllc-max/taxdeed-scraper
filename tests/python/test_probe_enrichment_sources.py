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


# --- Galveston DBF identity join --------------------------------------------


def _synthetic_dbf(rows, fields):
    """Minimal dBase III file: 32-byte header + 32-byte field descriptors + 0x0D + records."""
    import struct
    rec_len = 1 + sum(l for _, l in fields)
    header_len = 32 + 32 * len(fields) + 1
    out = bytearray(struct.pack("<4BIHH", 3, 26, 9, 18, len(rows), header_len, rec_len)) + b"\0" * 20
    for name, ln in fields:
        desc = bytearray(32)
        desc[:len(name)] = name.encode("ascii")
        desc[11] = ord("C")
        desc[16] = ln
        out += desc
    out += b"\x0D"
    for r in rows:
        out += b" "
        for name, ln in fields:
            out += str(r.get(name, "")).ljust(ln)[:ln].encode("latin-1")
    return bytes(out)


GAL_FIELDS = [("GEOID", 20), ("PID", 10), ("SITUS", 30), ("LANDUSE", 6), ("ACRES", 10),
              ("VAL26LAND", 12), ("VAL26IMP", 12), ("VAL26TOT", 12)]
GAL_ROWS = [
    {"GEOID": "3510-0065-2002-002", "PID": "123456", "SITUS": "2823 AVENUE O 1/2", "LANDUSE": "A1",
     "ACRES": "0.118", "VAL26LAND": "50000", "VAL26IMP": "422600", "VAL26TOT": "472600"},
    {"GEOID": "0197-0060-0000-000", "PID": "223456", "SITUS": "", "LANDUSE": "C1",
     "ACRES": "1.0", "VAL26LAND": "18450", "VAL26IMP": "0", "VAL26TOT": "18450"},
    {"GEOID": "9999-0000-0000-001", "PID": "323456", "SITUS": "X", "LANDUSE": "A1",
     "ACRES": "0.2", "VAL26LAND": "1", "VAL26IMP": "2", "VAL26TOT": "3"},
]


def test_parse_dbf_records_round_trips_a_synthetic_file(probe):
    blob = _synthetic_dbf(GAL_ROWS, GAL_FIELDS)
    header = probe.parse_dbf_header(blob)
    assert header["record_count"] == 3 and header["field_count"] == 8
    recs = list(probe.parse_dbf_records(blob, header))
    assert [r["GEOID"] for r in recs] == [r["GEOID"] for r in GAL_ROWS]
    assert recs[0]["VAL26TOT"] == "472600"


def test_identity_join_matches_stored_case_no_to_geoid_digits(probe):
    blob = _synthetic_dbf(GAL_ROWS, GAL_FIELDS)
    header = probe.parse_dbf_header(blob)
    stored = ["351000652002002", "019700600000000", "000000000000000"]
    j = probe.galveston_identity_join(blob, header, stored)
    assert j["records_parsed"] == 3
    assert j["matched_via_geoid"] == 2 and j["matched_via_pid"] == 0
    assert j["unmatched"] == 1 and j["unmatched_examples"] == ["000000000000000"]
    assert j["ambiguous_geoid"] == 0
    ex = j["examples"][0]
    assert ex["stored_case_no"] == "351000652002002" and ex["GEOID"] == "3510-0065-2002-002"
    assert ex["VAL26TOT"] == "472600" and ex["SITUS"] == "2823 AVENUE O 1/2"


def test_identity_join_flags_duplicate_geoids_as_ambiguous(probe):
    rows = GAL_ROWS + [dict(GAL_ROWS[0], PID="999999")]
    blob = _synthetic_dbf(rows, GAL_FIELDS)
    j = probe.galveston_identity_join(blob, probe.parse_dbf_header(blob), ["351000652002002"])
    assert j["matched_via_geoid"] == 1 and j["ambiguous_geoid"] == 1


def test_tx_verdict_is_driven_by_the_identity_join(probe):
    base = {"dbf": {"fields": []}, "has_value_field": True, "has_account_field": True}
    assert probe.verdict_tx({**base, "identity_join": {"stored_accounts": 203, "matched_via_geoid": 200}}) == "VIABLE"
    assert probe.verdict_tx({**base, "identity_join": {"stored_accounts": 203, "matched_via_geoid": 50}}) == "PARTIAL"
    assert probe.verdict_tx({**base, "identity_join": {"stored_accounts": 203, "matched_via_geoid": 0}}) == "NOT_VIABLE"
    assert probe.verdict_tx({"dbf": None}) == "NOT_VIABLE"


# --- FL direct ALT_KEY lookup -------------------------------------------------


class _Resp:
    def __init__(self, payload, status=200):
        self._p, self.status_code = payload, status

    def json(self):
        return self._p

    def raise_for_status(self):
        pass


def test_altkey_lookup_prefers_the_query_form_that_returns_features(probe, monkeypatch):
    calls = []

    def fake_get(url, **kw):
        calls.append(kw.get("params", {}))
        params = kw.get("params", {})
        if params.get("f") == "json" and "where" not in params:
            return _Resp({"fields": [{"name": "ALT_KEY", "type": "esriFieldTypeDouble"}]})
        where = params["where"]
        if where.startswith("ALT_KEY='"):
            return _Resp({"error": {"code": 400, "message": "Cannot perform query"}})
        key = where.split("=")[1]
        hits = {"2102746": ["21 3507-01-3-12"], "1028868": ["17E19S27 10000 005S"]}
        return _Resp({"features": [{"attributes": {"PARCEL_ID": p}} for p in hits.get(key, [])]})

    monkeypatch.setattr(probe.requests, "get", fake_get)
    monkeypatch.setattr(probe.time, "sleep", lambda *_: None)
    out = probe.probe_altkey_lookups({"Citrus": ["1028868", "0000001"], "Hernando": ["00190947"]})
    assert out["layer_altkey_type"] == "esriFieldTypeDouble"
    assert out["working_form"] == "numeric"
    assert out["form_trials"]["quoted"]["error"]
    assert out["counties"]["Citrus"] == {
        "tried": 2, "one_to_one_hits": 1, "multi_hits": 0, "misses": 1, "errors": [],
        "examples": [{"key": "1028868", "fdor_parcel_id": "17E19S27 10000 005S"}]}
    assert out["counties"]["Hernando"]["misses"] == 1
    # a leading-zero key is sent as a bare integer under the numeric form
    assert any(p.get("where") == "ALT_KEY=190947" for p in calls)


def test_altkey_lookup_stops_when_neither_form_works(probe, monkeypatch):
    monkeypatch.setattr(probe.requests, "get",
                        lambda url, **kw: _Resp({"error": {"code": 400}}) if "where" in kw.get("params", {}) else _Resp({"fields": []}))
    monkeypatch.setattr(probe.time, "sleep", lambda *_: None)
    out = probe.probe_altkey_lookups({"Brevard": ["2102746"]})
    assert out["working_form"] is None and out["counties"] == {}
