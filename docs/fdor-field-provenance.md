# FDOR cadastral fields: what they mean, and what this project may store

Source of every definition on this page: the Florida Department of Revenue
**2025 NAL/SDF/NAP User's Guide**. Wording in quotation marks is the guide's,
verbatim.

## Why this document exists

The Florida Statewide Cadastral ArcGIS layer exposes **127 fields**. Its own
service metadata is useless for understanding them: every field reports an
`alias` identical to its `name`, so the service will tell you there is a
column called `DEL_VAL` and nothing at all about what is in it.

That is not a harmless gap. `DEL_VAL` reads like "delinquent value". It is
not:

> **DEL_VAL** — "Reduction in just value resulting from the deletion of
> improvements on the property since the previous assessment."

It is a demolition adjustment. A tax-deed product that mapped it to a
`delinquent_tax` column on the strength of its name would show a confident
back-taxes figure — on the one screen where a person decides how much of their
own money to bid — that is actually the value of a torn-down barn.

So: **no field on this layer is mapped into the database until its definition
has been read in the guide.** Field names are a hypothesis, never a source.

## Mapped (Phase 52)

| Column | FDOR field | Guide definition |
|---|---|---|
| `taxable_value` | `TV_NSD` | "Taxable value for county purposes, which is based on non-school district assessed value." |
| `land_use` | `PA_UC` | "County-defined use codes. Please contact the county property appraiser for information." |
| `effective_year_built` | `EFF_YR_BLT` | "Primary structure's effective year built, adjusted to compensate for any substantial changes." |
| `num_res_units` | `NO_RES_UNT` | "Number of residential units on the parcel." |
| `last_sale_month` | `SALE_MO1` | "Month of the transaction listed." |
| `last_sale_qual_code` | `QUAL_CD1` | "Code denoting the property appraiser's sales qualification decisions." |
| `last_sale_vi_code` | `VI_CD1` | "Code indicating V for vacant property or I for improved property." |
| `last_sale_or_book` | `OR_BOOK1` | "Official record book number for the sale transaction listed as the county's clerk of the court has recorded." |
| `last_sale_or_page` | `OR_PAGE1` | "Official record book's page number for the sale transaction listed." |
| `last_sale_clerk_no` | `CLERK_NO1` | "Clerk's Instrument Number for the sale transaction listed." |
| `prior_sale_price` | `SALE_PRC2` | "Sale price indicated by documentary stamps on the deed." |
| `prior_sale_year` | `SALE_YR2` | "Year of the transaction listed." |
| `prior_sale_month` | `SALE_MO2` | "Month of the transaction listed." |
| `prior_sale_qual_code` | `QUAL_CD2` | as `QUAL_CD1`. |
| `fdor_alt_key` | `ALT_KEY` | "Optional alternate key identifier some counties use in addition to unique parcel identification." |

### Derived, and labelled as derived

Two columns are arithmetic on verified fields rather than fields in their own
right. Both are documented as such in `scripts/migrations/009_...sql` and in
the writer, so nothing downstream can present them as something the county
reported.

* `improvement_value` = `JV` − `LND_VAL`. The NAL layout has **no**
  improvement-value field. This is the just value not attributable to the
  land, which therefore **includes special-feature value**, not only
  structures. Written only when both inputs are present and the result is
  positive.
* `acreage` = `LND_SQFOOT` / 43560. A pure unit conversion: `LND_SQFOOT` is
  "Equivalent square footage of the site **regardless of the information in
  fields 42 and 43**", i.e. already normalised to square feet whatever unit
  basis the county assessed the land on. No `LND_UNTS_CD` branching is needed
  or appropriate.

### The one that travels with a warning

`last_sale_qual_code` is the reason the sale columns were expanded at all. A
tax roll's most recent "sale" is very often a $100 intra-family quitclaim, a
deed correction, or a forced sale — and the property appraiser marks exactly
those as disqualified so they are **not** read as market evidence. `properties`
has carried `last_sale_price` since before this expansion with no way to tell
which kind of transaction it was.

**The UI must not present `last_sale_price` as a market price without
`last_sale_qual_code` alongside it.**

## Confirmed NOT available from this layer

Checked against the guide's full field layout. These are absent from the NAL
file entirely, so no amount of expanding the request will produce them:

