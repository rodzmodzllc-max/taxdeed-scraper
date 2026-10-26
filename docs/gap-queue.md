# Gap-closure work queue

Generated from public/acquisition-evidence.json, data/current_state/state-coverage.json, data/acquisition_candidate_pages.csv and the registry. Counts only.

- Acquisition-path units: 87 total, 58 unresolved (NEEDS_REVIEW 6, NOT_FOUND 46, UNAVAILABLE 6, VERIFIED 29).
- State x ledger units: 39 total (APPROVAL_UNRESOLVED 7, CURRENT 6, OFFERED_SOURCE_NOT_IMPLEMENTED 1, OFFERED_VERIFIED_EMPTY 1, RULES_NOT_VERIFIED 19, SOURCE_FAILED_OR_STALE 4, SOURCE_IMPLEMENTED_NEVER_READ 1).
- Queue: 91 entries - by category A 2, B 4, C 27, D 7, E 10, F 41; completable now from the repository: 2.

## A. implementable now from repository data or an accessible official source (2)

| Unit | Ledger | Status | Source reachable | Approved | Rule verified | Process verified | Next action |
|---|---|---|---|---|---|---|---|
| LA * | AVAILABLE | SOURCE_FAILED_OR_STALE | yes | yes | no | yes | Deploy the keyset-read fix (PR #132 stack: sync_state_inventory.stored_provenance) - the state's sync has failed on HTTP 500 every run since; no code left to write |
| WI * | AUCTIONS | OFFERED_VERIFIED_EMPTY | yes | yes | no | no | Nothing to do: the source was read and lists nothing |

## B. needs a parser / extractor / adapter / enrichment implementation (4)

| Unit | Ledger | Status | Source reachable | Approved | Rule verified | Process verified | Next action |
|---|---|---|---|---|---|---|---|
| FL Indian River (fl_laft_html) | AVAILABLE | NEEDS_REVIEW | yes | yes | n/a | no | Implement a browser-rendered capture for the county's script-rendered process page, then record the evidence row |
| FL St. Lucie (fl_laft_stlucie) | AVAILABLE | NEEDS_REVIEW | yes | yes | n/a | no | Implement a browser-rendered capture for the county's script-rendered process page, then record the evidence row |
| TN Shelby (tn_shelby_landbank) | AVAILABLE | NEEDS_REVIEW | yes | no | n/a | no | Implement OCR extraction of the scanned process packet, then record the evidence row |
| WY * | LIENS_CERTIFICATES | OFFERED_SOURCE_NOT_IMPLEMENTED | yes | no | no | no | Implement the adapter for the known source (registry candidate), gated and fixture-validated first |

## C. needs official evidence through the approved capture mechanism (job=evidence) (27)

| Unit | Ledger | Status | Source reachable | Approved | Rule verified | Process verified | Next action |
|---|---|---|---|---|---|---|---|
| FL Bay (fl_laft_pioneer) | AVAILABLE | NOT_FOUND | yes | yes | n/a | no | Capture the identified candidate page(s) with job=evidence, read the digest, record a verified evidence row or an outcome |
| FL Hillsborough (fl_laft_hillsborough) | AVAILABLE | NEEDS_REVIEW | yes | yes | n/a | no | Capture the identified official page(s) with job=evidence (acquisition_candidates scope), read the digest, record a verified evidence row |
| FL Miami-Dade (fl_laft_realtdm) | AVAILABLE | NOT_FOUND | yes | yes | n/a | no | Capture the identified candidate page(s) with job=evidence, read the digest, record a verified evidence row or an outcome |
| FL Polk (fl_laft_realtdm) | AVAILABLE | NOT_FOUND | yes | yes | n/a | no | Capture the identified candidate page(s) with job=evidence, read the digest, record a verified evidence row or an outcome |
| FL Putnam (fl_laft_html) | AVAILABLE | NOT_FOUND | yes | yes | n/a | no | Capture the identified candidate page(s) with job=evidence, read the digest, record a verified evidence row or an outcome |
| MI Wayne (mi_detroit_landbank_programs) | AVAILABLE | NEEDS_REVIEW | yes | no | n/a | no | Capture the identified official page(s) with job=evidence (acquisition_candidates scope), read the digest, record a verified evidence row |
| MI Wayne (mi_wayne_county_landbank) | AVAILABLE | NEEDS_REVIEW | yes | no | n/a | no | Capture the identified official page(s) with job=evidence (acquisition_candidates scope), read the digest, record a verified evidence row |
| CO * | AUCTIONS | SOURCE_IMPLEMENTED_NEVER_READ | yes | yes | no | no | The next scheduled read (or job=evidence) records the first read; nothing to change until it runs |
| CO * | AVAILABLE | RULES_NOT_VERIFIED | not from the sandbox (statute hosts are DNS-blocked); unverified from the GitHub runner | no | no | no | Read the state's enabling statute / sale-authority page through the approved capture job, record a VERIFIED LAW rule and the ledger's eligibility |
| LA * | AUCTIONS | RULES_NOT_VERIFIED | not from the sandbox (statute hosts are DNS-blocked); unverified from the GitHub runner | no | no | no | Read the state's enabling statute / sale-authority page through the approved capture job, record a VERIFIED LAW rule and the ledger's eligibility |
| LA * | LIENS_CERTIFICATES | RULES_NOT_VERIFIED | not from the sandbox (statute hosts are DNS-blocked); unverified from the GitHub runner | no | no | no | Read the state's enabling statute / sale-authority page through the approved capture job, record a VERIFIED LAW rule and the ledger's eligibility |
| MI * | LIENS_CERTIFICATES | RULES_NOT_VERIFIED | not from the sandbox (statute hosts are DNS-blocked); unverified from the GitHub runner | no | no | no | Read the state's enabling statute / sale-authority page through the approved capture job, record a VERIFIED LAW rule and the ledger's eligibility |
| MN * | AUCTIONS | RULES_NOT_VERIFIED | not from the sandbox (statute hosts are DNS-blocked); unverified from the GitHub runner | no | no | no | Read the state's enabling statute / sale-authority page through the approved capture job, record a VERIFIED LAW rule and the ledger's eligibility |
| MN * | LIENS_CERTIFICATES | RULES_NOT_VERIFIED | not from the sandbox (statute hosts are DNS-blocked); unverified from the GitHub runner | no | no | no | Read the state's enabling statute / sale-authority page through the approved capture job, record a VERIFIED LAW rule and the ledger's eligibility |
| MO * | AUCTIONS | RULES_NOT_VERIFIED | not from the sandbox (statute hosts are DNS-blocked); unverified from the GitHub runner | no | no | no | Read the state's enabling statute / sale-authority page through the approved capture job, record a VERIFIED LAW rule and the ledger's eligibility |
| MO * | LIENS_CERTIFICATES | RULES_NOT_VERIFIED | not from the sandbox (statute hosts are DNS-blocked); unverified from the GitHub runner | no | no | no | Read the state's enabling statute / sale-authority page through the approved capture job, record a VERIFIED LAW rule and the ledger's eligibility |
| OK * | AUCTIONS | RULES_NOT_VERIFIED | not from the sandbox (statute hosts are DNS-blocked); unverified from the GitHub runner | no | no | no | Read the state's enabling statute / sale-authority page through the approved capture job, record a VERIFIED LAW rule and the ledger's eligibility |
| OK * | LIENS_CERTIFICATES | RULES_NOT_VERIFIED | not from the sandbox (statute hosts are DNS-blocked); unverified from the GitHub runner | no | no | no | Read the state's enabling statute / sale-authority page through the approved capture job, record a VERIFIED LAW rule and the ledger's eligibility |
| PA * | AUCTIONS | RULES_NOT_VERIFIED | not from the sandbox (statute hosts are DNS-blocked); unverified from the GitHub runner | no | no | no | Read the state's enabling statute / sale-authority page through the approved capture job, record a VERIFIED LAW rule and the ledger's eligibility |
| PA * | LIENS_CERTIFICATES | RULES_NOT_VERIFIED | not from the sandbox (statute hosts are DNS-blocked); unverified from the GitHub runner | no | no | no | Read the state's enabling statute / sale-authority page through the approved capture job, record a VERIFIED LAW rule and the ledger's eligibility |
| SC * | LIENS_CERTIFICATES | RULES_NOT_VERIFIED | not from the sandbox (statute hosts are DNS-blocked); unverified from the GitHub runner | no | no | no | Read the state's enabling statute / sale-authority page through the approved capture job, record a VERIFIED LAW rule and the ledger's eligibility |
| TN * | AUCTIONS | RULES_NOT_VERIFIED | not from the sandbox (statute hosts are DNS-blocked); unverified from the GitHub runner | no | no | no | Read the state's enabling statute / sale-authority page through the approved capture job, record a VERIFIED LAW rule and the ledger's eligibility |
| TN * | LIENS_CERTIFICATES | RULES_NOT_VERIFIED | not from the sandbox (statute hosts are DNS-blocked); unverified from the GitHub runner | no | no | no | Read the state's enabling statute / sale-authority page through the approved capture job, record a VERIFIED LAW rule and the ledger's eligibility |
| TX * | LIENS_CERTIFICATES | RULES_NOT_VERIFIED | not from the sandbox (statute hosts are DNS-blocked); unverified from the GitHub runner | no | no | no | Read the state's enabling statute / sale-authority page through the approved capture job, record a VERIFIED LAW rule and the ledger's eligibility |
| WI * | AVAILABLE | RULES_NOT_VERIFIED | not from the sandbox (statute hosts are DNS-blocked); unverified from the GitHub runner | no | no | no | Read the state's enabling statute / sale-authority page through the approved capture job, record a VERIFIED LAW rule and the ledger's eligibility |
| WI * | LIENS_CERTIFICATES | RULES_NOT_VERIFIED | not from the sandbox (statute hosts are DNS-blocked); unverified from the GitHub runner | no | no | no | Read the state's enabling statute / sale-authority page through the approved capture job, record a VERIFIED LAW rule and the ledger's eligibility |
| WY * | AVAILABLE | RULES_NOT_VERIFIED | not from the sandbox (statute hosts are DNS-blocked); unverified from the GitHub runner | no | no | no | Read the state's enabling statute / sale-authority page through the approved capture job, record a VERIFIED LAW rule and the ledger's eligibility |

## D. blocked by source access or a technical restriction (7)

| Unit | Ledger | Status | Source reachable | Approved | Rule verified | Process verified | Next action |
|---|---|---|---|---|---|---|---|
| FL Escambia (fl_laft_html) | AVAILABLE | UNAVAILABLE | no | yes | n/a | no | The county's official pages answer HTTP 403 to the GitHub runner; a records request or an allow-listed capture host is the only way forward |
| FL Hendry (fl_laft_pdfs) | AVAILABLE | UNAVAILABLE | no | yes | n/a | no | The county's official pages answer HTTP 403 to the GitHub runner; a records request or an allow-listed capture host is the only way forward |
| FL Lee (fl_laft_realtdm) | AVAILABLE | UNAVAILABLE | no | yes | n/a | no | The county's official pages answer HTTP 403 to the GitHub runner; a records request or an allow-listed capture host is the only way forward |
| FL Osceola (fl_laft_osceola) | AVAILABLE | UNAVAILABLE | no | yes | n/a | no | The county's official pages answer HTTP 403 to the GitHub runner; a records request or an allow-listed capture host is the only way forward |
| FL Palm Beach (fl_laft_pioneer) | AVAILABLE | UNAVAILABLE | no | yes | n/a | no | The county's official pages answer HTTP 403 to the GitHub runner; a records request or an allow-listed capture host is the only way forward |
| FL Sarasota (fl_laft_realtdm) | AVAILABLE | UNAVAILABLE | no | yes | n/a | no | The county's official pages answer HTTP 403 to the GitHub runner; a records request or an allow-listed capture host is the only way forward |
| FL * | LIENS_CERTIFICATES | SOURCE_FAILED_OR_STALE | no | yes | yes | no | LienHub answers HTTP 403 to the GitHub runner since 2026-10-01; nothing to change in code until the source is reachable |

## E. blocked by source-use permission or an owner decision (10)

| Unit | Ledger | Status | Source reachable | Approved | Rule verified | Process verified | Next action |
|---|---|---|---|---|---|---|---|
| TX Harris (tx_hctax) | AVAILABLE | NOT_FOUND | yes | no | n/a | no | Owner / legal decision on the source: registry governance LEGAL_REVIEW_REQUIRED: hctax.net terms not cleared for redistribution |
| MI * | AVAILABLE | APPROVAL_UNRESOLVED | yes | no | no | yes | Owner publication review of the source (admin publication panel): approve, restrict or block |
| MN * | AVAILABLE | APPROVAL_UNRESOLVED | yes | no | no | yes | Owner publication review of the source (admin publication panel): approve, restrict or block |
| MO * | AVAILABLE | APPROVAL_UNRESOLVED | yes | no | no | yes | Owner publication review of the source (admin publication panel): approve, restrict or block |
| OK * | AVAILABLE | APPROVAL_UNRESOLVED | yes | no | no | yes | Owner publication review of the source (admin publication panel): approve, restrict or block |
| PA * | AVAILABLE | APPROVAL_UNRESOLVED | yes | no | no | yes | Owner publication review of the source (admin publication panel): approve, restrict or block |
| SC * | AVAILABLE | APPROVAL_UNRESOLVED | yes | no | no | yes | Owner publication review of the source (admin publication panel): approve, restrict or block |
| TN * | AVAILABLE | APPROVAL_UNRESOLVED | yes | no | no | no | Owner publication review of the source (admin publication panel): approve, restrict or block |
| TX * | AUCTIONS | SOURCE_FAILED_OR_STALE | yes | yes | no | yes | Manual-only source by owner decision (job=texas); a read happens only when the owner dispatches it |
| TX * | AVAILABLE | SOURCE_FAILED_OR_STALE | yes | yes | no | yes | Manual-only source by owner decision (job=texas); a read happens only when the owner dispatches it |

## F. the jurisdiction's process or product cannot yet be established authoritatively (41)

| Unit | Ledger | Status | Source reachable | Approved | Rule verified | Process verified | Next action |
|---|---|---|---|---|---|---|---|
| FL Bradford (fl_laft_pdfs) | AVAILABLE | NOT_FOUND | unknown | yes | n/a | no | No official acquisition page identified; identify a candidate page first (add it to data/acquisition_candidate_pages.csv), then capture it |
| FL Columbia (fl_laft_html) | AVAILABLE | NOT_FOUND | unknown | yes | n/a | no | No official acquisition page identified; identify a candidate page first (add it to data/acquisition_candidate_pages.csv), then capture it |
| FL Flagler (fl_laft_realtdm) | AVAILABLE | NOT_FOUND | unknown | yes | n/a | no | No official acquisition page identified; identify a candidate page first (add it to data/acquisition_candidate_pages.csv), then capture it |
| FL Gadsden (fl_laft_html) | AVAILABLE | NOT_FOUND | unknown | yes | n/a | no | No official acquisition page identified; identify a candidate page first (add it to data/acquisition_candidate_pages.csv), then capture it |
| FL Glades (fl_laft_pdfs) | AVAILABLE | NOT_FOUND | unknown | yes | n/a | no | No official acquisition page identified; identify a candidate page first (add it to data/acquisition_candidate_pages.csv), then capture it |
| FL Gulf (fl_laft_html) | AVAILABLE | NOT_FOUND | unknown | yes | n/a | no | No official acquisition page identified; identify a candidate page first (add it to data/acquisition_candidate_pages.csv), then capture it |
| FL Hamilton (fl_laft_html) | AVAILABLE | NOT_FOUND | unknown | yes | n/a | no | No official acquisition page identified; identify a candidate page first (add it to data/acquisition_candidate_pages.csv), then capture it |
| FL Hardee (fl_laft_html) | AVAILABLE | NOT_FOUND | unknown | yes | n/a | no | No official acquisition page identified; identify a candidate page first (add it to data/acquisition_candidate_pages.csv), then capture it |
| FL Holmes (fl_laft_html) | AVAILABLE | NOT_FOUND | unknown | yes | n/a | no | No official acquisition page identified; identify a candidate page first (add it to data/acquisition_candidate_pages.csv), then capture it |
| FL Lafayette (fl_laft_html) | AVAILABLE | NOT_FOUND | unknown | yes | n/a | no | No official acquisition page identified; identify a candidate page first (add it to data/acquisition_candidate_pages.csv), then capture it |
| FL Manatee (fl_laft_html) | AVAILABLE | NOT_FOUND | unknown | yes | n/a | no | No official acquisition page identified; identify a candidate page first (add it to data/acquisition_candidate_pages.csv), then capture it |
| FL Martin (fl_laft_pioneer) | AVAILABLE | NOT_FOUND | unknown | yes | n/a | no | No official acquisition page identified; identify a candidate page first (add it to data/acquisition_candidate_pages.csv), then capture it |
| FL Okeechobee (fl_laft_pioneer) | AVAILABLE | NOT_FOUND | unknown | yes | n/a | no | No official acquisition page identified; identify a candidate page first (add it to data/acquisition_candidate_pages.csv), then capture it |
| FL Pinellas (fl_laft_realtdm) | AVAILABLE | NOT_FOUND | unknown | yes | n/a | no | No official acquisition page identified; identify a candidate page first (add it to data/acquisition_candidate_pages.csv), then capture it |
| FL Santa Rosa (fl_laft_realtdm) | AVAILABLE | NOT_FOUND | unknown | yes | n/a | no | No official acquisition page identified; identify a candidate page first (add it to data/acquisition_candidate_pages.csv), then capture it |
| FL Seminole (fl_laft_realtdm) | AVAILABLE | NOT_FOUND | unknown | yes | n/a | no | No official acquisition page identified; identify a candidate page first (add it to data/acquisition_candidate_pages.csv), then capture it |
| FL St. Johns (fl_laft_pioneer) | AVAILABLE | NOT_FOUND | unknown | yes | n/a | no | No official acquisition page identified; identify a candidate page first (add it to data/acquisition_candidate_pages.csv), then capture it |
| FL Union (fl_laft_html) | AVAILABLE | NOT_FOUND | unknown | yes | n/a | no | No official acquisition page identified; identify a candidate page first (add it to data/acquisition_candidate_pages.csv), then capture it |
| FL Walton (fl_laft_pioneer) | AVAILABLE | NOT_FOUND | unknown | yes | n/a | no | No official acquisition page identified; identify a candidate page first (add it to data/acquisition_candidate_pages.csv), then capture it |
| FL Washington (fl_laft_realtdm) | AVAILABLE | NOT_FOUND | unknown | yes | n/a | no | No official acquisition page identified; identify a candidate page first (add it to data/acquisition_candidate_pages.csv), then capture it |
| MI Arenac (mi_tax_sale_info_surplus) | AVAILABLE | NOT_FOUND | unknown | no | n/a | no | No official acquisition page identified; identify a candidate page first (add it to data/acquisition_candidate_pages.csv), then capture it |
| MI Bay (mi_tax_sale_info_surplus) | AVAILABLE | NOT_FOUND | unknown | no | n/a | no | No official acquisition page identified; identify a candidate page first (add it to data/acquisition_candidate_pages.csv), then capture it |
| MI Calhoun (mi_calhoun_landbank) | AVAILABLE | NOT_FOUND | unknown | no | n/a | no | No official acquisition page identified; identify a candidate page first (add it to data/acquisition_candidate_pages.csv), then capture it |
| MI Jackson (mi_tax_sale_info_surplus) | AVAILABLE | NOT_FOUND | unknown | no | n/a | no | No official acquisition page identified; identify a candidate page first (add it to data/acquisition_candidate_pages.csv), then capture it |
| MI Monroe (mi_tax_sale_info_surplus) | AVAILABLE | NOT_FOUND | unknown | no | n/a | no | No official acquisition page identified; identify a candidate page first (add it to data/acquisition_candidate_pages.csv), then capture it |
| MI Montcalm (mi_tax_sale_info_surplus) | AVAILABLE | NOT_FOUND | unknown | no | n/a | no | No official acquisition page identified; identify a candidate page first (add it to data/acquisition_candidate_pages.csv), then capture it |
| MI Oceana (mi_tax_sale_info_surplus) | AVAILABLE | NOT_FOUND | unknown | no | n/a | no | No official acquisition page identified; identify a candidate page first (add it to data/acquisition_candidate_pages.csv), then capture it |
| MI Otsego (mi_tax_sale_info_surplus) | AVAILABLE | NOT_FOUND | unknown | no | n/a | no | No official acquisition page identified; identify a candidate page first (add it to data/acquisition_candidate_pages.csv), then capture it |
| MI Presque Isle (mi_tax_sale_info_surplus) | AVAILABLE | NOT_FOUND | unknown | no | n/a | no | No official acquisition page identified; identify a candidate page first (add it to data/acquisition_candidate_pages.csv), then capture it |
| MI Saginaw (mi_saginaw_landbank) | AVAILABLE | NOT_FOUND | unknown | no | n/a | no | No official acquisition page identified; identify a candidate page first (add it to data/acquisition_candidate_pages.csv), then capture it |
| MN Hubbard (mn_hubbard_tfl_otc) | AVAILABLE | NOT_FOUND | unknown | no | n/a | no | No official acquisition page identified; identify a candidate page first (add it to data/acquisition_candidate_pages.csv), then capture it |
| MN Ramsey (mn_stpaul_hra_properties) | AVAILABLE | NOT_FOUND | unknown | no | n/a | no | No official acquisition page identified; identify a candidate page first (add it to data/acquisition_candidate_pages.csv), then capture it |
| MO Jackson (mo_kc_landbank) | AVAILABLE | NOT_FOUND | unknown | no | n/a | no | No official acquisition page identified; identify a candidate page first (add it to data/acquisition_candidate_pages.csv), then capture it |
| PA Allegheny (pa_pittsburgh_city_property) | AVAILABLE | NOT_FOUND | unknown | no | n/a | no | No official acquisition page identified; identify a candidate page first (add it to data/acquisition_candidate_pages.csv), then capture it |
| TX Goliad (tx_lgbs) | AVAILABLE | NOT_FOUND | yes | yes | n/a | no | No official resale-process page exists to read (The Tax Assessor-Collector page and the Trustee / Foreclosure Sales notices page carry no struck-off or resale text); the path cannot be established from a delinquent-tax counsel's vendor listing; the county publishes no resale process page |
| TX Hardin (tx_lgbs) | AVAILABLE | NOT_FOUND | yes | yes | n/a | no | No official resale-process page exists to read (The county site moved to hardincountytx.gov; its Foreclosure Sales and Tax Assessor-Collector pages carry no struck-off, resale or buyer text. Only a 2024 commissioners-court resale resolution exists); the path cannot be established from a delinquent-tax counsel's vendor listing; the county publishes no resale process page |
| TX Jim Wells (tx_lgbs) | AVAILABLE | NOT_FOUND | yes | yes | n/a | no | No official resale-process page exists to read (The City of Alice Property Tax Sales page sends buyers to the delinquent-tax counsel's site; the county site carries foreclosure notices only. No county list or buyer procedure); the path cannot be established from a delinquent-tax counsel's vendor listing; the county publishes no resale process page |
| TX Leon (tx_lgbs) | AVAILABLE | NOT_FOUND | yes | yes | n/a | no | No official resale-process page exists to read (The Tax Assessor-Collector page says to visit the delinquent-tax counsels' sites to view current tax-sale listings; no county list or buyer procedure); the path cannot be established from a delinquent-tax counsel's vendor listing; the county publishes no resale process page |
| TX Liberty (tx_lgbs) | AVAILABLE | NOT_FOUND | yes | yes | n/a | no | No official resale-process page exists to read (The Tax Assessor-Collector page links a 'Tax Sale Property Listing' document (Last-Modified 2017) that only says to contact a delinquent-tax counsel or obtain a list from the Tax Office; commissioners-court agendas approve resale bids requested through the counsel. No county list or buyer procedure); the path cannot be established from a delinquent-tax counsel's vendor listing; the county publishes no resale process page |
| TX Maverick (tx_lgbs) | AVAILABLE | NOT_FOUND | yes | yes | n/a | no | No official resale-process page exists to read (The county site listed in directories (co.maverick.tx.us) returned 404; the City of Eagle Pass Tax Office page carries no tax-sale text; the trust-property list is a blocked vendor's); the path cannot be established from a delinquent-tax counsel's vendor listing; the county publishes no resale process page |
| TX Van Zandt (tx_lgbs) | AVAILABLE | NOT_FOUND | yes | yes | n/a | no | No official resale-process page exists to read (The Tax Assessor-Collector page refers property-tax questions to the Van Zandt County Appraisal District; no struck-off or resale text); the path cannot be established from a delinquent-tax counsel's vendor listing; the county publishes no resale process page |
