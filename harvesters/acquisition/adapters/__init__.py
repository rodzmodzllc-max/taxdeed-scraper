"""Concrete source adapters - Phase 39 Section 4.

Two mechanisms are implemented this phase, chosen because each one serves
MANY jurisdictions from a single implementation (Section 46's statewide/
multi-county optimization preference):

  - `json_api.LgbsAdapter`  - paginated JSON REST. Serves `tx_lgbs`, a
    multi-county Texas source (6,309 rows live as of 2026-09-16).
  - `arcgis.ArcGisAdapter`  - unauthenticated ArcGIS REST parcel layers.
    Serves every CAD and county GIS portal that speaks ArcGIS, which is
    most of them in both states; two are configured (HCAD, TAD) and adding
    a third is a `CadLayerConfig` entry, not a new module.

Mechanisms deliberately NOT implemented this phase, each with a real
reason recorded rather than a stub left lying around (Section 23's "do not
implement a speculative scraper simply to eliminate the stub"):

  - DOCUMENT_PDF - `fl_laft_pdfs` already has a working production
    implementation (`scripts/harvest_laft_pdfs.py`); re-implementing it
    behind this contract with no behavioral gain would violate Section 10's
    "do not rewrite the Florida harvesters merely for architectural
    cleanliness". Its migration path is documented in
    `docs/acquisition-engine.md`.
  - HTML_PUBLIC_SEARCH - the mechanism behind `fl_realauction`/
    `tx_realauction`/`fl_lienhub_certificates`, all of which are
    LEGAL_REVIEW_REQUIRED for production use under Phase 34A/37 and are
    already served by working production harvesters. Building a new
    acquisition path for them would be engineering effort spent on sources
    whose blocker is legal, not technical.
  - BULK_DOWNLOAD - `fl_dor_statewide` is the highest-value target for
    this mechanism and is this phase's recommended next build; it was not
    implemented here because the portal URL recorded in the registry was
    found to be stale this phase (see `docs/florida-acquisition.md`) and
    the real file-level download contract has not yet been verified.
"""

from .arcgis import CAD_LAYERS, ArcGisAdapter, CadLayerConfig, HCAD_LAYER, TAD_LAYER
from .json_api import LGBS_CONFIG, JsonApiAdapter, LgbsAdapter

__all__ = [
    "ArcGisAdapter",
    "CAD_LAYERS",
    "CadLayerConfig",
    "HCAD_LAYER",
    "TAD_LAYER",
    "JsonApiAdapter",
    "LGBS_CONFIG",
    "LgbsAdapter",
]
