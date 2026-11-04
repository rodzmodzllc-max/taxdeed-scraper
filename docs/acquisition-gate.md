# Acquisition-path gate for customer actionability (2026-10-10, staged off)

**Policy.** Only a property with a defensible, verified acquisition path may
appear to customers as an actionable Available opportunity. Unverified
candidates stay visible to administrators for investigation and remediation.
A typed path, a source id, a URL, a source label or an observed date alone is
not proof that a buyer can act.

**Status.** Implemented end to end, shipped **off**: `config.js`
`availableGate: "off"`. Setting it to `"enforce"` is the owner's decision (see
section 7). Nothing in this work writes to production, changes the schema,
alters harvesting, changes a source approval or enables a restricted source.

## 1. Where the decision lives

| Layer | Code | Role |
|---|---|---|
| Rule | `harvesters/sources/acquisition_gate.py` `verify(row, unit=, record=, today=)` | the one definition: reasons, classes, windows |
| Browser mirror | `public/app.js` `acquisitionVerificationWith()` / `acquisitionVerification(p)` / `acqGateAllows(p)` | identical logic; `isPublishable()` consults it only when enforced |
| Shared vectors | `tests/python/fixtures/acquisition_gate_cases.json` (20 cases) | `tests/python/test_acquisition_gate.py` runs Python; `tests/run_test.mjs` `gateVectors` runs the browser against the same file |
| Dry run | `scripts/acquisition_gate_dryrun.py` (`--check` pinned) | counts-only report from a read-only production export |
| Switch | `config.js` `availableGate` | `"off"` (default) or `"enforce"`; read once at load into `ACQ_GATE_MODE` |

Administrators are never gated in either mode. The tester preview
(`publicationMode: "preview"`) **is** gated when enforced: an unverified
Available row is not an actionable opportunity for anyone but an admin.

## 2. Data flow: what a customer actually sees today

1. **Harvest / sync** writes `properties` rows (`source = 'laft'`) with
   `source_id`, `publication_status` (propagated from the registry by
   `scripts/publication_gate.py`), `last_seen_at` (stamped by the lifecycle or
   sync), `list_as_of` (only when the source publishes a date), and the
   typed-path columns `purchase_path_type` / `_scope` / `_evidence` /
   `_observed_on` plus `otc_provenance.acquisition` (written only by
   `scripts/purchase_path_engine.py` from a verified evidence row).
2. **Evidence tables** (`data/purchase_path_evidence*.csv`) are compiled by
   `scripts/build_acquisition_evidence.py` into `public/acquisition-evidence.json`:
   `records[]` (one county-level verified process: mode, channels, steps,
   office, phone, e-mail, address, form, evidence page, observed date) and
   `status[]` (one VERIFIED / NEEDS_REVIEW / UNAVAILABLE / NOT_FOUND per
   state × source × county, with its basis).
3. **Browser.** `fetchProperties()` pages `get_properties_list()`;
   `applyLedgerRows()` keeps a row for this viewer when `isPublishable(p)`.
   Before this change that meant: admins see everything; customers see rows
   whose **source** is approved (or, in preview mode, every non-BLOCKED
   source). The acquisition record only changed *wording* on the property
   page ("Not yet verified"), never visibility.

So an Available listing could be shown to a customer with no verified route,
with a stale read, or with a list dated years ago, as long as its source was
approved. That is the gap the gate closes.

## 3. Criteria (every reason a row can fail)

A row passes only when **no** reason applies. Windows: read within 14 days
(`OBSERVATION_DAYS`), published list date within 365 days (`LIST_DAYS`),
county process verified within 180 days (`EVIDENCE_DAYS`).

