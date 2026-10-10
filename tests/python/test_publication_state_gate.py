"""Mandatory acquisition-path gate for customer publication (2026-10-10).

Engine (harvesters/governance/publication_state.py): one auditable state per
row, decided in a fixed order - source, rules, validation, path, freshness -
with reasons, remediation and structured path evidence; a county-level
portal or procedure is a valid path, a homepage is not; a failed source read
closes nothing; CLOSED only mirrors the lifecycle. Writer
(scripts/publication_state_writer.py): changed rows only, grouped, logged.
Migration 031: the properties access policy is ALTERED (never dropped) so a
customer reads CUSTOMER_PUBLISHED rows only; admins read every row; NULL is
never visible. Frontend mirrors (app.js labels, the stub's server rule).

LIVE layer (local PostgreSQL only, skipped otherwise): 026's scratch schema +
025 + 026 + is_admin() + 031, then every role's reads through get_properties()
and a direct select, the counts RPC, the withheld RPC, the decision log.
"""
from __future__ import annotations

import json
import re
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from harvesters.governance import publication_state as PS  # noqa: E402
from harvesters.governance import state_verification as SV  # noqa: E402
import publication_state_writer as W  # noqa: E402
from test_migration_016_source_health import _psql_prefix, _run  # noqa: E402

APP = (ROOT / "public/app.js").read_text(encoding="utf-8")
STUB = (ROOT / "tests/vendor/supabase-stub.js").read_text(encoding="utf-8")
M031 = ROOT / "scripts/migrations/031_publication_state_gate.sql"
SQL = M031.read_text(encoding="utf-8")
WORKFLOW = (ROOT / ".github/workflows/harvest-and-sync.yml").read_text(encoding="utf-8")
NOW = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)


def ctx(**over) -> PS.Context:
    c = PS.Context(now=NOW)
    c.source_publication = {"fl_realauction_alachua": "APPROVED_GRANDFATHERED", "fl_laft_calhoun": "APPROVED",
                            "fl_lienhub_certificates": "APPROVED_GRANDFATHERED", "tn_shelby_landbank": "UNREVIEWED",
                            "fl_laft_broward_candidate": "RESTRICTED", "tx_lgbs": "APPROVED", "mi_eaton_treasurer_sale": "APPROVED",
                            "bad_vendor": "BLOCKED"}
    c.ledger_eligibility = {("FL", "AUCTIONS"): "OFFERED", ("FL", "AVAILABLE"): "OFFERED", ("FL", "LIENS_CERTIFICATES"): "OFFERED",
                            ("TN", "AVAILABLE"): "COUNTY_DEPENDENT", ("TX", "AVAILABLE"): "NOT_VERIFIED",
                            ("MI", "AUCTIONS"): "COUNTY_DEPENDENT", ("XX", "AUCTIONS"): "NOT_OFFERED"}
    c.coverage = {("TN", "AVAILABLE"): {"Shelby"}, ("MI", "AUCTIONS"): {"Eaton"}}
    c.registry_units = {("FL", "fl_lienhub_certificates", "Alachua"): {
        "canonical_url": "https://lienhub.example.gov/alachua/county-held", "purchase_url": "", "purchase_url_kind": "",
        "source_authority": "VENDOR_AUCTION", "last_checked": "2026-10-09", "publishing_unit_name": "Alachua County Tax Collector"}}
    c.acquisition_status = {("FL", "fl_laft_calhoun", "Calhoun"): {"state": "FL", "source_id": "fl_laft_calhoun", "county": "Calhoun", "status": "VERIFIED"},
                            ("FL", "fl_laft_broward_candidate", "Broward"): {"state": "FL", "source_id": "fl_laft_broward_candidate", "county": "Broward", "status": "NEEDS_REVIEW"}}
    c.acquisition_records = {("FL", "fl_laft_calhoun", "Calhoun"): {
        "state": "FL", "source_id": "fl_laft_calhoun", "county": "Calhoun", "path_type": "application_page",
        "purchase_evidence_url": "https://calhounclerk.example.gov/lands-available", "purchase_instructions": "Apply at the clerk's office.",
        "purchase_path_observed_on": "2026-09-30", "office": "Clerk of Court"}}
    for k, v in over.items():
        setattr(c, k, v)
    return c


