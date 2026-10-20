-- 034_parcel_boundaries.sql
-- Parcel boundaries from the two approved parcel-geometry sources
-- (data/source_approvals.csv): Florida DOR county parcel files
-- (fl_dor_pto_parcel_gis) and UGRC Salt Lake LIR (ut_ugrc_lir_saltlake).
--
-- NOT APPLIED. Written for review; apply only with explicit owner approval.
-- 033 is held by the billing refund / dispute PR, so this is 034.
--
-- * parcel_boundary_sources: one row per approved source - the display grant
--   the read path enforces, the attribution every surface must show (credit,
--   licence, change notice, disclaimer, metadata), the source's EXPECTED
--   cadence and TAXACQ's ACTUAL last successful refresh (separate columns).
-- * parcel_boundaries: at most one boundary per property (primary key), and a
--   source feature attached to at most one property (unique source feature),
--   kept apart from `properties` so a boundary write never bumps
--   properties.updated_at and the polygon never rides in the list payload.
-- * get_property_boundary(): the customer read. Invoker rights, so the
--   caller's RLS on properties (approval + publication gate) applies.
-- * upsert_parcel_boundaries() / record_parcel_boundary_refresh(): the
--   writer's only paths (service_role). Neither deletes anything: a failed
--   or partial read changes nothing, and a parcel missing from a read keeps
--   its stored boundary.
--
-- Reversible: see the DOWN block at the end (commented).

create extension if not exists postgis;

create table if not exists public.parcel_boundary_sources (
  source_id                  text primary key,
  state                      text not null,
  provider                   text not null,
  dataset                    text not null,
  display_approved           boolean not null default false,
  credit                     text not null check (btrim(credit) <> ''),
  license_name               text not null default '',
  license_url                text not null default '' check (license_url = '' or license_url ~ '^https://'),
  change_notice              text not null check (btrim(change_notice) <> ''),
  disclaimer                 text not null default '',
  disclaimer_url             text not null default '' check (disclaimer_url = '' or disclaimer_url ~ '^https://'),
  metadata_url               text not null default '' check (metadata_url = '' or metadata_url ~ '^https://'),
  expected_refresh_cadence   text not null,
  last_successful_refresh_at timestamptz,
  last_attempt_at            timestamptz,
  last_attempt_status        text,
  consecutive_failures       integer not null default 0,
  reviewed_on                date not null
);

-- Seeded from data/source_approvals.csv (a test pins these values equal).
-- ON CONFLICT DO NOTHING: re-applying never overwrites refresh state.
insert into public.parcel_boundary_sources
  (source_id, state, provider, dataset, display_approved, credit, license_name, license_url, change_notice,
   disclaimer, disclaimer_url, metadata_url, expected_refresh_cadence, reviewed_on)
values
  ('fl_dor_pto_parcel_gis', 'FL', 'Florida Department of Revenue, Property Tax Oversight',
   'DOR PTO Data Portal county GIS parcel files', true,
   'Florida Department of Revenue, Property Tax Oversight', '', '',
   'Boundaries reprojected to WGS84 and simplified by TAXACQ for display (Douglas-Peucker, about 0.5 m); matched to records by exact parcel identifier only',
   '', '', '',
   'Annual, published about mid-August to early September', date '2026-10-20'),
  ('ut_ugrc_lir_saltlake', 'UT', 'Utah Geospatial Resource Center (UGRC)', 'Parcels_SaltLake_LIR', true,
   'Utah Geospatial Resource Center (UGRC)', 'CC BY 4.0', 'https://creativecommons.org/licenses/by/4.0/',
   'Attributes normalized by TAXACQ; parcel boundaries reprojected to WGS84 and simplified (Douglas-Peucker, about 0.5 m); latitude/longitude are a centroid derived from the parcel polygon; matched to records by exact parcel ID',
   '', 'https://gis.utah.gov/documentation/policy/license/',
   'https://services1.arcgis.com/99lidPhWCzftIe9K/arcgis/rest/services/Parcels_SaltLake_LIR/FeatureServer/0',
   'Generally monthly', date '2026-10-20')
on conflict (source_id) do nothing;

alter table public.parcel_boundary_sources enable row level security;
drop policy if exists "parcel_boundary_sources: approved read" on public.parcel_boundary_sources;
create policy "parcel_boundary_sources: approved read" on public.parcel_boundary_sources
  as permissive for select to authenticated
  using ((select public.is_approved()) and display_approved);
revoke all on public.parcel_boundary_sources from anon, authenticated;
grant select on public.parcel_boundary_sources to authenticated;

