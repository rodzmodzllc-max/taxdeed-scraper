"""Per-ledger source health: what a reader may conclude from a status entry
(2026-10-13).

Every harvester records one entry per (source, county) read in its own
status file (scripts/laft_status.py StatusRecorder: COMPLETE / EMPTY /
INCOMPLETE / FAILED). The WRITER enforces that an EMPTY carries an
explicit empty signal; this module is the READER's check, applied wherever
a status file decides whether absent rows may be closed:

  * EMPTY counts only with row_count 0, an empty signal, and a read that
    did not fail at transport or parse - otherwise it is INCOMPLETE. A zero
    from a broken read is never "the county lists nothing".
  * COMPLETE counts only with a read that did not fail at transport or
    parse - otherwise INCOMPLETE.
  * FAILED with a transport / proxy / access category is SOURCE_UNAVAILABLE
    (it closes nothing, exactly like FAILED).
  * Anything unrecognised is NOT_RUN.

Ledger isolation: `ledger_units()` keeps an entry only when its source
feeds the ledger asked for; an entry that names no source (a legacy
single-source file) is the county fallback for that file ONLY - never a
stand-in for another source's or another ledger's read of the same county.
`closeable()` is each ledger's close-out rule.

Pure: reads dicts, never a file or the network.
"""
from __future__ import annotations

from . import Ledger, ledgers_for_source_id

__all__ = ["READER_STATES", "CLOSEABLE", "UNAVAILABLE_PREFIXES", "reader_status", "ledger_units", "unit_status",
           "closeable"]

READER_STATES = ("COMPLETE", "EMPTY", "INCOMPLETE", "FAILED", "SOURCE_UNAVAILABLE", "NOT_RUN")
UNAVAILABLE_PREFIXES = ("TRANSPORT_", "PROXY_", "ACCESS_")

# The only read states after which a ledger may close a row its read no
# longer lists (the domains' own gates, harvesters/ledgers/domains.py).
CLOSEABLE = {
    Ledger.AUCTIONS: frozenset({"COMPLETE", "EMPTY"}),
    Ledger.AVAILABLE: frozenset({"COMPLETE", "EMPTY"}),
    Ledger.LIENS_CERTIFICATES: frozenset({"COMPLETE", "EMPTY"}),
}


def _false(v) -> bool:
    return v is False or (isinstance(v, str) and v.strip().lower() == "false")


def reader_status(entry: dict) -> str:
    """The status a reader may act on for one entry (see the module docstring)."""
    recorded = str(entry.get("status") or "").strip().upper()
    broken = _false(entry.get("transport_ok")) or _false(entry.get("parse_ok"))
    if recorded == "EMPTY":
        try:
            # The PowerShell harvesters spell it rowCount; laft_status row_count.
            rows = int(entry.get("row_count", entry.get("rowCount")) or 0)
        except (TypeError, ValueError):
            rows = -1
        signal = entry.get("empty_signal") or entry.get("empty_marker_observed")
        return "EMPTY" if rows == 0 and signal and not broken else "INCOMPLETE"
    if recorded == "COMPLETE":
        return "INCOMPLETE" if broken else "COMPLETE"
    if recorded == "FAILED":
        cat = str(entry.get("error_category") or "")
        return "SOURCE_UNAVAILABLE" if cat.startswith(UNAVAILABLE_PREFIXES) else "FAILED"
    if recorded in ("INCOMPLETE", "SOURCE_UNAVAILABLE"):
        return recorded
    return "NOT_RUN"


_WORST = ("FAILED", "SOURCE_UNAVAILABLE", "NOT_RUN", "INCOMPLETE", "COMPLETE", "EMPTY")


def _worse(a: str | None, b: str) -> str:
    if a is None:
        return b
    return a if _WORST.index(a) <= _WORST.index(b) else b


def ledger_units(entries: list[dict], ledger: Ledger | None = None) -> dict:
    """{(source_id, county): status} for entries whose source feeds `ledger`
    (every entry with a source when `ledger` is None), plus {county: status}
    - the worst - built ONLY from entries that name no source."""
    out: dict = {}
    for e in entries:
        if not isinstance(e, dict):
            continue
        county = str(e.get("county") or "")
        status = reader_status(e)
        sid = e.get("source_id")
        if sid:
            if ledger is not None and ledger not in ledgers_for_source_id(str(sid)):
                continue
            key = (str(sid), county)
            out[key] = _worse(out.get(key), status)
        else:
            out[county] = _worse(out.get(county), status)
    return out


def unit_status(units: dict, source_id, county) -> str | None:
    """One source's read of one county; the source-less county entry is the
    fallback for a file that names no sources."""
    hit = units.get((str(source_id or ""), str(county or "")))
    return hit if hit is not None else units.get(str(county or ""))


def closeable(ledger: Ledger, status: str | None) -> bool:
    return status in CLOSEABLE[ledger]
