# Sources batch 2026-10-25: Philadelphia (PA) and Alabama ADOR transcripts

This batch adds two AVAILABLE sources. Both are **gated and UNREVIEWED**.
Nothing is enabled in production, no row is synced, and nothing is shown to
customers. Under the owner's 2026-10-25 direction, public records are
collected to fill gaps, and nothing is sold until legal review.

## 1. Philadelphia surplus land (PA): `pa_philadelphia_lama_available`

**Source.** The City of Philadelphia's `LAMAAssets` ArcGIS layer:
`https://services.arcgis.com/fLeGjb7u4uXqeF9q/arcgis/rest/services/LAMAAssets/FeatureServer/0`.
The layer describes itself as "surplus property in Philadelphia", taken from
the Land Management (LAMA) database.

**Why these rows count as AVAILABLE.** The Philadelphia Land Bank's own map,
"Available Properties in Philadelphia", draws this layer. The path is:

- `phillylandbank.org/view-properties-map/`
- ArcGIS instant app `cb23daec00b543f8a5ea00c11f69f50d`
- web map `58c5fc01ae3e42b28dff14780fde43f7`

That map applies this definition expression:

```
(STATUS_1 = 'Owned - Available') OR (STATUS_1 = 'Owned - Available (Garden Agreement)') OR
(STATUS_1 = 'Owned - Available (no construction permitted)') OR (STATUS_1 = 'Owned - Available (not for SY)')
```

The adapter config copies it verbatim (`expansion.PA_PHILADELPHIA_LAMA.where`).
Nothing is inferred.

**Live read on 2026-10-25.** These are counts only, read from the sandbox.
The layer holds 7,853 features.

`status_1` counts:

| status_1 | count |
|---|---|
| Owned - On Hold for AHD | 1,949 |
| Owned - Not Available | 1,769 |
| **Owned - Available** | **1,736** |
| Owned - Processing Applicant, Not Available | 755 |
| Owned - Managed and Not Available | 543 |
| Owned - On Hold | 473 |
| Owned - Sale Pending | 303 |
| Unknown - Research Pending | 89 |
| Owned - RFP Released | 79 |
| Owned - On Hold for HOME SD | 40 |
| Owned - Held for City Council Member | 32 |
| Owned - To Be Featured Soon | 24 |
| Owned - Not Available (GSI Project) | 24 |
| **Owned - Available (no construction permitted)** | **20** |
| **Owned - Available (not for SY)** | **13** |
| Owned - Competitive Bid Posted | 4 |
| **Owned - Available (Garden Agreement)** | **0** |

The four statuses in bold are read: **1,769 rows**. That total happens to
equal the "Owned - Not Available" count; the research agent's earlier
"~1,769 owned-and-available" referred to the bold set.

By owning agency (counts only): PUB 3,447, PLB 2,641, PRA 1,670, PHDC 95.
The agency column is never mapped.

I ran the config through the real adapter (`arcgis.fetch_all`) live:

- **Read:** COMPLETE, 2 pages, 1,769 records, 0 validation problems.
- **Identifier:** `mapreg_1`, the registry map number. It is filled and unique on all 1,769 rows, in one shape.
- **Parcel:** `opabrt`, the OPA account. It is filled on 1,733 rows; stray whitespace on a few is stripped.
- **Address:** `location`, filled on all rows.
- **Coordinates:** derived as the centroid of each feature's own polygon. All 1,769 fall inside Philadelphia's bounding box.

**Never mapped:** `agency` (the owning public agency), `councildistrict`,
`sideyardeligible`, `zoning` and `pin`.

**Price.** The layer has no price. The Land Bank's Disposition Policies (PDF,
November 2025), linked from `phillylandbank.org/acquisition-and-disposition-policies-landing/`:

- set a Valuation Price by appraisal or in-house opinion of value;
- take an applicant's offer price with an application;
- allow nominal or discounted pricing for eligible uses.

The financial basis is therefore `OFFER_NEGOTIATED`
(`data/available_financial_terms.csv`). The purchase path is that
policies page, recorded as `purchase_instructions`. Because the registry row
is `PRODUCTION_VERIFIED` and carries an instructions page, the unit is
VERIFIED at source scope in `public/acquisition-evidence.json`. That brings
the count to 73 units, 27 of them VERIFIED.

**Gating.** The source is registered with `publication_status=UNREVIEWED`.
On its own, that would still mean "collected for admins": an AVAILABLE source
awaiting review is normally collected (`source_publication.collectable`). To
honour "nothing enabled in production", this batch adds
`expansion.COLLECTION_HOLD`. `harvest_expansion.runnable_sources()` reports a
held source as `GATED publication=UNREVIEWED (collection hold) - 0 requests`
and never requests it. The PA matrix leg keeps reading Fayette.

To enable the source, remove it from `COLLECTION_HOLD` in a reviewed commit.
Customer publication would still need an admin review and a `display`
permission, neither of which exists.

## 2. Alabama ADOR weekly county transcripts (AL): `al_ador_transcripts`

**Source.** The Alabama Department of Revenue page "Tax Delinquent Property
and Land Sales", read live 2026-10-25. Its own words:

> Transcripts of Delinquent Property. Below is a listing by county of tax delinquent properties currently in
> State inventory. ... The transcripts are updated weekly. This listing does not contain the physical address
> of the property.

> You may request a price quote for state-held tax delinquent property by submitting an electronic application.
> Once your price quote is processed it will be emailed to you. You are given 10 calendar days from the date on
> the price quote to remit your payment.

**The 68 files.** The page links one PDF per county:
`/wp-content/uploads/property-tax-transcripts/WWW_TRANS_<NN>.PDF`.

