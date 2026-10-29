#!/usr/bin/env python3
"""Buyer's Guide capture (manual: harvest-and-sync job=evidence,
evidence_scope=buyers_guide). Reads the official page each researched answer
in data/buyers_guide_answers.csv cites and checks that the answer's quote is
on it (every " ... "-separated piece, compared after
harvesters/sources/buyers_guide.normalize()).

Prints one line per answer, never page text:

    BGCAP<TAB>state|county|ledger|question<TAB>quote sha256<TAB>RESULT<TAB>http status

RESULT: FOUND / PARTIAL / NOT_FOUND / FETCH_FAILED / BLOCKED (401, 403, 429 or
a challenge page - never retried or worked around) / DENIED (no discover
permission for the page's source). A person copies the job log and records it
with scripts/record_buyers_guide_captures.py; nothing here writes anywhere.

--leads: for NOT_VERIFIED / SOURCE_RESTRICTED answers that name an official
page (pages the research network could not read), print the page's own
sentences about the question instead (at most 8 per answer, 400 characters
each, chosen by the question's keywords):

    BGLEAD<TAB>key<TAB>RESULT<TAB>http status
    BGTEXT<TAB>key<TAB>sentence

A person writes the answer and quote from those sentences; the next normal
capture confirms the quote. Only official process pages are cited, never a
property record, so no row data can be printed.

Every request goes through the discovery guard (permission_gate): the page
must belong to a source with an in-date discover permission - the guide's
own pages map to buyers_guide_<state> (harvesters/governance/discovery_guard.py).
One request per distinct URL, at least one second apart on the same host.
"""
from __future__ import annotations

import argparse
import io
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urlsplit

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

USER_AGENT = "taxdeed-scraper/1.0 (buyer's guide capture; read-only)"
MAX_BYTES = 30 * 1024 * 1024
_CHALLENGE = re.compile(r"cf-chl|just a moment\.\.\.|attention required! \| cloudflare|captcha", re.I)


def page_text(content: bytes, content_type: str, url: str) -> str:
    ct = (content_type or "").lower()
    path = urlsplit(url).path.lower()
    if "pdf" in ct or path.endswith(".pdf") or content[:5] == b"%PDF-":
        import pdfplumber  # noqa: PLC0415
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            return "\n".join((p.extract_text() or "") for p in pdf.pages)
    text = content.decode("utf-8", errors="replace")
    if path.endswith(".rtf") or text.startswith("{\\rtf"):
        text = re.sub(r"\\'[0-9a-f]{2}", " ", text)
        text = re.sub(r"\\[a-z]+-?\d* ?|[{}]", " ", text)
        return text
    if "html" in ct or "<html" in text[:2000].lower():
        from bs4 import BeautifulSoup  # noqa: PLC0415
        soup = BeautifulSoup(text, "html.parser")
        for t in soup(["script", "style", "noscript"]):
            t.decompose()
        return soup.get_text(" ")
    return text


def fetch(session, url: str) -> tuple[str, int, str]:
    """(result, http status, text) - result is "" when the page was read."""
    from harvesters.governance.discovery_guard import DiscoveryDenied  # noqa: PLC0415
    try:
        r = session.get(url, timeout=45, allow_redirects=True, stream=True)
    except DiscoveryDenied:
        return "DENIED", 0, ""
    except Exception:  # noqa: BLE001 - any transport error is a failed read
        return "FETCH_FAILED", 0, ""
    status = r.status_code
    if status in (401, 403, 429):
        return "BLOCKED", status, ""
    if status != 200:
        return "FETCH_FAILED", status, ""
    body = r.raw.read(MAX_BYTES + 1, decode_content=True)
    if len(body) > MAX_BYTES:
        return "FETCH_FAILED", status, ""
    try:
        text = page_text(body, r.headers.get("content-type", ""), r.url)
    except Exception:  # noqa: BLE001
        return "FETCH_FAILED", status, ""
    if _CHALLENGE.search(text[:5000]) and len(text) < 20000:
        return "BLOCKED", status, ""
    return "", status, text


LEAD_KEYWORDS = {
    "register": r"regist|sign up|account|bidder",
    "deposit": r"deposit",
    "pay_after_win": r"pay|wire|cashier|balance|due",
    "pay": r"pay|wire|cashier|check|due",
    "extra_costs": r"fee|recording|stamp|cost",
    "costs": r"fee|cost",
    "schedule": r"held|sale date|sales are|schedule|calendar|month|week",
    "where_when": r"online|in person|courthouse|auction site|website|bid",
    "how_to_buy": r"purchase|buy|apply|application|offer|bid",
    "application": r"form|application|submit|document",
    "price": r"price|minimum|amount|value",
    "surplus": r"surplus|excess|overage",
    "title": r"title|quiet|insur",
    "occupied": r"occup|evict|possession|tenant",
    "inspect": r"inspect|as is|as-is|view",
    "refunds": r"refund|final|as is|as-is",
    "assignment": r"assign|county.held|struck|over the counter",
    "due_diligence": r"research|responsib|as is|as-is|beware|due diligence|caveat",
}
_SENT = re.compile(r"(?<=[.!?])\s+")


def lead_sentences(text: str, question: str, limit: int = 8) -> list[str]:
    pat = re.compile(LEAD_KEYWORDS.get(question, r"tax (sale|deed|lien)"), re.I)
    out, seen = [], set()
    for s in _SENT.split(re.sub(r"\s+", " ", text)):
        s = s.strip()
        if 25 <= len(s) and pat.search(s) and s.lower() not in seen:
            seen.add(s.lower())
            out.append(s[:400])
            if len(out) >= limit:
                break
    return out


def main(argv=None) -> int:
    import permission_gate as _PG  # noqa: PLC0415
    _PG.install_discovery_guard("capture_buyers_guide")
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--state", action="append", default=[], help="only these states (repeatable)")
    ap.add_argument("--delay", type=float, default=1.0, help="seconds between requests to one host")
    ap.add_argument("--leads", action="store_true", help="print the sentences of unread pages instead")
    a = ap.parse_args(argv)
    import requests  # noqa: PLC0415
    from harvesters.sources import buyers_guide as G  # noqa: PLC0415

    want = (lambda x: x.status not in G.READ_STATUSES and x.source_url) if a.leads else (lambda x: x.status in G.READ_STATUSES)
    answers = [x for x in G.load_answers() if want(x) and (not a.state or x.state in a.state)]
    by_url: dict[str, list] = defaultdict(list)
    for x in answers:
        by_url[x.source_url].append(x)
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    last: dict[str, float] = {}
    tally: Counter = Counter()
    for url in sorted(by_url):
        host = urlsplit(url).hostname or ""
        wait = last.get(host, 0) + a.delay - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        result, status, text = fetch(session, url)
        last[host] = time.monotonic()
        for x in by_url[url]:
            if a.leads:
                res = result or "READ"
                tally[res] += 1
                print(f"BGLEAD\t{x.key}\t{res}\t{status}", flush=True)
                for sent in ([] if result else lead_sentences(text, x.question)):
                    print(f"BGTEXT\t{x.key}\t{sent}", flush=True)
                continue
            res = result or G.match_quote(x.quote, text)
            tally[res] += 1
            print(f"BGCAP\t{x.key}\t{G.quote_sha(x.quote)}\t{res}\t{status}", flush=True)
    print(f"buyers guide capture: {len(by_url)} page(s), {len(answers)} answer(s): "
          + ", ".join(f"{k} {v}" for k, v in sorted(tally.items())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
