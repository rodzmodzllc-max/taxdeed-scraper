# Refunds, disputes and the webhook: policy, changes and approvals

Status: code and tests on branch `feat/billing-refund-dispute`; policy confirmed by the owner 2026-10-13. Billing stays
OFF (`config.js` `billing.enabled: false`). Migration 033 is a DRAFT and is NOT
applied. No live Stripe prices, no deploys, no production writes.

## 1. What the code did before (inspected 2026-10-13)

- `planEvent()` used only subscription events and invoice payment events.
  `charge.refunded` and every `charge.dispute.*` event fell through to
  "ignored" and were acknowledged. A refund or chargeback therefore changed
  nothing, and access stayed on.
- `invoice.payment_*` for a subscription that was not yet recorded was
  acknowledged as `payment_for_unknown_subscription` and never retried. A
  payment failure that arrived before its subscription event was lost for good.
- `recordPayment` did not compare event times. An older `payment_failed`
  could overwrite a newer `paid`.
- Idempotency (`billing_events`, one row per event id), signature checks, the
  stale-subscription guard, failed-event retry, and the seven-day grace period
  were already in place, and they are unchanged.

## 2. Access policy (confirmed by the owner, 2026-10-13)

| Event state | Access | State shown | Notes |
|---|---|---|---|
| Full refund on a paid subscription | ends | `refunded` | Overrides Stripe's status and the grace period. Manual customer grant still applies (support exception). |
| Partial refund | kept, **flagged for manual review** | normal state, `review_required: true` | Never revokes by itself. An administrator checks the case. |
| Partial refund later becomes full | ends | `refunded` | Refunded amounts never shrink. |
| Dispute opened (`needs_response`, `under_review`) | **held** until resolved | `dispute_open` | Temporary hold, `disputed: true`. |
| Dispute resolved as lost | ends | `dispute_lost` | Persists after later subscription events. |
| Dispute resolved as won, or inquiry closed (`warning_closed`) | hold removed; access recalculated from all other conditions | normal state | A full refund still ends access. |
| Manual customer grant (`access_grant = customer`) | kept | "Customer access granted by an administrator" | Documented support exception. |
| Tester / admin | unaffected | unchanged | Holds apply only to paid subscriptions. |
| Cancellation at period end | unchanged | "Cancellation scheduled" | A refund or dispute hold still applies on top. |
| Payment failed (grace, then restricted) | unchanged | unchanged | A full refund or open dispute applies during grace too. |

Resolution is recalculated: after a dispute closes, entitlement is computed
again from every remaining condition (refund, lost dispute, subscription state,
grace period), not restored to a previous value.

Each charge's refund and dispute facts apply only to the subscription the charge
belongs to. A refund on an old payment never touches a newer subscription.

## 3. Event handling and ordering

- New events, all signature-verified and recorded in `billing_events`:
  `charge.refunded`, `charge.dispute.created`, `charge.dispute.updated`,
  `charge.dispute.closed`. The `invoice.paid` / `payment_succeeded` event also
  links its charge to the subscription.
- **Monotone state.** Refunded amounts take the largest reported value. Dispute
  status only moves forward (`needs_response` < `under_review` < `won` / `lost`),
  and `won` / `lost` are terminal. A late or duplicate event therefore cannot
  undo a later fact.
- **Duplicates.** The existing `billing_events` claim already acknowledges a
  processed event without applying it again. Re-applying the same fact is also a
  no-op by construction.
- **Out-of-order payments.** A payment event older than the last applied one is
  recorded as `payment_stale` and ignored. A payment for a subscription that is
  not yet recorded now fails (500), so Stripe redelivers it. This replaces the
  old silent drop. It is a behaviour change, and it is covered by tests.
- **Failed processing** is recorded as `failed` with the error text and answers
  500, so Stripe retries. A failed event grants or revokes nothing. Redelivery
  from the Stripe dashboard applies it once the cause is fixed.

Stripe dashboard setting needed (owner action, not made here): the webhook
endpoint must subscribe to `charge.refunded`, `charge.dispute.created`,
`charge.dispute.updated` and `charge.dispute.closed`. Until it does, Stripe
sends none of these events and nothing is revoked on a refund.

## 4. Tests

- `tests/billing/refund_dispute.test.mjs`: 36 checks covering full and partial
  refunds, refund-to-full, opened / updated / won / lost / warning-closed
  disputes, duplicate refund and dispute events, out-of-order dispute and
  payment events, a dispute that arrives before its charge link, failed
  processing and redelivery, a missing table (migration not applied), bad
  signatures, malformed events, the grace period, cancellation at period end,
  the manual-grant support exception, tester and admin unaffected, and the
  pure helpers.
- `tests/billing/billing_core.test.mjs`: the existing 45 checks, unchanged in
  expectation (one store helper gained the new fields). All pass.

## 5. Deploy order and blockers

Deploying `stripe-webhook` before migration 033 breaks every subscription
event, because the function selects `subscriptions.last_payment_event_at`. So
the order is:

1. Owner approves migration 033 and the policy in section 2.
2. Apply 033 (adds `last_payment_event_at` and `billing_charges`).
3. Update the SQL mirror `public.entitlement_for()` (migration 027) to read
   `billing_charges` with the same holds as `accessHolds()`, and extend
   `tests/billing/fixtures/entitlement_cases.json` with refund and dispute
   cases so the SQL and JavaScript are pinned together. **This change is not
   written yet. It is a blocker before billing is enabled.** Until it lands,
   the SQL side ignores refunds and disputes, so the server must not be the
   source of access for a refunded customer.
4. Redeploy `stripe-webhook`, then subscribe the endpoint to the four charge
   events in section 3.
5. Pre-launch check: replay one refund and one dispute against a test-mode
   endpoint.

## 6. Migration request (not applied)

`scripts/migrations/033_billing_refunds_disputes.sql`, a draft, NOT applied.
Number 032 is reserved by the boundary-storage branch (PR #144), so this takes
033. Adds: `subscriptions.last_payment_event_at`, and `billing_charges` (one row
per charge: refund state, dispute status, subscription link), with the same
privilege pattern as the other billing tables (no client writes, admin read,
service_role writes).

## 7. Still open

- The SQL mirror change in 5.3 is not written, and so it cannot be tested
  against Postgres here.
- No Deno type-check of `stripe-webhook/index.ts` was possible in this sandbox.
  The store methods mirror the JavaScript contract the tests pin, but the Deno
  file has not been compiled.
- Frontend: the two new states have labels (`app.js`, `admin.js`). The SQL does
  not yet emit them, so no customer sees them until step 5.3 lands.
