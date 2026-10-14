# Three customer ledgers: Auctions, Available, Liens & Certificates (2026-09-30)

The product is three first-class ledgers over one shared property
intelligence layer. Each ledger is a product with its own harvesting
domain, lifecycle, freshness record and customer surface. They are not
three filters over one feed.

| Ledger | Customer name | `properties.source` | `properties.ledger_type` | Route slug | What a record is |
|---|---|---|---|---|---|
| AUCTIONS | Auctions | `auction` | `auctions` | `#/auctions` | property in a tax sale / auction process |
| AVAILABLE | Available | `laft` | `buy` | `#/lands` | property purchasable or applicable for after a sale, or held by a government unit for direct sale |
| LIENS_CERTIFICATES | Liens & Certificates | `certificate` | `lien` | `#/certificates` | the lien / certificate instrument itself, never the land |

`harvesters/ledgers/__init__.py` holds the one mapping between those
spellings (`Ledger`, `CUSTOMER_NAMES`, `LEDGER_BY_SOURCE`,
`LEDGER_BY_LEDGER_TYPE`), the harvest-side source-id map
(`SOURCE_LEDGERS`), the per-ledger status vocabulary (`LEDGER_STATUSES`)
and the row classifier (`ledger_for_row`). `public/app.js` `LEDGERS`
carries the same three keys (`auction` / `laft` / `certificate`) with the
same customer names.

## 1. What already carried the distinction, and what was added

Nothing here is a second architecture. The existing schema already
distinguishes the three:

- `properties.source` is the ledger discriminator on every row and the
  identity is `(state, source, county, case_no)`. The same parcel may hold a
  row in more than one ledger (a certificate on a parcel that is also
  scheduled for a deed sale; an auction that failed and became an Available
  record). `ledger_type` (migration 003) is its trigger-synced alias.
- History is beside the row, never over it: `auction_events` +
  `auction_event_observations` (014) for AUCTIONS; the append-only
  `inventory_status_observations` (021, unapplied) for every ledger's
  status changes; `field_provenance` / `otc_provenance` for origin.
- The three harvesters already wrote three status files:
  `harvest_all_status.json` (deeds), `harvest_laft_status.json`,
  `harvest_certificates_status.json` (plus `harvest_texas_status.json` and
  the per-state files of the registered, inactive states).

What this pass added:

- `harvesters/ledgers/domains.py`: the three harvester domains as data
  (`AuctionHarvester`, `AvailableHarvester`, `LienCertificateHarvester`):
  which scripts harvest, which status and harvest files they own, which
  sync writes rows, the lifecycle, the only close-out gate, where history
  lives, which registry source ids and states participate.
  `assert_isolated()` proves no status or harvest file is shared, so a
  failed read in one ledger can never be read as an empty inventory in
  another. LGBS (Texas) feeds AUCTIONS and AVAILABLE from one feed; its rows
  are told apart by the vendor's own raw status
  (`texas_harvester.LGBS_STATUS_TO_LEDGER`), never by guess.
- `county_source_registry.ledgers` (registry column; migration 020,
  unapplied): every source names the ledger(s) it feeds, "|"-joined. The
  committed CSV now carries every production source of every ledger: the
  47 FL deed-auction sources (46 RealAuction + Okaloosa Bid4Assets), the
  32 FL LienHub certificate sources and the 24 TX RealAuction sources,
  generated from the harvesters' own county CSVs exactly as the LAFT rows
  are. `expected_harvest_units(rows, state, ledger)` is scoped per ledger,
  so an AUCTIONS unit that did not run never gates an AVAILABLE county of
  the same name. A production row must name a ledger; an inventory type is
  allowed only on a source that feeds AVAILABLE; a blocked vendor feeds
  none.
- `scripts/laft_status.py`: `SOURCE_UNAVAILABLE` joins the vocabulary as a
  reader-side refinement of FAILED (a transport / proxy / access error
  category). It closes nothing, exactly like FAILED.
- `harvesters/governance/inventory_status.py`: four certificate statuses
  (`certificate_listed`, `certificate_redeemed`, `certificate_assigned`,
  `certificate_expired`). Presence on the county-held list is the only
  status the FL feed publishes; the other three are RESULT statuses and
  need the source's own column. A certificate that left the list is
  `closed`, never a certificate result. Migration 021's check constraints
  are widened accordingly (unapplied).
