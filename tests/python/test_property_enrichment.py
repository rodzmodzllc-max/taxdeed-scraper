"""Property-enrichment sprint (2026-10-01): the new sources and evidence are
exactly what was read live, cleared, and nothing more."""
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from harvesters.enrichment import parcels as P  # noqa: E402
from harvesters.enrichment.sources import PARCEL_SOURCES, for_state  # noqa: E402
import purchase_path_engine as PE  # noqa: E402


def test_la_tax_parcels_config_is_public_domain_socrata_exact_match():
    cfg = for_state("LA")
    assert cfg.source_id == "la_ebr_tax_parcels" and cfg.transport == "socrata" and cfg.publication_status == "APPROVED"
    assert cfg.layer_url == "https://data.brla.gov/resource/ei2c-krsr.json" and "Public Domain" in cfg.licence
    assert cfg.id_field == "assessment_num" and cfg.id_rule == "exact" and cfg.county_field is None and not cfg.centroid
    # only attributes seen populated in the live sample are mapped
    assert set(cfg.field_map.values()) == {"sum_land_value", "sum_fair_market_value", "sum_assessed_value"}
    assert P.enrichment_allowed(cfg)[0]
    [url] = P.query_urls(cfg, "East Baton Rouge", ["123-4567-8", "123-4567-8"])
    q = parse_qs(urlsplit(url).query)
    assert q["$where"] == ["assessment_num in('123-4567-8')"]


def test_la_tax_parcel_match_fails_closed_on_duplicates_and_maps_land_value():
    cfg = for_state("LA")
    recs = [{"attributes": {"assessment_num": "123-4567-8", "sum_land_value": "15000", "sum_fair_market_value": "90000"}},
            {"attributes": {"assessment_num": "222-2222-2", "sum_land_value": "1"}},
            {"attributes": {"assessment_num": "222-2222-2", "sum_land_value": "2"}}]
    idx = P.index_features(cfg, recs)
    got = {m.row_id: m for m in P.match_rows(cfg, [{"id": "a", "county": "East Baton Rouge", "parcel": "123-4567-8"},
                                                   {"id": "b", "county": "East Baton Rouge", "parcel": "222-2222-2"}], idx)}
    assert got["a"].status == "MATCHED" and got["b"].status == "AMBIGUOUS"
    fields, prov = P.plan_update(cfg, {"id": "a"}, got["a"], recorded_at="t")
    assert fields == {"land_value": 15000, "market": 90000}
    assert prov["land_value"]["source"] == "statewide_parcel" and prov["land_value"]["source_id"] == "la_ebr_tax_parcels"


def test_unreviewed_or_unreachable_sources_are_not_configured():
    # TxGIO StratMap (public-domain programme statement, but no answer to any query from the
    # runners), Wyoming's statewide viewer (disclaimer only), Michigan county parcels
    # (disclaimer / click-through licence) - none is a configured, usable source.
    assert "TX" not in PARCEL_SOURCES and "WY" not in PARCEL_SOURCES and "MI" not in PARCEL_SOURCES
    assert PARCEL_SOURCES["WI"].publication_status == "UNREVIEWED" and not P.enrichment_allowed(PARCEL_SOURCES["WI"])[0]


def test_la_acquisition_evidence_is_the_parish_attorney_process_at_source_scope():
    [la] = [e for e in PE.load_evidence() if e.state == "LA"]
    assert la.applicable and PE.evidence_problems(la) == []
    assert la.source_id == "la_ebr_adjudicated" and la.path_type == "county_instructions" and not la.third_party_permitted
    assert "Office of the Parish Attorney handles these sales" in la.instructions
    assert "remains adjudicated" in la.instructions and "civicsource" not in la.url.lower()
    assert not la.phone and "No phone recorded" in la.notes                                  # nothing attributed, nothing invented
    path, reasons = PE.resolve({"case_no": "123-4567-8", "county": "East Baton Rouge"}, state="LA", source_id="la_ebr_adjudicated",
                               county="East Baton Rouge", evidence=PE.load_evidence(),
                               registry_row={"canonical_url": "https://data.brla.gov/Housing-and-Development/Adjudicated-Property/a4h4-zi7e"})
    assert reasons == [] and path.scope == "source" and path.url == "https://www.brla.gov/455/Adjudicated-Property"
    assert not PE.complete_record(path.acquisition())                                         # no contact channel -> not "complete"
