"""Property imagery (2026-10-05): sources and rights, deterministic matching,
priority, coverage, and the app.js mirror."""
from __future__ import annotations

import json
import re
from pathlib import Path

from harvesters import imagery as I

REPO = Path(__file__).resolve().parents[2]
APP = (REPO / "public/app.js").read_text(encoding="utf-8")
CASES = json.loads((REPO / "tests/python/fixtures/imagery_cases.json").read_text())["cases"]


def test_vectors_match_the_python_rules():
    for c in CASES:
        assert I.match_method(c["row"]) == c["match"], c["name"]
        assert I.imagery_state(c["row"]) == c["state"], c["name"]
        if "url" in c:
            assert I.naip_export_url(c["row"]["latitude"], c["row"]["longitude"], tuple(c["size"])) == c["url"]


def test_rights_street_view_blocked_county_gis_needs_review_naip_public_domain():
    assert I.SOURCES["google_street_view"]["terms_status"] == "BLOCKED"
    assert not any(I.usable("google_street_view", d) for d in ("stored", "live_export", "provider_static"))
    assert I.SOURCES["county_gis_orthoimagery"]["terms_status"] == "REVIEW_REQUIRED"
    assert not any(I.usable("county_gis_orthoimagery", d) for d in ("stored", "live_export", "provider_static"))
    assert I.usable("usda_naip", "stored") and I.usable("usda_naip", "live_export")
    assert "Public domain" in I.SOURCES["usda_naip"]["license"]
    # Provider snapshots are display-only: never stored by this app.
    for p in ("maptiler_static", "google_static"):
        assert I.SOURCES[p]["terms_status"] == "PROVIDER_DISPLAY"
        assert I.usable(p, "provider_static") and not I.usable(p, "stored")
    for s in I.SOURCES.values():
        assert s["terms_status"] in I.TERMS_STATUSES
    # The frontend never asks Street View for an image.
    assert "maps/api/streetview" not in APP


def test_matching_is_only_ever_the_records_own_coordinates():
    assert I.match_method({"latitude": None, "longitude": -80}) == "none"
    assert I.match_method({"latitude": 0, "longitude": 0}) == "none"
    assert I.match_method({"latitude": 99, "longitude": 0}) == "none"
    src = (REPO / "harvesters/imagery/__init__.py").read_text()
    code = re.sub(r'"""[\s\S]*?"""', "", src)
    assert not re.search(r"nearest|distance|similar|fuzzy|buffer", code, re.I)


def test_priority_is_coverage_order_not_a_judgement():
    rows = [
        {"id": "a", "publication_status": "UNREVIEWED", "parcel": "1", "latitude": 1, "longitude": 1, "purchase_path_type": "county_instructions"},
        {"id": "b", "publication_status": "APPROVED", "parcel": "", "latitude": None, "longitude": None},
        {"id": "c", "publication_status": "APPROVED_GRANDFATHERED", "parcel": "2", "latitude": 1, "longitude": 1},
        {"id": "d", "publication_status": "APPROVED", "parcel": "3", "latitude": 1, "longitude": 1, "purchase_path_type": "application_download"},
    ]
    assert [r["id"] for r in sorted(rows, key=I.imagery_priority)] == ["d", "c", "b", "a"]
    for word in ("value", "market", "assessed", "score", "likely", "sell"):
        assert word not in I.imagery_priority.__code__.co_names
    assert I.order_units([(("MI", "Wayne"), 9), (("LA", "EBR"), 3)], [(("LA", "EBR"), 3)]) == [(("LA", "EBR"), 3), (("MI", "Wayne"), 9)]


