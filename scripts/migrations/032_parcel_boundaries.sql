-- 032_parcel_boundaries.sql
-- Verified parcel polygons, kept apart from `properties` so that a boundary
-- write never bumps properties.updated_at (touch_updated_at) and so that the
-- polygon never travels in the list payload (get_properties_list).
--
-- NOT APPLIED. Written for review. Apply only with explicit owner approval.
-- Reversible: see the DOWN block at the end (commented).

create table if not exists public.parcel_boundaries (
  property_id       bigint primary key references public.properties(id) on delete cascade,
  state             text not null,
  county            text not null,
  parcel            text not null,
  geom              geometry(MultiPolygon, 4326) not null,
  source_id         text not null,
  boundary_policy   text not null check (boundary_policy in ('APPROVED')),
  match_method      text not null check (match_method in ('EXACT_PARCEL_ID')),
  source_observed_at timestamptz not null,
  checked_at        timestamptz not null default now(),
  content_sha256    text not null check (content_sha256 ~ '^[0-9a-f]{64}$'),
  attribution       text,
  constraint parcel_boundaries_geom_valid check (ST_IsValid(geom)),
  constraint parcel_boundaries_geom_srid check (ST_SRID(geom) = 4326)
);

create index if not exists parcel_boundaries_geom_gix on public.parcel_boundaries using gist (geom);

alter table public.parcel_boundaries enable row level security;

-- Customers and admins read only boundaries of an approved account. Writes are
-- service_role only (the harvester), so there is no client write policy.
drop policy if exists parcel_boundaries_approved_read on public.parcel_boundaries;
create policy parcel_boundaries_approved_read on public.parcel_boundaries
  as permissive for select to authenticated
  using ((select public.is_approved()));

revoke all on public.parcel_boundaries from anon, authenticated;
grant select on public.parcel_boundaries to authenticated;

-- DOWN (manual, reversible):
--   drop table if exists public.parcel_boundaries;

-- Read contract for the front end (docs/parcel-boundary-api.md). Invoker
-- rights: the caller's RLS on parcel_boundaries AND properties applies, so a
-- customer only ever receives a boundary for a property they may see. Zero
-- rows is the only answer for "no boundary", including every row whose
-- source is not APPROVED for display or whose attribution is missing.
create or replace function public.get_property_boundary(p_property_id bigint)
returns table (
  property_id bigint,
  boundary jsonb,
  display_permitted boolean,
  attribution text,
  source_id text,
  match_method text,
  source_observed_at timestamptz
)
language sql
stable
security invoker
set search_path = public
as $$
  select b.property_id,
         ST_AsGeoJSON(ST_Multi(b.geom), 9)::jsonb,
         true,
         b.attribution,
         b.source_id,
         b.match_method,
         b.source_observed_at
  from public.parcel_boundaries b
  where b.property_id = p_property_id
    and b.boundary_policy = 'APPROVED'
    and coalesce(b.attribution, '') <> ''
    and ST_SRID(b.geom) = 4326
    and exists (select 1 from public.properties p where p.id = b.property_id);
$$;

revoke all on function public.get_property_boundary(bigint) from public, anon;
grant execute on function public.get_property_boundary(bigint) to authenticated;
