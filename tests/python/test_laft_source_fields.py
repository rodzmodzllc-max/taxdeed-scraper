"""scripts/laft_source_fields.py + scripts/field_provenance.py - the
county-list -> properties fill-blank carry and the per-column provenance /
precedence rule. Pure unit tests; the end-to-end run lives in
test_laft_lifecycle.py (test_e04 / test_e05).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
import field_provenance as FP  # noqa: E402
import laft_lifecycle as L  # noqa: E402
import laft_source_fields as SF  # noqa: E402

ALL = list(SF.ALL_COLUMNS)
BASE = list(SF.BASE_COLUMNS)


def _obs(*rows):
    out: dict = {}
    for r in rows:
        out.setdefault(r["county"], {})[r["case_no"]] = r
    return out


def _db(*rows):
    return [dict(r) for r in rows]


# ==================== 1. matching: identity only ====================


def test_m01_exact_identity_match_writes_only_blank_columns():
    updates, c = SF.plan_source_fields(
        _obs({"county": "Marion", "case_no": "2024-001", "legal_desc": "LOT 1", "owner_name": "X"}),
        _db({"id": "a", "county": "Marion", "case_no": "2024-001", "owner_name": "Already Here"}), ALL)
    assert [(u.id, u.fields) for u in updates] == [("a", {"legal_desc": "LOT 1"})]
    assert c.matched == 1 and c.skipped_present == {"owner_name": 1} and c.fields_written == {}


def test_m02_leading_zeros_and_punctuation_are_part_of_the_key_never_normalized_away():
    updates, c = SF.plan_source_fields(
        _obs({"county": "Marion", "case_no": "0042", "legal_desc": "L"}),
        _db({"id": "a", "county": "Marion", "case_no": "42"}, {"id": "b", "county": "Marion", "case_no": "42-0"}), ALL)
    assert updates == [] and c.unmatched == 1 and c.matched == 0


def test_m03_no_cross_county_match_even_for_an_identical_case_number():
    updates, c = SF.plan_source_fields(
        _obs({"county": "Marion", "case_no": "A1", "legal_desc": "L"}),
        _db({"id": "z", "county": "Polk", "case_no": "A1"}), ALL)
    assert updates == [] and c.unmatched == 1


def test_m04_ambiguous_duplicate_database_rows_are_rejected_untouched():
    updates, c = SF.plan_source_fields(
        _obs({"county": "Marion", "case_no": "A1", "legal_desc": "L"}),
        _db({"id": "x", "county": "Marion", "case_no": "A1"}, {"id": "y", "county": "Marion", "case_no": "A1"}), ALL)
    assert updates == [] and c.ambiguous == 1 and c.matched == 0


def test_m05_unmatched_harvest_rows_change_nothing_and_are_counted():
    updates, c = SF.plan_source_fields(
        _obs({"county": "Marion", "case_no": "NEW", "legal_desc": "L"}), _db(), ALL)
    assert updates == [] and c.to_json()["unmatched"] == 1


# ==================== 2. value rules ====================


@pytest.mark.parametrize("raw,expected", [("$12,500", 12500.0), ("12500.50", 12500.5), ("0", None), ("$0.00", None), ("n/a", None), ("", None), (None, None)])
def test_v01_assessed_is_positive_number_or_nothing(raw, expected):
    assert SF.parse_positive_number(raw) == expected


@pytest.mark.parametrize("raw,expected", [("Y", True), ("yes", True), ("X", True), ("Homestead", True), ("N", None), ("no", None), ("", None), (False, None)])
def test_v02_homestead_is_yes_or_nothing_never_false(raw, expected):
    assert SF.parse_yes(raw) is expected


@pytest.mark.parametrize("raw,expected", [("07/01/2029", "2029-07-01"), ("7/1/2029", "2029-07-01"), ("2026-09-01", "2026-09-01"),
                                          ("07-01-2029", "2029-07-01"), ("July 1 2029", None), ("13/40/2029", None), ("", None)])
def test_v03_dates_parse_deterministically_or_not_at_all(raw, expected):
    assert SF.parse_date(raw) == expected


def test_v04_unparseable_cells_are_counted_and_never_coerced():
    updates, c = SF.plan_source_fields(
        _obs({"county": "Marion", "case_no": "A", "assessed": "unknown", "escheatment_date": "TBD", "homestead": "N", "legal_desc": "  LOT 1   BLK 2 "}),
        _db({"id": "a", "county": "Marion", "case_no": "A"}), ALL)
    assert updates[0].fields == {"legal_desc": "LOT 1 BLK 2"}
    assert c.unparseable == {"assessed": 1, "escheatment_date": 1}
    assert "homestead" not in c.unparseable  # a plain "N" is not an error, it is nothing to write


def test_v05_homestead_true_on_file_is_present_false_is_blank():
    updates, _ = SF.plan_source_fields(
        _obs({"county": "M", "case_no": "1", "homestead": "Y"}, {"county": "M", "case_no": "2", "homestead": "Y"}),
        _db({"id": "1", "county": "M", "case_no": "1", "homestead": False}, {"id": "2", "county": "M", "case_no": "2", "homestead": True}), ALL)
    assert [(u.id, u.fields) for u in updates] == [("1", {"homestead": True})]


def test_v06_optional_019_columns_are_never_planned_when_unavailable():
    updates, c = SF.plan_source_fields(
        _obs({"county": "M", "case_no": "1", "escheatment_date": "07/01/2029", "available_date": "07/01/2026"}),
        _db({"id": "1", "county": "M", "case_no": "1"}), BASE)
    assert updates == [] and c.nothing_to_write == 1 and c.unparseable == {}


# ==================== 3. provenance + precedence ====================


def test_p01_patch_body_merges_provenance_and_keeps_other_columns_entries():
    gate = {"harvester": "fl_laft_pdfs", "status": "COMPLETE",
            "entry": {"source_id": "fl_laft_pdfs", "source_url": "https://m/page", "document_url": "https://m/l.pdf",
                      "document_sha256": "abc", "list_as_of": "2026-09-15", "checked_at": "2026-09-29T10:00:00+00:00"}}
    u = SF.RowUpdate(id="a", county="Marion", case_no="A", fields={"owner_name": "X"},
                     existing_provenance={"acreage": {"source": "fdor_nal", "recorded_at": "t"}})
    body = SF.patch_body(u, gate, "2026-09-29T12:00:00+00:00")
    assert body["owner_name"] == "X"
    assert body["field_provenance"]["acreage"] == {"source": "fdor_nal", "recorded_at": "t"}
    assert body["field_provenance"]["owner_name"] == {
        "source": "county_list", "recorded_at": "2026-09-29T12:00:00+00:00", "source_id": "fl_laft_pdfs",
        "list_url": "https://m/page", "document_url": "https://m/l.pdf", "document_sha256": "abc",
        "list_as_of": "2026-09-15", "retrieved_at": "2026-09-29T10:00:00+00:00"}
    json.dumps(body)  # serialisable as sent


def test_p02_precedence_blank_fills_equal_rank_never_overwrites_hand_research_wins():
    prov = {"legal_desc": {"source": "county_list"}, "owner_name": {"source": "hand_research"}}
    assert FP.may_write(prov, "acreage", "fdor_nal", None) is True
    assert FP.may_write(prov, "legal_desc", "fdor_nal", "LOT 1") is False      # equal rank
    assert FP.may_write(prov, "legal_desc", "hand_research", "LOT 1") is True  # stronger
    assert FP.may_write(prov, "owner_name", "county_list", "Someone") is False # weaker
    assert FP.may_write(None, "owner_name", "county_list", "Someone") is False # unprovenanced value: equal rank


def test_p03_filter_by_provenance_blocks_only_provenanced_equal_or_stronger_values():
    row = {"legal_desc": "LIST LEGAL", "acreage": 1.5, "owner_name": "O",
           "field_provenance": {"legal_desc": {"source": "county_list"}, "owner_name": {"source": "vendor_listing"}}}
    fields = {"legal_desc": "ROLL LEGAL", "acreage": 2.0, "owner_name": "Roll Owner", "year_built": 1990}
    kept = FP.filter_by_provenance(row, fields, "fdor_nal")
    # legal_desc: county_list (rank 2) vs fdor_nal (rank 2) -> blocked.
    # acreage: no entry -> the writer's own rule decides -> kept.
    # owner_name: vendor_listing (rank 1) < fdor_nal (2) -> replaced.
    assert kept == {"acreage": 2.0, "owner_name": "Roll Owner", "year_built": 1990}


def test_p04_provenance_entries_reject_unknown_sources_and_drop_none_metadata():
    with pytest.raises(ValueError):
        FP.provenance_entry("search_engine")
    e = FP.provenance_entry("fdor_nal", recorded_at="t", matched_parcel_id="X", list_url=None)
    assert e == {"source": "fdor_nal", "recorded_at": "t", "matched_parcel_id": "X"}
    with pytest.raises(ValueError):
        FP.merge_field_provenance({}, {"x": {"source": "guess"}})


def test_p05_load_provenance_tolerates_legacy_text_and_garbage():
    assert FP.load_provenance('{"a": {"source": "fdor_nal"}}') == {"a": {"source": "fdor_nal"}}
    assert FP.load_provenance("not json") == {} and FP.load_provenance(None) == {} and FP.load_provenance([1]) == {}


# ==================== 4. currentness from the source's own statements ====================


@pytest.mark.parametrize("raw,expected", [
    ("Tue, 15 Sep 2026 14:03:00 GMT", "2026-09-15T14:03:00+00:00"),
    ("Tue, 15 Sep 2026 10:03:00 -0400", "2026-09-15T14:03:00+00:00"),
    ("yesterday", None), ("", None), (None, None)])
def test_c01_source_published_at_is_the_documents_last_modified_or_nothing(raw, expected):
    assert L.published_at_from_last_modified(raw) == expected


def test_c02_provenance_payload_carries_list_as_of_and_published_at_never_retrieval_time():
    gate = {"harvester": "fl_laft_pdfs", "entry": {"source_url": "https://m", "source_class": "GOVERNMENT_DIRECT",
                                                   "list_as_of": "2026-09-15", "document_last_modified": "Tue, 15 Sep 2026 14:03:00 GMT"}}
    p = L.provenance_payload({"county": "Marion", "case_no": "A"}, gate, "2026-09-29T00:00:00+00:00")
    assert p["list_as_of"] == "2026-09-15" and p["source_published_at"] == "2026-09-15T14:03:00+00:00"
    p2 = L.provenance_payload({"county": "Marion", "case_no": "A"}, {"harvester": "h", "entry": {}}, "2026-09-29T00:00:00+00:00")
    assert p2["list_as_of"] is None and p2["source_published_at"] is None
    assert "not stated" in p2["otc_provenance"]["list_as_of"]


# ==================== 5. logs carry counts only ====================


def test_l01_summary_names_columns_and_counts_never_values():
    updates, c = SF.plan_source_fields(
        _obs({"county": "Marion", "case_no": "A", "owner_name": "Private Person", "legal_desc": "LOT 99 SECRET"}),
        _db({"id": "a", "county": "Marion", "case_no": "A"}), ALL)

    class Api:
        dry_run = True

        def patch(self, q, body):
            pass
    SF.execute_source_fields(Api(), updates, {"Marion": {"harvester": "h", "entry": {}}}, "t", c)
    text = SF.summarize(c, ALL) + json.dumps(c.to_json())
    assert "Private Person" not in text and "SECRET" not in text and "rows written 1" in text
    assert "owner_name 1" in text and "legal_desc 1" in text
