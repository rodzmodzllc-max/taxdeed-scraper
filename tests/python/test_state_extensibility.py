"""The generic supported-state mechanism (harvesters/governance/states.py)
and everything that now reads it instead of an FL/TX literal: the OTC
record contract, the county source registry validator/loader, and
scripts/laft_lifecycle.py.

FL and TX behaviour is asserted unchanged; a hypothetical third state is
registered for the duration of a test only (`states.registered`) and is
never a real one. Nothing here touches a network or the committed CSV.
"""
from __future__ import annotations

import csv
import json
import os
import sys
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

from harvesters.governance import county_source_registry as csr  # noqa: E402
from harvesters.governance import states  # noqa: E402
from harvesters.governance.states import STATEWIDE_UNIT, PublishingUnit, StateConfig  # noqa: E402
from harvesters.otc import (DB_SUPPORTED_AMOUNT_KINDS, DB_SUPPORTED_INVENTORY_TYPES, AmountKind, InventoryType,  # noqa: E402
                            OtcRecord, SourceAuthority)
import laft_lifecycle as L  # noqa: E402
import laft_status as ls  # noqa: E402

T = datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)
NOW = ls.now_iso()

ZZ = StateConfig(code="ZZ", name="Zetaland", publishing_units=(PublishingUnit.STATE.value, PublishingUnit.COUNTY.value),
                 production_inventory_types=frozenset({"STATE_HELD_TAX_LAND"}), lifecycle_inventory_type=None, production=False)
# The same hypothetical state fully ACTIVATED (every requirement satisfied in
# this fixture) - the only shape the lifecycle and the gate let run.
ZZ_ACTIVE = StateConfig(code="ZZ", name="Zetaland", publishing_units=(PublishingUnit.STATE.value, PublishingUnit.COUNTY.value),
                        production_inventory_types=frozenset({"STATE_HELD_TAX_LAND"}), lifecycle_inventory_type=None, production=True,
                        activation=states.ALL_REQUIREMENTS)
# A third state whose lifecycle asserts a type the DB can store (the FL shape, different state).
YY = StateConfig(code="YY", name="Yland", publishing_units=(PublishingUnit.PARISH.value,),
                 production_inventory_types=frozenset({"POST_SALE_FIXED_PRICE"}), lifecycle_inventory_type="POST_SALE_FIXED_PRICE",
                 lifecycle_inventory_basis="fixture basis", production=True, activation=states.ALL_REQUIREMENTS)


def _rec(**kw):
    base = dict(state="FL", county="Marion", case_no="A1", source_id="fl_laft_pdfs", source_authority=SourceAuthority.GOVERNMENT_DIRECT,
                inventory_type=InventoryType.POST_SALE_FIXED_PRICE, retrieved_at=T)
    base.update(kw)
    return OtcRecord(**base)


def _row(**kw) -> csr.CountySourceRow:
    base = dict(state="FL", county="Marion", source_id="fl_laft_pdfs", harvester="scripts/harvest_laft_pdfs.py",
                inventory_type="POST_SALE_FIXED_PRICE", source_authority="GOVERNMENT_DIRECT",
                canonical_url="https://example.invalid/list", document_url="", purchase_url="", purchase_url_kind="",
                access_method="HTTP_GET_PDF", machine_format="PDF", verification_status="PRODUCTION_VERIFIED",
                governance_status="APPROVED", last_checked="2026-09-29", completeness_status="COMPLETE",
                evidence_ref="fixture", notes="")
    base.update(kw)
    if base.get("publishing_unit") == "STATE":
        base.setdefault("publishing_unit_name", "Fixture agency")   # a STATE-level row names its publisher
    return csr.CountySourceRow(**base)


# ==================== 1. the state registry ====================


def test_st01_registered_and_production_states():
    # AL (2026-09-29) is REGISTERED (representable) but not PRODUCTION / activated.
    # LA became production on 2026-09-30 (state-expansion sprint).
    assert states.supported_states() == {"FL", "TX", "AL", "AR", "LA", "AZ", "MI", "WY", "SC", "CO", "WI", "WV", "UT"} and states.PRODUCTION_STATES == {"FL", "TX", "LA", "MI", "WY", "SC", "CO", "WI"}
    assert states.is_activated("FL") and states.is_activated("TX") and not states.is_activated("AL")
    assert states.activation_blockers("AL") == list(states.ACTIVATION_REQUIREMENTS)
    assert states.activation_blockers("FL") == [] and states.activation_blockers("QQ")[0] == "not_registered"
    assert states.FL.lifecycle_inventory_type == "POST_SALE_FIXED_PRICE" and states.FL.production_inventory_types == {"POST_SALE_FIXED_PRICE"}
    assert states.TX.lifecycle_inventory_type is None and states.TX.production_inventory_types == {"", "STRUCK_OFF_HELD_IN_TRUST", "FUTURE_RESALE"}
    assert states.FL.publishing_units == states.TX.publishing_units == ("COUNTY",)
    assert states.state_problems("FL") == [] and states.state_problems("TX") == []
    for bad in ("ZZ", "fl", "Florida", "", None, "F", "FLA"):
        assert states.state_problems(bad), bad


