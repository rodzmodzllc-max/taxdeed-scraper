"""Customer-publication gate: one auditable state per properties row (2026-10-10).

Harvested data is not customer inventory. A row is CUSTOMER_PUBLISHED only
when every gate passes, in this order:

  1. source     the row's source is approved for customer use (registry
                publication APPROVED / APPROVED_GRANDFATHERED, after the admin
                reviews publication_gate.py applies)
  2. rules      the state's product rules for the row's ledger are verified
                sufficiently for the claimed behaviour: data/state_ledgers.csv
                eligibility OFFERED or COUNTY_DEPENDENT (and, for a
                county-dependent product, the row's county is covered)
  3. validation the row names its state, county, ledger and identifier
  4. path       a credible acquisition path is documented - per ledger:
                  AUCTIONS   the record's own sale listing or the county's
                             auction site (url_auction, kind sale / county),
                             an https page that is not a homepage
                  AVAILABLE  the verified acquisition evidence for the row's
                             (state, source, county) unit (public/
                             acquisition-evidence.json, status VERIFIED), or
                             a record-level typed path
                  LIENS      a record-level typed path (county-held lien
                             assignment evidence) or the county's own
                             certificate purchase page recorded in the
                             registry for that county
                A county-level portal or published procedure is a valid path
                - a unique URL per record is not required - but a homepage or
                a search engine never is.
  5. freshness  the row was observed recently (AVAILABLE 14 days, AUCTIONS and
                LIENS 7 days, on last_seen_at else updated_at), an auction's
                sale date has not passed, and county-level path evidence is
                not older than 180 days

The stored state is the first gate that fails, or CUSTOMER_PUBLISHED:

  DISCOVERED                 harvested; no gate evaluated yet (no context)
  RULES_VERIFIED             source and rules passed (milestone)
  PATH_VERIFIED              ... and a path is documented (milestone)
  CUSTOMER_PUBLISHED         every gate passed
  ADMIN_ONLY_SOURCE_REVIEW   source not approved, rules not verified, or the
                             record fails validation
  ADMIN_ONLY_NO_PATH         no credible acquisition path documented
  ADMIN_ONLY_STALE           path or observation too old, or sale date passed
  CLOSED                     the row is not active

`publication_progress` keeps the milestone reached (DISCOVERED /
RULES_VERIFIED / PATH_VERIFIED / CUSTOMER_PUBLISHED) beside the state, so an
admin sees how far a withheld row got. These states never replace the
auction / availability / certificate lifecycle status (`status`,
`inventory_status`): a CLOSED publication state follows the lifecycle, it
never drives it, and a failed source read changes nothing here (the row keeps
its last decision until a successful read says otherwise).

Every decision carries its reasons (REASONS), the remediation an admin needs,
and the structured path evidence (PathEvidence). Nothing here reaches the
network: the context is built from repository files and the rows handed in.
"""
from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

from . import state_rules as SR
from . import publication as pub
from . import county_source_registry as csr

REPO = Path(__file__).resolve().parents[2]
ACQUISITION_EVIDENCE = REPO / "public" / "acquisition-evidence.json"

STATES = ("DISCOVERED", "RULES_VERIFIED", "PATH_VERIFIED", "CUSTOMER_PUBLISHED",
          "ADMIN_ONLY_NO_PATH", "ADMIN_ONLY_SOURCE_REVIEW", "ADMIN_ONLY_STALE", "CLOSED")
MILESTONES = ("DISCOVERED", "RULES_VERIFIED", "PATH_VERIFIED", "CUSTOMER_PUBLISHED")
ADMIN_ONLY = ("ADMIN_ONLY_NO_PATH", "ADMIN_ONLY_SOURCE_REVIEW", "ADMIN_ONLY_STALE")
STATE_LABELS = {
    "DISCOVERED": "Discovered - not yet evaluated",
    "RULES_VERIFIED": "Source and rules verified",
    "PATH_VERIFIED": "Acquisition path verified",
    "CUSTOMER_PUBLISHED": "Customer-published",
    "ADMIN_ONLY_NO_PATH": "Admin only - no verified acquisition path",
    "ADMIN_ONLY_SOURCE_REVIEW": "Admin only - source or rules under review",
    "ADMIN_ONLY_STALE": "Admin only - stale",
    "CLOSED": "Closed",
}
GATES = ("source", "rules", "validation", "path", "freshness")
LEDGER_NAMES = {"auctions": "AUCTIONS", "buy": "AVAILABLE", "lien": "LIENS_CERTIFICATES",
                "auction": "AUCTIONS", "laft": "AVAILABLE", "certificate": "LIENS_CERTIFICATES"}
