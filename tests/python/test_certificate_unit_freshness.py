"""Certificate read health (2026-11-04).

LienHub has answered HTTP 403 to every county since 2026-10-01, yet the
certificates job never recorded its per-county reads, so the production
registry held no LienHub unit and the app showed those rows' read health as
"Not recorded". The job now runs scripts/unit_freshness.py on the LienHub and
Sarasota status files; a blocked county is SOURCE_UNAVAILABLE, never current,
and nothing is closed.
"""
from __future__ import annotations

import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]


def _uf():
    spec = importlib.util.spec_from_file_location("unit_freshness_cert", REPO / "scripts" / "unit_freshness.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


BLOCKED = {"county": "Alachua", "status": "FAILED", "error_category": "TRANSPORT_HTTP_403_BLOCKED",
           "transport_ok": False, "rowCount": 0, "reason": "Response status code does not indicate success: 403 (Forbidden)."}


def test_the_certificates_job_records_per_unit_freshness_for_both_sources():
    wf = yaml.safe_load((REPO / ".github/workflows/harvest-and-sync.yml").read_text(encoding="utf-8"))
    steps = wf["jobs"]["certificates"]["steps"]
    names = [s.get("name") or "" for s in steps]
    fresh = next(s for s in steps if (s.get("name") or "").startswith("Per-unit freshness"))
    assert fresh["if"] == "always()" and fresh["continue-on-error"] is True
    run = fresh["run"]
    assert "--status out/harvest_certificates_status.json:fl_lienhub_certificates" in run
    assert "--status out/harvest_sarasota_certificates_status.json" in run
    # Its own persisted record and report - the deeds job's are never overwritten.
    assert "--persist out/.harvest_cache/unit_freshness_certificates.json" in run
    assert "--report out/public/unit-freshness-certificates.json" in run
    # After both syncs (nothing it writes is a property row).
    assert names.index(fresh["name"]) > names.index("Sync to Supabase")
    assert names.index(fresh["name"]) > next(i for i, n in enumerate(names) if n.startswith("Sarasota Tax Collector county-held certificates - sync"))


def test_a_blocked_lienhub_county_is_source_unavailable_and_never_a_success(tmp_path):
    uf = _uf()
    status = tmp_path / "harvest_certificates_status.json"
    # PowerShell writes UTF-8 (possibly with a BOM).
    status.write_text(json.dumps([BLOCKED, dict(BLOCKED, county="Bay")]), encoding="utf-8-sig")
    entries = [uf.normalize_entry(e, default_state="FL", default_source="fl_lienhub_certificates") for e in uf.read_status(status)]
    assert [e["source_id"] for e in entries] == ["fl_lienhub_certificates"] * 2
    prev = {uf.unit_key("FL", "fl_lienhub_certificates", "Alachua"): {
        "state": "FL", "source_id": "fl_lienhub_certificates", "county": "Alachua", "last_success_at": "2026-09-30T12:00:00+00:00",
        "last_success_row_count": 100, "consecutive_failures": 2, "last_attempt_status": "FAILED"}}
    record, counts = uf.merge(prev, entries, at="2026-11-04T11:32:25+00:00")
    assert counts["failed"] == 2 and counts["succeeded"] == 0
    a = record[uf.unit_key("FL", "fl_lienhub_certificates", "Alachua")]
    assert a["last_success_at"] == "2026-09-30T12:00:00+00:00"      # a failure never advances the last success
    assert a["consecutive_failures"] == 3
    now = datetime(2026, 11, 4, 12, tzinfo=timezone.utc)
    assert uf.customer_health(a, now=now)["state"] == "SOURCE_UNAVAILABLE"
    b = record[uf.unit_key("FL", "fl_lienhub_certificates", "Bay")]
    assert b["last_success_at"] is None and uf.customer_health(b, now=now)["state"] == "SOURCE_UNAVAILABLE"
    # Every LienHub county the registry CSV lists is a unit the registry update matches.
    units = uf.registry_units()
    assert all(k in units for k in record)


def test_every_lienhub_county_is_in_the_registry_so_the_update_reaches_production():
    import csv
    uf = _uf()
    reg = uf.registry_units()
    harvester = (REPO / "scripts" / "harvest_lienhub_certificates.ps1").read_text(encoding="utf-8")
    lienhub = [r for r in csv.DictReader(open(REPO / "data" / "county_source_registry.csv", encoding="utf-8"))
               if r["source_id"] == "fl_lienhub_certificates"]
    assert len(lienhub) == 32
    for r in lienhub:
        assert uf.unit_key("FL", "fl_lienhub_certificates", r["county"]) in reg
    assert uf.unit_key("FL", "fl_sarasota_tc_certificates", "Sarasota") in reg
    assert "harvest_certificates_status.json" in harvester


def test_a_single_entry_status_file_is_one_unit(tmp_path):
    """PowerShell's ConvertTo-Json writes a one-element array as a bare
    object; that object is one unit, never zero."""
    uf = _uf()
    p = tmp_path / "s.json"
    p.write_text(json.dumps(BLOCKED), encoding="utf-8")
    assert uf.read_status(p) == [BLOCKED]
    p.write_text(json.dumps({"retrieved_at": "x", "counties": [BLOCKED]}), encoding="utf-8")
    assert uf.read_status(p) == [BLOCKED]
    p.write_text(json.dumps({"something": "else"}), encoding="utf-8")
    assert uf.read_status(p) == []


def test_stale_after_seven_days_without_a_complete_read():
    uf = _uf()
    now = datetime(2026, 11, 4, 12, tzinfo=timezone.utc)
    u = {"source_id": "fl_lienhub_certificates", "last_attempt_status": "COMPLETE",
         "last_success_at": (now - timedelta(days=9)).isoformat(), "last_success_row_count": 4}
    assert uf.customer_health(u, now=now)["state"] == "STALE"


def test_the_card_stamp_names_an_unreadable_or_stale_certificate_source():
    app = (REPO / "public" / "app.js").read_text(encoding="utf-8")
    i = app.index('if (p.source === "certificate") {', app.index("function cardStamp(p)"))
    block = app[i:app.index("return null;\n}", i)]
    assert 'key: "source-unavailable"' in block and 'label: "Source unavailable"' in block
    assert 'key: "source-stale"' in block and 'label: "Not recently read"' in block
    assert "nothing was closed" in block
    assert "try { u = unitForRow(p); }" in block    # TDZ-safe during module start-up
