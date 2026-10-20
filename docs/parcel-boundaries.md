# Parcel boundaries from the approved parcel-geometry sources (2026-10-20)

This change puts in place the boundary use that two written approvals cover:
1. Florida DOR Property Tax Oversight;
2. Utah UGRC (CC BY 4.0).

The product owner has confirmed receipt of both. It is repository-only:
- migration 034 is written and **NOT applied**;
- no production row was written;
- no workflow was dispatched and no schedule or secret was changed;
- no source owner was contacted.

## Which source, which dataset

| | Florida DOR | Utah UGRC |
|---|---|---|
| Source id | `fl_dor_pto_parcel_gis` | `ut_ugrc_lir_saltlake` |
| Covered and mapped | County GIS parcel files on DOR PTO's Request Assessment Roll GIS Data page (permission dataset key `county_parcel_geometry`) | `Parcels_SaltLake_LIR` (services1.arcgis.com/99lidPhWCzftIe9K, layer 0; fields read live 2026-09-30) |
| Covered but not mapped | Florida GeoData "current-year statewide parcels": named in the response as relayed, but the exact service could not be identified from this environment | The other county layers in the SGID parcels family. `Parcels_Utah_LIR` is Utah **County's** layer, not a statewide one |
| Not this approval | `fl_statewide_cadastral_fgio` (code id `fl_fdor_cadastral`, the `Florida_Statewide_Cadastral` FeatureServer). It is not shown to be the dataset the response names, so it keeps its interim attribute and centroid allowance and is **not** approved for geometry. Also not covered: NAL / SDF attributes, other DOR datasets, tax-sale and auction data, third-party data | Utah tax-sale or assessor feeds, unrelated UGRC datasets, other agencies |
| Expected cadence (source) | Annual, about mid-August to early September | Generally monthly |
| Actual last successful refresh | `parcel_boundary_sources.last_successful_refresh_at`. It advances only on a COMPLETE read; the register keeps `NEVER` until one happens | Same |

The approval register (`data/source_approvals.csv`) records the covered datasets, which ones are mapped, and what is still unresolved in `covered_datasets` and `unresolved_mapping`. A row whose own source id is not among its mapped datasets fails validation.

## Evidence

Neither original email is in this repository, and none could be read from this environment: the mailbox connector was refused and no copy exists in Drive. The register therefore records only what was supplied:

| | Florida DOR | Utah UGRC |
|---|---|---|
| Sender and role | Tom Canter, Systems Project Consultant, DOR Property Tax Oversight | Erik Neemann, GIS Data Coordinator, UGRC |
| Supplied | Relayed by the owner on 2026-10-20 and confirmed again in this instruction | Same |
| Received date, address, message id | Not supplied, so not recorded | Same |

Keep the originals somewhere private and durable, and reference them here by hash. This repository is public.

## What is allowed today (`permissions.authorize`)

| Operation | Florida DOR (`county_parcel_geometry`) | Utah UGRC |
|---|---|---|
| store, enrich, display | Allowed: documented written permission, condition `attribution_text_recorded` | Allowed: published licence. Display also needs `attribution_terms_recorded` (credit, CC BY 4.0 link, change notice, disclaimer, metadata) |
| fetch, parse | Held by `technical_readme_reviewed` (see below) | fetch allowed; parse has no record and is not needed |
| redistribute / export, fetch_via_proxy | No record, so denied | No record, so denied |
| Any other dataset key | No record, so denied | n/a |

### Florida: the DOR county shapefile reader (2026-10-20)

The product owner reviewed the Parcel Shapefiles Readme on 2026-10-20. The document itself is still not reachable from this environment (floridarevenue.com is refused by the network policy, and nothing was routed around that). The register records the review date and the caveats as the owner's review, each with how the code handles it (`technical_caveats`). That record satisfies `technical_readme_reviewed`, so `parse` and `fetch` are allowed for `county_parcel_geometry` only.

**Reading a county file** (`harvesters/boundary/fl_dor.py`, `shapefile.py`, `projection.py`; standard library only):

