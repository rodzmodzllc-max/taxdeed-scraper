# State-by-state coverage (generated)

Built by `scripts/build_state_coverage.py` from the registry, the rules, the ledger table, the acquisition evidence and the counts-only snapshots `coverage-2026-10-10.json` (measured 2026-10-10T10:26:40Z) and `source-quality-2026-10-10.json` (measured 2026-10-10 15:31:38.334866+00). Every count carries its denominator; nothing here is read live. Classification precedence and meanings: `harvesters/governance/state_coverage.py`.

| Classification | State x ledger |
|---|---|
| CURRENT | 12 |
| OFFERED_SOURCE_NOT_IMPLEMENTED | 1 |
| OFFERED_VERIFIED_EMPTY | 1 |
| RECORDS_WITHHELD_NO_PATH | 1 |
| RULES_NOT_VERIFIED | 19 |
| SOURCE_FAILED_OR_STALE | 4 |
| SOURCE_IMPLEMENTED_NEVER_READ | 1 |

## CO

| Ledger | Eligibility | Classification | Sources known / implemented / approved | Active rows | Never stamped | Older than 36 h | Acquisition units VERIFIED | Next action |
|---|---|---|---|---|---|---|---|---|
| AUCTIONS | COUNTY_DEPENDENT | SOURCE_IMPLEMENTED_NEVER_READ | 3 / 3 / 2 | - | - | - | 0 of 0 | Dispatch the source's job once (owner decision) and read its status file; a failure is a source problem, not an empty list. |
| AVAILABLE | NOT_VERIFIED | RULES_NOT_VERIFIED | 0 / 0 / 0 | - | - | - | 0 of 0 | Read the state's statute / an official county procedure and record it in data/state_rules.csv before any source is built. |
| LIENS_CERTIFICATES | COUNTY_DEPENDENT | CURRENT | 2 / 2 / 2 | 141 | 0 | 0 | 0 of 0 | Keep reading; raise field population where a verified official layer exists (see fields). |
CO - AUCTIONS: no row and no read recorded in the snapshot
CO - AVAILABLE: eligibility NOT_VERIFIED; no production source

CO - LIENS_CERTIFICATES field population (active rows, snapshot): amount 141/141; bid_amount_mismatch 0/141; coords 117/141; dup_parcel 0/141; flood_checked 117/141; laft_bid_without_amount 0/141; link_not_https 0/141; list_as_of 3/141; list_as_of_future 3/141; never_seen 0/141; parcel 141/141; parcel_no_digit 0/141; past_sale 0/141; path_typed 141/141; provenance 141/141; seen_gt36h 0/141; seen_order_bad 0/141; source_link 141/141
CO - LIENS_CERTIFICATES: 141 active rows; 0 never stamped, 0 older than 36 h at the snapshot

## FL

| Ledger | Eligibility | Classification | Sources known / implemented / approved | Active rows | Never stamped | Older than 36 h | Acquisition units VERIFIED | Next action |
|---|---|---|---|---|---|---|---|---|
| AUCTIONS | OFFERED | CURRENT | 47 / 47 / 47 | 1185 | 251 | 69 | 0 of 0 | Keep reading; raise field population where a verified official layer exists (see fields). |
| AVAILABLE | OFFERED | CURRENT | 64 / 52 / 52 | 157 | 3 | 13 | 19 of 52 | Keep reading; raise field population where a verified official layer exists (see fields). |
| LIENS_CERTIFICATES | OFFERED | SOURCE_FAILED_OR_STALE | 33 / 33 / 33 | 1611 | 1611 | 0 | 0 of 0 | Investigate the last read's error category (registry last_error_category / unit freshness) and restore the read; rows are kept, never closed, until a COMPLETE read. |

FL - AUCTIONS field population (active rows, snapshot): amount 1184/1185; bid_amount_mismatch 0/1185; coords 942/1185; dup_parcel 0/1185; flood_checked 942/1185; laft_bid_without_amount 0/1185; link_not_https 0/1185; list_as_of 0/1185; list_as_of_future 0/1185; never_seen 251/1185; parcel 1146/1185; parcel_no_digit 0/1185; past_sale 4/1185; path_typed 0/1185; provenance 243/1185; seen_gt36h 78/1185; seen_order_bad 0/1185; source_link 1185/1185
FL - AUCTIONS: 1185 active rows; 251 never stamped, 69 older than 36 h at the snapshot

