"""RealAuction skins that publish the appraiser's own key instead of a
"Parcel ID" (Citrus "Alternate Key", Hernando "Parcel Key"; label read
2026-09-18, Actions run 35402576827): the harvester keeps the cell's link as
the appraiser deep-link, never writes the key as a parcel, and carries it as
alt_key. Every block below is SYNTHETIC (no real parcel, key or address).

Runs Get-ParcelFields from scripts/harvest_all_counties.ps1 under pwsh;
skipped where pwsh is not installed (CI has it).
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PWSH = shutil.which("pwsh")
pytestmark = pytest.mark.skipif(not PWSH, reason="pwsh not installed")


def _functions() -> str:
    text = (ROOT / "scripts" / "harvest_all_counties.ps1").read_text(encoding="utf-8")
    return text[text.index("function Get-Field("):text.index("function ToNum(")]


def _cell(label: str, value: str, href: str | None = None) -> str:
    inner = f'<a href=\\"{href}\\" target=\\"_blank\\">{value}</a>' if href else value
    return f'@Htabindex=\\"0\\" @CAD_LBL\\" scope=\\"row\\">{label}:@F tabindex=\\"0\\" @CAD_DTA\\"> {inner}@G'


def _block(*cells: str) -> str:
    return ('@A@E_DETAILS\\"><@I @Cad_tab\\"><tbody>' + _cell("Case #", "2099-0001TD")
            + _cell("Opening Bid", "$1,000.00") + "".join(cells) + _cell("Assessed Value", "$2,000.00") + "</tbody></@I>")


def _run(tmp_path: Path, block: str) -> dict:
    (tmp_path / "item.txt").write_text(block, encoding="utf-8")
    script = tmp_path / "pf.ps1"
    script.write_text("$ErrorActionPreference = 'Stop'\n" + _functions()
                      + "\n$b = Get-Content (Join-Path $PSScriptRoot 'item.txt') -Raw\n"
                        "Get-ParcelFields $b | ConvertTo-Json -Compress\n", encoding="utf-8")
    r = subprocess.run([PWSH, "-NoProfile", "-NonInteractive", "-File", str(script)], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


def test_alternate_key_gives_the_link_and_no_parcel(tmp_path):
    href = "https://appraiser.example/datalet.aspx?pin=9000001"
    got = _run(tmp_path, _block(_cell("Alternate Key", "9000001", href)))
    assert got == {"parcel": "", "appraiser": href, "alt_key": "9000001"}


def test_parcel_key_gives_the_link_and_no_parcel(tmp_path):
    href = "https://appraiser.example/parcel/00900002"
    got = _run(tmp_path, _block(_cell("Parcel Key", "00900002", href)))
    assert got == {"parcel": "", "appraiser": href, "alt_key": "00900002"}


def test_a_parcel_id_wins_and_reads_exactly_as_before(tmp_path):
    href = "https://appraiser.example/q?KeyValue=00000-000-001"
    got = _run(tmp_path, _block(_cell("Parcel ID", "00000-000-001", href), _cell("Parcel Key", "00900002", "https://x.example/p")))
    assert got == {"parcel": "00000-000-001", "appraiser": href, "alt_key": None}


def test_no_identifier_cell_reads_as_nothing(tmp_path):
    assert _run(tmp_path, _block()) == {"parcel": "", "appraiser": None, "alt_key": None}


def test_the_harvest_row_uses_the_parcel_fields():
    text = (ROOT / "scripts" / "harvest_all_counties.ps1").read_text(encoding="utf-8")
    assert "$pf = Get-ParcelFields $b" in text
    assert "parcel      = $pf.parcel" in text and "appraiser   = $pf.appraiser" in text and "alt_key     = $pf.alt_key" in text
    # The key is evidence only: the deed sync never writes it.
    assert "alt_key" not in (ROOT / "scripts" / "sync-harvest-to-supabase.ps1").read_text(encoding="utf-8")
