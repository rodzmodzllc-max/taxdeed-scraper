#!/usr/bin/env python3
"""Purchase-path engine: the ONE place a row's "how does a buyer act on
this" is established from evidence (AVAILABLE commercial release,
2026-09-30; migration 023).

Ten path types, each of which must rest on evidence before it is stored:

  direct_property_url     a link the source published for THIS parcel
                          (an enabled, verified rule matched it on the
                          list row - scripts/laft_purchase_paths.py)
  county_instructions     the source's own purchase-instructions page
  application_page        the source's own application page (online)
  application_download    the source's application form as a document
  in_person               the source says the process is in person only
  phone_mail              the source says the process is by phone / mail
  quoted_amount           the source quotes the amount on request
  amount_plus_costs       the source says the amount is a stated amount
                          plus costs it names
  amount_on_application   the source states the amount only on an
                          application (the registry's QUOTED_ON_APPLICATION)
  none_published          the source states there is no purchase path

Every stored path carries: the type, the URL (URL types only), the
evidence (the wording / rule / registry row it rests on), the date the
evidence was observed, and its scope - "property" (this parcel's own link)
or "source" (the same for every parcel the source lists).

What it REFUSES, whatever rule or row proposed it (`rejection_reason`):
search engines, bare homepages, guessed URL patterns (placeholders,
templates), blocked-vendor hosts, a third-party host the evidence row did
not explicitly permit, the list page or the document itself, and anything
not https. A refusal is recorded as a reason, never as a path.

Evidence comes from three tables and nothing else:
  1. data/laft_purchase_link_rules.csv     property-scope links on list
                                            rows (an enabled rule; the
                                            harvester already applied it
                                            and left purchase_url_basis)
  2. data/purchase_path_evidence.csv        source-scope paths a human
                                            verified on the source's own
                                            page (ships EMPTY: no county
                                            page has been read from this
                                            repository)
  3. data/county_source_registry.csv        a production row's source-level
                                            purchase_url + kind, or its
                                            stated non-URL mode with the
                                            source's wording

When none of the three establishes a path the engine returns None: the
row's purchase_path_type stays NULL ("not yet evaluated / nothing
verified") - it is never written as none_published, because "the source
publishes no path" is itself a claim that needs the source's wording.
"""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
import sys  # noqa: E402
sys.path.insert(0, str(HERE))
import laft_purchase_paths as PP  # noqa: E402

EVIDENCE_PATH = REPO / "data" / "purchase_path_evidence.csv"

PATH_TYPES = ("direct_property_url", "county_instructions", "application_page", "application_download",
              "in_person", "phone_mail", "quoted_amount", "amount_plus_costs", "amount_on_application", "none_published")
URL_TYPES = frozenset({"direct_property_url", "county_instructions", "application_page", "application_download"})
NON_URL_TYPES = frozenset(PATH_TYPES) - URL_TYPES
SCOPES = ("property", "source")
# 017's purchase_url_kind -> path type (the URL types).
TYPE_FOR_KIND = {"online_purchase": "direct_property_url", "offer_form": "direct_property_url", "bid_form": "direct_property_url",
                 "purchase_instructions": "county_instructions", "application_form": "application_page"}
KIND_FOR_TYPE = {"direct_property_url": "online_purchase", "county_instructions": "purchase_instructions",
                 "application_page": "application_form", "application_download": "application_form"}
# The registry's non-URL modes (scripts/laft_purchase_paths.PURCHASE_PATH_MODES) -> path type.
TYPE_FOR_MODE = {"in_person_only": "in_person", "phone_mail": "phone_mail", "none": "none_published"}
# Path type -> the source-level mode the frontend / otc_provenance already understand.
MODE_FOR_TYPE = {"direct_property_url": "online_property", "county_instructions": "online_instructions",
                 "application_page": "application", "application_download": "application",
                 "in_person": "in_person_only", "phone_mail": "phone_mail", "none_published": "none",
                 "quoted_amount": "unknown", "amount_plus_costs": "unknown", "amount_on_application": "unknown"}
