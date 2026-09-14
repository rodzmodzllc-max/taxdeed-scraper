-- Adds the raw 2-digit Florida DOR property-use code (e.g. "00" Vacant
-- Residential, "01" Single Family, "10" Vacant Commercial, "40" Vacant
-- Industrial) alongside the existing translated `prop_type` label.
--
-- scripts/enrich_property_details.py has fetched DOR_UC from the FDOR
-- Statewide Cadastral layer for every matched parcel since 2026-09-02, but
-- only ever translated it into the coarser prop_type bucket
-- (Residential/Commercial/Industrial/etc.) - the exact code itself was
-- never persisted. Flagged as an open gap in this project's own docs
-- (claude/homestead-risk-and-bid-calculator.md,
-- claude/three-ledger-desktop-layouts.md) before this migration closed it
-- 2026-09-08.
--
-- Purely additive: no existing column is touched, no RLS change is needed
-- (this table's existing SELECT policies already cover every column), and
-- enrich_property_details.py backfills it incrementally on its normal
-- per-county schedule - no separate backfill script required.
--
-- DEPENDENCY (added Phase 14D, Migration Reconciliation & Pre-Execution
-- Re-Gate, 2026-09-14): this file was committed to the repo but never
-- actually run against production (confirmed via a live information_
-- schema.columns audit in Phase 14C - dor_use_code is absent from the live
-- 47-column public.properties table). scripts/migrations/
-- 005_customer_safe_properties_projection.sql's RETURNS TABLE clause names
-- dor_use_code, so 005 will fail outright with a "column does not exist"
-- error if run before this file. THIS MIGRATION MUST RUN BEFORE
-- scripts/migrations/005_customer_safe_properties_projection.sql (and,
-- transitively, before 005a). Corrected execution order: this file -> 005
-- -> 005a. See docs/phase-14d-migration-reconciliation.md for the full
-- reconciliation and the pre-execution checklist a fresh Gate A must
-- re-verify before any of the three are applied.
alter table public.properties add column if not exists dor_use_code text;

comment on column public.properties.dor_use_code is
  'Raw 2-digit Florida DOR property-use code from the FDOR Statewide Cadastral layer (e.g. "00" Vacant Residential, "01" Single Family), zero-padded to 2 digits. Null where there is no FDOR match yet, or the match came from a county-specific fallback layer (Santa Rosa, Flagler) that does not carry this field.';
