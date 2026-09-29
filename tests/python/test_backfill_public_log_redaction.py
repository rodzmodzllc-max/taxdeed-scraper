"""scripts/backfill_fdor_phase52_fields.py - the PUBLIC workflow log carries
operational facts only.

Residual from the final review of PR #35: this repository is public, so the
GitHub Actions log of the FDOR backfill workflow is public, and the script
printed one JSON record per property (`ROW {...}` / `WROTE {...}`) straight
from the plan record. The plan record's `gains` are the five FDOR roll
target fields (never owner name or address - TARGET_FIELDS has never
included them), but the printed record also carried the parcel number and
the roll VALUES, and a future target field could carry anything. The fix
routes every per-row print through public_log_view(), which keeps id,
source, county, case/path/strategy, reason and the NAMES of gained fields.

These tests drive the real dry-run loop with a fixture row that carries an
owner name, an address and a parcel number, and assert none of them reaches
stdout while the plan file (encrypted-artifact material) still holds the
gains.
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import re
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "backfill_fdor_phase52_fields.py"

OWNER = "Jane Q. Ownerperson"
ADDRESS = "1234 Very Specific Lane, Ocala FL 34470"
PARCEL = "12345-678-90"


@pytest.fixture
def mod(tmp_path, monkeypatch):
    # Same loader as test_backfill_fdor_phase52_fields.py: the script imports
    # enrich_property_details, which needs the Supabase env at import time.
    monkeypatch.setenv("SUPABASE_URL", "https://example.test")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "not-a-real-key")
    monkeypatch.setenv("BACKFILL_MODE", "dry-run")
    monkeypatch.setenv("BACKFILL_PLAN_OUT", str(tmp_path / "plan.json"))
    monkeypatch.setenv("BACKFILL_PLAN_IN", "")
    spec = importlib.util.spec_from_file_location("_backfill_p52_log", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    sys.modules["_backfill_p52_log"] = m
    spec.loader.exec_module(m)
    monkeypatch.setattr(m.time, "sleep", lambda *_: None)
    yield m
    sys.modules.pop("_backfill_p52_log", None)


def test_public_log_view_keeps_operational_keys_and_field_names_only(mod):
    rec = {
        "id": "row-1", "source": "auction", "county": "Marion", "parcel": PARCEL, "case": "match",
        "path": "fdor", "strategy": "identity", "matched_candidate": PARCEL,
        # A hypothetical future target field carrying personal data must
        # surface as a NAME only.
        "gains": {"dor_use_code": "0100", "acreage": 2.5, "owner_name": OWNER, "address": ADDRESS},
        "already": ["taxable_value"], "roll_empty": ["land_use", "fdor_alt_key"],
    }
    view = mod.public_log_view(rec)
    assert view == {
        "id": "row-1", "source": "auction", "county": "Marion", "case": "match", "path": "fdor",
        "strategy": "identity", "already": ["taxable_value"], "roll_empty": ["land_use", "fdor_alt_key"],
        "gain_fields": ["acreage", "address", "dor_use_code", "owner_name"],
    }
    text = json.dumps(view)
    for value in (OWNER, ADDRESS, PARCEL, "0100", "2.5"):
        assert value not in text, value


def test_dry_run_log_never_carries_row_or_roll_values(mod, tmp_path, capsys, monkeypatch):
    row = {"id": "row-1", "state": "FL", "source": "auction", "county": "Marion", "parcel": PARCEL,
           "address": ADDRESS, "owner_name": OWNER, "prop_type": None, "market": None, "assessed": None,
           "latitude": None, "longitude": None, "gone_since": None, "fdor_enriched_at": None,
           "dor_use_code": None, "taxable_value": 1500, "acreage": None, "land_use": None, "fdor_alt_key": None}
    monkeypatch.setattr(mod, "fetch_targets", lambda: [row])
    monkeypatch.setattr(mod, "production_lookup", lambda r: ({"DOR_UC": "01"}, (29.1, -82.1), PARCEL, "fdor"))
    monkeypatch.setattr(mod.prod, "build_update_fields",
                        lambda r, attrs, centroid: {"dor_use_code": "0100", "acreage": 2.5, "land_use": "SINGLE FAMILY"})
    monkeypatch.setattr(mod.prod, "REQUEST_DELAY_SECONDS", 0)
    summary = mod.run_dry_run()
    out = capsys.readouterr().out
    assert summary["targets"] == 1
    row_lines = [l for l in out.splitlines() if l.startswith("ROW ")]
    assert len(row_lines) == 1
    logged = json.loads(row_lines[0][4:])
    assert logged["id"] == "row-1" and logged["county"] == "Marion" and logged["case"] == "match"
    assert logged["gain_fields"] == ["acreage", "dor_use_code", "land_use"]
    for value in (OWNER, ADDRESS, PARCEL, "SINGLE FAMILY", "0100", "2.5"):
        assert value not in out, value
    for key in ("owner_name", "address", "parcel", "matched_candidate", "gains"):
        assert f'"{key}"' not in out, key
    # The plan file - encrypted-artifact material, never uploaded in the
    # clear (tests/python/test_artifact_privacy.py) - still holds the gains.
    plan = json.loads((tmp_path / "plan.json").read_text())
    assert plan["rows"][0]["gains"] == {"dor_use_code": "0100", "acreage": 2.5, "land_use": "SINGLE FAMILY"}
    assert plan["rows"][0]["parcel"] == PARCEL
    # The plan holds no owner/address either: plan_row() never copied them.
    assert OWNER not in json.dumps(plan) and ADDRESS not in json.dumps(plan)


def test_apply_log_lines_go_through_the_same_redaction(mod, tmp_path, capsys, monkeypatch):
    plan = {"mode": "dry-run", "cutoff": mod.CUTOFF, "target_fields": list(mod.TARGET_FIELDS), "generated_at": "x",
            "rows": [
                {"id": "row-1", "source": "auction", "county": "Marion", "parcel": PARCEL, "gains": {"acreage": 2.5}},
                {"id": "row-2", "source": "auction", "county": "Lake", "parcel": "999", "gains": {"acreage": 1.0}},
            ]}
    plan_in = tmp_path / "in.json"
    plan_in.write_text(json.dumps(plan))
    monkeypatch.setattr(mod, "PLAN_IN", str(plan_in))
    monkeypatch.setattr(mod.prod, "REQUEST_DELAY_SECONDS", 0)

    def fake_apply(planned):
        if planned["id"] == "row-1":
            return {"acreage": 2.5}, None
        return {}, f"skipped example mentioning {OWNER}"
    monkeypatch.setattr(mod, "apply_plan_row", fake_apply)
    mod.run_apply()
    out = capsys.readouterr().out
    wrote = [l for l in out.splitlines() if l.startswith("WROTE ")]
    assert json.loads(wrote[0][6:]) == {"id": "row-1", "source": "auction", "county": "Marion", "written": ["acreage"]}
    assert PARCEL not in out and "2.5" not in "".join(wrote)
    # A reason string is operational text and is kept verbatim in the
    # SKIP line - this test documents that reasons must never be built
    # from row values (apply_plan_row()'s reasons are fixed sentences).
    assert re.search(r'^SKIP \{"id":"row-2","county":"Lake","reason":', out, re.M)


def test_every_per_row_print_is_redacted_at_source():
    src = SCRIPT.read_text(encoding="utf-8")
    for tag in ("ROW ", "WROTE ", "SKIP ", "ERR "):
        for m in re.finditer(r'print\("%s" \+ json\.dumps\(([^,]+),' % re.escape(tag), src):
            assert m.group(1).startswith("public_log_view("), f"{tag} line prints an unredacted record: {m.group(0)}"
    assert 'json.dumps(rec, separators' not in src
    assert "def public_log_view(rec)" in src
    for banned in ("owner_name", "address", "parcel", "matched_candidate", "gains"):
        assert f'"{banned}"' not in src.split("PUBLIC_LOG_KEYS = ")[1].split("\n")[0], banned
