"""scripts/laft_lifecycle.py - last_seen_at, gated close-out, reactivation.

Three layers:
  1. The pure decision layer (plan_lifecycle) on the six scenarios the
     brief names, plus row identity and amount rules.
  2. An end-to-end run of the real script against a fake PostgREST
     (http.server in a thread) - once with migration 017 present, once
     without - asserting exactly which PATCHes are sent.
  3. Structural checks on the two PowerShell scripts (no pwsh here, same
     constraint as test_phase30b) and the workflow wiring.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
import laft_lifecycle as L  # noqa: E402
import laft_source_fields as SF  # noqa: E402
import laft_status as ls  # noqa: E402

NOW = ls.now_iso()


def _gates(**county_status):
    entries = []
    for county, status in county_status.items():
        e = {"county": county, "harvester": "h", "status": status, "checked_at": NOW,
             "source_url": f"https://{county.lower()}", "source_class": "GOVERNMENT_DIRECT", "source_id": "fl_laft_pdfs"}
        if status == "EMPTY":
            e["empty_signal"] = "empty_marker"
        if status in ("FAILED", "INCOMPLETE"):
            e["error_category"] = "UNCONFIRMED_EMPTY"
        entries.append(e)
    return L.county_gates(entries, [])


def _db(*rows):
    return [{"id": i + 1, "county": c, "case_no": k, "status": s} for i, (c, k, s) in enumerate(rows)]


# ==================== 1. decision layer: the six scenarios ====================


def test_d01_complete_source_and_previously_seen_property_absent_is_closed():
    plan = L.plan_lifecycle(_gates(Marion="COMPLETE"), L.observed_by_county([{"county": "Marion", "case_no": "A"}]),
                            _db(("Marion", "A", "active"), ("Marion", "B", "active")))
    assert plan.observe == [("Marion", "A")]
    assert [(r["county"], r["case_no"]) for r in plan.close] == [("Marion", "B")]


def test_d02_incomplete_source_and_property_absent_remains_active():
    plan = L.plan_lifecycle(_gates(Marion="INCOMPLETE"), L.observed_by_county([{"county": "Marion", "case_no": "A"}]),
                            _db(("Marion", "A", "active"), ("Marion", "B", "active")))
    assert plan.observe == [("Marion", "A")]   # what WAS read is still an observation
    assert plan.close == [] and plan.skipped_counties == {"Marion": "INCOMPLETE"}


def test_d03_failed_source_and_property_absent_remains_active():
    plan = L.plan_lifecycle(_gates(Union="FAILED"), L.observed_by_county([]), _db(("Union", "U1", "active")))
    assert plan.close == [] and plan.observe == [] and plan.skipped_counties == {"Union": "FAILED"}


def test_d04_explicit_empty_authoritative_list_closes_previously_seen_property():
    plan = L.plan_lifecycle(_gates(Glades="EMPTY"), L.observed_by_county([]), _db(("Glades", "G1", "active")))
    assert [(r["county"], r["case_no"]) for r in plan.close] == [("Glades", "G1")]


def test_d05_reappearance_of_a_closed_property_reactivates():
    plan = L.plan_lifecycle(_gates(Marion="COMPLETE"), L.observed_by_county([{"county": "Marion", "case_no": "A"}]),
                            _db(("Marion", "A", "closed")))
    assert plan.reactivate == [("Marion", "A")] and plan.close == []


def test_d06_last_seen_changes_only_from_actual_observation():
    # A row present in the DB but absent from every harvest file is never
    # "observed"; a harvested row from a FAILED/STALE/NOT_RUN county is not
    # an observation either.
    gates = L.county_gates([{"county": "Old", "harvester": "h", "status": "COMPLETE", "checked_at": "2026-09-01T00:00:00+00:00"}],
                           [("fl_laft_pioneer", "Walton")])
    plan = L.plan_lifecycle(gates, L.observed_by_county([{"county": "Old", "case_no": "O1"}, {"county": "Walton", "case_no": "W1"}]),
                            _db(("Old", "O1", "active"), ("Walton", "W1", "active"), ("Old", "O2", "active")))
    assert plan.observe == [] and plan.ignored_rows == 2 and plan.close == []
    assert plan.skipped_counties == {"Old": "STALE", "Walton": "NOT_RUN"}


def test_d07_close_out_ignores_already_gone_rows_and_uses_the_syncs_identity_rule():
    plan = L.plan_lifecycle(_gates(Marion="COMPLETE"), L.observed_by_county([{"county": "Marion", "parcel": "P-1"}]),
                            _db(("Marion", "P-1", "active"), ("Marion", "X", "closed"), ("Marion", "Y", "sold")))
    assert plan.observe == [("Marion", "P-1")] and plan.close == []
    assert L.identity_key({"county": "M", "case_no": "", "parcel": ""}) is None
    assert L.identity_key({"county": "M", "case_no": "C", "parcel": "P"}) == ("M", "C")


def test_d08_missing_status_file_closes_nothing():
    gates = L.county_gates([], [("fl_laft_pdfs", "Marion")])
    plan = L.plan_lifecycle(gates, L.observed_by_county([{"county": "Marion", "case_no": "A"}]), _db(("Marion", "B", "active")))
    assert plan.close == [] and plan.observe == [] and plan.skipped_counties == {"Marion": "NOT_RUN"}


def test_d09_amount_semantics_never_zero():
    assert L.amount_of({"bid": ""}) == (None, "NOT_PUBLISHED")
    assert L.amount_of({}) == (None, "NOT_PUBLISHED")
    assert L.amount_of({"bid": "n/a"}) == (None, "NOT_PUBLISHED")
    assert L.amount_of({"bid": "$1,234.50", "bid_kind": "OPENING_BID"}) == (1234.5, "OPENING_BID")
    assert L.amount_of({"bid": "12"}) == (12.0, "PUBLISHED_AMOUNT_KIND_UNSPECIFIED")
    assert L.amount_of({"bid": "12", "bid_kind": "NOT_PUBLISHED"}) == (12.0, "PUBLISHED_AMOUNT_KIND_UNSPECIFIED")
    assert L.amount_of({"bid": "0"}) == (0.0, "PUBLISHED_AMOUNT_KIND_UNSPECIFIED")  # a literal 0 in the source is kept as read


def test_d10_provenance_payload_comes_from_the_status_entry_and_row_only():
    gate = _gates(Marion="COMPLETE")["Marion"]
    gate["entry"].update({"document_url": "https://marion/x.pdf", "document_sha256": "abc", "checked_at": NOW})
    p = L.provenance_payload({"county": "Marion", "case_no": "A", "url_auction": "https://marion/x.pdf"}, gate, NOW)
    assert p["inventory_type"] == "POST_SALE_FIXED_PRICE" and p["source_authority"] == "GOVERNMENT_DIRECT"
    assert p["source_id"] == "fl_laft_pdfs" and p["list_url"] == "https://marion" and p["document_url"] == "https://marion/x.pdf"
    assert p["purchase_amount"] is None and p["purchase_amount_kind"] == "NOT_PUBLISHED"
    assert p["source_document_sha256"] == "abc" and p["last_seen_at"] == NOW
    assert "purchase_url" not in p  # a list page is never a purchase URL; none is invented
    assert p["otc_provenance"]["retrieved_at"] == NOW
    groups = L.group_provenance([("A", {"bid": "5", "bid_kind": "OPENING_BID"}), ("B", {"bid": "5", "bid_kind": "OPENING_BID"}), ("C", {})], gate, NOW)
    assert sorted(len(keys) for _, keys in groups) == [1, 2]


# ==================== 2. end to end against a fake PostgREST ====================


class _Store:
    def __init__(self, rows, have_017, have_019=False):
        self.rows = rows
        self.have_017 = have_017
        self.have_019 = have_019
        self.patches: list[tuple[str, dict]] = []


def _server(store):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, body=b"[]"):
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            u = urlparse(self.path)
            qs = parse_qs(u.query)
            assert self.headers.get("User-Agent", "").startswith("taxdeed-scraper/")
            sel = qs.get("select", [""])[0]
            if "limit" in qs and "county" not in qs:
                # Column probes: 017 (lifecycle columns) and 019 (list dates).
                present = store.have_017 if "last_seen_at" in sel else store.have_019
                if present:
                    return self._send(200, b"[]")
                return self._send(400, json.dumps({"code": "42703", "message": f"column properties.{sel.split(',')[0]} does not exist"}).encode())
            assert qs.get("state") == ["eq.FL"] and qs.get("source") == ["eq.laft"], self.path
            counties = unquote(qs["county"][0])[len("in.("):-1].replace('"', "").split(",")
            self._send(200, json.dumps([r for r in store.rows if r["county"] in counties]).encode())

        def do_PATCH(self):
            n = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(n) or b"{}")
            store.patches.append((unquote(self.path), body))
            self._send(204, b"")

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv


def _run_script(tmp_path, store, *, dry_run=False, harvest_rows=None):
    srv = _server(store)
    try:
        status = tmp_path / "status.json"
        status.write_text(json.dumps([
            {"county": "Marion", "harvester": "fl_laft_pdfs", "status": "COMPLETE", "checked_at": NOW, "row_count": 2,
             "source_url": "https://marion/page", "document_url": "https://marion/list.pdf", "source_class": "GOVERNMENT_DIRECT",
             "source_id": "fl_laft_pdfs", "document_sha256": "deadbeef"},
            {"county": "Glades", "harvester": "fl_laft_pdfs", "status": "EMPTY", "checked_at": NOW, "empty_signal": "empty_marker"},
            {"county": "Union", "harvester": "fl_laft_html", "status": "FAILED", "checked_at": NOW, "error_category": "PROXY_FAILURE"},
        ]))
        harvest = tmp_path / "harvest_laft.json"
        harvest.write_text(json.dumps(harvest_rows if harvest_rows is not None else [
            {"county": "Marion", "case_no": "A", "bid": "1,200.00", "bid_kind": "MINIMUM_PURCHASE_AMOUNT", "owner_name": "Private Person", "address": "9 Hidden Ln"},
            {"county": "Marion", "parcel": "P-2"},
            {"county": "Union", "case_no": "U1"},
        ]))
        registry = tmp_path / "registry.csv"
        registry.write_text("state,county,source_id,verification_status\nFL,Marion,fl_laft_pdfs,PRODUCTION_VERIFIED\nFL,Walton,fl_laft_pioneer,PRODUCTION_VERIFIED\nTX,Galveston,tx_lgbs,PRODUCTION_VERIFIED\n")
        report = tmp_path / "public" / "laft-lifecycle.json"
        env = dict(os.environ, SUPABASE_URL=f"http://127.0.0.1:{srv.server_port}", SUPABASE_SERVICE_KEY="sb_secret_test",
                   GITHUB_STEP_SUMMARY=str(tmp_path / "summary.md"))
        args = [sys.executable, str(REPO / "scripts/laft_lifecycle.py"), "--status", str(status), "--registry", str(registry),
                "--harvest", str(harvest), "--report", str(report)]
        if dry_run:
            args.append("--dry-run")
        r = subprocess.run(args, capture_output=True, text=True, env=env, cwd=tmp_path)
        return r, report
    finally:
        srv.shutdown()


DB = [
    {"id": "id-a", "county": "Marion", "case_no": "A", "status": "closed"},
    {"id": "id-p2", "county": "Marion", "case_no": "P-2", "status": "active"},
    {"id": "id-gone", "county": "Marion", "case_no": "GONE", "status": "active"},
    {"id": "id-g1", "county": "Glades", "case_no": "G1", "status": "active"},
    {"id": "id-u9", "county": "Union", "case_no": "U9", "status": "active"},
    {"id": "id-w1", "county": "Walton", "case_no": "W1", "status": "active"},
]


def test_e01_with_migration_017_observed_rows_get_last_seen_and_provenance_absent_rows_close(tmp_path):
    store = _Store([dict(r) for r in DB], have_017=True)
    r, report = _run_script(tmp_path, store)
    assert r.returncode == 0, r.stderr + r.stdout
    kinds = {}
    for path, body in store.patches:
        kinds.setdefault(tuple(sorted(body)), []).append((path, body))
    # Reactivation of the closed, re-listed row A.
    react = [(p, b) for p, b in store.patches if b == {"status": "active"}]
    assert len(react) == 1 and 'case_no=in.("A")' in react[0][0] and "county=eq.Marion" in react[0][0]
    # Provenance/last_seen for the two observed Marion rows (two payloads: one priced, one not).
    prov = [(p, b) for p, b in store.patches if "last_seen_at" in b]
    assert len(prov) == 2
    priced = next(b for p, b in prov if b["purchase_amount"] is not None)
    unpriced = next(b for p, b in prov if b["purchase_amount"] is None)
    assert priced["purchase_amount"] == 1200.0 and priced["purchase_amount_kind"] == "MINIMUM_PURCHASE_AMOUNT"
    assert unpriced["purchase_amount_kind"] == "NOT_PUBLISHED"
    for b in (priced, unpriced):
        assert b["inventory_type"] == "POST_SALE_FIXED_PRICE" and b["source_authority"] == "GOVERNMENT_DIRECT"
        assert b["source_id"] == "fl_laft_pdfs" and b["list_url"] == "https://marion/page" and b["document_url"] == "https://marion/list.pdf"
        assert b["source_document_sha256"] == "deadbeef" and "purchase_url" not in b
    for p, _ in prov:
        assert "state=eq.FL" in p and "source=eq.laft" in p and "county=eq.Marion" in p
    # Close-out: Marion GONE (COMPLETE) and Glades G1 (EMPTY) only - never Union (FAILED) or Walton (NOT_RUN).
    closes = [(p, b) for p, b in store.patches if b.get("status") == "closed"]
    assert len(closes) == 1 and "id-gone" in closes[0][0] and "id-g1" in closes[0][0]
    assert "id-u9" not in closes[0][0] and "id-w1" not in closes[0][0] and "id-p2" not in closes[0][0]
    assert closes[0][1]["delisted_at"]
    # Public outputs never carry a row value.
    text = r.stdout + (tmp_path / "summary.md").read_text() + report.read_text()
    assert "Private Person" not in text and "Hidden Ln" not in text and "1,200" not in text and "1200" not in text
    rep = json.loads(report.read_text())
    assert rep == {**rep, "observed": 2, "reactivated": 1, "closed": 2, "provenance_patches": 2, "migration_017": True, "dry_run": False}
    assert rep["counties"] == {"Marion": "COMPLETE", "Glades": "EMPTY", "Union": "FAILED", "Walton": "NOT_RUN"}
    assert "Galveston" not in rep["counties"]  # a Texas registry row never enters the Florida run


def test_e02_without_migration_017_only_status_is_written_and_the_script_says_so(tmp_path):
    store = _Store([dict(r) for r in DB], have_017=False)
    r, report = _run_script(tmp_path, store)
    assert r.returncode == 0, r.stderr + r.stdout
    assert "migration 017 not applied" in r.stdout
    bodies = [b for _, b in store.patches]
    # No 017 column is ever sent; the county-list carry (independent of 017,
    # see test_e04) may still write its own fill-blank columns.
    carry = set(SF.BASE_COLUMNS) | {"field_provenance"}
    assert all(set(b) <= {"status"} or set(b) <= carry for b in bodies), bodies
    assert {"status": "active"} in bodies and {"status": "closed"} in bodies
    assert json.loads(report.read_text())["migration_017"] is False


def test_e03_dry_run_sends_no_patch_and_missing_status_file_closes_nothing(tmp_path):
    store = _Store([dict(r) for r in DB], have_017=True)
    r, report = _run_script(tmp_path, store, dry_run=True)
    assert r.returncode == 0 and store.patches == [] and json.loads(report.read_text())["dry_run"] is True
    r2 = subprocess.run([sys.executable, str(REPO / "scripts/laft_lifecycle.py"), "--status", str(tmp_path / "nope.json"),
                         "--harvest", str(tmp_path / "harvest_laft.json"), "--report", str(tmp_path / "r.json")],
                        capture_output=True, text=True, env={k: v for k, v in os.environ.items() if not k.startswith("SUPABASE")}, cwd=tmp_path)
    assert r2.returncode == 0 and "not found" in r2.stdout and "close-out candidates: 0" in r2.stdout


def test_e04_county_list_fields_are_carried_fill_blank_with_provenance_on_observed_rows_only(tmp_path):
    """Marion A: owner_name blank in the DB -> written from the list, with a
    county_list provenance entry; legal_desc already on file (tax roll) ->
    left alone; Union U1 (FAILED county) -> never touched; the 019 date
    columns are absent -> never sent."""
    rows = [dict(r) for r in DB]
    rows[0]["legal_desc"] = "LOT 1 BLK 2 (tax roll)"
    rows[0]["field_provenance"] = {"legal_desc": {"source": "fdor_nal", "recorded_at": NOW}}
    store = _Store(rows, have_017=True, have_019=False)
    harvest = [
        {"county": "Marion", "case_no": "A", "owner_name": "Private Person", "legal_desc": "LOT 1 BLK 2 PLAT 9 (list)",
         "certificate_no": "2019-0042", "homestead": "N", "escheatment_date": "07/01/2029", "assessed": "$12,500"},
        {"county": "Marion", "parcel": "P-2"},
        {"county": "Union", "case_no": "U1", "owner_name": "Nobody"},
    ]
    r, report = _run_script(tmp_path, store, harvest_rows=harvest)
    assert r.returncode == 0, r.stderr + r.stdout
    carry = [(p, b) for p, b in store.patches if "field_provenance" in b]
    assert len(carry) == 1 and carry[0][0].endswith("id=eq.id-a")
    body = carry[0][1]
    assert body["owner_name"] == "Private Person" and body["certificate_no"] == "2019-0042" and body["assessed"] == 12500.0
    assert "legal_desc" not in body and "homestead" not in body and "escheatment_date" not in body
    prov = body["field_provenance"]
    assert prov["legal_desc"] == {"source": "fdor_nal", "recorded_at": NOW}  # kept verbatim
    for col in ("owner_name", "certificate_no", "assessed"):
        assert prov[col]["source"] == "county_list" and prov[col]["source_id"] == "fl_laft_pdfs"
        assert prov[col]["list_url"] == "https://marion/page" and prov[col]["document_sha256"] == "deadbeef"
    assert not any("id-u9" in p or "id-u1" in p for p, _ in carry)
    rep = json.loads(report.read_text())
    assert rep["migration_019"] is False
    assert rep["source_fields"] == {**rep["source_fields"], "matched": 2, "unmatched": 0, "ambiguous": 0, "written_rows": 1,
                                    "nothing_to_write": 1, "errored": 0, "fields_written": {"assessed": 1, "certificate_no": 1, "owner_name": 1},
                                    "skipped_present": {"legal_desc": 1}}
    text = r.stdout + (tmp_path / "summary.md").read_text() + report.read_text()
    assert "Private Person" not in text and "2019-0042" not in text and "12,500" not in text and "12500" not in text


def test_e05_migration_019_dates_are_written_only_when_the_columns_exist(tmp_path):
    store = _Store([dict(r) for r in DB], have_017=True, have_019=True)
    harvest = [{"county": "Marion", "case_no": "A", "escheatment_date": "07/01/2029", "available_date": "2026-09-01"},
               {"county": "Marion", "parcel": "P-2", "escheatment_date": "not a date"}]
    r, report = _run_script(tmp_path, store, harvest_rows=harvest)
    assert r.returncode == 0, r.stderr + r.stdout
    carry = [(p, b) for p, b in store.patches if "field_provenance" in b]
    assert len(carry) == 1 and carry[0][0].endswith("id=eq.id-a")
    assert carry[0][1]["escheatment_date"] == "2029-07-01" and carry[0][1]["available_date"] == "2026-09-01"
    rep = json.loads(report.read_text())
    assert rep["migration_019"] is True and rep["source_fields"]["unparseable"] == {"escheatment_date": 1}
    # Currentness columns ride on the provenance PATCH, from the source's own statements only.
    prov = [b for _, b in store.patches if "last_seen_at" in b]
    assert prov and all(b["list_as_of"] is None and b["source_published_at"] is None for b in prov)


# ==================== 3. structural: PowerShell + workflow ====================


def test_s01_sanity_check_is_state_filtered():
    src = (REPO / "scripts/sanity_check_laft.ps1").read_text(encoding="utf-8")
    # One state per run, from $env:LAFT_STATE, defaulting to FL - never an
    # unfiltered cross-state query, never an arbitrary string in the URL.
    assert "properties?state=eq.$State&source=eq.laft&select=county" in src
    assert 'IsNullOrWhiteSpace($env:LAFT_STATE)) { "FL" }' in src
    assert "$State -notmatch '^[A-Z]{2}$'" in src and "throw" in src.split("$State -notmatch")[1].split("\n")[1]
    assert "properties?source=eq.laft&select=county" not in src
    assert "state=eq.FL" not in src.split("$existingUrl")[1]


def test_s02_sync_reactivates_on_upsert_and_never_writes_closed():
    src = (REPO / "scripts/sync-laft-to-supabase.ps1").read_text(encoding="utf-8")
    row_block = src[src.index("$row = [ordered]@{"):src.index("$row[\"parcel\"]")]
    assert 'status      = "active"' in row_block
    assert '"closed"' not in src and "delisted_at" not in src and "last_seen_at" not in src.split("scripts/laft_lifecycle.py")[0].split("purchase_amount")[0]
    # The 0 sentinel is still written for `bid` (NOT NULL column) and documented as legacy.
    assert "if ($null -eq $bidVal) { $bidVal = 0 }" in src


def test_s03_workflow_wires_status_file_lifecycle_and_changes_no_schedule():
    wf = yaml.safe_load((REPO / ".github/workflows/harvest-and-sync.yml").read_text(encoding="utf-8"))
    steps = wf["jobs"]["laft"]["steps"]
    names = [s.get("name", "") for s in steps]
    evidence = next(s for s in steps if "artifact_evidence.py" in str(s.get("run")))
    assert "--status out/harvest_laft_status.json" in evidence["run"]
    health = next(s for s in steps if "source_health.py" in str(s.get("run")))
    assert "--status out/harvest_laft_status.json" in health["run"] and "--rows" not in health["run"]
    sync_i = next(i for i, s in enumerate(steps) if s.get("id") == "sync")
    health_i = next(i for i, s in enumerate(steps) if "source_health.py" in str(s.get("run")))
    life_i = next(i for i, s in enumerate(steps) if "laft_lifecycle.py" in str(s.get("run")))
    assert health_i == sync_i + 1 and life_i == health_i + 1
    life = steps[life_i]
    assert life["if"] == "always() && steps.sync.outcome == 'success'"
    assert "harvest_laft_" not in life["run"] and "SUPABASE_SERVICE_KEY" in json.dumps(life["env"])
    # The lifecycle never runs before the upsert, never in another job.
    for job, spec in wf["jobs"].items():
        for s in spec["steps"]:
            if "laft_lifecycle.py" in str(s.get("run", "")):
                assert job == "laft"
    raw = (REPO / ".github/workflows/harvest-and-sync.yml").read_text(encoding="utf-8")
    assert raw.count("cron:") == 3 and "cron: '0 12 * * *'" in raw
    texas = raw[raw.index("  texas:"):raw.index("\n  backup:")]
    assert "if: github.event_name == 'workflow_dispatch'" in texas and "laft_lifecycle" not in texas
    assert names.index("Sync to Supabase") < names.index("Record source health")
