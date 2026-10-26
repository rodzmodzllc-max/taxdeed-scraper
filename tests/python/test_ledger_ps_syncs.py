"""The Florida PowerShell syncs apply the three-ledger contract (2026-10-14).

These tests RUN the real scripts/sync-*.ps1 files under PowerShell 7 against a
local fake Supabase REST server and read what they would have written: every
POST (upsert), GET (close-out candidates) and PATCH (close-out). Nothing
leaves the machine. They prove:

  * rows reach the database only through scripts/ledger_gate.py (the record
    contract of harvesters/ledgers/records.py) - a row of another ledger is
    refused before any write, valid rows are written unchanged;
  * close-out happens only for a county the ledger health reader
    (harvesters/ledgers/health.py) calls COMPLETE or validly EMPTY: never after
    INCOMPLETE, FAILED, a transport/parse failure, an EMPTY without a signal,
    or a missing / unreadable status file;
  * a status entry naming another source never stands in for these syncs'
    own (source-less) county reads.

Skipped only where PowerShell is absent; under CI (GitHub's ubuntu runners
ship pwsh) a missing runtime FAILS rather than skipping silently.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
from datetime import date, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote

import pytest

ROOT = Path(__file__).resolve().parents[2]
PWSH = shutil.which("pwsh")
if not PWSH:
    if os.environ.get("CI"):
        pytest.fail("pwsh is required in CI to run the Florida PowerShell sync tests", pytrace=False)
    pytest.skip("PowerShell (pwsh) not installed", allow_module_level=True)

PAST = (date.today() - timedelta(days=10)).isoformat()


class FakeSupabase:
    """Records every request; GET /properties answers with `active_rows`
    filtered by the query's county=in.(...) list."""

    def __init__(self, active_rows=(), stored_rows=()):
        self.active_rows = list(active_rows)
        # Rows the stored-value guard (scripts/sync_value_guard.py) reads back:
        # its GET selects field_provenance and filters county=eq.<name>.
        self.stored_rows = list(stored_rows)
        self.fail_guard = False
        self.requests: list[dict] = []
        fake = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):  # quiet
                pass

            def _body(self):
                n = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(n) if n else b""
                try:
                    return json.loads(raw.decode("utf-8")) if raw else None
                except ValueError:
                    return raw.decode("utf-8", "replace")

            def _record(self, method):
                fake.requests.append({"method": method, "path": unquote(self.path), "body": self._body()})

            def do_POST(self):
                self._record("POST")
                self.send_response(201)
                self.end_headers()

            def do_PATCH(self):
                self._record("PATCH")
                self.send_response(204)
                self.end_headers()

            def do_GET(self):
                self._record("GET")
                path = unquote(self.path)
                rows = fake.active_rows
                if "field_provenance" in path and fake.fail_guard:
                    self.send_response(400)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                if "field_provenance" in path:
                    county = path.split("county=eq.", 1)[1].split("&", 1)[0].replace("+", " ")
                    rows = [r for r in fake.stored_rows if r["county"] == county and "id=gt." not in path]
                elif "county=in.(" in path:
                    allowed = set(path.split("county=in.(", 1)[1].split(")", 1)[0].split(","))
                    rows = [r for r in rows if r["county"] in allowed]
                data = json.dumps(rows).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()

    def of(self, method):
        """Requests of `method`; the stored-value guard's reads are listed by guard_reads()."""
        return [r for r in self.requests if r["method"] == method and not self._is_guard(r)]

    @staticmethod
    def _is_guard(r):
        return r["method"] == "GET" and "field_provenance" in r["path"]

    def guard_reads(self):
        return [r for r in self.requests if self._is_guard(r)]

    def posted_rows(self):
        out = []
        for r in self.of("POST"):
            out.extend(r["body"] if isinstance(r["body"], list) else [r["body"]])
        return out

    def patched_ids(self):
        ids = []
        for r in self.of("PATCH"):
            ids.extend(r["path"].split("id=in.(", 1)[1].split(")", 1)[0].split(","))
        return ids


