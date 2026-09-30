# The AVAILABLE ledger as a customer product (2026-09-30)

What a paying customer gets from the Available ledger, where each fact
comes from, and what the system refuses to do. Builds on
`docs/three-ledgers.md` (the ledger), `docs/otc-inventory-model.md`
(the inventory model, purchase paths, lifecycle) and PRs #43–#46.

## 1. What an Available record carries

Every column below already exists on `properties` (migrations 017, 019,
021) and is projected by `get_properties()`; migration 022 (unapplied) adds
the last one.

| Fact | Column(s) | Written by | When absent |
|---|---|---|---|
| Identity | `state`, `county`, `parcel`, `case_no`, `source` | the county sync | never absent |
| Legal description, assessed name, assessed / taxable value, acreage, land use | `legal_desc`, `owner_name`, `assessed`, `taxable_value`, `acreage`, `land_use` | the list itself (`laft_source_fields.py`) or the FDOR tax-roll match (`enrich_property_details.py`) | "Not published" / "No county value on file" |
| Coordinates | `latitude`, `longitude` | geocoder / FDOR centroid | "Not yet geocoded"; never a county-centroid point |
| Availability status | `inventory_status` + `_raw` + `_basis` + `_observed_at` | `inventory_status_writer.py` | "Not published" |
| Source, authority, list URL, document URL | `source_id`, `source_authority`, `list_url`, `document_url` | the lifecycle | shown as the harvester tag |
| List date / document date / last read | `list_as_of`, `source_published_at`, `last_seen_at` | the lifecycle, from the document only | "Not published by the source" / "Not yet verified" |
| Purchase path | `purchase_url` + `purchase_url_kind`; `otc_provenance.purchase_path_mode` | an enabled rule, or the registry's source-level path / mode | "No online purchase link on file" / "Not yet verified" |
| Amount | `purchase_amount` + `purchase_amount_kind` | the list's own column | "Not published by the source" |
| Field provenance | `field_provenance`, `otc_provenance` | `field_provenance.py`, the lifecycle | "No per-field provenance recorded" |
| Publication | `publication_status` (022) | `publication_gate.py`, from the source's registry row | NULL = not yet classified; shown as today |

## 2. The source-level publication gate

`harvesters/governance/publication.py`. One decision per source (a
registry row), never per property. Seven facets:

1. **harvestable** - PRODUCTION_VERIFIED, with a harvester and a URL.
2. **establishes availability** - feeds the AVAILABLE ledger with a stated
   inventory type.
3. **purchase info** - `property` (an enabled rule establishes per-property
   links), `instructions` (a source-level process / application page),
   `none`.
4. **governance ok** - `governance_status` APPROVED or APPROVED_GRANDFATHERED.
5. **publication APPROVED / APPROVED_GRANDFATHERED** - customers may see the
   source's rows. APPROVED_GRANDFATHERED means "already served to customers
   before this gate existed, carried forward"; it is not a new legal
   review and the docs say so.
6. **UNREVIEWED / RESTRICTED** - not shown. RESTRICTED must say why
   (`restrictions`).
7. **BLOCKED** - a blocked vendor.

Rules the validator enforces (`county_source_registry.validate_row`):
APPROVED* requires governance ok AND production-verified, so a government
website is never automatic commercial permission; a source under
LEGAL_REVIEW_REQUIRED is at most RESTRICTED whatever the column says; a
blocked vendor is BLOCKED whatever the column says; RESTRICTED needs a
reason; a blank is UNREVIEWED. Several county rows of one source must
agree; the strictest wins.

The committed registry: every production source (the 9 FL LAFT
harvesters, tx_lgbs, fl_realauction, fl_lienhub_certificates,
tx_realauction) is APPROVED_GRANDFATHERED; every candidate and every
registered-but-inactive state (AL, AR, LA, AZ) is UNREVIEWED; tx_hctax is
RESTRICTED (legal review); the four blocked vendors are BLOCKED.

`scripts/publication_gate.py` (laft job, after the freshness step,
non-blocking) writes `out/public/publication-gate.json` - every source's
decision plus the AVAILABLE measurement: total observed, publishable,
restricted, unreviewed, blocked, unclassified (source not nameable),
unavailable-source, with / without purchase path, stale (> 14 days since
the last read). Once migration 022 exists it propagates each row's SOURCE
decision to `properties.publication_status`. The frontend withholds every
non-APPROVED row from the list, the counts, the map and the export and
prints "N records withheld - source not approved for customer
publication" on the ledger page and the Dashboard. A NULL keeps today's
behaviour and is counted as unclassified, so the gap is measurable.

