-- 028_property_list_payload.sql
-- Customer-facing performance fix (2026-10-05). NOT applied to production by
-- this PR - applying it needs separate authorization.
--
-- Measured read-only in production (2026-10-05, to_jsonb byte counts):
-- Louisiana's Available ledger (10,334 rows) is ~113 MB of JSON through
-- get_properties(), ~76 MB of it otc_provenance + field_provenance - mostly
-- per-field evidence (field_provenance: list / layer URLs, timestamps,
-- licences per field) and the county's purchase instructions repeated in
-- 6,834 rows. Michigan's Available ledger is ~152 MB (~64 MB provenance).
-- With this projection: Louisiana ~64 MB (27 MB provenance), Michigan ~97 MB
-- (8 MB provenance); see docs/property-list-performance.md.
--
-- This migration ADDS two functions and changes nothing else:
--
--   get_properties_list(...)   the list payload. Same signature, same
--     RETURNS TABLE columns in the same order as get_properties() (migration
--     025), the same narrow-key sort, ordering, LIMIT / OFFSET paging,
--     STABLE, search_path, SECURITY INVOKER (the properties RLS policy
--     applies, exactly as for get_properties()) - with two columns slimmed
--     and one appended:
--       otc_provenance    every key EXCEPT the ones no list surface reads:
--                         purchase_instructions (the county's process text,
--                         ~1.5 KB, repeated in every row of a county - the
--                         list fills it from acquisition-evidence.json, built
--                         from the same evidence tables by the same engine,
--                         only for the identical record) and the ArcGIS
--                         harvest internals query_where, attributes,
--                         layer_url, columns, id_field, object_id_field.
--                         The acquisition record, source_match, amounts,
--                         statements and every other key are kept as stored;
--       field_provenance  only the entries that mark a source under review
--                         (governance set, or a source id in app.js's
--                         REVIEW_REQUIRED_SOURCES - a test pins both lists
--                         equal), reduced to source / source_id / governance;
--       provenance_scope  'list' - tells the frontend the row carries the
--                         list projection, so opening it loads the full one.
--
--   get_property_provenance(p_id)   the full otc_provenance and
--     field_provenance of one property, for the property page. SECURITY
--     INVOKER, STABLE, same search_path: a caller reads only a row the
--     properties RLS policy already lets them read.
--
-- get_properties() is NOT changed: the harvest / sync scripts and any client
-- that has not moved keep the full payload. Nothing is dropped from the
-- database; no grant is narrowed. EXECUTE is granted to the same roles that
-- hold it on get_properties() in production (read 2026-10-05).

create or replace function public.get_properties_list(
  p_state text,
  p_ledger_type text default null,
  p_status text default null,
  p_limit integer default 20000,
  p_offset integer default 0)
returns table(
  id uuid,
  state text,
  county text,
  source text,
  harvester_source text,
  address text,
  parcel text,
  case_no text,
  owner_name text,
  status text,
  prop_type text,
  dor_use_code text,
  tx_category text,
  lien_level text,
  lien_note text,
  homestead boolean,
  bid numeric,
  assessed numeric,
  market numeric,
  value_year integer,
  min_bid numeric,
  redemption_period_months integer,
  redemption_expiration_date date,
  max_statutory_return_usd numeric,
  year_built integer,
  living_area integer,
  lot_sqft integer,
  num_buildings integer,
  land_value numeric,
  legal_desc text,
  last_sale_price numeric,
  last_sale_year integer,
  sale_date date,
  certificate_no text,
  tax_year text,
  issued_date date,
  expiration_date date,
  interest_rate numeric,
  latitude double precision,
  longitude double precision,
  url_appraiser text,
  url_auction text,
  url_taxcoll text,
  url_title text,
  url_streetview text,
  url_zillow text,
  gone_since timestamp with time zone,
  updated_at timestamp with time zone,
  photo_url text,
  photo_source text,
  photo_captured_year integer,
  flood_zone text,
  flood_zone_subtype text,
  flood_sfha boolean,
  flood_bfe numeric,
  flood_firm_id text,
  flood_checked_at timestamp with time zone,
  taxable_value numeric,
  improvement_value numeric,
  acreage numeric,
  land_use text,
  effective_year_built integer,
  num_res_units integer,
  last_sale_month smallint,
  last_sale_qual_code text,
  last_sale_vi_code text,
  last_sale_or_book text,
  last_sale_or_page text,
  last_sale_clerk_no text,
  prior_sale_price numeric,
  prior_sale_year integer,
  prior_sale_month smallint,
  prior_sale_qual_code text,
  url_auction_kind text,
  tx_sale_status text,
  inventory_type text,
  source_authority text,
  source_id text,
  list_url text,
  document_url text,
  purchase_url text,
  purchase_url_kind text,
  purchase_amount numeric,
  purchase_amount_kind text,
  first_seen_at timestamp with time zone,
  last_seen_at timestamp with time zone,
  delisted_at timestamp with time zone,
  source_published_at timestamp with time zone,
  list_as_of date,
  escheatment_date date,
  available_date date,
  inventory_status text,
  inventory_status_raw text,
  inventory_status_basis text,
  inventory_status_observed_at timestamp with time zone,
  field_provenance jsonb,
  otc_provenance jsonb,
  publication_status text,
  purchase_path_type text,
  purchase_path_scope text,
  purchase_path_evidence text,
  purchase_path_observed_on date,
  result_amount numeric,
  result_date date,
  result_party text,
  provenance_scope text)
