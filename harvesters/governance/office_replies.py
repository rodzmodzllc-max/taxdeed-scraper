"""Replies from county offices about using their records (2026-11-04).

data/office_replies.csv lists each reply the product owner has received,
with the question it actually answered. The register exists because a reply
is easy to over-read:

  * a public link, or permission to link, is not permission to collect the
    records or to reuse them commercially;
  * a reply that only routes a records request, or only says what is
    technically acceptable, has not answered the commercial-use question.

question_answered: ROUTING_ONLY | TECHNICAL_ONLY | COMMERCIAL_USE
commercial_use:    PERMITTED | PROHIBITED_WITHOUT_WRITTEN_AUTHORIZATION | NOT_ANSWERED
restricted_link_patterns: "|"-separated, lower-case URL fragments the office
    restricts as links (e.g. court-case deep links); never offered to a
    customer as a link (restricted_link_reason()).

problems() is the consistency check a test runs: the register must agree with
data/source_permissions.csv and harvesters/governance/authorization.py.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
REPLIES_CSV = REPO / "data" / "office_replies.csv"

QUESTIONS = ("ROUTING_ONLY", "TECHNICAL_ONLY", "COMMERCIAL_USE")
COMMERCIAL = ("PERMITTED", "PROHIBITED_WITHOUT_WRITTEN_AUTHORIZATION", "NOT_ANSWERED")
# Operations that put an office's records into the product. A reply that did
# not answer the commercial-use question can never back a DOCUMENTED record
# for any of them; a reply that prohibits commercial use requires them denied.
REUSE_OPERATIONS = ("fetch", "parse", "store", "display", "enrich", "redistribute")


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
            ))
        return out


def restricted_link_reason(url: str | None, replies: list[OfficeReply] | None = None) -> str | None:
    """Why `url` may not be offered as a customer link, or None. A URL is
    refused when it contains a fragment an office restricted in its reply
    (Palm Beach County Clerk: court-case deep links)."""
    if not url:
        return None
    u = url.lower()
    for r in replies if replies is not None else load():
        for pat in r.restricted_link_patterns:
            if pat in u:
                return f"{r.office} restricts this link ({r.restricts})"
    return None


def problems(replies: list[OfficeReply] | None = None, records=None, authorizations=None) -> list[str]:
    """Every disagreement between the register, the permission records and
    the authorization records; an empty list means consistent."""
    from . import authorization as A  # noqa: PLC0415
    from . import permissions as P  # noqa: PLC0415

    replies = load() if replies is None else replies
    records = P.load() if records is None else records
    auths = dict(A.PROVIDER_AUTHORIZATIONS) if authorizations is None else authorizations
    out: list[str] = []
    for r in replies:
        tag = f"{r.office} ({r.county})"
        if r.question_answered not in QUESTIONS:
            out.append(f"{tag}: unknown question_answered {r.question_answered!r}")
        if r.commercial_use not in COMMERCIAL:
            out.append(f"{tag}: unknown commercial_use {r.commercial_use!r}")
        if r.question_answered != "COMMERCIAL_USE" and r.commercial_use != "NOT_ANSWERED":
            out.append(f"{tag}: a {r.question_answered} reply cannot settle commercial use")
        if not r.evidence or not r.recorded_on:
            out.append(f"{tag}: evidence and recorded_on are required")
        a = auths.get(r.authorization_id)
        if a is None:
            out.append(f"{tag}: authorization.py holds no record {r.authorization_id!r}")
        else:
            if a.county != r.county or a.source_id not in r.source_ids:
                out.append(f"{tag}: authorization {r.authorization_id} names {a.source_id}/{a.county}")
            if r.commercial_use != "PERMITTED" and a.scope.commercial_use.authorized:
                out.append(f"{tag}: authorization {r.authorization_id} grants commercial use the reply did not")
        for src in r.source_ids:
            mine = [x for x in records if x.source_id == src and x.state == r.state
                    and x.county in (None, r.county) and x.operation in REUSE_OPERATIONS]
            for x in mine:
                documented = x.status in P.DOCUMENTED_STATUSES
                if documented and r.commercial_use != "PERMITTED":
                    out.append(f"{tag}: {src}/{x.operation} recorded {x.status} although the reply did not permit "
                               f"commercial use ({r.commercial_use})")
                if (r.commercial_use == "PROHIBITED_WITHOUT_WRITTEN_AUTHORIZATION"
                        and x.status not in ("RESTRICTED", "BLOCKED")):
                    out.append(f"{tag}: {src}/{x.operation} is {x.status}; the reply prohibits it without written "
                               f"authorization, so it must be RESTRICTED")
    return out


def prohibits_reuse(source_id: str, state: str, county: str | None, replies: list[OfficeReply] | None = None) -> bool:
    """True when an office's reply prohibits collecting / reusing this
    source's records for this county without prior written authorization.
    The parity checks that keep every collected source collectable exempt
    exactly these, and nothing else."""
    for r in replies if replies is not None else load():
        if (source_id in r.source_ids and r.state == state and r.county == county
                and r.commercial_use == "PROHIBITED_WITHOUT_WRITTEN_AUTHORIZATION"):
            return True
    return False
