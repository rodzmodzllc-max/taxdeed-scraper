// Parcel boundary client contract (public/parcel-boundary.js). Deterministic
// fixture geometry only; nothing here is parcel data.
// Run: node --test tests/boundary/parcel_boundary.test.mjs
import { test } from "node:test";
import assert from "node:assert/strict";
import * as B from "../../public/parcel-boundary.js";

const sq = (x0, y0, x1, y1) => [[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]];
const ok = { type: "MultiPolygon", coordinates: [[sq(-82.05, 26.93, -82.04, 26.94)]] };
const multi = {
  type: "MultiPolygon",
  coordinates: [
    [sq(0, 0, 1, 1), sq(0.3, 0.3, 0.6, 0.6)],   // outer ring + hole
    [sq(2, 0, 3, 1)]                             // disconnected component
  ]
};

test("validateBoundary accepts a MultiPolygon and reports its bbox", () => {
  const v = B.validateBoundary(ok);
  assert.equal(v.ok, true);
  assert.deepEqual(v.bbox, { minX: -82.05, minY: 26.93, maxX: -82.04, maxY: 26.94 });
});

test("validateBoundary accepts JSON text and keeps holes and components", () => {
  const v = B.validateBoundary(JSON.stringify(multi));
  assert.equal(v.ok, true);
  assert.equal(v.polygons.length, 2);
  assert.equal(v.polygons[0].length, 2);
});

test("validateBoundary refuses every malformed or unsupported shape", () => {
  const cases = [
    [null, "missing"],
    [undefined, "missing"],
    ["{not json", "malformed"],
    [{ type: "Polygon", coordinates: [sq(0, 0, 1, 1)] }, "unsupported_type"],
    [{ type: "MultiPolygon", coordinates: [] }, "empty"],
    [{ type: "MultiPolygon", coordinates: [[]] }, "malformed"],
    [{ type: "MultiPolygon", coordinates: [[[[0, 0], [1, 0], [0, 0]]]] }, "short_ring"],
    [{ type: "MultiPolygon", coordinates: [[[[0, 0], [1, 0], [1, 1], [0, 1], [0.5, 0.5]]]] }, "open_ring"],
    [{ type: "MultiPolygon", coordinates: [[[[0, 0], [1, 0], [NaN, 1], [0, 1], [0, 0]]]] }, "malformed"],
    [{ type: "MultiPolygon", coordinates: [[sq(0, 0, 200, 1)]] }, "out_of_range"],
    [{ type: "MultiPolygon", coordinates: [[sq(0, 0, 0, 0)]] }, "zero_area"]
  ];
  for (const [input, reason] of cases) {
    const v = B.validateBoundary(input);
    assert.equal(v.ok, false, `expected refusal for ${reason}`);
    assert.equal(v.reason, reason);
  }
});

test("pointInPolygons respects holes (even-odd) and outside points", () => {
  const polys = multi.coordinates;
  assert.equal(B.pointInPolygons(0.1, 0.1, polys), true);   // solid part of the outer ring
  assert.equal(B.pointInPolygons(0.45, 0.45, polys), false); // inside the hole
  assert.equal(B.pointInPolygons(2.5, 0.5, polys), true);    // second component
  assert.equal(B.pointInPolygons(5, 5, polys), false);
});

test("pointMatchesBoundary allows the listed point near the parcel, refuses a far one", () => {
  const bbox = B.validateBoundary(ok).bbox;
  assert.equal(B.pointMatchesBoundary(-82.045, 26.935, bbox), true);
  assert.equal(B.pointMatchesBoundary(-82.04 + B.POINT_TOLERANCE_DEG / 2, 26.935, bbox), true);
  assert.equal(B.pointMatchesBoundary(-82.0, 26.935, bbox), false);
});

test("fitBox contains the parcel and matches the image aspect in ground terms", () => {
  const bbox = B.validateBoundary(ok).bbox;
  for (const aspect of [4 / 3, 16 / 9]) {
    const [minX, minY, maxX, maxY] = B.fitBox(bbox, aspect);
    assert.ok(minX < bbox.minX && maxX > bbox.maxX, "padded in longitude");
    assert.ok(minY < bbox.minY && maxY > bbox.maxY, "padded in latitude");
    const c = Math.cos(((bbox.minY + bbox.maxY) / 2) * Math.PI / 180);
    const ground = ((maxX - minX) * c) / (maxY - minY);
    assert.ok(Math.abs(ground - aspect) < 1e-9, `ground aspect ${ground} != ${aspect}`);
  }
});

test("projectToBox maps the box corners to the image corners (north up)", () => {
  const box = [-82.1, 26.9, -82.0, 27.0];
  assert.deepEqual(B.projectToBox(-82.1, 27.0, box, 400, 300), [0, 0]);
  assert.deepEqual(B.projectToBox(-82.0, 26.9, box, 400, 300), [400, 300]);
  const [x, y] = B.projectToBox(-82.05, 26.95, box, 400, 300);
  assert.ok(Math.abs(x - 200) < 1e-9 && Math.abs(y - 150) < 1e-9);
});