def row(**over) -> dict:
    base = {"id": "r1", "state": "FL", "county": "Alachua", "source": "auction", "ledger_type": "auctions", "status": "active",
            "case_no": "2026-TD-1", "parcel": "111", "source_id": "fl_realauction_alachua",
            "url_auction": "https://alachua.realtaxdeed.example.com/index.cfm?zaction=AUCTION&AuctionDate=10/20/2026", "url_auction_kind": "sale",
            "sale_date": "2026-10-20", "last_seen_at": "2026-10-10T06:00:00Z", "updated_at": "2026-10-10T06:00:00Z"}
    base.update(over)
    return base


# ==================== engine: per ledger ====================

def test_e01_auction_with_its_own_sale_listing_is_customer_published():
    d = PS.decide(row(), ctx())
    assert d.state == d.progress == "CUSTOMER_PUBLISHED" and d.reasons == []
    assert d.gates == {g: "PASS" for g in PS.GATES}
    assert d.path.path_type == "auction_bidding" and d.path.scope == "record" and d.path.ledger == "AUCTIONS"
    assert d.path.destination_url.startswith("https://") and d.path.verification_status


def test_e02_county_level_auction_portal_is_a_valid_path():
    d = PS.decide(row(url_auction="https://alachua.realtaxdeed.example.com/index.cfm?zaction=USER&zmethod=CALENDAR", url_auction_kind="county"), ctx())
    assert d.state == "CUSTOMER_PUBLISHED" and d.path.scope == "county"


@pytest.mark.parametrize("url", ["https://alachua.realtaxdeed.example.com/", "http://alachua.realtaxdeed.example.com/index.cfm?zaction=AUCTION",
                                 "https://www.google.com/search?q=alachua+tax+deed"])
def test_e03_homepage_search_engine_or_http_is_never_a_path(url):
    d = PS.decide(row(url_auction=url), ctx())
    assert d.state == "ADMIN_ONLY_NO_PATH" and d.reasons == ["PATH_UNTRUSTED"] and d.progress == "RULES_VERIFIED"
    assert d.gates["path"] == "FAIL" and d.gates["freshness"] is None
    assert d.remediation == PS.REMEDIATION["PATH_UNTRUSTED"]


def test_e04_auction_with_no_link_is_path_missing():
    d = PS.decide(row(url_auction=None, url_auction_kind=None), ctx())
    assert d.state == "ADMIN_ONLY_NO_PATH" and d.reasons == ["PATH_MISSING"]
    assert d.path.missing_reason == "PATH_MISSING" and d.path.verification_status == "NOT_VERIFIED"


def test_e05_available_with_verified_county_evidence_is_published_at_county_scope():
    d = PS.decide(row(id="a1", county="Calhoun", source="laft", ledger_type="buy", source_id="fl_laft_calhoun", url_auction=None,
                      sale_date=None, case_no="C-1"), ctx())
    assert d.state == "CUSTOMER_PUBLISHED"
    assert d.path.scope == "county" and d.path.path_type == "application" and d.path.destination_url.startswith("https://")
    assert d.path.last_verified == "2026-09-30" and d.path.verification_status == "VERIFIED"


def test_e06_available_with_captured_but_unverified_process_is_admin_only_no_path():
    d = PS.decide(row(id="a2", county="Broward", source="laft", ledger_type="buy", source_id="fl_laft_calhoun", url_auction=None, sale_date=None),
                  ctx(acquisition_status={("FL", "fl_laft_calhoun", "Broward"): {"state": "FL", "source_id": "fl_laft_calhoun", "county": "Broward", "status": "NEEDS_REVIEW"}}))
    assert d.state == "ADMIN_ONLY_NO_PATH" and d.reasons == ["PATH_NEEDS_REVIEW"]


def test_e07_available_record_level_typed_path_is_a_path():
    d = PS.decide(row(id="a3", county="Citrus", source="laft", ledger_type="buy", source_id="fl_laft_calhoun", url_auction=None, sale_date=None,
                      purchase_path_type="county_instructions_page", purchase_path_scope="record", purchase_url="https://citrusclerk.example.gov/tax-deeds/lands-available",
                      purchase_path_observed_on="2026-09-20"), ctx())
    assert d.state == "CUSTOMER_PUBLISHED" and d.path.scope in ("record", "source", "county")


