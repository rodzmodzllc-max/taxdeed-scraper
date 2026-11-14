"""photo_captured_year for stored USDA NAIP aerials (2026-11-14).

The year comes from the NAIP ImageServer's own catalog: `acquisition_date`
(epoch ms, UTC) of the primary items under the exported box - never from the
program `Year` field, never guessed. A stored row is backfilled only when the
image the service returns today is byte-identical to the stored one.
"""
from __future__ import annotations

import copy
import importlib
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
import image_storage as IS  # noqa: E402

CASES = json.loads((REPO / "tests/python/fixtures/naip_catalog_query_cases.json").read_text(encoding="utf-8"))
REAL = [k for k in CASES if not k.startswith("_")]


@pytest.fixture
def naip(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "test")
    monkeypatch.delenv("NAIP_YEAR_BACKFILL_LIMIT", raising=False)
    sys.modules.pop("enrich_property_photos_naip", None)
    mod = importlib.import_module("enrich_property_photos_naip")
    monkeypatch.setattr(mod, "REQUEST_DELAY_SECONDS", 0)
    return mod


class Resp:
    def __init__(self, payload=None, status=200, content=b""):
        self._payload, self.status_code, self.content = payload, status, content

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError(str(self.status_code))

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


# --- extraction from the real service answer ---------------------------------

@pytest.mark.parametrize("case", REAL)
def test_year_from_real_catalog_answers(naip, case):
    c = CASES[case]
    assert naip.capture_year_from_catalog(c["payload"], max_year=2026) == c["expect_year"]


def test_capture_year_is_acquisition_date_not_program_year(naip):
    # The Florida 2022 NAIP program tile was flown on 2023-01-26.
    a = CASES["alachua_fl"]["payload"]["features"][0]["attributes"]
    assert a["Year"] == 2022
    assert naip.capture_year_from_catalog(CASES["alachua_fl"]["payload"], max_year=2026) == 2023


def test_items_from_different_years_give_no_year(naip):
    p = copy.deepcopy(CASES["alachua_fl"]["payload"])
    p["features"].append({"attributes": {"OBJECTID": 1, "Name": "m_x_20210601", "Category": 1, "Year": 2021,
                                         "acquisition_date": 1622505600000}})
    assert naip.capture_year_from_catalog(p, max_year=2026) is None


@pytest.mark.parametrize("mutate", [
    lambda a: a.update(acquisition_date=None),
    lambda a: a.pop("acquisition_date"),
    lambda a: a.update(acquisition_date="2023-01-26"),
    lambda a: a.update(acquisition_date=True),
])
def test_missing_or_malformed_date_gives_no_year(naip, mutate):
    p = copy.deepcopy(CASES["alachua_fl"]["payload"])
    mutate(p["features"][0]["attributes"])
    assert naip.capture_year_from_catalog(p, max_year=2026) is None


def test_overview_items_are_ignored(naip):
    p = copy.deepcopy(CASES["alachua_fl"]["payload"])
    p["features"].append({"attributes": {"OBJECTID": 38297, "Name": "Ov_i02_L01", "Category": 2, "Year": 2022, "acquisition_date": None}})
    assert naip.capture_year_from_catalog(p, max_year=2026) == 2023


def test_truncated_empty_or_implausible_answers_give_no_year(naip):
    p = copy.deepcopy(CASES["alachua_fl"]["payload"])
    assert naip.capture_year_from_catalog(dict(p, exceededTransferLimit=True), max_year=2026) is None
    assert naip.capture_year_from_catalog({"features": []}) is None
    assert naip.capture_year_from_catalog(None) is None
    assert naip.capture_year_from_catalog(p, max_year=2022) is None          # past the sane-year check
    p["features"][0]["attributes"]["acquisition_date"] = 0                  # 1970
    assert naip.capture_year_from_catalog(p, max_year=2026) is None


# --- the request -------------------------------------------------------------

def test_fetch_capture_year_queries_the_exported_box(naip, monkeypatch):
    seen = {}

    def get(url, params=None, timeout=None):
        seen.update(url=url, params=params)
        return Resp(CASES["alachua_fl"]["payload"])
    monkeypatch.setattr(naip.requests, "get", get)
    year, ok = naip.fetch_capture_year(29.660087, -82.301424)
    assert ok and year == 2023
    assert seen["url"].endswith("/USGSNAIPImagery/ImageServer/query")
    assert seen["params"]["geometry"] == naip.bbox_for(29.660087, -82.301424)
    assert seen["params"]["inSR"] == "4326" and seen["params"]["where"] == "Category = 1"
    assert "acquisition_date" in seen["params"]["outFields"]