- `scripts/unit_freshness.py` reports `by_ledger` counts and stamps each
  unit with its `ledgers`, so the Dashboard groups per-county freshness per
  ledger.
- Arizona: `harvesters/otc/adapters/arizona.py`, the Maricopa County
  Treasurer "Current State CP Listing" - the first LIENS & CERTIFICATES
  source outside Florida. Fixture-driven, gated, not activated (section 5).

## 2. Source-to-ledger map

| Source | Ledger(s) | State | Standing |
|---|---|---|---|
| `fl_realauction`, `fl_bid4assets_okaloosa` | AUCTIONS | FL | production |
| `fl_laft_*` (nine harvesters) | AVAILABLE | FL | production |
| `fl_lienhub_certificates` | LIENS_CERTIFICATES | FL | production |
| `tx_realauction` | AUCTIONS | TX | production |
| `tx_lgbs` | AUCTIONS + AVAILABLE (by raw status) | TX | production; feed INCOMPLETE since 2026-09-29; **not retried** |
| `tx_hctax` | AVAILABLE | TX | LEGAL_REVIEW_REQUIRED, never runnable |
| `tx_pbfcm`, `tx_mvba`, `tx_govease`, `tx_ctsa` | none | TX | blocked; discovery only |
| `al_ador_state_land` | AVAILABLE | AL | registered, not activated |
| `ar_cosl_post_auction` | AVAILABLE | AR | registered, not activated |
| `la_ebr_adjudicated` | AVAILABLE | LA | registered, not activated |
| `az_maricopa_state_cp` | LIENS_CERTIFICATES | AZ | registered, not activated |

Texas has no certificate ledger and none was invented: the TX page's third
tab is the pre-existing "Redeemable Tax Deeds" copy with no source behind
it. Mississippi and West Virginia: no adapter (section 6).

## 3. Lifecycle and freshness per ledger

| | Auctions | Available | Liens & Certificates |
|---|---|---|---|
| Status file | `harvest_all_status.json`, `harvest_texas_status.json` | `harvest_laft_status.json` (+ AL/AR/LA files) | `harvest_certificates_status.json` (+ AZ file) |
| Freshness states | COMPLETE / EMPTY / INCOMPLETE / FAILED / SOURCE_UNAVAILABLE (+ STALE / NOT_RUN reader-side) | same | same |
| EMPTY is valid only when | the source was read successfully and published nothing | same (`laft_status`: a zero without an explicit empty signal is INCOMPLETE) | same |
| Close-out of an absent row | FL: sale date passed AND county COMPLETE this run; TX: never by absence | county COMPLETE or EMPTY only | county COMPLETE only |
| Statuses | upcoming, active, unknown (date passed, no result), closed; sold / redeemed / withdrawn / cancelled / struck_off only from a source column | available_otc, state_held, resale_inventory, struck_off, closed; sold only from the list's own "Sold To" column | certificate_listed, closed; redeemed / assigned / expired only from a source column |
| History | auction_events + observations; inventory_status_observations | inventory_status_observations; provenance | inventory_status_observations |

"Winning bid" is never derived from an opening bid; "Outcome: Not
published by the source" is the wording when the source did not say. A
certificate leaving the list is "Left the county-held list (redeemed,
assigned or expired is not published)".

## 4. Customer surface

- Primary navigation (sidebar and phone bottom bar): Auctions / Available /
  Liens & Certificates, each with its live count, each opening the ledger
  page with that ledger selected. Only the current ledger's entry lights.
  Dashboard and Map are unchanged.
