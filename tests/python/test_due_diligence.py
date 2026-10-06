"""Due diligence evidence states (2026-10-06): Python rule = app.js rule."""
import json
import re
from pathlib import Path

import pytest

from harvesters.sources import due_diligence as DD

REPO = Path(__file__).resolve().parents[2]
CASES = json.loads((REPO / "tests/python/fixtures/due_diligence_cases.json").read_text(encoding="utf-8"))["cases"]
APP = (REPO / "public/app.js").read_text(encoding="utf-8")


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["name"])
def test_vectors(case):
    got = {i["key"]: i["state"] for i in DD.checklist(case["facts"])}
    for k, v in case["expect"].items():
        assert got[k] == v, (k, got[k], v)


def test_every_item_has_a_known_state_for_every_case():
    for case in CASES:
        items = DD.checklist(case["facts"])
        assert [i["key"] for i in items] == [k for k, _, _ in DD.ITEMS]
        assert all(i["state"] in DD.STATES for i in items)
        assert sum(DD.summary(items).values()) == len(DD.ITEMS)


def test_a_populated_value_without_evidence_is_never_verified():
    f = {"ledger": "laft", "legal": "unsourced", "acreage": "unsourced", "land_use": "unsourced", "values": "unsourced",
         "coords": "other", "parcel": True}               # parcel present but the list was never read
    st = {i["key"]: i["state"] for i in DD.checklist(f)}
    assert all(st[k] == "NOT_VERIFIED" for k in ("legal", "acreage", "land_use", "values", "coords", "parcel"))


def test_ledger_scoping_is_not_applicable_not_missing():
    for led, own in (("laft", "acq_"), ("auction", ""), ("certificate", "cert_")):
        st = {i["key"]: i["state"] for i in DD.checklist({"ledger": led})}
        if led != "laft":
            assert all(st[k] == "NOT_APPLICABLE" for k in st if k.startswith("acq_"))
        if led != "certificate":
            assert all(st[k] == "NOT_APPLICABLE" for k in st if k.startswith("cert_"))


def test_js_mirror_constants():
    labels = re.search(r"var DILIGENCE_STATE_LABELS = (?:DILIGENCE_STATE_LABELS \|\| )?\{(.*?)\};", APP, re.S).group(1)
    assert dict(re.findall(r"(\w+):\s*\"([^\"]+)\"", labels)) == DD.STATE_LABELS
    items = re.search(r"var DILIGENCE_ITEMS = (?:DILIGENCE_ITEMS \|\| )?\[(.*?)\];", APP, re.S).group(1)
    assert re.findall(r'\["(\w+)", "(\w+)", "([^"]+)"\]', items) == [tuple(x) for x in DD.ITEMS]
