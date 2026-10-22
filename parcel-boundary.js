// Parcel boundary client (front end only). See docs/parcel-boundaries.md
// for the read contract (migration 034 get_property_boundary). Nothing here draws, fetches a geometry from a
// third party, or guesses a shape: a boundary exists only when the server
// returned one, it validates, and it is marked display_permitted.
//
// The module has no DOM access at import, so tests/boundary runs it under
// Node. app.js owns rendering.

export const BOUNDARY_RPC = "get_property_boundary";
// Tolerance, in degrees, for "the source point sits inside the parcel's own
// bounding box". About 55 m: a listed point on the road edge still counts.
export const POINT_TOLERANCE_DEG = 0.0005;
// Pad around the parcel when the aerial is fitted, as a share of the larger side.
export const FIT_PAD = 0.25;

const isFiniteNumber = v => typeof v === "number" && Number.isFinite(v);

function ringProblem(ring) {
  if (!Array.isArray(ring) || ring.length < 4) return "short_ring";
  for (const pos of ring) {
    if (!Array.isArray(pos) || pos.length < 2 || !isFiniteNumber(pos[0]) || !isFiniteNumber(pos[1])) return "malformed";
    if (pos[0] < -180 || pos[0] > 180 || pos[1] < -90 || pos[1] > 90) return "out_of_range";
  }
  const a = ring[0], b = ring[ring.length - 1];
  if (a[0] !== b[0] || a[1] !== b[1]) return "open_ring";
  if (Math.abs(ringArea(ring)) === 0) return "zero_area";
  return null;
}

// Shoelace area in degree space. Only used to reject zero-area rings.
export function ringArea(ring) {
  let s = 0;
  for (let i = 0; i < ring.length - 1; i++) s += ring[i][0] * ring[i + 1][1] - ring[i + 1][0] * ring[i][1];
  return s / 2;
}

// Accepts a parsed GeoJSON object or its JSON text. Only MultiPolygon is
// supported; anything else is refused, not converted.
export function validateBoundary(input) {
  if (input === null || input === undefined) return { ok: false, reason: "missing" };
  let geo = input;
  if (typeof geo === "string") {
    try { geo = JSON.parse(geo); } catch { return { ok: false, reason: "malformed" }; }
  }
  if (!geo || typeof geo !== "object") return { ok: false, reason: "malformed" };
  if (geo.type !== "MultiPolygon") return { ok: false, reason: "unsupported_type" };
  if (!Array.isArray(geo.coordinates) || geo.coordinates.length === 0) return { ok: false, reason: "empty" };
  const polygons = [];
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  for (const poly of geo.coordinates) {
    if (!Array.isArray(poly) || poly.length === 0) return { ok: false, reason: "malformed" };
    for (const ring of poly) {
      const problem = ringProblem(ring);
      if (problem) return { ok: false, reason: problem };
      for (const [x, y] of ring) {
        if (x < minX) minX = x;
        if (y < minY) minY = y;
        if (x > maxX) maxX = x;
        if (y > maxY) maxY = y;
      }
    }
    polygons.push(poly);
  }
  return { ok: true, polygons, bbox: { minX, minY, maxX, maxY } };
}

// Even-odd across every ring of every component, so a point in a hole is
// outside. Ray casting in degree space.
export function pointInPolygons(lng, lat, polygons) {
  let inside = false;
  for (const poly of polygons) {
    for (const ring of poly) {
      for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
        const [xi, yi] = ring[i], [xj, yj] = ring[j];
        if ((yi > lat) !== (yj > lat) && lng < ((xj - xi) * (lat - yi)) / (yj - yi) + xi) inside = !inside;
      }
    }
  }
  return inside;
}

// The source's own point must sit within the parcel's bounding box (plus a
// small tolerance). A point far from the geometry means the geometry is not
// this record's parcel; that is a mismatch, and nothing is drawn.
export function pointMatchesBoundary(lng, lat, bbox) {
  const t = POINT_TOLERANCE_DEG;
  return lng >= bbox.minX - t && lng <= bbox.maxX + t && lat >= bbox.minY - t && lat <= bbox.maxY + t;
}

// The aerial box to request: the parcel's bounding box, padded, then
// stretched to the image's aspect ratio. Latitude correction keeps ground
// proportions right, so the image is not distorted. Returns
// [minLng, minLat, maxLng, maxLat].
export function fitBox(bbox, aspect) {
  const midLat = (bbox.minY + bbox.maxY) / 2;
  const c = Math.cos((midLat * Math.PI) / 180);
  let sx = bbox.maxX - bbox.minX, sy = bbox.maxY - bbox.minY;
  const pad = Math.max(sx, sy) * FIT_PAD;
  sx += pad * 2; sy += pad * 2;
  // Ground width / height must equal the image aspect: sx * c / sy = aspect.
  if ((sx * c) / sy >= aspect) sy = (sx * c) / aspect;
  else sx = (sy * aspect) / c;
  const cx = (bbox.minX + bbox.maxX) / 2, cy = (bbox.minY + bbox.maxY) / 2;
  return [cx - sx / 2, cy - sy / 2, cx + sx / 2, cy + sy / 2];
}

