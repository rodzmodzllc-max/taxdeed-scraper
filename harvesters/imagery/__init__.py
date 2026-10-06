"""Property imagery: sources, rights, deterministic matching, priority, coverage.

The one place the app decides which images it may show for a property, how
the image is tied to the record, and in what order imagery work is done.
``public/app.js`` mirrors the constants it needs (``IMAGERY_MATCH_LABELS``,
``NAIP_EXPORT_ENDPOINT``, ``naipExportUrl()``). A test pins them to this
module.

Rights. Every source carries a ``terms_status``:
- ``APPROVED``: may be fetched, stored and shown with its attribution.
- ``PROVIDER_DISPLAY``: shown only through the provider's own API, under its
  terms, with its attribution. Never stored by this app.
- ``REVIEW_REQUIRED``: terms not established for this product. Never used
  until a person records a review.
- ``BLOCKED``: never used.

Being publicly viewable is never treated as permission.

Matching. An image is tied to a record only through the record's OWN
location. The match method names where that location came from: the source
list's published coordinates, a state parcel roll, a parcel layer, a vendor
listing, or coordinates of unrecorded origin. An image is never chosen
because it is near something, and never by visual similarity. With no
coordinates there is no image: "No property imagery available".

Priority. Imagery work is ordered for coverage only:
1. customer-visible records;
2. records with a parcel identity;
3. records with coordinates;
4. records with a verified acquisition path;
5. the rest.

It is an operational queue, not a judgement about any property.
"""
from __future__ import annotations

from collections import defaultdict

# --- sources -------------------------------------------------------------

NAIP_EXPORT_ENDPOINT = ("https://imagery.nationalmap.gov/arcgis/rest/services/"
                        "USGSNAIPImagery/ImageServer/exportImage")
# The same square the stored-image pipeline uses (scripts/enrich_property_photos_naip.py
# BOX_DEGREES), so a live image and a stored image of one record frame the same ground.
NAIP_BOX_DEGREES = 0.0012
NAIP_THUMB_SIZE = (400, 300)
NAIP_DETAIL_SIZE = (800, 600)

TERMS_STATUSES = ("APPROVED", "PROVIDER_DISPLAY", "REVIEW_REQUIRED", "BLOCKED")

SOURCES = {
    "usda_naip": {
        "name": "USDA National Agriculture Imagery Program (NAIP)",
        "publisher": "USDA Farm Service Agency, served by USGS The National Map",
        "license": "Public domain (U.S. Government work)",
        "terms_status": "APPROVED",
        "image_type": "Aerial orthoimagery",
        "delivery": ("stored", "live_export"),
        "capture_date": "Stored images carry the capture year when the service reports it; live images are the service's current mosaic",
        "attribution": "USDA NAIP imagery via USGS The National Map",
        "endpoint": NAIP_EXPORT_ENDPOINT,
    },
    "maptiler_static": {
        "name": "MapTiler Static Maps (satellite)",
        "publisher": "MapTiler",
        "license": "Provider terms; display through the provider API with its attribution",
        "terms_status": "PROVIDER_DISPLAY",
        "image_type": "Satellite basemap snapshot",
        "delivery": ("provider_static",),
        "capture_date": "Not published per image",
        "attribution": "© MapTiler © OpenStreetMap contributors (baked into the image)",
        "endpoint": "https://api.maptiler.com/maps/hybrid/static/",
    },
    "google_static": {
        "name": "Google Maps Static API (hybrid)",
        "publisher": "Google",
        "license": "Provider terms; display through the provider API with its attribution",
        "terms_status": "PROVIDER_DISPLAY",
        "image_type": "Satellite basemap snapshot",
        "delivery": ("provider_static",),
        "capture_date": "Not published per image",
        "attribution": "Google logo and map data notice (baked into the image)",
        "endpoint": "https://maps.googleapis.com/maps/api/staticmap",
    },
    "county_gis_orthoimagery": {
        "name": "County / state GIS orthoimagery services",
        "publisher": "Individual counties and states",
        "license": "Varies by publisher - not established for this product",
        "terms_status": "REVIEW_REQUIRED",
        "image_type": "Aerial orthoimagery",
        "delivery": (),
        "capture_date": "Varies",
        "attribution": "Per publisher",
        "endpoint": "",
    },
    "google_street_view": {
        "name": "Google Street View",
        "publisher": "Google",
        "license": "Not used",
        "terms_status": "BLOCKED",
        "image_type": "Street-level imagery",
        "delivery": (),
        "capture_date": "",
        "attribution": "",
        "endpoint": "",
    },
}


def usable(source_id: str, delivery: str) -> bool:
    """Whether this app may use this source this way."""
    s = SOURCES.get(source_id)
    if not s or delivery not in s["delivery"]:
        return False
    if delivery in ("stored", "live_export"):
        return s["terms_status"] == "APPROVED"
    return s["terms_status"] in ("APPROVED", "PROVIDER_DISPLAY")


# --- matching ------------------------------------------------------------

MATCH_METHODS = ("source_coordinates", "parcel_roll_coordinates", "parcel_layer_coordinates",
                 "vendor_coordinates", "recorded_coordinates", "none")
