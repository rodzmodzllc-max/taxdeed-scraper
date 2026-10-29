"""Buyer's Guide: per state / county / ledger answers to a buyer's questions,
from official sources only (docs/buyers-guide-contract.md, docs/buyers-guide.md).

data/buyers_guide_questions.csv  the questions per ledger (id, group, level, default where_to_look)
data/buyers_guide_answers.csv    researched answers (one row per state, county, ledger, question)
data/buyers_guide_captures.csv   what a capture run read (scripts/capture_buyers_guide.py ->
                                 scripts/record_buyers_guide_captures.py)
  -> public/buyers-guide.json    (scripts/build_buyers_guide.py)

An answer is VERIFIED in the published file only when a capture run fetched its
source_url and found its quote there (every " ... "-separated piece). A
researched answer without that capture is published as NOT_VERIFIED, with the
page to read named in where_to_look - never its answer text. A county answer
replaces the statewide answer for the same question in that county only; a
ledger "ALL" row (office, due_diligence) applies to each ledger of the state.
"""
from __future__ import annotations

import csv
import hashlib
import html
import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
QUESTIONS_PATH = REPO / "data" / "buyers_guide_questions.csv"
ANSWERS_PATH = REPO / "data" / "buyers_guide_answers.csv"
CAPTURES_PATH = REPO / "data" / "buyers_guide_captures.csv"
LEDGERS_PATH = REPO / "data" / "state_ledgers.csv"

LEDGERS = {"AUCTIONS": "Auctions", "AVAILABLE": "Available", "LIENS_CERTIFICATES": "Liens & Certificates"}
ALL_LEDGER_QUESTIONS = ("office", "due_diligence")   # questions an "ALL" row may answer
STATUSES = {
    "VERIFIED": "Answered from an official page a capture run read, with the source's own words.",
    "PARTIALLY_VERIFIED": "Part of the answer was read on an official page; the rest is not yet confirmed.",
    "NOT_VERIFIED": "No official answer has been confirmed yet - where_to_look names the page or office to check.",
    "SOURCE_RESTRICTED": "The official page could not be read (blocked, login or script-only) - check it directly.",
}
READ_STATUSES = ("VERIFIED", "PARTIALLY_VERIFIED")
ANSWER_COLUMNS = ("state", "county", "ledger", "question", "status", "answer", "quote", "source_url", "source_title",
                  "citation", "office", "verified_on", "where_to_look", "note")
CAPTURE_COLUMNS = ("answer_key", "quote_sha256", "source_url", "result", "http_status", "run_id", "captured_on")
CAPTURE_RESULTS = ("FOUND", "PARTIAL", "NOT_FOUND", "FETCH_FAILED", "BLOCKED", "DENIED")
QUOTE_MAX = 600
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_NUMBER = re.compile(r"\.?\d+(?:[.,:/]\d+)*")
_ADVICE = re.compile(r"\b(you should|we recommend|we advise|our advice|you must consult|we suggest|it is best to)\b", re.I)
_LONG_ID = re.compile(r"\b\d{9,}\b")          # parcel / account-like runs never belong in a guide answer
_SPLIT = re.compile(r"\s*(?:\.\.\.|…)\s*")


@dataclass(frozen=True)
class Question:
    ledger: str
    id: str
    order: int
    group: str
    level: str
    question: str
    where_to_look: str


@dataclass(frozen=True)
class Answer:
    state: str
    county: str
    ledger: str
    question: str
    status: str
    answer: str
    quote: str
    source_url: str
    source_title: str
    citation: str
    office: str
    verified_on: str
    where_to_look: str
    note: str
    line: int = 0

    @property
    def key(self) -> str:
        return answer_key(self.state, self.county, self.ledger, self.question)


def answer_key(state: str, county: str, ledger: str, question: str) -> str:
    return "|".join((state, county or "", ledger, question))


