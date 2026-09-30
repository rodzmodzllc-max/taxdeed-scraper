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

## 9. Not done, on purpose

No Florida county's purchase page has been read from this repository, so
no source-level path or mode is asserted for a production source; no
rule is enabled. No sale-result mapping was added (no approved source
publishes one beyond the LAFT lists' own "Sold To" column, already
handled). LGBS not retried, GovEase not implemented, blocked vendors
untouched, no state activated, migrations 020 / 021 / 022 unapplied.
