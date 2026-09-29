"""scripts/enrich_property_details.py, 2026-09-29: the identifier plausibility
gate, layer-error detection (source unavailable / parser rejection), the
Escambia alternate-key rule, and the counts-only diagnostics report.

Every layer answer here is a fixture; nothing is fetched. The Escambia rule
is asserted exactly as the production evidence supports it (a 9-digit
ALT_KEY from a dd-dddd-ddd account number) and refused for every other
county and every other shape.
"""
from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "enrich_property_details.py"
sys.path.insert(0, str(REPO / "scripts"))


@pytest.fixture()
def enrich(monkeypatch, tmp_path):
    monkeypatch.setenv("SUPABASE_URL", "https://example.test")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "not-a-real-key")
    monkeypatch.setenv("ENRICH_REPORT", str(tmp_path / "public" / "fdor-enrichment.json"))
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(tmp_path / "summary.md"))
    spec = importlib.util.spec_from_file_location("_diag_enrich", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_diag_enrich"] = mod
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod.time, "sleep", lambda *_: None)
    monkeypatch.setattr(mod.random, "randrange", lambda *_: 0)
    return mod


class FakeResponse:
    def __init__(self, payload, status=200, text=""):
        self._payload = payload
        self.status_code = status
        self.text = text

    def raise_for_status(self):
        return None

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


ROLL = {"PARCEL_ID": "362S301500001006", "ALT_KEY": "111856000", "JV": 50000, "AV_NSD": 40000, "OWN_NAME": "ROLL OWNER",
        "S_LEGAL": "ROLL LEGAL", "LND_SQFOOT": 43560, "ASMNT_YR": 2025, "TV_NSD": 30000, "PA_UC": "00", "DOR_UC": "000"}


class Harness:
    """`layer` maps a where-clause KEY - "PARCEL_ID:<cand>" or "ALT_KEY:<cand>" -
    to a roll dict, "dup", "error", "arcgis-error", "no-features", "html"."""

    def __init__(self, mod, monkeypatch, county, rows, *, layer):
        self.patches = []
        self.lookups = []

        def fake_get(url, headers=None, params=None, timeout=None):
            params = params or {}
            if "rest/v1/properties" in url:
                if params.get("select") == "county":
                    return FakeResponse([{"county": county} for _ in rows])
                if params.get("limit") == "0":
                    return FakeResponse([])
                return FakeResponse(rows[int(params["offset"]):int(params["offset"]) + int(params["limit"])])
            if url == mod.FDOR_ENDPOINT:
                m = re.search(r"(PARCEL_ID|ALT_KEY)='([^']*)' AND CO_NO=(\d+)", params["where"])
                key = f"{m.group(1)}:{m.group(2)}"
                self.lookups.append((key, int(m.group(3))))
                outcome = layer.get(key)
                if outcome == "error":
                    raise mod.requests.ConnectionError("boom")
                if outcome == "dup":
                    return FakeResponse({"features": [{"attributes": {}}, {"attributes": {}}]})
                if outcome == "arcgis-error":
                    return FakeResponse({"error": {"code": 500, "message": "Error performing query operation"}})
                if outcome == "no-features":
                    return FakeResponse({"objectIdFieldName": "OBJECTID"})
                if outcome == "html":
                    return FakeResponse(ValueError("Expecting value"), text="<html>maintenance</html>")
                if outcome:
                    return FakeResponse({"features": [{"attributes": outcome, "centroid": {"x": -87.2, "y": 30.4}}]})
                return FakeResponse({"features": []})
            raise AssertionError(f"unexpected GET {url}")

        def fake_patch(url, headers=None, json=None, timeout=None):
            self.patches.append((url.rsplit("eq.", 1)[1], json))
            return FakeResponse(None, status=204)

        monkeypatch.setattr(mod.requests, "get", fake_get)
        monkeypatch.setattr(mod.requests, "patch", fake_patch)


def _row(i, county="Escambia", source="certificate", parcel="11-1856-000", **extra):
    r = {"id": f"{county}-{i}", "source": source, "parcel": parcel, "county": county, "address": "x"}
    r.update(extra)
    return r


# ==================== 1. alternate key: rule, shape, county scope ====================


def test_a01_escambia_account_number_maps_to_its_nine_digit_alt_key_and_nothing_else_does(enrich):
    assert enrich.alt_key_candidate("Escambia", "11-1856-000") == "111856000"
    assert enrich.alt_key_candidate("Escambia", "111856000") == "111856000"     # already unpunctuated
    assert enrich.alt_key_candidate("Escambia", " 02-3125-000 ") == "023125000"  # leading zero kept
    for bad in ("362S301500001006", "11-1856-00", "11-18560-000", "1-1856-000", "11-1856-000-1", "", None, "HIT-1"):
        assert enrich.alt_key_candidate("Escambia", bad) is None, bad
    # Other counties publish identifiers of this exact shape too (Bay, Santa
    # Rosa, Okaloosa account numbers) - none has a proven ALT_KEY rule, so
    # none is tried: the rule is county-scoped, never a shape heuristic.
    for county in ("Bay", "Santa Rosa", "Okaloosa", "Indian River", "Hillsborough", "Citrus", "Marion"):
        assert enrich.alt_key_candidate(county, "11-1856-000") is None, county
    assert enrich.ALT_KEY_RULES.keys() == {"Escambia"}


