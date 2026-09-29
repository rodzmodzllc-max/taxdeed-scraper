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
    # Regex with one group capturing a date in the DOCUMENT NAME/TITLE,
    # e.g. r"(\d{1,2}\.\d{1,2}\.\d{2,4})" for "6.2.2026_Resale_List.pdf".
    list_as_of_pattern: str | None = None
    list_as_of_formats: tuple[str, ...] = ("%m.%d.%Y", "%m.%d.%y", "%Y%m%d", "%m/%d/%Y", "%Y-%m-%d")
    columns_verified: bool = False   # True only after a human read the live list
    notes: str = ""


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


class TabularListAdapter:
    def __init__(self, cfg: TabularConfig) -> None:
        self.cfg = cfg
        self._lookup: dict[str, str] = {}
        for field_name, labels in vars(cfg.columns).items():
            for label in labels:
                self._lookup[_norm(label)] = field_name

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
            if not rows:
                continue
            score = max((sum(1 for c in r if _norm(c) in self._lookup) for r in rows), default=0)
            if score > best_score:
                best, best_score = rows, score
        return self._records(best, retrieved_at=retrieved_at, document_name=document_name)

    # ---- core ------------------------------------------------------------------
    def _records(self, rows: list[list[str]], *, retrieved_at: datetime, document_name: str | None) -> list[OtcRecord]:
        header_idx, fields = self._find_header(rows)
        if header_idx is None:
            return []
        as_of = list_as_of_from_name(document_name, self.cfg)
        out: list[OtcRecord] = []
        for raw in rows[header_idx + 1:]:
            values: dict[str, str] = {}
            for i, f in enumerate(fields):
                if f and i < len(raw) and raw[i].strip():
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
            out.append(OtcRecord(
                state=self.cfg.state, county=self.cfg.county, case_no=values["case_no"],
                source_id=self.cfg.source_id, source_authority=self.cfg.source_authority,
                inventory_type=self.cfg.inventory_type, retrieved_at=retrieved_at,
                parcel=values.get("parcel"), address=values.get("address"), legal_desc=values.get("legal_desc"),
                amount=amount, amount_kind=kind,
                list_url=self.cfg.list_url, document_url=self.cfg.document_url,
                purchase_url=self.cfg.purchase_url, purchase_url_kind=self.cfg.purchase_url_kind,
                list_as_of=as_of, source_status_text=values.get("status"), provenance=prov,
            ))
        return out

    def _find_header(self, rows: list[list[str]]) -> tuple[int | None, list[str | None]]:
        best_idx, best_fields, best_score = None, [], 1
        for idx, row in enumerate(rows):
            fields = [self._lookup.get(_norm(c)) for c in row]
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
