# Alabama onboarding (2026-09-30)

Status: **implemented and gated; registered, not activated.** The source
adapter, the harvester script, the registry row and the lifecycle scoping
exist and are tested; Alabama cannot run, cannot be harvested and has no
production row. Nothing in this document is live-verified unless the
"Verified" section says so.

## The source

Alabama Department of Revenue, Property Tax Division (the State Land
Commissioner) - land on which taxes went unpaid is sold to the State and
held in State inventory; the Division publishes "a listing by county of
tax delinquent properties currently in State inventory" (county
"transcripts", "updated weekly"); a buyer applies for a specific parcel and
the State quotes a price.

**Evidence grade: SEARCH INDEX.** On 2026-09-30 a web search returned the
agency's own page titles, URLs, query strings and text snippets for the
pages below (`harvesters/otc/adapters/alabama.py` `ADOR_EVIDENCE`). No page
or document has been fetched from this repository: `revenue.alabama.gov`
is egress-blocked from the sandbox and from the assistant's fetch tool
alike. Search-index evidence is NOT production verification; the
implementation treats it exactly that way.

| Page (indexed title) | URL | What the indexed text establishes |
|---|---|---|
| Tax Delinquent Properties for Sale Search | `https://www.revenue.alabama.gov/property-tax/delinquent-search/` | The list / search page. Search "by County, CS Number, Parcel Number, or by the person's name in which the property was assessed when it sold to the State". Indexed URL carried `?ador-delinquent-county=68&_ador-delinquent-county-submit=submit`. |
| Tax Delinquent Properties for Sale Search Detail | `https://www.revenue.alabama.gov/property-tax/delinquent-search-detail/` | Per-property page; indexed URL carried `?ador-view-application=<8 digits, leading zero>`. |
| Tax Delinquent Property and Land Sales | `https://www.revenue.alabama.gov/property-tax/tax-delinquent-property-and-land-sales/` | "listing by county of tax delinquent properties currently in State inventory"; "How to Read County Transcript Instructions"; transcripts "updated weekly"; "Application for Purchase of Land Sold to State of Alabama for Delinquent Taxes". |
| FAQ: Where can I find a list of tax delinquent property? | `https://www.revenue.alabama.gov/faqs/where-can-i-find-a-list-of-tax-delinquent-property/` | "select the CS Number link to generate an online application"; "request a price quote ... by submitting an electronic application"; the quote "will be emailed"; "10 calendar days" to remit. |
| FAQ category: Land Sales | `https://www.revenue.alabama.gov/faq-categories/land-sales/` | Certificate held by the State < 3 years -> assignment of the certificate; > 3 years -> tax deed; neither gives clear title. |
| (2026-09-29 audit note) | none | "state ADOR transcripts, weekly, per-county PDF WWW_TRANS_NN, search app" - not corroborated by the 2026-09-30 search; no transcript URL known. |

## Semantics, as configured (`ADOR_SOURCE`)

- **Inventory type** `STATE_HELD_TAX_LAND` - the source's own words:
  "currently in State inventory", land "sold to the State".
