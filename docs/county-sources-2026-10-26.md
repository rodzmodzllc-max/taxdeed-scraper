# FL / TX county sources (2026-10-26)

Owner decision, 2026-10-26: "You need to find every fucking property and every source, and then we'll work
on the legal shit." The owner accepted the terms-of-use and licensing risk. Every source below is recorded
in `data/source_permissions.csv` as `OWNER_PERMISSION_REQUIRED` / `INTERNAL_RISK_ACCEPTANCE`. These records
are effective 2026-10-26 and expire 2027-04-12. They are an internal risk acceptance, never the publisher's
permission.

Hard limits held throughout:

- no CAPTCHA, bot challenge, login or paywall is solved or bypassed;
- no proxy is used to get round an IP block;
- requests carry an honest User-Agent and run at a polite rate.

A block is recorded as a block, with the source's own `FAILED` / `ACCESS_DENIED` status.

Live counts below come from GitHub Actions runs 40384154366 and 40385964621 (`job=evidence`,
`evidence_scope=county_sources`). The runs had no database credential and read only.

## Florida: Lands Available (15 counties had no harvester)

| County | Finding | Implemented | Live read on Actions |
|---|---|---|---|
| Lake | The Clerk's "Accept and Search" disclaimer links to `lake.realtdm.com` (realTDM) | Added to `data/laft_realtdm_counties.csv` | COMPLETE, 4 properties |
| DeSoto | The Clerk's Tax Deeds page carries the list inline: "There are no properties on the list of lands available at this time." | Added to `data/laft_html_sources.csv` | EMPTY (the page says so) |
| Wakulla | The Clerk's Tax Deed Sales page: "Currently, there are no parcels available on the List of Lands." | Added to `data/laft_html_sources.csv` | EMPTY (the page says so) |
| Charlotte | Tax Deed Services portal (`taxdeeds.charlotteclerk.com`). The Kendo grid reads `POST /TaxDeed/GetTaxDeedViewByLandsAvailable` with the page's anti-forgery token | New `scripts/harvest_laft_portals.py` (`fl_laft_portals`, `data/laft_portal_sources.csv`) | Sandbox: COMPLETE, 4 properties. Runners: HTTP 403 (datacenter block, not bypassed), so the county reads FAILED until the block lifts |
| Broward | The LAFT page and the SharePoint list both 301 to the Records, Taxes & Treasury landing page, which links only RealAuction auctions | Not implemented: no list is published (the county says to call for the count) | Probe: HTTP 200, no list |
| Baker | `bakerclerk.com` serves a Cloudflare challenge ("Just a moment...") to the sandbox and the runners | Not implemented: the challenge is not bypassed | Probe: 403 challenge |
| Okaloosa | The Lands Available page publishes the purchase process only | Not implemented: no list | n/a |
| Collier, Gilchrist, Monroe, Nassau, Jackson, Liberty, Suwannee | Clerk pages read: auction (realtaxdeed) links, surplus, brochures. No Lands Available list | Not implemented: no list | n/a |
| Jefferson | Only a 2022 PDF is indexed; the page carries no current list | Not implemented | n/a |

### How the four new counties are published

- Publication is decided per source (`scripts/publication_gate.py`).
- Lake, DeSoto and Wakulla carry their platform source's existing `APPROVED_GRANDFATHERED` decision.
- `fl_laft_portals` (Charlotte) is a new source. The owner's second decision of 2026-10-26 ("post their shit";
  `docs/publish-all-sources.md`) publishes it: registry `publication_status` `APPROVED`, restrictions "Owner approved
  customer publication 2026-10-26; legal review pending ...", INTERIM `display` / `link` records. No admin-only hold.

## Texas: county-published lists (harvested, synced, published)

`scripts/harvest_tx_county_sales.py` runs in the `texas` job as a `continue-on-error` step. Per ledger it writes:

- `out/harvest_tx_county_{auctions,available}.json` (the harvest rows; what the close-out reads);
- `out/harvest_tx_county_{auctions,available}_status.json` (one entry per source and county);
- `out/tx_county_{auctions,available}_properties_rows.json`: the same rows as `properties` rows, built through
  `harvesters/otc/model.py` `OtcRecord` (`to_properties_rows()`), so the record contract refuses anything it
  cannot store.

### Publication (owner decision 2026-10-26, legal review pending)

The owner's second decision of 2026-10-26 ("post their shit"; `docs/publish-all-sources.md`) publishes all eight:

