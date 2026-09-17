-- Phase 52: the columns needed to store the FDOR cadastral fields that
-- `scripts/enrich_property_details.py` was leaving on the table.
--
-- Provenance of every mapping in this file: the Florida Department of
-- Revenue "2025 NAL/SDF/NAP User's Guide", which is the only authoritative
-- definition of these codes. The ArcGIS layer's own metadata is NOT a source
-- of meaning - every one of its 127 fields has an `alias` identical to its
-- `name`, so the layer tells you a column is called DEL_VAL and nothing
-- whatsoever about what DEL_VAL contains. Each column below carries the
-- guide's wording for the field it is fed from.
--
-- ============================================================================
-- THE TRAP THIS FILE EXISTS TO NOT FALL INTO
-- ============================================================================
-- DEL_VAL is not delinquent tax.
--
-- The guide defines DEL_VAL as "Reduction in just value resulting from the
-- deletion of improvements on the property since the previous assessment" -
-- DELETION value, not DELINQUENT value. A tax-deed product that wrote
-- DEL_VAL into a `delinquent_tax` column would print a confident dollar
-- figure for back taxes owed that is actually the value of a torn-down barn,
-- on the exact screen where someone decides what to bid.
--
-- So this migration adds NO tax-amount column fed from FDOR, because the NAL
-- file contains no tax-amount field at all. Confirmed against the guide:
-- there is no billed tax, no taxes due, no delinquent tax, no bedrooms, no
-- bathrooms, no zoning, no subdivision name and no municipality anywhere in
-- the NAL layout. Those columns in 007 stay NULL until a real source (tax
-- collector, county CAMA, clerk, local zoning GIS) is acquired for them, and
-- `docs/fdor-field-provenance.md` records that so the next person does not
-- go looking for them here again.
-- ============================================================================

begin;

-- ---------------------------------------------------------------------------
-- 0. Columns 007 also declares.
-- ---------------------------------------------------------------------------
-- Repeated here with `if not exists` on purpose: 007 is on an unmerged
-- branch, so this file must be applicable before it, after it, or without it
-- ever landing. Both files are idempotent and neither depends on the other's
-- ordering.
alter table public.properties add column if not exists taxable_value     numeric;
alter table public.properties add column if not exists improvement_value numeric;
alter table public.properties add column if not exists land_use          text;
alter table public.properties add column if not exists acreage           numeric;
alter table public.properties add column if not exists field_provenance  jsonb;

comment on column public.properties.taxable_value is
  'FDOR TV_NSD: "Taxable value for county purposes, which is based on non-school '
  'district assessed value." Post-exemption. Pairs with assessed (AV_NSD), which '
  'is pre-exemption - see 007.';

comment on column public.properties.improvement_value is
  'DERIVED, not a source field: JV - LND_VAL. The NAL layout has no improvement-'
  'value column, so this is just value minus land just value, i.e. the just value '
  'not attributable to the land. It therefore INCLUDES special-feature value. '
  'Written only when both inputs are present and JV > LND_VAL; provenance is '
  'recorded as fdor:JV-LND_VAL so the UI can label it as computed, not reported.';

comment on column public.properties.land_use is
  'FDOR PA_UC: "County-defined use codes. Please contact the county property '
  'appraiser for information." This is the COUNTY''s own code and is not '
  'comparable across counties - unlike dor_use_code (DOR_UC), which is the '
  'state-defined code and is.';

comment on column public.properties.acreage is
  'DERIVED: LND_SQFOOT / 43560. LND_SQFOOT is defined as "Equivalent square '
  'footage of the site regardless of the information in fields 42 and 43", i.e. '
  'it is site square footage whatever the land-unit basis of assessment was, so '
  'this is a pure unit conversion rather than a reinterpretation.';

-- ---------------------------------------------------------------------------
-- 1. The most recent sale, told honestly
-- ---------------------------------------------------------------------------
-- `last_sale_price`/`last_sale_year` already exist and are already populated
-- from SALE_PRC1/SALE_YR1. What has been missing is everything that says
-- whether that number means anything.
--
-- QUAL_CD1 is the field that matters. A tax roll's most recent "sale" is very
-- often a $100 quitclaim between relatives, a deed correction, or a forced
-- sale - the property appraiser marks those as disqualified precisely so they
-- are not used as market evidence. Showing SALE_PRC1 on a bidder's screen
-- without its qualification code presents an intra-family $100 transfer as
-- the property's last market price.
alter table public.properties add column if not exists last_sale_month     smallint;
alter table public.properties add column if not exists last_sale_qual_code text;
alter table public.properties add column if not exists last_sale_vi_code   text;
alter table public.properties add column if not exists last_sale_or_book   text;
alter table public.properties add column if not exists last_sale_or_page   text;
alter table public.properties add column if not exists last_sale_clerk_no  text;

comment on column public.properties.last_sale_month is
  'FDOR SALE_MO1: "Month of the transaction listed."';
comment on column public.properties.last_sale_qual_code is
  'FDOR QUAL_CD1: "Code denoting the property appraiser''s sales qualification '
  'decisions." A disqualified sale is NOT market evidence. The UI must not '
  'present last_sale_price as a market price without this code.';
