# Mobile UX audit and first redesign pass (2026-10-23)

Branch `feat/taxacq-mobile-ux`, based on `origin/main` at `40b72d9`. Scope:
phone and tablet chrome of the Auctions list and the full property page. Not
a complete redesign: the Map, Watchlist, login and Home sections are audited
below but only measured, not changed.

## Baseline

- `main` at `40b72d9`. PR #167 (property card layout) is **merged**, so the
  card work is live in the codebase. Its earlier preview, not this one, is what
  the card reviews were based on.
- Open frontend PRs that touch the same screens (not merged, not rebased here):
  #141 (filter drawer), #143 (opaque top bar, countdown), #153 (bid bounds),
  #130 (record trust). Any of them can conflict with this branch; they should
  be reviewed against this change, not stacked on it.
- Viewports measured: 360, 390, 412, 768, 1280 and 1440 px. Preview data is the
  local fixture (9 auction rows), not production (about 1,061), so counts differ
  live. The probe is in the scratchpad, not the repo.

## Audit (390 × 844 unless stated)

| # | Screen | Finding | Severity | Evidence |
|---|---|---|---|---|
| 1 | Auctions | Calendar open by default: first card at **1546 px** on `main` | Critical | `audit-main` |
| 2 | Auctions, detail | 59 of 99 and 83 of 132 controls under 44 px (icon buttons, info bubbles, copy buttons, CTA, chips, summaries) | High | probe |
| 3 | Detail | 16-item section tab bar and an "At a glance" block repeating Decision and Financial | High | screenshots |
| 4 | Auctions | Controls in three rows (county, export, filters) | Medium | 360 px screenshot |
| 5 | Lands, Certificates, Map | Smaller controls remain on Map (19 under 44 px); not changed | Medium | probe |
| 6 | All phone pages | Smallest text is about 11 px | Low | probe |
| 7 | Home | Header search and hero search both visible on first screen | Low | screenshot |

Horizontal overflow: **none** on any route at any tested width, before or after.

## Changes in this branch

- Auction calendar is a single collapsed line, "Auction calendar · next 45 days".
  The data is unchanged. (`public/app.js`, `ledger-status-fold upcoming-fold`)
- On phones the section tabs and the "At a glance" block are hidden. The DOM is
  unchanged, so desktop keeps both. (`public/identity.css`)
- Touch targets of at least 44 px on phones and touch screens for the controls
  the probe found. The rules are in `public/identity.css` because they must
  override later and higher-specificity rules. (`public/identity.css`)
- Auctions and Available controls on phones: county beside Expand all, Export
  beside Filters & Sort, two rows instead of three.
- The Phase 66 "At a glance" and section-nav checks now read a 1280 px page,
  because those blocks are hidden on phones by design.

## Measured result

| Measure | `main` | This branch |
|---|---|---|
| Auctions first card top (390 px) | 1546 px | 954 px |
| Auctions controls under 44 px | 59 | 0 |
| Lands controls under 44 px | 25 | 0 |
| Certificates controls under 44 px | 19 | 0 |
| Property page controls under 44 px | 83 | 3 |
| Horizontal overflow, 360–1440 px | 0 | 0 |

Trade-off, stated plainly: the 44 px targets make the disclosure lines taller,
so the first Auctions card sits about 100 px lower than the calendar-fold
alone would give. A second header pass is needed (see below).

## Not done, and why

- Map: 19 controls under 44 px. The Map has its own pill and toggle markup; it
  was left for its own change so the satellite and outline logic is not touched
  in a chrome pass.
- Header consolidation on Auctions: merging the "What is coming up" bubble, the
  source-status line and the legend would cut about 90 px more. Needs a product
  decision on what Auctions should show above the first card.
- Home: the duplicate header search is a product decision, not a CSS fix.
- Font sizes below 12 px on metadata: not changed; they are one token in
  `identity.css` and easy to change once the layout is agreed.
- Property page duplicates (bid and value in Decision and Financial): audited,
  not merged.
