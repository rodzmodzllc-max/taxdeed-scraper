# TAXACQ - Data Source, Legal Permission and Usage Status Audit

**Date:** 2026-10-12 · **Repository state audited:** `main` at `a95593c5b6ec2390f1c64e35cd951539f39f2af7` (read-only worktree) · **Author:** audit session (backend/pipeline scope) · **Production:** unchanged - no migration applied, no database write, no workflow dispatched, no source enabled or disabled, no e-mail sent.

The machine-readable register with all 21 fields per source is `data/audit/source_register_2026-10-12.csv` (this file embeds a condensed view). Nothing in this report is a legal opinion; every classification cites the repository record it rests on.

## 1. Executive summary

**Total distinct sources discovered: 84** (one row per provider / dataset / API / portal / permission regime; Florida counties on a shared platform are split only where the recorded permission regime differs, e.g. the two RealAuction counties whose EULAs were located, the three LAFT counties reached through a proxy).

| Legal / contractual status | Sources |
|---|---|
| APPROVED | 1 |
| APPROVED WITH CONDITIONS | 8 |
| LINK-ONLY (as the enablement decision; no source has links-only as a *granted* legal status) | 14 |
| Awaiting review - LEGAL REVIEW REQUIRED | 19 |
| Awaiting review - OWNER PERMISSION REQUIRED | 11 |
| RESTRICTED | 8 |
| BLOCKED | 5 |
| UNKNOWN / UNVERIFIED | 32 |

36 of the 84 sources are ACTIVE today (scheduled, manual-dispatch or client-side display). Only 8 of those 36 rest on a licence or grant actually recorded in the repository (Douglas CO, East Baton Rouge x2, USDA NAIP, MapTiler, and the three directly-read Florida clerk-list groups); the Florida and Texas core (RealAuction, LienHub, LGBS, RealTDM) runs on **grandfathered practice** with the commercial-use question open, and the six owner-approved expansion sources run on an **internal risk acceptance dated 2026-09-30**, not on a grant from the county.

**The three highest-value next steps**

1. **Counsel reads the four documents that gate the core product** (pre-sale blockers 1-3 in `docs/legal/pre-sale-blockers.md`): the Alachua and Volusia RealAuction EULAs, the LienHub User Agreement, and the Linebarger legal-disclosures clause. One sitting resolves the legal status of 46 FL auction counties, the closed-results feed, 11 RealTDM LAFT counties, 24 TX RealAuction counties, 32 certificate counties and 8 LGBS counties - 121 of the 237 registry rows.
2. **Convert the six internal approvals into written permissions and close the loop on the six inquiries already sent.** Send the short county request (section 6, template C) to Morgan CO, Eaton MI, Lenawee MI, York SC, Green WI and Albany WY - five of these are the entire paid-beta scope (`data/paid_beta_sources.csv`). Record the status of the six inquiries the owner has already sent (FDOR, Detroit Enterprise GIS, St. Louis Assessor, Fayette GIS, Oklahoma OGI, RealAuction) in the repository; this session could not read the mailbox (section 9).
3. **Make permission a per-operation, fail-closed, expiring record** (backlog B-1 to B-3): today `legal_status` is one value per source, the FDOR cadastral layer is marked `APPROVED` in code with no licence cited, the Florida PowerShell pipeline never consults the governance package, and no permission has an expiry or review date.

**The specific evidence explaining GovEase's current status.** `tx_govease` is `legal_status=BLOCKED` in `harvesters/governance/registry.py` (review date 2026-09-14). The record's own words: commercial-use status is a *"LEGAL_REVIEW_REQUIRED-grade finding treated conservatively as BLOCKED for ingestion-gate purposes - robots.txt blanket disallow (`Disallow: /`) with no locatable Terms of Use to weigh against it"*; `robots_status` says the blanket disallow is *"the deciding factor for this source, in the absence of any locatable Terms of Use"*; `terms_status` says *"No Terms of Use page was located."* The cited reviewer document, `claude/govease-source-onboarding-blocked.md`, is a claude.ai project document and is **not in the repository**, so the robots.txt observation cannot be re-verified from the repo. `harvesters/governance/verification.py` records `contract_status NOT_CONTACTED` / `contact_status NOT_CONTACTED`; `data/tx_county_coverage_matrix.csv` carries four rows (Denton, Parker, Wichita, Wise) "BLOCKED, robots.txt Disallow: /"; `harvesters/texas_harvester.py` keeps `harvest_govease()` as a `NotImplementedError` stub; `govease.com` sits on the untrusted-host lists in `harvesters/sources/acquisition_gate.py`, `scripts/laft_purchase_paths.py` and `public/app.js`. In short: the block is a **technical signal (robots.txt) plus the absence of any terms**, applied under a conservative decision rule; it is not a legal finding, not a vendor refusal, and not a risk assessment of GovEase's data. It has not been re-checked since 2026-09-14, and this session could not resolve the GovEase hosts (DNS failure through the sandbox proxy on 2026-10-12). Full memo in section 4.

## 2. Status definitions used in this audit

Legal status and implementation status are separate columns; neither is inferred from the other, from public accessibility, from a county linking to a vendor, from the absence of a login, from the presence of rows in the database, from another county's use of the same platform, or from a prior scraper.

