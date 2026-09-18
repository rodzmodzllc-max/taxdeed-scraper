-- Phase 56 / plan step 4: FEMA National Flood Hazard Layer.
--
-- The first real entry in the Risk & Legal panel. Migration 007 established
-- the rule this file obeys: every risk fact is a PAIR of a value and a
-- `_checked_at` timestamp, because a NULL count rendered as "None found"
-- tells someone about to bid real money that a property is clear when the
-- truth is that nobody looked.
--
-- ============================================================================
-- THE DISTINCTION THIS FILE EXISTS TO PRESERVE
-- ============================================================================
-- A FEMA point query has THREE outcomes, not two:
--
--   1. A feature comes back           -> that is the property's flood zone.
--   2. No feature comes back          -> the area is NOT MAPPED by FEMA.
--   3. The request failed             -> we know nothing; nothing is written.
--
-- Case 2 is the trap. "FEMA has no flood map covering this parcel" is not
-- the same fact as "FEMA mapped it and found minimal hazard" (zone X), and a
-- pipeline that quietly wrote NULL for both would let the UI render an
-- unmapped rural parcel as low-risk. So case 2 writes the explicit sentinel
-- 'UNMAPPED' rather than NULL, and `flood_sfha` stays NULL because the
-- Special Flood Hazard Area question genuinely has no answer there.
--
-- `flood_sfha` is the field that actually matters to a bidder: it is FEMA's
-- own SFHA_TF flag, and it - not the zone letter - is what drives the
-- federal mandatory-purchase requirement for flood insurance on a mortgaged
-- property. Zone letters are easy to misread; the flag is not.
-- ============================================================================

begin;

-- 007 declares these two as well. Repeated with `if not exists` on purpose:
-- 007 is on an unmerged branch, so this file must apply before it, after it,
-- or without it ever landing.
alter table public.properties add column if not exists flood_zone       text;
alter table public.properties add column if not exists flood_checked_at timestamptz;

alter table public.properties add column if not exists flood_zone_subtype text;
alter table public.properties add column if not exists flood_sfha         boolean;
alter table public.properties add column if not exists flood_bfe          numeric;
alter table public.properties add column if not exists flood_firm_id      text;

comment on column public.properties.flood_zone is
  'FEMA NFHL FLD_ZONE at the parcel''s coordinates, or the sentinel '
  '''UNMAPPED'' when FEMA returns no polygon for that point. UNMAPPED is NOT '
  'zone X: it means no flood map covers the parcel, which is an absence of '
  'information, not a finding of low risk. NULL means never checked.';

comment on column public.properties.flood_checked_at is
  'When a FEMA lookup last succeeded for this row. NULL means never checked - '
  'and a NULL here must never render as "no flood risk". A failed request '
  'leaves this NULL rather than stamping a check that did not happen.';

comment on column public.properties.flood_zone_subtype is
  'FEMA NFHL ZONE_SUBTY, e.g. "AREA OF MINIMAL FLOOD HAZARD". Plain-language '
  'context for the zone letter.';

comment on column public.properties.flood_sfha is
  'FEMA NFHL SFHA_TF as a boolean: is this parcel in a Special Flood Hazard '
  'Area? This is the field that drives the federal mandatory flood-insurance '
  'purchase requirement on a mortgaged property - more decision-relevant than '
  'the zone letter, and harder to misread. NULL where unmapped or unchecked.';

comment on column public.properties.flood_bfe is
  'FEMA NFHL STATIC_BFE, the base flood elevation in feet. FEMA uses -9999 as '
  'its no-data sentinel; that is converted to NULL on write and never stored.';

comment on column public.properties.flood_firm_id is
  'FEMA NFHL DFIRM_ID - which Flood Insurance Rate Map panel the answer came '
  'from, so a zone can be traced back to its source map.';

-- The same shape of guard 007 puts on its risk pairs: a value without a
-- check is impossible by construction, so nothing downstream can render a
-- zone that no lookup produced.
alter table public.properties drop constraint if exists properties_flood_needs_a_check;
alter table public.properties add constraint properties_flood_needs_a_check check (
      (flood_zone         is null or flood_checked_at is not null)
  and (flood_zone_subtype is null or flood_checked_at is not null)
  and (flood_sfha         is null or flood_checked_at is not null)
  and (flood_bfe          is null or flood_checked_at is not null)
  and (flood_firm_id      is null or flood_checked_at is not null)
);

-- An unmapped parcel has no SFHA answer. Writing false there would be an
-- assertion FEMA never made.
alter table public.properties drop constraint if exists properties_flood_unmapped_has_no_sfha;
alter table public.properties add constraint properties_flood_unmapped_has_no_sfha check (
  flood_zone is distinct from 'UNMAPPED' or flood_sfha is null
);

create index if not exists properties_flood_unchecked_idx
  on public.properties (state, county)
  where flood_checked_at is null;

commit;
