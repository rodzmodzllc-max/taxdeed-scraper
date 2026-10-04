"""Generic header-mapped tabular list adapter (CSV text or an HTML table).

This is the mechanism most of the Texas government struck-off / resale
lists the audit found would need (Camp, Hood, Fayette, Montgomery, Collin,
Brazoria, Dallas, Tom Green, Trinity, Grayson publish HTML tables; Travis
publishes XLSX). It is deliberately configuration-driven: a county is a
`TabularConfig` naming its column labels, its inventory type and what its
amount column means - never a county-specific parser.

It does NOT fetch. Bytes go in, `OtcRecord`s come out. Running it against
a live source requires (a) a verified TabularConfig, which only exists
after a human has fetched the list and read its columns, and (b) a
`gate.evaluate_source()` decision of allowed=True. Neither exists for any
Texas government source today.
"""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from datetime import date, datetime

from ..model import AmountKind, InventoryType, OtcRecord, PurchaseUrlKind, SourceAuthority


@dataclass(frozen=True)
class ColumnMap:
    """Source column label -> record field. Labels are matched after
    lower-casing and whitespace/punctuation collapse, like the FL
    harvesters' HEADER_MAP."""
    case_no: tuple[str, ...]
    parcel: tuple[str, ...] = ()
    address: tuple[str, ...] = ()
    legal_desc: tuple[str, ...] = ()
    amount: tuple[str, ...] = ()
    status: tuple[str, ...] = ()
    # Six-state sprint. A label ending in "*" matches any header that
    # STARTS with it (e.g. "purchase amount to*" for "Purchase Amount to
    # 10/31/2026" - the date in such a label is read as the list's as-of).
    owner_name: tuple[str, ...] = ()
    certificate_no: tuple[str, ...] = ()
    sale_date: tuple[str, ...] = ()
    result_amount: tuple[str, ...] = ()
    eligible_date: tuple[str, ...] = ()
    land_use: tuple[str, ...] = ()          # the source's own property type wording (AVAILABLE expansion)


@dataclass(frozen=True)
class TabularConfig:
    source_id: str
    state: str
    county: str
    source_authority: SourceAuthority
    inventory_type: InventoryType | None
    columns: ColumnMap
    amount_kind: AmountKind = AmountKind.NOT_PUBLISHED   # what the amount column IS, from its label
    list_url: str | None = None
    document_url: str | None = None
    purchase_url: str | None = None
    purchase_url_kind: PurchaseUrlKind | None = None
    # Every row of this table is a PAST sale listing (e.g. a "Previous Sales" table):
    # the record is closed; a result is stored only where a price column publishes one.
    past_listing: bool = False
    # Regex with one group capturing a date in the DOCUMENT NAME/TITLE,
    # e.g. r"(\d{1,2}\.\d{1,2}\.\d{2,4})" for "6.2.2026_Resale_List.pdf".
    list_as_of_pattern: str | None = None
    list_as_of_formats: tuple[str, ...] = ("%m.%d.%Y", "%m.%d.%y", "%Y%m%d", "%m/%d/%Y", "%Y-%m-%d")
    columns_verified: bool = False   # True only after a human read the live list
    notes: str = ""
    record_source: str = "laft"      # "laft" | "certificate" | "auction" (six-state sprint)
    # Table selection when a page carries several tables with the same
    # columns: a header label every chosen table must / must not carry.
    header_required: tuple[str, ...] = ()
    header_forbidden: tuple[str, ...] = ()
    # Phrases that, alone in the table's first data row, are the source's own
    # statement that the table is empty (e.g. "no current sales").
    empty_phrases: tuple[str, ...] = ()
    # Five-state sprint. `empty_patterns`: regexes that, matching the only data
    # row, are the source's own statement that no list is posted (e.g. "The
    # 2026 Tax Sale is scheduled for <date>." in place of the list).
    empty_patterns: tuple[str, ...] = ()
    # The HTML id of the one table to read, when a page carries several
    # tables with the same columns (Dane County WI: available vs sold).
    table_id: str | None = None
    # A regex on the AMOUNT cell with named groups `bid` and `price` for a
    # source that writes a completed sale into it (Dane County WI:
    # "$1234.00 SOLD - $5678.00"): bid = the published minimum bid, price =
    # the published sale price, and the row's status is the source's own
    # word ("SOLD"). A cell that does not match is read as a plain amount.
    amount_sold_pattern: str | None = None
    # Per-row links the source publishes, by link text (lower-case, exact):
    # link text -> PurchaseUrlKind value (e.g. {"bid form": "bid_form"}).
    # Only a link on the row itself, on the source's own host, is taken.
    row_links: tuple[tuple[str, str], ...] = ()
    # AVAILABLE sprint (2026-10-02). A regex the identifier cell must match in
    # full: a row whose "identifier" is a note line or a word (a workbook's
    # footer, a section label) is not a property and is counted, never kept.
    id_pattern: str | None = None
    # AVAILABLE expansion (2026-10-04). The source's OWN status words that mean
    # the row is offered (e.g. St. Louis LRA Parcel_Status "Available"). When
    # set, a row whose status cell is any other word - or blank - is counted
    # (`excluded_status`) and never kept: availability is the source's
    # statement, never inferred from presence on a mixed inventory list.
    status_include: tuple[str, ...] = ()
    # The source's own status words that mean the row is NOT offered right now
    # (e.g. Fayette PA's "Bid Received": a bid is pending the taxing bodies'
    # consent). Counted in `excluded_status`, never kept.
    status_exclude: tuple[str, ...] = ()


