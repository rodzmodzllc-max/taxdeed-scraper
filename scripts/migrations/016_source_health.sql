-- Migration 016: dataset-level source health, recorded by the harvest jobs.
--
-- STATUS: PROPOSED, NOT APPLIED. Applied by hand by the project owner after
-- review, like every file in this directory. Safe to apply before or after
-- 015; independent of it.
--
-- WHY
--
-- A green GitHub Actions run does not mean the datasets are healthy: the
-- deeds job hard-fails only below 15 fresh counties, the LAFT check is
-- advisory, certificates has no check, Texas is manual-only, and a county
-- whose calendar fetch failed is recorded as INCOMPLETE in the per-run
-- status file (harvest_all_status.json etc.) that nobody but the artifact
-- ever sees. The app shows one dataset-wide "Data updated <newest row>"
-- line - the newest row across every source - which hides a source that
-- stopped. This table is one row per source, written by
-- scripts/source_health.py at the end of each job's sync step (whether the
-- sync succeeded or failed), so the app can say, per dataset: last attempt,
-- last success, how many rows, how many of its units (counties or vendor
-- sources) were complete, and the error when there was one.
--
-- WHAT THIS DOES NOT DO
--
--   - Does not change any harvester, sync, retry or completeness gate. The
--     writer is `continue-on-error`, runs after the sync and never re-runs
--     anything (docs/production-configuration.md, "Source health").
--   - Does not classify. HEALTHY / INCOMPLETE / FAILED / STALE / NOT_RUN is
--     derived at read time from these columns (in the app and in the
--     writer's own summary), because staleness depends on when you look.
--   - Does not store row data. Counts and unit names (county names, vendor
--     source names) only.
--
-- ACCESS: same posture as auction_events - RLS on, approved users read,
-- only service_role writes.

begin;

create table public.source_health (
  source            text        primary key,
  label             text        not null,
  state             text        not null,
  mode              text        not null default 'scheduled'
                    constraint source_health_mode_check check (mode in ('scheduled', 'manual')),
  cadence_hours     integer,
  last_attempt_at   timestamptz,
  last_attempt_status text
                    constraint source_health_attempt_status_check
                    check (last_attempt_status is null or last_attempt_status in ('SUCCESS', 'FAILED', 'INCOMPLETE')),
  last_success_at   timestamptz,
  last_run_id       text,
  row_count         integer,
  units_total       integer,
  units_complete    integer,
  units_incomplete  integer,
  incomplete_units  text[],
  completeness      text        not null default 'UNKNOWN'
                    constraint source_health_completeness_check
                    check (completeness in ('COMPLETE', 'INCOMPLETE', 'UNKNOWN')),
  error             text,
  updated_at        timestamptz not null default now()
);

comment on table public.source_health is
  'One row per harvested dataset, written by scripts/source_health.py after each job''s sync step. Health (HEALTHY/INCOMPLETE/FAILED/STALE/NOT_RUN) is derived at read time.';

alter table public.source_health enable row level security;

create policy "source_health: approved read" on public.source_health
  as permissive for select to authenticated
  using (public.is_approved());

revoke all on public.source_health from anon, public;
revoke all on public.source_health from authenticated;
grant select on public.source_health to authenticated;
grant select, insert, update, delete on public.source_health to service_role;

create trigger source_health_touch before update on public.source_health
  for each row execute function public.touch_updated_at();

commit;

-- Rollback:
--   drop table public.source_health;
