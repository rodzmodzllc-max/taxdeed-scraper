"""Document intelligence for official PDFs / spreadsheets / notices
(all-sources enrichment engine, 2026-10-01).

PDFs are a first-class source here, not an afterthought. One pipeline:

  read_document(bytes, url=..., content_type=...)  -> Document
      text PDFs     pdfplumber text + tables, page by page
      scanned PDFs  OCR (pytesseract + tesseract) when both are installed;
                    otherwise the document reports `ocr_status="OCR_UNAVAILABLE"`
                    and NOTHING is guessed from its images
      CSV / text    decoded as text (one "page")

  find_identifier_records(doc, identifiers, rule)  -> per-identifier hits
      Deterministic: a property identifier (parcel / account / case number)
      matches a document line only when its normalized form equals a whole
      token's normalized form (harvesters/enrichment/parcels.ID_RULES).
      Two different lines for one identifier -> AMBIGUOUS, never merged.

  acquisition_facts(doc)  -> contacts, steps, payment / deadline / deposit
      sentences, each with its page number. Office contacts only (phones,
      e-mails, mailing addresses the office publishes); nothing is inferred.

  notice_records(doc, identifiers, rule) -> for public / legal notices: the
      sale-date and amount sentences that name a matched identifier, with
      their page.

Every result carries provenance: source URL, document title, document date
(the document's own metadata / Last-Modified), page number, extraction
timestamp and method. A document's text is never stored or republished whole:
callers keep facts and link the customer to the source document.
"""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

from harvesters.enrichment.parcels import normalize_id

PHONE = re.compile(r"(?<!\d)(?:\(\d{3}\)\s*|\d{3}[-.\s])\d{3}[-.\s]\d{4}(?!\d)")
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
MONEY = re.compile(r"\$\s?\d[\d,]*(?:\.\d{2})?")
DATE = re.compile(r"\b(?:(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4}"
                  r"|\d{1,2}/\d{1,2}/\d{2,4}|\d{4}-\d{2}-\d{2})\b", re.I)
MAILING = re.compile(r"\b(?:P\.?\s?O\.?\s?Box\s+\d+[^.\n]{0,80}?\b[A-Z]{2}\s+\d{5}(?:-\d{4})?)", re.I)
# Acquisition vocabulary: a sentence is a candidate step / instruction only
# when it carries one of these (and is a sentence, not a table row).
STEP_VOCAB = re.compile(r"\b(purchase|apply|application|request|submit|contact|bid|deposit|payment|pay|certified funds|"
                        r"cashier|wire|deadline|form|registration|register|quote|minimum bid|first come)\b", re.I)
PAYMENT_VOCAB = re.compile(r"\b(certified funds|cashier'?s check|money order|wire transfer|cash|credit card|payment)\b", re.I)
DEADLINE_VOCAB = re.compile(r"\b(deadline|no later than|within \d+ days|by \d{1,2}:\d{2}|due)\b", re.I)
DEPOSIT_VOCAB = re.compile(r"\b(deposit)\b", re.I)
TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9\-./]*[A-Za-z0-9]|\d")
MAX_PAGES = 400

OCR_STATUSES = ("NOT_NEEDED", "OCR_USED", "OCR_UNAVAILABLE", "OCR_FAILED")


@dataclass
class Page:
    number: int                       # 1-based, as the document numbers its pages
    text: str
    tables: list = field(default_factory=list)   # list[list[list[str]]]
    ocr: bool = False


@dataclass
class Document:
    url: str
    title: str = ""
    document_date: str | None = None  # the document's own date (metadata / Last-Modified)
    content_type: str = ""
    method: str = ""                  # pdf_text | pdf_ocr | csv | text | unreadable
    ocr_status: str = "NOT_NEEDED"
    pages: list = field(default_factory=list)
    extracted_at: str = field(default_factory=lambda: datetime.now(timezone.utc).replace(microsecond=0).isoformat())
    error: str | None = None

    @property
    def readable(self) -> bool:
        return any((p.text or "").strip() for p in self.pages)

    def provenance(self, page: int | None = None) -> dict:
        out = {"source_url": self.url, "document_title": self.title or None, "document_date": self.document_date,
               "method": self.method, "extracted_at": self.extracted_at}
        if page is not None:
            out["page"] = page
        return {k: v for k, v in out.items() if v is not None}


