-- Current-state coverage matrix (read-only, counts only; never a row value).
-- One row per state x ledger (properties.source). Run in the Supabase SQL
-- editor (or any read-only connection), save the result as JSON under
-- data/current_state/, then render it with
--   python scripts/current_state_report.py --snapshot <file> --out docs/current-state-coverage.md
-- "active" = status active / available / scheduled and not delisted.
select now() as measured_at, state, source,
 count(*) total,
 count(*) filter (where status in ('active','available','scheduled') and delisted_at is null) active,
 count(*) filter (where status in ('active','available','scheduled') and delisted_at is null and nullif(trim(parcel),'') is not null) act_parcel,
 count(*) filter (where status in ('active','available','scheduled') and delisted_at is null and latitude is not null) act_coords,
 count(*) filter (where status in ('active','available','scheduled') and delisted_at is null and assessed is not null) act_assessed,
 count(*) filter (where status in ('active','available','scheduled') and delisted_at is null and nullif(trim(land_use),'') is not null) act_landuse,
 count(*) filter (where status in ('active','available','scheduled') and delisted_at is null and flood_zone is not null) act_flood,
 count(*) filter (where status in ('active','available','scheduled') and delisted_at is null and nullif(url_auction,'') is not null) act_url,
 count(*) filter (where status in ('active','available','scheduled') and delisted_at is null and last_seen_at is null) act_never_seen,
 count(*) filter (where status in ('active','available','scheduled') and delisted_at is null and last_seen_at < now() - interval '36 hours') act_seen_gt36h,
 count(*) filter (where status in ('active','available','scheduled') and delisted_at is null and source='auction' and sale_date < (now() at time zone 'America/New_York')::date) act_past_sale,
 count(*) filter (where status in ('active','available','scheduled') and delisted_at is null and field_provenance is not null and field_provenance <> '{}'::jsonb) act_prov,
 max(last_seen_at) last_seen_max
from public.properties group by state, source order by state, source;