def normalize(text: str) -> str:
    """Text as compared by the capture: entities decoded, compatibility forms,
    straight quotes and hyphens, collapsed whitespace, lower case."""
    t = unicodedata.normalize("NFKC", html.unescape(text or ""))
    t = (t.replace("‘", "'").replace("’", "'").replace("“", '"').replace("”", '"')
          .replace("–", "-").replace("—", "-").replace(" ", " ").replace("­", ""))
    return re.sub(r"\s+", " ", t).strip().lower()


def quote_pieces(quote: str) -> list[str]:
    return [p for p in (normalize(x) for x in _SPLIT.split(quote or "")) if p]


def quote_sha(quote: str) -> str:
    return hashlib.sha256(" ... ".join(quote_pieces(quote)).encode("utf-8")).hexdigest()


def match_quote(quote: str, page_text: str) -> str:
    """FOUND when every piece is on the page, PARTIAL when some are, else NOT_FOUND."""
    pieces = quote_pieces(quote)
    if not pieces:
        return "NOT_FOUND"
    text = normalize(page_text)
    hits = sum(1 for p in pieces if p in text)
    return "FOUND" if hits == len(pieces) else "PARTIAL" if hits else "NOT_FOUND"


# --- loading ------------------------------------------------------------------

def load_questions(path: Path = QUESTIONS_PATH) -> list[Question]:
    with path.open(newline="", encoding="utf-8") as f:
        return [Question(r["ledger"].strip(), r["id"].strip(), int(r["order"]), r["group"].strip(), r["level"].strip(),
                         r["question"].strip(), r["where_to_look"].strip()) for r in csv.DictReader(f)]


def load_answers(path: Path = ANSWERS_PATH) -> list[Answer]:
    with path.open(newline="", encoding="utf-8") as f:
        return [Answer(**{c: (r.get(c) or "").strip() for c in ANSWER_COLUMNS}, line=i)
                for i, r in enumerate(csv.DictReader(f), start=2)]


def load_captures(path: Path = CAPTURES_PATH) -> list[dict]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return [{c: (r.get(c) or "").strip() for c in CAPTURE_COLUMNS} for r in csv.DictReader(f)]


def load_ledgers(path: Path = LEDGERS_PATH) -> dict[tuple[str, str], dict]:
    with path.open(newline="", encoding="utf-8") as f:
        return {(r["state"], r["ledger"]): r for r in csv.DictReader(f)}


def capture_index(captures: list[dict]) -> dict[tuple[str, str, str], dict]:
    """The latest capture per (answer key, quote hash, url) - a later read wins,
    so a page that changed since an earlier FOUND downgrades the answer."""
    out: dict[tuple[str, str, str], dict] = {}
    for c in sorted(captures, key=lambda c: (c["captured_on"], c["run_id"])):
        out[(c["answer_key"], c["quote_sha256"], c["source_url"])] = c
    return out


# --- validation ---------------------------------------------------------------

