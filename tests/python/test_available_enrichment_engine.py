"""All-sources AVAILABLE enrichment engine (2026-10-01): the unified source
model and inventory, document extraction, the orchestrator's gap / outcome /
coverage logic, the parcel enricher's governance and precedence, and the
manual workflow job. Offline: every network call is injected."""
import csv
import io
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import enrich_available as EA  # noqa: E402
import enrich_statewide_parcels as ESP  # noqa: E402
from harvesters.documents import extract as D  # noqa: E402
from harvesters.enrichment import parcels as P  # noqa: E402
from harvesters.enrichment import sources as PS  # noqa: E402
from harvesters.governance import states as ST  # noqa: E402
from harvesters.sources import inventory as INV  # noqa: E402
from harvesters.sources.model import UnifiedSource, governance_from_publication  # noqa: E402

NOW = datetime(2026, 10, 1, 20, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------- PDF fixtures

def text_pdf(pages: list[list[str]], title: str = "Lands Available Procedures", date: str = "20250131") -> bytes:
    """A minimal, valid multi-page text PDF (Helvetica), built by hand."""
    objs = []

    def add(body: bytes) -> int:
        objs.append(body)
        return len(objs)

    font = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    page_ids, pages_id = [], len(pages) * 2 + 2
    for lines in pages:
        stream = b"BT /F1 10 Tf 40 760 Td 12 TL " + b" ".join(
            b"(" + ln.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)").encode("latin-1") + b") '" for ln in lines) + b" ET"
        content = add(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
        page_ids.append(add(b"<< /Type /Page /Parent %d 0 R /MediaBox [0 0 612 792] /Contents %d 0 R "
                            b"/Resources << /Font << /F1 %d 0 R >> >> >>" % (pages_id, content, font)))
    kids = b" ".join(b"%d 0 R" % i for i in page_ids)
    assert add(b"<< /Type /Pages /Kids [" + kids + b"] /Count %d >>" % len(page_ids)) == pages_id
    catalog = add(b"<< /Type /Catalog /Pages %d 0 R >>" % pages_id)
    info = add(b"<< /Title (" + title.encode() + b") /ModDate (D:" + date.encode() + b"120000) >>")
    out, offsets = io.BytesIO(), []
    out.write(b"%PDF-1.4\n")
    for i, body in enumerate(objs, start=1):
        offsets.append(out.tell())
        out.write(b"%d 0 obj\n" % i + body + b"\nendobj\n")
    xref = out.tell()
    out.write(b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1))
    for off in offsets:
        out.write(b"%010d 00000 n \n" % off)
    out.write(b"trailer\n<< /Size %d /Root %d 0 R /Info %d 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, catalog, info, xref))
    return out.getvalue()


def scanned_pdf() -> bytes:
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (600, 300), "white")
    ImageDraw.Draw(img).text((20, 20), "PARCEL 123-4567-8 ADJUDICATED", fill="black")
    buf = io.BytesIO()
    img.save(buf, "PDF")
    return buf.getvalue()


PROCESS_PDF = text_pdf([
    ["LANDS AVAILABLE FOR TAXES - PURCHASE PROCEDURE",
     "To purchase a property, submit a written request to the Tax Deed Clerk.",
     "Contact the Clerk at (850) 555-0101 or taxdeeds@example-clerk.gov.",
     "Mail requests to P.O. Box 1234, Exampletown, FL 32000."],
    ["Payment must be made in certified funds within 10 days of the quote.",
     "A deposit is not required. Requests are processed first come, first served.",
     "List as of March 3, 2026",
     "Parcel 01-02-03-0004 Case 2024-TD-17 $1,250.00 sale 03/12/2026",
     "Parcel 09-09-09-0009 Case 2024-TD-18 $900.00"],
])


# ---------------------------------------------------------------- 1, 19: states