language sql
stable
set search_path to 'public'
as $function$
  with page as (
    select k.id as pid, k.county as k_county, k.case_no as k_case
    from public.properties k
    where k.state = p_state
      and (p_ledger_type is null or k.ledger_type = p_ledger_type)
      and (p_status is null or k.status = p_status)
    order by county, case_no, id
    limit p_limit
    offset p_offset
  )
  select
    p.id,
    p.state,
    p.county,
    p.source,
    p.harvester_source,
    p.address,
    p.parcel,
    p.case_no,
    p.owner_name,
    p.status,
    p.prop_type,
    p.dor_use_code,
    p.tx_category,
    p.lien_level,
    p.lien_note,
    p.homestead,
    p.bid,
    p.assessed,
    p.market,
    p.value_year,
    p.min_bid,
    p.redemption_period_months,
    p.redemption_expiration_date,
    p.max_statutory_return_usd,
    p.year_built,
    p.living_area,
    p.lot_sqft,
    p.num_buildings,
    p.land_value,
    p.legal_desc,
    p.last_sale_price,
    p.last_sale_year,
    p.sale_date,
    p.certificate_no,
    p.tax_year,
    p.issued_date,
    p.expiration_date,
    p.interest_rate,
    p.latitude,
    p.longitude,
    p.url_appraiser,
    p.url_auction,
    p.url_taxcoll,
    p.url_title,
    p.url_streetview,
    p.url_zillow,
    p.gone_since,
    p.updated_at,
    p.photo_url,
    p.photo_source,
    p.photo_captured_year,
    p.flood_zone,
    p.flood_zone_subtype,
    p.flood_sfha,
    p.flood_bfe,
    p.flood_firm_id,
    p.flood_checked_at,
    p.taxable_value,
    p.improvement_value,
    p.acreage,
    p.land_use,
    p.effective_year_built,
    p.num_res_units,
    p.last_sale_month,
    p.last_sale_qual_code,
    p.last_sale_vi_code,
    p.last_sale_or_book,
    p.last_sale_or_page,
    p.last_sale_clerk_no,
    p.prior_sale_price,
    p.prior_sale_year,
    p.prior_sale_month,
    p.prior_sale_qual_code,
    p.url_auction_kind,
    p.tx_sale_status,
    p.inventory_type,
    p.source_authority,
    p.source_id,
    p.list_url,
    p.document_url,
    p.purchase_url,
    p.purchase_url_kind,
    p.purchase_amount,
    p.purchase_amount_kind,
    p.first_seen_at,
    p.last_seen_at,
    p.delisted_at,
    p.source_published_at,
    p.list_as_of,
    p.escheatment_date,
    p.available_date,
    p.inventory_status,
    p.inventory_status_raw,
    p.inventory_status_basis,
    p.inventory_status_observed_at,
    case when jsonb_typeof(p.field_provenance) = 'object' then (
      select jsonb_object_agg(e.key, jsonb_strip_nulls(jsonb_build_object(
               'source', e.value -> 'source', 'source_id', e.value -> 'source_id', 'governance', e.value -> 'governance')))
      from jsonb_each(p.field_provenance) e
      where jsonb_typeof(e.value) = 'object'
        and (e.value ? 'governance' or e.value ->> 'source_id' in ('tx_lgbs', 'tx_realauction')))
    else null end as field_provenance,
    case when jsonb_typeof(p.otc_provenance) = 'object'
         then p.otc_provenance - array['purchase_instructions', 'query_where', 'attributes', 'layer_url', 'columns',
                                       'id_field', 'object_id_field']
         else p.otc_provenance end as otc_provenance,
    p.publication_status,
    p.purchase_path_type,
    p.purchase_path_scope,
    p.purchase_path_evidence,
    p.purchase_path_observed_on,
    p.result_amount,
    p.result_date,
    p.result_party,
    'list'::text as provenance_scope
  from page
  join public.properties p on p.id = page.pid
  order by page.k_county, page.k_case, page.pid;
$function$;

create or replace function public.get_property_provenance(p_id uuid)
returns table(id uuid, otc_provenance jsonb, field_provenance jsonb)
language sql
stable
set search_path to 'public'
as $function$
  select p.id, p.otc_provenance, p.field_provenance
  from public.properties p
  where p.id = p_id;
$function$;

grant execute on function public.get_properties_list(text, text, text, integer, integer) to anon, authenticated, service_role;
grant execute on function public.get_property_provenance(uuid) to anon, authenticated, service_role;