def problems(answers: list[Answer] | None = None, questions: list[Question] | None = None,
             captures: list[dict] | None = None) -> list[str]:
    questions = load_questions() if questions is None else questions
    answers = load_answers() if answers is None else answers
    captures = load_captures() if captures is None else captures
    bad: list[str] = []
    qids: dict[str, set[str]] = {}
    seen_q = set()
    for q in questions:
        if q.ledger not in LEDGERS or not q.question or not q.where_to_look:
            bad.append(f"questions: bad question {q.ledger}/{q.id}")
        if (q.ledger, q.id) in seen_q:
            bad.append(f"questions: duplicate {q.ledger}/{q.id}")
        seen_q.add((q.ledger, q.id))
        qids.setdefault(q.ledger, set()).add(q.id)
    keys: dict[str, int] = {}
    for a in answers:
        where = f"answers line {a.line} ({a.state}/{a.county or '-'}/{a.ledger}/{a.question})"
        if a.ledger == "ALL":
            if a.question not in ALL_LEDGER_QUESTIONS:
                bad.append(f"{where}: an ALL row may only answer {ALL_LEDGER_QUESTIONS}")
        elif a.ledger not in LEDGERS:
            bad.append(f"{where}: unknown ledger")
        elif a.question not in qids.get(a.ledger, ()):
            bad.append(f"{where}: unknown question for this ledger")
        if not re.fullmatch(r"[A-Z]{2}", a.state):
            bad.append(f"{where}: state must be a two-letter code")
        if a.status not in STATUSES:
            bad.append(f"{where}: unknown status {a.status!r}")
        if a.source_url and not a.source_url.startswith("https://"):
            bad.append(f"{where}: source_url must be https")
        if a.status in READ_STATUSES:
            if not a.answer or not a.quote or not a.source_url:
                bad.append(f"{where}: {a.status} needs answer, quote and source_url")
            if not _DATE.match(a.verified_on):
                bad.append(f"{where}: {a.status} needs the research read date in verified_on (YYYY-MM-DD)")
            src = f" {a.quote} {a.citation} "
            for n in _NUMBER.findall(a.answer):
                if not re.search(rf"(?<![\d]){re.escape(n)}(?![\d])", src):
                    bad.append(f"{where}: number {n!r} in the answer is not in the quote")
            if _ADVICE.search(a.answer):
                bad.append(f"{where}: advice wording in the answer")
        else:
            if a.answer or a.quote:
                bad.append(f"{where}: {a.status} rows carry no answer or quote")
            if not (a.where_to_look or a.source_url):
                bad.append(f"{where}: {a.status} needs where_to_look or source_url")
        if _LONG_ID.search(f"{a.answer} {a.quote}"):
            bad.append(f"{where}: a long digit run (parcel / account-like) in the answer or quote")
        if len(a.quote) > QUOTE_MAX:
            bad.append(f"{where}: quote longer than {QUOTE_MAX} characters")
        if a.key in keys:
            bad.append(f"{where}: duplicate of line {keys[a.key]}")
        keys[a.key] = a.line
    for c in captures:
        if c["result"] not in CAPTURE_RESULTS or not _DATE.match(c["captured_on"]) or not c["run_id"]:
            bad.append(f"captures: bad row for {c['answer_key']}")
    return bad


# --- build --------------------------------------------------------------------

def _state_meta() -> dict[str, tuple[str, str]]:
    import sys
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    from harvesters.governance import states as S  # noqa: PLC0415
    out = {}
    for code in sorted(S.PRODUCTION_STATES):
        out[code] = (S.get_state(code).name, "Parish" if code == "LA" else "County")
    return out


def published(a: Answer, caps: dict, qdefault: str) -> dict:
    """The ANSWER object of the contract for one researched row."""
    base = {"q": a.question}
    for k in ("source_title", "citation", "office", "note"):
        if getattr(a, k):
            base[k] = getattr(a, k)
    if a.status in READ_STATUSES:
        cap = caps.get((a.key, quote_sha(a.quote), a.source_url))
        if cap and cap["result"] in ("FOUND", "PARTIAL"):
            status = "VERIFIED" if (cap["result"] == "FOUND" and a.status == "VERIFIED") else "PARTIALLY_VERIFIED"
            return {**base, "status": status, "answer": a.answer, "quote": a.quote, "source_url": a.source_url,
                    "verified_on": cap["captured_on"]}
        why = {"BLOCKED": "the page refused the capture run", "FETCH_FAILED": "the capture run could not load the page",
               "NOT_FOUND": "the capture run did not find the quoted words on the page"}.get(cap["result"] if cap else "",
                                                                                            "not yet confirmed by a capture run")
        status = "SOURCE_RESTRICTED" if cap and cap["result"] == "BLOCKED" else "NOT_VERIFIED"
        return {**base, "status": status, "source_url": a.source_url,
                "where_to_look": f"{a.source_title or 'Official page'} - {a.source_url} ({why})."}
    where = a.where_to_look or (f"{a.source_title or 'Official page'} - {a.source_url}" if a.source_url else qdefault)
    out = {**base, "status": a.status, "where_to_look": where}
    if a.source_url:
        out["source_url"] = a.source_url
    return out


