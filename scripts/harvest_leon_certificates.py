#!/usr/bin/env python3
"""
Harvest Leon County's county-held tax certificates from the Leon County Tax
Collector's own "Certificate Lists" page, which publishes them as a zipped
Excel workbook.

Added 2026-10-25 (Florida sources batch - docs/sources-batch-2026-10-25-florida.md).
GATED: source id `fl_leon_tc_certificates`, wired into NO workflow and NOT
read by sync-certificates-to-supabase.ps1 (which reads only
out/harvest_certificates.json). Registry row MANUAL_REVIEW_REQUIRED /
UNREVIEWED. The permission records (data/source_permissions.csv) are an
internal risk acceptance for fetch / parse / store only, excluded from the
paid tier, "not sold until legal review" - never the Tax Collector's
permission.

THE SOURCE (2026-10-25): https://www.leontaxcollector.net/Services/property-taxes/Certificate-Lists
links four dated zips under /Portals/69/userFiles/CertFiles/ - All
Certificates, All Outstanding (OpenCertificates), All County Held
(OpenCountyCertificates<YYYYMMDD>.zip) and All Redeemed - "as of" the date in
the file name (2026-10-01 when read). The page says the files are refreshed
on the first business day after the discount period's due date and the
first business day of each month from April. This harvester reads only the
COUNTY-HELD list (the certificates the county holds and a buyer can purchase,
the same scope as LienHub's countyheld list): the link is discovered on the
page by its OpenCountyCertificates<date>.zip name, never constructed.

The zip held one member, OpenCountyCertificates20261001.xlsx: one sheet, a
header row and 121 data rows. Headers (as written, with stray spaces):
bidderno, ceryear, cernumber, cerpartno, rollyear, interestrate, issuedate
(YYYYMMDD integer), holdername, holderaddr1/2, holdercity, holderstate,
holderzip, propertynumber, ownername, incareof, Asdbaname, address1-3, city,
state, country, zipcode, taxcode, justvalue, taxablevalue, faceamt,
legaldesc, subdiv, acreage. (ceryear, cernumber, cerpartno) was unique on
every row; one parcel can carry several certificates.

MAPPED (row shape of scripts/sync-certificates-to-supabase.ps1):
  case_no / certificate_no  "<ceryear>-<cernumber>" (+ "-<cerpartno>" when the
                            part is not 0) - the certificate is the record
  tax_year                  rollyear (the tax roll the certificate was sold for)
  issued_date               issuedate as YYYY-MM-DD
  bid                       faceamt (> 0) - CertificateRecord.face_amount
  interest_rate             interestrate
  parcel                    propertynumber, whitespace removed
  legal_desc                legaldesc
  url_auction               the Certificate Lists page (a county page)
NEVER MAPPED: ownername / incareof / Asdbaname and address1-3 / city / state /
zipcode (the owner's name and MAILING address - not the property's situs),
holdername / holderaddr* (the holder), bidderno, justvalue / taxablevalue
(not needed for the certificate ledger; values are not taxes), acreage,
subdiv, taxcode. No expiration date is published, and none is derived.

STATUS (out/harvest_certificates_leon_status.json, laft_status vocabulary):
  COMPLETE    the recognised header and >= 1 usable row
  EMPTY       the recognised header and zero data rows (empty_table)
  INCOMPLETE  recognised header but every row rejected / unusable
  FAILED      transport, zip, workbook or unrecognised-header failure

Logs carry counts and categories only - never a certificate, parcel, owner
or amount.

Run:
  python3 scripts/harvest_leon_certificates.py                  # live (gated)
  python3 scripts/harvest_leon_certificates.py --fixture F.zip  # no network
Output: out/harvest_certificates_leon.json
"""
from __future__ import annotations

import argparse
import io
import json
import re
import sys
import zipfile
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin

import requests

import laft_status as _LS  # noqa: E402 - permission gate
from laft_status import CategorizedError, StatusRecorder, describe_exception, extract_list_as_of, record_identifiers_plausible

HERE = Path(__file__).resolve().parent
OUT_DIR = HERE / "../out"
OUT_JSON = OUT_DIR / "harvest_certificates_leon.json"
STATUS_PATH = OUT_DIR / "harvest_certificates_leon_status.json"

