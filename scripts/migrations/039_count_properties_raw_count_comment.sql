-- 039: say what count_properties() counts (FL-AVAIL-8, 2026-11-09).
--
-- count_properties(state, ledger) (migration 024) is a RAW ROW COUNT of the
-- rows the caller can read: every status, closed rows included, and BLOCKED
-- sources included for an admin. It exists to size get_properties()'s
-- parallel pages, and get_properties() itself returns every status, so the
-- two must agree - a status filter here would make paging stop early.
-- It is therefore NOT a customer inventory count: on 2026-11-09 it read 226
-- for Florida Available against 198 records a customer sees (24 closed, 3
-- BLOCKED, 1 not confirmed by its source). The customer count is computed in
-- the browser (public/app.js countsInTotals()). No caller in public/ uses it.
--
-- Comment only: no change to the function body, grants or RLS. Idempotent.
comment on function public.count_properties(text, text) is
  'Raw row count of public.properties the caller can read for a state (+ ledger_type): every status, closed rows included. Sizes get_properties() paging; NOT a customer inventory count (see public/app.js countsInTotals()).';