def test_e08_lien_with_the_countys_certificate_page_in_the_registry_is_published():
    d = PS.decide(row(id="l1", source="certificate", ledger_type="lien", source_id="fl_lienhub_certificates", certificate_no="C-9",
                      url_auction=None, sale_date=None), ctx())
    assert d.state == "CUSTOMER_PUBLISHED" and d.path.path_type == "certificate_purchase" and d.path.scope == "county"


def test_e09_lien_without_any_county_record_is_not_published():
    d = PS.decide(row(id="l2", county="Baker", source="certificate", ledger_type="lien", source_id="fl_lienhub_certificates", certificate_no="C-9",
                      url_auction=None, sale_date=None), ctx())
    assert d.state == "ADMIN_ONLY_NO_PATH" and d.reasons[0].startswith("PATH_")


# ==================== engine: source, rules, validation, freshness ====================

def test_e10_unreviewed_restricted_blocked_unknown_sources_are_admin_only_source_review():
    for sid, reason in [("tn_shelby_landbank", "SOURCE_UNREVIEWED"), ("fl_laft_broward_candidate", "SOURCE_RESTRICTED"),
                        ("bad_vendor", "SOURCE_BLOCKED"), ("nobody", "SOURCE_UNKNOWN")]:
        d = PS.decide(row(source_id=sid), ctx())
        assert d.state == "ADMIN_ONLY_SOURCE_REVIEW" and d.reasons[0] == reason and d.progress == "DISCOVERED", sid
        assert d.gates["path"] is None


def test_e11_unverified_rules_county_not_covered_and_not_offered_are_admin_only():
    assert PS.decide(row(state="TX", county="Galveston", source="laft", ledger_type="buy", source_id="tx_lgbs"), ctx()).reasons == ["RULES_NOT_VERIFIED"]
    assert PS.decide(row(state="MI", county="Wayne", source_id="mi_eaton_treasurer_sale"), ctx()).reasons == ["COUNTY_NOT_COVERED"]
    assert PS.decide(row(state="MI", county="Eaton", source_id="mi_eaton_treasurer_sale"), ctx()).gates["rules"] == "PASS"
    assert PS.decide(row(state="XX", source_id="fl_realauction_alachua"), ctx()).reasons == ["RULES_NOT_OFFERED"]


def test_e12_record_without_identifier_or_county_is_invalid():
    d = PS.decide(row(case_no=None, parcel=None), ctx())
    assert d.reasons == ["RECORD_INVALID"] and d.state == "ADMIN_ONLY_SOURCE_REVIEW"
    assert "RECORD_INVALID" in PS.decide(row(county=""), ctx()).reasons


def test_e13_stale_observation_and_passed_sale_date_are_admin_only_stale_with_the_path_kept():
    d = PS.decide(row(last_seen_at="2026-10-01T00:00:00Z", updated_at="2026-10-01T00:00:00Z"), ctx())
    assert d.state == "ADMIN_ONLY_STALE" and d.reasons == ["OBSERVATION_STALE"] and d.progress == "PATH_VERIFIED"
    assert d.path is not None and d.gates["path"] == "PASS" and d.gates["freshness"] == "FAIL"
    d = PS.decide(row(sale_date="2026-10-09"), ctx())
    assert d.state == "ADMIN_ONLY_STALE" and d.reasons == ["SALE_DATE_PASSED"]
    # the ledger windows: AVAILABLE 14 days, AUCTIONS / LIENS 7
    assert PS.FRESHNESS_DAYS == {"AUCTIONS": 7, "AVAILABLE": 14, "LIENS_CERTIFICATES": 7}
    d = PS.decide(row(id="a1", county="Calhoun", source="laft", ledger_type="buy", source_id="fl_laft_calhoun", url_auction=None, sale_date=None,
                      last_seen_at="2026-09-28T00:00:00Z"), ctx())
    assert d.state == "CUSTOMER_PUBLISHED"


def test_e14_county_path_evidence_older_than_180_days_is_stale_not_missing():
    c = ctx()
    c.acquisition_records[("FL", "fl_laft_calhoun", "Calhoun")]["purchase_path_observed_on"] = "2026-03-01"
    d = PS.decide(row(id="a1", county="Calhoun", source="laft", ledger_type="buy", source_id="fl_laft_calhoun", url_auction=None, sale_date=None), c)
    assert d.state == "ADMIN_ONLY_STALE" and "PATH_STALE" in d.reasons and d.path.last_verified == "2026-03-01"