def test_st02_registered_is_temporary_and_cannot_shadow_a_production_state():
    assert not states.is_supported("ZZ")
    with states.registered(ZZ):
        assert states.is_supported("ZZ") and states.get_state("ZZ") is ZZ and states.state_problems("ZZ") == []
    assert not states.is_supported("ZZ") and states.get_state("ZZ") is None
    for code in ("FL", "TX"):
        with pytest.raises(ValueError, match="production state"):
            with states.registered(StateConfig(code=code, name="x", publishing_units=("COUNTY",), production_inventory_types=frozenset(),
                                               lifecycle_inventory_type=None, production=False)):
                pass
    assert states.get_state("FL") is states.FL


def test_st03_state_config_validates_itself():
    good = dict(name="x", publishing_units=("COUNTY",), production_inventory_types=frozenset(), lifecycle_inventory_type=None, production=False)
    for bad_code in ("fl", "F", "FLA", "1A"):
        with pytest.raises(ValueError):
            StateConfig(code=bad_code, **good)
    with pytest.raises(ValueError, match="publishing unit"):
        StateConfig(code="ZZ", **{**good, "publishing_units": ("DISTRICT",)})
    with pytest.raises(ValueError, match="at least one"):
        StateConfig(code="ZZ", **{**good, "publishing_units": ()})
    with pytest.raises(ValueError, match="go together"):
        StateConfig(code="ZZ", **{**good, "lifecycle_inventory_type": "POST_SALE_FIXED_PRICE"})
    assert {u.value for u in PublishingUnit} == {"COUNTY", "PARISH", "BOROUGH", "MUNICIPALITY", "STATE"}


# ==================== 2. OtcRecord ====================


def test_m01_fl_and_tx_records_validate_exactly_as_before():
    assert _rec().validate() == []
    assert _rec(state="TX", county="Camp", inventory_type=InventoryType.STRUCK_OFF_HELD_IN_TRUST, source_id="tx_camp").validate() == []
    row = _rec().to_properties_row()
    assert row["state"] == "FL" and row["inventory_type"] == "POST_SALE_FIXED_PRICE" and row["purchase_amount_kind"] == "NOT_PUBLISHED"


def test_m02_unregistered_and_malformed_states_are_rejected():
    for bad in ("ZZ", "fl", "Florida", "", "F"):
        problems = _rec(state=bad).validate()
        assert problems and ("not a registered state" in problems[0] or "two-letter" in problems[0]), bad
        with pytest.raises(ValueError):
            _rec(state=bad).to_properties_row()


def test_m03_a_registered_third_state_passes_validation_only_while_registered():
    with states.registered(ZZ):
        rec = _rec(state="ZZ", county=STATEWIDE_UNIT, source_id="zz_state_land", inventory_type=InventoryType.STATE_HELD_TAX_LAND)
        assert rec.validate() == []
        # ...and a registered state does not relax any other rule.
        assert _rec(state="ZZ", county="", inventory_type=InventoryType.STATE_HELD_TAX_LAND).validate() == ["county, case_no and source_id are required"]
        assert "a present amount cannot be NOT_PUBLISHED" in _rec(state="ZZ", amount=5).validate()
    assert _rec(state="ZZ").validate()


def test_m04_the_020_inventory_types_are_storable_and_the_guard_still_refuses_what_is_not(monkeypatch):
    # Migration 017 named three types; migration 020 (applied 2026-09-30) added three more.
    added = {InventoryType.POST_SALE, InventoryType.STATE_HELD_TAX_LAND, InventoryType.ADJUDICATED_PROPERTY}
    assert DB_SUPPORTED_INVENTORY_TYPES == {"POST_SALE_FIXED_PRICE", "STRUCK_OFF_HELD_IN_TRUST", "FUTURE_RESALE"} | {i.value for i in added}
    sql = (REPO / "scripts/migrations/017_otc_inventory_provenance_lifecycle.sql").read_text(encoding="utf-8")
    sql020 = (REPO / "scripts/migrations/020_state_extensible_vocabulary.sql").read_text(encoding="utf-8")
    for i in added:
        assert f"'{i.value}'" not in sql and f"'{i.value}'" in sql020
        rec = _rec(inventory_type=i)
        assert rec.validate() == []
        assert rec.to_properties_row()["inventory_type"] == i.value
    # The guard itself: a type outside the storable set is refused before any write.
    import harvesters.otc.model as model
    monkeypatch.setattr(model, "DB_SUPPORTED_INVENTORY_TYPES", model.DB_SUPPORTED_INVENTORY_TYPES - {"POST_SALE"})
    with pytest.raises(ValueError, match="not storable"):
        _rec(inventory_type=InventoryType.POST_SALE).to_properties_row()
    monkeypatch.undo()
    for i in (InventoryType.POST_SALE_FIXED_PRICE, InventoryType.STRUCK_OFF_HELD_IN_TRUST, InventoryType.FUTURE_RESALE):
        assert _rec(inventory_type=i).to_properties_row()["inventory_type"] == i.value
    assert _rec(inventory_type=None).to_properties_row()["inventory_type"] is None


