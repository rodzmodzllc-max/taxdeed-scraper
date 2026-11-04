"""Regression tests for the second half of the 2026-10-26 read-failure sweep.

1. LienHub has answered 403 to every GitHub runner request since 2026-10-01;
   each run spent ~35 minutes retrying 32 refused counties (#366, #374). The
   harvester now stops requesting after three counties in a row are refused
   on every attempt and records the rest FAILED / TRANSPORT_HTTP_403_BLOCKED
   (a reader's SOURCE_UNAVAILABLE - nothing stamped, reconciled or closed).
   The test runs the REAL PowerShell harvester against a local fake that
   answers like the real site does to a runner (HTTP 403 to the page GET).
2. The Texas RealAuction read check (scripts/tx_realauction_check.py) reads
   blocks from the raw response exactly as harvest_realauction() does.
3. The geocoder's per-row lines (which carry placeholder parcel numbers) are
   off in the public job log.
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import threading
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

PWSH = shutil.which("pwsh")


class FakeLienHub:
    """403 to the county page GET, unless the county slug is in `ok`: then
    the page carries the csrf meta tag and the DataTables POST answers
    recordsTotal / data (an empty county)."""

    def __init__(self, ok=()):
        self.ok, self.gets = set(ok), []
        fake = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, body, ctype="text/html"):
                data = body.encode()
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                slug = self.path.split("/county/")[1].split("/")[0]
                fake.gets.append(slug)
                if slug in fake.ok:
                    return self._send(200, '<html><head><meta name="csrf_token" content="tok"></head></html>')
                return self._send(403, "<html>Forbidden</html>")

            def do_POST(self):
                self.rfile.read(int(self.headers.get("Content-Length") or 0))
                return self._send(200, json.dumps({"recordsTotal": 0, "data": []}), "application/json")

        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.srv.server_address[1]}"

    def close(self):
        self.srv.shutdown()


def run_lienhub(tmp_path, counties, ok=()):
    if not PWSH:
        if os.environ.get("CI"):
            pytest.fail("pwsh is required in CI to run the LienHub harvester tests", pytrace=False)
        pytest.skip("PowerShell (pwsh) not installed")
    reg = tmp_path / "platforms.csv"
    reg.write_text("County,Platform,CertSaleWebsite\n" + "".join(f"{c},LienHub,x\n" for c in counties))
    out = tmp_path / "out"
    fake = FakeLienHub(ok)
    try:
        env = {**os.environ, "LIENHUB_REGISTRY": str(reg), "LIENHUB_OUT_DIR": str(out), "LIENHUB_BASE": fake.base,
               "LIENHUB_BACKOFFS": "0,0", "LIENHUB_COUNTY_DELAY": "0"}
        r = subprocess.run([PWSH, "-NoProfile", "-File", str(REPO / "scripts/harvest_lienhub_certificates.ps1")],
                           capture_output=True, text=True, env=env, timeout=300)
        assert r.returncode == 0, r.stdout + r.stderr
        status = json.loads((out / "harvest_certificates_status.json").read_text(encoding="utf-8-sig"))
        status = status if isinstance(status, list) else [status]
        return {s["county"]: s for s in status}, fake.gets, r.stdout
    finally:
        fake.close()


COUNTIES = ["Alachua", "Bay", "Brevard", "Broward", "Charlotte", "Citrus"]


def test_lienhub_stops_requesting_after_three_counties_refused_on_every_attempt(tmp_path):
    from harvesters.ledgers import health
    status, gets, out = run_lienhub(tmp_path, COUNTIES)
    # Three counties x three attempts each, then no further request.
    assert gets == ["alachua"] * 3 + ["bay"] * 3 + ["brevard"] * 3
    assert set(status) == set(COUNTIES)
    for c in COUNTIES:
        e = status[c]
        assert e["status"] == "FAILED" and e["error_category"] == "TRANSPORT_HTTP_403_BLOCKED", e
        assert health.reader_status(e) == "SOURCE_UNAVAILABLE"
    assert "not requested" in status["Broward"]["reason"]
    assert "0 COMPLETE, 0 INCOMPLETE, 6 FAILED" in out


def test_lienhub_a_county_that_answers_breaks_the_run_of_refusals(tmp_path):
    status, gets, _ = run_lienhub(tmp_path, COUNTIES, ok={"brevard"})
    assert gets == (["alachua"] * 3 + ["bay"] * 3 + ["brevard"]
                    + ["broward"] * 3 + ["charlotte"] * 3 + ["citrus"] * 3)
    assert status["Brevard"]["status"] == "COMPLETE"
    assert all(status[c]["status"] == "FAILED" for c in COUNTIES if c != "Brevard")


def test_lienhub_blocked_counties_are_never_reconciled_or_stamped():
    """The sync and stamp_seen act only on COMPLETE / EMPTY; the ledger gate
    reads FAILED + TRANSPORT_ as SOURCE_UNAVAILABLE."""
    from harvesters.ledgers import health
    e = {"county": "Alachua", "status": "FAILED", "error_category": "TRANSPORT_HTTP_403_BLOCKED",
         "transport_ok": False, "rowCount": 0}
    assert health.reader_status(e) == "SOURCE_UNAVAILABLE"
    assert health.ledger_units([{**e, "source_id": "fl_lienhub_certificates"}])[("fl_lienhub_certificates", "Alachua")] \
        == "SOURCE_UNAVAILABLE"


# ---------------------------------------------------------------------------
# Texas RealAuction read check
# ---------------------------------------------------------------------------

def test_tx_check_reads_labels_from_the_raw_json_escaped_response():
    """Run 40384532568: each of the five 'sale date found but 0 parsed'
    counties had one sale day, already past, whose items sit in the Closed
    area - the Waiting area is genuinely empty. The check must read the RAW
    response as harvest_realauction() does (escaped quotes); decoding the
    JSON first made every label read False."""
    import tx_realauction_check as T
    html = ('<div id="AITEM_9000001">@A@E_DETAILS"><table><tr><th @CAD_LBL" scope="row">Account Number:'
            '</th><td @CAD_DTA">00000000000000001</td></tr>'
            '<tr><th @CAD_LBL" scope="row">Cause Number:</th><td @CAD_DTA">TX-00-00000</td></tr></table>')
    raw = json.dumps({"retHTML": html, "rlist": "9000001"})
    blocks = T.blocks_of(raw)
    assert len(blocks) == 1
    shape = T.block_shape(blocks[0])
    assert shape["harvester_reads"]["Account Number"] is True
    assert shape["harvester_reads"]["Cause Number"] is True
    assert "Account Number" in shape["labels_on_page"]
    assert not any(ch.isdigit() for lab in shape["labels_on_page"] for ch in lab)


def test_tx_check_names_a_past_sale_day_as_past():
    import tx_realauction_check as T
    assert T.relative_day("10/06/2026", date(2026, 10, 26)) == "past (20 d ago)"
    assert T.relative_day("10/26/2026", date(2026, 10, 26)) == "today"
    assert T.relative_day("11/02/2026", date(2026, 10, 26)) == "future (in 7 d)"


# ---------------------------------------------------------------------------
# Geocoder: the public job log carries counts only
# ---------------------------------------------------------------------------

def test_geocode_row_lines_are_off_unless_asked_for(monkeypatch, capsys):
    monkeypatch.setenv("SUPABASE_URL", "https://example.test")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "k")
    monkeypatch.delenv("GEOCODE_ROW_LOG", raising=False)
    spec = importlib.util.spec_from_file_location("_oct26_geo", REPO / "scripts" / "geocode_properties.py")
    geo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(geo)
    geo._rowlog("  [1/2] no match: Parcel 00-0000-000, FL")
    assert capsys.readouterr().out == ""
    monkeypatch.setattr(geo, "ROW_LOG", True)
    geo._rowlog("local line")
    assert "local line" in capsys.readouterr().out


def test_workflow_never_turns_the_geocoder_row_log_on():
    text = (REPO / ".github" / "workflows" / "harvest-and-sync.yml").read_text(encoding="utf-8")
    assert "GEOCODE_ROW_LOG" not in text
