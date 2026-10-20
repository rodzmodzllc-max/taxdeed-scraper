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

### Florida: why file reads still wait

The approval itself is not in doubt. What the code cannot yet do correctly is join a county file's polygons to our records. That join depends on the Parcel Shapefiles Readme, which is to be confirmed from the document itself and covers:
- which file variant to read (PIN or PAR);
- which field carries the parcel number;
- how PARCELNO lines up with the tax roll's PARCEL_ID;
- identifier formatting;
- how condominium units are handled.

The Readme
(https://floridarevenue.com/property/dataportal/Documents/PTO%20Data%20Portal/Map%20Data/Parcel%20Shapefiles%20Readme.pdf) could not be retrieved: floridarevenue.com is refused by this environment's network policy (proxy 403), and the fetch tool gets no DNS resolution. Nothing was routed around that.

So:
- `FL_DOR` in `harvesters/boundary/sources.py` has no join configured and no file location, and refuses with `JOIN_NOT_CONFIGURED` before any request.
- The register keeps the caveats as NOT YET READ.
- To unblock it:
  1. Read the Readme and transcribe its caveats into `technical_caveats`, with `technical_readme_reviewed_on`.
  2. Set the join fields from the document.
  3. Add a county-file reader.

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
3. Florida: review the Readme, then configure the join and the county-file reader (a code change).
4. Decide whether to wire the writer into a workflow, and on what schedule.

PR #144 (`feat/parcel-boundary-storage`) carried an earlier, unmerged design for the same storage. This change supersedes its permission matrix with the approval register and renumbers its migration. Its bigint `property_id` is corrected to `uuid`, which is what `properties.id` actually is.