def test_m05_quoted_on_application_carries_no_amount_and_is_storable_since_020(monkeypatch):
    assert DB_SUPPORTED_AMOUNT_KINDS == set(ls.DB_AMOUNT_KINDS) and "QUOTED_ON_APPLICATION" in DB_SUPPORTED_AMOUNT_KINDS
    assert "QUOTED_ON_APPLICATION" in ls.AMOUNT_KINDS and ls.AMOUNT_KINDS.index("QUOTED_ON_APPLICATION") == len(ls.AMOUNT_KINDS) - 1
    sql = (REPO / "scripts/migrations/017_otc_inventory_provenance_lifecycle.sql").read_text(encoding="utf-8")
    assert "'QUOTED_ON_APPLICATION'" not in sql
    assert "'QUOTED_ON_APPLICATION'" in (REPO / "scripts/migrations/020_state_extensible_vocabulary.sql").read_text(encoding="utf-8")
    rec = _rec(amount=None, amount_kind=AmountKind.QUOTED_ON_APPLICATION)
    assert rec.validate() == []
    assert "a present amount cannot be QUOTED_ON_APPLICATION" in _rec(amount=100, amount_kind=AmountKind.QUOTED_ON_APPLICATION).validate()
    assert "an absent amount must be NOT_PUBLISHED or QUOTED_ON_APPLICATION" in _rec(amount=None, amount_kind=AmountKind.FIXED_PURCHASE_PRICE).validate()
    assert rec.to_properties_row()["purchase_amount_kind"] == "QUOTED_ON_APPLICATION"
    import harvesters.otc.model as model
    with monkeypatch.context() as m:
        m.setattr(model, "DB_SUPPORTED_AMOUNT_KINDS", model.DB_SUPPORTED_AMOUNT_KINDS - {"QUOTED_ON_APPLICATION"})
        with pytest.raises(ValueError, match="QUOTED_ON_APPLICATION is not storable"):
            rec.to_properties_row()
    assert _rec(amount=None, amount_kind=AmountKind.NOT_PUBLISHED).to_properties_row()["purchase_amount_kind"] == "NOT_PUBLISHED"
    # No FL harvester emits it. A row claiming it next to a figure is downgraded to the
    # honest DB value (the quoted kind carries no figure); with no figure it is kept now
    # that it is storable, and falls back to NOT_PUBLISHED where it is not.
    assert L.amount_of({"bid": "12", "bid_kind": "QUOTED_ON_APPLICATION"}) == (12.0, "PUBLISHED_AMOUNT_KIND_UNSPECIFIED")
    assert L.amount_of({"bid": "", "bid_kind": "QUOTED_ON_APPLICATION"}) == (None, "QUOTED_ON_APPLICATION")
    assert L.amount_of({"bid": "", "bid_kind": "QUOTED_ON_APPLICATION"}, storable_kinds=ls.AMOUNT_KINDS[:7]) == (None, "NOT_PUBLISHED")
    assert ls.AMOUNT_KIND_BY_HEADER and "QUOTED_ON_APPLICATION" not in ls.AMOUNT_KIND_BY_HEADER.values()


# ==================== 3. registry ====================


