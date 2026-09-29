# Alabama onboarding foundation (2026-09-29)

Status: **registered, not activated.** Alabama can be *represented* by the
national OTC/LAFT model; it cannot run, cannot be harvested and has no
production rows. Nothing in this document is live-verified unless the
"Verified" section says so.

## The researched concept

From the 50-state audit (2026-09-29), **search-index evidence only** - no
page or document was fetched from this repository, because the agency's
hosts are not reachable from the sandbox:

- Land on which taxes went unpaid is sold to the State of Alabama and
  held by the Alabama Department of Revenue, Property Tax Division (the
  State Land Commissioner).
- The Division was reported to publish per-county lists ("transcripts")
  of such land available for purchase, updated weekly, plus a search
  application.
- A buyer applies for a specific parcel and the State quotes a price;
  there is no auction opening bid.

In this framework: inventory type `STATE_HELD_TAX_LAND`, amount kind
`QUOTED_ON_APPLICATION`, publishing unit `STATE` (county named per row),
purchase path "application / instructions page" until a property-level
link is actually observed.

## Implemented

| Where | What |
|---|---|
| `harvesters/governance/states.py` | `AL` registered with `production=False`, publishing units STATE and COUNTY, production inventory type `STATE_HELD_TAX_LAND`, no activation requirement satisfied. `ACTIVATION_REQUIREMENTS` (ten items), `is_activated()`, `activation_blockers()`. `PRODUCTION_STATES` is derived from activation and stays `{FL, TX}`. |
| `harvesters/otc/gate.py` | New layer: a row whose state is not activated is refused (`state_activation`) before the row is read. |
| `harvesters/governance/county_source_registry.py` | `EXTENDED_COLUMNS` (+ `publishing_unit`, `publishing_unit_name`, `amount_kind`, `update_frequency`, `source_terminology`), `AMOUNT_KINDS`, validation (a STATE row names its agency; `amount_kind` in vocabulary), `runnable` requires an activated state, `to_db_rows(schema="018"|"020")`. |
| `data/county_source_registry.csv`, `scripts/build_county_source_registry.py` | Every FL/TX row unchanged (COUNTY, other new columns blank). One Alabama row: `AL / STATEWIDE / al_ador_state_land`, SEARCH_EVIDENCE_ONLY, TERMS_NOT_VERIFIED, access UNKNOWN, format UNKNOWN, **no URL**, amount kind QUOTED_ON_APPLICATION, update frequency "weekly (reported in search results; not verified)", the research wording kept in `source_terminology`. |
| `scripts/laft_lifecycle.py` | Refuses a registered-but-inactive state before any request (`--state AL` exits 2 with zero requests). |
| `harvesters/otc/adapters/alabama.py` | The adapter contract: `AlabamaSourceConfig` (publishing unit + name, field map, URLs, application page and its kind, amount kind, status vocabulary, source terminology, activation flags), `normalize_identifier` (as published; blank / digit-less / over 40 chars / multi-line rejected; **no reformatting**), `parse_rows` (fixture or future parser output -> `OtcRecord`s with provenance), `can_run` (false until the state is activated and the source is verified and enabled), `harvest` (refuses; no transport exists; no HTTP import). The 67 county names are the closed set a county may be. |
| `scripts/migrations/020_state_extensible_vocabulary.sql` | Written, **not applied**: widens the two `properties` check constraints, the registry's state and inventory-type checks, adds the five registry columns. Inserts nothing. |
| Tests | `tests/python/test_alabama_onboarding.py`; updates where a premise changed (AL is registered; a state must be activated to run). |

## Verified (directly established)

- Only what the repository itself establishes: the vocabulary, the gates,
  the registry shape, the adapter contract, and that an inactive state
  cannot run anywhere (gate, registry, lifecycle - all tested).
- The 67 Alabama county names.

## Not verified (needs live source access or a governance decision)

1. The source of record: which agency page and which document(s) publish
   the inventory. No URL is recorded anywhere in the repository.
2. Whether the source is a PDF transcript, an HTML list, a search
   application or several of these; its columns; its update cadence.
3. The identifier format (parcel number vs. account/receipt number, its
   shape). `normalize_identifier` therefore performs no normalization.
4. The status wording ("available", "sold", "redeemed", ...) and what each
   means for inventory lifecycle.
5. Whether any figure is published per parcel and what it is (the research
   says the price is quoted on application; a tax balance, if shown, is
   not a price).
6. Whether a property-specific online path exists (the research suggests
   an application, i.e. an application/instructions page, not a purchase
   link).
7. Terms of use for machine reading; governance status.

## Activation blockers (all ten must be satisfied, each in a reviewed commit)

`states.activation_blockers("AL")` returns exactly this list today:

1. `source_of_record_identified`
2. `live_source_verified`
3. `publishing_unit_coverage_established`
4. `identifier_format_established`
5. `inventory_semantics_established`
6. `purchase_path_established`
7. `amount_semantics_established`
8. `parser_fixture_validated`
9. `governance_approved`
10. `production_registry_authorized`

Plus, outside the code: migration 020 applied (the production constraints
cannot store `STATE_HELD_TAX_LAND` or `QUOTED_ON_APPLICATION` until then),
a workflow job for the source (none exists), and a schedule (none exists).

## What will NOT happen until then

No Alabama production row, harvest, schedule, workflow, registry
activation or live request. `can_run()` is false, `harvest()` raises,
`evaluate_source()` refuses at the state layer, `laft_lifecycle.py --state AL`
exits 2 before any query, and `OtcRecord.to_properties_row()` refuses the
inventory type and amount kind.
