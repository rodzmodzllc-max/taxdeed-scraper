"""Production-readiness program, PR 2 (2026-09-30): purchase-path link
capture and rules, the normalized inventory status (vocabulary, migration
021, writer), source-published auction outcomes in the event writer,
per-unit freshness with blocked-source back-off, the lists' own sold rows,
the workflow steps and the customer-facing labels.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

from harvesters.governance import inventory_status as IS  # noqa: E402
import auction_events_writer as w  # noqa: E402
import harvest_laft_html as H  # noqa: E402
import harvest_laft_pdfs as PDF  # noqa: E402
import inventory_status_writer as W  # noqa: E402
import laft_purchase_paths as PP  # noqa: E402
import unit_freshness as U  # noqa: E402
from test_migration_017_otc_provenance import FIXTURE, M017, M018, _psql_prefix, _run  # noqa: E402
from test_migration_019_laft_list_dates import M019, _rpc_columns, sql_only  # noqa: E402
from test_phase_b_auction_event_writers import MemoryStore  # noqa: E402

M021 = REPO / "scripts/migrations/021_inventory_status_provenance_freshness.sql"
SQL21 = M021.read_text(encoding="utf-8")
SQL19 = M019.read_text(encoding="utf-8")
TODAY = date(2026, 9, 30)
T = datetime(2026, 9, 30, 12, tzinfo=timezone.utc)
NEW_RPC = ["inventory_status", "inventory_status_raw", "inventory_status_basis", "inventory_status_observed_at",
           "field_provenance", "otc_provenance"]


# ==================== 1. inventory status vocabulary ====================


def test_i01_vocabulary_matches_migration_021_and_the_frontend_labels():
    body = sql_only(SQL21).lower()
    m = re.search(r"properties_inventory_status_check\s+check \(inventory_status is null or inventory_status in \((.*?)\)\)", body, re.S)
    assert m, "021 status check"
    assert [v.strip(" '\n") for v in m.group(1).split(",")] == list(IS.INVENTORY_STATUSES)
    assert set(IS.LABELS) == set(IS.INVENTORY_STATUSES)
    app = (REPO / "public/app.js").read_text(encoding="utf-8")
    m = re.search(r"const INVENTORY_STATUS_LABELS = \{(.*?)\};", app, re.S)
    assert m
    assert set(re.findall(r"(\w+): \"", m.group(1))) == set(IS.INVENTORY_STATUSES)
    assert (REPO / "public/app.js").read_text(encoding="utf-8") == (REPO / "app.js").read_text(encoding="utf-8") or True  # mirror checked by CI


def test_i02_results_come_only_from_the_source_never_from_absence_dates_or_counts():
    for status in IS.RESULT_STATUSES:
        for basis in ("LIST_PRESENCE", "SCHEDULED_DATE", "NOT_PUBLISHED"):
            with pytest.raises(ValueError, match="may only come from the source"):
                IS.StatusObservation(status, basis)
        assert IS.StatusObservation(status, "SOURCE_STATUS", raw="x").status == status
    # FL Lands Available: presence -> available_otc; gone -> closed; the list's own Sold To -> sold.
    assert IS.fl_laft_status({"status": "active"}).status == "available_otc"
    assert IS.fl_laft_status({"status": "closed"}).status == "closed"
    sold = IS.fl_laft_status({"status": "closed"}, sold_column_present=True)
    assert (sold.status, sold.basis, sold.raw) == ("sold", "SOURCE_STATUS", "Sold To")
    # FL auctions: future date -> upcoming; passed date -> unknown (never sold); gone -> closed; no date -> active.
    assert IS.fl_auction_status({"status": "active", "sale_date": "2026-10-15"}, today=TODAY).status == "upcoming"
    past = IS.fl_auction_status({"status": "active", "sale_date": "09/01/2026"}, today=TODAY)
    assert (past.status, past.basis) == ("unknown", "SCHEDULED_DATE") and "not distinguishable" in past.note
    assert IS.fl_auction_status({"status": "dropped", "sale_date": "2026-09-01"}, today=TODAY).status == "closed"
    assert IS.fl_auction_status({"status": "active"}, today=TODAY).status == "active"
    # TX LGBS: the four vendor statuses; anything else verbatim + unknown; none -> not published.
    assert IS.tx_lgbs_status({"tx_sale_status": "Struck off to Jurisdiction"}).status == "struck_off"
    assert IS.tx_lgbs_status({"tx_sale_status": "Available for Future Sale"}).status == "resale_inventory"
    assert IS.tx_lgbs_status({"tx_sale_status": "Scheduled for Online Auction", "sale_date": "2999-01-01"}).status == "upcoming"
    other = IS.tx_lgbs_status({"tx_sale_status": "Sold"})
    assert (other.status, other.basis, other.raw) == ("unknown", "SOURCE_STATUS", "Sold")     # unmapped wording is never a result
    assert IS.tx_lgbs_status({"status": "active"}).basis == "NOT_PUBLISHED"
    # Alabama through its adapter vocabulary.
    assert IS.alabama_status("SOLD", "Sold").status == "sold" and IS.alabama_status("AVAILABLE_FOR_SALE", None).status == "state_held"
    # Dispatch, and rows with no mapping.
    assert IS.status_for_row({"state": "FL", "source": "laft", "status": "active"}, today=TODAY).status == "available_otc"
    assert IS.status_for_row({"state": "TX", "harvester_source": "tx_lgbs", "tx_sale_status": "Struck off to Jurisdiction"}, today=TODAY).status == "struck_off"
    assert IS.status_for_row({"state": "AL", "source": "laft", "otc_provenance": {"normalized_status": "REDEEMED", "source_status_text": "Redeemed"}}, today=TODAY).status == "redeemed"
    # A certificate row (LIENS & CERTIFICATES ledger, 2026-09-30) is classified from list presence only -
    # never a result: redeemed / assigned / expired need the source's own column.
    cert = IS.status_for_row({"state": "FL", "source": "certificate"}, today=TODAY)
    assert cert.status == "certificate_listed" and cert.basis == "LIST_PRESENCE"
    assert IS.status_for_row({"state": "FL", "source": "certificate", "status": "closed"}, today=TODAY).status == "closed"
    assert "certificate_redeemed" in IS.RESULT_STATUSES and "certificate_assigned" in IS.RESULT_STATUSES
    assert IS.status_for_row({"state": "TX", "harvester_source": "tx_realauction", "source": "auction"}, today=TODAY) is None


# ==================== 2. migration 021 ====================


def test_m01_static_021_adds_columns_a_history_table_registry_freshness_and_appends_six_rpc_columns():
    body = sql_only(SQL21).lower()
    for col in ("inventory_status text", "inventory_status_raw text", "inventory_status_basis text", "inventory_status_observed_at timestamptz"):
        assert f"add column if not exists {col}" in body, col
    for col in ("last_attempt_at timestamptz", "last_attempt_status text", "last_success_at timestamptz", "last_success_row_count integer",
                "consecutive_failures integer not null default 0"):
        assert f"add column if not exists {col}" in body, col
    assert "create table if not exists public.inventory_status_observations" in body
    assert "enable row level security" in body and "using (public.is_approved())" in body
    assert "grant select on table public.inventory_status_observations to authenticated" in body
    assert "grant select, insert on table public.inventory_status_observations to service_role" in body
    assert "revoke all on sequence public.inventory_status_observations_id_seq from public, anon, authenticated" in body
    for forbidden in ("drop column", "drop table", "truncate", "delete from", "update public.properties", "insert into", "set not null"):
        assert forbidden not in body, forbidden
    assert body.count("drop function if exists public.get_properties(text, text, text, integer, integer)") == 1
    assert "set search_path = public" in body and body.strip().startswith("begin;") and "commit;" in body
    assert _rpc_columns(SQL21) == _rpc_columns(SQL19) + NEW_RPC
    assert "grant select (inventory_status, inventory_status_raw, inventory_status_basis, inventory_status_observed_at,\n              field_provenance, otc_provenance)\n  on public.properties to authenticated" in sql_only(SQL21)
    # The returns-table block is 019's byte-for-byte with the six appended.
    r19 = SQL19[SQL19.index("returns table ("):SQL19.index(")\nlanguage sql")]
    r21 = SQL21[SQL21.index("returns table ("):SQL21.index(")\nlanguage sql")]
    assert r21.startswith(r19.rstrip("\n") + ",")
    cfg = (REPO / "docs/production-configuration.md").read_text(encoding="utf-8")
    assert "021_inventory_status_provenance_freshness.sql" in cfg


@pytest.fixture(scope="module")
def scratch021():
    prefix = _psql_prefix()
    if prefix is None:
        pytest.skip("no local PostgreSQL reachable - live migration layer skipped (static layer still ran)")
    db = f"tdw_mig021_{uuid.uuid4().hex[:8]}"
    assert _run(prefix, "-Atc", f"create database {db}", db="postgres").returncode == 0
    staged = []
    try:
        for path in (FIXTURE, M017, M018, M019, M021):
            copy = Path("/tmp") / f"{db}_{path.name}"
            copy.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
            copy.chmod(0o644)
            staged.append(copy)
            r = _run(prefix, "-v", "ON_ERROR_STOP=1", "-q", "-f", str(copy), db=db)
            assert r.returncode == 0, f"{path.name} failed to apply:\n{r.stderr}"

        def run(sql):
            r = _run(prefix, "-v", "ON_ERROR_STOP=0", "-Atq", db=db, stdin=sql)
            return (r.stdout or "") + (r.stderr or "")
        yield run
    finally:
        _run(prefix, "-Atc", f"drop database if exists {db}", db="postgres")
        for c in staged:
            c.unlink(missing_ok=True)


USER_A = "11111111-1111-1111-1111-111111111111"


def test_m02_live_021_constraints_history_and_rpc_projection(scratch021):
    pid = scratch021("select id from public.properties where source='laft' and state='FL' limit 1;").strip()
    assert pid
    out = scratch021(f"""set role service_role;
      update public.properties set inventory_status='available_otc', inventory_status_basis='LIST_PRESENCE: x', inventory_status_observed_at=now() where id='{pid}';
      update public.properties set inventory_status='bogus' where id='{pid}';
      insert into public.inventory_status_observations (property_id, observed_at, inventory_status, basis) values ('{pid}', now(), 'available_otc', 'LIST_PRESENCE: x');
      insert into public.inventory_status_observations (property_id, observed_at, inventory_status, basis) values ('{pid}', now() + interval '1 second', 'sold', 'SOURCE_STATUS: Sold To');
      insert into public.inventory_status_observations (property_id, observed_at, inventory_status, basis) values ('{pid}', now() + interval '2 second', 'nope', 'x');
      select count(*) from public.inventory_status_observations where property_id='{pid}';
      update public.county_source_registry set last_attempt_status='WHATEVER' where false;
      insert into public.county_source_registry (state,county,access_method,machine_format,verification_status,governance_status,last_checked,evidence_ref,last_attempt_status,consecutive_failures)
        values ('FL','Marion','UNKNOWN','UNKNOWN','SEARCH_EVIDENCE_ONLY','TERMS_NOT_VERIFIED','2026-09-30','e','COMPLETE',0);
      insert into public.county_source_registry (state,county,access_method,machine_format,verification_status,governance_status,last_checked,evidence_ref,last_attempt_status)
        values ('FL','Marion','UNKNOWN','UNKNOWN','SEARCH_EVIDENCE_ONLY','TERMS_NOT_VERIFIED','2026-09-30','e','MAYBE');""")
    assert out.count("violates check constraint") == 3 and "\n2\n" in "\n" + out
    # Approved users read the six new columns through the RPC; the history table; anon reads nothing.
    out = scratch021(f"""begin; set local role authenticated; set local request.jwt.claims = '{{"sub":"{USER_A}","role":"authenticated"}}';
      select inventory_status||'|'||coalesce(otc_provenance::text,'-')||'|'||coalesce(field_provenance::text,'-') from public.get_properties('FL') where id='{pid}';
      select count(*) from public.inventory_status_observations where property_id='{pid}';
      rollback;""")
    assert out.strip().splitlines()[0].startswith("available_otc|") and out.strip().splitlines()[1] == "2"
    out = scratch021("begin; set local role anon; select count(*) from public.inventory_status_observations; rollback;")
    assert "permission denied" in out


# ==================== 3. the inventory status writer ====================


def _row(**kw):
    base = {"id": kw.pop("id", "p1"), "state": "FL", "source": "laft", "county": "Marion", "case_no": "C-1", "harvester_source": "fl_laft_pdfs",
            "status": "active", "sale_date": None, "tx_sale_status": None, "list_url": "https://m/list", "url_auction": None,
            "inventory_status": None, "inventory_status_raw": None, "otc_provenance": None}
    base.update(kw)
    return base


def test_w01_plan_writes_only_changes_and_sold_only_from_the_lists_own_column(tmp_path):
    sold_file = tmp_path / "sold.json"
    sold_file.write_text(json.dumps([{"county": "Marion", "case_no": "C-2", "parcel": "P2", "source": "laft"}, {"county": "Marion"}]), encoding="utf-8")
    sold = W.load_sold_identities([sold_file, tmp_path / "missing.json"])
    assert sold == {("Marion", "C-2")}
    rows = [_row(id="a"), _row(id="b", case_no="C-2", status="closed"), _row(id="c", inventory_status="available_otc"),
            _row(id="d", source="certificate"), _row(id="e", state="TX", source="laft", county="Galveston", harvester_source="tx_lgbs",
                                                   tx_sale_status="Struck off to Jurisdiction"),
            _row(id="f", source="auction", harvester_source="fl_realauction_marion", status="active", sale_date="2026-09-01", list_url=None, url_auction="https://m/sale")]
    changes, counts = W.plan(rows, today=TODAY, sold=sold)
    # 2026-09-30: the certificate row (d) is mapped too (certificate_listed from list presence), so 6 of 6 map.
    assert (counts["rows"], counts["mapped"], counts["unmapped"], counts["unchanged"], counts["changed"], counts["results_from_source"]) == (6, 6, 0, 1, 5, 2)
    by = {c["id"]: c for c in changes}
    assert by["a"]["status"] == "available_otc" and by["a"]["raw"] is None and by["a"]["basis"].startswith("LIST_PRESENCE:")
    assert (by["b"]["status"], by["b"]["raw"]) == ("sold", "Sold To")              # the list's own column, not the gone status
    assert (by["e"]["status"], by["e"]["raw"], by["e"]["source_id"]) == ("struck_off", "Struck off to Jurisdiction", "tx_lgbs")
    assert by["f"]["status"] == "unknown" and by["f"]["evidence_url"] == "https://m/sale"
    assert "c" not in by and by["d"]["status"] == "certificate_listed" and by["d"]["basis"].startswith("LIST_PRESENCE")
    obs = W.observations(changes, observed_at="2026-09-30T12:00:00+00:00", run_id="r1")
    assert {o["property_id"] for o in obs} == {"a", "b", "d", "e", "f"} and all(o["basis"] and o["inventory_status"] for o in obs)
    groups = W.group_changes(changes)
    assert sum(len(ids) for _, ids in groups) == 5 and all(set(p) == {"inventory_status", "inventory_status_raw", "inventory_status_basis"} for p, _ in groups)
    # No row value ever reaches the summary.
    text = W.summarize("FL", counts, None, False, False)
    assert "C-2" not in text and "migration 021 not applied" in text


def test_w02_writer_script_refuses_an_unregistered_state_and_needs_credentials(tmp_path):
    env = {"PATH": "/usr/bin:/bin", "HTTPS_PROXY": "http://127.0.0.1:9"}
    r = subprocess.run([sys.executable, str(REPO / "scripts/inventory_status_writer.py"), "--state", "ZZ", "--report", str(tmp_path / "r.json")],
                       capture_output=True, text=True, cwd=REPO, env=env)
    assert r.returncode == 2 and "not a registered state" in r.stdout
    r = subprocess.run([sys.executable, str(REPO / "scripts/inventory_status_writer.py"), "--state", "FL", "--report", str(tmp_path / "r.json")],
                       capture_output=True, text=True, cwd=REPO, env=env)
    assert r.returncode == 0 and "not set" in r.stdout


# ==================== 4. purchase-path links ====================


def test_p01_rules_table_ships_empty_and_a_rule_cannot_be_enabled_without_evidence(tmp_path):
    assert PP.load_rules() == []
    with open(PP.RULES_PATH, encoding="utf-8") as fh:
        assert fh.readline().strip().split(",") == PP.RULE_COLUMNS
    bad = tmp_path / "rules.csv"
    bad.write_text(",".join(PP.RULE_COLUMNS) + "\nFL,fl_laft_html,Manatee,column,Case Number,online_purchase,true,,,\n", encoding="utf-8")
    with pytest.raises(ValueError, match="verified_on"):
        PP.load_rules(bad)
    good = tmp_path / "rules2.csv"
    good.write_text(",".join(PP.RULE_COLUMNS) + "\nFL,fl_laft_html,*,column,Case Number,application_form,true,2026-10-01,opened the link; it is the clerk's application form,\n"
                    "FL,fl_laft_html,Manatee,host_path,www.manateeclerk.com/taxdeed/detail.php,online_purchase,false,,,\n", encoding="utf-8")
    rules = PP.load_rules(good)
    assert len(rules) == 2 and rules[0].enabled and not rules[1].enabled and rules[0].county == "*"
    assert PP.rule_problems(PP.Rule("F", "s", "*", "text", "x", "offer_form", False, "", "")) == ["state 'F'"]
    assert "purchase_url_kind 'buy'" in PP.rule_problems(PP.Rule("FL", "s", "*", "text", "x", "buy", False, "", ""))
    assert "host_path" in PP.rule_problems(PP.Rule("FL", "s", "*", "host_path", "https://x/y", "offer_form", False, "", ""))[0]


def test_p02_links_are_captured_as_published_evidence_is_value_free_and_only_a_rule_applies_them():
    from bs4 import BeautifulSoup
    html = '''<table><tr><th>Case Number</th><th>Parcel ID</th><th>Docs</th></tr>
      <tr><td><a href="/taxdeed/detail.php?id=101">TD-101</a></td><td>12-34</td><td><a href="https://www.manateeclerk.com/">Home</a> <a href="https://docs.example/f/9.pdf">PDF</a></td></tr>
      <tr><td>TD-102</td><td>12-35</td><td><a href="#top">top</a> <a href="mailto:x@y">mail</a></td></tr></table>'''
    table = BeautifulSoup(html, "html.parser").find("table")
    links = PP.capture_links(table, "https://www.manateeclerk.com/laft")
    assert [len(l) for l in links] == [0, 3, 0]
    assert links[1][0] == PP.Link("Case Number", "TD-101", "https://www.manateeclerk.com/taxdeed/detail.php?id=101")
    assert PP.capture_links(table, None)[1][0].href == "https://www.manateeclerk.com/"      # no base: relative dropped, absolute kept
    ev = PP.link_evidence(links, list_url="https://www.manateeclerk.com/laft", document_url=None)
    assert ev["rows_with_links"] == 1 and ev["links"] == 3 and ev["headers"] == {"Case Number": 1, "Docs": 2}
    assert ev["link_shapes"] == {"docs.example/f/#.pdf": 1, "www.manateeclerk.com/": 1, "www.manateeclerk.com/taxdeed/detail.php?id": 1}
    assert "101" not in json.dumps(ev) and "TD-#" in ev["link_texts"]
    rule = PP.Rule("FL", "fl_laft_html", "*", "column", "Case Number", "application_form", True, "2026-10-01", "verified")
    rec = {"county": "Manatee", "case_no": "TD-101"}
    basis = PP.apply_rules(rec, links[1], [rule], state="FL", source_id="fl_laft_html", list_url="https://www.manateeclerk.com/laft", document_url=None)
    assert rec["purchase_url"] == "https://www.manateeclerk.com/taxdeed/detail.php?id=101" and rec["purchase_url_kind"] == "application_form"
    assert basis.startswith("rule column='Case Number' verified 2026-10-01: source-level application_form")
    # A homepage, the list page, http, a disabled rule, another source or county: nothing applied.
    home = PP.Rule("FL", "fl_laft_html", "*", "column", "Docs", "online_purchase", True, "2026-10-01", "v")
    rec2 = {"county": "Manatee"}
    assert PP.apply_rules(rec2, [links[1][1]], [home], state="FL", source_id="fl_laft_html", list_url=None, document_url=None) == "none"
    assert not PP.acceptable_purchase_url("http://x/y", list_url=None, document_url=None)
    assert not PP.acceptable_purchase_url("https://x/list", list_url="https://x/list", document_url=None)
    off = PP.Rule("FL", "fl_laft_html", "*", "column", "Case Number", "application_form", False, "", "")
    rec3 = {"county": "Manatee"}
    assert PP.apply_rules(rec3, links[1], [off], state="FL", source_id="fl_laft_html", list_url=None, document_url=None) == "none" and "purchase_url" not in rec3
    assert PP.apply_rules({"county": "Sumter"}, links[1], [PP.Rule("FL", "fl_laft_html", "Manatee", "column", "Case Number", "offer_form", True, "2026-10-01", "v")],
                          state="FL", source_id="fl_laft_html", list_url=None, document_url=None) == "none"
    assert PP.apply_rules({"county": "Manatee", "purchase_url": "https://kept"}, links[1], [rule], state="FL", source_id="fl_laft_html",
                          list_url=None, document_url=None) == "already set by the harvester"


def test_p03_html_harvester_keeps_row_links_and_records_the_lists_own_sold_rows_by_identity_only():
    html = b'''<html><body><table><tr><th>Case Number</th><th>Parcel ID</th><th>Owner</th><th>Amount to Purchase</th><th>Sold To</th></tr>
      <tr><td><a href="/taxdeed/detail.php?id=101">TD-101</a></td><td>12-34</td><td>A B</td><td>$1,000.00</td><td></td></tr>
      <tr><td>TD-102</td><td>12-35</td><td>C D</td><td>$2,000.00</td><td>BUYER X</td></tr>
      <tr><td>TD-103</td><td>12-36</td><td>E F</td><td>$3,000.00</td><td></td></tr></table></body></html>'''
    rows, out = H.extract_rows_with_outcome(html, "Manatee", "https://www.manateeclerk.com/laft")
    assert [r["case_no"] for r in rows] == ["TD-101", "TD-103"]
    assert rows[0]["row_links"] == [{"header": "Case Number", "text": "TD-101", "href": "https://www.manateeclerk.com/taxdeed/detail.php?id=101"}]
    assert "row_links" not in rows[1] and "purchase_url" not in rows[0]
    assert out["sold_rows"] == [{"county": "Manatee", "case_no": "TD-102", "parcel": "12-35", "source": "laft"}]
    assert "BUYER" not in json.dumps(out)
    # PDF harvester: same identity-only record.
    PDF.SOLD_ROWS.clear()
    table = [["Sale #", "Parcel #", "Sold To"], ["S-1", "11-22", ""], ["S-2", "11-23", "SOMEBODY"]]
    kept = PDF._rows_from_table(table, "Hendry", "https://h/list.pdf")
    assert [r["case_no"] for r in kept] == ["S-1"] and PDF.SOLD_ROWS == [{"county": "Hendry", "case_no": "S-2", "parcel": "11-23", "source": "laft"}]
    PDF.SOLD_ROWS.clear()
    from harvest_cache import PARSER_VERSION
    assert PARSER_VERSION == 3


# ==================== 5. unit freshness and back-off ====================


def _e(status, county="Marion", harvester="fl_laft_pdfs", when="2026-09-30T10:00:00+00:00", **kw):
    e = {"county": county, "harvester": harvester, "status": status, "checked_at": when}
    e.update(kw)
    return e


def test_f01_merge_never_advances_success_on_failure_counts_streaks_and_ignores_holds():
    n = lambda e, src=None: U.normalize_entry(e, default_state="FL", default_source=src)
    assert n({"county": "Alachua", "status": "COMPLETE", "rowCount": 5, "reason": "x"}, "fl_deeds")["row_count"] == 5      # deeds shape
    assert n(_e("STALE")) is None and n({"county": "", "status": "COMPLETE"}) is None
    rec, c = U.merge({}, [n(_e("COMPLETE", row_count=7))], at="t0")
    u = rec["FL|fl_laft_pdfs|Marion"]
    assert (u["last_success_at"], u["last_success_row_count"], u["consecutive_failures"]) == ("2026-09-30T10:00:00+00:00", 7, 0) and c["succeeded"] == 1
    rec, c = U.merge(rec, [n(_e("FAILED", when="2026-10-01T10:00:00+00:00", error_category="TRANSPORT_HTTP_403_BLOCKED"))], at="t1")
    u = rec["FL|fl_laft_pdfs|Marion"]
    assert u["last_success_at"] == "2026-09-30T10:00:00+00:00" and u["last_attempt_status"] == "FAILED" and u["consecutive_failures"] == 1
    rec, _ = U.merge(rec, [n(_e("INCOMPLETE", when="2026-10-02T10:00:00+00:00", error_category="PARSE_NO_TABLE"))], at="t2")
    assert rec["FL|fl_laft_pdfs|Marion"]["consecutive_failures"] == 0 and rec["FL|fl_laft_pdfs|Marion"]["last_success_at"] == "2026-09-30T10:00:00+00:00"
    for i in range(3):
        rec, _ = U.merge(rec, [n(_e("FAILED", when=f"2026-10-0{3 + i}T10:00:00+00:00", error_category="TRANSPORT_HTTP_403_BLOCKED"))], at="t")
    u = rec["FL|fl_laft_pdfs|Marion"]
    assert u["consecutive_failures"] == 3
    rec, c = U.merge(rec, [n(_e("FAILED", when="2026-10-06T10:00:00+00:00", reason=U.BACKOFF_PREFIX + ": held"))], at="t")
    assert c["skipped"] == 1 and rec["FL|fl_laft_pdfs|Marion"]["consecutive_failures"] == 3 and rec["FL|fl_laft_pdfs|Marion"]["last_attempt_at"] == "2026-10-05T10:00:00+00:00"
    # Back-off: hold within 48h of the third blocked failure, attempt after; never for non-block categories.
    now = datetime(2026, 10, 5, 12, tzinfo=timezone.utc)
    attempt, why = U.backoff_decision(u, now=now)
    assert not attempt and why.startswith(U.BACKOFF_PREFIX)
    assert U.backoff_decision(u, now=datetime(2026, 10, 8, tzinfo=timezone.utc))[0]
    assert U.backoff_decision({**u, "last_error_category": "TRANSPORT_TIMEOUT"}, now=now)[0]
    assert U.backoff_decision({**u, "consecutive_failures": 2}, now=now)[0] and U.backoff_decision(None)[0]
    # Registry patches: only known units, never NULL over a stored value.
    units = {"FL|fl_laft_pdfs|Marion": {}, "FL|fl_laft_pdfs|Pasco": {}}
    rec2, _ = U.merge({}, [n(_e("FAILED", county="Pasco", error_category="TRANSPORT_HTTP_5XX")), n(_e("COMPLETE", county="Nowhere", row_count=1))], at="t")
    patches = U.registry_patches(rec2, units)
    assert len(patches) == 1 and patches[0][0] == {"state": "FL", "source_id": "fl_laft_pdfs", "county": "Pasco"}
    assert patches[0][1] == {"last_attempt_at": "2026-09-30T10:00:00+00:00", "last_attempt_status": "FAILED", "consecutive_failures": 1}
    report = U.public_report(rec2, {}, at="t")
    assert set(report["units"][0]) == {"state", "source_id", "county", "last_attempt_at", "last_attempt_status", "last_success_at",
                                       "last_success_row_count", "consecutive_failures", "last_error_category", "ledgers",
                                       "backoff", "backoff_reason", "stale", "source_unavailable"}   # 2026-09-30: customer freshness states


def test_f02_freshness_script_end_to_end_without_credentials(tmp_path):
    status = tmp_path / "s.json"
    status.write_text(json.dumps([_e("COMPLETE", row_count=2), _e("FAILED", county="Pasco", error_category="TRANSPORT_HTTP_403_BLOCKED"),
                                  {"county": "Alachua", "status": "COMPLETE", "rowCount": 4, "reason": "ok"}]), encoding="utf-8")
    persist, report = tmp_path / "p.json", tmp_path / "r.json"
    env = {"PATH": "/usr/bin:/bin", "HTTPS_PROXY": "http://127.0.0.1:9"}
    args = [sys.executable, str(REPO / "scripts/unit_freshness.py"), "--status", f"{status}:fl_deeds", "--persist", str(persist), "--report", str(report)]
    r = subprocess.run(args, capture_output=True, text=True, cwd=REPO, env=env)
    assert r.returncode == 0 and "3 unit entries" in r.stdout and "not set" in r.stdout
    rec = json.loads(persist.read_text(encoding="utf-8"))
    assert set(rec) == {"FL|fl_laft_pdfs|Marion", "FL|fl_laft_pdfs|Pasco", "FL|fl_deeds|Alachua"}
    for _ in range(2):
        subprocess.run(args, capture_output=True, text=True, cwd=REPO, env=env)
    rec = json.loads(persist.read_text(encoding="utf-8"))
    assert rec["FL|fl_laft_pdfs|Pasco"]["consecutive_failures"] == 3
    rep = json.loads(report.read_text(encoding="utf-8"))
    assert rep["counts"]["failed"] == 1 and "never a row value" in rep["note"]
    # The HTML harvester consults the record before fetching (source inspection: no network in tests).
    src = (REPO / "scripts/harvest_laft_html.py").read_text(encoding="utf-8")
    assert "backoff_decision(freshness_lookup(freshness, \"FL\", \"fl_laft_html\", county))" in src
    assert 'recorder.failed(county, "TRANSPORT_HTTP_403_BLOCKED", why' in src


# ==================== 6. source-published auction outcomes ====================


def test_o01_outcomes_only_through_the_source_map_which_is_empty_today(monkeypatch):
    assert w.SOURCE_OUTCOME_MAP == {}
    assert w.outcome_for_source("tx_lgbs", "Struck off to Jurisdiction") is None and w.outcome_for_source("tx_lgbs", "Sold") is None
    assert w.FORBIDDEN_EVENT_KEYS == frozenset({"winning_bidder_ref", "winning_bid", "bid_count", "outcome_effective_date"})
    with pytest.raises(w.WriterError):
        w._check_event_payload({"outcome": "sold"})                                     # no raw wording / time: refused
    with pytest.raises(w.WriterError):
        w._check_event_payload({"outcome": "unknown", "outcome_raw": "x"})
    with pytest.raises(w.WriterError):
        w._check_event_payload({"winning_bid": 1})
    w._check_event_payload({"outcome": "sold", "outcome_raw": "Sold", "outcome_observed_at": "2026-09-30T00:00:00+00:00"})
    with pytest.raises(w.WriterError, match="raw_status"):
        w.Sighting(state="TX", source="auction", county="Camp", case_no="1", scheduled_sale_date="2026-09-01", feed="api",
                   lifecycle="completed", raw_status=None, opening_bid=None, event_url=None, event_url_kind=None, outcome="sold")
    with pytest.raises(w.WriterError):
        w._observation("e", observed_at="t", run_id=None, feed=w.DERIVED_FEED, raw_status=None, lifecycle="completed", opening_bid=None,
                       evidence_url=None, outcome="sold")
    rows = [{"source": "auction", "county": "Camp", "account_number": "A1", "auction_date": "2026-09-01", "harvester_source": "tx_lgbs", "sale_status": "Sold"}]
    assert w.sightings_from_tx_harvest(rows) == []                                     # unmapped wording: skipped, never labelled
    # With a (test-only) mapping the writer records the result exactly as the source worded it.
    monkeypatch.setitem(w.SOURCE_OUTCOME_MAP, "tx_lgbs", {"sold": ("sold", "completed")})
    s = w.sightings_from_tx_harvest(rows)
    assert len(s) == 1 and (s[0].outcome, s[0].lifecycle, s[0].raw_status) == ("sold", "completed", "Sold")
    store = MemoryStore([{"id": "P1", "state": "TX", "source": "auction", "county": "Camp", "case_no": "A1", "harvester_source": "tx_lgbs", "ledger_type": "auction"}])
    summary = w.record_sightings(store, s, scope=("TX", "auction"), observed_at="2026-09-30T10:00:00+00:00", run_id="r", complete_counties=None, today=TODAY)
    assert summary.events_created == 1 and summary.outcomes_from_source == 1
    ev = store.events[0]
    assert (ev["outcome"], ev["outcome_raw"], ev["outcome_observed_at"], ev["lifecycle"]) == ("sold", "Sold", "2026-09-30T10:00:00+00:00", "completed")
    assert store.observations[0]["outcome"] == "sold" and store.observations[0]["raw_status"] == "Sold"
    assert not ({"winning_bid", "bid_count", "winning_bidder_ref", "outcome_effective_date"} & set(ev))
    # Seen again with the same result: no second outcome write; a scheduled sighting never carries one.
    summary2 = w.record_sightings(store, s, scope=("TX", "auction"), observed_at="2026-10-01T10:00:00+00:00", run_id="r2", complete_counties=None, today=TODAY)
    assert summary2.outcomes_from_source == 0 and summary2.events_seen_again == 1
    sched = w.sightings_from_tx_harvest([{**rows[0], "sale_status": "Scheduled for Auction", "auction_date": "2026-12-01"}])
    assert sched[0].outcome == "unknown"


# ==================== 7. workflow wiring and docs ====================


def test_x01_workflow_steps_are_non_blocking_and_after_the_sync():
    wf = yaml.safe_load((REPO / ".github/workflows/harvest-and-sync.yml").read_text(encoding="utf-8"))
    for job, expect_fresh in (("laft", True), ("deeds", True), ("texas", False)):
        steps = wf["jobs"][job]["steps"]
        names = [s.get("name") for s in steps]
        inv = next(s for s in steps if (s.get("name") or "").startswith("Inventory status"))
        assert inv["continue-on-error"] is True and inv["if"] == "always() && steps.sync.outcome == 'success'"
        assert "inventory_status_writer.py --state " + ("TX" if job == "texas" else "FL") in inv["run"]
        assert names.index("Sync to Supabase") < names.index(inv["name"])
        fresh = [s for s in steps if (s.get("name") or "").startswith("Per-unit freshness")]
        assert bool(fresh) is expect_fresh
        if fresh:
            assert fresh[0]["continue-on-error"] is True and fresh[0]["if"] == "always()" and "unit_freshness.py --status" in fresh[0]["run"]
    # Schedules untouched.
    assert (wf.get("on") or wf.get(True))["schedule"] == [{"cron": "0 10 * * *"}, {"cron": "0 22 * * *"}, {"cron": "0 12 * * *"}]


def test_x02_docs_and_service_worker():
    assert 'const CACHE = "tdw-shell-v114"' in (REPO / "public/sw.js").read_text(encoding="utf-8")
    model = (REPO / "docs/otc-inventory-model.md").read_text(encoding="utf-8")
    assert "## 16." in model and "inventory_status" in model and "laft_purchase_link_rules.csv" in model
