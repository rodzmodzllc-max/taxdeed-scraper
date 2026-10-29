"""Buyer's Guide: per state / county / ledger answers to a buyer's questions,
from official sources only (data/buyers_guide/README.md).

data/buyers_guide/<ST>[-part].csv  (research rows)
data/buyers_guide/topics.csv       (the fixed questions)
  -> public/buyers-guide.json      (scripts/build_buyers_guide.py)

The front end displays the file; it never adds an answer of its own. A county
row replaces the statewide row for that county only (same ledger + topic).
"""
from __future__ import annotations

import csv
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DIR = REPO / "data" / "buyers_guide"
TOPICS_PATH = DIR / "topics.csv"

COLUMNS = ("state", "county", "ledger", "topic", "answer", "status", "kind", "quote", "source_url",
           "source_title", "citation", "verified_on", "note")
LEDGERS = ("AUCTIONS", "AVAILABLE", "LIENS_CERTIFICATES")
ROW_LEDGERS = LEDGERS + ("ALL",)
STATUSES = ("VERIFIED", "NOT_VERIFIED", "NOT_APPLICABLE")
READ_STATUSES = ("VERIFIED", "NOT_APPLICABLE")
KINDS = ("LAW", "PROCEDURE")
LEVELS = ("state", "county", "both")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_FILE = re.compile(r"^([A-Z]{2})(-[a-z0-9-]+)?\.csv$")
QUOTE_MAX = 600


@dataclass(frozen=True)
class Topic:
    topic: str
    ledger: str
    level: str
    question: str
    order: int


@dataclass(frozen=True)
class Row:
    state: str
    county: str
    ledger: str
    topic: str
    answer: str
    status: str
    kind: str
    quote: str
    source_url: str
    source_title: str
    citation: str
    verified_on: str
    note: str
    file: str = ""


def load_topics(path: Path = TOPICS_PATH) -> list[Topic]:
    with path.open(newline="", encoding="utf-8") as f:
        return [Topic(r["topic"].strip(), r["ledger"].strip(), r["level"].strip(), r["question"].strip(),
                      int(r["order"])) for r in csv.DictReader(f)]


def research_files(directory: Path = DIR) -> list[Path]:
    return sorted(p for p in directory.glob("*.csv") if _FILE.match(p.name))


