# Parcel boundary: review record (f151768 onward)

Status: review for merge readiness. Migration 032 is NOT applied. No production
database write, backfill, workflow dispatch, source activation, merge or deploy
has happened. Every source below stays disabled.

## 1. Source-permission matrix

Source of truth: `data/parcel_boundary_permissions.csv`, enforced by
`harvesters/boundary/permissions.py` and echoed in the database by
`parcel_boundary_source_grants` (migration 032, nothing granted).

A registry status of APPROVED is an enrichment decision (attributes or a
centroid point). It is not permission to store or display a polygon.

| source | state | registry (enrichment) | boundary policy | geometry verified | licence evidence | why not enabled |
|---|---|---|---|---|---|---|
| co_oit_public_parcels | CO | APPROVED for attributes | DISABLED | yes | OIT item: resale forbidden; display approved 2026-09-30 for attributes | Resale forbidden: a stored boundary is a copy. Owner decision needed. |
| ut_ugrc_lir_saltlake | UT | APPROVED for attributes | ELIGIBLE_NOT_ENABLED | yes | CC BY 4.0, read live | Potentially eligible path only. Utah is not activated; no attribution template approved. |
| wi_sco_v12_parcels | WI | UNREVIEWED | DISABLED | yes | "free for public consumption" item; no explicit reuse grant | Terms not reviewed for storage or display. |
| la_ebr_tax_parcels | LA | APPROVED for attributes | DISABLED | no | Public Domain | Geometry field of ei2c-krsr not verified live. |
| la_ebr_tax_roll | LA | APPROVED for attributes | DISABLED | no | Public Domain | Tabular: no geometry published. |
| tx_jim_wells_cad_parcels | TX | UNREVIEWED | DISABLED | yes | none stated | No licence or terms. |
| mo_stl_parcels_coordinates | MO | UNREVIEWED | DISABLED | no | not reviewed | Terms and columns unverified. |
| fl_fdor_cadastral | FL | APPROVED for a centroid point only | DISABLED | yes | centroid approval only | Polygon storage and display terms not read. |
| fl_santa_rosa_parcels | FL | APPROVED for a centroid point only | DISABLED | yes | centroid approval only | County terms for polygons not read. |
| tx_stratmap | TX | not configured | DISABLED | no | not reachable; licence unsettled | Not configured. |

Result today: 0 sources enabled; the dry run makes 0 requests and 0 writes.

## 2. Migration 032 review

Findings, each verified against a live PostgreSQL 16 + PostGIS 3.3 scratch
database (`tests/python/test_migration_032_parcel_boundaries.py`):

1. **Confirmed bypass (fixed).** The table policy checked only `is_approved()`.
   An approved customer reading `parcel_boundaries` directly received
   geometry for a property the publication gate withholds (`1,2` instead of
   `1`). The policy now also requires the property to be visible through
   `properties` RLS, evaluated as the caller.
2. **Attribution could be blank (fixed).** `attribution` was nullable. It is now
   `not null check (btrim(attribution) <> '')`.
3. **No database-side source permission (fixed).** The writer's CSV check was
   the only control. `parcel_boundary_source_grants` (default empty,
   service_role writes, readable only where `display_approved`) is now required
   by both the table policy and the RPC.
4. **RPC contract matches the frontend.** `get_property_boundary(p_property_id
   bigint)` returns `property_id bigint, boundary jsonb, display_permitted
   boolean, attribution text, source_id text, match_method text,
   source_observed_at timestamptz`. The frontend reads `display_permitted`,
   `attribution`, `boundary`, `source_id` and `source_observed_at`, under the
   same name the function is called by (`BOUNDARY_RPC`).
5. **Invoker rights, grants.** `security invoker`, `stable`, `search_path`
   pinned. Execute revoked from `public` and `anon`, granted to `authenticated`.
   Anon has no table access (tested: permission denied).
6. **Fail-closed behaviour (tested).** Withheld property, unapproved account,
   ungranted source, blank attribution: zero rows. Admin sees a withheld
   property, which is the intended admin view. Blank attribution is refused at
   insert.
7. **Output shape.** `ST_AsGeoJSON(ST_Multi(geom), 9)` emits `[longitude,
   latitude]`, EPSG:4326, matching `validateBoundary`. Checked on a live row.

Known limits, not fixed here:
- Before migration 031 (the publication gate) is applied, the property check is
  visibility only, not publication state.
- The database trusts that `boundary_policy = 'APPROVED'` rows were written only
  for granted sources. The grant table is the enforced check; the writer is not
  yet written (see section 4).

## 3. Frontend guarantees (tested in Node and in the browser suite)

- Unauthorized or missing attribution suppresses geometry: `display_permitted`
  must be `true` and attribution non-blank, or the result is "none".
- Invalid or mismatched geometry never renders: validation refuses type, open or
  short rings, out-of-range coordinates, zero area; a point outside the
  bounding box (plus a 0.0005 degree tolerance) is refused.
- Stale responses cannot reach another property: a result applies only to a
  connected host with the same property id that is still its latest request.
  Browser check: the aerial host is removed before a slow answer; nothing is drawn.
- The aerial is never cropped away from the outline: the request uses the box's
  own aspect, and a resize that changes the aspect redraws.

## 4. Harvester, dry run and backfill

Implemented without enabling any source:
- `harvesters/boundary/` gate, validation and write rules (`decide_write`:
  never overwrite good geometry with weaker or older data; never replace across
  sources).
- `scripts/parcel_boundary_harvest.py`: read-only dry run and a counts-only
  backfill plan. It has no apply path, makes no request and writes nothing.

Not implemented, deliberately: the live geometry fetch and the writer. Both need
an enabled source, and none is approved.

## 5. Verification

See the PR description for the exact commands and results.
