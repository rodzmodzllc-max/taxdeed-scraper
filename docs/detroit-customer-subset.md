# Detroit customer-facing subset (2026-10-03)

The Detroit Land Bank Authority (DLBA) sources put more than 30,000
AVAILABLE rows in one county, Wayne MI. This document describes a
customer-facing **view** of that inventory. It deletes, closes, rejects or
reclassifies nothing, and it is not a publication decision.

```
SOURCE COLLECTION -> FULL ADMIN INVENTORY -> VERIFIED STRUCTURE FILTER
    -> DETERMINISTIC ~50% CUSTOMER SUBSET -> PUBLICATION GATE -> CUSTOMER
```

## Scope

Only `mi_detroit_landbank_lots` and `mi_detroit_landbank_programs` are in
scope. Every other source is outside this rule and is never capped. That
includes:

- Oceana MI, Horry SC and Georgetown SC;
- Florida, Louisiana and Texas;
- every other Michigan county;
- SC, WY, CO and WI.

## What the source publishes about structures

The only structure indicator in the DLBA data is its own **"DLBA Inventory
Status"** field (`inventory_status_socrata`, stored verbatim as
`inventory_status_raw`). The DLBA_Owned_Properties layer has no building,
improvement or structure-type field. Its fields are address, parcel,
inventory status, neighborhood, council district, street parts, block range
and coordinates.

| Status (source wording) | Read? | Structure? |
|---|---|---|
| Neighborhood Lot For Sale | yes | no: a vacant lot. The DLBA Vacant Land Policy defines Neighborhood, Side and Oversize lots as "vacant residential property without a structure" |
| Side Lot For Sale | yes | no (vacant lot) |
| Oversized Lot For Sale | yes | no (vacant lot) |
| Marketed Lot For Sale | yes | no (a lot) |
| **Marketed Structure For Sale** | **yes, from 2026-10-03** (owner decision) | **yes: the source's own statement of an offered structure** |
| DLBA Owned Lot / DLBA Owned Structure | no | ownership, not an offer |

The programs layer (DLBA_For_Sale: Own It Now / Renovation Programs /
Economic Development) has **no structure field**, so none of its records is
structure-qualified. A structure is never inferred from:

- a program name, an address or an owner;
- size, value or zoning;
- imagery or any model.

**Production on 2026-10-03.** All 30,661 lot records carry one of the four
"... Lot For Sale" statuses: Neighborhood 27,161, Side 2,358, Marketed Lot
1,000, Oversized 142. The 12 program records are Renovation Programs 6, Own It
Now 5 and Economic Development 1.

So **0 records are structure-qualified today**, and the customer subset is 0.
"Marketed Structure For Sale" rows first arrive with the first scheduled MI
expansion run after this change is merged. How many there are is not known
from here: the ArcGIS layer is egress-blocked from the sandbox, and one
appeared in a 200-row sample of the 56,896-feature layer.

## The selection rule

For a structure-qualified record (source `mi_detroit_landbank_lots`, status
"Marketed Structure For Sale"):

```
key  = "<source_id>|<parcel number as published, trimmed>"
hash = 32-bit FNV-1a over the UTF-8 bytes of key
in the customer subset  <=>  hash % 100 < 50
```

- **Same answer for the same parcel.** It does not depend on database order,
  time, randomness or other rows. It changes only if the source's parcel
  number or status changes.
- **Roughly half.** On a synthetic population of the real parcel shapes,
  about 50% is selected (the test allows 47–53%).
- **One rule, two implementations, one pinned answer set:**
  `harvesters/otc/detroit_subset.py` (Python) and `detroitSubsetStatus()` in
  `public/app.js` (JS). `tests/python/fixtures/detroit_subset_cases.json`
  holds 50 shared vectors; the Python and Playwright suites both check them.

## Who sees what

| Viewer | Detroit rows shown | Label |
|---|---|---|
| Admin | **every collected row** | rows outside the subset carry "Not included in current Detroit customer subset", with the reason (no structure in the source's status / outside the ~50% selection); the property page shows the structure evidence; the ledger and the admin Dashboard show collected / structure-qualified / in-subset counts |
| Preview (`config.js` `publicationMode: "preview"`) | the customer subset only | "Source review: Unreviewed · not customer-published" plus the Detroit ledger note |
| Customer (default enforced mode) | the customer subset **only once the source is APPROVED** | today: none. The subset rows count as "withheld"; rows outside the subset are not customer inventory and are not counted |

The publication gate is unchanged: both Detroit sources stay UNREVIEWED.

## AVAILABLE as the default inventory

With no ledger in the URL, the List now opens on **Available** whenever the
state has Available rows the viewer can see (FL, LA, TX, and SC / MI for
admins or preview). A state without any keeps Auctions. A routed `#/auctions`
or `#/certificates` always wins.

## No migration, no registry change

- The rule is a frontend visibility stage beside the existing publication
  gate.
- The collection change is a `where` clause in
  `harvesters/otc/adapters/expansion.py`.
- The registry row for `mi_detroit_landbank_lots` is byte-identical. Its
  notes text still says "only the four lot statuses", left unchanged on
  purpose.

## Known open question for the publication review

A "Marketed Structure For Sale" property may also appear in the DLBA's
Auction program, which is excluded from AVAILABLE. The harvester does not
cross-check the two layers. An admin reviewing the source for publication
should confirm how the DLBA sells marketed structures.