create table if not exists public.parcel_boundaries (
  property_id            uuid primary key references public.properties(id) on delete cascade,
  state                  text not null,
  county                 text not null,
  parcel                 text not null check (btrim(parcel) <> ''),
  source_id              text not null references public.parcel_boundary_sources(source_id),
  source_dataset         text not null check (btrim(source_dataset) <> ''),
  source_feature_id      text not null check (btrim(source_feature_id) <> ''),
  geom                   geometry(MultiPolygon, 4326) not null,
  match_method           text not null check (match_method in ('EXACT_PARCEL_ID')),
  simplify_tolerance_deg double precision not null check (simplify_tolerance_deg >= 0 and simplify_tolerance_deg <= 0.0001),
  source_observed_at     timestamptz not null,
  checked_at             timestamptz not null default now(),
  content_sha256         text not null check (content_sha256 ~ '^[0-9a-f]{64}$'),
  constraint parcel_boundaries_geom_valid check (ST_IsValid(geom)),
  constraint parcel_boundaries_geom_srid check (ST_SRID(geom) = 4326),
  -- One source feature is never attached to two properties.
  constraint parcel_boundaries_one_feature unique (source_id, source_dataset, source_feature_id)
);
create index if not exists parcel_boundaries_geom_gix on public.parcel_boundaries using gist (geom);
create index if not exists parcel_boundaries_source_idx on public.parcel_boundaries (source_id);

alter table public.parcel_boundaries enable row level security;
-- Readable by an approved account, only for a property that account may read
-- (the exists() runs as the caller, so properties RLS - including the
-- publication gate of 031 - applies), and only while the source's display
-- grant holds. No client write policy: writes go through the service_role
-- functions below.
drop policy if exists "parcel_boundaries: approved read" on public.parcel_boundaries;
create policy "parcel_boundaries: approved read" on public.parcel_boundaries
  as permissive for select to authenticated
  using (
    (select public.is_approved())
    and exists (select 1 from public.properties p where p.id = parcel_boundaries.property_id)
    and exists (select 1 from public.parcel_boundary_sources s
                where s.source_id = parcel_boundaries.source_id and s.display_approved)
  );
revoke all on public.parcel_boundaries from anon, authenticated;
grant select on public.parcel_boundaries to authenticated;
-- The writer reads stored hashes and the source rows (it never writes the
-- tables directly: every write goes through the functions below).
grant select on public.parcel_boundaries, public.parcel_boundary_sources to service_role;

-- The customer read (docs/parcel-boundaries.md). Zero rows is the only answer
-- for "no boundary": no row, a property the caller may not read, a source
-- without a display grant, or a source missing credit / change notice.
create or replace function public.get_property_boundary(p_property_id uuid)
returns table (
  property_id uuid,
  boundary jsonb,
  display_permitted boolean,
  attribution text,
  license_name text,
  license_url text,
  change_notice text,
  disclaimer text,
  disclaimer_url text,
  metadata_url text,
  source_id text,
  source_dataset text,
  source_feature_id text,
  match_method text,
  source_observed_at timestamptz
)
language sql
stable
security invoker
set search_path = public
as $$
  select b.property_id,
         ST_AsGeoJSON(ST_Multi(b.geom), 7)::jsonb,
         true,
         s.credit, s.license_name, s.license_url, s.change_notice, s.disclaimer, s.disclaimer_url, s.metadata_url,
         b.source_id, b.source_dataset, b.source_feature_id, b.match_method, b.source_observed_at
  from public.parcel_boundaries b
  join public.parcel_boundary_sources s on s.source_id = b.source_id
  where b.property_id = p_property_id
    and s.display_approved
    and btrim(s.credit) <> ''
    and btrim(s.change_notice) <> ''
    and exists (select 1 from public.properties p where p.id = b.property_id);
$$;
revoke all on function public.get_property_boundary(uuid) from public, anon;
grant execute on function public.get_property_boundary(uuid) to authenticated;

-- Writer path (scripts/parcel_boundary_refresh.py --apply). One call per
-- batch of planned rows for ONE source. Per row: an invalid geometry, a
-- property holding another source's boundary, or a feature already attached
-- to another property is skipped and counted - never forced. An unchanged
-- hash is a no-op. Nothing is deleted.
create or replace function public.upsert_parcel_boundaries(p_source_id text, p_rows jsonb)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  r jsonb;
  g geometry;
  existing record;
  v_inserted boolean;
  n_insert int := 0; n_replace int := 0; n_unchanged int := 0;
  n_invalid int := 0; n_other_source int := 0; n_feature_taken int := 0; n_no_property int := 0;
