"""The candidate-state capture prints structure only (2026-09-30)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import capture_state_sources as C  # noqa: E402


def test_shape_masks_every_digit_and_letter():
    assert C.shape("123-45a") == "999-99A"


def test_html_structure_masks_digits_and_drops_tables_and_selects():
    html = ("<title>T</title><table><tr><th>Parcel 12</th></tr><tr><td>1234567</td></tr></table>"
            "<form method=get><select name=c><option value=01>Ann 1</option><option>B</option><option>C</option></select></form>"
            "<p>Updated 09/07/2026 for purchase.</p><a href='/terms-of-use'>Terms of Use</a>")
    s = C.html_structure(html, "https://a.gov/x")
    assert s["tables"][0]["headers"] == ["Parcel 99"]
    assert s["tables"][0]["body_rows"] == 1
    assert "1234567" not in repr(s)
    assert s["forms"][0]["fields"][0]["option_texts"][0] == "Ann 9"
    assert any("Updated 99/99/9999 for purchase." in x for x in s["snippets"])
    assert not any("2026" in x for x in s["snippets"])
    assert s["terms_links"] == [{"text": "Terms of Use", "href": "https://a.gov/terms-of-use"}]


def test_csv_structure_reports_shapes_not_values():
    class R:
        def iter_content(self, n):
            yield b"PROPERTY NUMBER,TAXPAYER NAME\n012-3456-7,JANE DOE\n"
    s = C.csv_structure(R())
    assert s["csv_header"] == ["PROPERTY NUMBER", "TAXPAYER NAME"]
    col = s["columns"][0]
    assert col["shapes"] == {"999-9999-9": 1}
    assert "shapes" not in s["columns"][1]
    assert "JANE" not in repr(s) and "012-3456-7" not in repr(s)