def test_every_supported_state_is_in_the_inventory():
    inv = INV.build_inventory()
    states = {s.state for s in inv}
    for st in ST.supported_states():
        assert st in states, st
    for st in ("FL", "TX", "AL", "AR", "LA", "MI", "WY", "SC", "CO", "WI"):
        assert st in states, st
    assert INV.inventory_problems() == []


def test_inventory_states_match_the_state_registry_not_a_literal():
    assert set(INV.supported_states()) == set(ST.supported_states())
    assert set(INV.production_states()) == set(ST.PRODUCTION_STATES)


# ---------------------------------------------------------------- governance model

def test_three_governance_states_are_distinct_and_mapped_mechanically():
    assert governance_from_publication("APPROVED")[0] == "APPROVED"
    assert governance_from_publication("APPROVED_GRANDFATHERED")[0] == "APPROVED"
    assert governance_from_publication("UNREVIEWED")[0] == "REVIEW_REQUIRED"
    assert governance_from_publication("RESTRICTED")[0] == "REVIEW_REQUIRED"
    assert governance_from_publication("BLOCKED")[0] == "HARD_BLOCKED"
    # documented override: LGBS's own rights audit is unresolved
    gov, why = governance_from_publication("APPROVED_GRANDFATHERED", source_id="tx_lgbs")
    assert gov == "REVIEW_REQUIRED" and "lgbs-rights-audit" in why


def test_lgbs_is_in_scope_as_review_required_never_dropped():
    inv = INV.build_inventory()
    lgbs = [s for s in inv if s.source_id.startswith("TX:") and s.source_id.endswith(":tx_lgbs")]
    assert len(lgbs) == 8 and all(s.governance == "REVIEW_REQUIRED" and s.may_access for s in lgbs)
    statewide = [s for s in inv if s.source_id == "tx_lgbs_statewide_api"]
    assert statewide and statewide[0].governance == "REVIEW_REQUIRED" and "95 counties" in statewide[0].governance_reason


def test_blocked_vendors_are_hard_blocked_and_never_accessed():
    inv = INV.build_inventory()
    blocked = [s for s in inv if s.governance == "HARD_BLOCKED"]
    assert {s.source_id.split(":")[-1] for s in blocked if s.origin == "registry"} >= {"tx_pbfcm", "tx_mvba"}
    assert all(s.access == "NOT_ACCESSED_BLOCKED" and not s.may_access and not s.may_write for s in blocked)
    with pytest.raises(ValueError):
        UnifiedSource("x", "FL", "Lee", "x", "x", "THIRD_PARTY", "", governance="HARD_BLOCKED", governance_reason="r",
                      access="ACCESSIBLE")


def test_review_required_needs_a_reason_and_never_writes():
    with pytest.raises(ValueError):
        UnifiedSource("x", "FL", "Lee", "x", "x", "GIS", "", governance="REVIEW_REQUIRED")
    s = UnifiedSource("x", "FL", "Lee", "x", "x", "GIS", "", governance="REVIEW_REQUIRED", governance_reason="terms")
    assert s.may_access and not s.may_write


def test_every_source_type_class_is_represented():
    types = {s.source_type for s in INV.build_inventory()}
    assert types >= {"GOVERNMENT", "DOCUMENT", "GIS", "COURT_PUBLIC_RECORD", "PUBLIC_NOTICE", "AUCTION_VENDOR",
                     "THIRD_PARTY", "FEDERAL_DATASET"}


def test_catalog_rows_are_valid_and_carry_their_basis():
    with (ROOT / "data" / "enrichment_source_catalog.csv").open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert rows
    for r in rows:
        assert r["governance"] in ("REVIEW_REQUIRED", "HARD_BLOCKED")
        assert r["governance_reason"] and r["evidence"] and r["next_action"]
        if r["governance"] == "HARD_BLOCKED":
            assert not r["url"] and r["access"] == "NOT_ACCESSED_BLOCKED"


