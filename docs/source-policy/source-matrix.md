# TAXACQ source matrix: display, link and collection decisions (2026-10-22)

The full per-source evidence is in `source-matrix.csv`, alongside this file: 88 rows, 21 columns, and seven decisions per source. Each decision is written as `VALUE [VERIFIED|PARTIAL|UNVERIFIED] basis`.

**How this was built.** This was a read-only review. No repository file, git state or database was changed.

Permission results come from running `harvesters.governance.permissions.authorize()` for every source × operation, with `today = 2026-10-22`.

Web reads on 2026-10-22 were limited to public pages: no login, no forms, no contact with anyone. Pages actually read:
- St. Louis LRA dataset page and its DCAT metadata;
- the City of St. Louis website-policies page;
- the Detroit DLBA ArcGIS item JSON;
- the Ramsey MapServer JSON;
- the Oklahoma County list page;
- the Fayette copyright page;
- the Horry program and Terms pages;
- the Shelby ePropertyPlus robots.txt and landing page.

These returned HTTP 403 and were not read: lienhub.com/doc/terms, bid4assets.com/robots.txt, alachua.realtaxdeed.com/robots.txt.

**Statutes.** No state public-records statute was read. flsenate.gov returned 429, and no other statute was attempted. So no decision rests on public-records law, and every "government publisher, no licence" decision is PARTIAL or UNVERIFIED. Florida law is not applied to any other state.

## Group totals (active production rows, from the 2026-10-22 counts supplied)

| Group | Meaning | Sources | Active rows |
|---|---|---|---|
| **A** | Facts + official link now, with a documented licence or written permission on file | 8 (3 inventory sources and 5 enrichment sources) | **10,472** (LA EBR 10,334 and CO Douglas 138) |
| **B** | Facts + link once a specific, named item is recorded | 36 | **44,049** (WI Green and enrichment not counted) |
| **C** | Link only | 27 (all catalog, discovery or restricted sources) | **0** |
| **D** | Needs counsel (and usually vendor approval) | 12 | **3,272** (FL Bid4Assets not counted) |
| **E** | Must stay blocked | 5 | **0** |
| **Total** | | 88 | **57,793**, equal to the supplied production total |

### A: display now (10,472 rows)

| Source | Rows | Licence |
|---|---|---|
| `la_ebr_adjudicated` | 10,334 | Public Domain; shown only as a dated list |
| `co_douglas_county_held_liens` | 138 | CC BY-SA 4.0 |
| `co_douglas_tax_sale_list` | 0 | CC BY-SA 4.0 |

Enrichment sources in A:
- `la_ebr_tax_parcels`, `la_ebr_tax_roll`: Public Domain.
- `usda_naip`: public domain.
- `ut_ugrc_lir_saltlake`: CC BY 4.0. Utah is not activated.
- `fl_dor_pto_parcel_gis`: DOR written permission, geometry only.

Open items:
- Counsel on the share-alike scope of Douglas County's CC BY-SA 4.0.
- File the original DOR and UGRC e-mails. Both are recorded only as owner summaries; the e-mails are not in the repository.

### B: display once a named item is recorded (44,049 rows)

**1. Owner-approved interim sources, customer-visible today: 1,147 rows.**
- Sources: Eaton 3, Lenawee 35, York 853, Albany 253, Morgan certificates 3, and Green WI.
- Basis: INTERNAL_RISK_ACCEPTANCE, which expires 2027-04-12.
- Named item: county written permission, or a recorded owner policy decision under the new "facts plus link-out" principle, filed as a dated record. Also needed: counsel's decision on showing owner names (pre-sale blocker 6), for Albany, York and Morgan.

**2. UNREVIEWED government and land-bank AVAILABLE sources, admin-only today: 42,797 rows.**

| Source | Rows |
|---|---|
| Detroit DLBA lots | 30,590 |
| St. Louis LRA | 9,778 |
| Shelby Land Bank | 1,787 |
| Fayette | 376 |
| Oklahoma County | 195 |
| Horry | 51 |
| Detroit programs | 12 |
| Oceana | 5 |
| Ramsey | 2 |
| Georgetown | 1 |

None of these publishes a licence or a prohibition. Each has only fetch/parse/store INTERIM records and **no `display` record**. The named item is a `display` permission record, plus an admin review in `data/available_publication_reviews.csv`. Source-specific points:
- **St. Louis:** the DCAT metadata says `accessLevel: "restricted public"`. Ask SLDC what restriction this means.
- **Horry and Fayette:** both sites say "All rights reserved", and Horry adds "Any rights not expressly granted herein are reserved". It is a low-priority counsel question whether this reaches the list's facts.
- **Shelby:** its robots.txt is open ("Disallow:" with nothing after it). The ePropertyPlus and Land Bank terms are not read, and the source is read through the portal's internal JSON API.
- **Detroit:** the ArcGIS item's `licenseInfo` is null. Two presentation decisions are still open: the customer-subset rule and lots restricted to certain buyers.