def test_a02_alt_key_is_tried_only_after_every_parcel_id_spelling_missed_and_is_county_scoped(enrich, monkeypatch):
    h = Harness(enrich, monkeypatch, "Escambia", [], layer={"ALT_KEY:111856000": ROLL})
    attrs, centroid, cand = enrich.lookup_fdor("Escambia", "11-1856-000")
    assert attrs["OWN_NAME"] == "ROLL OWNER" and centroid == {"x": -87.2, "y": 30.4}
    assert cand == enrich.ALT_KEY_PREFIX + "111856000"
    keys = [k for k, _ in h.lookups]
    assert keys[-1] == "ALT_KEY:111856000" and all(k.startswith("PARCEL_ID:") for k in keys[:-1]) and len(keys[:-1]) >= 2
    assert {co for _, co in h.lookups} == {27}                       # CO_NO 27 on every request, alt key included
    # A PARCEL_ID hit short-circuits: the alternate key is never asked for.
    h2 = Harness(enrich, monkeypatch, "Escambia", [], layer={"PARCEL_ID:111856000": ROLL, "ALT_KEY:111856000": ROLL})
    attrs, _, cand = enrich.lookup_fdor("Escambia", "11-1856-000")
    assert cand == "111856000" and "ALT_KEY:111856000" not in [k for k, _ in h2.lookups]


def test_a03_alt_key_match_must_be_unique_and_echo_the_key(enrich, monkeypatch):
    Harness(enrich, monkeypatch, "Escambia", [], layer={"ALT_KEY:111856000": "dup"})
    assert enrich.lookup_fdor("Escambia", "11-1856-000") == (None, None, enrich.AMBIGUOUS_MATCH)
    # A feature whose own ALT_KEY is not the value asked for is not a match.
    Harness(enrich, monkeypatch, "Escambia", [], layer={"ALT_KEY:111856000": {**ROLL, "ALT_KEY": "999999999"}})
    assert enrich.lookup_fdor("Escambia", "11-1856-000") == (None, None, None)
    Harness(enrich, monkeypatch, "Escambia", [], layer={"ALT_KEY:111856000": {**ROLL, "ALT_KEY": None}})
    assert enrich.lookup_fdor("Escambia", "11-1856-000") == (None, None, None)


def test_a04_no_cross_county_or_cross_state_alt_key_match(enrich, monkeypatch):
    # The same account number in another county: no ALT_KEY request at all.
    h = Harness(enrich, monkeypatch, "Santa Rosa", [], layer={"ALT_KEY:111856000": ROLL})
    assert enrich.lookup_fdor("Santa Rosa", "11-1856-000") == (None, None, None)
    assert all(k.startswith("PARCEL_ID:") for k, _ in h.lookups) and {co for _, co in h.lookups} == {67}
    # A county this Florida layer does not know (a Texas county name): no request of any kind.
    h = Harness(enrich, monkeypatch, "Galveston", [], layer={"ALT_KEY:111856000": ROLL})
    assert enrich.lookup_fdor("Galveston", "11-1856-000") == (None, None, None) and h.lookups == []


def test_a05_main_records_an_alt_key_match_distinctly_in_provenance_and_counts_it(enrich, monkeypatch, capsys):
    rows = [_row(1)]
    h = Harness(enrich, monkeypatch, "Escambia", rows, layer={"ALT_KEY:111856000": ROLL})
    enrich.main()
    (pid, body), = h.patches
    assert pid == "Escambia-1" and body["owner_name"] == "ROLL OWNER" and body["taxable_value"] == 30000 and body["acreage"] == 1.0
    prov = body["field_provenance"]["owner_name"]
    assert prov["source"] == "fdor_nal" and prov["matched_field"] == "ALT_KEY"
    assert prov["matched_alt_key"] == "111856000" and prov["matched_parcel_id"] == "362S301500001006"
    assert body["fdor_alt_key"] == "111856000"
    out = capsys.readouterr().out
    assert "matched by alternate key 1" in out and "matched 1, written 1" in out
    for secret in ("11-1856-000", "111856000", "ROLL OWNER", "362S301500001006"):
        assert secret not in out, secret
    # A PARCEL_ID match carries no alternate-key keys at all.
    h = Harness(enrich, monkeypatch, "Escambia", [_row(2, parcel="362S301500001006")], layer={"PARCEL_ID:362S301500001006": ROLL})
    enrich.main()
    prov = h.patches[-1][1]["field_provenance"]["owner_name"]
    assert "matched_field" not in prov and "matched_alt_key" not in prov and prov["matched_parcel_id"] == "362S301500001006"