def _pdf_date(raw) -> str | None:
    """PDF metadata date 'D:20250131...' -> '2025-01-31'."""
    m = re.match(r"D?:?(\d{4})(\d{2})(\d{2})", str(raw or ""))
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else None


def _ocr_available() -> bool:
    try:
        import pytesseract  # noqa: F401
        import shutil
        return shutil.which("tesseract") is not None
    except ImportError:
        return False


def read_document(data: bytes, *, url: str, content_type: str = "", last_modified: str | None = None,
                  ocr: bool = True) -> Document:
    ctype = (content_type or "").lower()
    is_pdf = data[:5] == b"%PDF-" or "pdf" in ctype or url.lower().split("?")[0].endswith(".pdf")
    doc = Document(url=url, content_type=content_type, document_date=_http_date(last_modified))
    if is_pdf:
        return _read_pdf(data, doc, ocr=ocr)
    text = data.decode("utf-8-sig", errors="replace")
    if "csv" in ctype or url.lower().split("?")[0].endswith(".csv"):
        rows = list(csv.reader(io.StringIO(text)))
        doc.method = "csv"
        doc.pages = [Page(1, "\n".join(" ".join(r) for r in rows), tables=[rows])]
        return doc
    doc.method = "text"
    doc.pages = [Page(1, text)]
    return doc


def _http_date(value: str | None) -> str | None:
    if not value:
        return None
    try:
        from email.utils import parsedate_to_datetime
        return parsedate_to_datetime(value).date().isoformat()
    except (TypeError, ValueError):
        return None


def _read_pdf(data: bytes, doc: Document, *, ocr: bool) -> Document:
    try:
        import pdfplumber
    except ImportError:
        doc.method, doc.error = "unreadable", "pdfplumber not installed"
        return doc
    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            meta = pdf.metadata or {}
            doc.title = str(meta.get("Title") or "").strip()
            doc.document_date = _pdf_date(meta.get("ModDate") or meta.get("CreationDate")) or doc.document_date
            needs_ocr = []
            for i, page in enumerate(pdf.pages[:MAX_PAGES], start=1):
                text = page.extract_text() or ""
                try:
                    tables = page.extract_tables() or []
                except Exception:  # noqa: BLE001 - a table the parser cannot read is just absent
                    tables = []
                doc.pages.append(Page(i, text, tables=[[[(c or "").strip() for c in row] for row in t] for t in tables]))
                if not text.strip():
                    needs_ocr.append(i)
            doc.method = "pdf_text"
            if needs_ocr:
                if not ocr:
                    doc.ocr_status = "OCR_UNAVAILABLE"
                elif not _ocr_available():
                    doc.ocr_status = "OCR_UNAVAILABLE"
                else:
                    try:
                        import pytesseract
                        for n in needs_ocr:
                            img = pdf.pages[n - 1].to_image(resolution=200).original
                            doc.pages[n - 1].text = pytesseract.image_to_string(img) or ""
                            doc.pages[n - 1].ocr = True
                        doc.ocr_status = "OCR_USED"
                        doc.method = "pdf_ocr" if len(needs_ocr) == len(doc.pages) else "pdf_text+ocr"
                    except Exception as exc:  # noqa: BLE001
                        doc.ocr_status, doc.error = "OCR_FAILED", type(exc).__name__
    except Exception as exc:  # noqa: BLE001 - a corrupt / encrypted PDF is unreadable, never guessed
        doc.method, doc.error = "unreadable", type(exc).__name__
    return doc


# ---------------------------------------------------------------- identifiers

def _lines(doc: Document):
    for p in doc.pages:
        for line in (p.text or "").splitlines():
            if line.strip():
                yield p.number, line.strip()
        for t in p.tables:
            for row in t:
                joined = " ".join(c for c in row if c)
                if joined.strip():
                    yield p.number, joined.strip()


@dataclass
class IdentifierHit:
    identifier_key: str
    status: str                       # MATCHED | AMBIGUOUS | MATCH_FAILED
    page: int | None = None
    line: str | None = None           # the matched line - for the CALLER to extract facts from; never logged


