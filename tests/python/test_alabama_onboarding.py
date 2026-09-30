"""Alabama onboarding foundation (2026-09-29): registration without
activation, the widened vocabulary, the registry's publishing-unit and
semantics columns, the adapter contract, and every gate that keeps an
inactive state from running. All fixtures are synthetic: no Alabama
document has been read, so nothing here claims the source's real format.
2026-09-30: the registry row now carries the agency's own URLs (seen in a
web search's index - still search evidence, still not activated) and the
adapter is a real, gated implementation; see test_alabama_source_adapter.py.
"""
from __future__ import annotations

import ast
import csv
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

from harvesters.governance import county_source_registry as csr  # noqa: E402
from harvesters.governance import states  # noqa: E402
from harvesters.governance.states import STATEWIDE_UNIT, PublishingUnit, StateConfig  # noqa: E402
from harvesters.otc import (DB_SUPPORTED_AMOUNT_KINDS, DB_SUPPORTED_INVENTORY_TYPES, AmountKind, InventoryType,  # noqa: E402
                            PurchaseUrlKind, SourceAuthority)
from harvesters.otc.adapters import alabama as ala  # noqa: E402
from harvesters.otc.gate import evaluate_source  # noqa: E402
import laft_lifecycle as L  # noqa: E402

T = datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)
ROWS = csr.load_registry()
AL_ROW = csr.lookup(ROWS, "AL", STATEWIDE_UNIT)
M020 = REPO / "scripts/migrations/020_state_extensible_vocabulary.sql"


# ==================== 1. registration without activation ====================


def test_r01_alabama_is_registered_representable_and_not_production():
    cfg = states.get_state("AL")
    assert cfg is states.AL and cfg.name == "Alabama" and cfg.production is False and cfg.activated is False
    assert set(cfg.publishing_units) == {"STATE", "COUNTY"} and cfg.production_inventory_types == {"STATE_HELD_TAX_LAND"}
    # The lifecycle type is DECLARED (what would be stamped once activated
    # and storable) but lifecycle_inventory("AL") still refuses (x02).
    assert cfg.lifecycle_inventory_type == "STATE_HELD_TAX_LAND" and "State inventory" in cfg.lifecycle_inventory_basis
    assert cfg.activation == frozenset()
    assert states.state_problems("AL") == []                       # the model may represent it
    assert not states.is_activated("AL") and "AL" not in states.PRODUCTION_STATES
    assert states.activation_blockers("AL") == list(states.ACTIVATION_REQUIREMENTS) and len(states.ACTIVATION_REQUIREMENTS) == 10
    # FL / TX unchanged: production, activated, no blockers.
    for code in ("FL", "TX"):
        assert states.is_activated(code) and states.activation_blockers(code) == [] and states.get_state(code).activation == states.ALL_REQUIREMENTS
    with pytest.raises(ValueError, match="production state and cannot be re-registered"):
        with states.registered(StateConfig(code="FL", name="x", publishing_units=("COUNTY",), production_inventory_types=frozenset(),
                                           lifecycle_inventory_type=None, production=False)):
            pass


def test_r02_a_production_state_must_satisfy_every_requirement_and_requirements_are_closed():
    base = dict(name="x", publishing_units=("COUNTY",), production_inventory_types=frozenset(), lifecycle_inventory_type=None)
    with pytest.raises(ValueError, match="every activation requirement"):
        StateConfig(code="QQ", production=True, activation=frozenset({"live_source_verified"}), **base)
    with pytest.raises(ValueError, match="unknown activation requirement"):
        StateConfig(code="QQ", production=False, activation=frozenset({"looks_fine_in_search_results"}), **base)
    partial = StateConfig(code="QQ", production=False, activation=frozenset({"source_of_record_identified"}), **base)
    with states.registered(partial):
        assert not states.is_activated("QQ")
        blockers = states.activation_blockers("QQ")
        assert "source_of_record_identified" not in blockers and "production_registry_authorized" in blockers and len(blockers) == 9


# ==================== 2. vocabulary ====================