FL - AVAILABLE field population (active rows, snapshot): amount 142/157; bid_amount_mismatch 0/157; coords 141/157; dup_parcel 0/157; flood_checked 141/157; laft_bid_without_amount 0/157; link_not_https 0/157; list_as_of 0/157; list_as_of_future 0/157; never_seen 3/157; parcel 156/157; parcel_no_digit 0/157; past_sale 0/157; path_typed 43/157; provenance 100/157; seen_gt36h 13/157; seen_order_bad 0/157; source_link 157/157
FL - AVAILABLE: 157 active rows; 3 never stamped, 13 older than 36 h at the snapshot

FL - LIENS_CERTIFICATES field population (active rows, snapshot): amount 1610/1611; bid_amount_mismatch 0/1611; coords 839/1611; dup_parcel 0/1611; flood_checked 839/1611; laft_bid_without_amount 0/1611; link_not_https 0/1611; list_as_of 0/1611; list_as_of_future 0/1611; never_seen 1611/1611; parcel 1611/1611; parcel_no_digit 0/1611; past_sale 0/1611; path_typed 0/1611; provenance 25/1611; seen_gt36h 0/1611; seen_order_bad 0/1611; source_link 1611/1611
FL - LIENS_CERTIFICATES: 1611 of 1611 active rows never stamped, 0 read more than 36 h before the snapshot

## LA

| Ledger | Eligibility | Classification | Sources known / implemented / approved | Active rows | Never stamped | Older than 36 h | Acquisition units VERIFIED | Next action |
|---|---|---|---|---|---|---|---|---|
| AUCTIONS | NOT_VERIFIED | RULES_NOT_VERIFIED | 0 / 0 / 0 | - | - | - | 0 of 0 | Read the state's statute / an official county procedure and record it in data/state_rules.csv before any source is built. |
| AVAILABLE | COUNTY_DEPENDENT | SOURCE_FAILED_OR_STALE | 1 / 1 / 1 | 10334 | 0 | 10334 | 1 of 1 | Investigate the last read's error category (registry last_error_category / unit freshness) and restore the read; rows are kept, never closed, until a COMPLETE read. |
| LIENS_CERTIFICATES | NOT_VERIFIED | RULES_NOT_VERIFIED | 0 / 0 / 0 | - | - | - | 0 of 0 | Read the state's statute / an official county procedure and record it in data/state_rules.csv before any source is built. |
LA - AUCTIONS: eligibility NOT_VERIFIED; no production source

LA - AVAILABLE field population (active rows, snapshot): amount 0/10334; bid_amount_mismatch 0/10334; coords 10334/10334; dup_parcel 0/10334; flood_checked 10334/10334; laft_bid_without_amount 0/10334; link_not_https 0/10334; list_as_of 10334/10334; list_as_of_future 0/10334; never_seen 0/10334; parcel 10334/10334; parcel_no_digit 0/10334; past_sale 0/10334; path_typed 10334/10334; provenance 10334/10334; seen_gt36h 10334/10334; seen_order_bad 0/10334; source_link 10334/10334
LA - AVAILABLE: 0 of 10334 active rows never stamped, 10334 read more than 36 h before the snapshot
LA - LIENS_CERTIFICATES: eligibility NOT_VERIFIED; no production source

## MI

| Ledger | Eligibility | Classification | Sources known / implemented / approved | Active rows | Never stamped | Older than 36 h | Acquisition units VERIFIED | Next action |
|---|---|---|---|---|---|---|---|---|
| AUCTIONS | COUNTY_DEPENDENT | CURRENT | 77 / 77 / 2 | 38 | 0 | 0 | 0 of 0 | Keep reading; raise field population where a verified official layer exists (see fields). |
| AVAILABLE | COUNTY_DEPENDENT | CURRENT | 14 / 14 / 3 | 30775 | 0 | 30770 | 2 of 14 | Keep reading; raise field population where a verified official layer exists (see fields). |
| LIENS_CERTIFICATES | NOT_VERIFIED | RULES_NOT_VERIFIED | 0 / 0 / 0 | - | - | - | 0 of 0 | Read the state's statute / an official county procedure and record it in data/state_rules.csv before any source is built. |

MI - AUCTIONS field population (active rows, snapshot): amount 38/38; bid_amount_mismatch 0/38; coords 38/38; dup_parcel 0/38; flood_checked 38/38; laft_bid_without_amount 0/38; link_not_https 0/38; list_as_of 0/38; list_as_of_future 0/38; never_seen 0/38; parcel 38/38; parcel_no_digit 0/38; past_sale 35/38; path_typed 38/38; provenance 38/38; seen_gt36h 0/38; seen_order_bad 0/38; source_link 38/38
MI - AUCTIONS: 38 active rows; 0 never stamped, 0 older than 36 h at the snapshot

