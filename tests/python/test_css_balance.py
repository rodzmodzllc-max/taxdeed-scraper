"""Every stylesheet's braces balance (2026-10-06).

A merge that drops one closing brace leaves every later rule inside an
@media block - the page still loads and nothing errors, but whole features
lose their styling (this happened to the due-diligence state key). Comments
and strings are stripped before counting."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SHEETS = sorted(p for p in (ROOT / "public").glob("*.css")) + sorted(ROOT.glob("*.css"))


def _depths(text: str) -> tuple[int, int]:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    text = re.sub(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'', '""', text)
    depth = lowest = 0
    for ch in text:
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            lowest = min(lowest, depth)
    return depth, lowest


@pytest.mark.parametrize("sheet", SHEETS, ids=lambda p: str(p.relative_to(ROOT)))
def test_braces_balance(sheet: Path) -> None:
    final, lowest = _depths(sheet.read_text(encoding="utf-8"))
    assert lowest == 0, f"{sheet.name}: a closing brace appears before its opening one"
    assert final == 0, f"{sheet.name}: {final} unclosed brace(s)"


def test_sheets_found() -> None:
    assert any(p.name == "identity.css" for p in SHEETS)