**3. Florida clerk-run LAFT sources, grandfathered and customer-visible: 105 rows.**
- `fl_laft_html` 61, `pdfs` 15, `pioneer` 21, `hillsborough` 3, `stlucie` 3, `leon` 2.
- Named items:
  - **Stop** the ScraperAPI fallback in `fl_laft_html`, which routes around a county IP block.
  - Counsel or owner decision on the Volusia disclaimer bypass (pre-sale blocker 4).
  - Read the Pioneer TaxSmartWeb, Hillsborough OnBase and St. Lucie portal terms.

**4. Enrichment and not-yet-activated sources: 0 rows.**
- Interim enrichment: Census, FEMA, FDOR cadastral, Santa Rosa, Palm Coast.
- Never requested: WI V12 ("free for public consumption"), St. Louis parcels, Jim Wells CAD.
- Gated: Morgan deed auctions, Oconee, AL, AR, AZ.

### C: link only (0 rows)

- `tx_hctax` and `tx_comptroller_directory` have LINK_ONLY records.
- `wi_dane_tax_deed_auction`: "Copyright County of Dane".
- `la_ebr_arcgis_parcels`: "Access Constraints: copyright". The Public Domain Socrata layer is used instead.
- The discovery and catalog candidates: the SC Forfeited Land Commission pages, the WI tax-deed pages, Lenawee's land bank, the public-notice sites, court records and the TX CAD layers.
- Genesee Land Bank: its terms forbid publication ("solely for your personal use"). It should never be collected, only linked to.

### D: needs counsel (3,272 rows; customers see most of them today)

| Source | Rows | What blocks it |
|---|---|---|
| `fl_realauction` | 1,065 | The EULA summary prohibits automated access and distribution without RealAuction's written consent. robots.txt is disallowed. |
| `fl_lienhub_certificates` | 1,611 | The User Agreement "EXPRESSLY PROHIBITED" robots and spiders. The source has returned HTTP 403 since 2026-10-01, so these rows are stale. |
| `tx_lgbs` | 19 auctions + 421 laft | Linebarger's legal-disclosures clause prohibits reproduction without permission. Its scope over the API is unresolved. |
| `tx_realauction` | 103 | robots.txt refusals; no terms found. |
| `fl_laft_realtdm` | 40 | RealAuction family. |
| `fl_laft_osceola` | 10 | Read through the portal's private API. |
| `fl_laft_orange` | 3 | Scripted disclaimer click-through. |
| `fl_bid4assets_okaloosa` | not counted | Terms never read; robots.txt returned 403. |

Enrichment in D:
- `co_oit_public_parcels`: "resale ... forbidden".
- `wv_auditor_land_sales`: the Auditor's terms grant no reuse right.
- `tx_stratmap_land_parcels`: the parcel layer's own licence is unsettled.
- `mi_county_parcels`: Eaton's click-through licence has not been read.

Under the owner's principle, these sources can be **linked to now** (deep link to the county's sale or certificate page). Automated collection from the vendor stays unauthorized until counsel and the vendor's written approval say otherwise. LienHub's 403 is an access control and must never be worked around.

### E: must stay blocked (0 rows)

- `tx_pbfcm`: anti-reproduction clause.
- `tx_mvba`: non-commercial-use-only clause.
- `tx_ctsa`: paywall plus an anti-competitive-use clause.
- `tx_govease`: `Disallow: /` and no Terms of Use found. This is a technical signal only; a human reading of its terms could move it to D.
- `google_street_view`: storage is not permitted by the provider's terms.

## Findings that matter for the new principle

1. **Today's customer view is inconsistent with the evidence.** Every row from the four vendor sources has a NULL `publication_status`, so customers see them: `fl_realauction`, `fl_lienhub_certificates`, and the `tx_lgbs` and `tx_realauction` auctions (2,798 rows). Meanwhile 42,797 government and land-bank rows without a restriction are withheld. The new principle reverses this risk ordering.
2. **There is no `link` permission for almost any source.** `data/source_permissions.csv` records the `link` operation only for `tx_comptroller_directory` and `tx_hctax`, the latter scoped to Harris. For every other source, `authorize(..., "link")` returns NO_RECORD (denied). The "go directly to the official source" principle needs explicit `link` records, or a documented rule that linking to an official page is not gated.
3. **No source in groups B to D has a `display` record based on a documented licence.** All of these display records are INTERIM: grandfathered practice or internal risk acceptance, expiring 2027-04-12. Interim display records exist for the FL LAFT sources, the vendor sources and the six owner-approved counties. The ten UNREVIEWED AVAILABLE sources have no display record at all.
4. **Practices that bypass access controls or accept terms without a decision**, which the principle forbids:
   - the `fl_laft_html` ScraperAPI fallback;
   - the Volusia disclaimer bypass;
   - the scripted Orange click-through;
   - the private Osceola API;
   - LienHub's backoff, which was added in response to WAF 403s.

   Each one needs a keep, change or discontinue decision (pre-sale blocker 4).
5. **Unknowns are marked as unknown.** Not read:
   - the Bid4Assets, ePropertyPlus, Pioneer, OnBase, AcclaimWeb and RealAuction ToS;
   - Oceana's and Georgetown's terms text (the Georgetown page returned HTTP 200 but its text was unreadable);
   - the text of every state public-records statute.
