-- 013: remove the five LAFT rows whose identity is PDF header/footnote text.
--
-- Data cleanup, not a schema change. scripts/harvest_laft_pdfs.py stored
-- column headers and a disclaimer paragraph as `parcel` (and, via its
-- case_no-from-parcel fallback, as `case_no`) for Leon, Volusia and Pasco.
-- The harvester now rejects those cells (looks_like_parcel /
-- is_plausible_record), but sync-laft-to-supabase.ps1 only upserts - it has
-- no gone-tracking - so the rows already in production never retire on their
-- own. Measured 2026-09-18 against the live table; the WHERE clause names
-- each row by its full conflict key so nothing else can match.
--
-- Run the SELECT first and confirm exactly 5 rows come back, then the DELETE.

select source, county, case_no, left(parcel, 40) as parcel, updated_at
  from public.properties
 where source = 'laft'
   and (county, case_no) in (
         ('Leon',    'PARCELNUMBER'),
         ('Pasco',   '2. The'),
         ('Volusia', 'CURRENTPURCHASEPRICEC'),
         ('Volusia', 'IDNUMBER'),
         ('Volusia', 'WNISTHEORIGINALOPENING')
       );

delete from public.properties
 where source = 'laft'
   and (county, case_no) in (
         ('Leon',    'PARCELNUMBER'),
         ('Pasco',   '2. The'),
         ('Volusia', 'CURRENTPURCHASEPRICEC'),
         ('Volusia', 'IDNUMBER'),
         ('Volusia', 'WNISTHEORIGINALOPENING')
       );