## 3. Purchase paths

Reuses PR #44's rule engine (`scripts/laft_purchase_paths.py`,
`data/laft_purchase_link_rules.csv`, still no rule enabled) and adds:

- **Modes** (`PURCHASE_PATH_MODES`): `online_property`,
  `online_instructions`, `application` (each with a URL + kind),
  `in_person_only`, `phone_mail`, `none` (no URL; the source's own wording
  in `purchase_path_evidence`), `unknown` (nothing verified - what every
  Florida production source carries, because no county page has been read
  from this repository).
- **URL trust** (`untrusted_reason`): not https, the list page or document
  itself, a bare homepage, a search engine, a blocked vendor's domain, a
  search-results page - refused whatever rule matched.
- The lifecycle carries a registry-stated non-URL mode into
  `otc_provenance.purchase_path_mode` and its basis text ("in person only
  process published by the source: <wording>"); no URL is ever invented.

Customer wording: "Online link for the property", "Instructions page",
"Application page", "In-person process only (published by the source; no
online path)", "Phone or mail process", "No online purchase link on file",
"Not yet verified".

## 4. Lifecycle

`inventory_status_writer.plan()` names the transition of every change:
`newly_observed`, `status_changed`, `removed` (left the list - `closed`,
never sold), `result_published` (the list's own "Sold To" column or a
source status). The observation row carries it once migration 022's
column exists (probed). Absence still closes only under a COMPLETE / EMPTY
county read; FAILED, INCOMPLETE and SOURCE_UNAVAILABLE close nothing.

## 5. Enrichment

`enrich_property_details.fetch_county_batch` fills each county's slice from
its Available rows first, then every other ledger, deduplicated and capped
at the slice; the FDOR safety rules (identifier plausibility, unique
match, layer errors are not misses, counts-only logs) are untouched.
Imagery stays USDA NAIP; no Street View.

## 6. Freshness

`unit_freshness.public_report` adds per unit: `backoff` (+ reason),
`stale` (no complete read in 36 h), `source_unavailable` (FAILED with a
TRANSPORT_ / PROXY_ / ACCESS_ category, or the reader-side
SOURCE_UNAVAILABLE); per ledger: `backoff`, `source_unavailable` counts.
Migration 022 adds `county_source_registry.last_error_category` so the
Dashboard's per-county rows can say "source unavailable at the last
attempt - inventory kept, nothing closed", "no complete read in the last 36
hours", "back-off: attempted at most once per 48 hours".

## 7. Customer surface

- **Filters** (Available only, automatic, no Search button): purchase
  path, amount (published / not), availability status, acreage minimum,
  read from the source in the last 14 days - each on a stored field.
- **Provenance card**: Availability evidence (basis + observed date), Last
  verified, Source date, Purchase link source, How to purchase (the mode), and the
  legend: *Published by the source* / *Derived by our system* (named as
  such: parcel match, geocoder, FEMA) / *Not published*.
- **Map**: an Available row with coordinates is a pin; without them it is
  a strip card and the preview says "Not yet geocoded" - never a guessed
  point. The preview leads with Availability, Purchase path, Amount kind.
- **Withheld inventory** is counted on the ledger page and the Dashboard.

## 8. Commercial release (2026-09-30, migration 023)

Everything below is on top of sections 1-7 and is what the customer
AVAILABLE ledger ships with. Migrations 021, 022 and 023 are APPLIED to
production (owner-authorized sprint activation, 2026-09-30); every laft run
now writes the lifecycle, the status history, the freshness rows, the
publication decision and - once evidence exists - the typed purchase path.

### 8.1 The purchase-path engine (`scripts/purchase_path_engine.py`)

