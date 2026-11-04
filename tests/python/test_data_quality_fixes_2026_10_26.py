"""Regression tests for the production data-quality audit of 2026-10-26
(docs/review/data-quality-audit-2026-10-26.md). Each test pins the code fix
for one defect the audit measured; none reads production."""
from __future__ import annotations

import importlib.util
import json
import re
import sys
from datetime import date
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(1, str(REPO / "scripts"))

from harvesters.governance import inventory_status as IS  # noqa: E402
import apply_acquisition_paths as AAP  # noqa: E402
import laft_lifecycle as LL  # noqa: E402
import sync_state_inventory as SY  # noqa: E402


# ---------------------------------------------------------------- Texas sync

def _run_tx_sync(monkeypatch, tmp_path, fixture):
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    (out_dir / "harvest_texas.json").write_text(json.dumps(fixture))
    spec = importlib.util.spec_from_file_location("sync_dq", str(REPO / "scripts" / "sync-texas-to-supabase.py"))
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "HERE", tmp_path)
    monkeypatch.setattr(mod, "JSON_PATH", out_dir / "harvest_texas.json")
    monkeypatch.setenv("SUPABASE_URL", "http://example.invalid")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "test-fixture-not-a-real-key")
    posted: list[list[dict]] = []

    class _R:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b""

    def _fake_urlopen(req, timeout=60):
        posted.append(json.loads(req.data))
        return _R()

    monkeypatch.setattr(mod.urllib.request, "urlopen", _fake_urlopen)
    mod.main()
    return {r["case_no"]: r for batch in posted for r in batch}


TX = {"state": "TX", "auction_date": "2026-11-03", "cad_market_value": 1000.0, "legal_description": None,
      "address": "1 A St", "auction_url": None, "auction_url_kind": None, "sale_status": None}


def test_tx_sync_sends_the_harvesters_own_source_id(monkeypatch, tmp_path):
    rows = _run_tx_sync(monkeypatch, tmp_path, [
        dict(TX, account_number="LG-1", county="Galveston", cause_number="C-1", source="auction",
             harvester_source="tx_lgbs", min_bid=500.0, latitude=None, longitude=None),
        dict(TX, account_number="RA-1", county="Nueces", cause_number="C-2", source="auction",
             harvester_source="tx_realauction", min_bid=700.0, latitude=None, longitude=None),
    ])
    assert rows["LG-1"]["source_id"] == rows["LG-1"]["harvester_source"] == "tx_lgbs"
    assert rows["RA-1"]["source_id"] == rows["RA-1"]["harvester_source"] == "tx_realauction"


def test_tx_sync_a_zero_minimum_bid_is_not_published(monkeypatch, tmp_path):
    rows = _run_tx_sync(monkeypatch, tmp_path, [
        dict(TX, account_number="Z-0", county="Galveston", cause_number="C-1", source="auction",
             harvester_source="tx_lgbs", min_bid=0.0, latitude=None, longitude=None),
        dict(TX, account_number="Z-1", county="Galveston", cause_number="C-2", source="auction",
             harvester_source="tx_lgbs", min_bid=1250.0, latitude=None, longitude=None),
    ])
    assert rows["Z-0"]["min_bid"] is None and rows["Z-0"]["bid"] == 0      # 0 = the legacy "not published" sentinel
    assert rows["Z-1"]["min_bid"] == 1250.0 and rows["Z-1"]["bid"] == 1250.0


def test_tx_sync_drops_a_vendor_point_outside_texas(monkeypatch, tmp_path):
    rows = _run_tx_sync(monkeypatch, tmp_path, [
        dict(TX, account_number="OUT", county="Orange", cause_number="C-1", source="auction",
             harvester_source="tx_lgbs", min_bid=500.0, latitude=31.0, longitude=-92.0),      # Louisiana
        dict(TX, account_number="IN", county="Orange", cause_number="C-2", source="auction",
             harvester_source="tx_lgbs", min_bid=500.0, latitude=30.1, longitude=-93.8),      # Orange County, TX
    ])
    assert "latitude" not in rows["OUT"] and "longitude" not in rows["OUT"]   # never sent: no erase, no bad point
    assert (rows["IN"]["latitude"], rows["IN"]["longitude"]) == (30.1, -93.8)


# --------------------------------------------- acquisition paths reach every row

def test_apply_acquisition_paths_reads_rows_by_source_id_or_harvester_source(monkeypatch):
    seen = []
    monkeypatch.setattr(AAP, "_req", lambda method, url, key, body=None: seen.append(url) or [])
    AAP.fetch_rows("https://x.invalid", "k", "TX", "tx_lgbs")
    q = parse_qs(urlsplit(seen[0]).query)
    assert q["or"] == ["(source_id.eq.tx_lgbs,harvester_source.eq.tx_lgbs)"]
    assert "source_id" not in q


def test_apply_acquisition_paths_backfills_a_missing_source_id_from_the_harvester():
    reg = {("tx_lgbs", "Galveston"): {"canonical_url": "https://taxsales.lgbs.com/", "last_checked": ""}}
    row = {"id": "1", "state": "TX", "county": "Galveston", "source": "laft", "source_id": None,
           "harvester_source": "tx_lgbs", "case_no": "A1", "parcel": "C-1", "status": "active", "otc_provenance": {}}
    payload, _ = AAP.plan_row(row, registry=reg, evidence=[], state="TX", today="2026-10-26")
    assert payload["source_id"] == "tx_lgbs"
    assert payload["list_url"] == "https://taxsales.lgbs.com/"
    # A row that already names its source is not rewritten.
    payload2, _ = AAP.plan_row(dict(row, source_id="tx_lgbs"), registry=reg, evidence=[], state="TX", today="2026-10-26")
    assert "source_id" not in (payload2 or {})


