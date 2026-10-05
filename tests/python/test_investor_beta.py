"""Investor beta (2026-10-05): the county-level verified acquisition fallback
(scripts/build_acquisition_evidence.py -> public/acquisition-evidence.json)
and the product-usage event vocabulary. Static checks; no network, no database."""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import build_acquisition_evidence as B  # noqa: E402
import purchase_path_engine as PPE  # noqa: E402

APP = (ROOT / "public" / "app.js").read_text(encoding="utf-8")
M024 = (ROOT / "scripts" / "migrations" / "024_customer_monitoring_foundation.sql").read_text(encoding="utf-8")


def test_generated_file_is_current_and_mirrored():
    text = B.render()
    assert (ROOT / "public" / "acquisition-evidence.json").read_text(encoding="utf-8") == text
    assert (ROOT / "acquisition-evidence.json").read_text(encoding="utf-8") == text
    assert subprocess.run([sys.executable, str(ROOT / "scripts" / "build_acquisition_evidence.py"), "--check"],
                          capture_output=True, text=True).returncode == 0


def test_every_record_is_an_applicable_verified_evidence_row():
    rows = [e for t in B.TABLES for e in PPE.load_evidence(t)]
    applicable = {(e.state, e.source_id, e.county, e.path_type, e.observed_on) for e in rows if e.applicable}
    recs = json.loads(B.render())["records"]
    assert recs, "no records"
    for r in recs:
        assert (r["state"], r["source_id"], r["county"], r["path_type"], r["purchase_path_observed_on"]) in applicable
        acq = r["acquisition"]
        assert acq["mode"] in PPE.ACQUISITION_MODE_LABELS
        assert acq["observed_on"] == r["purchase_path_observed_on"]


def test_records_carry_no_per_parcel_data():
    for r in json.loads(B.render())["records"]:
        for k in r:
            assert k not in ("parcel", "case_no", "owner_name", "address_line", "source_match", "purchase_url")
        assert r["county"] != ""


def test_paid_beta_sources_with_verified_process_are_covered():
    keys = {(r["state"], r["source_id"], r["county"]) for r in json.loads(B.render())["records"]}
    for k in (("LA", "la_ebr_adjudicated", "East Baton Rouge"), ("SC", "sc_york_tax_sale", "York"),
              ("MI", "mi_lenawee_tax_sale", "Lenawee"), ("MI", "mi_eaton_treasurer_sale", "Eaton"),
              ("WI", "wi_green_tax_deed_sales", "Green")):
        assert k in keys, k


def test_frontend_fallback_requires_same_source_county_and_type():
    body = APP[APP.index("function countyAcquisitionRecord(p)"):APP.index("function acquisitionProvenance(p)")]
    for cond in ("r.state === st", "r.source_id === p.source_id", "r.path_type === p.purchase_path_type"):
        assert cond in body
    assert 'r.county === p.county' in body
    # The row's own record always wins; the fallback is only for a missing one.
    prov = APP[APP.index("function acquisitionProvenance(p)"):APP.index("function acquisitionOf(p)")]
    assert "op.acquisition && typeof op.acquisition === \"object\")) return op" in prov
    assert "...keys, ...op" in prov


def _check_list() -> set[str]:
    m = re.search(r"event text not null check \(event in \((.*?)\)\),", M024, re.S)
    assert m
    return set(re.findall(r"'([a-z_]+)'", m.group(1)))


def test_every_tracked_event_is_storable_by_migration_024():
    used = set(re.findall(r'\btrack\("([a-z_]+)"', APP)) | set(re.findall(r'\bevent = "([a-z_]+)"', APP))
    assert used, "no events"
    assert used <= _check_list(), used - _check_list()
    for e in ("state_selected", "county_selected", "map_used", "acquisition_section_viewed", "application_opened",
              "acquisition_instructions_opened", "acquisition_source_opened", "official_source_opened", "search_performed",
              "property_viewed", "property_saved"):
        assert e in used, e


def test_events_carry_no_free_text_or_identity():
    for m in re.finditer(r'\btrack\("[a-z_]+",\s*\{([^}]*)\}', APP):
        props = m.group(1)
        for bad in ("email", "address", "parcel", "href", "textContent", "owner"):
            assert bad not in props, (bad, props)
        # Search text is reduced to a boolean, never sent.
        assert not re.search(r"(?<!!!)state\.search", props), props