def test_e15_closed_mirrors_the_lifecycle_and_a_failed_read_changes_nothing():
    d = PS.decide(row(status="closed"), ctx())
    assert d.state == "CLOSED" and d.reasons == ["NOT_ACTIVE"]
    # A source failure never reaches the engine as a decision: the writer reads
    # active rows and decides them; nothing in the module closes a row.
    src = (ROOT / "harvesters/governance/publication_state.py").read_text(encoding="utf-8")
    assert "status" not in src.split("def decide", 1)[1].split("ledger = ledger_of(row)")[0].replace('str(row.get("status") or "active") != "active"', "")
    assert "closed" not in W.SELECT and "PATCH" in (ROOT / "scripts/publication_state_writer.py").read_text(encoding="utf-8")
    wsrc = (ROOT / "scripts/publication_state_writer.py").read_text(encoding="utf-8")
    assert '"status": ' not in wsrc.split("def execute", 1)[1].split("def main")[0]   # the writer never writes a lifecycle status


def test_e16_vocabulary_and_every_reason_has_a_remediation():
    assert PS.STATES == ("DISCOVERED", "RULES_VERIFIED", "PATH_VERIFIED", "CUSTOMER_PUBLISHED",
                         "ADMIN_ONLY_NO_PATH", "ADMIN_ONLY_SOURCE_REVIEW", "ADMIN_ONLY_STALE", "CLOSED")
    assert set(PS.REASONS) == set(PS.REMEDIATION) and set(PS.STATE_LABELS) == set(PS.STATES)
    assert set(PS.PATH_TYPES) == set(PS.PATH_TYPE_LABELS)
    assert PS.summarize([PS.decide(row(), ctx()), PS.decide(row(status="closed"), ctx())]) == {**{s: 0 for s in PS.STATES}, "CUSTOMER_PUBLISHED": 1, "CLOSED": 1}


def test_e17_build_context_reads_the_repository_records():
    c = PS.build_context(now=NOW)
    assert c.ledger_eligibility[("FL", "AUCTIONS")] == "OFFERED"
    assert c.source_publication.get("fl_lienhub_certificates") in ("APPROVED", "APPROVED_GRANDFATHERED")
    assert any(k[1] == "fl_lienhub_certificates" for k in c.registry_units)
    assert c.acquisition_status and all(len(k) == 3 for k in c.acquisition_status)


# ==================== writer ====================

class FakeApi:
    def __init__(self):
        self.patches, self.logs, self.dry_run = [], [], False

    def patch(self, ids, body):
        self.patches.append((list(ids), dict(body)))

    def insert_decisions(self, rows):
        self.logs.extend(rows)


def test_w01_writer_changes_only_rows_whose_decision_changed_and_logs_the_prior_state():
    rows = [row(id="11111111-1111-1111-1111-111111111111"),
            row(id="22222222-2222-2222-2222-222222222222", publication_state="CUSTOMER_PUBLISHED", publication_progress="CUSTOMER_PUBLISHED", publication_reasons=[]),
            row(id="33333333-3333-3333-3333-333333333333", url_auction="https://alachua.realtaxdeed.example.com/", publication_state="CUSTOMER_PUBLISHED",
                publication_progress="CUSTOMER_PUBLISHED", publication_reasons=[])]
    decided, counts = W.plan(rows, ctx())
    assert counts["rows"] == 3 and counts["changed"] == 2
    assert counts["by_state"] == {"CUSTOMER_PUBLISHED": 2, "ADMIN_ONLY_NO_PATH": 1}
    assert counts["by_ledger_state"] == {"auctions:CUSTOMER_PUBLISHED": 2, "auctions:ADMIN_ONLY_NO_PATH": 1}
    api = FakeApi()
    out = W.execute(api, decided, run_id="t", now=NOW)
    assert out["groups"] == 2 and len(api.patches) == 2
    patched = {i for ids, _ in api.patches for i in ids}
    assert patched == {"11111111-1111-1111-1111-111111111111", "33333333-3333-3333-3333-333333333333"}
    for ids, body in api.patches:
        assert set(body) == {"publication_state", "publication_progress", "publication_reasons", "publication_remediation", "publication_path", "publication_state_at"}
        assert "status" not in body
    log = {l["property_id"]: l for l in api.logs}
    assert log["33333333-3333-3333-3333-333333333333"]["prior_state"] == "CUSTOMER_PUBLISHED"
    assert log["33333333-3333-3333-3333-333333333333"]["publication_state"] == "ADMIN_ONLY_NO_PATH"
    assert log["33333333-3333-3333-3333-333333333333"]["reasons"] == ["PATH_UNTRUSTED"] and log["33333333-3333-3333-3333-333333333333"]["run_id"] == "t"
    assert log["11111111-1111-1111-1111-111111111111"]["prior_state"] is None


