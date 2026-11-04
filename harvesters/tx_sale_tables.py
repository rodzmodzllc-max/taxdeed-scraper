"""Generic reader for the Texas tax-sale / resale PDF tables the delinquent-tax
law firms publish (PBFCM, MVBA). Pure parsing - no network.

Every firm's document is a pdfplumber-extractable table, but the column set
and order differ per client (observed live 2026-10-26 across 82 PBFCM and 7
MVBA documents): "Cause No: | Style of Case | Legal Description | Adjudged
Value | Estimated Minimum | Cad Account #", "Item No. | Cause No. | Legal
Description | Geographic ID | Minimum Bid", "TRACT | SUIT # | STYLE |
PROPERTY DESCRIPTION, APPROXIMATE ADDRESS, ACCT # | MIN BID", "Prop Id |
Legal Description | Suit #/Style of Suit | ... | Market Value", and more.
So nothing here is keyed to a firm or county: a header row is recognised by
its own words, each column is classified by its header text, and each data
row's values are read from the classified columns, with the source's own
in-cell labels ("Account #44517", "Adjudged Value: $89,680.00",
"Cause # 38470") taking precedence over a column guess.

What a row needs to be kept: an account (the appraisal district's
account / parcel id - the repository's identity for Texas, stored in
case_no) or, failing that, nothing - a cause number alone is never an
identity (one tax suit covers several parcels; CLAUDE.md, data-quality
sprint). Rows the document marks PULLED / CANCELLED / WITHDRAWN / SOLD /
REDEEMED / POSTPONED are skipped and counted, never stored as offered.

A figure is never invented: no minimum bid column -> min_bid None. A blank
bid-form table (columns such as "Amount of Offer" / "Your Bid" and no legal
description) is not a property list and is ignored.
"""
from __future__ import annotations

import io
import re
from dataclasses import dataclass, field

# --- header classification ----------------------------------------------------

_FIELD_PATTERNS: tuple[tuple[str, re.Pattern], ...] = (
    ("form", re.compile(r"amount\s+of\s+offer|amount\s+offered|your\s+bid|total\s+amount\s+of\s+bid|"
                        r"amount\s+accompanying|total\s+amount\s+offered|amount\s+of\s+payment|bid\s+amount|"
                        r"winning\s+bid|purchaser|winning\s+bidder|taxes\s+paid", re.I)),
    ("min_bid", re.compile(r"minimum|min\.?\s*bid|starting\s+bid|target\s+bid|orig\.?\s*min|\bbid\b", re.I)),
    ("value", re.compile(r"adjudged|appraised|market\s+value|tax\s+appraised", re.I)),
    ("cause", re.compile(r"cause|suit\s*(?:no\.?|#|number)|case\s*(?:no\.?|#|number)", re.I)),
    ("account", re.compile(r"account|acct|parcel|geographic|prop(?:erty)?\.?\s*id|app\.?\s*dist|cad\b|tax\s+account", re.I)),
    ("legal", re.compile(r"legal|property\s+description", re.I)),
    ("address", re.compile(r"address|location|situs", re.I)),
    ("item", re.compile(r"^\s*(item|tract|no\.?|#)\b", re.I)),
    ("notes", re.compile(r"notes?|status|sale\s+date|deed\s+date|struck|judgment", re.I)),
    ("style", re.compile(r"style|previous\s+owner|taxpayer|owner|name|styling", re.I)),
)
# A header row names at least two of these.
_HEADER_FIELDS = {"cause", "account", "legal", "min_bid", "value"}

_STATUS_WORDS = re.compile(r"\b(PULLED|CANCELL?ED|CANCEL|WITHDRAWN|WITHDRAWAL|SOLD|REDEEMED|POSTPONED|"
                           r"PAID\s+IN\s+FULL|BANKRUPTCY|STAYED)\b", re.I)