@pytest.fixture
def workspace(tmp_path):
    """tmp/scripts holds symlinks to the real scripts (so $PSScriptRoot/../out
    is tmp/out); the Python they call resolves back to this repository."""
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    for f in (ROOT / "scripts").iterdir():
        if f.is_file():
            (scripts / f.name).symlink_to(f)
    (tmp_path / "out").mkdir()
    return tmp_path


def run_ps(workspace: Path, script: str, server: FakeSupabase) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k.upper() not in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY")}
    env.update(SUPABASE_URL=server.url, SUPABASE_SERVICE_KEY="test-key", NO_PROXY="127.0.0.1,localhost")
    return subprocess.run([PWSH, "-NoProfile", "-NonInteractive", "-File", str(workspace / "scripts" / script)],
                          env=env, capture_output=True, text=True, timeout=180)


def write(workspace: Path, name: str, data) -> None:
    (workspace / "out" / name).write_text(json.dumps(data), encoding="utf-8")


def deed(county, case, **kw):
    return {"county": county, "case": case, "parcel": f"P-{case}", "address": f"{case} Main St", "bid": 1000,
            "assessed": 5000, "sale_date": "12/01/2099", "appraiser": None, "auction_url": None, **kw}


def active(rid, county, case):
    return {"id": rid, "county": county, "case_no": case}


# ------------------------------------------------------------- deeds

def test_deeds_write_only_auction_rows_and_close_only_complete_counties(workspace):
    write(workspace, "harvest_all.json", [deed("Alachua", "A-1"), deed("Baker", "B-1"), deed("Clay", "C-1"), deed("Dixie", "D-1")])
    write(workspace, "harvest_all_status.json", [
        {"county": "Alachua", "status": "COMPLETE", "rowCount": 1},
        {"county": "Baker", "status": "INCOMPLETE", "rowCount": 1},
        {"county": "Clay", "status": "FAILED", "rowCount": 0, "error_category": "TRANSPORT_TIMEOUT"},
        {"county": "Dixie", "status": "COMPLETE", "rowCount": 1, "transport_ok": False},
    ])
    fake = FakeSupabase([active(11, "Alachua", "A-GONE"), active(12, "Baker", "B-GONE"),
                         active(13, "Clay", "C-GONE"), active(14, "Dixie", "D-GONE")])
    try:
        r = run_ps(workspace, "sync-harvest-to-supabase.ps1", fake)
    finally:
        fake.close()
    assert r.returncode == 0, r.stdout + r.stderr
    posted = fake.posted_rows()
    assert {p["case_no"] for p in posted} == {"A-1", "B-1", "C-1", "D-1"}
    assert all(p["source"] == "auction" for p in posted)
    # Only the COMPLETE, unbroken county is queried and closed.
    gets = fake.of("GET")
    assert len(gets) == 1 and "county=in.(Alachua)" in gets[0]["path"]
    assert fake.patched_ids() == ["11"]
    assert all(p["body"] == {"status": "closed"} for p in fake.of("PATCH"))


@pytest.mark.parametrize("status", [None, "not json {", []])
def test_deeds_missing_unreadable_or_empty_status_closes_nothing(workspace, status):
    write(workspace, "harvest_all.json", [deed("Alachua", "A-1")])
    if status is None:
        pass
    elif isinstance(status, str):
        (workspace / "out" / "harvest_all_status.json").write_text(status, encoding="utf-8")
    else:
        write(workspace, "harvest_all_status.json", status)
    fake = FakeSupabase([active(11, "Alachua", "A-GONE")])
    try:
        r = run_ps(workspace, "sync-harvest-to-supabase.ps1", fake)
    finally:
        fake.close()
    assert r.returncode == 0, r.stdout + r.stderr
    assert len(fake.posted_rows()) == 1
    assert fake.of("GET") == [] and fake.of("PATCH") == []


