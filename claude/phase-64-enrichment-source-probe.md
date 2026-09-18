# Phase 64 — Enrichment source probe (read-only evidence)

Status: **probe written, awaiting execution.** No enrichment implemented, no
schema change, no production write. Results are appended by the workflow run.

## Why a probe rather than a build

Coverage for auction + LAFT/OTC is 57.7% (1,440 / 2,494). The remaining
Florida gap is not a parcel-format problem — it is an *identifier* problem.
For the stalled counties we store the county's own account/folio number,
while FDOR's statewide layer is keyed on `PARCEL_ID`.

The FDOR FeatureServer was characterised live on 2026-09-18 and answers
exactly one kind of question:

| Query | Result |
|---|---|
| `PARCEL_ID='<exact>'` (+ `CO_NO`) | works, and returns `ALT_KEY` |
| `CO_NO=<n>` scan, 3 rows, `PARCEL_ID` only | HTTP 400 after ~55s |
| `CO_NO=<n>` scan including `ALT_KEY` | hangs |
| `ALT_KEY='<exact>'` | HTTP 400, every county tried |
| `PHY_ADDR1='<exact>'` | HTTP 400 |

**Therefore the FDOR API cannot discover a `PARCEL_ID` from a county account
number** — every query path that would do so is one the service refuses.
`ALT_KEY` was confirmed to hold a county account for one county (Alachua
parcel `08197-101-000` → `ALT_KEY 105284`), but that could not be verified
for the stalled counties for the same reason.

TX is blocked differently: Galveston and Liberty's `esearch` portals both
carry `robots.txt` with `Disallow: /Search/` and `Disallow: /Property/` —
exactly the paths a per-account lookup needs — and Leon publishes no API or
bulk export. Galveston CAD does publish a Parcel DBF for download with no
stated restriction, which is the only lawful automatable route found.

## What the probe measures

**FL (Hillsborough 132, Brevard 49, Suwannee 20 unenriched in scope):** pulls
`PARCEL_ID` + `ALT_KEY` per county from the published dataset and measures
the `account → ALT_KEY → PARCEL_ID` join: exact matches, accounts resolving
to multiple parcels, unmatched, and the 1:1 percentage. An account resolving
to several parcels is recorded as an ambiguity, never collapsed into a match.

**TX (Galveston, 203 rows):** downloads the published Parcel DBF and reports
its real field list, so we learn whether it carries appraisal attributes
(value, year built, owner, account) or only geometry.

## Guarantees

Every outbound call in `scripts/probe_enrichment_sources.py` routes through a
single `_get()` helper wrapping `requests.get`. There is no POST/PATCH/PUT/
DELETE anywhere in the file, no schema access, and the only `properties`
reference is a `?select=parcel` read. The workflow is `workflow_dispatch`
only — no `schedule:` block — and declares `permissions: contents: read`.

## Results

_Pending execution. The run writes `out/probe_enrichment_sources.json` and
`out/probe-evidence.md`, both uploaded as the `enrichment-source-evidence`
artifact and mirrored into the run's step summary._

| Fix | Verdict |
|---|---|
| FL `ALT_KEY` → `PARCEL_ID` mapping | _pending_ |
| TX Galveston CAD DBF | _pending_ |
