# Investor discovery: the research screen (screening-v1)

**The complete source inventory stays underneath. Investor discovery sits on top of it.**

Screening classifies each record. It never deletes, closes, hides or rewrites
a row, and it writes nothing to the database:

- The List *promotes* some records by default.
- **All inventory**, and any search, show every record.
- Each record carries the reason the screen gave it.

| Piece | File |
|---|---|
| Rules (what the browser runs) | `public/screening.js` |
| Python mirror (reports, any future server use) | `harvesters/screening/rules.py` |
| Shared vectors (both implementations must agree) | `tests/python/fixtures/screening_cases.json` |
| Tests | `tests/python/test_investor_screening.py` (runs the vectors through node and Python) |
| Read-only production measurement (SQL port) | `scripts/sql/screening_v1_measure.sql` |
| UI | `app.js` "Research screen (screening-v1)" section, List head `#screenBar`, filters `#screenFilters`, card `.screen-line`, property page section `screen` |

Changing a rule takes four steps:

1. Change `screening.js` and `rules.py` together.
2. Add or adjust a vector in `screening_cases.json`.
3. Bump `SCREENING_VERSION`.
4. Re-run the measurement.

## 1. Three inventories

| Concept | What it is | Where |
|---|---|---|
| Source inventory | Every record legitimately captured from a source | `properties`; the ledger tab counts; **All inventory** |
| Investor discovery inventory | Records the screen promotes: `PRIORITY_REVIEW` + `REVIEW` | The List's default **Discovery view** |
| Flagged / excluded inventory | Valid source records that are not promoted: `LIMITED_OPPORTUNITY`, `HIGH_RISK_REVIEW`, `INSUFFICIENT_DATA` | One click away, counted, labelled with the reason, and always found by search |

Junk or duplicate source records are a separate matter. The LAFT junk-row
cleanup handles those under its own deletion gates. The screen never removes
anything.

## 2. Classifications and reason codes

| Classification | Meaning | Promoted by default |
|---|---|---|
| `PRIORITY_REVIEW` ("Research candidate") | Parcel number, size, county value and property class are all present, and no rule matched | yes |
| `REVIEW` ("Needs review") | Something is missing or a provisional threshold matched; nothing indicates a problem | yes |
| `LIMITED_OPPORTUNITY` | The appraiser's own use code, the source's own program terms, or a tiny vacant parcel indicate limited utility | no |
| `HIGH_RISK_REVIEW` | The legal description designates the parcel as a common area, drainage, easement, right-of-way, strip or utility site | no |
| `INSUFFICIENT_DATA` | No parcel number, or no value, size or class at all | no |
| `NOT_SCREENED` | Liens & Certificates: a certificate is a lien, not a parcel offered for sale | n/a |

Severity of each reason:

- `limited` makes a record `LIMITED_OPPORTUNITY`.
- `risk` makes it `HIGH_RISK_REVIEW`.
- `review` keeps it out of `PRIORITY_REVIEW` but leaves it promoted.
- `info` is shown on the record and changes nothing.

Precedence: limited > risk > insufficient data > review > priority.