def test_v01_state_held_tax_land_and_quoted_on_application_are_model_only_until_020():
    assert InventoryType.STATE_HELD_TAX_LAND.value not in DB_SUPPORTED_INVENTORY_TYPES
    assert AmountKind.QUOTED_ON_APPLICATION.value not in DB_SUPPORTED_AMOUNT_KINDS
    assert set(csr.AMOUNT_KINDS) == {k.value for k in AmountKind}
    sql = M020.read_text(encoding="utf-8").lower()
    for v in ("state_held_tax_land", "post_sale", "adjudicated_property", "quoted_on_application"):
        assert f"'{v}'" in sql, v
    # 020 keeps the "no amount" rule for the quoted kind and inserts nothing.
    assert "purchase_amount_kind in ('not_published', 'quoted_on_application')" in sql
    for forbidden in ("insert into", "update public.properties", "delete from", "drop column", "drop table"):
        assert forbidden not in sql, forbidden
    assert re.search(r"add column if not exists publishing_unit text not null default 'county'", sql)
    assert "check (state ~ '^[a-z]{2}$')" in sql
    for col in ("publishing_unit_name", "amount_kind", "update_frequency", "source_terminology"):
        assert f"add column if not exists {col} text" in sql, col
    # Listed as unapplied in the production configuration.
    assert "020_state_extensible_vocabulary.sql" in (REPO / "docs/production-configuration.md").read_text(encoding="utf-8")


def test_v02_publishing_units_cover_every_unit_kind_without_a_state_assumption():
    assert {u.value for u in PublishingUnit} == {"STATE", "COUNTY", "PARISH", "BOROUGH", "MUNICIPALITY"}
    for unit in ("PARISH", "BOROUGH", "MUNICIPALITY"):
        cfg = StateConfig(code="QQ", name="x", publishing_units=(unit,), production_inventory_types=frozenset({"ADJUDICATED_PROPERTY"}),
                          lifecycle_inventory_type=None, production=False)
        with states.registered(cfg):
            row = csr.CountySourceRow(**{**_al_kwargs(), "state": "QQ", "county": "Orleans", "publishing_unit": unit, "publishing_unit_name": "",
                                         "inventory_type": "ADJUDICATED_PROPERTY", "source_id": "qq_x"})
            assert csr.validate_row(row) == []


# ==================== 3. registry ====================


def _al_kwargs(**over):
    base = dict(state="AL", county=STATEWIDE_UNIT, source_id="al_ador_state_land", harvester="", inventory_type="STATE_HELD_TAX_LAND",
                source_authority="GOVERNMENT_DIRECT", canonical_url="", document_url="", purchase_url="", purchase_url_kind="",
                access_method="UNKNOWN", machine_format="UNKNOWN", verification_status="SEARCH_EVIDENCE_ONLY",
                governance_status="TERMS_NOT_VERIFIED", last_checked="2026-09-29", completeness_status="UNKNOWN",
                evidence_ref="fixture", notes="", publishing_unit="STATE", publishing_unit_name="Agency", amount_kind="QUOTED_ON_APPLICATION",
                update_frequency="", source_terminology="")
    base.update(over)
    return base


def test_g01_committed_registry_has_exactly_one_alabama_candidate_that_is_not_production():
    al = [r for r in ROWS if r.state == "AL"]
    assert len(al) == 1 and AL_ROW is al[0]
    assert AL_ROW.publishing_unit == "STATE" and AL_ROW.county == STATEWIDE_UNIT
    assert "Alabama Department of Revenue" in AL_ROW.publishing_unit_name
    assert AL_ROW.verification_status == "SEARCH_EVIDENCE_ONLY" and AL_ROW.governance_status == "TERMS_NOT_VERIFIED"
    # 2026-09-30: the agency's own pages, as the search index showed them -
    # the search page is the list, the process page is purchase INSTRUCTIONS
    # (never a property link), the transcript document is unknown, and a
    # non-production row still names no harvester.
    assert AL_ROW.canonical_url == ala.ADOR_SEARCH_URL and AL_ROW.purchase_url == ala.ADOR_LAND_SALES_URL
    assert AL_ROW.purchase_url_kind == "purchase_instructions" and AL_ROW.document_url == "" and AL_ROW.harvester == ""
    assert AL_ROW.inventory_type == "STATE_HELD_TAX_LAND" and AL_ROW.amount_kind == "QUOTED_ON_APPLICATION"
    assert "not read directly" in AL_ROW.update_frequency and "search-index" in AL_ROW.source_terminology
    assert "WEB SEARCH 2026-09-30" in AL_ROW.evidence_ref
    assert not AL_ROW.is_production and not AL_ROW.runnable
    assert csr.validate_registry(ROWS) == []
    # The FL/TX rows are untouched: 109 rows, all COUNTY, the new columns blank.
    others = [r for r in ROWS if r.state in ("FL", "TX")]
    assert len(others) == 109 and all(r.publishing_unit == "COUNTY" and r.publishing_unit_name == "" and r.amount_kind == ""
                                      and r.update_frequency == "" and r.source_terminology == "" for r in others)
    assert len(csr.production_rows(ROWS, "FL")) == 52 and len(csr.production_rows(ROWS, "TX")) == 8 and csr.production_rows(ROWS, "AL") == []
    with open(csr.REGISTRY_PATH, newline="", encoding="utf-8") as fh:
        assert csv.DictReader(fh).fieldnames == csr.EXTENDED_COLUMNS