| Reason | Class | Fact read |
|---|---|---|
| `SOURCE_ID_MISSING` | metadata_gap | `source_id` / `harvester_source` empty |
| `SOURCE_NOT_PUBLISHED` | source_not_published | `publication_status` not APPROVED / APPROVED_GRANDFATHERED (NULL fails closed) |
| `ROW_NOT_ACTIVE` | stale | lifecycle `status` not active / available |
| `OBSERVATION_MISSING` | metadata_gap | no `last_seen_at` ever stamped |
| `OBSERVATION_STALE` | stale | `last_seen_at` older than 14 days |
| `LIST_DATED_STALE` | stale | `list_as_of` present and older than 365 days |
| `EVIDENCE_UNIT_UNKNOWN` | metadata_gap | no status entry for (state, source, county) |
| `EVIDENCE_NEEDS_REVIEW` | pending_verification | unit status NEEDS_REVIEW |
| `EVIDENCE_UNAVAILABLE` | pending_verification | unit status UNAVAILABLE (pages could not be read) |
| `EVIDENCE_NOT_FOUND` | no_route | unit status NOT_FOUND (pages read, no process described) |
| `EVIDENCE_NO_RECORD` | metadata_gap | unit VERIFIED but no county record to act on |
| `EVIDENCE_UNTRUSTED_URL` | pending_verification | evidence page not https, a homepage, a search engine or a blocked vendor (`laft_purchase_paths` host list) |
| `EVIDENCE_NO_CHANNEL` | pending_verification | record names no form / online page, and no steps with a contact |
| `EVIDENCE_STALE` | pending_verification | record verified more than 180 days ago |
| `PATH_NONE` | no_route | the source states there is no purchase path |
| `PATH_MISMATCH` | pending_verification | the row's typed path disagrees with the verified county record |

Classes, in precedence when several apply: `source_not_published` →
`no_route` → `pending_verification` → `metadata_gap` → `stale`. The class
labels customers and admins see are `CLASS_LABELS` (Python) =
`ACQ_GATE_CLASS_LABELS` (app.js), test-pinned equal.

**Missing metadata vs. no route.** `metadata_gap` means the pipeline has not
recorded a fact (no read stamp, no status entry, a verified unit with no
record). `no_route` means the official pages were read and describe no way to
acquire, or the source states there is none. They are reported separately
everywhere (dry run, ledger notice, admin chip, Source truth row).

## 4. Facts the schema supports, and facts it does not

Supported and read by the gate: `source_id`, `publication_status`, `status`,
`last_seen_at`, `list_as_of`, `purchase_path_type`, and the county-level
evidence record + status from the repository's own captures.

**Not available, and not invented:**
- Whether anyone ever completed a purchase through the recorded route. The
  gate says a route was *read and recorded from the source's own page*, never
  that it was tested.
- A per-property purchase link that is verified as such. Every verified
  record is county- or source-level; a row's own `purchase_url` is accepted
  only when it agrees with that record (`PATH_MISMATCH` otherwise).
- A current price or total due (see `docs/available-amount-semantics.md`);
  the gate does not require one, because most sources do not publish one.
- Contact for Marion FL: its verified record has steps but no phone / e-mail
  / address, so it fails `EVIDENCE_NO_CHANNEL` (2 rows) until the capture is
  extended. Four units are VERIFIED by registry basis with no record
  (Oceana MI, Oklahoma OK, Georgetown SC, Horry SC): `EVIDENCE_NO_RECORD`.

## 5. Dry run against production (read-only, 2026-10-10)

Report: `docs/review/acquisition-gate-dryrun-2026-10-10.md`; data:
`data/current_state/acquisition-gate-dryrun-2026-10-10.json` (counts only, no
row). Source: a counts-only export of production's active AVAILABLE rows,
grouped by state × source × county × publication × date bucket; no write.