def test_streetview_is_hard_blocked():
    sv = [s for s in INV.build_inventory() if s.source_id == "streetview_imagery"]
    assert sv and sv[0].governance == "HARD_BLOCKED"


# ---------------------------------------------------------------- 3, 4, 12, 15, 16: documents

def test_text_pdf_pages_title_date_and_provenance():
    doc = D.read_document(PROCESS_PDF, url="https://clerk.example.gov/lands.pdf", content_type="application/pdf")
    assert doc.method == "pdf_text" and doc.ocr_status == "NOT_NEEDED" and len(doc.pages) == 2 and doc.readable
    assert doc.title == "Lands Available Procedures" and doc.document_date == "2025-01-31"
    prov = doc.provenance(2)
    assert prov["source_url"] == "https://clerk.example.gov/lands.pdf" and prov["page"] == 2 and prov["extracted_at"]


def test_acquisition_facts_with_pages():
    doc = D.read_document(PROCESS_PDF, url="https://clerk.example.gov/lands.pdf")
    f = D.acquisition_facts(doc)
    assert {"value": "(850) 555-0101", "page": 1} in f["phones"]
    assert {"value": "taxdeeds@example-clerk.gov", "page": 1} in f["emails"]
    assert f["mailing_addresses"] and f["mailing_addresses"][0]["page"] == 1
    assert any("certified funds" in p["text"] and p["page"] == 2 for p in f["payment"])
    assert any("submit a written request" in s["text"] for s in f["steps"])
    assert any(d["date"] == "March 3, 2026" and d["page"] == 2 for d in f["dates"])
    assert f["provenance"]["source_url"] == "https://clerk.example.gov/lands.pdf"


def test_document_identifier_match_is_deterministic():
    doc = D.read_document(PROCESS_PDF, url="u.pdf")
    hits = D.find_identifier_records(doc, ["01-02-03-0004", "01020300 04", "77-77"], "alnum")
    assert hits["010203000 4".replace(" ", "")].status == "MATCHED" and hits["010203000 4".replace(" ", "")].page == 2
    assert hits["7777"].status == "MATCH_FAILED"


def test_document_ambiguous_identifier_fails_closed():
    doc = D.read_document(text_pdf([["Parcel 55-1 sold", "Parcel 55-1 resale"]]), url="u.pdf")
    assert D.find_identifier_records(doc, ["55-1"], "alnum")["551"].status == "AMBIGUOUS"
    assert D.notice_records(doc, ["55-1"], "alnum") == {}


def test_public_notice_extraction_keeps_url_and_page():
    doc = D.read_document(PROCESS_PDF, url="https://notices.example.com/n/1.pdf")
    rec = D.notice_records(doc, ["01-02-03-0004"], "alnum")
    (key, r), = rec.items()
    assert r["amounts"] == ["$1,250.00"] and r["dates"] == ["03/12/2026"]
    assert r["source_url"] == "https://notices.example.com/n/1.pdf" and r["page"] == 2


def test_scanned_pdf_is_never_guessed_without_ocr(monkeypatch):
    monkeypatch.setattr(D, "_ocr_available", lambda: False)
    doc = D.read_document(scanned_pdf(), url="scan.pdf")
    assert doc.ocr_status == "OCR_UNAVAILABLE" and not doc.readable
    assert D.find_identifier_records(doc, ["123-4567-8"], "alnum")["12345678"].status == "MATCH_FAILED"


def test_scanned_pdf_uses_ocr_when_available(monkeypatch):
    class FakeTess:
        @staticmethod
        def image_to_string(img):
            return "PARCEL 123-4567-8 ADJUDICATED"
    monkeypatch.setattr(D, "_ocr_available", lambda: True)
    monkeypatch.setitem(sys.modules, "pytesseract", FakeTess)
    doc = D.read_document(scanned_pdf(), url="scan.pdf")
    assert doc.ocr_status == "OCR_USED" and doc.pages[0].ocr
    assert D.find_identifier_records(doc, ["123-4567-8"], "alnum")["12345678"].status == "MATCHED"


