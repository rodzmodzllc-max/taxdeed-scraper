"""Alabama ADOR weekly county transcripts - a second Alabama AVAILABLE source
(2026-10-25). GATED, UNREVIEWED, never runnable: Alabama is a registered,
NON-production state (harvesters/governance/states.py) and `can_run()`
refuses before any request until the state is activated AND this source is
enabled.

THE SOURCE. The Alabama Department of Revenue, Property Tax Division, page
"Tax Delinquent Property and Land Sales" (`ADOR_LAND_SALES_URL`) says, in
its own words (read live 2026-10-25):

  * "Transcripts of Delinquent Property. Below is a listing by county of
    tax delinquent properties currently in State inventory. ... The
    transcripts are updated weekly. This listing does not contain the
    physical address of the property."              -> STATE_HELD_TAX_LAND, no address
  * "You may request a price quote for state-held tax delinquent property
    by submitting an electronic application. Once your price quote is
    processed it will be emailed to you. You are given 10 calendar days
    from the date on the price quote to remit your payment."
                                                    -> QUOTED_ON_APPLICATION, no price
  * One link per county to
    /wp-content/uploads/property-tax-transcripts/WWW_TRANS_<NN>.PDF - 68
    files: the 67 counties with Jefferson split into its Birmingham (01)
    and Bessemer (68) divisions. The file number is the page's OWN
    county -> file mapping (`TRANSCRIPT_FILES`, copied from the page's
    links), NOT an alphabetical code: 01 Jefferson-Birmingham, 02 Mobile,
    03 Montgomery, 04 Autauga, ...

The agency's "How to Read the Transcript" document (`ADOR_INSTRUCTIONS_URL`,
read 2026-10-25) names the columns: NAME (the name the property was
assessed in when it sold for taxes), CO. (county code), YR. (the year the
property sold to the State), C/S# (the certificate of sale number assigned
by the office), CLASS (assessment class), CODE (the assessor's city code),
PARCEL ID, DESCRIPTION (metes and bounds or lot and block); a second line
carries the amount due at the time of the tax sale ("AMT BID AT TAX SALE").

WHAT WAS VERIFIED, AND HOW (2026-10-25). ONE transcript (file 01) was
fetched from the sandbox and read value-free: an Oracle Reports text PDF,
landscape, a four-line page header ("STATE OF ALABAMA-DEPARTMENT OF
REVENUE-PROPERTY TAX DIVISION DATE : mm/dd/yyyy", "TRANSCRIPT OF TAX
DELINQUENT LAND AVAILABLE FOR SALE", "PAGE NO: n", the column line), then
one record per first line (name, 2-digit CO., 2-digit YR., 8-digit C/S#,
1-digit CLASS, 2-digit CODE, PARCEL ID, description start), a second line
starting with the amount, and description continuation lines. No PDF
table structure (pdfplumber finds no tables), so this is a LINE parser,
not tabular.pdf_table_rows. The other 67 files were NOT read; their
parcel-ID shapes may differ. Every committed fixture is SYNTHETIC
(tests/python/fixtures/alabama/transcript_SYNTHETIC.txt) - no real
transcript, name or identifier is in the repository.

So `TRANSCRIPT_SOURCE.parser_fixture_validated` stays False and
`classify_outcome()` reports nothing COMPLETE and nothing EMPTY - rows are
INCOMPLETE (observed, completeness not asserted) - the same rule as the
search-page adapter (alabama.py).

FIELDS. case_no = C/S# as published (8 digits, leading zeros kept); parcel
= PARCEL ID as published; legal_desc = the description lines joined; the
county from the file's own mapping (a CO. code that disagrees with the
file's is counted and the row rejected). NEVER mapped: NAME (an owner /
assessed name), CLASS, CODE, and the amount bid at tax sale (a historical
figure from the county sale, not the State's price - the price is quoted on
application). list_url / document_url = the county's own transcript PDF;
purchase_url = the land-sales page as PURCHASE_INSTRUCTIONS
(the application is generated from the search page; no per-property link
exists in the transcript and none is constructed).

This module imports no HTTP client (tests/python/test_otc_framework.py):
`harvest()` takes an injected `fetch_bytes(url)`.
"""
from __future__ import annotations

import hashlib
import io
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Callable

from ...governance import states
from ..model import AmountKind, InventoryType, OtcRecord, PurchaseUrlKind, SourceAuthority
from .alabama import ADOR_LAND_SALES_URL, ALABAMA_COUNTIES

