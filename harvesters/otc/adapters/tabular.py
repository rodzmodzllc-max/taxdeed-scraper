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
    for fmt in ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d"):
        try:
            return datetime.strptime((text or "").strip(), fmt).date()
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

    def parse_html_table(self, html: str | bytes, *, retrieved_at: datetime, document_name: str | None = None) -> list[OtcRecord]:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        best: list[list[str]] = []
        best_score = 0
        for table in soup.find_all("table"):
            rows = [[c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])] for tr in table.find_all("tr")]
            rows = [r for r in rows if r]
            if not rows or not self._table_ok(rows):
                continue
            score = max((sum(1 for c in r if self.field_for(c)) for r in rows), default=0)
            if score > best_score:
                best, best_score = rows, score
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
        if len(body) == 1 and self.cfg.empty_phrases and any(
                _norm(p) == _norm(" ".join(c for c in body[0] if c.strip())) for p in self.cfg.empty_phrases):
            self.empty_statement = True
            return []
        out: list[OtcRecord] = []
        for raw in body:
            values: dict[str, str] = {}
            for i, fs in enumerate(fields):
                # A cell the source fills with a "not applicable" token carries no value.
                if fs and i < len(raw) and raw[i].strip() and _norm(raw[i]) not in NOT_A_VALUE:
                    for f in fs:
                        values[f] = raw[i].strip()
            if not values.get("case_no"):
                continue
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
            sale_date = _date(values.get("sale_date")) if "sale_date" in values else None
            if result_amount is not None:
                prov["result"] = f"column {self.cfg.columns.result_amount[0]!r} as published (a completed sale)"
            out.append(OtcRecord(
                state=self.cfg.state, county=self.cfg.county, case_no=values["case_no"],
                source_id=self.cfg.source_id, source_authority=self.cfg.source_authority,
                inventory_type=self.cfg.inventory_type, retrieved_at=retrieved_at,
                parcel=values.get("parcel"), address=values.get("address"), legal_desc=values.get("legal_desc"),
                amount=amount, amount_kind=kind,
                list_url=self.cfg.list_url, document_url=self.cfg.document_url,
                purchase_url=self.cfg.purchase_url, purchase_url_kind=self.cfg.purchase_url_kind,
                list_as_of=as_of, source_status_text=values.get("status"), provenance=prov,
                record_source=self.cfg.record_source, owner_name=values.get("owner_name"),
                certificate_no=values.get("certificate_no"),
                listing_closed=self.cfg.past_listing,
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