def test_w02_writer_reads_active_rows_by_keyset_pages_and_is_plan_only_without_031():
    src = (ROOT / "scripts/publication_state_writer.py").read_text(encoding="utf-8")
    assert "RP.read_all(" in src and '"status": "eq.active"' in src and "offset=" not in src
    assert "has_migration_031" in src and "plan-only (migration 031 absent)" in src
    assert "SUPABASE_SERVICE_KEY" in src and "print(" in src and "self.key" not in src.split("def main")[1]


def test_w03_workflow_runs_the_writer_after_every_sync_and_offers_the_manual_job():
    assert WORKFLOW.count("scripts/publication_state_writer.py") >= 7
    assert ", publication]" in WORKFLOW
    assert re.search(r"job == 'publication'", WORKFLOW)


# ==================== migration 031: static ====================

def code() -> str:
    return "\n".join(l for l in SQL.splitlines() if not l.strip().startswith("--")).strip().lower()


def test_m01_policy_is_altered_never_dropped_and_keeps_with_check():
    body = code()
    assert "drop policy" not in body.replace('drop policy if exists "publication_decisions: admin read"', "")
    assert 'alter policy "properties: approved only" on public.properties' in body
    assert "using ((select public.is_approved()) and (publication_state = 'customer_published' or (select public.is_admin())))" in body
    assert "with check" not in body.split('alter policy "properties: approved only"')[1]


def test_m02_check_constraints_name_exactly_the_engine_states():
    for col in ("publication_state", "publication_progress"):
        m = re.search(rf"check \({col} is null or {col} in \((.*?)\)\)", code(), re.S)
        assert m, col
        assert [x.strip().strip("'").upper() for x in m.group(1).split(",")] == list(PS.STATES)


def test_m03_decision_log_revokes_before_granting_and_only_admins_read():
    body = code()
    i = body.index("create table if not exists public.publication_decisions")
    tail = body[i:]
    assert tail.index("revoke all on table public.publication_decisions from anon, authenticated") < tail.index("grant select on table public.publication_decisions to authenticated")
    assert "insert" not in tail.split("create policy")[1].split(";")[0]
    assert "using ((select public.is_admin()))" in tail.split("create policy")[1].split(";")[0]
    assert "enable row level security" in tail


def test_m04_rpc_grants_and_security():
    body = code()
    assert "create or replace function public.count_publication_states(p_state text, p_ledger_type text default null)" in body
    assert "security definer" in body.split("count_publication_states")[1].split("$$")[0] and "(select public.is_approved())" in body
    assert "create or replace function public.get_withheld_states(p_state text)" in body
    assert "security invoker" in body.split("get_withheld_states(p_state text)")[1].split("$$")[0]
    for fn in ("count_publication_states(text, text)", "get_withheld_states(text)"):
        assert f"revoke all on function public.{fn} from public, anon" in body and f"grant execute on function public.{fn} to authenticated" in body
    # nothing in 031 recreates get_properties / get_properties_list (their column lists are untouched)
    assert "get_properties(" not in body and "get_properties_list" not in body
    # fail-safe: NULL is never customer-visible, and the apply order is documented
    assert "null = not decided = not customer-visible" in SQL.lower() and "apply order" in SQL.lower()


def test_m05_migration_declared_unapplied():
    assert "NOT applied" in SQL and "031" in (ROOT / "CLAUDE.md").read_text(encoding="utf-8")


# ==================== frontend mirrors ====================

def js_object(name: str) -> dict:
    m = re.search(rf"const {name} = \{{(.*?)\n\}};", APP, re.S)
    assert m, name
    out = {}
    for k, v in re.findall(r'\n\s+([A-Za-z_]+): "((?:[^"\\]|\\.)*)"', m.group(1)):
        out[k] = v.replace('\\"', '"')
    return out


