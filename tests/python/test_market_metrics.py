"""Market measurement and the test-market shortlist (2026-10-06).

Explicit rules, no score; raw size never promotes a market past a failed
rule; large held inventories are preserved (listed, never dropped); the
generated report and the P5 county list are current; the snapshot is counts
only.
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from harvesters.enrichment import priority as PR  # noqa: E402
from harvesters.sources import market_metrics as MM  # noqa: E402
from scripts import build_market_report as BR  # noqa: E402

KEYS = ("counties", "active", "visible", "coordinates", "authoritative_coordinates", "parcel", "legal_description",
        "assessed_value", "taxable_value", "acreage", "land_use", "owner_name", "fdor_enriched", "acquisition_evidence",
        "purchase_url", "auction_url", "stored_imagery")


def unit(state, ledger, active, visible=None, **kw):
    u = {k: 0 for k in KEYS}
    u.update(state=state, ledger=ledger, counties=1, active=active, visible=active if visible is None else visible,
             parcel=active, coordinates=active, authoritative_coordinates=active, auction_url=active, acquisition_evidence=active)
    u.update(kw)
    return u


def ms(units, caveats=()):
    return MM.markets({"units": units}, list(caveats), {})


def test_focus_requires_every_rule():
    (m,) = ms([unit("XX", "AUCTION", 100)])
    assert (m.tier, m.failed) == ("FOCUS", [])
    (m,) = ms([unit("XX", "AUCTION", 100, parcel=94)])
    assert (m.tier, m.failed) == ("BROWSE", ["identity"])
    (m,) = ms([unit("XX", "AUCTION", 100, coordinates=74)])
    assert m.failed == ["coordinates"]
    (m,) = ms([unit("XX", "AUCTION", 100, auction_url=79)])
    assert m.failed == ["path"]
    (m,) = ms([unit("XX", "AUCTION", 100)], [{"state": "XX", "ledger": "AUCTION", "kind": "freshness", "note": "n"}])
    assert m.failed == ["current"]
    (m,) = ms([unit("XX", "AUCTION", 100)], [{"state": "XX", "ledger": "AUCTION", "kind": "gap", "note": "n"}])
    assert m.tier == "FOCUS"   # a documented gap is reported, never blocking


def test_available_path_is_verified_acquisition_evidence_only():
    (m,) = ms([unit("XX", "AVAILABLE", 100, acquisition_evidence=10, auction_url=100)])
    assert m.path_metric() == "acquisition_evidence" and "path" in m.failed


def test_lien_path_is_the_sale_page_or_acquisition_evidence():
    (m,) = ms([unit("XX", "LIEN", 100, acquisition_evidence=0, auction_url=100)])
    assert m.path_metric() == "auction_url" and m.tier == "FOCUS"


def test_held_and_not_current():
    (m,) = ms([unit("XX", "AVAILABLE", 30000, visible=0)])
    assert m.tier == "HELD"
    (m,) = ms([unit("XX", "AUCTION", 100)], [{"state": "XX", "ledger": "AUCTION", "kind": "not_current", "note": "n"}])
    assert m.tier == "NOT_CURRENT"


def test_raw_size_never_promotes_past_a_failed_rule():
    big = unit("BB", "AVAILABLE", 30000, coordinates=0)
    small = unit("SS", "AUCTION", 50)
    sl = MM.shortlist(ms([big, small]))
    assert [m.name for m in sl["strongest"]] == ["SS Auction", "BB Available"]
    held = unit("HH", "AVAILABLE", 90000, visible=0)
    sl = MM.shortlist(ms([held, small]))
    assert [m.name for m in sl["strongest"]] == ["SS Auction"]
    assert [m.name for m in sl["not_prioritized"]] == ["HH Available"]   # preserved, never dropped


def test_shortlist_is_deterministic():
    units = [unit("A%d" % i, "AUCTION", 10 * i, coordinates=(10 * i if i % 2 else 0)) for i in range(1, 9)]
    a = [m.name for m in sum(MM.shortlist(ms(units)).values(), [])]
    b = [m.name for m in sum(MM.shortlist(ms(list(reversed(units)))).values(), [])]
    assert a == b and len(a) == len(set(a)) == 8


def test_real_snapshot_classification():
    real = {m.name: m for m in MM.markets()}
    assert real["FL Auction"].tier == "FOCUS"
    assert real["SC Auction"].tier == "FOCUS"
    assert real["LA Available"].failed == ["current"]          # dated list
    assert real["WY Auction"].tier == "NOT_CURRENT"            # finished sale
    assert real["MI Available"].tier == "HELD" and real["MO Available"].tier == "HELD"
    assert real["TX Available"].tier == "BROWSE" and "current" in real["TX Available"].failed   # LGBS review / manual-only
    sl = MM.shortlist(list(real.values()))
    every = sum(sl.values(), [])
    assert {m.name for m in every} == set(real)                # every market appears exactly once
    assert len(every) == len(real)


def test_snapshot_is_counts_only_and_caveats_name_real_markets():
    snap = json.loads((REPO / "data" / "market_audit_snapshot.json").read_text(encoding="utf-8"))
    allowed = set(KEYS) | {"state", "ledger", "county_names", "sources"}
    names = {(u["state"], u["ledger"]) for u in snap["units"]}
    for u in snap["units"]:
        assert set(u) <= allowed
        for k in KEYS:
            assert isinstance(u[k], int) and u[k] >= 0
        assert u["visible"] <= u["active"]
        for k in KEYS[3:]:
            assert u[k] <= u["active"], (u["state"], u["ledger"], k)
    for c in MM.load_caveats():
        assert (c["state"], c["ledger"]) in names
        assert c["kind"] in {"freshness", "dated_list", "source_review", "not_current", "gap"}
        assert c["note"] and c["evidence"]


def test_generated_report_and_counties_are_current():
    assert BR.main(["--check"]) == 0


def test_market_test_counties_feed_enrichment_rule_p5():
    with (REPO / "data" / "market_test_counties.csv").open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert rows and {"state", "county", "ledger", "reason"} <= set(rows[0])
    strongest = {m.name for m in MM.shortlist(MM.markets())["strongest"]}
    for r in rows:
        assert f"{r['state']} {r['ledger'].title()}" in strongest
    ctx = PR.Context.from_repo()
    r = rows[0]
    hidden = {"id": "x", "state": r["state"], "county": r["county"], "ledger_type": "buy", "status": "active",
              "publication_status": "UNREVIEWED", "parcel": "123"}
    if (r["state"], r["county"]) not in ctx.verified:
        assert PR.rule_of(hidden, ctx) == "P5"


def test_report_never_scores_or_claims_demand():
    text = (REPO / "docs" / "market-test-report.md").read_text(encoding="utf-8").lower()
    assert "| score" not in text and "score |" not in text      # no score column
    for word in ("rating", "profit", "guaranteed", "demand is"):
        assert word not in text
