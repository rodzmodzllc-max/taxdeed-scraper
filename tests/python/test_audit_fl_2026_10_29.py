"""Audit fixes, Florida (2026-10-29; docs/review/audit-2026-10-28.md B1, B2, B3,
B15, B28).

B1  the deed sync dropped every listed auction lot without a street address;
B2  LienHub rows were keyed on the account, so a parcel holding several
    county-held certificates kept only one of them;
B3  Sarasota certificates were shown twice (LienHub's stale account-keyed copy
    beside the Tax Collector's own row);
B15 / B28  the FDOR and NAIP enrichment steps were killed by their step
    timeouts on every deeds run (one unresponsive county used the whole
    budget; the FDOR county scan saw only the first 1,000 outstanding rows).

The PowerShell checks run the real scripts under pwsh against the fake
Supabase of test_ledger_ps_syncs.py; they are skipped only where pwsh is
absent outside CI (that module fails in CI without it).
"""
from __future__ import annotations

import importlib
import importlib.util
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

PWSH = shutil.which("pwsh")
needs_pwsh = pytest.mark.skipif(not PWSH, reason="PowerShell (pwsh) not installed")


@pytest.fixture
def ps():
    if not PWSH:
        pytest.skip("PowerShell (pwsh) not installed")
    import test_ledger_ps_syncs as T  # noqa: PLC0415 - shares the fake Supabase
    return T


@pytest.fixture
def ws(tmp_path):
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    for f in (ROOT / "scripts").iterdir():
        if f.is_file():
            (scripts / f.name).symlink_to(f)
    (tmp_path / "out").mkdir()
    return tmp_path


# ------------------------------------------------------------------ B1

@needs_pwsh
def test_b1_deed_sync_keeps_a_listed_lot_without_a_street_address(ps, ws):
    ps.write(ws, "harvest_all.json", [
        ps.deed("Volusia", "V-1"),
        ps.deed("Volusia", "V-2", address=""),       # vacant lot: case number, no situs address
        ps.deed("Volusia", "V-3", address=None),
        ps.deed("Volusia", "", address="1 Main St"),  # no case number: unusable
    ])
    ps.write(ws, "harvest_all_status.json", [{"county": "Volusia", "status": "COMPLETE", "rowCount": 3}])
    fake = ps.FakeSupabase([ps.active(1, "Volusia", "V-2")])
    try:
        r = ps.run_ps(ws, "sync-harvest-to-supabase.ps1", fake)
    finally:
        fake.close()
    assert r.returncode == 0, r.stdout + r.stderr
    posted = {p["case_no"]: p for p in fake.posted_rows()}
    assert set(posted) == {"V-1", "V-2", "V-3"}
    assert posted["V-2"]["address"] == "" and posted["V-3"]["address"] == ""   # NOT NULL column: '' not null
    assert "(1 skipped for missing case #)" in r.stdout
    # The stored no-address lot is on the list, so the close-out leaves it alone.
    assert fake.patched_ids() == []


@needs_pwsh
def test_b1_an_empty_address_never_erases_a_stored_one(ps, ws):
    ps.write(ws, "harvest_all.json", [ps.deed("Volusia", "V-2", address="")])
    stored = {"id": 7, "county": "Volusia", "case_no": "V-2", "address": "9 Oak Ave", "field_provenance": {}}
    fake = ps.FakeSupabase(stored_rows=[stored])
    try:
        r = ps.run_ps(ws, "sync-harvest-to-supabase.ps1", fake)
    finally:
        fake.close()
    assert r.returncode == 0, r.stdout + r.stderr
    assert [p["address"] for p in fake.posted_rows()] == ["9 Oak Ave"]


# ------------------------------------------------------------------ B2

def test_b2_lienhub_rows_are_keyed_per_certificate_not_per_account():
    src = (ROOT / "scripts" / "harvest_lienhub_certificates.ps1").read_text(encoding="utf-8")
    assert "case_no         = $certKey" in src
    assert "case_no         = $d.account_number" not in src
    assert '$certKey = "$(([string]$d.tax_year).Trim())-$(([string]$d.certificate_number).Trim())"' in src
    assert "parcel          = $d.account_number" in src