def test_f01_app_labels_mirror_the_engine():
    assert js_object("PUBLICATION_STATE_LABELS") == PS.STATE_LABELS
    assert js_object("PUBLICATION_REASON_LABELS") == PS.REASONS
    m = re.search(r"const PUBLICATION_PATH_TYPE_LABELS = \{(.*?)\};", APP, re.S)
    assert dict(re.findall(r'(\w+): "([^"]+)"', m.group(1))) == PS.PATH_TYPE_LABELS


def test_f02_app_reads_both_rpcs_feature_detects_and_never_guesses_a_withheld_state():
    assert 'sb.rpc("count_publication_states", { p_state: PAGE_STATE })' in APP
    assert 'sb.rpc("get_withheld_states", { p_state: PAGE_STATE })' in APP
    assert "applyPublicationReads(pubCounts, pubWithheld)" in APP
    assert "PGRST202|could not find the function" in APP.split("function applyPublicationReads")[1].split("}")[0]
    # the customer defence: a non-published state is never shown to a non-admin
    body = APP.split("function isPublishable(p)")[1].split("\n}")[0]
    assert 'p.publication_state !== "CUSTOMER_PUBLISHED") return false' in body and body.index("if (IS_ADMIN) return true") < body.index("publication_state")
    # the zero case exists in both vocabularies, last
    assert SV.ZERO_CASES[-1] == "WITHHELD" and "WITHHELD: { label: \"Records withheld pending verification\"" in APP
    assert "This is not proof that no properties exist" in APP.split("WITHHELD: {")[1].split("}")[0]
    assert "withheld pending verification" in APP


def test_f03_stub_mirrors_the_server_rule_with_reasons_from_the_engine():
    block = STUB.split("const PUB_DECISIONS = {")[1].split("\n};")[0]
    reasons = set(re.findall(r'publication_reasons: \["([A-Z_]+)"\]', block))
    assert reasons <= set(PS.REASONS) and reasons >= {"PATH_UNTRUSTED", "PATH_NOT_FOUND", "OBSERVATION_STALE", "SALE_DATE_PASSED", "SOURCE_RESTRICTED", "SOURCE_UNREVIEWED", "RULES_NOT_VERIFIED"}
    assert set(re.findall(r'publication_state: "([A-Z_]+)"', block)) <= set(PS.ADMIN_ONLY)
    assert "pubVisibleTo(p, stubCallerIsAdmin())" in STUB and STUB.count("pubVisibleTo(") >= 3
    assert 'if (!stubCallerIsAdmin()) return { data: [], error: null };' in STUB


# ==================== LIVE ====================

FIXTURE = ROOT / "tests/python/fixtures/migration_026_scratch_fixture.sql"
M025 = ROOT / "scripts/migrations/025_get_properties_narrow_sort.sql"
M026 = ROOT / "scripts/migrations/026_properties_rls_initplan_and_page_index.sql"
USERS = {"admin": "11111111-1111-1111-1111-111111111111", "customer": "22222222-2222-2222-2222-222222222222",
         "pending": "33333333-3333-3333-3333-333333333333", "unknown": "44444444-4444-4444-4444-444444444444"}
IS_ADMIN_SQL = """create or replace function public.is_admin() returns boolean
language sql stable security definer set search_path to 'public'
as $$ select coalesce((select is_admin from public.profiles where id = auth.uid()), false) $$;
grant execute on function public.is_admin() to anon, authenticated, service_role;
"""
SEED = """delete from public.properties;
insert into public.properties (id, state, county, source, ledger_type, status, case_no, publication_state, publication_reasons, publication_remediation, publication_path) values
 ('aaaaaaaa-0000-0000-0000-000000000001','FL','Alachua','auction','auctions','active','A-1','CUSTOMER_PUBLISHED','[]',null,'{"path_type":"auction_bidding","scope":"record"}'),
 ('aaaaaaaa-0000-0000-0000-000000000002','FL','Baker','auction','auctions','active','B-1','ADMIN_ONLY_NO_PATH','["PATH_UNTRUSTED"]','Record the actual process page.','{"missing_reason":"PATH_UNTRUSTED"}'),
 ('aaaaaaaa-0000-0000-0000-000000000003','FL','Bay','laft','buy','active','C-1','CUSTOMER_PUBLISHED','[]',null,'{"path_type":"application","scope":"county"}'),
 ('aaaaaaaa-0000-0000-0000-000000000004','FL','Bay','laft','buy','active','C-2','ADMIN_ONLY_SOURCE_REVIEW','["SOURCE_UNREVIEWED"]','Record a review.',null),
 ('aaaaaaaa-0000-0000-0000-000000000005','FL','Alachua','certificate','lien','active','L-1','ADMIN_ONLY_STALE','["OBSERVATION_STALE"]','Run the harvest.','{"path_type":"certificate_purchase","scope":"county"}'),
 ('aaaaaaaa-0000-0000-0000-000000000006','FL','Alachua','certificate','lien','active','L-2','CUSTOMER_PUBLISHED','[]',null,null),
 ('aaaaaaaa-0000-0000-0000-000000000007','FL','Alachua','auction','auctions','active','A-7',null,'[]',null,null),
 ('aaaaaaaa-0000-0000-0000-000000000008','FL','Alachua','auction','auctions','closed','A-8','CLOSED','["NOT_ACTIVE"]',null,null);
"""