_MONEY = re.compile(r"\$\s*([0-9][0-9,]*(?:\.\d{1,2})?)")
_ACCOUNT_LABEL = re.compile(
    r"(?:CAD\s+)?(?:\bAccount|\bAcct\.?|\bGeographic\s+ID|\bProp(?:erty)?\s+ID|\bParcel\s+(?:ID|No\.?|Number|#)|\bGEO)\s*(?:No\.?|Number|#|ID)?\s*[:#]?\s*"
    r"([A-Z0-9][A-Z0-9\-\./]{2,40})", re.I)
_CAUSE_LABEL = re.compile(r"\b(?:Cause|Suit|Case)\s*(?:No\.?|Number|#)\s*[:#]?\s*([A-Z0-9][A-Z0-9,\-\./]{2,30})", re.I)
_VALUE_LABEL = re.compile(r"(?:Adjudged|Appraised|Market)\s+(?:Aggregate\s+)?Value[^$\d]{0,30}\$?\s*([0-9][0-9,]*(?:\.\d{1,2})?)", re.I)
_ADDRESS_LABEL = re.compile(r"(?:Approximate\s+)?(?:Property\s+)?Address(?:\s+per\s+CAD)?\s*:\s*([^\n;]{4,120})", re.I)
_ADDRESS_LINE = re.compile(r"^\d{1,6}\s+[A-Z0-9].{2,80}(?:,\s*[A-Z .]+)?(?:,?\s*TX\.?\s*\d{5}(?:-\d{4})?)?$", re.I)
_ADDRESS_TX = re.compile(r"(?:^|[),;]\s+)(\d{1,6}\s+[A-Za-z0-9 .'#-]{2,60},\s*[A-Za-z .]{2,40},?\s*(?:TX|Texas)\.?\s*\d{5}(?:-\d{4})?)")
_TX_ZIP_TAIL = re.compile(r"(?:,|\s)\s*(?:TX|Texas)\.?\s*\d{5}(?:-\d{4})?\s*$", re.I)


def address_in_cell(cell: str | None) -> str | None:
    """A situs address the cell carries after its legal description: the
    last line that starts with a house number, joined with the lines after
    it, when they end in 'TX 77506' / 'Texas 76513'. Or an address that
    follows '), ' / '; ' in a run-on description."""
    if not cell:
        return None
    lines = [l.strip() for l in str(cell).split("\n") if l.strip()]
    for i in range(len(lines) - 1, -1, -1):
        if re.match(r"^\d{1,6}\s+[A-Za-z0-9]", lines[i]):
            cand = " ".join(lines[i:])
            if _TX_ZIP_TAIL.search(cand) and len(cand) <= 120:
                return cand.strip(" ,;")
            break
    m = _ADDRESS_TX.search(re.sub(r"\s+", " ", str(cell)))
    return m.group(1).strip() if m else None
_ID_TOKEN = re.compile(r"^[A-Z0-9][A-Z0-9\-\./]{2,40}$", re.I)


def classify_header(text: str) -> set[str]:
    t = re.sub(r"\s+", " ", text or "").strip()
    if not t:
        return set()
    found = set()
    for name, pat in _FIELD_PATTERNS:
        if pat.search(t):
            found.add(name)
    # A bid-form column overrides the bid words it also contains.
    if "form" in found:
        found.discard("min_bid")
    return found


def _norm(cell) -> str:
    return re.sub(r"[ \t]+", " ", str(cell or "")).strip()


def _flat(cell) -> str:
    return re.sub(r"\s+", " ", str(cell or "")).strip()


def money(text: str | None) -> float | None:
    if not text:
        return None
    m = _MONEY.search(text)
    raw = m.group(1) if m else None
    if raw is None:
        m2 = re.search(r"(?<![\w/.-])([0-9]{1,3}(?:,[0-9]{3})+(?:\.\d{2})?|[0-9]+\.\d{2})(?![\w/-])", text)
        raw = m2.group(1) if m2 else None
    if raw is None:
        return None
    try:
        v = float(raw.replace(",", ""))
    except ValueError:
        return None
    return v if v > 0 else None


