"""Tests for Phase 52 - expanding the FDOR enrichment field set.

The expansion itself is not the risky part. The risky part is that the
ArcGIS layer publishes 127 fields and describes none of them: every field's
`alias` is identical to its `name`, so the only thing the service tells you
about `DEL_VAL` is that it is spelled DEL_VAL. The FDOR 2025 NAL/SDF/NAP
User's Guide defines it as the "[r]eduction in just value resulting from the
deletion of improvements ... since the previous assessment" - a demolition
adjustment, not delinquent tax.

So the tests below are mostly about what must NOT happen:

  * DEL_VAL must never be requested or mapped, and no tax-amount column may
    be fed from this layer at all, because the NAL is a value roll and
    contains no tax amount of any kind.
  * A field the roll omits must never overwrite a stored value with NULL.
    Enrichment is additive; silence is not evidence.
  * Derived columns must be reachable only through the named derivation
    helpers, so nothing can quietly start presenting arithmetic as a figure
    the county reported.
  * The writer must tolerate a database that predates migration 009, because
    PostgREST rejects an entire PATCH over one unknown key - an expanded
    writer deployed early would not degrade, it would stop enriching
    everything, silently.

No network and no database anywhere in this file.
"""

from __future__ import annotations

import importlib.util
import pathlib
import re
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "enrich_property_details.py"
MIGRATION = REPO / "scripts" / "migrations" / "009_fdor_verified_field_expansion.sql"
PROVENANCE_DOC = REPO / "docs" / "fdor-field-provenance.md"