# Cell tokens a source uses for "no value here" (never a published value).
NOT_A_VALUE = frozenset({"na", "none", ""})   # after _norm: "N/A" -> "na", "-" / "--" -> ""

def _norm(label: str) -> str:
    key = re.sub(r"[^a-z0-9()#. ]", "", (label or "").strip().lower())
    return re.sub(r"\s+", " ", key).strip()


def _amount(text: str | None) -> float | None:
    if text is None:
        return None
    cleaned = re.sub(r"[^0-9.]", "", str(text))
    if not re.match(r"^\d+(\.\d+)?$", cleaned):
        return None
    return float(cleaned)


def list_as_of_from_name(name: str | None, cfg: TabularConfig) -> date | None:
    """The list's own date from its document name - or None. Never today."""
    if not name or not cfg.list_as_of_pattern:
        return None
    m = re.search(cfg.list_as_of_pattern, name)
    if not m:
        return None
    for fmt in cfg.list_as_of_formats:
        try:
            return datetime.strptime(m.group(1), fmt).date()
        except ValueError:
            continue
    return None


DATE_IN_LABEL = re.compile(r"(\d{1,2}/\d{1,2}/\d{4})")


def _date(text: str | None) -> date | None:
    # A date may carry a time after it ("10/6/2026 1:00 PM" - a bid deadline).
    token = (text or "").strip().split(" ")[0]
    for fmt in ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d"):
        try:
            return datetime.strptime(token, fmt).date()
        except ValueError:
            continue
    return None