MI - AVAILABLE field population (active rows, snapshot): amount 0/30775; bid_amount_mismatch 0/30775; coords 30771/30775; dup_parcel 0/30775; flood_checked 434/30775; laft_bid_without_amount 0/30775; link_not_https 0/30775; list_as_of 0/30775; list_as_of_future 0/30775; never_seen 0/30775; parcel 30775/30775; parcel_no_digit 0/30775; past_sale 0/30775; path_typed 5/30775; provenance 30775/30775; seen_gt36h 30770/30775; seen_order_bad 0/30775; source_link 30775/30775
MI - AVAILABLE: 30775 active rows; 0 never stamped, 30770 older than 36 h at the snapshot
MI - LIENS_CERTIFICATES: eligibility NOT_VERIFIED; no production source

## MN

| Ledger | Eligibility | Classification | Sources known / implemented / approved | Active rows | Never stamped | Older than 36 h | Acquisition units VERIFIED | Next action |
|---|---|---|---|---|---|---|---|---|
| AUCTIONS | NOT_VERIFIED | RULES_NOT_VERIFIED | 0 / 0 / 0 | - | - | - | 0 of 0 | Read the state's statute / an official county procedure and record it in data/state_rules.csv before any source is built. |
| AVAILABLE | COUNTY_DEPENDENT | CURRENT | 3 / 3 / 1 | 2 | 0 | 0 | 1 of 3 | Keep reading; raise field population where a verified official layer exists (see fields). |
| LIENS_CERTIFICATES | NOT_VERIFIED | RULES_NOT_VERIFIED | 0 / 0 / 0 | - | - | - | 0 of 0 | Read the state's statute / an official county procedure and record it in data/state_rules.csv before any source is built. |
MN - AUCTIONS: eligibility NOT_VERIFIED; no production source

MN - AVAILABLE field population (active rows, snapshot): amount 2/2; bid_amount_mismatch 0/2; coords 2/2; dup_parcel 0/2; flood_checked 2/2; laft_bid_without_amount 0/2; link_not_https 0/2; list_as_of 0/2; list_as_of_future 0/2; never_seen 0/2; parcel 2/2; parcel_no_digit 0/2; past_sale 0/2; path_typed 0/2; provenance 2/2; seen_gt36h 0/2; seen_order_bad 0/2; source_link 2/2
MN - AVAILABLE: 2 active rows; 0 never stamped, 0 older than 36 h at the snapshot
MN - LIENS_CERTIFICATES: eligibility NOT_VERIFIED; no production source

## MO

| Ledger | Eligibility | Classification | Sources known / implemented / approved | Active rows | Never stamped | Older than 36 h | Acquisition units VERIFIED | Next action |
|---|---|---|---|---|---|---|---|---|
| AUCTIONS | NOT_VERIFIED | RULES_NOT_VERIFIED | 0 / 0 / 0 | - | - | - | 0 of 0 | Read the state's statute / an official county procedure and record it in data/state_rules.csv before any source is built. |
| AVAILABLE | COUNTY_DEPENDENT | CURRENT | 2 / 2 / 1 | 9759 | 0 | 0 | 1 of 2 | Keep reading; raise field population where a verified official layer exists (see fields). |
| LIENS_CERTIFICATES | NOT_VERIFIED | RULES_NOT_VERIFIED | 0 / 0 / 0 | - | - | - | 0 of 0 | Read the state's statute / an official county procedure and record it in data/state_rules.csv before any source is built. |
MO - AUCTIONS: eligibility NOT_VERIFIED; no production source

MO - AVAILABLE field population (active rows, snapshot): amount 0/9759; bid_amount_mismatch 0/9759; coords 0/9759; dup_parcel 0/9759; flood_checked 0/9759; laft_bid_without_amount 0/9759; link_not_https 0/9759; list_as_of 0/9759; list_as_of_future 0/9759; never_seen 0/9759; parcel 9759/9759; parcel_no_digit 0/9759; past_sale 0/9759; path_typed 0/9759; provenance 9759/9759; seen_gt36h 0/9759; seen_order_bad 0/9759; source_link 9759/9759
MO - AVAILABLE: 9759 active rows; 0 never stamped, 0 older than 36 h at the snapshot
MO - LIENS_CERTIFICATES: eligibility NOT_VERIFIED; no production source