SOURCE_ID = "fl_leon_tc_certificates"
DATASET = "county_held_certificates"
COUNTY = "Leon"
PAGE_URL = "https://www.leontaxcollector.net/Services/property-taxes/Certificate-Lists"
_ZIP_LINK = re.compile(r'href="([^"]*OpenCountyCertificates(\d{8})\.zip)"', re.IGNORECASE)

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
HEADERS = {"User-Agent": UA, "Accept": "*/*", "Accept-Language": "en-US,en;q=0.9", "Accept-Encoding": "gzip, deflate"}

MAX_ZIP_BYTES = 20 * 1024 * 1024
MAX_MEMBER_BYTES = 50 * 1024 * 1024

REQUIRED_HEADERS = ("ceryear", "cernumber", "cerpartno", "rollyear", "interestrate", "issuedate",
                    "propertynumber", "faceamt")


def _norm_header(h) -> str:
    return re.sub(r"\s+", "", str(h or "")).lower()


def discover_zip_url(html: str) -> tuple[str, str | None]:
    """(absolute zip URL, list_as_of ISO) of the county-held list on the page."""
    m = _ZIP_LINK.search(html)
    if not m:
        raise CategorizedError("PARSE_FORMAT_CHANGE", "no OpenCountyCertificates<date>.zip link on the Certificate Lists page")
    url = urljoin(PAGE_URL, m.group(1))
    return url, extract_list_as_of(url=url)


def read_workbook(zip_bytes: bytes) -> list[tuple]:
    """Rows (header first) of the single .xlsx member."""
    if len(zip_bytes) > MAX_ZIP_BYTES:
        raise CategorizedError("PARSE_FORMAT_CHANGE", "zip larger than expected")
    try:
        zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except zipfile.BadZipFile as exc:
        raise CategorizedError("PARSE_FORMAT_CHANGE", "download is not a zip archive") from exc
    members = [i for i in zf.infolist() if not i.is_dir()]
    if len(members) != 1 or not members[0].filename.lower().endswith(".xlsx"):
        raise CategorizedError("PARSE_FORMAT_CHANGE", "zip does not hold exactly one .xlsx workbook")
    if members[0].file_size > MAX_MEMBER_BYTES:
        raise CategorizedError("PARSE_FORMAT_CHANGE", "workbook larger than expected")
    import openpyxl  # noqa: PLC0415 - only needed for a real read
    wb = openpyxl.load_workbook(io.BytesIO(zf.read(members[0])), read_only=True, data_only=True)
    if len(wb.worksheets) != 1:
        raise CategorizedError("PARSE_FORMAT_CHANGE", "workbook does not hold exactly one sheet")
    return [tuple(r) for r in wb.worksheets[0].iter_rows(values_only=True)]


def _int(v) -> int | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, float) and v.is_integer():
        return int(v)
    if isinstance(v, str) and v.strip().isdigit():
        return int(v.strip())
    return None


def _num(v) -> float | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v.replace(",", "").replace("$", "").strip())
        except ValueError:
            return None
    return None


def _date(v) -> str | None:
    n = _int(v)
    if n is None:
        return None
    try:
        return datetime.strptime(str(n), "%Y%m%d").date().isoformat()
    except ValueError:
        return None


