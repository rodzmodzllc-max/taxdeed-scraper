#!/usr/bin/env python3
"""Record a Buyer's Guide capture run (scripts/capture_buyers_guide.py) in
data/buyers_guide_captures.csv from its job log.

    python3 scripts/record_buyers_guide_captures.py --log job.log --run-id 123 --date 2026-10-29

Only lines whose answer key still exists in data/buyers_guide_answers.csv are
kept; the source URL recorded is that answer's current source_url. Existing
rows of the same run id are replaced, other runs are kept (the builder uses
the latest capture per answer, quote and URL).
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from harvesters.sources import buyers_guide as G  # noqa: E402

_LINE = re.compile(r"BGCAP\t([^\t]+)\t([0-9a-f]{64})\t([A-Z_]+)\t(\d+)")


def parse(log_text: str) -> list[tuple[str, str, str, str]]:
    return [m.groups() for m in _LINE.finditer(log_text)]


def record(log_text: str, run_id: str, captured_on: str, path: Path = G.CAPTURES_PATH,
           answers: list | None = None) -> int:
    answers = G.load_answers() if answers is None else answers
    urls = {a.key: a.source_url for a in answers}
    new = [{"answer_key": k, "quote_sha256": sha, "source_url": urls[k], "result": res, "http_status": st,
            "run_id": run_id, "captured_on": captured_on}
           for k, sha, res, st in parse(log_text) if k in urls and res in G.CAPTURE_RESULTS]
    old = [r for r in G.load_captures(path) if r["run_id"] != run_id]
    rows = sorted(old + new, key=lambda r: (r["captured_on"], r["run_id"], r["answer_key"]))
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=G.CAPTURE_COLUMNS, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    return len(new)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--log", required=True)
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--date", required=True)
    a = ap.parse_args(argv)
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", a.date):
        print("--date must be YYYY-MM-DD")
        return 2
    n = record(Path(a.log).read_text(encoding="utf-8", errors="replace"), a.run_id, a.date)
    print(f"recorded {n} capture row(s) for run {a.run_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
