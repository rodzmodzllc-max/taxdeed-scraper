"""Tests for scripts/audit_enrichment_coverage.py.

The audit exists to give a measurable before/after for enrichment work, so
the one thing it must not do is miscount. The cases below pin the three ways
a count goes wrong quietly:

    '' counted as populated   -> photo_url's "checked, no coverage" sentinel
                                 would inflate photo coverage
    certificates in headline  -> a lien instrument is not a parcel; the
                                 headline is auction + laft only
    counties folded by name   -> "Harris" auction and "Harris" laft are two
                                 populations, not one

No network and no database: compute_coverage() is driven with literal rows,
and the REST fetch is exercised only through a faked requests.get.
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "audit_enrichment_coverage.py"
WORKFLOW = REPO / ".github" / "workflows" / "audit-enrichment-coverage.yml"


@pytest.fixture()
def audit(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://example.test/")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "not-a-real-key")
    spec = importlib.util.spec_from_file_location("_audit_cov", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_audit_cov"] = mod
    spec.loader.exec_module(mod)
    return mod


def _row(**kw):
    base = {"source": "auction", "state": "FL", "county": "Polk", "fdor_enriched_at": None}
    base.update(kw)
    return base


# --- is_populated -----------------------------------------------------------


@pytest.mark.parametrize(
    "value,expected",
    [
        (None, False),
        ("", False),
        ("   ", False),
        ("x", True),
        (0, True),  # a numeric zero is a real value (lot_sqft=0 is "0", not "unknown")
        (0.0, True),
        (False, True),
        ("2026-09-18T00:00:00+00:00", True),
    ],
)
def test_is_populated(audit, value, expected):
    assert audit.is_populated(value) is expected


# --- compute_coverage -------------------------------------------------------


def test_headline_counts_auction_and_laft_only(audit):
    rows = [
        _row(source="auction", fdor_enriched_at="2026-01-01T00:00:00Z"),
        _row(source="auction"),
        _row(source="laft", fdor_enriched_at="2026-01-01T00:00:00Z"),
        _row(source="certificate", fdor_enriched_at="2026-01-01T00:00:00Z"),
        _row(source="certificate", fdor_enriched_at="2026-01-01T00:00:00Z"),
    ]
    cov = audit.compute_coverage(rows)
    assert cov["total_rows"] == 5
    assert cov["headline"] == {
        "sources": ["auction", "laft"],
        "total": 3,
        "enriched": 2,
        "pct_enriched": 66.7,
    }
    assert cov["by_source"]["certificate"]["enriched"] == 2
    assert cov["by_source"]["certificate"]["pct_enriched"] == 100.0


def test_empty_string_photo_url_is_not_a_photo(audit):
    rows = [
        _row(photo_url=None),
        _row(photo_url=""),
        _row(photo_url="https://x.supabase.co/storage/v1/object/public/property-photos/a.jpg"),
    ]
    cov = audit.compute_coverage(rows)
    assert cov["field_coverage"]["photo_url"] == {"populated": 1, "total": 3, "pct_populated": 33.3}


def test_counties_keyed_by_state_source_and_name(audit):
    rows = [
        _row(state="TX", source="auction", county="Harris"),
        _row(state="TX", source="laft", county="Harris", fdor_enriched_at="2026-01-01T00:00:00Z"),
        _row(state="TX", source="laft", county="Harris"),
    ]
    cov = audit.compute_coverage(rows)
    assert set(cov["by_county"]) == {"TX/auction/Harris", "TX/laft/Harris"}
    assert cov["by_county"]["TX/auction/Harris"]["enriched"] == 0
    assert cov["by_county"]["TX/laft/Harris"] == {
        "total": 2,
        "enriched": 1,
        "source": "laft",
        "state": "TX",
        "county": "Harris",
        "pct_enriched": 50.0,
    }


def test_null_state_and_source_bucket_as_unknown(audit):
    cov = audit.compute_coverage([_row(state=None, source=None)])
    assert cov["by_state"] == {"unknown": {"total": 1, "enriched": 0, "pct_enriched": 0.0}}
    assert "unknown" in cov["by_source"]
    assert cov["headline"]["total"] == 0


def test_per_source_field_breakdown(audit):
    rows = [
        _row(source="auction", market=100),
        _row(source="auction", market=None),
        _row(source="laft", market=5),
    ]
    cov = audit.compute_coverage(rows)
    assert cov["by_source"]["auction"]["fields"]["market"] == {"populated": 1, "total": 2, "pct_populated": 50.0}
    assert cov["by_source"]["laft"]["fields"]["market"] == {"populated": 1, "total": 1, "pct_populated": 100.0}
    assert cov["field_coverage"]["market"] == {"populated": 2, "total": 3, "pct_populated": 66.7}


def test_empty_input_does_not_divide_by_zero(audit):
    cov = audit.compute_coverage([])
    assert cov["total_rows"] == 0
    assert cov["headline"]["pct_enriched"] == 0.0
    assert all(v["pct_populated"] == 0.0 for v in cov["field_coverage"].values())


# --- reports ----------------------------------------------------------------


def test_reports_round_trip(audit, tmp_path):
    rows = [
        _row(fdor_enriched_at="2026-01-01T00:00:00Z", market=1, county="Polk"),
        _row(county="Hillsborough"),
        _row(source="laft", state="TX", county="Galveston"),
    ]
    cov = audit.compute_coverage(rows)
    audit.write_json_report(cov, tmp_path / "a.json")
    audit.write_markdown_report(cov, tmp_path / "a.md")

    back = json.loads((tmp_path / "a.json").read_text())
    assert back["headline"]["enriched"] == 1
    md = (tmp_path / "a.md").read_text()
    assert "**Headline (auction + laft)**: 1 / 3 enriched (33.3%)" in md
    assert "**Hillsborough** (FL/auction): 1 of 1 unenriched (100.0%)" in md
    assert "**Galveston** (TX/laft): 1 of 1 unenriched (100.0%)" in md
    assert "**Polk**" not in md.split("## Top Unenriched Counties")[1].split("## Field Coverage")[0]


# --- fetch ------------------------------------------------------------------


def test_fetch_pages_until_empty_and_only_gets(audit, monkeypatch):
    calls = []

    class _Resp:
        def __init__(self, payload):
            self._payload = payload

        def raise_for_status(self):
            pass

        def json(self):
            return self._payload

    pages = [[_row()] * 1000, [_row()] * 3, []]

    def fake_get(url, timeout, headers, params):
        calls.append((url, dict(params), dict(headers)))
        return _Resp(pages[len(calls) - 1])

    monkeypatch.setattr(audit.requests, "get", fake_get)
    for verb in ("post", "patch", "put", "delete"):
        monkeypatch.setattr(audit.requests, verb, lambda *a, **k: pytest.fail(f"{verb} must never be called"))

    rows = audit.fetch_all_properties()
    assert len(rows) == 1003
    assert [c[1]["offset"] for c in calls] == ["0", "1000", "2000"]
    assert all(c[0] == "https://example.test/rest/v1/properties" for c in calls)
    selected = calls[0][1]["select"].split(",")
    assert set(audit.ALL_FIELDS) <= set(selected)
    assert {"source", "state", "county", "fdor_enriched_at"} <= set(selected)
    assert calls[0][2]["Authorization"] == "Bearer not-a-real-key"


def test_importing_the_module_creates_no_directories(audit):
    # Importing for tests (as this file does) must not litter the CWD with out/.
    assert audit.OUT_DIR == pathlib.Path("out")
    assert not (REPO / "tests" / "python" / "out").exists()


# --- workflow ---------------------------------------------------------------


def test_workflow_is_manual_and_read_only():
    yaml = pytest.importorskip("yaml")
    wf = yaml.safe_load(WORKFLOW.read_text())
    on = wf.get("on") or wf.get(True)
    assert on == {"workflow_dispatch": None}, "must be manual-only, no schedule"
    assert wf["permissions"] == {"contents": "read"}
    steps = wf["jobs"]["audit"]["steps"]
    run_step = next(s for s in steps if s.get("run", "").startswith("python3 scripts/audit_enrichment_coverage.py"))
    assert set(run_step["env"]) == {"SUPABASE_URL", "SUPABASE_SERVICE_KEY"}