class TabularListAdapter:
    def __init__(self, cfg: TabularConfig) -> None:
        self.cfg = cfg
        # A label may fill several fields (e.g. CERT # is both the record id
        # and the certificate number), so each maps to a tuple of fields.
        self._lookup: dict[str, tuple[str, ...]] = {}
        self._prefixes: list[tuple[str, str]] = []
        for field_name, labels in vars(cfg.columns).items():
            for label in labels:
                if label.endswith("*"):
                    self._prefixes.append((_norm(label[:-1]), field_name))
                else:
                    self._lookup[_norm(label)] = self._lookup.get(_norm(label), ()) + (field_name,)
        self.empty_statement = False
        self.label_as_of: date | None = None
        self._row_links: list[dict[str, str]] = []
        self.rejected_ids = 0
        self.excluded_status = 0

    def field_for(self, label: str) -> tuple[str, ...] | None:
        """Every record field a column label fills (None = not a mapped column)."""
        key = _norm(label)
        if key in self._lookup:
            return self._lookup[key]
        for prefix, field_name in self._prefixes:
            if key.startswith(prefix):
                return (field_name,)
        return None

    def _table_ok(self, rows: list[list[str]]) -> bool:
        labels = {_norm(c) for r in rows[:3] for c in r}
        if any(_norm(x) not in labels for x in self.cfg.header_required):
            return False
        return not any(_norm(x) in labels for x in self.cfg.header_forbidden)

    # ---- inputs --------------------------------------------------------------
    def parse_csv(self, text: str, *, retrieved_at: datetime, document_name: str | None = None) -> list[OtcRecord]:
        reader = csv.reader(io.StringIO(text))
        rows = [r for r in reader if any(c.strip() for c in r)]
        return self._records(rows, retrieved_at=retrieved_at, document_name=document_name)

    def parse_rows(self, rows: list[list[str]], *, retrieved_at: datetime, document_name: str | None = None) -> list[OtcRecord]:
        """Rows already split into cells (a PDF table, a workbook)."""
        rows = [[re.sub(r"\s+", " ", c or "").strip() for c in r] for r in rows if any((c or "").strip() for c in r)]
        return self._records(rows, retrieved_at=retrieved_at, document_name=document_name)

    def parse_html_table(self, html: str | bytes, *, retrieved_at: datetime, document_name: str | None = None) -> list[OtcRecord]:
        from bs4 import BeautifulSoup
        from urllib.parse import urljoin, urlsplit
        soup = BeautifulSoup(html, "html.parser")
        best: list[list[str]] = []
        best_links: list[dict[str, str]] = []
        best_score = 0
        wanted = {t: k for t, k in self.cfg.row_links}
        host = urlsplit(self.cfg.list_url or "").hostname
        tables = soup.find_all("table", id=self.cfg.table_id) if self.cfg.table_id else soup.find_all("table")
        for table in tables:
            trs = [tr for tr in table.find_all("tr") if tr.find_all(["th", "td"])]
            rows = [[c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])] for tr in trs]
            links = []
            for tr in trs:
                found = {}
                for a in tr.find_all("a", href=True):
                    kind = wanted.get(a.get_text(" ", strip=True).lower())
                    href = urljoin(self.cfg.list_url or "", a["href"].strip())
                    if kind and href.startswith("https://") and urlsplit(href).hostname == host:
                        found[kind] = href
                links.append(found)
            if not rows or not self._table_ok(rows):
                continue
            score = max((sum(1 for c in r if self.field_for(c)) for r in rows), default=0)
            if score > best_score:
                best, best_links, best_score = rows, links, score
        self._row_links = best_links
        return self._records(best, retrieved_at=retrieved_at, document_name=document_name)

    # ---- core ------------------------------------------------------------------
    def _records(self, rows: list[list[str]], *, retrieved_at: datetime, document_name: str | None) -> list[OtcRecord]:
        header_idx, fields = self._find_header(rows)
        if header_idx is None:
            return []
        as_of = list_as_of_from_name(document_name, self.cfg)
        # A date written into a matched header ("Purchase Amount to 10/31/2026")
        # is the list's own as-of date for that figure.
        for cell, f in zip(rows[header_idx], fields):
            m = DATE_IN_LABEL.search(cell or "") if f else None
            if m and _date(m.group(1)):
                self.label_as_of = _date(m.group(1))
        body = rows[header_idx + 1:]
        links = self._row_links[header_idx + 1:] if self._row_links else [{} for _ in body]
        only = " ".join(c for c in body[0] if c.strip()) if len(body) == 1 else ""
        if len(body) == 1 and (any(_norm(p) == _norm(only) for p in self.cfg.empty_phrases)
                               or any(re.search(p, only, re.I) for p in self.cfg.empty_patterns)):
            self.empty_statement = True
            return []
        out: list[OtcRecord] = []
        for raw, row_links in zip(body, links + [{}] * (len(body) - len(links))):
            values: dict[str, str] = {}
            for i, fs in enumerate(fields):
                # A cell the source fills with a "not applicable" token carries no value.
                if fs and i < len(raw) and raw[i].strip() and _norm(raw[i]) not in NOT_A_VALUE:
                    for f in fs:
                        values[f] = raw[i].strip()
            if not values.get("case_no"):
                continue
            if [_norm(c) for c in raw] == [_norm(c) for c in rows[header_idx]]:
                continue                      # the header repeated on a later page / sheet
            if self.cfg.id_pattern and not re.fullmatch(self.cfg.id_pattern, values["case_no"]):
                self.rejected_ids += 1
                continue
            if self.cfg.status_include and _norm(values.get("status", "")) not in {_norm(s) for s in self.cfg.status_include}:
                self.excluded_status += 1
                continue
            if self.cfg.status_exclude and _norm(values.get("status", "")) in {_norm(s) for s in self.cfg.status_exclude}:
                self.excluded_status += 1
                continue
            sold_price = None
            status_text = values.get("status")
            if self.cfg.amount_sold_pattern and values.get("amount"):
                m = re.search(self.cfg.amount_sold_pattern, values["amount"])
                if m:
                    values["amount"] = m.group("bid")
                    sold_price = _amount(m.group("price"))
                    status_text = "SOLD"
            amount = _amount(values.get("amount")) if "amount" in values else None
            kind = self.cfg.amount_kind if amount is not None else AmountKind.NOT_PUBLISHED
            prov = {
                "adapter": "tabular",
                "columns": {f: True for f in values},
                "amount": (f"column {self.cfg.columns.amount[0]!r} = {kind.value}" if amount is not None else "no amount column value"),
            }
            if as_of:
                prov["list_as_of"] = f"parsed from document name {document_name!r}"
            elif self.label_as_of:
                as_of = self.label_as_of
                prov["list_as_of"] = "the date written in the amount column's own header"
            if values.get("eligible_date"):
                prov["date_eligible_for_auction"] = values["eligible_date"]
            result_amount = _amount(values.get("result_amount")) if "result_amount" in values else None
            if sold_price is not None:
                result_amount = sold_price
                prov["result"] = f"the amount cell's own 'SOLD - <price>' wording (a completed sale, as published)"
            sale_date = _date(values.get("sale_date")) if "sale_date" in values else None
            if result_amount is not None and "result" not in prov:
                prov["result"] = f"column {self.cfg.columns.result_amount[0]!r} as published (a completed sale)"
            purchase_url, purchase_kind = self.cfg.purchase_url, self.cfg.purchase_url_kind
            if row_links and self.cfg.record_source == "auction" and status_text is None:
                kind_name, href = next(iter(row_links.items()))
                purchase_url, purchase_kind = href, PurchaseUrlKind(kind_name)
                prov["purchase_url"] = f"the row's own '{next(t for t, k in self.cfg.row_links if k == kind_name)}' link"
            out.append(OtcRecord(
                state=self.cfg.state, county=self.cfg.county, case_no=values["case_no"],
                source_id=self.cfg.source_id, source_authority=self.cfg.source_authority,
                inventory_type=self.cfg.inventory_type, retrieved_at=retrieved_at,
                parcel=values.get("parcel"), address=values.get("address"), legal_desc=values.get("legal_desc"),
                amount=amount, amount_kind=kind,
                list_url=self.cfg.list_url, document_url=self.cfg.document_url,
                purchase_url=purchase_url, purchase_url_kind=purchase_kind,
                list_as_of=as_of, source_status_text=status_text, provenance=prov,
                record_source=self.cfg.record_source, owner_name=values.get("owner_name"),
                certificate_no=values.get("certificate_no"), land_use=values.get("land_use"),
                listing_closed=self.cfg.past_listing,
                published_outcome="sold" if sold_price is not None else None,
                sale_date=sale_date if self.cfg.record_source == "auction" else None,
                result_amount=result_amount if self.cfg.record_source == "auction" else None,
                result_date=sale_date if (result_amount is not None and self.cfg.record_source == "auction") else None,
            ))
        return out

    def _find_header(self, rows: list[list[str]]) -> tuple[int | None, list[str | None]]:
        best_idx, best_fields, best_score = None, [], 1
        for idx, row in enumerate(rows):
            fields = [self.field_for(c) for c in row]
            score = sum(1 for f in fields if f)
            if score > best_score:
                best_idx, best_fields, best_score = idx, fields, score
        return best_idx, best_fields


