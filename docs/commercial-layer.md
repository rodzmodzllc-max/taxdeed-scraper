# Controlled paid beta: the commercial layer (2026-10-05)

The tester preview stays as it is while real investors test the product.
This layer adds paid subscriptions **on top of** it: one access decision,
Stripe-backed billing, a paid-beta source scope that is separate from the
tester preview, legal pages, and support wiring.

Nothing here is switched on in production:
- `billing.enabled` is `false`;
- migration 027 is not applied;
- the Stripe Edge Functions are not deployed;
- no Stripe key exists anywhere.

## 1. One access decision

`entitlementFor()` in `supabase/functions/_shared/billing_core.js` is mirrored in SQL by `public.entitlement_for()` (migration 027). Both are pinned to the same answers by `tests/billing/fixtures/entitlement_cases.json`.

| Role | When | Inventory (`scope`) |
|---|---|---|
| **admin** | `profiles.is_admin` | `all`: every collected row, labelled |
| **tester** | approved by an admin, `profiles.access_grant = 'tester'` (the default, so every existing approved account) | `preview`: today's tester experience. `config.js publicationMode` decides between preview (sources under review, labelled) and enforced |
| **customer** | a subscription that grants access, **or** approved with `access_grant = 'customer'` (admin-granted, no Stripe) | `approved`: paid-beta sources only (section 3) |
| **inactive** | none of the above | none: the plan screen (billing on) or the pending-approval screen |

Precedence is admin > tester > customer > inactive. A tester who also pays keeps tester access, and the subscription is still shown.

**Subscription states** (`state`):

| State | Stripe status / condition | Access |
|---|---|---|
| `active` | `active` | yes |
| `trial` | `trialing` | yes |
| `cancelling` | `active` with `cancel_at_period_end`, before the period end | yes, until the period end |
| `payment_failed_grace` | `past_due`, within 7 days of the failed payment (`billing_grace_days()` / `DEFAULT_GRACE_DAYS`) | yes |
| `payment_failed` | `past_due` beyond the grace window, or `unpaid` | no |
| `cancelled` | `canceled`, or `cancel_at_period_end` once the period is over | no |
| `inactive` | `incomplete`, `incomplete_expired`, `paused`, or no subscription | no |

Only the configured monthly price grants access (`plan_key`). A subscription to any other price in the same Stripe account is recorded and grants nothing.

**Frontend (`public/app.js`).**
- `checkApprovalAndEnter()` reads `my_entitlement()`. If the function is missing (027 not applied), the approval record decides exactly as before:
  - admin → admin;
  - approved → tester;
  - otherwise the pending screen.
- `viewerScope()` (`all` / `preview` / `enforced` / `paid`) feeds `isPublishable()`. A customer never gets the preview inventory, whatever `publicationMode` says.

**Switching from TESTER PREVIEW to PAID ENFORCED** is configuration only:
1. Apply migration 027.
2. Deploy the functions and set billing `enabled: true`.
3. When testing ends, set `publicationMode: "enforced"`.

Testers keep their approval and their access throughout.

## 2. Billing (Stripe)

**Files:**
- `supabase/functions/_shared/billing_core.js`: signature verification, event planning, idempotent processing, entitlement, Checkout / Portal request bodies. Plain JavaScript, with tests in `tests/billing/billing_core.test.mjs` (`node --test`).
- `supabase/functions/stripe-webhook`:
  - the only writer of `public.subscriptions`;
  - verifies `Stripe-Signature` (HMAC-SHA256, 5-minute tolerance) before reading anything;
  - records each event id once in `public.billing_events` (idempotency and audit);
  - never lets an older event overwrite a newer state;
  - never moves a subscription to another account.

  An event it cannot attribute yet answers 500, so Stripe retries. Unknown event types are acknowledged and ignored; malformed events get 400.
- `supabase/functions/billing-checkout`: a Checkout Session for the one monthly price, taken from `STRIPE_PRICE_ID` and never from the browser. The account always comes from the caller's JWT.
- `supabase/functions/billing-portal`: Stripe's customer billing portal for the caller's own Stripe customer (card, invoices, cancellation).

