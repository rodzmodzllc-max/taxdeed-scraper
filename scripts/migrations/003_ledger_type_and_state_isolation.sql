-- Adds a canonical, cross-state ledger classifier (`ledger_type`) and a
-- state-required RPC (`get_properties`) so Florida and Texas can be queried
-- with real server-side isolation - each state's page asks Postgres for
-- exactly its own rows, instead of the frontend fetching the whole table
-- and filtering client-side (which is what public/app.js's loadAll() does
-- today: `sb.from("properties").select("*")` with no state scoping at all).
--
-- MUST RUN AFTER 002_add_texas_support.sql - the composite index below
-- references the `state` column that migration adds. Also fine to run in
-- the same batch as schema-v9-dor-use-code.sql (unrelated, but was queued
-- alongside this one).
--
-- Purely additive: no existing column, index, or constraint is touched.
-- `source` keeps its exact current values and CHECK constraint
-- ('auction'/'laft'/'certificate') - every existing FL harvester script
-- (PowerShell + Python) keeps writing it exactly as before, unchanged.

-- 1. The canonical ledger classifier every state maps into, independent of
--    how each state's own vendors/statutes describe it. Values match the
--    frontend's existing 3-ledger model 1:1: 'auctions' (FL's live-bid
--    Auctions / TX's Event Terminal Sheriff-Constable sales), 'buy' (FL's
--    Lands Available / TX's OTC Catalog Struck-Off Inventory), 'lien' (FL's
--    Tax Certificates / TX's Yield Desk Redeemable Tax Deeds - see the
--    open semantic-mismatch note in public/app.js's LEDGERS comment and
--    claude/fl-tx-region-switcher.md for why that last mapping is a
--    surface-level fit, not a clean one).
alter table public.properties add column if not exists ledger_type text;

comment on column public.properties.ledger_type is
  'Canonical cross-state ledger classifier: auctions | buy | lien. Kept in sync with `source` by the sync_ledger_type_from_source trigger below - never written directly by harvester/sync scripts, so no existing FL script needs to change.';

-- 2. Per-vendor/source provenance tag, distinct from the ledger classifier
--    above. `source` already conflates "which ledger" and "which vendor"
--    for Florida (there was only ever one vendor shape per ledger), but
--    Texas has multiple vendors feeding the SAME ledger (e.g. both LGBS
--    and PBFCM feed 'auctions'/Event Terminal rows) - harvester_source is
--    where that distinction lives (e.g. 'tx_pbfcm', 'tx_lgbs',
--    'tx_govease' - see harvesters/texas_harvester.py). NULL for existing
--    Florida rows; Florida scripts are not required to start setting it.
alter table public.properties add column if not exists harvester_source text;

comment on column public.properties.harvester_source is
  'Per-vendor provenance tag distinct from ledger_type/source, e.g. tx_pbfcm / tx_lgbs / tx_govease for Texas rows fed by different vendors into the same ledger. NULL for Florida rows and any row not yet tagged.';

-- 3. Backfill every existing row from its current `source` value.
update public.properties
set ledger_type = case source
  when 'auction' then 'auctions'
  when 'laft' then 'buy'
  when 'certificate' then 'lien'
  else null
end
where ledger_type is null;

-- 4. Keep ledger_type in sync with source automatically, on every future
--    insert/update, for every writer (existing FL scripts included) - so
--    this is the ONLY place the source->ledger_type mapping needs to be
--    maintained, not fifteen sync scripts. A Texas harvester row should
--    set `source` to whichever of 'auction'/'laft'/'certificate' its
--    ledger corresponds to (the same three FL already uses - see point 1
--    above) and this trigger derives ledger_type from that automatically,
--    the same as it does for Florida.
create or replace function public.sync_ledger_type_from_source()
returns trigger
language plpgsql
as $$
begin
  new.ledger_type := case new.source
    when 'auction' then 'auctions'
    when 'laft' then 'buy'
    when 'certificate' then 'lien'
    else new.ledger_type  -- unrecognized source: leave whatever was explicitly set, don't clobber it
  end;
  return new;
end;
$$;

drop trigger if exists trg_sync_ledger_type_from_source on public.properties;
create trigger trg_sync_ledger_type_from_source
  before insert or update of source on public.properties
  for each row execute function public.sync_ledger_type_from_source();

-- 5. Constrain to the three known values once backfilled - `not valid`
--    initially so this migration can't fail on a source value the mapping
--    above didn't cover; validate separately once you've confirmed there
--    are no NULLs left (`select count(*) from properties where
--    ledger_type is null` should be 0 after step 3, since every live
--    source value maps to one of the three today).
alter table public.properties drop constraint if exists properties_ledger_type_check;
alter table public.properties add constraint properties_ledger_type_check
  check (ledger_type in ('auctions', 'buy', 'lien')) not valid;

-- 6. state+ledger_type+sale_date is the natural scoping+sort key for a
--    single state's single-ledger page (which is exactly what each of
--    public/index.html (FL) and public/tx.html (TX) now queries via
--    get_properties() below) - mirrors idx_properties_state_county from
--    002_add_texas_support.sql, one level more specific.
create index if not exists idx_properties_state_ledger_saledate
  on public.properties(state, ledger_type, sale_date);

-- 7. The state-required RPC. `p_state` has NO default - PostgREST/Supabase
--    will reject a call that omits it, so this is a hard requirement at
--    the API layer, not just a convention the frontend has to remember to
--    follow. `security invoker` (the default, spelled out for clarity)
--    means it runs with the CALLER's privileges - existing RLS policies on
--    properties (is_approved() etc.) apply exactly as they do to a direct
--    `sb.from("properties").select()` call today. This does not replace
--    RLS; it adds a second, harder-to-bypass layer of state scoping on top
--    of it, since a client can no longer construct a query that omits the
--    state filter even by accident.
create or replace function public.get_properties(
  p_state text,
  p_ledger_type text default null,
  p_status text default null,
  p_limit int default 20000,
  p_offset int default 0
)
returns setof public.properties
language sql
stable
security invoker
as $$
  select *
  from public.properties
  where state = p_state
    and (p_ledger_type is null or ledger_type = p_ledger_type)
    and (p_status is null or status = p_status)
  order by county, case_no
  limit p_limit
  offset p_offset;
$$;

grant execute on function public.get_properties(text, text, text, int, int) to authenticated;

-- Nothing here changes what an already-approved, signed-in Florida user
-- sees today - source/ledger_type/state all continue defaulting the same
-- way (state='FL' from 002, ledger_type derived from source by the new
-- trigger). The only behavior change is additive: get_properties() now
-- exists for the frontend to call instead of an unscoped select("*").
