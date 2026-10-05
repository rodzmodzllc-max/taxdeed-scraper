"""Detroit customer-facing subset (2026-10-03).

harvesters/otc/detroit_subset.py is a VISIBILITY stage between the full
collected inventory and the publication gate. These tests pin the rule
itself, its determinism and ~50% share, that it never touches a row or any
source outside the two Detroit Land Bank sources, that the collection reads
the one verified-structure status, and that public/app.js mirrors it.
"""
from __future__ import annotations

import copy
import csv
import json
import random
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from harvesters.otc import detroit_subset as D  # noqa: E402
from harvesters.otc.adapters import arcgis as AG  # noqa: E402
from harvesters.otc.adapters import expansion as EX  # noqa: E402

APP = (REPO / "public" / "app.js").read_text(encoding="utf-8")
CASES = json.loads((REPO / "tests" / "python" / "fixtures" / "detroit_subset_cases.json").read_text(encoding="utf-8"))
REGISTRY = list(csv.DictReader((REPO / "data" / "county_source_registry.csv").open(encoding="utf-8")))
LOTS, PROGRAMS = "mi_detroit_landbank_lots", "mi_detroit_landbank_programs"


def _row(sid, parcel, status, **kw):
    return {"id": f"{sid}:{parcel}", "source_id": sid, "source": "laft", "parcel": parcel, "case_no": parcel,
            "inventory_status_raw": status, "status": "active", "publication_status": "UNREVIEWED", **kw}


def _detroit_population(n=6000, seed=11):
    """A synthetic Detroit population in the real parcel shapes (99999999. /
    99999999-9 / 99999999.999), mixed lot and structure statuses."""
    rnd = random.Random(seed)
    rows = []
    for i in range(n):
        base = 10000000 + rnd.randrange(80000000)
        parcel = rnd.choice([f"{base}.", f"{base}-{i % 10}", f"{base}.{i % 1000:03d}"])
        status = rnd.choice(EX.DLBA_LOT_STATUSES + EX.DLBA_STRUCTURE_STATUSES * 2)
        rows.append(_row(LOTS, parcel, status))
    rows += [_row(PROGRAMS, f"{20000000 + i}.", p) for i, p in enumerate(("Own It Now", "Renovation Programs", "Economic Development"))]
    return rows


# --- 1. only verified-structure records reach the customer inventory -----------

def test_customer_inventory_holds_only_detroit_rows_with_the_sources_own_structure_status():
    rows = _detroit_population()
    cust = [r for r in D.customer_inventory(rows) if D.is_detroit(r)]
    assert cust, "the subset must not be empty for a population with structures"
    assert all(r["source_id"] == LOTS and r["inventory_status_raw"] == "Marketed Structure For Sale" for r in cust)
    # vacant lots and program records (no structure field) never qualify
    for status in EX.DLBA_LOT_STATUSES:
        assert D.subset_status(_row(LOTS, "12345678.", status)) == D.NOT_STRUCTURE
    for prog in ("Own It Now", "Renovation Programs", "Economic Development"):
        assert D.subset_status(_row(PROGRAMS, "12345678.", prog)) == D.NOT_STRUCTURE
    # a structure WORD elsewhere (an address, a program name) is not evidence
    assert D.subset_status(_row(LOTS, "12345678.", "Side Lot For Sale", address="1 STRUCTURE ST")) == D.NOT_STRUCTURE
    assert D.subset_status(_row(PROGRAMS, "12345678.", "Marketed Structure For Sale")) == D.NOT_STRUCTURE


# --- 2 / 4. deterministic: same ids, any order, any run ------------------------

def test_selection_is_deterministic_and_independent_of_row_order():
    rows = _detroit_population()
    first = [r["id"] for r in D.customer_inventory(rows)]
    second = [r["id"] for r in D.customer_inventory(copy.deepcopy(rows))]
    assert first == second
    shuffled = copy.deepcopy(rows)
    random.Random(99).shuffle(shuffled)
    assert sorted(r["id"] for r in D.customer_inventory(shuffled)) == sorted(first)


def test_the_hash_is_standard_fnv1a_and_the_shared_vectors_hold():
    assert D.fnv1a32("") == 0x811C9DC5 and D.fnv1a32("a") == 0xE40C292C and D.fnv1a32("foobar") == 0xBF9CF968
    for c in CASES:
        assert D.fnv1a32(D.selection_key(c["source_id"], c["parcel"])) == c["hash"], c["parcel"]
        assert D.subset_status(c) == c["expected"], c["parcel"]
    assert {c["expected"] for c in CASES} == {None, D.IN_SUBSET, D.NOT_SELECTED, D.NOT_STRUCTURE}


# --- 3. approximately half of the structure-qualified inventory ---------------

def test_subset_is_about_half_of_the_structure_qualified_inventory():
    rows = _detroit_population(20000)
    s = D.summary(rows)
    assert s["structure_qualified"] > 5000
    share = s["customer_subset"] / s["structure_qualified"]
    assert 0.47 <= share <= 0.53, share


# --- 5 / 6. excluded rows stay collected, untouched, admin-visible -------------

def test_the_subset_never_mutates_closes_or_drops_a_row():
    rows = _detroit_population(500)
    before = copy.deepcopy(rows)
    D.customer_inventory(rows)
    D.summary(rows)
    [D.subset_status(r) for r in rows]
    assert rows == before                                  # status, publication_status, everything unchanged
    assert all(r["status"] == "active" and r["publication_status"] == "UNREVIEWED" for r in rows)