PATH_TYPES = ("auction_bidding", "direct_purchase", "application", "certificate_purchase", "other_verified_process")
PATH_TYPE_LABELS = {"auction_bidding": "Auction / bidding", "direct_purchase": "Direct purchase",
                    "application": "Application", "certificate_purchase": "Certificate / lien purchase",
                    "other_verified_process": "Other verified process"}
SCOPES = ("record", "county", "source")
# Days a row may go unobserved and still be customer-published, per ledger.
FRESHNESS_DAYS = {"AUCTIONS": 7, "AVAILABLE": 14, "LIENS_CERTIFICATES": 7}
PATH_MAX_AGE_DAYS = 180
# Every reason a decision can carry, with the remediation an admin needs.
REASONS = {
    "SOURCE_UNREVIEWED": "The source is collected but awaiting customer-publication review.",
    "SOURCE_RESTRICTED": "The source's terms are under legal review.",
    "SOURCE_BLOCKED": "The source is blocked.",
    "SOURCE_UNKNOWN": "The row's source is not in the source registry.",
    "RULES_NOT_VERIFIED": "The state's rules for this product are not verified (eligibility NOT_VERIFIED).",
    "RULES_NOT_OFFERED": "The verified rules say this state does not offer this product.",
    "COUNTY_NOT_COVERED": "The product is county-dependent and this county has no tracked source or verified procedure.",
    "RECORD_INVALID": "The record is missing its state, county, ledger or identifier.",
    "PATH_MISSING": "No acquisition path is documented for this record or its county.",
    "PATH_UNTRUSTED": "The only link on file is a homepage, a search page or not https - not a route to the process.",
    "PATH_NEEDS_REVIEW": "The county's acquisition process was captured but not verified.",
    "PATH_UNAVAILABLE": "The county's acquisition page could not be read.",
    "PATH_NOT_FOUND": "No official acquisition page has been found for this county.",
    "PATH_STALE": "The acquisition evidence is older than the allowed age.",
    "OBSERVATION_STALE": "The record was not observed in a successful source read within the allowed window.",
    "SALE_DATE_PASSED": "The sale date has passed and no result is published.",
    "NOT_ACTIVE": "The lifecycle status is not active.",
}
REMEDIATION = {
    "SOURCE_UNREVIEWED": "Record an admin publication review for the source (Admin > Source publication).",
    "SOURCE_RESTRICTED": "Resolve the legal review and record the publication decision.",
    "SOURCE_BLOCKED": "None - a blocked source is never published.",
    "SOURCE_UNKNOWN": "Add the source to data/county_source_registry.csv and re-run the gate.",
    "RULES_NOT_VERIFIED": "Read the governing statute or county procedure and record it in data/state_ledgers.csv / state_rules.csv.",
    "RULES_NOT_OFFERED": "None - show the verified rules explanation instead of inventory.",
    "COUNTY_NOT_COVERED": "Add the county's source or verified procedure to the registry / rules.",
    "RECORD_INVALID": "Fix the harvester so the record carries state, county, ledger and identifier.",
    "PATH_MISSING": "Capture the county's official acquisition page (job=evidence) and record a verified evidence row.",
    "PATH_UNTRUSTED": "Record the actual process page or published procedure, not the homepage.",
    "PATH_NEEDS_REVIEW": "Read the capture digest and record a verified evidence row.",
    "PATH_UNAVAILABLE": "Re-run the capture when the county page is reachable.",
    "PATH_NOT_FOUND": "Add candidate pages (data/acquisition_candidate_pages.csv) and capture them.",
    "PATH_STALE": "Re-verify the county's acquisition page and update observed_on.",
    "OBSERVATION_STALE": "Run the source's harvest; a successful read refreshes the observation.",
    "SALE_DATE_PASSED": "The lifecycle closes past sales; verify the outcome or wait for the close-out.",
    "NOT_ACTIVE": "None - closed rows are history.",
}
_HOMEPAGE = re.compile(r"^https://[^/]+/?$")
_SEARCH_HOSTS = ("google.", "bing.", "duckduckgo.", "yahoo.")


@dataclass
class PathEvidence:
    ledger: str
    inventory_type: str
    state: str
    county: str
    authority: str
    source_url: str
    source_type: str
    destination_url: str
    procedure: str
    path_type: str
    instructions: str
    eligibility: str
    verification_status: str
    last_verified: str
    notes: str
    scope: str
    missing_reason: str

    def as_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v not in ("", None)}