| Wanted for | Available here? |
|---|---|
| Tax amount billed / taxes due | **No** |
| Delinquent taxes | **No** — and `DEL_VAL` is not it (see above) |
| Bedrooms | **No** — `NO_RES_UNT` is units, not bedrooms |
| Bathrooms | **No** |
| Zoning | **No** |
| Subdivision name | **No** — `NBRHD_CD` is a county-defined neighbourhood *code* |
| Municipality | **No** — `PHY_CITY` is the mailing city of the physical address, not the taxing municipality |

The design-gap columns for these (`annual_tax`, `delinquent_tax`, `beds`,
`baths`, `zoning`, `subdivision`, `municipality` in migration 007) therefore
stay NULL until a real source is acquired and authorized for each: county tax
collector for the tax amounts, county CAMA/property-appraiser detail for
beds/baths, municipal or county GIS for zoning, the clerk's plat records for
subdivision.

## Open hypothesis: `ALT_KEY`

`ALT_KEY` is stored raw, as `fdor_alt_key`, under the name of the field it
came from — deliberately. For several counties its values *look* like tax
collector account numbers, and it would be easy to name the column
`tax_collector_account` and start building tax-collector URLs out of it.

The guide does not support that. It says only that this is an "[o]ptional
alternate key identifier some counties use in addition to unique parcel
identification" — a county-chosen secondary key, with no statement about which
county system it belongs to. Since it is optional and county-chosen, the
answer can legitimately differ per county.

### Evidence so far — Alachua County (CO_NO 11), sampled live 2026-09-17

15 parcels sampled from the layer. `ALT_KEY` is populated on all 15 — no
nulls, no blanks — and every value is a 5-digit integer:

| PARCEL_ID | ALT_KEY |
|---|---|
| 03956-010-001 | 15703 |
| 03956-010-026 | 15728 |
| 03956-010-030 | 15732 |
| 05900-109-003 | 28724 |
| 05900-109-014 | 28735 |
| 05900-109-016 | 28737 |
| 07702-000-000 | 71618 |
| 07724-000-000 | 71690 |
| 17125-000-000 | 96197 |
| 17125-001-000 | 96198 |

**The values are sequential in parcel order.** Within `03956-010-xxx`, parcel
suffixes 001 → 026 (a gap of 25) map to alt keys 15703 → 15728 (a gap of 25);
`05900-109-003` → `-014` is a gap of 11 and 28724 → 28735 is a gap of 11;
`17125-000-000` → `17125-001-000` is +1 and 96197 → 96198 is +1. Across the
whole sample the two identifiers sort in the same order.

That is the signature of an internal record index in the property appraiser's
CAMA system — a row number assigned when parcels were loaded in parcel-number
order — and it is **not** what a tax collector's billing account number
usually looks like, since those are issued per tax account and per roll year
rather than tracking parcel-number sequence.

**This is evidence against the hypothesis, not proof either way.** The
decisive check is a direct comparison against the county's own tax bill for a
known parcel, and that check was not completed: Alachua County's tax system
(`alachua.county-taxes.com`) disallows automated retrieval in its robots.txt,
and this project does not bypass robots restrictions. The permitted routes to
finish it are to look one parcel up by hand in a browser, or to ask the county
directly.

**Status: unvalidated, and currently leaning negative.** Do not build a
tax-collector lookup from this field for a county until that county has been
checked individually. Validating it county by county is cheap and additive;
mislabelling the column is neither.

## Held back pending a decision: owner mailing address

`OWN_ADDR1` / `OWN_ADDR2` / `OWN_CITY` / `OWN_STATE` / `OWN_ZIPCD` are present
on the layer and are **not** requested by the enrichment writer.

They are genuinely useful — an owner whose mailing address is in another state
is the single strongest absentee-owner signal this dataset contains. They are
also personal information about identifiable private individuals, and the
existing `owner_name` column is already the most sensitive thing this project
stores. Collecting a home mailing address for every parcel in Florida is a
different scale of collection than storing a name that appears on a public
auction listing, and it should be an explicit decision rather than something
that arrives as a side effect of a field-list expansion.

Not blocked, not adopted — deliberately deferred, with the reasoning recorded
here so the decision is made on purpose.