One place establishes "how does a buyer act on this row", from evidence
only. Ten path types: `direct_property_url`, `county_instructions`,
`application_page`, `application_download`, `in_person`, `phone_mail`,
`quoted_amount`, `amount_plus_costs`, `amount_on_application`,
`none_published`. A stored path carries its type, the URL (the four URL
types only - 017's `purchase_url` + kind), the evidence, the date the
evidence was observed and its scope: `property` (a link the source
published for this parcel) or `source` (the source's own process, page or
wording, the same for every parcel it lists).

Evidence comes from three tables and nothing else, in this precedence:
the row's own link established by an enabled rule
(`data/laft_purchase_link_rules.csv`, property scope); a source-scope row
in `data/purchase_path_evidence.csv` (a human verified the source's own
page - ships empty); a PRODUCTION_VERIFIED registry row's source-level
`purchase_url` + kind, its stated non-URL mode with the source's wording,
or its `QUOTED_ON_APPLICATION` amount kind. The engine refuses, whatever
proposed it: not https, the list page or the document itself, a bare
homepage, a search engine, a blocked vendor's host, a search-results page,
a guessed URL pattern (placeholders / templates), and a third-party host
the evidence row did not explicitly permit. A refusal is a reason in
`otc_provenance.purchase_url`, never a path. Nothing verified = the four
columns stay NULL; `none_published` is written only from the source's own
wording (registry mode `none`), because "the source publishes no path" is
itself a claim.

`scripts/laft_lifecycle.py` runs the engine per observed row
(`PathContext`), carries the derived mode into `otc_provenance` as before,
and writes the four columns only once migration 023 is probed. The gate
report carries `purchase_paths` (rows / evaluated / by type / by scope /
with URL) - the purchase-path coverage metric.

### 8.2 Source-published outcomes (`scripts/outcome_ingest.py`)

A result (status, date, amount, party) is stored only when the source
published it and an enabled, verified rule in
`data/outcome_column_rules.csv` names which column carries what; a party
is carried only under a rule that says publishing it is permitted. The
table ships empty. The FL lists' own "Sold To" column keeps producing the
`sold` status through the identity files; the date / amount / party of
such a result reach `properties.result_*` and the history row only through
a rule. Absence is never a result.

### 8.3 Lifecycle history

`inventory_status_writer.plan()` now names `reactivated` (a row stored
`closed` that is on the list again) beside `newly_observed` /
`status_changed` / `removed` / `result_published`; on a 022-only
deployment it is sent as `status_changed` (022's check constraint), on 023
as itself. "Continued" is `properties.last_seen_at`, not a row per run.
The full property page's "What happened before?" reads the append-only
`inventory_status_observations` for the row (approved read), plus
`first_seen_at` / `delisted_at` / `last_seen_at`, in date order, with the
wording "a removal is never a sale".

### 8.4 Admin publication governance

`public.source_publication_reviews` (023) is the append-only decision
record: publication status, restrictions, decision note, evidence, notes,
decided_by, decided_at, next_review. The admin panel (`#adminPublication`,
rendered only for `IS_ADMIN`; the table is unreadable to customers) lists
every registry source of the page's state with its current status,
restrictions, governance / verification state and latest decision, and
records a new decision. `scripts/publication_gate.py` applies the latest
decision per source ONLY after `publication_problems` validates it exactly
like a CSV value: a blocked vendor, a source under legal review or a
non-production candidate cannot be approved from the panel; RESTRICTED
needs a reason; an approval needs evidence. Rejected reviews are reported
by name; an applied one is written back to the `county_source_registry`
table's publication columns so the Dashboard and the gate agree.

### 8.5 Customer surface

- **Available decision page** (`availableDecisionHtml`, section
  "Decision" after "At a glance" on every Available row): What is it? Is
  it available now? How do I buy it? What does it cost? Where is it? What
  is known about it? What is not known? Where did the data come from? How
  fresh is it? What happened before? Is this parcel in another ledger? -
  each from a stored field or its stated absence; no score, badge,
  estimate or recommendation.
- **Filters** (Available only, automatic): land use (only values the rows
  carry), coordinates on file, county value on file - beside purchase
  path, amount, availability, acreage, read in the last 14 days.
- **Map preview**: last verified, source date, same parcel in other
  ledgers.
- **Freshness per property**: source date (`list_as_of` /
  `source_published_at`), observation date
  (`inventory_status_observed_at`), last verified (`last_seen_at`), and
  the county source's own state (last complete read, source unavailable,
  back-off, row count) from `county_source_registry`.
- **Available export**: published fields only (identity, availability,
  typed purchase path + link, amount, tax-roll facts, coordinates, source
  list / document, source dates, first observed, last read). No
  governance field, no provenance JSON, no basis wording, no harvester
  tag, no diagnostics; withheld inventory never reaches the export.
- **Provenance card**: a "Path evidence" line (the typed path with its
  evidence and observed date, or "not yet evaluated").

### 8.6 Workflow

`harvest-and-sync.yml` takes a `job` input on manual dispatch (all /
deeds / certificates / laft / texas / backup, default all = the
historical behaviour) so the AVAILABLE path can be run by hand without
re-hitting LGBS; schedules are unchanged and the texas job is still never
scheduled.

## 9. Not done, on purpose (as of the commercial release; see section 10)

At the commercial release no Florida county's purchase page had been read
from this repository, so no source-level path or mode was asserted for a
production source and no rule was enabled - section 10 records the first
fifteen counties whose page was actually read. No sale-result mapping was added (no approved source
publishes one beyond the LAFT lists' own "Sold To" column, already
handled). LGBS not retried, GovEase not implemented, blocked vendors
untouched, no state activated, migrations 020 / 021 / 022 unapplied.

## 10. Customer value / evidence acquisition (2026-09-30)

### 10.1 The capture job

`scripts/capture_purchase_evidence.py` reads, on GitHub's runners (the
sandbox cannot reach county sites), the canonical / document / purchase
URLs of every FL AVAILABLE production source in the registry and writes a
**value-free** capture to `out/public/purchase-evidence-capture.json`: the
page title, headings, the anchors whose text uses purchase vocabulary,
the sentences outside tables that carry no 7+ digit run (so no parcel,
case or amount is ever captured), phone numbers and e-mail addresses,
plus the HTTP status / error per URL. PDFs go through `pdfplumber` with
the same sentence filter. It runs as the manual-only `evidence` job of
`harvest-and-sync.yml` (`job=evidence`; inputs `evidence_counties`,
`evidence_realauction_dates`), prints a compact digest into the job log
(`--digest`, read from the log since artifact downloads are blocked from
the sandbox) and uploads the same evidence-only artifact layout as every
other job. It writes nothing to the database. Schedules are unchanged.