@pytest.fixture()
def enrich(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://example.test")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "not-a-real-key")
    spec = importlib.util.spec_from_file_location("_p52_enrich", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_p52_enrich"] = mod
    spec.loader.exec_module(mod)
    return mod


def requested_fields(mod):
    return set(mod.FDOR_OUT_FIELDS.split(","))


# A complete, realistic roll record. Values chosen so every derivation has a
# checkable answer: JV-LND_VAL = 180000, LND_SQFOOT/43560 = 0.25 acres.
FULL_ATTRS = {
    "PARCEL_ID": "00310012000",
    "ASMNT_YR": 2025,
    "PHY_ADDR1": "412 NW 5TH AVE", "PHY_CITY": "GAINESVILLE", "PHY_ZIPCD": "32601",
    "DOR_UC": 1, "PA_UC": "0100",
    "JV": 240000, "AV_NSD": 210000, "TV_NSD": 185000,
    "LND_VAL": 60000, "JV_HMSTD": 25000,
    "ACT_YR_BLT": 1958, "EFF_YR_BLT": 1998,
    "TOT_LVG_AR": 1840, "NO_BULDNG": 1, "NO_RES_UNT": 1,
    "LND_SQFOOT": 10890,
    "OWN_NAME": "DOE JANE", "S_LEGAL": "LOT 4 BLK 2 SPRINGHILL",
    "SALE_PRC1": 195000, "SALE_YR1": 2021, "SALE_MO1": 7,
    "QUAL_CD1": "01", "VI_CD1": "I",
    "OR_BOOK1": "04821", "OR_PAGE1": "0117", "CLERK_NO1": "2021-0099123",
    "SALE_PRC2": 88000, "SALE_YR2": 2004, "SALE_MO2": 3, "QUAL_CD2": "11",
    "ALT_KEY": "07731100",
}

EMPTY_ROW = {
    "id": "00000000-0000-0000-0000-000000000000",
    "parcel": "00310012000", "county": "Alachua", "address": "412 NW 5TH AVE",
    "prop_type": None, "market": None, "assessed": None, "owner_name": None,
    "latitude": None, "longitude": None,
}


# ---------------------------------------------------------------------------
# 1. The trap: DEL_VAL, and tax amounts generally
# ---------------------------------------------------------------------------

def test_p52_01_del_val_is_never_requested(enrich):
    assert "DEL_VAL" not in requested_fields(enrich)


def test_p52_02_del_val_appears_only_in_prose_explaining_its_exclusion():
    """DEL_VAL is allowed - required, really - in the comments, so the next
    reader finds out why it is missing instead of "fixing" the omission. It
    must not appear in a single line of executable code."""
    import io
    import tokenize

    source = SCRIPT.read_text(encoding="utf-8")
    offending = [
        token.string
        for token in tokenize.generate_tokens(io.StringIO(source).readline)
        if token.type not in (tokenize.COMMENT, tokenize.STRING)
        and "DEL_VAL" in token.string
    ]
    assert offending == [], offending


def test_p52_03_del_val_is_never_mapped_to_a_column():
    source = SCRIPT.read_text(encoding="utf-8")
    assert 'attrs.get("DEL_VAL")' not in source


def test_p52_04_no_tax_amount_column_is_written(enrich):
    """The NAL is a value roll. It has no billed tax, no taxes due and no
    delinquent tax, so these columns must never appear in a patch built from
    it - however tempting DEL_VAL's spelling is."""
    fields = enrich.build_update_fields(dict(EMPTY_ROW), dict(FULL_ATTRS), None)
    for column in ("annual_tax", "delinquent_tax", "tax_due", "taxes_owed"):
        assert column not in fields


def test_p52_05_no_bed_bath_zoning_subdivision_or_municipality(enrich):
    """Confirmed absent from the NAL layout. NO_RES_UNT is units, not
    bedrooms, and NBRHD_CD is a county code, not a subdivision name."""
    fields = enrich.build_update_fields(dict(EMPTY_ROW), dict(FULL_ATTRS), None)
    for column in ("beds", "baths", "zoning", "subdivision", "municipality"):
        assert column not in fields


def test_p52_06_nbrhd_cd_is_not_requested_as_a_subdivision(enrich):
    assert "NBRHD_CD" not in requested_fields(enrich)


# ---------------------------------------------------------------------------
# 2. The verified mappings
# ---------------------------------------------------------------------------

EXPECTED = {
    "taxable_value": 185000,
    "land_use": "0100",
    "effective_year_built": 1998,
    "num_res_units": 1,
    "last_sale_month": 7,
    "last_sale_qual_code": "01",
    "last_sale_vi_code": "I",
    "last_sale_or_book": "04821",
    "last_sale_or_page": "0117",
    "last_sale_clerk_no": "2021-0099123",
    "prior_sale_price": 88000,
    "prior_sale_year": 2004,
    "prior_sale_month": 3,
    "prior_sale_qual_code": "11",
    "fdor_alt_key": "07731100",
}


@pytest.mark.parametrize("column,expected", sorted(EXPECTED.items()))
def test_p52_07_verified_field_maps_to_its_column(enrich, column, expected):
    fields = enrich.build_update_fields(dict(EMPTY_ROW), dict(FULL_ATTRS), None)
    assert fields[column] == expected


def test_p52_08_taxable_is_not_assessed(enrich):
    """TV_NSD is post-exemption, AV_NSD is pre-exemption, and the gap between
    them is the exemption the homestead feature is about. Collapsing them
    would corrupt that."""
    fields = enrich.build_update_fields(dict(EMPTY_ROW), dict(FULL_ATTRS), None)
    assert fields["taxable_value"] == 185000
    assert fields["assessed"] == 210000


def test_p52_09_county_use_code_is_kept_beside_the_state_one(enrich):
    """PA_UC is county-defined and not comparable across counties; DOR_UC is
    state-defined and is. Storing only one of them loses a real distinction."""
    fields = enrich.build_update_fields(dict(EMPTY_ROW), dict(FULL_ATTRS), None)
    assert fields["land_use"] == "0100"
    assert fields["dor_use_code"] == "01"


def test_p52_10_effective_year_is_separate_from_actual_year(enrich):
    fields = enrich.build_update_fields(dict(EMPTY_ROW), dict(FULL_ATTRS), None)
    assert fields["year_built"] == 1958
    assert fields["effective_year_built"] == 1998


def test_p52_11_clerk_lookup_key_is_complete(enrich):
    """Book, page and instrument number are only useful together - they are
    one lookup key into the clerk's official records, not three facts."""
    fields = enrich.build_update_fields(dict(EMPTY_ROW), dict(FULL_ATTRS), None)
    assert {"last_sale_or_book", "last_sale_or_page", "last_sale_clerk_no"} <= set(fields)


# ---------------------------------------------------------------------------
# 3. Derivations are derivations
# ---------------------------------------------------------------------------

def test_p52_12_improvement_value_is_jv_minus_land(enrich):
    assert enrich.improvement_value_from(FULL_ATTRS) == 180000


def test_p52_13_improvement_value_needs_both_inputs(enrich):
    assert enrich.improvement_value_from({"JV": 240000}) is None
    assert enrich.improvement_value_from({"LND_VAL": 60000}) is None


def test_p52_14_improvement_value_is_never_zero_or_negative(enrich):
    """Land value at or above just value is a vacant parcel or a roll quirk,
    not an improvement figure worth showing."""
    assert enrich.improvement_value_from({"JV": 60000, "LND_VAL": 60000}) is None
    assert enrich.improvement_value_from({"JV": 50000, "LND_VAL": 60000}) is None


def test_p52_15_acreage_is_a_unit_conversion(enrich):
    assert enrich.acreage_from({"LND_SQFOOT": 10890}) == 0.25
    assert enrich.acreage_from({"LND_SQFOOT": 43560}) == 1.0


def test_p52_16_acreage_absent_without_square_footage(enrich):
    assert enrich.acreage_from({}) is None
    assert enrich.acreage_from({"LND_SQFOOT": 0}) is None


def test_p52_17_derived_columns_are_documented_as_derived():
    """If these stop being labelled, the UI can start presenting arithmetic as
    a number the county reported."""
    sql = MIGRATION.read_text(encoding="utf-8")
    assert "DERIVED, not a source field" in sql
    assert "JV - LND_VAL" in sql
    assert "LND_SQFOOT / 43560" in sql


# ---------------------------------------------------------------------------
# 4. Additive only - silence never becomes NULL
# ---------------------------------------------------------------------------

def test_p52_18_absent_source_fields_write_nothing(enrich):
    """A roll record carrying only a parcel id must not produce a patch that
    nulls out everything a fuller record wrote last month."""
    fields = enrich.build_update_fields(
        dict(EMPTY_ROW), {"PARCEL_ID": "00310012000"}, None
    )
    assert all(value is not None for value in fields.values())
    for column in EXPECTED:
        assert column not in fields


def test_p52_19_no_patch_value_is_ever_none(enrich):
    """The invariant behind additive enrichment, stated directly: None never
    reaches the patch body, so PostgREST is never asked to write NULL."""
    sparse = {"PARCEL_ID": "x", "JV": 100000, "SALE_YR1": 0, "QUAL_CD1": "  "}
    fields = enrich.build_update_fields(dict(EMPTY_ROW), sparse, None)
    assert None not in fields.values()


def test_p52_20_zero_and_blank_sentinels_do_not_become_values(enrich):
    """FDOR uses 0/blank as its no-data sentinel throughout. A stored 0 book
    number or a 0 sale month would be worse than an empty column."""
    attrs = dict(FULL_ATTRS)
    attrs.update({
        "SALE_MO1": 0, "QUAL_CD1": "", "VI_CD1": "   ",
        "OR_BOOK1": 0, "ALT_KEY": "0", "TV_NSD": 0,
    })
    fields = enrich.build_update_fields(dict(EMPTY_ROW), attrs, None)
    for column in (
        "last_sale_month", "last_sale_qual_code", "last_sale_vi_code",
        "last_sale_or_book", "fdor_alt_key", "taxable_value",
    ):
        assert column not in fields


def test_p52_21_code_fields_keep_their_leading_zeros(enrich):
    """Book numbers and use codes are identifiers, not quantities. '0117'
    parsed as an int and back is '117', which is a different page."""
    fields = enrich.build_update_fields(dict(EMPTY_ROW), dict(FULL_ATTRS), None)
    assert fields["last_sale_or_page"] == "0117"
    assert fields["land_use"] == "0100"


def test_p52_22_integral_floats_do_not_grow_a_decimal_tail(enrich):
    """ArcGIS returns 3.0 for integer-typed columns often enough that '3.0'
    would otherwise end up stored as a clerk instrument number."""
    assert enrich._code(3.0) == "3"
    assert enrich._code(4821.0) == "4821"


def test_p52_23_out_of_range_months_are_dropped_not_stored(enrich):
    """The database CHECKs 1-12. A 13 would fail the whole row's patch and
    cost that property every other field with it."""
    assert enrich._month(13) is None
    assert enrich._month(0) is None
    assert enrich._month(7) == 7


# ---------------------------------------------------------------------------
# 5. Sale ordering
# ---------------------------------------------------------------------------

def test_p52_24_prior_sale_newer_than_last_sale_is_dropped(enrich):
    """FDOR orders sales most-recent-first. A record that violates it is an
    anomaly - and losing the prior sale is far cheaper than losing the whole
    patch to a CHECK violation."""
    attrs = dict(FULL_ATTRS)
    attrs["SALE_YR2"] = 2023  # newer than SALE_YR1 = 2021
    fields = enrich.build_update_fields(dict(EMPTY_ROW), attrs, None)
    assert "prior_sale_price" not in fields
    assert "prior_sale_year" not in fields
    assert fields["last_sale_year"] == 2021


def test_p52_25_equal_years_are_allowed(enrich):
    attrs = dict(FULL_ATTRS)
    attrs["SALE_YR2"] = 2021
    fields = enrich.build_update_fields(dict(EMPTY_ROW), attrs, None)
    assert fields["prior_sale_year"] == 2021


# ---------------------------------------------------------------------------
# 6. Schema tolerance - the writer must survive its own migration being late
# ---------------------------------------------------------------------------

def test_p52_26_every_new_column_is_declared_optional(enrich):
    """A column in the patch that is neither pre-existing nor listed in
    OPTIONAL_COLUMNS is one that would hard-fail every PATCH on a database
    that has not run migration 009."""
    fields = enrich.build_update_fields(dict(EMPTY_ROW), dict(FULL_ATTRS), None)
    pre_existing = {
        "prop_type", "market", "assessed", "owner_name", "latitude", "longitude",
        "address", "homestead", "year_built", "living_area", "lot_sqft",
        "num_buildings", "land_value", "legal_desc", "last_sale_price",
        "last_sale_year", "value_year", "dor_use_code",
    }
    for column in fields:
        assert column in pre_existing or column in enrich.OPTIONAL_COLUMNS, column


def test_p52_27_unavailable_columns_are_dropped_from_the_patch(enrich, monkeypatch):
    monkeypatch.setattr(enrich, "_available_optional_columns", frozenset({"taxable_value"}))
    kept = enrich.drop_unavailable_columns({
        "market": 1, "taxable_value": 2, "fdor_alt_key": "x", "acreage": 0.25,
    })
    assert kept == {"market": 1, "taxable_value": 2}


def test_p52_28_base_columns_are_never_dropped(enrich, monkeypatch):
    """Only the optional set is ever filtered. A base column going missing is
    a real fault and must fail loudly rather than be swallowed."""
    monkeypatch.setattr(enrich, "_available_optional_columns", frozenset())
    kept = enrich.drop_unavailable_columns({"market": 1, "year_built": 1958})
    assert kept == {"market": 1, "year_built": 1958}


def test_p52_29_probe_is_memoised(enrich, monkeypatch):
    calls = []

    def fake_exists(column):
        calls.append(column)
        return True

    monkeypatch.setattr(enrich, "_available_optional_columns", None)
    monkeypatch.setattr(enrich, "_column_exists", fake_exists)
    enrich.available_optional_columns()
    enrich.available_optional_columns()
    assert len(calls) == 1  # one batched probe, then cached


def test_p52_30_probe_falls_back_to_per_column(enrich, monkeypatch):
    monkeypatch.setattr(enrich, "_available_optional_columns", None)
    monkeypatch.setattr(
        enrich, "_column_exists", lambda column: column == "taxable_value"
    )
    assert enrich.available_optional_columns() == frozenset({"taxable_value"})


def test_p52_31_patch_with_nothing_writable_makes_no_request(enrich, monkeypatch):
    monkeypatch.setattr(enrich, "_available_optional_columns", frozenset())

    def explode(*args, **kwargs):
        raise AssertionError("no HTTP request should be made for an empty patch")

    monkeypatch.setattr(enrich.requests, "patch", explode)
    enrich.patch_property("some-id", {"fdor_alt_key": "x"})


# ---------------------------------------------------------------------------
# 7. ALT_KEY stays a hypothesis
# ---------------------------------------------------------------------------

def test_p52_32_alt_key_is_stored_under_its_own_name(enrich):
    """Naming it tax_collector_account would assert something the FDOR guide
    does not say, in a column name, permanently."""
    fields = enrich.build_update_fields(dict(EMPTY_ROW), dict(FULL_ATTRS), None)
    assert "fdor_alt_key" in fields
    assert not any(
        "tax_collector" in column or "taxcoll_account" in column for column in fields
    )


def test_p52_33_alt_key_hypothesis_is_recorded_as_unvalidated():
    doc = PROVENANCE_DOC.read_text(encoding="utf-8")
    assert "unvalidated" in doc.lower()
    assert "ALT_KEY" in doc


# ---------------------------------------------------------------------------
# 8. Migration hygiene
# ---------------------------------------------------------------------------

def test_p52_34_migration_is_transactional():
    sql = MIGRATION.read_text(encoding="utf-8")
    body = "\n".join(
        line for line in sql.splitlines() if not line.strip().startswith("--")
    ).strip()
    assert body.startswith("begin;")
    assert body.rstrip().endswith("commit;")


def test_p52_35_migration_is_idempotent():
    """It must be applicable before, after or without migration 007, which is
    on a separate unmerged branch."""
    sql = MIGRATION.read_text(encoding="utf-8")
    adds = re.findall(r"alter table public\.properties add column\s+(\S+)", sql)
    assert adds, "expected add column statements"
    assert all(token == "if" for token in adds), adds
    for constraint in re.findall(r"add constraint (\S+)", sql):
        assert f"drop constraint if exists {constraint}" in sql


def test_p52_36_every_mapped_field_is_actually_requested(enrich):
    """A column mapped from a field the query does not ask for silently never
    populates - the failure mode is an empty column, not an error."""
    source = SCRIPT.read_text(encoding="utf-8")
    start = source.index("def build_update_fields")
    body = source[start:source.index("\ndef ", start + 10)]
    used = set(re.findall(r'attrs\.get\("([A-Z0-9_]+)"\)', body))
    used |= {"JV", "LND_VAL", "LND_SQFOOT"}  # read inside the derivation helpers
    assert used <= requested_fields(enrich), used - requested_fields(enrich)


def test_p52_37_provenance_doc_covers_every_new_column(enrich):
    doc = PROVENANCE_DOC.read_text(encoding="utf-8")
    for column in enrich.OPTIONAL_COLUMNS:
        assert column in doc, column
