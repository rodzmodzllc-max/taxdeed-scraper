-- v4: allow 'certificate' as a properties.source value.
--
-- The frontend has always fully supported a Certificates ledger (ledger tab,
-- filters, card rendering all handle source='certificate'), but no schema
-- file in this repo ever added it to the CHECK constraint on
-- properties.source (schema.sql only allowed 'auction' / 'laft'). Live
-- certificate rows in Supabase mean this constraint was altered directly
-- against the database at some point and the change was never saved back
-- to a migration file here - this brings the schema file in sync with what
-- is actually deployed, so a fresh database built from these files matches
-- production.
--
-- Run this once in the Supabase SQL editor (or via `psql`) against the
-- project. Safe to run even if the constraint was already loosened by hand:
-- the DROP is guarded by IF EXISTS and the ADD will simply fail loudly
-- (rather than silently) if a constraint with this name already allows the
-- same values, which is fine to re-run.

ALTER TABLE properties
  DROP CONSTRAINT IF EXISTS properties_source_check;

ALTER TABLE properties
  ADD CONSTRAINT properties_source_check
  CHECK (source IN ('auction', 'laft', 'certificate'));
