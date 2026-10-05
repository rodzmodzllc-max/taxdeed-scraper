"""Migration 027 (paid-beta billing + entitlements) - contract tests.

STATIC: no property row is written, no existing policy is dropped, the
properties policy added is RESTRICTIVE + SELECT only, billing tables take
every client privilege away before granting reads, the paid-beta seed equals
data/paid_beta_sources.csv.

LIVE (local PostgreSQL only, skipped otherwise): 027 applies verbatim twice on
top of the 015 scratch fixture; the shared entitlement vectors give the same
answers as billing_core.js; a paying customer passes is_approved() without
manual approval and sees only paid-beta rows; an approved tester and an admin
still see every row; an inactive / cancelled / payment-failed account sees
nothing; clients cannot write billing tables; admin_billing_overview() is
admin-only.
"""
from __future__ import annotations

import csv
import json
import re
import sys
import uuid
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
MIGRATION = REPO / "scripts" / "migrations" / "027_commercial_billing_entitlements.sql"
FIXTURE = REPO / "tests" / "python" / "fixtures" / "migration_015_scratch_fixture.sql"
VECTORS = REPO / "tests" / "billing" / "fixtures" / "entitlement_cases.json"
SQL = MIGRATION.read_text(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_migration_016_source_health import _psql_prefix, _run  # noqa: E402

TESTER = "11111111-1111-1111-1111-111111111111"     # approved in the fixture
TESTER_B = "22222222-2222-2222-2222-222222222222"   # approved in the fixture
PENDING = "33333333-3333-3333-3333-333333333333"    # not approved
PAID = "44444444-4444-4444-4444-444444444444"
LAPSED = "55555555-5555-5555-5555-555555555555"
ADMIN = "66666666-6666-6666-6666-666666666666"
MANUAL = "77777777-7777-7777-7777-777777777777"


def code() -> str:
    return "\n".join(l for l in SQL.splitlines() if not l.strip().startswith("--"))


def test_s01_no_property_write_no_policy_drop_except_its_own():
    body = code().lower()
    assert "delete from" not in body and "update public.properties" not in body and "insert into public.properties" not in body
    assert "drop table" not in body and "drop column" not in body
    dropped = re.findall(r'drop policy if exists "([^"]+)"', code())
    created = re.findall(r'create policy "([^"]+)"', code())
    assert set(dropped) <= set(created), "027 may only drop (to re-create) its own policies"
    assert "properties: approved only" not in code()


def test_s02_properties_policy_is_restrictive_select_authenticated():
    m = re.search(r'create policy "properties: paid customers see paid-beta sources only" on public\.properties\s+as (\w+) for (\w+) to (\w+)', code())
    assert m and m.groups() == ("restrictive", "select", "authenticated")


def test_s03_billing_tables_are_read_only_for_clients():
    body = code()
    assert "revoke all on public.billing_customers, public.subscriptions, public.billing_events, public.commercial_source_scope from anon, authenticated;" in body
    assert "grant select on public.billing_customers, public.subscriptions, public.billing_events, public.commercial_source_scope to authenticated;" in body
    assert not re.search(r"grant (insert|update|delete|all)[^;]*to authenticated", body.split("grant all on public.billing_customers")[0])


def test_s04_paid_beta_seed_matches_decision_file():
    seeded = set(re.findall(r"\('([a-z0-9_]+)', true,", code()))
    with open(REPO / "data" / "paid_beta_sources.csv", newline="", encoding="utf-8") as f:
        decided = {r["source_id"] for r in csv.DictReader(f) if r["paid_beta"] == "yes"}
    assert seeded == decided


def test_s05_is_approved_keeps_its_signature_and_attributes():
    m = re.search(r"create or replace function public\.is_approved\(\) returns boolean\s+language sql security definer\s+set search_path to 'public'", code())
    assert m, "is_approved() must keep SECURITY DEFINER + search_path"


# ==================== LIVE ====================

@pytest.fixture(scope="module")
def scratch():
    prefix = _psql_prefix()
    if prefix is None:
        pytest.skip("no local PostgreSQL reachable - live migration layer skipped (static layer still ran)")
    db = f"tdw_mig027_{uuid.uuid4().hex[:8]}"
    assert _run(prefix, "-Atc", f"create database {db}", db="postgres").returncode == 0
    staged = []
    # Production carries these properties columns (migrations 017 / 022).
    pre = Path("/tmp") / f"{db}_pre.sql"
    pre.write_text("""
      alter table public.properties add column source_id text, add column publication_status text;
      create or replace function public.is_admin() returns boolean language sql stable security definer set search_path to 'public'
        as $$ select coalesce((select is_admin from public.profiles where id = auth.uid()), false) $$;
    """, encoding="utf-8")
    pre.chmod(0o644)
    staged.append(pre)
    try:
        for path in (FIXTURE, pre, MIGRATION, MIGRATION):           # 027 applied twice: idempotent
            copy = Path("/tmp") / f"{db}_{len(staged)}_{path.name}"
            copy.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
            copy.chmod(0o644)
            staged.append(copy)
            r = _run(prefix, "-v", "ON_ERROR_STOP=1", "-q", "-f", str(copy), db=db)
            assert r.returncode == 0, f"{path.name} failed to apply:\n{r.stderr}"

        def run(sql):
            r = _run(prefix, "-v", "ON_ERROR_STOP=0", "-Atq", db=db, stdin=sql)
            return (r.stdout or "") + (r.stderr or "")
        seed = f"""
          insert into auth.users (id, email) values ('{PAID}', 'paid@example.com'), ('{LAPSED}', 'lapsed@example.com'),
                                                    ('{ADMIN}', 'admin@example.com'), ('{MANUAL}', 'manual@example.com');
          update public.profiles set is_admin = true, approved = true where id = '{ADMIN}';
          update public.profiles set approved = true, access_grant = 'customer' where id = '{MANUAL}';
          update public.properties set source_id = 'fl_realauction' where case_no in ('A-1', 'B-1');
          insert into public.properties (id, state, source, county, case_no, status, source_id, publication_status) values
            ('bbbbbbbb-0000-0000-0000-000000000001', 'LA', 'laft', 'East Baton Rouge', 'L-1', 'active', 'la_ebr_adjudicated', 'APPROVED'),
            ('bbbbbbbb-0000-0000-0000-000000000002', 'WY', 'auction', 'Albany', 'W-1', 'active', 'wy_albany_tax_sale', 'APPROVED'),
            ('bbbbbbbb-0000-0000-0000-000000000003', 'MI', 'laft', 'Wayne', 'D-1', 'active', 'mi_detroit_landbank_lots', 'UNREVIEWED'),
            ('bbbbbbbb-0000-0000-0000-000000000004', 'TX', 'auction', 'Harris', 'X-1', 'active', 'tx_mvba', 'BLOCKED');
          set role service_role;
          insert into public.subscriptions (stripe_subscription_id, user_id, stripe_customer_id, status, plan_key, current_period_end)
            values ('sub_paid', '{PAID}', 'cus_paid', 'active', 'monthly', now() + interval '20 days'),
                   ('sub_lapsed', '{LAPSED}', 'cus_lapsed', 'canceled', 'monthly', now() - interval '2 days');
        """
        out = run(seed)
        assert "ERROR" not in out, out
        yield run
    finally:
        _run(prefix, "-Atc", f"drop database if exists {db}", db="postgres")
        for c in staged:
            c.unlink(missing_ok=True)


def as_user(uid: str, sql: str) -> str:
    return f"""set role authenticated; set request.jwt.claims = '{{"sub":"{uid}","role":"authenticated"}}';\n{sql}"""


def ids(out: str) -> list[str]:
    return sorted(l for l in out.splitlines() if re.match(r"^[ab]{8}-", l))


def test_l01_shared_vectors_match_billing_core(scratch):
    vectors = json.loads(VECTORS.read_text(encoding="utf-8"))
    now = vectors["now"]
    for i, c in enumerate(vectors["cases"]):
        uid = f"9{i:07d}-0000-0000-0000-000000000000"
        prof = c["profile"]
        sql = ["set role postgres;"]
        if prof is not None:
            sql.append(f"insert into auth.users (id, email) values ('{uid}', 'v{i}@example.com');")
            sql.append(f"update public.profiles set approved = {str(prof['approved']).lower()}, is_admin = {str(prof['is_admin']).lower()}, "
                       f"access_grant = '{prof['access_grant']}' where id = '{uid}';")
        else:
            sql.append(f"insert into auth.users (id, email) values ('{uid}', 'v{i}@example.com'); delete from public.profiles where id = '{uid}';")
        for j, s in enumerate(c["subscriptions"]):
            def q(k):
                v = s.get(k)
                return "null" if v is None else f"'{v}'"
            sql.append(
                "insert into public.subscriptions (stripe_subscription_id, user_id, stripe_customer_id, status, plan_key, current_period_end, "
                "cancel_at_period_end, payment_failed_at, stripe_event_created) values "
                f"('sub_v{i}_{j}', '{uid}', 'cus_v{i}', '{s['status']}', {q('plan_key')}, {q('current_period_end')}, "
                f"{str(bool(s.get('cancel_at_period_end'))).lower()}, {q('payment_failed_at')}, {q('stripe_event_created')});")
        sql.append(f"select public.entitlement_for('{uid}', '{now}');")
        out = scratch("\n".join(sql))
        got = json.loads(out.strip().splitlines()[-1])
        for k, v in c["expect"].items():
            assert got[k] == v, f"{c['name']}.{k}: sql={got[k]} js={v}"


def test_l02_tester_and_admin_see_every_row(scratch):
    q = "select id from properties;"
    tester_rows = ids(scratch(as_user(TESTER, q)))
    admin_rows = ids(scratch(as_user(ADMIN, q)))
    assert len(tester_rows) == 7 and tester_rows == admin_rows


def test_l03_paying_customer_sees_paid_beta_rows_only_without_manual_approval(scratch):
    out = scratch(as_user(PAID, "select public.is_approved(); select id from properties;"))
    assert out.splitlines()[0] == "t"
    assert ids(out) == ["bbbbbbbb-0000-0000-0000-000000000001"]      # LA only: WY approved but not paid-beta; others not approved


def test_l04_manual_customer_gets_the_paid_scope(scratch):
    assert ids(scratch(as_user(MANUAL, "select id from properties;"))) == ["bbbbbbbb-0000-0000-0000-000000000001"]


def test_l05_inactive_and_lapsed_see_nothing(scratch):
    for uid in (PENDING, LAPSED):
        out = scratch(as_user(uid, "select public.is_approved(); select count(*) from properties;"))
        assert out.split() == ["f", "0"], uid


def test_l06_entitlement_is_readable_only_for_yourself(scratch):
    out = scratch(as_user(PAID, "select public.my_entitlement()->>'role', public.my_entitlement()->>'state';"))
    assert out.split() == ["customer|active"]
    out = scratch(as_user(PAID, f"select public.entitlement_for('{TESTER}');"))
    assert "permission denied" in out


def test_l07_clients_cannot_write_billing_tables(scratch):
    out = scratch(as_user(PAID, f"""
      insert into subscriptions (stripe_subscription_id, user_id, stripe_customer_id, status, plan_key) values ('sub_x', '{PAID}', 'c', 'active', 'monthly');
      update subscriptions set status = 'active' where user_id = '{LAPSED}';
      insert into billing_events (stripe_event_id, type) values ('evt_x', 'x');
      insert into commercial_source_scope (source_id, paid_beta, reason, decided_on) values ('tx_mvba', true, 'x', '2026-10-05');
      select count(*) from subscriptions; select count(*) from billing_events;"""))
    assert out.count("permission denied") == 4
    assert [l for l in out.splitlines() if l.isdigit()] == ["1", "0"]       # own subscription only; events are admin-read
    out = scratch(as_user(LAPSED, "update subscriptions set status = 'active';"))
    assert "permission denied" in out
    assert scratch("set role anon; select count(*) from subscriptions;").count("permission denied") == 1


def test_l08_admin_overview_is_admin_only_and_explains_access(scratch):
    out = scratch(as_user(ADMIN, "select email, role, state, access from admin_billing_overview() order by email;"))
    rows = dict((l.split("|")[0], l.split("|")[1:]) for l in out.splitlines() if "|" in l)
    assert rows["admin@example.com"] == ["admin", "admin_override", "t"]
    assert rows["a@example.com"] == ["tester", "tester_beta", "t"]
    assert rows["paid@example.com"] == ["customer", "active", "t"]
    assert rows["manual@example.com"] == ["customer", "manual_customer", "t"]
    assert rows["lapsed@example.com"] == ["inactive", "cancelled", "f"]
    assert rows["pending@example.com"] == ["inactive", "inactive", "f"]
    assert "admin only" in scratch(as_user(TESTER, "select * from admin_billing_overview();"))


def test_l09_payment_failed_beyond_grace_loses_access(scratch):
    scratch(f"update public.subscriptions set status = 'past_due', payment_failed_at = now() - interval '10 days' where user_id = '{PAID}';")
    try:
        out = scratch(as_user(PAID, "select public.my_entitlement()->>'state'; select count(*) from properties;"))
        assert out.split() == ["payment_failed", "0"]
        scratch(f"update public.subscriptions set payment_failed_at = now() - interval '2 days' where user_id = '{PAID}';")
        out = scratch(as_user(PAID, "select public.my_entitlement()->>'state'; select count(*) from properties;"))
        assert out.split() == ["payment_failed_grace", "1"]
    finally:
        scratch(f"update public.subscriptions set status = 'active', payment_failed_at = null where user_id = '{PAID}';")


def test_l10_existing_approval_model_unchanged(scratch):
    out = scratch(f"select approved, access_grant from public.profiles where id in ('{TESTER}', '{TESTER_B}', '{PENDING}') order by id;")
    assert out.split() == ["t|tester", "t|tester", "f|tester"]
