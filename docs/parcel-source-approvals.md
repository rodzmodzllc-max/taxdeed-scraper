# Parcel source approvals: Florida DOR and Utah UGRC (2026-10-20)

> **Update (2026-10-20, later the same day).** The product owner confirmed
> receipt of both written approvals. The boundary use they cover is now
> implemented (migration 034, not applied) and is described in
> `docs/parcel-boundaries.md`, together with the exact dataset mapping. That
> document supersedes the "Today's decision" and "Blockers" parts of this one.

Two parcel-data sources are approved independently, on written or published terms
supplied by the product owner. This change is repository-only.
- No migration was applied, no production row was written, no workflow was
  dispatched, no source was activated and nothing was deployed.
- An approval is evidence for a permission decision. It is not authorization to
  ingest, harvest or display anything in production.

| | Florida DOR | Utah UGRC |
|---|---|---|
| Source id | `fl_dor_pto_parcel_gis` (new, permission records only) | `ut_ugrc_lir_saltlake` (existing) |
| Dataset scope | Parcel-boundary geometry in the eligible county GIS parcel files DOR publishes through the Property Tax Oversight Data Portal, and the current-year statewide parcels linked from Florida GeoData | UGRC SGID statewide and county parcel datasets linked from the official UGRC parcels page. Only the Salt Lake County LIR layer is implemented |
| Status | APPROVED_WITH_CONDITIONS | APPROVED_WITH_CONDITIONS |
| Basis | Written permission (DOR states no restrictions on the data) | Published licence, CC BY 4.0, corroborated in writing |
| Evidence | A written response from Tom Canter, Systems Project Consultant, DOR Property Tax Oversight, relayed by the product owner on 2026-10-20 | The UGRC licence page (read 2026-09-30) and a written response from Erik Neemann, GIS Data Coordinator, UGRC, relayed by the product owner on 2026-10-20 |
| Evidence limitation | The original email is **not** in this repository or any record it can reach. Its received date, address and message id were not supplied and are **not recorded** | Same |
| Permitted | Retain simplified parcel-boundary geometry. Display boundaries over aerial imagery in a commercial research application. No separate county permissions are needed | Commercial use. Storage, caching and retention, and retrieval at any frequency (no strict limits stated). Display with attribution |
| Not covered | Other DOR datasets. Owner names and other tax-roll personal fields. County tax-sale or auction listings, outcomes and purchase paths. Third-party data | Other UGRC or SGID datasets. Other Utah agencies. Tax-sale, auction or assessor feeds. Third-party data |
| Conditions (enforced) | `attribution_text_recorded` on every operation; `technical_readme_reviewed` on fetch and parse only | `attribution_text_recorded` on fetch, enrich and store. `attribution_terms_recorded` (credit, CC BY 4.0 link, change notice, disclaimer, metadata) on display |
| Attribution | Courtesy credit "Florida Department of Revenue, Property Tax Oversight". Per the response, attribution is at TAXACQ's discretion | Credit UGRC, link https://creativecommons.org/licenses/by/4.0/, state the changes, show the disclaimer and metadata |
| Expected cadence (source) | Annual, published about mid-August to early September | Generally monthly |
| Actual last successful TAXACQ refresh | NEVER (no ingestion path for these files exists) | NEVER (Utah is not activated; no workflow runs it) |
| Operations not recorded | redistribute / export, fetch_via_proxy, link | redistribute / export, parse, fetch_via_proxy, link |
| Today's decision (updated 2026-10-20, see docs/parcel-boundaries.md) | store, enrich and display **allowed**. fetch and parse wait for the Readme (the identifier join comes from it) | fetch, enrich, store and display **allowed**. The disclaimer is linked: UGRC's data license and disclaimer policy page |

## Where the records live

- **`data/source_approvals.csv`** holds one row per approved source:
  - scope, exclusions, basis, evidence and its limitation;
  - permitted activities and conditions;
  - attribution fields;
  - expected cadence and actual last successful refresh, kept as separate
    columns;
  - the Readme URL and its review state;
  - reviewer and decision date.

  It is validated by `harvesters/governance/source_approvals.py`. An invalid
  register makes both conditions fail closed.
- **`data/source_permissions.csv`** holds:
  - five Florida records (fetch, parse, store, enrich, display), dataset
    `county_parcel_geometry`, with evidence type WRITTEN_PERMISSION and
    review date 2027-10-20;
  - the existing Utah fetch and enrich records (evidence reference extended,
    `last_verified_on` 2026-10-20; dates and conditions unchanged);
  - new Utah store and display records.
- **`harvesters/governance/authorization.py`** holds
  `fl_dor_pto_parcel_gis__provider__dor_pto`, the first granted provider
  authorization. The permission engine requires it for WRITTEN_PERMISSION
  evidence.
  - It records `written_permission=False` and a pending document, because the
    email is not on file.
  - Export and API redistribution are not authorized.
- **`permissions.CONDITION_CHECKERS`** gained two condition checkers that read
  the register: `technical_readme_reviewed` and `attribution_terms_recorded`.
  No other gate behaviour changed. Interim allowances, their expiry dates and
  every other source decision are unchanged.

## Florida: the existing FDOR paths, mapped

