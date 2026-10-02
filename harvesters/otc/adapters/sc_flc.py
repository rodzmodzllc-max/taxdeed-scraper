"""South Carolina Forfeited Land Commission (FLC) lists - Georgetown and
Spartanburg counties (2026-10-02, feat/sc-available-inventory).

Configured from the LIVE documents, read value-free by the manual evidence
job (`job=evidence`, `evidence_scope=sc_available`, scripts/capture_sc_available.py,
run 37033274319). What that read established, and what this module does
with it:

Georgetown County - "2026 FLC LIST - UPDATED MAY 2026" (PDF, 3 pages)
  * Tables headed  Group | Name | TMS # | Description | Tax Sale Date | Opening Bid
    under two section headings: MOBILE HOMES (pages 1-2) and LAND (page 2);
    page 3 is the commission's procedure text.
  * The program page: "The main purpose of the Forfeited Land Commission is
    the sale or assignment of properties that have been abandoned or were not
    bid upon at the delinquent tax sale"; property is offered "AS IS, WHERE
    IS"; "The transferring deed will be a Quit Claim Deed"; a bidder
    application is decided by the Committee, which then notifies "the total
    amount due".
  * AVAILABLE here = a LAND row whose tax sale is past South Carolina's
    twelve-month redemption period (S.C. Code § 12-51-90; the discovery read
    recorded the county's own statement that properties from the most recent
    sale are in the redemption period). A MOBILE HOMES row is personal
    property, not land, and is never an AVAILABLE land record; a row still in
    the redemption period, or whose sale date cannot be read, is not
    qualified (fail closed).
  * Identifier: the TMS # as published (`99-9999-999-99-99`; a mobile home
    carries a `.999` suffix). Normalization = whitespace removed, nothing
    else; a cell that does not match is MALFORMED and the row is rejected.

Spartanburg County - "2025 TAX SALE PROPERTIES (REAL ESTATE) AVAILABLE FOR
ASSIGNMENT" (PDF, 1 page)
  * Table headed  ITEM # | DESCRIPTION (best known property address) |
    DEFAULTING TAXPAYER (Owner Name) | MAP NUMBER | TOTAL TAX DUE (Bid Amount Needed).
  * What is offered is an ASSIGNMENT of the commission's bid from the 2025 tax
    sale during the redemption period - the owner may still redeem - and the
    program page says "All properties prior to 2023 TAX SALE can only be
    purchased by on-line auction sales". Neither is government-held property
    offered for purchase now, so NO Spartanburg row qualifies as AVAILABLE.
    The parser still reads the table so the identifier and parse counts are
    measured from the real document; every row is rejected with category
    `redemption_assignment`.
  * Identifier: the MAP NUMBER as published (`9-99-99-999.99`).

Nothing here fetches on its own and nothing here writes anywhere. `harvest()`
refuses before any request unless the source's publication governance is
APPROVED (both are REVIEW_REQUIRED - data/enrichment_source_catalog.csv,
data/available_publication_reviews.csv). Records are AVAILABLE ledger records
only (`record_source="laft"`); this module cannot produce an auction or a
certificate record. No owner name is read into a record.
"""
from __future__ import annotations

import io
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime

from ..model import AmountKind, InventoryType, OtcRecord, PurchaseUrlKind, SourceAuthority

EVIDENCE_RUN = "37033274319"
REDEMPTION_MONTHS = 12   # S.C. Code § 12-51-90


@dataclass(frozen=True)
class FlcConfig:
    source_id: str
    county: str
    program_url: str
    document_url: str
    document_title: str                    # the title the county gives the document (its link text / heading)
    id_label: str                          # the identifier column's header label
    id_pattern: str                        # the published identifier format (after whitespace removal)
    amount_label: str | None
    amount_kind: AmountKind
    sale_date_label: str | None = None
    description_label: str | None = None
    # Section heading (as printed, upper-case) -> section key; rows inherit the
    # nearest heading above their table (carried across pages).
    sections: tuple[tuple[str, str], ...] = ()
    qualifying_sections: tuple[str, ...] = ()
    # None = rows in a qualifying section can be AVAILABLE; otherwise the
    # rejection category every row gets (the document is not AVAILABLE inventory).
    not_available_reason: str | None = None
    application_url: str | None = None     # linked from the county's own program page
    application_kind: PurchaseUrlKind | None = None
    acquisition: tuple[tuple[str, str], ...] = ()   # quoted / summarised from the program page, run EVIDENCE_RUN
    list_as_of_text: str | None = None     # e.g. "updated May 2026" - a month, so never turned into a date


