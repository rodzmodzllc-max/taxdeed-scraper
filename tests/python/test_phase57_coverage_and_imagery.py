"""Tests for Phase 57 - Texas pagination completeness, and NAIP imagery.

Two unrelated-looking changes that share one defect shape: something that
fails part-way through and reports the partial result as if it were whole.

  * harvest_lgbs() used to `break` on the first network error and return
    whatever it had. A truncated harvest was indistinguishable from a
    complete one to every caller. Measured 2026-09-17: 440 rows live against
    a roster observing ~4,205 genuine TX records.
  * A NAIP request that fails is not a parcel without imagery, and ArcGIS
    reports failures inside a 200 response body.

No network and no database.
"""

from __future__ import annotations

import importlib.util
import pathlib
import re
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

NAIP_SCRIPT = REPO / "scripts" / "enrich_property_photos_naip.py"
MIGRATION = REPO / "scripts" / "migrations" / "011_photo_provenance.sql"


@pytest.fixture()
def tx():
    import harvesters.texas_harvester as mod
    return mod


@pytest.fixture()
def naip(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://example.test")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "not-a-real-key")
    spec = importlib.util.spec_from_file_location("_p57_naip", NAIP_SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_p57_naip"] = mod
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# 1. Texas: a truncated walk must announce itself
# ---------------------------------------------------------------------------

def test_p57_01_harvest_lgbs_accepts_a_stats_out_param(tx):
    import inspect
    assert "stats" in inspect.signature(tx.harvest_lgbs).parameters


def test_p57_02_page_attempts_is_total_attempts_not_extra_retries(tx):
    """`max_retries` ambiguity has bitten this repo before; the constant is
    documented as TOTAL attempts and must stay >1 or the retry does nothing."""
    assert tx.LGBS_PAGE_ATTEMPTS >= 2


def test_p57_03_a_failed_page_no_longer_ends_the_walk_on_first_error(tx):
    src = (REPO / "harvesters" / "texas_harvester.py").read_text(encoding="utf-8")
    body = src[src.index("def harvest_lgbs"):src.index("REALAUCTION_COUNTIES_CSV")]
    assert "LGBS_PAGE_ATTEMPTS" in body
    assert "truncated_at_page" in body


def test_p57_04_completeness_is_reported(tx):
    src = (REPO / "harvesters" / "texas_harvester.py").read_text(encoding="utf-8")
    body = src[src.index("def harvest_lgbs"):src.index("REALAUCTION_COUNTIES_CSV")]
    assert '"complete": complete' in body
    assert "complete = truncated_at_page is None" in body


def test_p57_05_main_records_unknown_completeness_as_unknown_not_complete(tx):
    """A source that reports nothing must never be recorded as clean - absence
    of a signal is not a clean bill of health."""
    src = (REPO / "harvesters" / "texas_harvester.py").read_text(encoding="utf-8")
    body = src[src.index("def main() -> None:"):]
    assert "completeness-unknown" in body
    assert 'status_by_source[name]' in body


def test_p57_06_status_file_is_separate_from_the_sync_input_contract(tx):
    """harvest_texas.json's shape is the sync script's input; completeness
    goes in a sibling file so that contract is untouched."""
    src = (REPO / "harvesters" / "texas_harvester.py").read_text(encoding="utf-8")
    assert "harvest_texas_status.json" in src
    body = src[src.index("def main() -> None:"):]
    assert body.index("harvest_texas.json") < body.index("harvest_texas_status.json")


def test_p57_07_incomplete_walk_warns_loudly(tx):
    src = (REPO / "harvesters" / "texas_harvester.py").read_text(encoding="utf-8")
    assert "INCOMPLETE walk" in src or "INCOMPLETE" in src


def test_p57_08_philadelphia_rows_are_still_dropped(tx):
    """The area=TX leak is why the roster's 6,309 is not the denominator.
    Non-TX rows must stay filtered regardless of the retry change."""
    src = (REPO / "harvesters" / "texas_harvester.py").read_text(encoding="utf-8")
    body = src[src.index("def harvest_lgbs"):src.index("REALAUCTION_COUNTIES_CSV")]
    assert 'raw.get("state") != "TX"' in body


# ---------------------------------------------------------------------------
# 2. NAIP: a failed request is not "no imagery"
# ---------------------------------------------------------------------------

def test_p57_09_transport_failure_writes_nothing(naip, monkeypatch):
    def boom(*a, **k):
        raise naip.requests.RequestException("network down")
    monkeypatch.setattr(naip.requests, "get", boom)
    png, ok = naip.fetch_naip_image(29.66, -82.30)
    assert ok is False and png is None


def test_p57_10_arcgis_json_error_body_is_a_failure_not_a_missing_image(naip, monkeypatch):
    """ArcGIS answers failures with a 200 and a JSON body. Treating that as
    'no coverage' would stamp the no-coverage sentinel onto a row we learned
    nothing about, and it would never be retried."""
    class Resp:
        status_code = 200
        headers = {"Content-Type": "application/json;charset=utf-8"}
        content = b'{"error":{"code":500}}'
        def raise_for_status(self): pass
    monkeypatch.setattr(naip.requests, "get", lambda *a, **k: Resp())
    png, ok = naip.fetch_naip_image(29.66, -82.30)
    assert ok is False and png is None


def test_p57_11_empty_image_body_is_genuine_no_coverage(naip, monkeypatch):
    class Resp:
        status_code = 200
        headers = {"Content-Type": "image/png"}
        content = b""
        def raise_for_status(self): pass
    monkeypatch.setattr(naip.requests, "get", lambda *a, **k: Resp())
    png, ok = naip.fetch_naip_image(29.66, -82.30)
    assert ok is True and png is None


def test_p57_12_real_image_is_returned(naip, monkeypatch):
    class Resp:
        status_code = 200
        headers = {"Content-Type": "image/png"}
        content = b"\x89PNG\r\n\x1a\n" + b"x" * 200
        def raise_for_status(self): pass
    monkeypatch.setattr(naip.requests, "get", lambda *a, **k: Resp())
    png, ok = naip.fetch_naip_image(29.66, -82.30)
    assert ok is True and png.startswith(b"\x89PNG")


def test_p57_13_no_coverage_uses_the_established_empty_string_sentinel(naip):
    """photo_url's contract is already NULL=unchecked, ''=no coverage,
    value=real. A fourth state must not be invented."""
    f = naip.build_update_fields("", checked_at="T")
    assert f["photo_url"] == ""
    assert f["photo_checked_at"] == "T"
    assert "photo_source" not in f


def test_p57_14_a_stored_image_records_its_source(naip):
    f = naip.build_update_fields("https://x.test/a.png", checked_at="T")
    assert f["photo_source"] == "usda_naip"


def test_p57_15_bbox_is_lon_lat_ordered(naip):
    """ArcGIS bbox is xmin,ymin,xmax,ymax - longitude first. Swapping it puts
    every Florida parcel off the coast of Somalia and returns a confident
    wrong image."""
    box = naip.bbox_for(29.660087, -82.301424)
    xmin, ymin, xmax, ymax = (float(v) for v in box.split(","))
    assert xmin < 0 and xmax < 0, "longitude should be negative in FL/TX"
    assert 0 < ymin < 90 and 0 < ymax < 90, "latitude should be positive"
    assert xmin < xmax and ymin < ymax


def test_p57_16_bbox_is_centred_on_the_parcel(naip):
    box = naip.bbox_for(29.0, -82.0)
    xmin, ymin, xmax, ymax = (float(v) for v in box.split(","))
    assert abs(((xmin + xmax) / 2) - (-82.0)) < 1e-9
    assert abs(((ymin + ymax) / 2) - 29.0) < 1e-9


# ---------------------------------------------------------------------------
# 3. Migration hygiene and the provenance rules
# ---------------------------------------------------------------------------

def test_p57_17_migration_is_transactional_and_idempotent():
    sql = MIGRATION.read_text(encoding="utf-8")
    body = "\n".join(l for l in sql.splitlines() if not l.strip().startswith("--")).strip()
    assert body.startswith("begin;") and body.rstrip().endswith("commit;")
    adds = re.findall(r"alter table public\.properties add column\s+(\S+)", sql)
    assert adds and all(a == "if" for a in adds)
    for c in re.findall(r"add constraint (\S+)", sql):
        assert f"drop constraint if exists {c}" in sql


def test_p57_18_migration_has_no_destructive_statement():
    sql = MIGRATION.read_text(encoding="utf-8").lower()
    for bad in ("drop column", "drop table", "delete from", "truncate"):
        assert bad not in sql


def test_p57_19_photo_source_is_constrained_to_known_pipelines():
    sql = MIGRATION.read_text(encoding="utf-8")
    assert "usda_naip" in sql and "google_streetview" in sql
    assert "properties_photo_source_known" in sql


def test_p57_20_a_source_without_an_image_is_rejected():
    sql = MIGRATION.read_text(encoding="utf-8")
    assert "properties_photo_source_needs_an_image" in sql


def test_p57_21_capture_year_cannot_be_absurd():
    sql = MIGRATION.read_text(encoding="utf-8")
    assert "properties_photo_year_sane" in sql
    assert "1990" in sql


def test_p57_22_naip_needs_no_api_key():
    """The whole point: the Street View pipeline has never run because it
    needs a billing-attached key. If this one grows a key requirement it has
    lost its reason to exist."""
    import io
    import tokenize

    src = NAIP_SCRIPT.read_text(encoding="utf-8")
    # Comments and the module docstring legitimately DISCUSS the Street View
    # key - explaining why that pipeline never ran is the reason this file
    # exists. Only executable code is checked.
    code = [
        t.string
        for t in tokenize.generate_tokens(io.StringIO(src).readline)
        if t.type not in (tokenize.COMMENT, tokenize.STRING)
    ]
    joined = " ".join(code)
    for token in ("API_KEY", "api_key", "access_token", "GOOGLE_MAPS"):
        assert token not in joined, token


def test_p57_23_only_rows_with_coordinates_are_selected(naip):
    src = NAIP_SCRIPT.read_text(encoding="utf-8")
    for fn in ("fetch_counties_needing_photos", "fetch_county_batch"):
        body = src[src.index(f"def {fn}"):]
        body = body[:body.index("\ndef ", 5)]
        assert '"latitude": "not.is.null"' in body
        assert '"longitude": "not.is.null"' in body


def test_p57_24_schema_probe_drops_unavailable_columns(naip, monkeypatch):
    monkeypatch.setattr(naip, "_available_optional_columns", frozenset())
    kept = naip.drop_unavailable_columns(
        {"photo_url": "u", "photo_source": "usda_naip", "photo_checked_at": "T"}
    )
    assert kept == {"photo_url": "u"}