def test_r01_committed_registry_is_unchanged_county_level_and_still_valid():
    rows = csr.load_registry()
    # 110 = the 109 FL/TX rows unchanged + ONE Alabama state-level candidate (2026-09-29).
    # 112 = the 109 FL/TX rows unchanged + Alabama, Arkansas (STATE-level) and Louisiana (PARISH-level) candidates.
    # 216 (2026-09-30, three ledgers) = the 109 FL/TX AVAILABLE rows unchanged + Alabama, Arkansas,
    # Louisiana candidates + the AUCTIONS (47 FL, 24 TX) and LIENS & CERTIFICATES (32 FL) production
    # sources the registry now carries + ONE Arizona LIENS & CERTIFICATES candidate.
    # 222 (2026-09-30, six-state expansion) = 216 + the six owner-approved county sources of
    # MI (2), WY, SC, CO, WI (harvesters/otc/adapters/expansion.py).
    # 227 (2026-10-01, five-state sprint) = 222 + Douglas CO (2, CC BY-SA 4.0) and the three
    # implemented-but-UNREVIEWED county sources (Morgan CO deed auctions, Dane WI, Oconee SC).
    assert len(rows) == 227 and {r.state for r in rows} == {"FL", "TX", "AL", "AR", "LA", "AZ", "MI", "WY", "SC", "CO", "WI"}
    available = [r for r in rows if r.state in ("FL", "TX") and "AVAILABLE" in r.ledger_set or r.state in ("FL", "TX") and not r.ledger_set]
    assert len(available) == 112 - 3
    assert all(r.publishing_unit == "COUNTY" for r in rows if r.state in ("FL", "TX"))
    with open(csr.REGISTRY_PATH, newline="", encoding="utf-8") as fh:
        assert csv.DictReader(fh).fieldnames == csr.EXTENDED_COLUMNS
    assert "publishing_unit" not in csr.COLUMNS and csr.OPTIONAL_COLUMNS[0] == "publishing_unit"
    assert csr.validate_registry(rows) == []
    fl_tx = [r for r in rows if r.state in ("FL", "TX")]
    assert {tuple(d) for d in csr.to_db_rows(fl_tx)} == {tuple(csr.COLUMNS)}   # the live (018) shape
    with pytest.raises(ValueError, match="migration 018"):
        csr.to_db_rows(rows)                                                     # the AL row needs 020


def test_r02_fl_and_tx_production_rules_are_preserved():
    assert csr.validate_row(_row()) == []
    assert csr.validate_row(_row(inventory_type="FUTURE_RESALE")) == ["FL production row must carry one of: POST_SALE_FIXED_PRICE"]
    assert csr.validate_row(_row(inventory_type="")) == ["FL production row must carry one of: POST_SALE_FIXED_PRICE"]
    tx = dict(state="TX", county="Galveston", source_id="tx_lgbs", harvester="harvesters/texas_harvester.py", access_method="HTTP_GET_HTML",
              machine_format="HTML_TABLE", governance_status="APPROVED_GRANDFATHERED")
    for it in ("", "STRUCK_OFF_HELD_IN_TRUST", "FUTURE_RESALE"):
        assert csr.validate_row(_row(**tx, inventory_type=it)) == [], it
    assert csr.validate_row(_row(**tx, inventory_type="POST_SALE_FIXED_PRICE")) == ["TX production row must carry one of: (blank), FUTURE_RESALE, STRUCK_OFF_HELD_IN_TRUST"]
    known = {"FL": frozenset({"Marion"})}
    assert csr.validate_row(_row(county="Atlantis"), known_counties=known) == ["unknown FL county 'Atlantis'"]


def test_r03_unregistered_state_rows_are_rejected_registered_ones_accepted():
    zz_state = dict(state="ZZ", county=STATEWIDE_UNIT, source_id="zz_state_land", harvester="", inventory_type="STATE_HELD_TAX_LAND",
                    canonical_url="https://gis.example.invalid/FeatureServer/0", access_method="JSON_ENDPOINT", machine_format="JSON",
                    verification_status="SEARCH_EVIDENCE_ONLY", governance_status="TERMS_NOT_VERIFIED", completeness_status="UNKNOWN",
                    publishing_unit="STATE")
    assert csr.validate_row(_row(**zz_state)) == ["state 'ZZ' is not a registered state (harvesters/governance/states.py)"]
    with states.registered(ZZ):
        # State-level fixture: statewide publisher, county == STATEWIDE, no county list check.
        assert csr.validate_row(_row(**zz_state), known_counties={"ZZ": frozenset({"Alpha"})}) == []
        # County-level fixture in the same state.
        county_row = _row(**{**zz_state, "county": "Alpha", "publishing_unit": "COUNTY", "source_id": "zz_alpha"})
        assert csr.validate_row(county_row, known_counties={"ZZ": frozenset({"Alpha"})}) == []
        assert csr.validate_row(county_row, known_counties={"ZZ": frozenset({"Beta"})}) == ["unknown ZZ county 'Alpha'"]
        # Shape errors.
        assert csr.validate_row(_row(**{**zz_state, "county": "Alpha"})) == ["STATE-level row must use county 'STATEWIDE', not 'Alpha'"]
        assert csr.validate_row(_row(**{**zz_state, "publishing_unit": "COUNTY"})) == ["county 'STATEWIDE' requires publishing_unit STATE"]
        assert "publishing_unit 'DISTRICT'" in csr.validate_row(_row(**{**zz_state, "publishing_unit": "DISTRICT"}))
        assert csr.validate_row(_row(**{**zz_state, "county": "Orleans", "publishing_unit": "PARISH"})) == ["publishing_unit 'PARISH' is not one ZZ publishes by"]
        # Governance is not weakened: a search-evidence row is never runnable, blank unit = COUNTY.
        assert not _row(**zz_state).runnable and _row(**{**zz_state, "publishing_unit": ""}).publishing_unit == ""
        assert csr.validate_row(_row(**{**zz_state, "county": "Alpha", "publishing_unit": ""})) == []
    assert csr.validate_row(_row(**zz_state))   # gone again once unregistered
    # FL never gains a STATE unit through this: FL publishes by county only.
    assert csr.validate_row(_row(county=STATEWIDE_UNIT, publishing_unit="STATE")) == ["publishing_unit 'STATE' is not one FL publishes by"]