- registry rows `PRODUCTION_VERIFIED`, governance `APPROVED`, harvester `scripts/harvest_tx_county_sales.py`,
  `publication_status` `APPROVED`, restrictions "Owner approved customer publication 2026-10-26; legal review
  pending ..." (the same text as every other owner-approved source), with publisher, amount kind, cadence and
  terminology (`TX_COUNTY_META` in the registry builder);
- INTERIM `fetch` / `parse` / `store` / `display` / `link` records at state level (`TX`), expiring 2027-04-12;
  `redistribute` (export / API) is not granted. The old Harris `LINK_ONLY` record was replaced.
- `harvesters/governance/registry.py` `_TX_HCTAX` (the Phase 9.5 legal record, consulted by the vendor sync
  `sync-texas-to-supabase.py` and the OTC gate) still says `LEGAL_REVIEW_REQUIRED`: that is the truthful legal
  posture, and the county lists do not go through that path.

### Sync and close-out

- **Sync:** `scripts/sync_state_inventory.py --state TX --keep-other-sources`, once per ledger. It writes only
  rows of a production, APPROVED registry source whose (source, county) read was COMPLETE or INCOMPLETE, with the
  `store` permission, through the ledger contract; it stamps `publication_status`, `ledger_type`, `last_seen_at`
  and `field_provenance`. `--keep-other-sources` (new) never writes a row whose identity an LGBS / RealAuction row
  already holds (one Harris or Bexar account can be on both), so each source keeps closing only its own rows.
- **Close-out:** `scripts/texas_closeout.py` (#205), extended: `COUNTY_LIST_SOURCE_IDS`, repeatable `--harvest`
  / `--status`. A separate step after the county sync closes a source's stored active row (`closed` +
  `delisted_at`, never `sold`) only when that source's own read this run was COMPLETE or EMPTY and no longer lists
  the account; a FAILED / INCOMPLETE / unread source closes nothing, and more than half of a source's rows in one
  read is refused. The vendor close-out step is unchanged.
- **Status:** `inventory_status.status_for_row()` gives the Harris and Jefferson auction rows the feed status
  (upcoming / unknown after the sale date / closed); the AVAILABLE rows get the presence status.

### Record contract

| Field | Rule |
|---|---|
| `case_no` | the CAD account (as every Texas row stores it) |
| `parcel` | the same account; the cause / suit number is a lawsuit, kept in `otc_provenance.cause_number` |
| AUCTIONS amount | Harris "Minimum Bid" -> `min_bid` (`MINIMUM_PURCHASE_AMOUNT`); Jefferson "Estimated Minimum Bid" -> `purchase_amount` of `PUBLISHED_AMOUNT_KIND_UNSPECIFIED`, never `min_bid` |
| AVAILABLE amount | Bexar struck-off amount -> `PUBLISHED_AMOUNT_KIND_UNSPECIFIED`; Orange -> `MINIMUM_PURCHASE_AMOUNT`; Randall "Minimum Bid at Sale" -> `ORIGINAL_OPENING_BID`; Montgomery, Trinity, Hood -> `NOT_PUBLISHED` |
| AVAILABLE type | `STRUCK_OFF_HELD_IN_TRUST`; financial terms rows in `data/available_financial_terms.csv` |