| README caveat | Handling |
|---|---|
| PIN files hold the boundaries; PAR files add assessment attributes | `--variant PIN` is the default. A PAR file is refused unless `--allow-par-geometry`, and even then only its geometry is read. Only `PARCELNO` is decoded, plus `CO_NO` when present, which must equal the county's DOR number. Every other DBF column is skipped unread |
| PARCELNO joins to the NAL PARCEL_ID | Our key is the **validated** NAL PARCEL_ID: the `matched_parcel_id` recorded in `field_provenance` (source `fdor_nal`) when the record matched the tax-roll layer exactly. A record with none, or with two different ones, is not joined. Matching is exact string equality, with no reformatting |
| Identifier formatting (CSV loses leading zeros) | PARCELNO is read from the DBF. It must be a character (C) field, otherwise the file is refused. Only the DBF's right-padding is removed, so leading zeros, inner spaces, dashes, dots and case are kept |
| Format validation | Before any match is used, `format_check` requires the file's identifier shapes (value-free) to include the shapes of the county's validated ids. Otherwise the county is recorded `JOIN_NOT_VALIDATED` and nothing is written |
| Redacted NAL records | Only geometry and PARCELNO are read, never owner or address. A polygon with a blank PARCELNO is counted (`NO_PARCELNO`) and not attached |
| Rights-of-way | Polygons without a PARCELNO are not attached, and records with DOR use code `94` are never attached (`RIGHT_OF_WAY`) |
| Multi-parcel polygons | One geometry under several PARCELNOs goes to none of them (`MULTI_PARCEL_GEOMETRY`) |
| Stacked / phantom polygons | Several features with one PARCELNO, or two records claiming one feature, are `AMBIGUOUS`. Invalid, zero-area or unclosed rings and orphan holes are refused |
| Condominiums; Miami-Dade and St. Johns keep them in separate files | Units (DOR use code `04`) are never attached to the parcel polygon (`CONDO_UNIT`, or `CONDO_UNIT_SEPARATE_FILE` in those two counties). A file whose name says condo is refused (`CONDOMINIUM_FILE_NOT_INGESTED`) |
| Coordinate system | Read from the file's own `.prj`. Supported: geographic, Albers, Lambert conformal conic (2 parallels) and transverse Mercator, on NAD83 / WGS84 in meters or feet. The test suite cross-checks them against PROJ. NAD27 or anything else refuses the file. NAD83 is treated as WGS84 (under about 2 m); the change notice says so |

**Refresh** (`scripts/parcel_boundary_refresh.py --source fl_dor_pto_parcel_gis --county <County> --files <zip or .shp> [--dry-run | --apply --confirm-apply]`):
- Files are ones a person downloaded from DOR's portal. No download URL is configured or guessed.
- One county per run. The county is recorded in `parcel_boundary_refresh_units` with the dataset name and the DBF's own last-update date.
- Only a COMPLETE read with a validated format writes, and only it advances that county's last successful refresh. A FAILED, REFUSED or JOIN_NOT_VALIDATED read writes nothing and deletes nothing.
- A county read never counts as a statewide refresh: the source row's `last_successful_refresh_at` stays NULL for Florida.

**Coverage today** (production, read-only, 2026-10-20): 378 active Florida rows (of roughly 2,990) carry a validated NAL PARCEL_ID, across 26 counties. The other rows are reported `NO_VALIDATED_NAL_ID` and are never joined by reformatting their listing parcel number. More rows become joinable as the existing tax-roll enrichment matches them.

## How a boundary is matched and stored

**The plan** (`harvesters/boundary/plan.py`) is built on `source_approvals.match_geometries()` and `plan_geometry_refresh()`:
- **Exact identifier match only**, with the same `id_rule` both sides use.
- **Never associated:**
  - a record with no identifier, or with no feature (for example a condominium unit with no polygon of its own);
  - an identifier with several features (stacked polygons) is AMBIGUOUS;
  - a feature whose identifier field lists several parcels (MULTI_PARCEL_FEATURE) is refused;
  - a feature two records claim is AMBIGUOUS for both;
  - a feature with invalid geometry is INVALID_GEOMETRY.
