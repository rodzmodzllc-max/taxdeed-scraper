"""Audit 2026-10-28 link findings (B8, B41): customer links are human pages,
never a REST service directory or an id-less URL template."""
from __future__ import annotations

import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from harvesters.otc.adapters import expansion as EX  # noqa: E402

REGISTRY = ROOT / "data" / "county_source_registry.csv"


def _configs():
    for srcs in EX.SOURCES.values():
        for src in srcs:
            cfg = src.config
            yield getattr(cfg, "table", cfg)


def test_b8_no_customer_link_is_an_arcgis_rest_endpoint():
    """list_url becomes properties.list_url and url_auction ('View county auction site') and the
    registry canonical_url: it must never be a REST service directory page."""
    bad = [(c.source_id, c.list_url) for c in _configs()
           if getattr(c, "list_url", None) and "/rest/services/" in c.list_url.lower()]
    assert bad == []


def test_b8_minnesota_layers_keep_their_rest_layer_for_harvesting_only():
    for cfg, page in ((EX.MN_WRIGHT_TAX_FORFEIT, "https://www.publicsurplus.com/sms/wrightcore,mn/"),
                      (EX.MN_HUBBARD_TFL_OTC, "https://www.hubbardcounty.gov/"),
                      (EX.MN_STPAUL_HRA, "https://www.stpaul.gov/"),
                      (EX.MN_RAMSEY_TAX_FORFEIT, "https://www.ramseycountymn.gov/")):
        assert "/rest/services/" in cfg.layer_url
        assert cfg.list_url.startswith(page)
        rec = cfg.list_url
        assert rec.startswith("https://")


def test_b8_and_b41_registry_rows():
    rows = list(csv.DictReader(REGISTRY.open(newline="", encoding="utf-8")))
    mn = {r["source_id"]: r for r in rows if r["state"] == "MN"}
    for sid in ("mn_wright_tax_forfeit", "mn_hubbard_tfl_otc", "mn_stpaul_hra_properties", "mn_ramsey_tax_forfeit"):
        assert "/rest/services/" not in mn[sid]["canonical_url"]
    # A URL template with an empty id is not a document (it answers 404).
    for r in rows:
        for c in ("canonical_url", "document_url", "purchase_url"):
            assert not r[c].rstrip().endswith("/id/"), (r["source_id"], c)


# ---- B14 / F4: registry rows reach production; Texas rows get stamped ----------
import json  # noqa: E402

sys.path.insert(0, str(ROOT / "scripts"))
import sync_registry_to_supabase as RS  # noqa: E402
import unit_freshness as UF  # noqa: E402


def _csv(**kw):
    base = {c: "" for c in (*RS.IDENTITY, *RS.METADATA, *RS.INSERT_ONLY)}
    base.update(state="TN", county="Shelby", source_id="tn_shelby_landbank", harvester="h", access_method="JSON_ENDPOINT",
                machine_format="JSON", verification_status="PRODUCTION_VERIFIED", governance_status="APPROVED",
                last_checked="2026-10-08", evidence_ref="e", publishing_unit="COUNTY", completeness_status="UNKNOWN",
                publication_status="APPROVED", restrictions="r", ledgers="AVAILABLE")
    base.update(kw)
    return base


def test_b14_registry_sync_inserts_missing_rows_and_never_touches_freshness_or_publication():
    table = [{"id": "1", "state": "LA", "county": "East Baton Rouge", "source_id": "la_ebr_adjudicated",
              "canonical_url": "https://data.brla.gov/old", "access_method": "JSON_ENDPOINT", "machine_format": "CSV",
              "verification_status": "PRODUCTION_VERIFIED", "governance_status": "APPROVED", "harvester": "h",
              "last_checked": "2026-09-30", "evidence_ref": "e", "publishing_unit": "PARISH", "ledgers": "AVAILABLE",
              "publication_status": "RESTRICTED", "restrictions": "admin review", "completeness_status": "COMPLETE",
              "last_success_at": "2026-10-28T00:00:00Z"},
             {"id": "2", "state": "FL", "county": "Baker", "source_id": None, "canonical_url": None,
              "access_method": "NONE", "machine_format": "NONE", "verification_status": "NOT_FOUND_AFTER_SEARCH",
              "governance_status": "NOT_APPLICABLE", "last_checked": "2026-09-29", "evidence_ref": "e",
              "publishing_unit": "COUNTY", "publication_status": "UNREVIEWED", "completeness_status": "UNKNOWN"}]
    rows = [_csv(),
            _csv(state="LA", county="East Baton Rouge", source_id="la_ebr_adjudicated", canonical_url="https://data.brla.gov/new",
                 machine_format="CSV", last_checked="2026-10-26", publishing_unit="PARISH", publication_status="APPROVED",
                 restrictions="csv text", completeness_status="UNKNOWN")]
    p = RS.plan(rows, table)
    assert [b["source_id"] for b in p["insert"]] == ["tn_shelby_landbank"]
    assert p["insert"][0]["publication_status"] == "APPROVED" and p["insert"][0]["purchase_url"] is None
    (rid, body), = p["patch"]
    assert rid == "1" and body == {"canonical_url": "https://data.brla.gov/new", "last_checked": "2026-10-26"}
    for c in ("publication_status", "restrictions", "completeness_status", "last_success_at", "last_attempt_at"):
        assert c not in body
    assert p["table_only"] == 1          # Baker's candidate row: counted, never deleted


