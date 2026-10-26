"""Syncs write only what changed (2026-10-26, production overload).

scripts/write_diff_filter.py is the I/O half of scripts/write_diff.py: it
reads the stored rows for the identities a sync is about to upsert and keeps
only the rows `write_diff.split` says need a write. These tests prove, for the
CLI, the three Florida PowerShell syncs (run for real under pwsh against a
local fake PostgREST), the Texas sync and the Sarasota certificate sync:

  * an unchanged row whose stored last_seen_at is fresh is NOT sent;
  * a changed row IS sent, and a new row IS sent;
  * an unchanged row whose stored last_seen_at is stale is sent (once: the
    next run sees it fresh);
  * a stored-row read failure sends every row (fail open - a read error never
    loses a sync);
  * close-out still decides on what was harvested, not on what was written;
  * the log carries counts only, never a parcel, an address or an owner.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import write_diff_filter as WDF  # noqa: E402

NOW = datetime.now(timezone.utc).replace(microsecond=0)
FRESH = (NOW - timedelta(hours=2)).isoformat()
STALE = (NOW - timedelta(hours=30)).isoformat()


def _fetch_from(stored, calls=None):
    def fetch(qs):
        if calls is not None:
            calls.append(qs)
        return [] if "id=gt." in qs else [dict(s) for s in stored]
    return fetch


# ---------------------------------------------------------------- the filter

def test_filter_rows_skips_fresh_unchanged_sends_changed_new_and_stale():
    rows = [
        {"state": "FL", "source": "certificate", "county": "Lee", "case_no": "1", "bid": 100, "last_seen_at": NOW.isoformat()},
        {"state": "FL", "source": "certificate", "county": "Lee", "case_no": "2", "bid": 200, "last_seen_at": NOW.isoformat()},
        {"state": "FL", "source": "certificate", "county": "Lee", "case_no": "3", "bid": 300, "last_seen_at": NOW.isoformat()},
        {"state": "FL", "source": "certificate", "county": "Lee", "case_no": "4", "bid": 400, "last_seen_at": NOW.isoformat()},
    ]
    stored = [
        {"id": 1, "state": "FL", "source": "certificate", "county": "Lee", "case_no": "1", "bid": "100.00", "last_seen_at": FRESH},
        {"id": 2, "state": "FL", "source": "certificate", "county": "Lee", "case_no": "2", "bid": 250, "last_seen_at": FRESH},
        {"id": 3, "state": "FL", "source": "certificate", "county": "Lee", "case_no": "3", "bid": 300, "last_seen_at": STALE},
    ]
    calls: list[str] = []
    logs: list[str] = []
    keep, counts = WDF.filter_rows(rows, state="FL", base="http://x", key="k", fetch=_fetch_from(stored, calls),
                                   log=logs.append)
    assert [r["case_no"] for r in keep] == ["2", "3", "4"]
    assert counts == {"new": 1, "changed": 1, "restamp": 1, "unchanged_skipped": 1}
    # One keyset read: only the sent columns + identity + last_seen_at, scoped by state / source / county.
    assert len(calls) == 1
    q = calls[0]
    assert "select=bid,case_no,county,id,last_seen_at,source,state" in q
    assert "state=eq.FL" in q and "source=eq.certificate" in q and "county=in.(%22Lee%22)" in q
    assert "order=id.asc" in q and "offset" not in q
    # Counts only in the log.
    assert len(logs) == 1 and "unchanged_skipped=1" in logs[0] and "Lee" not in logs[0]


def test_filter_rows_second_run_same_day_writes_nothing():
    row = {"state": "FL", "source": "certificate", "county": "Lee", "case_no": "1", "bid": 100, "last_seen_at": NOW.isoformat()}
    stored = [{"id": 1, **row, "last_seen_at": STALE}]
    keep, counts = WDF.filter_rows([row], state="FL", base="http://x", key="k", fetch=_fetch_from(stored), log=lambda m: None)
    assert counts["restamp"] == 1
    stored = [{"id": 1, **keep[0]}]            # what the first run wrote
    keep, counts = WDF.filter_rows([row], state="FL", base="http://x", key="k", fetch=_fetch_from(stored), log=lambda m: None)
    assert keep == [] and counts["unchanged_skipped"] == 1


def test_filter_rows_identity_is_state_source_county_case():
    rows = [{"source": "auction", "county": "Orange", "case_no": "1", "bid": 1}]
    stored = [{"id": 1, "state": "TX", "source": "auction", "county": "Orange", "case_no": "1", "bid": 1},
              {"id": 2, "state": "FL", "source": "laft", "county": "Orange", "case_no": "1", "bid": 1}]
    keep, counts = WDF.filter_rows(rows, state="FL", base="http://x", key="k", fetch=_fetch_from(stored), log=lambda m: None)
    assert keep == rows and counts["new"] == 1


@pytest.mark.parametrize("exc", [urllib.error.HTTPError("u", 500, "x", {}, None), urllib.error.URLError("down"),
                                 TimeoutError(), ValueError("bad json")])
def test_filter_rows_fails_open_on_read_failure(exc):
    rows = [{"state": "FL", "source": "auction", "county": "Lee", "case_no": str(i), "bid": i} for i in range(3)]

    def fetch(qs):
        raise exc
    logs: list[str] = []
    keep, counts = WDF.filter_rows(rows, state="FL", base="http://x", key="k", fetch=fetch, log=logs.append)
    assert keep == rows and counts["read_failed"] == 1
    assert "fail open" in logs[0]


def test_filter_rows_fails_open_without_credentials(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_KEY", raising=False)
    rows = [{"source": "auction", "county": "Lee", "case_no": "1"}]
    keep, counts = WDF.filter_rows(rows, state="FL", log=lambda m: None)
    assert keep == rows and counts["read_failed"] == 1


def test_counties_are_chunked_into_short_urls():
    rows = [{"source": "laft", "county": f"County {i}", "case_no": "1"} for i in range(WDF.COUNTY_CHUNK * 2 + 1)]
    calls: list[str] = []
    WDF.filter_rows(rows, state="FL", base="http://x", key="k", fetch=_fetch_from([], calls), log=lambda m: None)
    assert len(calls) == 3


def test_cli_writes_kept_rows_and_counts_only(tmp_path, monkeypatch, capsys):
    rows = [{"source": "laft", "county": "Lee", "case_no": "1", "address": "1 Secret St", "bid": 5},
            {"source": "laft", "county": "Lee", "case_no": "2", "address": "2 Secret St", "bid": 6}]
    stored = [{"id": 1, "state": "FL", "source": "laft", "county": "Lee", "case_no": "1", "address": "1 Secret St", "bid": 5}]
    monkeypatch.setattr(WDF, "read_stored", lambda base, key, *, state, rows, fetch=None: stored)
    monkeypatch.setenv("SUPABASE_URL", "http://x")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "k")
    (tmp_path / "in.json").write_text(json.dumps(rows))
    assert WDF.main(["--state", "FL", "--source", "laft", "--in", str(tmp_path / "in.json"),
                     "--out", str(tmp_path / "out.json")]) == 0
    assert [r["case_no"] for r in json.loads((tmp_path / "out.json").read_text())] == ["2"]
    err = capsys.readouterr()
    assert err.out == ""                       # nothing on stdout (PowerShell would read it as rows)
    assert "Secret" not in err.err and "unchanged_skipped=1" in err.err


def test_cli_unreadable_input_exits_2(tmp_path):
    (tmp_path / "in.json").write_text("not json {")
    assert WDF.main(["--in", str(tmp_path / "in.json"), "--out", str(tmp_path / "o.json")]) == 2


# --------------------------------------------------- the PowerShell syncs

try:
    import test_ledger_ps_syncs as PS  # noqa: E402  (skips the module when pwsh is absent)
except BaseException:  # pytest.skip raises a BaseException subclass
    PS = None
needs_pwsh = pytest.mark.skipif(PS is None, reason="PowerShell (pwsh) not installed")
workspace = PS.workspace if PS is not None else None


def _deed_stored(rid, county, case, **kw):
    """The stored copy of PS.deed(county, case) exactly as the deeds sync sends it."""
    row = {"id": rid, "state": "FL", "source": "auction", "county": county, "case_no": case, "parcel": f"P-{case}",
           "address": f"{case} Main St", "bid": 1000, "assessed": 5000, "sale_date": "2099-12-01",
           "url_appraiser": None, "url_auction": None, "status": "active", "delisted_at": None,
           "url_auction_kind": None, "last_seen_at": FRESH}
    row.update(kw)
    return row


@needs_pwsh
def test_deeds_sync_sends_only_new_and_changed_rows_and_still_closes_on_the_harvest(workspace):
    PS.write(workspace, "harvest_all.json", [PS.deed("Alachua", "A-1"), PS.deed("Alachua", "A-2"), PS.deed("Alachua", "A-3")])
    PS.write(workspace, "harvest_all_status.json", [{"county": "Alachua", "status": "COMPLETE", "rowCount": 3}])
    fake = PS.FakeSupabase([PS.active(11, "Alachua", "A-GONE"), PS.active(12, "Alachua", "A-1")],
                           diff_rows=[_deed_stored(12, "Alachua", "A-1"),                 # unchanged, fresh
                                      _deed_stored(13, "Alachua", "A-2", bid="900.00")])  # changed bid
    try:
        r = PS.run_ps(workspace, "sync-harvest-to-supabase.ps1", fake)
    finally:
        fake.close()
    assert r.returncode == 0, r.stdout + r.stderr
    assert sorted(p["case_no"] for p in fake.posted_rows()) == ["A-2", "A-3"]
    assert len(fake.diff_reads()) == 1
    # A-1 was not rewritten but is still listed: only A-GONE closes.
    assert fake.patched_ids() == ["11"]
    log = r.stdout + r.stderr
    assert "new=1 changed=1 restamp=0 unchanged_skipped=1" in log
    assert "Main St" not in log and "P-A-" not in log


@needs_pwsh
def test_deeds_sync_sends_every_row_when_the_stored_read_fails(workspace):
    PS.write(workspace, "harvest_all.json", [PS.deed("Alachua", "A-1"), PS.deed("Alachua", "A-2")])
    fake = PS.FakeSupabase(diff_rows=[_deed_stored(12, "Alachua", "A-1"), _deed_stored(13, "Alachua", "A-2")])
    fake.fail_diff = True
    try:
        r = PS.run_ps(workspace, "sync-harvest-to-supabase.ps1", fake)
    finally:
        fake.close()
    assert r.returncode == 0, r.stdout + r.stderr
    assert sorted(p["case_no"] for p in fake.posted_rows()) == ["A-1", "A-2"]
    assert "fail open" in r.stdout + r.stderr


@needs_pwsh
def test_deeds_sync_with_nothing_changed_posts_nothing(workspace):
    PS.write(workspace, "harvest_all.json", [PS.deed("Alachua", "A-1")])
    fake = PS.FakeSupabase(diff_rows=[_deed_stored(12, "Alachua", "A-1")])
    try:
        r = PS.run_ps(workspace, "sync-harvest-to-supabase.ps1", fake)
    finally:
        fake.close()
    assert r.returncode == 0, r.stdout + r.stderr
    assert fake.of("POST") == []


@needs_pwsh
def test_laft_sync_sends_only_changed_rows(workspace):
    laft = {"county": "Lee", "case_no": "L-1", "parcel": "PL-1", "address": "1 Elm", "bid": "500", "sale_date": None,
            "url_auction": None}
    PS.write(workspace, "harvest_laft.json", [laft, {**laft, "case_no": "L-2", "address": "2 Elm"}])
    stored = {"state": "FL", "source": "laft", "county": "Lee", "address": "1 Elm", "bid": 500, "status": "active",
              "url_auction": None, "url_auction_kind": None, "parcel": "PL-1", "sale_date": None, "last_seen_at": FRESH}
    fake = PS.FakeSupabase(diff_rows=[{"id": 1, "case_no": "L-1", **stored},
                                      {"id": 2, "case_no": "L-2", **stored, "address": "2 Elm", "status": "closed"}])
    try:
        r = PS.run_ps(workspace, "sync-laft-to-supabase.ps1", fake)
    finally:
        fake.close()
    assert r.returncode == 0, r.stdout + r.stderr
    # L-2 had been closed: listed again => status changes => written.
    assert [p["case_no"] for p in fake.posted_rows()] == ["L-2"]


@needs_pwsh
def test_certificate_sync_sends_only_changed_rows_and_reconciles_on_the_harvest(workspace):
    cert = {"county": "Lee", "case_no": "C-1", "certificate_no": "100", "tax_year": "2024", "issued_date": None,
            "expiration_date": None, "bid": "250", "address": "1 Oak", "owner_name": None, "parcel": "PC-1",
            "assessed": None, "interest_rate": "18", "url_auction": None}
    PS.write(workspace, "harvest_certificates.json", [cert, {**cert, "case_no": "C-2", "interest_rate": "5"}])
    PS.write(workspace, "harvest_certificates_status.json", [{"county": "Lee", "status": "COMPLETE", "rowCount": 2}])
    stored = {"state": "FL", "source": "certificate", "county": "Lee", "certificate_no": "100", "tax_year": 2024,
              "issued_date": None, "expiration_date": None, "bid": 250, "address": "1 Oak", "owner_name": None,
              "parcel": "PC-1", "assessed": None, "interest_rate": 18, "url_auction": None, "url_auction_kind": None,
              "status": "active", "delisted_at": None, "last_seen_at": FRESH}
    fake = PS.FakeSupabase([PS.active(21, "Lee", "C-1"), PS.active(22, "Lee", "C-GONE")],
                           diff_rows=[{"id": 21, "case_no": "C-1", **stored}, {"id": 23, "case_no": "C-2", **stored}])
    try:
        r = PS.run_ps(workspace, "sync-certificates-to-supabase.ps1", fake)
    finally:
        fake.close()
    assert r.returncode == 0, r.stdout + r.stderr
    assert [p["case_no"] for p in fake.posted_rows()] == ["C-2"]     # interest rate 18 -> 5
    assert fake.patched_ids() == ["22"]                              # C-1 unwritten, still listed


@needs_pwsh
def test_the_helper_block_is_identical_in_all_three_syncs():
    start, end = "# --- Write only what changed (2026-10-26)", "# --- end write only what changed"
    blocks = []
    for name in ("sync-harvest-to-supabase.ps1", "sync-laft-to-supabase.ps1", "sync-certificates-to-supabase.ps1"):
        text = (ROOT / "scripts" / name).read_text(encoding="utf-8")
        blocks.append(text[text.index(start):text.index(end)])
        assert "$writeRows = @(Select-ChangedRows" in text
    assert blocks[0] == blocks[1] == blocks[2]


# ------------------------------------------------------------ Texas sync

def _texas_module(monkeypatch, tmp_path, fixture, stored, *, fail=False):
    out = tmp_path / "out"
    out.mkdir(exist_ok=True)
    (out / "harvest_texas.json").write_text(json.dumps(fixture))
    spec = importlib.util.spec_from_file_location("sync_tx_wd", str(ROOT / "scripts" / "sync-texas-to-supabase.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "JSON_PATH", out / "harvest_texas.json")
    monkeypatch.setenv("SUPABASE_URL", "http://example.invalid")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "test-fixture-not-a-real-key")
    posted: list[dict] = []
    gets: list[str] = []

    class _R:
        def __init__(self, body=b""):
            self.body = body

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return self.body

    def _urlopen(req, timeout=60):
        if req.get_method() == "GET":
            gets.append(req.full_url)
            if fail:
                raise urllib.error.HTTPError(req.full_url, 400, "bad", {}, None)
            return _R(json.dumps([] if "id=gt." in req.full_url else stored).encode())
        posted.extend(json.loads(req.data))
        return _R()

    monkeypatch.setattr(mod.urllib.request, "urlopen", _urlopen)
    return mod, posted, gets


TX = {"state": "TX", "auction_date": "2099-10-06", "min_bid": 100.0, "cad_market_value": 1000.0,
      "legal_description": None, "address": "1 A St", "latitude": None, "longitude": None, "county": "Galveston",
      "source": "auction", "harvester_source": "tx_lgbs", "auction_url": None, "auction_url_kind": None,
      "sale_status": None}


def test_texas_sync_writes_only_changed_rows(monkeypatch, tmp_path):
    fixture = [dict(TX, account_number="A-1", cause_number="C-1"), dict(TX, account_number="A-2", cause_number="C-2")]
    mod, first, _ = _texas_module(monkeypatch, tmp_path, fixture, [])
    mod.main()
    assert sorted(r["case_no"] for r in first) == ["A-1", "A-2"]
    stored = [{"id": i, **r, "last_seen_at": FRESH} for i, r in enumerate(first)]
    stored[1]["min_bid"] = 50.0                    # A-2 changed at the source
    mod, second, gets = _texas_module(monkeypatch, tmp_path, fixture, stored)
    mod.main()
    assert [r["case_no"] for r in second] == ["A-2"]
    assert gets and all("state=eq.TX" in g for g in gets)


def test_texas_sync_writes_everything_when_the_read_fails(monkeypatch, tmp_path):
    fixture = [dict(TX, account_number="A-1", cause_number="C-1")]
    mod, posted, _ = _texas_module(monkeypatch, tmp_path, fixture, [], fail=True)
    mod.main()
    assert [r["case_no"] for r in posted] == ["A-1"]


# ---------------------------------------------------------- laft lifecycle

def test_lifecycle_provenance_patch_carries_the_freshness_guard():
    import laft_lifecycle as LL

    class Api:
        def __init__(self):
            self.patches = []

        def patch(self, query, body):
            self.patches.append(query)

    plan = LL.Plan(observe=[("Lee", "L-1")], reactivate=[("Lee", "L-2")], close=[])
    gates = {"Lee": {"status": "COMPLETE", "entry": {}, "harvester": "fl_laft_pdf"}}
    observed = {"Lee": {"L-1": {"county": "Lee", "case_no": "L-1"}}}
    api = Api()
    LL.execute(plan, gates, observed, api, state="FL", have_017=True, retrieved_at=NOW.isoformat())
    reactivate, provenance = api.patches
    assert "last_seen_at" not in reactivate                       # reactivation is never gated
    assert "&or=(last_seen_at.is.null,last_seen_at.lt." in provenance
    api = Api()
    LL.execute(plan, gates, observed, api, state="FL", have_017=True, retrieved_at=NOW.isoformat(), fresh_guard=False)
    assert "last_seen_at" not in api.patches[1]


def test_louisiana_lifecycle_step_opts_out_of_the_guard():
    wf = (ROOT / ".github" / "workflows" / "harvest-and-sync.yml").read_text(encoding="utf-8")
    line = next(l for l in wf.splitlines() if "laft_lifecycle.py --state LA" in l)
    assert "--no-fresh-guard" in line
    fl = next(l for l in wf.splitlines() if l.strip() == "run: python3 scripts/laft_lifecycle.py")
    assert "--no-fresh-guard" not in fl


# ------------------------------------------------------------- schedule

def test_second_daily_reads_run_outside_us_daytime():
    import yaml
    wf = yaml.safe_load((ROOT / ".github" / "workflows" / "harvest-and-sync.yml").read_text(encoding="utf-8"))
    crons = [c["cron"] for c in (wf.get("on") or wf.get(True))["schedule"]]
    assert crons == ["13 10 * * *", "13 4 * * *", "37 11 * * *", "37 3 * * *"]
    # No scheduled run between 14:00 and 23:59 UTC (10 AM - 8 PM ET in EDT).
    assert all(not 14 <= int(c.split()[1]) <= 23 for c in crons)
