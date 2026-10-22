# Parcel boundaries from the approved parcel-geometry sources (2026-10-20)

This change puts in place the boundary use that two written approvals cover:
1. Florida DOR Property Tax Oversight;
2. Utah UGRC (CC BY 4.0).

The product owner has confirmed receipt of both.

## Production state (read-only check, 2026-10-21)

- **Migration 034 is live in production**, applied directly rather than through the migration history. Its function bodies match `034_parcel_boundaries.sql` exactly, so that file is left unchanged as the record of what runs. Every later change is in **migration 035** (`035_parcel_boundary_county_refresh.sql`), which is written to upgrade that live state and is **NOT applied**.
- **64 Broward outlines are stored**, all written by workflow `parcel-boundaries-broward` run #2 (2026-10-21, 10:40-10:49 UTC, on `main` at `e5ec234`). That run's loader matched on the listing's own parcel number, so it attached outlines to every active Broward record:
  - 34 condominium units;
  - 1 right-of-way;
  - 39 records with no validated NAL PARCEL_ID.

  The reviewed rules below would attach 10. The same run set Florida's **statewide** `last_successful_refresh_at` from that one county.
- **Correcting it is a production step for the owner**, in this order:
  1. Apply 035. It clears Florida's source-level refresh state, adds the per-county records and leaves every stored outline in place.
  2. Run `scripts/sql/parcel_boundaries_superseded_broward_2025.sql`. It previews the count, then deletes only the rows under that run's dataset name, `DOR PTO PIN 2025F Broward`.
  3. Dispatch the Broward workflow as a dry run, then apply.
- Nothing in this repository change writes to production.

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

**Reading a county file** (`harvesters/boundary/fl_dor.py` for the rules, `shapefile.py` for the file: pyshp, and pyproj for the reprojection):

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
| Wrong location | Every kept polygon must lie inside Florida (`OUT_OF_STATE`). Where the joined record has its own stored point, the polygon must lie within 1 km of it, or it is dropped and the record stays unmatched (`LOCATION_MISMATCH`). Records without a point are counted (`NO_RECORD_COORDINATES`). No county outline is available to the reader, so county containment is checked through the file's `CO_NO` (when present), the county the file is run for and the record's own point |
| Listing parcel numbers (Florida Available) | See "Florida Available outlines" below: separators ignored, exactly one PARCELNO, and the property's own point inside the polygon |
| Coordinate system | Read from the file's own `.prj` with pyproj. Accepted: a projected Florida system on a NAD83 datum (State Plane East, West or North, or Florida GDL Albers; Broward publishes NAD83(HARN) Florida East, US feet). WGS84, NAD27, UTM or an unreadable `.prj` refuses the file. Reprojected to WGS84; NAD83 to WGS84 differs by under about 2 m, and the change notice says so |

**Broward** (`scripts/load_florida_broward_boundaries.py`; manual workflow `.github/workflows/parcel-boundaries-broward.yml`):
- **Trigger:** `workflow_dispatch` only. There is no schedule, no push trigger and no other workflow calls it.
- **Inputs:**
  - `mode`: `dry_run` (the default) or `apply`;
  - `confirm`: must be exactly `APPLY` for `apply` to write.
- **Secrets:** the existing `SUPABASE_URL` / `SUPABASE_SERVICE_KEY`.
- **What a run does:**
  1. Downloads the 2025 PIN file whose link the owner copied from the portal (`FL_DOR_PIN_FILES`).
  2. Hands it to the shared refresh path below, for Broward only.
  3. Prints one counts-only line per stage. No parcel number is printed.
- **Before downloading,** it stops (exit 4) unless both 034 and 035 are applied.
- **A failed download or read** writes nothing. In apply mode it is recorded as a failed **Broward** attempt only.
- **Overlap:** a `concurrency` group keeps two runs from overlapping.

**Refresh** (`scripts/parcel_boundary_refresh.py --source fl_dor_pto_parcel_gis --county <County> --files <zip or .shp> [--dry-run | --apply --confirm-apply]`):
- Files are ones a person downloaded from DOR's portal. No download URL is configured or guessed.
- One county per run. The county is recorded in `parcel_boundary_refresh_units` with the dataset name and the DBF's own last-update date.
- Only a COMPLETE read with a validated format writes, and only it advances that county's last successful refresh. A FAILED, REFUSED or JOIN_NOT_VALIDATED read writes nothing and deletes nothing.
- A county read never counts as a statewide refresh: the source row's `last_successful_refresh_at` stays NULL for Florida.

