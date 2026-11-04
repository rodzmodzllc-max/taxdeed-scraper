# Financial honesty across states (2026-10-05)

Stacked on the first-run guide PR. It builds on what is already merged:

- `amountInfo()` and the source-aware terms table (#82);
- acquisition-evidence persistence (`merge_acquisition`, #88).

## Census (read-only, production, 2026-10-05)

The active Available and auction rows of FL, LA, TX, MI and SC carry these
amount shapes:

| State | Shapes |
|---|---|
| FL Available | opening bid (Hillsborough, Osceola, Pioneer counties, St. Lucie, HTML lists); estimated purchase price; original opening bid; minimum purchase amount (Orange); fixed price (RealTDM, shown as "Base purchase price" per its terms); not published; amount kind unspecified |
| LA | not published, 10,334 rows (the Parish Attorney's offer process) |
| TX LGBS | a vendor minimum bid with no amount kind |
| MI | Detroit Land Bank (program price per its terms); Oceana (proposal form); Lenawee / Eaton auctions with a minimum bid |
| SC | Horry / Georgetown opening bids; York auction with no bid |

## What changed

- **Application-required wording.** A row with no published figure whose
  source terms say how the price is reached now says so, instead of a bare
  "Not published":
  - `OFFER_NEGOTIATED` / `PROPOSAL` → "Application required";
  - `BID_SUBMISSION` → "Bid required";
  - `QUOTED_ON_REQUEST` → "Quoted on request".

  Each carries the process as its note. Louisiana EBR and Oceana MI now read
  "Price: Application required". The state stays `not_published`, so
  filters, exports and counts treat it exactly as before; no figure is
  shown.
- **One auction bid label on every surface.** The card headline said
  "Opening Bid" while the summary, preview and short label said "Minimum
  bid" for the same row. `auctionBidLabel(p)` now decides for all of them:
  - "Minimum bid" for Linebarger (`tx_lgbs`), whose listing field is
    `minimum_bid`;
  - "Opening bid" for every other auction source: Florida's statutory term,
    and the Michigan county lists' own column (stored in `min_bid`);
  - "Published amount (kind not stated)" when the source does not say.
- **"Just value" is Florida-only.** `valueLabel()` used it for Texas rows
  carrying `market` (none do in production today). Any non-Florida state
  now reads "Total value (source as published)" unless its own
  `STATE_META.marketLabel` names the figure.

## Tests

The Playwright "Financial honesty across states" block pins the label and
display of all 15 production shapes. It asserts that no opening, minimum or
original bid is ever called a purchase price. It also reads the auction
headline labels on the FL, TX, MI and SC pages: none says "price", and Texas
shows no Florida "Just Value".