| Code | Severity | Evidence |
|---|---|---|
| `POSSIBLE_RIGHT_OF_WAY` | limited (FL DOR 94) / risk (legal text) | FL DOR use code 94, "Right-of-way, streets, roads, irrigation channel, ditch"; or a legal description naming an abandoned or vacated right-of-way, or an undedicated street |
| `DRAINAGE_INDICATOR` | limited (DOR 96) / risk (text) | DOR 96, "Sewage disposal, solid waste, borrow pits, drainage reservoirs, waste land, marsh, swamps"; or "retention/detention pond", "drainage easement/servitude/tract" |
| `UTILITY_INDICATOR` | limited (DOR 91) / risk (text) | DOR 91, "Utility, pipelines, canals, communication"; or "lift/pump station", "well site", "utility strip/tract" |
| `COMMON_AREA_INDICATOR` | limited (DOR 09) / risk (text) | DOR 09, "Residential common elements/areas"; or "common area/ground/elements" |
| `SUBMERGED_LAND_INDICATOR` | limited | DOR 95, "Rivers and lakes, submerged lands" |
| `SUBSURFACE_RIGHTS_ONLY` | limited | DOR 93, "Subsurface rights" |
| `BUYER_ELIGIBILITY_RESTRICTED` | limited | Detroit Land Bank "Side Lot For Sale": sold only to the owner-occupant of the adjacent home (the DLBA Vacant Land Policy, see `docs/available-publication-evidence.md`) |
| `TINY_PARCEL` | limited when the source says vacant, else review | Acreage < 0.01 (section 3) |
| `POSSIBLE_EASEMENT` | risk | "drainage/utility/access/ingress-egress easement", "easement only/area/parcel/tract" |
| `STRIP_DESCRIPTION` | risk | "STRIP" opening the description, or standing in parentheses |
| `NOT_A_BUILDING_SITE` | risk | "not a building site", "non-buildable", "unbuildable" |
| `SMALL_ACREAGE` | review (provisional) | Acreage 0.01–0.05 |
| `LOW_JUST_VALUE` | review (provisional) | County value < $1,000 |
| `OPENING_BID_HIGH_RELATIVE_TO_VALUE` | review | Published amount ≥ county value |
| `OPENING_BID_LOW_RELATIVE_TO_VALUE` | info | Published amount < 10% of county value |
| `PARCEL_MISSING` / `ACREAGE_MISSING` / `VALUE_DATA_MISSING` / `PROPERTY_CLASS_UNKNOWN` | review | The field is absent from the record |
| `INSUFFICIENT_DATA` | review | Added when the class is `INSUFFICIENT_DATA` |

Reported on every record, and never used to flag it:

- `geometry: GEOMETRY_NOT_AVAILABLE`. No table holds parcel boundaries; only a point (latitude / longitude) is stored.
- `access: ACCESS_UNKNOWN`. No source carries road access.

Neither is a reason code. Both are statements of what the data cannot tell.

### Text rules: what is deliberately *not* matched

Before the text rules were written, every production legal description that
matched a broad keyword list was read, on 2026-10-04. These are **not**
evidence about the parcel, and the rules ignore them:

- A right-of-way or canal named as a **boundary**: "ALG R/W", "BD. S BY A DRAINAGE CANAL", "MEAS. 50 FT ON INTERSTATE R/W".
- An **exclusion** or **appurtenance**: "LESS R/W", "LESS DRAINAGE SERVITUDE", "SUBJ TO EASEMENTS", "TOGETHER WITH ... COMMON ELEMENTS", "INT IN COMMON AREA".
- A strip **added to or taken from** a lot: "LTS 23 & 24 & STRIP", "LESS & EXCEPT A 10 FT STRIP".

So a word only counts when no qualifier from that list sits in the same
clause within the preceding 40 characters. The qualifiers are LESS, EX, EXC,
EXCEPT, SUBJ, TOGETHER, WITH, PLUS, INT, ALSO, AND, RESERVING and &.
"STRIP" has one more condition: it must open the description or stand in
parentheses.

## 3. Thresholds and the evidence behind them

All figures were measured read-only in production on 2026-10-04, over active
(`status` active/available) auction and Available rows.

**Florida acreage distribution (rows with acreage):**

| Population | n | p1 | p5 | p10 | median | < 0.01 ac | < 0.05 ac |
|---|---|---|---|---|---|---|---|
| FL auction | 806 | 0.015 | 0.063 | 0.105 | 0.232 | 6 | 29 |
| FL Available | 140 | 0.012 | 0.037 | 0.043 | 0.110 | 1 | 19 |

**Value and bid distribution:**

- FL auction county value: p5 $2,630, p10 $5,373, median $62,496. 4 rows are under $1,000.
- FL Available county value: p5 $200, median $2,315. 37 of 142 are under $1,000.
- Bid ÷ county value, FL auction: median 0.12, p90 0.55, 38 rows ≥ 1.0.
- Bid ÷ county value, FL Available: median 1.15, 74 of 131 rows ≥ 1.0.

**Thresholds:**

| Rule | Threshold | Basis | Status |
|---|---|---|---|
| Tiny parcel | 0.01 ac (≈ 435 sq ft) | Below the 1st percentile of FL auction parcels. LIMITED only with the source's own vacancy evidence (DOR 00/10/40/70/80/99, a "lot"/"vacant" land use, or a Detroit lot program); never on an improved parcel (a condo unit's land share is tiny by design) | implemented |
| Small acreage | 0.05 ac | Below the 5th percentile of FL auction parcels; no zoning data exists to say what is buildable | **provisional, REVIEW only** |
| Low county value | $1,000 | 4 of 945 valued FL auction rows; common on FL Available (37 of 142), where it is a fact, not a defect | **provisional, REVIEW only** |
| Bid at or above value | ratio ≥ 1.0 | Arithmetic on two published figures | implemented, REVIEW only |
| Bid low vs value | ratio < 0.10 | Normal at FL auctions (the opening bid is the delinquent tax plus costs) | information only |