# ==================== 2. gates: malformed identifiers, layer errors ====================


def test_g01_malformed_identifiers_never_reach_the_layer_and_are_counted(enrich, monkeypatch, capsys):
    rows = [
        _row(1, county="Pasco", source="laft", parcel="****2025XX000042TDAXXXESCHEATEDTOCOUNTY09/17/2028****" * 3),  # > 40 chars
        _row(2, county="Pasco", source="laft", parcel="CURRENTPURCHASEPRICE,C"),   # no digit
        _row(3, county="Pasco", source="laft", parcel="12-34\n56"),                 # line break
        _row(4, county="Pasco", source="laft", parcel="24-26-16-0010-00000-0010"),  # real shape, layer has it
    ]
    h = Harness(enrich, monkeypatch, "Pasco", rows, layer={"PARCEL_ID:24-26-16-0010-00000-0010": ROLL})
    enrich.main()
    assert [pid for pid, _ in h.patches] == ["Pasco-4"]
    assert all(k.startswith("PARCEL_ID:24-26-16") or k.startswith("PARCEL_ID:242616") for k, _ in h.lookups)
    out = capsys.readouterr().out
    assert "malformed identifier (no request) 3" in out and "unmatched 0" in out and "matched 1, written 1" in out
    report = json.loads(Path(enrich.REPORT_PATH).read_text())
    assert report["malformed_identifier"] == 3 and report["matched"] == 1 and report["unmatched"] == 0
    assert "CURRENTPURCHASEPRICE" not in out and "ESCHEATED" not in out


def test_g02_an_arcgis_error_payload_is_source_unavailable_not_a_miss_and_abandons_the_slice(enrich, monkeypatch, capsys):
    rows = [_row(i, county="Marion", source="laft", parcel=f"4033-003-0{i:02d}") for i in range(1, 5)]
    layer = {f"PARCEL_ID:4033-003-0{i:02d}": "arcgis-error" for i in range(1, 5)}
    h = Harness(enrich, monkeypatch, "Marion", rows, layer=layer)
    enrich.main()
    assert h.patches == []
    assert len(h.lookups) == 1                      # the first answer already said the layer is broken
    out = capsys.readouterr()
    assert "source unavailable 1" in out.out and "unmatched 0" in out.out
    assert "FDOR layer unavailable (layer error 500)" in out.err and "abandoning this county's slice" in out.err
    report = json.loads(Path(enrich.REPORT_PATH).read_text())
    assert report["source_unavailable"] == 1 and report["unmatched"] == 0 and report["per_county"]["Marion"] == {"matched": 0, "attempted": 1}


def test_g03_a_body_without_features_is_unavailable_and_a_non_json_body_is_a_parser_rejection(enrich, monkeypatch, capsys):
    Harness(enrich, monkeypatch, "Marion", [], layer={"PARCEL_ID:4033-003-029": "no-features"})
    with pytest.raises(enrich.FdorUnavailable):
        enrich.lookup_fdor("Marion", "4033-003-029")
    rows = [_row(1, county="Marion", source="laft", parcel="4033-003-029"), _row(2, county="Marion", source="laft", parcel="4033-003-030")]
    h = Harness(enrich, monkeypatch, "Marion", rows, layer={"PARCEL_ID:4033-003-029": "html", "PARCEL_ID:4033-003-030": ROLL})
    enrich.main()
    assert [pid for pid, _ in h.patches] == ["Marion-2"]           # the rejection skipped one row, the next still ran
    out = capsys.readouterr()
    assert "parser rejection 1" in out.out and "unmatched 0" in out.out and "unreadable body" in out.err


def test_g04_layer_errors_never_advance_the_miss_streak_or_stamp_a_row(enrich, monkeypatch):
    rows = [_row(i, county="Marion", source="laft", parcel=f"4033-003-0{i:02d}") for i in range(1, 10)]
    layer = {f"PARCEL_ID:4033-003-0{i:02d}": "html" for i in range(1, 9)}
    layer["PARCEL_ID:4033-003-009"] = ROLL
    h = Harness(enrich, monkeypatch, "Marion", rows, layer=layer)
    enrich.main()
    assert [pid for pid, _ in h.patches] == ["Marion-9"]           # eight rejections did not exhaust the ledger


# ==================== 3. diagnostics report ====================