@dataclass
class Decision:
    state: str
    progress: str
    reasons: list[str]
    gates: dict
    path: PathEvidence | None
    remediation: str

    def as_dict(self) -> dict:
        return {"state": self.state, "progress": self.progress, "reasons": list(self.reasons), "gates": dict(self.gates),
                "path": self.path.as_dict() if self.path else None, "remediation": self.remediation}


@dataclass
class Context:
    """Everything a decision needs besides the row. Built once per run."""
    source_publication: dict[str, str] = field(default_factory=dict)          # source_id -> publication
    source_restrictions: dict[str, str] = field(default_factory=dict)         # source_id -> restrictions text
    ledger_eligibility: dict[tuple[str, str], str] = field(default_factory=dict)   # (state, ledger) -> eligibility
    coverage: dict[tuple[str, str], set[str]] = field(default_factory=dict)   # (state, ledger) -> counties
    registry_units: dict[tuple[str, str, str], dict] = field(default_factory=dict)  # (state, source_id, county) -> row dict
    acquisition_status: dict[tuple[str, str, str], dict] = field(default_factory=dict)
    acquisition_records: dict[tuple[str, str, str], dict] = field(default_factory=dict)
    now: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


def build_context(now: datetime | None = None, *, registry=None, ledgers=None, acquisition: dict | None = None,
                  coverage: dict | None = None) -> Context:
    from . import state_verification as SV  # noqa: PLC0415
    ctx = Context(now=now or datetime.now(timezone.utc))
    rows = csr.load_registry() if registry is None else registry
    for sid, d in pub.decisions_by_source(rows).items():
        ctx.source_publication[sid] = d.publication
        ctx.source_restrictions[sid] = d.restrictions
    for r in rows:
        if r.source_id and r.verification_status == "PRODUCTION_VERIFIED":
            ctx.registry_units[(r.state, r.source_id, r.county)] = {
                "canonical_url": r.canonical_url, "document_url": getattr(r, "document_url", ""),
                "purchase_url": getattr(r, "purchase_url", ""), "purchase_url_kind": getattr(r, "purchase_url_kind", ""),
                "source_authority": r.source_authority, "last_checked": r.last_checked,
                "publishing_unit_name": getattr(r, "publishing_unit_name", ""), "inventory_type": getattr(r, "inventory_type", "")}
    for l in (SR.load_ledgers() if ledgers is None else ledgers):
        ctx.ledger_eligibility[(l.state, l.ledger)] = l.eligibility
    if coverage is None:
        rules = SR.load_rules()
        for (st, ledger) in list(ctx.ledger_eligibility):
            ctx.coverage[(st, ledger)] = {c["county"] for c in SV.county_coverage(st, ledger, rules=[r for r in rules if r.state == st])}
    else:
        ctx.coverage = {k: set(v) for k, v in coverage.items()}
    doc = acquisition
    if doc is None and ACQUISITION_EVIDENCE.is_file():
        doc = json.loads(ACQUISITION_EVIDENCE.read_text(encoding="utf-8"))
    for u in (doc or {}).get("status", []):
        ctx.acquisition_status[(u["state"], u["source_id"], u["county"])] = u
    for rec in (doc or {}).get("records", []):
        ctx.acquisition_records[(rec["state"], rec["source_id"], rec["county"])] = rec
    return ctx


def ledger_of(row: dict) -> str | None:
    for k in ("source", "ledger_type"):
        v = row.get(k)
        if v in LEDGER_NAMES:
            return LEDGER_NAMES[v]
    return None


def _dt(value) -> datetime | None:
    if not value:
        return None
    s = str(value).replace("Z", "+00:00")
    try:
        d = datetime.fromisoformat(s[:10] if len(s) == 10 else s)
    except ValueError:
        return None
    return d.replace(tzinfo=timezone.utc) if d.tzinfo is None else d


def _https_process_url(url) -> str | None:
    """None when the URL is acceptable as a route to a process; else the reason."""
    u = str(url or "").strip()
    if not u.startswith("https://"):
        return "PATH_UNTRUSTED"
    host = (urlparse(u).hostname or "").lower()
    if any(host.startswith(h) or ("." + h) in host for h in _SEARCH_HOSTS):
        return "PATH_UNTRUSTED"
    if _HOMEPAGE.match(u):
        return "PATH_UNTRUSTED"
    return None


def _observed_at(row: dict) -> datetime | None:
    return _dt(row.get("last_seen_at")) or _dt(row.get("updated_at"))