| Legal / contractual status | Definition (what must be on record) |
|---|---|
| **APPROVED** | A licence, grant or terms text on record permits the operations the product performs, with no unmet condition. |
| **APPROVED WITH CONDITIONS** | A licence or grant on record permits the operations subject to conditions the product must satisfy (attribution, share-alike, dated-list presentation, display-only). |
| **LINK-ONLY** | Used as an *enablement decision*: the only operation the product performs is a link to the source's own published page; no copy, no store, no derived data. No source is classified as legally link-only, because linking needs no grant. |
| **LEGAL REVIEW REQUIRED** | Terms, a clause, a disclaimer, a robots.txt refusal or an access-control step exists and has been located, and a competent reader (counsel or the owner on counsel's advice) has not yet decided whether the product's use is permitted. |
| **OWNER PERMISSION REQUIRED** | Terms were looked for and are silent (no grant, no prohibition). The data-owning agency's written permission is the only way to establish a right beyond linking. Includes sources running under the product owner's internal risk acceptance of 2026-09-30, which is recorded as such and is not a grant. |
| **RESTRICTED** | A term on record permits some use and prohibits a specific operation the product would otherwise want (resale, harvesting, financial use, production use of a demo key, reuse right withheld). |
| **BLOCKED** | An affirmative prohibition, a paywall with an anti-competitive clause, a provider term that forbids the product's intended use, or a conservative block applied by this project's own decision rule. The reason and its evidence are stated per row. |
| **UNKNOWN / UNVERIFIED** | No terms have been read, or the only evidence is a search-index snippet. The source may be reachable and may even be in production; its legal status is simply not established. |

| Implementation status | Definition |
|---|---|
| ACTIVE (scheduled) | Read by a cron job in `.github/workflows/harvest-and-sync.yml`. |
| ACTIVE (manual dispatch only) | Read only when a human dispatches the job (`job=texas`, `job=available`, `job=enrich`). |
| ACTIVE (client-side display) | Loaded by the visitor's browser; nothing stored server-side. |
| IMPLEMENTED, ADMIN-ONLY | Collected and synced; rows carry `publication_status=UNREVIEWED` and are withheld from customers. |
| IMPLEMENTED, NOT SCHEDULED | Adapter exists and can be read live on dispatch; no row is written until an admin review approves. |
| IMPLEMENTED, SOURCE UNAVAILABLE | Scheduled, but every read fails (LienHub HTTP 403 since 2026-10-01). |
| GATED STUB / GATED ADAPTER | Code path exists but the gate refuses before the first request (`states.is_activated`, `otc.gate`, BLOCKED registry status). |
| CONFIG INERT | An enrichment configuration is registered but never requested. |
| NOT IMPLEMENTED | Catalogued or discovered only. |

## 3. Source register (condensed)

All 21 fields per row are in `data/audit/source_register_2026-10-12.csv`. The table below shows the identity, the two statuses and the decision.

| # | Source ID | Provider / owner (platform vs. data owner) | Coverage | Implementation | Legal status | Enablement decision |
|---|---|---|---|---|---|---|
| 1 | `fl_realauction_alachua_volusia` | Platform operator: RealAuction (Real Auction Inc., realtaxdeed.com / realforeclose.com). Data owner: Alachua County Clerk; Volusia County Clerk. | FL: Alachua, Volusia | ACTIVE | **LEGAL REVIEW REQUIRED** | KEEP ENABLED (grandfathered) - no expansion of operations |
| 2 | `fl_realauction_other_44` | Platform operator: RealAuction. Data owners: 44 Florida Clerks of Court (Baker ... Walton) | FL: 44 counties (data/county_source_registry.csv fl_realauction rows minus Alachua, Volusi | ACTIVE | **UNKNOWN / UNVERIFIED** | KEEP ENABLED (grandfathered) - no expansion |
| 3 | `fl_realauction_closed_results` | RealAuction (same hosts), AREA=C 'Auctions Closed or Canceled' AJAX feed | FL: same 46 counties | ACTIVE | **LEGAL REVIEW REQUIRED** | KEEP ENABLED (grandfathered practice) - no bidder data |
| 4 | `fl_bid4assets_okaloosa` | Platform operator: Bid4Assets (Liquidity Services). Data owner: Okaloosa County Clerk | FL: Okaloosa | ACTIVE | **UNKNOWN / UNVERIFIED** | KEEP ENABLED (grandfathered) - one county; review before any expansion |
| 5 | `fl_lienhub_certificates` | Platform operator: Grant Street Group (LienHub). Data owners: 32 Florida Tax Collectors | FL: 32 counties (registry fl_lienhub_certificates rows) | IMPLEMENTED, SOURCE UNAVAILABLE | **LEGAL REVIEW REQUIRED** | KEEP DISABLED PENDING PERMISSION (reads already fail); no bypass |
| 6 | `fl_laft_pdfs` | Data owner: Clerk of Court (official PDF lists). No platform operator (Brevard list hosted on library.municode.com) | FL: Bradford, Brevard, Glades, Hendry, Marion, Pasco, Volusia (7) | ACTIVE | **APPROVED WITH CONDITIONS** | KEEP ENABLED, CONDITIONS (official government lists; show the clerk's own wordin |
| 7 | `fl_laft_html_direct` | Data owner: Clerk of Court (county-run HTML pages) | FL: Calhoun, Dixie, Franklin, Gadsden, Gulf, Hamilton, Hardee, Holmes, Indian River, Lafay | ACTIVE | **APPROVED WITH CONDITIONS** | KEEP ENABLED, CONDITIONS |
| 8 | `fl_laft_html_proxied` | Data owner: Clerk of Court. Third party in the path: ScraperAPI (proxy vendor) used to reach hosts that block the GitHub runner's IP | FL: Escambia, Columbia, Union (3) | ACTIVE | **LEGAL REVIEW REQUIRED** | KEEP ENABLED ONLY UNTIL COUNSEL DECIDES; candidate to disable the proxy path |
| 9 | `fl_laft_realtdm` | Platform operator: RealAuction (RealTDM, <county>.realtdm.com). Data owner: each Clerk | FL: Alachua, Flagler, Highlands, Lee, Miami-Dade, Pinellas, Polk, Santa Rosa, Sarasota, Se | ACTIVE | **LEGAL REVIEW REQUIRED** | KEEP ENABLED (grandfathered) - covered by RealAuction outreach |
| 10 | `fl_laft_pioneer` | Platform operator: Pioneer Technology Group (TaxSmartWeb / Landmark Web / BenchMark). Data owner: each Clerk | FL: Bay, Citrus, Clay, Duval, Hernando, Levy, Martin, Okeechobee, Palm Beach, St. Johns, W | ACTIVE | **UNKNOWN / UNVERIFIED** | KEEP ENABLED (grandfathered); review terms before adding counties |
| 11 | `fl_laft_orange` | Data owner: Orange County Comptroller (occompt.com). Access requires a guest disclaimer acknowledgement POST | FL: Orange (1) | ACTIVE | **LEGAL REVIEW REQUIRED** | KEEP ENABLED ONLY UNTIL COUNSEL DECIDES |
| 12 | `fl_laft_osceola` | Platform operator: NewVision Systems (officialrecords.osceolaclerk.org). Data owner: Osceola Clerk | FL: Osceola (1) | ACTIVE | **LEGAL REVIEW REQUIRED** | KEEP ENABLED ONLY UNTIL COUNSEL DECIDES |
| 13 | `fl_laft_hillsborough` | Platform operator: Hillsborough Clerk public access portal (publicaccess.hillsclerk.com) | FL: Hillsborough (1) | ACTIVE | **UNKNOWN / UNVERIFIED** | KEEP ENABLED (grandfathered); review |
| 14 | `fl_laft_stlucie` | Platform operator: Acclaim (acclaimweb.stlucieclerk.gov). Data owner: St. Lucie Clerk | FL: St. Lucie (1) | ACTIVE | **UNKNOWN / UNVERIFIED** | KEEP ENABLED (grandfathered); review |
| 15 | `fl_laft_leon` | Data owner: Leon County Clerk (lforms.leonclerk.com JSON) | FL: Leon (1) | ACTIVE | **APPROVED WITH CONDITIONS** | KEEP ENABLED, CONDITIONS |
| 16 | `fl_laft_not_found_15` | 15 Florida Clerks with no machine-readable LAFT list located (Baker, Broward, Charlotte, Collier, DeSoto, Gilchrist, Jackson, Jefferson, Lake, Liberty, Monroe,  | FL: 15 counties | NOT IMPLEMENTED | **UNKNOWN / UNVERIFIED** | LINKS ONLY |
| 17 | `fl_dor_statewide_nal` | Florida Department of Revenue, Property Tax Oversight (NAL / tax roll files) | FL: statewide | NOT IMPLEMENTED | **LEGAL REVIEW REQUIRED** | KEEP DISABLED PENDING PERMISSION |
| 18 | `fl_statewide_cadastral_fgio` | Florida Geographic Information Office / FDOR 'Florida Statewide Cadastral' ArcGIS FeatureServer (services9.arcgis.com/Gh9awoU677aKree0) | FL: statewide | ACTIVE | **UNKNOWN / UNVERIFIED** | KEEP ENABLED (attributes + centroid) - correct the recorded status |
| 19 | `fl_santa_rosa_parcels` | Santa Rosa County (ArcGIS Hub open data ParcelsOpenData FeatureServer) | FL: Santa Rosa | ACTIVE | **UNKNOWN / UNVERIFIED** | KEEP ENABLED; record licence |
| 20 | `fl_palm_coast_flagler_parcels` | City of Palm Coast GIS (gis.palmcoast.gov FlaglerCountyParcels MapServer) | FL: Flagler | ACTIVE | **UNKNOWN / UNVERIFIED** | KEEP ENABLED; record licence |
| 21 | `fl_pa_pinellas` | Pinellas County Property Appraiser | FL: one county | NOT IMPLEMENTED | **RESTRICTED** | LINKS ONLY |
| 22 | `fl_pa_broward` | Broward County Property Appraiser (bcpa.net) | FL: one county | NOT IMPLEMENTED | **RESTRICTED** | LINKS ONLY |
| 23 | `fl_pa_duval` | Duval County Property Appraiser | FL: one county | NOT IMPLEMENTED | **RESTRICTED** | LINKS ONLY |
| 24 | `fl_pa_miami_dade` | Miami-Dade County Property Appraiser | FL: one county | NOT IMPLEMENTED | **LEGAL REVIEW REQUIRED** | LINKS ONLY |
| 25 | `fl_pa_other_eight` | Palm Beach, Orange, Polk, Volusia, Pasco, Hillsborough, Lee, Brevard Property Appraisers | FL: one county | NOT IMPLEMENTED | **UNKNOWN / UNVERIFIED** | LINKS ONLY |
| 26 | `fl_clerk_court_records_and_public_notices` | Florida clerks' official records (court filings) and Florida Press Association public notices | FL: statewide | NOT IMPLEMENTED | **LEGAL REVIEW REQUIRED** | DO NOT ADD (low value / high maintenance) |
| 27 | `tx_lgbs` | Linebarger Goggan Blair & Sampson, LLP (taxsales.lgbs.com) - delinquent-tax counsel acting for the taxing units; vendor listing | TX: Galveston, Goliad, Hardin, Jim Wells, Leon, Liberty, Maverick, Van Zandt (8) | ACTIVE | **LEGAL REVIEW REQUIRED** | KEEP AS IS (manual-only, no retry) PENDING COUNSEL |
| 28 | `tx_realauction` | Platform operator: RealAuction (<county>.texas.sheriffsaleauctions.com). Data owners: 24 Texas sheriff/constable sale authorities (not verified per county) | TX: 24 counties (registry tx_realauction rows) | ACTIVE | **LEGAL REVIEW REQUIRED** | KEEP AS IS (manual-only) PENDING REPLY |
| 29 | `tx_hctax` | Harris County Tax Assessor-Collector (hctax.net) | TX: Harris | IMPLEMENTED, NOT SCHEDULED | **LEGAL REVIEW REQUIRED** | LINKS ONLY until permission |
| 30 | `tx_pbfcm` | Vendor: Perdue Brandon Fielder Collins & Mott, LLP (pbfcm.com) (delinquent-tax counsel to the taxing units) | TX: Austin, Chambers, Fort Bend, Hidalgo, Matagorda, Maverick, Milam, Nacogdoches, San Jac | GATED STUB | **BLOCKED** | REMAIN BLOCKED |
| 31 | `tx_mvba` | Vendor: McCreary, Veselka, Bragg & Allen, P.C. (mvbalaw.com) (delinquent-tax counsel to the taxing units) | TX: Calhoun, Runnels | GATED STUB | **BLOCKED** | REMAIN BLOCKED |
| 32 | `tx_ctsa` | Vendor: CTSA (ctsa.com) tax-sale listing service (delinquent-tax counsel to the taxing units) | TX: Statewide listing service | GATED STUB | **BLOCKED** | REMAIN BLOCKED |
| 33 | `tx_govease` | Platform operator: GovEase (liveauctions.govease.com, govease.com). Data owners: Denton, Parker, Wichita, Wise county sale authorities (TX); also used by TN cou | TX: Denton, Parker, Wichita, Wise (4). TN: 6 counties noted, not registered | GATED STUB | **BLOCKED** | REMAIN BLOCKED (no operation) pending the memo's decisions |
| 34 | `tx_comptroller_directory` | Texas Comptroller of Public Accounts (county tax office / CAD directory; also Phase-36 'TX Comptroller reports') | TX: statewide | NOT IMPLEMENTED | **UNKNOWN / UNVERIFIED** | LINKS ONLY |
| 35 | `tx_county_struck_off_candidates_19` | 19 Texas county / CAD / tax-office websites (Bandera, Bee, Bexar, Brazoria, Camp, Collin, Dallas, Fayette, Grayson, Gregg, Hood, Jefferson, Jim Wells, Montgomer | TX: 19 counties | NOT IMPLEMENTED | **UNKNOWN / UNVERIFIED** | LINKS ONLY |
| 36 | `tx_cad_parcels_bis_and_jim_wells` | Hardin, Liberty, Goliad County Appraisal Districts (GIS hosted by BIS Consultants); Jim Wells CAD parcel layer (config tx_jim_wells_cad_parcels) | TX: Hardin, Liberty, Goliad, Jim Wells | CONFIG INERT / CATALOG | **UNKNOWN / UNVERIFIED** | KEEP DISABLED PENDING PERMISSION |
| 37 | `tx_stratmap_land_parcels` | Texas Geographic Information Office (TxGIO / formerly TNRIS) StratMap Land Parcels | TX: statewide | NOT IMPLEMENTED | **LEGAL REVIEW REQUIRED** | KEEP DISABLED PENDING COUNSEL |
| 38 | `tx_phase36_cads_and_notices` | Harris, Dallas, Bexar, Tarrant, Montgomery, Denton CADs (Phase 36); Texas Press Association public notices; Texas district clerks' tax suits | TX: 6 CADs; statewide notices | NOT IMPLEMENTED | **LEGAL REVIEW REQUIRED** | DO NOT ADD NOW (low value / high cost) |
| 39 | `la_ebr_adjudicated` | City of Baton Rouge / Parish of East Baton Rouge open data (data.brla.gov) - Adjudicated Property dataset | LA: East Baton Rouge | ACTIVE | **APPROVED WITH CONDITIONS** | KEEP ENABLED, CONDITIONS (dated list) |
| 40 | `la_ebr_tax_parcels_and_tax_roll` | EBR Parish Assessor via Open Data BR (Tax Parcels ei2c-krsr; Tax Roll) | LA: East Baton Rouge | ACTIVE | **APPROVED WITH CONDITIONS** | KEEP ENABLED, CONDITIONS (attribution) |
| 41 | `la_ebr_arcgis_parcels` | East Baton Rouge City-Parish GIS (ArcGIS parcels layer) | LA: East Baton Rouge | NOT IMPLEMENTED | **RESTRICTED** | CONSOLIDATE (duplicate of approved datasets) / REMAIN DISABLED |
| 42 | `la_ebr_sheriff_and_notices` | East Baton Rouge Parish Sheriff tax sale; Louisiana Press Association notices | LA | NOT IMPLEMENTED | **LEGAL REVIEW REQUIRED** | LINKS ONLY |
| 43 | `co_morgan_county_held_certificates` | Morgan County, Colorado (Treasurer) - morgancounty.colorado.gov HTML table | CO: Morgan | ACTIVE | **OWNER PERMISSION REQUIRED** | KEEP ENABLED (owner decision) - send permission request |
| 44 | `mi_eaton_treasurer_sale` | Eaton County, Michigan (Treasurer) ArcGIS layer | MI: Eaton | ACTIVE | **OWNER PERMISSION REQUIRED** | KEEP ENABLED (owner decision) - send permission request |
| 45 | `mi_lenawee_tax_sale` | Lenawee County, Michigan (Treasurer) ArcGIS layer | MI: Lenawee | ACTIVE | **OWNER PERMISSION REQUIRED** | KEEP ENABLED (owner decision) - send permission request |
| 46 | `sc_york_tax_sale` | York County, South Carolina ArcGIS layer | SC: York | ACTIVE | **OWNER PERMISSION REQUIRED** | KEEP ENABLED (owner decision) - send permission request |
| 47 | `wi_green_tax_deed_sales` | Green County, Wisconsin (Treasurer) HTML table + bid form | WI: Green | ACTIVE | **OWNER PERMISSION REQUIRED** | KEEP ENABLED (owner decision) - send permission request |
| 48 | `wy_albany_tax_sale` | Albany County, Wyoming ArcGIS layer | WY: Albany | ACTIVE | **OWNER PERMISSION REQUIRED** | KEEP ENABLED (owner decision) - send permission request |
| 49 | `co_douglas_open_data` | Douglas County, Colorado open data (two ArcGIS items: county-held liens; tax sale list) | CO: Douglas | ACTIVE | **APPROVED WITH CONDITIONS** | KEEP ENABLED, CONDITIONS |
| 50 | `co_morgan_treasurer_deed_auctions` | Morgan County, Colorado Treasurer deed auctions page | CO: Morgan | IMPLEMENTED, NOT SCHEDULED | **OWNER PERMISSION REQUIRED** | KEEP DISABLED PENDING PERMISSION |
| 51 | `co_oit_public_parcels` | State of Colorado, Office of Information Technology (OIT GIS) Public Parcels | CO: statewide (Morgan features carry owner/situs/zoning only) | ACTIVE | **RESTRICTED** | KEEP ENABLED, CONDITIONS (no paid tier, no export) |
| 52 | `ut_ugrc_lir_saltlake` | Utah Geospatial Resource Center (UGRC) LIR parcels, Salt Lake | UT: Salt Lake (state not activated) | CONFIG REGISTERED, STATE NOT ACTIVATED | **APPROVED WITH CONDITIONS** | NOT NEEDED NOW |
| 53 | `wi_sco_v12_parcels` | Wisconsin State Cartographer's Office V12 statewide parcels | WI: Green, Dane (config) | CONFIG REGISTERED, UNREVIEWED | **UNKNOWN / UNVERIFIED** | KEEP DISABLED PENDING PERMISSION |
| 54 | `wi_dane_tax_deed_auction` | Dane County, Wisconsin Treasurer (treasurer.danecounty.gov) | WI: Dane | IMPLEMENTED, NOT SCHEDULED | **RESTRICTED** | LINKS ONLY |
| 55 | `wi_wood_burnett_marathon` | Wood, Burnett, Marathon County Treasurers / Clerks (WI) | WI: 3 counties | NOT IMPLEMENTED | **UNKNOWN / UNVERIFIED** | LINKS ONLY |
| 56 | `wy_statewide_parcel_viewer` | Wyoming state GIS parcel viewer | WY: statewide | NOT IMPLEMENTED | **UNKNOWN / UNVERIFIED** | KEEP DISABLED PENDING PERMISSION |
| 57 | `mi_county_parcels_eaton_clickthrough` | Michigan county GIS offices (Eaton click-through licence not read) | MI | NOT IMPLEMENTED | **LEGAL REVIEW REQUIRED** | KEEP DISABLED PENDING COUNSEL |
| 58 | `mi_detroit_landbank_lots_and_programs` | Detroit Land Bank Authority (two ArcGIS layers: lots with four vacant-land statuses + 'Marketed Structure For Sale'; programs layer). Operated by DLBA; hosted o | MI: Wayne (Detroit) | IMPLEMENTED, ADMIN-ONLY | **OWNER PERMISSION REQUIRED** | KEEP ADMIN-ONLY PENDING PERMISSION |
| 59 | `mi_oceana_landbank` | Oceana County Land Bank (oceana.mi.us HTML) | MI: Oceana | IMPLEMENTED, ADMIN-ONLY | **UNKNOWN / UNVERIFIED** | KEEP ADMIN-ONLY PENDING PERMISSION |
| 60 | `mn_ramsey_tax_forfeit` | Ramsey County, Minnesota tax-forfeited land layer (maps.co.ramsey.mn.us) | MN: Ramsey | IMPLEMENTED, ADMIN-ONLY | **UNKNOWN / UNVERIFIED** | KEEP ADMIN-ONLY PENDING PERMISSION |
| 61 | `mo_stl_lra_inventory` | St. Louis City Land Reutilization Authority (LRA) CSV on stlouis-mo.gov | MO: St. Louis City | IMPLEMENTED, ADMIN-ONLY | **UNKNOWN / UNVERIFIED** | KEEP ADMIN-ONLY PENDING PERMISSION |
| 62 | `ok_oklahoma_county_owned` | Oklahoma County (docs.oklahomacounty.org) county-owned property list with suggested bid and offline bid form | OK: Oklahoma | IMPLEMENTED, ADMIN-ONLY | **UNKNOWN / UNVERIFIED** | KEEP ADMIN-ONLY PENDING PERMISSION |
| 63 | `pa_fayette_repository` | Fayette County, Pennsylvania Tax Claim Bureau repository list (PDF, dated 2025-10-07) | PA: Fayette | IMPLEMENTED, ADMIN-ONLY | **UNKNOWN / UNVERIFIED** | KEEP ADMIN-ONLY PENDING PERMISSION |
| 64 | `sc_georgetown_forfeited_land` | Georgetown County, SC Forfeited Land Commission PDF | SC: Georgetown | IMPLEMENTED, ADMIN-ONLY | **OWNER PERMISSION REQUIRED** | KEEP ADMIN-ONLY PENDING PERMISSION |
| 65 | `sc_horry_forfeited_land` | Horry County, SC FLC yearly workbooks (XLSX) + county-wide bid form | SC: Horry | IMPLEMENTED, ADMIN-ONLY | **UNKNOWN / UNVERIFIED** | KEEP ADMIN-ONLY PENDING PERMISSION |
| 66 | `tn_shelby_landbank` | Shelby County Land Bank via ePropertyPlus portal (public-sctn.epropertyplus.com; platform vendor ePropertyPlus) | TN: Shelby | IMPLEMENTED, ADMIN-ONLY | **UNKNOWN / UNVERIFIED** | KEEP ADMIN-ONLY PENDING PERMISSION |
| 67 | `sc_spartanburg_forfeited_land` | Spartanburg County, SC FLC (list is a redemption-period bid assignment; never AVAILABLE) | SC: Spartanburg | ADAPTER EXISTS, NEVER PUBLISHED | **OWNER PERMISSION REQUIRED** | REMAIN DISABLED (low value) |
| 68 | `sc_oconee_tax_sale_list` | Oconee County, SC tax sale list (oconeesc.com) | SC: Oconee | IMPLEMENTED, NOT SCHEDULED | **OWNER PERMISSION REQUIRED** | KEEP DISABLED PENDING PERMISSION |
| 69 | `sc_flc_catalog_other` | York, Richland (403), Jasper, Fairfield, Aiken, Lexington FLC pages; Oconee FLC | SC: 7 counties | NOT IMPLEMENTED | **UNKNOWN / UNVERIFIED** | LINKS ONLY |
| 70 | `mo_stl_parcels_coordinates` | City of St. Louis open data parcels (coordinate layer) | MO: St. Louis City | CONFIG INERT | **UNKNOWN / UNVERIFIED** | KEEP DISABLED PENDING PERMISSION |
| 71 | `mi_lenawee_landbank` | Lenawee County Landbank Authority | MI: Lenawee | NOT IMPLEMENTED | **UNKNOWN / UNVERIFIED** | LINKS ONLY |
| 72 | `al_ador_state_land` | Alabama Department of Revenue, Property Tax Division (State Land Commissioner) delinquent/sold-to-state search | AL: statewide | GATED ADAPTER / FIXTURE ONLY | **UNKNOWN / UNVERIFIED** | REMAIN GATED |
| 73 | `ar_cosl_post_auction` | Arkansas Commissioner of State Lands Post Auction Sales List | AR: statewide | GATED ADAPTER / FIXTURE ONLY | **UNKNOWN / UNVERIFIED** | REMAIN GATED |
| 74 | `az_maricopa_state_cp` | Maricopa County Treasurer State CP liens list (CSV) | AZ: Maricopa | GATED ADAPTER / FIXTURE ONLY | **UNKNOWN / UNVERIFIED** | REMAIN GATED |
| 75 | `wv_auditor_land_sales` | West Virginia State Auditor land sales (client-script flow) | WV: statewide | NOT IMPLEMENTED | **RESTRICTED** | REMAIN GATED |
| 76 | `census_geocoder` | U.S. Census Bureau Geocoder (geocoding.geo.census.gov) | National (used for FL and expansion states, except NO_ADDRESS_GEOCODE_SOURCES) | ACTIVE | **UNKNOWN / UNVERIFIED** | KEEP ENABLED; record terms |
| 77 | `fema_nfhl` | FEMA National Flood Hazard Layer (ArcGIS REST) | National | ACTIVE | **UNKNOWN / UNVERIFIED** | KEEP ENABLED; record terms |
| 78 | `usda_naip_via_usgs` | USDA NAIP aerial imagery served by USGS The National Map (imagery.nationalmap.gov exportImage); stored copies in Supabase Storage | National | ACTIVE | **APPROVED** | KEEP ENABLED, CONDITIONS (attribution) |
| 79 | `google_street_view_static` | Google Maps Platform Street View Static API | National | IMPLEMENTED, DISABLED | **BLOCKED** | REMAIN BLOCKED |
| 80 | `google_maps_js_and_static` | Google Maps Platform (Maps JavaScript API hybrid basemap; Maps Static API images) under a Google 'Demo Key' | Client-side, all states | ACTIVE | **RESTRICTED** | KEEP ENABLED, CONDITIONS (replace demo key) |
| 81 | `maptiler_cloud` | MapTiler Cloud (hybrid style, static maps) with MapLibre GL JS from unpkg | Client-side, all states | ACTIVE | **APPROVED WITH CONDITIONS** | KEEP ENABLED, CONDITIONS |
| 82 | `openstreetmap_embed` | OpenStreetMap Foundation (www.openstreetmap.org embed iframe on the property page GIS card) | Client-side | ACTIVE | **UNKNOWN / UNVERIFIED** | KEEP ENABLED; record policy |
| 83 | `county_gis_orthoimagery` | County GIS orthoimagery services (generic) | n/a | NOT IMPLEMENTED | **LEGAL REVIEW REQUIRED** | DO NOT ADD |
| 84 | `scraperapi_proxy` | ScraperAPI (commercial proxy vendor) - a service in the collection path, not a data source | FL: Escambia, Columbia, Union (fallback only) | ACTIVE | **LEGAL REVIEW REQUIRED** | DECISION REQUIRED (candidate to disable) |

### 3.1 Reading the register

- **Platform operator vs. data owner.** RealAuction (realtaxdeed / realforeclose / RealTDM / sheriffsaleauctions), Grant Street Group (LienHub), Bid4Assets, Pioneer Technology Group, NewVision, Acclaim, ePropertyPlus and GovEase are platform operators; the clerk, tax collector, treasurer, land bank or sale authority is the data owner. A permission from one does not bind the other; the register names both.
- **Florida counties on one platform were not collapsed where the recorded regime differs**: Alachua and Volusia (EULA located) are separate from the other 44 RealAuction counties (no terms located; Miami-Dade and Brevard robots.txt disallow); Escambia, Columbia and Union (reached through the ScraperAPI proxy) are separate from the 15 directly-read HTML counties; Orange (scripted disclaimer acknowledgement) and Osceola (portal-internal JSON API) each stand alone.
- **Geometry.** No source row stores or displays a parcel polygon. Where a layer's polygon is requested (`harvesters/otc/adapters/arcgis.py` with `cfg.centroid`, `harvesters/enrichment/parcels.py polygon_centroid`, `harvesters/enrichment/geocode.py` FDOR / Santa Rosa), it is used to derive one centroid and discarded; the stored coordinate carries a method (`PARCEL_GIS` / `TAX_ROLL` / `LAND_BANK_GIS` / `OFFICIAL_ADDRESS` / `DETERMINISTIC_GEOCODE`) and a geometry kind (`POINT` / `PARCEL_CENTROID`) in `field_provenance`, which the UI renders through `coordinateProvenance()` and `imageryBasis()`; the imagery caption always carries `CONTEXT_NOTE` ("does not show parcel boundaries, ownership, current condition or title"). Section 5 covers this in full.

## 4. GovEase decision memo

### 4.1 What is on record

| Question | Finding | Evidence |
|---|---|---|
| Where does the block originate? | A project decision rule applied on 2026-09-14 during Texas vendor reconnaissance: with a blanket `robots.txt` `Disallow: /` and no Terms of Use found, the reviewer set `BLOCKED` "conservatively". | `harvesters/governance/registry.py` `_TX_GOVEASE` (`commercial_use_status`, `robots_status`, `terms_status`, `review_date`, `reviewer`); `docs/auction-source-policy.md` ("Mode E - Blanket robots.txt, no locatable Terms of Use"). |
| Is it legal, technical, internal-risk, or assumption? | **Technical signal + absence of terms, applied by an internal conservative rule.** No clause prohibiting the product's use has ever been located; no vendor communication exists; no counsel opinion exists. | Same records; `verification.py` `contract_status NOT_CONTACTED`, `license_notes "No Terms of Use located; robots.txt blanket Disallow: / treated conservatively as blocking"`. |
| Is the basis current? | Not re-verified since 2026-09-14. The reviewer document is outside the repository. This session's attempts to fetch `liveauctions.govease.com/robots.txt` and `www.govease.com/terms-of-use` failed at DNS resolution through the sandbox proxy (2026-10-12), so the claim could be neither confirmed nor refuted. | Session log 2026-10-12; `registry.py` `doc_refs=("claude/govease-source-onboarding-blocked.md",)`. |
| Published ToS / AUP / API / licensing / partner contact? | Web search (2026-10-12) found: GovEase help-centre articles stating that creating a bidder account requires agreeing to the "GovEase Terms & Conditions" (so terms exist behind account creation); county-specific auction-terms PDFs published by counties; `support@govease.com` printed in a county auction flyer; a "Talk with Sales" form on govease.com. **No public API, data feed, affiliate or licensing page was found.** None of these pages were fetched from this sandbox; the findings are search-result snippets and are recorded as such. | Web search results 2026-10-12 (not repository evidence). |
| Can official county auction links be displayed without copying? | Yes in principle - a link to a county's own GovEase auction page is a link, not a copy. Today the product does **not** do this: `govease.com` is on `ACQ_GATE_UNTRUSTED_HOSTS` (`public/app.js`) and the untrusted purchase-host lists, so even a county-published GovEase URL would be refused as an acquisition path. | `harvesters/sources/acquisition_gate.py` line ~71; `scripts/laft_purchase_paths.py` ~94; `public/app.js` ~558. |
| Do county auction lists independently authorize reuse? | Unknown. Denton, Parker, Wichita and Wise have not been reviewed as county-first sources; `docs/auction-source-policy.md` notes that no Mode C source has independent establishment. Tennessee counties using GovEase (Montgomery, Rutherford, Robertson, Lawrence, Hawkins, Lincoln) are noted in `docs/tennessee-survey.md` only. | `docs/auction-source-policy.md`; `docs/tennessee-survey.md`. |
| Approved API / feed / affiliate route? | None found. | Web search 2026-10-12. |

### 4.2 Recommendation per data category

| Category | Recommendation | Evidence / unresolved question | Safest next step |
|---|---|---|---|
| Direct links to the official GovEase county auction pages | **Allow as link-out once the county's own page (not a search result) publishes the URL**, i.e. move `govease.com` from "untrusted" to "link-only" in the acquisition gate. A link copies nothing and no robots.txt governs a hyperlink. | Unresolved: whether the product wants to send customers to a platform it cannot otherwise describe. | Owner decision; code change P-5 (no ingestion). |
| County name + sale date from an independent source (county page, notice) | **Allow** - this is Mode C metadata from the county, not from GovEase. | Needs a county-first source per county (none registered for the four TX counties). | County-first reconnaissance for Denton, Parker, Wichita, Wise (value-free capture). |
| Listing summaries / identifiers copied from GovEase | **Do not collect** until terms are read. | robots.txt (unverified currency); terms behind account creation; no API. | Human read of robots.txt and the public Terms; counsel if the terms prohibit. |
| Opening bids / structured fields | **Do not collect**; same basis. | Same. | Same. |
| Cached records (retention of listings) | **Do not** - nothing may be cached from a source with no established right. | Same. | Same. |
| Outcomes / winning bids / bidder info / history | **Do not**, and bidder identity is never stored for any source (code rule in `scripts/auction_outcomes.py`). | Same, plus privacy. | None. |
| Parcel geometry | **Not applicable** - GovEase publishes no parcel geometry; geometry would come from a CAD, under that CAD's terms. | - | None. |

### 4.3 Should the no-contact instruction be reconsidered?

The block rests on a 2026-09-14 observation that cannot be re-verified from the repository and a terms page nobody has read. The product has four Texas counties and six Tennessee counties behind it. The lowest-risk path to a decision is a human read of `robots.txt` and the public Terms (no account creation, no scripted access). If the Terms are only available after account creation, the only way to learn the rules is to ask. **Recommendation:** keep the no-contact instruction until the owner has read section 4.1, then decide whether to authorize a single written inquiry (template D in section 6). This audit sends nothing.

### 4.4 Written questions GovEase would need to answer (draft, not sent)

1. Does GovEase publish Terms of Use for unauthenticated visitors of liveauctions.govease.com, and where?
2. Does GovEase object to a research product linking customers to a county's GovEase auction page?
3. Does GovEase offer any data feed, API, export or partner programme for auction calendars, listings or results, and under what licence?
4. Does GovEase's robots.txt `Disallow: /` express a policy against automated reading of public auction listings, and does GovEase consider the county, not GovEase, the owner of the listing data?
5. Which party (GovEase or the county sale authority) grants permission to display listing summaries, opening bids and published results?

## 5. Parcel geometry and enrichment permissions

| Question | Finding |
|---|---|
| Which sources provide geometry? | FDOR / FGIO Florida Statewide Cadastral (FeatureServer), Santa Rosa ParcelsOpenData, Palm Coast / Flagler MapServer (attributes only), Colorado OIT Public Parcels, UGRC LIR (UT, inactive), WI SCO V12 (inert), EBR Tax Parcels (Socrata, `centroid=False`), the ArcGIS inventory layers for Eaton, Lenawee, York, Albany, Ramsey, Douglas and the DLBA (polygon only when `cfg.centroid` is set), Jim Wells CAD and the BIS-hosted CADs (inert / catalog), St. Louis parcels coordinates (inert). |
| Fetched, discarded, simplified or persisted? | **Fetched and discarded after one centroid is derived.** `harvesters/otc/adapters/arcgis.py` requests `returnGeometry` only when `cfg.centroid` is true and computes `_geometry_centroid`; `harvesters/enrichment/parcels.py` `polygon_centroid` marks the entry `derived`; `harvesters/enrichment/geocode.py` stores `PARCEL_CENTROID` points. No migration defines a geometry column; the untracked PostGIS column noted in earlier phase docs is not written by any current script. **No simplified geometry is stored anywhere** - this matters because the owner's inquiries asked specifically about "storage of simplified geometry": no such storage exists today, so a negative answer costs nothing. |
| Commercial display / retention permitted? | Only where the source licence says so: Douglas (CC BY-SA 4.0, attribution + share-alike), EBR (Public Domain), UGRC (CC BY 4.0). Colorado OIT prohibits resale (display accepted internally, paid tiers excluded). FDOR/FGIO, Santa Rosa, Palm Coast: **no licence recorded**; `geocode.py` sets `publication_status="APPROVED"` for FDOR with no citation - this is the one place a status in code is stronger than its evidence (backlog B-5). |
| Derived vs. source geometry; attribution; refresh | Centroids are derived values recorded with `"derived: centroid of the layer's own parcel geometry (WGS84)"` provenance; attribution text exists for NAIP, EBR, Douglas, UGRC, OIT (as code strings); a UI test that the attribution actually renders exists for none of them (B-4). Refresh is per run; `coordinates.should_replace()` never downgrades an authoritative point. |
| Who grants permission? | The data-owning agency (county GIS / assessor / state GIS office). A platform host (BIS Consultants, arcgis.com) grants nothing. |
| How does the app distinguish verified geometry from centroid / approximate / placeholder? | `coordinateProvenance()` (method + geometry kind), `COORD_GEOMETRY_LABELS`, `imageryBasis()` (`parcel` / `listed_point` / `approximate` / `none`), captions "approximate point", `data-imagery="naip_failed"`, the county-only minimap for rows without coordinates (never a dot), and `IMAGERY_CONTEXT_NOTE` on every image. No boundary is ever drawn; the placeholder behaviour is kept. |
| Per-property provenance? | `field_provenance.latitude.source` + `method` + `geometry` per row; shown on the Source truth card. |

**No change recommended to geometry behaviour.** Do not fabricate polygons, do not infer boundaries from centroids, keep the placeholder.

## 6. Outreach queue

### 6.1 Status of the six inquiries the owner reports having sent

The owner states that personalized inquiries were sent to the six organisations below. **This session could not inspect the correspondence**: the Gmail connector returned `Forbidden` to every search on 2026-10-12, and no copy, date or reply is recorded anywhere in the repository (searched `docs/`, `data/`, `claude/`-referenced paths and the git log). Each is therefore recorded as *outreach sent per owner; permission pending; no response proven*.

| Addressee | Covers (register rows) | Caution about the addressee | What to record once the mailbox is readable |
|---|---|---|---|
| Florida DOR, Property Tax Oversight | `fl_dor_statewide_nal`, `fl_statewide_cadastral_fgio` | FGIO hosts the cadastral service; FDOR PTO may refer the GIS question. | Date sent, reply date, the exact permitted operations, attribution text, refresh cadence. |
| Detroit Enterprise GIS | `mi_detroit_landbank_lots_and_programs` | The Detroit Land Bank Authority owns the inventory; a GIS reply may not bind the DLBA. | Same; plus whether DLBA consent is needed. |
| St. Louis Assessor, Records and Mapping | `mo_stl_parcels_coordinates`, partly `mo_stl_lra_inventory` | The LRA / SLDC owns the inventory list; the Assessor owns parcel/mapping data. | Same; plus LRA referral. |
| Fayette County PA GIS | `pa_fayette_repository` | The Tax Claim Bureau owns the repository list. | Same. |
| Oklahoma Office of Geographic Information | `ok_oklahoma_county_owned` | A **state** GIS agency; it cannot grant reuse of Oklahoma County's county-owned list. A separate request to Oklahoma County is needed regardless of the reply. | Same; treat any reply as covering state GIS data only. |
| RealAuction customer service (RealForeclose permitted use) | `fl_realauction_*`, `fl_realauction_closed_results`, `fl_laft_realtdm`, `tx_realauction` | Customer service is not a licensing function; the reply may need escalation. County EULAs (Alachua, Volusia) are the clerks', not RealAuction's. | Same; plus whether historical results and RealTDM are covered. |

### 6.2 Queue (nothing sent by this audit)

| Priority | Addressee | Purpose | Verified contact surface | Draft | Status |
|---|---|---|---|---|---|
| 1 | Grant Street Group / LienHub | Permission for automated reading of county-held certificate lists; cause of the 403 since 2026-10-01 | lienhub.com/doc/support; support.grantstreet.com (listed in `docs/provider-authorization-requests.md`; not verified as licensing contacts) | Template exists in `docs/provider-authorization-requests.md` (drafted 2026-09-15) | NOT SENT |
| 1 | RealAuction (follow-up / escalation) | Permitted use of RealForeclose / RealTDM / sheriffsaleauctions, historical results | sales@realauction.com, customerservice@realauction.com (same doc; unverified) | Template exists (same doc) | Initial inquiry sent by owner; pending |
| 2 | Morgan CO Treasurer; Eaton MI Treasurer; Lenawee MI Treasurer; York SC; Green WI Treasurer; Albany WY | Written permission to display published sale / certificate lists; attribution wording | Not recorded in the repository - use each county's official contact page | Template C below | NOT SENT |
| 2 | Oklahoma County (Treasurer / Commissioners) | Reuse of the county-owned property list | Not recorded | Template C | NOT SENT (state OGI inquiry does not cover it) |
| 3 | Georgetown SC FLC; Horry SC FLC; Oceana MI Land Bank; Ramsey MN; Shelby County Land Bank; DLBA (after Enterprise GIS replies) | Reuse of AVAILABLE lists currently admin-only | Georgetown / Spartanburg copyright pages recorded in `data/available_publication_reviews.csv`; others not recorded | Template C | NOT SENT |
| 3 | Harris County Tax Office | The 12-question package | Not recorded | `claude/harris-hctax-rights-resolution-package.md` (outside repo) | Drafted, NOT SENT |
| 3 | Linebarger Goggan Blair & Sampson | Scope of the legal-disclosures clause; permission | Not recorded | Template E below | NOT SENT (counsel first) |
| 4 | GovEase | Section 4.4 questions | support@govease.com (seen in a county flyer; unverified); govease.com sales form | Template D below | NO-CONTACT instruction in force |
| 4 | Escambia, Columbia, Union clerks | Direct provision of the LAFT list or allow-listing of the runner, to retire the proxy | Clerk sites (recorded canonical_url) | Template C variant | NOT SENT |

### 6.3 Draft templates (for the owner's review; not sent)

**Template C - county short permission request** (one e-mail per county; fill the bracketed fields from the registry row)

> Subject: Permission to display [County]'s published [tax sale / county-held certificate / forfeited land] list
>
> [Office], TAXACQ is a subscription research tool for tax-sale investors. We read the list your office publishes at [canonical_url] and show its published fields (identifier, amount as you label it, sale date, status) to our subscribers, always with a link to your page and never with inferred results. We would like to confirm in writing that your office permits this use, and to learn (1) whether you require a particular attribution wording, (2) how often the list is refreshed, and (3) whether any field should not be redisplayed. If your office does not permit redisplay, please tell us and we will limit ourselves to a link.

**Template D - GovEase (do not send without lifting the no-contact instruction)** - the five questions of section 4.4, prefaced by one sentence describing the product and stating that no automated reading of GovEase pages takes place today.

**Template E - Linebarger** - after counsel: cite the legal-disclosures sentence, describe exactly which fields from taxsales.lgbs.com are redisplayed and how (manual reads, vendor-listing label, link back), and ask whether written permission is required and available.

**Follow-up to the six sent inquiries** (after 30 days without reply): one short message restating the three operations actually needed - display of published fields, a link back, and storage of a derived point only (no geometry) - and asking for the office that can answer if the addressee cannot.

## 7. Legal-review queue (for counsel; ordered by rows unlocked)

| # | Document / question | Sources unlocked | Evidence on file |
|---|---|---|---|
| L-1 | Alachua and Volusia RealAuction county EULAs: do they bind an anonymous reader; do they prohibit automated reading, redisplay, retention of results? | fl_realauction_* (46), fl_realauction_closed_results, fl_laft_realtdm (11), tx_realauction (24) | `data/phase36_terms_review.csv`; `docs/realauction-rights-audit.md` |
| L-2 | LienHub User Agreement robots/spider prohibition; the 403 since 2026-10-01 | fl_lienhub_certificates (32) | registry `_FL_LIENHUB`; registry CSV restrictions |
| L-3 | Linebarger legal-disclosures clause scope | tx_lgbs (8) | `docs/lgbs-rights-audit.md` |
| L-4 | Access-step bypasses: Orange scripted acknowledgement; Volusia disclaimer bypass; Osceola portal-internal API; ScraperAPI proxy for Escambia/Columbia/Union; `bypassPage=1` on RealAuction | fl_laft_orange, fl_laft_pdfs (Volusia), fl_laft_osceola, fl_laft_html_proxied, fl_realauction_* | `docs/legal/pre-sale-blockers.md` item 4 |
| L-5 | Colorado OIT "resale forbidden": does a subscription product count as resale? Douglas CC BY-SA share-alike effect on derived data | co_oit_public_parcels, co_douglas_open_data | `harvesters/enrichment/sources.py`; registry CSV |
| L-6 | Google Demo Key production use; MapTiler free plan for a paid product; OSM tile usage policy | google_maps_js_and_static, maptiler_cloud, openstreetmap_embed | CLAUDE.md Phase 56-61; `public/_headers` |
| L-7 | Miami-Dade PA "all rights reserved" disclaimer; Michigan county click-through licence (only if ever wanted) | fl_pa_miami_dade, mi_county_parcels_eaton_clickthrough | `data/phase36_terms_review.csv`; catalog |
| L-8 | FDOR NAL and FGIO cadastral service terms (after the FDOR reply) | fl_dor_statewide_nal, fl_statewide_cadastral_fgio | registry `_FL_DOR`; `geocode.py` |

## 8. Permission evidence ledger

| Source | Evidence (what, where) | Date | Permitted operation | Limitations | Confidence |
|---|---|---|---|---|---|
| Douglas CO (2 datasets) | CC BY-SA 4.0 stated on the dataset items; Open Data Guidelines | 2026-09-30 (read in the five-state runs) | Harvest, store, display, adapt | Attribute "Douglas County, Colorado"; share-alike on adaptations | High (licence text recorded) |
| East Baton Rouge adjudicated list | Socrata metadata `licenseId PUBLIC_DOMAIN`; harvest refuses if it changes | 2026-09-30 | Harvest, store, display | Owner's dated-list policy (never "available now") | High |
| EBR Tax Parcels / Tax Roll | Public Domain, read live in runs 36921157970 / 36940907360 | 2026-10-01 | Attribute enrichment, point coordinates | Attribution "EBR Parish Assessor" | High |
| UGRC LIR (UT) | CC BY 4.0 | 2026-09-30 | If used: enrichment | Credit UGRC, link licence, note changes; state inactive | High |
| USDA NAIP via USGS | Public domain per `harvesters/imagery` | 2026-10-05 | Store + live display | Attribution string; CONTEXT_NOTE | Medium (registry assertion; counsel read pending) |
| MapTiler | Free-plan key, origin-restricted; attribution control on | 2026-09-18 | Client display | 5,000 sessions/month; attribution | Medium |
| Colorado OIT Public Parcels | Licence string: resale forbidden; owner approved display 2026-09-30 | 2026-09-30 | Display only | No resale / paid tier / export | High (restriction), Low (display right) |
| Morgan CO certs; Eaton; Lenawee; York; Green; Albany | Registry restrictions: "No explicit reuse licence ... approved for publication by the owner on 2026-09-30" | 2026-09-30 | Internal acceptance only | Not a grant from the county | Low |
| Linebarger (tx_lgbs) | Legal-disclosures prohibition on reproduction/redistribution without prior permission (verbatim in `docs/lgbs-rights-audit.md`) | 2026-09-15 | None established (production practice continues) | Scope unresolved | High (restriction exists) |
| PBFCM | disclosure.html anti-reproduction clause | 2026-09-14 | None | Blocked | High |
| MVBA | Non-commercial-use-only clause | 2026-09-14 | None | Blocked | High |
| CTSA | Paywall + anti-competitive clause | 2026-09-14 | None | Blocked | High |
| GovEase | robots.txt `Disallow: /` (not re-verifiable from repo); no terms located | 2026-09-14 | None | Conservative block | Low (currency unknown) |
| LienHub | User Agreement prohibits robots/spiders; terms URL returned 403 on 2026-09-15; reads 403 since 2026-10-01 | 2026-09-15 / 2026-10-01 | None established (grandfathered rows shown) | Automated access prohibited by the agreement as recorded | High (restriction), Low (any right) |
| RealAuction Alachua / Volusia | County EULA located, not read by counsel | 2026-09-15 | None established (grandfathered) | - | Medium (existence), none (content) |
| Pinellas PA | Terms prohibit "electronic data harvesting" | 2026-09-15 | Link only | No harvesting | High |
| Broward PA | "for tax roll purposes only" | 2026-09-15 | Link only | - | High |
| Duval PA | Values "should not be used for any financial or business calculations" | 2026-09-15 | Link only | - | High |
| Miami-Dade PA | "all rights not expressly granted herein are reserved" | 2026-09-15 | Link only | - | High |
| WV Auditor | Terms grant no reuse right | 2026-09-30 | None | - | Medium |
| Dane County WI | "Copyright County of Dane" on the page | 2026-09-30 | Link only | - | Medium |
| EBR ArcGIS parcels | "Access Constraints: copyright" | 2026-10-01 | None | Superseded by Socrata Public Domain datasets | High |
| Georgetown / Spartanburg SC | County copyright pages: no grant, no prohibition | 2026-10-02 | None beyond link | - | Medium |
| DLBA Vacant Land Policy | Verified process document (evidence row) - not a data licence | 2026-10-11 | Describes acquisition; grants no data right | - | High (as process evidence) |
| Google Demo Key | Google docs: testing / prototyping only | 2026-09-18 | Client display in testing | Not production | High |
| WI SCO V12 | "free for public consumption" / "free of charge" | 2026-09-30 | None (cost statement, not licence) | - | Medium |
| Owner's six inquiries | Owner's statement only; mailbox not readable | 2026-10-12 | None yet | Pending | Not verifiable |

## 9. Audit limitations

1. **Correspondence not inspectable.** The Gmail connector returned `Forbidden` to every query on 2026-10-12. No sent message, date or reply for the six inquiries was verified. The repository holds no copy. Nothing in this report claims an e-mail was delivered, read or answered.
2. **External terms pages not fetched.** The sandbox's egress policy blocks county, vendor and GovEase hosts (DNS failure for govease; proxy 403 for others). Every terms finding comes from the repository's own records (Phase 36 review 2026-09-15, rights audits, registry text, evidence CSVs) or, for GovEase, from web-search snippets, which are labelled as such.
3. **Reviewer documents outside the repository.** `claude/govease-source-onboarding-blocked.md`, `claude/harris-hctax-rights-resolution-package.md` and the Phase 8/9 reconnaissance notes are claude.ai project documents; their contents were not available to this session.
4. **Currency.** Most terms findings date from 2026-09-14/15; none carries a re-check date. Terms can change.
5. **Two registries disagree in places.** `harvesters/governance/registry.py` marks `tx_lgbs`, `tx_realauction` and the Florida sources `APPROVED` (production practice) while their own notes say the approval basis "requires legal review"; this report classifies by the evidence, not by the enum value. `harvesters/enrichment/geocode.py` marks the FDOR cadastral source `APPROVED` with no licence cited.
6. **No production database or workflow was touched.** Row counts in this report come from repository files, not from live queries.
7. **Internal approvals are recorded only as free text** in the registry's `restrictions` column; there is no dated, signed decision record.

## 10. Prioritized remediation plan

| Tier | Action | Sources |
|---|---|---|
| **Enable safely now** | Nothing new. Every source with a recorded licence is already active. |  |
| **Links-only (safe immediately, no permission needed)** | Add link-out for county pages that today have no source: the 15 FL LAFT-not-found counties, the 19 TX struck-off candidates, the property appraisers, Harris County, Dane WI, the SC FLC catalog. Links to published URLs only; never a constructed URL. | 14 register rows with decision LINKS ONLY |
| **Short permission request unlocks** | Morgan CO, Eaton MI, Lenawee MI, York SC, Green WI, Albany WY (already running, convert acceptance to grant); Oklahoma County; Georgetown, Horry, Oceana, Ramsey, Shelby, DLBA (admin-only today); Escambia/Columbia/Union (retire the proxy); WI SCO V12; Santa Rosa / Palm Coast (record the licence). | ~17 rows |
| **Counsel / formal licence** | RealAuction EULAs, LienHub, Linebarger, access-step bypasses, Colorado resale, Google demo key, FDOR (after reply). | L-1 to L-8 |
| **Remain blocked** | PBFCM, MVBA, CTSA, GovEase (pending the memo), Street View stills, WV Auditor, EBR ArcGIS parcels, Dane (copy). |  |
| **Low value / high maintenance - do not add** | Press-association notices, clerk court records, district-clerk suits, county orthoimagery, TX Phase-36 CAD feeds, SC assignment list (Spartanburg). |  |
| **Duplicates to consolidate** | EBR ArcGIS parcels (use Socrata); Google static + MapTiler static (pick one for the card rung before paid launch); `fl_dor_statewide_nal` vs `fl_statewide_cadastral_fgio` (one FDOR answer should cover both). |  |

**Population principle preserved:** publication (`publication_state`), the Detroit 50 % subset, the staged acquisition gate and the Available dated-list rule remain the controls that keep large low-value populations (Michigan 30k, Louisiana 10k) from swamping results. Data-quality thresholds (identity, coordinates, path coverage in `market_metrics`) stay separate from permission status; this audit does not merge them.

## 11. Implementation backlog (proposed; nothing implemented)

| ID | Item | Acceptance criteria |
|---|---|---|
| B-1 | **Per-operation permission registry**: `data/source_permissions.csv` with one row per (source_id, operation) for operations `link`, `ingest`, `persist`, `display_customer`, `display_paid`, `export`, `geometry`, `historical_results`; columns status (the eight statuses of section 2), evidence_ref, granted_by, granted_on, review_due, expires_on. Loader in `harvesters/governance/permissions.py`. | Validator rejects an APPROVED* row without evidence_ref + granted_on; every registry source_id has a row for `link` and `ingest`; `scripts/build_source_inventory.py` reads it. |
| B-2 | **Fail-closed consumers**: `otc.gate`, `source_publication.collectable()`, `harvest_expansion.py`, `sync_state_inventory.py`, the enrichment factory and the PowerShell FL pipeline (via a generated allow-list file) consult `ingest`/`persist` permission. | A source with `ingest` ≠ APPROVED* (incl. missing row, UNKNOWN, expired) makes zero requests on scheduled AND manual dispatch; test asserts per workflow job by parsing `harvest-and-sync.yml` steps against the registry. |
| B-3 | **Expiry**: `review_due` default 180 days from `granted_on`; past due → `ingest` fails closed, `link` stays allowed; CI test lists due reviews. | Test with a fixture row past due; `scripts/permission_review_queue.py --check` fails CI when any active source is past due. |
| B-4 | **Attribution rendering**: UI test that Douglas (CC BY-SA), EBR Assessor, NAIP, MapTiler attribution strings appear wherever those rows / images are shown; attribution text sourced from the permission row. | Playwright checks per fixture row; Python test pins strings equal. |
| B-5 | **Evidence-backed APPROVED in code**: `geocode.py` / `enrichment/sources.py` `publication_status="APPROVED"` must cite `licence_evidence` (URL or run id); FDOR cadastral → UNKNOWN / UNVERIFIED until the FDOR reply. | Test fails on APPROVED without evidence; FDOR enrichment keeps running (attributes + centroid) because UNKNOWN does not block an already-grandfathered operation unless B-2 policy says so - owner decision documented. |
| B-6 | **ScraperAPI decision flag**: `LAFT_PROXY_FALLBACK` repository variable, default off, read by `harvest_laft_html.py`; the three counties read INCOMPLETE/SOURCE_UNAVAILABLE instead of via proxy when off. | Owner sets the variable; test covers both paths; no production change until the owner decides. |
| B-7 | **Link-only never copies**: adapters refuse to write any field for a source whose `ingest` permission is not APPROVED* even when `link` is; GovEase/county URLs classified `link_only_host` rather than `untrusted`. | Test: a link-only source yields zero `properties` writes and one acquisition link. |
| B-8 | **Terms capture scope**: `job=evidence`, `evidence_scope=terms` fetches and hashes the terms / robots.txt of every active host (value-free), writing `data/current_state/terms-capture.json` with dates. | Each active source has a terms hash + date; drift fails `--check`. |
| B-9 | **Outreach ledger**: `data/outreach_log.csv` (addressee, source_ids, sent_on, channel, reply_on, outcome, evidence_ref) maintained by the owner; register and inventory read it. | The six sent inquiries recorded with dates; report builder prints "pending N days". |
| B-10 | **GovEase relabel**: registry `legal_status` → `LEGAL_REVIEW_REQUIRED` with `review_due`, keeping the ingestion block identical (gate treats LRR as not approved). | No behaviour change; tests `test_three_ledgers` / `test_source_governance` still pass; docs updated. |

## 12. Proposed code changes (separate; awaiting approval)

| ID | Change | Alters collection? |
|---|---|---|
| P-1 | B-1 registry file + loader + validator + tests (additive). | No |
| P-2 | B-2 consumers read the registry; B-7 link-only semantics. | **Yes** - any source without an APPROVED* `ingest` row stops being requested; the migration plan would seed rows from today's behaviour so nothing changes on day one, then expire. |
| P-3 | B-5: downgrade `geocode.py` FDOR flag; require evidence. | No (with the documented grandfathering) |
| P-4 | B-6: ScraperAPI off-switch. | **Yes**, when the owner sets it. |
| P-5 | B-10 relabel + acquisition-gate `link_only_host` list. | No ingestion change; adds link-out. |

None of these is implemented in this audit. P-2 and P-4 change data collection and require explicit approval.
