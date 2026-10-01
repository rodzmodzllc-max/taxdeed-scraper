"""(state, county) work units for the coordinate-keyed backfills."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import enrichment_units as EU  # noqa: E402


def test_units_keep_states_apart():
    rows = [{"state": "SC", "county": "York"}, {"state": "SC", "county": "York"},
            {"state": "PA", "county": "York"}, {"state": "CO", "county": "Douglas"}]
    units = dict(EU.outstanding_units(rows, shuffle=False))
    assert units == {("CO", "Douglas"): 1, ("PA", "York"): 1, ("SC", "York"): 2}


def test_unit_params_scope_the_batch_to_one_state():
    assert EU.unit_params(("SC", "York")) == {"county": "eq.York", "state": "eq.SC"}
    assert EU.unit_params(("", "York")) == {"county": "eq.York"}


def test_state_filter_from_environment(monkeypatch):
    monkeypatch.setenv("ENRICH_STATE", "sc, wy,")
    assert EU.state_filter() == ["SC", "WY"]
    assert EU.state_param(EU.state_filter()) == {"state": "in.(SC,WY)"}
    monkeypatch.delenv("ENRICH_STATE")
    assert EU.state_param(EU.state_filter()) == {}


def test_both_backfills_use_the_shared_units():
    for name in ("enrich_flood_zone.py", "enrich_property_photos_naip.py"):
        src = (ROOT / "scripts" / name).read_text(encoding="utf-8")
        assert "EU.outstanding_units(" in src and "EU.unit_params(unit)" in src and '"select": "state,county"' in src
