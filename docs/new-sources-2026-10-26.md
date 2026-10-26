# New sources sprint (2026-10-26)

**Owner decision, 2026-10-26:** "You need to find every fucking property and every source, and then we'll work on
the legal shit." Terms-of-service and licensing risk is accepted by the owner for **collection**. Every source below:

- holds owner-accepted INTERIM permission records in `data/source_permissions.csv` (`discover`, `fetch`, `parse`,
  `store`; `OWNER_PERMISSION_REQUIRED` + `INTERNAL_RISK_ACCEPTANCE`, effective 2026-10-26, expiring 2027-04-12),
  written by `scripts/add_owner_interim_permissions.py`. There is no `display` record, so nothing is customer-published;
- is `UNREVIEWED` in the registry (`expansion.PUBLICATION`, restriction text `OWNER_INTERIM_2026_10_26`): admins see the
  rows labelled, customers do not until an admin review approves the source;
- is collected for **every** ledger, auctions included: `source_publication.owner_collection()` lets the sprint's
  sources (`expansion.NEW_SOURCE_IDS`) through the collection rule; the permission record is still required.

Hard limits kept: no login, no CAPTCHA, no paywall, no IP evasion or proxy rotation; honest User-Agent; polite rate.

Structure was read live from the sandbox on 2026-10-26 (field names, counts, status vocabularies only) and validated
read-only on GitHub Actions with `job=evidence`, `evidence_scope=new_sources_validate` (no database credential; the
harvest prints counts and identifier shapes only).

## Implemented

| State | Source id | Ledger | What | Live count 2026-10-26 |
|---|---|---|---|---|
| MO | `mo_kc_landbank` | Available | Land Bank of Kansas City, MO - ePropertyPlus `public-kclb` (list presence; one Clay row and the vendor's test row excluded) | 2,575 |
| PA | `pa_pittsburgh_city_property` | Available | City of Pittsburgh city-owned property - ePropertyPlus `public-pgh`, `s_custom_0010 = 'Available for Sale'` | 1,590 of 2,933 |
| MI | `mi_wayne_county_landbank` | Available | Wayne County Land Bank - ePropertyPlus `public-wclb`, `available = 'Y'` | 810 of 841 |
| MI | `mi_saginaw_landbank` | Available | Saginaw County Land Bank - ePropertyPlus `public-sclb` (list presence; no price) | 712 |
| MI | `mi_calhoun_landbank` | Available | Calhoun County Land Bank - ePropertyPlus `public-cclb` (list presence) | 219 |
| MI | `mi_genesee_landbank` | Available | Genesee County Land Bank (Flint) - "Search All Properties", a server-side paged table (`paged_table.py`); 'Demolition Program' excluded | ~10,670 listed (427 pages) |
| MI | `mi_tax_sale_info_auction` | Auctions | Tax-Sale.info (Title Check, LLC) upcoming county auction catalogs - Oct 30, 2026 No Reserve Auction (46 counties); one registry row per county of the 2026 season (75) | 753 |
| MI | `mi_tax_sale_info_surplus` | Available | Tax-Sale.info surplus (unsold, first come first served) catalogs, 8 counties | 57 |
| SC | `sc_horry_tax_sale` | Auctions | Horry County Treasurer's newest dated delinquent real-estate list (Dec 1, 2026 sale); FLC Bid Amount = opening bid | 2,343 |
| CO | `co_saguache_tax_sale` | Auctions | Saguache County "2026 Tax Sale" ArcGIS layer (tax lien sale list) | 900 |
| MN | `mn_hubbard_tfl_otc` | Available | Hubbard County tax-forfeited land, `Sales_Status = 'OTC'` | 16 |
| MN | `mn_stpaul_hra_properties` | Available | Saint Paul HRA land held for resale, Marketing Status 5 (available on the open market) | 32 |

New adapter code: `harvesters/otc/adapters/tax_sale_info.py`, `harvesters/otc/adapters/paged_table.py`; ePropertyPlus
per-portal options (`offered=()` list presence, `excluded`, `county_field`, `status_field`; the `required_fields` change
is the same as the Cook County PR #181); tabular `document_sheet="*"`; runner kinds `tax_sale_info`, `paged_table`.

## Found, not implemented (and why)

- **Wright County MN tax-forfeited parcels** (38 'Open', auction starting price) - configured as
  `expansion.MN_WRIGHT_TAX_FORFEIT` but **held**: the Minnesota page's customer copy in `app.js`
  (`EXPANSION_LEDGER_COPY`, "No Minnesota auction source is tracked.") is owned by the front-end session, and the
  state-rules engine fails a tracked ledger whose copy denies it. Front-end follow-up: change that string, then add the
  config to `SOURCES["MN"]`, ledgers and permissions.
- **CivicSource (Louisiana adjudicated / tax sales: Orleans, Jefferson and other parishes)** - the site's TLS chain
  fails verification from the sandbox; not probed from a runner yet.
- **South Carolina county tax sale lists** (Greenville, Charleston, Richland, Lexington, Berkeley, Spartanburg ...):
  lists are newspaper ads or not posted as files; Spartanburg / Berkeley return 403 to a scripted read; Richland 503.
- **Washington County PA upset / judicial sale layers** (266 / 83): sale dates 2026-09-30 and 2026-06-24 - past.
- **St. Louis County MO "Post Third" layer** (1,091): last edited June 2025 - stale.
- **Mille Lacs MN** (8 'SALEABLE'): no sale type or price - availability not stated.
- **Davidson TN, Tulsa OK**: no list file published (newspaper / office only).
- **Milwaukee County foreclosed / county-owned layers**: mortgage foreclosures and ownership, not tax-sale offers.
- **Philadelphia (PA)** is in PR #184, **Cook County (IL)** in PR #181 - not duplicated here.

## Front-end wiring still needed (not done here: app.js is owned by another session)

- `COORD_SOURCE_COORDINATES` (app.js) / `harvesters/sources/coordinates.py`: the new land-bank portals publish their own
  points (`LAND_BANK_GIS`), the Tax-Sale.info catalogs their own lat/long; the two tables are pinned equal, so they were
  left unchanged - rows read "Origin not recorded" until both are updated.
- `AVAILABLE_PROGRAMS` (program names per source id) and the MN auctions copy above.