__all__ = ["ADOR_INSTRUCTIONS_URL", "TRANSCRIPT_FILES", "TRANSCRIPT_SOURCE", "TRANSCRIPT_URL", "TranscriptConfig",
           "TranscriptParse", "TranscriptOutcome", "can_run", "classify_outcome", "harvest", "parse_lines",
           "parse_pdf", "transcript_url"]

STATE = "AL"
SOURCE_ID = "al_ador_transcripts"
EVIDENCE_DATE = "2026-10-25"
TRANSCRIPT_URL = "https://www.revenue.alabama.gov/wp-content/uploads/property-tax-transcripts/WWW_TRANS_{nn}.PDF"
ADOR_INSTRUCTIONS_URL = ("https://www.revenue.alabama.gov/wp-content/uploads/2022/06/"
                         "2017_05_DelinquentPropert_CountyTranscriptInstrucitons.pdf")

# The land-sales page's own county -> file links (read 2026-10-25). The
# value is (county, division label as the page prints it, or None).
TRANSCRIPT_FILES: dict[str, tuple[str, str | None]] = {
    "01": ("Jefferson", "Jefferson-Birmingham"), "02": ("Mobile", None), "03": ("Montgomery", None),
    "04": ("Autauga", None), "05": ("Baldwin", None), "06": ("Barbour", None), "07": ("Bibb", None),
    "08": ("Blount", None), "09": ("Bullock", None), "10": ("Butler", None), "11": ("Calhoun", None),
    "12": ("Chambers", None), "13": ("Cherokee", None), "14": ("Chilton", None), "15": ("Choctaw", None),
    "16": ("Clarke", None), "17": ("Clay", None), "18": ("Cleburne", None), "19": ("Coffee", None),
    "20": ("Colbert", None), "21": ("Conecuh", None), "22": ("Coosa", None), "23": ("Covington", None),
    "24": ("Crenshaw", None), "25": ("Cullman", None), "26": ("Dale", None), "27": ("Dallas", None),
    "28": ("DeKalb", None), "29": ("Elmore", None), "30": ("Escambia", None), "31": ("Etowah", None),
    "32": ("Fayette", None), "33": ("Franklin", None), "34": ("Geneva", None), "35": ("Greene", None),
    "36": ("Hale", None), "37": ("Henry", None), "38": ("Houston", None), "39": ("Jackson", None),
    "40": ("Lamar", None), "41": ("Lauderdale", None), "42": ("Lawrence", None), "43": ("Lee", None),
    "44": ("Limestone", None), "45": ("Lowndes", None), "46": ("Macon", None), "47": ("Madison", None),
    "48": ("Marengo", None), "49": ("Marion", None), "50": ("Marshall", None), "51": ("Monroe", None),
    "52": ("Morgan", None), "53": ("Perry", None), "54": ("Pickens", None), "55": ("Pike", None),
    "56": ("Randolph", None), "57": ("Russell", None), "58": ("Shelby", None), "59": ("St. Clair", None),
    "60": ("Sumter", None), "61": ("Talladega", None), "62": ("Tallapoosa", None), "63": ("Tuscaloosa", None),
    "64": ("Walker", None), "65": ("Washington", None), "66": ("Wilcox", None), "67": ("Winston", None),
    "68": ("Jefferson", "Jefferson-Bessemer"),
}
assert len(TRANSCRIPT_FILES) == 68 and {c for c, _ in TRANSCRIPT_FILES.values()} == ALABAMA_COUNTIES


def transcript_url(nn: str) -> str:
    if nn not in TRANSCRIPT_FILES:
        raise ValueError(f"not a transcript file number on the land-sales page: {nn!r}")
    return TRANSCRIPT_URL.format(nn=nn)


