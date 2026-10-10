-- 031_publication_state_gate.sql
-- Mandatory acquisition-path gate for customer publication (2026-10-10).
-- Written and NOT applied to production by the PR that adds it.
--
-- One auditable publication state per properties row, decided by
-- scripts/publication_state_writer.py from harvesters/governance/
-- publication_state.py (source approval, verified state/county rules, record
-- validation, a credible acquisition path, freshness - in that order), and
-- ENFORCED SERVER-SIDE: the properties access policy lets a customer read
-- only CUSTOMER_PUBLISHED rows, so every customer surface (get_properties,
-- get_properties_list, counts, maps, exports, search, property pages, any
-- direct REST read) sees the same inventory. Admins (profiles.is_admin) read
-- every row; the service role (the writers) bypasses RLS as before.
--
-- States (properties.publication_state and .publication_progress):
--   DISCOVERED  RULES_VERIFIED  PATH_VERIFIED  CUSTOMER_PUBLISHED
--   ADMIN_ONLY_NO_PATH  ADMIN_ONLY_SOURCE_REVIEW  ADMIN_ONLY_STALE  CLOSED
-- They never replace the lifecycle status (status / inventory_status).
--
-- FAIL-SAFE: a row with no decision yet (NULL) is NOT customer-visible.
-- APPLY ORDER (one maintenance window, owner-run):
--   1. apply this migration;
--   2. run scripts/publication_state_writer.py for every production state
--      (workflow dispatch job=publication) so every active row carries a
--      decision - until then customers see no inventory, by design.
-- The scheduled harvest jobs re-run the writer after every sync.
--
-- Adds:
--   properties.publication_state / publication_progress (CHECK the 8 states),
--     publication_reasons jsonb, publication_remediation text,
--     publication_path jsonb (the structured acquisition-path evidence),
--     publication_state_at timestamptz; an index on (state, ledger_type,
--     publication_state).
--   public.publication_decisions - append-only log of every decision change
--     (prior state, new state, progress, reasons, remediation, path evidence,
--     run id). Admins read it; nobody but the service role writes it.
--   public.count_publication_states(p_state, p_ledger_type) - SECURITY
--     DEFINER, counts only, for approved accounts: how many active rows sit
--     in each publication state, so a customer's zero can say "N records
--     withheld pending verification" without seeing them.
--   public.get_withheld_states(p_state) - SECURITY INVOKER: id + state +
--     reasons + remediation + path evidence for rows that are NOT
--     customer-published. RLS makes it empty for customers; admins use it to
--     label collected rows.
--   ALTER POLICY "properties: approved only": USING adds the publication
--     rule; WITH CHECK is unchanged. The policy stays PERMISSIVE / ALL /
--     PUBLIC (it is the table's only permissive policy - never dropped).
--
-- Rollback:
--   alter policy "properties: approved only" on public.properties using ((select public.is_approved()));
--   drop function if exists public.get_withheld_states(text);
--   drop function if exists public.count_publication_states(text, text);
--   drop table if exists public.publication_decisions;
--   drop index if exists properties_publication_state_idx;
--   alter table public.properties drop column if exists publication_state, drop column if exists publication_progress,
--     drop column if exists publication_reasons, drop column if exists publication_remediation,
--     drop column if exists publication_path, drop column if exists publication_state_at;

-- 1. columns
alter table public.properties
  add column if not exists publication_state text,
  add column if not exists publication_progress text,
  add column if not exists publication_reasons jsonb not null default '[]'::jsonb,
  add column if not exists publication_remediation text,
  add column if not exists publication_path jsonb,
  add column if not exists publication_state_at timestamptz;

alter table public.properties drop constraint if exists properties_publication_state_check;
alter table public.properties add constraint properties_publication_state_check
  check (publication_state is null or publication_state in (
    'DISCOVERED', 'RULES_VERIFIED', 'PATH_VERIFIED', 'CUSTOMER_PUBLISHED',
    'ADMIN_ONLY_NO_PATH', 'ADMIN_ONLY_SOURCE_REVIEW', 'ADMIN_ONLY_STALE', 'CLOSED'));
alter table public.properties drop constraint if exists properties_publication_progress_check;
alter table public.properties add constraint properties_publication_progress_check
  check (publication_progress is null or publication_progress in (
    'DISCOVERED', 'RULES_VERIFIED', 'PATH_VERIFIED', 'CUSTOMER_PUBLISHED',
    'ADMIN_ONLY_NO_PATH', 'ADMIN_ONLY_SOURCE_REVIEW', 'ADMIN_ONLY_STALE', 'CLOSED'));

comment on column public.properties.publication_state is
  'Customer-publication gate (publication_state.py): CUSTOMER_PUBLISHED or why not. NULL = not decided = not customer-visible. Never the lifecycle status.';
comment on column public.properties.publication_path is
  'Structured acquisition-path evidence behind the decision: ledger, authority, source URL / type, destination URL or procedure, path type, scope, verification status, last verified, missing reason.';

create index if not exists properties_publication_state_idx
  on public.properties (state, ledger_type, publication_state);

-- 2. the decision log
create table if not exists public.publication_decisions (
  id bigserial primary key,
  property_id uuid not null,
  state text,
  county text,
  ledger_type text,
  source_id text,
  prior_state text,
  publication_state text not null,
  publication_progress text,
  reasons jsonb not null default '[]'::jsonb,
  remediation text,
  path_evidence jsonb,
  decided_at timestamptz not null default now(),
  decided_by text not null default 'publication_state_writer',
  run_id text
);
create index if not exists publication_decisions_property_idx on public.publication_decisions (property_id, decided_at desc);
create index if not exists publication_decisions_decided_idx on public.publication_decisions (decided_at desc);
alter table public.publication_decisions enable row level security;
revoke all on table public.publication_decisions from anon, authenticated;
grant select on table public.publication_decisions to authenticated;
-- the writers run as the service role (Supabase grants it by default privilege;
-- stated here so a plain PostgreSQL has the same rule)
grant select, insert on table public.publication_decisions to service_role;
grant usage, select on sequence public.publication_decisions_id_seq to service_role;
drop policy if exists "publication_decisions: admin read" on public.publication_decisions;
create policy "publication_decisions: admin read" on public.publication_decisions
  as permissive for select to authenticated using ((select public.is_admin()));
comment on table public.publication_decisions is
  'Append-only log of customer-publication decisions (one row per change). Written by the service role only; admins read.';

-- 3. counts only, for every approved account
create or replace function public.count_publication_states(p_state text, p_ledger_type text default null)
returns table(ledger_type text, publication_state text, n bigint)
language sql stable security definer set search_path = public as $$
  select p.ledger_type, coalesce(p.publication_state, 'DISCOVERED') as publication_state, count(*)::bigint
  from public.properties p
  where (select public.is_approved())
    and p.state = p_state
    and p.status = 'active'
    and (p_ledger_type is null or p.ledger_type = p_ledger_type)
  group by 1, 2
  order by 1, 2;
$$;
revoke all on function public.count_publication_states(text, text) from public, anon;
grant execute on function public.count_publication_states(text, text) to authenticated;

-- 4. the withheld rows with their reasons (RLS applies: admins only, in practice)
create or replace function public.get_withheld_states(p_state text)
returns table(id uuid, ledger_type text, publication_state text, publication_progress text, publication_reasons jsonb,
              publication_remediation text, publication_path jsonb, publication_state_at timestamptz)
language sql stable security invoker set search_path = public as $$
  select p.id, p.ledger_type, coalesce(p.publication_state, 'DISCOVERED'), p.publication_progress, p.publication_reasons,
         p.publication_remediation, p.publication_path, p.publication_state_at
  from public.properties p
  where p.state = p_state
    and p.status = 'active'
    and (p.publication_state is null or p.publication_state <> 'CUSTOMER_PUBLISHED');
$$;
revoke all on function public.get_withheld_states(text) from public, anon;
grant execute on function public.get_withheld_states(text) to authenticated;

-- 5. the access rule: approved AND (customer-published OR admin). WITH CHECK unchanged.
alter policy "properties: approved only" on public.properties
  using ((select public.is_approved()) and (publication_state = 'CUSTOMER_PUBLISHED' or (select public.is_admin())));
