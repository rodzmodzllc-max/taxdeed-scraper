"""Customer actionability of an AVAILABLE record: the acquisition-path gate.

Policy (2026-10-10): only a property with a defensible, verified acquisition
path may appear to customers as an actionable Available opportunity. An
unverified candidate stays visible to administrators for investigation and
remediation; it is never deleted and its lifecycle status never changes.

A typed path, a source id, a URL, a source label or an observed date is not,
on its own, proof that a buyer can act. The gate therefore reads the facts
the schema actually records and refuses everything else:

Source identity
  SOURCE_ID_MISSING       the row names no source (source_id / harvester_source)
  SOURCE_NOT_PUBLISHED    the source's customer-publication decision is not
                          APPROVED / APPROVED_GRANDFATHERED (a missing decision
                          fails closed - it is not "approved by omission")
Record validity and freshness
  ROW_NOT_ACTIVE          lifecycle status is not active / available
  OBSERVATION_MISSING     no ``last_seen_at`` has ever been stamped (the row was
                          synced before stamping existed, or the sync does not
                          stamp this source) - a metadata gap, not a judgement
  OBSERVATION_STALE       ``last_seen_at`` older than OBSERVATION_DAYS
  LIST_DATED_STALE        the source publishes a list date (``list_as_of``) and
                          it is older than LIST_DAYS - a dated list, not a
                          current one
The acquisition route (the county / source-level verified process record)
  EVIDENCE_UNIT_UNKNOWN   the (state, source, county) unit is not in the
                          acquisition-evidence status file at all
  EVIDENCE_NEEDS_REVIEW   an official process was identified but no capture
                          verified it (NEEDS_REVIEW)
  EVIDENCE_UNAVAILABLE    the official pages could not be read (UNAVAILABLE)
  EVIDENCE_NOT_FOUND      the official pages were read and describe no
                          acquisition step (NOT_FOUND)
  EVIDENCE_NO_RECORD      the unit is VERIFIED but no county record exists in
                          the evidence file to act on
  EVIDENCE_UNTRUSTED_URL  the record's evidence page is not https, a bare
                          homepage, a search engine or a blocked vendor
  EVIDENCE_NO_CHANNEL     the record states no actionable channel: no
                          application / form document, no online page, and no
                          published steps with a contact
  EVIDENCE_STALE          the record was last verified more than EVIDENCE_DAYS
                          ago
  PATH_NONE               the source states there is no purchase path
  PATH_MISMATCH           the row's own typed path disagrees with the verified
                          county record's path type

Nothing here tests a route or implies that anyone did: VERIFIED means the
source's own page or document was read and recorded (acquisition_evidence_status).

The customer-facing gate is STAGED: ``config.js`` ``availableGate`` is "off"
(the publication decision alone decides, as before) or "enforce" (a
non-admin sees an Available row only when ``verify()`` passes). app.js
``acquisitionVerification()`` is the same function; ``tests/python/fixtures/
acquisition_gate_cases.json`` pins the two equal.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from urllib.parse import urlsplit

OBSERVATION_DAYS = 14      # an Available row must have been read from its source within this window
LIST_DAYS = 365            # a source-published list date older than this is a dated list, not current inventory
EVIDENCE_DAYS = 180        # the verified county process record must have been verified within this window

PUBLISHED_STATUSES = ("APPROVED", "APPROVED_GRANDFATHERED")
ACTIVE_STATUSES = ("active", "available")

# Hosts that are never an acquisition route (laft_purchase_paths.UNTRUSTED_HOST_SUFFIXES, mirrored).
UNTRUSTED_HOST_SUFFIXES = ("google.com", "bing.com", "duckduckgo.com", "yahoo.com", "search.brave.com",
                           "pbfcm.com", "mvbalaw.com", "govease.com", "ctsa.com", "lgbs.com")

REASONS = {
    "SOURCE_ID_MISSING": "The record names no source",
    "SOURCE_NOT_PUBLISHED": "The source is not approved for customer publication",
    "ROW_NOT_ACTIVE": "The record is not active",
    "OBSERVATION_MISSING": "No read date has been recorded for this record",
    "OBSERVATION_STALE": f"The record was not read from its source in the last {OBSERVATION_DAYS} days",
    "LIST_DATED_STALE": f"The source's list is dated more than {LIST_DAYS} days ago",
    "EVIDENCE_UNIT_UNKNOWN": "No acquisition-evidence status exists for this source and county",
    "EVIDENCE_NEEDS_REVIEW": "An official process was identified but has not been verified",
    "EVIDENCE_UNAVAILABLE": "The official acquisition pages could not be read",
    "EVIDENCE_NOT_FOUND": "No official acquisition process was found",
    "EVIDENCE_NO_RECORD": "The unit is marked verified but no county process record is on file",
    "EVIDENCE_UNTRUSTED_URL": "The evidence page is not an official https page",
    "EVIDENCE_NO_CHANNEL": "The verified process names no way to act (no form, page, or steps with a contact)",
    "EVIDENCE_STALE": f"The county process was last verified more than {EVIDENCE_DAYS} days ago",
    "PATH_NONE": "The source states there is no purchase path",
    "PATH_MISMATCH": "The record's typed path disagrees with the verified county process",
}

# Why a withheld row is withheld, for the dry run and the admin label:
#   source_not_published  the source decision (not this gate's finding)
#   no_route              the official pages describe no way to acquire
#   pending_verification  a process exists or may exist; it is not verified yet
#   metadata_gap          a fact the pipeline has not recorded (never a judgement
#                         about the route)
#   stale                 the record or its list is not current
CLASSES = ("verified", "source_not_published", "no_route", "pending_verification", "metadata_gap", "stale")
CLASS_OF_REASON = {
    "SOURCE_ID_MISSING": "metadata_gap",
    "SOURCE_NOT_PUBLISHED": "source_not_published",
    "ROW_NOT_ACTIVE": "stale",
    "OBSERVATION_MISSING": "metadata_gap",
    "OBSERVATION_STALE": "stale",
    "LIST_DATED_STALE": "stale",
    "EVIDENCE_UNIT_UNKNOWN": "metadata_gap",
    "EVIDENCE_NEEDS_REVIEW": "pending_verification",
    "EVIDENCE_UNAVAILABLE": "pending_verification",
    "EVIDENCE_NOT_FOUND": "no_route",
    "EVIDENCE_NO_RECORD": "metadata_gap",
    "EVIDENCE_UNTRUSTED_URL": "pending_verification",
    "EVIDENCE_NO_CHANNEL": "pending_verification",
    "EVIDENCE_STALE": "pending_verification",
    "PATH_NONE": "no_route",
    "PATH_MISMATCH": "pending_verification",
}
# The class that names a withheld row when several reasons apply.
CLASS_PRECEDENCE = ("source_not_published", "no_route", "pending_verification", "metadata_gap", "stale")

CLASS_LABELS = {
    "verified": "Verified acquisition path",
    "source_not_published": "Source not customer-published",
    "no_route": "No acquisition route found",
    "pending_verification": "Acquisition route pending verification",
    "metadata_gap": "Missing record metadata",
    "stale": "Not current",
}


@dataclass
class Verification:
    verified: bool
    reasons: list = field(default_factory=list)
    classification: str = "verified"
    evidence_status: str = ""
    path_type: str = ""
    evidence_observed_on: str = ""

    def as_dict(self) -> dict:
        return {"verified": self.verified, "reasons": list(self.reasons), "classification": self.classification,
                "evidence_status": self.evidence_status, "path_type": self.path_type,
                "evidence_observed_on": self.evidence_observed_on}


def _days_between(iso: str | None, today: date) -> int | None:
    if not iso:
        return None
    try:
        d = date.fromisoformat(str(iso)[:10])
    except ValueError:
        return None
    return (today - d).days


def untrusted_url(url) -> bool:
    """True when a URL can never be an acquisition evidence page."""
    if not isinstance(url, str) or not url.startswith("https://"):
        return True
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if not host:
        return True
    if parts.path in ("", "/") and not parts.query and not parts.fragment:
        return True
    if any(host == s or host.endswith("." + s) for s in UNTRUSTED_HOST_SUFFIXES):
        return True
    return False


def has_channel(acq: dict | None) -> bool:
    """A verified record is actionable only when it names a way to act."""
    if not isinstance(acq, dict):
        return False
    app = acq.get("application_url")
    if isinstance(app, str) and app.startswith("https://"):
        return True
    if acq.get("mode") == "online" and isinstance(acq.get("url"), str) and str(acq.get("url")).startswith("https://"):
        return True
    steps = acq.get("steps")
    contact = any(isinstance(acq.get(k), str) and acq.get(k).strip() for k in ("phone", "email", "address", "mailing_address"))
    return bool(isinstance(steps, list) and len(steps) > 0 and contact)


def classify(reasons: list[str]) -> str:
    if not reasons:
        return "verified"
    classes = {CLASS_OF_REASON[r] for r in reasons}
    for c in CLASS_PRECEDENCE:
        if c in classes:
            return c
    return "pending_verification"


def verify(row: dict, *, unit: dict | None, record: dict | None, today: date | None = None) -> Verification:
    """The gate for one AVAILABLE row.

    ``row``    the property row (only these keys are read: source_id,
               harvester_source, publication_status, status, last_seen_at,
               list_as_of, purchase_path_type)
    ``unit``   the acquisition-evidence status entry for the row's (state,
               source, county), or None
    ``record`` the county-level verified process record for that unit (an
               entry of acquisition-evidence.json "records"), or None
    """
    today = today or date.today()
    reasons: list[str] = []
    sid = row.get("source_id") or row.get("harvester_source")
    if not sid:
        reasons.append("SOURCE_ID_MISSING")
    if row.get("publication_status") not in PUBLISHED_STATUSES:
        reasons.append("SOURCE_NOT_PUBLISHED")
    if (row.get("status") or "active") not in ACTIVE_STATUSES:
        reasons.append("ROW_NOT_ACTIVE")
    seen = _days_between(row.get("last_seen_at"), today)
    if seen is None:
        reasons.append("OBSERVATION_MISSING")
    elif seen > OBSERVATION_DAYS:
        reasons.append("OBSERVATION_STALE")
    listed = _days_between(row.get("list_as_of"), today)
    if listed is not None and listed > LIST_DAYS:
        reasons.append("LIST_DATED_STALE")

    status = (unit or {}).get("status") or ""
    path_type = ""
    observed = ""
    if row.get("purchase_path_type") == "none_published":
        reasons.append("PATH_NONE")
    if not unit:
        reasons.append("EVIDENCE_UNIT_UNKNOWN")
    elif status == "NEEDS_REVIEW":
        reasons.append("EVIDENCE_NEEDS_REVIEW")
    elif status == "UNAVAILABLE":
        reasons.append("EVIDENCE_UNAVAILABLE")
    elif status == "NOT_FOUND":
        reasons.append("EVIDENCE_NOT_FOUND")
    elif status == "VERIFIED":
        if not record:
            reasons.append("EVIDENCE_NO_RECORD")
        else:
            path_type = str(record.get("path_type") or "")
            acq = record.get("acquisition") if isinstance(record.get("acquisition"), dict) else None
            observed = str(record.get("purchase_path_observed_on") or (acq or {}).get("observed_on") or "")
            if acq and acq.get("mode") == "none":
                reasons.append("PATH_NONE")
            if untrusted_url(record.get("purchase_evidence_url")):
                reasons.append("EVIDENCE_UNTRUSTED_URL")
            if not has_channel(acq):
                reasons.append("EVIDENCE_NO_CHANNEL")
            age = _days_between(observed, today)
            if age is None or age > EVIDENCE_DAYS:
                reasons.append("EVIDENCE_STALE")
            rt = row.get("purchase_path_type")
            if rt and rt != "none_published" and path_type and rt != path_type:
                reasons.append("PATH_MISMATCH")
    else:
        reasons.append("EVIDENCE_UNIT_UNKNOWN")
    # Each reason once, in the order above.
    seen_r: list[str] = []
    for r in reasons:
        if r not in seen_r:
            seen_r.append(r)
    return Verification(verified=not seen_r, reasons=seen_r, classification=classify(seen_r),
                        evidence_status=status, path_type=path_type, evidence_observed_on=observed)


def find_unit(status_rows, state: str, source_id: str, county: str) -> dict | None:
    for u in status_rows or []:
        if u.get("state") == state and u.get("source_id") == source_id and u.get("county") == county:
            return u
    return None


def find_record(records, state: str, source_id: str, county: str) -> dict | None:
    """The county record for the unit, else the source-wide ('*') record."""
    same = [r for r in records or [] if r.get("state") == state and r.get("source_id") == source_id]
    for r in same:
        if r.get("county") == county:
            return r
    for r in same:
        if r.get("county") == "*":
            return r
    return None
