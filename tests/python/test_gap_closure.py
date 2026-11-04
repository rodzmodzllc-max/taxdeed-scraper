"""Final backend completion sprint (2026-10-11): the gaps closed from
repository data and the contracts they must keep.

  * B1  the three scheduled per-state whole-population reads page by KEYSET
        (scripts/rest_pages), never by offset: 2026-10-10 run 38070616741
        hit HTTP 500 on the offset read (LA / WY sync, WY change detection);
  * B2  stamp_seen carries the two list columns the PowerShell syncs drop
        (RealAuction certificate number -> certificate_no, LienHub legal
        description -> legal_desc) FILL-BLANK under the provenance precedence,
        idempotently, with a vendor_listing entry per carried column;
  * A1  the DLBA Vacant Land Policy (an official document read and hashed) is
        a verified evidence row: MI Wayne lots NEEDS_REVIEW -> VERIFIED;
  * A2  every applicable verified evidence row has its county PROCEDURE rule
        (acquisition_procedure_<ledger>), generated, never invented, pinned by
        the builder's --check; the engine's county coverage counts them;
  * the gap queue is generated from the records and pinned by --check;
  * contracts: a bare homepage / search page never qualifies, a rule is never
    VERIFIED without a read source, a NOT_VERIFIED zero is never 'verified
    empty', a stale read is never current, direct_property_url never comes
    from the evidence table, an UNREVIEWED source is never customer-approved.
"""
from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from harvesters.governance import gap_queue as GQ, procedure_rules as PR, state_coverage as SC, state_rules as SR  # noqa: E402
from harvesters.governance import state_verification as SV  # noqa: E402
import detect_property_changes as DPC  # noqa: E402
import inventory_status_writer as ISW  # noqa: E402
import laft_purchase_paths as PP  # noqa: E402
import publication_gate as PG  # noqa: E402
import purchase_path_engine as PPE  # noqa: E402
import rest_pages as RP  # noqa: E402
import stamp_seen as SS  # noqa: E402

ACQ = json.loads((ROOT / "public/acquisition-evidence.json").read_text(encoding="utf-8"))


# ------------------------------------------------------------------ B1 keyset reads

def _capture_read_all(monkeypatch):
    calls = []

    def fake(base, table, headers, params, **kw):
        calls.append({"base": base, "table": table, "headers": headers, "params": dict(params)})
        return [{"id": "a"}, {"id": "b"}]
    monkeypatch.setattr(RP, "read_all", fake)
    return calls


def test_change_detection_reads_the_population_by_keyset(monkeypatch):
    calls = _capture_read_all(monkeypatch)
    api = DPC.Api("https://x.example/", "k")
    rows = api.population("properties", {"select": DPC.SELECT, "state": "eq.WY", "source": "eq.laft"})
    assert [r["id"] for r in rows] == ["a", "b"]
    c = calls[0]
    assert c["base"] == "https://x.example" and c["table"] == "properties"
    assert c["params"]["state"] == "eq.WY" and c["params"]["source"] == "eq.laft"
    assert "id" in c["params"]["select"].split(",") and not ({"order", "limit", "offset"} & set(c["params"]))
    assert c["headers"]["apikey"] == "k"


def test_inventory_status_and_publication_gate_read_by_keyset(monkeypatch):
    calls = _capture_read_all(monkeypatch)
    api = ISW.Api("https://x.example", "k")
    assert len(ISW.fetch_rows(api, "MI", with_results=True)) == 2
    assert calls[-1]["params"]["state"] == "eq.MI" and "result_amount" in calls[-1]["params"]["select"] and api.requests_made >= 1
    api2 = PG.Api("https://x.example", "k", dry_run=True)
    assert len(PG.fetch_rows(api2, "LA")) == 2
    assert calls[-1]["params"] == {"select": PG.SELECT, "state": "eq.LA", "source": "eq.laft"}
    for c in calls:
        assert not ({"order", "limit", "offset"} & set(c["params"]))


def test_no_offset_paging_remains_in_the_scheduled_population_readers():
    for name, marker in (("detect_property_changes.py", "def population"), ("inventory_status_writer.py", "def fetch_rows"),
                         ("publication_gate.py", "def fetch_rows")):
        src = (ROOT / "scripts" / name).read_text(encoding="utf-8")
        body = src[src.index(marker):]
        body = body[:body.index("\ndef ", 10)]
        assert "RP.read_all(" in body and "offset=" not in body and "&offset" not in body, name
    # change detection's properties read goes through the keyset method
    src = (ROOT / "scripts/detect_property_changes.py").read_text(encoding="utf-8")
    assert 'api.population("properties"' in src and 'api.paged(f"properties' not in src