# The evidence record (Customer Value / Evidence Acquisition sprint,
# 2026-09-30). The first ten columns are the original table; the rest carry
# the provenance a customer sees: WHERE the evidence was read (evidence_url,
# the page or document a person actually opened), WHAT kind of source it is
# (evidence_type), the source's own title, the instructions it publishes,
# the review state, and what the evidence proves / does not prove. A row is
# applied only when enabled AND review_state is "verified" AND it names an
# https evidence_url - an unreviewed capture can never become a path.
EVIDENCE_COLUMNS_V1 = ["state", "source_id", "county", "path_type", "url", "evidence", "observed_on", "enabled",
                       "third_party_permitted", "notes"]
EVIDENCE_COLUMNS_V2 = EVIDENCE_COLUMNS_V1 + ["evidence_url", "evidence_type", "source_title", "instructions", "review_state",
                                             "proves", "does_not_prove"]
# v3 (Acquisition sprint, 2026-09-30): the ACTIONABLE part of the process -
# the published office, street address (in person), phone, e-mail, mailing
# address, the sequential steps the source describes (" | "-separated), a
# direct application / instructions document and the published payment
# method. Every field is quoted from the evidence page; a blank means the
# source did not publish it - never a guess, never a county homepage.
EVIDENCE_COLUMNS = EVIDENCE_COLUMNS_V2 + ["office", "address", "phone", "email", "mailing_address", "steps",
                                          "application_url", "payment"]
STEP_SEPARATOR = " | "
# The customer-facing acquisition mode: what a person actually DOES. Derived
# from the path type and the published channels (acquisition_mode()); the
# frontend's ACQUISITION_MODE_LABELS carries the same keys (a test pins them).
ACQUISITION_MODES = ("online", "application", "bid", "instructions", "email", "phone", "mail", "in_person", "contact",
                     "multi_step", "none")
ACQUISITION_MODE_LABELS = {
    "online": "Purchase or apply online", "application": "Download the county application",
    "bid": "Bid application required - purchase process not online",
    "instructions": "Follow the county's purchase-instructions page", "email": "E-mail the county",
    "phone": "Phone the county", "mail": "Mail a written request", "in_person": "Apply in person",
    "contact": "Contact the county for the current amount", "multi_step": "Multi-step county process",
    "none": "No purchase path (stated by the source)",
}
EVIDENCE_TYPES = ("county_page", "county_document", "property_page", "registry", "other")
REVIEW_STATES = ("verified", "needs_review", "restricted")
_TRUE = frozenset({"1", "true", "yes", "y"})
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# A URL that is a template, not an address: placeholders and unresolved
# markers the harvesters never produce and a human never verifies.
_GUESSED = re.compile(r"[{}<>\[\]]|%7B|%7D|\bXXXX+\b|\{\{|\$\{|=\s*$", re.I)


