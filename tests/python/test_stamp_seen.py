"""Freshness for the PowerShell-synced Florida ledgers (stamp_seen.py)."""
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import stamp_seen as S  # noqa: E402


def test_only_rows_in_the_harvest_are_observed():
    rows = [{"county": "Lee", "case": "2026-01"}, {"county": "Lee", "case": "2026-01"}, {"county": "Lee", "case": ""},
            {"county": "", "case": "X"}, {"county": "Polk", "case": "9"}, "junk"]
    assert S.observed(rows, "case") == {"Lee": ["2026-01"], "Polk": ["9"]}
    assert S.observed({"not": "a list"}, "case") == {}


def test_patch_is_scoped_to_state_source_county_and_exact_cases():
    [url] = S.patch_urls("https://x.supabase.co", "FL", "auction", {"Miami-Dade": ['A"1', "B,2"]})
    q = parse_qs(urlsplit(url).query)
    assert q["state"] == ["eq.FL"] and q["source"] == ["eq.auction"] and q["county"] == ["eq.Miami-Dade"]
    assert q["case_no"] == ['in.("A\\"1","B,2")']


def test_chunks_and_workflow_wiring():
    urls = S.patch_urls("https://x", "FL", "certificate", {"Lee": [str(i) for i in range(S.CHUNK + 1)]})
    assert len(urls) == 2
    wf = (ROOT / ".github/workflows/harvest-and-sync.yml").read_text(encoding="utf-8")
    assert "stamp_seen.py --state FL --source auction --harvest out/harvest_all.json --case-key case" in wf
    assert "stamp_seen.py --state FL --source certificate --harvest out/harvest_certificates.json --case-key case_no" in wf