def plain_number(text: str | None) -> float | None:
    """A value written without a dollar sign ('Adjudged Value: 175110')."""
    if not text:
        return None
    m = re.search(r"([0-9][0-9,]*(?:\.\d{1,2})?)", text)
    if not m:
        return None
    try:
        v = float(m.group(1).replace(",", ""))
    except ValueError:
        return None
    return v if v > 0 else None


def _looks_like_id(tok: str) -> bool:
    tok = tok.strip().strip(",;")
    if not _ID_TOKEN.match(tok) or not any(c.isdigit() for c in tok):
        return False
    if re.fullmatch(r"\$?[0-9,]+\.\d{2}", tok):  # a money figure
        return False
    if re.fullmatch(r"\d{1,2}[-/]\w{2,3}[-/]\d{2,4}", tok):  # a date
        return False
    return len(re.sub(r"\D", "", tok)) >= 3


def first_id(text: str | None) -> str | None:
    """The first token of a cell that looks like an identifier. Spaces inside
    a broken-across-lines id ('11000-03000-00000-\\n000000') are joined."""
    if not text:
        return None
    lines = [l.strip() for l in str(text).split("\n") if l.strip()]
    for i, line in enumerate(lines):
        for tok in line.split():
            tok = tok.strip().strip(",;:")
            if _looks_like_id(tok):
                # Rejoin an id the PDF wrapped at a hyphen.
                if tok.endswith("-") and i + 1 < len(lines):
                    nxt = lines[i + 1].split()[0] if lines[i + 1].split() else ""
                    if nxt and re.fullmatch(r"[A-Z0-9\-]+", nxt, re.I):
                        tok = tok + nxt
                return tok.rstrip("-/.,")
    return None


def first_cause(text: str | None) -> str | None:
    """A cause / suit number as the cause column prints it (first token of
    the first line). Unlike an account it may carry a thousands comma
    ('30,346', 'T15,426')."""
    if not text:
        return None
    for line in str(text).split("\n"):
        for tok in line.split():
            tok = tok.strip().strip(";:").rstrip(".,/-")
            if re.fullmatch(r"[A-Z0-9][A-Z0-9,\-\./]{1,30}", tok, re.I) and sum(c.isdigit() for c in tok) >= 3:
                return tok
        break
    return first_id(text)


# --- row model ------------------------------------------------------------------

@dataclass
class SaleTableRow:
    account: str | None
    cause: str | None
    legal: str | None
    address: str | None
    min_bid: float | None
    value: float | None
    raw_status: str | None = None


@dataclass
class TableReadResult:
    rows: list[SaleTableRow] = field(default_factory=list)
    skipped_status: int = 0        # PULLED / CANCELLED / ... rows
    skipped_no_account: int = 0    # data-looking rows with no identifiable account
    tables_seen: int = 0
    tables_used: int = 0
    chars: int = 0                 # extractable text characters (0 = image-only document)
    text: str = ""                 # the document's text (first pages), for signals only

    @property
    def signal(self) -> str:
        if self.chars == 0:
            return "IMAGE_ONLY"
        if self.rows:
            return "ROWS"
        if self.tables_used == 0:
            return "NO_TABLE"
        return "NO_ROWS"


def _header_like(row: list) -> bool:
    """A row that can only be part of a header: no money, no long id, short cells."""
    cells = [_flat(c) for c in row]
    if any(_MONEY.search(c) for c in cells):
        return False
    for c in cells:
        if len(c) > 45:
            return False
        if any(sum(ch.isdigit() for ch in tok) >= 4 for tok in c.split()):
            return False
    return True