def test_g02_registry_validation_for_the_new_columns():
    assert csr.validate_row(csr.CountySourceRow(**_al_kwargs())) == []
    assert csr.validate_row(csr.CountySourceRow(**_al_kwargs(publishing_unit_name=""))) == ["STATE-level row must name its publishing unit (publishing_unit_name)"]
    assert csr.validate_row(csr.CountySourceRow(**_al_kwargs(amount_kind="QUOTE"))) == ["amount_kind 'QUOTE'"]
    assert csr.validate_row(csr.CountySourceRow(**_al_kwargs(publishing_unit="PARISH", county="Mobile", publishing_unit_name=""))) == ["publishing_unit 'PARISH' is not one AL publishes by"]
    # A production Alabama row is refused twice over: not storable yet, and (through the gate) not activated.
    prod = csr.CountySourceRow(**_al_kwargs(verification_status="PRODUCTION_VERIFIED", governance_status="APPROVED", harvester="x",
                                            canonical_url="https://example.invalid/list", completeness_status="COMPLETE"))
    assert "PRODUCTION_VERIFIED row carries inventory_type 'STATE_HELD_TAX_LAND', which public.properties cannot store yet" in csr.validate_row(prod)
    assert not prod.runnable
    assert evaluate_source(prod).layer == "state_activation" and not evaluate_source(prod).allowed


def test_g03_to_db_rows_keeps_the_live_shape_for_fl_tx_and_needs_020_for_alabama():
    fl_tx = [r for r in ROWS if r.state in ("FL", "TX")]
    live = csr.to_db_rows(fl_tx)
    assert len(live) == 109 and all(set(d) == set(csr.COLUMNS) for d in live)
    with pytest.raises(ValueError, match="migration 018"):
        csr.to_db_rows([AL_ROW])
    ext = csr.to_db_rows(ROWS, schema="020")
    assert len(ext) == len(ROWS) and all(set(d) == set(csr.EXTENDED_COLUMNS) for d in ext)
    al = next(d for d in ext if d["state"] == "AL")
    assert al["publishing_unit"] == "STATE" and al["canonical_url"] == ala.ADOR_SEARCH_URL and al["amount_kind"] == "QUOTED_ON_APPLICATION"
    assert all(d["publishing_unit"] == "COUNTY" and d["amount_kind"] is None for d in ext if d["state"] in ("FL", "TX"))
    with pytest.raises(ValueError, match="unknown registry schema"):
        csr.to_db_rows(ROWS, schema="019")


# ==================== 4. adapter contract ====================


VOCAB = {"available for sale": ala.AlabamaStatus.AVAILABLE_FOR_SALE, "sold": ala.AlabamaStatus.SOLD, "redeemed": ala.AlabamaStatus.REDEEMED}


def _cfg(**over):
    base = dict(source_id="al_fixture", publishing_unit="STATE", publishing_unit_name="Fixture agency",
                fields=ala.AlabamaFieldMap(identifier="Parcel", county="County", status="Status", legal_desc="Legal", balance="Taxes Due",
                                           property_url="Link", list_as_of="As Of"),
                list_url="https://fixture.invalid/list", application_url="https://fixture.invalid/apply",
                application_url_kind=PurchaseUrlKind.APPLICATION_FORM, status_vocabulary=VOCAB,
                source_terminology="fixture wording")
    base.update(over)
    return ala.AlabamaSourceConfig(**base)


