# TAXACQ source policy: what the audit found and the highest-value plan (2026-10-22)

Principle (owner, 2026-10-22): TAXACQ helps customers find opportunities and go
straight to the official source. A missing bespoke permission is not, by itself,
a reason to hide facts from an independently lawful source. Public-record status
or a link-out strategy is not a licence to scrape a vendor's site. Nobody
bypasses authentication, CAPTCHA or access controls.

This was a read-only audit. Nothing in production, the source registry or the
permission records was changed. Supporting files, all in this folder:

| File | What it is |
|---|---|
| `source-matrix.csv` / `source-matrix.md` | 88 sources × 21 columns, with seven decisions per source. Each decision is marked VERIFIED / PARTIAL / UNVERIFIED and cites its evidence |
| `gates.md` | Every place the code withholds, hides or refuses a record because of review or permission status (31 gates, with file:line references) |
| `parcel-geometry.md` / `parcel-geometry.csv` | The official parcel-geometry options for each supported state and county, with their terms, match quality, effort and the number of records each covers |

Caveat: no state public-records statute was read, so nothing below relies on
public-records law, and Florida law is not applied to any other state.

## 1. What is true today

- **Approved accounts already see the 42,797 records awaiting review.** The
  deployed `config.js` (checked on taxacq.com, 2026-10-22) sets
  `publicationMode: "preview"`, so they appear labelled "Source review".
  Customers would lose them on three triggers:
  - switching to enforced mode;
  - turning paid billing on (migration 027);
  - applying migration 031.

  Two exceptions already hold today:
  - the Detroit customer subset still hides about half of the Detroit
    structure lots and all 12 program rows;
  - county pages hide unreviewed sources' names and links.
- **The riskiest sources are shown; the safest are flagged.** Customers see
  2,798 rows with no `publication_status` at all: RealAuction (1,065), LienHub
  (1,611), Texas RealAuction (103) and LGBS auctions (19). In the matrix these
  are group D (needs counsel). The government and land-bank rows, which have no
  recorded restriction, carry "awaiting review".
- **NULL means different things in different places.** The list treats a NULL
  `publication_status` as visible. The acquisition gate, the paid-plan scope
  (migration 027) and the imagery priority treat it as not published.
- **Linking is permitted in practice, but no record says so.** No code path
  checks the `link` operation; the site links freely. Yet only 6 of the 230
  permission records name `link`. The records need to say that a link to an
  official page needs no per-source permission.
- **Some collection practices conflict with "never bypass access controls"**
  (matrix group B3/D):
  - the ScraperAPI proxy fallback for Florida county lists;
  - the Volusia disclaimer bypass;
  - the scripted Orange click-through;
  - the private Osceola API;
  - LienHub retries after the site began answering 403.

## 2. Matrix totals (active rows)

| Group | Meaning | Sources | Rows |
|---|---|---|---|
| A | Facts and an official link now; licence or written permission on file | 8 | 10,472 |
| B | Facts and link once one named item is recorded | 36 | 44,049 |
| C | Link only | 27 | 0 |
| D | Needs counsel (and usually vendor approval) | 12 | 3,272 |
| E | Stays blocked (PBFCM, MVBA, CTSA, GovEase, Street View) | 5 | 0 |

## 3. Source-registry changes: seven decisions per source

Add a reviewed decision file, `data/source_decisions.csv`: one row per source,
with the seven decisions as separate columns. Each decision has a value, a
status (VERIFIED / PARTIAL / UNVERIFIED), a basis, evidence, and a date.

1. `official_link`: direct link to the source's own page permitted.
2. `public_facts`: which fields are displayable, and from which identified source.
3. `bulk_download`: permitted or not.
4. `automated_collection`: permitted or not.
5. `media_geometry`: images, descriptions, maps and geometry, each separately.
6. `commercial_display_retention`: permitted or not.
7. `restriction`: an explicit restriction, an open issue, or a counsel question.

The file would be validated by `harvesters/governance/source_decisions.py`, in
the same style as `state_rules.py`, and the matrix CSV seeds it. Rules:

- Absence of a decision is not approval.
- An explicit restriction always wins.
- `official_link` defaults to permitted for a government page, never for a
  page behind a login.
- `public_facts` must name its source.

`permissions.authorize()` stays the per-operation gate for collection. The
decision file feeds the `display` and `link` records through a dated owner
policy record (status `OWNER_POLICY`, with basis, scope and expiry). Every
grant is written down; none is inferred.

## 4. The highest-value plan (in order)

| # | Change | Rows affected | Needs |
|---|---|---|---|
| 1 | **Owner policy record:** a link to an official page needs no per-source permission. Recorded as `OWNER_POLICY` link records | every source | Your sign-off (data file only) |
| 2 | **Owner decisions for the 10 government / land-bank Available sources** (matrix B2): public facts and a link, from the publisher's own list, with attribution. Two exceptions need your call: St. Louis (the dataset says "restricted public"; clarify with SLDC first or accept), and the Horry and Fayette "All rights reserved" footers | 42,797 | Your decision, per source or as a category |
| 3 | **Code PR: one display rule.** `isPublicRecordDisplayable(p)`: not BLOCKED or RESTRICTED, an https official link on file, and a recorded `public_facts` decision. It replaces the review-status check at `app.js` `isPublishable` (feeding list, counts, map, search, export, dashboard), the state-picker probe and the county-page source filters. NULL `publication_status` gets one meaning everywhere. Freshness, missing-data labels and acquisition-path checks stay. About 25 tests are updated with it | 42,797 now (stable under enforced or paid mode) | Review and merge |
| 4 | **Vendor sources go to minimal facts plus deep link** (RealAuction, LienHub, LGBS, Texas RealAuction: matrix D). Keep county, sale date, case or certificate number, parcel and the published opening bid, with a link to the county's sale page. Stop the practices listed in section 1. Counsel answers the matrix's D questions (does a county EULA bind a non-bidder; are clerk sale facts independent public records) | 3,272 | Counsel, then a code PR |
| 5 | **Parcel outlines** (see `parcel-geometry.md`). Stage 1, terms already quoted: Florida DOR for all ledgers (dry run pending), East Baton Rouge tax parcels (public domain, about 10,157 exact matches; needs a Socrata geometry reader) and Colorado statewide (141; commercial use with attribution, resale forbidden). Stage 2, needs your decision: Detroit "Parcels (Current)" (30,602, no licence published), St. Louis Assessor (9,778, no licence), and York and Albany tax-sale polygons (1,106; the lists are approved, the outlines are not). Neighbour lines (yellow) come only from whole-county or statewide layers | up to ~41,000 | Stage 1: review and approval to load. Stage 2: your decision |
| 6 | **Interim acceptances become dated owner policy records** for the six owner-approved counties (matrix B1: Eaton, Lenawee, York, Albany, Morgan, Green). They expire 2027-04-12. Owner names (Albany, York, Morgan) stay a counsel item | 1,147 | Your decision |

Not proposed: lifting any explicit restriction (group E, BLOCKED, RESTRICTED,
the Texas hard blocks); any login or captcha workaround; inventing an auction
URL, opening bid, outcome or permission status.

## 5. What happens next

- Items 1, 2 and 6 are decisions only you can make. Each one becomes a dated
  record in the repository.
- Item 3 is the code PR. It is reviewable on its own and changes no production
  data.
- Items 4 and 5 follow your decisions and counsel's answers.
- Nothing is loaded, enabled, migrated or deployed without your explicit
  approval.