def _merge_header(rows: list[list], start: int) -> tuple[list[str], int]:
    """The header text per column, merging the header-only rows that follow
    (some documents split one header across up to six rows - 'Cause No:' /
    'District Court:' / 'Judgment Date:' each on its own row). Returns
    (texts, index of the first data row)."""
    head = [_flat(c) for c in rows[start]]
    nxt = start + 1
    while nxt < len(rows) and nxt - start < 7 and len(rows[nxt]) == len(head) and _header_like(rows[nxt]):
        head = [f"{a} {_flat(b)}".strip() for a, b in zip(head, rows[nxt])]
        nxt += 1
    return head, nxt


def _is_header(row: list) -> bool:
    fields = set()
    for c in row:
        fields |= classify_header(_flat(c))
    if any(_MONEY.search(_flat(c)) for c in row):
        return False
    return len(fields & _HEADER_FIELDS) >= 2 or ("legal" in fields and ("style" in fields or "cause" in fields))


def _column_map(head: list[str]) -> dict[int, set[str]]:
    """Each column's fields. A column with a blank header takes the fields of
    its labelled neighbour (right first, then left): some documents draw the
    header one cell off the data it labels."""
    base = {i: classify_header(h) for i, h in enumerate(head)}
    out = dict(base)
    for i, f in base.items():
        if f:
            continue
        for j in (i + 1, i - 1):
            if j in base and base[j] and not (j == i + 1 and base.get(i + 2) == set() and False):
                out[i] = set(base[j])
                break
    return out


def _extract_row(cells: list, colmap: dict[int, set[str]]) -> tuple[SaleTableRow | None, str]:
    texts = [_norm(c) for c in cells]
    joined = "\n".join(t for t in texts if t)
    if not joined.strip():
        return None, "blank"

    def cols(name):
        return [texts[i] for i, f in colmap.items() if i < len(texts) and name in f and texts[i]]

    # Status: in any non-legal cell, or a standalone line of the legal cell.
    status = None
    for i, t in enumerate(texts):
        f = colmap.get(i, set())
        if not t:
            continue
        if "legal" in f and len(t) > 60:
            for line in t.split("\n"):
                m = _STATUS_WORDS.fullmatch(line.strip(" *-()"))
                if m:
                    status = m.group(1).upper()
            continue
        m = _STATUS_WORDS.search(t)
        if m:
            status = m.group(1).upper()
    if status:
        return SaleTableRow(None, None, None, None, None, None, raw_status=status), "status"

    legal_cells = cols("legal")
    legal = max(legal_cells, key=len) if legal_cells else None
    if legal is None:
        # The longest text cell with letters is the description when the
        # column headers did not line up with the data.
        cand = [t for i, t in enumerate(texts) if t and re.search(r"[A-Za-z]{4}", t) and not colmap.get(i, set()) & {"style", "cause"}]
        legal = max(cand, key=len) if cand else None
        if legal and len(legal) < 15:
            legal = None

    # Account: the account column (a short cell - a long one is a description
    # the header drew over), else the source's own in-cell label
    # ("Account #44517", "GEO: 100-0072-0005-00000").
    account = None
    for t in cols("account"):
        if len(t) > 80:
            continue
        # "Parcel Number & Cause Number" columns: the first id is the parcel.
        account = first_id(t)
        if account:
            break
    if account is None:
        m = _ACCOUNT_LABEL.search(joined.replace("\n", " "))
        if m and _looks_like_id(m.group(1)):
            account = m.group(1)
    if account is not None:
        # "R08335/460520000002003", "12805/ R12805": the first form is the identity.
        account = account.split("/")[0].rstrip("-.,;:") or None
        if account and not _looks_like_id(account):
            account = None
    cause = None
    m = _CAUSE_LABEL.search(joined.replace("\n", " "))
    if m and _looks_like_id(m.group(1)):
        cause = m.group(1).rstrip(".;,/-")
    if cause is None:
        for i, f in colmap.items():
            if i < len(texts) and "cause" in f and "account" not in f and texts[i]:
                cause = first_cause(texts[i])
                if cause:
                    break
    if cause is None:
        # A combined "Parcel Number & Cause Number" cell: the second id.
        for t in cols("account"):
            ids = [tok for tok in re.split(r"\s+", t) if _looks_like_id(tok.strip(",;:"))]
            if len(ids) >= 2:
                cause = ids[1].strip(",;:")
                break
    if account and cause and account == cause:
        cause = None

    min_bid = None
    for t in cols("min_bid"):
        min_bid = money(t)
        if min_bid is not None:
            break
    value = None
    m = _VALUE_LABEL.search(joined.replace("\n", " "))
    if m:
        value = plain_number(m.group(1))
    if value is None:
        for t in cols("value"):
            if "min_bid" in colmap.get(texts.index(t), set()):
                continue
            value = money(t) or plain_number(t)
            if value is not None:
                break

    address = None
    m = _ADDRESS_LABEL.search(joined)
    if m:
        address = m.group(1).strip(" ,;")
    if address is None:
        for t in cols("address"):
            if t and t is not legal:
                address = _flat(t)
                break
    if address is None and legal:
        address = address_in_cell(legal)
    if address and len(address) > 160:
        address = address[:160]

    if not account:
        return None, "no_account"
    return SaleTableRow(account=account, cause=cause, legal=_flat(legal) if legal else None,
                        address=address, min_bid=min_bid, value=value), "row"


