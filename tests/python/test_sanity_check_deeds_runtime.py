"""Runs the real scripts/sanity_check_deeds.ps1 under PowerShell against a fake
Supabase. Run 386 (2026-10-26) read 39 counties fresh yet the check said
"only 1": PowerShell 7 returns a JSON array from Invoke-RestMethod as ONE
object, so @(...) wrapped it as a single row whose county was every county
joined together. The fake returns real JSON arrays, like PostgREST."""
import json
import os
import shutil
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

ROOT = Path(__file__).resolve().parents[2]
PWSH = shutil.which("pwsh")
if not PWSH:
    if os.environ.get("CI"):
        pytest.fail("pwsh is required in CI to run the PowerShell sanity-check test", pytrace=False)
    pytest.skip("PowerShell (pwsh) not installed", allow_module_level=True)


def _serve(rows):
    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            q = parse_qs(urlsplit(self.path).query)
            body = []
            if urlsplit(self.path).path.endswith("/properties") and "last_seen_at" in q:
                after = int(q["id"][0].split(".", 1)[1]) if "id" in q else -1
                body = [r for r in rows if r["id"] > after][:1000]
            data = json.dumps(body).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *a):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def _run(rows):
    srv = _serve(rows)
    try:
        env = dict(os.environ, SUPABASE_URL=f"http://127.0.0.1:{srv.server_address[1]}", SUPABASE_SERVICE_KEY="test")
        return subprocess.run([PWSH, "-NoProfile", "-File", str(ROOT / "scripts" / "sanity_check_deeds.ps1")],
                              capture_output=True, text=True, env=env, timeout=120)
    finally:
        srv.shutdown()


def test_counts_every_fresh_county_across_keyset_pages():
    counties = [f"County{i:02d}" for i in range(20)]
    rows = [{"id": i, "county": counties[i % 20]} for i in range(2500)]  # three keyset pages
    p = _run(rows)
    assert p.returncode == 0, p.stdout + p.stderr
    assert "Counties with fresh (last 26h) active auction data: 20" in p.stdout


def test_fails_when_too_few_counties_are_fresh():
    rows = [{"id": i, "county": f"County{i % 3}"} for i in range(30)]
    p = _run(rows)
    assert p.returncode != 0 and "only 3 counties" in (p.stdout + p.stderr)