def test_coverage_counts_per_state_source_without_values():
    rows = [
        {"state": "LA", "source_id": "la", "publication_status": "APPROVED", "latitude": 30, "longitude": -91, "field_provenance": {"latitude": {"source": "county_list"}}},
        {"state": "LA", "source_id": "la", "publication_status": "APPROVED", "latitude": 30, "longitude": -91, "photo_url": "https://s/x.webp", "photo_checked_at": "2026-10-01"},
        {"state": "MO", "source_id": "mo", "publication_status": "UNREVIEWED", "latitude": None, "longitude": None},
        {"state": "MO", "source_id": "mo", "latitude": 38.6, "longitude": -90.2, "photo_url": ""},
    ]
    cov = {r["state"]: r for r in I.coverage(rows)}
    la, mo = cov["LA"], cov["MO"]
    assert (la["available"], la["stored_images"], la["live_images"], la["displayed"], la["missing"]) == (2, 1, 1, 2, 0)
    assert la["match_methods"] == {"source_coordinates": 1, "recorded_coordinates": 1} and la["terms_status"] == "APPROVED"
    assert (mo["displayed"], mo["checked_no_image"], mo["missing"], mo["coordinate_coverage"]) == (0, 1, 2, 1)
    assert json.dumps(cov).count("38.6") == 0                     # no coordinate leaks into the report


def test_app_constants_mirror_the_python_module():
    js = lambda name: re.search(r"var %s = (.*?);\n" % name, APP, re.S).group(1)  # noqa: E731
    assert json.loads(js("NAIP_EXPORT_ENDPOINT")) == I.NAIP_EXPORT_ENDPOINT
    assert float(js("NAIP_BOX_DEGREES")) == I.NAIP_BOX_DEGREES
    assert re.search(r"var NAIP_THUMB_SIZE = \[(\d+), (\d+)\], NAIP_DETAIL_SIZE = \[(\d+), (\d+)\];", APP).groups() == tuple(
        str(v) for v in I.NAIP_THUMB_SIZE + I.NAIP_DETAIL_SIZE)
    labels = dict(re.findall(r'^\s+([a-z_]+): "([^"]+)"', js("IMAGERY_MATCH_LABELS"), re.M))
    assert labels == I.MATCH_LABELS
    prov = dict(re.findall(r'([a-z_]+): "([a-z_]+)"', js("IMAGERY_PROVENANCE_METHOD")))
    assert prov == I._PROVENANCE_METHOD
    # Same square the stored pipeline uses.
    naip = (REPO / "scripts/enrich_property_photos_naip.py").read_text()
    assert 'os.environ.get("NAIP_BOX_DEGREES", "0.0012")' in naip and I.NAIP_EXPORT_ENDPOINT.split("/rest/")[1] in naip.replace('"\n    "', "")


def test_live_images_are_lazy_csp_allowed_and_switchable():
    block = APP[APP.index("function naipLiveHtml"):APP.index("function propertyVisual")]
    assert 'data-naip-src=' in block and ' src=' not in block.replace('data-naip-src=', '')   # src set only in view
    assert 'function hydrateNaip' in APP and 'IntersectionObserver' in APP[APP.index('function hydrateNaip'):APP.index('function hydrateVisuals')]
    assert "naipLiveEnabled()" in APP[APP.index("function propertyVisual"):APP.index("function propertyVisual") + 600]
    assert 'p.photo_url !== ""' in APP[APP.index("function propertyVisual"):APP.index("function propertyVisual") + 600]
    headers = (REPO / "public/_headers").read_text()
    csp = next(l for l in headers.splitlines() if "Content-Security-Policy" in l)
    img_src = re.search(r"img-src ([^;]+);", csp).group(1)
    assert "https://imagery.nationalmap.gov" in img_src
    assert "imagery.nationalmap.gov" not in re.search(r"connect-src ([^;]+);", csp).group(1)
    assert "naipLiveImagery: false" in (REPO / "tests/config.js").read_text()