| | Rows |
|---|---|
| Active AVAILABLE rows | 54,105 |
| Customer-visible today (customer mode, approved sources) | 10,908 |
| Customer-visible today (production's `publicationMode: "preview"`) | 54,105 |
| **Customer-visible with the gate enforced** | **185** |

Withheld, by class: source not customer-published 43,197 (the existing source
decision, not this gate's finding) · not current 10,334 · no route 311 ·
missing metadata 40 · pending verification 38.

**This is a large reduction, stated plainly.** By state: FL 153 → 41, TX 421 →
144 (Galveston), LA 10,334 → 0, and MI / MN / MO / OK / PA / SC / TN → 0 (all
already withheld in customer mode by the source decision; visible today only
because production runs in preview mode). The breakdown by source and by
county is in the report.

Why the biggest buckets fail:
- **LA (10,334):** every row carries `list_as_of = 2024-02-27`, the dataset's
  own `rowsUpdatedAt`. The owner approved Louisiana **as a dated list**
  (`docs/state-expansion.md`), and the gate reads a list dated over a year ago
  as not current. See section 6.
- **TX (277 of 421):** 238 Galveston-adjacent counties with NOT_FOUND
  evidence; 39 rows never stamped `last_seen_at` (Texas has no lifecycle
  read; LGBS is manual-only).
- **FL (112 of 153):** 73 counties whose pages describe no process
  (NOT_FOUND), 38 pending (UNAVAILABLE / NEEDS_REVIEW / no channel), 1 never
  stamped.

## 6. Louisiana `purchase_url` audit (read-only)

Question: 10,334 East Baton Rouge rows carry `purchase_path_type =
county_instructions` and a populated `purchase_url`; what is it?

Finding (read-only SQL, 2026-10-10): **one identical URL on every row**, the
Parish's own "Adjudicated Property" information page (`brla.gov`, kind
`purchase_instructions`, scope `source`). It is **informational**, not
transactional: it is not a per-property link and nothing on it is a checkout.
The acquisition itself is the Parish Attorney's offline process (Request to
Purchase form, phone, mailing address), which is the verified county-level
record in `data/purchase_path_evidence.csv` (memorandum PDF read 2026-10-01).
6,834 rows still carry the full acquisition provenance; 3,500 lost it at a
later sync and are refilled in the browser from the same county record
(`acquisitionProvenance(p)`). The presence of `purchase_url` therefore proves
nothing beyond "the Parish has an instructions page".

Recommended classification: **county-level instructions (informational)**.
Present it as "View purchase instructions" / the multi-step Parish process,
never as "purchase online". Under the gate LA is `stale` (`LIST_DATED_STALE`),
not `no_route`: the route is verified and current (observed 2026-10-01); the
**list** is dated 2024-02-27. Enabling LA listings for customers therefore
needs one of: a fresher list from the Parish (the harvest reads
`rowsUpdatedAt`; nothing to change in code), or an explicit owner decision
that a dated list is acceptable with a longer `LIST_DAYS` for this source.
Neither was done here.

## 7. What is enforced where, and the decision left open

- **Off (shipped):** customer visibility is unchanged. The gate still runs for
  information: the property page's Source truth shows "Customer
  actionability" with the verdict, every reason and "Gate not enforced on
  this deployment"; admins see a chip "Not customer-actionable (gate off):
  <class>" on each failing card; Home's Available card shows "N pending
  verification".
- **Enforce:** a non-admin's Available ledger drops every failing row and
  shows "N records withheld pending acquisition-path verification (by class)";
  Home, Map, counts and export follow (they all read `ALL`, which
  `isPublishable()` already filters). Admins see everything, each withheld
  card chipped "Withheld from customers: <class>". Rows are never deleted or
  re-statused.
- **Relation to PR #136 (migration 031, not applied):** 031 is the
  server-side publication_state gate (source approved → rules verified →
  path verified → fresh). This gate is its browser-side, finer-grained
  counterpart on the acquisition record itself and needs no migration. When
  031 is applied, the server already withholds rows with no credible path;
  this gate additionally requires the county record to be verified, current
  and to name a channel.

**Decision required (owner):** set `availableGate: "enforce"` in production
`config.js`, accepting the counts in section 5, or keep it off. Second
decision: the Louisiana dated-list policy (section 6).

## 8. Tests

- Python: `tests/python/test_acquisition_gate.py` (vectors, every reason,
  class precedence, untrusted hosts, app.js mirror pins, config default off,
  `dryrun --check`).
- Browser (`tests/run_test.mjs`): `gateVectors` (same JSON through
  `window.__tdwAcquisitionGate.verifyWith`), `gateOffByDefault`,
  `gateEnforcedCustomer` (every fixture Available row fails for a documented
  reason → notice, 0 cards), `gateEnforcedFreshCustomer` (`?gatefresh=1`
  adds the one row that passes: Calhoun FL, approved source, read today,
  verified county record → only it shows), `gateEnforcedAdmin` (admin keeps
  every row, chips on the withheld ones, none on the passing one),
  `gateTruthRow` (Source truth verdict + reasons + mode note).
