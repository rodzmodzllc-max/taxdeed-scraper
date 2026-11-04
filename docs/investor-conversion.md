# Investor conversion: Available (2026-10-05)

The investor's path: find a property, understand the money, understand the acquisition path, open the official form or source, save the property, return to it.

## 1. Acquisition evidence no longer erased by an inventory sync

**Bug.** `scripts/sync_state_inventory.py` upserted each adapter row with PostgREST `resolution=merge-duplicates`. That replaces every column it sends, including the `otc_provenance` jsonb. The adapter's dict holds layer, identifier and coordinates facts. The verified acquisition record (steps, office, contacts, form, evidence page) lives in the same column. The laft lifecycle or purchase-path engine writes it there. A re-sync therefore erased the record. On 2026-10-04, 3,500 East Baton Rouge rows kept `purchase_path_type = county_instructions` but lost the record. Only `field_provenance` was read back and merged; `otc_provenance` never was.

**Fix (sync only; identity model, lifecycle semantics and publication unchanged):**
- `stored_provenance()` now also reads `harvester_source`, `otc_provenance` and the six path columns for this state's rows (`rows_out` → `stored_rows`).
- `merge_acquisition(row, stored)` uses the stored dict as the base. The row's own non-blank keys overwrite it, so a blank never erases a stored fact. The acquisition keys (`acquisition`, `purchase_evidence_*`, `purchase_instructions`, `purchase_path_observed_on`) move as one unit and are never spliced.

| Situation | Result |
|---|---|
| Nothing stored | The row's evidence, if any, is added. |
| The row states a different non-null path type | Only the row's own evidence; never mixed across path types. |
| The row's evidence is equal or stronger (`acquisition_strength`: complete record, then published steps and contact fields, then evidence page) | The row's evidence replaces the stored unit. |
| Weaker evidence, or none | The stored unit is kept. |
| An active row states no path over a stored verified path | The stored path columns are restored too, so the record and its columns stay together. |
| A row that is no longer active | Sheds its path, exactly as before. |

- A stored row of another source (`harvester_source`) is never a merge base. Identity (state, source, county, case_no) isolates county and parcel.
- Outcomes are counted in the plan line only when they occur; counts only, never a value.
- Tests: `tests/python/test_acquisition_persistence.py`, which reproduces the 2026-10-04 read and covers merge, isolation, the path columns and that no URL is synthesized.

The 3,500 rows already stripped in production still read their county record through `acquisition-evidence.json` (PR #87). The next scheduled Louisiana sync will no longer strip any. No production row was written by this change.

## 2. "How to acquire" is the first section of every Available page

`acquireBlockHtml()` answers seven questions in order:

| Question | Answer comes from |
|---|---|
| What is this? | Why it is available, and the listing match. |
| What does the source say I need to pay? | `acquisitionCostRows()`: `amountInfo` / `termsFor` semantics. An opening bid is never a price, and costs and deposits are never added. |
| How do I acquire it? | The truthful CTA, method, steps, partial / "Not yet verified", and scope. |
| What form do I need? | County forms from the verified record and the row; offline forms are said to be offline. |
| Where do I submit it? | Online page, in-person address, mailing address, e-mail, payment. Only what the record publishes. |
| Who do I contact? | Office, phone, e-mail. |
| What is the official source? | Evidence page, official availability listing, last verified, "No online purchase link on file" when no online path exists, listing last read. |

Nothing is shown that the row or its verified county record does not carry. Every visible Available source has a source-backed row in `data/available_financial_terms.csv`, enforced by `tests/python/test_investor_conversion.py`.

## 3. Saved properties keep the way back

The existing watchlist (`bid_list`, `BIDLIST`) is unchanged; no second list was added. Under each saved Available card, `savedAcquisitionHtml()` shows:
- the verified method;
- the amount, as `amountInfo` names it;
- the first county form;
- the official process page and the official listing;
- a **How to acquire** button (`data-action="openacq"`) that reopens the property page at that section.

## 4. Activation funnel (existing `track()`, migration 024 still unapplied)

| Step | Event |
|---|---|
| state_selected | `state_selected` |
| county_selected | `county_selected` |
| property opened | `property_viewed` |
| acquisition section viewed | `acquisition_section_viewed` |
| acquisition link clicked | `application_opened` / `acquisition_instructions_opened` / `acquisition_source_opened` |
| property saved | `property_saved` (favorites) / `property_watched` (watchlist) |

- Links carry `data-acq-link` (form / instructions / source), and the event records only that class.
- The click handler also covers links on the watchlist.
- No search text, address, parcel, URL or e-mail is recorded.
- Nothing is recorded until 024 is applied.
