-- Phase 57: provenance for property imagery.
--
-- `photo_url` already exists (schema-v10-property-photos.sql) with a
-- three-state contract this file does not touch:
--     NULL  = never checked
--     ''    = checked, no imagery available for this parcel
--     value = a public URL to show
--
-- What is missing is WHOSE image it is and WHEN it was taken, and those two
-- gaps matter more here than for most fields.
--
-- The project now has two possible imagery pipelines with very different
-- properties. scripts/fetch_property_photos.py fetches Google Street View
-- (street-level, needs a billing-attached API key, and sits against this
-- repo's own docs/image-rights-policy.md, which says the approach is
-- "linking, not copying"). scripts/enrich_property_photos_naip.py fetches
-- USDA NAIP aerial imagery (public domain, no key, no restriction on storing
-- or re-serving). A single `photo_url` column cannot tell those apart, and
-- they are not interchangeable to a viewer: one is a photograph of a
-- building's facade, the other is an overhead view of a parcel.
--
-- `photo_captured_year` exists because aerial imagery is dated by nature.
-- NAIP flies a state every few years, so an image can easily be two or three
-- years old. A 2023 image of a lot whose house burned down in 2025 is not a
-- lie until the UI presents it as current - which is exactly what it will do
-- if the vintage is not stored.

begin;

alter table public.properties add column if not exists photo_source        text;
alter table public.properties add column if not exists photo_captured_year integer;
alter table public.properties add column if not exists photo_checked_at    timestamptz;

comment on column public.properties.photo_source is
  'Which pipeline produced photo_url: ''usda_naip'' (public-domain aerial '
  'orthoimagery, overhead view of the parcel) or ''google_streetview'' '
  '(street-level facade). NULL alongside a non-empty photo_url means a '
  'pre-provenance row. The UI must not label an aerial image a photograph of '
  'a building.';

comment on column public.properties.photo_captured_year is
  'Vintage of the imagery, where the source reports it. Aerial orthoimagery '
  'is flown every few years, so an image can be materially out of date; '
  'showing it without the year invites a viewer to read it as current.';

comment on column public.properties.photo_checked_at is
  'When an imagery lookup last succeeded. NULL means never checked. A failed '
  'request leaves this NULL so the row is retried rather than being recorded '
  'as having no coverage.';

-- Only the two pipelines that exist. A new value is a deliberate decision,
-- not a typo that silently becomes a third category.
alter table public.properties drop constraint if exists properties_photo_source_known;
alter table public.properties add constraint properties_photo_source_known check (
  photo_source is null or photo_source in ('usda_naip', 'google_streetview')
);

-- A source without an image is meaningless; the pairing is enforced rather
-- than trusted, the same way migration 007 pairs every risk value with its
-- _checked_at.
alter table public.properties drop constraint if exists properties_photo_source_needs_an_image;
alter table public.properties add constraint properties_photo_source_needs_an_image check (
  photo_source is null or (photo_url is not null and photo_url <> '')
);

alter table public.properties drop constraint if exists properties_photo_year_sane;
alter table public.properties add constraint properties_photo_year_sane check (
  photo_captured_year is null
  or (photo_captured_year between 1990 and extract(year from now())::int + 1)
);

create index if not exists properties_photo_unchecked_idx
  on public.properties (state, county)
  where photo_url is null;

commit;