@pytest.fixture(scope="module")
def scratch():
    prefix = _psql_prefix()
    if prefix is None:
        pytest.skip("no local PostgreSQL reachable - live migration layer skipped (static layer still ran)")
    db = f"tdw_mig031_{uuid.uuid4().hex[:8]}"
    assert _run(prefix, "-Atc", f"create database {db}", db="postgres").returncode == 0
    staged = []

    def stage(text: str, name: str) -> str:
        copy = Path("/tmp") / f"{db}_{len(staged)}_{name}"
        copy.write_text(text, encoding="utf-8")
        copy.chmod(0o644)
        staged.append(copy)
        return str(copy)

    def apply(text: str, name: str):
        r = _run(prefix, "-v", "ON_ERROR_STOP=1", "-q", "-f", stage(text, name), db=db)
        assert r.returncode == 0, f"{name} failed to apply:\n{r.stderr}"

    def run(sql):
        r = _run(prefix, "-v", "ON_ERROR_STOP=0", "-Atq", db=db, stdin=sql)
        return (r.stdout or "") + (r.stderr or "")

    try:
        apply(FIXTURE.read_text(encoding="utf-8"), FIXTURE.name)
        apply(M025.read_text(encoding="utf-8"), M025.name)
        apply(M026.read_text(encoding="utf-8"), M026.name)
        apply(IS_ADMIN_SQL, "is_admin.sql")
        apply(SQL, M031.name)
        apply(SQL, "031_again.sql")   # idempotent
        apply(SEED, "seed.sql")
        yield run
    finally:
        _run(prefix, "-Atc", f"drop database if exists {db}", db="postgres")
        for c in staged:
            c.unlink(missing_ok=True)


def claims(uid: str) -> str:
    return ('{"sub":"%s","role":"authenticated","aud":"authenticated","email":"x@example.com","aal":"aal1",'
            '"app_metadata":{"provider":"email","providers":["email"]},"user_metadata":{"email_verified":true}}' % uid)


def as_user(uid: str, sql: str) -> str:
    return f"reset role; set role authenticated; set request.jwt.claims = '{claims(uid)}';\n{sql}"


def ids(out: str) -> list[str]:
    return sorted(l.strip()[-2:] for l in out.splitlines() if l.strip().startswith("aaaaaaaa-"))


def test_l01_customer_reads_customer_published_rows_only_everywhere(scratch):
    rpc = "select g.id from (values ('auctions'),('buy'),('lien')) v(l), lateral get_properties('FL', v.l, null, 1000, 0) g;"
    assert ids(scratch(as_user(USERS["customer"], rpc))) == ["01", "03", "06"]
    assert ids(scratch(as_user(USERS["customer"], "select id from public.properties;"))) == ["01", "03", "06"]
    assert ids(scratch(as_user(USERS["customer"], "select id from public.properties where county = 'Bay';"))) == ["03"]
    # NULL (not decided yet) is never visible; closed rows neither
    assert "07" not in ids(scratch(as_user(USERS["customer"], "select id from public.properties;")))


def test_l02_admin_reads_every_row_including_withheld_and_undecided(scratch):
    rpc = "select g.id from (values ('auctions'),('buy'),('lien')) v(l), lateral get_properties('FL', v.l, null, 1000, 0) g;"
    assert ids(scratch(as_user(USERS["admin"], rpc))) == ["01", "02", "03", "04", "05", "06", "07", "08"]
    assert ids(scratch(as_user(USERS["admin"], "select id from public.properties;"))) == ["01", "02", "03", "04", "05", "06", "07", "08"]


