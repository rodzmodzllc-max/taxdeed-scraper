"""capture_state_sources.table_structure (available-five evidence pass,
2026-10-04): a list document's structure is printed to a PUBLIC job log, so
no cell value - an owner name, a street, a legal description - may reach it,
even when the first data row is mistaken for the header. Regression for the
first run, whose free-text 'first lines' printed a list row."""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
import capture_state_sources as C  # noqa: E402

OWNER, STREET, LEGAL = "Zebulon Quillfeather", "Marigold Lane", "Lot Seventeen Wexford Plat"


def _flat(obj) -> str:
    return json.dumps(obj)


def test_names_and_streets_never_reach_the_structure():
    rows = [["PARCEL", "Municipality", "OWNER", "DESCRIPTION", "Min. Bid"],
            ["12-34-5678", "Belle Boro", OWNER, f"412 {STREET} {LEGAL}", "$ 412.10"],
            ["12-34-5679", "Belle Boro", "Acme Holdings LLC", f"9 {STREET}", "$ 1,200.00"]]
    out = C.table_structure(rows)
    assert out["header"] == ["PARCEL", "Municipality", "OWNER", "DESCRIPTION", "Min. Bid"]
    assert out["table_rows"] == 2
    flat = _flat(out)
    for secret in (OWNER, "Zebulon", "Quillfeather", STREET, "Marigold", "Wexford", "Acme", "Belle"):
        assert secret not in flat
    assert out["col_shapes"]["PARCEL"] == {"99-99-9999": 2}


def test_a_data_row_mistaken_for_the_header_is_masked():
    rows = [["38310005000", "1413", "Marigold", "LN", OWNER, "Old North St. Louis"],
            ["38310005001", "1415", "Marigold", "LN", "Acme Holdings LLC", "Old North St. Louis"]]
    out = C.table_structure(rows)
    flat = _flat(out)
    for secret in (OWNER, "Marigold", "Old North", "Acme", "38310005000"):
        assert secret not in flat
    assert set(out["header"]) == {"?"}
    assert out["table_rows"] == 2


def test_header_cell_vocabulary():
    assert C.header_cell("Parcel_No") == "Parcel_No"
    assert C.header_cell("Initial Bid Amount") == "Initial Bid Amount"
    assert C.header_cell("Zebulon Quillfeather") is None      # a name is not a column name
    assert C.header_cell("412 Marigold Lane") is None          # digits never pass
    assert C.header_cell("") == ""


def test_the_available_five_pass_never_runs_free_text_snippets_on_list_documents():
    src = (REPO / "scripts" / "capture_state_sources.py").read_text(encoding="utf-8")
    block = src[src.index("    if args.available_five:"):src.index("    passes = []")]
    assert "pdf_process(" not in block
    assert "first_page_lines" not in src


def test_pdf_line_shapes_never_prints_a_line(monkeypatch):
    import io as _io

    class _Page:
        def extract_text(self):
            return ("PARCEL OWNER ADDRESS MIN BID\n"
                    "JOHN QUILLFEATHER LOT BLOCK\n"
                    "12-345-678 ZEBULON QUILLFEATHER 14 MARIGOLD LANE $ 1,200.00\n")

    class _Pdf:
        pages = [_Page()]
        def __enter__(self): return self
        def __exit__(self, *a): return False

    class _Resp:
        status_code, content = 200, b"%PDF"

    import pdfplumber
    monkeypatch.setattr(pdfplumber, "open", lambda *_a, **_k: _Pdf())
    monkeypatch.setattr(C, "fetch", lambda *_a, **_k: (_Resp(), None))
    out = C.pdf_line_shapes(None, "https://example.invalid/list.pdf")
    flat = json.dumps(out)
    for secret in ("QUILLFEATHER", "ZEBULON", "JOHN", "MARIGOLD", "12-345-678"):
        assert secret not in flat
    assert out["table_rows"] == 3
    assert out["header"] == ["PARCEL OWNER ADDRESS MIN BID"]