def test_a01_config_contract_refuses_every_unsafe_shape():
    assert _cfg().amount_kind is AmountKind.QUOTED_ON_APPLICATION and _cfg().inventory_type is InventoryType.STATE_HELD_TAX_LAND
    with pytest.raises(ValueError, match="STATE or COUNTY"):
        _cfg(publishing_unit="PARISH")
    with pytest.raises(ValueError, match="67 counties"):
        _cfg(publishing_unit="COUNTY", county="Orleans")
    with pytest.raises(ValueError, match="names the county per row"):
        _cfg(county="Mobile")
    with pytest.raises(ValueError, match="map the county column"):
        _cfg(fields=ala.AlabamaFieldMap(identifier="Parcel"))
    with pytest.raises(ValueError, match="must be https"):
        _cfg(list_url="http://fixture.invalid/list")
    with pytest.raises(ValueError, match="go together"):
        _cfg(application_url_kind=None)
    with pytest.raises(ValueError, match="never a property purchase kind"):
        _cfg(application_url_kind=PurchaseUrlKind.ONLINE_PURCHASE)
    with pytest.raises(ValueError, match="not an application page"):
        _cfg(application_url="https://fixture.invalid/list")
    with pytest.raises(ValueError, match="publishes no price"):
        _cfg(fields=ala.AlabamaFieldMap(identifier="Parcel", county="County", amount="Price"))
    with pytest.raises(ValueError, match="unknown status"):
        _cfg(status_vocabulary={"sold": "GONE"})
    with pytest.raises(ValueError, match="cannot be enabled"):
        _cfg(enabled=True)
    assert len(ala.ALABAMA_COUNTIES) == 67 and "Jefferson" in ala.ALABAMA_COUNTIES and "Orleans" not in ala.ALABAMA_COUNTIES


def test_a02_identifiers_are_taken_as_published_and_malformed_ones_rejected():
    assert ala.normalize_identifier(" 12-34-56 ") == "12-34-56"
    assert ala.normalize_identifier("R 0012  345") == "R 0012 345"          # internal runs of spaces collapsed, nothing else
    assert ala.normalize_identifier("12-34-56") != "123456"                 # never stripped Florida-style
    for bad in (None, "", "   ", "NO DIGITS", "12\n34", "12\r34", "1" * 41, "Parcel Number"):
        assert ala.normalize_identifier(bad) is None, bad
    assert ala.normalize_identifier("1" * 40) == "1" * 40


