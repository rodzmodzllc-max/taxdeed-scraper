"""ePropertyPlus land banks, batch 2 (2026-10-25): Cook County Land Bank (IL).

The fixture (tests/python/fixtures/illinois/) carries the LIVE field names of
the public-cclba portal with SYNTHETIC values. Illinois is registered but NOT
activated, so the source is never requested; the adapter's per-portal
configuration is tested offline. Kansas City (MO) is a candidate only.
See docs/sources-batch-2026-10-25-epropertyplus.md."""
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import harvest_expansion as HE  # noqa: E402
import source_publication as SP  # noqa: E402
from harvesters.governance import county_source_registry as csr  # noqa: E402
from harvesters.governance import permissions as P  # noqa: E402
from harvesters.governance import states  # noqa: E402
from harvesters.ledgers import SOURCE_LEDGERS, Ledger  # noqa: E402
from harvesters.otc.adapters import epropertyplus as EPP, expansion as EX  # noqa: E402
from harvesters.otc.model import AmountKind  # noqa: E402

AT = datetime(2026, 10, 25, 12, tzinfo=timezone.utc)
FX = ROOT / "tests/python/fixtures/illinois/il_cook_landbank.json"
SID = "il_cook_landbank"
COOK = EX.IL_COOK_LANDBANK


def _pages():
    return json.loads(FX.read_text())


def _fetch(pages):
    def fj(url):
        n = int(url.split("page=")[1].split("&")[0])
        return pages[min(n, len(pages)) - 1]
    return fj


def test_illinois_is_registered_but_not_activated():
    assert states.get_state("IL") is not None
    assert not states.is_activated("IL") and "IL" not in states.PRODUCTION_STATES
    assert states.activation_blockers("IL")


def test_shelby_requirements_are_unchanged_by_the_generalised_adapter():
    assert EPP.required_fields(EX.TN_SHELBY_LANDBANK) == EPP.REQUIRED
    assert EPP.required_fields(COOK) == ("parcelNumber", "currentStatus", "county")


def test_cook_reads_list_presence_excludes_targets_other_counties_bad_ids_and_duplicates():
    res = EPP.fetch_all(COOK, _fetch(_pages()), retrieved_at=AT)
    # A read row whose parcel id fails the pattern makes the read INCOMPLETE
    # (good rows kept, nothing closed); without it the same read is COMPLETE.
    assert res.outcome == "INCOMPLETE"
    clean = _pages()
    clean[1]["rows"] = [r for r in clean[1]["rows"] if r["parcelNumber"] != "SYNTHETIC-BAD"]
    for p in clean:
        p["size"] = 5
    assert EPP.fetch_all(COOK, _fetch(clean), retrieved_at=AT).outcome == "COMPLETE"
    recs = {r.case_no: r for r in res.records}
    assert set(recs) == {"00-00-000-000-0001", "00-00-000-000-0002"}
    assert (res.excluded_status, res.excluded_county, res.rejected_ids, res.duplicates) == (1, 1, 1, 1)
    a, b = recs["00-00-000-000-0001"], recs["00-00-000-000-0002"]
    assert a.validate() == [] and b.validate() == []
    # The row's own status is kept verbatim; nothing is inferred from it.
    assert (a.source_status_text, b.source_status_text) == ("Acquired", "Rehab In Progress")
    # minimumBid is the one amount; askingPrice is never mapped.
    assert a.amount == 1500 and a.amount_kind is AmountKind.OPENING_BID
    assert b.amount is None and b.amount_kind is AmountKind.NOT_PUBLISHED
    assert a.county == "Cook" and a.state == "IL" and a.latitude == 41.85
    assert a.list_as_of is None and "never the read time" in a.provenance["list_as_of"]
    assert "never currentStatus = 'TARGET - DLQT TAXES'" in a.provenance["offered_rule"]
    assert "comments" not in json.dumps(a.provenance) and "SYNTHETIC FREE TEXT" not in repr(a)
    # No per-parcel purchase link is constructed.
    assert a.purchase_url == COOK.purchase_url and "00-00" not in a.purchase_url