# ------------------------------------------------------------------ B2 carried list columns

def test_carry_columns_are_the_two_dropped_list_columns_and_markup_is_stripped():
    assert SS.CARRY_COLUMNS == {"auction": {"cert": "certificate_no"}, "certificate": {"legal_desc": "legal_desc"}}
    assert not (set(SS.CARRY_COLUMNS["auction"]) & set(SS.PROVENANCE_COLUMNS["auction"]))      # carried, not blindly provenanced
    assert SS.clean_value("<b> 2023-00123 </b>") == "2023-00123" and SS.clean_value("  ") is None and SS.clean_value(None) is None


def test_carry_fills_blanks_only_never_a_higher_ranked_value_and_is_idempotent():
    rows = [{"county": "Alachua", "case": "C1", "cert": "<i>2023-00123</i>", "bid": "100"},
            {"county": "Alachua", "case": "C2", "cert": "", "bid": "5"},
            {"county": "Baker", "case": "C9", "cert": "2020-1"}]
    stored = [{"id": 1, "case_no": "C1", "field_provenance": None, "certificate_no": None},
              {"id": 2, "case_no": "C2", "field_provenance": None, "certificate_no": None},
              {"id": 3, "case_no": "C1", "field_provenance": {"certificate_no": {"source": "hand_research", "recorded_at": "x"}}, "certificate_no": "HAND"},
              {"id": 4, "case_no": "C7", "field_provenance": None, "certificate_no": None}]
    plan = dict(SS.plan_carry(rows, stored, source="auction", county="Alachua", case_key="case", recorded_at="2026-10-11T00:00:00Z"))
    assert set(plan) == {1}                                     # 2: blank in the list; 3: hand-researched; 4: not read; Baker: other county
    assert plan[1]["certificate_no"] == "2023-00123"
    assert plan[1]["field_provenance"]["certificate_no"] == {"source": "vendor_listing", "recorded_at": "2026-10-11T00:00:00Z", "source_id": "fl_realauction"}
    stored[0].update(plan[1])
    assert SS.plan_carry(rows, stored, source="auction", county="Alachua", case_key="case", recorded_at="2026-10-12T00:00:00Z") == []
    # LienHub's legal description never replaces an FDOR (rank 2) value
    crow = [{"county": "Baker", "case_no": "A1", "legal_desc": "LOT 1 BLK 2"}, {"county": "Baker", "case_no": "A2", "legal_desc": "LOT 9"}]
    cst = [{"id": 9, "case_no": "A1", "field_provenance": {"legal_desc": {"source": "fdor_nal", "recorded_at": "x"}}, "legal_desc": "FDOR LEGAL"},
           {"id": 8, "case_no": "A2", "field_provenance": None, "legal_desc": ""}]
    cplan = dict(SS.plan_carry(crow, cst, source="certificate", county="Baker", case_key="case_no", recorded_at="2026-10-11T00:00:00Z"))
    assert set(cplan) == {8} and cplan[8]["legal_desc"] == "LOT 9" and cplan[8]["field_provenance"]["legal_desc"]["source_id"] == "fl_lienhub_certificates"
    assert SS.source_id_for("auction", "Okaloosa") == "fl_bid4assets_okaloosa"


def test_one_patch_per_row_merges_provenance_entries_and_carried_columns(monkeypatch):
    rows = [{"county": "Alachua", "case": "C1", "cert": "2023-5", "parcel": "P1", "bid": "1"}]
    stored = [{"id": "r1", "case_no": "C1", "field_provenance": None, "certificate_no": None}]
    plan = SS.plan_patches(rows, stored, source="auction", county="Alachua", case_key="case", recorded_at="2026-10-11T00:00:00Z")
    assert len(plan) == 1 and plan[0][0] == "r1"
    body = plan[0][1]
    assert body["certificate_no"] == "2023-5" and set(body["field_provenance"]) == {"parcel", "bid", "certificate_no"}
    # stamp_provenance reads the carry column back and sends the merged body once
    seen = {}

    def fake_read_all(base, table, headers, params, **kw):
        seen["select"] = params["select"]
        return stored
    monkeypatch.setattr(RP, "read_all", fake_read_all)
    sent = []

    class Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=0):
        sent.append((req.get_method(), req.full_url, json.loads(req.data)))
        return Resp()
    monkeypatch.setattr(SS.urllib.request, "urlopen", fake_urlopen)
    read, patched, failed = SS.stamp_provenance("https://x.example", "k", state="FL", source="auction", rows=rows,
                                                by_county={"Alachua": ["C1"]}, case_key="case", recorded_at="2026-10-11T00:00:00Z")
    assert (read, patched, failed) == (1, 1, 0)
    assert seen["select"] == "id,case_no,field_provenance,certificate_no"
    assert sent[0][0] == "PATCH" and sent[0][1].endswith("/rest/v1/properties?id=eq.r1") and sent[0][2]["certificate_no"] == "2023-5"


