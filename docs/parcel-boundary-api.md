# Parcel boundary read contract

Status: front end implemented against this contract. The RPC is written in
`scripts/migrations/032_parcel_boundaries.sql` and is NOT applied. Until it is,
PostgREST answers `PGRST202` and the app shows the aerial image with no outline.

## Call

`sb.rpc("get_property_boundary", { p_property_id: <properties.id> })`

Security invoker. Caller RLS applies to `parcel_boundaries` and to
`properties`, so the result is withheld whenever the caller cannot see the
property.

## Response

Zero rows: no boundary. This is the only answer for missing geometry, a
source not APPROVED for display, or missing attribution.

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