- Jefferson County is split into two files: Birmingham (01) and Bessemer (68).
- The file numbers are **not alphabetical**. For example, 01 is
  Jefferson-Birmingham, 02 Mobile, 03 Montgomery and 04 Autauga.
- `alabama_transcripts.TRANSCRIPT_FILES` is copied from the page's own links.

**Column meanings.** The agency's "How to Read the Transcript" PDF names the
columns:

- NAME: the name the property was assessed in when it sold;
- CO.: the county code;
- YR.: the year it sold to the State;
- C/S#: the certificate of sale number;
- CLASS and CODE;
- PARCEL ID;
- DESCRIPTION.

A second line carries the "Amt Bid at Tax Sale".

**One transcript read live (file 01, Jefferson-Birmingham).** It was read
value-free; nothing from it is committed.

- **Format:** an Oracle Reports text PDF of 474 pages, dated 10/19/2026 in its header. pdfplumber finds no table structure, so the adapter is a **line parser**. `tabular.pdf_table_rows` does not apply.
- **Parse:** 8,977 records and 474 page headers, with 0 county mismatches, 0 duplicate C/S#, 0 orphan lines and 0 validation problems. 7 records carry no amount line, which is counted and is not drift.
- **C/S#:** 8 digits on every record.
- **PARCEL ID shapes:** 22 digits (6,767), 18 (1,987), 20 (219), 17 (2), 16 (1).
- **Description:** blank on 52 records.

Two layout details were found on the live file and handled:

- A name printed against the county code with no space between them, on 68 records.
- An amount line that follows a description line, or a page header, instead of the record line.

**The other 67 files were not read** (one PDF only, as instructed). Their
parcel-ID shapes may differ.

**Fields.**

- `case_no` is the C/S# as published, with leading zeros kept.
- `parcel` is the PARCEL ID.
- `legal_desc` is the description lines joined.
- The county comes from the file number. A CO. value that disagrees with the file is rejected and counted.
- `list_url` and `document_url` are the county's own transcript.
- `purchase_url` is the land-sales page, recorded as `purchase_instructions`.
- `amount` is None, with kind `QUOTED_ON_APPLICATION`. The financial basis is `QUOTED_ON_REQUEST`.
- **Never read:** NAME (an assessed / owner name), CLASS, CODE, and the tax-sale amount. The tax-sale amount is the county sale's figure, not the State's price.

**Gating.** Alabama is a registered, **non-activated** state.

- `alabama_transcripts.can_run()` checks state activation first.
- `harvest()` raises before the first request, even for a config that claims full verification.
- A recorded `fetch` permission does not change this (tested).
- `parser_fixture_validated=False`, so `classify_outcome()` reports rows as INCOMPLETE and a zero as INCOMPLETE / UNCONFIRMED_EMPTY. Nothing is ever COMPLETE or EMPTY, which is the same rule as `alabama.py`.
- The registry row is non-production (`MANUAL_REVIEW_REQUIRED` / `TERMS_NOT_VERIFIED`) and names no harvester.
- The adapter is not wired into any workflow or runner.

**Fixture.** `tests/python/fixtures/alabama/transcript_04_SYNTHETIC.txt` is
the live layout with invented names, C/S#, parcels, descriptions and amounts.

## 3. Records changed

| File | Change |
|---|---|
| `harvesters/otc/adapters/expansion.py` | Separate appended block: `PA_PHILADELPHIA_LAMA`, `PUBLICATION.update`, `SOURCES["PA"] +=`, `BATCH_2026_10_25_SOURCE_IDS`, `COLLECTION_HOLD` |
| `harvesters/otc/adapters/alabama_transcripts.py` | New: line parser, file map, gate, `classify_outcome`, `harvest` |
| `scripts/harvest_expansion.py` | `runnable_sources()` honours `COLLECTION_HOLD` |
| `scripts/build_county_source_registry.py` | Batch flag for the PA row; `AL_TRANSCRIPTS` row |
| `data/county_source_registry.csv` | +2 rows (239) |
| `data/source_permissions.csv` | +6 rows: fetch / parse / store per source. `OWNER_PERMISSION_REQUIRED` on `INTERNAL_RISK_ACCEPTANCE`, 2026-10-25 to 2027-04-12, `excluded_from_paid_tier` |
| `data/available_financial_terms.csv` | PA `OFFER_NEGOTIATED`, AL `QUOTED_ON_REQUEST` |
| `harvesters/ledgers/__init__.py`, `governance/inventory_status.py`, `sources/acquisition_evidence_status.py` | Ledger, offered wordings, authority |
| Generated | source-inventory, available-coverage, county-intelligence, acquisition-evidence, available-terms, state-rules, commercial-scope (public + root mirror), state-coverage, gap-queue, interim-permissions, market report |

**Not changed, and why:**

- **`data/available_publication_reviews.csv`.** That table records reviews of
  *catalog candidates*, and every row must cite a GitHub Actions capture run
  id. These two sources were read from the sandbox, so no run id exists, and
  none is invented. Their UNREVIEWED state lives where every other registry
  source's does: `publication_status` in the registry.
- **app.js coordinate and program labels** (`COORD_SOURCE_COORDINATES`,
  `AVAILABLE_PROGRAMS`). This batch is backend only. Philadelphia's derived
  centroid would show "origin not recorded" until a frontend change, and no
  row exists yet anyway.

## 4. Next steps (owner)

1. **Philadelphia:** decide on collection, then remove the source from
   `COLLECTION_HOLD`. Decide separately on customer publication, which needs
   an admin review plus a `display` permission.
2. **Alabama:** Alabama must be activated (all ten `ACTIVATION_REQUIREMENTS`)
   before either ADOR source can run. Also needed:
   - an evidence-job capture of more transcript files, to confirm the
     parcel-ID shapes across counties;
   - a terms review.
