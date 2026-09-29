-- Migration 017: OTC / LAFT / struck-off inventory type, source authority,
-- row provenance, currentness and honest purchase-amount semantics.
--
-- STATUS: PROPOSED, NOT APPLIED. Applied by hand by the project owner after
-- review, like every file in this directory. Independent of 015/016 (may be
-- applied before or after either); must be applied AFTER 013 (it re-creates
-- get_properties() from 013's exact signature and column list) and AFTER
-- 006 (the close-out relies on its gone_since trigger). If 015 has already
-- been applied, the search_path pin it put on get_properties() is re-applied
-- here because CREATE FUNCTION replaces it; if 015 comes later, its ALTER
-- FUNCTION simply pins the function this file created.
--
-- WHY (master LAFT / OTC / struck-off audit, 2026-09-29, sections 13 and 17)
--
-- `source = 'laft'` covers three different things: Florida's post-sale
-- fixed-price Lands Available list (F.S. 197.502(7)), Texas property struck
-- off to the taxing units and held in trust, and Texas property merely
-- "Available for Future Sale". Nothing in the schema said which, who the
-- source of record was, what URL the row came from, when it was last seen
-- on its list, or whether an amount of 0 meant "free" or "not published".
--
-- WHAT THIS ADDS (all nullable; nothing existing is renamed, dropped or
-- re-typed; every writer that exists today keeps working unchanged)
--
--   inventory_type          POST_SALE_FIXED_PRICE | STRUCK_OFF_HELD_IN_TRUST | FUTURE_RESALE
--                           These are NOT the same thing: only the first is
--                           purchasable now at a published price.
--   source_authority        GOVERNMENT_DIRECT | GOVERNMENT_PLATFORM | VENDOR_COUNSEL | VENDOR_AUCTION
--   source_id               the stable harvester/registry id that produced the row
--                           (fl_laft_pdfs, fl_laft_realtdm, tx_lgbs, tx_realauction, ...)
--   list_url                the source LIST page this row was read from
--   document_url            the source DOCUMENT (PDF/JSON/HTML file) when it differs
--   purchase_url            where the buyer actually acts (instructions, offer/bid/
--   purchase_url_kind       application form, online purchase). NEVER the list page
--                           itself: a county list page is not a purchase mechanism.
--   purchase_amount         nullable numeric; purchase_amount_kind says what it is
--   purchase_amount_kind    MINIMUM_PURCHASE_AMOUNT | OPENING_BID | ORIGINAL_OPENING_BID |
--                           FIXED_PURCHASE_PRICE | ESTIMATED_PURCHASE_PRICE |
--                           PUBLISHED_AMOUNT_KIND_UNSPECIFIED | NOT_PUBLISHED
--                           NOT_PUBLISHED requires purchase_amount IS NULL; an
--                           amount requires a kind other than NOT_PUBLISHED.
--   first_seen_at           default now() for rows inserted AFTER this migration
--                           (the default is added after the column so existing
--                           rows stay NULL - their true first sighting is unknown)
--   last_seen_at            written only by scripts/laft_lifecycle.py, only for a
--                           row actually read from its source this run
--   delisted_at             when the lifecycle script closed the row out
--   source_published_at     the source's own publication timestamp when it has one
--   list_as_of              the list's own as-of date (filename/title) when it has one
--   source_document_sha256  the retrieved document's hash / ETag / Last-Modified,
--   source_etag             from scripts/harvest_cache.py's validators
--   source_last_modified
--   otc_provenance          jsonb: per-field origin (harvester, URL, retrieved_at,
--                           what column the amount came from, status wording)
--
-- Retrieval time is never written into source_published_at or list_as_of.
--
-- `bid` is NOT changed. It is NOT NULL with no default, and every FL sync
-- still writes 0 when nothing was published (documented sentinel,
-- docs/production-data-contract.md section 9). purchase_amount /
-- purchase_amount_kind are the honest columns; the app's hasPublishedBid()
-- consults purchase_amount_kind first. Retiring the sentinel is a later,
-- separately-reviewed change.
--
-- BACKFILL RULES (deterministic; from what the writers actually did)
--
--   Florida `laft` rows, by county: inventory_type POST_SALE_FIXED_PRICE,
--     source_authority / source_id / list_url / document_url from the county
--     source registry (data/county_source_registry.csv, PRODUCTION_VERIFIED
--     rows, inlined below and pinned by tests/python/test_migration_017_*).
--     A county not in the registry (rows left by a since-removed harvester)
--     gets inventory_type only.
--     purchase_amount: bid > 0 -> bid, kind PUBLISHED_AMOUNT_KIND_UNSPECIFIED
--     (the legacy column never recorded WHICH published figure it was);
--     bid = 0 -> NULL, NOT_PUBLISHED.
--   Texas `laft` rows (harvester_source = 'tx_lgbs'): source_authority
--     VENDOR_COUNSEL, source_id tx_lgbs. inventory_type from the vendor's raw
--     status when the row carries one ('Struck off to Jurisdiction' ->
--     STRUCK_OFF_HELD_IN_TRUST, 'Available for Future Sale' -> FUTURE_RESALE);
--     rows whose tx_sale_status is NULL (all 421 as of 2026-09-29 - they
--     predate the raw-status writer) stay NULL: struck-off cannot be told
--     from future-resale for them and nothing here guesses. No URL is
--     invented (LGBS publishes none per property). purchase_amount is NOT
--     set from min_bid: the Texas column keeps its own documented meaning.
--   Auction / certificate rows: source_authority + source_id only
--     (fl_realauction, fl_lienhub_certificates, tx_realauction, tx_lgbs).
--
-- Same shape as 012/013: grants first, then the exact live signature of
-- get_properties() is dropped and re-created with the new columns appended,
-- then execute re-granted.

begin;

-- ---------------------------------------------------------------------------
-- 1. Columns.
-- ---------------------------------------------------------------------------
alter table public.properties
  add column if not exists inventory_type text,
  add column if not exists source_authority text,
  add column if not exists source_id text,
  add column if not exists list_url text,
  add column if not exists document_url text,
  add column if not exists purchase_url text,
  add column if not exists purchase_url_kind text,
  add column if not exists purchase_amount numeric,
  add column if not exists purchase_amount_kind text,
  add column if not exists first_seen_at timestamptz,
  add column if not exists last_seen_at timestamptz,
  add column if not exists delisted_at timestamptz,
  add column if not exists source_published_at timestamptz,
  add column if not exists list_as_of date,
  add column if not exists source_document_sha256 text,
  add column if not exists source_etag text,
  add column if not exists source_last_modified text,
  add column if not exists otc_provenance jsonb;

-- Default added AFTER the column exists so existing rows are not stamped
-- with the migration time as their "first seen".
alter table public.properties alter column first_seen_at set default now();

alter table public.properties drop constraint if exists properties_inventory_type_check;
alter table public.properties add constraint properties_inventory_type_check
  check (inventory_type is null or inventory_type in ('POST_SALE_FIXED_PRICE', 'STRUCK_OFF_HELD_IN_TRUST', 'FUTURE_RESALE'));

alter table public.properties drop constraint if exists properties_source_authority_check;
alter table public.properties add constraint properties_source_authority_check
  check (source_authority is null or source_authority in ('GOVERNMENT_DIRECT', 'GOVERNMENT_PLATFORM', 'VENDOR_COUNSEL', 'VENDOR_AUCTION'));

alter table public.properties drop constraint if exists properties_purchase_url_kind_check;
alter table public.properties add constraint properties_purchase_url_kind_check
  check (purchase_url_kind is null or purchase_url_kind in ('purchase_instructions', 'offer_form', 'bid_form', 'application_form', 'online_purchase'));

alter table public.properties drop constraint if exists properties_purchase_url_pair_check;
alter table public.properties add constraint properties_purchase_url_pair_check
  check ((purchase_url is null) = (purchase_url_kind is null));

alter table public.properties drop constraint if exists properties_purchase_amount_kind_check;
alter table public.properties add constraint properties_purchase_amount_kind_check
  check (purchase_amount_kind is null or purchase_amount_kind in (
    'MINIMUM_PURCHASE_AMOUNT', 'OPENING_BID', 'ORIGINAL_OPENING_BID', 'FIXED_PURCHASE_PRICE',
    'ESTIMATED_PURCHASE_PRICE', 'PUBLISHED_AMOUNT_KIND_UNSPECIFIED', 'NOT_PUBLISHED'));

alter table public.properties drop constraint if exists properties_purchase_amount_nonneg_check;
alter table public.properties add constraint properties_purchase_amount_nonneg_check
  check (purchase_amount is null or purchase_amount >= 0);

-- "Not published" is NULL + NOT_PUBLISHED, never 0; an amount always says what it is.
alter table public.properties drop constraint if exists properties_purchase_amount_semantics_check;
alter table public.properties add constraint properties_purchase_amount_semantics_check
  check (
    (purchase_amount is null and (purchase_amount_kind is null or purchase_amount_kind = 'NOT_PUBLISHED'))
    or (purchase_amount is not null and purchase_amount_kind is not null and purchase_amount_kind <> 'NOT_PUBLISHED')
  );

alter table public.properties drop constraint if exists properties_seen_order_check;
alter table public.properties add constraint properties_seen_order_check
  check (first_seen_at is null or last_seen_at is null or last_seen_at >= first_seen_at);

comment on column public.properties.inventory_type is
  'POST_SALE_FIXED_PRICE (FL Lands Available: purchasable now at a set price) | STRUCK_OFF_HELD_IN_TRUST (TX: struck off to the taxing units, held in trust) | FUTURE_RESALE (TX: awaiting a future resale). NULL = not classified; never assume.';
comment on column public.properties.source_authority is
  'Who published the row: GOVERNMENT_DIRECT (the county/clerk/CAD on its own site), GOVERNMENT_PLATFORM (a platform contracted by the government entity), VENDOR_COUNSEL (delinquent-tax counsel publishing for its client units), VENDOR_AUCTION (an auction platform).';
comment on column public.properties.source_id is 'Stable harvester/registry id that produced the row (harvesters/governance/registry.py, data/county_source_registry.csv).';
comment on column public.properties.list_url is 'The source LIST page the row was read from.';
comment on column public.properties.document_url is 'The source document (PDF/JSON/HTML file) the row was read from, when it is a separate URL.';
comment on column public.properties.purchase_url is 'Where a buyer acts (instructions / offer form / bid form / application / online purchase). A list page is never a purchase URL.';
comment on column public.properties.purchase_amount is 'Nullable. NULL with purchase_amount_kind NOT_PUBLISHED means the source published no amount - never 0.';
comment on column public.properties.purchase_amount_kind is 'What purchase_amount IS, from the source''s own label: MINIMUM_PURCHASE_AMOUNT | OPENING_BID | ORIGINAL_OPENING_BID | FIXED_PURCHASE_PRICE | ESTIMATED_PURCHASE_PRICE | PUBLISHED_AMOUNT_KIND_UNSPECIFIED | NOT_PUBLISHED.';
comment on column public.properties.first_seen_at is 'First insertion after migration 017 (default now()); NULL for rows that predate it - their first sighting is unknown.';
comment on column public.properties.last_seen_at is 'Last time a harvester actually read this row from its source (scripts/laft_lifecycle.py). Never set by a sync alone.';
comment on column public.properties.delisted_at is 'When the lifecycle script closed the row out because a COMPLETE/EMPTY harvest of its county no longer listed it.';
comment on column public.properties.source_published_at is 'The source''s own publication timestamp when it publishes one. Never the retrieval time.';
comment on column public.properties.list_as_of is 'The list''s own as-of date (from its filename or title) when it has one. Never the retrieval date.';
comment on column public.properties.otc_provenance is 'Per-field origin for OTC rows: harvester, source_id, retrieved_at, list/document URL, what the amount column was, status wording.';

-- ---------------------------------------------------------------------------
-- 2. Grants first (additive).
-- ---------------------------------------------------------------------------
grant select (inventory_type, source_authority, source_id, list_url, document_url, purchase_url,
              purchase_url_kind, purchase_amount, purchase_amount_kind, first_seen_at, last_seen_at,
              delisted_at, source_published_at, list_as_of)
  on public.properties to authenticated;

-- ---------------------------------------------------------------------------
-- 3. get_properties(): drop the exact live (013) signature, re-create with
--    the customer-facing new columns appended. Everything before them is
--    byte-for-byte 013's list; WHERE/ORDER/LIMIT/OFFSET unchanged. The
--    document hash/ETag/Last-Modified and otc_provenance are pipeline
--    evidence, not customer fields - not projected.
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
  url_auction_kind text, tx_sale_status text,
  -- 017: inventory classification, source authority, provenance URLs,
  -- honest amount semantics, currentness
  inventory_type text, source_authority text, source_id text,
  list_url text, document_url text, purchase_url text, purchase_url_kind text,
  purchase_amount numeric, purchase_amount_kind text,
  first_seen_at timestamptz, last_seen_at timestamptz, delisted_at timestamptz,
  source_published_at timestamptz, list_as_of date
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
    url_auction_kind, tx_sale_status,
    inventory_type, source_authority, source_id,
    list_url, document_url, purchase_url, purchase_url_kind,
    purchase_amount, purchase_amount_kind,
    first_seen_at, last_seen_at, delisted_at,
    source_published_at, list_as_of
  from public.properties
  where state = p_state
    and (p_ledger_type is null or ledger_type = p_ledger_type)
    and (p_status is null or status = p_status)
  order by county, case_no
  limit p_limit
  offset p_offset;
$function$;

-- 015 pins search_path on this function; re-pin here so the order of 015
-- and 017 does not matter.
alter function public.get_properties(text, text, text, integer, integer) set search_path = public;

grant execute on function public.get_properties(text, text, text, integer, integer)
  to anon, authenticated, service_role;

-- ---------------------------------------------------------------------------
-- 4. Backfill: Florida Lands Available rows, by county, from the county
--    source registry's PRODUCTION_VERIFIED rows (data/county_source_registry.csv).
--    Pinned by tests: the VALUES below must equal the CSV.
-- ---------------------------------------------------------------------------
with fl_sources(county, source_id, source_authority, list_url, document_url) as (
  values
    ('Alachua', 'fl_laft_realtdm', 'GOVERNMENT_PLATFORM', 'https://alachua.realtdm.com/public/cases/list', ''),
    ('Bay', 'fl_laft_pioneer', 'GOVERNMENT_PLATFORM', 'https://records2.baycoclerk.com/TaxDeed', ''),
    ('Bradford', 'fl_laft_pdfs', 'GOVERNMENT_DIRECT', 'https://bradfordclerk.com/tax-deeds-and-foreclosure-sales/', 'https://bradfordclerk.com/wp-content/uploads/Lands-Available-for-Taxes.pdf'),
    ('Brevard', 'fl_laft_pdfs', 'GOVERNMENT_DIRECT', 'https://www.brevardclerk.us/lands-available', 'https://www.brevardclerk.us/_cache/files/7/b/7b8e6515-1af7-4968-977f-cc32647e2257/A61EE6220F52FD754C0693E0343635FF.lola.pdf'),
    ('Calhoun', 'fl_laft_html', 'GOVERNMENT_DIRECT', 'https://calhounclerk.com/court-services/property-sales/list-of-lands-available/', 'https://calhounclerk.com/court-services/property-sales/list-of-lands-available/'),
    ('Citrus', 'fl_laft_pioneer', 'GOVERNMENT_PLATFORM', 'https://search.citrusclerk.org/TaxSmartWeb', ''),
    ('Clay', 'fl_laft_pioneer', 'GOVERNMENT_PLATFORM', 'https://landmark.clayclerk.com/TaxDeed', ''),
    ('Columbia', 'fl_laft_html', 'GOVERNMENT_DIRECT', 'https://columbiaclerk.com/land-available-for-taxes/', 'https://columbiaclerk.com/land-available-for-taxes/'),
    ('Dixie', 'fl_laft_html', 'GOVERNMENT_DIRECT', 'https://dixieclerk.com/departments-services/court-services/lands-available-for-taxes/', 'https://dixieclerk.com/departments-services/court-services/lands-available-for-taxes/'),
    ('Duval', 'fl_laft_pioneer', 'GOVERNMENT_PLATFORM', 'https://taxdeed.duvalclerk.com', ''),
    ('Escambia', 'fl_laft_html', 'GOVERNMENT_DIRECT', 'https://public.escambiaclerk.com/taxsale/landsavailable.asp', 'https://public.escambiaclerk.com/taxsale/landsavailable.asp'),
    ('Flagler', 'fl_laft_realtdm', 'GOVERNMENT_PLATFORM', 'https://flagler.realtdm.com/public/cases/list', ''),
    ('Franklin', 'fl_laft_html', 'GOVERNMENT_DIRECT', 'https://www.franklinclerk.com/clerk-services/lands-available/', 'https://www.franklinclerk.com/clerk-services/lands-available/'),
    ('Gadsden', 'fl_laft_html', 'GOVERNMENT_DIRECT', 'https://www.gadsdenclerk.com/Tax_deeds/Tax_deed_disclaimer.html', 'https://www.gadsdenclerk.com/Tax_deeds/Tax_deeds_files/sheet002.htm'),
    ('Glades', 'fl_laft_pdfs', 'GOVERNMENT_PLATFORM', 'https://gladesclerk.com/clerk-services/tax-deeds/', 'https://mcclibraryfunctions.azurewebsites.us/api/munidocDownload/31194/55e3c7109add3/pdf'),
    ('Gulf', 'fl_laft_html', 'GOVERNMENT_DIRECT', 'https://www.gulfclerk.com/courts/tax-deeds/', 'https://www.gulfclerk.com/courts/tax-deeds/'),
    ('Hamilton', 'fl_laft_html', 'GOVERNMENT_DIRECT', 'https://hamiltonclerk.com/list-of-lands-available-for-taxes/', 'https://hamiltonclerk.com/list-of-lands-available-for-taxes/'),
    ('Hardee', 'fl_laft_html', 'GOVERNMENT_DIRECT', 'https://www.hardeeclerk.com/departments/tax-deeds/lands-available/', 'https://www.hardeeclerk.com/departments/tax-deeds/lands-available/'),
    ('Hendry', 'fl_laft_pdfs', 'GOVERNMENT_PLATFORM', 'https://library.municode.com/FL/hendry_clerk_of_courts/munidocs/munidocs?nodeId=4b2b2ea877a65', 'https://mcclibraryfunctions.azurewebsites.us/api/munidocDownload/31143/8216f21582c5d/pdf'),
    ('Hernando', 'fl_laft_pioneer', 'GOVERNMENT_PLATFORM', 'https://or.hernandoclerk.com/TaxSmart/', ''),
    ('Highlands', 'fl_laft_realtdm', 'GOVERNMENT_PLATFORM', 'https://highlands.realtdm.com/public/cases/list', ''),
    ('Hillsborough', 'fl_laft_hillsborough', 'GOVERNMENT_PLATFORM', 'https://publicaccess.hillsclerk.com/TD/', ''),
    ('Holmes', 'fl_laft_html', 'GOVERNMENT_DIRECT', 'https://holmesclerk.com/courts/foreclosures-tax-deeds/lands-available-for-taxes/', 'https://holmesclerk.com/courts/foreclosures-tax-deeds/lands-available-for-taxes/'),
    ('Indian River', 'fl_laft_html', 'GOVERNMENT_DIRECT', 'https://indianriverclerk.com/land-available-for-taxes/', 'https://indianriverclerk.com/land-available-for-taxes/'),
    ('Lafayette', 'fl_laft_html', 'GOVERNMENT_DIRECT', 'https://www.lafayetteclerk.com/tax-deeds/', 'https://www.lafayetteclerk.com/tax-deeds/'),
    ('Lee', 'fl_laft_realtdm', 'GOVERNMENT_PLATFORM', 'https://lee.realtdm.com/public/cases/list', ''),
    ('Leon', 'fl_laft_leon', 'GOVERNMENT_DIRECT', 'https://lforms.leonclerk.com/tax_deeds/lands-available.html', 'https://lforms.leonclerk.com/tax_deeds/listoflands.txt'),
    ('Levy', 'fl_laft_pioneer', 'GOVERNMENT_PLATFORM', 'https://online.levyclerk.com/TaxSmartWeb', ''),
    ('Madison', 'fl_laft_html', 'GOVERNMENT_DIRECT', 'https://www.madisonclerk.com/list-of-lands-available-for-taxes/', 'https://www.madisonclerk.com/list-of-lands-available-for-taxes/'),
    ('Manatee', 'fl_laft_html', 'GOVERNMENT_DIRECT', 'https://www.manateeclerk.com/departments/tax-deeds/lands-available-for-taxes/', 'https://www.manateeclerk.com/departments/tax-deeds/lands-available-for-taxes/'),
    ('Marion', 'fl_laft_pdfs', 'GOVERNMENT_DIRECT', 'https://www.marioncountyclerk.org/departments/records-recording/tax-deeds-and-lands-available-for-taxes/land-available-for-taxes-information/', 'https://www.marioncountyclerk.org/uploads/2026/07/LAT-List-updated3.13.2026-1.pdf'),
    ('Martin', 'fl_laft_pioneer', 'GOVERNMENT_PLATFORM', 'https://or.martinclerk.com/taxsmartweb', ''),
    ('Miami-Dade', 'fl_laft_realtdm', 'GOVERNMENT_PLATFORM', 'https://miamidade.realtdm.com/public/cases/list', ''),
    ('Okeechobee', 'fl_laft_pioneer', 'GOVERNMENT_PLATFORM', 'https://pioneer.okeechobeelandmark.com/TaxSmartWebLive/', ''),
    ('Orange', 'fl_laft_orange', 'GOVERNMENT_DIRECT', 'https://occompt.com/158/Land-Available-For-Taxes', ''),
    ('Osceola', 'fl_laft_osceola', 'GOVERNMENT_PLATFORM', 'https://officialrecords.osceolaclerk.org/browserviewtd/', ''),
    ('Palm Beach', 'fl_laft_pioneer', 'GOVERNMENT_PLATFORM', 'https://taxdeed.mypalmbeachclerk.com/', ''),
    ('Pasco', 'fl_laft_pdfs', 'GOVERNMENT_DIRECT', 'https://www.pascoclerk.com/202/Purchasing-Property-off-the-Lists-of-Lan', 'https://app.pascoclerk.com/public_records/tax-deeds/List%20of%20Lands%20Available%20for%20Taxes%2020260706.pdf'),
    ('Pinellas', 'fl_laft_realtdm', 'GOVERNMENT_PLATFORM', 'https://pinellas.realtdm.com/public/cases/list', ''),
    ('Polk', 'fl_laft_realtdm', 'GOVERNMENT_PLATFORM', 'https://polk.realtdm.com/public/cases/list', ''),
    ('Putnam', 'fl_laft_html', 'GOVERNMENT_DIRECT', 'https://apps.putnam-fl.com/coc/taxdeeds/public/public_LAFT.php', 'https://apps.putnam-fl.com/coc/taxdeeds/public/public_LAFT.php'),
    ('Santa Rosa', 'fl_laft_realtdm', 'GOVERNMENT_PLATFORM', 'https://santarosa.realtdm.com/public/cases/list', ''),
    ('Sarasota', 'fl_laft_realtdm', 'GOVERNMENT_PLATFORM', 'https://sarasota.realtdm.com/public/cases/list', ''),
    ('Seminole', 'fl_laft_realtdm', 'GOVERNMENT_PLATFORM', 'https://seminole.realtdm.com/public/cases/list', ''),
    ('St. Johns', 'fl_laft_pioneer', 'GOVERNMENT_PLATFORM', 'https://apps.stjohnsclerk.com/TaxSmart', ''),
    ('St. Lucie', 'fl_laft_stlucie', 'GOVERNMENT_PLATFORM', 'https://acclaimweb.stlucieclerk.gov/TributeWeb/', ''),
    ('Sumter', 'fl_laft_html', 'GOVERNMENT_DIRECT', 'https://www.sumterclerk.com/public-records/tax-deeds/land-available-for-taxes/', 'https://www.sumterclerk.com/public-records/tax-deeds/land-available-for-taxes/'),
    ('Taylor', 'fl_laft_html', 'GOVERNMENT_DIRECT', 'https://taylorclerk.com/departments/list-of-lands-available/', 'https://taylorclerk.com/departments/list-of-lands-available/'),
    ('Union', 'fl_laft_html', 'GOVERNMENT_DIRECT', 'https://unionclerk.com/departments-services/clerk-services/list-of-lands-available/', 'https://unionclerk.com/departments-services/clerk-services/list-of-lands-available/'),
    ('Volusia', 'fl_laft_pdfs', 'GOVERNMENT_DIRECT', 'https://app02.clerk.org/cm_rpt/?id=lat', 'https://app02.clerk.org/cm_rpt/lands/LandsAvailableForTaxes.pdf'),
    ('Walton', 'fl_laft_pioneer', 'GOVERNMENT_PLATFORM', 'https://taxsmart.clerkofcourts.co.walton.fl.us/', ''),
    ('Washington', 'fl_laft_realtdm', 'GOVERNMENT_PLATFORM', 'https://washington.realtdm.com/public/cases/list', '')
)
update public.properties p
set inventory_type   = coalesce(p.inventory_type, 'POST_SALE_FIXED_PRICE'),
    source_authority = coalesce(p.source_authority, s.source_authority),
    source_id        = coalesce(p.source_id, s.source_id),
    list_url         = coalesce(p.list_url, s.list_url),
    document_url     = coalesce(p.document_url, nullif(s.document_url, ''))
from fl_sources s
where p.state = 'FL'
  and p.source = 'laft'
  and p.county = s.county;

-- FL laft rows whose county has no registry row (a harvester since removed,
-- or hand-entered rows): classify the inventory only.
update public.properties
set inventory_type = 'POST_SALE_FIXED_PRICE'
where state = 'FL' and source = 'laft' and inventory_type is null;

-- Honest amount semantics for FL laft rows: the sentinel 0 becomes NULL +
-- NOT_PUBLISHED; a real published figure is carried over, kind unspecified
-- (the legacy column never said which published figure it held).
update public.properties
set purchase_amount      = case when bid > 0 then bid else null end,
    purchase_amount_kind = case when bid > 0 then 'PUBLISHED_AMOUNT_KIND_UNSPECIFIED' else 'NOT_PUBLISHED' end
where state = 'FL' and source = 'laft' and purchase_amount_kind is null;

-- ---------------------------------------------------------------------------
-- 5. Backfill: Texas rows, by the harvester that wrote them.
-- ---------------------------------------------------------------------------
update public.properties
set source_authority = coalesce(source_authority, 'VENDOR_COUNSEL'),
    source_id        = coalesce(source_id, 'tx_lgbs'),
    inventory_type   = coalesce(inventory_type, case tx_sale_status
                          when 'Struck off to Jurisdiction' then 'STRUCK_OFF_HELD_IN_TRUST'
                          when 'Available for Future Sale' then 'FUTURE_RESALE'
                          else null end)
where state = 'TX' and harvester_source = 'tx_lgbs';

update public.properties
set source_authority = coalesce(source_authority, 'VENDOR_AUCTION'),
    source_id        = coalesce(source_id, 'tx_realauction')
where state = 'TX' and harvester_source = 'tx_realauction';

-- ---------------------------------------------------------------------------
-- 6. Backfill: Florida auction / certificate rows - authority and id only.
-- ---------------------------------------------------------------------------
update public.properties
set source_authority = coalesce(source_authority, 'VENDOR_AUCTION'),
    source_id        = coalesce(source_id, 'fl_realauction')
where state = 'FL' and source = 'auction';

update public.properties
set source_authority = coalesce(source_authority, 'VENDOR_AUCTION'),
    source_id        = coalesce(source_id, 'fl_lienhub_certificates')
where state = 'FL' and source = 'certificate';

commit;

-- Rollback (reverses everything above; get_properties() returns to 013's
-- projection - re-run 013's section 3 to restore it, then 015's pin if
-- applied):
--   alter table public.properties
--     drop column if exists inventory_type, drop column if exists source_authority,
--     drop column if exists source_id, drop column if exists list_url,
--     drop column if exists document_url, drop column if exists purchase_url,
--     drop column if exists purchase_url_kind, drop column if exists purchase_amount,
--     drop column if exists purchase_amount_kind, drop column if exists first_seen_at,
--     drop column if exists last_seen_at, drop column if exists delisted_at,
--     drop column if exists source_published_at, drop column if exists list_as_of,
--     drop column if exists source_document_sha256, drop column if exists source_etag,
--     drop column if exists source_last_modified, drop column if exists otc_provenance;