## OK

| Ledger | Eligibility | Classification | Sources known / implemented / approved | Active rows | Never stamped | Older than 36 h | Acquisition units VERIFIED | Next action |
|---|---|---|---|---|---|---|---|---|
| AUCTIONS | NOT_VERIFIED | RULES_NOT_VERIFIED | 0 / 0 / 0 | - | - | - | 0 of 0 | Read the state's statute / an official county procedure and record it in data/state_rules.csv before any source is built. |
| AVAILABLE | COUNTY_DEPENDENT | CURRENT | 1 / 1 / 1 | 195 | 0 | 0 | 1 of 1 | Keep reading; raise field population where a verified official layer exists (see fields). |
| LIENS_CERTIFICATES | NOT_VERIFIED | RULES_NOT_VERIFIED | 0 / 0 / 0 | - | - | - | 0 of 0 | Read the state's statute / an official county procedure and record it in data/state_rules.csv before any source is built. |
OK - AUCTIONS: eligibility NOT_VERIFIED; no production source

OK - AVAILABLE field population (active rows, snapshot): amount 195/195; bid_amount_mismatch 0/195; coords 0/195; dup_parcel 0/195; flood_checked 0/195; laft_bid_without_amount 0/195; link_not_https 0/195; list_as_of 0/195; list_as_of_future 0/195; never_seen 0/195; parcel 195/195; parcel_no_digit 0/195; past_sale 0/195; path_typed 195/195; provenance 195/195; seen_gt36h 0/195; seen_order_bad 0/195; source_link 195/195
OK - AVAILABLE: 195 active rows; 0 never stamped, 0 older than 36 h at the snapshot
OK - LIENS_CERTIFICATES: eligibility NOT_VERIFIED; no production source

## PA

| Ledger | Eligibility | Classification | Sources known / implemented / approved | Active rows | Never stamped | Older than 36 h | Acquisition units VERIFIED | Next action |
|---|---|---|---|---|---|---|---|---|
| AUCTIONS | NOT_VERIFIED | RULES_NOT_VERIFIED | 0 / 0 / 0 | - | - | - | 0 of 0 | Read the state's statute / an official county procedure and record it in data/state_rules.csv before any source is built. |
| AVAILABLE | COUNTY_DEPENDENT | CURRENT | 2 / 2 / 1 | 376 | 0 | 0 | 1 of 2 | Keep reading; raise field population where a verified official layer exists (see fields). |
| LIENS_CERTIFICATES | NOT_VERIFIED | RULES_NOT_VERIFIED | 0 / 0 / 0 | - | - | - | 0 of 0 | Read the state's statute / an official county procedure and record it in data/state_rules.csv before any source is built. |
PA - AUCTIONS: eligibility NOT_VERIFIED; no production source

PA - AVAILABLE field population (active rows, snapshot): amount 375/376; bid_amount_mismatch 0/376; coords 0/376; dup_parcel 0/376; flood_checked 0/376; laft_bid_without_amount 0/376; link_not_https 0/376; list_as_of 376/376; list_as_of_future 0/376; never_seen 0/376; parcel 376/376; parcel_no_digit 0/376; past_sale 0/376; path_typed 0/376; provenance 376/376; seen_gt36h 0/376; seen_order_bad 0/376; source_link 376/376
PA - AVAILABLE: 376 active rows; 0 never stamped, 0 older than 36 h at the snapshot
PA - LIENS_CERTIFICATES: eligibility NOT_VERIFIED; no production source

## SC

| Ledger | Eligibility | Classification | Sources known / implemented / approved | Active rows | Never stamped | Older than 36 h | Acquisition units VERIFIED | Next action |
|---|---|---|---|---|---|---|---|---|
| AUCTIONS | COUNTY_DEPENDENT | CURRENT | 3 / 3 / 2 | 853 | 0 | 0 | 0 of 0 | Keep reading; raise field population where a verified official layer exists (see fields). |
| AVAILABLE | COUNTY_DEPENDENT | CURRENT | 2 / 2 / 2 | 52 | 0 | 0 | 2 of 2 | Keep reading; raise field population where a verified official layer exists (see fields). |
| LIENS_CERTIFICATES | NOT_VERIFIED | RULES_NOT_VERIFIED | 0 / 0 / 0 | - | - | - | 0 of 0 | Read the state's statute / an official county procedure and record it in data/state_rules.csv before any source is built. |