def _path_for(row: dict, ledger: str, sid: str, ctx: Context) -> tuple[PathEvidence, str | None]:
    """The structured path evidence for a row and the failing reason, if any."""
    st, county = str(row.get("state") or ""), str(row.get("county") or "")
    unit = ctx.registry_units.get((st, sid, county)) or next((v for (s, i, c), v in ctx.registry_units.items() if s == st and i == sid), None) or {}
    base = dict(ledger=ledger, inventory_type=str(row.get("inventory_type") or unit.get("inventory_type") or ""), state=st, county=county,
                authority=str(unit.get("publishing_unit_name") or ""), source_url=str(unit.get("canonical_url") or ""),
                source_type=str(unit.get("source_authority") or ""), destination_url="", procedure="", path_type="", instructions="",
                eligibility="", verification_status="NOT_VERIFIED", last_verified="", notes="", scope="", missing_reason="")
    observed = _observed_at(row)
    if ledger == "AUCTIONS":
        url, kind = str(row.get("url_auction") or "").strip(), str(row.get("url_auction_kind") or "")
        if not url:
            return PathEvidence(**{**base, "missing_reason": "PATH_MISSING"}), "PATH_MISSING"
        bad = _https_process_url(url)
        if bad or kind not in ("sale", "county"):
            return PathEvidence(**{**base, "destination_url": url, "missing_reason": "PATH_UNTRUSTED",
                                   "notes": f"url_auction_kind {kind or 'unknown'}"}), "PATH_UNTRUSTED"
        return PathEvidence(**{**base, "destination_url": url, "path_type": "auction_bidding", "scope": "record" if kind == "sale" else "county",
                               "verification_status": "VERIFIED", "last_verified": observed.isoformat() if observed else "",
                               "procedure": "Bid on the county's sale listing" if kind == "sale" else "Bid on the county's auction site",
                               "notes": "read from the county's sale site with the record"}), None
    # AVAILABLE and LIENS: a record-level typed path first.
    ptype, pscope = str(row.get("purchase_path_type") or ""), str(row.get("purchase_path_scope") or "")
    rec = ctx.acquisition_records.get((st, sid, county))
    status = ctx.acquisition_status.get((st, sid, county))
    if status and status.get("status") == "VERIFIED" and rec:
        acq = rec.get("acquisition") or {}
        ev_url = str(rec.get("purchase_evidence_url") or acq.get("evidence_url") or "")
        observed_on = str(rec.get("purchase_path_observed_on") or acq.get("observed_on") or "")
        rtype = str(rec.get("path_type") or "")
        path_type = ("application" if rtype in ("application_download", "application_page", "bid_form", "offer_form") else
                     "direct_purchase" if rtype in ("direct_property_url", "online_purchase") else
                     "certificate_purchase" if ledger == "LIENS_CERTIFICATES" else "other_verified_process")
        ev = PathEvidence(**{**base, "authority": str(status.get("authority") or base["authority"]), "destination_url": str(acq.get("application_url") or ev_url),
                             "procedure": " | ".join(acq.get("steps") or []) or str(rec.get("purchase_instructions") or "")[:400],
                             "path_type": path_type, "instructions": str(rec.get("purchase_instructions") or "")[:400],
                             "eligibility": str(rec.get("eligibility") or ""), "verification_status": "VERIFIED",
                             "last_verified": observed_on, "scope": str(status.get("scope") or rec.get("purchase_path_scope") or "county"),
                             "notes": f"verified evidence row ({rec.get('purchase_evidence_type') or 'official page'})"})
        if observed_on and ctx.now - _dt(observed_on) > timedelta(days=PATH_MAX_AGE_DAYS):
            ev.missing_reason = "PATH_STALE"
            return ev, "PATH_STALE"
        return ev, None
    if ptype and pscope == "record":
        url = str(row.get("purchase_url") or "")
        bad = _https_process_url(url) if url else None
        if not bad:
            return PathEvidence(**{**base, "destination_url": url, "path_type": "direct_purchase" if ptype == "direct_property_url" else "application",
                                   "scope": "record", "verification_status": "VERIFIED", "last_verified": str(row.get("purchase_path_observed_on") or ""),
                                   "notes": f"record-level typed path {ptype}"}), None
    if ledger == "LIENS_CERTIFICATES" and unit:
        # The county's own certificate purchase page recorded for this county
        # (LienHub's county-held list, a treasurer's assignment page).
        url = str(unit.get("purchase_url") or unit.get("canonical_url") or "")
        bad = _https_process_url(url)
        if not bad and ctx.registry_units.get((st, sid, county)):
            last = str(unit.get("last_checked") or "")
            ev = PathEvidence(**{**base, "destination_url": url, "path_type": "certificate_purchase", "scope": "county",
                                 "verification_status": "VERIFIED", "last_verified": last,
                                 "procedure": "Purchase (assignment) of county-held certificates on the county's own list page",
                                 "notes": "registry row for this county (PRODUCTION_VERIFIED)"})
            if last and ctx.now - _dt(last) > timedelta(days=PATH_MAX_AGE_DAYS):
                ev.missing_reason = "PATH_STALE"
                return ev, "PATH_STALE"
            return ev, None
    reason = "PATH_MISSING"
    if status:
        reason = {"NEEDS_REVIEW": "PATH_NEEDS_REVIEW", "UNAVAILABLE": "PATH_UNAVAILABLE", "NOT_FOUND": "PATH_NOT_FOUND"}.get(status.get("status"), "PATH_MISSING")
    return PathEvidence(**{**base, "missing_reason": reason, "notes": str((status or {}).get("reason") or "")[:300],
                           "authority": str((status or {}).get("authority") or base["authority"])}), reason