def test_b14_registry_sync_refuses_values_the_table_checks_reject_and_matches_candidates_on_url():
    p = RS.plan([_csv(machine_format="SHAPEFILE")], [])
    assert p["insert"] == [] and p["refused"]["machine_format"] == 1
    table = [{"id": "9", "state": "TX", "county": "Camp", "source_id": None, "canonical_url": "https://www.campcad.org/struck-off-list/",
              "access_method": "UNKNOWN", "machine_format": "PDF", "verification_status": "SEARCH_EVIDENCE_ONLY",
              "governance_status": "TERMS_NOT_VERIFIED", "last_checked": "2026-10-26", "evidence_ref": "e",
              "publishing_unit": "COUNTY"}]
    cand = _csv(state="TX", county="Camp", source_id="", harvester="", canonical_url="https://campcad.org/struck-off-list/",
                access_method="UNKNOWN", machine_format="PDF", verification_status="SEARCH_EVIDENCE_ONLY",
                governance_status="TERMS_NOT_VERIFIED", last_checked="2026-10-26", ledgers="")
    p = RS.plan([cand], table)
    assert p["insert"] == [] and p["table_only"] == 0
    assert p["patch"] == [("9", {"canonical_url": "https://campcad.org/struck-off-list/"})]


def test_b14_repository_registry_is_storable_in_full():
    p = RS.plan(RS.csv_rows(), [])
    assert sum(p["refused"].values()) == 0 and len(p["insert"]) == len(RS.csv_rows())


def test_b14_unit_freshness_reads_the_texas_counties_object(tmp_path):
    f = tmp_path / "harvest_texas_status.json"
    f.write_text(json.dumps({"retrieved_at": "x", "sources": {}, "counties": [
        {"source_id": "tx_lgbs", "county": "Galveston", "status": "COMPLETE", "row_count": 4},
        {"source_id": "tx_pbfcm", "county": "Walker", "status": "FAILED", "row_count": 0}]}), encoding="utf-8")
    entries = [UF.normalize_entry(e, default_state="TX", default_source=None) for e in UF.read_status(f)]
    assert [(e["state"], e["source_id"], e["county"], e["status"]) for e in entries] == [
        ("TX", "tx_lgbs", "Galveston", "COMPLETE"), ("TX", "tx_pbfcm", "Walker", "FAILED")]


def test_b14_texas_job_runs_unit_freshness():
    wf = (ROOT / ".github" / "workflows" / "harvest-and-sync.yml").read_text(encoding="utf-8")
    texas = wf.split("\n  texas:\n", 1)[1].split("\n  backup:\n", 1)[0]
    assert "scripts/unit_freshness.py --status out/harvest_texas_status.json --state TX" in texas


def test_b14_registry_job_is_manual_and_plans_by_default():
    wf = (ROOT / ".github" / "workflows" / "harvest-and-sync.yml").read_text(encoding="utf-8")
    assert "\n  registry:\n" in wf
    body = wf.split("\n  registry:\n", 1)[1][:3000]
    assert "github.event.inputs.job == 'registry'" in body          # manual only, never scheduled
    assert "--apply" in body and "registry_mode == 'apply'" in body  # writes only when asked
    assert "registry" in wf.split("options: [all, deeds", 1)[1].split("]", 1)[0]


# ---- B44: repository internals on the product domain ---------------------------
def test_b44_discovery_report_defaults_to_out_public_not_the_working_directory(monkeypatch, tmp_path):
    from harvesters.governance import discovery_guard as DG
    monkeypatch.delenv("DISCOVERY_REPORT_DIR", raising=False)
    monkeypatch.chdir(tmp_path)
    g = DG.Guard("audit_b44_test", index=[])
    p = g.write_report()
    try:
        assert p.parent == DG.REPO / "out" / "public"
        assert not (tmp_path / p.name).exists()
    finally:
        p.unlink(missing_ok=True)


def test_b44_root_robots_txt_exists_and_is_not_a_public_file():
    robots = (ROOT / "robots.txt").read_text(encoding="utf-8")
    for path in ("/.github/", "/data/", "/docs/", "/scripts/", "/supabase/", "/tests/", "/harvesters/"):
        assert f"Disallow: {path}" in robots
    assert not (ROOT / "public" / "robots.txt").exists()     # the mirror guard fails on an unlisted public/ file
    assert not list(ROOT.glob("discovery-permission-*.json"))
