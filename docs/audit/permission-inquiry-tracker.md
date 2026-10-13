# Permission inquiry tracker

**As of 2026-10-12.** Machine-readable copy: `data/audit/permission_inquiry_tracker.csv`, one row per inquiry.

**Nothing was sent by this work.** No county, vendor, agency or counsel was contacted.

## Rules for this tracker

- **What may be marked SENT.** An inquiry is SENT only when a copy, or at least a send date, is recorded where the repository can reference it. The owner's statement that an inquiry went out is recorded as `REPORTED_SENT_UNVERIFIED`, never as SENT.
- **What may be marked GRANTED.** Only a written reply from the responsible authority that covers the operations asked about. A reply from a different office, a phone call, or silence is not permission.
- **What the owner's decision is.** The owner's 2026-09-30 publication decision for group A is an *internal risk acceptance*, not a grant. `data/source_permissions.csv` (PR #145) records it as an interim allowance that **expires 2027-04-12**. When it expires, those sources are denied unless documented permission has been recorded by then.

## Mailbox status

The Gmail connector returned `Forbidden` on 2026-10-12, as it did on the earlier audit day. On 2026-10-13 it was not connected to the session at all. No sent message, date or reply could be read, so every response status below is UNKNOWN or NONE, and every delivery is unverified.

## Group A - counties with no inquiry on record

The source register's queue (`docs/audit/source-register-2026-10-12.md` section 6.2) lists these as NOT SENT. The six inquiries the owner reported sending (group B) went to different organisations. None of these county authorities has a recorded inquiry.

| Jurisdiction | Source | Responsible authority | Inquiry | Last evidence | Permission today | Next action |
|---|---|---|---|---|---|---|
| CO: Morgan | `co_morgan_county_held_certificates` | Morgan County Treasurer | NOT SENT | 2026-09-30 live capture | Internal acceptance (interim) | Confirm contact; template C |
| MI: Eaton | `mi_eaton_treasurer_sale` | Eaton County Treasurer | NOT SENT | 2026-09-30 | Internal acceptance (interim) | Confirm contact; template C |
| MI: Lenawee | `mi_lenawee_tax_sale` | Lenawee County Treasurer | NOT SENT | 2026-09-30 | Internal acceptance (interim) | Confirm contact; template C |
| SC: York | `sc_york_tax_sale` | York County - **office not established** | NOT SENT | 2026-09-30 | Internal acceptance (interim) | Establish the responsible office first |
| WI: Green | `wi_green_tax_deed_sales` | Green County Treasurer | NOT SENT | 2026-09-30 | Internal acceptance (interim) | Confirm contact; template C |
| WY: Albany | `wy_albany_tax_sale` | Albany County Treasurer | NOT SENT | 2026-09-30 | Internal acceptance (interim) | Confirm contact; template C |
| OK: Oklahoma | `ok_oklahoma_county_owned` | Oklahoma County Treasurer | **DRAFTED, NOT SENT** (`docs/audit/drafts/oklahoma-county-inquiry-draft.md`) | 2026-10-04 | Unknown (admin-only) | Owner confirms contact details and decides |

The required reviewer for every group A row is the owner.

## Group B - inquiries the owner reports having sent

| Addressee | Covers | Inquiry | Response | Caution |
|---|---|---|---|---|
| Florida DOR, Property Tax Oversight | `fl_dor_statewide_nal`, `fl_statewide_cadastral_fgio` | REPORTED SENT, UNVERIFIED | Unknown | FGIO hosts the cadastral service |
| Detroit Enterprise GIS | `mi_detroit_landbank_lots_and_programs` | REPORTED SENT, UNVERIFIED | Unknown | The DLBA owns the inventory |
| St. Louis Assessor, Records and Mapping | `mo_stl_parcels_coordinates`, `mo_stl_lra_inventory` | REPORTED SENT, UNVERIFIED | Unknown | The LRA / SLDC owns the inventory list |
| Fayette County PA GIS | `pa_fayette_repository` | REPORTED SENT, UNVERIFIED | Unknown | The Tax Claim Bureau owns the list |
| Oklahoma OGI | State GIS only | REPORTED SENT, UNVERIFIED | Unknown | Cannot cover the county list (see group A) |
| RealAuction customer service | `fl_realauction_*`, `fl_laft_realtdm`, `tx_realauction` | REPORTED SENT, UNVERIFIED | Unknown | County EULAs are the clerks'; counsel packet `docs/audit/counsel-review-packet.md` |

## Updating this tracker

1. Edit the CSV row:
   - set `inquiry_status` to `SENT`, with the date in `last_known_evidence_date`;
   - record `response_status`;
   - put the location of the correspondence in `evidence_reference`.
2. A written grant does not take effect by being entered here. To change a source's permission:
   - add a `WRITTEN_PERMISSION` or `PUBLISHED_LICENSE` row to `data/source_permissions.csv`, citing that reference;
   - record a matching `ProviderAuthorization` where the source has one;
   - follow `docs/source-permissions.md`.
