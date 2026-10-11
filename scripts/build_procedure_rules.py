#!/usr/bin/env python3
"""Append the county acquisition-procedure rules that verified evidence rows
establish to data/state_rules.csv (harvesters/governance/procedure_rules.py).

  python3 scripts/build_procedure_rules.py              # append missing rules (today's date)
  python3 scripts/build_procedure_rules.py --check      # exit 1 when a rule is missing or drifted

Never rewrites an existing rule: a drift (the evidence wording changed) is
reported, and corrected by hand with a history row and a version bump, as
every other rule change. After appending, rebuild the rules outputs:
python3 scripts/build_state_rules.py (and mirror public/state-rules.json).
"""
from __future__ import annotations

import argparse
import csv
import dataclasses
import sys
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from harvesters.governance import procedure_rules as PR, state_rules as SR  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--changed-on", default=date.today().isoformat())
    a = ap.parse_args(argv)
    existing = SR.load_rules()
    if a.check:
        probs = PR.problems(existing)
        for p in probs:
            print(p)
        print(f"procedure rules: {'current' if not probs else f'{len(probs)} problem(s)'}")
        return 1 if probs else 0
    expected = PR.expected_rules(changed_on=a.changed_on)
    new = PR.missing(existing, expected)
    drift = PR.drifted(existing, expected)
    for d in drift:
        print(f"::warning::{d} - fix by hand with a history row and a version bump")
    if not new:
        print("procedure rules: nothing to append")
        return 0
    fields = [f.name for f in dataclasses.fields(SR.Rule)]
    with open(SR.RULES_PATH, newline="", encoding="utf-8") as fh:
        header = next(csv.reader(fh))
    assert header == fields, (header, fields)
    with open(SR.RULES_PATH, "a", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, lineterminator="\n")
        for r in new:
            w.writerow(dataclasses.asdict(r))
    probs = SR.validate()
    for p in probs:
        print(f"::error::{p}")
    print(f"procedure rules: appended {len(new)} rule(s) to {SR.RULES_PATH.relative_to(REPO)}")
    return 1 if probs else 0


if __name__ == "__main__":
    sys.exit(main())
