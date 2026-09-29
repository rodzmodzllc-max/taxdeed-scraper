"""Enrichment phase (2026-09-29): the identifier plausibility gate in the
LAFT PDF/HTML parsers, list_as_of extraction, and the FDOR enricher's new
rules - Hendry list-form normalization, ambiguous-match rejection, public-
log redaction and per-column provenance / precedence.

Pure unit tests; every request is faked (same contract as the rest of
tests/python/). Fixture values are synthetic; no production row value
appears here.
"""
from __future__ import annotations

import importlib.util
import io
import json
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
import harvest_cache  # noqa: E402
import harvest_laft_html as html_h  # noqa: E402
import harvest_laft_pdfs as pdf_h  # noqa: E402
import laft_status as ls  # noqa: E402

from test_laft_harvester_gates import _minimal_pdf  # noqa: E402

SCRIPT = REPO / "scripts" / "enrich_property_details.py"


# ==================== 1. identifier plausibility gate ====================


@pytest.mark.parametrize("value,kind,ok", [
    ("17E19S27 10000 005S", "parcel", True),
    ("0035260000", "parcel", True),
    ("2-01-43-29-010-0050-F020", "parcel", True),
    ("23-09 / Cert 15-2918", "case_no", True),
    ("512026XX000151TDAXXX", "case_no", True),
    ("IDNUMBER", "parcel", False),                       # Volusia wrapped heading
    ("CURRENTPURCHASEPRICE,C", "parcel", False),         # Volusia wrapped heading
    ("WNISTHEORIGINALOPENING", "parcel", False),         # Volusia wrapped note
    ("Account", "case_no", False),                        # Escambia second header line
    ("2. The", "case_no", True),                          # has a digit, short: gate is on the parcel of that row
    ("****2025XX000042TDAXXX" + "X" * 30, "parcel", False),  # over 40 chars
    ("12 34\n56", "parcel", False),
    ("", "parcel", False), (None, "parcel", False),
])
def test_g01_plausible_identifier_rule(value, kind, ok):
    assert ls.plausible_identifier(value, kind=kind) is ok


def test_g02_record_gate_rejects_on_either_identifier_and_ignores_absent_ones():
    assert ls.record_identifiers_plausible({"parcel": "0035260000"})
    assert ls.record_identifiers_plausible({"case_no": "2024-435"})
    assert not ls.record_identifiers_plausible({"case_no": "2024-435", "parcel": "IDNUMBER"})
    assert not ls.record_identifiers_plausible({"case_no": "Account"})
    assert ls.record_identifiers_plausible({"case_no": "2024-435", "parcel": ""})


def test_g03_pdf_table_rows_drop_heading_fragments_and_count_them():
    table = [
        ["Case Number", "Parcel ID", "Description", "Opening Bid"],
        ["", "ID NUMBER", "", ""],                                # wrapped heading second line
        ["2024-0001", "533874050071", "LOT 1", "$1,000"],
        ["", "CURRENT PURCHASE PRICE, C", "", ""],
    ]
    rejected: list = []
    rows = pdf_h._rows_from_table(table, "Volusia", "https://v", rejected)
    assert [r["parcel"] for r in rows] == ["533874050071"] and len(rejected) == 2


def test_g04_pdf_label_scanner_runaway_value_is_rejected_not_a_property():
    text = ("Tax Deed #: 2025-042 Parcel ID: 31-26-16-0120-00A00-0100 PA PASCO LONY SUB PB 5 PG 4 THE SOUTH 140.00 FT "
            "OF THE FOLLOWING DESC BEG AT SW COR OF LOT 9 BLOCK A TH ALG WLY BDY LINE " * 2)
    rejected: list = []
    rows = pdf_h.extract_label_value_rows(text, "Pasco", "https://p", rejected)
    assert rows == [] and rejected == [1, 1]   # two 'Tax Deed #' blocks, both rejected
    # The same scanner keeps a well-formed block.
    good = "Sale #: 1 Sale Date: 01/02/2026 Parcel #: 12345-000-00 Description: LOT 7"
    assert [r["parcel"] for r in pdf_h.extract_label_value_rows(good, "Marion", "https://m")] == ["12345-000-00"]


def test_g05_pdf_outcome_reports_rejected_and_list_as_of_and_main_treats_rejected_only_as_format_change():
    pdf = _minimal_pdf(["LIST OF LANDS AVAILABLE FOR TAXES as of 09/15/2026",
                        "Parcel ID: NOTANUMBERATALL Description: junk"])
    rows, outcome = pdf_h.extract_rows_with_outcome(pdf, "X", "https://x/list.pdf")
    assert rows == [] and outcome["rejected"] == 1 and outcome["empty_marker"] is False
    assert outcome["list_as_of"] == "2026-09-15"
    src = SCRIPT.parent.joinpath("harvest_laft_pdfs.py").read_text(encoding="utf-8")
    assert 'elif outcome.get("rejected"):' in src and '"PARSE_FORMAT_CHANGE"' in src
    assert src.index('elif outcome.get("rejected")') < src.index('"PARSE_NO_TABLE" if not outcome["table_seen"]')