def build(answers: list[Answer] | None = None, questions: list[Question] | None = None,
          captures: list[dict] | None = None, ledgers: dict | None = None) -> dict:
    questions = load_questions() if questions is None else questions
    answers = load_answers() if answers is None else answers
    captures = load_captures() if captures is None else captures
    ledgers = load_ledgers() if ledgers is None else ledgers
    caps = capture_index(captures)
    qdefault = {(q.ledger, q.id): q.where_to_look for q in questions}
    meta = _state_meta()
    states: dict[str, dict] = {}
    for code, (name, unit) in meta.items():
        states[code] = {"name": name, "unit": unit, "ledgers": {}, "counties": {}}
        for led in LEDGERS:
            r = ledgers.get((code, led)) or {}
            states[code]["ledgers"][led] = {"offered": r.get("eligibility") or "NOT_VERIFIED",
                                           "tracked": r.get("status") == "TRACKED",
                                           "summary": (r.get("meaning") or "").strip() or None, "answers": []}
    counts = {s: 0 for s in STATUSES}
    for a in sorted(answers, key=lambda a: (a.state, a.county, a.ledger == "ALL", a.ledger, a.question)):
        if a.state not in states:
            continue
        targets = list(LEDGERS) if a.ledger == "ALL" else [a.ledger]
        st = states[a.state]
        for led in targets:
            if a.ledger == "ALL" and not st["ledgers"][led]["tracked"]:
                continue
            entry = published(a, caps, qdefault.get((led, a.question), ""))
            bucket = st["counties"].setdefault(a.county, {}).setdefault(led, {"answers": []})["answers"] if a.county \
                else st["ledgers"][led]["answers"]
            if any(e["q"] == a.question for e in bucket):   # a ledger-specific row beats the ALL row
                continue
            bucket.append(entry)
            counts[entry["status"]] += 1
    order = {(q.ledger, q.id): q.order for q in questions}
    for code, st in states.items():
        for led, b in st["ledgers"].items():
            b["answers"].sort(key=lambda e: order.get((led, e["q"]), 999))
            b.pop("tracked")
        for c in st["counties"].values():
            for led, b in c.items():
                b["answers"].sort(key=lambda e: order.get((led, e["q"]), 999))
    dates = [c["captured_on"] for c in captures] + [a.verified_on for a in answers if a.verified_on]
    return {
        "_comment": "Generated by scripts/build_buyers_guide.py - do not edit.",
        "generated_at": max(dates) if dates else None,
        "statuses": STATUSES,
        "ledgers": LEDGERS,
        "questions": {led: [{"id": q.id, "question": q.question, "group": q.group, "level": q.level,
                             "where_to_look": q.where_to_look}
                            for q in sorted((q for q in questions if q.ledger == led), key=lambda q: q.order)]
                      for led in LEDGERS},
        "states": states,
        "counts": counts,
    }


def render(**kw) -> str:
    return json.dumps(build(**kw), ensure_ascii=False, separators=(",", ":")) + "\n"


def answer_for(guide: dict, state: str, county: str | None, ledger: str, q: str) -> dict | None:
    """What the front end shows: the county's own answer, else the statewide one."""
    st = (guide.get("states") or {}).get(state) or {}
    c = ((st.get("counties") or {}).get(county or "") or {}).get(ledger) or {}
    for e in c.get("answers") or []:
        if e["q"] == q:
            return {"scope": "county", **e}
    for e in ((st.get("ledgers") or {}).get(ledger) or {}).get("answers") or []:
        if e["q"] == q:
            return {"scope": "state", **e}
    return None
