# Source Rights Matrix

`data/source_rights_matrix.csv` — Phase 38 Section 32's operational map of what
may lawfully be done with each source, per county, per field category.

## Columns

`state, county, provider, source, field_category, technical_access,
automated_access, storage, caching, derivation, customer_display, export, api,
image_use, document_use, commercial_use, authorization_required, legal_status,
evidence_url, reviewed_at, notes`

## How to read it today

Every rights column defaults to **`UNREVIEWED`**, and that is the honest current
state for almost every row: Phase 38 identified *who* the official source is for
each county, not *what may be done with it*. A cell says `UNREVIEWED` because
nobody has read that source's terms yet — never because a right is assumed.

`legal_status` is `LEGAL_REVIEW_REQUIRED` on every county row. Under Section 31,
a source whose terms have not been found or read cannot be anything else.

The only rows with an observed `technical_access` are the two statewide
directories themselves, which were actually fetched this phase. Even there,
`automated_access` for Texas records only that `robots.txt` allows the path —
the site's terms of use were still not reviewed.

## Row count

696 rows: 2 statewide directories + 198 Florida county offices (67 Property
Appraiser + 67 Tax Collector + 64 Clerk/VAB) + 496 Texas county offices (246
Appraisal District + 250 Tax Assessor-Collector).

## What promotes a row

Nothing in this file promotes anything. Production access is still gated by
`harvesters/governance/gate.py` and `authorization.py`, which read
`SourceStatus` from the registry, not this CSV. A row here moving to
`APPROVED` requires the existing authorization path: terms read, rights
established, `can_promote_source_for_use()` satisfied.
