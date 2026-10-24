# Permission decisions of 2026-10-24

The product owner read the replies to TAXACQ's permission requests and made
three decisions. This page records what changed, and where.

## 1. Florida DOR: written permission on file, statewide data covered

- **Evidence:** the email of 2026-10-12 from Tom Canter (Florida DOR, Property
  Tax Oversight). It is now on file as a redacted transcript with the original
  `.eml`'s SHA-256: `docs/agreements/fl-dor-pto-parcel-data-2026-10-12.md`.
  - "There are no restrictions placed on the data."
  - Display over aerial imagery in a commercial research application: "Yes".
  - No county-level permissions are required.
  - Both locations are refreshed annually, mid-August to early September.
- **Owner's decision:** the response also covers the "current year statewide
  parcel data" it names at geodata.floridagio.gov. In the code that dataset is
  `fl_fdor_cadastral` (the `Florida_Statewide_Cadastral` FeatureServer).
- **Records changed:**
  - `harvesters/governance/authorization.py`:
    - `fl_dor_pto_parcel_gis__provider__dor_pto` now points at the document
      (`written_permission=True`).
    - New `fl_fdor_cadastral__provider__dor_pto`, the same document.
  - `data/source_permissions.csv`: `fl_fdor_cadastral` parcel attributes and
    parcel centroid (fetch and enrich), plus display of the attributes, now
    rest on WRITTEN_PERMISSION. They previously had an expiring grandfathered
    allowance.
  - `harvesters/enrichment/geocode.py`: `FDOR_SOURCE.publication_status` is
    `APPROVED`.
  - `data/source_approvals.csv`: the evidence dates are now the emails' own,
    and the statewide dataset is mapped.
- **Not covered:**
  - Redistribution outside the app (exports, API, resale) was not asked about.
  - No statewide polygon is stored. Parcel outlines still come from the county
    PIN files.

## 2. Utah UGRC: the disclaimer text is recorded

- **Evidence:** the email of 2026-10-13 from Erik Neemann (UGRC):
  `docs/agreements/ugrc-parcel-licensing-2026-10-13.md`.
  - CC BY 4.0, and commercial use is allowed.
  - Required: credit UGRC, link the licence, note changes, and include the
    disclaimer and metadata.
- **Records changed:** the disclaimer text is now in
  `data/source_approvals.csv` (`disclaimer`), alongside the link to UGRC's
  licence page.
- **Basis:** still the published licence. Utah is still not an activated state.

## 3. RealAuction: minimal facts plus a deep link

- **Evidence:** RealAuction's reply of 2026-10-21 (ticket 914220): "we will not
  be providing any form of written permission to use automated means for
  scanning or crawling our auction sites."
- **Owner's decision:** keep the sale calendars (`fl_realauction` sale calendar
  and `tx_realauction`) as an **internal risk acceptance, never permission**.
  - Only the columns in `harvesters/governance/minimal_facts.py` are written:
    county, sale date, case or certificate number, parcel, situs address, the
    published opening or minimum bid and the published sale status.
  - Links go to the county's own auction and appraiser pages.
  - No assessed or market value, legal description or coordinates from the
    vendor.
- **Records changed:**
  - `data/source_permissions.csv` evidence becomes INTERNAL_RISK_ACCEPTANCE,
    citing the refusal. The record still expires 2027-04-12.
  - `authorization.py`: the Alachua and Volusia RealAuction records now read
    `request_status=DECLINED`, with a `declined` audit entry.
- **Code changed:**
  - `scripts/sync-harvest-to-supabase.ps1` no longer writes `assessed`. The
    value comes from the DOR statewide data instead.
  - `scripts/sync-texas-to-supabase.py` passes `tx_realauction` rows through
    `minimal_row()`.
- **Values already stored stay stored.** Removing them is a separate,
  owner-authorized data change.
- **Not decided here:** the closed-results feed (`fl_realauction` /
  `closed_results`, verified outcomes) is unchanged. It still rests on its
  grandfathered allowance.

## 4. Indian River and Volusia: link only

| County | Ledgers | Record owner's reply |
|---|---|---|
| Indian River | Auctions (RealAuction calendar and results) and Lands Available | Clerk, 2026-10-22: "we do not grant permission for any commercial activities" |
| Volusia | Lands Available only | Clerk, 2026-10-21: the user is "expressly prohibited from reproducing, publishing online ... or otherwise disseminating" its data |

Volusia's RealAuction sale calendar is a separate source and is unchanged.

### Records

`data/source_permissions.csv` adds county-level records for these sources:
- RESTRICTED (PROHIBITION_FOUND) on fetch, parse, store and display;
- LINK_ONLY on link.

### Enforcement before any request

- **`scripts/harvest_all_counties.ps1`:** its permission guard lists the denied
  counties (`source_permission_check.py --list-denied-counties`). It skips
  them, records them INCOMPLETE / NOT_PERMITTED and makes no request.
- **`scripts/harvest_laft_html.py`:** checks each county, the same way as the
  PDF harvester. Volusia's PDF is already skipped through its county record.
- **`scripts/auction_outcomes.py`:** skips a denied county's sale days.

### Website

`public/app.js` `LINK_ONLY_UNITS` lists these units, and a test pins the list to
the permission records:
- rows stored before the decision are never shown to a customer;
- admins see them labelled "Link only";
- the ledger names the county and links to the Clerk's own pages.

`sw.js` is now `tdw-shell-v137`.

### Rows already stored

Rows already stored (8 Indian River auctions, 2 Indian River and 10 Volusia
Lands Available rows on 2026-10-24) stay in the database, hidden. Closing or
deleting them is a separate, owner-authorized data change.