def test_csv_and_corrupt_documents():
    doc = D.read_document(b"parcel,amount\n01-02,$5\n", url="list.csv", content_type="text/csv")
    assert doc.method == "csv" and D.find_identifier_records(doc, ["01-02"], "alnum")["0102"].status == "MATCHED"
    bad = D.read_document(b"%PDF-1.4 not really", url="x.pdf")
    assert bad.method == "unreadable" and not bad.readable and bad.error


def test_summary_is_value_free():
    s = D.summarize(D.read_document(PROCESS_PDF, url="u.pdf"))
    assert "0004" not in json.dumps(s) and s["phones"] == 1 and s["pages"] == 2


# ---------------------------------------------------------------- 2, 18: every row, >1,000

def _row(i, **kw):
    base = {"id": f"r{i:05d}", "state": "LA", "county": "East Baton Rouge", "parcel": f"{i:03d}-0000-1",
            "publication_status": "APPROVED", "last_seen_at": "2026-10-01T18:00:00+00:00", "source_id": "la_ebr_adjudicated"}
    base.update(kw)
    return base


def test_every_available_row_is_counted_and_over_1000_rows():
    rows = [_row(i) for i in range(2500)] + [_row(5000 + i, state="FL", county="Putnam") for i in range(10)]
    cov = EA.coverage(rows, now=NOW)
    assert cov["totals"]["available_records"] == 2510
    la = next(u for u in cov["units"] if u["state"] == "LA")
    assert la["available_records"] == 2500
    # every row is classified for every missing dimension
    assert sum(la["gap_outcomes"]["imagery"].values()) == 2500


def test_fetch_rows_pages_every_state(monkeypatch):
    pages = {"LA": [[{"id": i} for i in range(1000)], [{"id": i} for i in range(1000, 1500)]], "FL": [[{"id": "f"}]]}
    calls = []

    def fake(url, headers=None, timeout=0):
        st = url.split("state=eq.")[1].split("&")[0]
        calls.append(url)
        return pages[st].pop(0) if pages[st] else []
    monkeypatch.setattr(ESP, "http_json", fake)
    rows = EA.fetch_rows("https://x", "k", ["LA", "FL"])
    assert len(rows) == 1501 and all("order=id.asc" in c and "limit=1000" in c for c in calls)


# ---------------------------------------------------------------- outcomes

def test_gap_outcomes_distinguish_review_from_none_from_blocked():
    inv = INV.build_inventory()
    la = INV.sources_for("LA", "East Baton Rouge", inventory=inv)
    row = _row(1, latitude=30.4, longitude=-91.1)
    assert EA.gap_outcome(row, "acreage", la) == "SOURCE_REVIEW_REQUIRED"          # only the copyright ArcGIS service
    assert EA.gap_outcome(row, "imagery", la) == "SOURCE_FOUND"                    # NAIP, approved
    assert EA.gap_outcome(_row(2), "imagery", la) == "NEEDS_COORDINATES"
    blocked = [UnifiedSource("b", "TX", "Leon", "b", "b", "THIRD_PARTY", "", frozenset({"acreage"}),
                             governance="HARD_BLOCKED", governance_reason="r", access="NOT_ACCESSED_BLOCKED")]
    assert EA.gap_outcome(row, "acreage", blocked) == "SOURCE_HARD_BLOCKED"
    assert EA.gap_outcome(row, "acreage", []) == "NO_SOURCE_FOUND"
    assert EA.gap_outcome(row, "acreage", la, match_outcome="AMBIGUOUS") == "MATCH_FAILED"


def test_review_required_does_not_stop_other_dimensions():
    """LA acreage / land use are REVIEW_REQUIRED; imagery / flood are still eligible."""
    rows = [_row(i, latitude=30.4, longitude=-91.1) for i in range(5)]
    la = EA.coverage(rows, now=NOW)["units"][0]
    assert la["gap_outcomes"]["acreage"] == {"SOURCE_REVIEW_REQUIRED": 5}
    assert la["gap_outcomes"]["imagery"] == {"SOURCE_FOUND": 5}
    assert la["gap_outcomes"]["flood"] == {"SOURCE_FOUND": 5}


