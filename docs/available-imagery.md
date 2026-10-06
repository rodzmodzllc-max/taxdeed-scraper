# AVAILABLE imagery: rights, deterministic matching, live NAIP, coverage

2026-10-05. Frontend + Python, no migration, no production write.

## Rule

An image is shown for a property only when:

1. its **source may be used for this product** (`harvesters/imagery.SOURCES`,
   `terms_status`), and
2. it is tied to the record **through the record's own location**, recorded as
   a match method. A nearby record, a lookalike image or a geocoded guess never
   counts.

Being publicly viewable is never treated as permission. Google Street View is
`BLOCKED` and is never requested. No consumer map imagery is scraped.

## Sources (`harvesters/imagery/__init__.py`)

| Source | Terms status | How it may be used |
|---|---|---|
| USDA NAIP (served by USGS The National Map) | APPROVED: public domain (U.S. Government work) | stored (existing pipeline), live export (new) |
| MapTiler Static Maps | PROVIDER_DISPLAY | only through the provider's API with its attribution, never stored |
| Google Maps Static API | PROVIDER_DISPLAY | same |
| County / state GIS orthoimagery | REVIEW_REQUIRED | not used until a person records a review |
| Google Street View | BLOCKED | never |

`usable(source_id, delivery)` is the single test.

## Matching

The match method is read from `field_provenance.latitude.source`:

| Provenance source | Match method | Customer label |
|---|---|---|
| `county_list` | `source_coordinates` | Centered on the coordinates the source list publishes for this record |
| `fdor_nal` | `parcel_roll_coordinates` | … from the state tax roll |
| `statewide_parcel`, `county_gis` | `parcel_layer_coordinates` | … from a parcel layer |
| `vendor_listing` | `vendor_coordinates` | … in the vendor listing |
| anything else, with coordinates | `recorded_coordinates` | … on file for this record (origin not recorded) |
| no coordinates, or (0, 0) | `none` | No property imagery available - no coordinates on file |

The live image request is deterministic. It is a fixed 0.0012° box
(the same square the stored-image pipeline uses), centered on the record's
own latitude / longitude: `naip_export_url()` in Python, `naipExportUrl()` in
app.js. `tests/python/fixtures/imagery_cases.json` pins both to the same URLs.

## Imagery ladder (app.js `propertyVisual`)

1. A stored image (`photo_url`, labelled from `photo_source`, e.g. USDA NAIP).
2. **New:** a live USDA NAIP export centered on the record's coordinates.
   - Thumbnails are 400 × 300 on cards and 800 × 600 on the property page.
   - Captions read "Aerial · USDA NAIP" and "Aerial imagery · USDA NAIP
     (public domain) · centered on …". Imagery is never called Street View.
   - Images are requested only when in view: a deferred `data-naip-src`, an
     IntersectionObserver and a geometric scroll / resize check. The browser's
     own lazy loading did not fire inside the app's scroll layout, so the app
     sets `src` itself and switches the image to eager at that moment.
   - Results never wait on an image.
   - A failure is remembered for the session (`naipFailedSet()`). The image
     steps down to the provider snapshot when a key exists, otherwise to the
     county context.
   - `photo_url = ''` ("checked, no image") skips this rung: the live export
     would ask the same service.
3. A provider static snapshot (unchanged), then the county context mini-map,
   then the placeholder.

`config.js` `naipLiveImagery: false` switches rung 2 off. It is on by default
and off in the test fixture, so the suite never contacts USGS.

CSP: `_headers` adds `https://imagery.nationalmap.gov` to `img-src` only.
Privacy is the same trade-off as the satellite basemaps: a record's
coordinates reach USGS when its card is on screen.

Source truth gains an **Imagery** row (`imageryTruthHtml`) on every non-
certificate property page. It shows the source, its licence, the match method
and "Imagery may be years old." Certificates get no imagery.

## Priority (stored-image pipeline)

`imagery_priority(row)` orders the work:
1. customer-visible;
2. has a parcel;
3. has coordinates;
4. has a verified acquisition path;
5. the rest.

This is a coverage queue, never a judgement about a property.
`enrich_property_photos_naip.py` now runs the customer-visible counties
first within the Available tier (`order_units`, `CUSTOMER_FILTER`). Storage
stays fail-closed at the 950 MB budget.

## Coverage report

`scripts/available_quality_report.py` writes a counts-only report per state /
source to `out/public/available-quality.json`. It covers identity, amounts,
acquisition, values, provenance, freshness, and imagery from
`imagery.coverage()`: coordinates, deterministic matches, stored, live,
displayed, checked-no-image, missing, image source and terms status.

- Offline: `--rows rows.json`.
- Online: it reads only, paging by id at 1,000 rows.

It is not wired into any workflow.

## Production coverage (read-only SQL, 2026-10-05, active AVAILABLE rows)

| State | Available | Customer-visible | With coordinates | Stored image | Live NAIP eligible | Displayed after this change | No coordinates |
|---|---|---|---|---|---|---|---|
| FL | 158 | 158 | 142 | 142 | 0 | 142 | 16 |
| LA | 10,334 | 10,334 | 10,334 | 2,153 | 8,181 | 10,334 | 0 |
| MI | 30,783 | 0 | 30,779 | 178 | 30,601 | 30,779 | 4 |
| MN | 2 | 0 | 2 | 2 | 0 | 2 | 0 |
| MO | 9,758 | 0 | 0 | 0 | 0 | 0 | 9,758 |
| OK | 195 | 0 | 0 | 0 | 0 | 0 | 195 |
| PA | 376 | 0 | 0 | 0 | 0 | 0 | 376 |
| SC | 52 | 0 | 0 | 0 | 0 | 0 | 52 |
| TX | 421 | 421 | 421 | 421 | 0 | 421 | 0 |
| **All** | **52,079** | **10,913** | **41,678** | **2,896** | **38,782** | **41,678** | **10,401** |

- Of the 10,913 customer-visible rows, 10,897 now have imagery. The 16
  without it are FL rows with no coordinates.
- No row is `checked_no_image`.
- Nothing is rights-review-blocked from display: the only REVIEW_REQUIRED
  imagery source (county orthoimagery) is never requested.
- MO / OK / PA / SC have no coordinates. Geocoding them is a production run
  outside this PR.
- "Displayed" counts what the frontend asks for. A live export can still fail
  at USGS; that row then shows the county context.
