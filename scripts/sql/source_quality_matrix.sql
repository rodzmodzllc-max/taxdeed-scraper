-- Source-quality matrix (read-only, counts only; never a row value).
-- One row per state x county x source x ledger, active rows only
-- ("active" = status active / available / scheduled and not delisted).
-- Every measure is a count with `active` as its denominator. Save the result
-- as JSON under data/current_state/ and render it with
--   python scripts/source_quality_report.py --snapshot <file> --out docs/source-quality-matrix.md
with a as (
  select *, coalesce(nullif(harvester_source,''), nullif(source_id,''), '(unattributed)') as src
  from public.properties
  where status in ('active','available','scheduled') and delisted_at is null
), dup as (
  select state, county, src, source, count(*) - count(distinct nullif(trim(parcel),'')) - count(*) filter (where nullif(trim(parcel),'') is null) as dup_parcel
  from a group by 1,2,3,4
)
select a.state, a.county, a.src as source_id, a.source as ledger,
 count(*) active,
 count(*) filter (where nullif(trim(parcel),'') is not null) parcel,
 count(*) filter (where nullif(trim(parcel),'') is not null and parcel !~ '[0-9]') parcel_no_digit,
 count(*) filter (where latitude is not null and longitude is not null) coords,
 count(*) filter (where flood_checked_at is not null) flood_checked,
 count(*) filter (where purchase_amount is not null or coalesce(min_bid,0) > 0 or (source in ('auction','certificate') and coalesce(bid,0) > 0)) amount,
 count(*) filter (where purchase_amount is null and coalesce(bid,0) > 0 and source='laft') laft_bid_without_amount,
 count(*) filter (where purchase_amount is not null and bid is not null and bid > 0 and round(bid::numeric, 2) <> round(purchase_amount::numeric, 2)) bid_amount_mismatch,
 count(*) filter (where nullif(list_url,'') is not null or nullif(url_auction,'') is not null) source_link,
 count(*) filter (where coalesce(nullif(list_url,''), nullif(url_auction,''), 'https://') !~ '^https://') link_not_https,
 count(*) filter (where list_as_of is not null) list_as_of,
 count(*) filter (where list_as_of is not null and list_as_of > (now() at time zone 'UTC')::date) list_as_of_future,
 count(*) filter (where nullif(purchase_path_type,'') is not null) path_typed,
 count(*) filter (where field_provenance is not null and field_provenance <> '{}'::jsonb) provenance,
 count(*) filter (where last_seen_at is null) never_seen,
 count(*) filter (where last_seen_at < now() - interval '36 hours') seen_gt36h,
 count(*) filter (where source='auction' and sale_date < (now() at time zone 'America/New_York')::date) past_sale,
 count(*) filter (where first_seen_at is not null and last_seen_at is not null and first_seen_at > last_seen_at) seen_order_bad,
 max(d.dup_parcel) dup_parcel,
 string_agg(distinct coalesce(publication_status,'NULL'), '|') publication,
 max(last_seen_at) last_seen_max
from a join dup d using (state, county, src, source)
group by a.state, a.county, a.src, a.source
order by 1,3,2,4;