def test_r04_a_production_row_may_only_carry_a_storable_inventory_type(monkeypatch):
    with states.registered(ZZ):
        prod = _row(state="ZZ", county=STATEWIDE_UNIT, source_id="zz_state_land", inventory_type="STATE_HELD_TAX_LAND",
                    publishing_unit="STATE", canonical_url="https://gis.example.invalid/FeatureServer/0", access_method="JSON_ENDPOINT",
                    machine_format="JSON", ledgers="AVAILABLE")   # a production row names its ledger (2026-09-30)
        assert csr.validate_row(prod) == []          # storable since migration 020
        with monkeypatch.context() as m:
            m.setattr(csr, "DB_SUPPORTED_INVENTORY_TYPES", csr.DB_SUPPORTED_INVENTORY_TYPES - {"STATE_HELD_TAX_LAND"})
            assert csr.validate_row(prod) == ["PRODUCTION_VERIFIED row carries inventory_type 'STATE_HELD_TAX_LAND', which public.properties cannot store yet"]
        assert csr.expected_harvest_units([prod], "ZZ") == [("zz_state_land", STATEWIDE_UNIT)]
        assert csr.expected_harvest_units([prod], "FL") == []
        with pytest.raises(ValueError, match="no column in migration 018"):
            csr.to_db_rows([prod])


def test_r05_loader_accepts_the_optional_column_and_nothing_else(tmp_path):
    base = _row()
    def write(path, columns, rows):
        with open(path, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=columns)
            w.writeheader()
            for r in rows:
                w.writerow({c: getattr(r, c, "") for c in columns})
    p = tmp_path / "plain.csv"
    write(p, csr.COLUMNS, [base])
    assert csr.load_registry(p)[0].publishing_unit == "COUNTY"
    p = tmp_path / "unit.csv"
    with states.registered(ZZ):
        rows = [base, _row(state="ZZ", county=STATEWIDE_UNIT, source_id="zz_state_land", harvester="", inventory_type="STATE_HELD_TAX_LAND",
                           canonical_url="https://gis.example.invalid/FeatureServer/0", access_method="JSON_ENDPOINT", machine_format="JSON",
                           verification_status="SEARCH_EVIDENCE_ONLY", governance_status="TERMS_NOT_VERIFIED", completeness_status="UNKNOWN",
                           publishing_unit="STATE")]
        write(p, csr.COLUMNS + csr.OPTIONAL_COLUMNS, rows)
        loaded = csr.load_registry(p)
        assert [r.publishing_unit for r in loaded] == ["COUNTY", "STATE"] and csr.validate_registry(loaded) == []
        assert csr.lookup(loaded, "ZZ", STATEWIDE_UNIT).source_id == "zz_state_land"
    p = tmp_path / "extra.csv"
    write(p, csr.COLUMNS + ["publishing_unit", "region"], [base])
    with pytest.raises(ValueError, match="columns"):
        csr.load_registry(p)
    p = tmp_path / "reordered.csv"
    write(p, ["publishing_unit"] + csr.COLUMNS, [base])
    with pytest.raises(ValueError, match="columns"):
        csr.load_registry(p)


# ==================== 4. lifecycle ====================


def _gate(county="Marion", status="COMPLETE", source_id="fl_laft_pdfs"):
    e = {"county": county, "harvester": "h", "status": status, "checked_at": NOW, "source_url": "https://x.invalid/list",
         "source_class": "GOVERNMENT_DIRECT", "source_id": source_id}
    if status == "EMPTY":
        e["empty_signal"] = "empty_marker"
    return L.county_gates([e], [])[county]


