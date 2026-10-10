"""Where each AVAILABLE source/county stands on acquisition evidence.

One status per (state, source_id, county) acquisition unit:

- ``VERIFIED``: an official page or document describing the acquisition
  process was read and recorded. This comes only from an applicable row of
  the verified evidence tables (``data/purchase_path_evidence*.csv``), or from
  a PRODUCTION_VERIFIED registry row that names the source's own purchase
  document.
- ``NEEDS_REVIEW``: an authoritative process has been identified, but it has
  not been verified by a capture. Examples: a process found through the
  search index only, a policy document read but possibly out of date, or
  wording the capture could not see.
- ``UNAVAILABLE``: the official pages could not be read (for example, HTTP
  403 to the capture runner). This is never treated as "no process exists".
- ``NOT_FOUND``: the official pages were read and describe no acquisition
  step for this inventory, or no official page has been identified.

Only ``data/acquisition_evidence_outcomes.csv`` (one row per unit, each
citing a capture run or the discovery method) can move a unit off the
default. A URL alone never makes evidence VERIFIED.

Evidence here is COUNTY / SOURCE-WIDE: one process record per unit, shared
by every property of that unit and never copied into each row. A
property-specific link (a per-parcel purchase page) stays on the property
row (``purchase_path_scope = 'property'``) and is reported separately.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
OUTCOMES = REPO / "data" / "acquisition_evidence_outcomes.csv"
CANDIDATES = REPO / "data" / "acquisition_candidate_pages.csv"

STATUSES = ("VERIFIED", "NEEDS_REVIEW", "UNAVAILABLE", "NOT_FOUND")
STATUS_LABELS = {
    "VERIFIED": "Verified official process",
    "NEEDS_REVIEW": "Official process identified - not yet verified",
    "UNAVAILABLE": "Official source could not be read",
    "NOT_FOUND": "No official acquisition process found",
}
# How an outcome was established. "capture" = a recorded capture run read the
# official pages; "document_read" = an official document was read directly;
# "search_index" = discovery only (never VERIFIED).
BASES = ("capture", "document_read", "search_index", "evidence_table", "registry")

# Authority types, in the order the product prefers them.
AUTHORITY_TYPES = ("county_treasurer", "county_clerk", "county_tax_collector", "county_land_bank",
                   "state_treasurer", "state_revenue", "state_land_office", "other_government")
AUTHORITY_TYPE_LABELS = {
    "county_treasurer": "County treasurer", "county_clerk": "County clerk", "county_tax_collector": "County tax office",
    "county_land_bank": "Land bank", "state_treasurer": "State treasurer", "state_revenue": "State revenue agency",
    "state_land_office": "State land office", "other_government": "Government office",
}

# What an official acquisition link is.
DOC_KINDS = ("SOURCE_PAGE", "PURCHASE_LINK", "APPLICATION_FORM", "BID_FORM", "INSTRUCTIONS", "TAX_STATEMENT",
             "PROCEDURE", "CONTACT", "PAYMENT_INSTRUCTIONS", "DEED_TRANSFER_INFO", "OTHER_OFFICIAL_DOCUMENT")
DOC_KIND_LABELS = {
    "SOURCE_PAGE": "Official page", "PURCHASE_LINK": "Purchase link", "APPLICATION_FORM": "Application form",
    "BID_FORM": "Bid form", "INSTRUCTIONS": "Instructions", "TAX_STATEMENT": "Tax statement",
    "PROCEDURE": "Procedure", "CONTACT": "Contact", "PAYMENT_INSTRUCTIONS": "Payment instructions",
    "DEED_TRANSFER_INFO": "Deed / transfer information", "OTHER_OFFICIAL_DOCUMENT": "Official document",
}

# The acquisition authority behind each AVAILABLE source, from the source's
# own registry description. Florida Lands Available is always the Clerk of
# the Circuit Court (F.S. 197.502(7)). Texas struck-off property is resold by
# the taxing units through the county; the Galveston evidence names the
# Sheriff.
_AUTHORITY = {
    "fl_laft": ("county_clerk", "Clerk of the Circuit Court"),
    "la_ebr_adjudicated": ("other_government", "East Baton Rouge Parish Attorney's Office"),
    "tx_lgbs": ("county_tax_collector", "County tax assessor-collector / taxing units"),
    "mi_detroit_landbank": ("county_land_bank", "Detroit Land Bank Authority"),
    "mi_oceana_landbank": ("county_land_bank", "Oceana County Land Bank Authority"),
    "mo_stl_lra_inventory": ("county_land_bank", "Land Reutilization Authority (St. Louis Development Corporation)"),
    "ok_oklahoma_county_owned": ("county_treasurer", "Oklahoma County Treasurer"),
    "pa_fayette_repository": ("county_tax_collector", "Fayette County Tax Claim Bureau"),
    "mn_ramsey_tax_forfeit": ("other_government", "Ramsey County Tax-Forfeited Land"),
    "sc_horry_forfeited_land": ("other_government", "Horry County Forfeited Land Commission"),
    "sc_georgetown_forfeited_land": ("other_government", "Georgetown County Forfeited Land Commission"),
    "tn_shelby_landbank": ("county_land_bank", "Shelby County Land Bank"),
}
_AUTHORITY_COUNTY = {("tx_lgbs", "Galveston"): ("other_government", "Galveston County Sheriff's Office")}


def authority_for(source_id: str, county: str = "") -> tuple[str, str]:
    """(authority_type, authority name) for a unit; ('', '') when not recorded."""
    if (source_id, county) in _AUTHORITY_COUNTY:
        return _AUTHORITY_COUNTY[(source_id, county)]
    if source_id in _AUTHORITY:
        return _AUTHORITY[source_id]
    for prefix, val in _AUTHORITY.items():
        if source_id.startswith(prefix):
            return val
    return ("", "")


@dataclass(frozen=True)
class Outcome:
    state: str
    source_id: str
    county: str
    status: str
    basis: str
    reason: str
    attempted_on: str
    run_id: str = ""
    document_url: str = ""


def outcome_problems(o: Outcome) -> list[str]:
    p = []
    if o.status not in STATUSES or o.status == "VERIFIED":
        p.append(f"status {o.status!r} (VERIFIED comes only from the evidence tables or the registry)")
    if o.basis not in ("capture", "document_read", "search_index"):
        p.append(f"basis {o.basis!r}")
    if o.basis == "capture" and not o.run_id:
        p.append("a capture outcome must cite its run_id")
    if o.basis == "search_index" and o.status != "NEEDS_REVIEW":
        p.append("a search-index finding is at most NEEDS_REVIEW")
    if not o.reason.strip() or not o.attempted_on:
        p.append("reason and attempted_on are required")
    if o.document_url and not o.document_url.startswith("https://"):
        p.append("document_url must be https")
    return p


def load_outcomes(path: Path = OUTCOMES) -> list[Outcome]:
    if not Path(path).is_file():
        return []
    with open(path, newline="", encoding="utf-8") as fh:
        return [Outcome(**{k: (r.get(k) or "").strip() for k in Outcome.__dataclass_fields__}) for r in csv.DictReader(fh)]


def load_candidates(path: Path = CANDIDATES) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as fh:
        rows = []
        for r in csv.DictReader(fh):
            url = (r.get("url") or "").strip()
            if not url.startswith("https://"):
                continue
            kind = (r.get("doc_kind") or "").strip() or "SOURCE_PAGE"
            rows.append({"state": r["state"].strip(), "county": r["county"].strip(), "source_id": (r.get("source_id") or "").strip(),
                         "url": url, "doc_kind": kind, "found_via": (r.get("found_via") or "").strip()})
        return rows


@dataclass
class UnitStatus:
    state: str
    source_id: str
    county: str
    status: str
    basis: str
    reason: str = ""
    attempted_on: str = ""
    run_id: str = ""
    authority_type: str = ""
    authority: str = ""
    path_type: str = ""
    scope: str = "source"
    candidates: list = field(default_factory=list)
    document_url: str = ""

    def as_dict(self) -> dict:
        d = {k: v for k, v in self.__dict__.items() if v not in ("", [], None)}
        d["status"] = self.status
        return d


def unit_status(state: str, source_id: str, county: str, *, evidence, registry_row=None,
                outcomes=(), candidates=()) -> UnitStatus:
    """The status of one acquisition unit. Pure: every input is passed in."""
    at, an = authority_for(source_id, county)
    base = dict(state=state, source_id=source_id, county=county, authority_type=at, authority=an)
    for e in evidence:
        if e.applicable and e.state == state and e.source_id == source_id and e.county in (county, "*"):
            return UnitStatus(status="VERIFIED", basis="evidence_table", attempted_on=e.observed_on, path_type=e.path_type,
                              reason=e.source_title or "Official process recorded", **base)
    if registry_row is not None and getattr(registry_row, "purchase_url", "") and \
            getattr(registry_row, "verification_status", "") == "PRODUCTION_VERIFIED" and \
            str(registry_row.purchase_url).startswith("https://"):
        return UnitStatus(status="VERIFIED", basis="registry", attempted_on=getattr(registry_row, "last_checked", ""),
                          reason="The source's own purchase document, recorded with the source", **base)
    cands = [c for c in candidates if c["state"] == state and c["county"] == county and c["source_id"] in ("", source_id)]
    cand_out = [{"url": c["url"], "doc_kind": c["doc_kind"]} for c in cands]
    for o in outcomes:
        if o.state == state and o.source_id == source_id and o.county == county:
            return UnitStatus(status=o.status, basis=o.basis, reason=o.reason, attempted_on=o.attempted_on,
                              run_id=o.run_id, document_url=o.document_url, candidates=cand_out, **base)
    if cands:
        return UnitStatus(status="NEEDS_REVIEW", basis="search_index", candidates=cand_out,
                          reason="Official pages identified; no capture recorded yet", **base)
    return UnitStatus(status="NOT_FOUND", basis="search_index", reason="No official acquisition page identified yet", **base)


# What kind of acquisition evidence a ROW carries (2026-10-10). One value per
# row, decided only from what was verified - never from a URL's existence:
#   property_specific        a verified per-parcel purchase page (scope 'property')
#   listing_level            a verified purchase / offer step on the source's
#                            listing, shared by its parcels (source scope)
#   application_process      a verified county process that is an application,
#                            instructions or an offline step
#   source_list_only         no verified process; only the official list the
#                            row was read from
#   no_verified_online_path  nothing verified and no usable official list link
EVIDENCE_TYPES = ("property_specific", "listing_level", "application_process", "source_list_only",
                  "no_verified_online_path")
EVIDENCE_TYPE_LABELS = {
    "property_specific": "Property-specific purchase page (verified)",
    "listing_level": "Purchase step on the official listing (verified)",
    "application_process": "Official application process (verified)",
    "source_list_only": "Official list only - no online purchase link on file",
    "no_verified_online_path": "No online purchase link on file",
}
_LISTING_TYPES = frozenset({"direct_property_url"})
_URL_TYPES = frozenset({"direct_property_url", "county_instructions", "application_page", "application_download"})
_PROCESS_TYPES = frozenset({"county_instructions", "application_page", "application_download", "in_person",
                            "phone_mail", "quoted_amount", "amount_plus_costs", "amount_on_application"})


def _https(url) -> bool:
    u = str(url or "").strip()
    return u.startswith("https://") and len(u) > len("https://x.y") and " " not in u


def evidence_type(row: dict, unit: "UnitStatus | None" = None) -> str:
    """The acquisition evidence type of one properties row. Pure.

    `row` carries the stored path columns (purchase_path_type /
    purchase_path_scope / purchase_url) and list_url; `unit` is the row's
    acquisition unit status, when known. A path the engine did not type
    (purchase_path_type NULL) is never treated as verified, whatever URL the
    row holds; a URL type without an https URL is malformed and counts as
    nothing verified."""
    ptype = (row.get("purchase_path_type") or "").strip()
    scope = (row.get("purchase_path_scope") or "").strip()
    url = row.get("purchase_url")
    typed_ok = bool(ptype) and (ptype not in _URL_TYPES or _https(url)) and ptype != "none_published"
    if typed_ok and scope == "property" and ptype in _URL_TYPES:
        return "property_specific"
    if typed_ok and ptype in _LISTING_TYPES:
        return "listing_level"
    if typed_ok and ptype in _PROCESS_TYPES:
        return "application_process"
    if unit is not None and unit.status == "VERIFIED" and unit.path_type in _PROCESS_TYPES:
        return "application_process"
    if unit is not None and unit.status == "VERIFIED" and unit.path_type in _LISTING_TYPES:
        return "listing_level"
    if _https(row.get("list_url")):
        return "source_list_only"
    return "no_verified_online_path"
