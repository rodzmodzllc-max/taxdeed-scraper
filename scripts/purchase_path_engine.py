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
EVIDENCE_COLUMNS = ["state", "source_id", "county", "path_type", "url", "evidence", "observed_on", "enabled",
                    "third_party_permitted", "notes"]
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

    @property
    def mode(self) -> str:
        return MODE_FOR_TYPE[self.path_type]

    def columns(self) -> dict:
        """The migration 023 columns (plus 017's URL columns for URL types)."""
        out = {"purchase_path_type": self.path_type, "purchase_path_scope": self.scope,
               "purchase_path_evidence": self.evidence, "purchase_path_observed_on": self.observed_on}
        if self.path_type in URL_TYPES:
            out["purchase_url"] = self.url
            out["purchase_url_kind"] = self.url_kind
        return out


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
    return problems


def load_evidence(path: Path | str = EVIDENCE_PATH) -> list[EvidenceRow]:
    p = Path(path)
    if not p.is_file():
        return []
    out: list[EvidenceRow] = []
    with open(p, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames != EVIDENCE_COLUMNS:
            raise ValueError(f"{p.name}: columns must be {EVIDENCE_COLUMNS}, got {reader.fieldnames}")
        for i, r in enumerate(reader, 2):
            row = EvidenceRow(state=(r["state"] or "").strip(), source_id=(r["source_id"] or "").strip(),
                              county=(r["county"] or "").strip() or "*", path_type=(r["path_type"] or "").strip(),
                              url=(r["url"] or "").strip(), evidence=(r["evidence"] or "").strip(),
                              observed_on=(r["observed_on"] or "").strip(),
                              enabled=(r["enabled"] or "").strip().lower() in _TRUE,
                              third_party_permitted=(r["third_party_permitted"] or "").strip().lower() in _TRUE,
                              notes=(r["notes"] or "").strip())
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
    ptype = TYPE_FOR_KIND[kind]
    scope = "property" if kind in PP.PROPERTY_KINDS else "source"
    evidence = basis or f"{kind} link published by the source on the list row"
    return PurchasePath(ptype, scope, evidence, observed, url=str(url), url_kind=kind), None


def from_evidence_table(rows: list[EvidenceRow], *, state: str, source_id: str, county: str, canonical_url: str | None,
                        list_url: str | None, document_url: str | None) -> tuple[PurchasePath | None, str | None]:
    for e in rows:
        if not e.enabled or e.state != state or e.source_id != source_id or e.county not in ("*", county):
            continue
        if e.path_type in URL_TYPES:
            reason = rejection_reason(e.url, canonical_url=canonical_url, list_url=list_url, document_url=document_url,
                                      third_party_permitted=e.third_party_permitted)
            if reason:
                return None, f"evidence row refused: {reason}"
            return PurchasePath(e.path_type, "source", f"{e.evidence} (data/purchase_path_evidence.csv, observed {e.observed_on})",
                                e.observed_on, url=e.url, url_kind=KIND_FOR_TYPE[e.path_type]), None
        return PurchasePath(e.path_type, "source", f"{e.evidence} (data/purchase_path_evidence.csv, observed {e.observed_on})",
                            e.observed_on), None
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
        ptype = TYPE_FOR_KIND[kind]
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
    for fn in (lambda: from_row_link(row, canonical_url=canonical, list_url=list_url, document_url=document_url, harvest_date=harvest_date),
               lambda: from_evidence_table(evidence or [], state=state, source_id=source_id, county=county, canonical_url=canonical,
                                           list_url=list_url, document_url=document_url),
               lambda: from_registry(reg, list_url=list_url, document_url=document_url, harvest_date=harvest_date)):
        path, reason = fn()
        if path:
            return path, reasons
        if reason:
            reasons.append(reason)
    return None, reasons


def measure(rows: list[dict]) -> dict:
    """Coverage counts for the purchase path (the product metric): rows,
    evaluated (a type stored), by type, by scope, with a URL."""
    c = {"rows": 0, "evaluated": 0, "not_evaluated": 0, "with_url": 0, "by_type": {}, "by_scope": {}}
    for r in rows:
        c["rows"] += 1
        t = r.get("purchase_path_type")
        if not t:
            c["not_evaluated"] += 1
            continue
        c["evaluated"] += 1
        c["by_type"][t] = c["by_type"].get(t, 0) + 1
        s = r.get("purchase_path_scope") or "?"
        c["by_scope"][s] = c["by_scope"].get(s, 0) + 1
        if r.get("purchase_url"):
            c["with_url"] += 1
    return c