def test_both_florida_stamp_steps_carry_with_provenance():
    wf = (ROOT / ".github/workflows/harvest-and-sync.yml").read_text(encoding="utf-8")
    lines = [l for l in wf.splitlines() if "scripts/stamp_seen.py" in l and "--state FL" in l]
    assert len(lines) == 2 and all("--provenance" in l for l in lines)


# ------------------------------------------------------------------ A1 DLBA evidence row

def test_the_dlba_vacant_land_policy_is_a_verified_official_document_row():
    ev = [e for e in PPE.load_evidence(ROOT / "data/purchase_path_evidence_expansion.csv") if e.source_id == "mi_detroit_landbank_lots"]
    assert len(ev) == 1
    e = ev[0]
    assert e.applicable and e.county == "Wayne" and e.path_type == "county_instructions" and e.evidence_type == "county_document"
    assert e.evidence_url.startswith("https://dlba-production-bucket.s3.us-east-2.amazonaws.com/") and e.url == e.evidence_url
    assert PP.is_document_url(e.url)                                  # a PDF: an application-style document, never an online checkout
    # 2026-10-26: the October 2023 policy is no longer linked by the DLBA; the row now cites the
    # Second Amended and Restated Vacant Land Policy (adopted 11/11/2025) the DLBA's Policies page links.
    assert "SECOND-AMENDED-AND-RESTATED-VACANT-LAND-POLICY" in e.url
    assert "66690c9200cf75e82672e75ff2ba55e8419116982f6b4bc805376494bc68e866" in e.notes   # the read document's SHA-256
    assert "still offered" in e.does_not_prove and "Marketed" in e.does_not_prove         # currency and Marketed Lots stay unverified
    assert "owner-occupant" in e.steps[0]
    # The PDF sits on the DLBA's own S3 bucket, linked from buildingdetroit.org: permitted against the ArcGIS canonical URL.
    assert e.third_party_permitted is True and "buildingdetroit.org" in e.notes
    assert PPE.evidence_problems(e) == []
    unit = next(u for u in ACQ["status"] if u["source_id"] == "mi_detroit_landbank_lots")
    assert unit["status"] == "VERIFIED" and unit["basis"] == "evidence_table"
    # verified evidence never approves a source: the source's publication comes from
    # the owner's 2026-10-26 decision alone (registry restrictions say so)
    reg = {r["source_id"]: r for r in csv.DictReader((ROOT / "data/county_source_registry.csv").open(encoding="utf-8", newline=""))}
    assert reg["mi_detroit_landbank_lots"]["publication_status"] == "APPROVED"
    assert "Owner approved customer publication 2026-10-26" in reg["mi_detroit_landbank_lots"]["restrictions"]


def test_acquisition_unit_counts_after_the_sprint():
    by = {}
    for u in ACQ["status"]:
        by[u["status"]] = by.get(u["status"], 0) + 1
    # 2026-10-26: LRA (MO), Ramsey (MN) and Fayette (PA) processes read -> VERIFIED with records.
    # 2026-10-26: + 55 PBFCM / MVBA AVAILABLE units (owner decision) and the county-source sprint's units (FL Lake /
    # DeSoto / Wakulla / Charlotte, TX county lists), none with acquisition evidence yet.
    # + 15 new-sources sprint units (5 ePropertyPlus land banks, 8 Tax-Sale.info surplus counties, Hubbard, Saint Paul HRA).
    assert len(ACQ["status"]) == 157 and by == {"VERIFIED": 29, "NEEDS_REVIEW": 9, "UNAVAILABLE": 6, "NOT_FOUND": 113}


# ------------------------------------------------------------------ A2 county procedure rules

