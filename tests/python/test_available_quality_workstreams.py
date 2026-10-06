"""The counts-only AVAILABLE quality report measures the three workstreams
(acquisition evidence, coordinates, current amounts) independently."""
import importlib.util
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("_aqr", REPO / "scripts/available_quality_report.py")
Q = importlib.util.module_from_spec(spec)
spec.loader.exec_module(Q)
NOW = datetime(2026, 10, 6, tzinfo=timezone.utc)

ROWS = [
    # MO: address only, no coordinates, no price, process NEEDS_REVIEW (unit status file)
    {"source": "laft", "state": "MO", "county": "St. Louis City", "source_id": "mo_stl_lra_inventory", "status": "active",
     "parcel": "1", "address": "1 X ST", "purchase_amount_kind": "NOT_PUBLISHED", "last_seen_at": "2026-10-04T00:00:00Z"},
    # MN: parcel-layer point, opening bid, no verified path
    {"source": "laft", "state": "MN", "county": "Ramsey", "source_id": "mn_ramsey_tax_forfeit", "status": "active",
     "parcel": "2", "latitude": 44.9, "longitude": -93.1, "field_provenance": {"latitude": {"source": "county_list"}},
     "purchase_amount": 15000, "purchase_amount_kind": "OPENING_BID", "last_seen_at": "2026-10-04T00:00:00Z"},
    # FL: verified path, statement with taxes and fees, still current
    {"source": "laft", "state": "FL", "county": "Citrus", "source_id": "fl_laft_pioneer", "status": "active",
     "parcel": "3", "purchase_path_type": "phone_mail", "purchase_amount": 100, "purchase_amount_kind": "OPENING_BID",
     "otc_provenance": {"purchase_statement": {"total_due": 300.0, "valid_through": "2026-10-31",
                                               "components": {"taxes": 150.0, "recording_fees": 50.0, "opening_bid": 100.0}}},
     "last_seen_at": "2026-10-04T00:00:00Z"},
    # an auction row is never counted
    {"source": "auction", "state": "FL", "county": "Bay", "status": "active"},
]


def test_three_workstreams_are_counted_independently():
    out = {(r["state"], r["source_id"]): r for r in Q.report(ROWS, NOW)}
    mo, mn, fl = out[("MO", "mo_stl_lra_inventory")], out[("MN", "mn_ramsey_tax_forfeit")], out[("FL", "fl_laft_pioneer")]
    assert mo["acquisition"]["needs_review"] == 1 and mo["coordinates"]["missing"] == 1 and mo["amounts"]["no_current_amount"] == 1
    assert mn["acquisition"]["needs_review"] == 1 and mn["coordinates"]["authoritative_parcel_gis"] == 1
    assert mn["amounts"]["opening_bid"] == 1 and mn["amounts"]["temporal_current"] == 1
    assert fl["acquisition"]["verified"] == 1 and fl["amounts"]["current_amount_due"] == 1
    assert fl["amounts"]["published_taxes"] == 1 and fl["amounts"]["published_fees"] == 1
    # A gap in one workstream never shows in another: MO's missing coordinates and
    # missing amount do not change its acquisition status count.
    assert sum(mo["acquisition"].values()) == mo["available"] == 1
    assert sum(mo["coordinates"].values()) == 1


def test_report_carries_no_values():
    import json
    text = json.dumps(Q.report(ROWS, NOW))
    for leak in ("1 X ST", "15000", "300.0", "44.9"):
        assert leak not in text
