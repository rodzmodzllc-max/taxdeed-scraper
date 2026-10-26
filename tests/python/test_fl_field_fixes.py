"""Florida field defects fixed 2026-10-26.

A. The PowerShell syncs never erase a stored value: a blank or a placeholder
   never replaces a non-blank stored value, and a value whose field_provenance
   names another source of equal or higher rank (FDOR's `fdor_nal`, hand
   research) is never replaced by the listing (scripts/sync_value_guard.py).
   Production before the fix (read-only, counts only): 146 active FL auction
   rows had `assessed` provenance `fdor_nal` and a blank value.
B. The FL deed harvester reads the tax certificate number under the label
   variants a county skin may use (Get-CertificateNumber), exact label cells
   only; the manual evidence job can print the label vocabulary, value-free.

The PowerShell checks run the real scripts under pwsh against the local fake
Supabase of test_ledger_ps_syncs.py.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import sync_value_guard as G  # noqa: E402


def fdor(col="assessed"):
    return {col: {"source": "fdor_nal", "recorded_at": "2026-10-20T00:00:00+00:00"}}


def stored(**kw):
    base = {"id": 1, "county": "Lee", "case_no": "C-1", "field_provenance": {}}
    base.update(kw)
    return base


def auction(**kw):
    base = {"source": "auction", "county": "Lee", "case_no": "C-1", "parcel": "P", "address": "1 Main St",
            "bid": 1000, "assessed": None, "sale_date": "2099-12-01", "url_appraiser": None,
            "url_auction": "https://x.example/a", "status": "active", "url_auction_kind": "sale"}
    base.update(kw)
    return base


# ------------------------------------------------------------- A: the rule

def test_blank_listing_value_never_erases_the_tax_roll_value():
    out = G.guard_row("auction", auction(assessed=None), stored(assessed=123000, field_provenance=fdor()))
    assert out["assessed"] == 123000


def test_blank_never_erases_even_without_provenance():
    out = G.guard_row("auction", auction(assessed=None, parcel=""), stored(assessed=5, parcel="P-9"))
    assert out["assessed"] == 5 and out["parcel"] == "P-9"


def test_listing_never_replaces_a_higher_ranked_value():
    out = G.guard_row("auction", auction(assessed=999), stored(assessed=123000, field_provenance=fdor()))
    assert out["assessed"] == 123000
    hand = {"assessed": {"source": "hand_research"}}
    assert G.guard_row("auction", auction(assessed=999), stored(assessed=1, field_provenance=hand))["assessed"] == 1


def test_listing_refreshes_its_own_and_unprovenanced_values():
    own = {"bid": {"source": "vendor_listing"}, "assessed": {"source": "vendor_listing"}}
    out = G.guard_row("auction", auction(bid=2000, assessed=7), stored(bid=1000, assessed=6, field_provenance=own))
    assert out["bid"] == 2000 and out["assessed"] == 7
    out = G.guard_row("auction", auction(bid=2000), stored(bid=1000))
    assert out["bid"] == 2000


def test_new_row_is_sent_as_harvested():
    row = auction(assessed=None)
    assert G.guard_row("auction", row, None) == row


def test_status_and_identity_are_never_guarded():
    out = G.guard_row("auction", auction(status="active"), stored(status="closed"))
    assert out["status"] == "active" and out["case_no"] == "C-1"


def test_url_auction_kind_follows_a_kept_url():
    out = G.guard_row("auction", auction(url_auction=None, url_auction_kind=None),
                      stored(url_auction="https://x.example/s", url_auction_kind="county"))
    assert out["url_auction"] == "https://x.example/s" and out["url_auction_kind"] == "county"


def test_certificate_placeholders_never_erase():
    row = {"source": "certificate", "county": "Lee", "case_no": "77", "address": "Account 77", "bid": 0,
           "owner_name": None, "url_auction": None, "url_auction_kind": None}
    out = G.guard_row("certificate", row, stored(case_no="77", address="9 Oak St", bid=812.5, owner_name="X"))
    assert out["address"] == "9 Oak St" and out["bid"] == 812.5 and out["owner_name"] == "X"


def test_laft_placeholders_and_precedence():
    row = {"source": "laft", "county": "Lee", "case_no": "L-1", "parcel": "12-34", "address": "Parcel 12-34",
           "bid": 0, "sale_date": None, "url_auction": None, "url_auction_kind": None}
    out = G.guard_row("laft", row, stored(case_no="L-1", address="5 Elm", bid=450, sale_date="2026-01-01"))
    assert out["address"] == "5 Elm" and out["bid"] == 450 and out["sale_date"] == "2026-01-01"
    # The county list (rank 2) never replaces an equal-rank value of another source...
    real = dict(row, address="7 Pine")
    assert G.guard_row("laft", real, stored(case_no="L-1", address="5 Elm", field_provenance=fdor("address")))["address"] == "5 Elm"
    # ...but refreshes its own.
    own = {"address": {"source": "county_list"}}
    assert G.guard_row("laft", real, stored(case_no="L-1", address="5 Elm", field_provenance=own))["address"] == "7 Pine"


def test_guard_rows_keeps_order_and_keys():
    rows = [auction(case_no="A"), auction(case_no="B", assessed=3)]
    out = G.guard_rows("auction", rows, [stored(case_no="A", assessed=10, field_provenance=fdor())])
    assert [r["case_no"] for r in out] == ["A", "B"]
    assert [r["assessed"] for r in out] == [10, 3]
    assert all(set(r) == set(rows[0]) for r in out)


def test_cli_fails_closed_without_credentials(tmp_path, monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    (tmp_path / "in.json").write_text(json.dumps([auction()]))
    assert G.main(["--source", "auction", "--in", str(tmp_path / "in.json"), "--out", str(tmp_path / "o.json")]) == 2
    assert not (tmp_path / "o.json").exists()


def test_every_sync_calls_the_guard_once_before_its_upsert():
    block = None
    for name, source in (("sync-harvest-to-supabase.ps1", "auction"), ("sync-certificates-to-supabase.ps1", "certificate"),
                         ("sync-laft-to-supabase.ps1", "laft")):
        text = (ROOT / "scripts" / name).read_text(encoding="utf-8")
        s, e = text.index("# --- Stored-value guard (2026-10-26) "), text.index("# --- end stored-value guard ")
        assert block in (None, text[s:e])
        block = text[s:e]
        call = f'$rows = @(Protect-StoredValues "{source}" $rows)'
        assert text.count(call) == 1
        upsert = text.index("Invoke-RestMethod -Uri $endpoint")
        assert text.index(call) < upsert
        assert text.index('Select-LedgerRows "') < text.index(call)
    assert set(G.GUARDED) == {"auction", "certificate", "laft"}


# ------------------------------------------------------------- A: end to end under pwsh

def _ps():
    import importlib
    sys.path.insert(0, str(ROOT / "tests" / "python"))
    return importlib.import_module("test_ledger_ps_syncs")


@pytest.fixture
def ps(tmp_path):
    m = _ps()
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    for f in (ROOT / "scripts").iterdir():
        if f.is_file():
            (scripts / f.name).symlink_to(f)
    (tmp_path / "out").mkdir()
    return m, tmp_path


def test_deeds_sync_keeps_the_tax_roll_assessed_value(ps):
    m, ws = ps
    m.write(ws, "harvest_all.json", [m.deed("Lee", "A-1", assessed=None), m.deed("Lee", "A-2", assessed=None),
                                     m.deed("Lee", "A-3", assessed=777)])
    fake = m.FakeSupabase(stored_rows=[
        {"id": 1, "county": "Lee", "case_no": "A-1", "assessed": 123000, "field_provenance": fdor()},
        {"id": 3, "county": "Lee", "case_no": "A-3", "assessed": 150000, "field_provenance": fdor()},
    ])
    try:
        r = m.run_ps(ws, "sync-harvest-to-supabase.ps1", fake)
    finally:
        fake.close()
    assert r.returncode == 0, r.stdout + r.stderr
    posted = {p["case_no"]: p for p in fake.posted_rows()}
    assert posted["A-1"]["assessed"] == 123000      # blank never erases
    assert posted["A-2"]["assessed"] is None        # nothing stored: as harvested
    assert posted["A-3"]["assessed"] == 150000      # FDOR outranks the listing
    assert len({frozenset(p) for p in posted.values()}) == 1   # one key set (PGRST102)
    assert len(fake.guard_reads()) == 1


def test_certificate_sync_keeps_stored_values(ps):
    m, ws = ps
    m.write(ws, "harvest_certificates.json", [m.cert("Lee", "C-1", address="", parcel="", bid="")])
    fake = m.FakeSupabase(stored_rows=[{"id": 1, "county": "Lee", "case_no": "C-1", "address": "9 Oak St",
                                        "parcel": "P-77", "bid": 812.5, "field_provenance": {}}])
    try:
        r = m.run_ps(ws, "sync-certificates-to-supabase.ps1", fake)
    finally:
        fake.close()
    assert r.returncode == 0, r.stdout + r.stderr
    (p,) = fake.posted_rows()
    assert p["address"] == "9 Oak St" and p["parcel"] == "P-77" and p["bid"] == 812.5


def test_laft_sync_keeps_stored_values(ps):
    m, ws = ps
    m.write(ws, "harvest_laft.json", [{"county": "Lee", "case_no": "L-1", "parcel": "12-34"}])
    fake = m.FakeSupabase(stored_rows=[{"id": 1, "county": "Lee", "case_no": "L-1", "address": "5 Elm", "bid": 450,
                                        "field_provenance": {}}])
    try:
        r = m.run_ps(ws, "sync-laft-to-supabase.ps1", fake)
    finally:
        fake.close()
    assert r.returncode == 0, r.stdout + r.stderr
    (p,) = fake.posted_rows()
    assert p["address"] == "5 Elm" and p["bid"] == 450


def test_a_failed_stored_read_writes_nothing(ps):
    m, ws = ps
    m.write(ws, "harvest_all.json", [m.deed("Lee", "A-1", assessed=None)])
    fake = m.FakeSupabase()
    fake.fail_guard = True
    try:
        r = m.run_ps(ws, "sync-harvest-to-supabase.ps1", fake)
    finally:
        fake.close()
    assert r.returncode != 0
    assert fake.of("POST") == [] and fake.of("PATCH") == []


# ------------------------------------------------------------- B: certificate labels under pwsh

def _harvester_functions() -> str:
    text = (ROOT / "scripts" / "harvest_all_counties.ps1").read_text(encoding="utf-8")
    s = text.index("function Get-Field(")
    e = text.index("function ToNum(")
    return text[s:e]


def _item(label: str, value: str = "2019-1234") -> str:
    # The AJAX body as the harvester sees it: a JSON string of HTML, quotes escaped.
    return ('@ACAD_LBL\\" scope=\\"row\\">Case #:@F@ACAD_DTA\\">2024-TD-1@G'
            f'@ACAD_LBL\\" scope=\\"row\\">{label}@F@ACAD_DTA\\">{value}@G'
            '@ACAD_LBL\\" scope=\\"row\\">Opening Bid:@F@ACAD_DTA\\">$1,000.00@G')


@pytest.mark.parametrize("label,expected", [
    ("Certificate #:", "2019-1234"),
    ("Tax Certificate #:", "2019-1234"),
    ("Cert #:", "2019-1234"),
    ("Certificate Number:", "2019-1234"),
    ("CERTIFICATE NO.:", "2019-1234"),
    ("Tax Cert #:", "2019-1234"),
    ("Parcel ID:", None),            # no certificate label: nothing, never a guess
])
def test_certificate_label_variants(ps, label, expected):
    m, ws = ps
    script = ws / "scripts" / "cert_under_test.ps1"
    script.write_text("$ErrorActionPreference = 'Stop'\n" + _harvester_functions() +
                      "\n$b = Get-Content (Join-Path $PSScriptRoot 'item.txt') -Raw\n"
                      "$v = Get-CertificateNumber $b\n"
                      "if ($null -eq $v) { 'NULL' } else { $v }\n", encoding="utf-8")
    (ws / "scripts" / "item.txt").write_text(_item(label), encoding="utf-8")
    r = subprocess.run([m.PWSH, "-NoProfile", "-NonInteractive", "-File", str(script)], capture_output=True, text=True,
                       timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    got = r.stdout.strip().splitlines()[-1]
    assert got == (expected or "NULL")


def test_label_report_masks_digits(ps):
    m, ws = ps
    script = ws / "scripts" / "labels_under_test.ps1"
    script.write_text("$ErrorActionPreference = 'Stop'\n" + _harvester_functions() +
                      "\n$b = Get-Content (Join-Path $PSScriptRoot 'item.txt') -Raw\n"
                      "@(Get-LabelTexts $b) | ConvertTo-Json -Compress\n", encoding="utf-8")
    (ws / "scripts" / "item.txt").write_text(_item("Cert 2019 #:"), encoding="utf-8")
    r = subprocess.run([m.PWSH, "-NoProfile", "-NonInteractive", "-File", str(script)], capture_output=True, text=True,
                       timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    labels = json.loads(r.stdout.strip().splitlines()[-1])
    assert labels == ["Case #", "Cert #### #", "Opening Bid"]
    assert not any(ch.isdigit() for ch in "".join(labels))


def test_label_capture_scope_reads_only_and_syncs_nothing():
    wf = (ROOT / ".github" / "workflows" / "harvest-and-sync.yml").read_text(encoding="utf-8")
    assert "realauction_labels" in wf.split("options: [available,", 1)[1].split("]", 1)[0] or \
        "options: [available, realauction_labels," in wf
    i = wf.index('if [ "$SCOPE" = "realauction_labels" ]; then')
    block = wf[i:wf.index("exit 0", i)]
    assert "harvest_all_counties.ps1" in block and "HARVEST_LABEL_REPORT=1" in block
    assert "sync-" not in block and "SUPABASE" not in block
    # The evidence job holds no database credential.
    ev = wf[wf.index("\n  evidence:\n"):wf.index("\n  enrich:\n")]
    assert "SUPABASE_SERVICE_KEY" not in ev
