# Auction sale process (cross-state enrichment sprint, 2026-10-02)

What an auction customer needs before bidding is the county's **sale
process**: how and where the sale runs, whether bidders register (where, by
when), the deposit, the payment method and deadline, bidder and
identification requirements, the published sale time, and the office to
contact. This is **not a purchase path** (that answers how to buy property a
county already holds, `scripts/purchase_path_engine.py`) and it is always
**county-level guidance**: the county publishes one process for every
property on its sale list.

## Pipeline

```
data/auction_candidate_pages.csv         official county pages found by search (leads only)
        │  job=evidence, evidence_scope=auction_process
        ▼
scripts/capture_auction_process.py       value-free capture: each page + one hop to its own
                                         tax-sale documents; prints ONLY sale-process sentences
        │  a person reads the digest in the job log
        ▼
data/auction_process_evidence.csv        verified rows only (review_state=verified, https page)
        │  scripts/auction_process_engine.py  (load / validate / resolve / record)
        ▼
scripts/apply_auction_process.py         ACTIVE auction rows -> otc_provenance.auction_process
                                         (FL after every scheduled deeds sync; job=auction
                                         auction_mode=plan|apply for every production state)
        ▼
app.js auctionProcessOf() / auctionProcessHtml()   "How do I register and bid?"
```

## Rules

- **Every field is quoted, or faithfully shortened, from the evidence page.**
  A blank cell means the page does not publish it. Nothing is inferred from
  another county or from general knowledge.
  - **Sale time:** stored only when written on the page.
  - **Vendor phones:** never recorded as the county's. This covers
    Linebarger, Perdue and RealAuction support; they are named in `notes`.
- **Dates:** two separate fields.
  - `sale_date` with `sale_date_applies=yes` means the page states the date
    of the CURRENT sale list. The apply step may then fill a **blank**
    `properties.sale_date`, recording `field_provenance` with the page's URL.
  - `next_sale_date` is a FUTURE sale the county announces (Albany WY,
    2027-08-13). It is county information only and is never written onto a
    row from an earlier list.
- **Apply step limits:**
  - It replaces the stored record rather than mixing two pages, and keeps
    every other `otc_provenance` key.
  - It never touches a closed or gone row, a lifecycle field, an amount, an
    owner or an outcome.
- **No verified row:** the auction page says "Not yet verified - the
  county's registration, deposit and payment rules for this sale have not
  been captured from its own page".

## Coverage, 2026-10-02 (capture run 36960322323)

There are 38 verified county records:

| State | Records | Counties |
|---|---|---|
| FL | 27 | see list below |
| TX | 7 | Atascosa, Caldwell, Galveston (Sheriff's Sale Procedures PDF), Matagorda, Smith, Travis, Victoria |
| MI | 2 | Eaton (2026-10-22 sale, in person), Lenawee (2026-10-06 online sale) |
| SC | 1 | York (Tax Sale Fact Sheet) |
| WY | 1 | Albany (next sale 2027-08-13) |

The Florida counties are Alachua, Bay, Brevard, Citrus, Clay, DeSoto, Duval,
Hernando, Highlands, Hillsborough, Indian River, Jackson, Lake, Leon,
Manatee, Marion, Martin, Miami-Dade, Orange, Pasco, Polk, Putnam, St. Lucie,
Suwannee, Volusia, Walton and Washington.

Of the 38 records, 30 are complete: they give a method or steps AND a way to
reach the office or the sale site.

No verified process was found on the captured pages for:

| State | Counties |
|---|---|
| FL | Broward, Charlotte, Escambia, Flagler, Hendry, Lee, Nassau, Osceola, Palm Beach, Pinellas, Santa Rosa, Sarasota, Seminole |
| TX | Cameron, Concho, Dallas, Llano, Nueces |

Each of these reads "Not yet verified". The next step for each is a better
official page in `data/auction_candidate_pages.csv`.
