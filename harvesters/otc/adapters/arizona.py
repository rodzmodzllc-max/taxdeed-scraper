"""Arizona - the Maricopa County Treasurer's "Current State CP Listing"
(LIENS & CERTIFICATES source adapter, 2026-09-30).

THE PRODUCT. A CP (certificate of purchase) is the tax LIEN sold at
Arizona's February tax-lien sale. Liens nobody bought are struck to the
State ("State CP"); the Treasurer publishes the current list of those and
sells them by ASSIGNMENT (a buyer applies with an Assignments Purchase
Form). This is the lien product - never the land - so every record here
is a LIENS & CERTIFICATES record (`record_source = "certificate"`), the
first such source outside Florida, and Arizona participates in that one
ledger only until an auction or available source is verified.

Evidence grade: SEARCH INDEX (`MARICOPA_EVIDENCE`, 2026-09-30) - page
titles, the CSV download's URL (two hosts), the Assignments Purchase Form
and the assignment-by-mail rule. Nothing fetched from this repository
(treasurer.maricopa.gov is egress-blocked). The CSV's columns and value
formats are UNVERIFIED; fixtures are SYNTHETIC; `parser_fixture_validated`
stays unmet. The parser therefore reads only what its candidate labels
match and reports the rest by label.

  Established from the indexed text:
    * "Current State CP Listing Downloads" - download as CSV or PDF, plus
      an "Assignments Purchase Form"                    -> the list + the application path
    * CSV at .../TaxAssignment/State_CP/state-cp-data.csv (soa. and ftp. hosts)
    * "beginning March 2, 2026, buyers are able to purchase 2024
      assignments via mail; in-person assignment purchasing is limited"
                                                        -> assignment is the purchase process
  NOT established: the CSV's header names and value formats (parcel
  number shape, CP number shape, amount, rate, tax year), the refresh
  cadence, terms of use.
"""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from ...governance import states
from ...governance.states import PublishingUnit
from ..model import AmountKind, OtcRecord, PurchaseUrlKind, SourceAuthority
from . import common
from .common import CountyOutcome, Evidence, GateDecision, HarvestResult

__all__ = ["MARICOPA_EVIDENCE", "MARICOPA_SOURCE", "ArizonaCpSourceConfig", "can_run", "classify_outcome", "harvest",
           "parse_csv", "requirement_evidence"]

STATE = "AZ"
STATUS_FILE_NAME = "harvest_arizona_status.json"
HARVEST_FILE_NAME = "harvest_arizona.json"
EVIDENCE_DATE = "2026-09-30"
MCT_HOST = "treasurer.maricopa.gov"
MCT_STATE_CP_PAGE = "https://treasurer.maricopa.gov/TaxAssignment/statecpdata"
MCT_STATE_CP_CSV = "https://soa.treasurer.maricopa.gov/TaxAssignment/State_CP/state-cp-data.csv"
MCT_STATE_CP_CSV_FTP = "https://ftp.treasurer.maricopa.gov/TaxAssignment/State_CP/state-cp-data.csv"
MCT_TAX_ASSIGNMENT_PAGE = "https://treasurer.maricopa.gov/TaxAssignment/index"
MCT_TAX_LIEN_PAGE = "https://treasurer.maricopa.gov/TaxLien"
COUNTY = "Maricopa"

