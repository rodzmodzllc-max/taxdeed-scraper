#!/usr/bin/env python3
"""Source-published outcome ingestion for the AVAILABLE ledger (2026-09-30,
migration 023).

A RESULT (sold / redeemed / withdrawn ... with its date, amount and - where
the source publishes it AND publishing it is permitted - the party) is
stored only when the SOURCE published it and a verified rule says which
column carries what. Nothing is derived from absence, dates, bids or
counts; no "speculative mapping" exists.

  data/outcome_column_rules.csv      one row per (state, source_id, county,
                                     column_label) naming the field the
                                     column feeds (result_status /
                                     result_date / result_amount /
                                     result_party), whether it is enabled,
                                     when it was verified, the evidence, and
                                     for result_party whether publishing it
                                     is permitted. Ships EMPTY.

  outcomes_by_identity(records, rules)
                                     {(county, key): {result_status,
                                     result_date, result_amount,
                                     result_party, raw}} for the harvest
                                     records that carry `source_columns`
                                     (label -> cell text). With no enabled
                                     rule the result is {}.

The FL lists' own 'Sold To' column is the one source-published result the
pipeline already handles (harvest_laft_html / _pdfs write those rows'
IDENTITIES to out/harvest_laft_sold*.json and the writer marks them sold
with raw 'Sold To'). This module is how the date / amount / party of such
a result would be added - and only through a rule.
"""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
RULES_PATH = REPO / "data" / "outcome_column_rules.csv"
FIELDS = ("result_status", "result_date", "result_amount", "result_party")
RESULT_STATUSES = ("sold", "redeemed", "withdrawn", "cancelled", "struck_off")
RULE_COLUMNS = ["state", "source_id", "county", "column_label", "field", "result_status", "party_permitted",
                "enabled", "verified_on", "evidence", "notes"]
_TRUE = frozenset({"1", "true", "yes", "y"})
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@dataclass(frozen=True)
class OutcomeRule:
    state: str
    source_id: str
    county: str
    column_label: str
    field: str
    result_status: str          # for field result_status: the normalized status the column's presence means
    party_permitted: bool
    enabled: bool
    verified_on: str
    evidence: str
    notes: str = ""


def _norm(label: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", (label or "").lower())).strip()


def rule_problems(rule: OutcomeRule) -> list[str]:
    problems: list[str] = []
    if not re.match(r"^[A-Z]{2}$", rule.state):
        problems.append(f"state {rule.state!r}")
    if not rule.source_id:
        problems.append("source_id required")
    if not rule.column_label:
        problems.append("column_label required")
    if rule.field not in FIELDS:
        problems.append(f"field {rule.field!r}")
    if rule.field == "result_status" and rule.result_status not in RESULT_STATUSES:
        problems.append(f"result_status {rule.result_status!r} (one of {RESULT_STATUSES})")
    if rule.field != "result_status" and rule.result_status:
        problems.append("result_status only on a result_status rule")
    if rule.field == "result_party" and rule.enabled and not rule.party_permitted:
        problems.append("an enabled result_party rule must state party_permitted (the source publishes it and publishing it is permitted)")
    if rule.enabled and not (_DATE.match(rule.verified_on) and rule.evidence):
        problems.append("an enabled rule needs verified_on (YYYY-MM-DD) and evidence")
    return problems


def load_rules(path: Path | str = RULES_PATH) -> list[OutcomeRule]:
    p = Path(path)
    if not p.is_file():
        return []
    out: list[OutcomeRule] = []
    with open(p, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames != RULE_COLUMNS:
            raise ValueError(f"{p.name}: columns must be {RULE_COLUMNS}, got {reader.fieldnames}")
        for i, r in enumerate(reader, 2):
            rule = OutcomeRule(state=(r["state"] or "").strip(), source_id=(r["source_id"] or "").strip(),
                               county=(r["county"] or "").strip() or "*", column_label=(r["column_label"] or "").strip(),
                               field=(r["field"] or "").strip(), result_status=(r["result_status"] or "").strip(),
                               party_permitted=(r["party_permitted"] or "").strip().lower() in _TRUE,
                               enabled=(r["enabled"] or "").strip().lower() in _TRUE, verified_on=(r["verified_on"] or "").strip(),
                               evidence=(r["evidence"] or "").strip(), notes=(r["notes"] or "").strip())
            problems = rule_problems(rule)
            if problems:
                raise ValueError(f"{p.name} line {i}: " + "; ".join(problems))
            out.append(rule)
    return out


def parse_amount(text: str) -> float | None:
    m = re.search(r"\$?\s*([\d,]+(?:\.\d{1,2})?)", str(text or ""))
    if not m:
        return None
    try:
        v = float(m.group(1).replace(",", ""))
    except ValueError:
        return None
    return v if v >= 0 else None


def parse_date(text: str) -> str | None:
    s = str(text or "").strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def identity_of(record: dict) -> tuple[str, str] | None:
    county = str(record.get("county") or "").strip()
    key = str(record.get("case_no") or "").strip() or str(record.get("parcel") or "").strip()
    return (county, key) if county and key else None


def outcomes_by_identity(records: list[dict], rules: list[OutcomeRule], *, state: str, source_id: str) -> dict[tuple[str, str], dict]:
    """The results the enabled rules establish from each record's
    `source_columns` (label -> cell text). A record with no matching
    non-blank cell yields nothing; a party is carried only under an enabled
    result_party rule (which must say the publication is permitted)."""
    active = [r for r in rules if r.enabled and r.state == state and r.source_id == source_id]
    if not active:
        return {}
    out: dict[tuple[str, str], dict] = {}
    for rec in records:
        ident = identity_of(rec)
        cols = rec.get("source_columns") or {}
        if not ident or not isinstance(cols, dict):
            continue
        by_label = {_norm(k): str(v or "").strip() for k, v in cols.items()}
        result: dict = {}
        for rule in active:
            if rule.county not in ("*", ident[0]):
                continue
            cell = by_label.get(_norm(rule.column_label))
            if not cell:
                continue
            if rule.field == "result_status":
                result["result_status"] = rule.result_status
                result["raw"] = f"{rule.column_label}: {cell}" if rule.result_status != "sold" else rule.column_label
            elif rule.field == "result_date":
                d = parse_date(cell)
                if d:
                    result["result_date"] = d
            elif rule.field == "result_amount":
                a = parse_amount(cell)
                if a is not None:
                    result["result_amount"] = a
            elif rule.field == "result_party" and rule.party_permitted:
                result["result_party"] = cell
        if result.get("result_status"):
            out[ident] = result
    return out


def load_result_files(paths) -> dict[tuple[str, str], dict]:
    """Results a harvester already resolved and wrote beside its sold
    identities (keys result_status / result_date / result_amount /
    result_party on the identity rows). Identity-only rows (today's
    files) yield nothing here - the writer still marks them sold from
    the identity, as before."""
    import json
    out: dict[tuple[str, str], dict] = {}
    for p in paths:
        p = Path(p)
        if not p.is_file():
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except ValueError:
            continue
        for r in data if isinstance(data, list) else []:
            if not isinstance(r, dict):
                continue
            ident = identity_of(r)
            fields = {k: r[k] for k in ("result_date", "result_amount", "result_party") if r.get(k) not in (None, "")}
            if ident and fields:
                out[ident] = fields
    return out