@dataclass(frozen=True)
class PurchasePath:
    path_type: str
    scope: str                      # property | source
    evidence: str
    observed_on: str                # YYYY-MM-DD
    url: str | None = None
    url_kind: str | None = None     # 017's purchase_url_kind (URL types only)
    # Customer-facing provenance (carried in otc_provenance, no schema change):
    evidence_url: str = ""          # the page / document the evidence was read from
    evidence_type: str = ""         # EVIDENCE_TYPES
    source_title: str = ""          # the source's own page / document title
    instructions: str = ""          # the process wording the source publishes, verbatim or closely quoted
    # v3: the actionable acquisition record (all published by the source, or blank).
    office: str = ""
    address: str = ""
    phone: str = ""
    email: str = ""
    mailing_address: str = ""
    steps: tuple = ()
    application_url: str = ""
    payment: str = ""

    @property
    def mode(self) -> str:
        return MODE_FOR_TYPE[self.path_type]

    @property
    def channels(self) -> tuple:
        """The published ways to act, in the order a customer would use them."""
        out = []
        offline_form = PP.is_document_url(self.url) or self.url_kind in PP.BID_KINDS
        if self.path_type in ("direct_property_url", "application_page") and self.url and not offline_form:
            out.append("online")
        if (self.path_type in URL_TYPES and self.url and offline_form and self.path_type != "county_instructions"
                or self.path_type == "application_download" and self.url or self.application_url):
            out.append("application")
        if self.path_type == "county_instructions" and self.url:
            out.append("instructions")
        if self.email:
            out.append("email")
        if self.phone:
            out.append("phone")
        if self.mailing_address:
            out.append("mail")
        if self.address or self.path_type == "in_person":
            out.append("in_person")
        return tuple(dict.fromkeys(out))

    @property
    def acquisition_mode(self) -> str:
        return acquisition_mode(self.path_type, self.channels, self.steps, url_kind=self.url_kind, url=self.url)

    def acquisition(self) -> dict:
        """The customer-facing acquisition record for otc_provenance.acquisition."""
        out = {"mode": self.acquisition_mode, "channels": list(self.channels)}
        for k in ("office", "address", "phone", "email", "mailing_address", "application_url", "payment"):
            v = getattr(self, k)
            if v:
                out[k] = v
        if self.steps:
            out["steps"] = list(self.steps)
        if self.evidence_url:
            out["evidence_url"] = self.evidence_url
        out["observed_on"] = self.observed_on
        return out

    def provenance(self) -> dict:
        """otc_provenance keys the frontend renders beside the path."""
        out = {}
        if self.evidence_url:
            out["purchase_evidence_url"] = self.evidence_url
        if self.evidence_type:
            out["purchase_evidence_type"] = self.evidence_type
        if self.source_title:
            out["purchase_evidence_title"] = self.source_title
        if self.instructions:
            out["purchase_instructions"] = self.instructions
        out["purchase_path_observed_on"] = self.observed_on
        out["acquisition"] = self.acquisition()
        return out


    def columns(self) -> dict:
        """The migration 023 columns (plus 017's URL columns for URL types)."""
        out = {"purchase_path_type": self.path_type, "purchase_path_scope": self.scope,
               "purchase_path_evidence": self.evidence, "purchase_path_observed_on": self.observed_on}
        if self.path_type in URL_TYPES:
            out["purchase_url"] = self.url
            out["purchase_url_kind"] = self.url_kind
        return out

def acquisition_mode(path_type: str, channels, steps, *, url_kind: str | None = None, url: str | None = None) -> str:
    """What the customer does first. Three or more published steps is a
    multi-step process; otherwise the path type decides, refined by the
    published channels (an e-mail address before a phone number before a
    mailing address). Never "contact" unless the source's own wording is a
    contact-for-the-amount process (the quoted_amount family).

    "online" only for a web page or checkout: a bid / offer form is "bid"
    and a downloadable form (an application PDF) is "application", whatever
    the path type - an offline form is never "Purchase or apply online"
    (evidence review 2026-10-03)."""
    if path_type == "none_published":
        return "none"
    if path_type == "in_person":
        return "in_person"          # the source says in person; its steps are how, not a different mode
    if len(tuple(steps or ())) >= 3:
        return "multi_step"
    chans = tuple(channels or ())
    if path_type in URL_TYPES and path_type != "county_instructions" and url_kind in PP.BID_KINDS:
        return "bid"
    if path_type in ("direct_property_url", "application_page") and PP.is_document_url(url):
        return "application"
    if path_type in ("direct_property_url", "application_page"):
        return "online"
    if path_type == "application_download":
        return "application"
    if path_type == "county_instructions":
        return "instructions"
    if path_type == "in_person":
        return "in_person"
    if path_type == "phone_mail":
        for c in ("email", "phone", "mail", "in_person"):
            if c in chans:
                return c
        return "phone"
    # quoted_amount / amount_plus_costs / amount_on_application: the source's
    # process IS "ask the county for the amount".
    return "contact"