MATCH_LABELS = {
    "source_coordinates": "Centered on the coordinates the source list publishes for this record",
    "parcel_roll_coordinates": "Centered on this parcel's coordinates from the state tax roll",
    "parcel_layer_coordinates": "Centered on this parcel's coordinates from a parcel layer",
    "vendor_coordinates": "Centered on the coordinates in the vendor listing",
    "recorded_coordinates": "Centered on the coordinates on file for this record (origin not recorded)",
    "none": "No property imagery available - no coordinates on file",
}
# field_provenance source -> match method.
_PROVENANCE_METHOD = {
    "county_list": "source_coordinates",
    "fdor_nal": "parcel_roll_coordinates",
    "statewide_parcel": "parcel_layer_coordinates",
    "county_gis": "parcel_layer_coordinates",
    "vendor_listing": "vendor_coordinates",
}


def _num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None


def has_coordinates(row: dict) -> bool:
    lat, lng = _num(row.get("latitude")), _num(row.get("longitude"))
    return lat is not None and lng is not None and -90 <= lat <= 90 and -180 <= lng <= 180 and not (lat == 0 and lng == 0)


def match_method(row: dict) -> str:
    """How an image is tied to this record: always the record's own location."""
    if not has_coordinates(row):
        return "none"
    fp = row.get("field_provenance") or {}
    src = ((fp.get("latitude") or {}).get("source")) if isinstance(fp, dict) else None
    return _PROVENANCE_METHOD.get(src or "", "recorded_coordinates")


def naip_bbox(lat: float, lng: float, box: float = NAIP_BOX_DEGREES) -> str:
    half = box / 2.0
    return f"{lng - half:.6f},{lat - half:.6f},{lng + half:.6f},{lat + half:.6f}"


def naip_export_url(lat: float, lng: float, size=NAIP_THUMB_SIZE) -> str:
    """A deterministic, cacheable NAIP image request for the record's own coordinates."""
    w, h = size
    return (f"{NAIP_EXPORT_ENDPOINT}?bbox={naip_bbox(lat, lng)}&bboxSR=4326&size={w},{h}"
            f"&format=jpg&f=image")


# --- state of one record's imagery ----------------------------------------

IMAGERY_STATES = ("stored", "live", "checked_no_image", "no_coordinates")


def imagery_state(row: dict) -> str:
    """What the record shows.

    - ``stored``: an image this app stored.
    - ``live``: the NAIP live export, centered on the record's coordinates.
    - ``checked_no_image``: the stored-image check found no imagery. The live
      export would ask the same service, so it is not attempted.
    - ``no_coordinates``: nothing to match against.
    """
    url = row.get("photo_url")
    if isinstance(url, str) and url.strip():
        return "stored"
    if url == "":
        return "checked_no_image"
    if has_coordinates(row):
        return "live"
    return "no_coordinates"


# --- priority -------------------------------------------------------------

CUSTOMER_PUBLICATION = ("APPROVED", "APPROVED_GRANDFATHERED")


def imagery_priority(row: dict) -> tuple:
    """Sort key: smaller first. Coverage order only - never a property judgement."""
    path = row.get("purchase_path_type")
    return (
        0 if row.get("publication_status") in CUSTOMER_PUBLICATION else 1,
        0 if str(row.get("parcel") or "").strip() else 1,
        0 if has_coordinates(row) else 1,
        0 if path and path != "none_published" else 1,
        str(row.get("state") or ""), str(row.get("county") or ""), str(row.get("id") or ""),
    )


CUSTOMER_FILTER = {"publication_status": "in.(" + ",".join(CUSTOMER_PUBLICATION) + ")"}


def order_units(units, customer_units):
    """Stored-image work units with customer-visible counties first, stable."""
    first = {u for u, _ in customer_units or []}
    return sorted(units, key=lambda un: 0 if un[0] in first else 1)


# --- coverage -------------------------------------------------------------

def coverage(rows) -> list[dict]:
    """Counts per (state, source): the operational imagery report. No values."""
    acc = defaultdict(lambda: defaultdict(int))
    for r in rows:
        key = (r.get("state") or "", r.get("source_id") or r.get("harvester_source") or "")
        c = acc[key]
        c["available"] += 1
        if r.get("publication_status") in CUSTOMER_PUBLICATION:
            c["customer_visible"] += 1
        if has_coordinates(r):
            c["coordinates"] += 1
        st = imagery_state(r)
        c["state_" + st] += 1
        if r.get("photo_checked_at"):
            c["attempted_stored"] += 1
        m = match_method(r)
        c["match_" + m] += 1
        if m != "none":
            c["deterministic_match"] += 1
    out = []
    for (state, source), c in sorted(acc.items()):
        displayed = c["state_stored"] + c["state_live"]
        out.append({
            "state": state, "source_id": source,
            "available": c["available"], "customer_visible": c["customer_visible"],
            "coordinate_coverage": c["coordinates"],
            "deterministic_match": c["deterministic_match"],
            "stored_images": c["state_stored"], "live_images": c["state_live"],
            "displayed": displayed,
            "checked_no_image": c["state_checked_no_image"],
            "missing": c["available"] - displayed,
            "attempted_stored": c["attempted_stored"],
            "image_sources": ["usda_naip"] if displayed else [],
            "terms_status": SOURCES["usda_naip"]["terms_status"] if displayed else "",
            "match_methods": {m: c["match_" + m] for m in MATCH_METHODS if c["match_" + m]},
        })
    return out