# --- the page layout, as read from file 01 (value-free) --------------------
HEADER_AGENCY = re.compile(r"^STATE OF ALABAMA-DEPARTMENT OF REVENUE-PROPERTY TAX DIVISION\s+DATE\s*:\s*(\d{1,2}/\d{1,2}/\d{4})\s*$")
HEADER_TITLE = "TRANSCRIPT OF TAX DELINQUENT LAND AVAILABLE FOR SALE"
HEADER_PAGE = re.compile(r"^PAGE\s+NO\s*:\s*\d+\s*$")
HEADER_COLUMNS = re.compile(r"^Name\s+Amt Bid at Tax Sale\s+CO\.\s+YR\.\s+C/S#\s+CLASS\s+CODE\s+PARCEL ID\s+DESCRIPTION\s*$")
# First line of a record. The name is lazily matched; the fixed-width
# numeric block (CO. YR. C/S# CLASS CODE) anchors it.
RECORD = re.compile(r"^(?P<name>.*?\S)\s*(?P<co>\d{2})\s+(?P<yr>\d{2})\s+(?P<cs>\d{8})\s+(?P<cls>\d)\s+(?P<code>\d{2})"
                    r"\s+(?P<parcel>\S+)(?:\s+(?P<desc>.*))?$")
AMOUNT_LINE = re.compile(r"^(?P<amt>\d[\d,]*(?:\.\d{1,2})?)(?:\s+(?P<rest>.*))?$")
AMOUNT_LINE_STRICT = re.compile(r"^(?P<amt>\d[\d,]*\.\d{2})(?:\s+(?P<rest>.*))?$")
PARCEL_PLAUSIBLE = re.compile(r"^(?=.*\d)[0-9A-Za-z.\-]{1,40}$")


@dataclass(frozen=True)
class TranscriptConfig:
    source_id: str
    files: dict
    list_url: str
    instructions_url: str
    purchase_url: str
    purchase_url_kind: PurchaseUrlKind
    inventory_type: InventoryType = InventoryType.STATE_HELD_TAX_LAND
    amount_kind: AmountKind = AmountKind.QUOTED_ON_APPLICATION
    source_authority: SourceAuthority = SourceAuthority.GOVERNMENT_DIRECT
    record_source: str = "laft"
    publishing_unit_name: str = "Alabama Department of Revenue, Property Tax Division"
    source_terminology: str = ""
    # ---- activation evidence (all false until a reviewed commit says otherwise)
    live_verified: bool = False                # one transcript (01) read value-free 2026-10-25; not all 68
    parser_fixture_validated: bool = False     # a fixture captured from the live source - none may be committed
    enabled: bool = False
    notes: str = ""

    def __post_init__(self) -> None:
        if self.purchase_url_kind is not PurchaseUrlKind.PURCHASE_INSTRUCTIONS:
            raise ValueError("the land-sales page is an instructions page, never a property purchase link")
        if self.amount_kind is not AmountKind.QUOTED_ON_APPLICATION:
            raise ValueError("ADOR quotes the price on application; the transcript's tax-sale amount is not a price")
        for u in (self.list_url, self.instructions_url, self.purchase_url):
            if not u.startswith("https://"):
                raise ValueError(f"not https: {u!r}")
        if self.enabled and not (self.live_verified and self.parser_fixture_validated):
            raise ValueError("a source cannot be enabled before it is live-verified and its parser fixture-validated")


@dataclass
class TranscriptParse:
    records: list[OtcRecord] = field(default_factory=list)
    list_as_of: date | None = None
    headers_seen: int = 0
    record_lines: int = 0
    amount_lines: int = 0
    continuation_lines: int = 0
    orphan_lines: int = 0             # a non-header line before any record
    county_mismatch: int = 0          # CO. disagrees with the file's own county code (row rejected)
    parcel_dropped: int = 0           # a PARCEL ID that failed the plausibility gate (record kept without it)
    duplicate_identifier: int = 0     # the same C/S# twice in one file (second rejected)
    missing_amount_line: int = 0      # a record with no amount line (counted only; the amount is never read)

    @property
    def rejected(self) -> int:
        return self.county_mismatch + self.duplicate_identifier


@dataclass
class TranscriptOutcome:
    file_no: str
    county: str
    status: str                       # COMPLETE | EMPTY | INCOMPLETE | FAILED
    row_count: int = 0
    category: str | None = None
    reason: str | None = None
    empty_signal: str | None = None
    url: str | None = None


def _text(s: str | None) -> str | None:
    t = re.sub(r"\s+", " ", s or "").strip()
    return t or None