| Path in code | Endpoint | Dataset | Covered by this approval? |
|---|---|---|---|
| `scripts/enrich_property_details.py` `lookup_fdor()` (deeds job), `scripts/backfill_fdor_phase52_fields.py`, `harvesters/enrichment/geocode.py` (`fl_fdor_cadastral`) | ArcGIS `services9.arcgis.com/Gh9awoU677aKree0/.../Florida_Statewide_Cadastral/FeatureServer/0`, attributes plus a server-computed centroid (`returnGeometry=false`) | Statewide cadastral **attributes and centroid** | **Not changed.** Whether this FeatureServer is the Florida GeoData "current-year statewide parcels" dataset named in the response could not be verified: the sandbox cannot reach geodata.floridagio.gov. Its interim attribute and centroid allowance stays as is, and storing or displaying its geometry stays denied. Moving it under this approval is a separate decision that needs that verification |
| `fl_dor_statewide` (registry entry) | DOR NAL tax-roll files | Statewide tax roll | **No.** Not parcel geometry; still denies every operation |
| DOR Property Tax Oversight Data Portal county GIS parcel files | floridarevenue.com Data Portal | County parcel shapefiles | **Yes** (`fl_dor_pto_parcel_gis`). **No code reads these files today** |
| RealAuction / Bid4Assets / LienHub / LAFT harvesters | county sale sites | Auction, certificate and Available listings | **No.** Unchanged |

**Production, read-only (2026-10-20):**
- No geometry or boundary column, and no boundary table, exists in `public`.
  PostGIS 3.3.7 is installed.
- 2,989 active Florida rows. 2,094 of them carry coordinates:
  - 344 with `field_provenance.latitude.source = fdor_nal` (centroid points from
    the cadastral path above);
  - 1,750 with no recorded origin.
- 383 active Florida rows carry an FDOR market value (assessment year 2026).
- **No parcel boundary is stored, served or exposed anywhere.**

## The Parcel Shapefiles Readme: not yet read

The Readme
(https://floridarevenue.com/property/dataportal/Documents/PTO%20Data%20Portal/Map%20Data/Parcel%20Shapefiles%20Readme.pdf)
could not be retrieved from this environment, and the block was not routed
around:
- floridarevenue.com: the proxy refused it (HTTP 403);
- the fetch tool: no DNS resolution.

The register therefore records its caveats as **NOT YET READ**, listing only
the topics the owner reports it covers:
- PIN/PAR file variants;
- PARCELNO to PARCEL_ID joins;
- condominium units omitted or in separate files;
- stacked polygons;
- polygons covering several parcels;
- unmatched geometries;
- identifier-format differences.

These are technical caveats, not permission restrictions.
`technical_readme_reviewed` keeps every Florida operation denied until someone
who has read the document records:
- the review date (`technical_readme_reviewed_on`);
- the caveats transcribed from the document itself (`technical_caveats`).

## Geometry rules, ready for an ingestion path

There is no parcel-geometry storage on `main`. PR #144 carries an unmerged
design for it: a `parcel_boundaries` table, an RPC and a renderer. That PR's
migration is numbered 032, which collides with `main`'s 032, and its boundary
permission matrix predates both approvals. This change adds no storage and no
second layer. It adds the rules any path must follow, as pure functions in
`source_approvals.py`:

- **Refresh: expected cadence versus actual success** (`apply_refresh`)
  - Only a COMPLETE read, or an EMPTY read carrying the source's own empty
    signal, advances the last successful refresh.
  - FAILED, INCOMPLETE, SOURCE_UNAVAILABLE and STALE never advance it.
  - The cadence window never stands in for a refresh.
- **Deterministic association** (`match_geometries`)
  - A record is associated only on an exact identifier match.
  - No match is reported UNMATCHED; two or more features for one identifier
    (stacked polygons, condominium units) are reported AMBIGUOUS. Neither is
    ever associated.
  - Features that no record claims are counted (`unmatched_features`).
- **Simplification** (`simplify_ring`): Douglas-Peucker. A ring stays closed,
  keeps at least four positions and is never reduced to zero area.
- **Refresh plan** (`plan_geometry_refresh`)
  - One geometry per (source, property).
  - A read that is not COMPLETE changes nothing.
  - A record missing from a COMPLETE read keeps its geometry and is reported,
    never deleted.

The Florida join key (PARCELNO to PARCEL_ID) and any condominium handling are
not configured: both depend on the Readme. A future Florida path must take its
key fields and caveats from the reviewed Readme.

## Blockers before any production use

1. **Florida:** read the Parcel Shapefiles Readme and record its caveats and the
   review date. Until then every Florida operation is denied.
2. **Florida:** decide whether the existing `fl_fdor_cadastral` FeatureServer is
   the Florida GeoData dataset named in the response. This needs a reachable
   read of geodata.floridagio.gov.
3. **Utah:** record UGRC's disclaimer (text or an https page) in
   `data/source_approvals.csv`. Until then Utah display is denied. Utah is also
   not an activated state.
4. **Both:** decide whether export or API redistribution is wanted. Neither
   approval records it.
5. **Both:** an ingestion path and geometry storage, PR #144 or its successor,
   with a migration. That is a separate production change that needs explicit
   approval.
6. **Both:** keep the original emails somewhere durable. This repository is
   public, so a private record with a hash referenced here is safer than
   committing them.
