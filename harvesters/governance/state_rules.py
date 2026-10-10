"""State tax-sale rules and ledger support, as recorded evidence (2026-10-10).

Two version-controlled tables:

* ``data/state_rules.csv`` - one row per rule. ``kind`` keeps four kinds of
  information apart:

    LAW         state law or regulation (a statute that was read)
    PROCEDURE   a government procedure or county instruction (a page / document
                that was read)
    SOURCE      how a data source behaves (what it publishes, how it is read)
    UNRESOLVED  something not verified, not available, or in conflict

  ``status`` is VERIFIED / NOT_VERIFIED / NOT_PUBLISHED / NOT_APPLICABLE /
  NOT_YET_IMPLEMENTED / CONFLICT. A VERIFIED row must name its official source
  (https), a title, the date it was verified and the repository evidence of
  the read; a VERIFIED LAW row must also carry its citation. An UNRESOLVED
  row is never VERIFIED. ``county`` empty = statewide; a county row applies
  only to that county and never stands in for the state.

* ``data/state_ledgers.csv`` - for each state and each of the three ledgers,
  TRACKED / NOT_TRACKED / NOT_OFFERED / NOT_VERIFIED with a plain note.
  NOT_OFFERED (the state has no such product) needs evidence; none is
  claimed today.

Nothing here reaches the network. ``validate()`` returns the problems; the
verification engine (``state_verification.py``) and the tests refuse any.
"""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass, fields
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
RULES_PATH = REPO / "data" / "state_rules.csv"
LEDGERS_PATH = REPO / "data" / "state_ledgers.csv"

KINDS = ("LAW", "PROCEDURE", "SOURCE", "UNRESOLVED")
KIND_LABELS = {"LAW": "State law", "PROCEDURE": "Government procedure", "SOURCE": "Source behaviour",
               "UNRESOLVED": "Unresolved"}
STATUSES = ("VERIFIED", "NOT_VERIFIED", "NOT_PUBLISHED", "NOT_APPLICABLE", "NOT_YET_IMPLEMENTED", "CONFLICT")
STATUS_LABELS = {"VERIFIED": "Verified", "NOT_VERIFIED": "Not verified", "NOT_PUBLISHED": "Not published",
                 "NOT_APPLICABLE": "Not applicable", "NOT_YET_IMPLEMENTED": "Not yet implemented",
                 "CONFLICT": "Sources conflict"}
LEDGERS = ("AUCTIONS", "AVAILABLE", "LIENS_CERTIFICATES")
LEDGER_STATUSES = ("TRACKED", "NOT_TRACKED", "NOT_OFFERED", "NOT_VERIFIED")
LEDGER_STATUS_LABELS = {"TRACKED": "Tracked", "NOT_TRACKED": "Not tracked by TAXACQ",
                        "NOT_OFFERED": "Not offered by this state", "NOT_VERIFIED": "Not verified"}
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@dataclass(frozen=True)
class Rule:
    state: str
    county: str
    topic: str
    kind: str
    status: str
    statement: str
    source_url: str
    source_title: str
    citation: str
    effective_date: str
    verified_on: str
    evidence: str
    ambiguity: str

    @property
    def scope(self) -> str:
        return "county" if self.county else "statewide"

    def as_dict(self) -> dict:
        d = {f.name: getattr(self, f.name) for f in fields(self)}
        d["scope"] = self.scope
        return {k: v for k, v in d.items() if v != ""}


@dataclass(frozen=True)
class LedgerSupport:
    state: str
    ledger: str
    status: str
    note: str
    evidence: str


def load_rules(path: Path = RULES_PATH) -> list[Rule]:
    with open(path, newline="", encoding="utf-8") as fh:
        return [Rule(**{f.name: (r.get(f.name) or "").strip() for f in fields(Rule)}) for r in csv.DictReader(fh)]


def load_ledgers(path: Path = LEDGERS_PATH) -> list[LedgerSupport]:
    with open(path, newline="", encoding="utf-8") as fh:
        return [LedgerSupport(**{f.name: (r.get(f.name) or "").strip() for f in fields(LedgerSupport)})
                for r in csv.DictReader(fh)]


def rule_problems(r: Rule) -> list[str]:
    p = []
    where = f"{r.state}/{r.county or '-'}/{r.topic}"
    if r.kind not in KINDS:
        p.append(f"{where}: kind {r.kind!r}")
    if r.status not in STATUSES:
        p.append(f"{where}: status {r.status!r}")
    if not r.statement:
        p.append(f"{where}: no statement")
    if r.source_url and not r.source_url.startswith("https://"):
        p.append(f"{where}: source_url must be https")
    if r.kind == "UNRESOLVED" and r.status == "VERIFIED":
        p.append(f"{where}: an UNRESOLVED row is never VERIFIED")
    if r.status == "VERIFIED":
        if not (r.source_url and r.source_title and r.evidence):
            p.append(f"{where}: VERIFIED needs source_url, source_title and evidence")
        if not _DATE.match(r.verified_on):
            p.append(f"{where}: VERIFIED needs verified_on (YYYY-MM-DD)")
        if r.kind == "LAW" and not r.citation:
            p.append(f"{where}: a VERIFIED LAW row needs its citation")
        if "lead only" in r.citation:
            p.append(f"{where}: a 'lead only' citation is never VERIFIED")
    else:
        if r.verified_on:
            p.append(f"{where}: verified_on is set on a {r.status} row - only a verified row has a verification date")
    if r.status == "CONFLICT" and not r.ambiguity:
        p.append(f"{where}: a CONFLICT row must describe the conflict")
    return p


def validate(rules: list[Rule] | None = None, ledgers: list[LedgerSupport] | None = None) -> list[str]:
    rules = load_rules() if rules is None else rules
    ledgers = load_ledgers() if ledgers is None else ledgers
    p = [x for r in rules for x in rule_problems(r)]
    seen = set()
    for r in rules:
        key = (r.state, r.county, r.topic)
        if key in seen:
            p.append(f"{r.state}/{r.county or '-'}/{r.topic}: duplicate rule key")
        seen.add(key)
    lseen = set()
    for l in ledgers:
        if l.ledger not in LEDGERS:
            p.append(f"{l.state}: ledger {l.ledger!r}")
        if l.status not in LEDGER_STATUSES:
            p.append(f"{l.state}/{l.ledger}: ledger status {l.status!r}")
        if l.status == "NOT_OFFERED" and not l.evidence:
            p.append(f"{l.state}/{l.ledger}: NOT_OFFERED needs evidence that the state has no such product")
        if not l.note:
            p.append(f"{l.state}/{l.ledger}: no note")
        if (l.state, l.ledger) in lseen:
            p.append(f"{l.state}/{l.ledger}: duplicate")
        lseen.add((l.state, l.ledger))
    return p


def rules_for(state: str, county: str = "", rules: list[Rule] | None = None) -> list[Rule]:
    """The rules that apply to (state, county): every statewide rule, plus that
    county's own rules. A county rule REPLACES a statewide rule of the same
    topic for that county only; another county never sees it."""
    rules = load_rules() if rules is None else rules
    statewide = {r.topic: r for r in rules if r.state == state and not r.county}
    own = {r.topic: r for r in rules if r.state == state and county and r.county == county}
    merged = dict(statewide)
    merged.update(own)
    return [merged[t] for t in sorted(merged)]


def ledger_support(state: str, ledgers: list[LedgerSupport] | None = None) -> dict[str, LedgerSupport]:
    ledgers = load_ledgers() if ledgers is None else ledgers
    return {l.ledger: l for l in ledgers if l.state == state}
