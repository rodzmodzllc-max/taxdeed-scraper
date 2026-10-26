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
    assert "stamp_seen.py --state FL --source certificate --harvest out/harvest_certificates.json --case-key case_no --status out/harvest_certificates_status.json" in wf


def test_texas_mixed_ledger_harvest_stamps_each_ledger_only_from_its_own_rows():
    """2026-10-26: the Texas harvest file mixes auction and laft rows; with
    --row-source a case read in one ledger never stamps the other's row."""
    import stamp_seen as S
    rows = [{"county": "Galveston", "account_number": "100", "source": "laft"},
            {"county": "Galveston", "account_number": "200", "source": "auction"},
            {"county": "Liberty", "account_number": "300", "source": "laft"}]
    assert S.observed(rows, "account_number", "laft") == {"Galveston": ["100"], "Liberty": ["300"]}
    assert S.observed(rows, "account_number", "auction") == {"Galveston": ["200"]}
    assert S.observed(rows, "account_number") == {"Galveston": ["100", "200"], "Liberty": ["300"]}


def test_texas_ledgers_have_a_store_permission_mapping():
    import stamp_seen as S
    assert S.STORE_SOURCES[("TX", "laft")][0] == ("tx_lgbs",)
    assert set(S.STORE_SOURCES[("TX", "auction")][0]) == {"tx_lgbs", "tx_realauction"}
    assert S.store_permitted("TX", "laft") and S.store_permitted("TX", "auction")


def test_texas_job_stamps_after_sync_and_before_inventory_status():
    from pathlib import Path
    wf = (Path(__file__).resolve().parents[2] / ".github/workflows/harvest-and-sync.yml").read_text(encoding="utf-8")
    sync = wf.index("run: python3 scripts/sync-texas-to-supabase.py")
    stamp = wf.index("stamp_seen.py --state TX --source laft")
    status = wf.index("inventory_status_writer.py --state TX")
    assert sync < stamp < status
    assert "--state TX --source auction --harvest out/harvest_texas.json --case-key account_number --row-source" in wf
