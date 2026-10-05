"""Render public/commercial-scope.json from data/paid_beta_sources.csv and the
source registry (harvesters/governance/commercial_scope.py).

    python scripts/build_commercial_scope.py          # write the file
    python scripts/build_commercial_scope.py --check  # exit 1 if it is stale or a decision is invalid
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from harvesters.governance import commercial_scope  # noqa: E402

OUT = REPO / "public" / "commercial-scope.json"


def main(argv: list[str]) -> int:
    errs = commercial_scope.problems()
    if errs:
        print("\n".join(errs), file=sys.stderr)
        return 1
    text = commercial_scope.render()
    if "--check" in argv:
        if not OUT.exists() or OUT.read_text(encoding="utf-8") != text:
            print(f"{OUT.relative_to(REPO)} is stale - run scripts/build_commercial_scope.py", file=sys.stderr)
            return 1
        return 0
    OUT.write_text(text, encoding="utf-8")
    print(f"wrote {OUT.relative_to(REPO)}: {len(commercial_scope.paid_beta_source_ids())} paid-beta sources")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
