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
  claimed today. Since 2026-10-10 each row also carries the ledger's
  ELIGIBILITY - whether the product exists in that state, decided apart
  from whether TAXACQ tracks it and apart from any count:

    OFFERED            authoritative evidence (a statute read) establishes the product statewide
    NOT_OFFERED        authoritative evidence establishes the state has no such product
    COUNTY_DEPENDENT   the product is established county by county (a county's own published
                       list or procedure was read); other counties are not claimed
    NOT_VERIFIED       the evidence is insufficient to decide either way
    SOURCE_RESTRICTED  the only relevant source cannot be used under the approved access rules

  OFFERED / NOT_OFFERED / COUNTY_DEPENDENT need a basis, an https source and a
  verification date; NOT_VERIFIED / SOURCE_RESTRICTED carry no date. Every
  row has ``meaning`` (what the ledger represents in that state) and, where
  known, ``office`` (the responsible government office).

* ``data/state_rules_history.csv`` - append-only: one row per superseded
  version of a rule (its prior status and statement, what changed, what
  depends on it). A rule's ``version`` is 1 + the number of its history rows.

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
ELIGIBILITIES = ("OFFERED", "NOT_OFFERED", "COUNTY_DEPENDENT", "NOT_VERIFIED", "SOURCE_RESTRICTED")
ELIGIBILITY_LABELS = {"OFFERED": "Offered in this state", "NOT_OFFERED": "Not offered in this state",
                      "COUNTY_DEPENDENT": "Offered county by county", "NOT_VERIFIED": "Not verified",
                      "SOURCE_RESTRICTED": "Source restricted"}
EVIDENCED_ELIGIBILITIES = ("OFFERED", "NOT_OFFERED", "COUNTY_DEPENDENT")
RULE_LEDGERS = LEDGERS + ("ALL",)
IMPLEMENTATION_STATUSES = ("IMPLEMENTED", "DISPLAY_ONLY", "NOT_IMPLEMENTED", "NOT_APPLICABLE")
HISTORY_PATH = REPO / "data" / "state_rules_history.csv"
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
    # 2026-10-10: which ledger the rule governs (or ALL), the responsible
    # office, the source ids it concerns, what code or customer behaviour
    # depends on it, how far it is implemented, the test that pins it, and
    # its version (1 + the rule's history rows) with the date of that version.
    ledger: str = "ALL"
    office: str = ""
    related_sources: str = ""
    depends_on: str = ""
    implementation_status: str = "DISPLAY_ONLY"
    test_ref: str = ""
    version: str = "1"
    changed_on: str = ""

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.state, self.county, self.topic)

    @property
    def ledgers(self) -> tuple[str, ...]:
        """The ledgers the rule governs ('ALL' = every ledger)."""
        parts = tuple(x for x in self.ledger.split("|") if x)
        return LEDGERS if "ALL" in parts else parts

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
    eligibility: str = "NOT_VERIFIED"
    eligibility_basis: str = ""
    eligibility_source_url: str = ""
    eligibility_verified_on: str = ""
    meaning: str = ""
    office: str = ""

    def as_dict(self) -> dict:
        return {f.name: getattr(self, f.name) for f in fields(self) if getattr(self, f.name) != ""}


@dataclass(frozen=True)
class RuleHistory:
    state: str
    county: str
    topic: str
    version: str
    changed_on: str
    change: str
    prior_status: str
    prior_statement: str
    affects: str

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.state, self.county, self.topic)


def load_rules(path: Path = RULES_PATH) -> list[Rule]:
    with open(path, newline="", encoding="utf-8") as fh:
        return [Rule(**{f.name: (r.get(f.name) or "").strip() for f in fields(Rule)}) for r in csv.DictReader(fh)]


def load_ledgers(path: Path = LEDGERS_PATH) -> list[LedgerSupport]:
    with open(path, newline="", encoding="utf-8") as fh:
        return [LedgerSupport(**{f.name: (r.get(f.name) or "").strip() for f in fields(LedgerSupport)})
                for r in csv.DictReader(fh)]


def load_history(path: Path = HISTORY_PATH) -> list[RuleHistory]:
    if not path.is_file():
        return []
    with open(path, newline="", encoding="utf-8") as fh:
        return [RuleHistory(**{f.name: (r.get(f.name) or "").strip() for f in fields(RuleHistory)}) for r in csv.DictReader(fh)]