`capture_realauction` fetches a RealAuction past-sale page
(`zaction=AUCTION&zmethod=PREVIEW&AuctionDate=`) and records only the
labels and status vocabulary it finds. Finding: anonymous requests get
the **login form** ("User Name" / "User Password", zero items) - the
published results sit behind an account, so no auction outcome is
ingested from RealAuction (section 10.5).

### 10.2 The evidence record (v2)

`purchase_path_engine.EVIDENCE_COLUMNS` = the ten original columns +
`evidence_url, evidence_type, source_title, instructions, review_state,
proves, does_not_prove`. `EVIDENCE_TYPES` = county_page /
county_document / property_page / registry / other; `REVIEW_STATES` =
verified / needs_review / restricted. A row is **applicable** only when
enabled AND `review_state == "verified"` AND `evidence_url` is https and
not a search engine or blocked vendor; `load_evidence` refuses an enabled
row lacking any of that and still reads a v1 header. A county-specific
row beats a `*` row. `PurchasePath.provenance()` carries
`purchase_evidence_url / _type / _title`, `purchase_instructions` and
`purchase_path_observed_on` into `otc_provenance` (merged by
`laft_lifecycle.provenance_payload`), so a customer sees where the
process was read and what the source says, next to the typed path.

### 10.3 The committed rows (run 36698285461, observed 2026-09-30)

Fifteen FL counties, all SOURCE scope, all quoting the source's own
wording, each with the page or document it was read from:

| County | Type | What the source publishes |
|---|---|---|
| Brevard | phone_mail | written request (e-mail / fax / mail) for the minimum bid; pay in Titusville in certified funds |
| Calhoun, Madison, Sumter, Taylor | quoted_amount | "amounts listed are no longer the opening bid; contact the Clerk's Office to calculate" |
| Citrus | phone_mail | e-mail TaxDeeds@CitrusClerk.org with Case # and Certificate #, or phone |
| Clay | phone_mail | e-mail the Clerk with certificate numbers; ~72 h for the price |
| Dixie | in_person | in person only, certified / cashier's check, no electronic payment |
| Franklin | quoted_amount | amounts are estimates; Tax Collector quotes the exact amount |
| Hernando | quoted_amount | contact the Tax Deed Department for the purchase amount |
| Leon | phone_mail | e-mail Clerk_TaxDeedAdmin@leoncountyfl.gov with parcel and address |
| Levy | phone_mail | phone or e-mail for the current purchase price |
| Orange | amount_plus_costs | opening bid plus omitted years' taxes, s. 197.542(1) |
| Pasco | phone_mail | written request to the Dade City office; then in person, certified funds |
| Volusia | quoted_amount | list document: call the Tax Deed Department for the current price |