**First real-file check** (2026-10-21, Broward 2025 PIN file read in this repository's sandbox; production read-only, nothing written, counts only):
- The file is what the reader expects: PARCELNO is a 12-character DBF text field, the projection is NAD83(HARN) Florida East in US feet, there are 786,580 polygon records, and the DBF date is 2025-04-08.
- Read COMPLETE, and the identifier format check passed (7 identifier shapes in the file).
- Of 64 active Broward records, 10 are joinable: 15 are condominium units, 1 is a right-of-way, and 38 have no validated NAL id.
- All 10 matched exactly one polygon: none was ambiguous or multi-parcel, and every one lies inside Broward. A run would write 10.
- The full read took about 3.5 minutes. Peak memory was about 3 GB, nearly all of it from unpacking the 1.6 GB `.shp` into memory; ZIP extraction now streams to disk, and the reader itself stays under about 100 MB. Only the joinable keys' polygons are reprojected and kept.

**Florida Available outlines** (`scripts/load_florida_available_boundaries.py`; manual workflow `.github/workflows/parcel-boundaries-florida-available.yml`; product owner's decision 2026-10-22):
- **Scope:** active Florida Available (`laft`) properties only. Auctions and certificates are not read.
- **Files:** each county's file comes from DOR's own folder listing of `Map Data/<year>F/<year>F PIN`, 2026 by default. No URL is guessed, and condominium files are never used.
- **Join**, one of two:
  - **`EXACT_PARCEL_ID`:** the validated NAL PARCEL_ID equals PARCELNO;
  - **`PARCEL_NUMBER_LOCATION_CONFIRMED`:** the listing parcel number, with separators ignored and case ignored but every digit and leading zero kept, equals **exactly one** PARCELNO value in the county file, **and** the property's own stored point lies **inside** that polygon.
- **Never joined:**
  - a record with no point, or whose point falls outside the polygon;
  - two PARCELNO spellings that collapse to the same value;
  - condo units and rights-of-way;
  - stacked and multi-parcel polygons;
  - a PARCELNO carried by more than one record of the county file (`AMBIGUOUS_DUPLICATE_IDENTIFIER`), in both match modes. The reader counts every in-scope record per PARCELNO before dropping any of them (malformed or empty shape, outside Florida, shared geometry), and the duplicate check runs before the 1 km location check, so distance never picks one of the duplicates. One record whose shape has several parts is one parcel (a MultiPolygon) and is attached normally: the shapefile record itself says the parts belong together, while separate records with the same PARCELNO say nothing of the kind.
- **Inputs:**
  - `mode`: `dry_run` (the default) or `apply`;
  - `confirm`: must be `APPLY` for `apply`;
  - `year`;
  - `counties`, optional;
  - `match_mode`: `listing_location_confirmed` (the default, both joins above) or `validated_id_only` (only `EXACT_PARCEL_ID`; a record without a validated NAL PARCEL_ID is never joined, however unique its listing parcel number and wherever its point lies). Every run prints its mode first.
- **Refresh:** each county is its own refresh unit. A failed download or read writes nothing for that county, and the other counties carry on.
- **Overlap:** both Florida workflows share one concurrency group.
- **Local dry run (2026-10-22, counts only):** all 25 counties with active Available properties read COMPLETE. 129 of 157 records would be outlined.
  - Not outlined:
    - 7 whose stored point falls outside the polygon;
    - 6 with no stored point;
    - 12 with no matching parcel or no usable listing parcel;
    - 2 rights-of-way and 1 condo unit.
  - Refused by the safety checks:
    - 1 Polk multi-parcel polygon;
    - 1 malformed shape in Levy's file, skipped while the rest of Levy read.
  - About 9 minutes, 433 MB peak.

**A malformed shape inside a file** (seen in the 2026 Alachua and Levy files: a PolygonZ with no points) is counted `MALFORMED_SHAPE` and skipped, and the rest of the county reads. A truncated file, where the `.shp` length differs from its header, still fails the whole county.

**Statewide Florida GeoData parcels: NOT used, follow-up only.**
- Florida GeoData's "Florida Statewide Parcels" item (`efa909d6b1c841d298b0a649e7f71cf2`, owner FloridaGIO, read 2026-10-21) is the same service as `fl_statewide_cadastral_fgio` (`Florida_Statewide_Cadastral/FeatureServer`).
- Its description says it holds DOR PTO's county GIS files, exported August 2026 and joined with the NAL tax roll, so it carries owner names and other tax-roll attributes.
- The register keeps that source unapproved for geometry, and nothing here reads it.
- Before it could ever be used, two things are needed:
  - the exact written authorization must be checked against that named service;
  - any implementation must take the geometry and the parcel identifier only, never the NAL attributes.

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

**Migration 034** (`scripts/migrations/034_parcel_boundaries.sql`; live in production, see above) and **migration 035** (`035_parcel_boundary_county_refresh.sql`, NOT applied, upgrades 034 in place and is safe to apply twice):
- `parcel_boundary_sources`, seeded from the register: display grant, credit, licence, change notice, disclaimer, metadata, expected cadence, actual refresh state.
- `parcel_boundaries`:
  - `property_id` is the primary key, so there is one boundary per property;
  - `unique (source_id, source_dataset, source_feature_id)`, so a feature is attached to one property at most;
  - it keeps the source's own feature id and dataset;
  - the geometry must be a valid `MultiPolygon` in SRID 4326.
- RLS: an approved account reads a boundary only for a property it may read (so 031's publication gate applies) and only while the source's display grant holds. Clients cannot write.
- `get_property_boundary(uuid)`: the customer read (invoker rights), returning the geometry plus the full attribution.
- `upsert_parcel_boundaries()` / `record_parcel_boundary_refresh()`: service_role only, and neither deletes anything. Invalid geometry, another source's row and an already-attached feature are counted and skipped. Only COMPLETE advances `last_successful_refresh_at`.
- `parcel_boundary_refresh_units` (035): per-county refresh state (dataset, dataset date, last attempt, last success) for a source delivered per county. Service role only.
- `parcel_boundaries.source_dataset_date` (035): the dataset's own date where it states one.
- `parcel_boundary_refresh_of()` (035, SECURITY DEFINER, returns one timestamp): the freshness a customer sees. For a source delivered per county it is the property's own county; otherwise the whole layer's. NULL reads "not yet recorded". 035 re-creates `get_property_boundary()` to use it.
- `record_parcel_boundary_refresh()` (035): gains an optional county, dataset and dataset date. The 3-argument form is replaced, and 3-argument calls still work.
- Numbering: 033 is held by the billing refund / dispute PR.

**The writer** (`scripts/parcel_boundary_refresh.py`) is called only by the manual Broward workflow, and no schedule runs it:
- Default: a readiness report with no request and no database access.
- `--dry-run` and `--apply --confirm-apply`:
  - need `SUPABASE_URL` / `SUPABASE_SERVICE_KEY`;
  - stop if 034 is absent, or for a files source if 035 is absent;
  - read only the identifier and feature id from the source (no assessment attributes).
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
- Cards (2026-10-22): the app reads the state's outline ids once per load (`parcel_boundaries` `property_id`, the same RLS as
  the outline itself) and only those cards request their outline. The card shows the outline with the short credit on the
  picture; the full credit line sits in the photo's info bubble. A list with no outline ids costs no boundary request.
- A boundary without credit or change notice, or with a licence named but no https link, is not drawn.
- Only https links are rendered.
- Exports, list payloads and saved searches never carry geometry: it is fetched per property into its own cache and is never put on a property row.

Florida shows credit and changes only. The response leaves attribution and disclaimers to TAXACQ's discretion, and a written permission is not a licence.

## Production steps (each needs explicit approval)

1. Apply migration 035 (034 is already live) and remove the superseded Broward rows (see "Production state" above).
2. Utah: activate the state, or extend `UT_UGRC.counties` to an activated state's records. Then run `--dry-run`, and `--apply --confirm-apply` once approved.
3. Florida: download the county PIN shapefiles from DOR's portal and run the refresh per county (`--dry-run` first).
4. Decide whether to wire the writer into a workflow, and on what schedule.

PR #144 (`feat/parcel-boundary-storage`) carried an earlier, unmerged design for the same storage. This change supersedes its permission matrix with the approval register and renumbers its migration. Its bigint `property_id` is corrected to `uuid`, which is what `properties.id` actually is.
