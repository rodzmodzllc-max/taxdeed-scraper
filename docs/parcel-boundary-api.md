# Parcel boundary read contract

Status: front end implemented against this contract. The RPC and table are
written in `scripts/migrations/032_parcel_boundaries.sql` and are NOT applied.
The migration was live-tested against PostgreSQL 16 with PostGIS 3.3 in a
scratch database (tests/python/test_migration_032_parcel_boundaries.py). Until it is,
PostgREST answers `PGRST202` and the app shows the aerial image with no outline.

## Call

`sb.rpc("get_property_boundary", { p_property_id: <properties.id> })`

Security invoker. Caller RLS applies to `parcel_boundaries`,
`parcel_boundary_source_grants` and `properties`, so the result is withheld
whenever the caller cannot see the property or the source has no grant.

## Response

Zero rows: no boundary. This is the only answer for missing geometry, a
source with no database grant (`parcel_boundary_source_grants.display_approved`
not true), a source not APPROVED, missing or blank attribution, or a property
the caller cannot see. The table policy applies the same four conditions, so a
direct table read cannot return what the RPC withholds.

One row:

| field | type | meaning |
|---|---|---|
| `property_id` | bigint | the requested property |
| `boundary` | GeoJSON MultiPolygon object | coordinates are `[longitude, latitude]`, EPSG:4326 |
| `display_permitted` | boolean | always `true` from the server; the client also fails closed unless it is exactly `true` |
| `attribution` | text | supplied verbatim by the source record; required non-empty |
| `source_id` | text | internal id, never shown to customers |
| `match_method` | text | `EXACT_PARCEL_ID`; internal, never shown |
| `source_observed_at` | timestamptz | when the source was read |

## Client handling

`public/parcel-boundary.js` owns validation and the adapter.

- `not_deployed`: PGRST202. Quiet; the aerial stays, no outline, no message.
- `none`: zero rows, or `display_permitted` not `true`, or no attribution.
- `invalid`: the geometry fails validation (wrong type, unclosed ring,
  fewer than four positions, out-of-range coordinates, zero area, or a point
  that is not inside the source's own bounding box). Refused, never drawn.
- `error`: any other PostgREST error. Shows "Boundary unavailable" with a
  Retry control and logs the error code to the console.
- `available`: validated geometry, drawn over the aerial.

Stale responses are discarded: a result applies only if its host is still
connected and still carries the same property id.

## Rendering

The aerial is requested over the parcel's own bounding box, padded and
adjusted for the image aspect ratio with latitude correction, so the outline
is fitted rather than cropped. Interior rings are holes (even-odd fill).
Only the selected property's outline is drawn; neighbouring parcel geometry
is not part of this contract.

## Not in this contract

- Neighbouring parcels.
- Any Colorado, FDOR, Santa Rosa, Louisiana, Wisconsin, Jim Wells or St. Louis
  polygon. Those stay disabled for boundary use until their permissions are
  established (see docs/parcel-boundaries-audit.md).

## Authorization (as implemented; policy question open)

Current behaviour, unchanged by this fix:

- **Customer / approved account.** Reads a boundary only when all of these hold:
  the account is approved (`is_approved()`); the property is visible to it under
  `properties` RLS, which after migration 031 means `CUSTOMER_PUBLISHED`; and the
  source has `parcel_boundary_source_grants.display_approved = true`.
- **Admin.** The `properties` policy also admits `is_admin()` accounts to
  `publication_state` values other than `CUSTOMER_PUBLISHED`. An admin therefore
  receives the geometry of a withheld property, but only when its source is also
  granted. The source grant applies to admins too.
- **Anon.** No table or function access.

Open question for the owner (not decided in code): should an admin see the
geometry of a property the publication gate withholds from customers? The
present policy allows it because admins need to review withheld records. If
the answer is no, the change belongs in the `parcel_boundaries` policy, not in
the client.
