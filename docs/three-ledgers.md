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
- Liens & Certificates cards and pages lead with the instrument's own
  lines: Status (list presence, or the 021 status when written), Redemption
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