@needs_pwsh
def test_b2_every_certificate_on_one_parcel_is_kept_and_the_account_row_is_superseded(ps, ws):
    certs = [
        {**ps.cert("Volusia", "2023-101"), "parcel": "ACC-1", "certificate_no": "101", "tax_year": 2023, "address": ""},
        {**ps.cert("Volusia", "2024-202"), "parcel": "ACC-1", "certificate_no": "202", "tax_year": 2024, "address": ""},
    ]
    ps.write(ws, "harvest_certificates.json", certs)
    ps.write(ws, "harvest_certificates_status.json", [{"county": "Volusia", "status": "COMPLETE", "rowCount": 2}])
    # 31: the old one-row-per-account key of the same parcel; 32: a certificate gone from the list.
    fake = ps.FakeSupabase([ps.active(31, "Volusia", "ACC-1"), ps.active(32, "Volusia", "ACC-9")])
    try:
        r = ps.run_ps(ws, "sync-certificates-to-supabase.ps1", fake)
    finally:
        fake.close()
    assert r.returncode == 0, r.stdout + r.stderr
    posted = fake.posted_rows()
    assert sorted(p["case_no"] for p in posted) == ["2023-101", "2024-202"]
    assert "De-duplicated" not in r.stdout
    # The address placeholder names the account, which the stored-value guard recognises.
    assert {p["address"] for p in posted} == {"Account ACC-1"}
    patches = {r_["path"].split("id=in.(", 1)[1].split(")", 1)[0]: r_["body"] for r_ in fake.of("PATCH")}
    assert patches == {"31": {"status": "closed"}, "32": {"status": "notfound"}}


def test_b2_account_placeholder_is_still_a_placeholder_under_the_certificate_key():
    import sync_value_guard as G
    row = {"case_no": "2024-202", "parcel": "ACC-1"}
    assert G.is_placeholder("certificate", "address", "Account ACC-1", row)


# ------------------------------------------------------------------ B3

def test_b3_lienhub_copies_of_a_listed_sarasota_certificate_are_superseded():
    import sync_sarasota_certificates as S
    kept = [{"case_no": "2024-3896", "parcel": "0123-45-6789", "certificate_no": "3896"},
            {"case_no": "2024-7745", "parcel": "0999-00-0001", "certificate_no": "7745"}]
    stored = [
        {"id": 1, "status": "active", "source_id": "fl_lienhub_certificates", "case_no": "0123456789",
         "parcel": "0123456789", "certificate_no": "3896"},                       # same cert, other key
        {"id": 2, "status": "active", "source_id": None, "case_no": "0999000001",
         "parcel": "0999000001", "certificate_no": "7745"},                       # pre-017 LienHub row
        {"id": 3, "status": "active", "source_id": "fl_lienhub_certificates", "case_no": "0123456789x",
         "parcel": "0123456789", "certificate_no": "4000"},                       # another certificate
        {"id": 4, "status": "closed", "source_id": "fl_lienhub_certificates", "case_no": "z",
         "parcel": "0123456789", "certificate_no": "3896"},                       # already closed
        {"id": 5, "status": "active", "source_id": "fl_sarasota_tc_certificates", "case_no": "2024-3896",
         "parcel": "0123-45-6789", "certificate_no": "3896"},                     # the TC row itself
        {"id": 6, "status": "active", "source_id": "fl_lienhub_certificates", "case_no": "2024-7745",
         "parcel": "0999-00-0001", "certificate_no": "7745"},                     # same key = same row
    ]
    assert S.superseded_plan(stored, kept) == [1, 2]
    # The TC close-out itself is unchanged: only its own rows absent from the read.
    assert S.close_plan(stored, {r["case_no"] for r in kept}) == []


# ------------------------------------------------------------------ B15 / B28: FDOR

@pytest.fixture
def fdor(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://example.test")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "not-a-real-key")
    spec = importlib.util.spec_from_file_location("_audit_fdor", ROOT / "scripts" / "enrich_property_details.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_audit_fdor"] = mod
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod.time, "sleep", lambda *_: None)
    monkeypatch.setattr(mod.random, "shuffle", lambda xs: None)
    monkeypatch.setattr(mod.random, "randrange", lambda *_: 0)
    monkeypatch.setattr(mod, "build_update_fields", lambda row, attrs, centroid: {"prop_type": "x"})
    monkeypatch.setattr(mod, "write_report", lambda report: None)
    return mod


class _Resp:
    def __init__(self, payload):
        self._p = payload
        self.status_code = 200
        self.text = ""

    def raise_for_status(self):
        return None

    def json(self):
        return self._p


def _fake_requests(mod, monkeypatch, rows_by_county, *, timeout_counties=()):
    lookups, patches = [], []

    def fake_get(url, headers=None, params=None, timeout=None):
        params = params or {}
        if "rest/v1/properties" in url:
            if params.get("select") == "county":
                allr = [{"county": c} for c, rows in rows_by_county.items() for _ in rows]
                off, lim = int(params.get("offset", 0)), int(params["limit"])
                return _Resp(allr[off:off + lim])
            if params.get("limit") == "0":
                return _Resp([])
            county = params["county"].split("eq.", 1)[1]
            rows = rows_by_county[county]
            return _Resp(rows[int(params["offset"]):int(params["offset"]) + int(params["limit"])])
        if url == mod.FDOR_ENDPOINT:
            where = params["where"]
            lookups.append(where)
            if any(f"'{c[:3].upper()}" in where for c in timeout_counties):
                raise mod.requests.ReadTimeout("slow")
            return _Resp({"features": [{"attributes": {"PARCEL_ID": "x"}, "centroid": {"x": -82.0, "y": 28.0}}]})
        raise AssertionError(url)

    def fake_patch(url, headers=None, json=None, timeout=None):
        patches.append(url.rsplit("eq.", 1)[1])
        return _Resp(None)

    monkeypatch.setattr(mod.requests, "get", fake_get)
    monkeypatch.setattr(mod.requests, "patch", fake_patch)
    return lookups, patches