def parse_lines(cfg: TranscriptConfig, file_no: str, lines: list[str], *, retrieved_at: datetime,
                document_url: str | None = None, document_sha256: str | None = None) -> TranscriptParse:
    """The transcript's text lines (page after page) -> records. Never
    reads the NAME, CLASS, CODE or the tax-sale amount into a record."""
    county, division = cfg.files[file_no]
    out = TranscriptParse()
    seen: set[str] = set()
    current: dict | None = None

    def flush() -> None:
        nonlocal current
        if current is None:
            return
        rec = current
        current = None
        if not rec["amount_seen"]:
            out.missing_amount_line += 1
        if rec["co"] != file_no:
            out.county_mismatch += 1
            return
        if rec["cs"] in seen:
            out.duplicate_identifier += 1
            return
        seen.add(rec["cs"])
        parcel = rec["parcel"] if PARCEL_PLAUSIBLE.match(rec["parcel"] or "") else None
        if rec["parcel"] and parcel is None:
            out.parcel_dropped += 1
        out.records.append(OtcRecord(
            state=STATE, county=county, case_no=rec["cs"], source_id=cfg.source_id,
            source_authority=cfg.source_authority, inventory_type=cfg.inventory_type, retrieved_at=retrieved_at,
            parcel=parcel, legal_desc=_text(" ".join(rec["desc"])), amount=None, amount_kind=cfg.amount_kind,
            # The county's own transcript IS the list this row is on; the
            # land-sales page (which links all 68) is the purchase
            # instructions page (its price-quote text).
            list_url=transcript_url(file_no), document_url=document_url or transcript_url(file_no),
            purchase_url=cfg.purchase_url, purchase_url_kind=cfg.purchase_url_kind,
            source_status_text="currently in State inventory",
            document_sha256=document_sha256, record_source=cfg.record_source,
            provenance={
                "adapter": "alabama_transcripts",
                "file_no": file_no,
                "division": division,
                "identifier": "C/S# (certificate of sale number), as published",
                "year_sold_to_state": f"YR. column (two digits as published): {rec['yr']}",
                "amount": "not read: the transcript's 'Amt Bid at Tax Sale' is the amount due at the county tax sale, "
                          "not the State's price (quoted on application)",
                "status": "the land-sales page: 'tax delinquent properties currently in State inventory'",
                "name_column": "not read (the name the property was assessed in)",
            },
        ))

    for raw in lines:
        line = raw.rstrip()
        if not line.strip():
            continue
        m = HEADER_AGENCY.match(line)
        if m:
            out.headers_seen += 1
            try:
                out.list_as_of = out.list_as_of or datetime.strptime(m.group(1), "%m/%d/%Y").date()
            except ValueError:
                pass
            continue
        if line.strip() == HEADER_TITLE or HEADER_PAGE.match(line) or HEADER_COLUMNS.match(line):
            continue
        m = RECORD.match(line)
        if m:
            flush()
            out.record_lines += 1
            current = {"co": m.group("co"), "yr": m.group("yr"), "cs": m.group("cs"), "parcel": m.group("parcel"),
                       "desc": [m.group("desc") or ""], "amount_seen": False, "lines_after": 0}
            continue
        if current is None:
            out.orphan_lines += 1
            continue
        current["lines_after"] += 1
        if not current["amount_seen"]:
            # The amount line normally follows the record line (a page
            # header may sit between them); when a description line comes
            # first, a later line that starts with a decimal amount is it.
            a = (AMOUNT_LINE if current["lines_after"] == 1 else AMOUNT_LINE_STRICT).match(line.strip())
            if a:
                current["amount_seen"] = True
                out.amount_lines += 1           # the figure itself is never kept
                if a.group("rest"):
                    current["desc"].append(a.group("rest"))
                continue
        out.continuation_lines += 1
        current["desc"].append(line.strip())
    flush()
    for r in out.records:
        r.list_as_of = out.list_as_of
    return out


def parse_pdf(cfg: TranscriptConfig, file_no: str, data: bytes, *, retrieved_at: datetime,
              document_url: str | None = None) -> TranscriptParse:
    """A transcript PDF's bytes -> TranscriptParse (pdfplumber text lines)."""
    import pdfplumber  # noqa: PLC0415 - only the PDF sources need it
    lines: list[str] = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page in pdf.pages:
            lines.extend((page.extract_text() or "").splitlines())
    return parse_lines(cfg, file_no, lines, retrieved_at=retrieved_at, document_url=document_url,
                       document_sha256=hashlib.sha256(data).hexdigest())


