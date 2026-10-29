# Tester feedback: design

Status: design only, 2026-10-13. Nothing is stored, no table is created, no
email is sent. The storage destination needs the owner's decision (section 8).

## 1. Purpose

Learn which parts of the research workflow a real investor can use, and where
they get stuck. Feedback is about the product, never about a property's facts.
A property's facts are changed through the source, not by a tester's comment.

## 2. Fields

| Field | Required | Notes |
|---|---|---|
| `id` | yes | uuid, generated |
| `user_id` | yes | the signed-in account; `on delete cascade` |
| `created_at` | yes | server time |
| `page` | yes | one of a fixed list: sign-in, list, map, property, watchlist, research, county, rules, account, other |
| `context_ref` | no | the state and county, or a property id; never an address or owner name |
| `category` | yes | fixed list: can't do a task, wrong or missing data, confusing wording, bug, suggestion |
| `severity` | yes | `blocker`, `major`, `minor`, `idea` (set by the submitter; the admin may re-set it) |
| `body` | yes | free text, 10 to 2,000 characters |
| `status` | yes | `new`, `triaged`, `resolved`, `wont_fix`, `duplicate` |
| `admin_note` | no | visible to admins only |
| `resolved_at` | no | |
| `body_hash` | yes | sha256 of the normalised body, for duplicate detection |

Not collected: names, phone numbers, email in the feedback row (the account
already holds it), browser fingerprints, IP addresses, screenshots containing
addresses. A screenshot is a manual attachment only if the tester chooses it,
and it is not in the first version.

## 3. Who may submit

Signed-in accounts with `approved = true` only. A pending account cannot submit,
which keeps the table from becoming a public inbox.

## 4. Who may view and manage

- Submitter: may read their own rows (status and resolution only, never
  `admin_note`). Cannot edit a row after submission; a new row is the correction.
- Administrators: read all rows, change `status`, `severity`, `admin_note`.
- Nobody else. No anonymous access, no export to customers.

## 5. Spam and duplicates

- Rate limit: at most 10 submissions per account per 24 hours, enforced in the
  insert policy or the RPC (not in the browser).
- Duplicate: same `user_id` and `body_hash` within 24 hours is rejected with a
  clear message, not stored twice.
- Length cap enforced server-side (2,000 characters), not only in the form.
- Administrators can mark `duplicate`; a resolved item can be reopened by a new
  row, not by editing the old one.

## 6. Retention and deletion

- Open items: kept until resolved.
- Resolved, won't fix, duplicate: kept 12 months from `resolved_at`, then deleted
  by a scheduled job (not yet written).
- Account deletion (`delete_my_account()`): the submitter's rows are deleted
  with the account (cascade), unless an administrator has already copied an
  item into a tracked fix. Such a copy holds the text only, never the user id.
- Export: administrators only, for the owner's own review.

## 7. Tester participation

Feedback does not make anyone a tester and does not change access. Access comes
from the approval record and, once migration 027 is applied, `access_grant`.
Feedback is never used as a reason to grant or remove access.

## 8. Storage: two supported routes (owner-confirmed 2026-10-13)

The owner has asked for both routes to be designed. Each is independently
buildable; neither is applied. Route A is preferred for structured triage; route
B is the fallback and the first contact point.

### Route A: restricted Supabase table

- Table `tester_feedback` (migration 034, drafted, NOT applied), fields as in
  section 2.
- Writes only through an RPC `submit_tester_feedback(...)` that checks
  `is_approved()`, applies the rate limit and duplicate check (section 5),
  and inserts. Direct `insert` from `anon` or `authenticated` is revoked.
- Reads: the submitter sees their own status and resolution; administrators
  see all rows through an admin-only policy wrapped as `(select is_admin())`.
- Grants follow the billing tables' pattern: `revoke all` from `anon` and
  `authenticated` first, then explicit grants.
- Operational owner: the site administrator, who triages from the admin area.
- Test plan before any application: static checks plus live Postgres tests in a
  scratch cluster (the pattern of `tests/python/test_migration_030_*`), covering
  the rate limit, duplicate rejection, cross-account reads (must fail), and
  anonymous writes (must fail).

### Route B: monitored support mailbox

- The support dialog's `supportEmail` in `config.js` is blank by design. Route B
  needs the owner to set it to a real mailbox, and to name the person who reads it.
- Operational requirements, which must be written down before go-live:
  - a named monitor and a backup monitor;
  - a response-time target (proposed: acknowledge within two business days);
  - a spam filter and a rule that forwards nothing to personal mail;
  - the mailbox retains messages for at most 12 months, then deletes them;
  - messages are never copied into the repository, a spreadsheet, or a
    public channel.
- The form stays in the app: it opens a `mailto:` with the page and category
  prefilled and a notice that the body is sent by e-mail. Nothing is sent by
  TAXACQ itself, so no server state changes.
- Minimisation: the mail body contains only what the tester types. The app adds
  no account identifier or property detail unless the tester chooses to paste it.

### Choosing between them

- Route B works today once the mailbox exists. It has no triage state, no
  duplicate detection and no admin count.
- Route A needs migration 034 and the test plan above, and it gives structured
  triage. It is the recommended long-term route.
- A tester may be sent to route B until route A is approved and applied.

Decisions needed: approve route A's migration for testing in a scratch cluster;
name the mailbox and its monitors for route B.

## 9. Notifications

No email is needed for version 1. The administrator opens the admin area and
sees a count of new items. If an e-mail alert is wanted later, it goes through
the existing outbox pattern (migration 030, `account_notifications`), and a
failed send is retried and then shown as failed in the admin view, not silently
dropped.

## 10. Minimal implementation plan

1. Owner decides the destination (section 8).
2. Draft and test migration 034 (table, policies, RPC with the rate limit and
   duplicate check, grants revoked from `anon`, `authenticated` writes only
   through the RPC). Test against a scratch Postgres, not production.
3. Add a "Report a problem" form to the support dialog, submitting through the
   RPC, with the page and category fields and a visible confirmation.
4. Add an admin panel count and list. Triage actions only for administrators.
5. Only after 1 to 4 are reviewed: apply 034 with explicit approval.

Nothing in steps 2 to 4 changes production until step 5 is approved.

## 11. Open decisions

- Route A (table) or route B (mailbox), or both in sequence (section 8).
- Route B: the mailbox address and the named monitors.
- Route A: approval to test migration 034 in a scratch cluster.
- Whether testers may attach screenshots in version 1 (recommended: no).
