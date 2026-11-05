"""Replies from offices and vendors about using their records (2026-11-04;
second round 2026-11-05).

data/office_replies.csv lists each reply the product owner has received,
with the question it actually answered. The register exists because a reply
is easy to over-read:

  * a public link, or permission to link, is not permission to collect the
    records or to reuse them commercially;
  * a reply that only routes a records request, or only says what is
    technically acceptable, has not answered the commercial-use question.

question_answered: ROUTING_ONLY | TECHNICAL_ONLY | COMMERCIAL_USE
commercial_use:    PERMITTED | PROHIBITED_WITHOUT_WRITTEN_AUTHORIZATION | NOT_ANSWERED
automated_collection: PERMITTED_WITH_LIMITS | PROHIBITED | NOT_ANSWERED - what
    the reply said about automated reading, kept apart from commercial use
    (RealAuction refused automated collection and did not address display or
    links).
collection_limits: "host=...;max_per_day=N;min_interval_s=N" when a reply
    allowed automation under limits (Citrus Clerk); collection_limits_for()
    hands them to the harvesters (scripts/host_limits.py).
restricted_link_patterns: "|"-separated, lower-case URL fragments the office
    restricts as links (e.g. court-case deep links); never offered to a
    customer as a link (restricted_link_reason()). A pattern starting with
    "!" names an entry page the office itself sends people to (Volusia Clerk:
    app02.clerk.org/or_td/): a URL that is exactly that page (scheme and a
    trailing slash ignored) stays allowed, and entry_link() returns it as the
    link to offer instead of a restricted one.
owner_decision: "" or PENDING. A prohibition is enforced on the permission
    records (RESTRICTED) unless the owner's decision on it is PENDING. A
    PENDING prohibition keeps the existing interim records, can never back a
    documented record, withholds nothing by itself (prohibits_reuse() is
    False) and must be listed in docs/source-permissions.md.
authorization_id: required for a reply that grants something; a reply
    recorded without one grants nothing, so the sources it names may carry no
    documented reuse record.

problems() is the consistency check a test runs: the register must agree with
data/source_permissions.csv and harvesters/governance/authorization.py.
"""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
REPLIES_CSV = REPO / "data" / "office_replies.csv"
DOCS = REPO / "docs" / "source-permissions.md"

QUESTIONS = ("ROUTING_ONLY", "TECHNICAL_ONLY", "COMMERCIAL_USE")
COMMERCIAL = ("PERMITTED", "PROHIBITED_WITHOUT_WRITTEN_AUTHORIZATION", "NOT_ANSWERED")
AUTOMATED = ("PERMITTED_WITH_LIMITS", "PROHIBITED", "NOT_ANSWERED")
OWNER_DECISIONS = ("", "PENDING")
# Operations that put an office's records into the product. A reply that did
# not answer the commercial-use question can never back a DOCUMENTED record
# for any of them; a reply that prohibits commercial use requires them denied.
REUSE_OPERATIONS = ("fetch", "parse", "store", "display", "enrich", "redistribute")
# Operations that read a source automatically.
COLLECTION_OPERATIONS = ("fetch", "parse")


@dataclass(frozen=True)
class OfficeReply:
    office: str
    state: str
    county: str
    source_ids: tuple[str, ...]
    authorization_id: str
    question_answered: str
    commercial_use: str
    permits: str
    restricts: str
    restricted_link_patterns: tuple[str, ...]
    recorded_on: str
    evidence: str
    received_on: str = ""
    automated_collection: str = "NOT_ANSWERED"
    collection_limits: str = ""
    owner_decision: str = ""

    @property
    def pending(self) -> bool:
        return self.owner_decision == "PENDING"

    @property
    def enforced_prohibition(self) -> bool:
        """A commercial-use prohibition the permission records must enforce."""
        return self.commercial_use == "PROHIBITED_WITHOUT_WRITTEN_AUTHORIZATION" and not self.pending

    def limits(self) -> dict[str, str]:
        out: dict[str, str] = {}
        for part in self.collection_limits.split(";"):
            if "=" in part:
                k, v = part.split("=", 1)
                out[k.strip()] = v.strip()
        return out


