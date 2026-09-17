-- Widens the customer-facing projection with the fields 007 added, so the new
-- screens can read them. Separate from 007 on purpose: 007 is schema, this is
-- the API BOUNDARY, and the boundary is the file that deserves its own review.
--
-- What is preserved exactly, because it is the security model:
--   * LANGUAGE sql STABLE, and NOT security definer - the function runs as
--     the caller, so Row Level Security still applies to every row it reads.
--     (See 005_customer_safe_properties_projection.sql and
--     005a_close_direct_properties_grant.sql.)
--   * The deferred/unbuilt fields `outcome` and `sold_price` stay OUT. Several
--     tests assert their absence from this projection by name.
--   * Argument list, filters, ordering, limit/offset are unchanged, so an
--     existing caller sees identical rows with extra columns.
--
-- Risk fields are exposed IN PAIRS - every `<risk>_count` travels with its
-- `<risk>_checked_at`. Shipping the count alone would let the detail screen
-- render "Liens: None found" for a property nobody has ever checked, which is
-- the one outcome 007's header says must not happen. The pair is what lets the
-- UI distinguish "not checked" from "checked, clear".

begin;

create or replace function public.get_properties(
  p_state       text,
  p_ledger_type text    default null,
  p_status      text    default null,
  p_limit       integer default 20000,
  p_offset      integer default 0
)
returns table (
  id uuid, state text, county text, source text, harvester_source text,
  address text, parcel text, case_no text, owner_name text, status text,
  prop_type text, dor_use_code text, tx_category text, lien_level text,
  lien_note text, homestead boolean, bid numeric, assessed numeric,
  market numeric, value_year integer, min_bid numeric,
  redemption_period_months integer, redemption_expiration_date date,
  max_statutory_return_usd numeric, year_built integer, living_area integer,
  lot_sqft integer, num_buildings integer, land_value numeric,
  legal_desc text, last_sale_price numeric, last_sale_year integer,
  sale_date date, certificate_no text, tax_year text, issued_date date,
  expiration_date date, interest_rate numeric, latitude double precision,
  longitude double precision, url_appraiser text, url_auction text,
  url_taxcoll text, url_title text, url_streetview text, url_zillow text,
  gone_since timestamptz, updated_at timestamptz,
  -- Phase 50 design fields ---------------------------------------------------
  taxable_value numeric, improvement_value numeric, annual_tax numeric,
  delinquent_tax numeric, acreage numeric, beds smallint, baths numeric,
  land_use text, zoning text, municipality text, subdivision text,
  liens_count integer, liens_checked_at timestamptz,
  judgments_count integer, judgments_checked_at timestamptz,
  code_violations_count integer, code_violations_checked_at timestamptz,
  foreclosure_status text, foreclosure_checked_at timestamptz,
  flood_zone text, flood_checked_at timestamptz,
  field_provenance jsonb
)
language sql
stable
as $function$
  select
    id, state, county, source, harvester_source, address, parcel, case_no,
    owner_name, status, prop_type, dor_use_code, tx_category, lien_level,
    lien_note, homestead, bid, assessed, market, value_year, min_bid,
    redemption_period_months, redemption_expiration_date,
    max_statutory_return_usd, year_built, living_area, lot_sqft,
    num_buildings, land_value, legal_desc, last_sale_price,
    last_sale_year, sale_date, certificate_no, tax_year, issued_date,
    expiration_date, interest_rate, latitude, longitude, url_appraiser,
    url_auction, url_taxcoll, url_title, url_streetview, url_zillow,
    gone_since, updated_at,
    taxable_value, improvement_value, annual_tax, delinquent_tax, acreage,
    beds, baths, land_use, zoning, municipality, subdivision,
    liens_count, liens_checked_at,
    judgments_count, judgments_checked_at,
    code_violations_count, code_violations_checked_at,
    foreclosure_status, foreclosure_checked_at,
    flood_zone, flood_checked_at,
    field_provenance
  from public.properties
  where state = p_state
    and (p_ledger_type is null or ledger_type = p_ledger_type)
    and (p_status is null or status = p_status)
  order by county, case_no
  limit p_limit
  offset p_offset;
$function$;

-- Timeline for one property. Its own function rather than a join into
-- get_properties: the detail screen asks for it once, for one property, and
-- folding a one-to-many into the list projection would multiply every list row.
create or replace function public.get_property_events(p_property_id uuid)
returns table (
  event_date date, event_type text, description text, amount numeric,
  source text, source_record_id text, retrieved_at timestamptz
)
language sql
stable
as $function$
  select e.event_date, e.event_type, e.description, e.amount,
         e.source, e.source_record_id, e.retrieved_at
  from public.property_events e
  -- The join is the access control: a caller only sees events for a property
  -- RLS already lets them read. No separate policy to keep in step.
  join public.properties p on p.id = e.property_id
  where e.property_id = p_property_id
  order by e.event_date desc, e.event_type;
$function$;

commit;
