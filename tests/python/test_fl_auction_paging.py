"""The FL deed harvester reads EVERY page of a RealAuction sale day (2026-10-26).

Bug: scripts/harvest_all_counties.ps1 asked for page N with
`PageDir=N&doR=1&bypassPage=1`. RealAuction keeps the current page in the
server session and, with bypassPage=1, ignores PageDir and serves page one
again - so only the first ten items of each sale day were ever read (deeds
run 40200487211: 62 sale days at "10 of 20 seen"; 155 active rows on 40 sale
days were never seen). The page's own pager (auction.js changePage ->
loadArea(area, 1, 0, 0)) asks for the NEXT page with
`PageDir=1&doR=0&bypassPage=0`; the live paging check (run 40380815661,
scripts/realauction_paging_check.py) measured page 1..5 of 5 that way and
page one again with every bypassPage=1 form.

These tests RUN the real PowerShell harvester against a local fake
RealAuction server that behaves like the measured one:
  * session-based paging (a cookie set by the sale-day page);
  * bypassPage=1 or doR=1 -> page one, whatever PageDir says;
  * bypassPage=0, doR=0 -> moves PageDir pages, and repeats the last page
    once past the end;
  * the status refresh (FNC=UPDATE&ref=...) publishes "page N of M".
Nothing leaves the machine. Skipped only where PowerShell is absent; under CI
a missing runtime fails.
"""
from __future__ import annotations

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
        pytest.fail("pwsh is required in CI to run the FL auction paging tests", pytrace=False)
    pytest.skip("PowerShell (pwsh) not installed", allow_module_level=True)

PAGE = 10
DAY = "11/05/2026"


def _item(n: int, county_tag: str) -> str:
    """One synthetic AITEM_ block in the site's own compressed markup (shape of
    tests/python/fixtures/realauction/closed_area.json; every value invented)."""
    aid = 9000000 + n
    return (f'<div id="AITEM_{aid}" aria-label="Auction Details" @C@E_ITEM PREVIEW" aid="{aid}">@A@E_DETAILS">'
            f'<@I @Cad_tab"><tbody>@Htabindex="0" @CAD_LBL" scope="row">Auction Type:@F tabindex="0" @CAD_DTA">TAXDEED @G'
            f'@Htabindex="0" @CAD_LBL" scope="row" aria-label="Case Number">Case #:@F @CAD_DTA"> 2026 TD {county_tag}{n:04d}@G'
            f'@Htabindex="0" @CAD_LBL" scope="row">Opening Bid:@F tabindex="0" @CAD_DTA">$1,000.00@G'
            f'@Htabindex="0" @CAD_LBL" scope="row">Parcel ID:@F tabindex="0" @CAD_DTA"> <a href="https://example.invalid/p" '
            f'target="_blank">00-00-{n:04d}</a>@G'
            f'@Htabindex="0" @CAD_LBL" scope="row">Property Address:@F tabindex="0" @CAD_DTA">{n} FIXTURE ST@G'
            f'</tbody></@I>@B@B')


