"""Admin "Needs attention" panel (2026-10-29).

The panel (public/admin.js refreshAttention) translates the registry's
last_error_category into plain words. Two backend gaps made that impossible
in production and are fixed here:
  * scripts/unit_freshness.py never sent last_error_category (the flag it
    waited for was never set) - every failed unit read "reason not recorded";
  * the Texas job never ran unit_freshness, so no Texas unit had a read on
    record.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

import laft_status as LS  # noqa: E402
import unit_freshness as U  # noqa: E402

ADMIN_JS = (REPO / "public" / "admin.js").read_text(encoding="utf-8")
ADMIN_HTML = (REPO / "public" / "admin.html").read_text(encoding="utf-8")


def _entry(status, county="Hendry", **kw):
    e = {"county": county, "status": status, "source_id": "fl_laft_pdfs", "checked_at": "2026-10-28T17:00:00+00:00"}
    e.update(kw)
    return U.normalize_entry(e, default_state="FL", default_source=None)


def test_patches_carry_the_error_category_when_the_column_exists():
    units = {"FL|fl_laft_pdfs|Hendry": {}, "FL|fl_laft_pdfs|Marion": {}}
    rec, _ = U.merge({}, [_entry("FAILED", error_category="TRANSPORT_HTTP_404"), _entry("COMPLETE", county="Marion", row_count=3)], at="t")
    by = {m["county"]: b for m, b in U.registry_patches(rec, units, error_category=True)}
    assert by["Hendry"]["last_error_category"] == "TRANSPORT_HTTP_404"
    assert "last_error_category" in by["Marion"] and by["Marion"]["last_error_category"] is None   # a success clears it
    # Without the column (migration 022 absent) the PATCH never names it.
    assert all("last_error_category" not in b for _, b in U.registry_patches(rec, units))


def test_main_probes_the_column_and_sends_the_category(tmp_path, monkeypatch):
    status = tmp_path / "s.json"
    status.write_text(json.dumps([{"county": "Hendry", "status": "FAILED", "source_id": "fl_laft_pdfs", "error_category": "TRANSPORT_HTTP_404"}]))
    registry = tmp_path / "r.csv"
    registry.write_text("state,county,source_id\nFL,Hendry,fl_laft_pdfs\n")
    sent = []
    monkeypatch.setattr(U.RegistryApi, "has_columns", lambda self: True)
    monkeypatch.setattr(U.RegistryApi, "has_error_category", lambda self: True)
    monkeypatch.setattr(U.RegistryApi, "patch", lambda self, m, b: sent.append((m, b)))
    monkeypatch.setenv("SUPABASE_URL", "https://example.invalid")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "k")
    assert U.main(["--status", str(status), "--persist", str(tmp_path / "p.json"), "--report", str(tmp_path / "o.json"),
                   "--registry", str(registry)]) == 0
    assert sent == [({"state": "FL", "source_id": "fl_laft_pdfs", "county": "Hendry"},
                     {"last_attempt_at": sent[0][1]["last_attempt_at"], "last_attempt_status": "FAILED", "consecutive_failures": 1,
                      "last_error_category": "TRANSPORT_HTTP_404"})]


def test_texas_status_file_counties_are_units(tmp_path):
    p = tmp_path / "harvest_texas_status.json"
    p.write_text(json.dumps({"retrieved_at": "t", "sources": {"tx_lgbs": {}}, "counties": [
        {"source_id": "tx_lgbs", "county": "Galveston", "status": "FAILED", "error_category": "TRANSPORT_PAGE_FAILED", "row_count": 0},
        {"source_id": "tx_lgbs", "county": "Harris", "status": "COMPLETE", "row_count": 4}, "junk"]}))
    entries = [U.normalize_entry(e, default_state="TX", default_source=None) for e in U.read_status(p)]
    assert [(e["state"], e["source_id"], e["county"], e["status"]) for e in entries] == [
        ("TX", "tx_lgbs", "Galveston", "FAILED"), ("TX", "tx_lgbs", "Harris", "COMPLETE")]


def test_texas_job_records_per_unit_freshness():
    wf = yaml.safe_load((REPO / ".github" / "workflows" / "harvest-and-sync.yml").read_text(encoding="utf-8"))
    steps = wf["jobs"]["texas"]["steps"]
    runs = [s.get("run", "") for s in steps]
    hit = [r for r in runs if "unit_freshness.py" in r]
    assert hit and "out/harvest_texas_status.json" in hit[0] and "--state TX" in hit[0]
    step = next(s for s in steps if "unit_freshness.py" in s.get("run", ""))
    assert step.get("continue-on-error") is True and step.get("if") == "always()"


def _js_object_keys(name: str) -> set[str]:
    m = re.search(r"const " + name + r" = \{(.*?)\n\};", ADMIN_JS, re.S)
    assert m, name
    return set(re.findall(r"^\s+([A-Z_0-9]+):", m.group(1), re.M))


def test_every_recorded_error_category_has_plain_words():
    keys = _js_object_keys("ATTENTION_READ_REASONS")
    written = {"TRANSPORT_PAGE_FAILED", "TRANSPORT_REQUEST_FAILED", "TRANSPORT", "PARSE_UNREADABLE_DOCUMENT", "SOURCE_LINK_MISSING"}
    assert set(LS.ERROR_CATEGORIES) | written <= keys


def test_panel_is_first_on_the_admin_page_and_reads_recorded_fields_only():
    first = re.search(r'<section class="admin-card[^"]*" id="([a-z]+)"', ADMIN_HTML)
    assert first and first.group(1) == "attention"
    assert ADMIN_HTML.index('id="attention"') < ADMIN_HTML.index('aria-labelledby="adminIdentityLabel"')
    assert '"reason not recorded"' in ADMIN_JS and "Nothing needs attention." in ADMIN_JS
    # Counts and places only: the unconfirmed read never selects a row's identity.
    sel = re.search(r'select\("id,state,county,source,source_id,harvester_source,last_seen_at"\)', ADMIN_JS)
    assert sel and not re.search(r"attention[^\n]*select\([^)]*(parcel|address|owner_name)", ADMIN_JS)