- **Amount kind** `QUOTED_ON_APPLICATION` - established by the source's own
  FAQ text ("request a price quote ... by submitting an electronic
  application"). The record's amount is always `None`; no figure is ever
  turned into an opening bid or price. No amount column is mapped (the
  contract refuses one under this kind).
- **Identifier** the **CS Number**, as published, no reformatting (the one
  observed value starts with a zero, so leading zeros are kept). The parcel
  number is a separate field, also as published. `identifier_shape()`
  counts unobserved shapes; it never rewrites a value.
- **Publishing unit** STATE, county per row (or per query - the live flow
  reads the search page's own county `<select>` and queries one county at a
  time; no selector value lives in code, and the one value seen, 68, is
  deliberately not mapped to any county).
- **Owner name** = the name in which the property was assessed when it
  sold to the State, as published; provenance says exactly that (it is not
  asserted to be the current owner).
- **Purchase path**, two levels, kept distinct:
  - the row's own CS Number link (read from the page, resolved against the
    page URL, https, on the agency's host, never the list page) ->
    `purchase_url_kind = application_form` (a per-property application,
    not a checkout);
  - otherwise the agency's process page -> `purchase_instructions`.
  - The list page is never a purchase URL. Nothing is constructed from a CS
    number.
- **Status** through a candidate vocabulary (available / in State inventory
  / sold / redeemed / withdrawn); any other wording is UNKNOWN with the text
  preserved verbatim.
- **Dates**: `list_as_of` only from a row/list date the source states;
  `retrieved_at` is never written as a publication date.

## Implemented

| Where | What |
|---|---|
| `harvesters/otc/adapters/alabama.py` | `ADOR_EVIDENCE` (the ledger above), `requirement_evidence()` (per activation requirement: what exists, why it is unmet), `ADOR_SOURCE` (the configuration, NOT enabled), `parse_county_options()` (county selector from the page), `parse_search_results_html()` (header-mapped table reader; the CS Number cell's own link becomes the application link; unknown headers reported by label only), `parse_rows()` (deterministic rows -> `OtcRecord` with per-field provenance), `classify_outcome()` (COMPLETE / EMPTY / INCOMPLETE / FAILED - **nothing is COMPLETE or EMPTY until `parser_fixture_validated`**, so an unverified parser can never let the lifecycle close a row), `harvest()` (the live flow, refused by `can_run()` before the first request; transport injected; no HTTP import), `to_harvest_row()` (the lifecycle's row shape). |
| `scripts/harvest_alabama_state_land.py` | Fixture mode (`--fixture [County=]PATH`, no network - how the first saved live page gets validated) and live mode (refuses with exit 2 and zero requests unless `can_run()` allows). Writes `out/harvest_alabama.json`, its OWN status file `out/harvest_alabama_status.json` (county names repeat across states) and a counts-only report. Not wired into any workflow; no schedule. |
| `harvesters/otc/model.py` | `OtcRecord.owner_name` (optional; `to_properties_row()` adds the key only when set). |
| `harvesters/governance/states.py` | AL declares `lifecycle_inventory_type = STATE_HELD_TAX_LAND` with its basis; `lifecycle_inventory("AL")` still refuses (not activated; not storable before 020). Activation set unchanged: empty. |
| `scripts/laft_lifecycle.py` | `amount_of()` keeps `QUOTED_ON_APPLICATION` only once storable (NOT_PUBLISHED until then); `county_gates(state=...)` and the harvest-row reader are scoped to the run's state (an Alabama Escambia entry can no longer gate Florida's Escambia). FL rows carry no state key and read as FL, as before. |
| `data/county_source_registry.csv` | The one AL row now carries the search page as `canonical_url`, the process page as `purchase_url` (`purchase_instructions`), `HTTP_GET_HTML` / `PORTAL`, `last_checked 2026-09-30`, evidence "WEB SEARCH 2026-09-30 ..."; still SEARCH_EVIDENCE_ONLY / TERMS_NOT_VERIFIED, no harvester, not runnable. Generated from the adapter's constants so the two cannot drift. |
| `tests/python/test_alabama_source_adapter.py`, `tests/python/fixtures/alabama/` | 15 tests on SYNTHETIC fixtures (see the fixtures' README). |

## Verified (directly established)

- What the repository itself establishes: the configuration, the readers,
  parsing determinism, amount and purchase-path semantics, provenance,
  outcome classification, the gate (state -> enabled -> verified -> URL),
  the script's two modes, the registry row, the lifecycle scoping, and
  that the 67 county names are the closed county set.

## Not verified (needs a saved live page, or a governance decision)

1. The results page's HTML layout: whether it is a table, its header
   wording, any column beyond CS Number / Parcel Number / Name / County
   (no year sold, tax year, acreage, taxes due or description is claimed),
   and its pagination.
2. The county selector's option labels and values (Jefferson may be split
   into divisions; nothing is assumed).
3. The identifier format beyond one 8-digit observation; the parcel-number
   format.
4. The list's own status wording, if it has a status column at all.
5. Whether the results page states a list date.
6. The transcript documents (URL, format) and the "How to Read County
   Transcript Instructions".
7. Terms of use for machine reading; governance status.
8. Whether the detail page itself is the application, or links onward.

Each of these is isolated to one place: a field-map label, a vocabulary
entry, `EMPTY_MARKERS`, `observed_identifier_shapes`, or `document_url`.

## Activation blockers (all ten must be satisfied, each in a reviewed commit)

`states.activation_blockers("AL")` returns exactly this list today, and
`requirement_evidence()` says what exists against each:

1. `source_of_record_identified` - pages identified in the search index; not read directly
2. `live_source_verified` - no page fetched from this repository
3. `publishing_unit_coverage_established` - county selector seen; its values not read
4. `identifier_format_established` - one 8-digit observation is not a format
5. `inventory_semantics_established` - status wording of the list not read
6. `purchase_path_established` - the CS Number link described in a snippet; not read
7. `amount_semantics_established` - "price quote ... by application" in a snippet; not read
8. `parser_fixture_validated` - synthetic fixtures only
9. `governance_approved` - terms not reviewed
10. `production_registry_authorized` - no decision

Plus, outside the code: migration 020 applied (the production constraints
cannot store `STATE_HELD_TAX_LAND` or `QUOTED_ON_APPLICATION` until then),
a workflow job for the harvester (none exists), a schedule (none exists),
and a lifecycle decision for a STATE publishing unit (the registry expects
`(source_id, STATEWIDE)`; the harvester reports per county - to be
reconciled when the source is verified).

## The first live step, when it is authorized

Save the search page and one county's results page from a browser, run
`python3 scripts/harvest_alabama_state_land.py --fixture <County>=<saved.html>`,
compare the counters and the unmapped-column list against the page, then
replace the synthetic fixtures with the saved ones and set
`parser_fixture_validated` in a reviewed commit. Only then does
`classify_outcome()` report COMPLETE or EMPTY.
