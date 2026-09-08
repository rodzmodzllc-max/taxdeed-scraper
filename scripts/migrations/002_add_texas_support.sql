-- Adds Texas tax-sale support to the shared `properties` table, extending
-- the existing Florida-only schema to a `state`-partitioned multi-state
-- model.
--
-- Context: every existing row implicitly assumed state='FL' (no column
-- existed because there was only one state). This migration makes state
-- explicit and additive so every existing FL row keeps working unchanged.
--
-- Texas-specific columns store what Florida has no equivalent for: the raw
-- Texas Comptroller property classification code (tx_category, mirroring
-- how dor_use_code already stores Florida's raw DOR code - see
-- schema-v9-dor-use-code.sql), the statutory redemption period and its
-- resulting expiration date, and the statutory maximum return an investor
-- could realize if the owner redeems right up to the deadline.
--
-- Purely additive: no existing column is touched, no RLS change needed
-- (this table's existing SELECT policies already cover every column), and
-- every new column besides `state` is nullable so existing FL rows land
-- with state='FL' and everything else NULL until Texas harvesting starts.
--
-- NOT YET RUN against production. Draft only - see the accompanying
-- writeup for the open architectural questions (per-CAD enrichment source,
-- per-vendor harvester coverage) that should be resolved with real,
-- live-verified research before this is applied, the same discipline this
-- project used for every Florida schema change.

-- 1. State partition column. Defaults to 'FL' so every existing row is
--    correctly backfilled by this single statement with no separate
--    UPDATE needed.
alter table public.properties add column if not exists state text not null default 'FL';

comment on column public.properties.state is
  'Two-letter USPS state code the property sits in (e.g. "FL", "TX"). Defaults to FL for backward compatibility with every row that predates multi-state support.';

-- 2. Raw Texas Comptroller property classification code (SPTB state code),
--    e.g. "A1" (Single-Family Residential), "C1" (Vacant Lots/Tracts),
--    "D1" (Qualified Open-Space Land), "F1" (Commercial Real Property).
--    Mirrors dor_use_code's role for Florida: store the raw code so the
--    frontend can render the state's own exact category rather than only
--    a translated bucket. NULL for Florida rows and for Texas rows not yet
--    CAD-enriched.
--
--    NOTE, confirmed via research before writing this: the Texas
--    Comptroller's own Property Classification Guide
--    (comptroller.texas.gov/taxes/property-tax/docs/96-313.pdf) documents
--    "standard" SPTB codes, but individual appraisal districts are NOT
--    required to follow it exactly - multiple independent sources state
--    plainly that state codes are not standardized across all counties in
--    Texas. Treat any per-CAD code -> label mapping the same way this
--    project treats FDOR per-county parcel-ID normalization: verify live
--    against each CAD before trusting it, never assume county B's "C1"
--    means the same thing as county A's.
alter table public.properties add column if not exists tx_category text;

comment on column public.properties.tx_category is
  'Raw Texas Comptroller property classification (SPTB) code from the county CAD, e.g. "A1" Single-Family Residential, "C1" Vacant Lots/Tracts, "D1" Qualified Open-Space/Agricultural, "F1" Commercial. NULL for non-Texas rows or before CAD enrichment. Individual CADs are not required to follow the state's standard code list exactly - verify per-CAD, do not assume it is standardized across counties.';

-- 3. Statutory redemption period length, in whole months, derived at
--    enrichment/harvest time from homestead/agricultural/mineral-interest
--    status per Tex. Tax Code 34.21: 24 months if any of those apply, 6
--    otherwise. Stored explicitly (not only derived on read) so a future
--    change to the classification logic doesn't retroactively change the
--    redemption terms shown for a deed already sold under the old
--    mapping.
--
--    IMPORTANT, and the reason this column exists separately from
--    redemption_expiration_date: the short period is statutorily 180
--    DAYS, which is not exactly 6 calendar months. This column is a
--    coarse, human-readable summary ("6" or "24") for filtering/display;
--    redemption_expiration_date below is the actual day-precise deadline
--    and is what any real countdown or "days left to redeem" UI should
--    use.
alter table public.properties add column if not exists redemption_period_months int;

comment on column public.properties.redemption_period_months is
  'Statutory redemption period under Tex. Tax Code 34.21, in whole months: 24 for homestead/agricultural-use/mineral-interest property, 6 for everything else. A coarse summary field - see redemption_expiration_date for the day-precise deadline, since the short period is statutorily 180 days, not exactly 6 calendar months. NULL for non-Texas rows.';

-- 4. Exact redemption deadline: deed-filing (or, until that date is
--    tracked, auction/sale) date + the precise statutory period - 180
--    DAYS for non-homestead/ag/mineral property, or 2 CALENDAR YEARS for
--    homestead/agricultural/mineral-interest property (Tex. Tax Code
--    34.21(a)-(e)).
alter table public.properties add column if not exists redemption_expiration_date date;

comment on column public.properties.redemption_expiration_date is
  'Day-precise date the statutory right of redemption expires: sale/deed-filing date + 180 days for non-homestead/agricultural/mineral property, or + 2 calendar years for homestead/agricultural-use/mineral-interest property (Tex. Tax Code 34.21). NULL for non-Texas rows or before a sale date is known.';

-- 5. The maximum statutory return an investor could realize if the owner
--    redeems at the last possible moment (worst-case-for-owner /
--    best-case-for-investor timing): (min/winning bid + deed recording
--    fee + taxes/penalties/interest/costs paid) x 1.50 for a 2nd-year
--    homestead/agricultural/mineral redemption, or x 1.25 for everything
--    else. This is a CEILING, not an expected value - most redemptions
--    (when they happen at all - most tax-sale purchases are never
--    redeemed) happen earlier and pay a smaller premium, and many
--    properties are never redeemed at all, in which case the purchaser
--    simply keeps the property rather than receiving a cash premium.
--    Informational only - not legal or financial advice, and not a
--    guarantee of any return; verify current statute and consult counsel
--    before relying on this figure for a real bid.
alter table public.properties add column if not exists max_statutory_return_usd numeric(12,2);

comment on column public.properties.max_statutory_return_usd is
  'Ceiling on the statutory redemption premium an investor could realize if the property is redeemed at the last possible moment: aggregate redemption cost (bid + recording fee + taxes/penalties/interest/costs) x 1.50 for homestead/agricultural/mineral property redeemed in year 2, or x 1.25 otherwise. A maximum, not an expected value - most tax-sale purchases are never redeemed at all. Informational only, not financial advice. NULL for non-Texas rows or before a bid amount is known.';

-- 6. Minimum bid required to enter the sale (distinct from a Florida-style
--    opening bid - Texas sales run against a court-ordered minimum set to
--    cover taxes/penalties/interest/costs and (for a resale) an
--    adjudicated or assessed value floor, not a bid that starts at $0 or
--    at back-taxes-owed the way some FL LAFT listings do). Kept as its
--    own column rather than overloading an FL-shaped bid column so a
--    future MAO/spread calculation (min_bid vs. CAD market value) has an
--    unambiguous input.
alter table public.properties add column if not exists min_bid numeric(12,2);

comment on column public.properties.min_bid is
  'Court-ordered minimum bid required to participate in a Texas tax sale (Tex. Tax Code 34.01 / 34.05), distinct from a Florida-style opening bid. NULL for non-Texas rows or before harvest data includes it.';

-- Indexes: state+county is the natural scoping filter for almost every
-- future Texas query (mirrors how every FL query already scopes by
-- county); tx_category supports filtering/faceting by property type in
-- the OTC catalog and Event Terminal views, the same role dor_use_code
-- already plays for Florida.
create index if not exists idx_properties_state_county on public.properties(state, county);
create index if not exists idx_properties_tx_category on public.properties(tx_category) where tx_category is not null;
