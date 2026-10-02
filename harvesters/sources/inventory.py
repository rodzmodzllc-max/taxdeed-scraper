"""The unified source inventory: every source the project knows about, for
every supported state, in the one shape of `model.UnifiedSource`.

Built (no network, no database) from what the repository already records:

  registry     data/county_source_registry.csv - inventory lists per county
  parcel       harvesters/enrichment/sources.py - parcel / tax-roll layers
  builtin      the federal / statewide datasets the enrichers already call
               (FEMA NFHL, USDA NAIP, Census geocoder, Florida statewide cadastral)
  evidence     data/purchase_path_evidence*.csv - verified official acquisition pages
  candidate    data/acquisition_candidate_pages.csv + the last capture outcome
               per county (data/acquisition_capture_outcomes.csv)
  catalog      data/enrichment_source_catalog.csv - known sources not yet used
               (REVIEW_REQUIRED / HARD_BLOCKED), each with its documented basis

`build_inventory()` returns them all; `sources_for(state, county)` is what the
engine and the coverage matrix read; `inventory_problems()` validates it.
"""
from __future__ import annotations

import csv
from functools import lru_cache
from pathlib import Path

from harvesters.governance import states as ST
from harvesters.governance.county_source_registry import BLOCKED_SOURCE_IDS, load_registry

from .model import NATIONAL, STATEWIDE, UnifiedSource, governance_from_publication

REPO = Path(__file__).resolve().parent.parent.parent
CATALOG_PATH = REPO / "data" / "enrichment_source_catalog.csv"
CANDIDATES_PATH = REPO / "data" / "acquisition_candidate_pages.csv"
CAPTURE_OUTCOMES_PATH = REPO / "data" / "acquisition_capture_outcomes.csv"
EVIDENCE_PATHS = (REPO / "data" / "purchase_path_evidence.csv", REPO / "data" / "purchase_path_evidence_expansion.csv")

# Registry source_authority -> unified source type.
_AUTHORITY_TYPE = {"VENDOR_AUCTION": "AUCTION_VENDOR", "VENDOR_COUNSEL": "THIRD_PARTY",
                   "GOVERNMENT_DIRECT": "GOVERNMENT", "GOVERNMENT_PLATFORM": "GOVERNMENT"}
_DOCUMENT_FORMATS = {"PDF", "XLSX", "DOCX", "CSV"}
_LEDGER_ROLES = {"AVAILABLE": {"availability", "identity", "lifecycle", "source_date"},
                 "AUCTIONS": {"identity", "lifecycle"}, "LIENS_CERTIFICATES": {"identity", "lifecycle"}}
# A parcel-config column -> the customer dimension it fills.
_COLUMN_ROLE = {"assessed": "assessment", "market": "assessment", "land_value": "assessment",
                "improvement_value": "assessment", "taxable_value": "assessment", "legal_desc": "legal",
                "acreage": "acreage", "land_use": "land_use", "prop_type": "land_use", "owner_name": "identity",
                "address": "identity", "year_built": "assessment", "living_area": "assessment"}


def supported_states() -> list[str]:
    """Every state the repository registers (activated or not), sorted."""
    return sorted(ST.supported_states())


def production_states() -> list[str]:
    return sorted(ST.PRODUCTION_STATES)


def _csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def _registry_sources() -> list[UnifiedSource]:
    out = []
    for r in load_registry():
        blocked = r.source_id in BLOCKED_SOURCE_IDS or r.governance_status == "BLOCKED"
        gov, why = governance_from_publication("BLOCKED" if blocked else r.publication_status, source_id=r.source_id)
        stype = _AUTHORITY_TYPE.get(r.source_authority, "THIRD_PARTY" if blocked else "GOVERNMENT")
        if stype == "GOVERNMENT" and r.machine_format in _DOCUMENT_FORMATS:
            stype = "DOCUMENT"
        roles = set()
        for ledger in r.ledger_set:
            roles |= _LEDGER_ROLES.get(ledger, set())
        if not roles:
            roles = {"discovery"}
        if r.purchase_url or r.purchase_path_evidence:
            roles.add("acquisition")
        if gov == "HARD_BLOCKED":
            access, note = "NOT_ACCESSED_BLOCKED", "never requested (blocked vendor)"
        elif r.verification_status == "PRODUCTION_VERIFIED":
            access, note = "ACCESSIBLE", f"production harvester {r.harvester or '-'}; last completeness {r.completeness_status}"
        else:
            access, note = "NOT_CHECKED", f"verification {r.verification_status}"
        next_action = ("" if gov == "APPROVED" else
                       "None - excluded under the blocked-vendor rule" if gov == "HARD_BLOCKED" else
                       "Publication / rights review (registry restrictions: " + (r.restrictions or "none recorded") + ")")
        out.append(UnifiedSource(
            source_id=f"{r.state}:{r.county}:{r.source_id or 'unharvested_list'}", state=r.state, county=r.county,
            name=r.source_terminology or r.source_id or "county list", publisher=r.publishing_unit_name or r.source_authority or "",
            source_type=stype, url=r.canonical_url or r.document_url or "", roles=frozenset(roles), governance=gov,
            governance_reason="" if gov == "APPROVED" else why, access=access, access_note=note,
            evidence=r.evidence_ref, last_checked=r.last_checked, next_action=next_action, origin="registry",
            legacy_status=r.publication_status or r.governance_status))
    return out


