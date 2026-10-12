# Legal, support and source-disclosure readiness (2026-10-05)

Billing is out of scope and stays off (`config.js billing.enabled: false`).
Migration 027 is unapplied and the Stripe functions are not deployed.

## What the repository provides

- **Legal pages.** Terms, Privacy, Acceptable Use and the Source & Research
  Disclaimer each load `legal.js`. It fills operator, governing law,
  effective date and contact from `config.js`, and shows "[not configured]"
  for anything blank, with a notice at the top of the page. Nothing is
  invented.
- **Source disclaimer.** It now states:
  - that publication by a government office does not, by itself, establish
    permission for commercial reuse;
  - that each source carries a review status (approved / under review /
    blocked), that only approved sources are offered to customers, and that
    blocked sources are never collected.

  This matches what the code enforces: the publication gate
  (`isCustomerPublishable`) and the collection gate
  (`source_publication.collectable`).
- **`scripts/legal_readiness_check.py`.** A repository-only report of the
  blank owner values and of the page structure. `--strict` exits 1 while
  anything is missing. It also fails if billing is switched on.

## Values only the owner can supply (blank today)

| config.js key | What |
|---|---|
| `legal.operatorName` | The operator's legal business name |
| `legal.governingLaw` | Governing law / jurisdiction |
| `legal.effectiveDate` | Effective date of the documents |
| `supportEmail` (or `legal.contactEmail`) | Support / contact e-mail |

The Privacy Policy and Terms text are templates and should be reviewed by
counsel before a paid launch. No business address is printed anywhere. If
counsel wants one, it is a new owner-supplied value, not something to fill
in from guesswork.