@pytest.mark.parametrize("resp", [
    Resp({"error": {"code": 400, "message": "Unable to complete operation."}}),
    Resp(ValueError("not json")),
    Resp({}, status=502),
    Resp({"objectIdFieldName": "OBJECTID"}),
])
def test_failed_lookup_is_not_a_finding(naip, monkeypatch, resp):
    monkeypatch.setattr(naip.requests, "get", lambda *a, **k: resp)
    assert naip.fetch_capture_year(29.66, -82.30) == (None, False)


# --- new images carry the year ------------------------------------------------

def test_build_update_fields_records_the_year_only_with_an_image(naip):
    assert naip.build_update_fields("https://x.test/a.webp", checked_at="T", captured_year=2023)["photo_captured_year"] == 2023
    assert "photo_captured_year" not in naip.build_update_fields("https://x.test/a.webp", checked_at="T")
    assert "photo_captured_year" not in naip.build_update_fields("", checked_at="T", captured_year=2023)


def _drive_main(naip, monkeypatch, year_answer):
    monkeypatch.setattr(naip, "storage_used_bytes", lambda *a, **k: 0)
    monkeypatch.setattr(naip, "fetch_counties_needing_photos", lambda flt=None: [(("FL", "Alachua"), 1)])
    monkeypatch.setattr(naip, "fetch_county_batch",
                        lambda unit, limit, o=None, flt=None: [{"id": "r1", "latitude": 29.660087, "longitude": -82.301424}])
    monkeypatch.setattr(naip, "fetch_naip_image", lambda *a, **k: (b"png-bytes", True))
    monkeypatch.setattr(naip, "fetch_capture_year", lambda *a, **k: year_answer)
    monkeypatch.setattr(naip, "object_exists", lambda p: False)
    monkeypatch.setattr(naip, "put_object", lambda *a: True)
    monkeypatch.setattr(naip, "available_optional_columns", lambda: frozenset(naip.OPTIONAL_COLUMNS))
    patches, reports = [], []
    monkeypatch.setattr(naip.requests, "patch", lambda url, **k: patches.append((url, k)) or Resp())
    monkeypatch.setattr(naip, "write_priority_report", reports.append)
    monkeypatch.setattr(naip, "BATCH_LIMIT", 1)
    assert naip.main() == 0
    return patches, reports[0]


def test_new_image_is_stored_with_its_year(naip, monkeypatch):
    patches, report = _drive_main(naip, monkeypatch, (2023, True))
    assert len(patches) == 1 and patches[0][1]["json"]["photo_captured_year"] == 2023
    assert patches[0][1]["json"]["photo_source"] == "usda_naip" and report["captured_year_written"] == 1


@pytest.mark.parametrize("answer", [(None, True), (None, False)])
def test_new_image_without_a_year_is_still_stored_without_one(naip, monkeypatch, answer):
    patches, report = _drive_main(naip, monkeypatch, answer)
    assert len(patches) == 1 and "photo_captured_year" not in patches[0][1]["json"]
    assert patches[0][1]["json"]["photo_url"] and report["captured_year_written"] == 0


# --- backfill of stored rows ----------------------------------------------------

PNG = b"today's export bytes"
SHA = IS.sha256(PNG)
URL = "https://example.supabase.co/storage/v1/object/public/property-photos/"


def _backfill(naip, monkeypatch, rows, *, image=(PNG, True), year=(2023, True), stored=None):
    reads, patches = [], []

    def get_json(url, params):
        reads.append(dict(params))
        if params.get("id", "").startswith("gt.") and "and" not in params:
            return [r for r in rows][: int(params["limit"])]
        return []
    monkeypatch.setattr(naip, "_get_json", get_json)
    monkeypatch.setattr(naip, "available_optional_columns", lambda: frozenset(naip.OPTIONAL_COLUMNS))
    monkeypatch.setattr(naip, "fetch_naip_image", lambda *a, **k: image)
    monkeypatch.setattr(naip, "fetch_capture_year", lambda *a, **k: year)
    monkeypatch.setattr(naip, "fetch_stored_object", lambda url: stored)
    monkeypatch.setattr(naip.requests, "patch", lambda url, **k: patches.append((url, k)) or Resp())
    monkeypatch.setattr(naip.EU, "get_window", lambda get, url, params, limit, start=None:
                        naip.EU.get_paged(get, url, dict(params, id="gt.00000000-0000-0000-0000-000000000000"), limit))
    out = naip.backfill_capture_years(len(rows) or 5)
    return out, reads, patches


def _row(i, path):
    return {"id": f"00000000-0000-0000-0000-00000000000{i}", "latitude": 29.660087, "longitude": -82.301424, "photo_url": URL + path}


def test_backfill_reads_only_stored_naip_rows_without_a_year_in_bounded_pages(naip, monkeypatch):
    out, reads, patches = _backfill(naip, monkeypatch, [_row(1, f"naip/v2/{SHA}.webp")])
    q = reads[0]
    assert q["photo_source"] == "eq.usda_naip" and q["photo_captured_year"] == "is.null"
    assert q["photo_url"] == "not.is.null" and q["order"] == "id.asc" and int(q["limit"]) <= 1000
    assert out["written"] == 1