def test_g06_html_second_header_line_is_rejected_and_real_rows_survive():
    html = b"""<table>
      <tr><td>Clerk's FileNumber</td><td>Parcel ID</td><td>Legal Description</td><td>Opening Bid</td></tr>
      <tr><td>Account</td><td>Number</td><td></td><td></td></tr>
      <tr><td>0226-64</td><td></td><td>BEG AT INTER OF W LI</td><td>$500.00</td></tr>
    </table>"""
    rows, outcome = html_h.extract_rows_with_outcome(html, "Escambia", "https://e")
    assert [r["case_no"] for r in rows] == ["0226-64"] and outcome["rejected"] == 1
    only_junk = b"""<table><tr><td>Case Number</td><td>Parcel ID</td></tr><tr><td>Account</td><td>Number</td></tr></table>"""
    rows2, outcome2 = html_h.extract_rows_with_outcome(only_junk, "E", "https://e")
    assert rows2 == [] and outcome2["rejected"] == 1 and outcome2["header_table_found"] is True
    src = SCRIPT.parent.joinpath("harvest_laft_html.py").read_text(encoding="utf-8")
    # rejected-only must be checked BEFORE the recognised-table-zero-rows EMPTY branch.
    assert src.index('elif outcome.get("rejected"):') < src.index('elif outcome["header_table_found"]:')


def test_g07_parser_version_bumped_so_cached_pre_gate_rows_are_reparsed():
    assert harvest_cache.PARSER_VERSION >= 2


# ==================== 2. list_as_of: the source's own date only ====================


@pytest.mark.parametrize("text,url,expected", [
    ("LANDS AVAILABLE FOR TAXES AS OF 09/15/2026", None, "2026-09-15"),
    ("List updated: 2026-09-15 by the Clerk", None, "2026-09-15"),
    ("Revised 9/1/2026", None, "2026-09-01"),
    ("no date here", "https://app.pascoclerk.com/x/List%20of%20Lands%20Available%20for%20Taxes%2020260706.pdf", "2026-07-06"),
    ("no date here", "https://app02.clerk.org/cm_rpt/lands/LandsAvailableForTaxes.pdf", None),
    ("as of 13/45/2026", "https://x/doc20261399.pdf", None),   # neither parses -> nothing
    (None, None, None),
])
def test_a01_extract_list_as_of(text, url, expected):
    assert ls.extract_list_as_of(text, url) == expected


def test_a02_status_entry_carries_list_as_of_and_never_a_retrieval_date(tmp_path):
    rec = ls.StatusRecorder("fl_laft_pdfs", source_class="GOVERNMENT_DIRECT", path=tmp_path / "s.json") \
        if "path" in ls.StatusRecorder.__init__.__code__.co_varnames else None
    if rec is None:
        pytest.skip("StatusRecorder has no path parameter")
    e = rec.complete("Pasco", 3, source_url="https://p", document_url="https://p/l.pdf", list_as_of="2026-07-06")
    assert e.to_json()["list_as_of"] == "2026-07-06"
    e2 = rec.complete("Volusia", 3, source_url="https://v")
    assert e2.to_json()["list_as_of"] is None


# ==================== 3. FDOR enricher ====================


