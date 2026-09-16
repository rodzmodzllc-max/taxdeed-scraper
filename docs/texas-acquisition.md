# Texas acquisition

**Status:** Phase 40, 2026-09-16 (supersedes the Phase 39 revision). Companion to `docs/texas-data-map.md` (Phase 37/38's source map) and `docs/acquisition-status.md`.

## 1. Existing implementations: inspected, verified, preserved

Section 9/10 of Phase 39's brief required inspecting rather than assuming. All three were re-read directly this phase.

| Function | Claimed state | Verified state, 2026-09-16 |
|---|---|---|
| `harvest_lgbs()` | real implementation | **Confirmed real.** Live API re-verified: envelope unchanged, all 29 fields present, `count` = 6,309 rows for `area=TX`. Not modified. |
| `harvest_pbfcm()` | stub | **Confirmed stub** (raises `NotImplementedError`). Source is `BLOCKED` on an affirmative terms prohibition, independent of the stub. Not modified. |
| `harvest_govease()` | stub | **Confirmed stub** (raises `NotImplementedError`, line 973). Not modified — Section 23's "do not implement a speculative scraper simply to eliminate the stub." |
| `scripts/enrich_property_details_tx.py` | real Harris/Tarrant CAD fetchers | **Confirmed real, and both layers verified live** (see §2). Not modified. |

`SOURCES` in `texas_harvester.py` still maps the same four vendors, and the ingestion gate still runs before every `harvest_*()` call. Nothing about the Texas pipeline's behavior changed this phase.

## 2. CAD enrichment — layers verified live for the first time

Both `_fetch_hcad()` and `_fetch_tad()` carried a comment saying "NOT execution-tested from this project's own sandbox." That is no longer true of the endpoints themselves:

- **HCAD** (`gis.hctx.net/.../HCAD/Parcels/MapServer/0`): layer "HCAD Parcels", Feature Layer. A real single-parcel query for `HCAD_NUM='1011020000003'` returned attributes matching the 2026-09-08 sample **exactly** — `total_market_val` 199689.0, `land_value` 61382.0, `bld_value` 138307.0, `Acreage` null, `land_sqft` 7697.0. The existing query mechanics are correct.
- **TAD** (`mapit.tarrantcounty.com/.../Tax/TCProperty/MapServer/0`): layer "Tarrant County Parcel". All 16 expected fields confirmed present, including `EXEMPTION_` and `LIVING_ARE`, both confirmed absent from HCAD's layer.

These are contract checks, not acquisition runs. The pre-existing caveats stand unchanged: HCAD has no exemption flag and no building square footage; TAD's `PARCELTYPE`/`DESCR`/`EXEMPTION_` *values* remain unsampled, so those mappings are still best-guess.

`ArcGisAdapter` now reaches both layers through the acquisition contract, reusing `hcad_attributes_to_generic()` / `tad_attributes_to_generic()` / `normalize_cad_response()` rather than reimplementing them. Adding Bexar — a real endpoint found in earlier research, classification fields never sampled — is a `CadLayerConfig` entry and one sampling query.

## 3. Texas heterogeneity, stated numerically

254 counties, 277 county-source config rows (Phase 40 expanded this from 257):

| Mechanism | Rows | Adapter implemented |
|---|---|---|
| `NONE` — no acquisition mechanism identified | 158 | — |
| `HTML_PUBLIC_SEARCH` — `tx_realauction` | 24 | No (working harvester exists) |
| `JSON_API` — `tx_lgbs` | **95** | **Yes** |

Texas has no statewide equivalent to Florida's FDOR cadastral layer. Appraisal is administered by 254 independent CADs, each with its own site and data-access mechanics. That is the structural reason Florida is covered by one statewide layer while Texas depends on a multi-county vendor API plus per-CAD integrations.

## 4. The LGBS footprint, measured (Phase 40)

Phase 39 flagged that the coverage matrix named `tx_lgbs` for only 8 counties while the live API returned 6,309 rows. Phase 40 measured the actual footprint.

**95 Texas counties**, not 8. Full detail in `claude/phase-40-lgbs-roster.md` and `data/tx_lgbs_observed_county_roster.csv`.

| Query | Count |
|---|---|
| `?area=TX` | 6,309 |
| `?state=TX` | 4,205 |
| `?state=PA` (Philadelphia) | 2,104 |

4,205 + 2,104 = 6,309 exactly, which both validates the measurement and proves Philadelphia is the only non-Texas county in the feed.

**`area=TX` is 33.4% Pennsylvania data.** Phase 39 preserved the rule that the harvester filters on each row's own `state` field; this phase quantified it. Trusting the parameter would import 2,104 Philadelphia properties into the Texas ledger.

Attribution: 4,197 of 4,205 records assigned to named counties (**99.81%**), with an explicitly recorded 8-record residual rather than a distributed or hidden one.

Configured Texas coverage moved from 8 counties to 95 with no new scraper — the API is statewide, so the roster is configuration. `AcquisitionMechanism.NONE` fell from 225 county-source rows to 158.

The roster lives in its own artifact and does **not** rewrite `data/tx_county_coverage_matrix.csv`: that matrix records what research established, with its own evidence trail, while the roster records what a source actually returned on a date. A test asserts the matrix is unmodified.

## 5. Blocked sources — unchanged, and testing does not unlock them

| Source | Status | Why |
|---|---|---|
| `tx_pbfcm` | `BLOCKED` | Affirmative terms prohibition on reproduction/redistribution |
| `tx_mvba` | `BLOCKED` | Affirmative terms prohibition |
| `tx_ctsa` | `BLOCKED` | Paywall + anti-competitive-use clause |
| `tx_govease` | `BLOCKED` | Blanket `Disallow: /`, no locatable terms |
| `tx_hctax` | `LEGAL_REVIEW_REQUIRED` | No prohibition found, no permission found |

The acquisition policy gate refuses the four `BLOCKED` sources for **both** purposes, including `INTERNAL_TECHNICAL_TESTING`. Section 17's testing allowance covers unresolved *commercial* questions, never a found prohibition — a test asserts this for every `BLOCKED`/`DISABLED`/`TERMS_CHANGED` source in the registry.

`tx_hctax` is different: no prohibition has been found, so internal technical testing is permitted, and the HCAD adapter demonstrably acquires and normalizes a real record under that purpose. Its production promotion remains denied. Both facts hold at once, which is the model working as designed.

## 6. What a production Texas acquisition run would need

1. Outbound access — Texas harvesting currently runs on `workflow_dispatch` only, not a schedule, so a Texas row's freshness already depends on someone triggering it manually. That pre-existing gap is unchanged.
2. Nothing else for `tx_lgbs`: it is `APPROVED`, has no authorization record, passes the promotion gate, and the adapter is built and tested.
3. For everything else: either an authorization resolution (`tx_hctax`) or a source that does not currently exist (the 158 `NONE` counties).
