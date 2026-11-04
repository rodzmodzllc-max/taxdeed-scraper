-- 036_source_link_checks.sql
-- Daily health of every source link a customer can click (2026-10-27).
--
-- STATUS: WRITTEN, NOT APPLIED. Applied by hand by the project owner after
-- review, like every file in this directory. Independent of 031 / 032 / 033 /
-- 034 / 035; safe to apply more than once.
--
-- WHY
--
-- Hendry County's only Lands Available row linked to a county PDF that had
-- answered HTTP 404 for four weeks; the app kept offering it. The daily
-- scripts/check_source_links.py (workflow source-link-check.yml) checks every
-- distinct URL the app can render as a link - property url_auction / list_url /
-- document_url / purchase_url and the otc_provenance links, the registry's
-- source pages, the acquisition evidence pages - once each, and writes one row
-- per URL here. The app reads the rows that are BROKEN on 2+ separate daily
-- checks and renders those links as "Link broken at source (checked <date>)"
-- with no href. BLOCKED (401 / 403 / 429 / a bot challenge) is never treated
-- as broken: the link may work in a person's browser.
--
-- WHAT THIS DOES NOT DO
--
--   - Nothing here closes, hides or changes a property row.
--   - Nothing is deleted: a URL no longer referenced keeps its last result.
--
-- ACCESS: RLS on. Approved accounts read (the URLs are the same ones their
-- property pages already carry); only service_role writes. Grants are revoked
-- from anon / authenticated first - Supabase's default privileges would grant
-- them ALL otherwise.

begin;

create table if not exists public.source_link_checks (
  url                   text        primary key,
  host                  text        not null default '',
  status                text        not null
                        constraint source_link_checks_status_check
                        check (status in ('OK', 'BROKEN', 'BLOCKED', 'ERROR')),
  http_code             integer,
  detail                text,
  checked_at            timestamptz not null default now(),
  first_failed_at       timestamptz,
  consecutive_failures  integer     not null default 0
                        constraint source_link_checks_failures_check check (consecutive_failures >= 0),
  final_url             text,
  referenced_by         text[]      not null default '{}',
  updated_at            timestamptz not null default now(),
  constraint source_link_checks_broken_streak_check
    check (status = 'BROKEN' or consecutive_failures = 0)
);

comment on table public.source_link_checks is
  'One row per source URL the app can render as a link, written daily by scripts/check_source_links.py. A link is hidden as broken only when status = BROKEN and consecutive_failures >= 2 (separate daily checks). BLOCKED is never treated as broken.';

create index if not exists source_link_checks_broken_idx
  on public.source_link_checks (url) where status = 'BROKEN' and consecutive_failures >= 2;

alter table public.source_link_checks enable row level security;

drop policy if exists "source_link_checks: approved read" on public.source_link_checks;
create policy "source_link_checks: approved read" on public.source_link_checks
  as permissive for select to authenticated
  using ((select public.is_approved()));

revoke all on public.source_link_checks from public, anon, authenticated;
grant select on public.source_link_checks to authenticated;
grant select, insert, update, delete on public.source_link_checks to service_role;

drop trigger if exists source_link_checks_touch on public.source_link_checks;
create trigger source_link_checks_touch before update on public.source_link_checks
  for each row execute function public.touch_updated_at();

commit;