def parse_rows(rows: list[tuple], *, as_of: str | None = None) -> tuple[list[dict], dict]:
    """(records, outcome). Raises PARSE_FORMAT_CHANGE when the header is not the
    recognised one; `outcome` counts what was kept and what was not."""
    if not rows:
        raise CategorizedError("PARSE_FORMAT_CHANGE", "empty sheet (no header row)")
    header = [_norm_header(h) for h in rows[0]]
    missing = [h for h in REQUIRED_HEADERS if h not in header]
    if missing:
        raise CategorizedError("PARSE_FORMAT_CHANGE", f"header lacks {len(missing)} expected column(s)")
    idx = {h: i for i, h in enumerate(header) if h}
    outcome = {"data_rows": 0, "kept": 0, "rejected": 0, "duplicate": 0}
    out: list[dict] = []
    seen: set[str] = set()

    def cell(r, name):
        i = idx.get(name)
        return r[i] if i is not None and i < len(r) else None

    for r in rows[1:]:
        if not any(c not in (None, "") for c in r):
            continue
        outcome["data_rows"] += 1
        year, number, part = _int(cell(r, "ceryear")), _int(cell(r, "cernumber")), _int(cell(r, "cerpartno"))
        if year is None or number is None:
            outcome["rejected"] += 1
            continue
        cert = f"{year}-{number}" + (f"-{part}" if part else "")
        if cert in seen:
            outcome["duplicate"] += 1
            continue
        record: dict = {"source": "certificate", "county": COUNTY, "host": "leontaxcollector.net",
                        "case_no": cert, "certificate_no": cert, "url_auction": PAGE_URL}
        roll = _int(cell(r, "rollyear"))
        if roll is not None:
            record["tax_year"] = str(roll)
        issued = _date(cell(r, "issuedate"))
        if issued:
            record["issued_date"] = issued
        face = _num(cell(r, "faceamt"))
        if face is not None and face > 0:
            record["bid"] = round(face, 2)
        rate = _num(cell(r, "interestrate"))
        if rate is not None:
            record["interest_rate"] = rate
        parcel = re.sub(r"\s+", "", str(cell(r, "propertynumber") or "")).upper()
        if parcel:
            record["parcel"] = parcel
        legal = re.sub(r"\s+", " ", str(cell(r, "legaldesc") or "")).strip()
        if legal:
            record["legal_desc"] = legal
        if as_of:
            record["list_as_of"] = as_of
        if not record_identifiers_plausible(record):
            outcome["rejected"] += 1
            continue
        seen.add(cert)
        out.append(record)
    outcome["kept"] = len(out)
    return out, outcome


def run(zip_bytes: bytes | None = None, *, as_of: str | None = None,
        recorder: StatusRecorder | None = None) -> list[dict]:
    recorder = recorder or StatusRecorder(SOURCE_ID, source_class="GOVERNMENT_DIRECT", source_id=SOURCE_ID,
                                          path=STATUS_PATH)
    kw: dict = dict(source_url=PAGE_URL)
    try:
        if zip_bytes is None:
            s = requests.Session()
            page = s.get(PAGE_URL, headers=HEADERS, timeout=30)
            page.raise_for_status()
            zip_url, as_of = discover_zip_url(page.text)
            kw["document_url"] = zip_url
            resp = s.get(zip_url, headers={**HEADERS, "Referer": PAGE_URL}, timeout=60)
            resp.raise_for_status()
            zip_bytes = resp.content
        kw["list_as_of"] = as_of
        records, outcome = parse_rows(read_workbook(zip_bytes), as_of=as_of)
        if records:
            recorder.complete(COUNTY, len(records), **kw)
            status = "COMPLETE"
        elif outcome["data_rows"] == 0:
            recorder.empty(COUNTY, "empty_table", **kw)
            status = "EMPTY"
        else:
            recorder.incomplete(COUNTY, "PARSE_FORMAT_CHANGE", "every data row was unusable", **kw)
            status = "INCOMPLETE"
        print(f"    {status}: {outcome['kept']} of {outcome['data_rows']} row(s) kept "
              f"(rejected {outcome['rejected']}, duplicate {outcome['duplicate']}); list as of {as_of or 'not stated'}",
              flush=True)
        return records
    except Exception as exc:  # noqa: BLE001 - recorded, never a silent zero
        category, _ = describe_exception(exc)
        print(f"    FAILED ({category})", flush=True)
        recorder.failed(COUNTY, exc, **kw)
        return []


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Leon County Tax Collector county-held certificates (gated)")
    ap.add_argument("--fixture", help="a local OpenCountyCertificates<YYYYMMDD>.zip (no network)")
    args = ap.parse_args(argv)
    # Source permission: fetch / parse / store must each be recorded, or 0
    # requests and nothing written (exit 3). A fixture read makes no request.
    ops = ("parse", "store") if args.fixture else ("fetch", "parse", "store")
    denied = _LS.permission_gate(SOURCE_ID, operations=ops, dataset=DATASET)
    if denied:
        return denied
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    recorder = StatusRecorder(SOURCE_ID, source_class="GOVERNMENT_DIRECT", source_id=SOURCE_ID, path=STATUS_PATH)
    print(f"[1/1] {COUNTY}", flush=True)
    if args.fixture:
        path = Path(args.fixture)
        records = run(path.read_bytes(), as_of=extract_list_as_of(url=path.name), recorder=recorder)
    else:
        records = run(recorder=recorder)
    recorder.write()
    print(recorder.summary_line(), flush=True)
    OUT_JSON.write_text(json.dumps(records, indent=2), encoding="utf-8")
    print(f"Saved {len(records)} row(s) to {OUT_JSON.name}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
