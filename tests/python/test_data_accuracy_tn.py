"""TN data-accuracy fixes (2026-11-09).

TN-1: the ledger copy (data/state_ledgers.csv -> public/state-rules.json) said
"awaiting review" for AVAILABLE sources the owner approved for customer
publication on 2026-10-26 (Shelby, Oklahoma County, Fayette, Pittsburgh,
Ramsey, Hubbard, Saint Paul HRA). Copy may say a source awaits review only
while the registry still holds one that is not APPROVED.

TN-2: the Shelby Land Bank's per-property page carries the portal's own
'Apply For this Property' action (a portal account is needed; the transaction
is an offer). The record now carries that wording and the account flag, so the
customer label is "Apply online", never "Buy online". The acquisition mode
stays 'online' (the application is made on the web), and the evidence status
stays NEEDS_REVIEW (the offer packet has not been read).
"""
from __future__ import annotations

import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

from harvesters.governance import state_rules as SR  # noqa: E402
from harvesters.otc.adapters import epropertyplus as EPP  # noqa: E402
from harvesters.otc.adapters import expansion as EX  # noqa: E402
from harvesters.otc.adapters.property_page import PropertyPage  # noqa: E402
from harvesters.otc.model import PurchaseUrlKind  # noqa: E402
import harvest_expansion as H  # noqa: E402

AT = datetime(2026, 11, 9, tzinfo=timezone.utc)


# ------------------------------------------------------------------ TN-1

def _registry_status():
    out: dict[tuple[str, str], set[str]] = {}
    with (REPO / "data/county_source_registry.csv").open(encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            for ledger in (r.get("ledgers") or "").split("|"):
                if ledger:
                    out.setdefault((r["state"], ledger), set()).add(r.get("publication_status") or "")
    return out


def test_ledger_copy_says_awaiting_review_only_while_a_source_is_not_approved():
    status = _registry_status()
    stale = []
    for led in SR.load_ledgers():
        text = f"{led.note} {led.eligibility_basis}".lower()
        if "awaiting review" not in text and "awaiting customer" not in text:
            continue
        held = {s for s in status.get((led.state, led.ledger), set()) if not s.startswith("APPROVED")}
        if not held:
            stale.append(f"{led.state}/{led.ledger}")
    assert not stale, stale


def test_tn_and_the_other_approved_available_rows_name_the_approval():
    by = {(l.state, l.ledger): l for l in SR.load_ledgers()}
    for st in ("TN", "OK", "PA", "MN"):
        led = by[(st, "AVAILABLE")]
        assert "approved for customer publication 2026-10-26" in led.note, st
        assert "legal review pending" in led.note, st
        assert "awaiting review" not in led.eligibility_basis, st


def test_generated_state_rules_json_carries_the_new_copy():
    text = (REPO / "public/state-rules.json").read_text(encoding="utf-8")
    json.loads(text)
    assert "awaiting review" not in text
    assert "Shelby County Land Bank inventory (approved for customer publication 2026-10-26" in text
    assert (REPO / "state-rules.json").read_text(encoding="utf-8") == text


# ------------------------------------------------------------------ TN-2

def _epp_row(pid):
    return {"id": 1, "parcelNumber": pid, "currentStatus": "FOR SALE", "available": "Y",
            "propertyAddress1": "1 FIXTURE ST", "askingPrice": 0}


def test_shelby_record_carries_the_portals_own_action_and_the_account_flag():
    (r,), _ = EPP.parse_rows(EX.TN_SHELBY_LANDBANK, [_epp_row("FIXTURE0000001")], retrieved_at=AT)
    assert r.purchase_url_kind is PurchaseUrlKind.ONLINE_PURCHASE      # still a property-scoped web action
    assert r.provenance["purchase_action_label"] == "Apply For this Property"
    assert r.provenance["purchase_account_required"] is True
    assert "Apply For this Property" in r.provenance["purchase_url_basis"]


def test_shelby_acquisition_mode_stays_online_never_bid():
    row = EPP.parse_rows(EX.TN_SHELBY_LANDBANK, [_epp_row("FIXTURE0000001")], retrieved_at=AT)[0][0].to_properties_row()
    rows, n = H.attach_purchase_paths("TN", [row], harvest_date="2026-11-09")
    assert n == 1
    r = rows[0]
    assert (r["purchase_path_type"], r["purchase_path_scope"]) == ("direct_property_url", "property")
    assert r["otc_provenance"]["acquisition"]["mode"] == "online"
    assert r["otc_provenance"]["purchase_account_required"] is True


def test_a_page_without_an_action_label_or_account_adds_no_keys():
    page = PropertyPage(template="https://example.gov/p/{id}", kind=PurchaseUrlKind.OFFER_FORM, id_pattern=r"\d+",
                        verified_on="2026-11-09", verification="fixture", pattern_source="fixture")
    assert set(page.provenance()) == {"purchase_url_basis"}


def test_frontend_never_calls_an_application_buy_online():
    js = (REPO / "public/app.js").read_text(encoding="utf-8")
    assert "function purchaseKindLabel(p)" in js
    assert "purchase_account_required" in js and "purchase_action_label" in js
    # every purchase-path label goes through the one function
    assert "label: PURCHASE_URL_KIND_LABELS[p.purchase_url_kind]" not in js
    assert (REPO / "app.js").read_text(encoding="utf-8") == js
