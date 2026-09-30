"""Louisiana activation (state-expansion sprint, 2026-09-30).

East Baton Rouge Parish's open-data adjudicated-property list is the first
source of a third production state. These tests pin the whole path the
state takes that FL / TX never needed: the sync script for adapter records,
the laft-job steps, and the frontend assets of a third state page - and the
one rule the owner's publication decision rests on: the list is DATED and
is never presented as available now.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(1, str(REPO))

from harvesters.governance import county_source_registry as csr  # noqa: E402
from harvesters.governance import publication as pub  # noqa: E402
from harvesters.governance import states  # noqa: E402
from harvesters.otc.adapters import louisiana as LA  # noqa: E402
import sync_state_inventory as SYNC  # noqa: E402

WF = REPO / ".github/workflows/harvest-and-sync.yml"


def _row(**kw):
    base = {"state": "LA", "source": "laft", "county": "East Baton Rouge", "case_no": "012-3456-7", "source_id": "la_ebr_adjudicated",
            "address": "10 FIXTURE AVE", "bid": 0, "purchase_amount": None, "purchase_amount_kind": "NOT_PUBLISHED",
            "inventory_type": "ADJUDICATED_PROPERTY", "list_as_of": "2024-02-27", "status": "active"}
    base.update(kw)
    return base


# ==================== sync ====================

def test_s01_sync_plan_stamps_the_registry_decision_the_ledger_and_the_source():
    reg = SYNC.registry_rows("LA")
    rows, counts = SYNC.plan("LA", [_row(), _row(case_no="098-7654-3", latitude=30.4)], reg, {"East Baton Rouge": "COMPLETE"})
    assert counts == {"input": 2, "upsert": 2, "skipped_unit_not_read": 0, "wrong_state": 0}
    for r in rows:
        assert r["publication_status"] == "APPROVED" and r["ledger_type"] == "buy" and r["harvester_source"] == "la_ebr_adjudicated"
        assert r["list_as_of"] == "2024-02-27" and r["purchase_amount"] is None
    # PostgREST bulk upsert: one key set for every row; a key absent on a row is sent as NULL.
    assert len({tuple(sorted(r)) for r in rows}) == 1 and rows[0]["latitude"] is None and rows[1]["latitude"] == 30.4


def test_s02_sync_syncs_nothing_for_a_unit_that_was_not_read_and_refuses_unactivated_states():
    reg = SYNC.registry_rows("LA")
    for status in ({}, {"East Baton Rouge": "FAILED"}, {"East Baton Rouge": "EMPTY"}):
        rows, counts = SYNC.plan("LA", [_row()], reg, status)
        assert rows == [] and counts["skipped_unit_not_read"] == 1
    rows, counts = SYNC.plan("LA", [_row(state="FL")], reg, {"East Baton Rouge": "COMPLETE"})
    assert rows == [] and counts["wrong_state"] == 1
    with pytest.raises(ValueError, match="not activated"):
        SYNC.plan("AR", [], SYNC.registry_rows("AR"), {})
    with pytest.raises(ValueError, match="not a production, governance-approved"):
        SYNC.plan("LA", [_row(source_id="la_unknown")], reg, {"East Baton Rouge": "COMPLETE"})


def test_s03_sync_reads_the_harvesters_own_status_file_shape(tmp_path):
    p = tmp_path / "s.json"
    p.write_text(json.dumps([{"county": "East Baton Rouge", "state": "LA", "status": "COMPLETE", "harvester": "la_ebr_adjudicated"}]))
    assert SYNC.status_units(p) == {"East Baton Rouge": "COMPLETE"}
    assert SYNC.status_units(tmp_path / "missing.json") == {}


def test_s04_dry_run_makes_no_request_and_a_missing_credential_refuses(tmp_path, monkeypatch):
    rows = tmp_path / "r.json"
    rows.write_text(json.dumps([_row()]))
    status = tmp_path / "s.json"
    status.write_text(json.dumps([{"county": "East Baton Rouge", "state": "LA", "status": "COMPLETE"}]))
    monkeypatch.setattr(SYNC, "upsert", lambda *a, **k: pytest.fail("no request in dry-run / without credentials"))
    assert SYNC.main(["--state", "LA", "--rows", str(rows), "--status", str(status), "--dry-run"]) == 0
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_KEY", raising=False)
    assert SYNC.main(["--state", "LA", "--rows", str(rows), "--status", str(status)]) == 2


# ==================== governance ====================

def test_g01_the_registry_row_is_the_owner_decision_on_the_live_evidence():
    row = csr.lookup(csr.load_registry(), "LA", "East Baton Rouge")
    assert row.is_production and row.runnable and row.governance_status == "APPROVED"
    assert pub.effective_publication(row) == "APPROVED" and pub.publication_problems(row) == []
    assert "never as available now" in row.restrictions and "2024-02-27" in row.restrictions
    assert "36752875012" in row.evidence_ref and "PUBLIC_DOMAIN" in row.evidence_ref
    assert row.publishing_unit == "PARISH" and row.amount_kind == "NOT_PUBLISHED" and not row.purchase_url
    # Coverage is exactly one parish; nothing else in LA is runnable.
    assert [r.source_id for r in csr.load_registry() if r.state == "LA"] == ["la_ebr_adjudicated"]
    assert states.PRODUCTION_STATES == frozenset({"FL", "TX", "LA"})
    assert LA.APPROVED_LICENSE_ID == "PUBLIC_DOMAIN"


# ==================== workflow ====================

def test_w01_louisiana_runs_in_the_existing_laft_job_after_florida_and_can_never_fail_it():
    wf = yaml.safe_load(WF.read_text(encoding="utf-8"))
    on = wf.get("on") or wf.get(True)
    assert on["schedule"] == [{"cron": "0 10 * * *"}, {"cron": "0 22 * * *"}, {"cron": "0 12 * * *"}]   # unchanged
    steps = wf["jobs"]["laft"]["steps"]
    names = [s.get("name", "") for s in steps]
    la = [i for i, n in enumerate(names) if n.startswith("Louisiana")]
    fl_gate = names.index("Publication gate (source-level customer publication, migration 022)")
    assert len(la) == 4 and min(la) > fl_gate
    for i in la:
        assert steps[i].get("continue-on-error") is True and str(steps[i].get("if", "")).startswith("always()"), names[i]
    runs = " ".join(steps[i]["run"] for i in la)
    assert "harvest_state_inventory.py --state LA" in runs and "sync_state_inventory.py --state LA" in runs
    assert "laft_lifecycle.py --state LA --status out/harvest_louisiana_status.json --harvest out/harvest_louisiana.json" in runs
    assert "publication-gate-la.json" in runs and "unit-freshness-la.json" in runs     # Florida's reports are never overwritten
    # Texas / LGBS untouched: the texas job is still manual-only and names no Louisiana step.
    assert "Louisiana" not in json.dumps(wf["jobs"]["texas"]) and "harvest_state_inventory" not in json.dumps(wf["jobs"]["texas"])


# ==================== frontend ====================

def test_f01_a_third_state_page_with_its_own_assets():
    app = (REPO / "public/app.js").read_text(encoding="utf-8")
    assert re.search(r'LA: \{ name: "Louisiana", page: "la\.html", basemap: "la-parishes\.svg".*unit: "Parish"', app)
    assert "LA: { x: { lon: 0.175438596" in app
    assert 'LA: { basemap: "la-parishes.svg"' in (REPO / "public/explore.js").read_text(encoding="utf-8")
    assert "LA: { center: [-91.9, 31.0]" in (REPO / "public/satellite-map.js").read_text(encoding="utf-8")
    html = (REPO / "public/la.html").read_text(encoding="utf-8")
    assert '<body data-state="LA">' in html and "<title>Tax Acquisitions — Louisiana</title>" in html
    for page in ("index.html", "tx.html", "la.html"):
        text = (REPO / "public" / page).read_text(encoding="utf-8")
        # One header state selector per page (options built from STATE_META, which carries LA).
        assert text.count('<select id="stateSelect" aria-label="State"></select>') == 1 and "data-state-link" not in text, page
    sw = (REPO / "public/sw.js").read_text(encoding="utf-8")
    assert '"/la.html",' in sw and '"/la-parishes.svg",' in sw and 'isLa ? "/la.html"' in sw
    for f in ("la.html", "la-parishes.svg"):
        assert (REPO / f).read_text(encoding="utf-8") == (REPO / "public" / f).read_text(encoding="utf-8"), f


def test_f02_the_parish_basemap_and_centroids_agree_on_all_64_parishes():
    svg = (REPO / "public/la-parishes.svg").read_text(encoding="utf-8")
    names = re.findall(r'<path data-county="([^"]+)"', svg)
    cent = json.loads((REPO / "public/county-centroids.json").read_text(encoding="utf-8"))
    assert len(names) == 64 and set(names) == set(cent["LA"]) and "East Baton Rouge" in names
    assert cent["LA"]["East Baton Rouge"]["fips"] == "22033"
    assert 'viewBox="0 0 1000 901"' in svg and 'id="laMap"' in svg
    # The adapter's county value is a basemap parish name, exactly.
    assert LA.EBR_SOURCE.county in names


def test_f03_the_dated_list_is_never_called_available_now():
    app = (REPO / "public/app.js").read_text(encoding="utf-8")
    assert 'const isDatedList = p => p && p.source === "laft" && p.inventory_type === "ADJUDICATED_PROPERTY";' in app
    # Every availability statement branches on it before the Florida "available now" wording.
    kicker = app[app.index("  else if (p.source === \"laft\") {"):]
    assert kicker.index("isDatedList(p)") < kicker.index('"Lands Available list · fixed price"')
    when = app[app.index('else if (isLaft && txStatus)'):]
    assert when.index("isDatedList(p)") < when.index('"Available now - no auction date"')
    assert "Not verified as available now - on the Parish's adjudicated-property list as of" in app
    assert 'ADJUDICATED_PROPERTY: "Adjudicated to the parish after no one bought it at the tax sale (Louisiana)"' in app
    assert 'PAGE_STATE === "LA" ? "Adjudicated property - the Parish\'s list as of its own last-update date, not verified available now"' in app