def test_l01_fl_provenance_is_identical_with_and_without_the_state_argument():
    gate = _gate()
    row = {"county": "Marion", "case_no": "A", "bid": "1,200", "bid_kind": "OPENING_BID"}
    default = L.provenance_payload(row, gate, NOW)
    assert default == L.provenance_payload(row, gate, NOW, state="FL")
    assert default["inventory_type"] == "POST_SALE_FIXED_PRICE"
    assert default["otc_provenance"]["inventory_type"] == "harvester constant (F.S. 197.502(7) Lands Available list)"
    assert L.group_provenance([("A", row)], gate, NOW) == L.group_provenance([("A", row)], gate, NOW, state="FL")
    assert L.DEFAULT_STATE == "FL" and not hasattr(L, "STATE") and not hasattr(L, "INVENTORY_TYPE")
    assert L.lifecycle_inventory("FL") == ("POST_SALE_FIXED_PRICE", "harvester constant (F.S. 197.502(7) Lands Available list)")
    assert L.lifecycle_inventory("TX") == (None, None)


def test_l02_expected_units_are_scoped_to_the_requested_state(tmp_path):
    reg = tmp_path / "r.csv"
    reg.write_text("state,county,source_id,verification_status\nFL,Marion,fl_laft_pdfs,PRODUCTION_VERIFIED\nTX,Galveston,tx_lgbs,PRODUCTION_VERIFIED\n"
                   "ZZ,STATEWIDE,zz_state_land,PRODUCTION_VERIFIED\nZZ,Alpha,zz_alpha,SEARCH_EVIDENCE_ONLY\n")
    assert L.load_expected_units(reg) == L.load_expected_units(reg, "FL") == [("fl_laft_pdfs", "Marion")]
    assert L.load_expected_units(reg, "ZZ") == [("zz_state_land", "STATEWIDE")]
    assert L.load_expected_units(reg, "QQ") == []


def test_l03_a_third_state_with_no_lifecycle_type_leaves_inventory_type_alone_and_a_storable_one_stamps_it(monkeypatch):
    gate = _gate(county=STATEWIDE_UNIT, source_id="zz_state_land")
    with pytest.raises(ValueError, match="not registered"):
        L.provenance_payload({"county": STATEWIDE_UNIT, "case_no": "P-1"}, gate, NOW, state="ZZ")
    # Registered but NOT activated (Alabama's situation): refused before any payload is built.
    with states.registered(ZZ):
        with pytest.raises(ValueError, match="not activated"):
            L.provenance_payload({"county": STATEWIDE_UNIT, "case_no": "P-1"}, gate, NOW, state="ZZ")
    with states.registered(ZZ_ACTIVE):
        p = L.provenance_payload({"county": STATEWIDE_UNIT, "case_no": "P-1"}, gate, NOW, state="ZZ")
        assert "inventory_type" not in p and "inventory_type" not in p["otc_provenance"]
        assert p["last_seen_at"] == NOW and p["source_id"] == "zz_state_land" and p["purchase_amount_kind"] == "NOT_PUBLISHED"
    with states.registered(YY):
        p = L.provenance_payload({"county": "Orleans", "case_no": "P-1"}, _gate(county="Orleans", source_id="yy_src"), NOW, state="YY")
        assert p["inventory_type"] == "POST_SALE_FIXED_PRICE" and p["otc_provenance"]["inventory_type"] == "fixture basis"
    # A state whose lifecycle type the DB cannot store is refused before any write.
    unstorable = StateConfig(code="XX", name="X", publishing_units=("COUNTY",), production_inventory_types=frozenset({"STATE_HELD_TAX_LAND"}),
                             lifecycle_inventory_type="STATE_HELD_TAX_LAND", lifecycle_inventory_basis="fixture", production=True,
                             activation=states.ALL_REQUIREMENTS)
    with states.registered(unstorable), monkeypatch.context() as m:
        m.setattr(L, "DB_SUPPORTED_INVENTORY_TYPES", L.DB_SUPPORTED_INVENTORY_TYPES - {"STATE_HELD_TAX_LAND"})
        with pytest.raises(ValueError, match="not storable"):
            L.lifecycle_inventory("XX")


class _Store:
    def __init__(self, rows, state):
        self.rows, self.state = rows, state
        self.patches: list[tuple[str, dict]] = []
        self.gets = 0