def load(directory: Path = DIR) -> list[Row]:
    rows: list[Row] = []
    for path in research_files(directory):
        with path.open(newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                rows.append(Row(**{c: (r.get(c) or "").strip() for c in COLUMNS}, file=path.name))
    return rows


def _topic_index(topics: list[Topic]) -> dict[tuple[str, str], Topic]:
    return {(t.topic, t.ledger): t for t in topics}


def topic_for(row: Row, index: dict[tuple[str, str], Topic]) -> Topic | None:
    return index.get((row.topic, row.ledger)) or index.get((row.topic, "ALL"))


def problems(rows: list[Row] | None = None, topics: list[Topic] | None = None,
             directory: Path = DIR) -> list[str]:
    topics = load_topics() if topics is None else topics
    rows = load(directory) if rows is None else rows
    bad: list[str] = []
    seen_t = set()
    for t in topics:
        if t.level not in LEVELS or t.ledger not in ROW_LEDGERS or not t.question:
            bad.append(f"topics.csv: bad topic {t.topic!r}")
        if (t.topic, t.ledger) in seen_t:
            bad.append(f"topics.csv: duplicate {t.topic}/{t.ledger}")
        seen_t.add((t.topic, t.ledger))
    if directory.exists():
        for p in directory.glob("*.csv"):
            if p.name != "topics.csv" and not _FILE.match(p.name):
                bad.append(f"{p.name}: file name must be <ST>.csv or <ST>-<part>.csv")
    index = _topic_index(topics)
    keys: dict[tuple, str] = {}
    for r in rows:
        where = f"{r.file}: {r.state}/{r.county or '-'}/{r.ledger}/{r.topic}"
        m = _FILE.match(r.file or "XX.csv")
        if m and r.state != m.group(1):
            bad.append(f"{where}: state does not match the file name")
        if r.ledger not in ROW_LEDGERS:
            bad.append(f"{where}: unknown ledger")
        t = topic_for(r, index)
        if t is None:
            bad.append(f"{where}: unknown topic for this ledger")
        elif t.level == "state" and r.county:
            bad.append(f"{where}: statewide-only topic written for a county")
        elif t.level == "county" and not r.county:
            bad.append(f"{where}: county-only topic written statewide")
        if r.status not in STATUSES:
            bad.append(f"{where}: unknown status {r.status!r}")
        if r.kind not in KINDS:
            bad.append(f"{where}: unknown kind {r.kind!r}")
        if not r.source_url.startswith("https://"):
            bad.append(f"{where}: source_url must be https")
        if r.status in READ_STATUSES:
            if not r.quote:
                bad.append(f"{where}: {r.status} needs the quote")
            if not _DATE.match(r.verified_on):
                bad.append(f"{where}: {r.status} needs verified_on YYYY-MM-DD")
            if not r.answer:
                bad.append(f"{where}: {r.status} needs an answer")
            if r.kind == "LAW" and not r.citation:
                bad.append(f"{where}: LAW row needs a citation")
        else:
            if r.answer:
                bad.append(f"{where}: NOT_VERIFIED rows carry no answer")
            if r.verified_on:
                bad.append(f"{where}: NOT_VERIFIED rows carry no verified_on")
        if len(r.quote) > QUOTE_MAX:
            bad.append(f"{where}: quote longer than {QUOTE_MAX} characters")
        k = (r.state, r.county.lower(), r.ledger, r.topic)
        if k in keys:
            bad.append(f"{where}: duplicate of a row in {keys[k]}")
        keys[k] = r.file
    return bad


def _entry(r: Row, t: Topic) -> dict:
    d = {k: v for k, v in asdict(r).items() if k not in ("state", "county", "ledger", "file") and v}
    d["topic"] = r.topic
    d["question"] = t.question
    d["order"] = t.order
    return d


def build(rows: list[Row] | None = None, topics: list[Topic] | None = None) -> dict:
    topics = load_topics() if topics is None else topics
    rows = load() if rows is None else rows
    index = _topic_index(topics)
    states: dict[str, dict] = {}
    counts = {s: 0 for s in STATUSES}
    for r in sorted(rows, key=lambda r: (r.state, r.county, r.ledger, r.topic)):
        t = topic_for(r, index)
        if t is None:
            continue
        counts[r.status] = counts.get(r.status, 0) + 1
        st = states.setdefault(r.state, {"statewide": {}, "counties": {}})
        target = st["counties"].setdefault(r.county, {}) if r.county else st["statewide"]
        target.setdefault(r.ledger, []).append(_entry(r, t))
    for st in states.values():
        for bucket in [st["statewide"], *st["counties"].values()]:
            for lst in bucket.values():
                lst.sort(key=lambda e: (e["order"], e["topic"]))
    return {
        "about": "Answers quoted from official sources only. A county entry replaces the statewide entry "
                 "for the same ledger and topic. NOT_VERIFIED = no official answer read yet; check source_url.",
        "topics": [asdict(t) for t in sorted(topics, key=lambda t: (t.ledger, t.order))],
        "states": states,
        "counts": counts,
    }


def render(rows: list[Row] | None = None, topics: list[Topic] | None = None) -> str:
    return json.dumps(build(rows, topics), ensure_ascii=False, separators=(",", ":")) + "\n"


def answer_for(guide: dict, state: str, county: str, ledger: str, topic: str) -> dict | None:
    """The entry a page shows: the county's own row, else the statewide row
    (ledger first, then ALL)."""
    st = guide.get("states", {}).get(state) or {}
    for bucket in ((st.get("counties") or {}).get(county) or {}, st.get("statewide") or {}):
        for led in (ledger, "ALL"):
            for e in bucket.get(led) or []:
                if e["topic"] == topic:
                    return e
    return None
