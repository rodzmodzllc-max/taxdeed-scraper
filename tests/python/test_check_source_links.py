"""scripts/check_source_links.py - classification, streaks, scheduling and
URL collection, with injected HTTP answers (no network)."""
from __future__ import annotations

import io
import json
import sys
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import check_source_links as csl  # noqa: E402
from check_source_links import FetchError, Response, Result  # noqa: E402


def fake(answers: dict):
    """answers: (method, url) -> Response | FetchError; a missing HEAD falls back to GET's answer."""
    calls = []

    def fetch(method, url):
        calls.append((method, url))
        a = answers.get((method, url), answers.get(("*", url)))
        if isinstance(a, Exception):
            raise a
        assert a is not None, (method, url)
        return a
    fetch.calls = calls
    return fetch


HENDRY = "https://mcclibraryfunctions.azurewebsites.us/api/munidocDownload/31143/8216f21582c5d/pdf"


@pytest.mark.parametrize("resp, status, detail", [
    (Response(200, {"content-type": "application/pdf"}), "OK", "OK"),
    (Response(404, {}), "BROKEN", "HTTP_404"),
    (Response(410, {}), "BROKEN", "HTTP_410"),
    (Response(401, {}), "BLOCKED", "HTTP_401"),
    (Response(429, {}), "BLOCKED", "HTTP_429"),
    (Response(500, {}), "ERROR", "HTTP_500"),
    (Response(503, {"server": "cloudflare"}, b"<title>Just a moment...</title>"), "BLOCKED", "CHALLENGE"),
    (Response(403, {"cf-mitigated": "challenge"}), "BLOCKED", "CHALLENGE"),
])
def test_classify(resp, status, detail):
    r = csl.classify("https://county.gov/list.pdf", resp)
    assert (r.status, r.detail) == (status, detail)


def test_hendry_pdf_404_is_broken():
    f = fake({("HEAD", HENDRY): Response(404, {"content-type": "text/html"}),
              ("GET", HENDRY): Response(404, {"content-type": "text/html"})})
    r = csl.check(HENDRY, f)
    assert r.status == "BROKEN" and r.http_code == 404
    assert [m for m, _ in f.calls] == ["HEAD", "GET"]


CIVICPLUS = "https://www.county.gov/DocumentCenter/View/1234/Repository-Bid-Form"


@pytest.mark.parametrize("head", [404, 410])
def test_head_not_found_is_confirmed_by_get_civicplus(head):
    """Audit B7 / B11 / B12: CivicPlus answers HEAD 404 for a file GET serves."""
    f = fake({("HEAD", CIVICPLUS): Response(head, {"content-type": "text/html"}),
              ("GET", CIVICPLUS): Response(200, {"content-type": "application/pdf"}, b"%PDF-1.7")})
    r = csl.check(CIVICPLUS, f)
    assert (r.status, r.http_code) == ("OK", 200)
    assert [m for m, _ in f.calls] == ["HEAD", "GET"]


def test_head_404_then_get_transport_failure_is_not_broken():
    f = fake({("HEAD", CIVICPLUS): Response(404, {}), ("GET", CIVICPLUS): FetchError("CONNECTION")})
    assert (csl.check(CIVICPLUS, f).status, csl.check(CIVICPLUS, f).detail) == ("ERROR", "CONNECTION")


def test_head_refused_falls_back_to_get():
    url = "https://county.gov/page"
    f = fake({("HEAD", url): Response(405, {}), ("GET", url): Response(200, {"content-type": "application/pdf"})})
    assert csl.check(url, f).status == "OK"
    assert [m for m, _ in f.calls] == ["HEAD", "GET"]


def test_head_403_get_ok_is_ok_and_get_403_is_blocked_not_broken():
    url = "https://waf.gov/x"
    f = fake({("HEAD", url): Response(403, {}), ("GET", url): Response(200, {"content-type": "text/plain"})})
    assert csl.check(url, f).status == "OK"
    f = fake({("HEAD", url): Response(403, {}), ("GET", url): Response(403, {})})
    assert csl.check(url, f).status == "BLOCKED"