@dataclass(frozen=True)
class EvidenceRow:
    state: str
    source_id: str
    county: str                     # a county name, or "*" for every county of the source
    path_type: str
    url: str
    evidence: str
    observed_on: str
    enabled: bool
    third_party_permitted: bool
    notes: str = ""
    evidence_url: str = ""
    evidence_type: str = ""
    source_title: str = ""
    instructions: str = ""
    review_state: str = ""
    proves: str = ""
    does_not_prove: str = ""
    office: str = ""
    address: str = ""
    phone: str = ""
    email: str = ""
    mailing_address: str = ""
    steps: tuple = ()
    application_url: str = ""
    payment: str = ""

    @property
    def applicable(self) -> bool:
        """Enabled, verified, and anchored to an https evidence page."""
        return self.enabled and self.review_state == "verified" and self.evidence_url.startswith("https://")


# ---------------------------------------------------------------------------
# Refusals
# ---------------------------------------------------------------------------
def _host(url: str) -> str:
    return (urlsplit(url).hostname or "").lower()


def same_site(url: str, canonical_url: str | None) -> bool:
    """The URL's host is the source's own host or a subdomain of its
    registrable part (clerk.example.gov ~ example.gov)."""
    if not canonical_url:
        return False
    a, b = _host(url), _host(canonical_url)
    if not a or not b:
        return False
    if a == b or a.endswith("." + b) or b.endswith("." + a):
        return True
    ra, rb = ".".join(a.split(".")[-2:]), ".".join(b.split(".")[-2:])
    return ra == rb


def rejection_reason(url: str, *, canonical_url: str | None, list_url: str | None, document_url: str | None,
                     third_party_permitted: bool = False) -> str | None:
    """Why a URL cannot be a purchase path, or None. Builds on
    laft_purchase_paths.untrusted_reason (https, list/document page,
    homepage, search engines, blocked vendors, search-results pages) and
    adds: guessed patterns and unverified third-party hosts."""
    base = PP.untrusted_reason(url, list_url=list_url, document_url=document_url)
    if base:
        return base
    if _GUESSED.search(url):
        return "a guessed URL pattern (placeholder or template), not a published address"
    if canonical_url and not same_site(url, canonical_url) and not third_party_permitted:
        return f"a third-party host ({_host(url)}) the evidence does not explicitly permit"
    return None


# ---------------------------------------------------------------------------
# Evidence table
# ---------------------------------------------------------------------------
def evidence_problems(row: EvidenceRow) -> list[str]:
    problems: list[str] = []
    if not re.match(r"^[A-Z]{2}$", row.state):
        problems.append(f"state {row.state!r}")
    if not row.source_id:
        problems.append("source_id required")
    if row.path_type not in PATH_TYPES:
        problems.append(f"path_type {row.path_type!r}")
    elif row.path_type in URL_TYPES:
        if not row.url:
            problems.append(f"{row.path_type} needs a url")
        elif row.path_type == "direct_property_url":
            problems.append("direct_property_url is property-scope: it comes from a list-row rule, never from this table")
    elif row.url:
        problems.append(f"{row.path_type} carries no url")
    if row.enabled and not (_DATE.match(row.observed_on) and row.evidence):
        problems.append("an enabled row needs observed_on (YYYY-MM-DD) and evidence")
    if row.evidence_type and row.evidence_type not in EVIDENCE_TYPES:
        problems.append(f"evidence_type {row.evidence_type!r}")
    if row.review_state and row.review_state not in REVIEW_STATES:
        problems.append(f"review_state {row.review_state!r}")
    if row.enabled:
        if row.review_state != "verified":
            problems.append("an enabled row must be review_state=verified")
        if not row.evidence_url.startswith("https://"):
            problems.append("an enabled row needs an https evidence_url (the page or document the evidence was read from)")
        if not row.evidence_type:
            problems.append("an enabled row needs an evidence_type")
        if row.evidence_url and (PP.untrusted_reason(row.evidence_url) or "").startswith("untrusted host"):
            problems.append("evidence_url is a search engine or a blocked vendor - not evidence")
    if row.application_url:
        if not row.application_url.startswith("https://"):
            problems.append("application_url must be https")
        elif (PP.untrusted_reason(row.application_url) or "").startswith("untrusted host"):
            problems.append("application_url is a search engine or a blocked vendor - not a county document")
        elif _GUESSED.search(row.application_url):
            problems.append("application_url looks like a template, not a published document")
    if row.email and "@" not in row.email:
        problems.append("email is not an address")
    return problems


