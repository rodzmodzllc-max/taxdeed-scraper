"""Front-end follow-ups to the 2026-10-26 source sprints (owner approval
2026-10-27): the app.js source tables cover every source that produces rows.

* CAUSE_IN_PARCEL_SOURCES (app.js) == harvesters/ledgers/records.py's;
* every collected source id has a publisher label (HARVESTER_SOURCE_NAMES);
* SOURCE_ID_LEDGERS (app.js) == harvesters/ledgers SOURCE_LEDGERS;
* every Available source outside Florida names its program (AVAILABLE_PROGRAMS);
* Wright County MN is scheduled and the MN auctions ledger is tracked.
"""
from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from harvesters.ledgers import Ledger, SOURCE_LEDGERS  # noqa: E402
from harvesters.ledgers import records as LR  # noqa: E402
from harvesters.otc.adapters import expansion as EX  # noqa: E402

APP = (REPO / "public" / "app.js").read_text(encoding="utf-8")


def _obj(decl: str) -> str:
    start = APP.index(decl)
    return APP[start:APP.index("\n};", start)]


def _obj_keys(decl: str) -> set[str]:
    return set(re.findall(r"(?:^\s*|,\s*)(\w+):", _obj(decl), re.M))


def _collected_source_ids() -> set[str]:
    with (REPO / "data" / "county_source_registry.csv").open(newline="", encoding="utf-8") as fh:
        prod = {r["source_id"] for r in csv.DictReader(fh) if r["verification_status"] == "PRODUCTION_VERIFIED"}
    return prod | set(EX.NEW_SOURCE_IDS) | set(EX.OWNER_APPROVED_2026_10_26_SOURCE_IDS) | set(SOURCE_LEDGERS)


def test_cause_in_parcel_sources_js_equals_python():
    js = re.search(r"var CAUSE_IN_PARCEL_SOURCES = \[(.*?)\];", APP).group(1)
    assert set(re.findall(r'"(\w+)"', js)) == set(LR.CAUSE_IN_PARCEL_SOURCES)
    assert {"tx_pbfcm", "tx_mvba", "tx_govease"} <= set(LR.CAUSE_IN_PARCEL_SOURCES)
    # causeInParcel() reads the list, never a second inline copy.
    body = APP[APP.index("function causeInParcel(p)"):APP.index("function parcelOf(p)")]
    assert "CAUSE_IN_PARCEL_SOURCES" in body and '"tx_lgbs"' not in body


def test_every_collected_source_has_a_publisher_label():
    labels = _obj_keys("const HARVESTER_SOURCE_NAMES = {")
    missing = sorted(_collected_source_ids() - labels)
    assert not missing, f"no HARVESTER_SOURCE_NAMES label for {missing}"


def test_source_id_ledgers_js_equals_python():
    k = {"AUCTIONS": "auction", "AVAILABLE": "laft", "LIENS_CERTIFICATES": "certificate"}
    js = {a: set(re.findall(r'"(\w+)"', b)) for a, b in re.findall(r"(\w+): \[([^\]]*)\]", _obj("const SOURCE_ID_LEDGERS = {"))}
    py = {sid: {k[l.value] for l in v} for sid, v in SOURCE_LEDGERS.items()}
    assert js == py


def test_every_available_source_outside_florida_names_its_program():
    programs = _obj_keys("var AVAILABLE_PROGRAMS = {")
    avail = {sid for sid, v in SOURCE_LEDGERS.items() if Ledger.AVAILABLE in v and not sid.startswith("fl_")}
    missing = sorted(avail - programs)
    assert not missing, f"no AVAILABLE_PROGRAMS entry for {missing}"


def test_epropertyplus_tenants_publish_their_own_points():
    from harvesters.sources import coordinates as C
    for cfg in EX.NEW_EPP_SOURCES + (EX.TN_SHELBY_LANDBANK,):
        assert cfg.source_id in C.SOURCE_COORDINATES, cfg.source_id
        assert C.SOURCE_COORDINATES[cfg.source_id][1] == "POINT"


def test_wright_mn_is_scheduled_and_mn_auctions_tracked():
    assert EX.MN_WRIGHT_TAX_FORFEIT in EX.NEW_TABLE_SOURCES
    assert "mn_wright_tax_forfeit" in {s.config.source_id for s in EX.SOURCES["MN"]}
    assert "mn_wright_tax_forfeit" in EX.NEW_SOURCE_IDS
    assert SOURCE_LEDGERS["mn_wright_tax_forfeit"] == frozenset({Ledger.AUCTIONS})
    with (REPO / "data" / "state_ledgers.csv").open(newline="", encoding="utf-8") as fh:
        mn = {r["ledger"]: r for r in csv.DictReader(fh) if r["state"] == "MN"}
    assert mn["AUCTIONS"]["status"] == "TRACKED"
    copy = _obj("const EXPANSION_LEDGER_COPY = {")
    assert "No Minnesota auction source is tracked." not in copy