- **A property that holds another source's boundary keeps it.**
- **A read that is not COMPLETE writes nothing.** A parcel missing from a COMPLETE read keeps its stored boundary. Nothing is deleted.

**Geometry** (`harvesters/boundary/geometry.py`):
- normalised to MultiPolygon in WGS84;
- simplified with Douglas-Peucker at 0.000005° (about 0.5 m);
- every part and hole is kept, and a ring that would become invalid keeps its rounded original;
- coordinates are rounded to 7 decimals;
- a SHA-256 of the canonical GeoJSON means an unchanged boundary is never rewritten.

**Migration 034** (`scripts/migrations/034_parcel_boundaries.sql`, NOT applied):
- `parcel_boundary_sources`, seeded from the register: display grant, credit, licence, change notice, disclaimer, metadata, expected cadence, actual refresh state.
- `parcel_boundaries`:
  - `property_id` is the primary key, so there is one boundary per property;
  - `unique (source_id, source_dataset, source_feature_id)`, so a feature is attached to one property at most;
  - it keeps the source's own feature id and dataset;
  - the geometry must be a valid `MultiPolygon` in SRID 4326.
- RLS: an approved account reads a boundary only for a property it may read (so 031's publication gate applies) and only while the source's display grant holds. Clients cannot write.
- `get_property_boundary(uuid)`: the customer read (invoker rights), returning the geometry plus the full attribution.
- `upsert_parcel_boundaries()` / `record_parcel_boundary_refresh()`: service_role only, and neither deletes anything. Invalid geometry, another source's row and an already-attached feature are counted and skipped. Only COMPLETE advances `last_successful_refresh_at`.
- `parcel_boundary_refresh_units`: per-county refresh state (dataset, dataset date, last attempt, last success) for a source delivered per county.
- `parcel_boundaries.source_dataset_date`: the dataset's own date where it states one.
- Number: 033 is held by the billing refund / dispute PR, so this is 034.

**The writer** (`scripts/parcel_boundary_refresh.py`) is not wired into any workflow:
- Default: a readiness report with no request and no database access.
- `--dry-run` and `--apply --confirm-apply`: need `SUPABASE_URL` / `SUPABASE_SERVICE_KEY`, stop if 034 is absent, and read only the identifier and feature id from the source (no assessment attributes).
- Output is counts only.
- Utah is not an activated state, so it has no Utah property to match today.

## What customers see

On the property page aerial and the map preview aerial (`public/parcel-boundary.js`, `app.js` `drawBoundary()`):
- the outline, with the credit on the image;
- a credit line under it carrying:
  - "Parcel outline: <credit>";
  - "Licence: CC BY 4.0" linked, when there is a licence;
  - "Changes: <change notice>";
  - "Source disclaimer" and "Dataset metadata", linked;
  - "Outline is for orientation; it is not a survey and does not show ownership or title."

Display rules:
- Cards never request a boundary.
- A boundary without credit or change notice, or with a licence named but no https link, is not drawn.
- Only https links are rendered.
- Exports, list payloads and saved searches never carry geometry: it is fetched per property into its own cache and is never put on a property row.

Florida shows credit and changes only. The response leaves attribution and disclaimers to TAXACQ's discretion, and a written permission is not a licence.

## Production steps (each needs explicit approval)

1. Apply migration 034.
2. Utah: activate the state, or extend `UT_UGRC.counties` to an activated state's records. Then run `--dry-run`, and `--apply --confirm-apply` once approved.
3. Florida: download the county PIN shapefiles from DOR's portal and run the refresh per county (`--dry-run` first).
4. Decide whether to wire the writer into a workflow, and on what schedule.

PR #144 (`feat/parcel-boundary-storage`) carried an earlier, unmerged design for the same storage. This change supersedes its permission matrix with the approval register and renumbers its migration. Its bigint `property_id` is corrected to `uuid`, which is what `properties.id` actually is.