def find_identifier_records(doc: Document, identifiers, rule: str = "alnum") -> dict[str, IdentifierHit]:
    """For each property identifier, the one document line that carries it
    as a whole token. Normalized on both sides with the same named rule."""
    wanted = {}
    for raw in identifiers:
        k = normalize_id(raw, rule)
        if k:
            wanted[k] = raw
    found: dict[str, list] = {}
    for page, line in _lines(doc):
        seen_here = set()
        for tok in TOKEN.findall(line):
            k = normalize_id(tok, rule)
            if k and k in wanted and k not in seen_here:
                seen_here.add(k)
                found.setdefault(k, []).append((page, line))
    out = {}
    for k in wanted:
        hits = {(p, l) for p, l in found.get(k, [])}
        if len(hits) == 1:
            p, l = next(iter(hits))
            out[k] = IdentifierHit(k, "MATCHED", p, l)
        elif hits:
            out[k] = IdentifierHit(k, "AMBIGUOUS")
        else:
            out[k] = IdentifierHit(k, "MATCH_FAILED")
    return out


# ---------------------------------------------------------------- acquisition

def _sentences(text: str):
    for s in re.split(r"(?<=[.!?])\s+|\n{2,}", text or ""):
        s = re.sub(r"\s+", " ", s).strip()
        if len(s) > 20:
            yield s


def acquisition_facts(doc: Document, *, max_items: int = 25) -> dict:
    """Office contacts and process sentences the document publishes, each
    with its page. Table cells are not read here (they are inventory rows)."""
    phones, emails, mailing = {}, {}, {}
    steps, payment, deadlines, deposits, dates = [], [], [], [], []
    for p in doc.pages:
        text = p.text or ""
        for m in PHONE.finditer(text):
            phones.setdefault(m.group(0), p.number)
        for m in EMAIL.finditer(text):
            emails.setdefault(m.group(0), p.number)
        for m in MAILING.finditer(text):
            mailing.setdefault(re.sub(r"\s+", " ", m.group(0)).strip(), p.number)
        for s in _sentences(text):
            if len(steps) < max_items and STEP_VOCAB.search(s):
                steps.append({"text": s[:400], "page": p.number})
            if len(payment) < max_items and PAYMENT_VOCAB.search(s):
                payment.append({"text": s[:400], "page": p.number})
            if len(deadlines) < max_items and DEADLINE_VOCAB.search(s):
                deadlines.append({"text": s[:400], "page": p.number})
            if len(deposits) < max_items and DEPOSIT_VOCAB.search(s):
                deposits.append({"text": s[:400], "page": p.number})
            for m in DATE.finditer(s):
                if len(dates) < max_items:
                    dates.append({"date": m.group(0), "page": p.number})
    return {"phones": [{"value": k, "page": v} for k, v in phones.items()][:max_items],
            "emails": [{"value": k, "page": v} for k, v in emails.items()][:max_items],
            "mailing_addresses": [{"value": k, "page": v} for k, v in mailing.items()][:max_items],
            "steps": steps, "payment": payment, "deadlines": deadlines, "deposits": deposits, "dates": dates,
            "provenance": doc.provenance()}


def notice_records(doc: Document, identifiers, rule: str = "alnum") -> dict[str, dict]:
    """Public / legal notice facts per matched identifier: the sale dates and
    amounts on the identifier's own line. AMBIGUOUS / unmatched identifiers
    yield nothing."""
    out = {}
    for key, hit in find_identifier_records(doc, identifiers, rule).items():
        if hit.status != "MATCHED":
            continue
        out[key] = {"dates": DATE.findall(hit.line or ""), "amounts": MONEY.findall(hit.line or ""),
                    **doc.provenance(hit.page)}
    return out


def summarize(doc: Document) -> dict:
    """Value-free description of a document for public logs."""
    facts = acquisition_facts(doc)
    return {"url": doc.url, "title": doc.title or None, "document_date": doc.document_date, "method": doc.method,
            "ocr_status": doc.ocr_status, "pages": len(doc.pages), "readable": doc.readable, "error": doc.error,
            "tables": sum(len(p.tables) for p in doc.pages), "phones": len(facts["phones"]), "emails": len(facts["emails"]),
            "step_sentences": len(facts["steps"]), "payment_sentences": len(facts["payment"]),
            "deadline_sentences": len(facts["deadlines"])}