def test_soft_404_html_title_and_pdf_answered_with_error_page():
    url = "https://county.gov/notice"
    f = fake({("HEAD", url): Response(200, {"content-type": "text/html"}),
              ("GET", url): Response(200, {"content-type": "text/html"}, b"<html><title>Page Not Found</title></html>")})
    r = csl.check(url, f)
    assert (r.status, r.detail) == ("BROKEN", "SOFT_404")
    pdf = "https://county.gov/docs/list.pdf"
    f = fake({("HEAD", pdf): Response(200, {"content-type": "text/html"}),
              ("GET", pdf): Response(200, {"content-type": "text/html"}, b"<title>County</title><h1>Error: document not found</h1>")})
    assert csl.check(pdf, f).detail == "SOFT_404"
    ok = "https://county.gov/home"
    f = fake({("HEAD", ok): Response(200, {"content-type": "text/html"}),
              ("GET", ok): Response(200, {"content-type": "text/html"}, b"<title>Tax Deeds</title>")})
    assert csl.check(ok, f).status == "OK"


def test_transport_failures():
    url = "https://gone.example/"
    assert csl.check(url, fake({("HEAD", url): FetchError("DNS")})).status == "BROKEN"
    for kind in ("TIMEOUT", "TLS", "CONNECTION", "PROXY"):
        r = csl.check(url, fake({("HEAD", url): FetchError(kind)}))
        assert (r.status, r.detail) == ("ERROR", kind)


NOW = datetime(2026, 10, 27, 12, 0, tzinfo=timezone.utc)


def test_streak_counts_separate_days_only():
    broken = Result("BROKEN", 404, "HTTP_404", None)
    r1 = csl.next_row("u", broken, None, NOW, {"x"})
    assert r1["consecutive_failures"] == 1 and r1["first_failed_at"]
    same_day = csl.next_row("u", broken, {**r1, "checked_at": "2026-10-27T03:00:00+00:00"}, NOW, set())
    assert same_day["consecutive_failures"] == 1          # a second check the same day does not count
    next_day = csl.next_row("u", broken, {**r1, "checked_at": "2026-10-26T11:00:00+00:00"}, NOW, set())
    assert next_day["consecutive_failures"] == 2 and next_day["first_failed_at"] == r1["first_failed_at"]
    for other in ("OK", "BLOCKED", "ERROR"):
        reset = csl.next_row("u", Result(other, 200, other, None), next_day, NOW, set())
        assert reset["consecutive_failures"] == 0 and reset["first_failed_at"] is None


def test_schedule_failures_first_and_per_host_cap():
    urls = [f"https://a.gov/{i}" for i in range(5)] + ["https://b.gov/1"]
    prior = {"https://a.gov/0": {"status": "OK", "checked_at": "2026-10-26"},
             "https://a.gov/1": {"status": "BROKEN", "checked_at": "2026-10-26"},
             "https://a.gov/2": {"status": "OK", "checked_at": "2026-10-20"}}
    plan = csl.order_for_run(urls, prior, 3)
    assert plan["a.gov"] == ["https://a.gov/1", "https://a.gov/3", "https://a.gov/4"]
    assert plan["b.gov"] == ["https://b.gov/1"]


def test_run_checks_one_host_serial_with_pause():
    pauses = []
    urls = {"a.gov": ["https://a.gov/1", "https://a.gov/2"], "b.gov": ["https://b.gov/1"]}
    f = fake({("*", u): Response(200, {"content-type": "application/pdf"}) for us in urls.values() for u in us})
    out = csl.run_checks(urls, f, pause=0.5, workers=2, sleep=pauses.append)
    assert set(out) == {"https://a.gov/1", "https://a.gov/2", "https://b.gov/1"}
    assert pauses == [0.5]


