"""Migration 016 (source_health) and scripts/source_health.py - contract tests.

STATIC: the migration creates exactly one table with the documented columns,
RLS on, approved-read only, service_role write; the script derives health
the same way public/app.js does; the workflow records health after every
sync step without being able to fail or retry a job.

LIVE (local PostgreSQL only, skipped otherwise): 016 applies verbatim on top
of the 015 scratch fixture; an approved user can read, a pending user reads
nothing, authenticated cannot write, service_role can upsert.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
MIGRATION = REPO / "scripts" / "migrations" / "016_source_health.sql"
FIXTURE = REPO / "tests" / "python" / "fixtures" / "migration_015_scratch_fixture.sql"
SCRIPT = REPO / "scripts" / "source_health.py"
WORKFLOW = REPO / ".github" / "workflows" / "harvest-and-sync.yml"
APP = (REPO / "public" / "app.js").read_text(encoding="utf-8")
SQL = MIGRATION.read_text(encoding="utf-8")

sys.path.insert(0, str(REPO / "scripts"))
import source_health as sh  # noqa: E402

COLUMNS = ["source", "label", "state", "mode", "cadence_hours", "last_attempt_at", "last_attempt_status",
           "last_success_at", "last_run_id", "row_count", "units_total", "units_complete", "units_incomplete",
           "incomplete_units", "completeness", "error", "updated_at"]


def sql_only() -> str:
    return "\n".join(l for l in SQL.splitlines() if not l.strip().startswith("--"))


# ==================== STATIC: migration ====================


def test_s01_creates_one_table_with_the_documented_columns_and_nothing_else():
    body = sql_only().lower()
    assert body.count("create table") == 1
    block = re.search(r"create table public\.source_health \((.*?)\n\);", body, re.S).group(1)
    for col in COLUMNS:
        assert re.search(rf"^\s+{col}\s", block, re.M), col
    for forbidden in ("properties", "auction_events", "insert into", "drop ", "alter table public.properties"):
        assert forbidden not in body.replace("comment on table public.source_health", ""), forbidden


def test_s02_access_posture_matches_auction_events():
    body = sql_only().lower()
    assert "enable row level security" in body
    assert 'create policy "source_health: approved read" on public.source_health' in body
    assert "for select to authenticated" in body and "using (public.is_approved())" in body
    assert "revoke all on public.source_health from anon, public" in body
    assert "revoke all on public.source_health from authenticated" in body
    assert "grant select on public.source_health to authenticated" in body
    assert "grant select, insert, update, delete on public.source_health to service_role" in body
    assert body.strip().startswith("begin;") and body.strip().endswith("commit;")


# ==================== STATIC: the script and the app agree ====================


def _rec(**kw):
    base = {"mode": "scheduled", "cadence_hours": 12, "last_attempt_at": "2026-09-29T10:00:00+00:00",
            "last_attempt_status": "SUCCESS", "last_success_at": "2026-09-29T10:00:00+00:00", "completeness": "COMPLETE"}
    base.update(kw)
    return base


def test_s03_derive_health_vocabulary():
    at = datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)
    assert sh.derive_health({}, at) == "NOT_RUN"
    assert sh.derive_health(_rec(), at) == "HEALTHY"
    assert sh.derive_health(_rec(last_attempt_status="FAILED"), at) == "FAILED"
    assert sh.derive_health(_rec(completeness="INCOMPLETE", last_attempt_status="INCOMPLETE"), at) == "INCOMPLETE"
    assert sh.derive_health(_rec(last_success_at=(at - timedelta(hours=25)).isoformat()), at) == "STALE"
    assert sh.derive_health(_rec(last_success_at=(at - timedelta(hours=23)).isoformat()), at) == "HEALTHY"
    # A manual source is never STALE by the clock.
    assert sh.derive_health(_rec(mode="manual", cadence_hours=None, last_success_at="2026-01-01T00:00:00+00:00"), at) == "HEALTHY"
    # Incomplete is never reported as empty / healthy.
    assert sh.derive_health(_rec(completeness="INCOMPLETE"), at) != "HEALTHY"


def test_s04_app_mirror_of_derive_health_exists_with_the_same_rules():
    assert "function healthOf(rec, now)" in APP
    assert "const HEALTH_STALE_MULTIPLIER = 2;" in APP and sh.STALE_MULTIPLIER == 2
    fn = APP.split("function healthOf(rec, now)")[1].split("\n}\n")[0]
    for line in ('return "NOT_RUN"', 'return "FAILED"', 'return "INCOMPLETE"', 'return "STALE"', 'return "HEALTHY"'):
        assert line in fn, line
    assert 'rec.mode === "scheduled" && rec.cadence_hours' in fn
    # The app never says a dataset is healthy when the table is absent.
    assert "not recorded yet" in APP
    assert 'sb.from("source_health").select("*")' in APP


def test_s05_units_from_both_status_shapes_and_row_counts():
    fl = [{"county": "Alachua", "status": "COMPLETE", "rowCount": 3}, {"county": "Baker", "status": "INCOMPLETE", "rowCount": 0}]
    assert sh.units_from_status(fl) == (["Alachua"], ["Baker"])
    tx = {"retrieved_at": "x", "sources": {"lgbs": {"complete": False, "rows": 0}, "realauction": {"complete": True, "rows": 20}}}
    assert sh.units_from_status(tx) == (["realauction"], ["lgbs"])
    assert sh.row_count_of(None, fl) == 3
    manifest = {"tables": {"properties": {"rows": 10}, "notes": {"rows": 2}}}
    assert sh.row_count_of(None, manifest) == 12


def test_s06_script_end_to_end_without_network_writes_evidence_and_never_fails(tmp_path):
    status = tmp_path / "harvest_all_status.json"
    status.write_text(json.dumps([{"county": "Alachua", "status": "COMPLETE", "rowCount": 2}, {"county": "Baker", "status": "INCOMPLETE", "rowCount": 0, "reason": "curl exit 7"}]))
    rows = tmp_path / "harvest_all.json"
    rows.write_text(json.dumps([{"county": "Alachua", "owner_name": "Jane Private", "address": "1 Secret St"}, {"county": "Alachua"}]))
    env = {k: v for k, v in os.environ.items() if k not in ("SUPABASE_URL", "SUPABASE_SERVICE_KEY")}
    r = subprocess.run([sys.executable, str(SCRIPT), "--source", "fl_deeds", "--label", "Florida deeds", "--state", "FL",
                        "--cadence-hours", "12", "--status", str(status), "--rows", str(rows), "--outcome", "success",
                        "--public-dir", str(tmp_path / "public")], capture_output=True, text=True, env=env, cwd=tmp_path)
    assert r.returncode == 0, r.stderr
    ev = json.loads((tmp_path / "public" / "source_health-fl_deeds.json").read_text())
    assert ev["health"] == "INCOMPLETE" and ev["last_attempt_status"] == "INCOMPLETE"
    assert ev["row_count"] == 2 and ev["units_total"] == 2 and ev["incomplete_units"] == ["Baker"]
    assert ev["last_success_at"] == ev["last_attempt_at"]
    text = json.dumps(ev)
    assert "Jane Private" not in text and "1 Secret St" not in text
    assert "::warning" in r.stdout and "SUPABASE_URL" in r.stdout
    # A failed sync is FAILED, keeps no success timestamp, still exits 0.
    r = subprocess.run([sys.executable, str(SCRIPT), "--source", "fl_deeds", "--label", "Florida deeds", "--state", "FL",
                        "--status", str(status), "--rows", str(rows), "--outcome", "failure", "--no-upsert",
                        "--public-dir", str(tmp_path / "public")], capture_output=True, text=True, env=env, cwd=tmp_path)
    assert r.returncode == 0
    ev = json.loads((tmp_path / "public" / "source_health-fl_deeds.json").read_text())
    assert ev["health"] == "FAILED" and ev["last_success_at"] is None and "failure" in ev["error"]


def test_s07_workflow_records_health_after_every_sync_step_without_retrying_or_failing():
    wf = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    expected = {"deeds": "fl_deeds", "certificates": "fl_certificates", "laft": "fl_laft", "texas": "tx_sales", "backup": "db_backup"}
    for job, source in expected.items():
        steps = wf["jobs"][job]["steps"]
        sync = [i for i, s in enumerate(steps) if s.get("id") == "sync"]
        assert len(sync) == 1, job
        health = [i for i, s in enumerate(steps) if "scripts/source_health.py" in str(s.get("run", ""))]
        assert len(health) == 1, job
        assert health[0] == sync[0] + 1, f"{job}: health step must directly follow the sync step"
        step = steps[health[0]]
        assert step.get("if") == "always()" and step.get("continue-on-error") is True
        assert f"--source {source}" in step["run"]
        assert "--outcome ${{ steps.sync.outcome }}" in step["run"]
        # Never a harvester invocation, never a retry.
        assert "harvest" not in step["run"].split("--status")[0].replace("harvest_", "")
    # Texas is manual, everything else scheduled with a cadence.
    tx = next(s for s in wf["jobs"]["texas"]["steps"] if "source_health.py" in str(s.get("run", "")))
    assert "--mode manual" in tx["run"] and "--cadence-hours" not in tx["run"]
    for job, hours in (("deeds", 12), ("certificates", 24), ("laft", 24), ("backup", 24)):
        st = next(s for s in wf["jobs"][job]["steps"] if "source_health.py" in str(s.get("run", "")))
        assert f"--cadence-hours {hours}" in st["run"], job


def test_s08_no_harvest_or_sync_script_changed_by_the_monitoring_work():
    """The brief: do not change harvest behaviour or retries. The monitoring
    code lives only in the new script and the workflow step."""
    for rel in ("scripts/harvest_all_counties.ps1", "scripts/sync-harvest-to-supabase.ps1", "harvesters/texas_harvester.py",
                "scripts/sync-texas-to-supabase.py", "scripts/harvest_lienhub_certificates.ps1", "scripts/sync-laft-to-supabase.ps1"):
        assert "source_health" not in (REPO / rel).read_text(encoding="utf-8", errors="replace"), rel


# ==================== LIVE ====================


def _psql_prefix():
    override = os.environ.get("TDW_SCRATCH_PG")
    candidates = [override.split()] if override else []
    if shutil.which("psql"):
        candidates += [["psql"], ["su", "postgres", "-c", "psql"]]
    for cand in candidates:
        try:
            r = _run(cand, "-Atc", "select 1", db="postgres", timeout=15)
        except Exception:
            continue
        if r.returncode == 0 and r.stdout.strip() == "1":
            return cand
    return None


def _run(prefix, *args, db, timeout=120, stdin=None):
    if prefix[:2] == ["su", "postgres"]:
        cmd = ["su", "postgres", "-c", " ".join(["psql", "-d", db, *(f"'{a}'" if " " in a else a for a in args)])]
    else:
        cmd = [*prefix, "-d", db, *args]
    return subprocess.run(cmd, input=stdin, capture_output=True, text=True, timeout=timeout)


@pytest.fixture(scope="module")
def scratch():
    prefix = _psql_prefix()
    if prefix is None:
        pytest.skip("no local PostgreSQL reachable - live migration layer skipped (static layer still ran)")
    db = f"tdw_mig016_{uuid.uuid4().hex[:8]}"
    assert _run(prefix, "-Atc", f"create database {db}", db="postgres").returncode == 0
    staged = []
    try:
        for path in (FIXTURE, MIGRATION):
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
USER_PENDING = "33333333-3333-3333-3333-333333333333"


def test_l01_service_role_writes_approved_reads_pending_reads_nothing_clients_cannot_write(scratch):
    out = scratch("""set role service_role;
      insert into public.source_health (source, label, state, mode, cadence_hours, last_attempt_at, last_attempt_status, last_success_at, row_count, completeness)
      values ('fl_deeds', 'Florida deeds', 'FL', 'scheduled', 12, now(), 'SUCCESS', now(), 800, 'COMPLETE')
      on conflict (source) do update set row_count = excluded.row_count;
      insert into public.source_health (source, label, state, mode, cadence_hours, last_attempt_at, last_attempt_status, last_success_at, row_count, completeness)
      values ('fl_deeds', 'Florida deeds', 'FL', 'scheduled', 12, now(), 'SUCCESS', now(), 812, 'COMPLETE')
      on conflict (source) do update set row_count = excluded.row_count;
      select row_count from public.source_health;""")
    assert "ERROR" not in out and out.strip().splitlines()[-1] == "812"
    out = scratch(f"""set role authenticated; set request.jwt.claims = '{{"sub":"{USER_A}","role":"authenticated"}}';
      select source||':'||row_count from public.source_health;
      insert into public.source_health (source, label, state) values ('x', 'x', 'FL');
      update public.source_health set row_count = 0;
      delete from public.source_health;""")
    assert "fl_deeds:812" in out
    assert out.count("permission denied for table source_health") == 3
    out = scratch(f"""set role authenticated; set request.jwt.claims = '{{"sub":"{USER_PENDING}","role":"authenticated"}}';
      select count(*) from public.source_health;""")
    assert out.strip() == "0"
    out = scratch("set role anon; select count(*) from public.source_health;")
    assert "permission denied" in out


def test_l02_check_constraints_reject_out_of_vocabulary_values(scratch):
    out = scratch("""set role service_role;
      insert into public.source_health (source, label, state, mode) values ('bad1', 'x', 'FL', 'sometimes');
      insert into public.source_health (source, label, state, completeness) values ('bad2', 'x', 'FL', 'MOSTLY');
      insert into public.source_health (source, label, state, last_attempt_status) values ('bad3', 'x', 'FL', 'OK');""")
    assert out.count("violates check constraint") == 3