- Each ledger keeps its own heading, description, "how it works" line,
  facts line, filters, county groups, cards and empty state. The Available
  ledger's card kicker reads `<County>, FL · Available · Lands Available
  list · fixed price`.
- Each ledger's card leads with its own emphasis line (`ledgerLineHtml`):
  Auctions - "Auction result": a source-published outcome when the row
  carries one, "Not published by the source" once the sale date passed
  or the row left the feed, "Sale not yet held" before then. Available -
  "Purchase path": the row's own purchase link by kind (property action
  vs instructions) or "No online purchase link on file", plus the amount
  kind the source used. Nothing on either line is derived from absence.
- Liens & Certificates cards and pages lead with the instrument's own
  lines: Status (list presence, or the 021 status when written), Issued
  (issue date and tax year, or "Not published"), Redemption
  ("Not published by the source"), Property (parcel number, or "not
  published by the source", with the count of records in other ledgers).
- Shared property layer: every full page has "Same parcel in other
  ledgers" - exact match on state, county and punctuation-stripped parcel
  number, never on address or owner. No parcel = "cannot be matched"; no
  match = says so.
- Dashboard: the ledger rows carry "N of M counties current" from the
  per-county freshness table, per ledger; the per-county list is grouped
  under one heading per ledger, with an explicit "no recorded read yet in
  this ledger" for an empty group.

## 5. Arizona (Maricopa State CP) - the first non-Florida certificate source

Search-index evidence only (`MARICOPA_EVIDENCE`): the Treasurer's "Current
State CP Listing Downloads" page, its CSV, the Tax Assignment page
(assignment by mail with the Assignments Purchase Form). Nothing was
fetched from this repository - every government host is egress-blocked
here. The adapter parses a header-mapped CSV into `OtcRecord`s with
`record_source="certificate"`, the parcel as identity, the CP number as
`certificate_no`, and the Tax Assignment page as purchase instructions.
`parser_fixture_validated=False`, so no county outcome can be COMPLETE or
EMPTY; `can_run()` refuses; `harvest()` raises before the first request.
Registry row: `AZ / Maricopa / az_maricopa_state_cp`, SEARCH_EVIDENCE_ONLY,
TERMS_NOT_VERIFIED, ledgers LIENS_CERTIFICATES. Arizona's tax-deeded land
(an AVAILABLE source) is not represented: nothing was located.

## 6. Not done, and why

- Mississippi, West Virginia: no adapter. The only endpoint the search
  surfaced for Mississippi is token-gated third-party evidence; West
  Virginia produced page titles only. No empty placeholders were created.
- Texas: LGBS not retried, GovEase not implemented, blocked vendors not
  touched, no TX certificate ledger.
- Migrations 020 and 021 remain unapplied; nothing was written to
  production; no workflow was dispatched.

## Record contracts and read health (2026-10-13, implementation sprint 1)

The ledgers already had separate rows (`properties.source` is part of the
`(state, source, county, case_no)` identity), separate harvesters and
separate status files. This sprint gave each ledger a record contract and
the readers a health check, and enforced both in the places they decide
something. No migration: the schema already carries every field.

### `harvesters/ledgers/records.py`

| Record | Row | Fields it owns | Missing values read |
|---|---|---|---|
| `AuctionRecord` | `source='auction'` | sale date, opening bid (`min_bid` / `purchase_amount` / `bid` > 0), auction URL + kind, raw source status, result / winning bid / result date (only beside a source-published `sold`) | "Not published"; result "Not published by the source" |
| `AvailableRecord` | `source='laft'` | inventory type (017/020 Available set), amount + its kind (never assumed; QUOTED_ON_APPLICATION / NOT_PUBLISHED carry no figure), purchase link (https only, never the list or the document page), list URL, source document, application instructions, list date | "Not published"; link "No online purchase link on file" |
| `CertificateRecord` | `source='certificate'` | certificate number, tax year, face amount, interest rate, certificate sale date (`issued_date`), expiration, redemption (instrument statuses only) | "Not published"; holder always "Not published" (never `owner_name`) |

`problems(row)` names a classification bug:
- the row's source / `ledger_type` / source id disagree;
- the vendor's own LGBS sale status puts the row in another ledger;
- a status lies outside the ledger's vocabulary;
- an Available-only or certificate-only field sits on another ledger;
- any result field sits on a certificate row (a certificate result is never a property sale);
- a result field sits beside a non-result status.

`property_key(row)` is the shared property reference: state, county, and the normalized parcel. For the Texas tax-suit sources it is the CAD account (`case_no`), never the cause number. One parcel can therefore be found in several ledgers while each keeps its own row, status and history.

### `harvesters/ledgers/health.py`

`reader_status(entry)` is the reader's check on a status-file entry:
- EMPTY only with row count 0, an empty signal and no transport/parse failure;
- COMPLETE only with no transport/parse failure;
- otherwise INCOMPLETE;
- a FAILED with a TRANSPORT_ / PROXY_ / ACCESS_ category is SOURCE_UNAVAILABLE.

`ledger_units()` keys the entries by (source, county), scoped to a ledger. Its bare-county fallback is built only from entries that name no source. `closeable(ledger, status)` allows COMPLETE / EMPTY only.

### Where it is enforced

- **`scripts/sync_state_inventory.py`:**
  - refuses rows with ledger problems (`refused_ledger_contract`);
  - `units_for()` uses the health reader. Before this, the bare-county fallback was the worst of every entry, so a source with no entry of its own took a sibling's read;
  - `plan_close()` closes only rows of a ledger that the reading source feeds.
- **`scripts/inventory_status_writer.py`** never writes a status outside the row's ledger (`refused_outside_ledger`).
- **`scripts/sync-texas-to-supabase.py`:**
  - de-duplicates on `(source, county, case_no)`. Before this, an account listed in two ledgers kept only the last one;
  - refuses rows that break the ledger contract.

Tests: `tests/python/test_three_ledger_separation.py`.

## Integration: Florida PowerShell syncs, LAFT lifecycle, customer read path (2026-10-14)

The contracts above are now applied on every remaining path.

### Florida PowerShell syncs (Gap A)

`scripts/ledger_gate.py` is the command-line form of the two modules, so
PowerShell never carries a second copy of the rules:

- `rows --ledger L --in rows.json` prints the indices of refused rows. A row
  is refused when it is not in ledger L or breaks L's contract.
- `closeable --ledger L --status file` prints the counties whose read the
  health reader accepts for close-out. A missing or unreadable file gives
  `[]`.

All three syncs (`sync-harvest-to-supabase.ps1`, `sync-certificates-to-supabase.ps1`
and `sync-laft-to-supabase.ps1`) carry one identical helper block after the
permission guard:

- `Select-LedgerRows` runs before every upsert.
- `Get-LedgerCloseableCounties` replaces the old inline `status -eq "COMPLETE"`
  check in the deed close-out and the certificate reconciliation.

Both fail closed. A gate that cannot run stops the write, and a status file
that cannot be read closes nothing. One behavioural difference: a county
whose entries disagree (a COMPLETE read and a failed retry) now reads as its
worst entry, not as COMPLETE.

`tests/python/test_ledger_ps_syncs.py` runs the real scripts under PowerShell 7
against a local fake Supabase server.

### Florida LAFT lifecycle (Gap B)

`scripts/laft_lifecycle.py`:

- `county_gates()` passes every entry through `health_checked()`. An EMPTY
  without a valid signal, or a COMPLETE / EMPTY from a broken read, becomes
  INCOMPLETE (`health_downgrade`).
- Each gate now carries the per-source `units` (`source_units()`) and the
  registry's `missing_sources`.
- `row_closeable()` closes a row only on its own source's COMPLETE or EMPTY
  read. A row with no source is closed only when the county has exactly one
  source and no expected source is missing.
- Reactivation still writes `status` alone.

Tests: `tests/python/test_laft_lifecycle_ledger_health.py`.

### Customer read path (Gap C)

- **Frontend mirror:** `public/app.js` `ledgerRecordView(p)` mirrors
  `records.customer_view()`, field for field, on
  `tests/python/fixtures/ledger_record_cases.json`. Both Python and Playwright
  run those cases.
- **Purchase link:** `purchasePathOf()` refuses an Available row's
  `purchase_url` when it is the list page, the source document or plain http.
- **Status band:** the property status band names the record's ledger
  (`data-ledger-record`, plus "<Ledger> ledger" when the state calls the list
  something else).
- **Backend gate:** `publication_state.decide()` withholds a row that breaks
  its ledger contract (reason `LEDGER_CONTRACT`). The writer reads the columns
  the contract needs.

That backend gate becomes customer-binding only when migration 031 is
applied, and 031 is NOT applied. Until then the publication-state writer
plans only, and customers are protected by the existing read-path behaviour.
