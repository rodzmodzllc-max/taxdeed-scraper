# MRV - Marc Research Value (2026-11-25)

Owner, 2026-11-25: replace the case number on the property card with an **MRV** - one median value built from the
references on file - and "present a median price, not the exact Zestimates": the sources are references, named in an
informational bubble, never shown as individual figures.

## What the MRV is

The **median** of the references on file for a property (app.js `mrvOf`):

| Reference | Where it comes from | Status |
|---|---|---|
| County value | the row's own `market`, else `assessed` (the card's county value) | live |
| TAXACQ comparables | properties on file in the same county with the same land use that carry a county value and a size: median value per acre x this property's acreage; used only with >= 5 comparables (`MRV_COMPS_MIN`), the property itself never counts | live |
| RentCast | RentCast AVM (`api.rentcast.io/v1/avm/value`), stored in `property_value_estimates` | needs the `RENTCAST_API_KEY` secret and migration 045 |
| Zillow | Zillow's official Zestimate API (Bridge) | not built: waits for the owner's API approval and its display terms |

- Shown only when at least one reference **besides** the county value exists (the county value alone is already on the card).
- The (i) bubble names the references and their dates and says individual estimates are not shown. No individual
  figure is ever displayed. Not an appraisal, a price or an offer.
- Certificates get no MRV (a lien is not the property).
- Zillow's and Realtor.com's websites are never copied: their terms forbid it, and this project never scrapes against terms.

## Where it shows

- Merged Available cards (`.xt-mrv`), Merged Auctions placards (plain text `.xpt-mrv` - the face is a button), Classic
  cards (`.card-mrv`), the full record and the Guided view (`.detail-mrv`).
- The case number is no longer on any card face; the property page keeps it.

## RentCast lookups

`scripts/fetch_rentcast_estimates.py`, workflow `mrv-estimates.yml` (daily 13:20 UTC, own concurrency group):

- Nothing without `RENTCAST_API_KEY` (one line, exit 0), the permission records (`rentcast_avm` fetch / store), or
  migration 045.
- Budget: `RENTCAST_MONTHLY_LIMIT` lookups a calendar month (default 45, under the free plan's 50), counted from the
  estimates stored this month; `RENTCAST_RUN_LIMIT` caps one run.
- Order: active Available rows, then auctions with a sale date ahead. Never certificates.
- Query: the street address when it has a house number and a ZIP code, else the row's own coordinates (most lists
  publish no ZIP). A row with neither is skipped.
- An estimate whose point is more than 1.5 km from the row's point is refused (a different house).
- A stored estimate younger than `RENTCAST_REFRESH_DAYS` (90) is not looked up again.
- Logs: counts only.

## Permissions

`data/source_permissions.csv`:

- `rentcast_avm` (US): fetch / store / display, OWNER_PERMISSION_REQUIRED on INTERNAL_RISK_ACCEPTANCE (owner decision
  2026-11-25), expiring 2027-04-12. RentCast's API terms are still to be read and recorded.
- `zillow_zestimate` (US): UNKNOWN / NO_EVIDENCE - every operation denied until the API is approved.

## Production steps (owner)

1. Apply migration `045_property_value_estimates.sql` (and `044_product_events_link_opened.sql`).
2. Create a RentCast account, then add its key as the `RENTCAST_API_KEY` repository secret.
3. Optional: `RENTCAST_MONTHLY_LIMIT` repository variable for a paid plan.
