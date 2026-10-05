#!/usr/bin/env python3
"""Florida Lands Available clerk purchase statements (Pioneer TaxSmartWeb).

READ-ONLY. Builds `out/clerk_statements.json` and a value-free report. It
writes NOTHING to any database: putting a statement total in front of a
customer needs (a) a publication decision on the clerk documents' reuse and
(b) the owner's authorization of the production write - see
docs/clerk-statements.md.

Why: the Lands Available grid only carries the tax deed OPENING BID. The
amount a buyer owes is on the clerk's "List of Lands" statement - Citrus
2024-0075TD: opening bid $2,606.70 vs "Total Due from Purchaser $27,689.42
(IF RECEIVED BY 8/31/2026)". F.S. 197.502(7) / 197.542(1): interest on the
opening bid, taxes that came due after it was set, documentary stamp tax and
recording fees are added (docs/available-amount-semantics.md).

Where it is (read-only captures, runs 37248790485 / 37248930656):
grid row -> Home/Details?id=<row id> -> docket entries -> Home/Image/<doc id>
(PDF). The documents are SCANNED: no text layer, so OCR (tesseract) reads
them. OCR can misread a digit, so a statement is accepted ONLY when its own
itemised lines sum, to the cent, to its own printed total; anything else is
reported OCR_UNVERIFIED and produces no figure. The app's own arithmetic is
never substituted for the clerk's total.

Per-county configuration is explicit: a county is read only when its docket
wording and statement labels were verified from a capture. Today: Citrus.
Duval (statement OCR found none of the labels) and Palm Beach (labels
partial) are recorded as NOT_VERIFIED and are not read.

Output record (otc_provenance.purchase_statement shape the frontend reads):
  case_no, county, total_due, valid_through (YYYY-MM-DD), statement_date,
  document_url, observed_on, publisher, components {opening_bid, interest,
  omitted_taxes, doc_stamps, recording_fees}, docket_label
plus `history` - earlier statements on the same docket, each validated the
same way, never current.

--report prints counts, check results and date SHAPES only - never an
amount, a name, a parcel or an address (the job log of a public repository
is public).
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

HERE = Path(__file__).resolve().parent
COUNTIES_CSV = HERE / "../data/laft_pioneer_counties.csv"
OUT = HERE / "../out/clerk_statements.json"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

MONEY = r"\$?\s*(-?[\d,]+\.\d{2})"
DATE = r"(\d{1,2}/\d{1,2}/\d{4})"


@dataclass(frozen=True)
class CountyStatementConfig:
    county: str
    enabled: bool
    publisher: str
    docket_pattern: str            # regex on a docket entry's own text
    labels: dict                   # component key -> regex label (statement's own wording)
    total_labels: tuple            # the statement's printed total, first match wins
    valid_through_labels: tuple
    reason: str = ""


CITRUS = CountyStatementConfig(
    county="Citrus", enabled=True,
    publisher="Citrus County Clerk of the Circuit Court and Comptroller",
    docket_pattern=r"^\s*LOL\b",
    labels={
        "opening_bid": r"Opening\s+Bid",
        "interest": r"Lands\s+Available\s+Interest",
        "omitted_taxes": r"Total\s+Omitted\s+Taxes",
        "doc_stamps": r"Documentary\s+Stamp\s+Tax",
        "recording_fees": r"Deed\s+Recording\s+Fee",
    },
    total_labels=(r"Total\s+Due\s+from\s+Purchaser", r"Lands\s+Available\s+Total"),
    valid_through_labels=(r"IF\s+RECEIVED\s+BY", r"Valid\s+Through"),
)
NOT_VERIFIED = {
    "Duval": "statement documents found (LANDS AVAILABLE ... STATEMENT) but OCR found none of the statement labels",
    "Palm Beach": "LANDS AVAILABLE documents found; OCR labels partial (no total line recognised)",
    "Levy": "only a LIST OF LANDS LETTER TO TAX ... entry; no statement with a total",
    "Bay": "no statement entry on the docket",
    "Hernando": "no statement entry on the docket",
}
CONFIGS = {"Citrus": CITRUS}


def _num(s: str | None) -> float | None:
    if s is None:
        return None
    try:
        return round(float(s.replace(",", "").replace("$", "").strip()), 2)
    except ValueError:
        return None


def _after(text: str, label_re: str, value_re: str, span: int = 80) -> str | None:
    m = re.search(label_re + r"[^\n$\d]{0," + str(span) + r"}" + value_re, text, re.I)
    return m.group(1) if m else None


def _iso(d: str | None) -> str | None:
    if not d:
        return None
    try:
        return datetime.strptime(d, "%m/%d/%Y").date().isoformat()
    except ValueError:
        return None


@dataclass
class Parsed:
    status: str                     # VERIFIED / OCR_UNVERIFIED / NO_TOTAL / NO_LABELS
    total_due: float | None = None
    valid_through: str | None = None
    components: dict = field(default_factory=dict)
    missing: list = field(default_factory=list)


def parse_statement(text: str, cfg: CountyStatementConfig) -> Parsed:
    """Parse one statement's OCR text. VERIFIED only when every component the
    configuration names was read AND they sum to the printed total to the
    cent - so a misread digit can never become a customer figure."""
    comps = {k: _num(_after(text, rx, MONEY)) for k, rx in cfg.labels.items()}
    total = None
    for rx in cfg.total_labels:
        total = _num(_after(text, rx, MONEY))
        if total is not None:
            break
    valid = None
    for rx in cfg.valid_through_labels:
        valid = _iso(_after(text, rx, DATE, span=40))
        if valid:
            break
    missing = [k for k, v in comps.items() if v is None]
    if all(v is None for v in comps.values()):
        return Parsed("NO_LABELS", missing=missing)
    if total is None:
        return Parsed("NO_TOTAL", components={k: v for k, v in comps.items() if v is not None}, missing=missing, valid_through=valid)
    if missing or round(sum(comps.values()), 2) != total:
        return Parsed("OCR_UNVERIFIED", components={k: v for k, v in comps.items() if v is not None}, missing=missing, valid_through=valid)
    return Parsed("VERIFIED", total_due=total, valid_through=valid, components=comps)


def statement_record(p: Parsed, *, county: str, case_no: str, document_url: str, observed_on: str,
                     publisher: str, docket_label: str, statement_date: str | None) -> dict:
    """The otc_provenance.purchase_statement shape. Only a VERIFIED parse
    becomes a record."""
    if p.status != "VERIFIED":
        raise ValueError(f"only a VERIFIED statement becomes a record (got {p.status})")
    return {
        "county": county, "case_no": case_no, "total_due": p.total_due, "valid_through": p.valid_through,
        "statement_date": statement_date, "document_url": document_url, "observed_on": observed_on,
        "publisher": publisher, "components": p.components, "docket_label": docket_label,
        "basis": "OCR of the clerk's scanned statement; accepted because its itemised lines sum to its printed total",
    }


def is_expired(valid_through: str | None, today: date) -> bool | None:
    if not valid_through:
        return None
    return date.fromisoformat(valid_through) < today


def order_statements(records: list[dict]) -> tuple[dict | None, list[dict]]:
    """Latest statement (by statement date, then valid-through) is current;
    the rest are history. A newer statement replaces the current figure; the
    older ones are kept, never deleted."""
    if not records:
        return None, []
    key = lambda r: (r.get("statement_date") or "", r.get("valid_through") or "")
    ranked = sorted(records, key=key, reverse=True)
    return ranked[0], ranked[1:]


# ---------------------------------------------------------------- live read
def _ocr_pdf(blob: bytes, max_pages: int) -> str:
    import pdfplumber
    import pytesseract
    texts = []
    with pdfplumber.open(io.BytesIO(blob)) as pdf:
        for pg in pdf.pages[:max_pages]:
            texts.append(pytesseract.image_to_string(pg.to_image(resolution=300).original))
    return "\n".join(texts)


def _docket(html: str) -> list[tuple[str, str]]:
    out = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.I | re.S):
        link = re.search(r"""href\s*=\s*["']([^"']*Image/\d+)["']""", tr, re.I)
        if link:
            out.append((link.group(1), re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", tr)).strip()))
    return out


def harvest(counties: list[str], max_pages: int = 4) -> dict:
    import requests
    s = requests.Session()
    s.headers["User-Agent"] = UA
    today = datetime.now(timezone.utc).date()
    observed = today.isoformat()
    rows = {r["County"]: r["BaseUrl"].rstrip("/") + "/" for r in csv.DictReader(open(COUNTIES_CSV, encoding="utf-8"))}
    result = {"observed_on": observed, "counties": {}, "statements": []}
    for county in counties:
        cfg = CONFIGS.get(county)
        if not cfg or not cfg.enabled:
            result["counties"][county] = {"status": "NOT_VERIFIED", "reason": NOT_VERIFIED.get(county, "no verified statement configuration")}
            continue
        base = rows[county]
        g = s.get(urljoin(base, "Home/GridSearchData"), params={"SearchType": "Lands Available", "_search": "false", "rows": "100", "page": "1", "sidx": "", "sord": "asc"},
                  headers={"X-Requested-With": "XMLHttpRequest"}, timeout=30).json()
        cstat = {"status": "READ", "rows": 0, "with_statement_docs": 0, "statuses": {}, "expired": 0, "current": 0}
        for r in g.get("rows") or []:
            cstat["rows"] += 1
            row_id, cells = str(r.get("id")), r.get("cell") or []
            case_no = str(cells[1]).strip() if len(cells) > 1 else ""
            det_url = urljoin(base, f"Home/Details?id={row_id}")
            docs = [(h, t) for h, t in _docket(s.get(det_url, timeout=30).text) if re.search(cfg.docket_pattern, t, re.I)]
            if not docs:
                cstat["statuses"]["NO_STATEMENT_DOC"] = cstat["statuses"].get("NO_STATEMENT_DOC", 0) + 1
                continue
            cstat["with_statement_docs"] += 1
            recs = []
            for href, label in docs:
                url = urljoin(det_url, href)
                blob = s.get(url, timeout=60).content
                p = parse_statement(_ocr_pdf(blob, max_pages), cfg)
                cstat["statuses"][p.status] = cstat["statuses"].get(p.status, 0) + 1
                for k in p.missing:
                    cstat.setdefault("missing_labels", {})[k] = cstat.setdefault("missing_labels", {}).get(k, 0) + 1
                if p.status == "VERIFIED":
                    dm = re.search(DATE, label)
                    recs.append(statement_record(p, county=county, case_no=case_no, document_url=url, observed_on=observed,
                                                 publisher=cfg.publisher, docket_label=re.sub(r"\d", "9", label)[:40],
                                                 statement_date=_iso(dm.group(1)) if dm else None))
            current, history = order_statements(recs)
            if current:
                exp = is_expired(current["valid_through"], today)
                cstat["expired" if exp else "current"] += 1
                result["statements"].append({"county": county, "case_no": case_no, "purchase_statement": current, "purchase_statement_history": history})
        result["counties"][county] = cstat
    return result


def report(result: dict) -> str:
    """Value-free: counts, statuses and date shapes. Never an amount."""
    lines = [f"observed_on {result['observed_on']}"]
    for county, c in result["counties"].items():
        if c.get("status") != "READ":
            lines.append(f"{county}: {c['status']} - {c.get('reason', '')}")
            continue
        lines.append(f"{county}: rows={c['rows']} with_statement_docs={c['with_statement_docs']} "
                     f"statuses={json.dumps(c['statuses'], sort_keys=True)} missing_labels={json.dumps(c.get('missing_labels', {}), sort_keys=True)} current_statements={c['current']} expired_statements={c['expired']}")
    for st in result["statements"]:
        cur = st["purchase_statement"]
        lines.append(f"  case shape {re.sub(r'[0-9]', '9', st['case_no'])}: current statement valid_through shape "
                     f"{re.sub(r'[0-9]', '9', cur['valid_through'] or '-')}, components={sorted(cur['components'])}, history={len(st['purchase_statement_history'])}")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--counties", default="Citrus")
    ap.add_argument("--max-pages", type=int, default=4)
    ap.add_argument("--report", action="store_true", help="print the value-free report (safe for a public log)")
    a = ap.parse_args(argv)
    res = harvest([c.strip() for c in a.counties.split(",") if c.strip()], a.max_pages)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(res, indent=1), encoding="utf-8")
    if a.report:
        print(report(res))
    return 0


if __name__ == "__main__":
    sys.exit(main())
