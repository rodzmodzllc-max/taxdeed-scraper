#!/usr/bin/env python3
"""Build a state's page (public/<code>.html) from public/tx.html - the
non-Florida page template - plus the state's own copy (six-state expansion,
2026-09-30). A state page differs from tx.html in exactly five places: the
<title>, <body data-state>, the sign-in tagline, the footer's coverage
notice and the terms-modal comment. Everything else (markup, ids, scripts)
is shared, so a fix to tx.html reaches every state page by re-running this.

    python3 scripts/build_state_page.py            # every state in PAGES
    python3 scripts/build_state_page.py --check    # exit 1 if a page is stale

The copy names only what the state's approved source publishes
(docs/six-state-expansion.md). No statutory copy is stated for any state:
none has been reviewed with counsel.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TEMPLATE = REPO / "public" / "tx.html"

TX_TITLE = "<title>Tax Acquisitions — Texas</title>"
TX_BODY = '<body data-state="TX">'
TX_TAGLINE = '<p class="auth-tagline">Texas Tax Sale Intelligence &amp; Auction Tracking</p>'
TX_NOTICE = ("<b>Fees, closing costs and lien notes are not tracked for Texas.</b> No Texas fee or closing-cost formula "
             "exists in this app, so none is shown. This app does not run a title search. Confirm title and costs with a "
             "title company or attorney before bidding.")
TX_TERMS_COMMENT = """<!-- Texas terms. The Florida fee/statute copy that used to be carried over here
(doc stamps, Fla. Stat. 197.x, the homestead half-assessed minimum) was removed:
it is not Texas law and no Texas equivalent has been researched. Do not add
Texas statutory copy here without counsel review. -->"""

PAGES = {
    "MI": dict(name="Michigan", tagline="Michigan County Tax Sale Tracking",
               notice="<b>Michigan coverage is two county treasurers' published tax-sale lists (Eaton, Lenawee).</b> Minimum bids "
                      "and Eaton's own 'Has Been Sold' flag are shown as each county publishes them. No Michigan fee, closing-cost "
                      "or redemption rule is tracked, and none is shown. Confirm terms with the county treasurer and a title "
                      "company or attorney before bidding."),
    "WY": dict(name="Wyoming", tagline="Wyoming County Tax Sale Tracking",
               notice="<b>Wyoming coverage is Albany County's published tax sale list.</b> Wyoming's sale sells a tax lien "
                      "certificate, not the land; the amount shown is the list's own 'Total' column as published. No fee, "
                      "interest or redemption rule is tracked, and none is shown. Confirm terms with the County Treasurer and "
                      "a title company or attorney before bidding."),
    "SC": dict(name="South Carolina", tagline="South Carolina County Tax Sale Tracking",
               notice="<b>South Carolina coverage is York County's published tax sale list.</b> The list publishes no opening "
                      "bid, and none is shown. No fee or redemption rule is tracked. Confirm terms with the county and a title "
                      "company or attorney before bidding."),
    "CO": dict(name="Colorado", tagline="Colorado County-Held Tax Lien Certificates",
               notice="<b>Colorado coverage is Morgan County's county-held tax lien sale certificates.</b> The purchase amount "
                      "is the Treasurer's own figure, good to the date in the list's header. Parcel details come from the "
                      "State of Colorado's Colorado Public Parcels layer, matched by assessor account number only; the State "
                      "states resale of that data is forbidden. No interest or redemption rule is tracked. Confirm with the "
                      "County Treasurer and a title company or attorney before buying."),
    "WI": dict(name="Wisconsin", tagline="Wisconsin County Tax Deed Sale Tracking",
               notice="<b>Wisconsin coverage is Green County's tax deed sale page.</b> Minimum bids and the sale prices of "
                      "previous sales are shown as the county publishes them; the county states when it has no current "
                      "sales. No fee or closing-cost rule is tracked. Confirm terms with the County Clerk and a title company "
                      "or attorney before bidding."),
}


def render(code: str, template: str) -> str:
    cfg = PAGES[code]
    out = template
    for old, new in (
        (TX_TITLE, f"<title>Tax Acquisitions — {cfg['name']}</title>"),
        (TX_BODY, f'<body data-state="{code}">'),
        (TX_TAGLINE, f'<p class="auth-tagline">{cfg["tagline"]}</p>'),
        (TX_NOTICE, cfg["notice"]),
        (TX_TERMS_COMMENT, f"<!-- {cfg['name']} terms (2026-09-30, six-state expansion). No {cfg['name']} statutory copy\n"
                           "is stated here: none has been reviewed with counsel. Do not add it without counsel review. -->"),
    ):
        if out.count(old) != 1:
            raise SystemExit(f"{code}: template anchor not found exactly once: {old[:60]!r}")
        out = out.replace(old, new)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args(argv)
    template = TEMPLATE.read_text(encoding="utf-8")
    stale = []
    for code in PAGES:
        page = REPO / "public" / f"{code.lower()}.html"
        html = render(code, template)
        if a.check:
            if not page.exists() or page.read_text(encoding="utf-8") != html:
                stale.append(page.name)
        else:
            page.write_text(html, encoding="utf-8")
    if stale:
        print("stale state pages: " + ", ".join(stale))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