def test_capture_outcomes_explain_acquisition_gaps():
    row = _row(1, state="FL", county="Sarasota")
    srcs = INV.sources_for("FL", "Sarasota")
    assert EA.gap_outcome(row, "acquisition", srcs, capture_outcome="SOURCE_UNAVAILABLE") == "SOURCE_UNAVAILABLE"
    assert EA.coverage([row], now=NOW)["units"][0]["gap_outcomes"]["acquisition"] == {"SOURCE_UNAVAILABLE": 1}


def test_imagery_checked_empty_is_not_a_gap():
    assert "imagery" not in EA.row_gaps(_row(1, photo_url=""))
    assert "imagery" in EA.row_gaps(_row(1, photo_url=None))


# ---------------------------------------------------------------- 10, 14: availability / freshness

def test_source_failure_never_closes_or_hides_available_inventory():
    stale = _row(1, last_seen_at="2026-09-01T00:00:00+00:00")
    manual = _row(2, state="TX", county="Leon", last_seen_at=None, source_id="tx_lgbs",
                  publication_status="APPROVED_GRANDFATHERED")
    cov = EA.coverage([stale, manual, _row(3)], now=NOW)
    assert cov["totals"]["available_records"] == 3                     # nothing dropped
    assert EA.availability(stale, now=NOW)[0] == "NOT_VERIFIED_AVAILABLE"
    status, why = EA.availability(manual, now=NOW, manual_only=frozenset({"tx_lgbs"}))
    assert status == "NOT_VERIFIED_AVAILABLE" and "manual-only" in why
    assert EA.availability(_row(3), now=NOW)[0] == "VERIFIED_AVAILABLE"
    src = (ROOT / "scripts" / "enrich_available.py").read_text()
    for forbidden in ('"status": "closed"', "delisted_at", "publication_status\": "):
        assert forbidden not in src


# ---------------------------------------------------------------- 6, 7, 9, 11, 13: parcel enricher

def _cfg(**kw):
    base = dict(source_id="t_layer", state="LA", agency="A", dataset="D", landing_url="https://x",
                layer_url="https://x.example/arcgis/rest/services/P/FeatureServer/0", id_field="PIN", id_rule="alnum",
                field_map={"acreage": "ACRES", "legal_desc": "LEGAL"}, licence="Public Domain", publication_status="APPROVED",
                columns_verified=True, counties=("East Baton Rouge",))
    base.update(kw)
    return P.ParcelSourceConfig(**base)


def _feature(pin, acres=1.5, legal="LOT 1"):
    return {"attributes": {"PIN": pin, "ACRES": acres, "LEGAL": legal}}


def test_deterministic_match_writes_with_provenance_and_url():
    cfg = _cfg()
    rows = [_row(1, parcel="111-0000-1"), _row(2, parcel="222-0000-1")]
    writes = {}
    rep = ESP.run("LA", rows, lambda url: {"features": [_feature("1110000-1")]}, write=writes.__setitem__,
                  recorded_at="2026-10-01T00:00:00+00:00", cfg=cfg, outcomes=(oc := {}))
    assert oc == {"r00001": "MATCHED", "r00002": "UNMATCHED"}
    assert set(writes) == {"r00001"} and writes["r00001"]["acreage"] == 1.5
    prov = writes["r00001"]["field_provenance"]["acreage"]
    assert prov["layer_url"] == cfg.layer_url and prov["source_id"] == "t_layer" and prov["matched_parcel_id"] == "11100001"
    assert rep["matched"] == 1 and rep["unmatched"] == 1


