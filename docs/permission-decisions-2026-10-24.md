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

## The owner's position (2026-10-24, revised the same day)

The owner holds that these listings are public records: TAXACQ sells a service that organizes the acquisition path and
links to the county and its vendor sites, sending them traffic, and does not sell the data. Some counties referred the
owner to their public-records request process. **No working harvester is switched off.** Records whose owner refused reuse
keep being collected and are not shown to customers until legal review.

## 3. RealAuction: collection unchanged, recorded as a risk acceptance

- **Evidence:** RealAuction's reply of 2026-10-21 (ticket 914220): "we will not be providing any form of written
  permission to use automated means for scanning or crawling our auction sites."
- **Records:** the `fl_realauction` sale-calendar and `tx_realauction` evidence is now INTERNAL_RISK_ACCEPTANCE (the
  owner's decision, citing the refusal and the owner's position) - never permission. It still expires 2027-04-12.
  `authorization.py`: the Alachua and Volusia RealAuction records read `request_status=DECLINED` with a `declined` audit
  entry.
- **Code:** unchanged. The harvesters and syncs collect the same fields as before; customer display is as today.
- The closed-results feed is unchanged.

## 4. Indian River and Volusia: collected, not shown to customers until legal review

| County | Ledgers | Record owner's reply |
|---|---|---|
| Indian River | Auctions (RealAuction calendar and results) and Lands Available | Clerk, 2026-10-22: "we do not grant permission for any commercial activities" |
| Volusia | Lands Available only | Clerk, 2026-10-21: the user is "expressly prohibited from reproducing, publishing online ... or otherwise disseminating" its data |

Volusia's RealAuction sale calendar is a separate source and is unchanged.

- **Records** (`data/source_permissions.csv`, county level): fetch / parse / store are LEGAL_REVIEW_REQUIRED on an
  INTERNAL_RISK_ACCEPTANCE (collection continues, expires 2027-04-12); display is RESTRICTED (PROHIBITION_FOUND, quoting
  the Clerk); link is LINK_ONLY.
- **Harvesters:** every one keeps running. The per-county checks added here
  (`source_permission_check.py --list-denied-counties` in the PowerShell guard, the county check in `harvest_laft_html.py`
  and `auction_outcomes.py`) skip a county only if its fetch is ever denied - none is today.
- **Website (not in this PR):** hiding these rows from customers, labelling them "Held for legal review" for admins
  and linking to the Clerk's pages is left to the session working on the UI. The records it should read are display
  RESTRICTED and link LINK_ONLY for `fl_realauction` / `fl_laft_html` in `FL:Indian River` and `fl_laft_pdfs` in
  `FL:Volusia`; each LINK_ONLY record's reason names the Clerk's https pages. Until that ships, the stored rows are
  still visible as today (migration 031, once applied, would enforce `display` server-side).
- **To show them later:** after legal review, change the county's `display` record (and drop the website's hiding entry).