SC - AUCTIONS field population (active rows, snapshot): amount 0/853; bid_amount_mismatch 0/853; coords 853/853; dup_parcel 0/853; flood_checked 853/853; laft_bid_without_amount 0/853; link_not_https 0/853; list_as_of 0/853; list_as_of_future 0/853; never_seen 0/853; parcel 853/853; parcel_no_digit 0/853; past_sale 0/853; path_typed 853/853; provenance 853/853; seen_gt36h 0/853; seen_order_bad 0/853; source_link 853/853
SC - AUCTIONS: 853 active rows; 0 never stamped, 0 older than 36 h at the snapshot

SC - AVAILABLE field population (active rows, snapshot): amount 52/52; bid_amount_mismatch 0/52; coords 0/52; dup_parcel 0/52; flood_checked 0/52; laft_bid_without_amount 0/52; link_not_https 0/52; list_as_of 0/52; list_as_of_future 0/52; never_seen 0/52; parcel 52/52; parcel_no_digit 0/52; past_sale 0/52; path_typed 52/52; provenance 52/52; seen_gt36h 0/52; seen_order_bad 0/52; source_link 52/52
SC - AVAILABLE: 52 active rows; 0 never stamped, 0 older than 36 h at the snapshot
SC - LIENS_CERTIFICATES: eligibility NOT_VERIFIED; no production source

## TN

| Ledger | Eligibility | Classification | Sources known / implemented / approved | Active rows | Never stamped | Older than 36 h | Acquisition units VERIFIED | Next action |
|---|---|---|---|---|---|---|---|---|
| AUCTIONS | NOT_VERIFIED | RULES_NOT_VERIFIED | 0 / 0 / 0 | - | - | - | 0 of 0 | Read the state's statute / an official county procedure and record it in data/state_rules.csv before any source is built. |
| AVAILABLE | COUNTY_DEPENDENT | RECORDS_WITHHELD_NO_PATH | 1 / 1 / 1 | 2038 | 0 | 0 | 0 of 1 | Capture the county's official acquisition process (job=evidence, acquisition_candidates) and record a verified evidence row; rows stay admin-only. |
| LIENS_CERTIFICATES | NOT_VERIFIED | RULES_NOT_VERIFIED | 0 / 0 / 0 | - | - | - | 0 of 0 | Read the state's statute / an official county procedure and record it in data/state_rules.csv before any source is built. |
TN - AUCTIONS: eligibility NOT_VERIFIED; no production source

TN - AVAILABLE field population (active rows, snapshot): amount 2037/2038; bid_amount_mismatch 0/2038; coords 2037/2038; dup_parcel 0/2038; flood_checked 0/2038; laft_bid_without_amount 0/2038; link_not_https 0/2038; list_as_of 0/2038; list_as_of_future 0/2038; never_seen 0/2038; parcel 2038/2038; parcel_no_digit 0/2038; past_sale 0/2038; path_typed 0/2038; provenance 2038/2038; seen_gt36h 0/2038; seen_order_bad 0/2038; source_link 2038/2038
TN - AVAILABLE: 1 acquisition unit(s), none VERIFIED: NEEDS_REVIEW 1
TN - LIENS_CERTIFICATES: eligibility NOT_VERIFIED; no production source

## TX

| Ledger | Eligibility | Classification | Sources known / implemented / approved | Active rows | Never stamped | Older than 36 h | Acquisition units VERIFIED | Next action |
|---|---|---|---|---|---|---|---|---|
| AUCTIONS | COUNTY_DEPENDENT | SOURCE_FAILED_OR_STALE | 32 / 32 / 32 | 122 | 122 | 0 | 1 of 8 | Investigate the last read's error category (registry last_error_category / unit freshness) and restore the read; rows are kept, never closed, until a COMPLETE read. |
| AVAILABLE | NOT_VERIFIED | SOURCE_FAILED_OR_STALE | 28 / 8 / 8 | 421 | 39 | 382 | 1 of 9 | Investigate the last read's error category (registry last_error_category / unit freshness) and restore the read; rows are kept, never closed, until a COMPLETE read. |
| LIENS_CERTIFICATES | NOT_VERIFIED | RULES_NOT_VERIFIED | 0 / 0 / 0 | - | - | - | 0 of 0 | Read the state's statute / an official county procedure and record it in data/state_rules.csv before any source is built. |