def test_ambiguous_parcel_match_writes_nothing():
    rows = [_row(1, parcel="111-0000-1")]
    writes = {}
    ESP.run("LA", rows, lambda url: {"features": [_feature("1110000-1"), _feature("111-0000-1", acres=9)]},
            write=writes.__setitem__, recorded_at="t", cfg=_cfg(), outcomes=(oc := {}))
    assert oc == {"r00001": "AMBIGUOUS"} and writes == {}


def test_stronger_existing_evidence_is_not_overwritten():
    row = _row(1, parcel="111-0000-1", legal_desc="LOT 9 BLK 2 (county list)",
               field_provenance={"legal_desc": {"source": "county_list"}})
    writes = {}
    ESP.run("LA", [row], lambda url: {"features": [_feature("1110000-1")]}, write=writes.__setitem__,
            recorded_at="t", cfg=_cfg())
    assert "legal_desc" not in writes.get("r00001", {}) and writes["r00001"]["acreage"] == 1.5


def test_source_failure_attaches_nothing_and_is_reported():
    def boom(url):
        raise OSError("down")
    writes = {}
    ESP.run("LA", [_row(1, parcel="111-0000-1")], boom, write=writes.__setitem__, recorded_at="t", cfg=_cfg(),
            outcomes=(oc := {}))
    assert writes == {} and oc == {"r00001": "SOURCE_UNAVAILABLE"}


def test_review_required_layer_is_never_queried_or_written(monkeypatch):
    unreviewed = _cfg(source_id="t_unrev", publication_status="UNREVIEWED")
    approved = _cfg(source_id="t_ok", counties=("Other Parish",))
    monkeypatch.setattr(EA, "all_sources", lambda: [unreviewed, approved])
    monkeypatch.setattr(ST, "is_activated", lambda s: True)
    calls = []
    reports, _ = EA.parcel_plan([_row(1, parcel="111-0000-1"), _row(2, county="Other Parish", parcel="111-0000-1")],
                                lambda url: calls.append(url) or {"features": [_feature("1110000-1")]},
                                write=None, recorded_at="t")
    by = {r["source_id"]: r for r in reports}
    assert by["t_unrev"]["governance"] == "REVIEW_REQUIRED" and "rows_considered" not in by["t_unrev"]
    assert by["t_ok"]["matched"] == 1          # the other, approved source still ran
    assert len(calls) == 1


def test_plan_mode_writes_nothing(monkeypatch):
    monkeypatch.setattr(EA, "all_sources", lambda: [_cfg()])
    monkeypatch.setattr(ST, "is_activated", lambda s: True)
    patched = []
    monkeypatch.setattr(ESP, "patch", lambda *a: patched.append(a))
    reports, oc = EA.parcel_plan([_row(1, parcel="111-0000-1")], lambda url: {"features": [_feature("1110000-1")]},
                                 write=None, recorded_at="t")
    assert patched == [] and reports[0]["rows_written"] == 1 and oc == {"r00001": "MATCHED"}


def test_county_scoped_layers_coexist_with_a_statewide_one():
    assert PS.for_state("LA").source_id == "la_ebr_tax_parcels"
    assert [c.source_id for c in PS.for_county("LA", "East Baton Rouge")] == ["la_ebr_tax_roll", "la_ebr_tax_parcels"]  # county roll first
    assert _cfg().covers("East Baton Rouge") and not _cfg().covers("Orleans")
    with pytest.raises(ValueError):
        PS.register(PS.LA_EBR_TAX_PARCELS)                          # same id twice


# ---------------------------------------------------------------- 5: provenance / 17: publication separate

def test_other_enricher_plan_respects_storage_and_prerequisites():
    rows = [_row(1, latitude=1, longitude=1), _row(2, latitude=1, longitude=1, photo_url=""), _row(3),
            _row(4, address="12 Main St, Baton Rouge")]
    plan = EA.other_enricher_plan(rows, storage_headroom_bytes=46000)
    assert plan["imagery"]["eligible_rows"] == 1 and plan["imagery"]["expected_writes"] == 1
    assert EA.other_enricher_plan(rows, storage_headroom_bytes=0)["imagery"]["expected_writes"] == 0
    assert plan["flood"]["eligible_rows"] == 2 and plan["geocode"]["eligible_rows"] == 1


