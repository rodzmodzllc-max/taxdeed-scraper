-- parcel_boundaries_superseded_broward_2025.sql
-- NOT RUN. For the owner to run in production, by hand, with explicit approval.
--
-- What it corrects (found read-only on 2026-10-21): the first Broward outline
-- run (workflow parcel-boundaries-broward run #2, 2026-10-21 10:40-10:49 UTC,
-- on main at e5ec234) matched Broward PIN polygons to records by the listing's
-- own parcel number. It wrote 64 boundaries - every active Broward record -
-- under the dataset name 'DOR PTO PIN 2025F Broward'. The rules the reviewed
-- reader now enforces would attach none of these 54:
--   * 34 condominium units (DOR use code 04): a unit has no parcel polygon of
--     its own (Parcel Shapefiles Readme);
--   * 1 right-of-way (use code 94);
--   * records without a validated NAL PARCEL_ID (the Readme's join key).
-- Only that run used the dataset name 'DOR PTO PIN 2025F Broward'; the
-- reviewed loader writes 'DOR PTO PIN parcel shapefile broward_2025pin'.
--
-- Order: apply migration 035 first; run this file; then the Broward workflow
-- (dry run, then apply) re-attaches the outlines the reviewed rules accept
-- (10 on the 2026-10-21 check).

-- 1. Preview (counts only).
select count(*) as rows_to_remove,
       count(*) filter (where p.dor_use_code = '04') as condo_units,
       count(*) filter (where p.dor_use_code = '94') as right_of_way
  from public.parcel_boundaries b
  left join public.properties p on p.id = b.property_id
 where b.source_id = 'fl_dor_pto_parcel_gis'
   and b.source_dataset = 'DOR PTO PIN 2025F Broward';

-- 2. Remove them, in one transaction. Expected: 64 on 2026-10-21; if the
--    count differs, roll back and re-check before going on.
begin;
delete from public.parcel_boundaries
 where source_id = 'fl_dor_pto_parcel_gis'
   and source_dataset = 'DOR PTO PIN 2025F Broward';
-- commit;   -- only after the deleted count matches the preview