def test_a03_parse_rows_is_deterministic_and_never_invents_an_amount_or_a_purchase_link():
    rows = [
        {"Parcel": "12-34-56-0-000-001.000", "County": "Jefferson", "Status": "Available for Sale", "Legal": "LOT 1", "Taxes Due": "$412.10", "As Of": "09/01/2026"},
        {"Parcel": "77-00-01", "County": "Mobile", "Status": "SOLD", "Link": "https://fixture.invalid/parcel/77-00-01"},
        {"Parcel": "88-00-02", "County": "Mobile", "Status": "Pending review"},                        # wording outside the vocabulary
        {"Parcel": "99-00-03", "County": "Mobile", "Link": "https://fixture.invalid/list"},            # a "link" that is the list page
        {"Parcel": "", "County": "Mobile"},                                                            # no identifier
        {"Parcel": "NO DIGITS", "County": "Mobile"},                                                   # malformed identifier
        {"Parcel": "55-00-05", "County": "Orleans"},                                                   # not an Alabama county
        {"Parcel": "66-00-06"},                                                                        # statewide list, county missing
    ]
    recs, rep = ala.parse_rows(_cfg(), rows, retrieved_at=T, list_as_of=date(2026, 8, 25))
    assert (rep.accepted, rep.rejected_identifier, rep.rejected_county, rep.unknown_status, rep.amount_ignored,
            rep.property_links, rep.rejected_property_url) == (4, 2, 2, 1, 1, 1, 1)
    a, b, c, d = recs
    # The identifier is the identity; a parcel exists only when the source publishes a parcel column (none here).
    assert (a.state, a.county, a.case_no, a.parcel) == ("AL", "Jefferson", "12-34-56-0-000-001.000", None)
    assert a.provenance["parcel"] == "no parcel column"
    assert a.inventory_type is InventoryType.STATE_HELD_TAX_LAND and a.amount is None and a.amount_kind is AmountKind.QUOTED_ON_APPLICATION
    assert a.source_status_text == "Available for Sale" and a.provenance["normalized_status"] == "AVAILABLE_FOR_SALE"
    assert a.list_as_of == date(2026, 9, 1) and b.list_as_of == date(2026, 8, 25)      # row date, else the list's; never T
    assert a.purchase_url == "https://fixture.invalid/apply" and a.purchase_url_kind is PurchaseUrlKind.APPLICATION_FORM
    assert b.purchase_url == "https://fixture.invalid/parcel/77-00-01" and b.purchase_url_kind is PurchaseUrlKind.ONLINE_PURCHASE
    assert c.provenance["normalized_status"] == "UNKNOWN" and c.source_status_text == "Pending review"
    assert d.purchase_url == "https://fixture.invalid/apply"                                # the list page never became a link
    assert a.provenance["amount"].startswith("QUOTED_ON_APPLICATION") and a.provenance["identifier"].startswith("as published")
    assert a.provenance["publishing_unit_name"] == "Fixture agency" and a.provenance["source_terminology"] == "fixture wording"
    assert all(r.validate() == [] for r in recs)
    # Same input, same output: no randomness, no cross-row state.
    recs2, _ = ala.parse_rows(_cfg(), rows, retrieved_at=T, list_as_of=date(2026, 8, 25))
    assert [r.as_dict() for r in recs2] == [r.as_dict() for r in recs]
    # Storable only after migration 020.
    with pytest.raises(ValueError, match="not storable"):
        a.to_properties_row()


def test_a04_a_published_amount_is_carried_only_with_a_declared_kind_and_a_county_list_fixes_its_county():
    cfg = _cfg(publishing_unit="COUNTY", county="Baldwin", amount_kind=AmountKind.FIXED_PURCHASE_PRICE,
               fields=ala.AlabamaFieldMap(identifier="Parcel", amount="Price"), application_url=None, application_url_kind=None)
    recs, rep = ala.parse_rows(cfg, [{"Parcel": "1-2-3", "Price": "$1,500.00", "County": "IGNORED"}, {"Parcel": "1-2-4", "Price": "TBD"}], retrieved_at=T)
    assert [r.county for r in recs] == ["Baldwin", "Baldwin"]
    assert (recs[0].amount, recs[0].amount_kind) == (1500.0, AmountKind.FIXED_PURCHASE_PRICE)
    assert (recs[1].amount, recs[1].amount_kind) == (None, AmountKind.NOT_PUBLISHED)
    assert recs[0].purchase_url is None and recs[0].provenance["purchase_url"] == "no online path published"
    with pytest.raises(ValueError, match="publishes no price"):
        _cfg(fields=ala.AlabamaFieldMap(identifier="Parcel", county="County", amount="Taxes Due"))


# ==================== 5. gates: an inactive state cannot run anywhere ====================


def test_x01_adapter_can_never_run_today_and_has_no_transport():
    d = ala.can_run(_cfg())
    assert not d.allowed and d.reason.startswith("state AL is not activated")
    with pytest.raises(RuntimeError, match="may not run"):
        ala.harvest(_cfg(), lambda url: "", retrieved_at=T)
    # Even a configuration that claims full verification is refused while the state is inactive.
    verified = _cfg(live_verified=True, identifier_format_established=True, parser_fixture_validated=True, enabled=True)
    assert not ala.can_run(verified).allowed
    src = (REPO / "harvesters/otc/adapters/alabama.py").read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [a.name for a in node.names] + ([node.module] if isinstance(node, ast.ImportFrom) and node.module else [])
            for n in names:
                # urllib.parse (URL joining) is allowed; no transport is.
                assert not n.startswith(("requests", "urllib.request", "urllib.error", "http", "playwright", "socket")), n
                assert n != "urllib", n
    # The only hosts the module names are the agency's own (the evidence ledger).
    hosts = set(re.findall(r"https://([^/\s\"']+)", src))
    assert hosts == {ala.ADOR_HOST}, hosts
    # The one ADOR row of the registry carries exactly those URLs and nothing else names the host.
    csv_text = (REPO / "data/county_source_registry.csv").read_text(encoding="utf-8")
    assert csv_text.count("https://www.revenue.alabama.gov/") == 2 and csv_text.count("\nAL,") == 1