Not recorded, because the capture found no process wording: the realTDM
counties, the Pioneer portals without a text block (Bay, Duval, Palm
Beach, Okeechobee, St. Johns, Martin), Hillsborough, Holmes, Hamilton,
Hardee, Indian River, Lafayette, Gulf, Gadsden, Glades, Marion, Manatee
(amount composition only). Unreachable from the runner: Bradford,
Columbia, Escambia, St. Lucie, Union (403), Walton (reset), Hendry (404).
No property-level URL was recorded for any county (none is published).
Every row is `enabled=yes`, `third_party_permitted=no`, `url` empty.

### 10.4 Property intelligence, lifecycle, cross-ledger, decision pages

- Land use falls back to the DOR use code label (`dorUseLabel`) when
  `land_use` is empty; never a guess. First-observed shows "First
  recorded by this app" with the tracking-began note; `properties` has no
  `created_at` and `first_seen_at` is NULL on every laft row - not
  backfilled, not invented.
- `relatedWhen(o)` / `crossLedgerSummary(p)`: same parcel (exact state /
  county / parcel) in another ledger, "Currently listed" or "Previously
  listed" from `isGone` and its date; no probabilistic matching.
- Available decision: thirteen questions (`what, why, available, how,
  proof, cost, where, known, unknown, source, fresh, history, related`).
  Auction decision (`auctionDecisionHtml`): what / when / bid / known /
  source / result / related / unknown; the result row reads a result
  status only from `inventory_status` with the source's raw wording,
  otherwise "Not published by the source ..." (past date) or "No result
  yet". Certificate decision (`certificateDecisionHtml`): what / amount /
  terms / redemption / source / related / unknown. Certificates get the
  section nav.
- Exports: `availableCols` + Purchase Instructions / Purchase Evidence
  Page / Same Parcel In Other Ledgers; auction `cols` + Result (per the
  source) / Result Source Wording / Result Date / Same Parcel;
  `certificateCols` (new) - no governance, evidence id or diagnostic
  column anywhere. `sw.js` -> `tdw-shell-v50`.

### 10.5 Gaps that stay explicit

No approved auction source publishes an accessible result: RealAuction
is a login wall, the FL deed harvester captures no status wording, TX
rows carry a NULL `tx_sale_status`. `auction_events` holds 914 events
and zero outcomes; nothing was inferred. Winning bid, bidder count and
bidder identity stay forbidden. Seventeen active FL rows have no
coordinates (Citrus 5, Hillsborough 3, Volusia 3, Indian River 2,
Escambia / Hendry / Miami-Dade / Pasco 1 each) and are shown as "Not yet
geocoded".

## 11. Acquisition path (2026-09-30)

An AVAILABLE property is commercially useful only when the customer can
see exactly how to acquire it. The objective is a verified, actionable
acquisition path backed by the county's own evidence - online, PDF,
e-mail, phone, mail or in person - not a purchase URL.

### 11.1 The evidence record (v3)

`purchase_path_engine.EVIDENCE_COLUMNS` = v2 + `office, address, phone,
email, mailing_address, steps, application_url, payment`. Every value is
quoted from the evidence page; a blank means the source did not publish
it. `steps` is `" | "`-separated and sequential. An `application_url`
must be an https county document (search engines, blocked vendors and
template URLs are refused). `PurchasePath.channels` lists the published
ways to act; `acquisition_mode()` names what the customer does first:
online / application / instructions / email / phone / mail / in_person /
contact (the quoted-amount family: the source's own process is "ask the
county for the amount") / multi_step (three or more published steps,
unless the source says in person) / none. `PurchasePath.provenance()`
now carries `otc_provenance.acquisition` (mode, channels, office,
address, phone, email, mailing_address, steps, application_url, payment,
evidence_url, observed_on). No schema change: the 023 columns are
untouched.

### 11.2 Property-to-source match

`laft_lifecycle.source_match_of()` writes `otc_provenance.source_match`
on every observed row: the identifier the row was read under (`case_no`,
else `parcel`; `parcel` and `certificate_no` alongside when published),
the list / document it was read from, the read time and the basis - the
harvester's own read, keyed exactly as the sync upserts. Never an owner
name or address match. A row with neither identifier is not an
observation (`identity_key`).

### 11.3 The committed rows

The fifteen FL rows (section 10.3) now carry the office, the published
phone / e-mail / mailing address, the in-person address where published
(Citrus, Pasco), the sequential steps and the payment method (Brevard,
Dixie, Pasco). Modes: Brevard and Pasco multi_step; Dixie in_person;
Citrus and Leon email; Clay and Levy phone; Calhoun, Franklin, Hernando,
Madison, Orange, Sumter, Taylor, Volusia contact. Protected e-mail
addresses on the Clay and Levy portal pages stay blank - the steps say
where the address is shown. No application document is recorded for any
county (none was captured).

