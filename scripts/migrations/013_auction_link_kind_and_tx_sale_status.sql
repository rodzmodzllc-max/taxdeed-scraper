-- Phase 72: say what an auction link IS, and stop losing the Texas sale link.
--
-- Two findings from the 2026-09-24 read-only Texas auction-link audit:
--
--   1. Every one of the 531 Texas rows had every url_* column empty, although
--      harvesters/texas_harvester.py's harvest_realauction() builds and
--      successfully fetches the county sale-event preview page for every sale
--      date it harvests - the very same URL template
--      scripts/harvest_all_counties.ps1 stores for Florida as url_auction.
--      The Texas harvester threw it away.
--   2. url_auction has never said what it points at. For Florida RealAuction
--      deed rows it is the SALE-EVENT page for that county and date (not a
--      per-property page); for LAFT rows it is the county's Lands Available
--      list; for certificates it is LienHub's county-held list. The UI labelled
--      all of them "Bid on County Auction Site", which overstates the first and
--      misdescribes the other two.
--
-- WHAT THIS ADDS
--
--   url_auction_kind  text  one of 'property' | 'sale' | 'county' | 'info'
--       property - opens the specific property/listing/notice
--       sale     - opens the sale/auction EVENT page (a county's sale-date
--                  listing where this property appears among others)
--       county   - a verified county or provider page where the property can
--                  be found or the buyer registers (a Lands Available list, a
--                  county-held liens list, a county auction site's landing)
--       info     - an official county tax-sale information page (how the sale
--                  is conducted), not a listing
--     The DATABASE value is authoritative. The frontend must never derive the
--     kind from harvester_source, county or URL shape - it reads this column
--     and shows the matching label, or "Auction link not published" when
--     url_auction is null. A url_auction_kind with no url_auction is ignored
--     by the UI; the column is never a link on its own.
--
--   tx_sale_status    text  the Texas vendor's own raw sale status, verbatim.
--     For LGBS that is one of "Scheduled for Auction", "Scheduled for Online
--     Auction", "Available for Future Sale", "Struck off to Jurisdiction".
--     Before this migration the harvester collapsed those four into the
--     auction/laft ledger and the distinction was lost - a struck-off resale
--     row and a not-yet-scheduled future-sale row were indistinguishable, and
--     an online sale was indistinguishable from an in-person one.
--
-- BACKFILL RULES (deterministic, from the writers' own behaviour, not guessed)
--
--   Existing url_auction values, by what the writer that produced them stored:
--     - RealAuction/RealForeclose/RealTaxDeed sale-date preview pages
--       (index.cfm?zaction=AUCTION&zmethod=PREVIEW&AuctionDate=..., any letter
--       case - Palm Beach's rows carry "Zmethod"/"AUCTIONDATE") -> 'sale'.
--       Written by scripts/harvest_all_counties.ps1 line ~233 via
--       sync-harvest-to-supabase.ps1.
--     - Collier's per-application notice page
--       (notices.collierclerk.com/notice/notice-of-application-for-tax-deed-N)
--       -> 'property': it opens that one tax-deed application's notice.
--     - Everything else that exists today -> 'county': LienHub county-held
--       certificate lists (harvest_lienhub_certificates.ps1 sets url_auction to
--       the county list URL), every LAFT harvester's county list page or PDF
--       (harvest_laft_*.py set url_auction to the source page), DeSoto's clerk
--       tax-deed sales page, and the Municode-hosted county sale-list PDFs.
--     Rows with url_auction null keep url_auction_kind null.
--
--   Texas RealAuction rows (harvester_source = 'tx_realauction'): url_auction
--   is set to the sale-event preview page for the row's county host and
--   sale_date, kind 'sale'. The host comes from data/tx_realauction_counties.csv
--   (the harvester's own roster, inlined below - 24 counties). A tx_realauction
--   row can only exist because harvest_realauction() fetched that county's
--   preview page from that host, so this reconstructs what the harvester saw;
--   it does not invent a destination. AuctionDate is MM/DD/YYYY, the format
--   the harvester requests and Florida stores. Rows whose county is not on the
--   roster, or with no sale_date, are left null - never a guess.
--
--   Texas LGBS rows (harvester_source = 'tx_lgbs'): NOT touched. No verified
--   per-property or per-sale LGBS URL exists anywhere in this repository, and a
--   provider homepage is not an auction link. url_auction stays null and the
--   UI says "Auction link not published".
--
--   tx_sale_status is NOT backfilled. The rows in production were written from
--   out/harvest_texas.json, which never carried the raw status (TexasSaleRow
--   had no such field), and the only artifacts that do carry it are small
--   validation samples from 2026-09-16 that predate the rows' own harvests.
--   Null is the honest value until the next Texas harvest run writes it.
--
-- Same shape as 012: grants first (005a granted `authenticated` column-level
-- SELECT on an explicit list, so a projected-but-ungranted column takes the
-- whole API down with `permission denied for column`), then the exact live
-- signature is dropped and recreated (a return-type change cannot use CREATE
-- OR REPLACE), then execute is re-granted to the same roles.

begin;

-- ---------------------------------------------------------------------------
-- 1. Columns.
-- ---------------------------------------------------------------------------
alter table public.properties
  add column if not exists url_auction_kind text,
  add column if not exists tx_sale_status text;

alter table public.properties
  drop constraint if exists properties_url_auction_kind_check;
alter table public.properties
  add constraint properties_url_auction_kind_check
  check (url_auction_kind is null or url_auction_kind in ('property', 'sale', 'county', 'info'));

comment on column public.properties.url_auction_kind is
  'What url_auction opens: property (the specific listing/notice), sale (the sale-event page for that county+date), county (a verified county/provider page where the property can be found or the buyer registers), info (an official county tax-sale information page). Authoritative for UI labelling; never inferred client-side.';
comment on column public.properties.tx_sale_status is
  'Texas vendor''s raw sale status, verbatim (LGBS: Scheduled for Auction / Scheduled for Online Auction / Available for Future Sale / Struck off to Jurisdiction). Null when the source did not publish one or the row predates Phase 72.';

-- ---------------------------------------------------------------------------
-- 2. Grants first (additive; nothing already granted is revoked).
-- ---------------------------------------------------------------------------
grant select (url_auction_kind, tx_sale_status) on public.properties to authenticated;

-- ---------------------------------------------------------------------------
-- 3. Drop the exact live signature, then recreate with the two columns
--    appended. Every pre-existing column keeps its position and type; the
--    WHERE clause, ordering, limit and offset are byte-for-byte unchanged.
-- ---------------------------------------------------------------------------
drop function if exists public.get_properties(text, text, text, integer, integer);

create function public.get_properties(
  p_state text,
  p_ledger_type text default null,
  p_status text default null,
  p_limit integer default 20000,
  p_offset integer default 0
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
  photo_url text, photo_source text, photo_captured_year integer,
  flood_zone text, flood_zone_subtype text, flood_sfha boolean,
  flood_bfe numeric, flood_firm_id text, flood_checked_at timestamptz,
  taxable_value numeric, improvement_value numeric, acreage numeric,
  land_use text, effective_year_built integer, num_res_units integer,
  last_sale_month smallint, last_sale_qual_code text, last_sale_vi_code text,
  last_sale_or_book text, last_sale_or_page text, last_sale_clerk_no text,
  prior_sale_price numeric, prior_sale_year integer,
  prior_sale_month smallint, prior_sale_qual_code text,
  -- Phase 72: what the auction link opens + the Texas vendor's raw status
  url_auction_kind text, tx_sale_status text
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
    photo_url, photo_source, photo_captured_year,
    flood_zone, flood_zone_subtype, flood_sfha, flood_bfe, flood_firm_id,
    flood_checked_at,
    taxable_value, improvement_value, acreage, land_use,
    effective_year_built, num_res_units,
    last_sale_month, last_sale_qual_code, last_sale_vi_code,
    last_sale_or_book, last_sale_or_page, last_sale_clerk_no,
    prior_sale_price, prior_sale_year, prior_sale_month, prior_sale_qual_code,
    url_auction_kind, tx_sale_status
  from public.properties
  where state = p_state
    and (p_ledger_type is null or ledger_type = p_ledger_type)
    and (p_status is null or status = p_status)
  order by county, case_no
  limit p_limit
  offset p_offset;
$function$;

grant execute on function public.get_properties(text, text, text, integer, integer)
  to anon, authenticated, service_role;

-- ---------------------------------------------------------------------------
-- 4. Backfill url_auction_kind for every existing url_auction, by what the
--    writer that produced it actually stored (see the header). Only rows that
--    have a URL and no kind yet; url_auction itself is never modified here.
-- ---------------------------------------------------------------------------
update public.properties
set url_auction_kind = case
  when url_auction ~* 'zaction=auction&zmethod=preview&auctiondate=' then 'sale'
  when url_auction ~* '^https?://(www\.)?notices\.collierclerk\.com/notice/' then 'property'
  else 'county'
end
where nullif(url_auction, '') is not null
  and url_auction_kind is null;

-- ---------------------------------------------------------------------------
-- 5. Texas RealAuction rows: the sale-event page the harvester fetched.
--    Roster = data/tx_realauction_counties.csv, verbatim.
-- ---------------------------------------------------------------------------
with tx_hosts(county, host) as (
  values
    ('Angelina',     'angelina.texas.sheriffsaleauctions.com'),
    ('Aransas',      'aransas.texas.sheriffsaleauctions.com'),
    ('Atascosa',     'atascosa.texas.sheriffsaleauctions.com'),
    ('Caldwell',     'caldwell.texas.sheriffsaleauctions.com'),
    ('Cameron',      'cameron.texas.sheriffsaleauctions.com'),
    ('Dallas',       'dallas.texas.sheriffsaleauctions.com'),
    ('El Paso',      'elpaso.texas.sheriffsaleauctions.com'),
    ('Ellis',        'ellis.texas.sheriffsaleauctions.com'),
    ('Galveston',    'galveston.texas.sheriffsaleauctions.com'),
    ('Gregg',        'gregg.texas.sheriffsaleauctions.com'),
    ('Hopkins',      'hopkins.texas.sheriffsaleauctions.com'),
    ('Jackson',      'jackson.texas.sheriffsaleauctions.com'),
    ('Kaufman',      'kaufman.texas.sheriffsaleauctions.com'),
    ('Llano',        'llano.texas.sheriffsaleauctions.com'),
    ('Matagorda',    'matagorda.texas.sheriffsaleauctions.com'),
    ('Montgomery',   'montgomery.texas.realforeclose.com'),
    ('Nueces',       'nueces.texas.sheriffsaleauctions.com'),
    ('Orange',       'orange.texas.sheriffsaleauctions.com'),
    ('San Patricio', 'sanpatricio.texas.sheriffsaleauctions.com'),
    ('Smith',        'smith.texas.sheriffsaleauctions.com'),
    ('Travis',       'travis.texas.realforeclose.com'),
    ('Tyler',        'tyler.texas.sheriffsaleauctions.com'),
    ('Victoria',     'victoria.texas.sheriffsaleauctions.com'),
    ('Wilson',       'wilson.texas.sheriffsaleauctions.com')
)
update public.properties p
set url_auction = 'https://' || h.host
                  || '/index.cfm?zaction=AUCTION&zmethod=PREVIEW&AuctionDate='
                  || to_char(p.sale_date, 'MM/DD/YYYY'),
    url_auction_kind = 'sale'
from tx_hosts h
where p.state = 'TX'
  and p.harvester_source = 'tx_realauction'
  and p.county = h.county
  and p.sale_date is not null
  and nullif(p.url_auction, '') is null;

commit;
