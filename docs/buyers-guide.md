# Buyer's Guide (2026-10-29)

How buying works, per state / county / ledger, quoted from official sources.
The front end displays it; it never writes an answer of its own.

## Pipeline

```
data/buyers_guide/topics.csv        the fixed questions (topic, ledger, level, question, order)
data/buyers_guide/<ST>[-part].csv   research rows (rules: data/buyers_guide/README.md)
  -> harvesters/sources/buyers_guide.py   problems() / build() / answer_for()
  -> scripts/build_buyers_guide.py        writes public/buyers-guide.json (--check pinned by a test)
```

Rebuild after editing any CSV, then copy to the root (`cp public/buyers-guide.json .`) or let the mirror bot do it.

## public/buyers-guide.json

```
{ "about": "...",
  "topics": [ {topic, ledger, level, question, order}, ... ],
  "states": { "FL": { "statewide": { "AUCTIONS": [entry, ...], "AVAILABLE": [...], "LIENS_CERTIFICATES": [...], "ALL": [...] },
                      "counties":  { "Lee": { "AUCTIONS": [...], "ALL": [...] }, ... } } },
  "counts": { "VERIFIED": n, "NOT_VERIFIED": n, "NOT_APPLICABLE": n } }
entry = { topic, question, order, answer?, status, kind, quote?, source_url, source_title?, citation?, verified_on?, note? }
```

Lookup (mirror `answer_for()`): the county's own entry for the ledger, then the county's ALL entry, then the
statewide entry for the ledger, then statewide ALL. A county `county_office` entry may sit under the ledger
(Florida: clerk for AVAILABLE, tax collector for LIENS_CERTIFICATES) or under ALL.

Display rules:
- VERIFIED: show `answer`, then the quote and a link to `source_url` (+ `citation` for LAW, `verified_on`).
- NOT_APPLICABLE: show `answer` (e.g. "Texas does not sell tax lien certificates") with its quote and source.
- NOT_VERIFIED: never invent an answer - "Not verified yet - check <source_title or the official page>" linking `source_url`.
- Show `note` when present (amended law, conflicting county pages, reused earlier read).

## Coverage (2026-10-29)

1,122 VERIFIED, 223 NOT_VERIFIED, 2 NOT_APPLICABLE; county rows for FL 46, TX 123, MI 50, SC 4, CO 3, MN 3,
MO 2, PA 2, LA 1, OK 1, TN 1, WI 1 counties. Known gaps:
- RealAuction rules / FAQ pages (Florida auction details) answered 403 to the sandbox; a runner capture can fill them.
- Wisconsin statutes (docs.legis.wisconsin.gov) unreachable: all WI statewide rows NOT_VERIFIED.
- Tennessee statewide rows quote CTAS (University of Tennessee County Technical Assistance Service), which quotes
  the code; the code itself (LexisNexis) could not be read.
- Michigan `lien_overview` / `due_diligence` statewide rows quote Tax-Sale.info (the treasurers' contracted platform).

## Facts found that affect the rest of the product

- **Louisiana** (Acts 2024 No. 774, 2025 No. 411; const. amendment Acts 2024 No. 409): from 2026-01-01 the parish
  tax sale sells a tax lien certificate (bid down the monthly interest rate, 1% to 0.7%), not the property.
- **Colorado** SB 26-144 (effective 2026-06-01): treasurer's deeds replaced by a public auction; certificates issued
  from 2026-01-01 last 7 years, not 15.
- **Oklahoma**: tax certificate sections repealed in 2008; only the June resale.
- `kcmolandbank.org` now redirects to an unrelated site; never link it.
