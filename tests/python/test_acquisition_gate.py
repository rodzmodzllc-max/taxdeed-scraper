"""The acquisition-path gate (2026-10-10): a customer-actionable AVAILABLE
row needs a verified acquisition route, a customer-published source and a
current record - a typed path, a URL or a date alone never passes.
The shared vectors also drive the app.js mirror (tests/run_test.mjs)."""
import json
import re
from pathlib import Path

import pytest

from harvesters.sources import acquisition_gate as G

REPO = Path(__file__).resolve().parents[2]
CASES = json.loads((REPO / "tests/python/fixtures/acquisition_gate_cases.json").read_text(encoding="utf-8"))
TODAY = __import__("datetime").date.fromisoformat(CASES["today"])


def _ref(v):
    return CASES[v] if isinstance(v, str) else v


@pytest.mark.parametrize("case", CASES["cases"], ids=[c["name"][:60] for c in CASES["cases"]])
def test_vectors(case):
    got = G.verify(case["row"], unit=_ref(case["unit"]), record=_ref(case["record"]), today=TODAY)
    assert got.verified == case["expect"]["verified"], got
    assert got.reasons == case["expect"]["reasons"], got
    assert got.classification == case["expect"]["classification"], got


def test_every_reason_has_a_label_and_a_class_and_every_class_a_label():
    assert set(G.REASONS) == set(G.CLASS_OF_REASON)
    assert set(G.CLASS_OF_REASON.values()) <= set(G.CLASSES)
    assert set(G.CLASS_LABELS) == set(G.CLASSES)
    assert set(G.CLASS_PRECEDENCE) == set(G.CLASSES) - {"verified"}


def test_a_typed_path_url_source_label_or_date_alone_is_never_proof():
    row = {"source_id": "fl_laft_pioneer", "publication_status": "APPROVED_GRANDFATHERED", "status": "active",
           "last_seen_at": "2026-10-09T10:00:00Z", "purchase_path_type": "county_instructions",
           "purchase_url": "https://example-clerk.test/lands", "purchase_path_observed_on": "2026-10-01",
           "purchase_path_evidence": "The clerk page says so", "harvester_source": "fl_laft_pioneer"}
    assert not G.verify(row, unit=None, record=None, today=TODAY).verified
    assert not G.verify(row, unit={"status": "NEEDS_REVIEW"}, record=None, today=TODAY).verified


def test_untrusted_hosts_match_the_purchase_path_rules():
    import sys
    sys.path.insert(0, str(REPO / "scripts"))
    import laft_purchase_paths as PP
    assert set(G.UNTRUSTED_HOST_SUFFIXES) == set(PP.UNTRUSTED_HOST_SUFFIXES)


def test_has_channel_rules():
    assert G.has_channel({"application_url": "https://x.test/form.pdf"})
    assert G.has_channel({"steps": ["a"], "phone": "1"})
    assert G.has_channel({"steps": ["a"], "mailing_address": "PO Box 1"})
    assert not G.has_channel({"steps": ["a"]})
    assert not G.has_channel({"phone": "1"})
    assert not G.has_channel({"application_url": "http://x.test/form.pdf"})
    assert not G.has_channel(None)


def test_verified_units_in_the_shipped_evidence_file_are_assessed_not_assumed():
    """Every VERIFIED unit in public/acquisition-evidence.json either carries
    an actionable county record or the gate names the gap - never a silent pass."""
    data = json.loads((REPO / "public/acquisition-evidence.json").read_text(encoding="utf-8"))
    fresh = {"publication_status": "APPROVED", "status": "active", "last_seen_at": CASES["today"] + "T00:00:00Z"}
    for u in data["status"]:
        if u["status"] != "VERIFIED":
            continue
        rec = G.find_record(data["records"], u["state"], u["source_id"], u["county"])
        v = G.verify(dict(fresh, source_id=u["source_id"]), unit=u, record=rec, today=TODAY)
        if rec is None:
            assert "EVIDENCE_NO_RECORD" in v.reasons, u
        else:
            assert "EVIDENCE_UNIT_UNKNOWN" not in v.reasons and "EVIDENCE_NO_RECORD" not in v.reasons, u


def test_app_js_mirrors_the_vocabulary():
    app = (REPO / "public/app.js").read_text(encoding="utf-8")
    assert "function acquisitionVerification(" in app
    for reason, label in G.REASONS.items():
        assert f'{reason}: "{label}"' in app, reason
    for cls, label in G.CLASS_LABELS.items():
        assert f'{cls}: "{label}"' in app, cls
    for name, value in (("ACQ_GATE_OBSERVATION_DAYS", G.OBSERVATION_DAYS), ("ACQ_GATE_LIST_DAYS", G.LIST_DAYS), ("ACQ_GATE_EVIDENCE_DAYS", G.EVIDENCE_DAYS)):
        assert re.search(rf"var {name} = {value};", app), name
    # Staged: off unless config.js says enforce, and never applied to an admin.
    assert 'String((window.TDW_CONFIG || {}).availableGate || "off")' in app
    cfg = (REPO / "config.js").read_text(encoding="utf-8")
    assert 'availableGate: "off"' in cfg