def read_tables(tables: list[list[list]]) -> TableReadResult:
    """Read already-extracted tables (pdfplumber `extract_tables()` output,
    page after page). A table with no header of its own continues the
    previous header when it has the same column count."""
    res = TableReadResult()
    colmap: dict[int, set[str]] | None = None
    width = None
    for table in tables:
        res.tables_seen += 1
        if not table:
            continue
        start = None
        for i, row in enumerate(table[:8]):
            if _is_header(row):
                start = i
                break
        if start is not None:
            # Header fragments drawn above the row that names two fields.
            while (start > 0 and _header_like(table[start - 1])
                   and any(classify_header(_flat(c)) for c in table[start - 1])):
                start -= 1
            head, first = _merge_header(table, start)
            cm = _column_map(head)
            allf = set().union(*cm.values()) if cm else set()
            if "form" in allf and "legal" not in allf:
                colmap, width = None, None  # a blank bid form, not a list
                continue
            colmap, width = cm, len(head)
            body = table[first:]
        elif colmap is not None and len(table[0]) == width:
            body = table
        else:
            continue
        res.tables_used += 1
        for row in body:
            if _is_header(row):
                continue
            r, why = _extract_row(row, colmap)
            if why == "status":
                res.skipped_status += 1
            elif why == "no_account":
                # A wrapped continuation of the previous row carries no id: not a property.
                if any(_MONEY.search(_flat(c)) for c in row):
                    res.skipped_no_account += 1
            elif r is not None:
                res.rows.append(r)
    return res


def read_pdf(data: bytes, max_pages: int = 80) -> TableReadResult:
    """Extract and read every table of a PDF document."""
    import pdfplumber  # noqa: PLC0415 - heavy, only when a document is read

    tables: list[list[list]] = []
    chars = 0
    text_parts: list[str] = []
    layout_parts: list[str] = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for n, page in enumerate(pdf.pages[:max_pages]):
            chars += len(page.chars)
            if n < 2:
                text_parts.append(page.extract_text() or "")
            tables.extend(page.extract_tables())
            layout_parts.append(page.extract_text(layout=True) or "")
    res = read_tables(tables)
    if not res.rows and chars:
        # No ruled table: the 'CASE # / JUDGMENT AMOUNT / VALUE AT TIME OF
        # JUDGMENT / ACCOUNT #' resale layout is plain positioned text.
        text_res = read_case_layout("\n".join(layout_parts))
        if text_res.rows or text_res.skipped_status:
            text_res.tables_seen = res.tables_seen
            res = text_res
    res.chars = chars
    res.text = "\n".join(text_parts)
    return res