def test_deeds_another_sources_read_never_closes_this_syncs_rows(workspace):
    write(workspace, "harvest_all.json", [deed("Alachua", "A-1")])
    # A COMPLETE read that names a different source (a Texas auction source and
    # an Available source) is not this sync's county read.
    write(workspace, "harvest_all_status.json", [
        {"county": "Alachua", "status": "COMPLETE", "rowCount": 3, "source_id": "tx_realauction"},
        {"county": "Alachua", "status": "COMPLETE", "rowCount": 3, "source_id": "fl_laft_pdfs"},
    ])
    fake = FakeSupabase([active(11, "Alachua", "A-GONE")])
    try:
        r = run_ps(workspace, "sync-harvest-to-supabase.ps1", fake)
    finally:
        fake.close()
    assert r.returncode == 0, r.stdout + r.stderr
    assert fake.of("PATCH") == []


def test_deeds_a_failed_retry_of_a_county_blocks_its_close_out(workspace):
    write(workspace, "harvest_all.json", [deed("Alachua", "A-1")])
    write(workspace, "harvest_all_status.json", [
        {"county": "Alachua", "status": "COMPLETE", "rowCount": 1},
        {"county": "Alachua", "status": "INCOMPLETE", "rowCount": 0},
    ])
    fake = FakeSupabase([active(11, "Alachua", "A-GONE")])
    try:
        run_ps(workspace, "sync-harvest-to-supabase.ps1", fake)
    finally:
        fake.close()
    assert fake.of("PATCH") == []


# ------------------------------------------------------------- certificates

def cert(county, case, **kw):
    return {"county": county, "case_no": case, "certificate_no": case, "tax_year": 2024, "issued_date": "06/01/2025",
            "bid": "812.50", "address": f"{case} Oak St", "parcel": f"P-{case}", **kw}


def test_certificates_reconcile_only_valid_complete_or_empty_reads(workspace):
    write(workspace, "harvest_certificates.json", [cert("Alachua", "C-1")])
    write(workspace, "harvest_certificates_status.json", [
        {"county": "Alachua", "status": "COMPLETE", "rowCount": 1},
        {"county": "Baker", "status": "EMPTY", "rowCount": 0},                              # no empty signal
        {"county": "Clay", "status": "EMPTY", "rowCount": 0, "empty_signal": "reported_count_zero"},
        {"county": "Dixie", "status": "INCOMPLETE", "rowCount": 0},
        {"county": "Duval", "status": "FAILED", "error_category": "TRANSPORT_HTTP_403_BLOCKED"},
    ])
    fake = FakeSupabase([active(21, "Alachua", "C-GONE"), active(22, "Baker", "X"), active(23, "Clay", "Y"),
                         active(24, "Dixie", "Z"), active(25, "Duval", "W")])
    try:
        r = run_ps(workspace, "sync-certificates-to-supabase.ps1", fake)
    finally:
        fake.close()
    assert r.returncode == 0, r.stdout + r.stderr
    posted = fake.posted_rows()
    assert [p["case_no"] for p in posted] == ["C-1"] and posted[0]["source"] == "certificate"
    # A certificate row carries no property-sale field.
    assert not {"result_amount", "result_date", "result_party", "winning_bid"} & set(posted[0])
    assert sorted(fake.patched_ids()) == ["21", "23"]
    assert all(p["body"] == {"status": "notfound"} for p in fake.of("PATCH"))


# ------------------------------------------------------------- LAFT

def test_laft_sync_writes_only_available_rows_and_never_closes(workspace):
    write(workspace, "harvest_laft.json", [{"county": "Alachua", "case_no": "L-1", "parcel": "12-34", "bid": "500"}])
    fake = FakeSupabase([active(31, "Alachua", "L-GONE")])
    try:
        r = run_ps(workspace, "sync-laft-to-supabase.ps1", fake)
    finally:
        fake.close()
    assert r.returncode == 0, r.stdout + r.stderr
    posted = fake.posted_rows()
    assert [p["case_no"] for p in posted] == ["L-1"] and posted[0]["source"] == "laft"
    assert fake.of("PATCH") == [] and fake.of("GET") == []


# ------------------------------------------------------------- the PowerShell helper itself