def load(path: Path | None = None) -> list[OfficeReply]:
    with (path or REPLIES_CSV).open(encoding="utf-8", newline="") as fh:
        out = []
        for r in csv.DictReader(fh):
            out.append(OfficeReply(
                office=r["office"].strip(), state=r["state"].strip(), county=r["county"].strip(),
                source_ids=tuple(s for s in r["source_ids"].split("|") if s),
                authorization_id=r["authorization_id"].strip(),
                question_answered=r["question_answered"].strip(), commercial_use=r["commercial_use"].strip(),
                permits=r["permits"].strip(), restricts=r["restricts"].strip(),
                restricted_link_patterns=tuple(p.strip().lower() for p in r["restricted_link_patterns"].split("|") if p.strip()),
                recorded_on=r["recorded_on"].strip(), evidence=r["evidence"].strip(),
                received_on=(r.get("received_on") or "").strip(),
                automated_collection=(r.get("automated_collection") or "NOT_ANSWERED").strip(),
                collection_limits=(r.get("collection_limits") or "").strip(),
                owner_decision=(r.get("owner_decision") or "").strip(),
            ))
        return out


def _bare(url: str) -> str:
    return re.sub(r"^https?://", "", url.strip().lower()).rstrip("/")


def _restricting_reply(url: str, replies: list[OfficeReply]) -> OfficeReply | None:
    u = url.lower()
    for r in replies:
        entries = {_bare(p[1:]) for p in r.restricted_link_patterns if p.startswith("!")}
        if _bare(u) in entries:
            continue
        if any(not p.startswith("!") and p in u for p in r.restricted_link_patterns):
            return r
    return None


def restricted_link_reason(url: str | None, replies: list[OfficeReply] | None = None) -> str | None:
    """Why `url` may not be offered as a customer link, or None. A URL is
    refused when it contains a fragment an office restricted in its reply
    (Palm Beach County Clerk: court-case deep links; Volusia Clerk: any page
    on app02.clerk.org other than the entry pages it names)."""
    if not url:
        return None
    r = _restricting_reply(url, load() if replies is None else replies)
    return f"{r.office} restricts this link ({r.restricts})" if r else None


def entry_link(url: str | None, replies: list[OfficeReply] | None = None) -> str | None:
    """The entry page an office asks links to go to, for a `url` it restricts
    (Volusia Clerk: https://app02.clerk.org/or_td/), else None."""
    if not url:
        return None
    r = _restricting_reply(url, load() if replies is None else replies)
    if r is None:
        return None
    for p in r.restricted_link_patterns:
        if p.startswith("!"):
            return "https://" + _bare(p[1:]) + "/"
    return None


def collection_limits_for(host: str, replies: list[OfficeReply] | None = None) -> tuple[int, float] | None:
    """(max requests per day, minimum seconds between requests) an office set
    for automated reading of `host`, or None when it set none."""
    h = (host or "").lower()
    for r in load() if replies is None else replies:
        lim = r.limits()
        if r.automated_collection == "PERMITTED_WITH_LIMITS" and lim.get("host", "").lower() == h:
            return int(lim["max_per_day"]), float(lim["min_interval_s"])
    return None