MARICOPA_EVIDENCE: tuple[Evidence, ...] = (
    Evidence("state_cp_page", "SEARCH_INDEX", EVIDENCE_DATE, MCT_STATE_CP_PAGE,
             "Title 'Current State CP Listing Downloads'. Snippet: 'Current State CP Listing that can be downloaded as CSV or PDF, along "
             "with an Assignments Purchase Form'."),
    Evidence("csv", "SEARCH_INDEX", EVIDENCE_DATE, MCT_STATE_CP_CSV, "Indexed CSV download (also mirrored at ftp.treasurer.maricopa.gov)."),
    Evidence("tax_assignment", "SEARCH_INDEX", EVIDENCE_DATE, MCT_TAX_ASSIGNMENT_PAGE,
             "Title 'Maricopa County - Treasurer's Office' (Tax Assignment). Snippet: 'beginning March 2, 2026, buyers are able to "
             "purchase 2024 assignments via mail, and in-person assignment purchasing is limited to 20 minutes on the lobby PC'."),
    Evidence("tax_lien", "SEARCH_INDEX", EVIDENCE_DATE, MCT_TAX_LIEN_PAGE,
             "Title 'Tax Lien Services'. Snippet: the Treasurer 'oversees ... unpaid taxes, tax liens, and the sale of certificates of "
             "purchase at public auctions'."),
    Evidence("audit_note", "AUDIT_NOTE", "2026-09-29", "",
             "50-state audit group 1: 'AZ=A (state-held CP liens by assignment - Maricopa CSV; BOS tax-deeded land OTC; 15 counties, "
             "6 lien + 9 deed sources)'. Only the Maricopa State CP list is implemented; the tax-deeded-land (AVAILABLE) sources are not."),
)


def requirement_evidence() -> dict[str, str]:
    return {
        "source_of_record_identified": "search index names the Treasurer's State CP listing page and its CSV; not read directly",
        "live_source_verified": "nothing fetched from this repository (egress blocked)",
        "publishing_unit_coverage_established": "one county (Maricopa); the other 14 counties' lists not located",
        "identifier_format_established": "no parcel or CP number observed; nothing is normalized",
        "inventory_semantics_established": "'State CP' = liens struck to the State, sold by assignment (snippets); the list's own status wording not read",
        "purchase_path_established": "an Assignments Purchase Form and assignment by mail are named in snippets; no per-lien link observed",
        "amount_semantics_established": "no amount column read; the CP amount / rate columns are candidates only",
        "parser_fixture_validated": "parser exercised on SYNTHETIC fixtures only",
        "governance_approved": "terms of use not reviewed; registry governance_status TERMS_NOT_VERIFIED",
        "production_registry_authorized": "no decision taken",
    }


@dataclass(frozen=True)
class ArizonaCpSourceConfig:
    source_id: str
    county: str
    list_url: str
    document_url: str
    application_url: str | None = None
    application_url_kind: PurchaseUrlKind | None = None
    # Candidate column labels (matched after normalization). Only `parcel`
    # is required; the rest are read when the CSV carries them.
    parcel_labels: tuple[str, ...] = ("Parcel", "Parcel Number", "Parcel No", "APN")
    cp_labels: tuple[str, ...] = ("CP", "CP Number", "CP No", "Certificate", "Certificate Number", "Cert No")
    tax_year_labels: tuple[str, ...] = ("Tax Year", "Year")
    amount_labels: tuple[str, ...] = ("Amount", "CP Amount", "Total", "Purchase Amount", "Total Due")
    rate_labels: tuple[str, ...] = ("Rate", "Interest Rate", "Interest")
    address_labels: tuple[str, ...] = ("Address", "Property Address", "Situs")
    amount_kind: AmountKind = AmountKind.PUBLISHED_AMOUNT_KIND_UNSPECIFIED   # what the amount column IS - not read yet
    source_terminology: str = ""
    live_verified: bool = False
    identifier_format_established: bool = False
    parser_fixture_validated: bool = False
    enabled: bool = False
    evidence: str = ""

    def __post_init__(self) -> None:
        for name in ("list_url", "document_url", "application_url"):
            value = getattr(self, name)
            if value is not None and not value.startswith("https://"):
                raise ValueError(f"{name} must be https")
        if (self.application_url is None) != (self.application_url_kind is None):
            raise ValueError("application_url and application_url_kind go together")
        if self.application_url_kind is not None and self.application_url_kind not in (
                PurchaseUrlKind.APPLICATION_FORM, PurchaseUrlKind.PURCHASE_INSTRUCTIONS):
            raise ValueError("an application page is application_form or purchase_instructions - never a property purchase kind")
        if self.application_url in (self.list_url, self.document_url):
            raise ValueError("the list page / document is not an application page")
        if self.amount_kind in (AmountKind.QUOTED_ON_APPLICATION, AmountKind.NOT_PUBLISHED):
            raise ValueError("a certificate list's amount column, when read, is a published figure")
        if self.enabled and not (self.live_verified and self.identifier_format_established and self.parser_fixture_validated):
            raise ValueError("a source cannot be enabled before it is live-verified, its identifier format established "
                             "and its parser fixture validated")