def test_l03_pending_unknown_and_anon_read_nothing(scratch):
    for who in ("pending", "unknown"):
        assert ids(scratch(as_user(USERS[who], "select id from public.properties;"))) == []
    assert ids(scratch("reset role; set role anon; select id from public.properties;")) == []


def test_l04_counts_rpc_answers_every_approved_account_with_counts_only(scratch):
    q = "select ledger_type || ':' || publication_state || ':' || n from count_publication_states('FL');"
    cust = [l for l in scratch(as_user(USERS["customer"], q)).splitlines() if ":" in l]
    assert sorted(cust) == ["auctions:ADMIN_ONLY_NO_PATH:1", "auctions:CUSTOMER_PUBLISHED:1", "auctions:DISCOVERED:1",
                            "buy:ADMIN_ONLY_SOURCE_REVIEW:1", "buy:CUSTOMER_PUBLISHED:1", "lien:ADMIN_ONLY_STALE:1", "lien:CUSTOMER_PUBLISHED:1"]
    assert sorted(l for l in scratch(as_user(USERS["admin"], q)).splitlines() if ":" in l) == sorted(cust)
    assert [l for l in scratch(as_user(USERS["pending"], q)).splitlines() if ":" in l] == []
    one = [l for l in scratch(as_user(USERS["customer"], "select ledger_type || ':' || publication_state || ':' || n from count_publication_states('FL', 'lien');")).splitlines() if ":" in l]
    assert sorted(one) == ["lien:ADMIN_ONLY_STALE:1", "lien:CUSTOMER_PUBLISHED:1"]


def test_l05_withheld_rpc_is_empty_for_customers_and_names_reasons_for_admins(scratch):
    q = "select id || '|' || publication_state || '|' || publication_reasons::text || '|' || coalesce(publication_remediation,'') from get_withheld_states('FL');"
    assert ids(scratch(as_user(USERS["customer"], q))) == []
    out = scratch(as_user(USERS["admin"], q))
    rows = {l.split("|")[0][-2:]: l for l in out.splitlines() if l.startswith("aaaaaaaa-")}
    assert sorted(rows) == ["02", "04", "05", "07"]
    assert rows["02"].endswith('|ADMIN_ONLY_NO_PATH|["PATH_UNTRUSTED"]|Record the actual process page.')
    assert "|DISCOVERED|" in rows["07"]


def test_l06_decision_log_is_admin_read_only_and_service_role_writes(scratch):
    ins = ("reset role; set role service_role; insert into public.publication_decisions (property_id, state, county, ledger_type, source_id, prior_state, publication_state, reasons, run_id)"
           " values ('aaaaaaaa-0000-0000-0000-000000000002','FL','Baker','auctions','fl_x',null,'ADMIN_ONLY_NO_PATH','[\"PATH_UNTRUSTED\"]','t'); select count(*) from public.publication_decisions;")
    assert scratch(ins).strip().splitlines()[-1] == "1"
    assert scratch(as_user(USERS["admin"], "select count(*) from public.publication_decisions;")).strip().splitlines()[-1] == "1"
    assert scratch(as_user(USERS["customer"], "select count(*) from public.publication_decisions;")).strip().splitlines()[-1] == "0"
    denied = scratch(as_user(USERS["admin"], "insert into public.publication_decisions (property_id, publication_state) values ('aaaaaaaa-0000-0000-0000-000000000002','CLOSED');"))
    assert "permission denied" in denied.lower() or "violates row-level security" in denied.lower()


def test_l07_policy_stays_the_single_permissive_all_public_policy(scratch):
    out = scratch("select policyname || '|' || permissive || '|' || cmd || '|' || roles::text from pg_policies where tablename = 'properties';")
    lines = [l for l in out.splitlines() if "|" in l]
    assert lines == ["properties: approved only|PERMISSIVE|ALL|{public}"]
    assert scratch("select count(*) from pg_indexes where indexname = 'properties_publication_state_idx';").strip().splitlines()[-1] == "1"


def test_l08_a_state_the_check_does_not_allow_is_refused(scratch):
    out = scratch("reset role; set role service_role; update public.properties set publication_state = 'PUBLISHED' where id = 'aaaaaaaa-0000-0000-0000-000000000001';")
    assert "properties_publication_state_check" in out
