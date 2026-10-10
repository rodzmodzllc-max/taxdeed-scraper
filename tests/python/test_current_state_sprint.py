"""Current-state data sprint (2026-10-10): regression tests for the three
production defects found in that day's read-only baseline.

1. Whole-population reads crossed the statement timeout under load (HTTP
   500): the SC sync (2026-10-08), the LA sync (2026-10-09, which then
   skipped the Louisiana lifecycle -> 10,334 rows not refreshed) and the
   deeds job's geocoding read (2026-10-10, which then skipped FDOR / FEMA /
   NAIP). Fix: keyset paging + bounded retry (scripts/rest_pages.py).
2. One merged status per county: Detroit Land Bank lots read COMPLETE while
   Detroit's programs layer (same county) FAILED, the merged entry said
   FAILED and the sync skipped all 30,706 lot rows. Fix: one entry per
   (source, county), read per source by the sync and its close-out.
3. An enrichment step failure stopped the steps after it (workflow).
"""
import importlib.util
import io
import json
import re
import sys
import urllib.error
from pathlib import Path
from urllib.parse import parse_qs

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(1, str(ROOT))
import rest_pages as RP  # noqa: E402
import sync_state_inventory as SY  # noqa: E402
from laft_status import StatusRecorder  # noqa: E402


# ------------------------------------------------------------ 1. reads

def _fake_table(n):
    return [{"id": f"{i:08d}-0000-0000-0000-000000000000", "v": i} for i in range(n)]


def _keyset_fetch(rows, log):
    def fetch(qs):
        q = parse_qs(qs)
        log.append(q)
        assert q["order"] == ["id.asc"] and "offset" not in q
        data = sorted(rows, key=lambda r: r["id"])
        if "id" in q:
            data = [r for r in data if r["id"] > q["id"][0][3:]]
        return data[:int(q["limit"][0])]
    return fetch


def test_keyset_reads_every_row_exactly_once_across_pages():
    rows, log = _fake_table(2345), []
    got = RP.read_all("https://x.test", "properties", {}, {"select": "id,v", "state": "eq.MI"}, fetch=_keyset_fetch(rows, log))
    assert [r["v"] for r in got] == list(range(2345))
    assert len(log) == 3 and "id" not in log[0] and log[1]["id"][0].startswith("gt.")


def test_keyset_exact_multiple_ends_on_an_empty_page():
    rows, log = _fake_table(2000), []
    assert len(RP.read_all("https://x.test", "properties", {}, {"select": "id"}, fetch=_keyset_fetch(rows, log))) == 2000
    assert len(log) == 3


def test_keyset_needs_id_and_owns_paging_params():
    with pytest.raises(ValueError):
        RP.read_all("https://x.test", "properties", {}, {"select": "county"}, fetch=lambda qs: [])
    for k in ("order", "limit", "offset", "id"):
        with pytest.raises(ValueError):
            RP.keyset_query({k: "x"}, None)


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _opener(script):
    calls = []

    def opener(req, timeout):
        calls.append(req.full_url)
        step = script[len(calls) - 1]
        if isinstance(step, int):
            raise urllib.error.HTTPError(req.full_url, step, "x", {}, None)
        if isinstance(step, Exception):
            raise step
        return _Resp(json.dumps(step).encode())
    return opener, calls


def test_transient_500_is_retried_then_succeeds():
    opener, calls = _opener([500, 503, [{"id": "a"}]])
    sleeps = []
    assert RP.get_json("https://x.test/rest/v1/properties?a=1", {}, sleep=sleeps.append, opener=opener) == [{"id": "a"}]
    assert len(calls) == 3 and sleeps == [2.0, 4.0]


def test_connection_error_is_retried():
    opener, calls = _opener([urllib.error.URLError("reset"), [{"id": "a"}]])
    assert RP.get_json("https://x.test/p", {}, sleep=lambda s: None, opener=opener) == [{"id": "a"}]
    assert len(calls) == 2


