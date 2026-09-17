-- Adds `properties.photo_url` (a real Google Street View Static image,
-- cached in the `property-photos` Storage bucket by
-- scripts/fetch_property_photos.py) and creates that bucket.
--
-- Purely additive - one nullable column plus one new public-read Storage
-- bucket, nothing existing is touched. Run once in the Supabase SQL editor:
--   Dashboard -> SQL Editor -> New query -> paste this file -> Run.
--
-- NULL means "not yet checked"; '' (empty string) means "checked, no
-- Street View coverage at this address" (common for vacant land / rural
-- parcels); a real value is a public Supabase Storage URL. Never
-- fabricate a value for this column - see the frontend rendering, which
-- must fall back to a plain placeholder (not a fake photo) when it's
-- empty or null.
--
-- Requires GOOGLE_MAPS_API_KEY (a Street View Static API key, billing
-- account attached) as a GitHub Actions secret before
-- scripts/fetch_property_photos.py will actually populate anything -
-- until then it's a no-op, same shipped-ahead-of-the-credential pattern
-- as texas_harvester.py's still-stubbed vendors. See CLAUDE.md's
-- "Property photos" section for the exact setup steps.

alter table public.properties
  add column if not exists photo_url text;

comment on column public.properties.photo_url is
  'Public Supabase Storage URL of a real Google Street View Static image for this address, fetched server-side by scripts/fetch_property_photos.py. NULL = not yet checked, '''' = checked and no coverage there. Never fabricate a value for this column.';

-- Public read (no RLS policy needed on storage.objects for this bucket -
-- same trust level as the Street View image itself, which Google already
-- serves with no auth). Only the service_role key (used server-side by
-- fetch_property_photos.py) can write to it.
insert into storage.buckets (id, name, public)
values ('property-photos', 'property-photos', true)
on conflict (id) do nothing;