BLOCK_START = "# --- Three-ledger contract (2026-10-14) "
BLOCK_END = "# --- end three-ledger contract "
SYNCS = ("sync-harvest-to-supabase.ps1", "sync-certificates-to-supabase.ps1", "sync-laft-to-supabase.ps1")


def helper_block(name: str) -> str:
    text = (ROOT / "scripts" / name).read_text(encoding="utf-8")
    s, e = text.index(BLOCK_START), text.index(BLOCK_END)
    return text[s:e]


def test_the_three_syncs_carry_one_identical_helper():
    blocks = {helper_block(n) for n in SYNCS}
    assert len(blocks) == 1
    for n in SYNCS:
        text = (ROOT / "scripts" / n).read_text(encoding="utf-8")
        # The helper sits after the permission guard and before any request.
        assert text.index("# --- end source permission gate ") < text.index(BLOCK_START)
        # The first executable (non-comment) line that makes a request.
        offset, first_request = 0, None
        for line in text.split("\n"):
            if "Invoke-RestMethod" in line and not line.lstrip().startswith("#"):
                first_request = offset
                break
            offset += len(line) + 1
        assert first_request is not None
        assert text.index(BLOCK_END) < first_request
        # Every write path goes through the row contract first.
        assert text.index("Select-LedgerRows \"") < first_request


@pytest.mark.parametrize("ledger,rows,kept", [
    ("AUCTIONS", [{"source": "auction", "county": "A", "case_no": "1"},
                  {"source": "laft", "county": "A", "case_no": "2"},
                  {"source": "certificate", "county": "A", "case_no": "3"},
                  {"source": "auction", "county": "A", "case_no": "4", "inventory_type": "POST_SALE_FIXED_PRICE"}], ["1"]),
    ("LIENS_CERTIFICATES", [{"source": "certificate", "county": "A", "case_no": "1", "issued_date": "2025-06-01"},
                            {"source": "certificate", "county": "A", "case_no": "2", "result_amount": 900},
                            {"source": "auction", "county": "A", "case_no": "3"}], ["1"]),
    ("AVAILABLE", [{"source": "laft", "county": "A", "case_no": "1"},
                   {"source": "laft", "county": "A", "case_no": "2", "ledger_type": "auctions"},
                   {"source": "laft", "county": "A", "case_no": "3", "purchase_amount": 10}], ["1"]),
    ("AUCTIONS", [{"source": "auction", "county": "A", "case_no": "only"}], ["only"]),
])
def test_select_ledger_rows_in_powershell(workspace, ledger, rows, kept):
    (workspace / "scripts" / "helper_under_test.ps1").write_text(
        "$ErrorActionPreference = 'Stop'\n" + helper_block(SYNCS[0]) +
        f"\n$rows = Get-Content (Join-Path $PSScriptRoot 'rows.json') -Raw | ConvertFrom-Json\n"
        f"$kept = @(Select-LedgerRows '{ledger}' $rows)\n"
        "@($kept | ForEach-Object { $_.case_no }) | ConvertTo-Json -Compress\n", encoding="utf-8")
    (workspace / "scripts" / "rows.json").write_text(json.dumps(rows), encoding="utf-8")
    r = subprocess.run([PWSH, "-NoProfile", "-NonInteractive", "-File", str(workspace / "scripts" / "helper_under_test.ps1")],
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    out = json.loads(r.stdout.strip().splitlines()[-1])
    assert (out if isinstance(out, list) else [out]) == kept


def test_select_ledger_rows_fails_closed_without_the_gate(workspace):
    (workspace / "scripts" / "ledger_gate.py").unlink()
    (workspace / "scripts" / "ledger_gate.py").write_text("import sys; sys.exit(2)\n", encoding="utf-8")
    write(workspace, "harvest_all.json", [deed("Alachua", "A-1")])
    fake = FakeSupabase()
    try:
        r = run_ps(workspace, "sync-harvest-to-supabase.ps1", fake)
    finally:
        fake.close()
    assert r.returncode != 0
    assert fake.requests == []          # nothing written, nothing read