def _parcel_sources() -> list[UnifiedSource]:
    from harvesters.enrichment.parcels import enrichment_allowed
    from harvesters.enrichment.sources import all_sources
    out = []
    for cfg in all_sources():
        gov, why = governance_from_publication(cfg.publication_status, source_id=cfg.source_id)
        roles = {"identity"} | {_COLUMN_ROLE[c] for c in cfg.field_map if c in _COLUMN_ROLE}
        if cfg.centroid:
            roles.add("coordinates")
        ok, allowed_why = enrichment_allowed(cfg)
        access = "ACCESSIBLE" if cfg.columns_verified else "NOT_CHECKED"
        scope = ",".join(cfg.counties) if cfg.counties else STATEWIDE
        out.append(UnifiedSource(
            source_id=cfg.source_id, state=cfg.state, county=scope if not cfg.counties or len(cfg.counties) > 1 else cfg.counties[0],
            name=cfg.dataset, publisher=cfg.agency, source_type="GIS", url=cfg.landing_url, roles=frozenset(roles),
            governance=gov, governance_reason="" if gov == "APPROVED" else f"{why}; licence: {cfg.licence}",
            access=access, access_note=("columns verified live; " + cfg.notes) if cfg.columns_verified else "columns not verified",
            evidence=cfg.notes, last_checked="", next_action="" if ok else f"enrichment refused: {allowed_why}",
            origin="parcel_config", legacy_status=cfg.publication_status))
    return out


def _builtin_sources() -> list[UnifiedSource]:
    return [
        UnifiedSource("fema_nfhl", NATIONAL, NATIONAL, "National Flood Hazard Layer", "FEMA", "FEDERAL_DATASET",
                      "https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer", frozenset({"flood"}),
                      access="ACCESSIBLE", access_note="scripts/enrich_flood_zone.py; needs coordinates",
                      evidence="federal public-domain dataset", origin="builtin", governance="APPROVED"),
        UnifiedSource("usda_naip", NATIONAL, NATIONAL, "NAIP aerial imagery (USGS National Map)", "USDA / USGS",
                      "FEDERAL_DATASET", "https://imagery.nationalmap.gov/", frozenset({"imagery"}), access="ACCESSIBLE",
                      access_note="scripts/enrich_property_photos_naip.py; needs coordinates; 950 MB storage budget",
                      evidence="federal public-domain imagery", origin="builtin", governance="APPROVED"),
        UnifiedSource("census_geocoder", NATIONAL, NATIONAL, "Census Bureau Geocoder", "US Census Bureau", "FEDERAL_DATASET",
                      "https://geocoding.geo.census.gov/", frozenset({"coordinates"}), access="ACCESSIBLE",
                      access_note="scripts/geocode_properties.py; needs a street address", evidence="federal service",
                      origin="builtin", governance="APPROVED"),
        UnifiedSource("fl_statewide_cadastral", "FL", STATEWIDE, "Florida Statewide Cadastral (FDOR NAL on parcels)",
                      "Florida Department of Revenue / Florida Geographic Information Office", "GIS",
                      "https://services9.arcgis.com/Gh9awoU677aKree0/arcgis/rest/services/",
                      frozenset({"identity", "assessment", "legal", "acreage", "land_use", "coordinates"}),
                      access="ACCESSIBLE", access_note="scripts/enrich_property_details.py (FDOR)",
                      evidence="scripts/enrich_property_details.py module docstring", origin="builtin", governance="APPROVED"),
    ]


def _evidence_sources() -> list[UnifiedSource]:
    out, seen = [], set()
    for path in EVIDENCE_PATHS:
        for r in _csv(path):
            if (r.get("review_state") or "").strip() != "verified" or not r.get("evidence_url"):
                continue
            key = (r["state"], r["county"], r["evidence_url"])
            if key in seen:
                continue
            seen.add(key)
            stype = "DOCUMENT" if r.get("evidence_type") == "county_document" else "GOVERNMENT"
            out.append(UnifiedSource(
                source_id=f"evidence:{r['state']}:{r['county']}:{len(seen)}", state=r["state"], county=r["county"],
                name=r.get("source_title") or "official acquisition page", publisher=r.get("office") or "county office",
                source_type=stype, url=r["evidence_url"], roles=frozenset({"acquisition", "source_date"}),
                access="ACCESSIBLE", access_note=f"verified capture, observed {r.get('observed_on')}",
                evidence=(r.get("notes") or "")[:240], last_checked=r.get("observed_on") or "", origin="evidence", governance="APPROVED"))
    return out


