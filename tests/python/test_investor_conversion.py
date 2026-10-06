"""Investor-conversion sprint (2026-10-05): the Available "How to acquire"
section, the saved-property return path, financial-terms coverage for every
visible Available source, and the privacy-safe activation funnel. Static
checks against the shipped files; no network, no database."""
from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from harvesters.governance.county_source_registry import load_registry  # noqa: E402

APP = (ROOT / "public" / "app.js").read_text(encoding="utf-8")
SW = (ROOT / "public" / "sw.js").read_text(encoding="utf-8")


def _fn(name: str) -> str:
    m = re.search(r"function " + re.escape(name) + r"\(p\) \{(.*?)\n\}\n", APP, re.S)
    assert m, name
    return m.group(1)


def test_every_visible_available_source_has_source_backed_financial_terms():
    terms = {(r["state"], r["source_id"]) for r in csv.DictReader(open(ROOT / "data/available_financial_terms.csv", encoding="utf-8"))}
    missing = sorted((r.state, r.source_id) for r in load_registry()
                     if "AVAILABLE" in str(r.ledgers).upper() and r.is_production and str(r.publication_status) != "BLOCKED"
                     and (r.state, r.source_id) not in terms)
    assert missing == [], missing


def test_how_to_acquire_answers_the_seven_questions_in_order():
    block = _fn("acquireBlockHtml")
    qs = ["What is this?", "What does the source say I need to pay?", "How do I acquire it?", "What form do I need?",
          "Where do I submit it?", "Who do I contact?", "What is the official source?"]
    pos = [block.index(f'"{q}"') for q in qs]
    assert pos == sorted(pos)
    assert 'detailSectionHtml("How to acquire"' in block
    assert '"No online purchase link on file"' in block and 'a.mode !== "online"' in block
    assert not re.search(r"\b(score|ROI|confidence|recommend)\b", block, re.I)


def test_submission_and_contact_come_only_from_the_verified_record():
    block = _fn("acquireBlockHtml")
    seg = block[block.index("// 5. Where do I submit it?"):block.index("// 7. What is the official source?")]
    # every value comes from acquisitionOf() (a.*) - nothing constructed from the row's address or parcel
    assert "p.address" not in seg and "p.parcel" not in seg
    assert "if (a.verified)" in seg


def test_links_are_marked_for_the_funnel_without_their_urls():
    assert 'data-acq-link="${f.kind === "purchase_instructions" ? "instructions" : "form"}"' in APP
    handler = APP[APP.index("const marked = a.dataset ? a.dataset.acqLink"):APP.index("}, true);", APP.index("const marked = a.dataset"))]
    assert '{ form: "application_opened", source: "acquisition_source_opened", instructions: "acquisition_instructions_opened" }' in handler
    assert "href" not in re.sub(r"const href = .*", "", handler.split("track(")[-1])


def test_activation_funnel_events_exist_in_the_existing_track_vocabulary():
    used = set(re.findall(r'\btrack\("([a-z_]+)"', APP)) | set(re.findall(r'\bevent = "([a-z_]+)"', APP)) | \
        set(re.findall(r'"(application_opened|acquisition_source_opened|acquisition_instructions_opened)"', APP))
    for e in ("state_selected", "county_selected", "property_viewed", "acquisition_section_viewed",
              "application_opened", "acquisition_instructions_opened", "acquisition_source_opened", "property_saved", "property_watched"):
        assert e in used, e
    m024 = (ROOT / "scripts/migrations/024_customer_monitoring_foundation.sql").read_text(encoding="utf-8")
    allowed = set(re.findall(r"'([a-z_]+)'", re.search(r"event in \((.*?)\)\),", m024, re.S).group(1)))
    assert used <= allowed, used - allowed


def test_saved_property_reuses_the_existing_watchlist():
    saved = _fn("savedAcquisitionHtml")
    for reader in ("acquisitionOf(p)", "amountInfo(p)", "acquisitionForms(p)", "availabilityLink(p)"):
        assert reader in saved
    assert "localStorage" not in saved and "sb.from(" not in saved          # no second list, no new storage
    assert 'data-action="openacq"' in saved
    modal = APP[APP.index("function renderBidListModal()"):APP.index("function openBidList()")]
    assert "savedAcquisitionHtml(p)" in modal and "BIDLIST" in modal
    assert 'action === "openacq"' in APP and '[data-section="acquire"]' in APP


def test_service_worker_cache_bumped():
    assert 'const CACHE = "tdw-shell-v104"' in SW