// Linear lon/lat -> pixel for an exportImage with bboxSR=4326: exact, since
// the server stretches the box over the requested size.
export function projectToBox(lng, lat, box, width, height) {
  const [minX, minY, maxX, maxY] = box;
  return [((lng - minX) / (maxX - minX)) * width, ((maxY - lat) / (maxY - minY)) * height];
}

// SVG path data for every ring. Holes are rings inside a polygon and are
// filled even-odd, so they stay open.
export function boundaryPath(polygons, box, width, height) {
  const parts = [];
  for (const poly of polygons) {
    for (const ring of poly) {
      ring.forEach(([x, y], i) => {
        const [px, py] = projectToBox(x, y, box, width, height);
        parts.push(`${i === 0 ? "M" : "L"}${px.toFixed(2)} ${py.toFixed(2)}`);
      });
      parts.push("Z");
    }
  }
  return parts.join(" ");
}

// Only https links from the server are ever rendered as links.
const httpsOrEmpty = v => (typeof v === "string" && /^https:\/\/[^\s/]+\.[^\s/]+/.test(v.trim()) ? v.trim() : "");
const textOrEmpty = v => (typeof v === "string" ? v.trim() : "");

// What every surface that draws a boundary must show for its source: credit,
// licence (name + link), the change notice, the disclaimer (text or link) and
// the metadata page. Credit and change notice are required - without them
// the boundary is not shown at all (fetchPropertyBoundary returns "none").
export function boundaryAttribution(r) {
  return {
    credit: textOrEmpty(r && r.attribution),
    licenseName: textOrEmpty(r && r.license_name),
    licenseUrl: httpsOrEmpty(r && r.license_url),
    changeNotice: textOrEmpty(r && r.change_notice),
    disclaimer: textOrEmpty(r && r.disclaimer),
    disclaimerUrl: httpsOrEmpty(r && r.disclaimer_url),
    metadataUrl: httpsOrEmpty(r && r.metadata_url),
    // TAXACQ's own last successful refresh of this source (a real timestamp
    // or null - never inferred) and the source's published cadence (text).
    lastRefreshedAt: textOrEmpty(r && r.source_last_successful_refresh_at),
    expectedCadence: textOrEmpty(r && r.source_expected_cadence)
  };
}

// Adapter. Returns one of:
//   { status: "available", boundary: { polygons, bbox, attribution, sourceId, sourceDataset, sourceFeatureId, observedAt, matchMethod } }
//   { status: "none" } | { status: "not_deployed" } | { status: "invalid", reason }
//   { status: "error", code }
// `row` is the property's own point (latitude / longitude), used only for
// the mismatch check.
export async function fetchPropertyBoundary(sb, propertyId, row) {
  let result;
  try {
    result = await sb.rpc(BOUNDARY_RPC, { p_property_id: String(propertyId) });
  } catch (e) {
    return { status: "error", code: "NETWORK" };
  }
  const { data, error } = result || {};
  if (error) {
    if (error.code === "PGRST202") return { status: "not_deployed" };
    return { status: "error", code: String(error.code || "UNKNOWN") };
  }
  const rows = Array.isArray(data) ? data : data ? [data] : [];
  if (rows.length === 0) return { status: "none" };
  const r = rows[0];
  // The row must be the property that was asked for. The RPC filters by primary
  // key, so this is a second, client-side guard. A row without a matching id
  // (including a missing one) is refused before any of its fields are read.
  if (String(r.property_id) !== String(propertyId)) return { status: "invalid", reason: "property_mismatch" };
  // Fail closed: the server must say the geometry is permitted for display,
  // and must carry the source's credit and change notice.
  if (r.display_permitted !== true) return { status: "none" };
  const attribution = boundaryAttribution(r);
  if (!attribution.credit || !attribution.changeNotice) return { status: "none" };
  // A licence named without its link is not shown as licensed: refuse.
  if (attribution.licenseName && !attribution.licenseUrl) return { status: "none" };
  const v = validateBoundary(r.boundary);
  if (!v.ok) return { status: "invalid", reason: v.reason };
  if (row && isFiniteNumber(Number(row.latitude)) && isFiniteNumber(Number(row.longitude))
      && String(row.latitude) !== "" && String(row.longitude) !== "") {
    if (!pointMatchesBoundary(Number(row.longitude), Number(row.latitude), v.bbox)) {
      return { status: "invalid", reason: "point_mismatch" };
    }
  }
  return {
    status: "available",
    boundary: {
      polygons: v.polygons, bbox: v.bbox, attribution,
      sourceId: textOrEmpty(r.source_id), sourceDataset: textOrEmpty(r.source_dataset),
      sourceFeatureId: textOrEmpty(r.source_feature_id), observedAt: r.source_observed_at || null,
      matchMethod: textOrEmpty(r.match_method)
    }
  };
}