### 11.4 Customer page

The Available decision reads, in order: what property; **why it is in
Available** (inventory type, basis, the county list page and list
document with the source date, and "Matched to the list by case no … ·
read …"); is it verified as available; **how do I acquire it** (the mode,
the numbered steps, the application / instructions document and the
county's process page, the source's wording, observed date); **who do I
contact, and where do I go** (office, in-person address, phone as a
`tel:` link, e-mail as a `mailto:` link, mailing address, payment); what
proves it; cost; where; known; unknown (the gap is "Acquisition path not
yet verified", never a missing hyperlink); source documents (list, list
document, evidence page, application document); freshness; history;
other ledgers. "At a glance" carries a "How to acquire" cell, every card
an "Acquire" fact, the Map preview a "How to acquire" line, the Inventory
& Purchase card a "How to acquire" row above the legacy "Purchase link"
row. The Available export adds Acquisition Path, Acquisition Steps,
County Office / Phone / E-mail / Address / Mailing Address, Payment,
Application / Instructions Document and Matched To Source By.

### 11.5 Metrics

`purchase_path_engine.measure()` reports, per AVAILABLE row: with a
source listing / document, property-to-source matched, with a verified
acquisition path (a stored type other than none_published), by mode,
with contact, with steps, with a direct document, with a source date,
with a last-verified date, unverified - and the two percentages the
product tracks: % with a verified actionable acquisition path and % with
a verified source listing. The laft job's publication-gate step prints
them. `publication.measure()` counts an offline process as a purchase
path.

## 12. Acquisition coverage and failure-safe evidence (2026-09-30)

### 12.1 Following the source to the process

`capture_purchase_evidence.py --follow` (the manual evidence job passes
it) fetches up to six links per county that are PRESENT on an approved
source page, carry tax-deed context in their text or URL, and are not a
search engine, social site or blocked vendor; documents first. Followed
process pages keep their table text; the inventory list itself never
does. Links carrying a 7+ digit run (per-parcel links) are never
captured. Two runs (36717720575, 36718027256) covered the counties with
active unverified inventory:

| County | Result |
|---|---|
| Marion | Process found on the Clerk's "Tax Deeds & Lands Available for Taxes" page (linked from the source page): recorded as `amount_plus_costs`, four steps, payment method. No phone recorded - the page shows two numbers and the capture does not establish which one handles this process. |
| Indian River | FAQ page linked; it covers the auction sale only, not Lands Available purchases. Not evidence. |
| Bay, Duval, Palm Beach | Pioneer portal text names only the Official Records office for certified copies. Not a purchase process. |
| Alachua, Highlands, Lee, Polk, Sarasota, Miami-Dade | realTDM pages publish only the category labels "List of Lands - BOCC / Public Purchase". No process, no link. |
| Hillsborough, Osceola, Putnam, Gadsden | No process wording and no process link on the source page. |
| Escambia, St. Lucie | HTTP 403 from the runner. |
| Hendry | List document 404. |

No application or instructions document is linked from any of these
source pages, so no `application_url` is recorded.

### 12.2 A failed read never erases evidence

`laft_lifecycle.carry_plan()` runs on every lifecycle pass for active
rows the run did NOT read (county INCOMPLETE, SOURCE_UNAVAILABLE, FAILED,
STALE or not run). It only adds: the deterministic match from the
identity the sync upserted the row under (`case_no`, else parcel) and
the list / document it was last read from, dated by `last_seen_at`
(the basis says it was carried); and the acquisition record the verified
evidence table establishes for the row's source + county. It never
removes a key, never touches `last_seen_at`, never matches by name,
address or proximity, and skips rows never stamped by a read. An
explicit change (an evidence row removed or rewritten) takes effect on
the next read of the county.

### 12.3 Metrics

`measure()` also reports `with_complete_record` (steps AND a published
channel: phone, e-mail, in-person address, mailing address, application
document or an online URL), `with_in_person` and
`with_application_document`. A typed mode without a complete record
counts as a path, never as a complete record.

### 12.4 Customer page

"How do I acquire it?" adds the first step, the scope ("County process:
... not an approval for this parcel, and being listed does not prove the
county will still sell it today" / "Property-specific: ...") and
"Acquisition process last verified <date>", with a retry note when the
county's source was not fully read at the last attempt - the verified
process stays. "Why is it in Available?" says whether the parcel was
matched on the official list.
