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


def _naip(monkeypatch):
    import importlib
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "test")
    if "enrich_property_photos_naip" in sys.modules:
        del sys.modules["enrich_property_photos_naip"]
    return importlib.import_module("enrich_property_photos_naip")


def test_naip_storage_budget_fails_closed(monkeypatch, capsys):
    naip = _naip(monkeypatch)
    calls = []
    monkeypatch.setattr(naip, "fetch_counties_needing_photos", lambda: calls.append("fetched") or [])
    monkeypatch.setattr(naip, "storage_used_bytes", lambda *a, **k: None)
    assert naip.main() == 0 and calls == []                          # unknown usage: nothing fetched or uploaded
    monkeypatch.setattr(naip, "storage_used_bytes", lambda *a, **k: int(naip.STORAGE_BUDGET_MB * 1048576))
    assert naip.main() == 0 and calls == []                          # at the budget: nothing fetched or uploaded
    assert "budget" in capsys.readouterr().out


def test_naip_storage_total_is_recursive(monkeypatch):
    naip = _naip(monkeypatch)
    pages = {"": [{"id": None, "name": "naip"}, {"id": "1", "metadata": {"size": 10}}],
             "naip/": [{"id": "2", "metadata": {"size": 5}}, {"id": "3", "metadata": {"size": 7}}]}

    class R:
        def __init__(self, d): self.d = d
        def raise_for_status(self): pass
        def json(self): return self.d
    monkeypatch.setattr(naip.requests, "post", lambda url, headers, timeout, json: R(pages[json["prefix"]]))
    assert naip.storage_used_bytes() == 22


def test_paged_reads_past_the_api_row_cap():
    data = list(range(2500))
    calls = []

    def get(url, params):
        calls.append((params["offset"], params["limit"]))
        o, n = int(params["offset"]), int(params["limit"])
        return data[o:o + min(n, EU.API_MAX_ROWS)]
    rows = EU.get_paged(get, "u", {"offset": "100"}, 2300)
    assert rows == data[100:2400] and calls == [("100", "1000"), ("1100", "1000"), ("2100", "300")]
    calls.clear()
    assert EU.get_paged(get, "u", {}, 9000) == data and calls[-1] == ("2000", "1000")   # a short page ends the read