def pdf_table_rows(data: bytes) -> list[list[str]]:
    """Every table row of a text PDF, page after page (pdfplumber's own table
    finder; a header repeated on each page is just another row - the id
    pattern rejects it). A scanned PDF yields no rows (never a guess)."""
    import pdfplumber  # noqa: PLC0415 - only the PDF sources need it
    rows: list[list[str]] = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables() or []:
                rows.extend([[c if c is not None else "" for c in r] for r in table])
    return rows


# The Texas government-direct lists the audit found, and why each is a
# candidate rather than a configured adapter. `blocker` is what a human
# must do before a TabularConfig can exist. None of these is fetched by
# anything in this repository.
TX_CANDIDATES: tuple[tuple[str, str, str, str], ...] = (
    # county, expected format, adapter family, blocker
    ("Travis", "XLSX", "tabular (needs an XLSX reader - openpyxl not a dependency yet)", "fetch ResaleList.xlsx; read columns; terms"),
    ("Grayson", "PORTAL", "tabular (HTML) if the portal renders a table server-side", "fetch; confirm rendering; terms"),
    ("Camp", "HTML_TABLE", "tabular (HTML)", "fetch; read columns; terms"),
    ("Hood", "HTML_TABLE", "tabular (HTML)", "fetch; read columns; terms"),
    ("Fayette", "HTML_TABLE", "tabular (HTML)", "fetch; read columns; terms"),
    ("Montgomery", "HTML_TABLE", "tabular (HTML)", "fetch; read columns; terms"),
    ("Collin", "HTML_TABLE", "tabular (HTML)", "fetch; read columns; terms"),
    ("Brazoria", "HTML_TABLE", "tabular (HTML)", "fetch; read columns; terms"),
    ("Dallas", "HTML_TABLE", "tabular (HTML) or a downloadable list", "fetch; locate the list file; terms"),
    ("Jefferson", "PDF", "PDF header-map (scripts/harvest_laft_pdfs.py pattern)", "fetch dated PDFs; distinguish resale list from sale notice; terms"),
    ("Gregg", "PDF", "PDF header-map", "fetch; read columns; terms"),
    ("Orange", "PDF", "PDF header-map", "fetch 04.09.25 listing; confirm currency; terms"),
    ("Jim Wells", "PDF", "PDF header-map", "fetch; read columns; terms; reconcile with the LGBS rows"),
    ("Tom Green", "HTML_TABLE", "tabular (HTML) + procedures PDF", "fetch; read columns; terms"),
    ("Trinity", "HTML_TABLE", "tabular (HTML)", "fetch; read columns; terms"),
    ("Bexar", "UNKNOWN", "unknown until the DocumentCenter container is opened", "open DocumentCenter View/41852; terms"),
)