def rule_problems(r: Rule) -> list[str]:
    p = []
    where = f"{r.state}/{r.county or '-'}/{r.topic}"
    if r.kind not in KINDS:
        p.append(f"{where}: kind {r.kind!r}")
    if not r.ledger or any(x not in RULE_LEDGERS for x in r.ledger.split("|")):
        p.append(f"{where}: ledger {r.ledger!r} (AUCTIONS / AVAILABLE / LIENS_CERTIFICATES, '|'-joined, or ALL)")
    if r.implementation_status not in IMPLEMENTATION_STATUSES:
        p.append(f"{where}: implementation_status {r.implementation_status!r}")
    if r.implementation_status == "IMPLEMENTED" and not (r.depends_on and r.test_ref):
        p.append(f"{where}: an IMPLEMENTED rule names what depends on it and the test that pins it")
    if not r.version.isdigit() or int(r.version) < 1:
        p.append(f"{where}: version {r.version!r}")
    if not _DATE.match(r.changed_on):
        p.append(f"{where}: changed_on (YYYY-MM-DD) is required")
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


def ledger_problems(l: LedgerSupport) -> list[str]:
    p = []
    where = f"{l.state}/{l.ledger}"
    if l.ledger not in LEDGERS:
        p.append(f"{l.state}: ledger {l.ledger!r}")
    if l.status not in LEDGER_STATUSES:
        p.append(f"{where}: ledger status {l.status!r}")
    if l.status == "NOT_OFFERED" and not l.evidence:
        p.append(f"{where}: NOT_OFFERED needs evidence that the state has no such product")
    if not l.note:
        p.append(f"{where}: no note")
    if l.eligibility not in ELIGIBILITIES:
        p.append(f"{where}: eligibility {l.eligibility!r}")
    if not l.eligibility_basis:
        p.append(f"{where}: eligibility needs its basis")
    if not l.meaning:
        p.append(f"{where}: meaning (what this ledger represents here) is required")
    if l.eligibility in EVIDENCED_ELIGIBILITIES:
        if not l.eligibility_source_url.startswith("https://"):
            p.append(f"{where}: {l.eligibility} needs an https eligibility_source_url")
        if not _DATE.match(l.eligibility_verified_on):
            p.append(f"{where}: {l.eligibility} needs eligibility_verified_on (YYYY-MM-DD)")
    else:
        if l.eligibility_verified_on:
            p.append(f"{where}: {l.eligibility} carries no verification date")
    if l.eligibility == "NOT_OFFERED" and l.status == "TRACKED":
        p.append(f"{where}: a product the state does not offer cannot be TRACKED")
    if l.status == "NOT_OFFERED" and l.eligibility != "NOT_OFFERED":
        p.append(f"{where}: status NOT_OFFERED needs eligibility NOT_OFFERED")
    return p


def history_problems(rules: list[Rule], history: list[RuleHistory]) -> list[str]:
    """Versions are contiguous: a rule at version N has history rows 1..N-1,
    each dated, each with its prior statement and the change; a history row
    never names a rule that does not exist."""
    p = []
    by_key: dict[tuple, list[RuleHistory]] = {}
    for h in history:
        by_key.setdefault(h.key, []).append(h)
        where = f"{h.state}/{h.county or '-'}/{h.topic} v{h.version}"
        if not h.version.isdigit():
            p.append(f"{where}: version")
        if not _DATE.match(h.changed_on):
            p.append(f"{where}: changed_on (YYYY-MM-DD)")
        if not (h.change and h.prior_statement and h.prior_status in STATUSES):
            p.append(f"{where}: a history row records the change, the prior statement and the prior status")
    keys = {r.key for r in rules}
    for k, rows in by_key.items():
        if k not in keys:
            p.append(f"{k[0]}/{k[1] or '-'}/{k[2]}: history for a rule that does not exist")
    for r in rules:
        rows = by_key.get(r.key, [])
        want = list(range(1, int(r.version) if r.version.isdigit() else 1))
        have = sorted(int(h.version) for h in rows if h.version.isdigit())
        if have != want:
            p.append(f"{r.state}/{r.county or '-'}/{r.topic}: version {r.version} needs history rows {want}, has {have}")
    return p


def validate(rules: list[Rule] | None = None, ledgers: list[LedgerSupport] | None = None,
             history: list[RuleHistory] | None = None) -> list[str]:
    rules = load_rules() if rules is None else rules
    ledgers = load_ledgers() if ledgers is None else ledgers
    history = load_history() if history is None else history
    p = [x for r in rules for x in rule_problems(r)]
    seen = set()
    for r in rules:
        key = (r.state, r.county, r.topic)
        if key in seen:
            p.append(f"{r.state}/{r.county or '-'}/{r.topic}: duplicate rule key")
        seen.add(key)
    lseen = set()
    for l in ledgers:
        p.extend(ledger_problems(l))
        if (l.state, l.ledger) in lseen:
            p.append(f"{l.state}/{l.ledger}: duplicate")
        lseen.add((l.state, l.ledger))
    p.extend(history_problems(rules, history))
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