def load_evidence(path: Path | str = EVIDENCE_PATH) -> list[EvidenceRow]:
    p = Path(path)
    if not p.is_file():
        return []
    out: list[EvidenceRow] = []
    with open(p, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames not in (EVIDENCE_COLUMNS, EVIDENCE_COLUMNS_V2, EVIDENCE_COLUMNS_V1):
            raise ValueError(f"{p.name}: columns must be {EVIDENCE_COLUMNS}, got {reader.fieldnames}")
        g = lambda r, k: (r.get(k) or "").strip()  # noqa: E731
        for i, r in enumerate(reader, 2):
            row = EvidenceRow(state=g(r, "state"), source_id=g(r, "source_id"), county=g(r, "county") or "*", path_type=g(r, "path_type"),
                              url=g(r, "url"), evidence=g(r, "evidence"), observed_on=g(r, "observed_on"),
                              enabled=g(r, "enabled").lower() in _TRUE, third_party_permitted=g(r, "third_party_permitted").lower() in _TRUE,
                              notes=g(r, "notes"), evidence_url=g(r, "evidence_url"), evidence_type=g(r, "evidence_type"),
                              source_title=g(r, "source_title"), instructions=g(r, "instructions"), review_state=g(r, "review_state"),
                              proves=g(r, "proves"), does_not_prove=g(r, "does_not_prove"),
                              office=g(r, "office"), address=g(r, "address"), phone=g(r, "phone"), email=g(r, "email"),
                              mailing_address=g(r, "mailing_address"),
                              steps=tuple(x.strip() for x in g(r, "steps").split("|") if x.strip()),
                              application_url=g(r, "application_url"), payment=g(r, "payment"))
            problems = evidence_problems(row)
            if problems:
                raise ValueError(f"{p.name} line {i}: " + "; ".join(problems))
            out.append(row)
    return out


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------
def _registry_fields(registry_row) -> dict:
    """The registry fields the engine reads, from a CountySourceRow or a dict."""
    if registry_row is None:
        return {}
    get = registry_row.get if isinstance(registry_row, dict) else (lambda k, d="": getattr(registry_row, k, d))
    return {k: (get(k, "") or "") for k in ("canonical_url", "document_url", "purchase_url", "purchase_url_kind",
                                             "purchase_path_mode", "purchase_path_evidence", "last_checked",
                                             "verification_status", "evidence_ref", "amount_kind")}


def type_and_scope(kind: str, url: str | None) -> tuple[str, str]:
    """The typed path for a published URL of this purchase_url_kind. A
    downloadable form (an application or bid-form PDF the buyer returns to
    the county) is an application_download at SOURCE scope - never a
    direct_property_url, never a per-parcel link, even when the adapter puts
    the county's one form on every row (Horry SC's FLC bid form, evidence
    review 2026-10-03). Otherwise TYPE_FOR_KIND decides, and only a
    property-action kind is property scope."""
    if PP.is_document_url(url):
        return "application_download", "source"
    return TYPE_FOR_KIND[kind], ("property" if kind in PP.PROPERTY_KINDS else "source")


def from_row_link(row: dict, *, canonical_url: str | None, list_url: str | None, document_url: str | None,
                  harvest_date: str) -> tuple[PurchasePath | None, str | None]:
    """A property-scope path from the harvester row's own purchase_url +
    kind (set by an enabled rule - purchase_url_basis names it)."""
    url, kind, basis = row.get("purchase_url"), row.get("purchase_url_kind"), str(row.get("purchase_url_basis") or "")
    if not url or kind not in TYPE_FOR_KIND:
        return None, None
    reason = rejection_reason(str(url), canonical_url=canonical_url, list_url=list_url, document_url=document_url)
    if reason:
        return None, f"row link refused: {reason}"
    m = re.search(r"verified (\d{4}-\d{2}-\d{2})", basis)
    observed = m.group(1) if m else harvest_date
    ptype, scope = type_and_scope(kind, str(url))
    evidence = basis or f"{kind} link published by the source on the list row"
    return PurchasePath(ptype, scope, evidence, observed, url=str(url), url_kind=kind), None


def from_evidence_table(rows: list[EvidenceRow], *, state: str, source_id: str, county: str, canonical_url: str | None,
                        list_url: str | None, document_url: str | None) -> tuple[PurchasePath | None, str | None]:
    # A county-specific row beats the source's wildcard row.
    matching = [e for e in rows if e.applicable and e.state == state and e.source_id == source_id and e.county in ("*", county)]
    matching.sort(key=lambda e: 0 if e.county == county else 1)
    for e in matching:
        extra = dict(evidence_url=e.evidence_url, evidence_type=e.evidence_type, source_title=e.source_title, instructions=e.instructions,
                     office=e.office, address=e.address, phone=e.phone, email=e.email, mailing_address=e.mailing_address,
                     steps=e.steps, application_url=e.application_url, payment=e.payment)
        text = f"{e.evidence} (data/purchase_path_evidence.csv, observed {e.observed_on})"
        if e.path_type in URL_TYPES:
            reason = rejection_reason(e.url, canonical_url=canonical_url, list_url=list_url, document_url=document_url,
                                      third_party_permitted=e.third_party_permitted)
            if reason:
                return None, f"evidence row refused: {reason}"
            return PurchasePath(e.path_type, "source", text, e.observed_on, url=e.url, url_kind=KIND_FOR_TYPE[e.path_type], **extra), None
        return PurchasePath(e.path_type, "source", text, e.observed_on, **extra), None
    return None, None


def from_registry(reg: dict, *, list_url: str | None, document_url: str | None, harvest_date: str) -> tuple[PurchasePath | None, str | None]:
    if not reg or reg.get("verification_status") != "PRODUCTION_VERIFIED":
        return None, None
    observed = reg.get("last_checked") if _DATE.match(reg.get("last_checked") or "") else harvest_date
    url, kind = reg.get("purchase_url"), reg.get("purchase_url_kind")
    if url and kind in TYPE_FOR_KIND:
        reason = rejection_reason(url, canonical_url=reg.get("canonical_url"), list_url=list_url, document_url=document_url)
        if reason:
            return None, f"registry purchase_url refused: {reason}"
        ptype, _ = type_and_scope(kind, url)
        if ptype == "direct_property_url":
            return None, "registry purchase_url refused: a source-level row cannot establish a per-property link"
        ev = f"source-level {kind} page verified for this source (data/county_source_registry.csv, last_checked {observed}"
        ev += f"; {reg['evidence_ref']})" if reg.get("evidence_ref") else ")"
        return PurchasePath(ptype, "source", ev, observed, url=url, url_kind=kind), None
    mode, wording = reg.get("purchase_path_mode"), reg.get("purchase_path_evidence")
    if mode in TYPE_FOR_MODE and wording:
        return PurchasePath(TYPE_FOR_MODE[mode], "source", f"{mode.replace('_', ' ')} process published by the source: {wording} "
                            f"(data/county_source_registry.csv, last_checked {observed})", observed), None
    if reg.get("amount_kind") == "QUOTED_ON_APPLICATION":
        return PurchasePath("amount_on_application", "source", "the source states the amount only on application "
                            f"(registry amount_kind QUOTED_ON_APPLICATION, last_checked {observed})", observed), None
    return None, None


def resolve(row: dict, *, state: str, source_id: str, county: str, registry_row=None, evidence: list[EvidenceRow] | None = None,
            list_url: str | None = None, document_url: str | None = None, harvest_date: str | None = None) -> tuple[PurchasePath | None, list[str]]:
    """(path or None, refusal reasons). Precedence: the row's own verified
    link (property scope) > the evidence table (source scope) > the
    registry row (source scope). None = nothing verified: the columns stay
    NULL and the existing otc_provenance wording ("none invented") stands."""
    harvest_date = harvest_date or date.today().isoformat()
    reg = _registry_fields(registry_row)
    canonical = reg.get("canonical_url") or None
    reasons: list[str] = []
    for i, fn in enumerate((lambda: from_row_link(row, canonical_url=canonical, list_url=list_url, document_url=document_url, harvest_date=harvest_date),
                            lambda: from_evidence_table(evidence or [], state=state, source_id=source_id, county=county, canonical_url=canonical,
                                                        list_url=list_url, document_url=document_url),
                            lambda: from_registry(reg, list_url=list_url, document_url=document_url, harvest_date=harvest_date))):
        path, reason = fn()
        if path:
            if i == 0:
                # A row's own verified link (e.g. a per-parcel bid form) keeps its
                # property scope and URL, and takes the source's VERIFIED process
                # record (steps, office, contacts) from the evidence table - so the
                # customer sees how to use the link, not just the link.
                src, _ = from_evidence_table(evidence or [], state=state, source_id=source_id, county=county, canonical_url=canonical,
                                             list_url=list_url, document_url=document_url)
                if src is not None:
                    from dataclasses import replace  # noqa: PLC0415
                    path = replace(path, **{k: getattr(src, k) for k in ("evidence_url", "evidence_type", "source_title", "instructions",
                                                                         "office", "address", "phone", "email", "mailing_address",
                                                                         "steps", "application_url", "payment")})
            return path, reasons
        if reason:
            reasons.append(reason)
    return None, reasons


def complete_record(acq: dict, row: dict | None = None) -> bool:
    """A usable verified acquisition record: steps AND a published channel
    (phone, e-mail, in-person address, mailing address, application
    document or an online URL)."""
    if not isinstance(acq, dict) or not acq.get("steps"):
        return False
    return any(acq.get(k) for k in ("phone", "email", "address", "mailing_address", "application_url")) or bool((row or {}).get("purchase_url"))


def measure(rows: list[dict]) -> dict:
    """Coverage counts for the ACQUISITION workflow (the product metric,
    Acquisition sprint 2026-09-30). Per row: a verified source listing /
    document (otc_provenance.list_url / document_url), a property-to-source
    match (otc_provenance.source_match), a verified acquisition path (a
    stored path type that is not none_published), the acquisition mode, a
    direct source document, a source publication date, a last-verified
    date - and the rows where the process remains unverified. The old
    purchase-URL counts stay for continuity but are no longer the headline."""
    c = {"rows": 0, "evaluated": 0, "not_evaluated": 0, "with_url": 0, "by_type": {}, "by_scope": {},
         "with_source_listing": 0, "with_source_match": 0, "with_acquisition_path": 0, "acquisition_unverified": 0,
         "by_mode": {}, "with_direct_document": 0, "with_source_date": 0, "with_last_verified": 0,
         "with_contact": 0, "with_steps": 0, "with_complete_record": 0, "with_in_person": 0, "with_application_document": 0}
    for r in rows:
        c["rows"] += 1
        prov = r.get("otc_provenance") if isinstance(r.get("otc_provenance"), dict) else {}
        if prov.get("list_url") or prov.get("document_url") or r.get("list_url") or r.get("document_url"):
            c["with_source_listing"] += 1
        if isinstance(prov.get("source_match"), dict) and prov["source_match"].get("value"):
            c["with_source_match"] += 1
        if prov.get("document_url") or r.get("document_url"):
            c["with_direct_document"] += 1
        if r.get("list_as_of") or r.get("source_published_at"):
            c["with_source_date"] += 1
        if r.get("last_seen_at"):
            c["with_last_verified"] += 1
        t = r.get("purchase_path_type")
        if not t:
            c["not_evaluated"] += 1
            c["acquisition_unverified"] += 1
            continue
        c["evaluated"] += 1
        c["by_type"][t] = c["by_type"].get(t, 0) + 1
        s = r.get("purchase_path_scope") or "?"
        c["by_scope"][s] = c["by_scope"].get(s, 0) + 1
        if r.get("purchase_url"):
            c["with_url"] += 1
        if t == "none_published":
            c["acquisition_unverified"] += 1
            continue
        c["with_acquisition_path"] += 1
        acq = prov.get("acquisition") if isinstance(prov.get("acquisition"), dict) else {}
        mode = acq.get("mode") or acquisition_mode(t, (), (), url_kind=r.get("purchase_url_kind"), url=r.get("purchase_url"))
        c["by_mode"][mode] = c["by_mode"].get(mode, 0) + 1
        if any(acq.get(k) for k in ("phone", "email", "address", "mailing_address", "office")):
            c["with_contact"] += 1
        if acq.get("steps"):
            c["with_steps"] += 1
        if acq.get("address"):
            c["with_in_person"] += 1
        if acq.get("application_url"):
            c["with_application_document"] += 1
        # A COMPLETE actionable record (the commercial metric; a typed mode
        # alone does not count): the acquisition record exists, carries the
        # published steps, and names at least one way to act on them.
        if complete_record(acq, r):
            c["with_complete_record"] += 1
    c["pct_with_complete_record"] = round(100.0 * c["with_complete_record"] / c["rows"], 1) if c["rows"] else 0.0
    c["pct_with_acquisition_path"] = round(100.0 * c["with_acquisition_path"] / c["rows"], 1) if c["rows"] else 0.0
    c["pct_with_source_listing"] = round(100.0 * c["with_source_listing"] / c["rows"], 1) if c["rows"] else 0.0
    return c


# ---------------------------------------------------------------------------
# Acquisition-path coverage (Acquisition-path sprint, 2026-10-01)
# ---------------------------------------------------------------------------
# The acquisition path is ENRICHMENT, never a publication decision: an
# AVAILABLE row the source establishes as available is published under the
# existing source rules (publication_status) whether or not its acquisition
# process has been captured. These are the independently measured parts of
# the acquisition record - what is still missing for a row, never a reason
# to withhold it. app.js acquisitionGaps() carries the same keys (a test pins
# them equal) and renders each missing part as "Not yet verified".
ACQUISITION_GAP_REASONS = {
    "no_source_listing": "no source listing or document link on file",
    "no_source_match": "no deterministic match to the source listing on file",
    "no_acquisition_path": "acquisition path not yet verified",
    "no_evidence_page": "no official acquisition evidence page on file",
    "no_verified_date": "acquisition process last-verified date not on file",
}


def acquisition_gaps(row: dict) -> list[str]:
    """The ACQUISITION_GAP_REASONS keys an AVAILABLE (source = laft) row is
    missing; [] = a complete acquisition record. Never used to withhold a row."""
    if row.get("source") != "laft":
        return []
    prov = row.get("otc_provenance") if isinstance(row.get("otc_provenance"), dict) else {}
    out = []
    if not (row.get("list_url") or row.get("document_url") or prov.get("list_url") or prov.get("document_url")):
        out.append("no_source_listing")
    m = prov.get("source_match")
    if not (isinstance(m, dict) and m.get("value")):
        out.append("no_source_match")
    t = row.get("purchase_path_type")
    if not t or t == "none_published":
        out.append("no_acquisition_path")
    if not (prov.get("purchase_evidence_url") or (t in URL_TYPES and row.get("purchase_url"))):
        out.append("no_evidence_page")
    if not (row.get("purchase_path_observed_on") or prov.get("purchase_path_observed_on")):
        out.append("no_verified_date")
    return out


def acquisition_state(row: dict) -> str:
    """complete | partial | source_only | not_verified - the customer page's
    three cases plus the row with neither a path nor a source link."""
    prov = row.get("otc_provenance") if isinstance(row.get("otc_provenance"), dict) else {}
    t = row.get("purchase_path_type")
    if t and t != "none_published":
        return "complete" if complete_record(prov.get("acquisition") or {}, row) else "partial"
    if row.get("list_url") or row.get("document_url") or prov.get("list_url") or prov.get("document_url"):
        return "source_only"
    return "not_verified"