def _rows(county, n):
    return [{"id": f"{county}-{i}", "source": "auction", "parcel": f"{county[:3].upper()}{i:05d}", "county": county}
            for i in range(n)]


def test_b15_an_unresponsive_county_is_abandoned_and_the_next_county_is_enriched(fdor, monkeypatch, capsys):
    rows = {"Hillsborough": _rows("Hillsborough", 20), "Lee": _rows("Lee", 5)}
    lookups, patches = _fake_requests(fdor, monkeypatch, rows, timeout_counties=("Hillsborough",))
    fdor.main()
    hill = [w for w in lookups if "'HIL" in w]
    # Abandoned after COUNTY_ERROR_STREAK timed-out rows, not all twenty.
    assert len({w.split("'")[1][:8] for w in hill}) == fdor.COUNTY_ERROR_STREAK == 3
    assert sorted(patches) == sorted(r["id"] for r in rows["Lee"])
    assert "consecutive request errors - abandoning" in capsys.readouterr().err


def test_b15_the_time_budget_stops_the_run_cleanly_with_a_summary(fdor, monkeypatch, capsys):
    rows = {"Lee": _rows("Lee", 5)}
    _fake_requests(fdor, monkeypatch, rows)
    clock = iter(range(0, 10_000, 100))
    monkeypatch.setattr(fdor.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(fdor, "TIME_BUDGET_SECONDS", 250)
    fdor.main()
    out = capsys.readouterr().out
    assert "Time budget of 250 s reached" in out and "Done. Attempted 1," in out


def test_b15_the_county_scan_reads_past_the_first_thousand_rows(fdor, monkeypatch):
    rows = {"Alachua": _rows("Alachua", 1000), "Lee": _rows("Lee", 3)}
    _fake_requests(fdor, monkeypatch, rows)
    assert dict(fdor.fetch_needing_enrichment_counties()) == {"Alachua": 1000, "Lee": 3}


def test_b28_deeds_job_runs_fdor_and_naip_with_budgets_below_their_timeouts():
    import yaml
    wf = yaml.safe_load((ROOT / ".github/workflows/harvest-and-sync.yml").read_text(encoding="utf-8"))
    steps = wf["jobs"]["deeds"]["steps"]
    fdor_step = next(s for s in steps if "enrich_property_details.py" in s.get("run", ""))
    naip_step = next(s for s in steps if "enrich_property_photos_naip.py" in s.get("run", ""))
    assert int(fdor_step["env"]["ENRICH_TIME_BUDGET_SECONDS"]) < fdor_step["timeout-minutes"] * 60
    assert int(naip_step["env"]["NAIP_TIME_BUDGET_SECONDS"]) < naip_step["timeout-minutes"] * 60
    assert "python3 -u " in fdor_step["run"] and "python3 -u " in naip_step["run"]


# ------------------------------------------------------------------ B28: NAIP

def test_b28_naip_time_budget_stops_before_the_step_timeout(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "test")
    sys.modules.pop("enrich_property_photos_naip", None)
    naip = importlib.import_module("enrich_property_photos_naip")
    monkeypatch.setattr(naip, "REQUEST_DELAY_SECONDS", 0)
    monkeypatch.setattr(naip, "storage_used_bytes", lambda *a, **k: 0)
    monkeypatch.setattr(naip, "fetch_counties_needing_photos", lambda flt=None: [(("FL", "Bay"), 5)])
    monkeypatch.setattr(naip, "fetch_county_batch",
                        lambda unit, limit, o=None, flt=None: [{"id": f"r{i}", "latitude": 30, "longitude": -85} for i in range(5)])
    fetched, reports = [], []
    monkeypatch.setattr(naip, "fetch_naip_image", lambda *a, **k: (fetched.append(1), (None, True))[1])
    monkeypatch.setattr(naip, "patch_property", lambda pid, f: None)
    monkeypatch.setattr(naip, "write_priority_report", reports.append)
    clock = iter(range(0, 10_000, 100))
    monkeypatch.setattr(naip.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(naip, "TIME_BUDGET_SECONDS", 250)
    assert naip.main() == 0
    assert len(fetched) == 2 and reports[0]["time_budget_reached"] is True