| County | Source id | List | Ledger | Live read on Actions |
|---|---|---|---|---|
| Harris | `tx_hctax` | hctax.net Delinquent Tax Sale Property Listing (sale 2026-11-03) | AUCTIONS | COMPLETE, 149 For Sale (182 listings, 33 cancelled) |
| Jefferson | `tx_jefferson_sheriff_sale` | Tax Office "Notice of Sale" PDF (Sheriff's sale 2026-12-01) | AUCTIONS | COMPLETE, 131. The page sometimes serves a Sucuri bot challenge; the reader then fails ACCESS_DENIED and does not bypass it |
| Bexar | `tx_bexar_resale` | Resale Properties Distribution List PDF (updated 2026-10-06) | AVAILABLE | COMPLETE, 46 (2 multiple-account groups) |
| Montgomery | `tx_montgomery_tax_trust` | Tax Trust Listing PDF | AVAILABLE | Sandbox: COMPLETE, 240. Runners: HTTP 403 (not bypassed) |
| Orange | `tx_orange_trust_property` | Trust Property list PDF (as of 2026-02) | AVAILABLE | COMPLETE, 17 |
| Trinity | `tx_trinity_cad_resale` | Trinity CAD Resale Property Lists, 2 PDFs (2026-09-22) | AVAILABLE | COMPLETE, 343 |
| Randall | `tx_randall_trustee_property` | Trustee Property Listing PDF (updated 2025-10-02) | AVAILABLE | COMPLETE, 3 |
| Hood | `tx_hood_cad_struck_off` | Hood CAD "Struck off" Property List | AVAILABLE | EMPTY (headings, no property) |

### Texas sources found and not implemented

| County | Why |
|---|---|
| Johnson | The constable sale page answers HTTP 403 "Access Denied" (Akamai) to the sandbox and the runners. Not bypassed |
| Brazoria | Same 403 "Access Denied". Not bypassed |
| Grayson | The struck-off portal on port 8443 refuses connections from the sandbox and the runners |
| Gregg | The resale PDF's TLS certificate does not verify. TLS verification is never disabled |
| Jefferson County site | Connection refused from the runners; the Tax Office page above is the working source |
| Dallas | The Public Works resale page links only the LGBS map (already harvested) and RealAuction |
| Travis | Resales link to RealAuction (already harvested) |
| Collin | One Notice of Constable Sale PDF per case, with tax and mortgage cases mixed; no list |
| Fayette | A 2024 scanned PDF with no text layer |
| Camp | The page is gone; the newest list is from 2023 |
| Tom Green | Mortgage substitute-trustee notices, not tax sales |
| Bandera | Procedure and blank forms only |
| Denton | Sales run on GovEase (hard-blocked vendor) |
| Hidalgo | Commissioners' Court agenda exhibits on a per-meeting URL |
| Fort Worth (Tarrant) | The newest city tax-foreclosed inventory list is from 2020 |

## Probe

`scripts/capture_county_sources.py` runs under `job=evidence`, `evidence_scope=county_sources`. It is
discovery-guarded and value-free. It reads the sources the sandbox could not reach, then runs the readers
above for real and prints counts only. It never retries a block with different headers.

## Florida county-held tax certificates outside LienHub (12 counties)

This section follows up on PR #210 (`docs/review/fl-certificate-sources-2026-10-26.md`). The fields agent could not
read these 12 counties from its sandbox.

Each county got one value-free read from a GitHub runner, in run 40387347545 (`job=evidence`,
`evidence_scope=county_certificates`, `scripts/capture_county_sources.py --certificates`):

- the candidates are listed in `data/county_source_candidates.csv`, which the discovery guard indexes;
- each county has an interim `discover` record, `fl_<county>_tc_certificates`;
- the read followed one hop to same-host links only;
- LienHub and TaxSys were not requested, because their refusals are final.

| County | What the runner read | County-held list of its own? |
|---|---|---|
| Bay | `baycountyfltax.gov`, Delinquent Property Taxes page: certificate sale links LienHub, tax deeds link realtaxdeed | No (LienHub only) |
| Broward | `broward.org` Records, Taxes & Treasury: tax-deed auction and legal-notice links only | No |
| Charlotte | `cctaxcol.com` Delinquent Taxes: "County Held Certificates" links LienHub; certificate search links TaxSys | No (LienHub / TaxSys only) |
| Citrus | `citrustc.us` "Tax Certificate Information" page: no list or document link | No |
| Collier | `colliertaxcollector.com`: "Tax Certificate Sale" links LienHub | No (LienHub only) |
| Hernando | The County-Held Tax Certificates page now answers 404. The anonymous FTP file `ftp.hernandocounty.us/TCData/BIDCERAUTO.TXT` (named in search results) timed out from the runner; the permission was checked before the connection | Not reachable today; a reader can be built once the FTP host answers |
| Martin | `martintaxcollector.com`: Cloudflare challenge ("Just a moment...") to the runner, not bypassed | Not read; the sandbox read showed LienHub only |
| Miami-Dade | `mdctaxcollector.gov`: Cloudflare challenge to the runner, not bypassed | Not read |
| Orange | `octaxcol.com` Tax Certificate and Deed Sales: LienHub plus the 2026 sale advertisement and procedure PDFs | No (the advertisement lists the annual sale, not county-held certificates) |
| Escambia | `escambiataxsale.com`: connection timed out from the runner | Not reachable |
| Nassau | `nassautaxes.com` Delinquent page: county-held certificates are sold through LienHub ("nassau lien express") | No (LienHub only) |
| Seminole | `seminoletax.org` serves a JavaScript redirect challenge (not solved); the runner was redirected to `ww19.seminoletax.org`, a page with no title, tables or certificate links | Not read |

**Result:** none of the 12 publishes its own county-held list that can be read, so no harvester was built.

Two counties are worth a later re-check:
- **Hernando:** its FTP file, once the host answers;
- **Escambia:** its separate sale site, once it is reachable.
