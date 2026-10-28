"""Coordinates for MI / PA / OK records left without a point (2026-10-28,
docs/coordinates-mi-pa-ok-2026-10-28.md). Every identifier below is SYNTHETIC."""
from __future__ import annotations

import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from harvesters.enrichment import geocode as G  # noqa: E402
from harvesters.enrichment import parcels as P  # noqa: E402
from harvesters.enrichment.sources import all_sources  # noqa: E402
from harvesters.governance import permissions as PERM  # noqa: E402

SQUARE = {"rings": [[[-83.30, 42.20], [-83.29, 42.20], [-83.29, 42.21], [-83.30, 42.21], [-83.30, 42.20]]]}
OTHER = {"rings": [[[-83.40, 42.30], [-83.39, 42.30], [-83.39, 42.31], [-83.40, 42.31], [-83.40, 42.30]]]}


def cfg(source_id):
    return next(c for c in all_sources() if c.source_id == source_id)


def row(**kw):
    base = {"id": "r1", "state": "MI", "county": "Wayne", "ledger_type": "buy", "source": "laft", "status": "active",
            "source_id": "mi_wayne_county_landbank", "parcel": "99000010001000", "latitude": None, "longitude": None,
            "field_provenance": {}}
    base.update(kw)
    return base


# --- Michigan: the Wayne County GIS parcel layer --------------------------------
def test_wayne_county_layer_is_a_cleared_scoped_coordinate_source():
    c = cfg("mi_wayne_county_parcels")
    assert (c.state, c.counties, c.id_field, c.id_rule, c.centroid) == ("MI", ("Wayne",), "pnum", "exact", True)
    assert c.field_map == {}                       # coordinates only
    assert c.row_source_ids == ("mi_wayne_county_landbank",)
    assert c.layer_url.startswith("https://services1.arcgis.com/b6rkZNtCd6Mx2gvB/")
    assert P.enrichment_allowed(c)[0]
    for op in ("fetch", "enrich"):
        d = PERM.authorize("mi_wayne_county_parcels", op, state="MI")
        assert d.allowed and not d.documented     # an interim acceptance, never documented permission
    assert not PERM.authorize("mi_wayne_county_parcels", "display", state="MI").allowed
    assert "mi_wayne_county_parcels" in {s.source_id for s in G.coordinate_sources()}


def test_wayne_land_bank_rows_are_planned_against_the_county_layer():
    cls, src = G.plan_row(row())
    assert (cls, src.source_id) == ("MISSING", "mi_wayne_county_parcels")
    # The Detroit-style number, trailing dot included, is the same identifier.
    assert G.plan_row(row(parcel="99000001."))[1].source_id == "mi_wayne_county_parcels"


def test_other_sources_rows_are_never_looked_up_on_a_scoped_layer():
    # Detroit Land Bank rows keep the land bank's own points; a row without one
    # is still not this layer's to match.
    assert G.plan_row(row(source_id="mi_detroit_landbank_lots"))[0] == "NO_SOURCE"
    dlba = row(source_id="mi_detroit_landbank_lots", latitude=42.3, longitude=-83.1,
               field_provenance={"latitude": {"source": "county_list", "method": "LAND_BANK_GIS"}})
    src = G.plan_row(dlba, allow_upgrade=True)[1]
    assert src is None or src.source_id != "mi_wayne_county_parcels"
    # Same rule for every scoped layer (Harris CAD: only the vendor listings
    # carry the CAD account in case_no).
    harris = row(state="TX", county="Harris", source_id="tx_hctax", parcel="", case_no="0000000000001")
    src = G.plan_row(harris)[1]
    assert src is None or src.source_id != "tx_hcad_parcels"
    vendor = dict(harris, source_id="tx_lgbs")
    assert G.plan_row(vendor)[1].source_id == "tx_hcad_parcels"


def _ids_in(url):
    where = parse_qs(urlparse(url).query)["where"][0]
    return where