No acreage threshold stronger than these could be justified. Zoning minimums,
frontage and access are not in the data, so the size rules never go beyond
REVIEW without vacancy evidence. Moving a provisional rule to a stronger
severity would need:

- a zoning or minimum-lot source per county;
- parcel geometry, for frontage and width;
- an access source (road centrelines intersected with parcel boundaries).

## 4. Geometry

No parcel geometry is stored anywhere in production; `properties` has only a
point. Sliver detection (width-to-length ratio, area-to-perimeter ratio) is
therefore **not implemented**, and every record reports
`GEOMETRY_NOT_AVAILABLE`. Sliver evidence comes only from:

- the appraiser's use code;
- the source's own legal description;
- a tiny vacant acreage.

To add geometry would take an approved, licensed parcel-polygon source per
county, a column or table to hold it, and a derived indicator such as
`SLIVER_GEOMETRY_REVIEW` (a research flag, never a legal conclusion).

## 5. Screening metrics (never a return)

Computed only when both figures exist:

- bid ÷ county value
- county value ÷ bid
- value spread (county value − bid)
- bid per acre
- county value per acre

The county value is the market figure (FL just value, LA fair market value
and so on) when present, otherwise the assessed figure. The page names which
one was used.

The property page says it in words: these figures are arithmetic on published
numbers. They exclude:

- liens that survive the sale;
- title work;
- costs;
- the final price.

They are never labelled ROI, profit or return. A test (`s09`) pins that the
words do not appear in the rule code.

## 6. Investor controls

**List head (`#screenBar`)** shows:

- `N source properties · N match the research screen · N flagged for additional research · N insufficient data`;
- one button per view: Discovery view / Research candidates / Needs review / Limited opportunity / High-risk review / Insufficient data / All inventory.

Every number comes from the loaded rows after the investor's other filters.
None is hard-coded.

**Search** always looks through the whole inventory. A record the discovery
view does not promote is still found by its parcel or case number, and
labelled "Not promoted by default · Reason: …".

**Buy box (`#screenFilters`, Auctions and Available):**

- acreage min / max;
- county value min;
- bid ÷ county value max (%);
- source;
- require parcel number / acreage / county value / property class.

The maximum opening bid is the existing Bid Range. A range never matches a
record that lacks the field. Road access and parcel geometry are named as not
in the data, and are not offered as filters.

**Other surfaces:**

- **Card:** one line, the classification, plus the top two reasons when the record is not promoted.
- **Property page:** a "Research screen" section with the classification, every reason with its evidence, the screening metrics, geometry and access status, and the rule version. "Why am I seeing this?" names the screen too.
- **Exports:** Auction and Available CSVs carry `Research Screen`, `Research Screen Reasons` and `Research Screen Rules`.

The Map page is **not** screened. It shows every record for the chosen
ledger, as before.

## 7. Production classification (read-only measurement, 2026-10-04)

Active Auction and Available rows, from `scripts/sql/screening_v1_measure.sql`.
The SQL classification agreed with the Python classifier on all 219 sampled
rows, which included every flagged row outside Michigan.

| State | Ledger | Source inventory | Research candidates | Needs review | Limited | High-risk | Insufficient |
|---|---|---|---|---|---|---|---|
| FL | Auctions | 1,297 | 819 | 341 | 7 | 0 | 130 |
| FL | Available | 158 | 53 | 82 | 7 | 0 | 16 |
| TX | Auctions | 122 | 0 | 122 | 0 | 0 | 0 |
| TX | Available | 421 | 0 | 421 | 0 | 0 | 0 |
| MI | Available | 30,783 | 0 | 28,410 | 2,356 (side lots) | 0 | 17 |
| LA | Available | 10,334 | 0 | 10,261 | 0 | 73 | 0 |
| MO | Available | 9,758 | 0 | 9,377 | 0 | 3 | 378 |

Texas has no acreage or property class on any row, and no CAD source is
verified. Every Texas record is therefore REVIEW and stays promoted: the
screen does not penalise missing enrichment.