test("boundaryPath emits one closed subpath per ring, holes included", () => {
  const box = [0, 0, 3, 1];
  const d = B.boundaryPath(multi.coordinates, box, 300, 100);
  assert.equal((d.match(/Z/g) || []).length, 3);   // outer, hole, second component
  assert.ok(d.startsWith("M0.00 100.00"));          // (0,0) lower-left -> bottom edge
});

// --- adapter ---------------------------------------------------------------
const fakeSb = result => ({ rpc: async (name, args) => { fakeSb.calls.push([name, args]); return typeof result === "function" ? result(args) : result; } });
fakeSb.calls = [];
const row = { latitude: 26.935, longitude: -82.045 };
const good = { property_id: "p5", boundary: ok, display_permitted: true, attribution: "Source attribution",
  license_name: "CC BY 4.0", license_url: "https://creativecommons.org/licenses/by/4.0/", change_notice: "Simplified for display",
  disclaimer: "", disclaimer_url: "https://example.org/disclaimer", metadata_url: "https://example.org/metadata",
  source_id: "s1", source_dataset: "D", source_feature_id: "7", match_method: "EXACT_PARCEL_ID", source_observed_at: "2026-10-01T00:00:00Z" };

test("fetchPropertyBoundary: passes the recorded refresh and cadence through, never inventing them", async () => {
  const withRefresh = Object.assign({}, good, { source_last_successful_refresh_at: "2026-10-02T06:00:00Z", source_expected_cadence: "Generally monthly" });
  const res = await B.fetchPropertyBoundary(fakeSb({ data: [withRefresh], error: null }), "p5", row);
  assert.equal(res.boundary.attribution.lastRefreshedAt, "2026-10-02T06:00:00Z");
  assert.equal(res.boundary.attribution.expectedCadence, "Generally monthly");
  const never = await B.fetchPropertyBoundary(fakeSb({ data: [Object.assign({}, good, { source_last_successful_refresh_at: null })], error: null }), "p5", row);
  assert.equal(never.boundary.attribution.lastRefreshedAt, "");
});

test("fetchPropertyBoundary: verified and permitted geometry is available", async () => {
  const res = await B.fetchPropertyBoundary(fakeSb({ data: [good], error: null }), "p5", row);
  assert.equal(res.status, "available");
  assert.deepEqual(res.boundary.attribution, {
    credit: "Source attribution", licenseName: "CC BY 4.0", licenseUrl: "https://creativecommons.org/licenses/by/4.0/",
    changeNotice: "Simplified for display", disclaimer: "", disclaimerUrl: "https://example.org/disclaimer",
    metadataUrl: "https://example.org/metadata", lastRefreshedAt: "", expectedCadence: "" });
  assert.equal(res.boundary.polygons.length, 1);
  assert.equal(res.boundary.sourceFeatureId, "7");
  assert.equal(res.boundary.sourceDataset, "D");
  assert.equal(res.boundary.matchMethod, "EXACT_PARCEL_ID");
});

test("fetchPropertyBoundary sends the property id as text (properties.id is a uuid)", async () => {
  fakeSb.calls = [];
  await B.fetchPropertyBoundary(fakeSb({ data: [], error: null }), "123", row);
  await B.fetchPropertyBoundary(fakeSb({ data: [], error: null }), "aaaaaaaa-0000-0000-0000-000000000001", row);
  assert.deepEqual(fakeSb.calls.map(c => c[1].p_property_id), ["123", "aaaaaaaa-0000-0000-0000-000000000001"]);
  assert.equal(fakeSb.calls[0][0], B.BOUNDARY_RPC);
});

test("fetchPropertyBoundary: no rows is no boundary, not an error", async () => {
  assert.equal((await B.fetchPropertyBoundary(fakeSb({ data: [], error: null }), "p5", row)).status, "none");
  assert.equal((await B.fetchPropertyBoundary(fakeSb({ data: null, error: null }), "p5", row)).status, "none");
});

test("fetchPropertyBoundary fails closed on permission, attribution and mismatch", async () => {
  const unauth = { ...good, display_permitted: false };
  assert.equal((await B.fetchPropertyBoundary(fakeSb({ data: [unauth], error: null }), "p5", row)).status, "none");
  const noAttr = { ...good, attribution: "   " };
  assert.equal((await B.fetchPropertyBoundary(fakeSb({ data: [noAttr], error: null }), "p5", row)).status, "none");
  const noChange = { ...good, change_notice: "" };
  assert.equal((await B.fetchPropertyBoundary(fakeSb({ data: [noChange], error: null }), "p5", row)).status, "none");
  const licenceNoLink = { ...good, license_url: "" };
  assert.equal((await B.fetchPropertyBoundary(fakeSb({ data: [licenceNoLink], error: null }), "p5", row)).status, "none");
  const undef = { ...good, display_permitted: undefined };
  assert.equal((await B.fetchPropertyBoundary(fakeSb({ data: [undef], error: null }), "p5", row)).status, "none");
  const far = await B.fetchPropertyBoundary(fakeSb({ data: [good], error: null }), "p5", { latitude: 10, longitude: 10 });
  assert.deepEqual(far, { status: "invalid", reason: "point_mismatch" });
});

