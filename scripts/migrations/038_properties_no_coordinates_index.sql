-- 038: partial index on properties still waiting for coordinates.
--
-- Why: the Census address geocoder (scripts/geocode_properties.py) reads its
-- work pool as
--   where latitude is null and delisted_at is null and status in (...)
--         and address ... order by id limit 1000
-- With only the primary key, Postgres walked every row in id order to find
-- the ~3,300 without coordinates: EXPLAIN ANALYZE 2026-10-27 removed 70,097
-- rows by filter and took 22.8 s, past the statement timeout, so passes 1
-- and 3 of run #422 (job=geocode, geocode_mode=address) failed with HTTP
-- 500 after every retry. This index holds only the rows that still need a
-- location, in id order, so the same page reads those rows alone.
--
-- Idempotent. Not a security or RLS change. Plain CREATE INDEX (the SQL
-- editor runs inside a transaction, so CONCURRENTLY is not possible).
create index if not exists properties_no_coordinates_idx
  on public.properties (id)
  where latitude is null and delisted_at is null;