def decide(row: dict, ctx: Context) -> Decision:
    reasons: list[str] = []
    gates = {g: None for g in GATES}
    if str(row.get("status") or "active") != "active":
        return Decision("CLOSED", "DISCOVERED", ["NOT_ACTIVE"], gates, None, REMEDIATION["NOT_ACTIVE"])
    ledger = ledger_of(row)
    sid = pub.source_id_of(row) or ""
    st, county = str(row.get("state") or ""), str(row.get("county") or "")
    # 1. source
    publication = ctx.source_publication.get(sid)
    if sid and publication in pub.PUBLISHABLE_STATUSES:
        gates["source"] = "PASS"
    else:
        gates["source"] = "FAIL"
        reasons.append({"UNREVIEWED": "SOURCE_UNREVIEWED", "RESTRICTED": "SOURCE_RESTRICTED", "BLOCKED": "SOURCE_BLOCKED"}.get(publication or "", "SOURCE_UNKNOWN"))
    # 2. rules
    elig = ctx.ledger_eligibility.get((st, ledger or ""))
    if elig in ("OFFERED", "COUNTY_DEPENDENT") and (elig == "OFFERED" or county in ctx.coverage.get((st, ledger), set())):
        gates["rules"] = "PASS"
    else:
        gates["rules"] = "FAIL"
        reasons.append("RULES_NOT_OFFERED" if elig == "NOT_OFFERED" else "COUNTY_NOT_COVERED" if elig == "COUNTY_DEPENDENT" else "RULES_NOT_VERIFIED")
    # 3. validation
    if st and county and ledger and (row.get("case_no") or row.get("parcel") or row.get("certificate_no")):
        gates["validation"] = "PASS"
    else:
        gates["validation"] = "FAIL"
        reasons.append("RECORD_INVALID")
    if "FAIL" in (gates["source"], gates["rules"], gates["validation"]):
        return Decision("ADMIN_ONLY_SOURCE_REVIEW", "DISCOVERED", reasons, gates, None, REMEDIATION[reasons[0]])
    # 4. path
    path, path_reason = _path_for(row, ledger, sid, ctx)
    if path_reason and path_reason != "PATH_STALE":
        gates["path"] = "FAIL"
        reasons.append(path_reason)
        return Decision("ADMIN_ONLY_NO_PATH", "RULES_VERIFIED", reasons, gates, path, REMEDIATION[path_reason])
    gates["path"] = "PASS"
    # 5. freshness
    observed = _observed_at(row)
    window = timedelta(days=FRESHNESS_DAYS[ledger])
    if observed is None or ctx.now - observed > window:
        reasons.append("OBSERVATION_STALE")
    sale = _dt(row.get("sale_date")) if ledger == "AUCTIONS" else None
    if sale and sale.date() < ctx.now.date():
        reasons.append("SALE_DATE_PASSED")
    if path_reason == "PATH_STALE":
        reasons.append("PATH_STALE")
    if reasons:
        gates["freshness"] = "FAIL"
        return Decision("ADMIN_ONLY_STALE", "PATH_VERIFIED", reasons, gates, path, REMEDIATION[reasons[0]])
    gates["freshness"] = "PASS"
    return Decision("CUSTOMER_PUBLISHED", "CUSTOMER_PUBLISHED", [], gates, path, "")


def summarize(decisions) -> dict:
    """Counts only, per state."""
    out: dict[str, int] = {s: 0 for s in STATES}
    for d in decisions:
        out[d.state] = out.get(d.state, 0) + 1
    return out
