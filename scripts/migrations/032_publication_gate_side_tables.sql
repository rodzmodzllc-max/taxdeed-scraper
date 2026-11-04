-- 032_publication_gate_side_tables.sql
-- The customer-publication gate for the per-property side tables (2026-10-13).
-- Written and NOT applied to production by the PR that adds it.
--
-- Why: 031 limits public.properties to CUSTOMER_PUBLISHED rows for customers
-- (admins read every row). Four tables carry one row per property and are
-- read by the property page (sale event history, inventory history, what
-- changed). Their read policies check only is_approved(), so after 031 an
-- approved customer could still read the events, observations and changes
-- of a WITHHELD property by querying them directly: county, case, status
-- wording, dates, outcomes. Search, map, detail, count and export would then
-- disagree with these tables about which records a customer may see.
--
-- The rule here is the same for every side table, and it is not restated:
-- a side row is readable only when its property row is readable BY THE SAME
-- CALLER - `exists (select 1 from public.properties p where p.id = ...)`.
-- The subquery runs under the caller's own RLS, so it inherits exactly the
-- properties policies in force (031's publication rule, 027's paid-beta
-- RESTRICTIVE policy when applied, admin access) with no second copy that
-- could drift. Admins keep every row; the service role (the writers)
-- bypasses RLS as before.
--
--   auction_events                    (014)  -> its property
--   auction_event_observations        (014)  -> its event (whose policy -> its property)
--   inventory_status_observations     (021)  -> its property
--   property_change_events            (024)  -> its property
--   user_alerts                       (024)  -> RESTRICTIVE SELECT: an alert about a
--                                              property the caller cannot read is not shown
--
-- Policies are ALTERed, never dropped: each stays PERMISSIVE / SELECT /
-- authenticated, and remains its table's only permissive read policy. The
-- helper call becomes an InitPlan ((select public.is_approved())).
--
-- Ledgers stay separate: the decision is the property row's own
-- publication_state, which publication_state.py sets per row and per ledger.
-- Withholding reasons are untouched (properties.publication_reasons and
-- public.publication_decisions, admin-readable; counts through
-- count_publication_states()).
--
-- PREREQUISITE: 031 (refused otherwise). A table that does not exist yet
-- (024 is not applied) is skipped. ORDER: 024's own file DROPs and
-- re-CREATEs its policies, so apply (or re-apply) 032 AFTER 024, and after
-- any re-run of 014 / 021 / 024. 032 is idempotent.
--
-- Rollback (restores the pre-032 read rules exactly):
--   alter policy "auction_events: approved read" on public.auction_events using (public.is_approved());
--   alter policy "auction_event_observations: approved read" on public.auction_event_observations using (public.is_approved());
--   alter policy "inventory_status_observations: approved read" on public.inventory_status_observations using (public.is_approved());
--   alter policy "property_change_events: approved read" on public.property_change_events using (public.is_approved());
--   drop policy if exists "user_alerts: property readable" on public.user_alerts;
-- Rolling back reopens the side tables of withheld properties to every
-- approved account; it changes no data.

do $$
begin
  if not exists (select 1 from information_schema.columns
                 where table_schema = 'public' and table_name = 'properties' and column_name = 'publication_state') then
    raise exception '032 requires 031 (properties.publication_state) - apply 031 first';
  end if;
end $$;

do $$
declare
  r record;
begin
  for r in
    select * from (values
      ('auction_events', 'auction_events: approved read',
       'exists (select 1 from public.properties p where p.id = auction_events.property_id)'),
      ('auction_event_observations', 'auction_event_observations: approved read',
       'exists (select 1 from public.auction_events e where e.id = auction_event_observations.event_id)'),
      ('inventory_status_observations', 'inventory_status_observations: approved read',
       'exists (select 1 from public.properties p where p.id = inventory_status_observations.property_id)'),
      ('property_change_events', 'property_change_events: approved read',
       'exists (select 1 from public.properties p where p.id = property_change_events.property_id)')
    ) v(tbl, pol, cond)
  loop
    if to_regclass('public.' || r.tbl) is null then
      raise notice '032: %.% does not exist yet - skipped (re-run 032 after it is created)', 'public', r.tbl;
      continue;
    end if;
    if not exists (select 1 from pg_policies where schemaname = 'public' and tablename = r.tbl and policyname = r.pol) then
      raise exception '032: policy "%" on public.% not found - refusing to guess', r.pol, r.tbl;
    end if;
    execute format('alter policy %I on public.%I using ((select public.is_approved()) and %s)', r.pol, r.tbl, r.cond);
  end loop;

  if to_regclass('public.user_alerts') is null then
    raise notice '032: public.user_alerts does not exist yet - skipped (re-run 032 after 024)';
  else
    execute 'drop policy if exists "user_alerts: property readable" on public.user_alerts';
    execute 'create policy "user_alerts: property readable" on public.user_alerts as restrictive for select to authenticated '
            'using (property_id is null or exists (select 1 from public.properties p where p.id = user_alerts.property_id))';
  end if;
end $$;
