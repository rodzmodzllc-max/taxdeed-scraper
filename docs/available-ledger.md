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

## 8. Not done, on purpose

No Florida county's purchase page has been read from this repository, so
no source-level path or mode is asserted for a production source; no
rule is enabled. No sale-result mapping was added (no approved source
publishes one beyond the LAFT lists' own "Sold To" column, already
handled). LGBS not retried, GovEase not implemented, blocked vendors
untouched, no state activated, migrations 020 / 021 / 022 unapplied.
