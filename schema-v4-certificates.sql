-- Adds tax CERTIFICATE sales as a third tracked source, alongside the
-- existing 'auction' (tax deed) and 'laft' (Lands Available for Taxes).
--
-- Certificates are a different asset class: you're buying a lien position
-- (interest-earning, redeemable by the owner), not property. They're the
-- upstream step — a certificate only becomes a deed auction if it goes
-- unredeemed for 2+ years and someone applies for a deed. Kept in the same
-- `properties` table (not a new table) since the app's read/filter/note
-- patterns all already work off this one table; a `source` value is enough
-- to keep them distinct, same as 'auction' vs 'laft' today.
--
-- Safe to re-run. Purely additive — no drops, no data loss.

alter table public.properties drop constraint if exists properties_source_check;
alter table public.properties add constraint properties_source_check
  check (source in ('auction','laft','certificate'));

-- Certificate-specific fields that don't map cleanly onto the deed columns:
--   interest_rate   - the winning/asking rate (deeds use `bid` as a dollar
--                      amount; certificate auctions bid the rate down from
--                      18%, so `bid` stays null for certificates and this
--                      carries the number instead)
--   certificate_no  - the certificate #, distinct from case_no (case_no
--                      holds the account/parcel # for certificates, to
--                      match how `case_no` + `county` + `source` already
--                      forms the unique key everything upserts against)
alter table public.properties add column if not exists interest_rate numeric(5,2);
alter table public.properties add column if not exists certificate_no text;

-- Added alongside the above once the LienHub harvester's actual output shape
-- was worked out: the "County-Held Liens" listing carries a tax year and a
-- redemption window (issued/expiration), not a bid-down interest rate. The
-- expiration date is the important one - a certificate becomes deed-eligible
-- once it's gone unredeemed for 2 years, which is exactly the event this
-- whole app exists to watch for further upstream.
alter table public.properties add column if not exists tax_year text;
alter table public.properties add column if not exists issued_date date;
alter table public.properties add column if not exists expiration_date date;

create index if not exists properties_source_idx on public.properties (source);
