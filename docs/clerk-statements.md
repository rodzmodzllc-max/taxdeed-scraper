# Florida Lands Available clerk statements (read-only harvester)

`scripts/harvest_clerk_statements.py` reads the clerk's per-case "List of
Lands" purchase statement from Pioneer TaxSmartWeb portals and produces
`out/clerk_statements.json` in the `otc_provenance.purchase_statement` shape
the app already renders (PR #82). **It writes nothing to any database and is
wired into no workflow.**

## Source (read-only captures, 2026-10-05)

| Item | Finding |
|---|---|
| Portal | `https://search.citrusclerk.org/TaxSmartWeb` (Citrus); one deployment per county (`data/laft_pioneer_counties.csv`) |
| Lookup | `Home/GridSearchData?SearchType=Lands Available` -> row id -> `Home/Details?id=<row id>` |
| Statement | a docket entry ("LOL <date>" in Citrus) linking `Home/Image/<doc id>`, a PDF |
| Public | yes - no sign-in, CAPTCHA or WAF on the portal, the details page or the image |
| Document | scanned image, **no text layer**; OCR (tesseract) required |
| Labels (Citrus OCR) | Opening Bid, Lands Available Interest, Omitted Taxes, Total Omitted Taxes, Documentary Stamp Tax, Deed Recording Fee, Lands Available Total, Valid Through |
| Identifier | the case number on the grid row (and on the statement) |
| Current obligation | the statement total is the clerk's amount due **only until** its valid-through date; interest accrues monthly (F.S. 197.502(7)) |
| History | several dated LOL entries per case: re-issued statements, kept as history |
| Terms | "makes no warranty or guarantee concerning the accuracy or reliability"; "Official Record images ... have not been certified as being true and correct copies". **No reuse licence and no reuse prohibition found.** Technically public; reuse permission not established. |

Other Pioneer counties: Duval has "LANDS AVAILABLE ... STATEMENT" entries but
OCR found none of the labels; Palm Beach labels partial; Levy only a "LIST OF
LANDS LETTER"; Bay and Hernando no statement entry. None is configured.

## Statement structure (Citrus, read value-free from OCR, run 37253789695)

The newest Citrus statements print three subtotals; each is checked:

    OPENING BID + LANDS AVAILABLE INTEREST + TOTAL OMITTED TAXES = LANDS AVAILABLE TOTAL
    LANDS AVAILABLE TOTAL + DOCUMENTARY STAMP TAX + DEED RECORDING FEE
        + AFFIDAVIT RECORDING FEE                                = LOL TOTAL
    LOL TOTAL - LESS ... RECORDING FEES                          = TOTAL DUE FROM PURCHASER

Per-year "Omitted Taxes" lines sit inside TOTAL OMITTED TAXES and are never
added again. Older statements in the same docket carry no TOTAL DUE FROM
PURCHASER line.

## How a figure is accepted

1. OCR the statement (300 dpi, first pages); keep every line that ends in an
   amount, with its label.
2. For each line the configuration names (by the statement's own label),
   collect the candidate amounts - OCR noise produces extra candidates (a
   doc-stamp RATE line, a "$" read as "8").
3. **VERIFIED only when exactly one choice of candidates satisfies all three
   subtotals to the cent.** No solution = `OCR_UNVERIFIED`; two different
   consistent readings = `AMBIGUOUS`; no total line = `NO_TOTAL`.
4. The record keeps the clerk's **printed** Total Due from Purchaser - never
   our sum - plus its valid-through date, the components (recording netted
   exactly as the statement nets it) and the printed subtotals.
5. **Current = the verified statement from the docket's newest statement
   document.** If the newest one does not verify, there is no current figure;
   an older verified statement is history only. A past valid-through date is
   Expired in the app; nothing is refreshed without a new statement.

## Dry runs (value-free), 2026-10-05

- Run 37253656360 (first parser, flat sum): 0 VERIFIED - the flat model was
  wrong (the statement is a chain of subtotals).
- Run 37253991507 (subtotal chain): Citrus 5 rows, 1 with statement
  documents (9 dated LOL entries): 1 VERIFIED, 1 OCR_UNVERIFIED, 3 NO_TOTAL,
  4 NO_LABELS.
- Run 37254130383 / 37254269522 (value-free comparison with the customer's
  screenshot): the case matches (2024-0075TD) and the verified statement's
  opening bid equals the grid's base bid; but the verified statement is an
  **older** issue (total lower, valid-through earlier than 8/31/2026). The
  **newest** statement - the screenshot's $27,689.42 / 8/31/2026 - did not
  verify. Under rule 5 the harvester therefore reports **no current figure**
  for the case and keeps the older one as history.

## Production write - NOT authorized, NOT performed

When (and only when) a statement verifies and the owner approves both the
reuse of the clerk documents and the write, it would be:

- table `public.properties`, rows matched by `(state='FL', source='laft',
  county, case_no)` exactly - never by parcel or address;
- one jsonb key set inside `otc_provenance`: `purchase_statement`
  `{county, case_no, total_due, valid_through, statement_date, document_url,
  observed_on, publisher, components, docket_label, basis}` and
  `purchase_statement_history` (array of the same);
- no column change, no migration, no change to `bid` / `purchase_amount` /
  `purchase_amount_kind`;
- example (Citrus 2024-0075TD, from the customer's screenshot, not from
  this harvester): before `otc_provenance.purchase_statement` absent ->
  after `{total_due: 27689.42, valid_through: "2026-08-31", ...}` - which the
  app would show as **Expired** today;
- affected rows today: **0 current** statements (the newest Citrus
  statement does not verify), 1 historical statement (Citrus 2024-0075TD).
  Writing only a superseded, expired historical figure is not proposed.