class FakeRealAuction:
    """`days` maps county tag -> item count for DAY. `mode` per tag:
    "ok" (the measured behaviour), "stuck" (the pager never moves - every
    load is page one) or "no_count" (the refresh publishes no page text)."""

    def __init__(self, days: dict[str, int], modes: dict[str, str] | None = None):
        self.days, self.modes = days, modes or {}
        self.sessions: dict[str, dict] = {}
        self.loads: list[dict] = []
        fake = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, body: str, ctype="text/html", cookie=None):
                data = body.encode()
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                if cookie:
                    self.send_header("Set-Cookie", f"SID={cookie}; Path=/")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                q = {k.lower(): v[0] for k, v in parse_qs(urlsplit(self.path).query).items()}
                sid = ""
                for part in (self.headers.get("Cookie") or "").split(";"):
                    if part.strip().startswith("SID="):
                        sid = part.strip()[4:]
                tag = q.get("tag") or ""
                zm = q.get("zmethod", "").upper()
                if zm == "CALENDAR":
                    return self._send(f'<div class="CALBOX CALW5 CALSELT" dayid="{DAY}">x</div>')
                if zm == "PREVIEW":
                    new = f"s{len(fake.sessions) + 1}"
                    # The county is the cookie jar's session; the fake learns it
                    # from the Referer-less preview via the Host port map.
                    fake.sessions[new] = {"page": 1, "tag": fake.port_tag[self.server.server_address[1]]}
                    return self._send("<html>sale day shell</html>", cookie=new)
                st = fake.sessions.get(sid)
                if st is None:
                    return self._send(json.dumps({"retHTML": "", "rlist": ""}), "application/json")
                n = fake.days[st["tag"]]
                pages = max(1, -(-n // PAGE)) if n else 0
                mode = fake.modes.get(st["tag"], "ok")
                if q.get("fnc") == "LOAD":
                    pd, dor, bp = int(q.get("pagedir", 0)), q.get("dor"), q.get("bypasspage")
                    fake.loads.append({"tag": st["tag"], "PageDir": pd, "doR": dor, "bypassPage": bp})
                    if mode == "stuck" or bp == "1" or dor == "1":
                        st["page"] = 1
                    else:
                        st["page"] = min(max(1, st["page"] + pd), max(1, pages))
                    lo = (st["page"] - 1) * PAGE
                    ids = list(range(lo + 1, min(n, lo + PAGE) + 1))
                    html = "".join(_item(i, st["tag"]) for i in ids)
                    return self._send(json.dumps({"retHTML": html, "rlist": ",".join(str(9000000 + i) for i in ids)}),
                                      "application/json")
                if q.get("fnc") == "UPDATE":
                    body = {"ADATA": {"AITEM": [], "COUNT": "0"}, "WC": str(st["page"]), "WM": str(pages),
                            "PW": "" if mode == "no_count" else f"page {st['page']} of {pages}"}
                    return self._send(json.dumps(body), "application/json")
                return self._send("", "text/plain")

        self.servers = []
        self.port_tag: dict[int, str] = {}
        for tag in days:
            srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
            self.port_tag[srv.server_address[1]] = tag
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            self.servers.append((tag, srv))

    def close(self):
        for _, s in self.servers:
            s.shutdown()


def _run(tmp_path: Path, days: dict[str, int], modes: dict[str, str] | None = None):
    fake = FakeRealAuction(days, modes)
    try:
        csv_path = tmp_path / "counties.csv"
        lines = ["County,Host"] + [f"Fake{tag},127.0.0.1:{srv.server_address[1]}" for tag, srv in fake.servers]
        csv_path.write_text("\n".join(lines) + "\n")
        out = tmp_path / "out"
        env = {**os.environ, "RA_COUNTIES_CSV": str(csv_path), "RA_OUT_DIR": str(out), "TMPDIR": str(tmp_path)}
        r = subprocess.run([PWSH, "-NoProfile", "-File", str(ROOT / "scripts/harvest_all_counties.ps1")],
                           capture_output=True, text=True, env=env, timeout=300)
        assert r.returncode == 0, r.stdout + r.stderr
        harvest = json.loads((out / "harvest_all.json").read_text(encoding="utf-8-sig") or "[]")
        status = json.loads((out / "harvest_all_status.json").read_text(encoding="utf-8-sig"))
        harvest = harvest if isinstance(harvest, list) else [harvest]
        status = status if isinstance(status, list) else [status]
        return harvest, {s["county"]: s for s in status}, fake, r.stdout
    finally:
        fake.close()


def _days(entry):
    d = entry.get("saleDays")
    return d if isinstance(d, list) else [d]


def test_every_page_of_every_sale_day_is_read(tmp_path):
    harvest, status, fake, out = _run(tmp_path, {"A": 23, "B": 3, "C": 20, "D": 0})
    per = {}
    for r in harvest:
        per[r["county"]] = per.get(r["county"], 0) + 1
    assert per == {"FakeA": 23, "FakeB": 3, "FakeC": 20}
    for tag, n, pages in (("A", 23, 3), ("B", 3, 1), ("C", 20, 2)):
        e = status[f"Fake{tag}"]
        assert e["status"] == "COMPLETE", e
        assert _days(e) == [{"sale_date": DAY, "read": n, "pages_read": pages, "published_pages": pages, "complete": True}]
    assert status["FakeD"]["status"] == "COMPLETE"
    assert _days(status["FakeD"])[0]["read"] == 0 and _days(status["FakeD"])[0]["complete"] is True
    # The site's own request shape: first page reset, then "next" with bypassPage=0.
    a_loads = [x for x in fake.loads if x["tag"] == "A"]
    assert a_loads[0] == {"tag": "A", "PageDir": 0, "doR": "1", "bypassPage": "1"}
    assert all(x == {"tag": "A", "PageDir": 1, "doR": "0", "bypassPage": "0"} for x in a_loads[1:])
    assert len(a_loads) == 3                       # stops at the published last page
    # Counts only in the log: no case number reaches stdout.
    assert "TD A0001" not in out and "23 items on 3 of 3 page(s)" in out


def test_the_old_request_reads_page_one_only_on_this_fake(tmp_path):
    # The fake is faithful to the measured server: the old request form
    # (PageDir=N&doR=1&bypassPage=1) gets page one back every time.
    fake = FakeRealAuction({"A": 23})
    try:
        import urllib.request
        port = fake.servers[0][1].server_address[1]
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor())
        opener.open(f"http://127.0.0.1:{port}/index.cfm?zaction=AUCTION&zmethod=PREVIEW&AuctionDate={DAY}").read()
        firsts = set()
        for page in range(3):
            body = json.loads(opener.open(f"http://127.0.0.1:{port}/index.cfm?zaction=AUCTION&Zmethod=UPDATE&FNC=LOAD"
                                          f"&AREA=W&PageDir={page}&doR=1&bypassPage=1&test=1").read())
            firsts.add(body["rlist"])
        assert len(firsts) == 1
    finally:
        fake.close()


def test_a_pager_that_does_not_move_marks_the_county_incomplete(tmp_path):
    harvest, status, _, out = _run(tmp_path, {"A": 23, "B": 4}, {"A": "stuck"})
    e = status["FakeA"]
    assert e["status"] == "INCOMPLETE" and "read short" in e["reason"]
    assert _days(e) == [{"sale_date": DAY, "read": 10, "pages_read": 1, "published_pages": 3, "complete": False}]
    assert status["FakeB"]["status"] == "COMPLETE"
    # The ten rows that were read are still harvested (synced, never closed from).
    assert sum(1 for r in harvest if r["county"] == "FakeA") == 10
    assert "READ SHORT" in out


def test_no_published_page_count_marks_the_county_incomplete(tmp_path):
    _, status, _, _ = _run(tmp_path, {"A": 5}, {"A": "no_count"})
    e = status["FakeA"]
    assert e["status"] == "INCOMPLETE" and "page count not published" in e["reason"]
    assert _days(e)[0]["complete"] is False and _days(e)[0]["published_pages"] is None


def test_offlist_closeout_reads_the_harvesters_own_status(tmp_path):
    # End to end: the status file the harvester writes is what the off-list
    # close-out reads - a fully read 23-item day is no longer held.
    import sys
    sys.path.insert(0, str(ROOT / "scripts"))
    import auction_offlist_closeout as C  # noqa: PLC0415
    _, status, _, _ = _run(tmp_path, {"A": 23}, {})
    days = C.day_reads(list(status.values()))
    assert days[("FakeA", "2026-11-05")]["complete"] is True


def test_results_reader_uses_the_same_next_page_request():
    import sys
    sys.path.insert(0, str(ROOT / "scripts"))
    import realauction_results as RR  # noqa: PLC0415
    assert "PageDir=0&doR=1&bypassPage=1" in RR.ajax_url("h", "C", 0, reset=True)
    assert "PageDir=1&doR=0&bypassPage=0" in RR.ajax_url("h", "C", 1, reset=False)