def test_no_collection_sync_or_lifecycle_code_uses_the_subset():
    """The subset is a view rule: nothing that writes rows may import it."""
    imports = re.compile(r"^\s*(?:from\s+\S*\s+import\s+[^\n]*\bdetroit_subset\b|import\s+\S*detroit_subset\b|from\s+\S*detroit_subset\s+import)", re.M)
    users = [p.relative_to(REPO).as_posix() for root in ("scripts", "harvesters") for p in (REPO / root).rglob("*.py")
             if p.name != "detroit_subset.py" and imports.search(p.read_text(encoding="utf-8"))]
    assert users == []


def test_frontend_admin_sees_everything_and_the_subset_runs_before_the_publication_gate():
    fn = APP[APP.index("function isPublishable(p)"):APP.index("function sourceReviewLabel")]
    order = [fn.index('p.publication_status === "BLOCKED"'), fn.index("if (IS_ADMIN) return true"),
             fn.index("if (!inCustomerInventory(p)) return false"), fn.index('isCustomerPublishable(p) || viewerScope() === "preview"')]
    assert order == sorted(order)
    load = APP[APP.index("DETROIT_SUMMARY = { collected: 0, structure: 0, subset: 0 };\n  ALL.forEach"):]
    assert "if (!IS_ADMIN && !inCustomerInventory(p)) return false;" in load[:2000]
    assert '"Not included in current Detroit customer subset' in APP


# --- 7-10. no other source is capped --------------------------------------------

@pytest.mark.parametrize("sid,parcel", [("mi_oceana_landbank", "64-001-001-001-00"), ("sc_horry_forfeited_land", "12345678901"),
                                        ("sc_georgetown_forfeited_land", "01-0001-001-01-01")])
def test_oceana_horry_and_georgetown_are_never_capped(sid, parcel):
    rows = [_row(sid, f"{parcel}{i}", None) for i in range(200)]
    assert all(D.subset_status(r) is None for r in rows)
    assert D.customer_inventory(rows) == rows


def test_every_registry_source_outside_detroit_is_outside_the_subset():
    for r in REGISTRY:
        row = _row(r["source_id"], "12345678.", "Marketed Structure For Sale")
        if r["source_id"] in (LOTS, PROGRAMS):
            continue
        assert D.subset_status(row) is None, r["source_id"]
    states = {r["state"] for r in REGISTRY if r["source_id"] not in (LOTS, PROGRAMS)}
    assert {"FL", "LA", "TX", "SC", "WY", "CO", "WI"} <= states
    assert D.DETROIT_SOURCE_IDS == {LOTS, PROGRAMS}


# --- collection and the frontend mirror ----------------------------------------

def test_collection_reads_the_offered_structure_status_and_keeps_it_verbatim():
    assert EX.DLBA_STRUCTURE_STATUSES == ("Marketed Structure For Sale",)
    assert set(EX.DLBA_STRUCTURE_STATUSES) == D.STRUCTURE_STATUSES
    where = AG.query_params(EX.MI_DETROIT_LANDBANK_LOTS)["where"]
    for s in EX.DLBA_LOT_STATUSES + EX.DLBA_STRUCTURE_STATUSES:
        assert f"'{s}'" in where
    assert "Owned" not in where
    payload = {"objectIdFieldName": "OBJECTID", "features": [
        {"attributes": {"OBJECTID": 1, "parcel_id": "99000102.", "name": "1 SYNTHETIC AVE",
                        "inventory_status_socrata": "Marketed Structure For Sale", "latitude": 42.3, "longitude": -83.1}}]}
    rec = AG.parse_page(EX.MI_DETROIT_LANDBANK_LOTS, payload, retrieved_at=__import__("datetime").datetime(2026, 10, 3)).records[0]
    row = rec.to_properties_row()
    assert row["inventory_status_raw"] == "Marketed Structure For Sale" and row["source"] == "laft"


def test_registry_row_for_detroit_is_unchanged_by_the_collection_change():
    lots = next(r for r in REGISTRY if r["source_id"] == LOTS)
    assert lots["publication_status"] == "UNREVIEWED"
    assert "only the four lot statuses ending 'For Sale' are read" in lots["notes"]     # text left as it was (no registry change)


def test_frontend_mirrors_the_python_rule():
    js_ids = re.search(r"const DETROIT_SOURCE_IDS = \[(.*?)\];", APP).group(1)
    assert set(re.findall(r'"([^"]+)"', js_ids)) == D.DETROIT_SOURCE_IDS
    assert re.search(r'const DETROIT_STRUCTURE_SOURCE_ID = "([^"]+)";', APP).group(1) == D.STRUCTURE_SOURCE_ID
    js_st = re.search(r"const DETROIT_STRUCTURE_STATUSES = \[(.*?)\];", APP).group(1)
    assert set(re.findall(r'"([^"]+)"', js_st)) == D.STRUCTURE_STATUSES
    assert int(re.search(r"const DETROIT_SUBSET_PERCENT = (\d+);", APP).group(1)) == D.SUBSET_PERCENT
    assert "h = Math.imul(h, 0x01000193) >>> 0" in APP and "let h = 0x811c9dc5;" in APP