def test_every_applicable_evidence_row_has_its_procedure_rule_and_nothing_is_invented():
    rules = SR.load_rules()
    assert PR.problems(rules) == []
    expected = PR.expected_rules(changed_on="2026-10-11")
    # 29 before this sprint + the DLBA policy row; Morgan CO: one county, two ledgers;
    # + the LRA, Ramsey and Fayette process rows (2026-10-26)
    assert len(expected) == len(PR.applicable_evidence()) == 42   # + 9 Texas county processes (TX enrichment 2026-10-27, run 40430155571)
    by_key = {(r.state, r.county, r.topic): r for r in rules}
    for r in expected:
        cur = by_key[(r.state, r.county, r.topic)]
        assert cur.kind == "PROCEDURE" and cur.status == "VERIFIED" and cur.county
        assert cur.statement == r.statement and cur.source_url == r.source_url and cur.verified_on == r.verified_on
        assert cur.source_url.startswith("https://") and cur.implementation_status == "IMPLEMENTED" and (ROOT / cur.test_ref).is_file()
        assert cur.related_sources == r.related_sources and cur.topic.startswith("acquisition_procedure_")
    topics = {r.topic for r in expected}
    assert topics == {"acquisition_procedure_available", "acquisition_procedure_auctions", "acquisition_procedure_liens_certificates",
                      "acquisition_procedure_auctions_available"}
    # every rule statement IS an evidence row's own wording
    wordings = {e.evidence for _, e in PR.applicable_evidence()}
    assert all(r.statement in wordings for r in rules if r.topic.startswith("acquisition_procedure_"))


def test_procedure_rule_builder_detects_a_missing_and_a_drifted_rule():
    expected = PR.expected_rules(changed_on="2026-10-11")
    rules = SR.load_rules()
    without = [r for r in rules if not (r.state == "FL" and r.county == "Brevard" and r.topic == "acquisition_procedure_available")]
    assert [p for p in PR.problems(without) if p.startswith("missing rule FL/Brevard/")]
    import dataclasses
    drifted = [dataclasses.replace(r, statement="something else") if (r.state, r.county, r.topic) == ("FL", "Brevard", "acquisition_procedure_available") else r
               for r in rules]
    assert "FL/Brevard/acquisition_procedure_available: statement differs from its evidence row" in PR.problems(drifted)
    assert PR.topic_for("AUCTIONS|AVAILABLE") == "acquisition_procedure_auctions_available"
    out = subprocess.run([sys.executable, "scripts/build_procedure_rules.py", "--check"], cwd=ROOT, capture_output=True, text=True)
    assert out.returncode == 0, out.stdout


def test_county_coverage_counts_the_procedure_rules():
    rules = SR.load_rules()
    fl = {c["county"]: c for c in SV.county_coverage("FL", "AVAILABLE", rules=rules)}
    assert "acquisition_procedure_available" in fl["Brevard"]["procedures"] and "acquisition_procedure_available" in fl["Orange"]["procedures"]
    co = {c["county"]: c for c in SV.county_coverage("CO", "LIENS_CERTIFICATES", rules=rules)}
    assert "acquisition_procedure_liens_certificates" in co["Morgan"]["procedures"]
    page = json.loads((ROOT / "public/state-rules.json").read_text(encoding="utf-8"))
    assert page == json.loads((ROOT / "state-rules.json").read_text(encoding="utf-8"))
    assert any(r["topic"] == "acquisition_procedure_available" and r["county"] == "Brevard" for r in page["states"]["FL"]["county_rules"])


# ------------------------------------------------------------------ the gap queue