def test_x02_the_gate_registry_and_lifecycle_all_refuse_alabama():
    assert evaluate_source(AL_ROW).layer == "state_activation" and not evaluate_source(AL_ROW).allowed
    assert not AL_ROW.runnable
    with pytest.raises(ValueError, match="not activated"):
        L.lifecycle_inventory("AL")
    assert L.load_expected_units(csr.REGISTRY_PATH, "AL") == []               # nothing expected of a candidate
    assert L.load_registry_purchase_paths(csr.REGISTRY_PATH, "AL") == {}


def test_x03_activating_the_hypothetical_state_in_a_fixture_is_the_only_way_through_and_fl_tx_are_unchanged():
    active = StateConfig(code="QQ", name="Q", publishing_units=("STATE",), production_inventory_types=frozenset({"STATE_HELD_TAX_LAND"}),
                         lifecycle_inventory_type=None, production=True, activation=states.ALL_REQUIREMENTS)
    with states.registered(active):
        row = csr.CountySourceRow(**_al_kwargs(state="QQ", source_id="qq_src", verification_status="PRODUCTION_VERIFIED", governance_status="APPROVED",
                                               harvester="x", canonical_url="https://example.invalid/list", completeness_status="COMPLETE",
                                               inventory_type=""))
        assert row.runnable and evaluate_source(row).allowed
    # FL / TX production rows behave exactly as before.
    fl = next(r for r in csr.production_rows(ROWS, "FL"))
    tx = next(r for r in csr.production_rows(ROWS, "TX"))
    assert fl.runnable and evaluate_source(fl).allowed and evaluate_source(tx).layer in ("ok", "vendor_registry")
    assert L.lifecycle_inventory("FL") == ("POST_SALE_FIXED_PRICE", "harvester constant (F.S. 197.502(7) Lands Available list)")
    assert L.lifecycle_inventory("TX") == (None, None)


# ==================== 6. migration 020, live on a scratch cluster (skipped without PostgreSQL) ====================

import uuid  # noqa: E402

from test_migration_017_otc_provenance import FIXTURE, M017, M018, _psql_prefix, _run  # noqa: E402


@pytest.fixture(scope="module")
def scratch020():
    prefix = _psql_prefix()
    if prefix is None:
        pytest.skip("no local PostgreSQL reachable - live migration layer skipped (static layer still ran)")
    db = f"tdw_mig020_{uuid.uuid4().hex[:8]}"
    assert _run(prefix, "-Atc", f"create database {db}", db="postgres").returncode == 0
    staged = []
    try:
        for path in (FIXTURE, M017, M018, M020):
            copy = Path("/tmp") / f"{db}_{path.name}"
            copy.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
            copy.chmod(0o644)
            staged.append(copy)
            r = _run(prefix, "-v", "ON_ERROR_STOP=1", "-q", "-f", str(copy), db=db)
            assert r.returncode == 0, f"{path.name} failed to apply:\n{r.stderr}"

        def run(sql):
            r = _run(prefix, "-v", "ON_ERROR_STOP=0", "-Atq", db=db, stdin=sql)
            return (r.stdout or "") + (r.stderr or "")
        yield run
    finally:
        _run(prefix, "-Atc", f"drop database if exists {db}", db="postgres")
        for c in staged:
            c.unlink(missing_ok=True)


