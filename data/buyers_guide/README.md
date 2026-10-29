# Buyer's Guide data

One CSV per state (`<ST>.csv`), written from official sources only. The builder
(`scripts/build_buyers_guide.py`) validates every file and renders
`public/buyers-guide.json`. The front end only displays it.

## Columns

| column | meaning |
|---|---|
| `state` | two-letter code |
| `county` | blank = statewide; otherwise the county / parish name exactly as `properties.county` spells it |
| `ledger` | `AUCTIONS`, `AVAILABLE`, `LIENS_CERTIFICATES` or `ALL` |
| `topic` | one of the topics in `topics.csv` |
| `answer` | 1-3 plain-English sentences that say ONLY what the quote says. No advice, no inference, no numbers that are not in the quote. |
| `status` | `VERIFIED` (quote read from the source, below), `NOT_VERIFIED` (no source found / not readable - `answer` must be blank) or `NOT_APPLICABLE` (the source itself says the state/county does not do this, quoted) |
| `kind` | `LAW` (statute / constitution / rule) or `PROCEDURE` (county or agency page / document) |
| `quote` | the exact words from the source the answer rests on (max ~400 chars). Required for VERIFIED and NOT_APPLICABLE. |
| `source_url` | https URL of the official page / document actually read. Required for every row (for NOT_VERIFIED: the official page a buyer should check). |
| `source_title` | the page's own title |
| `citation` | statute citation for LAW rows (e.g. `F.S. 197.502(6)`), blank for PROCEDURE |
| `verified_on` | date the source was read (YYYY-MM-DD). Required for VERIFIED / NOT_APPLICABLE, blank otherwise. |
| `note` | optional: e.g. "statute amended 2025; effective 2026-01-01" |

## Rules

- **Official sources only**: the state legislature / revisor / code site, the state agency, the county
  (clerk, treasurer, tax collector, sheriff, assessor, land bank) or the county's contracted sale
  platform's own rules page. Never a blog, a seminar site, a law-firm article or an AI summary.
- **Never from memory.** If the page cannot be read, the row is `NOT_VERIFIED` with a blank answer.
- One row per (state, county, ledger, topic). A county row overrides the statewide row for that county.
- Public files: never a parcel number, owner name or street address.