def test_quality_report_offline_counts_only(tmp_path):
    import importlib.util
    spec = importlib.util.spec_from_file_location("aqr", REPO / "scripts/available_quality_report.py")
    aqr = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(aqr)
    rows = [
        {"id": 1, "source": "laft", "state": "FL", "source_id": "fl_x", "status": "active", "publication_status": "APPROVED_GRANDFATHERED",
         "parcel": "123", "address": "1 A St", "purchase_amount_kind": "OPENING_BID", "bid": 2000, "purchase_path_type": "phone_mail",
         "latitude": 28, "longitude": -82, "photo_url": "https://s/x.webp", "last_seen_at": "2026-10-05T00:00:00Z", "list_as_of": "2026-09-01",
         "field_provenance": {"assessed": {"source": "fdor_nal"}}, "inventory_status": "available_otc"},
        {"id": 2, "source": "laft", "state": "FL", "source_id": "fl_x", "status": "closed"},
        {"id": 3, "source": "auction", "state": "FL", "source_id": "fl_x", "status": "active"},
        {"id": 4, "source": "laft", "state": "MO", "source_id": "mo_x", "status": "active", "parcel": "9", "address": "PARCEL 9",
         "purchase_amount_kind": "NOT_PUBLISHED", "bid": 0},
    ]
    from datetime import datetime, timezone
    out = {r["state"]: r for r in aqr.report(rows, now=datetime(2026, 10, 6, tzinfo=timezone.utc))}
    fl, mo = out["FL"], out["MO"]
    assert (fl["available"], fl["acquisition_verified"], fl["amount_published"], fl["read_7d"], fl["imagery"]["displayed"]) == (1, 1, 1, 1, 1)
    assert (mo["available"], mo["address"], mo["amount_published"], mo["never_read"], mo["imagery"]["missing"]) == (1, 0, 0, 1, 1)
    p = tmp_path / "rows.json"
    p.write_text(json.dumps(rows))
    assert aqr.main(["--rows", str(p), "--out", str(tmp_path / "q.json")]) == 0
    text = (tmp_path / "q.json").read_text()
    assert "1 A St" not in text and '"123"' not in text            # no identifier or address in the report


# --- what the image's centre stands for (2026-10-06) ------------------------
def test_basis_vectors_match_the_python_rules():
    for c in CASES:
        assert I.imagery_basis(c["row"]) == c["basis"], c["name"]


def test_only_parcel_layer_coordinates_are_parcel_centred():
    assert {m for m, b in I.BASIS_OF_MATCH.items() if b == "parcel"} == {"parcel_roll_coordinates", "parcel_layer_coordinates"}
    # Vendor, address geocode and unrecorded origins are approximate - never parcel.
    for m in ("vendor_coordinates", "geocoded_address", "recorded_coordinates"):
        assert I.BASIS_OF_MATCH[m] == "approximate"
    assert set(I.BASIS_OF_MATCH) == set(I.MATCH_METHODS)
    assert set(I.BASIS_LABELS) == set(I.IMAGERY_BASES)


def test_context_note_never_claims_boundaries_ownership_condition_or_title():
    note = I.CONTEXT_NOTE
    for word in ("boundaries", "ownership", "condition", "title"):
        assert word in note
    assert "context only" in note and "does not show" in note


def test_app_mirrors_the_basis_rules_and_note():
    app = (REPO / "public" / "app.js").read_text(encoding="utf-8")
    for m, b in I.BASIS_OF_MATCH.items():
        assert f'{m}: "{b}"' in app, m
    for b, label in I.BASIS_LABELS.items():
        assert label in app, b
    assert I.CONTEXT_NOTE in app


def test_coverage_counts_basis():
    rows = [
        {"state": "FL", "source_id": "x", "latitude": 29.6, "longitude": -82.3, "field_provenance": {"latitude": {"source": "fdor_nal"}}},
        {"state": "FL", "source_id": "x", "latitude": 29.6, "longitude": -82.3},
        {"state": "FL", "source_id": "x"},
    ]
    (u,) = I.coverage(rows)
    assert (u["parcel_centred"], u["approximate_point"], u["listed_point"]) == (1, 1, 0)