**The rule:** a redirect back from Checkout (`#/billing?checkout=success`) grants nothing. The page re-reads the server until the webhook has recorded the subscription (bounded polling), and only then enters.

**Customer-facing:**
- the plan screen (`#planGate`): plan, price, the paid-beta scope sentence, Subscribe, Manage billing after a failed payment, and the tester note;
- Plan & billing in the account menu (`#billingModal`): access, why, plan, subscription state, renewal or access-end date, cancellation, payment problem, inventory scope, and Manage billing.

**Admin** (`admin.html`, "Customers & access"): `admin_billing_overview()`, admin-only on the server.
- It shows each account's role, state, reason, subscription status and id, period end, and payment / cancellation problem.
- E-mail addresses appear only after "Show accounts" (the admin page shows no e-mail by default).
- Before 027 it lists accounts from approval only, and says so.

## 3. Paid-beta source scope (separate from the tester preview)

`data/paid_beta_sources.csv` holds one decision per collected source. It is validated by `harvesters/governance/commercial_scope.py`, rendered to `public/commercial-scope.json` by `scripts/build_commercial_scope.py` (with a `--check` mode), and seeded into `public.commercial_source_scope` by migration 027 (a test pins that the two are equal).

| Scope | Meaning |
|---|---|
| `CUSTOMER_APPROVED` | registry `publication_status = APPROVED`: an explicit decision |
| `REQUIRES_PUBLICATION_DECISION` | customer-visible today only through a grandfathered approval or no recorded decision |
| `TESTER_PREVIEW` | collected, not approved; testers see it, labelled |
| `UNREVIEWED` | registered, not collected |
| `BLOCKED` | never shown |

**Paid beta** = `CUSTOMER_APPROVED` **and** every check ok: provenance, lifecycle, financial, acquisition. The paid customer's rule is enforced twice:
- in the browser: `isPaidBetaPublishable()` (`publication_status === "APPROVED"` and the source is in the paid-beta set);
- in the database: migration 027's RESTRICTIVE SELECT policy `"properties: paid customers see paid-beta sources only"`. It is layered on the existing PERMISSIVE policy, never replacing it.

**Initial paid-beta inventory.** Decided 2026-10-05; row counts read from production that day.

| Source | State | Publication | Paid beta | Tester preview | Why |
|---|---|---|---|---|---|
| la_ebr_adjudicated | LA | APPROVED | **yes** (10,334) | yes | Public Domain; dated list; offer-negotiated terms; verified Parish Attorney process |
| sc_york_tax_sale | SC | APPROVED | **yes** (853) | yes | owner-approved; provenance; process recorded |
| mi_lenawee_tax_sale | MI | APPROVED | **yes** (35) | yes | owner-approved; process recorded |
| mi_eaton_treasurer_sale | MI | APPROVED | **yes** (3) | yes | owner-approved; county's own sold flag |
| wi_green_tax_deed_sales | WI | APPROVED | **yes** (0 active) | yes | owner-approved; no active rows today |
| wy_albany_tax_sale | WY | APPROVED | no | yes | every row's status is unknown after the 2026 sale; no process represented |
| co_douglas_county_held_liens | CO | APPROVED | no | yes | rows show Colorado Public Parcels (State OIT) fields, whose terms prohibit resale: needs an owner decision |
| co_morgan_county_held_certificates | CO | APPROVED | no | yes | same enrichment issue |
| fl_laft_* (9 sources) | FL | APPROVED_GRANDFATHERED | no | yes | legacy approval, never reviewed for paid reuse: requires a publication decision |
| fl_realauction | FL | none on the rows | no | yes | requires a publication decision |
| fl_lienhub_certificates | FL | none on the rows | no | yes | requires a publication decision; LienHub refusing reads |
| tx_lgbs, tx_realauction | TX | grandfathered / none | no | yes | rights audits REVIEW_REQUIRED; manual-only |
| Detroit lots / programs, Oceana, St. Louis LRA, Oklahoma County, Fayette, Ramsey, Horry, Georgetown | MI / MO / OK / PA / MN / SC | UNREVIEWED | no | yes (Detroit subset applies) | not reviewed |
| tx_mvba, tx_pbfcm | TX | BLOCKED | no | no | never shown |

