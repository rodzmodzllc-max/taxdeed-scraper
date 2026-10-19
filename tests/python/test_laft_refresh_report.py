"""The weekly "Central Florida Tax-Deed Land Check" scheduled routine used
to republish an out-of-band claude.ai Artifact
(claude.ai/code/artifact/920fdffd-f73e-42ea-8091-1063c683b9c9) that scraped
county LAFT PDFs/pages directly, with no repository governance attached.
That artifact was deleted. This test proves the repository no longer
carries that dead dependency, and that its repository-backed replacement
(scripts/build_laft_refresh_report.py -> public/laft-refresh-report.json)
is current, deterministic and value-free: it never bypasses a publication
gate, never shows a HARD_BLOCKED source as accessed, and never carries a
parcel, price, acreage, address or owner field - that data stays behind
the governed AVAILABLE ledger / publication gate, never this report."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

from harvesters.sources import inventory as INV  # noqa: E402
from harvesters.sources.model import GOVERNANCE  # noqa: E402

import build_laft_refresh_report as R  # noqa: E402

DEAD_ARTIFACT_ID = "920fdffd-f73e-42ea-8091-1063c683b9c9"

# Keys a value-free governance report may never carry - the actual listing
# content (parcel, price, acreage, address, owner) lives behind the
# governed AVAILABLE ledger / publication gate, never here.
FORBIDDEN_KEYS = {"price", "amount", "bid", "acreage", "acres", "address",
                   "owner", "parcel_id", "parcel", "legal_description"}


def _report() -> dict:
    return json.loads(R.render())


def test_dead_artifact_id_is_not_referenced_anywhere_in_the_repository():
    """The routine's dependency was an out-of-band Artifact URL, never a
    repository file - but nothing in the repo should name it either, so a
    future edit can't accidentally reintroduce a reference to a deleted
    page as if it were still live."""
    this_file = Path(__file__).resolve()
    hits = []
    for path in REPO.rglob("*"):
        if ".git" in path.parts or "__pycache__" in path.parts or not path.is_file():
            continue
        if path.resolve() == this_file:
            continue  # this test's own docstring names the dead id, deliberately
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if DEAD_ARTIFACT_ID in text:
            hits.append(str(path.relative_to(REPO)))
    assert hits == []


def test_report_is_current():
    r = subprocess.run([sys.executable, str(REPO / "scripts" / "build_laft_refresh_report.py"), "--check"],
                        capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def test_covers_exactly_the_counties_the_dead_routine_named():
    doc = _report()
    counties = [c["county"] for c in doc["counties"]]
    assert counties == list(R.COUNTIES)


def test_every_source_has_the_availability_role_and_a_recognised_governance_state():
    doc = _report()
    inv = INV.build_inventory()
    for county in doc["counties"]:
        direct = {s.source_id for s in INV.sources_for("FL", county["county"], inv) if "availability" in s.roles}
        assert {s["source_id"] for s in county["sources"]} == direct
        for s in county["sources"]:
            assert s["governance"] in GOVERNANCE


def test_hard_blocked_sources_are_never_shown_as_accessed():
    doc = _report()
    for county in doc["counties"]:
        for s in county["sources"]:
            if s["governance"] == "HARD_BLOCKED":
                assert s["access"] == "NOT_ACCESSED_BLOCKED"


def test_report_carries_no_parcel_level_value():
    """A county with a tracked source is never confused for a list of
    parcels: every key in every source entry is a governance/identity
    fact, never a row value."""
    doc = _report()
    for county in doc["counties"]:
        for s in county["sources"]:
            assert set(s.keys()) & FORBIDDEN_KEYS == set()


def test_lake_has_no_approved_source_review_required_not_hidden():
    """Regression for the specific fact this report corrected: the dead
    routine assumed Lake/Hillsborough/Orange/... all needed an interactive
    browser session. The governed registry shows most of them already have
    an APPROVED harvester; Lake genuinely does not yet (REVIEW_REQUIRED,
    an unharvested_list placeholder) - the report must say so plainly,
    never omit the county or silently call it approved."""
    doc = _report()
    lake = next(c for c in doc["counties"] if c["county"] == "Lake")
    assert lake["sources"], "Lake must still be listed even with no approved source"
    assert all(s["governance"] != "APPROVED" for s in lake["sources"])
