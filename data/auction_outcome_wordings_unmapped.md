# RealAuction closed-item wordings observed and deliberately NOT mapped

Observed in capture run 36731266591 (21 counties x 6 past sale days,
2026-09-16..2026-09-29), status field B of the sale-day page's own status
refresh. None states a final result, so none is in
`auction_outcome_wordings.csv`; an event carrying one stays
"Outcome not yet verified" with the wording quoted.

| Wording | Items | Why not mapped |
|---|---|---|
| Bidder Walked Away | 4 | The winning bidder defaulted; whether the property was re-offered, struck off or cancelled afterwards is not stated. |
| Auction to be rescheduled | 4 | A postponement, not a result. The new date (if listed) becomes its own event. |
| Rescheduled | 2 | Same as above. |

No "struck off" or "withdrawn" wording was observed on any RealAuction sale
day read; no row exists for either.