def can_run(cfg: ArizonaCpSourceConfig) -> GateDecision:
    return common.can_run(STATE, enabled=cfg.enabled, live_verified=cfg.live_verified,
                          identifier_format_established=cfg.identifier_format_established,
                          parser_fixture_validated=cfg.parser_fixture_validated, list_url=cfg.list_url)


def _norm(label: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", (label or "").strip().lower())).strip()


_HAS_DIGIT = re.compile(r"\d")


def _text(value) -> str | None:
    t = re.sub(r"\s+", " ", str(value or "")).strip()
    return t or None


def _num(value) -> float | None:
    if value is None:
        return None
    cleaned = re.sub(r"[^0-9.]", "", str(value))
    if not re.match(r"^\d+(\.\d+)?$", cleaned):
        return None
    return float(cleaned)


def parse_csv(cfg: ArizonaCpSourceConfig, text: str, *, retrieved_at: datetime) -> tuple[list[OtcRecord], dict]:
    """The State CP CSV -> (certificate records, outcome). The parcel column
    is the identity (as FL's certificate rows use the account number); the
    CP number, tax year, amount, rate and address are read when their
    candidate labels match. Every record is `record_source = "certificate"`
    with no inventory type. A CSV without a parcel column reads nothing
    (PARSE_FORMAT_CHANGE)."""
    reader = csv.reader(io.StringIO(text))
    rows = [r for r in reader if any(c.strip() for c in r)]
    outcome = {"header_table_found": False, "data_rows": 0, "empty_marker": False, "rejected_identifier": 0,
               "unmapped_columns": [], "matched": {}}
    if not rows:
        return [], outcome
    header = [_norm(c) for c in rows[0]]
    idx = {h: i for i, h in enumerate(header)}

    def col(labels):
        for lb in labels:
            if _norm(lb) in idx:
                return idx[_norm(lb)]
        return None
    slots = {"parcel": col(cfg.parcel_labels), "cp": col(cfg.cp_labels), "tax_year": col(cfg.tax_year_labels),
             "amount": col(cfg.amount_labels), "rate": col(cfg.rate_labels), "address": col(cfg.address_labels)}
    outcome["matched"] = {k: rows[0][v] for k, v in slots.items() if v is not None}
    mapped = {v for v in slots.values() if v is not None}
    outcome["unmapped_columns"] = sorted(rows[0][i] for i in range(len(rows[0])) if i not in mapped)
    if slots["parcel"] is None:
        return [], outcome
    outcome["header_table_found"] = True
    body = rows[1:]
    outcome["data_rows"] = len(body)

    def cell(r, k):
        i = slots[k]
        return r[i] if i is not None and i < len(r) else None

    out: list[OtcRecord] = []
    for r in body:
        parcel = _text(cell(r, "parcel"))
        if not parcel or not _HAS_DIGIT.search(parcel) or len(parcel) > 40:
            outcome["rejected_identifier"] += 1
            continue
        amount = _num(cell(r, "amount")) if slots["amount"] is not None else None
        rate = _num(cell(r, "rate")) if slots["rate"] is not None else None
        cp = _text(cell(r, "cp")) if slots["cp"] is not None else None
        prov = {
            "adapter": "arizona",
            "ledger": "LIENS_CERTIFICATES",
            "publishing_unit": PublishingUnit.COUNTY.value,
            "publishing_unit_name": "Maricopa County Treasurer",
            "source_terminology": cfg.source_terminology or None,
            "identifier": "parcel number as published (the certificate's parcel, the record identity); no normalization",
            "certificate_no": (f"column {outcome['matched']['cp']!r} as published" if cp else "no CP number column / value"),
            "amount": (f"column {outcome['matched']['amount']!r} = {cfg.amount_kind.value}; what the figure IS has not been read from the source"
                       if amount is not None else "no amount published on the row"),
            "interest_rate": (f"column {outcome['matched']['rate']!r} as published" if rate is not None else "not published on the row"),
            "purchase_url": (f"Treasurer's tax-assignment page ({cfg.application_url_kind.value}); assignment by mail with the "
                             "Assignments Purchase Form" if cfg.application_url else "no online path published"),
            "product": "a certificate of purchase (tax lien) held by the State and sold by assignment - never the land",
            "list_as_of": "not stated per row",
        }
        out.append(OtcRecord(
            state=STATE, county=cfg.county, case_no=parcel, source_id=cfg.source_id, source_authority=SourceAuthority.GOVERNMENT_DIRECT,
            inventory_type=None, retrieved_at=retrieved_at, parcel=parcel, address=_text(cell(r, "address")) if slots["address"] is not None else None,
            amount=amount, amount_kind=cfg.amount_kind if amount is not None else AmountKind.NOT_PUBLISHED,
            list_url=cfg.list_url, document_url=cfg.document_url,
            purchase_url=cfg.application_url, purchase_url_kind=cfg.application_url_kind,
            tax_year=_text(cell(r, "tax_year")) if slots["tax_year"] is not None else None,
            record_source="certificate", certificate_no=cp, interest_rate=rate, provenance=prov,
        ))
    return out, outcome


def classify_outcome(cfg: ArizonaCpSourceConfig, records: list[OtcRecord], outcome: dict, *, url: str | None = None) -> CountyOutcome:
    if outcome.get("data_rows", 0) == 0 and not outcome.get("header_table_found") and outcome.get("unmapped_columns"):
        return CountyOutcome(county=cfg.county, status="INCOMPLETE", category="PARSE_FORMAT_CHANGE", url=url, report=outcome,
                             reason="no parcel column among: " + ", ".join(outcome["unmapped_columns"][:8]))
    return common.classify(parser_fixture_validated=cfg.parser_fixture_validated, county=cfg.county, records=records,
                           header_found=bool(outcome.get("header_table_found")), data_rows=int(outcome.get("data_rows") or 0),
                           empty_marker=False, url=url, report=outcome, unmapped=tuple(outcome.get("unmapped_columns") or ()))


def harvest(cfg: ArizonaCpSourceConfig, fetch_text: Callable[[str], str], *, retrieved_at: datetime) -> HarvestResult:
    """One CSV download, REFUSED unless can_run() allows it. Transport injected."""
    decision = can_run(cfg)
    if not decision.allowed:
        raise RuntimeError(f"Arizona source {cfg.source_id} may not run: {decision.reason}")
    result = HarvestResult(units_offered=1)
    try:
        text = fetch_text(cfg.document_url)
        result.requests += 1
        recs, outcome = parse_csv(cfg, text, retrieved_at=retrieved_at)
    except Exception as exc:  # noqa: BLE001
        result.outcomes.append(CountyOutcome(county=cfg.county, status="FAILED", category=common.error_category(exc),
                                             reason=type(exc).__name__, url=cfg.document_url))
        return result
    result.records.extend(recs)
    result.outcomes.append(classify_outcome(cfg, recs, outcome, url=cfg.document_url))
    return result


MARICOPA_SOURCE = ArizonaCpSourceConfig(
    source_id="az_maricopa_state_cp",
    county=COUNTY,
    list_url=MCT_STATE_CP_PAGE,
    document_url=MCT_STATE_CP_CSV,
    application_url=MCT_TAX_ASSIGNMENT_PAGE,
    application_url_kind=PurchaseUrlKind.PURCHASE_INSTRUCTIONS,
    source_terminology="State CP; certificate of purchase; assignment; Assignments Purchase Form; Current State CP Listing",
    evidence="harvesters/otc/adapters/arizona.py MARICOPA_EVIDENCE (search index, 2026-09-30); docs/three-ledgers.md",
)
