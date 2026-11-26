-- 044: product_events accepts 'link_opened' (2026-11-25).
--
-- Owner, 2026-11-25: the admin Users & usage view should show the outside
-- links people open (the property appraiser, Zillow, maps, county pages).
-- Only links inside an open property were recorded, under the four
-- acquisition / source events. app.js now records every other outside link
-- as 'link_opened' with props {host, area} - the site's host name and where
-- in the app it was clicked, never the full address.
--
-- 024 created the table with a CHECK on event (product_events_event_check,
-- confirmed in production 2026-11-25). This replaces that CHECK with the same
-- list plus 'link_opened'. Nothing else changes: grants, RLS, props size check.
-- Idempotent: dropping and re-adding the named constraint.

alter table public.product_events drop constraint if exists product_events_event_check;
alter table public.product_events add constraint product_events_event_check check (event in (
  'session_start', 'search_performed', 'property_viewed', 'property_saved', 'property_watched',
  'acquisition_source_opened', 'acquisition_instructions_opened', 'application_opened', 'official_source_opened',
  'export_performed', 'alert_created', 'alert_opened', 'saved_search_created', 'saved_search_opened', 'saved_search_updated',
  'state_selected', 'county_selected', 'map_used', 'acquisition_section_viewed', 'search_interpreted', 'county_dossier_opened',
  'link_opened'));
