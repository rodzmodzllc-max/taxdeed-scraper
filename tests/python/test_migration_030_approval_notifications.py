"""Migration 030 (account-approval notification outbox) - contract tests.
Written, NOT applied.

STATIC: additive only (profiles' columns untouched, nothing dropped); the
trigger fires only on approved false -> true; customers have no write path
and no claim/finish access; one row per (user, kind); no backfill of
already-approved accounts.

LIVE (local PostgreSQL only, skipped otherwise): 030 applies verbatim (twice)
on top of the 015 scratch fixture; approving a pending account queues exactly
one notification in the same transaction; pending / rejected / re-saved /
re-approved / failed approvals queue nothing more; only an admin can approve
(a customer's UPDATE changes nothing and queues nothing); claim / finish /
requeue behave as the sender relies on.
"""
from __future__ import annotations

import sys
import uuid
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
MIGRATION = REPO / "scripts" / "migrations" / "030_account_approval_notifications.sql"
FIXTURE = REPO / "tests" / "python" / "fixtures" / "migration_015_scratch_fixture.sql"
SQL = MIGRATION.read_text(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_migration_016_source_health import _psql_prefix, _run  # noqa: E402

ADMIN = "44444444-4444-4444-4444-444444444444"
CUSTOMER = "11111111-1111-1111-1111-111111111111"     # approved in the fixture
PENDING = "33333333-3333-3333-3333-333333333333"
PENDING2 = "55555555-5555-5555-5555-555555555555"


def code() -> str:
    return "\n".join(l for l in SQL.splitlines() if not l.strip().startswith("--"))


def test_s01_additive_only_no_backfill():
    body = code().lower()
    for bad in ("drop table", "drop column", "alter column", "delete from", "truncate", "alter table public.profiles add"):
        assert bad not in body
    assert "insert into public.account_notifications" in body
    # The only insert is the trigger's; nothing selects existing approved profiles into the outbox.
    assert body.count("insert into public.account_notifications") == 1
    assert "on conflict (user_id, kind) do nothing" in body
    assert "unique (user_id, kind)" in body


def test_s02_trigger_is_transition_only_and_privileges_are_closed():
    body = code()
    assert "after update of approved on public.profiles" in body
    assert "when (new.approved is true and old.approved is distinct from true)" in body
    assert "revoke all on public.account_notifications from public, anon, authenticated;" in body
    assert "grant select on public.account_notifications to authenticated;" in body
    assert "using ((select public.is_admin()))" in body
    for fn in ("claim_account_notifications(integer, integer)", "finish_account_notification(uuid, integer, text, text, text, integer)"):
        assert f"revoke all on function public.{fn} from public, anon, authenticated;" in body
        assert f"grant execute on function public.{fn} to service_role;" in body
    assert "for update skip locked" in body
    assert "where id = p_id and status = 'sending' and attempts = p_attempt" in body


# ==================== LIVE ====================

@pytest.fixture(scope="module")
def scratch():
    prefix = _psql_prefix()
    if prefix is None:
        pytest.skip("no local PostgreSQL reachable - live migration layer skipped (static layer still ran)")
    db = f"tdw_mig030_{uuid.uuid4().hex[:8]}"
    assert _run(prefix, "-Atc", f"create database {db}", db="postgres").returncode == 0
    staged = []
    # The admin and a second pending account exist BEFORE 030 (like every
    # account in production), so applying 030 must not queue anything for them.
    seed = (f"insert into auth.users (id, email) values ('{ADMIN}', 'admin@example.com'), ('{PENDING2}', 'p2@example.com');\n"
            f"update public.profiles set approved = true, is_admin = true where id = '{ADMIN}';\n")
    try:
        for path, text in ((FIXTURE, None), (Path("seed.sql"), seed), (MIGRATION, None), (MIGRATION, None)):
            copy = Path("/tmp") / f"{db}_{len(staged)}_{path.name}"
            copy.write_text(text if text is not None else path.read_text(encoding="utf-8"), encoding="utf-8")
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


def as_user(uid: str, sql: str) -> str:
    return f"""set role authenticated; set request.jwt.claims = '{{"sub":"{uid}","role":"authenticated"}}';\n{sql}"""


def queued(run, uid) -> str:
    return run(f"select count(*) from account_notifications where user_id = '{uid}';").strip()


def test_l01_existing_approved_accounts_are_not_backfilled(scratch):
    # The fixture approved two customers (and this module the admin) BEFORE 030's
    # second application; the first application ran after them too - no rows.
    # Two fixture customers and the admin were approved before 030 was applied (twice): no rows.
    assert scratch("select count(*) from account_notifications;").strip() == "0"


def test_l02_admin_approval_queues_exactly_one_in_the_same_transaction(scratch):
    out = scratch(as_user(ADMIN, f"update profiles set approved = true, approved_at = now() where id = '{PENDING}';"))
    assert "ERROR" not in out
    assert queued(scratch, PENDING) == "1"
    row = scratch(f"select kind||'|'||status||'|'||attempts from account_notifications where user_id = '{PENDING}';").strip()
    assert row == "account_approved|pending|0"


def test_l03_resave_reapprove_and_unrelated_updates_queue_nothing_more(scratch):
    scratch(as_user(ADMIN, f"update profiles set approved = true where id = '{PENDING}';"))            # approve again
    scratch(as_user(ADMIN, f"update profiles set approved_at = now() where id = '{PENDING}';"))         # unrelated edit
    scratch(as_user(ADMIN, f"update profiles set is_admin = false where id = '{PENDING}';"))
    scratch(as_user(ADMIN, f"update profiles set approved = false where id = '{PENDING}';"))           # revoke ...
    scratch(as_user(ADMIN, f"update profiles set approved = true where id = '{PENDING}';"))            # ... re-approve
    assert queued(scratch, PENDING) == "1"


def test_l04_pending_rejected_and_rolled_back_approvals_queue_nothing(scratch):
    scratch(as_user(ADMIN, f"update profiles set requested_at = now() where id = '{PENDING2}';"))     # still pending
    assert queued(scratch, PENDING2) == "0"
    # Approval that fails to persist (transaction rolled back) -> nothing queued.
    scratch(as_user(ADMIN, f"begin; update profiles set approved = true where id = '{PENDING2}'; rollback;"))
    assert queued(scratch, PENDING2) == "0"
    assert scratch(f"select approved from profiles where id = '{PENDING2}';").strip() == "f"


def test_l05_customers_cannot_approve_or_touch_the_outbox(scratch):
    out = scratch(as_user(CUSTOMER, f"update profiles set approved = true where id = '{PENDING2}' returning id;"))
    assert out.strip() == ""                                     # RLS: no row matched, nothing changed
    assert queued(scratch, PENDING2) == "0"
    out = scratch(as_user(PENDING2, f"update profiles set approved = true where id = '{PENDING2}' returning id;"))
    assert out.strip() == ""                                     # cannot approve themselves
    assert queued(scratch, PENDING2) == "0"
    assert scratch(as_user(CUSTOMER, "select count(*) from account_notifications;")).strip() == "0"
    out = scratch(as_user(CUSTOMER, f"insert into account_notifications (user_id, kind) values ('{CUSTOMER}', 'account_approved');"))
    assert "permission denied" in out
    out = scratch(as_user(CUSTOMER, "select * from claim_account_notifications(10, 300);"))
    assert "permission denied" in out
    out = scratch(as_user(ADMIN, "select * from claim_account_notifications(10, 300);"))
    assert "permission denied" in out                            # even an admin's browser cannot claim
    out = scratch("set role anon; select count(*) from account_notifications;")
    assert "permission denied" in out
    assert scratch(as_user(ADMIN, "select count(*) from account_notifications;")).strip() == "1"   # admins can monitor


def test_l06_claim_finish_retry_and_stale_attempts(scratch):
    claim = "set role service_role; select id||'|'||attempt||'|'||coalesce(email,'')||'|'||approved from claim_account_notifications(10, 300);"
    first = scratch(claim).strip().splitlines()
    assert len(first) == 1 and first[0].split("|")[1:] == ["1", "pending@example.com", "true"]
    nid = first[0].split("|")[0]
    assert scratch(claim).strip() == ""                          # leased: a second sender gets nothing
    out = scratch(f"set role service_role; select finish_account_notification('{nid}', 1, 'failed', null, 'HTTP_503', 60);")
    assert out.strip() == "t"
    assert scratch(f"select status||'|'||last_error||'|'||(next_attempt_at > now()) from account_notifications where id = '{nid}';").strip() == "failed|HTTP_503|true"
    assert scratch(claim).strip() == ""                          # back-off not elapsed
    scratch(f"update account_notifications set next_attempt_at = now() - interval '1 second' where id = '{nid}';")
    second = scratch(claim).strip().splitlines()
    assert second[0].split("|")[1] == "2"
    out = scratch(f"set role service_role; select finish_account_notification('{nid}', 1, 'sent', 'm-stale', null, 60);")
    assert out.strip() == "f"                                    # a stale attempt cannot record
    out = scratch(f"set role service_role; select finish_account_notification('{nid}', 2, 'sent', 're_123', null, 60);")
    assert out.strip() == "t"
    assert scratch(f"select status||'|'||provider_message_id||'|'||(sent_at is not null)||'|'||coalesce(last_error,'-') from account_notifications where id = '{nid}';").strip() == "sent|re_123|true|-"
    scratch(f"update account_notifications set next_attempt_at = now() - interval '1 day' where id = '{nid}';")
    assert scratch(claim).strip() == ""                          # a sent notification is never claimed again
    out = scratch(as_user(ADMIN, f"select requeue_account_notification('{nid}');"))
    assert out.strip() == "f"                                    # sent is never re-queued


def test_l07_admin_requeue_only_for_failed_and_only_by_admins(scratch):
    scratch(as_user(ADMIN, f"update profiles set approved = true where id = '{PENDING2}';"))
    nid = scratch(f"select id from account_notifications where user_id = '{PENDING2}';").strip()
    scratch(f"update account_notifications set status = 'failed', attempts = 8, last_error = 'HTTP_500' where id = '{nid}';")
    assert scratch("set role service_role; select count(*) from claim_account_notifications(10, 300);").strip() == "0"   # exhausted
    out = scratch(as_user(CUSTOMER, f"select requeue_account_notification('{nid}');"))
    assert "admin only" in out
    assert scratch(as_user(ADMIN, f"select requeue_account_notification('{nid}');")).strip() == "t"
    assert scratch(f"select status||'|'||attempts from account_notifications where id = '{nid}';").strip() == "pending|0"
    assert scratch("set role service_role; select count(*) from claim_account_notifications(10, 300);").strip() == "1"


def test_l08_finish_rejects_unknown_outcome_and_trims_error(scratch):
    out = scratch(f"set role service_role; select finish_account_notification(gen_random_uuid(), 1, 'delivered', null, null, 60);")
    assert "unknown outcome" in out
    out = scratch(f"insert into account_notifications (user_id, kind, last_error) values ('{CUSTOMER}', 'account_approved', repeat('x', 81));")
    assert "check constraint" in out
