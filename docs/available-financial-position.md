# AVAILABLE: financial position and documents & links (2026-10-05)

Frontend and shared-rule work for every Available source. There is no
migration, no new data and no source change. Every value shown comes from a
stored field, from the source's terms row (`data/available_financial_terms.csv`)
or from a stored clerk statement.

## Financial position

The rule lives in `harvesters/sources/financial_position.py`, mirrored by
`financialPositionCore()` in `public/app.js`. Both are pinned by
`tests/python/fixtures/financial_position_cases.json`: the Python test checks
the rule, and the browser test runs the same vectors.

The property page's **Financial position** section (`data-section="money"`)
sits right after How to acquire and has these parts:

| Part | What it shows |
|---|---|
| Current acquisition amount | The source's own figure under the source's own label. It is authoritative only when it is a current clerk statement total, or when the source calls the figure the price. An opening bid stays an opening bid. |
| Known tax obligation | Taxes, interest and penalties. A stored current statement shows its printed amounts, marked "included". For a starting figure, it names the items the source says are inside the figure and the items added on top (amount not published). A value (assessed, market, taxable) is never a tax owed: a test proves no value column reaches this code. |
| Known fees | Documentary stamps, recording and clerk fees, with the same three statuses. |
| Other published amounts | Any other component the statement printed. |
| Application / advanced costs, Deposit | Always separate, with the source's own statement of whether they are in the price (yes / no / unknown). Never added. |
| Total | The source's own current total, or "Not published", with how to obtain the official figure. A total is never computed from parts. |

Double counting is impossible by construction. A current statement's parts
are "included" and its total is the total. A starting figure's additions
carry no amount, so nothing is summed. The Florida "inside the opening bid"
note comes from the terms row (F.S. 197.502(6)) and applies only to the
sources whose terms say so. No other state inherits it.

## Documents & links

The rule lives in `harvesters/sources/acquisition_documents.py`, mirrored by
`classifyAcquisitionLink()`. Both are pinned by
`tests/python/fixtures/acquisition_documents_cases.json`.

Each link on a record is classified as one of:
- **Purchase / apply online:** a web page, never a file.
- **Form:** application, bid, offer or request forms, including any PDF
  stored as an "online purchase".
- **Instructions:** the office's process.
- **Document:** a list PDF, a statement or a policy.
- **Official listing page.**

A link that is not `https://` is never shown. The section
(`data-section="documents"`) sits after Source truth. Each entry names its
host.

## What the data allows today (read-only production count, 2026-10-05)

No stored clerk statement exists yet, so no record shows an authoritative
current total. The parts table says "Not published" or names the additions.
Application costs (Louisiana) and the deposit (Galveston, TX) come from the
terms table.
