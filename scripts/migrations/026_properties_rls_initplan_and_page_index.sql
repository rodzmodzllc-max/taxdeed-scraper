-- 026_properties_rls_initplan_and_page_index.sql
-- Large-state page performance (2026-10-04). APPLIED 2026-10-04 as version 20261004180726.
--
-- Production evidence (read-only):
--   - one deep get_properties('MI','buy',...,1000,29000) page took 4,556 ms;
--   - a Louisiana page (offset 9000) took 1,921 ms;
--   - the app fetches several pages at once, so pages crossed the
--     authenticated role's 8 s statement timeout (HTTP 500 at 11:43, 12:36
--     and 13:01 UTC); one failed page left the whole state blank.
--
-- Cause 1 - the access rule ran once PER ROW. The only policy on properties,
-- "properties: approved only" (PERMISSIVE, ALL, PUBLIC), is
-- `using (is_approved()) with check (is_approved())`. is_approved() is
-- VOLATILE + SECURITY DEFINER + SET search_path, so Postgres can neither
-- inline nor cache it: every row the scan touches runs a profiles lookup and
-- re-parses the request's JWT claims in auth.uid() - ~31,000 times for one
-- Michigan page (the page's key scan) and again for the 1,000-row join.
--
-- Fix 1 - wrap the same call in a scalar sub-select. An uncorrelated
-- sub-select becomes an InitPlan: evaluated ONCE per statement, its boolean
-- result applied to every row. The decision is identical, because
-- is_approved() reads nothing from the row - only auth.uid() (fixed for the
-- statement) and that user's profiles row. ALTER POLICY changes only the
-- expressions: the policy is never dropped (so there is no instant with no
-- PERMISSIVE policy - see CLAUDE.md, 2026-08-24 outage), and its name,
-- PERMISSIVE type, command (ALL) and role (PUBLIC) are unchanged.
-- Supabase's own RLS performance guidance recommends exactly this form.
--
-- Cause 2 - no index matched the page query. get_properties() (migration
-- 025) pages with
--   where state = $1 and ledger_type = $2 [and status = $3]
--   order by county, case_no, id  limit/offset
-- and no index covered (state, ledger_type) in that order, so every page
-- read and sorted the whole state's keys.
--
-- Fix 2 - one btree index in exactly that order. The page becomes an ordered
-- index scan that stops after offset + limit entries; no sort. Building it
-- takes a short SHARE lock on properties (writes wait, reads continue) -
-- ~47,000 rows, about a second.
--
-- Nothing else changes: get_properties() (body, signature, columns, order,
-- grants, SECURITY INVOKER), the publication gate, grants, other tables'
-- policies and every row are untouched. Idempotent.

alter policy "properties: approved only" on public.properties
  using ((select public.is_approved()))
  with check ((select public.is_approved()));

create index if not exists properties_state_ledger_county_case_id_idx
  on public.properties (state, ledger_type, county, case_no, id);
