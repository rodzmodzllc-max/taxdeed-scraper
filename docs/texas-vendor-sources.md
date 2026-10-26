# Texas vendor sources: PBFCM, MVBA, GovEase (2026-10-26)

## Decision

Owner decision, 2026-10-26, verbatim: "Do not block vendors. Post their shit and we'll figure out the legal shit afterwards... You need to find every fucking property and every source, and then we'll work on the legal shit."

The owner accepts the terms-of-service / robots.txt risk for:

| Source | Earlier finding (still on record) | Now |
|---|---|---|
| `tx_pbfcm` Perdue Brandon Fielder Collins & Mott | disclosure.html anti-reproduction / redistribution clause | harvested |
| `tx_mvba` McCreary Veselka Bragg & Allen | non-commercial-use-only clause | harvested |
| `tx_govease` GovEase | robots.txt `Disallow: /`, no terms located | harvested |
| `tx_ctsa` County Tax Sale App | paywall + anti-competitive-use clause | **still BLOCKED** (paywalled; never logged into or bypassed) |

How it is recorded:

- `data/source_permissions.csv`: `discover`, `fetch`, `parse`, `store`, `display`, `link` are `LEGAL_REVIEW_REQUIRED` + `INTERNAL_RISK_ACCEPTANCE`, effective 2026-10-26, expiring 2027-04-12. That is an interim internal risk acceptance, never the vendor's permission. `enrich`, `redistribute` and `fetch_via_proxy` stay `BLOCKED`.
- `harvesters/governance/registry.py`: `legal_status=APPROVED` with the decision in `notes` (the same production-practice standing as `tx_lgbs`, not a rights clearance). The earlier terms / robots findings are kept in `terms_status` / `robots_status`.
- Hard-block sets (`permissions.HARD_BLOCKED_SOURCE_IDS`, `county_source_registry.BLOCKED_SOURCE_IDS`, `ledgers.BLOCKED_SOURCE_IDS`) hold `tx_ctsa` only.
- Registry rows (`data/county_source_registry.csv`, from `data/tx_vendor_counties.csv`): `PRODUCTION_VERIFIED`, `APPROVED_GRANDFATHERED`, the decision in `restrictions`.

## Access rules

Plain HTTPS GET / POST, `User-Agent: taxdeed-scraper/1.0`, at least one second between requests (`texas_vendors.PoliteFetcher`, which refuses to go faster), no login, no CAPTCHA, no proxy, no identity other than the honest one. HTTP 401 / 403 is a refusal: the unit is FAILED and nothing is retried or worked around.

## Sources and structure (read live 2026-10-26)

### PBFCM (`www.pbfcm.com`)
- `taxsale.html`: `<li class="tax-list-entity">` per county (inactive counties sit inside HTML comments), each linking the firm's sale-list PDFs (`docs/taxdocs/sales/<MM-YYYY><client>taxsale.pdf`; Harris and Fort Bend per constable precinct). AUCTIONS.
- `taxresale.html`: the same shape, resale lists of struck-off property per taxing unit (`docs/taxdocs/resales/...`). AVAILABLE. Some entries link texascg.com (another firm) or an appraisal district page; those are counted and never followed.
- PDFs: ruled tables in several column families (read by `harvesters/tx_sale_tables.py`, header-driven), plus a positioned-text layout for the Harris-area resale lists. One Brazoria resale list is a scanned image (INCOMPLETE); Childress's sale list has no ruled table (INCOMPLETE).
- Live read: 84 requests, 545 rows (225 AUCTIONS, 320 AVAILABLE) across 35 counties; units 30 COMPLETE, 8 EMPTY, 7 INCOMPLETE.

### MVBA (`mvbalaw.com`, `www.mvbataxsales.com`)
- `/tax-sales/month-sales/`: the month's sale bid sheets (`wp-content/TaxUploads/<MMYY>_<County>.pdf`). AUCTIONS.
- `/tax-sales/trust-properties-for-sale/`: trust (struck-off) property lists. AVAILABLE. Bandera's trust list draws its header outside the table (INCOMPLETE).
- `www.mvbataxsales.com` (the firm's own AuctionMethod site, robots.txt allows `/`): `POST /api/auctions` lists the open auctions; `POST /api/getitems` with `auction_id=<id>&filters[page]=<n>` pages one auction's items (24 a page). Each item's description carries `Account No.`, `Suit No.` and `Approximate Property Address:`. AUCTIONS.
- Live read: 13 requests, 194 rows (166 AUCTIONS, 28 AVAILABLE) across 10 counties.

### GovEase (`liveauctions.govease.com`)
- Any county page carries the state / county picker (`<option value="tx|<slug>|<id>">TX - <County></option>`): Denton, Grayson, McLennan (MVBA's online constable sale), Palo Pinto, Parker, Wichita.
- `/tx/<slug>/<id>/browse` is a server-rendered table (50 a page; later pages `<PostUrl>/<n>`), each row linking `openparcel` / `openstandardparcel`. The parcel page carries Physical Address, Property Description (`Cause No.`, `Account Number`, `Adjudged Value`), Legal Description and, for some counties, "scheduled to begin MM/DD/YYYY".
- `Parcel #` is the CAD account in some counties (Wichita, Parker, Palo Pinto) and the suit number in others (Grayson, McLennan, Denton); a labelled account decides. HOA foreclosures (Denton) are not tax sales and are skipped.
- Live read: 116 requests, 92 rows across 6 counties, all COMPLETE.

## Output

`harvesters/texas_harvester.py` `SOURCES` runs `harvest_pbfcm`, `harvest_mvba`, `harvest_govease` in the daily `texas` job. Rows follow the Texas convention: the account is `account_number` (DB `case_no`), the cause is `cause_number` (DB `parcel`; `ledgers.records.CAUSE_IN_PARCEL_SOURCES`). The document read is `sale_list_url` (DB `document_url`); a GovEase / mvbataxsales item page is `auction_url` with kind `property`. `out/harvest_texas_status.json` carries each source's `units`: per county `status` (COMPLETE / EMPTY / INCOMPLETE / FAILED, worst document wins), `rows`, per-ledger status and each document's signal.

Value-free runner check: `job=evidence`, `evidence_scope=tx_vendors` (`scripts/capture_tx_vendors.py`).

## Not done

- `tx_ctsa`: paywalled; stays BLOCKED.
- texascg.com city lists linked from PBFCM's resale page: another firm, not inspected.
- The frontend's `parcelOf()` cause-in-parcel list (public/app.js) still names only `tx_lgbs` / `tx_realauction`; until it is extended, a vendor row's cause shows where the parcel is shown.
