# Parcel boundaries: source audit (Phase 1)

Status: audit only. No harvester, migration applied, or production write.
Branch: `feat/parcel-boundary-storage`, based on `origin/main` (a95593c).

## What the pipeline does with polygons today

- `harvesters/enrichment/parcels.py` requests `returnGeometry=true` only for
  `centroid=True` configs, reads the matched feature's rings, computes an
  area-weighted centroid (`polygon_centroid`), and **discards the rings**.
  Nothing downstream stores geometry. Coordinates are a derived point with
  provenance `PARCEL_CENTROID`.
- The database has PostGIS 3.3.7 installed (`public` schema; checked
  read-only 2026-10-12). No `geometry` column exists on `properties`.

## Source-by-source

| Source (config) | Provider / coverage | Geometry endpoint | Identifier + match | Terms evidence in repo | Store polygon? | Display boundary? |
|---|---|---|---|---|---|---|
| `ut_ugrc_lir_saltlake` (UT, Salt Lake) | Utah AGRC/UGRC, Salt Lake County LIR parcels | ArcGIS FeatureServer layer 0 | county parcel id, exact | CC BY 4.0 read live (UGRC licence page): attribution + licence link + change note | **Yes, with attribution** | Yes, with attribution. UT not activated, so gated |
| `co_oit_public_parcels` (CO, Morgan) | Colorado OIT, composite of county assessor parcels | FeatureServer layer 0 | account, exact | Item says "modified from original source", no warranty, **resale forbidden**. Owner approved *display* 2026-09-30 | Unclear: a stored derivative is a copy, not display. **Owner decision needed** | Only as approved for display |
| `wi_sco_v12_parcels` (WI statewide) | UW SCO v12 statewide | FeatureServer | LRA ParcelId, unverified handle | "Free for public consumption" with no explicit reuse grant. **UNREVIEWED** | No | No |
| `la_ebr_tax_parcels` (LA, EBR) | EBR open data, Socrata `ei2c-krsr` | Socrata JSON; geometry field **not verified in repo** | assessment_num, exact | Public Domain (metadata read live) | Only after the geometry field is confirmed on the live dataset | Yes once confirmed |
| `la_ebr_tax_roll` (LA) | EBR open data `myfc-nh6n` | none (tabular) | assessment_num | Public Domain | No geometry | No |
| `tx_jim_wells_cad_parcels` (TX, Jim Wells) | Jim Wells CAD ArcGIS | FeatureServer layer 0 | account, exact | **No licence stated, no terms found. UNREVIEWED** | No | No |
| `mo_stl_parcels_coordinates` (MO, St. Louis) | City of St. Louis PDA_ZONING MapServer | MapServer layer 0 | parcel, unverified | City open data, **terms not reviewed**, `columns_verified=False` | No | No |
| `fl_fdor_cadastral` (FL statewide, TAX_ROLL) | FDOR Florida Statewide Cadastral | FDOR layer (`FDOR_LAYER_URL`) | parcel id, exact, one feature | Repo marks `publication_status=APPROVED` for coordinates only. **No FDOR terms were read for polygon storage** | Unknown; needs terms read | Only after terms read |
| `fl_santa_rosa_parcels` (FL, Santa Rosa) | Santa Rosa County ParcelsOpenData | FeatureServer layer 0 | PAR_NUM = stored parcel, exact | APPROVED for coordinates. **County terms not read** | Unknown; needs terms read | Only after terms read |

### Terms gaps that must be closed before any polygon is stored

1. **FDOR and Santa Rosa** are APPROVED for a centroid point, not for
   storing or displaying the polygon. The sandbox cannot reach these sites
   (the proxy blocks them), so the terms must be read by the existing manual
   evidence job, then recorded in the registry.
2. **Colorado** explicitly forbids resale. Storing a boundary is a copy
   retained for display. The owner must decide this before any CO row is
   loaded.
3. **Louisiana** `ei2c-krsr` geometry field has not been verified live.

## Decision for this PR

Only **Utah** (CC BY 4.0, which permits storage and display with attribution)
would qualify today, and Utah is not an activated state. The migration,
harvester and renderer are built so that **no source is enabled by default**:
each source needs an explicit `boundary_policy` in the config, and the
harvester refuses to write any source whose policy is not `APPROVED` for
storage. Nothing is written in this PR.
