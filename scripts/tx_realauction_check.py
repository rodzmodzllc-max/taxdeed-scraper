#!/usr/bin/env python3
"""Texas RealAuction sale-day READ check (value-free, read-only, manual only).

Why: harvest_realauction() (harvesters/texas_harvester.py) printed "1 sale
date(s) found but 0 properties parsed" for Atascosa, Llano, Matagorda, Orange
and Victoria on every Texas run (#377, #378). That line cannot tell a sale
day whose waiting list is empty (the day already ran: its items sit in the
Closed / Canceled area) from a page the parser does not understand. This
script reads, per county and sale day, exactly what the harvester reads and
prints only structure:

  * the sale day relative to today (past / today / future, and days apart);
  * per AJAX area (W = waiting, R = running, C = closed / canceled), page one:
    HTTP status, JSON keys, AITEM_ block count;
  * for the first block of an area: which field labels the page carries
    (label text only, digits masked) and, for each label the harvester maps
    (REALAUCTION_FIELD_LABELS), whether the harvester's own parser reads a
    value from it (True / False - never the value).

Permission: the SAME record the harvester uses - tx_realauction fetch +
parse (data/source_permissions.csv). It stops before any request when that
is denied, writes nothing to any database, and prints no identifier, name,
address or amount.

    python3 scripts/tx_realauction_check.py --county Atascosa --county Llano
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
import urllib.parse
from datetime import date, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO))
sys.path.insert(1, str(REPO / "harvesters"))

HOSTS = REPO / "data" / "tx_realauction_counties.csv"
DEFAULT_COUNTIES = ("Atascosa", "Llano", "Matagorda", "Orange", "Victoria")
PAUSE = 0.7
_LABEL = re.compile(r"CAD_LBL[^>]*>\s*([^<@]{1,40}?)\s*:?\s*(?:@|<)")


def mask(text: str) -> str:
    return re.sub(r"\d", "#", text or "")


def permitted() -> bool:
    from harvesters.governance import permissions as P
    perms = P.Permissions.from_file(None)
    ok = True
    for op in ("fetch", "parse"):
        d = perms.authorize("tx_realauction", op, state="TX")
        print(json.dumps({"operation": op, "allowed": d.allowed, "reason_code": d.reason_code}))
        ok = ok and d.allowed
    return ok


def relative_day(day: str, today: date) -> str:
    try:
        d = datetime.strptime(day, "%m/%d/%Y").date()
    except ValueError:
        return "unparsed"
    delta = (d - today).days
    return "today" if delta == 0 else (f"past ({-delta} d ago)" if delta < 0 else f"future (in {delta} d)")


def blocks_of(body: str) -> list[str]:
    """AITEM_ blocks of the RAW response text, split exactly as
    harvest_realauction() splits it. The harvester's field pattern expects
    the JSON-escaped markup (CAD_DTA\\">) - decoding the JSON first made
    every label read False in the first capture (run 40384532568), an
    artifact of this script, not of the harvester."""
    return (body or "").split("AITEM_")[1:]


def json_keys(body: str) -> list[str]:
    try:
        d = json.loads(body)
    except ValueError:
        return ["NOT_JSON"]
    return sorted(d.keys()) if isinstance(d, dict) else [type(d).__name__]


def block_shape(block: str) -> dict:
    import texas_harvester as TH
    labels = sorted({mask(m.group(1).strip()) for m in _LABEL.finditer(block)})
    parsed = {lab: TH._realauction_get_field(block, lab) is not None for lab in TH.REALAUCTION_FIELD_LABELS}
    return {"labels_on_page": labels, "harvester_reads": parsed}


def check_county(county: str, host: str, today: date) -> dict:
    import requests
    s = requests.Session()
    ua = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/124.0.0.0 Safari/537.36"}
    out: dict = {"county": county, "days": []}
    dates: list[str] = []
    for off in range(3):
        m = today.month - 1 + off
        y, mo = today.year + m // 12, m % 12 + 1
        ts = urllib.parse.quote(f"{{ts '{y:04d}-{mo:02d}-01 00:00:00'}}", safe="")
        try:
            r = s.get(f"https://{host}/index.cfm?zaction=user&zmethod=calendar&selCalDate={ts}", headers=ua, timeout=25)
        except Exception as exc:  # noqa: BLE001 - value-free report
            out.setdefault("calendar_errors", []).append(type(exc).__name__)
            continue
        out.setdefault("calendar_http", []).append(r.status_code)
        dates += re.findall(r"CALSELT[^>]*dayid=['\"](\d{2}/\d{2}/\d{4})['\"]", r.text)
        time.sleep(PAUSE)
    for day in sorted(set(dates)):
        preview = f"https://{host}/index.cfm?zaction=AUCTION&zmethod=PREVIEW&AuctionDate={day}"
        entry: dict = {"sale_day": relative_day(day, today), "areas": {}}
        try:
            pr = s.get(preview, headers={**ua, "Referer": f"https://{host}/index.cfm?zaction=USER&zmethod=CALENDAR"},
                       timeout=25)
            entry["preview_http"] = pr.status_code
            entry["preview_has_areas"] = {a: f'id="Area_{a}"' in pr.text for a in ("W", "R", "C")}
        except Exception as exc:  # noqa: BLE001
            entry["preview_error"] = type(exc).__name__
            out["days"].append(entry)
            continue
        for area in ("W", "R", "C"):
            time.sleep(PAUSE)
            q = f"zaction=AUCTION&Zmethod=UPDATE&FNC=LOAD&AREA={area}&PageDir=0&doR=1&bypassPage=1&test=1"
            try:
                r = s.get(f"https://{host}/index.cfm?{q}", timeout=25,
                          headers={**ua, "Accept": "application/json, text/javascript, */*; q=0.01",
                                   "X-Requested-With": "XMLHttpRequest", "Referer": preview})
            except Exception as exc:  # noqa: BLE001
                entry["areas"][area] = {"error": type(exc).__name__}
                continue
            blocks = blocks_of(r.text)
            a = {"http": r.status_code, "json_keys": json_keys(r.text), "items": len(blocks)}
            if blocks:
                a["first_item"] = block_shape(blocks[0])
            entry["areas"][area] = a
        out["days"].append(entry)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--county", action="append")
    a = ap.parse_args(argv)
    if not permitted():
        print("tx_realauction fetch/parse not permitted - no request made")
        return 3
    hosts = {r["County"]: r["Host"] for r in csv.DictReader(HOSTS.open(encoding="utf-8"))}
    today = date.today()
    for county in a.county or DEFAULT_COUNTIES:
        if county not in hosts:
            print(json.dumps({"county": county, "error": "not in data/tx_realauction_counties.csv"}))
            continue
        print(json.dumps(check_county(county, hosts[county], today)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