def _candidate_sources() -> list[UnifiedSource]:
    outcomes = {(r["state"], r["county"]): r for r in _csv(CAPTURE_OUTCOMES_PATH)}
    out = []
    for i, r in enumerate(_csv(CANDIDATES_PATH)):
        oc = outcomes.get((r["state"], r["county"]))
        access = "SOURCE_UNAVAILABLE" if oc and oc["capture_outcome"] == "SOURCE_UNAVAILABLE" else (
            "ACCESSIBLE" if oc else "NOT_CHECKED")
        stype = "DOCUMENT" if r["url"].lower().endswith(".pdf") else "GOVERNMENT"
        out.append(UnifiedSource(
            source_id=f"candidate:{r['state']}:{r['county']}:{i}", state=r["state"], county=r["county"],
            name=r.get("note") or "official page", publisher="county office", source_type=stype, url=r["url"],
            roles=frozenset({"acquisition", "discovery"}), access=access,
            access_note=(f"{oc['capture_outcome']}: {oc['reason']}" if oc else "not captured yet"),
            evidence=(oc or {}).get("evidence") or r.get("found_via", ""), last_checked="2026-10-01" if oc else "",
            next_action=("Manual review of the page (automated capture refused)" if access == "SOURCE_UNAVAILABLE" else
                         "Look for a separate Lands Available / resale process document" if oc else
                         "Capture with job=evidence, evidence_scope=acquisition_candidates"),
            origin="candidate", governance="APPROVED"))
    return out


def _catalog_sources() -> list[UnifiedSource]:
    out = []
    for r in _csv(CATALOG_PATH):
        out.append(UnifiedSource(
            source_id=r["source_id"], state=r["state"], county=r["county"], name=r["name"], publisher=r["publisher"],
            source_type=r["source_type"], url=r["url"], roles=frozenset(x for x in r["roles"].split("|") if x),
            governance=r["governance"], governance_reason=r["governance_reason"], access=r["access"],
            access_note=r["access_note"], evidence=r["evidence"], last_checked=r["last_checked"],
            next_action=r["next_action"], origin="catalog", legacy_status=r["governance"]))
    return out


@lru_cache(maxsize=1)
def build_inventory() -> tuple[UnifiedSource, ...]:
    registry = _registry_sources()
    # A catalog candidate that has graduated to a registry source (its
    # source_id is now a registry row) is that registry source - listed once.
    graduated = {s.source_id.split(":")[-1] for s in registry}
    catalog = [s for s in _catalog_sources() if s.source_id not in graduated]
    return tuple(registry + _parcel_sources() + _builtin_sources() + _evidence_sources()
                 + _candidate_sources() + catalog)


def sources_for(state: str, county: str, inventory=None) -> list[UnifiedSource]:
    inv = build_inventory() if inventory is None else inventory
    return [s for s in inv if s.covers(state, county) or (s.state == state and county in s.county.split(","))]


def inventory_problems(inventory=None) -> list[str]:
    inv = build_inventory() if inventory is None else inventory
    problems = []
    ids = [s.source_id for s in inv]
    dupes = {i for i in ids if ids.count(i) > 1}
    if dupes:
        problems.append(f"duplicate source ids: {sorted(dupes)[:5]}")
    known = set(supported_states()) | {NATIONAL}
    for s in inv:
        if s.state not in known:
            problems.append(f"{s.source_id}: state {s.state} is not a supported state")
        if s.governance == "HARD_BLOCKED" and s.url and s.origin != "registry":
            problems.append(f"{s.source_id}: a HARD_BLOCKED catalog entry carries no URL to request")
    for st in supported_states():
        if not [s for s in inv if s.state == st]:
            problems.append(f"{st}: no source recorded for a supported state")
    return problems


def summary(inventory=None) -> dict:
    inv = build_inventory() if inventory is None else inventory
    by = {}
    for s in inv:
        key = s.state
        b = by.setdefault(key, {"sources": 0, "APPROVED": 0, "REVIEW_REQUIRED": 0, "HARD_BLOCKED": 0, "by_type": {}})
        b["sources"] += 1
        b[s.governance] += 1
        b["by_type"][s.source_type] = b["by_type"].get(s.source_type, 0) + 1
    return by