def test_m01_live_020_widens_constraints_adds_registry_columns_and_changes_no_row(scratch020):
    out = scratch020("select count(*) from public.properties where inventory_type is not null;")
    before = out.strip()
    # The whole registry, Alabama row included, loads in the 020 shape.
    rows = csr.to_db_rows(ROWS, schema="020")
    cols = list(rows[0].keys())

    def lit(v):
        return "null" if v is None else "'" + str(v).replace("'", "''") + "'"
    values = ",\n".join("(" + ",".join(lit(r[c]) for c in cols) + ")" for r in rows)
    out = scratch020(f"set role service_role;\ninsert into public.county_source_registry ({','.join(cols)}) values\n{values};\n"
                     "select count(*), count(*) filter (where publishing_unit='STATE'), count(*) filter (where state='AL' and canonical_url is null) from public.county_source_registry;")  # noqa: E501
    assert "ERROR" not in out, out[:600]
    # Two STATE-level rows (Alabama, Arkansas); the Louisiana row is PARISH-level.
    assert out.strip().splitlines()[-1] == f"{len(rows)}|2|0"
    # Registry constraints: a STATE row must say STATEWIDE and name its agency; a county row may not say STATEWIDE.
    out = scratch020("""set role service_role;
      insert into public.county_source_registry (state,county,publishing_unit,access_method,machine_format,verification_status,governance_status,last_checked,evidence_ref) values ('AL','Jefferson','STATE','UNKNOWN','UNKNOWN','SEARCH_EVIDENCE_ONLY','TERMS_NOT_VERIFIED','2026-09-29','e');
      insert into public.county_source_registry (state,county,publishing_unit,access_method,machine_format,verification_status,governance_status,last_checked,evidence_ref) values ('AL','STATEWIDE','STATE','UNKNOWN','UNKNOWN','SEARCH_EVIDENCE_ONLY','TERMS_NOT_VERIFIED','2026-09-29','e');
      insert into public.county_source_registry (state,county,publishing_unit,access_method,machine_format,verification_status,governance_status,last_checked,evidence_ref) values ('LA','Orleans','DISTRICT','UNKNOWN','UNKNOWN','SEARCH_EVIDENCE_ONLY','TERMS_NOT_VERIFIED','2026-09-29','e');
      insert into public.county_source_registry (state,county,access_method,machine_format,verification_status,governance_status,last_checked,evidence_ref,amount_kind) values ('LA','Orleans','UNKNOWN','UNKNOWN','SEARCH_EVIDENCE_ONLY','TERMS_NOT_VERIFIED','2026-09-29','e','QUOTE');
      insert into public.county_source_registry (state,county,access_method,machine_format,verification_status,governance_status,last_checked,evidence_ref) values ('fl','Marion','UNKNOWN','UNKNOWN','SEARCH_EVIDENCE_ONLY','TERMS_NOT_VERIFIED','2026-09-29','e');""")
    assert out.count("violates check constraint") == 5
    # properties: the new vocabulary is storable, an amount under QUOTED_ON_APPLICATION is not, FL/TX values still are.
    out = scratch020("""set role service_role;
      insert into public.properties (source, county, case_no, address, bid, state, inventory_type, purchase_amount, purchase_amount_kind) values ('laft','STATEWIDE','AL-FIX-1','Parcel AL-FIX-1',0,'AL','STATE_HELD_TAX_LAND',null,'QUOTED_ON_APPLICATION');
      select inventory_type||'|'||purchase_amount_kind from public.properties where case_no='AL-FIX-1';
      insert into public.properties (source, county, case_no, address, bid, state, inventory_type, purchase_amount, purchase_amount_kind) values ('laft','STATEWIDE','AL-FIX-2','Parcel AL-FIX-2',0,'AL','STATE_HELD_TAX_LAND',100,'QUOTED_ON_APPLICATION');
      insert into public.properties (source, county, case_no, address, bid, state, inventory_type, purchase_amount, purchase_amount_kind) values ('laft','Marion','FL-FIX-1','Parcel FL-FIX-1',0,'FL','POST_SALE_FIXED_PRICE',1200,'FIXED_PURCHASE_PRICE');
      insert into public.properties (source, county, case_no, address, bid, state, inventory_type, purchase_amount, purchase_amount_kind) values ('laft','Marion','FL-FIX-2','Parcel FL-FIX-2',0,'FL','NOT_A_TYPE',null,'NOT_PUBLISHED');
      delete from public.properties where case_no in ('AL-FIX-1','FL-FIX-1');""")
    assert "STATE_HELD_TAX_LAND|QUOTED_ON_APPLICATION" in out and out.count("violates check constraint") == 2
    assert scratch020("select count(*) from public.properties where inventory_type is not null;").strip() == before
    assert scratch020("select count(*) from public.properties where state='AL';").strip() == "0"
