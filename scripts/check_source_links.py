"""Daily check of every source link a customer can click (2026-10-27).

Why: Hendry County's only Lands Available row pointed at a Municode PDF that
had answered HTTP 404 since 2026-09-29. The page still offered it as the
county's list, and the owner found the dead link before we did. This script
reads every distinct URL the app can render as a link, checks each one once,
and records the result in public.source_link_checks (migration 036). The app
reads that table and stops offering a link only after it was BROKEN on two
separate daily checks, so one bad day never hides a link.

What is collected (each URL checked once, however many rows carry it):

* active / available `properties` rows: url_auction, list_url, document_url,
  purchase_url, and the otc_provenance values the property page renders as
  links (purchase_evidence_url, list_url, document_url,
  acquisition.application_url, purchase_statement.document_url / url). Read
  with keyset pages (scripts/rest_pages.py), never offset;
* data/county_source_registry.csv: canonical_url, document_url, purchase_url;
* public/acquisition-evidence.json: every http(s) string in it.

Classification (one per URL):

* OK      - a 2xx answer, after redirects;
* BROKEN  - 404 / 410, a host that does not resolve, or a soft 404 (a 2xx
            HTML page titled "not found" / "404", or an HTML error page where
            a PDF is expected);
* BLOCKED - 401 / 403 / 429 or a bot challenge (Cloudflare "Just a moment").
            The link may work in a person's browser: never treated as broken;
* ERROR   - a timeout, a 5xx, a TLS or connection failure. Not proof either way.

`consecutive_failures` counts BROKEN results on separate days (a second check
on the same UTC day does not add to it); any other result resets it to 0.

Politeness: HEAD first, GET (first 64 KB only) when a server refuses HEAD
(405 / 403 / 501) or when a body is needed to tell a PDF from an error page;
one request at a time per host with a pause between them; a per-host cap per
run (URLs that failed last time first, then never checked, then the oldest).
A challenge, a login or a block is recorded as BLOCKED and never worked
around.

Logs carry counts per status and per host only - never a full URL (a URL can
carry a parcel number); a sample path is masked to its shape.

    python3 scripts/check_source_links.py               # check + write (needs SUPABASE_*)
    python3 scripts/check_source_links.py --dry-run     # check, print counts, write nothing
    python3 scripts/check_source_links.py --no-db --urls-file urls.txt --dry-run   # offline list

Without the table (migration 036 not applied) it checks and prints counts only.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import socket
import ssl
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

REGISTRY = ROOT / "data" / "county_source_registry.csv"
EVIDENCE = ROOT / "public" / "acquisition-evidence.json"
TABLE = "source_link_checks"
STATUSES = ("OK", "BROKEN", "BLOCKED", "ERROR")
BROKEN_AFTER = 2                      # BROKEN on this many separate days = broken
TIMEOUT = 20.0
READ_BYTES = 64 * 1024
PER_HOST_PAUSE = 0.5
PER_HOST_LIMIT = 1500
HOST_WORKERS = 8
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/126.0 Safari/537.36 taxdeed-scraper-linkcheck/1.0")

PROPERTY_COLUMNS = ("url_auction", "list_url", "document_url", "purchase_url")
# otc_provenance paths the app renders as links (alias -> PostgREST json path).
OTC_PATHS = {
    "o_evidence": "otc_provenance->>purchase_evidence_url",
    "o_list": "otc_provenance->>list_url",
    "o_document": "otc_provenance->>document_url",
    "o_application": "otc_provenance->acquisition->>application_url",
    "o_statement_doc": "otc_provenance->purchase_statement->>document_url",
    "o_statement_url": "otc_provenance->purchase_statement->>url",
}
REGISTRY_COLUMNS = ("canonical_url", "document_url", "purchase_url")
VISIBLE_STATUSES = ("active", "available")

_DIGITS = re.compile(r"\d")
_TITLE = re.compile(rb"<title[^>]*>(.*?)</title>", re.I | re.S)
_SOFT404 = re.compile(rb"(page not found|file not found|document not found|not found|\b404\b|\b410\b|no longer available|does not exist)", re.I)
_CHALLENGE = re.compile(rb"(just a moment|cf-chl|challenge-platform|attention required|captcha|are you a robot|access denied)", re.I)


# ---------------------------------------------------------------------------
# URL collection
# ---------------------------------------------------------------------------
def is_http(u) -> bool:
    return isinstance(u, str) and u.strip().lower().startswith(("http://", "https://")) and " " not in u.strip()


def host_of(u: str) -> str:
    return (urllib.parse.urlsplit(u).hostname or "").lower()


def mask_url(u: str) -> str:
    """A URL's shape for a public log: host kept, every digit -> '#', the
    query reduced to its parameter names."""
    p = urllib.parse.urlsplit(u)
    q = "&".join(sorted({k for k, _ in urllib.parse.parse_qsl(p.query, keep_blank_values=True)}))
    return f"{p.scheme}://{p.hostname or ''}{_DIGITS.sub('#', p.path)}{'?' + q if q else ''}"


def add(refs: dict, url, where: str) -> None:
    if is_http(url):
        refs[url.strip()].add(where)


def urls_from_property_rows(rows: Iterable[dict], refs: dict) -> None:
    for r in rows:
        for c in PROPERTY_COLUMNS:
            add(refs, r.get(c), f"properties.{c}")
        for alias in OTC_PATHS:
            add(refs, r.get(alias), f"properties.otc_provenance.{alias[2:]}")


def urls_from_registry(path: Path, refs: dict) -> None:
    if not path.exists():
        return
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            for c in REGISTRY_COLUMNS:
                add(refs, row.get(c), f"registry.{c}")


def urls_from_json(obj, refs: dict, where: str) -> None:
    if isinstance(obj, dict):
        for v in obj.values():
            urls_from_json(v, refs, where)
    elif isinstance(obj, list):
        for v in obj:
            urls_from_json(v, refs, where)
    elif is_http(obj):
        add(refs, obj, where)


def property_select() -> str:
    return ",".join(["id", *PROPERTY_COLUMNS, *(f"{a}:{p}" for a, p in OTC_PATHS.items())])


def read_property_urls(base: str, headers: dict, refs: dict, fetch=None) -> int:
    import rest_pages  # noqa: PLC0415
    rows = rest_pages.read_all(base, "properties", headers,
                               {"select": property_select(), "status": f"in.({','.join(VISIBLE_STATUSES)})"}, fetch=fetch)
    urls_from_property_rows(rows, refs)
    return len(rows)


# ---------------------------------------------------------------------------
# One check
# ---------------------------------------------------------------------------
@dataclass
class Response:
    status: int
    headers: dict = field(default_factory=dict)      # lower-case keys
    body: bytes = b""
    final_url: str = ""


class FetchError(Exception):
    """A request that produced no HTTP answer. kind: DNS / TIMEOUT / TLS /
    CONNECTION / PROXY."""
    def __init__(self, kind: str):
        super().__init__(kind)
        self.kind = kind


@dataclass
class Result:
    status: str
    http_code: int | None
    detail: str
    final_url: str | None


def expects_pdf(url: str) -> bool:
    path = urllib.parse.urlsplit(url).path.lower()
    return path.endswith(".pdf") or path.endswith("/pdf")


def is_html(resp: Response) -> bool:
    return "html" in str(resp.headers.get("content-type", "")).lower()


def challenge(resp: Response) -> bool:
    h = resp.headers
    if str(h.get("cf-mitigated", "")).lower() == "challenge":
        return True
    return resp.status in (403, 429, 503) and bool(_CHALLENGE.search(resp.body[:READ_BYTES]))


def soft_404(url: str, resp: Response) -> bool:
    if not is_html(resp) or not resp.body:
        return False
    m = _TITLE.search(resp.body[:READ_BYTES])
    title = m.group(1) if m else b""
    if title and _SOFT404.search(title):
        return True
    # An HTML page where the link promises a PDF: an error page unless it
    # names itself a viewer (some hosts wrap PDFs in an HTML viewer).
    return expects_pdf(url) and bool(_SOFT404.search(resp.body[:READ_BYTES])) and b"pdf" not in title.lower()


def classify(url: str, resp: Response) -> Result:
    s = resp.status
    final = resp.final_url or url
    if challenge(resp):
        return Result("BLOCKED", s, "CHALLENGE", final)
    if s in (404, 410):
        return Result("BROKEN", s, f"HTTP_{s}", final)
    if s in (401, 403, 407, 429):
        return Result("BLOCKED", s, f"HTTP_{s}", final)
    if 200 <= s < 300:
        if soft_404(url, resp):
            return Result("BROKEN", s, "SOFT_404", final)
        return Result("OK", s, "OK", final)
    if 300 <= s < 400:
        return Result("ERROR", s, "REDIRECT_UNFOLLOWED", final)
    if s >= 500:
        return Result("ERROR", s, f"HTTP_{s}", final)
    return Result("ERROR", s, f"HTTP_{s}", final)


def check(url: str, fetch: Callable[[str, str], Response]) -> Result:
    """HEAD, then GET when the server refuses HEAD or a body is needed."""
    try:
        resp = fetch("HEAD", url)
        need_get = resp.status in (403, 405, 501, 400) or (
            200 <= resp.status < 300 and (expects_pdf(url) and is_html(resp)))
        # A 2xx HTML page can be a soft 404: look at its title.
        if 200 <= resp.status < 300 and is_html(resp):
            need_get = True
        if need_get:
            resp = fetch("GET", url)
        return classify(url, resp)
    except FetchError as exc:
        if exc.kind == "DNS":
            return Result("BROKEN", None, "DNS", None)
        return Result("ERROR", None, exc.kind, None)


def http_fetch(method: str, url: str, *, timeout: float = TIMEOUT) -> Response:
    """The real request. Redirects are followed (urllib does this for HEAD and
    GET); a GET reads at most READ_BYTES."""
    req = urllib.request.Request(url, method=method, headers={
        "User-Agent": UA, "Accept": "text/html,application/pdf,application/xhtml+xml,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read(READ_BYTES) if method == "GET" else b""
            return Response(r.status, {k.lower(): v for k, v in r.headers.items()}, body, r.geturl())
    except urllib.error.HTTPError as e:
        try:
            body = e.read(READ_BYTES) if method == "GET" else b""
        except Exception:  # noqa: BLE001
            body = b""
        return Response(e.code, {k.lower(): v for k, v in (e.headers or {}).items()}, body, e.geturl() or url)
    except urllib.error.URLError as e:
        reason = e.reason
        text = str(reason)
        if isinstance(reason, socket.gaierror):
            raise FetchError("DNS") from None
        if "Tunnel connection failed" in text or "407" in text:
            raise FetchError("PROXY") from None
        if isinstance(reason, (socket.timeout, TimeoutError)) or "timed out" in text:
            raise FetchError("TIMEOUT") from None
        if isinstance(reason, ssl.SSLError) or "CERTIFICATE" in text.upper() or "SSL" in text.upper():
            raise FetchError("TLS") from None
        raise FetchError("CONNECTION") from None
    except (socket.timeout, TimeoutError):
        raise FetchError("TIMEOUT") from None
    except (ConnectionError, OSError):
        raise FetchError("CONNECTION") from None


# ---------------------------------------------------------------------------
# Scheduling and history
# ---------------------------------------------------------------------------
def order_for_run(urls: Iterable[str], prior: dict, per_host_limit: int) -> dict[str, list[str]]:
    """Per host, the URLs to check this run: last-time failures first, then
    never-checked, then oldest-checked; at most `per_host_limit` per host."""
    by_host: dict[str, list[str]] = defaultdict(list)
    for u in urls:
        by_host[host_of(u)].append(u)
    plan: dict[str, list[str]] = {}
    for h, us in by_host.items():
        def key(u):
            p = prior.get(u)
            if not p:
                return (1, "", u)
            failing = 0 if p.get("status") in ("BROKEN", "ERROR") else 2
            return (failing, str(p.get("checked_at") or ""), u)
        plan[h] = sorted(us, key=key)[:per_host_limit]
    return plan


def utc_day(ts) -> str:
    return str(ts or "")[:10]


def next_row(url: str, res: Result, prior: dict | None, now: datetime, refs: set) -> dict:
    """The row to store, carrying the BROKEN streak across separate days."""
    today = now.date().isoformat()
    p = prior or {}
    streak = int(p.get("consecutive_failures") or 0)
    first = p.get("first_failed_at")
    if res.status == "BROKEN":
        if p.get("status") == "BROKEN" and streak > 0:
            if utc_day(p.get("checked_at")) != today:
                streak += 1
        else:
            streak, first = 1, now.isoformat()
    else:
        streak, first = 0, None
    return {"url": url, "host": host_of(url), "status": res.status, "http_code": res.http_code,
            "detail": res.detail, "checked_at": now.isoformat(), "first_failed_at": first,
            "consecutive_failures": streak, "final_url": res.final_url,
            "referenced_by": sorted(refs)}


def run_checks(plan: dict[str, list[str]], fetch, *, pause: float = PER_HOST_PAUSE,
               workers: int = HOST_WORKERS, sleep=time.sleep) -> dict[str, Result]:
    out: dict[str, Result] = {}
    lock = threading.Lock()

    def one_host(urls: list[str]):
        for i, u in enumerate(urls):
            if i:
                sleep(pause)
            r = check(u, fetch)
            with lock:
                out[u] = r

    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        list(ex.map(one_host, plan.values()))
    return out


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
class Db:
    def __init__(self, base: str, key: str):
        self.base = base.rstrip("/")
        self.h = {"apikey": key, "Authorization": f"Bearer {key}", "Accept": "application/json"}

    def table_exists(self) -> bool:
        try:
            self._get(f"/rest/v1/{TABLE}?select=url&limit=1")
            return True
        except urllib.error.HTTPError as e:
            if e.code in (404, 400):
                return False
            raise

    def _get(self, path: str):
        import rest_pages  # noqa: PLC0415
        return rest_pages.get_json(self.base + path, self.h)

    def prior(self) -> dict:
        """Every stored check, keyset-paged on the primary key (url)."""
        out: dict = {}
        after = None
        while True:
            q = {"select": "url,status,checked_at,first_failed_at,consecutive_failures", "order": "url.asc", "limit": "1000"}
            if after is not None:
                q["url"] = f"gt.{after}"
            chunk = self._get(f"/rest/v1/{TABLE}?" + urllib.parse.urlencode(q, safe="(),.*:")) or []
            for r in chunk:
                out[r["url"]] = r
            if len(chunk) < 1000:
                return out
            after = chunk[-1]["url"]

    def upsert(self, rows: list[dict], batch: int = 500) -> int:
        n = 0
        for i in range(0, len(rows), batch):
            body = json.dumps(rows[i:i + batch]).encode()
            req = urllib.request.Request(f"{self.base}/rest/v1/{TABLE}?on_conflict=url", data=body, method="POST",
                                         headers={**self.h, "Content-Type": "application/json",
                                                  "Prefer": "resolution=merge-duplicates,return=minimal"})
            with urllib.request.urlopen(req, timeout=120):
                n += len(rows[i:i + batch])
        return n


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------
def summary(results: dict[str, Result], rows: list[dict] | None = None) -> str:
    by_status = Counter(r.status for r in results.values())
    by_detail = Counter(f"{r.status}:{r.detail}" for r in results.values())
    by_host: dict[str, Counter] = defaultdict(Counter)
    for u, r in results.items():
        by_host[host_of(u)][r.status] += 1
    lines = [f"checked {len(results)} distinct URL(s): " + ", ".join(f"{s} {by_status.get(s, 0)}" for s in STATUSES)]
    lines.append("by result: " + ", ".join(f"{k} {v}" for k, v in sorted(by_detail.items())))
    if rows is not None:
        confirmed = sum(1 for r in rows if r["status"] == "BROKEN" and r["consecutive_failures"] >= BROKEN_AFTER)
        lines.append(f"broken on {BROKEN_AFTER}+ separate daily checks (hidden as links in the app): {confirmed}")
    lines.append("by host (non-OK hosts first):")
    for h, c in sorted(by_host.items(), key=lambda kv: (-sum(v for k, v in kv[1].items() if k != "OK"), kv[0])):
        lines.append(f"  {h}: " + ", ".join(f"{s} {c[s]}" for s in STATUSES if c[s]))
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dry-run", action="store_true", help="check and print counts; write nothing")
    ap.add_argument("--no-db", action="store_true", help="do not read properties / the table (registry + evidence only)")
    ap.add_argument("--urls-file", help="extra URLs, one per line")
    ap.add_argument("--per-host-limit", type=int, default=PER_HOST_LIMIT)
    ap.add_argument("--pause", type=float, default=PER_HOST_PAUSE)
    ap.add_argument("--workers", type=int, default=HOST_WORKERS)
    ap.add_argument("--json-out", help="write the counts-only summary as JSON here")
    a = ap.parse_args(argv)

    refs: dict[str, set] = defaultdict(set)
    urls_from_registry(REGISTRY, refs)
    if EVIDENCE.exists():
        urls_from_json(json.loads(EVIDENCE.read_text(encoding="utf-8")), refs, "acquisition-evidence")
    if a.urls_file:
        for line in Path(a.urls_file).read_text(encoding="utf-8").splitlines():
            add(refs, line, "urls-file")

    db = None
    prior: dict = {}
    base, key = os.environ.get("SUPABASE_URL", ""), os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not a.no_db:
        if not base or not key:
            print("SUPABASE_URL / SUPABASE_SERVICE_KEY not set - checking registry and evidence URLs only, nothing written")
        else:
            db = Db(base, key)
            n = read_property_urls(db.base, db.h, refs)
            print(f"read {n} active / available property row(s)")
            if db.table_exists():
                prior = db.prior()
            else:
                print(f"table public.{TABLE} not found (migration 036 not applied) - results are printed, not stored")
                db = None
    plan = order_for_run(refs, prior, a.per_host_limit)
    planned = sum(len(v) for v in plan.values())
    print(f"{len(refs)} distinct URL(s) across {len(plan)} host(s); {planned} checked this run "
          f"(at most {a.per_host_limit} per host)")
    results = run_checks(plan, http_fetch, pause=a.pause, workers=a.workers)
    now = datetime.now(timezone.utc).replace(microsecond=0)
    rows = [next_row(u, r, prior.get(u), now, refs[u]) for u, r in results.items()]
    print(summary(results, rows))
    if a.json_out:
        out = {"checked": len(results), "distinct": len(refs), "hosts": len(plan),
               "by_status": dict(Counter(r.status for r in results.values())),
               "by_host": {h: dict(Counter(results[u].status for u in us if u in results)) for h, us in plan.items()},
               "by_detail": dict(Counter(f"{r.status}:{r.detail}" for r in results.values()))}
        Path(a.json_out).write_text(json.dumps(out, indent=2, sort_keys=True), encoding="utf-8")
    if a.dry_run or db is None:
        print("dry run - nothing written" if a.dry_run else "nothing written")
        return 0
    written = db.upsert(rows)
    print(f"stored {written} check result(s) in public.{TABLE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
