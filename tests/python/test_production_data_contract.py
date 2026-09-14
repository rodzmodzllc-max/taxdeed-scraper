"""Phase 13 (Production Data Contract & Provenance Readiness Gate) tests.

Every test below reads a REAL repository file (Python source, SQL, or
YAML/JS text) and asserts something about its actual content, rather than
re-implementing a parallel model of the data contract that could silently
drift from the code it's meant to describe - the same anti-drift discipline
test_florida_sources_registered_for_state_agnostic_design_but_untouched
(Phase 10A) already established for the Florida/governance boundary. See
docs/production-data-contract.md for the full write-up each test group
below corresponds to (lettered sections A-J match that doc's Section 23).

No source is contacted, no schema is touched, no fixture invents facts not
already present in the repository.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from harvesters.governance import Provenance
from harvesters.texas_harvester import FIELD_LINEAGE_MAP, TexasSaleRow
from harvesters.governance.restrictions import FIELD_SHAPE_KEYWORDS

REPO_ROOT = Path(__file__).resolve().parents[2]


def _read(*parts: str) -> str:
    return (REPO_ROOT / Path(*parts)).read_text()


# ==================== A: Identity contract ====================


def test_A_identity_key_is_state_source_county_case_no():
    sql = _read("scripts", "migrations", "004_widen_unique_constraint_for_state.sql")
    assert "unique (state, source, county, case_no)" in sql
    # The narrower, pre-Phase-13 key must actually be dropped, not merely
    # superseded - otherwise both constraints would coexist and the wider
    # one would not actually prevent the FL/TX same-named-county collision
    # this migration exists to fix.
    assert "drop constraint if exists properties_source_county_case_no_key" in sql


def test_A_tx_account_number_is_the_identity_field_not_cause_number():
    sync_src = _read("scripts", "sync-texas-to-supabase.py")
    # case_no (the uniqueness-bearing column) must come from account_number.
    assert 'case_no = p.get("account_number")' in sync_src
    # cause_number must land in the secondary/display-only `parcel` column,
    # never in `case_no` - this is the exact distinction
    # harvest_lgbs()'s own live-verification finding (two parcels sharing
    # one cause number) exists to protect.
    assert '"parcel": p.get("cause_number") or None' in sync_src


def test_A_harris_reconnaissance_independently_confirms_the_same_uniqueness_pattern():
    """Not a live check against hctax.net (tx_hctax has no harvester and is
    not implemented - this phase does not activate it). This only confirms
    the DESIGN RATIONALE already shipped for tx_lgbs (account_number
    unique, cause_number not) is not invented for this project's Texas
    identity contract in isolation - texas_harvester.py's own module
    docstring cites a live LGBS sample finding two parcels sharing one
    cause number, which is the actual basis for the design under test
    above."""
    src = _read("harvesters", "texas_harvester.py")
    assert "cause_nbr" in src
    assert "account_number" in src
    # The rationale text itself, not just the field names, must still be
    # present - this is what a future maintainer would read to understand
    # WHY account_number was chosen over cause_number. (Wrapped across
    # source lines, so check for a phrase that survives the wrap rather
    # than one spanning the line break.)
    assert "routinely covers multiple" in src


# ==================== B: Field contract / canonical inventory ====================

_REQUIRED_CSV_COLUMNS = {
    "State", "County", "Source", "Address", "Parcel", "Case/Account #",
    "Status", "Opening Bid", "Sale/Auction Date",
}

# Internal-only columns (Section 6 of the contract doc) that the frontend's
# own code never renders or exports - if one of these ever appears in the
# CSV export's column list, the internal/customer-visible line this
# document draws has silently moved and the doc is now wrong.
_INTERNAL_ONLY_FIELDS = {"harvester_source", "ledger_type", "fdor_enriched_at"}


def _csv_export_block() -> str:
    app_js = _read("public", "app.js")
    start = app_js.index("const exportCsvBtn")
    end = app_js.index("csvEscape", start)
    return app_js[start:end]


def test_B_csv_export_contains_the_required_canonical_columns():
    block = _csv_export_block()
    for label in _REQUIRED_CSV_COLUMNS:
        assert f'"{label}"' in block, f"expected CSV column {label!r} not found in app.js's export cols array"


def test_B_internal_only_fields_never_appear_in_the_csv_export():
    block = _csv_export_block()
    for field in _INTERNAL_ONLY_FIELDS:
        assert field not in block, (
            f"{field!r} (documented as internal/not-customer-facing in "
            "docs/production-data-contract.md Section 6) appears in the CSV "
            "export column block - the customer/internal boundary has moved "
            "and the doc is now out of sync with the code"
        )


# ==================== C: Field-level lineage completeness ====================


def test_C_field_lineage_map_covers_every_content_field_of_texassalerow():
    # Structural fields (state/source/harvester_source) are not per-source
    # "content" - they're the row's own routing/classification metadata,
    # not something a source "publishes" in the FIELD_LINEAGE_MAP sense.
    structural = {"state", "source", "harvester_source"}
    content_fields = {f.name for f in TexasSaleRow.__dataclass_fields__.values()} - structural
    for harvester_source, mapping in FIELD_LINEAGE_MAP.items():
        mapped_fields = set(mapping.keys())
        missing = content_fields - mapped_fields
        assert not missing, (
            f"FIELD_LINEAGE_MAP[{harvester_source!r}] is missing an entry for "
            f"{missing} - TexasSaleRow gained a content field this map was "
            "never updated to document (see docs/production-data-contract.md "
            "Section 13)"
        )


# ==================== D: Null semantics ====================


def test_D_missing_tx_min_bid_becomes_a_zero_bid_sentinel_not_null():
    sync_src = _read("scripts", "sync-texas-to-supabase.py")
    assert "bid = min_bid if min_bid is not None else 0" in sync_src


def test_D_frontend_treats_a_zero_bid_as_not_published_not_free():
    app_js = _read("public", "app.js")
    assert 'const hasPublishedBid = p => p.bid !== null && p.bid !== undefined && Number(p.bid) > 0;' in app_js
    assert '"Not published"' in app_js


# ==================== E: Value semantics ====================


def test_E_market_column_is_never_written_by_the_texas_sync_path():
    sync_src = _read("scripts", "sync-texas-to-supabase.py")
    assert '"market"' not in sync_src, (
        "the TX sync script must never write `market` - market is FL-"
        "enrichment-only (see docs/production-data-contract.md Section 9); "
        "a `market` key appearing here would mean Texas rows can now get a "
        "'County Just Value' label they have never legitimately carried"
    )


def test_E_assessed_is_fill_blank_for_florida_but_unconditional_for_texas():
    fl_src = _read("scripts", "enrich_property_details.py")
    tx_src = _read("scripts", "sync-texas-to-supabase.py")
    # FL: only ever fills `assessed` when the row doesn't already have one.
    assert '_num(row.get("assessed")) is None' in fl_src
    # TX: writes `assessed` from cad_market_value on every row, unconditionally
    # - the exact asymmetry docs/production-data-contract.md Section 9/10
    # documents as a real, unresolved semantic collision (FL's AV_NSD vs.
    # TX's raw CAD "value"/RealAuction's "Adjudged Value" sharing one column).
    assert '"assessed": _num(p.get("cad_market_value"))' in tx_src


# ==================== F: Status contract ====================


def test_F_gone_statuses_and_the_not_currently_emitted_disclosure_are_both_present():
    app_js = _read("public", "app.js")
    assert 'const GONE_STATUSES = ["dropped", "sold", "notfound", "closed"];' in app_js
    # The frontend's own honest admission that most of GONE_STATUSES is
    # forward-looking, not actually emitted by any current harvester today
    # - if this comment is ever removed without the underlying gap being
    # closed, a future reader would wrongly assume all four values are real.
    assert "do not capture it yet" in app_js


# ==================== G: Restriction/provenance leak ====================


_SYNC_ROW_KEYS = {
    "state", "source", "county", "case_no", "parcel", "address", "bid",
    "min_bid", "assessed", "sale_date", "legal_desc", "harvester_source",
    "latitude", "longitude",
}


def test_G_the_real_sync_row_shape_is_inert_against_every_field_shape_keyword():
    """Extends Phase 11's TexasSaleRow-only inertness test to the actual
    dict shape scripts/sync-texas-to-supabase.py builds for the Supabase
    upsert - the real thing project_row_for_customer_output() is called
    against in production, not merely the dataclass it started from."""
    for restriction, keywords in FIELD_SHAPE_KEYWORDS.items():
        for key in _SYNC_ROW_KEYS:
            matched = [kw for kw in keywords if kw in key.lower()]
            assert not matched, (
                f"sync row key {key!r} matches field-shape keyword(s) {matched} "
                f"for {restriction} - a future APPROVED_WITH_RESTRICTIONS source "
                "carrying this restriction would now have a real field stripped, "
                "which the inertness claim in docs/production-data-contract.md "
                "Section 14 says does not happen today"
            )


def test_G_no_provenance_field_name_appears_in_the_csv_export():
    block = _csv_export_block()
    provenance_field_names = {f for f in Provenance.__dataclass_fields__.keys()}
    # A couple of Provenance's field names ("classification", "retrieved_at")
    # are generic enough that they legitimately collide with unrelated words
    # already in app.js (e.g. the word "classification" appearing nowhere
    # in this file is not actually guaranteed, and isn't the point here);
    # check only the field names that are distinctly Provenance-shaped and
    # would be a real, unambiguous leak if ever found in the CSV export.
    distinctive = {"is_source_provided", "derived_from"}
    assert distinctive <= provenance_field_names, "Provenance's shape changed - update this test's field list"
    for field_name in distinctive:
        assert field_name not in block


# ==================== H: Production reality ====================


def test_H_texas_harvest_job_is_manual_only_not_on_any_cron_schedule():
    workflow = _read(".github", "workflows", "harvest-and-sync.yml")
    texas_block_start = workflow.index("  texas:")
    next_job_start = workflow.index("\n  backup:", texas_block_start)
    texas_block = workflow[texas_block_start:next_job_start]
    assert "if: github.event_name == 'workflow_dispatch'" in texas_block
    # A schedule branch would look like `|| github.event.schedule ==` -
    # confirm that pattern is absent from the texas job's own `if:` line
    # specifically (not merely absent from the whole file, which also
    # contains schedule-gated jobs elsewhere).
    if_line = next(line for line in texas_block.splitlines() if line.strip().startswith("if:"))
    assert "github.event.schedule" not in if_line


def test_H_florida_deed_job_is_on_a_real_cron_schedule_for_contrast():
    workflow = _read(".github", "workflows", "harvest-and-sync.yml")
    assert "cron: '0 10 * * *'" in workflow
    assert "cron: '0 22 * * *'" in workflow
    deeds_start = workflow.index("\n  deeds:")
    next_job_start = workflow.index("\n  certificates:", deeds_start)
    deeds_block = workflow[deeds_start:next_job_start]
    if_line = next(line for line in deeds_block.splitlines() if line.strip().startswith("if:"))
    assert "github.event.schedule" in if_line


# ==================== I: API contract ====================


def test_I_digest_rpc_field_list_matches_its_own_sql_definition_and_edge_function_type():
    sql = _read("schema-v5-digest.sql")
    ts = _read("supabase", "functions", "send-digest", "index.ts")
    declared_sql_fields = {
        "user_id", "property_id", "county", "address", "case_no", "bid",
        "market", "sale_date", "url_auction", "days_out",
    }
    for field_name in declared_sql_fields:
        assert field_name in sql, f"digest_candidates() SQL no longer declares {field_name!r}"
        assert field_name in ts, f"send-digest's Row type no longer declares {field_name!r}"
    # The two must agree on count too, not just "each declared field is
    # present somewhere in the other file" - a genuinely new field added to
    # one but not the other would still pass the loop above if it happened
    # to share a substring with something already expected.
    row_type_start = ts.index("type Row = {")
    row_type_end = ts.index("};", row_type_start)
    row_type_block = ts[row_type_start:row_type_end]
    row_type_field_count = sum(1 for line in row_type_block.splitlines() if ":" in line)
    assert row_type_field_count == len(declared_sql_fields)


# ==================== J: FL field coverage (doc-sync, Florida side) ====================

_FL_ENRICHMENT_FIELDS = {
    "prop_type", "market", "assessed", "owner_name", "latitude", "longitude",
    "address", "homestead", "year_built", "living_area", "lot_sqft",
    "num_buildings", "land_value", "legal_desc", "last_sale_price",
    "last_sale_year", "value_year", "dor_use_code",
}


def test_J_every_documented_fl_enrichment_field_is_actually_written_by_the_enrichment_script():
    fl_src = _read("scripts", "enrich_property_details.py")
    build_fn_start = fl_src.index("def build_update_fields")
    build_fn_end = fl_src.index("\ndef main", build_fn_start)
    build_fn = fl_src[build_fn_start:build_fn_end]
    for field_name in _FL_ENRICHMENT_FIELDS:
        assert f'"{field_name}"' in build_fn, (
            f"docs/production-data-contract.md Section 5/21 attributes "
            f"{field_name!r} to FL enrichment, but build_update_fields() no "
            "longer writes it - the doc's field inventory has drifted from "
            "the actual enrichment code"
        )