TX - AUCTIONS field population (active rows, snapshot): amount 122/122; bid_amount_mismatch 0/122; coords 82/122; dup_parcel 3/122; flood_checked 82/122; laft_bid_without_amount 0/122; link_not_https 0/122; list_as_of 0/122; list_as_of_future 0/122; never_seen 122/122; parcel 122/122; parcel_no_digit 0/122; past_sale 122/122; path_typed 0/122; provenance 0/122; seen_gt36h 0/122; seen_order_bad 0/122; source_link 103/122
TX - AUCTIONS: 122 of 122 active rows never stamped, 0 read more than 36 h before the snapshot; every production source is manual-only (dispatched by hand, never scheduled): the last read is the last manual dispatch

TX - AVAILABLE field population (active rows, snapshot): amount 402/421; bid_amount_mismatch 0/421; coords 421/421; dup_parcel 94/421; flood_checked 421/421; laft_bid_without_amount 402/421; link_not_https 0/421; list_as_of 0/421; list_as_of_future 0/421; never_seen 39/421; parcel 421/421; parcel_no_digit 0/421; past_sale 0/421; path_typed 183/421; provenance 382/421; seen_gt36h 382/421; seen_order_bad 0/421; source_link 421/421
TX - AVAILABLE: 39 of 421 active rows never stamped, 382 read more than 36 h before the snapshot; every production source is manual-only (dispatched by hand, never scheduled): the last read is the last manual dispatch
TX - LIENS_CERTIFICATES: eligibility NOT_VERIFIED; no production source

## WI

| Ledger | Eligibility | Classification | Sources known / implemented / approved | Active rows | Never stamped | Older than 36 h | Acquisition units VERIFIED | Next action |
|---|---|---|---|---|---|---|---|---|
| AUCTIONS | COUNTY_DEPENDENT | OFFERED_VERIFIED_EMPTY | 2 / 2 / 2 | 0 | 0 | 0 | 0 of 0 | Nothing to publish; the next scheduled read re-checks the list. |
| AVAILABLE | NOT_VERIFIED | RULES_NOT_VERIFIED | 0 / 0 / 0 | - | - | - | 0 of 0 | Read the state's statute / an official county procedure and record it in data/state_rules.csv before any source is built. |
| LIENS_CERTIFICATES | NOT_VERIFIED | RULES_NOT_VERIFIED | 0 / 0 / 0 | - | - | - | 0 of 0 | Read the state's statute / an official county procedure and record it in data/state_rules.csv before any source is built. |
WI - AUCTIONS: 0 active rows; last read 2026-10-09 18:15:46+00
WI - AVAILABLE: eligibility NOT_VERIFIED; no production source
WI - LIENS_CERTIFICATES: eligibility NOT_VERIFIED; no production source

## WY

| Ledger | Eligibility | Classification | Sources known / implemented / approved | Active rows | Never stamped | Older than 36 h | Acquisition units VERIFIED | Next action |
|---|---|---|---|---|---|---|---|---|
| AUCTIONS | COUNTY_DEPENDENT | CURRENT | 1 / 1 / 1 | 253 | 0 | 0 | 0 of 0 | Keep reading; raise field population where a verified official layer exists (see fields). |
| AVAILABLE | NOT_VERIFIED | RULES_NOT_VERIFIED | 0 / 0 / 0 | - | - | - | 0 of 0 | Read the state's statute / an official county procedure and record it in data/state_rules.csv before any source is built. |
| LIENS_CERTIFICATES | COUNTY_DEPENDENT | OFFERED_SOURCE_NOT_IMPLEMENTED | 0 / 0 / 0 | - | - | - | 0 of 0 | Locate the official list for this ledger (job=evidence capture), register it, then build the adapter. |

WY - AUCTIONS field population (active rows, snapshot): amount 253/253; bid_amount_mismatch 0/253; coords 253/253; dup_parcel 0/253; flood_checked 253/253; laft_bid_without_amount 0/253; link_not_https 0/253; list_as_of 0/253; list_as_of_future 0/253; never_seen 0/253; parcel 253/253; parcel_no_digit 0/253; past_sale 0/253; path_typed 0/253; provenance 253/253; seen_gt36h 0/253; seen_order_bad 0/253; source_link 253/253
WY - AUCTIONS: 253 active rows; 0 never stamped, 0 older than 36 h at the snapshot
WY - AVAILABLE: eligibility NOT_VERIFIED; no production source
WY - LIENS_CERTIFICATES: eligibility COUNTY_DEPENDENT; 0 known source(s), none in production
