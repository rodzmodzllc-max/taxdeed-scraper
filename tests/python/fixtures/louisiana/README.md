# Louisiana fixtures

`ebr_adjudicated_LIVE_SHAPE.csv` / `ebr_metadata_LIVE_SHAPE.json` (2026-09-30):
the CSV header is the LIVE East Baton Rouge "Adjudicated Property" dataset
(a4h4-zi7e) header verbatim, and the metadata keys and values (licenseId
PUBLIC_DOMAIN, rowsUpdatedAt 1709060068 = 2024-02-27, provenance,
attribution, Update Frequency) are the live metadata's own - both read by
the manual evidence job (`scripts/capture_state_sources.py`, GitHub Actions
runs 36752875012 / 36753767965). Every ROW VALUE is SYNTHETIC ("SAMPLE",
"FIXTURE"), written in the live value shapes (PROPERTY NUMBER 999-9999-9 and
999-99999-9, one row per property number per tax year). No real property,
owner or address is in this repository.

`ebr_adjudicated_SYNTHETIC.csv` / `ebr_adjudicated_badheader_SYNTHETIC.csv`:
the original search-index-era fixtures (header as indexed - it matched the
live header exactly), kept for the parser's structural tests.