def classify_outcome(cfg: TranscriptConfig, file_no: str, parse: TranscriptParse, *, url: str | None = None) -> TranscriptOutcome:
    """One transcript -> a status entry. Until `cfg.parser_fixture_validated`
    nothing is COMPLETE and nothing is EMPTY (the alabama.py rule): an
    unverified parser can never let the lifecycle close a row."""
    county = cfg.files[file_no][0]
    n = len(parse.records)
    base = dict(file_no=file_no, county=county, row_count=n, url=url)
    if parse.headers_seen == 0:
        return TranscriptOutcome(status="INCOMPLETE", category="PARSE_FORMAT_CHANGE",
                                 reason="the transcript page header was not found", **base)
    # A record without its amount line is counted but is not drift: the
    # amount is never read (and file 01 has records printed without one).
    drift = parse.rejected or parse.orphan_lines
    if not cfg.parser_fixture_validated:
        return TranscriptOutcome(status="INCOMPLETE", category="UNCONFIRMED_EMPTY" if n == 0 else "UNKNOWN",
                                 reason="parser not fixture-validated against the live source; completeness not asserted", **base)
    if drift:
        return TranscriptOutcome(status="INCOMPLETE", category="PARSE_FORMAT_CHANGE",
                                 reason="rows rejected or layout drift (county mismatch / duplicate / orphan line)", **base)
    if n:
        return TranscriptOutcome(status="COMPLETE", **base)
    return TranscriptOutcome(status="EMPTY", empty_signal="header_no_records", **base)


@dataclass(frozen=True)
class GateDecision:
    allowed: bool
    reason: str


def can_run(cfg: TranscriptConfig) -> GateDecision:
    """The state gate first: a registered-but-inactive state is refused
    whatever the configuration claims."""
    if not states.is_activated(STATE):
        return GateDecision(False, "state AL is not activated - blockers: " + ", ".join(states.activation_blockers(STATE)))
    if not cfg.enabled:
        return GateDecision(False, "source configuration is not enabled")
    if not (cfg.live_verified and cfg.parser_fixture_validated):
        return GateDecision(False, "source not live-verified / parser not fixture-validated")
    return GateDecision(True, "activated state, verified and enabled source")


@dataclass
class HarvestResult:
    records: list[OtcRecord] = field(default_factory=list)
    outcomes: list[TranscriptOutcome] = field(default_factory=list)
    requests: int = 0


def harvest(cfg: TranscriptConfig, fetch_bytes: Callable[[str], bytes], *, retrieved_at: datetime,
            file_nos: list[str] | None = None) -> HarvestResult:
    """The only path to the live source; refused before the first request
    unless can_run() allows it. One file failing never stops the others
    (class name only is recorded)."""
    decision = can_run(cfg)
    if not decision.allowed:
        raise RuntimeError(f"Alabama source {cfg.source_id} may not run: {decision.reason}")
    result = HarvestResult()
    for nn in (sorted(cfg.files) if file_nos is None else [n for n in sorted(cfg.files) if n in set(file_nos)]):
        url = transcript_url(nn)
        try:
            data = fetch_bytes(url)
            result.requests += 1
            parse = parse_pdf(cfg, nn, data, retrieved_at=retrieved_at, document_url=url)
        except Exception as exc:  # noqa: BLE001
            result.outcomes.append(TranscriptOutcome(file_no=nn, county=cfg.files[nn][0], status="FAILED",
                                                     category="UNKNOWN", reason=type(exc).__name__, url=url))
            continue
        result.records.extend(parse.records)
        result.outcomes.append(classify_outcome(cfg, nn, parse, url=url))
    return result


TRANSCRIPT_SOURCE = TranscriptConfig(
    source_id=SOURCE_ID,
    files=TRANSCRIPT_FILES,
    list_url=ADOR_LAND_SALES_URL,
    instructions_url=ADOR_INSTRUCTIONS_URL,
    purchase_url=ADOR_LAND_SALES_URL,
    purchase_url_kind=PurchaseUrlKind.PURCHASE_INSTRUCTIONS,
    source_terminology="Transcripts of Delinquent Property: 'tax delinquent properties currently in State inventory' "
                       "(weekly per-county PDF); C/S# certificate of sale number; price quote by electronic application",
    live_verified=False,
    parser_fixture_validated=False,
    enabled=False,
    notes="Read value-free 2026-10-25: the land-sales page (county -> file links, 68 files) and ONE transcript (file 01, "
          "Jefferson-Birmingham). The other 67 files are not read. Synthetic fixtures only.",
)