def test_d01_identifier_shapes_are_value_free(enrich):
    assert enrich.identifier_shape("0035260000") == "d10"
    assert enrich.identifier_shape("A0009240000") == "A1d10"
    assert enrich.identifier_shape("11-1856-000") == "d2-d4-d3"
    assert enrich.identifier_shape("17E19S27 10000 005S") == "d2A1d2A1d2 d5 d3A1"
    assert enrich.identifier_shape("02239-137") == enrich.identifier_shape("06085-000") == "d5-d3"
    assert enrich.identifier_shape("") == enrich.identifier_shape(None) == "(blank)"
    assert not re.search(r"\d{4,}", enrich.identifier_shape("31370000007008000010.0"))


def test_d02_report_distinguishes_every_outcome_and_names_no_value(enrich, monkeypatch, capsys):
    rows = [
        _row(1, county="Hillsborough", source="laft", parcel="0035260000"),                        # unmatched
        _row(2, county="Hillsborough", source="laft", parcel="0542481800"),                        # unmatched
        _row(3, county="Hillsborough", source="certificate", parcel="A0009240000"),                # unmatched
        _row(4, county="Hillsborough", source="auction", parcel="0014440000",                      # matched, already populated
             prop_type="House", market=1, assessed=1, owner_name="ON FILE", latitude=1, longitude=1, address="12 Real St"),
        _row(5, county="Hillsborough", source="auction", parcel="DUP-0001"),                       # ambiguous
        _row(6, county="Hillsborough", source="auction", parcel="ERR-0001"),                       # transport error
        _row(7, county="Hillsborough", source="auction", parcel="NODIGITS"),                       # malformed
        _row(8, county="Hillsborough", source="auction", parcel="0100730000"),                     # matched, written
    ]
    # A roll record carrying only the fill-blank columns, on a row that has
    # them all: matched, nothing to write, stamped only.
    thin = {"PARCEL_ID": "0014440000", "JV": 1, "AV_NSD": 1, "OWN_NAME": "ROLL OWNER", "PHY_ADDR1": "1 X", "PHY_CITY": "Y"}
    layer = {"PARCEL_ID:0014440000": thin, "PARCEL_ID:DUP-0001": "dup", "PARCEL_ID:ERR-0001": "error", "PARCEL_ID:0100730000": ROLL}
    h = Harness(enrich, monkeypatch, "Hillsborough", rows, layer=layer)
    enrich.main()
    report = json.loads(Path(enrich.REPORT_PATH).read_text())
    assert {k: report[k] for k in ("attempted", "matched", "written", "already_populated", "unmatched", "ambiguous",
                                   "malformed_identifier", "source_unavailable", "parser_rejection", "error", "alt_key_matches")} == {
        "attempted": 8, "matched": 2, "written": 2, "already_populated": 1, "unmatched": 3, "ambiguous": 1,
        "malformed_identifier": 1, "source_unavailable": 0, "parser_rejection": 0, "error": 1, "alt_key_matches": 0}
    assert report["unmatched_shapes"] == {"Hillsborough": {"certificate": {"A1d10": 1}, "laft": {"d10": 2}}}
    assert report["per_county"] == {"Hillsborough": {"matched": 2, "attempted": 8}}
    text = json.dumps(report) + capsys.readouterr().out + Path(enrich.REPORT_PATH).parent.parent.joinpath("summary.md").read_text()
    for secret in ("0035260000", "0542481800", "A0009240000", "0014440000", "0100730000", "ROLL OWNER", "ON FILE", "DUP-0001", "ERR-0001"):
        assert secret not in text, secret
    assert "Hillsborough / laft: d10 x2" in text and "Hillsborough / certificate: A1d10 x1" in text
    assert "| already_populated | 1 |" in text and "| malformed_identifier | 1 |" in text
    # The already-populated row is still stamped (it matched) but got no provenance for values it did not receive.
    stamped = dict(h.patches)["Hillsborough-4"]
    assert set(stamped) == {"fdor_enriched_at"}


def test_d03_existing_fill_rules_and_texas_scoping_are_unchanged(enrich):
    src = SCRIPT.read_text(encoding="utf-8")
    assert 'ENRICH_STATE = os.environ.get("ENRICH_STATE", "FL")' in src
    assert 'fields["homestead"] = True' in src and "_num(attrs.get(\"JV_HMSTD\")) is not None" in src
    assert enrich._num(0) is None and enrich._num("0") is None and enrich._num(25000) == 25000.0   # a zero exemption is never "homestead"
    fields = enrich.build_update_fields({"owner_name": "SCRAPED", "assessed": 5}, {**ROLL, "JV_HMSTD": 0}, None)
    assert "owner_name" not in fields and "assessed" not in fields and "homestead" not in fields
    assert fields["taxable_value"] == 30000 and fields["land_use"] == "00" and fields["acreage"] == 1.0 and fields["legal_desc"] == "ROLL LEGAL"