def test_a_page_without_the_county_field_is_a_format_change():
    pages = _pages()
    for r in pages[0]["rows"]:
        r.pop("county")
    res = EPP.fetch_all(COOK, _fetch(pages), retrieved_at=AT)
    assert res.outcome == "FAILED" and res.error_category == "PARSE_FORMAT_CHANGE" and "county" in res.error_detail


def test_harvest_refuses_illinois_before_any_request(monkeypatch, tmp_path):
    # requests is imported only after the gate passed: make any import fail loudly.
    monkeypatch.setitem(sys.modules, "requests", None)
    assert HE.main(["--state", "IL", "--out-dir", str(tmp_path)]) == 2
    assert not any(tmp_path.iterdir())
    reg = SP.registry_with_reviews("IL", reviews={})[0]
    problems = HE.gate("IL", reg=reg)
    assert any("not activated" in p for p in problems) and any(SID in p for p in problems)
    run, gated = HE.runnable_sources("IL", reg)
    assert run == [] and gated == [(SID, "STATE_NOT_ACTIVATED")]


def test_fixture_run_parses_offline(tmp_path):
    out = tmp_path / "il"
    assert HE.main(["--state", "IL", "--fixture", f"{SID}={FX}", "--out-dir", str(out)]) == 0
    rows = json.loads((out / "il_properties_rows.json").read_text())
    assert sorted(r["case_no"] for r in rows) == ["00-00-000-000-0001", "00-00-000-000-0002"]
    assert all(r["source"] == "laft" and r["state"] == "IL" for r in rows)


def test_registry_row_is_an_unrunnable_unreviewed_candidate():
    (row,) = [r for r in csr.load_registry() if r.source_id == SID]
    assert (row.state, row.county, row.harvester, row.publication_status) == ("IL", "Cook", "", "UNREVIEWED")
    assert row.verification_status == "MANUAL_REVIEW_REQUIRED" and row.governance_status == "TERMS_NOT_VERIFIED"
    assert not row.is_production and not row.runnable
    assert row.canonical_url.startswith("https://public-cclba.epropertyplus.com/")
    assert SOURCE_LEDGERS[SID] == frozenset({Ledger.AVAILABLE})
    assert EX.PUBLICATION[SID][0] == "UNREVIEWED"


def test_permissions_allow_collection_only_and_never_display():
    for op in ("fetch", "parse", "store"):
        d = P.authorize(SID, op, state="IL", county="Cook")
        assert d.allowed and not d.documented, op
    for op in ("display", "redistribute", "enrich"):
        assert not P.authorize(SID, op, state="IL", county="Cook").allowed, op
    with open(ROOT / "data/source_permissions.csv", encoding="utf-8", newline="") as fh:
        rows = [r for r in csv.DictReader(fh) if r["source_id"] == SID]
    assert {r["operation"] for r in rows} == {"fetch", "parse", "store"}
    for r in rows:
        assert (r["status"], r["evidence_type"], r["effective_on"], r["expires_on"], r["conditions"]) == (
            "OWNER_PERMISSION_REQUIRED", "INTERNAL_RISK_ACCEPTANCE", "2026-10-25", "2027-04-12", "excluded_from_paid_tier")
        assert r["reason"].endswith("not sold until legal review.")


def test_financial_terms_name_the_portal_field():
    with open(ROOT / "data/available_financial_terms.csv", encoding="utf-8", newline="") as fh:
        (t,) = [r for r in csv.DictReader(fh) if r["source_id"] == SID]
    assert t["state"] == "IL" and t["basis"] == "MINIMUM_BID" and "minimumBid" in t["quote"]


@pytest.mark.parametrize("sid", ["mo_kc_landbank_portal"])
def test_kansas_city_is_a_candidate_only(sid):
    assert all(s.config.source_id != sid for srcs in EX.SOURCES.values() for s in srcs)
    assert sid not in SOURCE_LEDGERS and all(r.source_id != sid for r in csr.load_registry())
    with open(ROOT / "data/available_source_candidates.csv", encoding="utf-8", newline="") as fh:
        (c,) = [r for r in csv.DictReader(fh) if r["source_id"] == sid]
    assert (c["state"], c["county"]) == ("MO", "Jackson") and "could not be verified" in c["program"]