def test_backfill_writes_one_column_once_and_only_while_null(naip, monkeypatch):
    out, reads, patches = _backfill(naip, monkeypatch, [_row(1, f"naip/v2/{SHA}.webp"), _row(2, f"naip/v2/{SHA}.png")])
    assert out["written"] == 2 and len(patches) == 2
    for url, k in patches:
        assert k["json"] == {"photo_captured_year": 2023}
        assert k["params"]["photo_captured_year"] == "is.null" and k["params"]["id"].startswith("eq.")


def test_backfill_skips_a_row_whose_image_changed_since_it_was_stored(naip, monkeypatch):
    out, reads, patches = _backfill(naip, monkeypatch, [_row(1, f"naip/v2/{'0' * 64}.webp")])
    assert patches == [] and out["image_changed"] == 1


def test_backfill_compares_bytes_for_a_legacy_path(naip, monkeypatch):
    out, _, patches = _backfill(naip, monkeypatch, [_row(1, "naip/abc.png")], stored=PNG)
    assert out["written"] == 1 and len(patches) == 1
    out, _, patches = _backfill(naip, monkeypatch, [_row(1, "naip/abc.png")], stored=b"re-encoded webp")
    assert patches == [] and out["image_changed"] == 1
    out, _, patches = _backfill(naip, monkeypatch, [_row(1, "naip/abc.png")], stored=None)
    assert patches == [] and out["image_changed"] == 1


@pytest.mark.parametrize("kw,counter", [
    ({"image": (None, False)}, "failed"),
    ({"year": (None, False)}, "failed"),
    ({"year": (None, True)}, "no_year"),
])
def test_backfill_writes_nothing_without_an_established_year(naip, monkeypatch, kw, counter):
    out, _, patches = _backfill(naip, monkeypatch, [_row(1, f"naip/v2/{SHA}.webp")], **kw)
    assert patches == [] and out[counter] == 1 and out["written"] == 0


def test_backfill_honours_its_limit_and_the_time_budget(naip, monkeypatch):
    rows = [_row(i, f"naip/v2/{SHA}.webp") for i in range(1, 4)]
    monkeypatch.setattr(naip, "available_optional_columns", lambda: frozenset(naip.OPTIONAL_COLUMNS))
    monkeypatch.setattr(naip, "fetch_year_backfill_rows", lambda limit: rows)
    monkeypatch.setattr(naip, "fetch_naip_image", lambda *a, **k: (PNG, True))
    monkeypatch.setattr(naip, "fetch_capture_year", lambda *a, **k: (2023, True))
    patches = []
    monkeypatch.setattr(naip, "patch_capture_year", lambda pid, y: patches.append(pid))
    assert naip.backfill_capture_years(2)["written"] == 2 and len(patches) == 2
    patches.clear()
    out = naip.backfill_capture_years(3, deadline=naip.time.monotonic() - 1)
    assert patches == [] and out["time_budget_reached"] is True
    assert naip.backfill_capture_years(0)["examined"] == 0


def test_backfill_is_off_by_default_and_runs_alone_with_the_flag(naip, monkeypatch):
    assert naip.YEAR_BACKFILL_LIMIT == 0
    calls = []
    monkeypatch.setattr(naip, "backfill_capture_years", lambda limit, deadline=None: calls.append(limit) or {})
    monkeypatch.setattr(naip, "storage_used_bytes", lambda *a, **k: calls.append("storage") or None)
    monkeypatch.setattr(naip, "fetch_counties_needing_photos", lambda flt=None: [])
    monkeypatch.setattr(naip, "write_priority_report", lambda r: None)
    assert naip.main([]) == 0 and calls == ["storage"]
    calls.clear()
    assert naip.main(["--backfill-capture-year", "--limit", "7"]) == 0 and calls == [7]


def test_stored_source_sha_reads_the_content_address(naip):
    assert naip.stored_source_sha(URL + f"naip/v2/{SHA}.webp") == SHA
    assert naip.stored_source_sha(URL + "naip/abc.png") is None
    assert naip.stored_source_sha(None) is None


def test_the_deeds_job_backfills_a_bounded_slice():
    import yaml
    wf = yaml.safe_load((REPO / ".github/workflows/harvest-and-sync.yml").read_text(encoding="utf-8"))
    step = next(s for s in wf["jobs"]["deeds"]["steps"] if "enrich_property_photos_naip.py" in s.get("run", ""))
    assert step.get("continue-on-error") is True
    assert 0 < int(step["env"]["NAIP_YEAR_BACKFILL_LIMIT"]) <= 1000
