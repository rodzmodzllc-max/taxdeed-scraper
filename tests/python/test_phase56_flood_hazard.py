"""Tests for the FEMA flood-hazard enrichment.

The whole risk of this feature is one distinction. A FEMA point query has
three outcomes, not two:

    a feature comes back  -> that is the flood zone
    zero features         -> FEMA HAS NO MAP covering this point
    the request failed    -> we learned nothing

"FEMA does not map this parcel" is not "FEMA mapped it and found minimal
hazard." A pipeline that wrote NULL for both would let the UI render an
unmapped rural parcel as low risk, on the screen where someone commits money.
Most of this file exists to keep those three apart.

No network and no database.
"""

from __future__ import annotations

import importlib.util
import pathlib
import re
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "enrich_flood_zone.py"
MIGRATION = REPO / "scripts" / "migrations" / "010_flood_hazard.sql"


@pytest.fixture()
def flood(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://example.test")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "not-a-real-key")
    spec = importlib.util.spec_from_file_location("_p56_flood", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_p56_flood"] = mod
    spec.loader.exec_module(mod)
    return mod


# A real response shape, from the live Alachua parcel at 29.660087, -82.301424.
ALACHUA_X = {
    "FLD_ZONE": "X",
    "ZONE_SUBTY": "AREA OF MINIMAL FLOOD HAZARD",
    "SFHA_TF": "F",
    "DFIRM_ID": "12001C",
    "STATIC_BFE": -9999.0,
}

AE_ZONE = {
    "FLD_ZONE": "AE",
    "ZONE_SUBTY": None,
    "SFHA_TF": "T",
    "DFIRM_ID": "12086C",
    "STATIC_BFE": 9.0,
}


# ---------------------------------------------------------------------------
# 1. Unmapped is not low risk
# ---------------------------------------------------------------------------

def test_p56_01_no_feature_is_recorded_as_unmapped_not_null(flood):
    fields = flood.build_update_fields(None, checked_at="2026-09-17T00:00:00Z")
    assert fields["flood_zone"] == "UNMAPPED"


def test_p56_02_unmapped_never_claims_an_sfha_answer(flood):
    """FEMA made no determination. False would be a positive claim that the
    parcel is NOT in a Special Flood Hazard Area."""
    fields = flood.build_update_fields(None, checked_at="2026-09-17T00:00:00Z")
    assert "flood_sfha" not in fields


def test_p56_03_unmapped_is_not_spelled_like_a_real_zone(flood):
    """Zone letters are single letters or short codes (X, A, AE, VE). The
    sentinel must not be mistakable for one."""
    fields = flood.build_update_fields(None, checked_at="2026-09-17T00:00:00Z")
    assert fields["flood_zone"] == "UNMAPPED"
    assert len(fields["flood_zone"]) > 4


def test_p56_04_unmapped_still_stamps_a_check(flood):
    """It IS a finding - it stops the row being retried forever."""
    fields = flood.build_update_fields(None, checked_at="2026-09-17T00:00:00Z")
    assert fields["flood_checked_at"] == "2026-09-17T00:00:00Z"


def test_p56_05_database_forbids_an_sfha_answer_on_an_unmapped_row():
    sql = MIGRATION.read_text(encoding="utf-8")
    assert "properties_flood_unmapped_has_no_sfha" in sql
    assert "flood_sfha is null" in sql


# ---------------------------------------------------------------------------
# 2. A failed request writes nothing
# ---------------------------------------------------------------------------

def test_p56_06_transport_failure_is_not_a_finding(flood, monkeypatch):
    def boom(*a, **k):
        raise flood.requests.RequestException("network down")
    monkeypatch.setattr(flood.requests, "get", boom)
    attrs, ok = flood.lookup_flood_zone(29.66, -82.30)
    assert ok is False and attrs is None


def test_p56_07_arcgis_error_envelope_is_a_failure_not_an_unmapped_point(flood, monkeypatch):
    """ArcGIS reports failures inside a 200 body. Reading that as "no features"
    would stamp a finding onto a row we learned nothing about."""
    class Resp:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return {"error": {"code": 500, "message": "boom"}}
    monkeypatch.setattr(flood.requests, "get", lambda *a, **k: Resp())
    attrs, ok = flood.lookup_flood_zone(29.66, -82.30)
    assert ok is False and attrs is None


def test_p56_08_zero_features_is_a_success_meaning_unmapped(flood, monkeypatch):
    class Resp:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return {"features": []}
    monkeypatch.setattr(flood.requests, "get", lambda *a, **k: Resp())
    attrs, ok = flood.lookup_flood_zone(29.66, -82.30)
    assert ok is True and attrs is None


# ---------------------------------------------------------------------------
# 3. The real mapped cases
# ---------------------------------------------------------------------------

def test_p56_09_zone_x_maps_correctly(flood):
    f = flood.build_update_fields(ALACHUA_X, checked_at="T")
    assert f["flood_zone"] == "X"
    assert f["flood_zone_subtype"] == "AREA OF MINIMAL FLOOD HAZARD"
    assert f["flood_sfha"] is False
    assert f["flood_firm_id"] == "12001C"


def test_p56_10_zone_ae_is_inside_an_sfha(flood):
    f = flood.build_update_fields(AE_ZONE, checked_at="T")
    assert f["flood_zone"] == "AE"
    assert f["flood_sfha"] is True
    assert f["flood_bfe"] == 9.0


def test_p56_11_fema_bfe_sentinel_is_never_stored(flood):
    """-9999 feet is not an elevation. Storing it would put a nonsense number
    on a bid screen."""
    f = flood.build_update_fields(ALACHUA_X, checked_at="T")
    assert "flood_bfe" not in f
    assert flood.bfe_value(-9999.0) is None
    assert flood.bfe_value(9.0) == 9.0


def test_p56_12_sfha_flag_parses_fema_t_and_f(flood):
    assert flood.sfha_to_bool("T") is True
    assert flood.sfha_to_bool("F") is False


def test_p56_13_unrecognized_sfha_value_is_unknown_not_false(flood):
    """False is a positive claim. An unexpected code must not become one."""
    for raw in (None, "", "   ", "?", "MAYBE", "0"):
        assert flood.sfha_to_bool(raw) is None


def test_p56_14_mapped_polygon_with_no_zone_string_is_treated_as_unmapped(flood):
    f = flood.build_update_fields({"FLD_ZONE": "  ", "SFHA_TF": "T"}, checked_at="T")
    assert f["flood_zone"] == "UNMAPPED"
    assert "flood_sfha" not in f


# ---------------------------------------------------------------------------
# 4. The value/checked_at pairing, which is migration 007's rule
# ---------------------------------------------------------------------------

def test_p56_15_every_write_carries_a_checked_at(flood):
    for attrs in (None, ALACHUA_X, AE_ZONE):
        assert "flood_checked_at" in flood.build_update_fields(attrs, checked_at="T")


def test_p56_16_database_enforces_the_pairing():
    sql = MIGRATION.read_text(encoding="utf-8")
    assert "properties_flood_needs_a_check" in sql
    for col in ("flood_zone", "flood_zone_subtype", "flood_sfha", "flood_bfe", "flood_firm_id"):
        assert f"({col}" in sql.replace(" ", " ")


def test_p56_17_no_field_is_ever_written_as_none(flood):
    for attrs in (None, ALACHUA_X, AE_ZONE, {}):
        f = flood.build_update_fields(attrs, checked_at="T")
        assert None not in f.values()


# ---------------------------------------------------------------------------
# 5. Schema tolerance and fairness
# ---------------------------------------------------------------------------

def test_p56_18_refuses_to_run_without_the_irreducible_pair(flood, monkeypatch):
    monkeypatch.setattr(flood, "_available_optional_columns", frozenset({"flood_bfe"}))
    assert flood.schema_is_ready() is False


def test_p56_19_ready_when_zone_and_timestamp_exist(flood, monkeypatch):
    monkeypatch.setattr(
        flood, "_available_optional_columns", frozenset({"flood_zone", "flood_checked_at"})
    )
    assert flood.schema_is_ready() is True


def test_p56_20_unavailable_columns_are_dropped_from_the_patch(flood, monkeypatch):
    monkeypatch.setattr(
        flood, "_available_optional_columns", frozenset({"flood_zone", "flood_checked_at"})
    )
    kept = flood.drop_unavailable_columns(
        {"flood_zone": "X", "flood_checked_at": "T", "flood_bfe": 9.0}
    )
    assert kept == {"flood_zone": "X", "flood_checked_at": "T"}


def test_p56_21_main_exits_cleanly_when_the_migration_is_missing(flood, monkeypatch):
    monkeypatch.setattr(flood, "schema_is_ready", lambda: False)
    assert flood.main() == 0


def test_p56_22_county_batch_is_randomly_windowed(flood):
    """Phase 51's lesson: without a random window the same rows lead every
    run, and a county never advances past its first failures."""
    src = SCRIPT.read_text(encoding="utf-8")
    body = src[src.index("def fetch_county_batch"):src.index("def patch_property")]
    assert "random.randrange" in body
    assert '"order"' in body


def test_p56_23_counties_are_shuffled(flood):
    src = SCRIPT.read_text(encoding="utf-8")
    body = src[src.index("def fetch_counties_needing_flood"):src.index("def fetch_county_batch")]
    assert "random.shuffle" in body


def test_p56_24_only_rows_with_coordinates_are_selected(flood):
    src = SCRIPT.read_text(encoding="utf-8")
    for fn in ("fetch_counties_needing_flood", "fetch_county_batch"):
        body = src[src.index(f"def {fn}"):]
        body = body[:body.index("\ndef ", 5)]
        assert '"latitude": "not.is.null"' in body
        assert '"longitude": "not.is.null"' in body


# ---------------------------------------------------------------------------
# 6. Migration hygiene
# ---------------------------------------------------------------------------

def test_p56_25_migration_is_transactional_and_idempotent():
    sql = MIGRATION.read_text(encoding="utf-8")
    body = "\n".join(l for l in sql.splitlines() if not l.strip().startswith("--")).strip()
    assert body.startswith("begin;") and body.rstrip().endswith("commit;")
    adds = re.findall(r"alter table public\.properties add column\s+(\S+)", sql)
    assert adds and all(a == "if" for a in adds)
    for c in re.findall(r"add constraint (\S+)", sql):
        assert f"drop constraint if exists {c}" in sql


def test_p56_26_migration_contains_no_destructive_statement():
    sql = MIGRATION.read_text(encoding="utf-8").lower()
    for bad in ("drop column", "drop table", "delete from", "truncate"):
        assert bad not in sql


def test_p56_27_coordinates_are_sent_as_lon_lat_not_lat_lon(flood, monkeypatch):
    """ArcGIS point geometry is x,y - longitude first. Swapping them puts every
    Florida parcel in the Indian Ocean and returns a confident wrong zone."""
    seen = {}
    class Resp:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return {"features": []}
    def fake_get(url, params=None, timeout=None):
        seen.update(params or {})
        return Resp()
    monkeypatch.setattr(flood.requests, "get", fake_get)
    flood.lookup_flood_zone(29.660087, -82.301424)
    assert seen["geometry"] == "-82.301424,29.660087"
    assert seen["inSR"] == "4326"
