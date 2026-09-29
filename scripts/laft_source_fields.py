#!/usr/bin/env python3
"""Carry the fields a Florida LAFT harvester already reads off the county's
own list into public.properties - fill-blank only, with per-column
provenance - so a list-published legal description, name in which
assessed, assessed value, certificate number, homestead flag, escheatment
date or availability date is no longer dropped on the floor by
scripts/sync-laft-to-supabase.ps1 (which sends only the identity/price/
link columns and uses legal_desc merely as an address fallback).

This is a reusable mechanism, not a backfill: it runs inside
scripts/laft_lifecycle.py on every laft job, on exactly the rows that job
OBSERVED (a harvested row whose county is COMPLETE or INCOMPLETE this run -
the same gate the lifecycle uses for last_seen_at). Nothing is inferred:
every value is the county's own cell, parsed deterministically, and every
write records where it came from in field_provenance
(scripts/field_provenance.py).

MATCHING is by row identity only - (state, source='laft', county, case_no),
the sync's own upsert key - never by address, never across counties or
states, never fuzzy. A harvested row with no database row is UNMATCHED and
untouched; a key that resolves to more than one database row is AMBIGUOUS
and untouched.

VALUE RULES (a value that fails its rule is SKIPPED - never coerced):
  legal_desc, owner_name, certificate_no   non-blank text, whitespace collapsed
  assessed                                  parses as a positive number
  homestead                                 the cell says yes -> True; anything
                                            else writes NOTHING (never False)
  escheatment_date, available_date          MM/DD/YYYY, M/D/YYYY or YYYY-MM-DD;
                                            columns exist only after migration
                                            019 and are written only when the
                                            database has them

A column that already holds a value is left alone (fill-blank), whatever
the source of that value - the tax roll's legal description, a hand-
researched owner, a value this mechanism wrote last run. Counts of
matched / written / skipped / unmatched / ambiguous / unparseable /
errored rows are reported; no row value ever appears in the log.

Standard library only.
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from field_provenance import is_blank, merge_field_provenance, provenance_entry  # noqa: E402

SOURCE = "county_list"

# column -> harvest key. Same names on both sides today; the mapping exists
# so a harvester rename never silently detaches a column. HARVEST_KEY_ALIASES
# names the OTHER keys a harvester may use for the same list cell: the
# Pioneer/TaxSmartWeb grid ("Owners"), Osceola's NewVision API (last_name)
# and St. Lucie's AcclaimWeb grid ("Property Owners") all emit the owner of
# record under `owners`, which this carry silently ignored until 2026-09-29.
# The first key with a non-blank value wins; nothing is merged or guessed.
BASE_COLUMNS = {
    "legal_desc": "legal_desc",
    "owner_name": "owner_name",
    "assessed": "assessed",
    "certificate_no": "certificate_no",
    "homestead": "homestead",
}
# Migration 019 (scripts/migrations/019_laft_list_dates.sql). Probed at run
# time; absent columns are never sent.
OPTIONAL_COLUMNS = {
    "escheatment_date": "escheatment_date",
    "available_date": "available_date",
}
ALL_COLUMNS = {**BASE_COLUMNS, **OPTIONAL_COLUMNS}
HARVEST_KEY_ALIASES = {
    "owner_name": ("owner_name", "owners"),
}


def harvest_value(row: dict, column: str):
    """The harvested cell for `column`: the mapped key, then its aliases,
    first non-blank wins."""
    for key in HARVEST_KEY_ALIASES.get(column, (ALL_COLUMNS[column],)):
        value = row.get(key)
        if not is_blank(value):
            return value
    return None


_NUM_RE = re.compile(r"^\d+(\.\d+)?$")
_YES = frozenset({"y", "yes", "true", "x", "hx", "homestead", "homestead exemption"})
# Every format a Florida list has been seen to publish a date in. Each is an
# unambiguous, complete calendar date; a two-digit year (%y) is accepted only
# in the slash form the clerks use ("07/01/29") and strptime pins it to
# 1969-2068. A cell that fits none of these is UNPARSEABLE, never coerced.
_DATE_FORMATS = ("%m/%d/%Y", "%Y-%m-%d", "%m-%d-%Y", "%m/%d/%y",
                 "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%m/%d/%Y %H:%M:%S", "%m/%d/%Y %I:%M:%S %p",
                 "%B %d, %Y", "%b %d, %Y", "%B %d %Y", "%b %d %Y", "%d-%b-%Y", "%d-%b-%y")


def parse_text(raw) -> str | None:
    if is_blank(raw):
        return None
    text = re.sub(r"\s+", " ", str(raw)).strip()
    return text or None


def parse_positive_number(raw) -> float | None:
    if is_blank(raw):
        return None
    cleaned = re.sub(r"[^0-9.]", "", str(raw))
    if not _NUM_RE.match(cleaned):
        return None
    value = float(cleaned)
    return value if value > 0 else None


def parse_yes(raw) -> bool | None:
    """True only when the cell affirmatively says so; None otherwise. A
    'N', blank or unknown token never becomes False - the column already
    carries a value on every row and this mechanism is fill-blank."""
    if is_blank(raw):
        return None
    if raw is True:
        return True
    return True if str(raw).strip().lower() in _YES else None


def parse_date(raw) -> str | None:
    if is_blank(raw):
        return None
    text = re.sub(r"\s+", " ", str(raw)).strip()
    # An ISO timestamp with fractional seconds / zone (Osceola, St. Lucie
    # style "2025-04-22T00:00:00.000Z") carries its date in the first ten
    # characters; only that exact shape is trimmed.
    if re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:?\d{2})?$", text):
        text = text[:10]
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return None


PARSERS = {
    "legal_desc": parse_text,
    "owner_name": parse_text,
    "certificate_no": parse_text,
    "assessed": parse_positive_number,
    "homestead": parse_yes,
    "escheatment_date": parse_date,
    "available_date": parse_date,
}


def column_present(column: str, value) -> bool:
    """Does the database row already hold a value for this column?
    homestead is a NOT NULL boolean whose False is the default, so only
    True counts as present there."""
    if column == "homestead":
        return value is True
    return not is_blank(value)


@dataclass
class Counters:
    matched: int = 0
    unmatched: int = 0
    ambiguous: int = 0
    written_rows: int = 0
    nothing_to_write: int = 0
    errored: int = 0
    fields_written: dict = field(default_factory=dict)
    skipped_present: dict = field(default_factory=dict)
    unparseable: dict = field(default_factory=dict)

    def bump(self, bucket: str, column: str) -> None:
        d = getattr(self, bucket)
        d[column] = d.get(column, 0) + 1

    def to_json(self) -> dict:
        return {
            "matched": self.matched, "unmatched": self.unmatched, "ambiguous": self.ambiguous,
            "written_rows": self.written_rows, "nothing_to_write": self.nothing_to_write, "errored": self.errored,
            "fields_written": dict(sorted(self.fields_written.items())),
            "skipped_present": dict(sorted(self.skipped_present.items())),
            "unparseable": dict(sorted(self.unparseable.items())),
        }


@dataclass
class RowUpdate:
    id: str
    county: str
    case_no: str
    fields: dict
    existing_provenance: object = None


def index_db_rows(db_rows: list[dict]) -> dict[tuple[str, str], list[dict]]:
    index: dict[tuple[str, str], list[dict]] = {}
    for r in db_rows:
        key = (str(r.get("county")), str(r.get("case_no")))
        index.setdefault(key, []).append(r)
    return index


def plan_source_fields(observed: dict[str, dict[str, dict]], db_rows: list[dict], columns) -> tuple[list[RowUpdate], Counters]:
    """observed: county -> case_no -> harvested row (scripts/laft_lifecycle.py's
    observed_by_county, already restricted to COMPLETE/INCOMPLETE counties).
    db_rows: the state's laft rows for those counties, carrying id, county,
    case_no, every column in `columns` and field_provenance.
    columns: the database columns available to write this run."""
    counters = Counters()
    index = index_db_rows(db_rows)
    updates: list[RowUpdate] = []
    wanted = [c for c in ALL_COLUMNS if c in set(columns)]
    for county in sorted(observed):
        for case_no in sorted(observed[county]):
            row = observed[county][case_no]
            matches = index.get((county, case_no), [])
            if not matches:
                counters.unmatched += 1
                continue
            if len(matches) > 1:
                counters.ambiguous += 1
                continue
            db = matches[0]
            counters.matched += 1
            fields: dict = {}
            for column in wanted:
                raw = harvest_value(row, column)
                if is_blank(raw):
                    continue
                value = PARSERS[column](raw)
                if value is None:
                    # A homestead cell that does not say yes ("N", "No") is
                    # nothing to write, not a parse failure.
                    if column != "homestead":
                        counters.bump("unparseable", column)
                    continue
                if column_present(column, db.get(column)):
                    counters.bump("skipped_present", column)
                    continue
                fields[column] = value
            if not fields:
                counters.nothing_to_write += 1
                continue
            updates.append(RowUpdate(id=str(db.get("id")), county=county, case_no=case_no, fields=fields,
                                     existing_provenance=db.get("field_provenance")))
    return updates, counters


def provenance_for(gate: dict, retrieved_at: str) -> dict:
    entry = (gate or {}).get("entry") or {}
    return provenance_entry(
        SOURCE,
        recorded_at=retrieved_at,
        source_id=entry.get("source_id") or (gate or {}).get("harvester"),
        list_url=entry.get("source_url"),
        document_url=entry.get("document_url"),
        document_sha256=entry.get("document_sha256"),
        list_as_of=entry.get("list_as_of"),
        retrieved_at=entry.get("checked_at") or retrieved_at,
    )


def patch_body(update: RowUpdate, gate: dict, retrieved_at: str) -> dict:
    prov = provenance_for(gate, retrieved_at)
    body = dict(update.fields)
    body["field_provenance"] = merge_field_provenance(update.existing_provenance, {c: dict(prov) for c in update.fields})
    return body


def execute_source_fields(api, updates: list[RowUpdate], gates: dict[str, dict], retrieved_at: str, counters: Counters) -> Counters:
    """One PATCH per row (id=eq.<id>) - a row's fill-blank set is its own.
    `api` is scripts/laft_lifecycle.py's Api (patch(query, body)); its
    dry_run flag makes patch() a no-op, so a dry run still counts what it
    WOULD write."""
    for update in updates:
        body = patch_body(update, gates.get(update.county, {}), retrieved_at)
        try:
            api.patch(f"id=eq.{update.id}", body)
        except Exception as exc:  # noqa: BLE001 - one row's failure must not abort the run
            counters.errored += 1
            print(f"::warning title=laft_source_fields::PATCH failed for one {update.county} row ({type(exc).__name__})")
            continue
        counters.written_rows += 1
        for column in update.fields:
            counters.bump("fields_written", column)
    return counters


def summarize(counters: Counters, columns) -> str:
    c = counters
    lines = ["LAFT source fields (county list -> properties, fill-blank):",
             f"  columns available: {', '.join(sorted(set(columns)))}",
             f"  matched {c.matched}, unmatched {c.unmatched}, ambiguous {c.ambiguous}, "
             f"rows written {c.written_rows}, nothing to write {c.nothing_to_write}, errored {c.errored}"]
    if c.fields_written:
        lines.append("  fields written: " + ", ".join(f"{k} {v}" for k, v in sorted(c.fields_written.items())))
    if c.skipped_present:
        lines.append("  skipped (already had a value): " + ", ".join(f"{k} {v}" for k, v in sorted(c.skipped_present.items())))
    if c.unparseable:
        lines.append("  skipped (cell did not parse): " + ", ".join(f"{k} {v}" for k, v in sorted(c.unparseable.items())))
    return "\n".join(lines)
