# State launch playbook

This is the repeatable process for adding a state to the product. Run
`python3 scripts/state_launch_check.py --state XX` at each step. It reads the
repository only: it never makes a network call, never activates anything and
never changes a source decision. `--all` checks every production state, and
CI runs the same check in `tests/python/test_state_launch_check.py`.

A launch is **evidence first**. A state is never activated because a
government website exists, or because a vendor lists the state. Every step
below names the evidence it needs.

## Sources that are never used

Do not retry these sources, and do not add them to a new state, unless the
owner explicitly authorizes it later: **GovEase, LGBS, PBFCM, MVBA, CTSA**, and
every other vendor `harvesters/otc/gate.py` refuses by name. A vendor domain
is also refused as a purchase path (`laft_purchase_paths.untrusted_reason`).

## Steps

1. **Register the state** in `harvesters/governance/states.py`. It must stay
   NON-production until every activation requirement is met.
   Check: `registered`.
2. **Identify the source of record and verify it live.** Run the value-free
   capture (`scripts/capture_state_sources.py`, the `job=evidence` workflow)
   and record:
   - the reuse terms;
   - the identifier format;
   - the inventory semantics;
   - the amount semantics.

   Fixtures stay SYNTHETIC until a live read validates the parser. Check:
   `activated` lists every requirement that is still missing.
3. **Configure the adapter.** Use configuration only: the shared ArcGIS and
   tabular adapters, or `harvesters/otc/adapters/expansion.py`. Validate it
   against fixtures. Nothing reports COMPLETE or EMPTY until
   `parser_fixture_validated` is met.
4. **Add the registry rows** to `data/county_source_registry.csv`. Each source
   needs a publication decision:
   - APPROVED only with governance ok AND production-verified;
   - legal review is at most RESTRICTED;
   - blocked vendors are BLOCKED.

   Check: `registry_rows` fails while any of the state's sources has no
   decision.
5. **Build the page and the map assets.**
   - Run `scripts/build_state_basemap.py`, then `scripts/build_state_page.py`.
   - Add the state's row to `STATE_META` (app.js), `STATE_ASSETS` (explore.js)
     and `STATEWIDE_VIEW` (satellite-map.js).
   - Add the state to `county-centroids.json`.
   - Add the page to the `sw.js` SHELL, the mirror `FILES` list and the CI
     importmap injection.

   Checks: `page`, `page_current`, `app_state_meta`, `explore_assets`,
   `satellite_view`, `centroids`, `basemap`, `sw_shell`, `mirror_files`,
   `ci_importmap`.
6. **Wire monitoring.** Put the state into a change-detection step:
   `detect_property_changes.py --state XX` in `harvest-and-sync.yml`, or the
   `expansion` job matrix. Then saved-search alerts and watched-property
   alerts cover it. Check: `change_detection` (advisory).
7. **Acquisition evidence.** Add only rows read from the county's own page,
   with `review_state=verified` and an https evidence page. A missing
   acquisition path is an enrichment gap. It is never a reason to withhold
   published inventory. Check: `acquisition_evidence` (advisory).
8. **Activate.** Production runs follow the job's own schedule or a manual
   dispatch of that job. Measure coverage before and after, and record the
   decision in `states.EXPANSION_EVIDENCE`.

## What "READY" means

- **READY** means every REQUIRED item passes, so the state is wired end to end
  in the repository.
- **Advisory GAP lines** are customer-facing gaps to close next, such as no
  verified acquisition evidence. They never block a launch.
- READY says nothing about data quality, and nothing about whether a migration
  has been applied in production. Check those against production directly.