def test_a_4xx_is_never_retried_and_keeps_its_type():
    # laft_lifecycle's column probes depend on seeing the HTTP 400 unchanged.
    opener, calls = _opener([400, [{"id": "a"}]])
    with pytest.raises(urllib.error.HTTPError) as exc:
        RP.get_json("https://x.test/p", {}, sleep=lambda s: None, opener=opener)
    assert exc.value.code == 400 and len(calls) == 1


def test_retries_are_bounded():
    opener, calls = _opener([500] * 10)
    with pytest.raises(urllib.error.HTTPError) as exc:
        RP.get_json("https://x.test/p", {}, sleep=lambda s: None, opener=opener)
    assert exc.value.code == 500 and len(calls) == RP.ATTEMPTS == 4


def test_no_offset_paging_left_in_the_population_readers():
    for name in ("sync_state_inventory.py", "laft_lifecycle.py"):
        src = (ROOT / "scripts" / name).read_text(encoding="utf-8")
        assert not re.search(r"[\"'&]offset[\"'=]", src), f"{name} still pages by offset"


@pytest.fixture
def geo(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://example.test")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "not-a-real-key")
    monkeypatch.delenv("GEOCODE_SOURCE_ID", raising=False)
    spec = importlib.util.spec_from_file_location("_sprint_geo", ROOT / "scripts/geocode_properties.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _R:
    def __init__(self, code, body=None):
        self.status_code, self._body, self.text = code, body or [], ""

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def test_geocode_read_retries_a_500_and_reads_only_listed_rows(geo, monkeypatch):
    seen = []
    script = [_R(500), _R(200, [{"id": "a", "address": "1 Main St, Tampa", "county": "Hillsborough", "state": "FL"}])]

    def fake_get(url, headers, params, timeout):
        seen.append(dict(params))
        return script[len(seen) - 1]
    monkeypatch.setattr(geo.requests, "get", fake_get)
    rows = geo._fetch(5, geo.ADDRESS_CONTEXT_FILTER)
    assert rows and len(seen) == 2
    assert seen[0]["status"] == "in.(active,available,scheduled)" and seen[0]["delisted_at"] == "is.null"
    assert seen[0]["latitude"] == "is.null"


def test_geocode_read_does_not_retry_a_4xx(geo, monkeypatch):
    calls = []
    monkeypatch.setattr(geo.requests, "get", lambda *a, **k: calls.append(1) or _R(404))
    with pytest.raises(RuntimeError):
        geo._fetch(5, geo.ADDRESS_CONTEXT_FILTER)
    assert len(calls) == 1


# ------------------------------------------------------------ 2. per-source status

LOTS, PROGRAMS = "mi_detroit_landbank_lots", "mi_detroit_landbank_programs"


def _status_file(tmp_path, entries):
    p = tmp_path / "harvest_mi_status.json"
    p.write_text(json.dumps(entries), encoding="utf-8")
    return p


def _wayne(order):
    lots = {"county": "Wayne", "source_id": LOTS, "status": "COMPLETE", "row_count": 2}
    prog = {"county": "Wayne", "source_id": PROGRAMS, "status": "FAILED"}
    return [lots, prog] if order == "lots-first" else [prog, lots]


def _row(source_id, case_no):
    return {"state": "MI", "source": "laft", "source_id": source_id, "county": "Wayne", "case_no": case_no,
            "parcel": case_no, "status": "active"}


@pytest.mark.parametrize("order", ["lots-first", "programs-first"])
def test_a_failed_sibling_source_does_not_hide_a_complete_read(tmp_path, order):
    units = SY.units_for(_status_file(tmp_path, _wayne(order)))
    rows = [_row(LOTS, "L1"), _row(LOTS, "L2"), _row(PROGRAMS, "P1")]
    sent, counts = SY.plan("MI", rows, SY.registry_rows("MI"), units)
    assert sorted(r["case_no"] for r in sent) == ["L1", "L2"]
    assert counts["skipped_unit_not_read"] == 1          # the failed source's row only


@pytest.mark.parametrize("order", ["lots-first", "programs-first"])
def test_close_out_is_per_source(tmp_path, order):
    units = SY.units_for(_status_file(tmp_path, _wayne(order)))
    harvested = [_row(LOTS, "L1")]
    stored = [{"id": "lot-gone", "state": "MI", "status": "active", "harvester_source": LOTS, "source": "laft",
               "county": "Wayne", "case_no": "L-GONE"},
              {"id": "prog-kept", "state": "MI", "status": "active", "harvester_source": PROGRAMS, "source": "laft",
               "county": "Wayne", "case_no": "P-NOT-READ"}]
    closes = SY.plan_close("MI", harvested, stored, units, {LOTS, PROGRAMS})
    # The lot the COMPLETE lots read no longer lists is closed; the programs
    # row is never closed by a read that FAILED - whatever the entry order.
    assert [c["id"] for c in closes] == ["lot-gone"]


def test_county_fallback_is_the_worst_read(tmp_path):
    for order in ("lots-first", "programs-first"):
        assert SY.status_units(_status_file(tmp_path, _wayne(order))) == {"Wayne": "FAILED"}


def test_rows_of_a_source_without_its_own_entry_use_the_county_fallback(tmp_path):
    units = SY.units_for(_status_file(tmp_path, [{"county": "Wayne", "status": "COMPLETE"}]))
    sent, _ = SY.plan("MI", [_row(LOTS, "L1")], SY.registry_rows("MI"), units)
    assert len(sent) == 1


def test_recorder_keeps_one_entry_per_source_of_a_county(tmp_path):
    rec = StatusRecorder("expansion_mi", source_id="expansion_mi", path=tmp_path / "s.json", state="MI")
    rec.complete("Wayne", 2, source_id=LOTS)
    rec.failed("Wayne", "PARSE_FORMAT_CHANGE", "paging not stable", source_id=PROGRAMS)
    rec.complete("Wayne", 3, source_id=LOTS)              # a retry of the same source supersedes
    by = {(e.source_id, e.status, e.row_count) for e in rec.entries}
    assert by == {(LOTS, "COMPLETE", 3), (PROGRAMS, "FAILED", 0)}


def test_expansion_runner_records_each_source_separately():
    src = (ROOT / "scripts/harvest_expansion.py").read_text(encoding="utf-8")
    block = src[src.index("for county, results in per_county.items():"):src.index("recorder.write()")]
    assert block.count("source_id=sid") == 4               # failed / incomplete / complete / empty


# ------------------------------------------------------------ 3. workflow isolation

def _step(wf, name):
    i = wf.index(f"- name: {name}")
    j = wf.find("\n      - name:", i + 1)
    return wf[i:j if j != -1 else len(wf)]


def test_deeds_enrichment_steps_are_isolated_from_each_other():
    wf = (ROOT / ".github/workflows/harvest-and-sync.yml").read_text(encoding="utf-8")
    names = ["Backfill geocoding (US Census Bureau Geocoder)",
             "Backfill address/property-type enrichment (FL DOR statewide parcel lookup)",
             "Backfill FEMA flood hazard (National Flood Hazard Layer)",
             "Backfill property imagery (USDA NAIP aerial)"]
    for n in names:
        step = _step(wf, n)
        assert "continue-on-error: true" in step, n
        assert "if: ${{ !cancelled() }}" in step, n


# ------------------------------------------------------------ 4. coverage matrix

def test_coverage_matrix_is_current_and_counts_only():
    import subprocess
    r = subprocess.run([sys.executable, "scripts/current_state_report.py", "--snapshot", "data/current_state/coverage-2026-10-10.json",
                        "--out", "docs/current-state-coverage.md", "--check"], cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    snap = json.loads((ROOT / "data/current_state/coverage-2026-10-10.json").read_text(encoding="utf-8"))
    allowed = {"state", "source", "total", "active", "act_parcel", "act_coords", "act_assessed", "act_landuse", "act_flood",
               "act_url", "act_never_seen", "act_seen_gt36h", "act_past_sale", "act_prov", "last_seen_max"}
    assert all(set(row) == allowed for row in snap["rows"])     # counts and timestamps only, never a row value
    sql = (ROOT / "scripts/sql/current_state_coverage.sql").read_text(encoding="utf-8").lower()
    assert not re.search(r"\b(insert|update|delete|alter|drop|create|grant|truncate)\b", sql)