# ------------------------------------------------------- inventory status

def test_a_texas_lgbs_row_off_the_feed_is_closed_whatever_status_it_last_carried():
    row = {"state": "TX", "source": "auction", "harvester_source": "tx_lgbs", "status": "closed",
           "tx_sale_status": "Scheduled for Auction", "sale_date": "2026-10-06"}
    obs = IS.status_for_row(row, today=date(2026, 10, 26))
    assert (obs.status, obs.basis, obs.raw) == ("closed", "LIST_PRESENCE", "Scheduled for Auction")
    listed = IS.status_for_row(dict(row, status="active", sale_date="2026-11-03"), today=date(2026, 10, 26))
    assert listed.status == "upcoming"


# ------------------------------------------------- delisted_at lifecycle

def test_state_inventory_sync_clears_delisted_at_on_a_listed_row(tmp_path):
    import harvest_expansion as HX
    fix = REPO / "tests/python/fixtures/expansion"
    assert HX.main(["--state", "SC", "--out-dir", str(tmp_path),
                    "--fixture", f"sc_york_tax_sale={fix / 'sc_york_page.json'}"]) == 0
    rows = json.loads((tmp_path / "sc_properties_rows.json").read_text())
    sent, _ = SY.plan("SC", rows, SY.registry_rows("SC"), {"York": "COMPLETE"}, observed_at="2026-10-26T12:00:00+00:00")
    active = [r for r in sent if r["status"] == "active"]
    assert active and all("delisted_at" in r and r["delisted_at"] is None for r in active)


class _Api:
    def __init__(self):
        self.patches = []

    def patch(self, where, body):
        self.patches.append((where, body))


@pytest.mark.parametrize("have_017,expected", [(True, {"status": "active", "delisted_at": None}),
                                                (False, {"status": "active"})])
def test_laft_lifecycle_reactivation_clears_delisted_at(have_017, expected):
    api = _Api()
    plan = LL.Plan(reactivate=[("Alachua", "L-1")])
    LL.execute(plan, {}, {}, api, state="FL", have_017=have_017, retrieved_at="2026-10-26T12:00:00Z")
    assert [b for _, b in api.patches] == [expected]


def _payload_literal(text: str) -> str:
    """The per-row upsert hashtable: from its opening line to the first
    following `$rows = ` / `$deduped` statement."""
    start = text.index("$rows += [ordered]@{")
    end = min(i for i in (text.find("\n$rows = ", start), text.find("\n$deduped", start)) if i > 0)
    return text[start:end]


def test_florida_powershell_upserts_reactivate_and_clear_delisted_at():
    deeds = (REPO / "scripts" / "sync-harvest-to-supabase.ps1").read_text(encoding="utf-8")
    certs = (REPO / "scripts" / "sync-certificates-to-supabase.ps1").read_text(encoding="utf-8")
    # A listed row is active (a notfound certificate listed again comes back) and sheds delisted_at.
    for text in (deeds, certs):
        payload = _payload_literal(text)
        assert re.search(r'\bstatus\s*=\s*"active"', payload)
        assert re.search(r"\bdelisted_at\s*=\s*\$null", payload)
    # The close-out bodies are unchanged (status only); delisted_at comes from stamp_seen --delisted.
    assert """'{"status":"closed"}'""" in deeds and """'{"status":"notfound"}'""" in certs


def test_stamp_seen_delisted_copies_the_close_out_time_for_absence_closes_only():
    import stamp_seen as SS
    t1, t2 = "2026-10-20T22:16:00+00:00", "2026-10-21T10:00:00+00:00"
    rows = [
        {"id": "a", "status": "closed", "gone_since": t1, "delisted_at": None},
        {"id": "b", "status": "notfound", "gone_since": t1, "delisted_at": None},
        {"id": "c", "status": "closed", "gone_since": t2, "delisted_at": None},
        {"id": "d", "status": "closed", "gone_since": None, "delisted_at": None},          # no close time: untouched
        {"id": "e", "status": "closed", "gone_since": t2, "delisted_at": "2026-10-21T10:00:01+00:00"},
        {"id": "f", "status": "closed", "gone_since": t2, "delisted_at": None, "inventory_status": "sold"},   # source's sold flag
        {"id": "g", "status": "closed", "gone_since": t2, "delisted_at": None, "result_amount": 1200},       # published result
        {"id": "h", "status": "active", "gone_since": None, "delisted_at": None},
        {"id": "i", "status": "dropped", "gone_since": "2026-08-01T00:00:00+00:00", "delisted_at": None},
    ]
    assert SS.plan_delisted(rows) == {t1: ["a", "b"], t2: ["c"]}


def test_stamp_seen_delisted_is_wired_to_both_florida_stamp_steps():
    wf = (REPO / ".github" / "workflows" / "harvest-and-sync.yml").read_text(encoding="utf-8")
    lines = [ln for ln in wf.splitlines() if "stamp_seen.py --state FL" in ln]
    assert len(lines) == 2 and all(ln.rstrip().endswith("--delisted") for ln in lines)