_CASE_START = re.compile(r"^(\s*)(\d{2,4}-?\d{3,6}(?:-[A-Z0-9]+)?)\s+\$\s*([0-9][0-9,]*\.\d{2})")
_HCAD_ACCOUNT = re.compile(r"\b(\d{3}-\d{3}-\d{3}-\d{4}|\d{13}|\d{10,12})\b")
_SOLD_NOTE = re.compile(r"\bSold\s+at\s+the\b|\bSOLD\b|\bREDEEMED\b|\bPULLED\b|\bWITHDRAWN\b", re.I)


def read_case_layout(text: str) -> TableReadResult:
    """The text-positioned resale list ('CASE # | JUDGMENT AMOUNT | VALUE AT
    THE TIME OF JUDGMENT | ACCOUNT #'). An entry starts at a line that opens
    with a case number followed by a dollar figure and runs to the next such
    line. The judgment amount is the list's own figure (min_bid), the value
    is the value at judgment, the account is the first appraisal-district
    account number in the entry. An entry the list marks sold is skipped."""
    res = TableReadResult()
    if not re.search(r"CASE\s*#", text or "", re.I) or not re.search(r"JUDGMENT", text or "", re.I):
        return res
    lines = (text or "").split("\n")
    starts = [i for i, line in enumerate(lines) if _CASE_START.match(line)]
    if not starts:
        return res
    res.tables_used = 1
    for k, i in enumerate(starts):
        end = starts[k + 1] if k + 1 < len(starts) else min(len(lines), i + 14)
        entry = lines[i:end]
        for j, line in enumerate(entry[1:], 1):
            if re.search(r"If you would like|Prices listed|^\s*\*(?!\*)|Full Judgment Offer", line, re.I):
                entry = entry[:j]
                break
        m = _CASE_START.match(entry[0])
        cause = m.group(2)
        if _SOLD_NOTE.search("\n".join(entry)):
            res.skipped_status += 1
            continue
        amounts = _MONEY.findall(entry[0])
        min_bid = money("$" + amounts[0]) if amounts else None
        value = money("$" + amounts[1]) if len(amounts) > 1 else None
        acct = _HCAD_ACCOUNT.search(" ".join(entry))
        if not acct:
            res.skipped_no_account += 1
            continue
        col = entry[0].find("$")
        left = [line[:col].strip() for line in entry[1:] if line[:col].strip()]
        legal = " ".join(left[1:]) or None  # left[0] is the previous owner, never stored
        address = None
        for line in entry[1:]:
            right = line[col:].strip() if col > 0 else line.strip()
            mm = re.fullmatch(r"(\d{1,6}\s+[A-Za-z][A-Za-z0-9 .'#-]{2,50})", right)
            if mm and not _HCAD_ACCOUNT.search(mm.group(1)):
                address = mm.group(1).strip()
                break
        res.rows.append(SaleTableRow(account=acct.group(1), cause=cause, legal=legal, address=address,
                                     min_bid=min_bid, value=value))
    return res


_MONTHS = "JANUARY|FEBRUARY|MARCH|APRIL|MAY|JUNE|JULY|AUGUST|SEPTEMBER|OCTOBER|NOVEMBER|DECEMBER"
_SALE_DATE = re.compile(rf"\b({_MONTHS})\s+(\d{{1,2}})(?:ST|ND|RD|TH)?,?\s+(20\d\d)\b", re.I)


def sale_date_from_text(text: str) -> str | None:
    """The sale date a sale document states in its heading: the first
    'MONTH D, YYYY' within the first 400 characters. Never a guess from a
    file name or from 'the first Tuesday'."""
    head = (text or "")[:400]
    m = _SALE_DATE.search(head)
    if not m:
        return None
    month = _MONTHS.split("|").index(m.group(1).upper()) + 1
    day = int(m.group(2))
    if not 1 <= day <= 31:
        return None
    return f"{int(m.group(3)):04d}-{month:02d}-{day:02d}"