def _server(store):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, body=b"[]"):
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            store.gets += 1
            qs = parse_qs(urlparse(self.path).query)
            if "limit" in qs and "county" not in qs:
                return self._send(200, b"[]")   # 017 and 019 present
            assert qs.get("state") == [f"eq.{store.state}"] and qs.get("source") == ["eq.laft"], self.path
            counties = unquote(qs["county"][0])[len("in.("):-1].replace('"', "").split(",")
            self._send(200, json.dumps([r for r in store.rows if r["county"] in counties]).encode())

        def do_PATCH(self):
            n = int(self.headers.get("Content-Length", 0))
            store.patches.append((unquote(self.path), json.loads(self.rfile.read(n) or b"{}")))
            self._send(204, b"")

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def _run_main(tmp_path, monkeypatch, store, state, status_entries, harvest_rows, registry_text, extra_args=()):
    srv = _server(store)
    try:
        status = tmp_path / "status.json"
        status.write_text(json.dumps(status_entries))
        harvest = tmp_path / "harvest.json"
        harvest.write_text(json.dumps(harvest_rows))
        registry = tmp_path / "registry.csv"
        registry.write_text(registry_text)
        report = tmp_path / "public" / "report.json"
        monkeypatch.setenv("SUPABASE_URL", f"http://127.0.0.1:{srv.server_port}")
        monkeypatch.setenv("SUPABASE_SERVICE_KEY", "sb_secret_test")
        monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
        argv = ["--state", state, "--status", str(status), "--registry", str(registry), "--harvest", str(harvest), "--report", str(report), *extra_args]
        rc = L.main(argv)
        return rc, (json.loads(report.read_text()) if report.is_file() else None)
    finally:
        srv.shutdown()


ZZ_STATUS = [
    {"county": "Alpha", "harvester": "zz_h", "status": "COMPLETE", "checked_at": NOW, "row_count": 2, "source_url": "https://zz.invalid/list",
     "source_class": "GOVERNMENT_DIRECT", "source_id": "zz_state_land"},
    {"county": "Beta", "harvester": "zz_h", "status": "EMPTY", "checked_at": NOW, "empty_signal": "platform_count_zero"},
    {"county": "Gamma", "harvester": "zz_h", "status": "INCOMPLETE", "checked_at": NOW, "error_category": "PARSE_TRUNCATED", "source_url": "https://zz.invalid/list",
     "source_class": "GOVERNMENT_DIRECT", "source_id": "zz_state_land"},
    {"county": "Delta", "harvester": "zz_h", "status": "FAILED", "checked_at": NOW, "error_category": "HTTP_403"},
]
ZZ_HARVEST = [
    {"county": "Alpha", "case_no": "A1", "bid": "500", "bid_kind": "MINIMUM_PURCHASE_AMOUNT"},
    {"county": "Alpha", "case_no": "A2"},
    {"county": "Gamma", "case_no": "G1"},
    {"county": "Delta", "case_no": "D1"},
]
ZZ_DB = [
    {"id": "a1", "county": "Alpha", "case_no": "A1", "status": "closed"},
    {"id": "a-gone", "county": "Alpha", "case_no": "A9", "status": "active"},
    {"id": "b-gone", "county": "Beta", "case_no": "B9", "status": "active"},
    {"id": "g1", "county": "Gamma", "case_no": "G1", "status": "active"},
    {"id": "g-stays", "county": "Gamma", "case_no": "G9", "status": "active"},
    {"id": "d-stays", "county": "Delta", "case_no": "D9", "status": "active"},
    {"id": "e-stays", "county": "Epsilon", "case_no": "E9", "status": "active"},
]
ZZ_REGISTRY = ("state,county,source_id,verification_status\nZZ,Alpha,zz_state_land,PRODUCTION_VERIFIED\nZZ,Epsilon,zz_state_land,PRODUCTION_VERIFIED\n"
               "FL,Marion,fl_laft_pdfs,PRODUCTION_VERIFIED\n")