GEORGETOWN = FlcConfig(
    source_id="sc_georgetown_forfeited_land", county="Georgetown",
    program_url="https://www.gtcountysc.gov/415/Forfeited-Land-Commission",
    document_url="https://www.gtcountysc.gov/DocumentCenter/View/3019/2026-FLC-LIST---UPDATED-MAY-2026-PDF",
    document_title="2026 FLC LIST - UPDATED MAY 2026",
    id_label="TMS #", id_pattern=r"\d{2}-\d{4}-\d{3}-\d{2}-\d{2}(?:\.\d{3})?",
    amount_label="Opening Bid", amount_kind=AmountKind.OPENING_BID,
    sale_date_label="Tax Sale Date", description_label="Description",
    sections=(("MOBILE HOMES", "mobile_home"), ("MOBILE HOME", "mobile_home"), ("LAND", "land")),
    qualifying_sections=("land",),
    application_url="https://www.gtcountysc.gov/DocumentCenter/View/1587/FLC-Procedures-and-Bid-Apps-PDF",
    application_kind=PurchaseUrlKind.APPLICATION_FORM,
    acquisition=(
        ("mode", "application"),
        ("deed", "The transferring deed will be a Quit Claim Deed."),
        ("condition", "All property offered for sale by the Forfeited Land Commission of Georgetown County is offered on an "
                      "“AS IS, WHERE IS” basis. No warranty of any kind is offered to the purchaser."),
        ("decision", "Once a decision is made by the Committee you will be notified of their decision and the total amount "
                     "due via email or telephone number provided on the bidder application."),
        ("steps", "Complete the FLC bidder application (FLC Procedures and Bid Apps, linked from the program page) | "
                  "The Forfeited Land Commission's Committee decides the application | The county notifies the decision "
                  "and the total amount due"),
        ("payment", "Not published"),
        ("online_purchase", "No online purchase link on file"),
    ),
    list_as_of_text="updated May 2026",
)

SPARTANBURG = FlcConfig(
    source_id="sc_spartanburg_forfeited_land", county="Spartanburg",
    program_url="https://www.spartanburgcounty.org/388/Forfeited-Land-Commission",
    document_url="https://www.spartanburgcounty.gov/DocumentCenter/View/104130/Real-Estate-Tax-Sale-List",
    document_title="2025 TAX SALE PROPERTIES (REAL ESTATE) AVAILABLE FOR ASSIGNMENT",
    id_label="MAP NUMBER", id_pattern=r"\d-\d{2}-\d{2}-\d{3}\.\d{2}",
    amount_label="TOTAL TAX DUE", amount_kind=AmountKind.PUBLISHED_AMOUNT_KIND_UNSPECIFIED,
    description_label="DESCRIPTION",
    not_available_reason="redemption_assignment",
    acquisition=(
        ("mode", "assignment of the commission's tax-sale bid during the redemption period (not a purchase of property)"),
        ("prior_sales", "All properties prior to 2023 TAX SALE can only be purchased by on-line auction sales."),
        ("contact", "Please contact The Auditor's office concerning the Forfeited Land Commission (FLC) properties."),
    ),
)

SOURCES: dict[str, FlcConfig] = {c.source_id: c for c in (GEORGETOWN, SPARTANBURG)}

REJECTION_CATEGORIES = ("missing_identifier", "malformed_identifier", "duplicate_identifier", "personal_property_section",
                        "unknown_section", "in_redemption_period", "sale_date_unreadable", "redemption_assignment")


def norm_label(text: str | None) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9# ]", " ", (text or "").lower())).strip()


def normalize_identifier(raw: str | None) -> str:
    """The published identifier with whitespace removed - nothing else (no
    padding, no punctuation change). Deterministic, so the same cell always
    yields the same key."""
    return re.sub(r"\s+", "", raw or "")


def valid_identifier(cfg: FlcConfig, ident: str) -> bool:
    return bool(ident) and re.fullmatch(cfg.id_pattern, ident) is not None


def _amount(text: str | None) -> float | None:
    m = re.search(r"\d[\d,]*(?:\.\d\d)?", text or "")
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", ""))
    except ValueError:
        return None


