-- Adds latitude/longitude to properties for precise Street View / Zillow
-- links (see PHASE_4_SUMMARY.md's geocoding design + scripts/geocode_properties.py).
--
-- Purely additive - two nullable columns, nothing existing is touched, no
-- backfill happens here. Run once in the Supabase SQL editor:
--   Dashboard -> SQL Editor -> New query -> paste this file -> Run.
--
-- After this runs, geocode_properties.py (wired into harvest-and-sync.yml's
-- deeds job) will start filling these in a few hundred properties per run
-- for any row where they're still null, using the free US Census Bureau
-- Geocoder (no API key needed). Until you run this file, that script's
-- sync-back step will fail the same way the certificates sync does without
-- schema-v4-certificates.sql - loudly, on purpose, so it isn't missed.

alter table public.properties
  add column if not exists latitude double precision,
  add column if not exists longitude double precision;

comment on column public.properties.latitude is 'Geocoded via US Census Bureau Geocoder (see scripts/geocode_properties.py) - null until that script has processed this row.';
comment on column public.properties.longitude is 'Geocoded via US Census Bureau Geocoder (see scripts/geocode_properties.py) - null until that script has processed this row.';
