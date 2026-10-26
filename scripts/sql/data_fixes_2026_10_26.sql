-- Production data corrections from the data-quality audit of 2026-10-26
-- (docs/review/data-quality-audit-2026-10-26.md). Each statement is a
-- deterministic correction of a value the code fixed in the same PR would no
-- longer write; none invents a value. Applied 2026-10-26 through the
-- Supabase SQL editor API, one statement at a time; the row counts below are
-- the counts measured immediately before applying (counts only, no values).
--
-- Every UPDATE also bumps updated_at through the properties_touch trigger.
-- No RLS policy, migration, trigger or constraint is touched.

-- 1. Texas min_bid = 0 is the vendor's "not posted" value, not a $0 bid.
--    scripts/sync-texas-to-supabase.py now stores it as NULL (bid keeps the
--    legacy 0 sentinel, which every reader already treats as "not published").
--    Rows applied: 22, all active (8 auction, 14 laft), all tx_lgbs.
update public.properties
   set min_bid = null
 where state = 'TX' and min_bid = 0;

-- 2. Texas rows written without source_id. The harvester's own id is in
--    harvester_source; scripts/sync-texas-to-supabase.py now sends it as
--    source_id too, and scripts/apply_acquisition_paths.py (keyed on
--    source_id) could not reach these rows, so 3,263 active LGBS Available
--    rows carried no source link. Rows applied: 3,775, all active (3,263 laft
--    tx_lgbs, 443 auction tx_lgbs, 69 auction tx_realauction).
update public.properties
   set source_id = harvester_source
 where state = 'TX' and source_id is null and harvester_source is not null;

-- 3. Coordinates outside the row's own state (the bounds in
--    harvesters/enrichment/geocode.STATE_BOUNDS) are not the property's
--    location: one FL auction row sat in Texas (no recorded coordinate
--    origin - a legacy geocode from before verify_match), one TX LGBS row in
--    Louisiana (vendor point; the Texas sync now refuses it). The flood check
--    and the NAIP image of the FL row were taken at that wrong point, so they
--    are cleared back to "not checked" and the enrichment jobs redo them.
--    Rows applied: 6 (2 active - 1 FL, 1 TX - and 4 FL closed / notfound rows
--    with the same out-of-state points).
update public.properties
   set latitude = null, longitude = null,
       flood_zone = null, flood_zone_subtype = null, flood_sfha = null, flood_bfe = null, flood_firm_id = null,
       flood_checked_at = null,
       photo_url = null, photo_source = null, photo_captured_year = null, photo_checked_at = null
 where latitude is not null
   and ((state = 'FL' and not (latitude between 24.0 and 31.5 and longitude between -88.0 and -79.5))
     or (state = 'TX' and not (latitude between 25.5 and 37.0 and longitude between -107.0 and -93.0)));

-- 4. Florida rows closed by absence carry no delisted_at: the PowerShell
--    close-outs write status only. The close-out instant is the row's own
--    trigger-stamped gone_since (migration 006); copy it, the same rule
--    scripts/stamp_seen.py --delisted applies after every run. Rows the
--    source marked sold, with a published result, or without a gone_since are
--    left alone. Rows applied: 1,092 (1,036 closed auctions + 56 notfound
--    certificates). 586 closed auctions have no gone_since (closed in a bulk
--    write on 2026-09-30) and stay without delisted_at - no time is invented.
update public.properties
   set delisted_at = gone_since
 where state = 'FL' and source in ('auction', 'certificate')
   and status in ('closed', 'notfound')
   and delisted_at is null and gone_since is not null
   and coalesce(inventory_status, '') <> 'sold'
   and result_amount is null and result_date is null;

-- 5. An active row carrying delisted_at: it was re-listed after a close-out
--    and the reactivation never cleared it (fixed in sync_state_inventory.py
--    and laft_lifecycle.py). Only rows last seen after their delisted_at.
--    Rows applied: 1 (mi_detroit_landbank_lots).
update public.properties
   set delisted_at = null
 where status in ('active', 'available') and delisted_at is not null and last_seen_at > delisted_at;
