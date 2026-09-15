# Image and document rights policy

**Status:** Phase 33 (Commercial Source-of-Truth, Scraping Compliance, and Lawful Acquisition Audit), 2026-09-15.

Phase 33 Sections 10 and 31 require image rights and document rights to be tracked separately from ordinary structured-property-data rights, and never assumed reusable merely because they're attached to a public government record. This page is the current, honest inventory — it is short because this project does not currently harvest images or documents from any source at scale, and Phase 33 did not change that.

## Current state: no image/document harvesting exists

Grepping `app.js`, `public/app.js`, and every `harvesters/`/`scripts/` file for image- or document-fetching code (Phase 33 Section 4's repository audit) found no code path that downloads, stores, or re-serves a source's own images or PDF/document files as binary content. What does exist:

- **`data-provenance.md`/registry entries note `document_image_rights_status`** per source (mostly `"Not formally reviewed"` for the three grandfathered Florida entries, `"N/A"` for LGBS/RealAuction/the two new Phase 33 statewide entries since those sources don't publish images, and explicit `PROHIBITED` for the four BLOCKED TX vendors).
- **LAFT PDFs (`fl_laft_pdfs`) are parsed for their tabular text content only** (`pdfplumber` extracts rows into structured fields) — the PDF files themselves are never stored, re-hosted, or served to customers; only the extracted text fields (case number, parcel, bid, etc.) reach the database. This is a meaningfully different activity from "distributing the PDF," but Phase 33 does not treat that distinction as automatically dispositive — see [Classification](#classification) below.
- **`Street View` / `Appraiser` / `Zillow` / `Tax Collector` / `GIS Map` links in the frontend CSV export and detail view are all outbound links to third-party sites**, not embedded/re-hosted images or documents. Linking out is not covered by this policy — no image or document bytes cross this project's own infrastructure for those.
- **County GIS parcel boundary data** (via the FDOR Statewide Cadastral FeatureServer, `parcel-enrichment-and-gis-plan.md`) is geometry/attribute data, not imagery — satellite/aerial photography from that or any other source is not currently fetched.

## Classification

| Category | Status | Basis |
|---|---|---|
| Structured text extracted from `fl_laft_pdfs` (case #, parcel, bid, etc.) | `APPROVED` (inherits the grandfathered `fl_laft_pdfs` status) | Text extraction into the existing customer-facing property record, same treatment as every other `fl_laft_pdfs` field |
| The LAFT PDF files themselves (binary distribution/re-hosting) | `LEGAL_REVIEW_REQUIRED` | Never attempted; would be a materially different activity (redistributing the source document itself) than extracting its text, and has not been reviewed |
| PBFCM tax-sale PDFs (`tx_pbfcm`) | `BLOCKED` | `disclosure.html`'s prohibition explicitly covers "any material contained on this Site" — the PDFs are the entire product; see `harvesters/governance/registry.py`'s `_TX_PBFCM.document_image_rights_status` |
| Any property photo from any source (county appraiser sites, RealAuction listings, LienHub, etc.) | `LEGAL_REVIEW_REQUIRED` | Never fetched or reviewed; no source's photo-reuse rights have been examined at all |
| Outbound links to Street View / Appraiser / Zillow / county sites | Not applicable to this policy | Linking, not copying — no bytes from those services are stored or re-served |

No image or document source in this project is currently `APPROVED`, `APPROVED_WITH_RESTRICTIONS`, or `LINK_ONLY` for binary reuse. The one Mode-A-eligible activity (LAFT text extraction) is scoped narrowly to structured fields already flowing through the existing, grandfathered `fl_laft_pdfs` registry entry — it is not a general license to store or redistribute source documents or images.

## What Phase 33 did not do

Per Section 57's explicit prohibition, this phase did not implement image downloading at scale, document downloading at scale, or any new binary-content harvesting. This page is a classification of the status quo (nothing harvested) plus the policy that would govern a future image/document feature, not an announcement of a new capability.