comment on column public.properties.last_sale_vi_code is
  'FDOR VI_CD1: "Code indicating V for vacant property or I for improved '
  'property." This is the state at the time of THAT SALE, not today.';
comment on column public.properties.last_sale_or_book is
  'FDOR OR_BOOK1: "Official record book number for the sale transaction listed '
  'as the county''s clerk of the court has recorded."';
comment on column public.properties.last_sale_or_page is
  'FDOR OR_PAGE1: "Official record book''s page number for the sale transaction '
  'listed."';
comment on column public.properties.last_sale_clerk_no is
  'FDOR CLERK_NO1: "Clerk''s Instrument Number for the sale transaction '
  'listed." Book/page/instrument together are the lookup key into the county '
  'clerk''s official records - the entry point for a real title/lien check.';

-- ---------------------------------------------------------------------------
-- 2. The prior sale
-- ---------------------------------------------------------------------------
-- Two points make a line. One sale is a number; a prior sale is the only
-- thing in this dataset that says which way the number was going.
alter table public.properties add column if not exists prior_sale_price     numeric;
alter table public.properties add column if not exists prior_sale_year      integer;
alter table public.properties add column if not exists prior_sale_month     smallint;
alter table public.properties add column if not exists prior_sale_qual_code text;

comment on column public.properties.prior_sale_price is
  'FDOR SALE_PRC2: "Sale price indicated by documentary stamps on the deed", '
  'for the second transaction listed.';
comment on column public.properties.prior_sale_qual_code is
  'FDOR QUAL_CD2, same meaning as QUAL_CD1. Same warning applies.';

-- ---------------------------------------------------------------------------
-- 3. Structure facts the layer has and we were not asking for
-- ---------------------------------------------------------------------------
alter table public.properties add column if not exists effective_year_built integer;
alter table public.properties add column if not exists num_res_units        integer;

comment on column public.properties.effective_year_built is
  'FDOR EFF_YR_BLT: "Primary structure''s effective year built, adjusted to '
  'compensate for any substantial changes." Renovation-aware; year_built '
  '(ACT_YR_BLT) is the actual year the structure was built. A 1950 house with '
  'an effective year of 1998 has been substantially rebuilt - which is the '
  'difference between the two columns and worth showing as such.';
comment on column public.properties.num_res_units is
  'FDOR NO_RES_UNT: "Number of residential units on the parcel." Units, not '
  'bedrooms. The NAL layout has no bedroom or bathroom field.';

-- ---------------------------------------------------------------------------
-- 4. ALT_KEY - stored under its own name, deliberately
-- ---------------------------------------------------------------------------
-- It is tempting to call this the tax collector account number, because for
-- several counties it looks like one. The guide does not say that. It says:
-- "Optional alternate key identifier some counties use in addition to unique
-- parcel identification" - which tells us it is a county-chosen secondary
-- key and tells us nothing about which system that key belongs to.
--
-- So it is stored as fdor_alt_key: the raw value, under the name of the field
-- it came from. If the tax-collector hypothesis is later validated for a
-- county, that becomes a documented per-county fact and nothing here has to
-- be rewritten or un-mislabelled.
alter table public.properties add column if not exists fdor_alt_key text;

comment on column public.properties.fdor_alt_key is
  'FDOR ALT_KEY: "Optional alternate key identifier some counties use in '
  'addition to unique parcel identification." NOT established to be a tax '
  'collector account number - that is an open hypothesis, per county. Do not '
  'build a tax-collector URL from this without validating that county first.';

-- ---------------------------------------------------------------------------
-- 5. Sanity constraints
-- ---------------------------------------------------------------------------
-- Months are months. FDOR uses 0/blank as its no-data sentinel, and the
-- enrichment writer already converts those to NULL, so a 0 arriving here
-- means the writer regressed.
alter table public.properties drop constraint if exists properties_sale_months_valid;
alter table public.properties add constraint properties_sale_months_valid check (
      (last_sale_month  is null or (last_sale_month  between 1 and 12))
  and (prior_sale_month is null or (prior_sale_month between 1 and 12))
);

alter table public.properties drop constraint if exists properties_derived_values_non_negative;
alter table public.properties add constraint properties_derived_values_non_negative check (
      (taxable_value     is null or taxable_value     >= 0)
  and (improvement_value is null or improvement_value >= 0)
  and (acreage           is null or acreage           >= 0)
  and (prior_sale_price  is null or prior_sale_price  >= 0)
);

-- A prior sale that is newer than the "last" sale means the two sale slots
-- got written in the wrong order somewhere upstream. FDOR orders them
-- most-recent-first; this pins that assumption so a reordering is caught at
-- write time rather than shown as a price history running backwards.
alter table public.properties drop constraint if exists properties_sale_order_is_recent_first;
alter table public.properties add constraint properties_sale_order_is_recent_first check (
  last_sale_year is null or prior_sale_year is null or prior_sale_year <= last_sale_year
);

commit;
