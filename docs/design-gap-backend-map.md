# Design → backend gap map

What each panel of the RODZ TAXDEEDS screens needs, and whether the backend can
answer it. Written against the live schema on 2026-09-17.

Legend: **✅ exists** · **🟡 partial** · **➕ added by 007/008** · **❌ no source yet**

## Dashboard

| Element | Status | Notes |
|---|---|---|
| Properties count | ✅ | `count(properties)` — **4,005 today**, not 125,430 |
| Upcoming Auctions | ✅ | 1,028 live with `sale_date >= today` |
| Watchlist count | ✅ | `favorites` |
| "+12% vs last 30 days" | ➕ | needs `daily_metrics`; nothing records history today |
| Opportunity map | 🟡 ➕ | 2,253 of 4,005 rows have coordinates; `geog` + GiST index added |
| Upcoming auctions by date/county | ✅ | |
| Recent activity feed | 🟡 | derivable from `updated_at` / `fdor_enriched_at`; no dedicated log |

## Auctions list

| Element | Status | Notes |
|---|---|---|
| Address, County, Opening Bid, Assessed, Auction Date | ✅ | |
| Type — Tax Deed / Tax Lien / Foreclosure | 🟡 | `source` is auction/certificate/laft and `ledger_type`/`tx_category` carry more; **no column means "Foreclosure"** — needs a mapping decision, not a column |
| **Distance (2.4 mi)** | ➕ | needs a user origin; `geog` makes `ST_Distance` indexable. The origin itself is a frontend/profile concern. |
| Opening-bid range slider | ✅ | `bid` / `min_bid` |
| Star / watchlist | ✅ | |
| Pagination | ✅ | `p_limit` / `p_offset` |

## Property detail

| Panel field | Status | Notes |
|---|---|---|
| Market / Assessed value | ✅ | 43% / 93% populated |
| **Taxable value** | ➕ | own column — FL assessed is pre-exemption, taxable is post; the homestead feature depends on the gap |
| **Annual taxes, Delinquent taxes** | ➕ ❌ | columns added; **no source wired** — Tax Collector data is not harvested |
| Land value | ✅ | 40% |
| **Improvement value** | ➕ | column added; derivable as market − land where both exist |
| Acreage | ➕ | column added; `lot_sqft` exists at 41% and converts |
| Sq ft, Year built | ✅ | 13% each |
| **Beds / Baths** | ➕ ❌ | columns added; FDOR cadastral does not carry them — needs county CAMA |
| Property type | ✅ | 43% |
| **Land use** | ➕ 🟡 | `dor_use_code` exists at 5% and maps to it |
| Opening bid, Bid/Value % | ✅ | derived |
| **History timeline** | ➕ | `property_events` table — `last_sale_*` holds one point and is overwritten each harvest, so history cannot live on the row |
| **Liens / Judgments / Foreclosure / Code violations** | ➕ ❌ | see the warning below |
| **Flood zone** | ➕ ❌ | column added; no FEMA source wired |
| Latitude / Longitude | ✅ | 56% |
| **Zoning / Municipality / Subdivision** | ➕ ❌ | columns added; no source wired |
| Research & Sources links | ✅ | six `url_*` columns exist |
| **Permits tab** | ❌ | nothing. Not in 007 — a permit is an event stream per property, and inventing columns before a source exists would be schema theatre. `property_events` already has a `PERMIT` type for when one does. |
| **Documents tab** | ❌ | nothing. Document rights are separately restricted from metadata rights (Phase 38). |
| Property photo | ❌ | no image source; image rights are their own policy question |
| Data quality / provenance | ➕ 🟡 | `harvester_source` is one value per row; `field_provenance` jsonb added because the bid, the values and the coordinates come from different places |

## Watchlist

| Element | Status | Notes |
|---|---|---|
| Active / Researching / Completed tabs | ➕ | `favorites.stage` |
| Pipeline Watchlist → … → Post-Auction | ➕ | seven-stage constraint |
| "Auction Soon" tab | ✅ | deliberately **not** a stage — it is a `sale_date` filter; as a stage it could disagree with the calendar |

---

## The Risk & Legal panel — read this before building it

The mockup renders:

```
Liens            None found
Judgments        None found
Foreclosure      No
Code Violations  None found
Flood Zone       X (No risk)
```

**We have never checked any of these, for any property.** There is no lien
source, no judgment source, no code-enforcement source and no FEMA source in
this pipeline. Rendering "None found" from an empty column tells someone about
to bid real money that a property is clear when the truth is that nobody looked.

A wrong address wastes a trip. A wrong "no liens" loses the money.

So 007 models every risk as a **pair**, and the database refuses the shape that
would allow the lie:

```
liens_checked_at IS NULL   →  "Not checked"          ← never "None found"
liens_checked_at set, count 0 → "None found as of <date>"
liens_checked_at set, count n → "n found"
```

`properties_risk_counts_need_a_check` enforces that a count cannot exist
without its timestamp, and no count has a `DEFAULT 0` — a default would mark
every existing row checked-and-clear the instant the migration ran.

**Until a real source is wired, every one of these fields must render "Not
checked".** That is an honest empty state and it is buildable today.

---

## Status of these migrations

`007_design_gap_property_intelligence.sql` and
`008_get_properties_design_fields.sql` are **written and tested but NOT
applied**. They need explicit authorization before running against production.

Both are transactional, re-runnable (`if not exists` throughout) and
non-destructive (no drop table/column, no truncate, no delete). 008 preserves
the projection's argument list, filters, ordering, and its non-SECURITY-DEFINER
status, so RLS continues to apply.