def problems(replies: list[OfficeReply] | None = None, records=None, authorizations=None,
             docs_text: str | None = None) -> list[str]:
    """Every disagreement between the register, the permission records and
    the authorization records; an empty list means consistent."""
    from . import authorization as A  # noqa: PLC0415
    from . import permissions as P  # noqa: PLC0415

    replies = load() if replies is None else replies
    records = P.load() if records is None else records
    auths = dict(A.PROVIDER_AUTHORIZATIONS) if authorizations is None else authorizations
    if docs_text is None:
        docs_text = DOCS.read_text(encoding="utf-8") if DOCS.exists() else ""
    out: list[str] = []
    for r in replies:
        tag = f"{r.office} ({r.county or r.state})"
        if r.question_answered not in QUESTIONS:
            out.append(f"{tag}: unknown question_answered {r.question_answered!r}")
        if r.commercial_use not in COMMERCIAL:
            out.append(f"{tag}: unknown commercial_use {r.commercial_use!r}")
        if r.automated_collection not in AUTOMATED:
            out.append(f"{tag}: unknown automated_collection {r.automated_collection!r}")
        if r.owner_decision not in OWNER_DECISIONS:
            out.append(f"{tag}: unknown owner_decision {r.owner_decision!r}")
        if r.question_answered != "COMMERCIAL_USE" and r.commercial_use != "NOT_ANSWERED":
            out.append(f"{tag}: a {r.question_answered} reply cannot settle commercial use")
        if not r.evidence or not r.recorded_on:
            out.append(f"{tag}: evidence and recorded_on are required")
        lim = r.limits()
        if (r.automated_collection == "PERMITTED_WITH_LIMITS") != bool(r.collection_limits):
            out.append(f"{tag}: collection_limits are given exactly when automation is PERMITTED_WITH_LIMITS")
        if r.collection_limits and not (lim.get("host") and lim.get("max_per_day", "").isdigit()
                                        and re.fullmatch(r"\d+(\.\d+)?", lim.get("min_interval_s", ""))):
            out.append(f"{tag}: collection_limits need host, max_per_day and min_interval_s")
        prohibits = (r.commercial_use == "PROHIBITED_WITHOUT_WRITTEN_AUTHORIZATION"
                     or r.automated_collection == "PROHIBITED")
        if r.pending and not prohibits:
            out.append(f"{tag}: an owner decision can be PENDING only on a prohibition")
        if r.pending and r.office not in docs_text:
            out.append(f"{tag}: a PENDING owner decision must be listed in docs/source-permissions.md")
        if r.authorization_id:
            a = auths.get(r.authorization_id)
            if a is None:
                out.append(f"{tag}: authorization.py holds no record {r.authorization_id!r}")
            else:
                if (a.county or "") != r.county or a.source_id not in r.source_ids:
                    out.append(f"{tag}: authorization {r.authorization_id} names {a.source_id}/{a.county}")
                if r.commercial_use != "PERMITTED" and a.scope.commercial_use.authorized:
                    out.append(f"{tag}: authorization {r.authorization_id} grants commercial use the reply did not")
                if r.automated_collection == "PROHIBITED" and a.scope.automated_access.authorized:
                    out.append(f"{tag}: authorization {r.authorization_id} grants automated access the reply refused")
        for src in r.source_ids:
            mine = [x for x in records if x.source_id == src and x.state == r.state
                    and (not r.county or x.county in (None, r.county)) and x.operation in REUSE_OPERATIONS]
            for x in mine:
                documented = x.status in P.DOCUMENTED_STATUSES
                restricted = x.status in ("RESTRICTED", "BLOCKED")
                if documented and r.commercial_use != "PERMITTED":
                    out.append(f"{tag}: {src}/{x.operation} recorded {x.status} although the reply did not permit "
                               f"commercial use ({r.commercial_use})")
                if documented and not r.authorization_id:
                    out.append(f"{tag}: {src}/{x.operation} recorded {x.status}, but a reply with no authorization "
                               f"record grants nothing")
                if documented and r.automated_collection == "PROHIBITED" and x.operation in COLLECTION_OPERATIONS:
                    out.append(f"{tag}: {src}/{x.operation} recorded {x.status} although the reply refused "
                               f"automated collection")
                if r.enforced_prohibition and not restricted:
                    out.append(f"{tag}: {src}/{x.operation} is {x.status}; the reply prohibits it without written "
                               f"authorization, so it must be RESTRICTED")
                if (r.automated_collection == "PROHIBITED" and not r.pending
                        and x.operation in COLLECTION_OPERATIONS and not restricted):
                    out.append(f"{tag}: {src}/{x.operation} is {x.status}; the reply prohibits automated "
                               f"collection, so it must be RESTRICTED")
    return out


def prohibits_reuse(source_id: str, state: str, county: str | None, replies: list[OfficeReply] | None = None) -> bool:
    """True when an office's reply prohibits collecting / reusing this
    source's records for this county without prior written authorization.
    The parity checks that keep every collected source collectable exempt
    exactly these, and nothing else. A prohibition whose owner decision is
    PENDING is recorded but not yet enforced, so it withholds nothing."""
    for r in replies if replies is not None else load():
        if (source_id in r.source_ids and r.state == state and r.county == county
                and r.enforced_prohibition):
            return True
    return False


def pending_decisions(replies: list[OfficeReply] | None = None) -> list[OfficeReply]:
    """Replies whose prohibition waits on the owner's decision."""
    return [r for r in (load() if replies is None else replies) if r.pending]