def parse_sale_date(text: str | None) -> date | None:
    t = re.sub(r"\s+", " ", (text or "")).strip()
    for fmt in ("%m/%d/%Y", "%m/%d/%y", "%m-%d-%Y", "%B %d, %Y", "%b %d, %Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(t, fmt).date()
        except ValueError:
            continue
    m = re.fullmatch(r"(?:19|20)\d\d", t)
    if m:
        return date(int(t), 12, 31)   # a year alone: the latest day it can mean (conservative for redemption)
    return None


def redemption_over(sale: date, today: date) -> bool:
    """True once the twelve-month redemption period after `sale` has run."""
    months = sale.year * 12 + sale.month - 1 + REDEMPTION_MONTHS
    end = date(months // 12, months % 12 + 1, min(sale.day, 28))
    return today > end


@dataclass
class ParseResult:
    source_id: str
    pages: int = 0
    tables: int = 0
    data_rows: int = 0
    header_mapped_rows: int = 0
    valid_identifiers: int = 0
    rejected: Counter = field(default_factory=Counter)
    sections: Counter = field(default_factory=Counter)
    sale_years_qualifying_section: Counter = field(default_factory=Counter)
    amounts_published: int = 0
    records: list = field(default_factory=list)
    error: str | None = None


def _spans(header: list[str | None]) -> list[tuple[str, list[int]]]:
    """Each labelled header cell owns its column plus the unlabelled columns
    right of it (the PDFs leave value cells under blank header cells)."""
    spans: list[tuple[str, list[int]]] = []
    for i, cell in enumerate(header):
        label = norm_label(cell)
        if label:
            spans.append((label, [i]))
        elif spans:
            spans[-1][1].append(i)
    return spans


def _find(spans, label: str | None) -> list[int]:
    if not label:
        return []
    want = norm_label(label)
    for lab, cols in spans:
        if lab == want or lab.startswith(want + " ") or lab.endswith(" " + want) or f" {want} " in f" {lab} ":
            return cols
    return []


def _cell(row: list, cols: list[int]) -> str:
    for c in cols:
        if c < len(row) and (row[c] or "").strip():
            return re.sub(r"\s+", " ", row[c]).strip()
    return ""


def _heading_positions(page, cfg: FlcConfig) -> list[tuple[float, str]]:
    names = {norm_label(h).upper(): key for h, key in cfg.sections}
    out = []
    try:
        lines = page.extract_text_lines() or []
    except Exception:  # noqa: BLE001 - no text layer: no section headings
        lines = []
    for ln in lines:
        key = names.get(norm_label(ln.get("text", "")).upper())
        if key:
            out.append((float(ln.get("top", 0)), key))
    return sorted(out)


def parse_pages(cfg: FlcConfig, pages, *, retrieved_at: datetime) -> ParseResult:
    res = ParseResult(source_id=cfg.source_id)
    pages = list(pages)
    res.pages = len(pages)
    header: list | None = None
    section = None if cfg.sections else "document"
    seen: set[str] = set()
    today = retrieved_at.date()
    for page in pages:
        headings = _heading_positions(page, cfg)
        try:
            tables = page.find_tables() or []
        except Exception:  # noqa: BLE001
            tables = []
        for tbl in tables:
            res.tables += 1
            top = float(tbl.bbox[1]) if getattr(tbl, "bbox", None) else 0.0
            above = [k for y, k in headings if y <= top + 1]
            if above:
                section = above[-1]
            rows = [r for r in (tbl.extract() or []) if r and any((c or "").strip() for c in r)]
            body_start = 0
            want = f" {norm_label(cfg.id_label)} "
            for i, r in enumerate(rows[:3]):
                if any(want in f" {norm_label(c)} " for c in r if c):
                    header, body_start = r, i + 1   # a header row: the identifier label as whole words in a cell
                    break
            if header is None:
                continue   # a table before any header: nothing is mapped
            spans = _spans(header)
            id_cols = _find(spans, cfg.id_label)
            for row in rows[body_start:]:
                res.data_rows += 1
                if len(row) != len(header) or not id_cols:
                    res.rejected["missing_identifier"] += 1
                    continue
                res.header_mapped_rows += 1
                res.sections[section or "unknown"] += 1
                ident = normalize_identifier(_cell(row, id_cols))
                if not ident:
                    res.rejected["missing_identifier"] += 1
                    continue
                if not valid_identifier(cfg, ident):
                    res.rejected["malformed_identifier"] += 1
                    continue
                res.valid_identifiers += 1
                amount = _amount(_cell(row, _find(spans, cfg.amount_label))) if cfg.amount_label else None
                if amount is not None:
                    res.amounts_published += 1
                if cfg.not_available_reason:
                    res.rejected[cfg.not_available_reason] += 1
                    continue
                if section is None or section == "unknown":
                    res.rejected["unknown_section"] += 1
                    continue
                if section not in cfg.qualifying_sections:
                    res.rejected["personal_property_section"] += 1
                    continue
                sale = parse_sale_date(_cell(row, _find(spans, cfg.sale_date_label))) if cfg.sale_date_label else None
                if sale is None:
                    res.rejected["sale_date_unreadable"] += 1
                    continue
                res.sale_years_qualifying_section[str(sale.year)] += 1
                if not redemption_over(sale, today):
                    res.rejected["in_redemption_period"] += 1
                    continue
                if ident in seen:
                    res.rejected["duplicate_identifier"] += 1
                    continue
                seen.add(ident)
                res.records.append(_record(cfg, ident, amount, sale, row, spans, retrieved_at))
    return res


def _record(cfg: FlcConfig, ident: str, amount: float | None, sale: date, row, spans, retrieved_at) -> OtcRecord:
    desc = _cell(row, _find(spans, cfg.description_label)) or None
    prov = {
        "adapter": "sc_flc",
        "evidence_run": EVIDENCE_RUN,
        "document_title": cfg.document_title,
        "identifier": f"column {cfg.id_label!r} as published (whitespace removed)",
        "availability": "LAND section of the Forfeited Land Commission's current list; tax sale past the twelve-month "
                        "redemption period (S.C. Code § 12-51-90)",
        "tax_sale_date": f"column {cfg.sale_date_label!r} ({sale.isoformat()})",
        "amount": (f"column {cfg.amount_label!r} = {cfg.amount_kind.value}" if amount is not None else "Not published"),
        "acquisition": dict(cfg.acquisition),
    }
    if cfg.list_as_of_text:
        prov["list_as_of_text"] = cfg.list_as_of_text
    return OtcRecord(
        state="SC", county=cfg.county, case_no=ident, source_id=cfg.source_id,
        source_authority=SourceAuthority.GOVERNMENT_DIRECT, inventory_type=InventoryType.POST_SALE,
        retrieved_at=retrieved_at, parcel=ident, legal_desc=desc,
        amount=amount, amount_kind=cfg.amount_kind if amount is not None else AmountKind.NOT_PUBLISHED,
        list_url=cfg.program_url, document_url=cfg.document_url,
        purchase_url=cfg.application_url, purchase_url_kind=cfg.application_kind,
        provenance=prov, record_source="laft",
    )


def parse_document(source_id: str, data: bytes, *, retrieved_at: datetime, opener=None) -> ParseResult:
    """Parse the live PDF (bytes) - fail closed on anything that is not a PDF."""
    cfg = SOURCES[source_id]
    if not data.startswith(b"%PDF"):
        return ParseResult(source_id=source_id, error="NOT_A_PDF")
    try:
        if opener is None:
            import pdfplumber  # noqa: PLC0415
            opener = lambda b: pdfplumber.open(io.BytesIO(b))  # noqa: E731
        with opener(data) as pdf:
            return parse_pages(cfg, pdf.pages, retrieved_at=retrieved_at)
    except Exception as exc:  # noqa: BLE001 - a parse failure is FAILED, never zero rows
        return ParseResult(source_id=source_id, error=type(exc).__name__)


def outcome(res: ParseResult) -> str:
    """COMPLETE / EMPTY / FAILED for one read. A read that mapped no row or
    rejected a row as malformed is FAILED (format change), never EMPTY."""
    if res.error or res.header_mapped_rows == 0 or res.rejected.get("malformed_identifier"):
        return "FAILED"
    return "COMPLETE" if res.records else "EMPTY"


def summary(res: ParseResult) -> dict:
    """Counts only - safe to print in a public log."""
    return {"source_id": res.source_id, "outcome": outcome(res), "error": res.error, "pages": res.pages, "tables": res.tables,
            "data_rows": res.data_rows, "header_mapped_rows": res.header_mapped_rows,
            "valid_identifiers": res.valid_identifiers, "rejected": dict(sorted(res.rejected.items())),
            "sections": dict(sorted(res.sections.items())), "amounts_published": res.amounts_published,
            "sale_years_qualifying_section": dict(sorted(res.sale_years_qualifying_section.items())),
            "available_records": len(res.records)}


def match_existing(records: list[OtcRecord], properties: list[dict]) -> tuple[list[tuple[OtcRecord, dict]], list[OtcRecord]]:
    """Deterministic match: same state, same county, and the record's
    identifier equal to the property's published parcel after whitespace
    removal. Never owner name, address, legal description or any fuzzy rule.
    Returns (matched pairs, unmatched records) - an unmatched record is kept,
    never turned into a property."""
    index: dict[tuple[str, str, str], dict] = {}
    for p in properties:
        key = ((p.get("state") or "").upper(), (p.get("county") or "").lower(), normalize_identifier(p.get("parcel")))
        if key[2]:
            index.setdefault(key, p)
    matched, unmatched = [], []
    for r in records:
        p = index.get((r.state.upper(), r.county.lower(), normalize_identifier(r.parcel or r.case_no)))
        (matched.append((r, p)) if p else unmatched.append(r))
    return matched, unmatched


def harvest(source_id: str, fetch_bytes, *, retrieved_at: datetime, publication: str) -> ParseResult:
    """Read the live document - only when the source's publication governance
    is APPROVED. Refuses before any request otherwise."""
    if publication != "APPROVED":
        raise PermissionError(f"{source_id}: publication {publication} - 0 requests made")
    cfg = SOURCES[source_id]
    if cfg.not_available_reason:
        raise PermissionError(f"{source_id}: the document is not AVAILABLE inventory ({cfg.not_available_reason})")
    return parse_document(source_id, fetch_bytes(cfg.document_url), retrieved_at=retrieved_at)