test("fetchPropertyBoundary refuses invalid geometry instead of drawing it", async () => {
  const bad = { ...good, boundary: { type: "MultiPolygon", coordinates: [[[[0, 0], [1, 0], [1, 1], [0, 1]]]] } };
  const res = await B.fetchPropertyBoundary(fakeSb({ data: [bad], error: null }), "p5", row);
  assert.equal(res.status, "invalid");
});

test("fetchPropertyBoundary: PGRST202 is not deployed, other errors are errors", async () => {
  assert.equal((await B.fetchPropertyBoundary(fakeSb({ data: null, error: { code: "PGRST202", message: "x" } }), "p5", row)).status, "not_deployed");
  const e = await B.fetchPropertyBoundary(fakeSb({ data: null, error: { code: "XX000", message: "boom" } }), "p5", row);
  assert.deepEqual(e, { status: "error", code: "XX000" });
  const thrown = await B.fetchPropertyBoundary({ rpc: async () => { throw new Error("offline"); } }, "p5", row);
  assert.deepEqual(thrown, { status: "error", code: "NETWORK" });
});

// ---- property identity (regression: a row for another property is refused) --

test("fetchPropertyBoundary refuses a valid-looking row that belongs to a different property", async () => {
  // Same geometry, permission and attribution as a good row, but a different id:
  // it must be refused before any geometry is validated, drawn or returned.
  const other = { ...good, property_id: "p99" };
  const res = await B.fetchPropertyBoundary(fakeSb({ data: [other], error: null }), "p5", row);
  assert.deepEqual(res, { status: "invalid", reason: "property_mismatch" });
  assert.equal(res.boundary, undefined, "no geometry may be returned for a mismatched row");
});

test("fetchPropertyBoundary refuses a row with no property id at all", async () => {
  const { property_id, ...noId } = good;
  const res = await B.fetchPropertyBoundary(fakeSb({ data: [noId], error: null }), "p5", row);
  assert.deepEqual(res, { status: "invalid", reason: "property_mismatch" });
});

test("fetchPropertyBoundary refuses a numeric id that differs from the requested one", async () => {
  const res = await B.fetchPropertyBoundary(fakeSb({ data: [{ ...good, property_id: 6 }], error: null }), "5", row);
  assert.deepEqual(res, { status: "invalid", reason: "property_mismatch" });
});

test("fetchPropertyBoundary still succeeds when the row's property id matches (numeric and text)", async () => {
  const numeric = { ...good, property_id: 5 };
  assert.equal((await B.fetchPropertyBoundary(fakeSb({ data: [numeric], error: null }), "5", row)).status, "available");
  const textual = { ...good, property_id: "p5" };
  assert.equal((await B.fetchPropertyBoundary(fakeSb({ data: [textual], error: null }), "p5", row)).status, "available");
});

test("a mismatched row is refused even when every other field would have been rendered", async () => {
  // Pins the order: the id check runs before permission, attribution and geometry.
  const bad = { ...good, property_id: "p99", display_permitted: true, attribution: "A", boundary: ok };
  const res = await B.fetchPropertyBoundary(fakeSb({ data: [bad], error: null }), "p5", row);
  assert.equal(res.status, "invalid");
  assert.equal(res.reason, "property_mismatch");
});

// ---- attribution (2026-10-20: credit, licence, changes, disclaimer, metadata) --

test("boundaryAttribution keeps https links only and never invents a licence", () => {
  const a = B.boundaryAttribution({ attribution: " UGRC ", license_name: "CC BY 4.0", license_url: "http://insecure.example/licence",
    change_notice: "x", disclaimer_url: "javascript:alert(1)", metadata_url: "https://ok.example/m" });
  assert.equal(a.credit, "UGRC");
  assert.equal(a.licenseUrl, "");
  assert.equal(a.disclaimerUrl, "");
  assert.equal(a.metadataUrl, "https://ok.example/m");
});

test("a written-permission source without a licence (Florida DOR) is shown with credit and changes only", async () => {
  const fl = { ...good, attribution: "Florida Department of Revenue, Property Tax Oversight", license_name: "", license_url: "",
    disclaimer_url: "", metadata_url: "" };
  const res = await B.fetchPropertyBoundary(fakeSb({ data: [fl], error: null }), "p5", row);
  assert.equal(res.status, "available");
  assert.equal(res.boundary.attribution.licenseName, "");
  assert.equal(res.boundary.attribution.changeNotice, "Simplified for display");
});