def test_customer_publication_stays_separate_from_governance():
    """The engine never writes publication_status; the unified model maps but
    never rewrites the registry's publication decision."""
    src = (ROOT / "scripts" / "enrich_available.py").read_text() + (ROOT / "harvesters" / "sources" / "inventory.py").read_text()
    assert "publication_status\"]" not in src and "PATCH" not in (ROOT / "harvesters" / "sources" / "inventory.py").read_text()
    lgbs = next(s for s in INV.build_inventory() if s.source_id == "TX:Leon:tx_lgbs")
    assert lgbs.legacy_status == "APPROVED_GRANDFATHERED" and lgbs.governance == "REVIEW_REQUIRED"


def test_markdown_and_report_are_value_free():
    rows = [_row(1, parcel="SECRET-PARCEL-999", latitude=1, longitude=1)]
    report = {"mode": "plan", "coverage": EA.coverage(rows, now=NOW), "parcels": [], "other_enrichers": EA.other_enricher_plan(rows, storage_headroom_bytes=None)}
    text = EA.markdown(report) + json.dumps(report, default=str)
    assert "SECRET-PARCEL" not in text


# ---------------------------------------------------------------- workflow

def _wf():
    return yaml.safe_load((ROOT / ".github/workflows/harvest-and-sync.yml").read_text(encoding="utf-8"))


def test_available_job_is_manual_only_and_scoped():
    wf = _wf()
    job = wf["jobs"]["available"]
    assert job["if"] == "github.event_name == 'workflow_dispatch' && github.event.inputs.job == 'available'"
    inputs = (wf.get("on") or wf.get(True))["workflow_dispatch"]["inputs"]
    assert inputs["available_mode"]["options"] == ["plan", "metadata", "probe", "discover", "apply", "acquisition", "imagery"] and inputs["available_mode"]["default"] == "plan"
    runs = "\n".join(s.get("run", "") for s in job["steps"])
    # LGBS is authorized for the AVAILABLE sprint (2026-10-01) ONLY through the
    # AVAILABLE-scoped refresh: never the harvester's main(), never the Texas
    # sync (which upserts the auction ledger too).
    assert "texas_harvester" not in runs and "sync-texas" not in runs
    # (apply_acquisition_paths.py only NAMES the tx_lgbs source; it makes no request to any source.)
    lgbs_lines = [ln for ln in runs.splitlines() if "lgbs" in ln.lower() and "apply_acquisition_paths.py" not in ln]
    assert lgbs_lines and all("scripts/lgbs_available_refresh.py" in ln for ln in lgbs_lines)
    assert "enrich_available.py --plan --label before" in runs and "enrich_available.py --apply" in runs
    apply_steps = [s for s in job["steps"] if "apply" in str(s.get("if", "")) and "Plan" not in s["name"]]
    assert all(s.get("continue-on-error") for s in apply_steps)      # one enricher failing never stops the rest


def test_discovery_never_requests_hard_blocked_sources():
    import discover_sources as DS
    for st in INV.production_states():
        for county in {s.county for s in INV.build_inventory() if s.state == st}:
            for sid, url in DS.document_urls(st, county):
                src = next(s for s in INV.build_inventory() if s.source_id == sid)
                assert src.may_access, sid
    assert DS.mask("parcel 123456789 page 2") == "parcel ######### page 2"


def test_source_inventory_json_is_current_and_value_free():
    import build_source_inventory as B
    assert (ROOT / "public" / "source-inventory.json").read_text(encoding="utf-8") == B.render()
    assert (ROOT / "source-inventory.json").read_text(encoding="utf-8") == B.render()     # root mirror
    doc = json.loads(B.render())
    assert set(doc["states"]) == set(ST.supported_states()) and doc["sources"]
    assert "@" not in B.render()