begin
  if not exists (select 1 from public.parcel_boundary_sources where source_id = p_source_id) then
    raise exception 'unknown parcel boundary source %', p_source_id;
  end if;
  for r in select * from jsonb_array_elements(coalesce(p_rows, '[]'::jsonb)) loop
    if not exists (select 1 from public.properties where id = (r->>'property_id')::uuid) then
      n_no_property := n_no_property + 1; continue;
    end if;
    begin
      g := ST_SetSRID(ST_Multi(ST_GeomFromGeoJSON(r->'geometry')), 4326);
    exception when others then
      n_invalid := n_invalid + 1; continue;
    end;
    if g is null or GeometryType(g) <> 'MULTIPOLYGON' or not ST_IsValid(g) or ST_IsEmpty(g) then
      n_invalid := n_invalid + 1; continue;
    end if;
    select b.source_id, b.content_sha256 into existing
      from public.parcel_boundaries b where b.property_id = (r->>'property_id')::uuid;
    if found and existing.source_id <> p_source_id then
      n_other_source := n_other_source + 1; continue;
    end if;
    if found and existing.content_sha256 = r->>'content_sha256' then
      update public.parcel_boundaries set checked_at = now() where property_id = (r->>'property_id')::uuid;
      n_unchanged := n_unchanged + 1; continue;
    end if;
    begin
      insert into public.parcel_boundaries as b
        (property_id, state, county, parcel, source_id, source_dataset, source_feature_id, geom, match_method,
         simplify_tolerance_deg, source_observed_at, content_sha256)
      values ((r->>'property_id')::uuid, r->>'state', r->>'county', r->>'parcel', p_source_id,
              r->>'source_dataset', r->>'source_feature_id', g, coalesce(r->>'match_method', 'EXACT_PARCEL_ID'),
              (r->>'simplify_tolerance_deg')::double precision, (r->>'source_observed_at')::timestamptz,
              r->>'content_sha256')
      on conflict (property_id) do update
        set state = excluded.state, county = excluded.county, parcel = excluded.parcel,
            source_dataset = excluded.source_dataset, source_feature_id = excluded.source_feature_id,
            geom = excluded.geom, match_method = excluded.match_method,
            simplify_tolerance_deg = excluded.simplify_tolerance_deg,
            source_observed_at = excluded.source_observed_at, checked_at = now(),
            content_sha256 = excluded.content_sha256
        where b.source_id = excluded.source_id
      returning (xmax = 0) into v_inserted;
      if not found then n_other_source := n_other_source + 1;
      elsif v_inserted then n_insert := n_insert + 1;
      else n_replace := n_replace + 1; end if;
    exception when unique_violation then
      n_feature_taken := n_feature_taken + 1;
    end;
  end loop;
  return jsonb_build_object('inserted', n_insert, 'replaced', n_replace, 'unchanged', n_unchanged, 'invalid', n_invalid,
                            'kept_other_source', n_other_source, 'feature_already_attached', n_feature_taken,
                            'no_property', n_no_property, 'deleted', 0);
end;
$$;
revoke all on function public.upsert_parcel_boundaries(text, jsonb) from public, anon, authenticated;
grant execute on function public.upsert_parcel_boundaries(text, jsonb) to service_role;

-- Refresh bookkeeping. Only a COMPLETE read advances the last successful
-- refresh; every other status counts a failure and leaves it alone. The
-- expected cadence is never written here.
create or replace function public.record_parcel_boundary_refresh(p_source_id text, p_status text, p_at timestamptz)
returns void
language plpgsql
security definer
set search_path = public
as $$
begin
  update public.parcel_boundary_sources
     set last_attempt_at = p_at,
         last_attempt_status = upper(coalesce(p_status, 'UNKNOWN')),
         last_successful_refresh_at = case when upper(coalesce(p_status, '')) = 'COMPLETE' then p_at
                                           else last_successful_refresh_at end,
         consecutive_failures = case when upper(coalesce(p_status, '')) = 'COMPLETE' then 0
                                     else consecutive_failures + 1 end
   where source_id = p_source_id;
  if not found then
    raise exception 'unknown parcel boundary source %', p_source_id;
  end if;
end;
$$;
revoke all on function public.record_parcel_boundary_refresh(text, text, timestamptz) from public, anon, authenticated;
grant execute on function public.record_parcel_boundary_refresh(text, text, timestamptz) to service_role;

-- DOWN (manual, reversible):
--   drop function if exists public.record_parcel_boundary_refresh(text, text, timestamptz);
--   drop function if exists public.upsert_parcel_boundaries(text, jsonb);
--   drop function if exists public.get_property_boundary(uuid);
--   drop table if exists public.parcel_boundaries;
--   drop table if exists public.parcel_boundary_sources;
