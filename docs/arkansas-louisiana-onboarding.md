> **Update 2026-09-30 (state-expansion sprint):** Louisiana / East Baton Rouge is
> ACTIVATED on live evidence and the owner's dated-publication decision -
> see `docs/state-expansion.md`. Arkansas stays gated (the COSL list page now
> carries no table; purchases moved to the online auction). Migration 020 is
> applied. The rest of this document describes the search-index-era state.

# Arkansas and Louisiana onboarding (2026-09-30)

Status: **implemented and gated; registered, not activated.** Both
adapters, the generic harvester script, the registry rows and the state
registrations exist and are tested; neither state can run, be harvested
or have a production row. Nothing here is live-verified.

**Evidence grade for both: SEARCH INDEX.** On 2026-09-30 a web search
returned the agencies' own page / dataset titles, URLs, one query string,
descriptions and (for Louisiana) a column list. No page or file was
fetched from this repository - `cosl.org` and `data.brla.gov` are
egress-blocked from the sandbox and from the assistant's fetch tool. Every
fixture under `tests/python/fixtures/arkansas/` and `.../louisiana/` is
SYNTHETIC (each folder's README says exactly what was invented).

## Arkansas - Commissioner of State Lands, Post Auction Sales List

| Indexed page | URL | What the indexed text establishes |
|---|---|---|
| Post Auction Sales List | `https://cosl.org/Home/PostAuctionView` (indexed with `?county=DALLAS`) | The list, "organized by county"; one per-county query value observed. |
| FAQ | `https://cosl.org/Home/Faq` | Parcels "offered at the initial public auction but do not sell are made available for sale through the Post Auction Sales process thirty (30) days from the date of the initial public offering"; owner may redeem "ten (10) business days following the official post auction sale date"; since July 1 2021 buyers "bid on these parcels through the online auction available on auction.cosl.org". |
| Buyers Information | `https://cosl.org/Home/Buyers` | "the tax due amount represents the minimum bid required to purchase the parcel"; entries include legal descriptions with acreage, lien information and the delinquent tax owed. |
| COSL Online Auction | `https://auction.cosl.org/` | The bidding platform (not a per-parcel link; not recorded as a purchase URL). |
| Laws | `https://cosl.org/Home/Laws` | Title only. |

Semantics as configured (`harvesters/otc/adapters/arkansas.py` `COSL_SOURCE`):
inventory type `POST_SALE`; amount kind `OPENING_BID` (the tax due is the
minimum bid - carried only when the row's amount column parses, else
`NOT_PUBLISHED`); publishing unit STATE with the county per query;
identifier = the parcel number as published (no format observed, nothing
normalized); purchase path = the State's buyer-instructions page as
`purchase_instructions` (never the list page, never the auction home
page); status wording kept verbatim. `county_url()` builds the per-county
URL only in the ONE observed shape (`county=<NAME>` upper case) and only
for single-word counties - how the site spells "Hot Spring", "Little
River", "St. Francis" or "Van Buren" is not observed, so those four are
reported unresolved, never guessed.

## Louisiana - East Baton Rouge Parish, adjudicated property

| Indexed page | URL | What the indexed text establishes |
|---|---|---|
| Adjudicated Property (dataset) | `https://data.brla.gov/Housing-and-Development/Adjudicated-Property/a4h4-zi7e` | "a list of properties that have been adjudicated due to delinquent property taxes"; "if no one buys the property at the tax sale, the property will then be adjudicated to the Parish of East Baton Rouge in compliance with the laws of the State of Louisiana". |
| Dataset columns | same, `/data` | TAX YEAR, PROPERTY NUMBER, TAXPAYER NAME, TAXPAYER ADDRESS, TAXPAYER CITY STATE ZIP, PHYSICAL ADDRESS, SUBDIVISION NAME, BLOCK/SQUARE NO, LOT NO, WARD, LEGAL DESCRIPTION, FAIR MARKET VALUE, TOTAL ASSESSED VALUE, COUNCIL DISTRICT, ZIP CODE, GEOLOCATION. |
| CSV download | `https://data.brla.gov/api/views/a4h4-zi7e/rows.csv?accessType=DOWNLOAD` | The machine-readable file (JSON / XML / RDF also offered). |
| Adjudicated Property Map | `https://data.brla.gov/Housing-and-Development/Adjudicated-Property-Map/c7mi-6t2x` | Interactive map of the same parcels. |
| EBRGIS Adjudicated Property | `https://gisdata.brla.gov/datasets/adjudicated-property` | Parcel polygons, "last updated on September 07, 2026". |

Semantics as configured (`harvesters/otc/adapters/louisiana.py` `EBR_SOURCE`):
inventory type `ADJUDICATED_PROPERTY`; publishing unit PARISH (East Baton
Rouge); identity and parcel = PROPERTY NUMBER as published; address, legal
description, taxpayer name (the name on the roll for TAX YEAR - never
asserted to be the current owner), assessed and market value (tax-roll
figures, never a price), tax year, and coordinates when GEOLOCATION parses
in one of two deterministic shapes (WKT `POINT (lon lat)` or `(lat, lon)`);
amount always `NOT_PUBLISHED` (the dataset has no price column); no
purchase URL (the audit reports a vendor purchase process - unverified,
not implemented). Header spelling is matched after normalization; a CSV
missing any required column is `INCOMPLETE / PARSE_FORMAT_CHANGE` and
nothing is read.

## Implemented

| Where | What |
|---|---|
| `harvesters/governance/states.py` | `AR` (STATE, COUNTY; `POST_SALE`) and `LA` (PARISH, MUNICIPALITY; `ADJUDICATED_PROPERTY`) registered with `production=False`, no activation requirement satisfied, a declared lifecycle inventory type with its basis. `PRODUCTION_STATES` stays `{FL, TX}`. |
| `harvesters/otc/adapters/common.py` | The shared gate (`can_run`: state activation first, then enabled / verified flags, then a URL) and the shared outcome rule (`classify`: nothing COMPLETE or EMPTY until `parser_fixture_validated`). |
| `harvesters/otc/adapters/arkansas.py` | `COSL_EVIDENCE`, `requirement_evidence()`, `COSL_SOURCE` (not enabled), `county_url()`, `parse_list_html()` (header-mapped table via the generic `TabularListAdapter` with candidate labels, identifier gate), `classify_outcome()`, gated `harvest()`. |
| `harvesters/otc/adapters/louisiana.py` | `EBR_EVIDENCE`, `requirement_evidence()`, `EBR_SOURCE` (not enabled), `parse_csv()`, `parse_geolocation()`, `classify_outcome()`, gated `harvest()` (one download). |
| `harvesters/otc/model.py` | `OtcRecord.assessed` / `market` / `tax_year` / `latitude` / `longitude` (optional, validated) and `to_harvest_row()`. |
| `harvesters/governance/county_source_registry.py`, migration 020 | `MachineFormat.CSV` (020, applied 2026-09-30, widens 018's check). |
| `data/county_source_registry.csv` | `AR / STATEWIDE / ar_cosl_post_auction` and `LA / East Baton Rouge / la_ebr_adjudicated`, both SEARCH_EVIDENCE_ONLY / TERMS_NOT_VERIFIED, no harvester, not runnable; generated from the adapters' constants. |
| `scripts/harvest_state_inventory.py` | `--state AR|LA`, `--fixture` mode (no network) and a live mode that exits 2 with zero requests; own status file per state; counts-only report; wired into no workflow. |
| `tests/python/test_states_ar_la.py` | Registration, evidence, configurations, parsing, semantics, provenance, outcomes, gated flows, script, registry, common rules. |

## Not verified

Arkansas: the list's column headers and layout; the parcel-number format;
the county selector's values (multi-word counties); any per-parcel auction
link; the "daily" cadence and the "negotiated after 2 years" rule the
audit reported; terms of use. Louisiana: the CSV's exact header spelling;
the GEOLOCATION format; whether the dataset is the current inventory or a
yearly snapshot; the purchase process; the other 63 parishes; terms of use.

## Activation blockers

`states.activation_blockers("AR")` / `("LA")` return all ten requirements;
each adapter's `requirement_evidence()` says what exists against each.
Plus migration 020 (unapplied: `POST_SALE`, `ADJUDICATED_PROPERTY` and the
registry's `CSV` / state / unit vocabulary), a workflow job and a schedule
(none exist), and a lifecycle decision for a STATE-level publisher (the
registry expects `(source_id, STATEWIDE)`; the Arkansas harvester reports
per county).

## The first live step, when authorized

Save one county's Post Auction Sales List page (Arkansas) and the CSV
download (Louisiana) from a browser, run
`scripts/harvest_state_inventory.py --state AR --fixture <County>=<saved.html>`
/ `--state LA --fixture <saved.csv>`, compare the counters and the
unmapped-column list against the file, replace the synthetic fixtures with
the saved ones and set `parser_fixture_validated` in a reviewed commit.