**Nothing was approved to enlarge this set.** To add a source:
1. Record an explicit publication decision (the admin publication panel, or the registry).
2. Set `paid_beta=yes` only when every check is ok.
3. Rebuild the JSON.
4. Add the source to `commercial_source_scope`. That is a production write; do it deliberately.

## 4. Legal, support, password reset

- **Legal pages.** `terms.html`, `privacy.html`, `acceptable-use.html` and `source-disclaimer.html`, linked from:
  - the sign-in, pending and plan screens;
  - the Terms & disclaimer modal.

  `legal.js` fills the business details from `config.js` (`legal.*`, `supportEmail`, `billing.priceDisplay`) and shows a "not complete" notice listing every value that is missing. Nothing is invented. These pages are a starting draft and need review by counsel before launch.
- **Support.** Topics: general, data, source, account, **billing**, **technical**, deletion. With `supportEmail` blank, the modal says no address is configured, and the topics stay disabled.
- **Password reset.** This is unchanged and already wired:
  - the request (`resetPasswordForEmail`, redirect = the page's own URL);
  - `PASSWORD_RECOVERY` opens "Set a new password" (`updateUser`);
  - an expired or used link is explained on the sign-in screen (`otp_expired`).

  The configuration it needs is in `docs/production-configuration.md` section 2.

## 5. Tests

| Suite | What it covers |
|---|---|
| `node --test tests/billing/billing_core.test.mjs` | 45 tests: entitlement vectors; valid / invalid / tampered / stale signature; missing secret; activation; checkout linking without access; unknown customer retry; duplicate; payment failure → grace → restricted; recovery; cancel at period end; expiration; out-of-order; account move refused; foreign price; unknown event; malformed; checkout / portal bodies |
| `tests/python/test_migration_027_commercial_billing.py` | static checks, plus live PostgreSQL: the shared vectors in SQL; tester / admin see all; paid sees paid-beta only without manual approval; manual customer; inactive / lapsed see nothing; entitlement own-only; no client writes; admin overview admin-only; payment failure beyond grace; approval model unchanged |
| `tests/python/test_commercial_scope.py` | the decision file, mirror, paid = APPROVED only, mapping, validator refusals, blocked never shown, grandfathered withheld |
| `tests/python/test_commercial_layer.py` | webhook verifies before reading; price and account from the server; no Stripe secret in the repository; billing ships off; legal pages never invent details; plan / billing / legal links on every page; no 024 dependency; customers never get the preview |
| `tests/run_test.mjs` (`paid*` checks) | legacy and tester entitlement (preview unchanged); paid customer on LA / SC / FL; manual customer; grace / cancelling billing view; plan screen; checkout and portal calls; checkout unavailable; incomplete config; payment failed; cancelled; redirect without webhook (no access); access after the webhook; support topics; legal pages; admin customers |

## 6. Production activation (separate step, not done)

See section 11 of `docs/production-configuration.md` for the value-by-value checklist.
In order:
1. Stripe:
   - create the product and the monthly price;
   - configure the customer portal (allow cancellation at period end and card updates);
   - create a restricted secret key.
2. Supabase Edge Function secrets: `STRIPE_SECRET_KEY`, `STRIPE_PRICE_ID`, `STRIPE_WEBHOOK_SECRET`, `APP_URL`.
3. Deploy the functions:
   - `supabase functions deploy stripe-webhook --no-verify-jwt`;
   - `billing-checkout` and `billing-portal` with JWT verification on.
4. Register a Stripe webhook endpoint at `https://<project>.supabase.co/functions/v1/stripe-webhook` for these events:
   - `checkout.session.completed`;
   - `customer.subscription.created`, `.updated`, `.deleted`, `.paused`, `.resumed`;
   - `invoice.paid`, `invoice.payment_succeeded`, `invoice.payment_failed`.

   Copy its signing secret into `STRIPE_WEBHOOK_SECRET`.
5. Apply migration 027, with explicit authorization.
6. Set `config.js` `billing` to `enabled: true`, `planName`, and `priceDisplay` (matching the Stripe price).
7. Test in Stripe test mode end to end before using live keys.

Migration 024 (saved searches / alerts) is **not** a prerequisite. It stays unapplied, and those features stay feature-detected off.
