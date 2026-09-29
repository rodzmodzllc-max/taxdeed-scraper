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
--
-- EXECUTED against production 2026-09-18 (Claude Code session, with Marc's
-- explicit authorization). Pre-check: SELECT returned exactly 5 rows; table
-- total 4,167; no notes/favorites/bid_list references; one `hidden` row
-- pointed at the Pasco junk row and was removed with it (hidden has no FK).
-- Deleted ids: 5151e428-1cbe-460a-983d-874e618f1eae (Leon),
-- de7c3044-7123-411a-98ee-e536ade44adb (Pasco),
-- 5788b580-0593-449b-ac4d-51c2530b0b53, a023ea07-6b2f-4345-8542-984c8200226f,
-- 4f340703-153c-48dd-95d4-754beb608f47 (Volusia). Post-check: total 4,162,
-- 0 of these keys remain, Leon LAFT 2 / Volusia LAFT 11 legitimate rows
-- untouched, 0 orphaned hidden rows. Kept as the audit record; re-running
-- is a no-op.

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