def test_wayne_lookup_is_exact_single_feature_only():
    c = cfg("mi_wayne_county_parcels")
    src = next(s for s in G.coordinate_sources() if s.source_id == c.source_id)
    seen = []

    def fetch(url):
        seen.append(_ids_in(url))
        return {"features": [
            {"attributes": {"pnum": "99000010001000"}, "geometry": SQUARE},
            {"attributes": {"pnum": "99000001."}, "geometry": SQUARE},
            {"attributes": {"pnum": "99000010002000"}, "geometry": SQUARE},
            {"attributes": {"pnum": "99000010002000"}, "geometry": OTHER},
            # the base number of a suffixed account is another parcel
            {"attributes": {"pnum": "990000100030"}, "geometry": SQUARE},
        ]}
    rows = [row(id="a"), row(id="b", parcel="99000001."), row(id="c", parcel="99000010002000"),
            row(id="d", parcel="99000010003000"), row(id="e", parcel="99000001")]
    out = G.lookup_parcel_layer(src, rows, fetch)
    assert out["a"].status == "MATCHED" and abs(out["a"].lat - 42.205) < 1e-6 and abs(out["a"].lng + 83.295) < 1e-6
    assert out["b"].status == "MATCHED"
    assert out["c"].status == "AMBIGUOUS"          # two different polygons: nothing written
    assert out["d"].status == "NO_MATCH"
    assert out["e"].status == "NO_MATCH"           # the dot is part of the identifier - never added or dropped
    assert all(w.startswith("pnum IN (") for w in seen)
    action, _ = G.decide(rows[2], src, out["c"], allow_upgrade=False, recorded_at="2026-10-28T00:00:00+00:00")
    assert action == "skip"


def test_wayne_lookup_never_replaces_equal_or_stronger_coordinates():
    src = next(s for s in G.coordinate_sources() if s.source_id == "mi_wayne_county_parcels")
    lk = G.Lookup("MATCHED", 42.205, -83.295, "99000010001000", "pnum")
    held = row(latitude=42.2, longitude=-83.3, field_provenance={"latitude": {"source": "statewide_parcel",
                                                                             "method": "PARCEL_GIS"}})
    assert G.decide(held, src, lk, allow_upgrade=True, recorded_at="2026-10-28T00:00:00+00:00")[0] == "skip"
    action, payload = G.decide(row(), src, lk, allow_upgrade=False, recorded_at="2026-10-28T00:00:00+00:00")
    assert action != "skip" and payload["latitude"] == 42.205


# --- Pennsylvania / Oklahoma: no deterministic rule exists, nothing changed -------
def test_fayette_suffixed_accounts_never_match_their_base_parcel():
    c = cfg("pa_fayette_pasda_parcels")
    assert (c.id_field, c.id_rule, c.alt_id_fields) == ("TAXIDNUM", "exact", ())
    idx = P.index_features(c, [{"attributes": {"TAXIDNUM": "99-99-0001"}, "geometry": SQUARE}])
    rows = [{"id": "s", "county": "Fayette", "parcel": "99-99-0001-98"},
            {"id": "t", "county": "Fayette", "parcel": "99-99-0001-A0-0"},
            {"id": "u", "county": "Fayette", "parcel": "99-99-0001"}]
    got = {m.row_id: m.status for m in P.match_rows(c, rows, idx)}
    assert got == {"s": "UNMATCHED", "t": "UNMATCHED", "u": "MATCHED"}


def test_oklahoma_county_pin_stays_exact_and_multi_feature_pins_stay_ambiguous():
    c = cfg("ok_oklahoma_county_parcels")
    assert (c.id_field, c.id_rule, c.alt_id_fields) == ("pin", "exact", ())
    idx = P.index_features(c, [{"attributes": {"pin": "9999-99-999-0001"}, "geometry": SQUARE},
                               {"attributes": {"pin": "9999-99-999-0001"}, "geometry": OTHER}])
    rows = [{"id": "x", "county": "Oklahoma", "parcel": "9999-99-999-0001"},
            {"id": "y", "county": "Oklahoma", "parcel": "9999-99-999-0002"}]
    assert {m.row_id: m.status for m in P.match_rows(c, rows, idx)} == {"x": "AMBIGUOUS", "y": "UNMATCHED"}
