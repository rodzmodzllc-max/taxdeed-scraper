# Investor beta (2026-10-05)

The tester preview stays live while investors use the product. Billing is still off: `billing.enabled: false`, migration 027 not applied, and no Stripe functions deployed. This phase only improves what investors run into.

## Paid-beta source audit (production, read-only, 2026-10-05)

| Source | Active rows | What the source gives | Finding |
|---|---|---|---|
| LA East Baton Rouge (`la_ebr_adjudicated`) | 10,334 | address, parcel, values, coordinates, flood and `list_as_of` on every row; legal description on 8,351 rows; land use on 5,999 rows; imagery on 2,124 rows. No acreage and no price; the amount is NOT_PUBLISHED, which is correct. | **Defect, fixed in the frontend (below).** 3,500 rows had lost their verified acquisition record. |
| SC York (`sc_york_tax_sale`) | 853 | coordinates, values, land use | No sale date and no opening bid is published. The cards read "Sale not scheduled" and "Opening bid not published", which is correct. `last_seen_at` is 2026-10-02. |
| MI Lenawee (`mi_lenawee_tax_sale`) | 35 | sale date 2026-10-06 | No values published. |
| MI Eaton (`mi_eaton_treasurer_sale`) | 3 active, 5 sold | | The sold rows come from the county's own flag. |
| WI Green (`wi_green_tax_deed_sales`) | 0 active, 9 closed | | Closed rows are never shown as available. |

## The East Baton Rouge acquisition defect

`scripts/sync_state_inventory.py` writes `otc_provenance` as a whole. The 2026-10-04 sync therefore replaced the lifecycle's acquisition record on 3,500 rows. Those rows kept `purchase_path_type = county_instructions` but lost:
- the Parish Attorney's steps;
- the office, phone and mailing address;
- the Request to Purchase form;
- the evidence page.

The page showed only a bare path type.

**Frontend fix.** No data is written and no harvester changes.
- `scripts/build_acquisition_evidence.py` writes `public/acquisition-evidence.json` (mirrored to the root). It uses the engine's own `resolve()` over the two verified evidence tables, and contains only county-level records, never per-parcel ones.
- `acquisitionProvenance(p)` in app.js fills in that record **only when** the row has a typed path, has no record of its own, and has the same state, source, county and path type. The row's own keys always win.
- `acquisitionOf`, `acquisitionGaps`, the How-to-acquire block, the decision rows and the export all read through it.

**Pipeline root cause, not fixed in this phase** (harvesting and sync changes need authorization): the sync should merge `otc_provenance` instead of replacing it, or re-run the purchase-path engine on every synced row.

## Usage events

The existing `track()` writes to `product_events` (migration 024, **not applied**). Until 024 is applied it records nothing; the probe sees the table is missing and sends nothing.

| Event | When |
|---|---|
| `state_selected` | Header state switch. Recorded on the next page, carrying only the `from` state. |
| `county_selected` | List or Map county select, with surface `list` / `map`. |
| `map_used` | The Map page is opened. |
| `property_viewed` | The full page or the desktop side panel opens a property. |
| `acquisition_section_viewed` | The How-to-acquire block, or the decision block's "How do I acquire it?" row, scrolls into view. Once per property per page load; carries the mode. |
| `application_opened` | A form or application document link in the acquisition or decision section. |
| `acquisition_instructions_opened` | The county process page, or a phone / e-mail link, in those sections. |
| `acquisition_source_opened` | The official availability listing in those sections. |
| `official_source_opened` | A link in the sources, provenance or inventory section. |
| `search_performed`, `property_saved`, `property_watched`, `export_performed`, `saved_search_*` | Unchanged. |

No event carries search text, an address, a parcel, a URL or an e-mail address. A test pins every event name to 024's CHECK list (`tests/python/test_investor_beta.py`).
