#!/usr/bin/env python3
"""RealAuction sale-day PAGING check (value-free, read-only, manual only).

Why: the FL deed harvester (scripts/harvest_all_counties.ps1) read only the
first ten items of a sale day - deeds run 40200487211 printed "10 of 20 seen"
on 62 sale days: its request for the second Waiting page returned page one
again. This script learns, from the live site, how the sale-day page itself
moves to page two, without printing a single value:

  * the sale-day page's own script code around its pager (PageDir, curPW,
    maxW, ...), every run of 3+ digits masked;
  * the pager markup of the sale-day page shell, attribute values and digit
    runs masked;
  * for each paging sequence tried, per response: item count, how many items
    were new and how many repeated an earlier response (counts only - item
    identity is compared in memory by a hash and never printed);
  * the page's own status-refresh call (FNC=UPDATE&ref=<the ids the first
    response lists>): its keys, and the Waiting page / count fields (page
    text "Page N of M" and small counts only).

Permission: the SAME record the harvester uses - fl_realauction fetch + parse
for dataset sale_calendar (harvesters/governance/permissions.py). It reads
exactly what the harvester reads (calendar, sale-day page, its AJAX areas),
nothing more, writes nothing to any database, and stops before any request
when the permission is denied.

    python3 scripts/realauction_paging_check.py --county Polk --county Duval
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
import time
import urllib.parse
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO))
sys.path.insert(1, str(HERE))

HOSTS = REPO / "data" / "realauction_counties.csv"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
PAUSE = 0.7
DEFAULT_COUNTIES = ("Polk", "Duval", "Hillsborough", "Volusia", "Marion")
_LONG = re.compile(r"\d{3,}")
_ATTR = re.compile(r'\b(href|src|aid|value|title|data-[a-z-]+)\s*=\s*"[^"]*"', re.I)
_JS_KEYS = re.compile(r"PageDir|curP[WC]|max[WC]A?\b|PageLeft|PageRight|PageText|PAGE_|FNC=LOAD|bypassPage|doR\b|"
                      r"function\s+\w*[Pp]age\w*|\bpgDir\b|\bpage(?:Num|No)\b", re.I)


def mask(text: str) -> str:
    return _LONG.sub(lambda m: "#" * len(m.group(0)), _ATTR.sub(lambda m: f'{m.group(1)}="…"', text or ""))


def permitted() -> bool:
    from harvesters.governance import permissions as P
    perms = P.Permissions.from_file(None)
    ok = True
    for op in ("fetch", "parse"):
        d = perms.authorize("fl_realauction", op, state="FL", dataset="sale_calendar")
        print(json.dumps({"operation": op, "allowed": d.allowed, "reason_code": d.reason_code}))
        ok = ok and d.allowed
    return ok


def item_keys(body: str) -> list[str]:
    """One opaque key per AITEM_ block (hash of its Case # cell, else of the
    block) - compared in memory, never printed."""
    text = (body or "").replace('\\"', '"')
    keys = []
    for block in text.split("AITEM_")[1:]:
        m = re.search(r"Case #:[\s\S]{0,120}?CAD_DTA\">\s*([^@<]+)", block)
        raw = (m.group(1) if m else block[:400]).strip()
        keys.append(hashlib.sha256(raw.encode()).hexdigest()[:16])
    return keys


def json_keys(body: str) -> list[str]:
    try:
        d = json.loads(body)
    except ValueError:
        return ["NOT_JSON"]
    return sorted(d.keys()) if isinstance(d, dict) else [type(d).__name__]


def rlist(body: str) -> list[str]:
    try:
        d = json.loads(body)
    except ValueError:
        return []
    return [x for x in str((d or {}).get("rlist") or "").split(",") if x.strip().isdigit()] if isinstance(d, dict) else []


def page_counts(update_body: str) -> dict:
    """The status refresh's page / count fields, printed only when they are a
    'Page N of M' text or a short integer (counts, never identifiers)."""
    try:
        d = json.loads(update_body)
    except ValueError:
        return {"error": "NOT_JSON"}
    out = {"keys": sorted(d.keys()) if isinstance(d, dict) else []}
    for k in ("PW", "PC", "WC", "CC", "WM", "CM", "RW", "RC", "RA", "RR", "NC"):
        v = str((d or {}).get(k, "")) if isinstance(d, dict) else ""
        if re.fullmatch(r"Page \d{1,3} of \d{1,3}", v) or re.fullmatch(r"\d{1,4}", v) or v == "":
            out[k] = v
        else:
            out[k] = re.sub(r"\d", "#", re.sub(r"[A-Za-z]", "a", v))[:30]
    return out


class Site:
    def __init__(self, host: str, day: str):
        import requests
        self.s = requests.Session()
        self.host, self.day = host, day
        self.preview = f"https://{host}/index.cfm?zaction=AUCTION&zmethod=PREVIEW&AuctionDate={day}"

    def warm(self) -> str:
        self.s.get(f"https://{self.host}/index.cfm?zaction=user&zmethod=calendar", headers={"User-Agent": UA}, timeout=25)
        r = self.s.get(self.preview, headers={"User-Agent": UA,
                                              "Referer": f"https://{self.host}/index.cfm?zaction=USER&zmethod=CALENDAR"}, timeout=25)
        return r.text

    def ajax(self, query: str) -> tuple[int, str]:
        time.sleep(PAUSE)
        r = self.s.get(f"https://{self.host}/index.cfm?{query}", timeout=25,
                       headers={"User-Agent": UA, "Accept": "application/json, text/javascript, */*; q=0.01",
                                "X-Requested-With": "XMLHttpRequest", "Referer": self.preview})
        return r.status_code, r.text


def load(area: str, page_dir: int, do_r: int) -> str:
    return f"zaction=AUCTION&Zmethod=UPDATE&FNC=LOAD&AREA={area}&PageDir={page_dir}&doR={do_r}&bypassPage=1&test=1"


SEQUENCES = {
    # name -> list of (PageDir, doR); the first call of every sequence starts a fresh session.
    "harvester_now(0/1,1/1,2/1)": [(0, 1), (1, 1), (2, 1)],
    "next_doR0(0/1,1/0,1/0)": [(0, 1), (1, 0), (1, 0)],
    "fresh_doR0(0/0,1/0,1/0)": [(0, 0), (1, 0), (1, 0)],
}


def script_snippets(site: "Site", shell: str, limit: int = 40) -> dict:
    out: dict = {"scripts": [], "snippets": [], "pager_markup": []}
    srcs = re.findall(r'<script[^>]+src="([^"]+)"', shell or "", re.I)
    bodies = [("inline", "\n".join(re.findall(r"<script[^>]*>([\s\S]*?)</script>", shell or "", re.I)))]
    for src in srcs[:15]:
        url = urllib.parse.urljoin(site.preview, src)
        if urllib.parse.urlsplit(url).hostname != site.host or re.search(r"jquery|3rdParty", url, re.I):
            continue
        out["scripts"].append(urllib.parse.urlsplit(url).path)
        try:
            time.sleep(PAUSE)
            bodies.append((urllib.parse.urlsplit(url).path, site.s.get(url, headers={"User-Agent": UA}, timeout=25).text))
        except Exception:  # noqa: BLE001
            continue
    for name, body in bodies:
        for m in _JS_KEYS.finditer(body or ""):
            a, b = max(0, m.start() - 200), min(len(body), m.end() + 300)
            snip = re.sub(r"\s+", " ", body[a:b])
            if all(snip[40:120] not in x for x in out["snippets"]):
                out["snippets"].append(f"{name}: {mask(snip)}")
            if len(out["snippets"]) >= limit:
                break
    for m in re.finditer(r"(curP[WC]|max[WC]|PageLeft|PageRight|PageText|Page\s*<)", shell or ""):
        a, b = max(0, m.start() - 250), min(len(shell), m.end() + 250)
        frag = mask(re.sub(r"\s+", " ", shell[a:b]))
        if all(frag[60:140] not in x for x in out["pager_markup"]):
            out["pager_markup"].append(frag)
        if len(out["pager_markup"]) >= 8:
            break
    return out


def sale_days(host: str, months: int = 3) -> list[str]:
    import requests
    s = requests.Session()
    days: list[str] = []
    today = date.today()
    for off in range(months):
        y, mth = today.year + (today.month - 1 + off) // 12, (today.month - 1 + off) % 12 + 1
        ts = f"{{ts '{y:04d}-{mth:02d}-01 00:00:00'}}"
        r = s.get(f"https://{host}/index.cfm?zaction=user&zmethod=calendar&selCalDate=" + urllib.parse.quote(ts, safe=""),
                  headers={"User-Agent": UA}, timeout=25)
        days += re.findall(r"CALSELT[^>]*dayid=['\"](\d{2}/\d{2}/\d{4})['\"]", r.text)
        time.sleep(PAUSE)
    return sorted(set(days), key=lambda d: (d[6:], d[:5]))


def probe(county: str, host: str, max_days: int, want_script: bool) -> dict:
    rec: dict = {"county": county, "days": []}
    days = [d for d in sale_days(host) if (d[6:], d[:2], d[3:5]) >= (f"{date.today():%Y}", f"{date.today():%m}", f"{date.today():%d}")]
    rec["future_sale_days"] = len(days)
    for day in days[:max_days]:
        drec: dict = {"day_index": days.index(day), "sequences": {}}
        for name, seq in SEQUENCES.items():
            site = Site(host, day)
            shell = site.warm()
            if want_script and "script" not in rec:
                rec["script"] = script_snippets(site, shell)
            seen: set[str] = set()
            steps = []
            for i, (pd, dr) in enumerate(seq):
                code, body = site.ajax(load("W", pd, dr))
                keys = item_keys(body)
                new = [k for k in keys if k not in seen]
                steps.append({"PageDir": pd, "doR": dr, "http": code, "json_keys": json_keys(body),
                              "items": len(keys), "new": len(new), "repeated": len(keys) - len(new)})
                seen.update(keys)
                if i == 0 and name.startswith("harvester"):
                    ids = rlist(body)
                    if ids:
                        uc, ub = site.ajax(f"zaction=AUCTION&ZMETHOD=UPDATE&FNC=UPDATE&ref={','.join(ids)}")
                        drec["status_refresh"] = {"http": uc, **page_counts(ub)}
            drec["sequences"][name] = {"distinct_items": len(seen), "steps": steps}
        rec["days"].append(drec)
        print(f"  {county} day#{drec['day_index']}: " + json.dumps(drec, sort_keys=True), flush=True)
    return rec


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--county", action="append", default=[])
    ap.add_argument("--max-days", type=int, default=2)
    ap.add_argument("--out", default="out/public/realauction-paging-check.json")
    a = ap.parse_args(argv)
    if not permitted():
        print("realauction paging check: fl_realauction sale_calendar fetch/parse not permitted - no request made")
        return 3
    with open(HOSTS, newline="", encoding="utf-8") as fh:
        hosts = {r["County"]: r["Host"] for r in csv.DictReader(fh)}
    counties = a.county or list(DEFAULT_COUNTIES)
    report = {"counties": []}
    for i, c in enumerate(counties):
        if c not in hosts:
            print(f"  {c}: not a RealAuction county")
            continue
        try:
            report["counties"].append(probe(c, hosts[c], a.max_days, want_script=(i == 0)))
        except Exception as exc:  # noqa: BLE001 - transport; reported, never retried
            print(f"  {c}: {type(exc).__name__}")
    for r in report["counties"]:
        if r.get("script"):
            print("@@ scripts: " + ", ".join(r["script"]["scripts"]))
            for s in r["script"]["snippets"]:
                print("@@ js " + s)
            for s in r["script"]["pager_markup"]:
                print("@@ pager " + s)
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