def test_collection_from_rows_registry_and_evidence(tmp_path):
    refs = csl.defaultdict(set)
    csl.urls_from_property_rows([
        {"id": 1, "url_auction": HENDRY, "document_url": HENDRY, "list_url": "not a url", "o_evidence": "https://ev.gov/p",
         "o_application": "https://ev.gov/form.pdf"},
        {"id": 2, "purchase_url": "https://buy.gov/1", "o_statement_doc": None}], refs)
    assert set(refs) == {HENDRY, "https://ev.gov/p", "https://ev.gov/form.pdf", "https://buy.gov/1"}
    assert refs[HENDRY] == {"properties.url_auction", "properties.document_url"}
    csl.urls_from_property_rows([{"id": 3, "url_appraiser": "http://pa.county.gov/parcel?acct=1",
                                  "url_taxcoll": "https://tc.gov/x", "url_title": "https://clerk.gov/t"}], refs)
    assert refs["http://pa.county.gov/parcel?acct=1"] == {"properties.url_appraiser"}  # audit F40 / F67
    assert refs["https://tc.gov/x"] == {"properties.url_taxcoll"} and refs["https://clerk.gov/t"] == {"properties.url_title"}
    reg = tmp_path / "r.csv"
    reg.write_text("canonical_url,document_url,purchase_url,notes\nhttps://c.gov/,,https://buy.gov/1,x\n", encoding="utf-8")
    csl.urls_from_registry(reg, refs)
    csl.urls_from_json({"records": [{"evidence_url": "https://e.gov/a", "nested": {"u": "http://e.gov/b"}}], "n": 3}, refs, "acquisition-evidence")
    assert {"https://c.gov/", "https://e.gov/a", "http://e.gov/b"} <= set(refs)
    assert refs["https://buy.gov/1"] == {"properties.purchase_url", "registry.purchase_url"}


def test_property_select_is_keyset_ready_and_has_every_rendered_column():
    sel = csl.property_select()
    assert sel.startswith("id,")
    for c in ("url_auction", "list_url", "document_url", "purchase_url", "purchase_evidence_url", "application_url",
              "url_appraiser", "url_taxcoll", "url_title"):
        assert c in sel


def test_property_read_uses_keyset_pages_only():
    seen = []

    def fetch(qs):
        seen.append(qs)
        return [{"id": i, "url_auction": "https://a.gov/x"} for i in range(1000)] if len(seen) == 1 else []
    refs = csl.defaultdict(set)
    assert csl.read_property_urls("https://db.example", {}, refs, fetch=fetch) == 1000
    assert "offset" not in "".join(seen) and "id=gt.999" in seen[1]
    assert "status=in.(active,available)" in seen[0]


def test_mask_and_summary_never_print_a_full_url():
    assert csl.mask_url("https://stl.gov/parcel?parcel=12345678&x=1") == "https://stl.gov/parcel?parcel&x"
    results = {HENDRY: Result("BROKEN", 404, "HTTP_404", None), "https://stl.gov/p/123456": Result("OK", 200, "OK", None)}
    rows = [csl.next_row(u, r, None, NOW, set()) for u, r in results.items()]
    text = csl.summary(results, rows)
    assert "31143" not in text and "123456" not in text and "munidoc" not in text
    assert "mcclibraryfunctions.azurewebsites.us: BROKEN 1" in text


def test_main_without_credentials_writes_nothing(monkeypatch, tmp_path):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_KEY", raising=False)
    monkeypatch.setattr(csl, "REGISTRY", tmp_path / "none.csv")
    monkeypatch.setattr(csl, "EVIDENCE", tmp_path / "none.json")
    urls = tmp_path / "u.txt"
    urls.write_text(HENDRY + "\n", encoding="utf-8")
    monkeypatch.setattr(csl, "http_fetch", lambda m, u, **k: Response(404, {}))
    out_json = tmp_path / "o.json"
    buf = io.StringIO()
    with redirect_stdout(buf):
        assert csl.main(["--urls-file", str(urls), "--json-out", str(out_json)]) == 0
    assert "nothing written" in buf.getvalue()
    assert json.loads(out_json.read_text())["by_status"] == {"BROKEN": 1}