def test_gap_queue_is_generated_from_the_records_and_pinned():
    out = subprocess.run([sys.executable, "scripts/build_gap_queue.py", "--check"], cwd=ROOT, capture_output=True, text=True)
    assert out.returncode == 0, out.stdout
    doc = json.loads((ROOT / "data/current_state/gap-queue.json").read_text(encoding="utf-8"))
    assert doc == GQ.build()
    # 46 before the 2026-10-26 LRA / Ramsey / Fayette reads; then the PBFCM / MVBA and county-source units of the same day.
    assert doc["denominators"]["acquisition_units"] == 157 and doc["denominators"]["acquisition_unresolved"] == 128   # + 15 new-sources units
    assert doc["denominators"]["state_ledger_units"] == 39
    assert set(doc["summary"]["by_category"]) <= set(GQ.CATEGORIES)
    # one queue entry per unresolved acquisition unit plus one per non-current state x ledger unit.
    assert sum(doc["summary"]["by_category"].values()) == len(doc["units"]) == 128 + 27
    for u in doc["units"]:
        assert u["category"] in GQ.CATEGORIES and u["next_action"] and u["source_accessible"] and "reason" in u
        assert u["completable_now"] == (u["category"] == "A")
    by = {(u["state"], u["county"], u.get("source_id", ""), u["ledger"]): u for u in doc["units"]}
    assert by[("FL", "Escambia", "fl_laft_html", "AVAILABLE")]["category"] == "D"          # HTTP 403 to the runner
    # 2026-10-26: the Harris listing is the next constable SALE (AUCTIONS), no longer an AVAILABLE acquisition unit.
    assert ("TX", "Harris", "tx_hctax", "AVAILABLE") not in by
    assert by[("TX", "Bexar", "tx_bexar_resale", "AVAILABLE")]["category"] == "F"         # resale list read, process not yet
    assert by[("TX", "Liberty", "tx_lgbs", "AVAILABLE")]["category"] == "F"               # no official resale process
    assert by[("FL", "Indian River", "fl_laft_html", "AVAILABLE")]["category"] == "B"     # script-rendered page
    assert by[("TN", "*", "", "AVAILABLE")]["category"] == "C"                            # published 2026-10-26; process not verified
    assert by[("LA", "*", "", "AVAILABLE")]["category"] == "A"                            # fix exists, awaiting deploy
    assert by[("FL", "*", "", "LIENS_CERTIFICATES")]["category"] == "D"                  # LienHub 403
    # The coverage snapshot (2026-10-10) predates every source added 2026-10-26 (GovEase / PBFCM / MVBA, the county
    # lists), so its stale Texas rows are still the manual-only LGBS / RealAuction ones
    # (state_coverage._in_snapshot): E until a new snapshot is taken.
    assert by[("TX", "*", "", "AUCTIONS")]["category"] == "E"
    assert ("MI", "Wayne", "mi_detroit_landbank_lots", "AVAILABLE") not in by             # closed this sprint


# ------------------------------------------------------------------ contracts that must hold

def test_contracts_homepages_search_pages_and_wrong_ledger_paths_never_qualify():
    assert PP.untrusted_reason("https://www.clerk.example.invalid/") == "a bare homepage"
    assert "search-results page" in PP.untrusted_reason("https://county.example.invalid/search?q=parcel")
    assert PP.untrusted_reason("http://county.example.invalid/tax-deeds/lands-available") == "not https"
    row = PPE.EvidenceRow(state="FL", source_id="fl_laft_html", county="Union", path_type="direct_property_url",
                          url="https://county.example.invalid/parcel/1", evidence="e", observed_on="2026-10-11", enabled=True,
                          third_party_permitted=False, notes="", evidence_url="https://county.example.invalid/x", evidence_type="county_page",
                          source_title="t", instructions="", review_state="verified")
    assert any("direct_property_url is property-scope" in p for p in PPE.evidence_problems(row))


def test_contracts_rules_and_zero_states():
    bad = SR.Rule(state="FL", county="", topic="t", kind="PROCEDURE", status="VERIFIED", statement="s", source_url="", source_title="",
                  citation="", effective_date="", verified_on="", evidence="", ambiguity="", ledger="AUCTIONS")
    assert SR.rule_problems(bad)                                                           # never VERIFIED without a read source
    snap_empty = {"total": 0, "active": 0, "act_never_seen": 0, "act_seen_gt36h": 0, "last_seen_max": "2026-10-10 00:00:00+00"}
    src = [{"source_id": "x", "implemented": True, "approved_for_customers": True, "restrictions": "", "publication_status": "APPROVED"}]
    acq = {"units": 0, "by_status": {}, "verified_units": []}
    assert SC.classify(eligibility="NOT_VERIFIED", sources=src, snap=snap_empty, acq=acq, ledger="AUCTIONS")[0] == "RULES_NOT_VERIFIED"
    stale = dict(snap_empty, total=10, active=10, act_never_seen=10)
    assert SC.classify(eligibility="OFFERED", sources=src, snap=stale, acq=acq, ledger="AUCTIONS")[0] == "SOURCE_FAILED_OR_STALE"
    unreviewed = [dict(src[0], approved_for_customers=False, publication_status="UNREVIEWED")]
    assert SC.classify(eligibility="OFFERED", sources=unreviewed, snap=dict(stale, act_never_seen=0), acq=acq, ledger="AVAILABLE")[0] == "APPROVAL_UNRESOLVED"
