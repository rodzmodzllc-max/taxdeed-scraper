# Billing options: audit and comparison (2026-10-13)

Every fact below was read from `origin/main`. Nothing is configured: `config.js`
has `billing.enabled: false` and no price. Prices are **hypotheses**, not
validated, and need customer conversations before any is published.

## What exists today

- `supabase/functions/_shared/billing_core.js`: entitlement states (active, trial,
  cancelling, payment-failed grace, payment failed, cancelled), a 7-day grace
  period after `past_due`, Stripe signature verification with a 300 s tolerance,
  per-event idempotency (`claimEvent` returns `duplicate`), and a stale-event
  guard (`stripe_event_created`). Covered by 76 Node tests.
- `stripe-webhook`, `billing-checkout`, `billing-portal` edge functions. Checkout
  takes the price and account from the server; the webhook is the only writer of
  subscription state; a checkout redirect never grants access.
- `plansFromEnv` reads **one** price, `STRIPE_PRICE_ID` (monthly).
- Migration 027 (not applied) defines `billing_customers`, `subscriptions`,
  `billing_events`, and a paid-beta source scope on `properties`.

## Gaps found by reading the code

1. **No annual plan.** `plansFromEnv` maps only a monthly key. Annual needs a second price, a mapping, and a UI choice.
2. **No refund handling.** `charge.refunded` and `charge.dispute.*` are not handled, so a refund alone leaves access unchanged.
3. **No trial in checkout.** `checkoutSessionParams` sets no `trial_period_days`. A trial would have to come from the Stripe price.
4. **Failed payments** are handled (`invoice.payment_failed` → grace, then payment failed). Recovery through the customer portal is possible; there is no in-app dunning message beyond the status text.
5. **Cancellation** is handled (`cancel_at_period_end` → cancelling; access continues to period end).
6. **Subscription changes** (plan change) are not modelled; only one price exists.

## Options

| | A. Free preview / lead | B. One monthly plan | C. Monthly + annual | D. Professional tier |
|---|---|---|---|---|
| Hypothesis price | $0 | $49–99 / month (unvalidated) | B plus an annual discount, e.g. 2 months free (unvalidated) | not justified |
| Included | tester-preview scope only | paid-beta sources (5 today) | same as B | no extra feature exists to charge for |
| Existing support | `publicationMode: preview`, tester role | `entitlement_for`, webhook, checkout | needs a second `STRIPE_PRICE_ID`-style key and UI | none |
| Stripe needs | none | one product, one monthly price, webhook | plus one annual price | more prices, no evidence |
| DB migrations | none | 027 | 027 | 027 plus more |
| Secrets | none | `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, `STRIPE_PRICE_ID` | plus annual price id | same |
| Trial / refund / dup / change | n/a | trial via Stripe price; refunds unhandled (gap 2) | same, plus plan-change not modelled | same gaps |
| Expiry / failed payment | n/a | grace 7 days then no access | same | same |
| Risk | leads only | **charging for sources not all approved for display** (only the 5 paid-beta sources are sold; the rest stay withheld) | same | higher exposure with no added value |

## Recommendation

Launch **A + B**: a free preview (what testers already get) and one monthly plan
limited to the paid-beta sources. Do not add C until B has paying customers, and
do not build D: there is no professional feature to charge for.

Before any charge:
1. Apply migration 027 (owner approval).
2. Handle `charge.refunded` in the webhook (new code, with tests).
3. Confirm each of the five paid-beta sources is approved for display and sale in writing.
4. Decide the price from interviews, not from this document.

Nothing here enables billing, creates a Stripe product or price, or sends a charge.