def test_html_pages_are_read_as_visible_text():
    html = (b"<!DOCTYPE html><html><head><title>Lands Available</title><script>var tracking=1</script></head>"
            b"<body><nav>Home | Courts</nav><p>To purchase a property, contact the Tax Deed Clerk at (850) 555-0102.</p>"
            b"<footer>(999) 999-9999 footer</footer></body></html>")
    doc = D.read_document(html, url="https://clerk.example.gov/lands", content_type="text/html; charset=utf-8")
    assert doc.method == "html" and doc.title == "Lands Available"
    text = doc.pages[0].text
    assert "tracking" not in text and "Home | Courts" not in text and "footer" not in text
    f = D.acquisition_facts(doc)
    assert [p["value"] for p in f["phones"]] == ["(850) 555-0102"]
    assert any("contact the Tax Deed Clerk" in s["text"] for s in f["steps"])


def test_jim_wells_cad_is_implemented_but_gated_until_reviewed():
    cfg = PS.TX_JIM_WELLS_CAD
    assert cfg.counties == ("Jim Wells",) and cfg.row_id_column == "case_no" and cfg.id_field == "geoID"
    ok, why = P.enrichment_allowed(cfg)
    assert not ok and "UNREVIEWED" in why
    src = next(s for s in INV.build_inventory() if s.source_id == "tx_jim_wells_cad_parcels")
    assert src.governance == "REVIEW_REQUIRED" and not src.may_write and src.may_access
    # the engine reports the review requirement; it never queries or writes it
    row = _row(1, state="TX", county="Jim Wells", case_no="1234567890123", latitude=1, longitude=1)
    assert EA.gap_outcome(row, "acreage", INV.sources_for("TX", "Jim Wells")) == "SOURCE_REVIEW_REQUIRED"


def test_la_tax_parcels_now_fill_legal_description_blank_only():
    cfg = PS.LA_EBR_TAX_PARCELS
    rows = [_row(1, parcel="111-0000-1"), _row(2, parcel="222-0000-1", legal_desc="FROM THE LIST",
                                                field_provenance={"legal_desc": {"source": "county_list"}})]
    feats = [{"attributes": {"assessment_num": "111-0000-1", "legal_description": "LOT 4 SUB A"}},
             {"attributes": {"assessment_num": "222-0000-1", "legal_description": "OTHER TEXT"}}]
    writes = {}
    ESP.run("LA", rows, lambda url: [f["attributes"] for f in feats], write=writes.__setitem__, recorded_at="t", cfg=cfg)
    assert writes["r00001"]["legal_desc"] == "LOT 4 SUB A"
    assert "r00002" not in writes or "legal_desc" not in writes["r00002"]


def test_execution_priority_imagery_never_shares_a_run_with_priority_enrichment():
    """AVAILABLE customer value first, imagery last (docs section 8): apply runs
    the priority 1-2 enrichers only; imagery is its own short, bounded mode."""
    job = _wf()["jobs"]["available"]
    naip = [s for s in job["steps"] if "enrich_property_photos_naip.py" in s.get("run", "")]
    assert len(naip) == 1
    step = naip[0]
    assert step["if"] == "github.event.inputs.available_mode == 'imagery'"
    assert int(step["env"]["NAIP_BATCH_LIMIT"]) <= 600 and step["timeout-minutes"] <= 60 and step.get("continue-on-error")
    apply_runs = "\n".join(s.get("run", "") for s in job["steps"] if "'apply'" in str(s.get("if", "")))
    assert "naip" not in apply_runs.lower()
    assert "enrich_available.py --apply" in apply_runs and "enrich_flood_zone.py" in apply_runs
    order = [s["name"] for s in job["steps"]]
    assert order.index(next(n for n in order if n.startswith("Apply - cleared parcel"))) < order.index(step["name"])