def test_l04_end_to_end_for_an_activated_third_state_applies_the_same_gates(tmp_path, monkeypatch):
    store = _Store([dict(r) for r in ZZ_DB], "ZZ")
    with states.registered(ZZ_ACTIVE):
        rc, report = _run_main(tmp_path, monkeypatch, store, "ZZ", ZZ_STATUS, ZZ_HARVEST, ZZ_REGISTRY)
    assert rc == 0 and report["state"] == "ZZ"
    assert report["counties"] == {"Alpha": "COMPLETE", "Beta": "EMPTY", "Gamma": "INCOMPLETE", "Delta": "FAILED", "Epsilon": "NOT_RUN"}
    assert "Marion" not in report["counties"]                      # FL registry rows never enter a ZZ run
    # Every query and patch was scoped to state=eq.ZZ (the fake server asserts GETs; check PATCHes here).
    scoped = [p for p, b in store.patches if "state=eq." in p]
    assert scoped and all("state=eq.ZZ" in p and "source=eq.laft" in p for p in scoped)
    # Observed: COMPLETE + INCOMPLETE rows only; A1 reactivated.
    assert [(p, b) for p, b in store.patches if b == {"status": "active"}][0][0].count("Alpha") == 1
    prov = [(p, b) for p, b in store.patches if "last_seen_at" in b]
    assert {p.split("county=eq.")[1].split("&")[0] for p, _ in prov} == {"Alpha", "Gamma"}
    for _, b in prov:
        assert "inventory_type" not in b and "inventory_type" not in b["otc_provenance"]   # ZZ lifecycle asserts no type
        assert b["source_id"] == "zz_state_land"
    priced = next(b for _, b in prov if b["purchase_amount"] is not None)
    assert priced["purchase_amount"] == 500.0 and priced["purchase_amount_kind"] == "MINIMUM_PURCHASE_AMOUNT"
    # Close-out: absent rows of COMPLETE (Alpha) and EMPTY (Beta) only - never INCOMPLETE, FAILED or NOT_RUN.
    closes = [(p, b) for p, b in store.patches if b.get("status") == "closed"]
    assert len(closes) == 1 and "a-gone" in closes[0][0] and "b-gone" in closes[0][0]
    for stays in ("g1", "g-stays", "d-stays", "e-stays", "a1"):
        assert stays not in closes[0][0]
    assert report == {**report, "observed": 3, "reactivated": 1, "closed": 2}


def test_l05_an_unregistered_or_inactive_state_stops_before_any_request(tmp_path, monkeypatch):
    store = _Store([dict(r) for r in ZZ_DB], "ZZ")
    rc, report = _run_main(tmp_path, monkeypatch, store, "ZZ", ZZ_STATUS, ZZ_HARVEST, ZZ_REGISTRY)
    assert rc == 2 and report is None and store.gets == 0 and store.patches == []
    # Registered but not activated: the same stop, zero requests.
    with states.registered(ZZ):
        rc, report = _run_main(tmp_path, monkeypatch, store, "ZZ", ZZ_STATUS, ZZ_HARVEST, ZZ_REGISTRY)
    assert rc == 2 and report is None and store.gets == 0 and store.patches == []
    # Alabama, registered in code and not activated: the same stop, zero requests.
    rc, report = _run_main(tmp_path, monkeypatch, store, "AL", ZZ_STATUS, ZZ_HARVEST, ZZ_REGISTRY)
    assert rc == 2 and report is None and store.gets == 0 and store.patches == []
    for bad in ("zz", "Florida", "F"):
        rc, report = _run_main(tmp_path, monkeypatch, store, bad, ZZ_STATUS, ZZ_HARVEST, ZZ_REGISTRY)
        assert rc == 2 and report is None and store.gets == 0 and store.patches == []


def test_l06_fl_end_to_end_is_unchanged_by_the_default_state(tmp_path, monkeypatch):
    fl_db = [{"id": "m1", "county": "Marion", "case_no": "A", "status": "active"}, {"id": "m-gone", "county": "Marion", "case_no": "Z", "status": "active"}]
    fl_status = [{"county": "Marion", "harvester": "fl_laft_pdfs", "status": "COMPLETE", "checked_at": NOW, "row_count": 1,
                  "source_url": "https://marion.invalid/list", "source_class": "GOVERNMENT_DIRECT", "source_id": "fl_laft_pdfs"}]
    store = _Store(fl_db, "FL")
    rc, report = _run_main(tmp_path, monkeypatch, store, "FL", fl_status, [{"county": "Marion", "case_no": "A"}], ZZ_REGISTRY)
    assert rc == 0 and report["state"] == "FL" and report["counties"] == {"Marion": "COMPLETE"}
    prov = [b for p, b in store.patches if "last_seen_at" in b]
    assert len(prov) == 1 and prov[0]["inventory_type"] == "POST_SALE_FIXED_PRICE"
    assert prov[0]["otc_provenance"]["inventory_type"] == "harvester constant (F.S. 197.502(7) Lands Available list)"
    closes = [(p, b) for p, b in store.patches if b.get("status") == "closed"]
    assert len(closes) == 1 and "m-gone" in closes[0][0] and "m1" not in closes[0][0]


def test_l07_workflow_and_sanity_check_still_run_florida_by_default():
    wf = (REPO / ".github/workflows/harvest-and-sync.yml").read_text(encoding="utf-8")
    assert "python3 scripts/laft_lifecycle.py" in wf and "--state" not in wf.split("laft_lifecycle.py")[1].split("\n")[0]
    assert "LAFT_STATE" not in wf
    src = (REPO / "scripts/laft_lifecycle.py").read_text(encoding="utf-8")
    assert 'DEFAULT_STATE = "FL"' in src and "state_problems(state)" in src
