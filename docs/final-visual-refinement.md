# Final visual refinement (2026-10-05)

A refinement pass on the approved identity (`docs/identity-redesign.md`). The
design system, navigation, data semantics, harvesters, sources and production
configuration are unchanged. Every value shown below is a field the record
already carries, or a stated absence.

## Three ledgers, three questions

Each ledger head now opens with the question that ledger answers, in its own
semantic colour (`LEDGERS[...].question` in `app.js`; Texas keeps its own
third ledger):

| Ledger | Colour | Question |
|---|---|---|
| Available | sage | What can I acquire now? |
| Auctions | rust / copper | What is coming up for sale? |
| Liens & Certificates | plum | What tax lien or certificate am I buying? |
| Texas: Redeemable Deeds | plum | What redeemable deed am I looking at? |

On the List page, the page title already names the ledger. The section head
therefore leads with the question and keeps its `h2` for screen readers only,
instead of repeating the ledger name. The colours stay accents: the ledger
head's top rule, the figure labels on cards, and the headline figure's rule.
They are never page backgrounds.

## Property page: a research dossier

The page reads in this order:

1. **Identity:** kicker, address and actions.
2. **Current status** (`detailStatusHtml()`): ledger, status (the card kicker's
   phase) and when the source was last read ("Not recorded" when it was not).
3. **How to acquire:** still the one stone panel on the sheet.
4. Summary, decision, inventory, **financial**, **property**, **history** and
   sale events.
5. Risk & Legal. The Florida manual lien-notes banner now sits here, instead
   of interrupting the path from status to acquisition.
6. Map, then **Source truth**.
7. Legal description, **Research & Sources** (documents) and provenance.

Sections are numbered in reading order with a CSS counter, like a brief. The
counter is presentation only; no id, `data-section` value or nav pill changed.

## Source truth: one citation shape

`sourceTruthHtml()` now always shows the same rows, in a fixed order:

- **Source record:** the dataset name with its publisher. When no dataset name
  is recorded, the publisher alone, marked "Dataset name not recorded".
- **Last read:** with first observed.
- **Source date.**
- **Publication status.**
- **Source health.**
- **Acquisition path** (Available) or **Sale process** (Auctions): verified
  label and date, or "Not yet verified".
- **Price** (Available, from `amountInfo()`), the auction bid label, or
  **Certificate amount**: the figure, or "Not published".
- **Official listing.**
- **County intelligence.**

A lede says it plainly: "The record as its source publishes it. Nothing here
is inferred or scored." There is no confidence, score or "AI" wording.

## Cards, dossier and sign-in

- **Cards:** figure labels take the ledger colour, addresses use the display
  serif, and fact labels are uppercase micro-labels. Nothing was added to the
  card.
- **County dossier:** monospaced section heads, and the ledger name in its
  ledger colour.
- **Sign-in:** the design is unchanged; only the following were adjusted.
  - Each field label sits above its field with clear spacing.
  - Inputs are at least 44px tall, with a copper focus ring.
  - Hidden sign-up fields stay hidden (`:has(input[hidden])`).

## Wide screens (1920)

`styles.css` turns the card list into a multi-column grid from 1600px. Each
row was then narrower than its container query assumed, and the identity
column was squeezed to 0px, so the kicker ran under the figures. Editorial
rows are now one per line at every width (`identity.css`). The refinement test
block checks for this.

## Phones (390 / 430 / 768)

- The status strip uses two columns.
- Source truth and the acquisition checklist stack label over value.
- The section nav scrolls sideways inside itself, never the page.
- An empty minimap slot takes no space.

## Tests

- `tests/run_test.mjs`, block "Final visual refinement":
  - each ledger's question;
  - the status strip;
  - the Source truth labels;
  - no score or "AI" wording;
  - no horizontal overflow at 390, 430 and 768 px;
  - no squeezed row columns at 1440 and 1920 px;
  - sign-in fields at least 44px tall;
  - hidden sign-up fields stay hidden.
- `sourceTruth` pin updated for the new labels.
- `sw.js` → `tdw-shell-v92`.