@pytest.fixture()
def enrich(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://example.test")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "not-a-real-key")
    spec = importlib.util.spec_from_file_location("_gates_enrich", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_gates_enrich"] = mod
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod.time, "sleep", lambda *_: None)
    monkeypatch.setattr(mod.random, "randrange", lambda *_: 0)
    return mod


class FakeResponse:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status
        self.text = ""

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def test_f01_hendry_list_form_expands_to_the_verified_fdor_spelling(enrich):
    # The production pair (same clerk case, two rows): list form -> FDOR form.
    assert enrich._expand_hendry_list_form("2-01-43-29-010-0050-F020") == "2 29 43 01 010 0050-F02.0"
    assert "2 29 43 01 010 0050-F02.0" in enrich.normalize_candidates("2-01-43-29-010-0050-F020")
    # Any other shape: no candidate, no extra request.
    for other in ("1 33 44 31 A00 0180.0000", "12734 001 000", "0035260000", "02239-137", "31-26-16-0120-00A00-0100"):
        assert enrich._expand_hendry_list_form(other) is None
    # Numeric tail splits the same way (XXX.X).
    assert enrich._expand_hendry_list_form("4-29-43-10-020-2065-0300") == "4 10 43 29 020 2065-030.0"


def test_f02_more_than_one_layer_feature_is_ambiguous_and_never_taken(enrich, monkeypatch):
    seen = []

    def fake_get(url, headers=None, params=None, timeout=None):
        seen.append(params)
        return FakeResponse({"features": [{"attributes": {"PARCEL_ID": "A"}}, {"attributes": {"PARCEL_ID": "B"}}]})
    monkeypatch.setattr(enrich.requests, "get", fake_get)
    attrs, centroid, cand = enrich.lookup_fdor("Alachua", "12734 001 000")
    assert attrs is None and centroid is None and cand == enrich.AMBIGUOUS_MATCH
    assert seen and seen[0]["resultRecordCount"] == "2"


class Harness:
    def __init__(self, mod, monkeypatch, county, rows, *, layer):
        self.patches = []       # (row id, body)
        self.lookups = []

        def fake_get(url, headers=None, params=None, timeout=None):
            params = params or {}
            if "rest/v1/properties" in url:
                if params.get("select") == "county":
                    return FakeResponse([{"county": county} for _ in rows])
                if params.get("limit") == "0":
                    return FakeResponse([])
                assert "field_provenance" in params["select"], "main() must read field_provenance for precedence"
                return FakeResponse(rows[int(params["offset"]):int(params["offset"]) + int(params["limit"])])
            if url == mod.FDOR_ENDPOINT:
                cand = re.search(r"PARCEL_ID='([^']*)'", params["where"]).group(1)
                self.lookups.append(cand)
                outcome = layer.get(cand)
                if outcome == "error":
                    raise mod.requests.ConnectionError("boom " + cand)
                if outcome == "dup":
                    return FakeResponse({"features": [{"attributes": {}}, {"attributes": {}}]})
                if outcome:
                    return FakeResponse({"features": [{"attributes": outcome, "centroid": {"x": -82.0, "y": 28.5}}]})
                return FakeResponse({"features": []})
            raise AssertionError(f"unexpected GET {url}")

        def fake_patch(url, headers=None, json=None, timeout=None):
            self.patches.append((url.rsplit("eq.", 1)[1], json))
            return FakeResponse(None, status=204)

        monkeypatch.setattr(mod.requests, "get", fake_get)
        monkeypatch.setattr(mod.requests, "patch", fake_patch)


ROLL = {"PARCEL_ID": "x", "JV": 50000, "AV_NSD": 40000, "OWN_NAME": "ROLL OWNER", "S_LEGAL": "ROLL LEGAL", "LND_SQFOOT": 43560, "ASMNT_YR": 2025}


def test_f03_main_writes_provenance_respects_precedence_skips_ambiguous_and_redacts_logs(enrich, monkeypatch, capsys):
    rows = [
        # legal_desc already on file from the county list (provenanced) -> the roll's copy must not replace it;
        # owner_name blank -> filled; acreage (no entry) -> written.
        {"id": "r1", "source": "laft", "parcel": "HIT-1", "county": "Marion", "address": "Parcel HIT-1",
         "legal_desc": "LIST LEGAL", "field_provenance": {"legal_desc": {"source": "county_list", "recorded_at": "t"}}},
        {"id": "r2", "source": "laft", "parcel": "DUP-2", "county": "Marion", "address": "x"},   # ambiguous
        {"id": "r3", "source": "laft", "parcel": "ERR-3", "county": "Marion", "address": "x"},   # transport error
        {"id": "r4", "source": "laft", "parcel": "MISS-4", "county": "Marion", "address": "x"},  # no feature
    ]
    layer = {"HIT-1": ROLL, "DUP-2": "dup", "ERR-3": "error"}
    h = Harness(enrich, monkeypatch, "Marion", rows, layer=layer)
    enrich.main()
    out = capsys.readouterr()
    patched = dict(h.patches)
    assert set(patched) == {"r1"}
    body = patched["r1"]
    assert "legal_desc" not in body and body["owner_name"] == "ROLL OWNER" and body["acreage"] == 1.0
    prov = body["field_provenance"]
    assert prov["legal_desc"] == {"source": "county_list", "recorded_at": "t"}          # kept verbatim
    assert prov["owner_name"]["source"] == "fdor_nal" and prov["owner_name"]["matched_parcel_id"] == "HIT-1"
    assert prov["acreage"]["source"] == "fdor_nal" and "fdor_enriched_at" not in prov
    # Public log: counts and row ids, never a parcel number or a roll value.
    text = out.out + out.err
    for secret in ("HIT-1", "DUP-2", "ERR-3", "MISS-4", "ROLL OWNER", "ROLL LEGAL", "LIST LEGAL"):
        assert secret not in text, secret
    assert "ambiguous (skipped) 1" in text and "errored 1" in text and "unmatched 1" in text
    assert "matched 1, written 1" in text and "withheld by provenance precedence 1" in text


def test_f04_ambiguous_rows_are_not_stamped_and_do_not_count_toward_the_miss_streak(enrich, monkeypatch):
    rows = [{"id": f"d{i}", "source": "laft", "parcel": f"DUP-{i}", "county": "Marion", "address": "x"} for i in range(8)]
    rows.append({"id": "hit", "source": "laft", "parcel": "HIT-9", "county": "Marion", "address": "x"})
    layer = {f"DUP-{i}": "dup" for i in range(8)}
    layer["HIT-9"] = ROLL
    h = Harness(enrich, monkeypatch, "Marion", rows, layer=layer)
    enrich.main()
    assert [pid for pid, _ in h.patches] == ["hit"]   # the streak (6 misses) never abandoned the ledger
