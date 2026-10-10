# Customer testing script (invited tax-sale investors)

This is a moderated, task-based session of about 45 minutes, with one participant at a time, on the production site (`https://taxacq.com`) using a tester account.

**No sessions have been run yet. There are no results to report.** Record the results in the sheet at the end. Never paraphrase a participant into an endorsement.

## Before the session

- **Account:** create a tester account (approved, tester preview on). Note the date, the browser and the device.
- **Records to use:**
  - pick one county per ledger from `docs/record-quality-benchmark-results.md`;
  - note three record ids per county;
  - include at least one record whose acquisition path is "Not yet verified";
  - include one record that is stale.
- **Script discipline:**
  - read each task aloud exactly as written;
  - do not explain the interface or name a section;
  - if a participant is stuck for 3 minutes, mark the task "not completed" and move on.
- **Record:** screen and voice, with consent. Use a timer per task.

## Warm-up (5 min)

1. "Which counties and states do you buy in? How do you find properties today?" Record the tools named, the paid subscriptions and the spreadsheets.
2. "Walk me through the last property you researched. Where did you lose time?"

## Tasks (time each one; note wrong interpretations verbatim)

| # | Task as read to the participant | Success means |
|---|---|---|
| T1 | "Find a property in [county] that is being auctioned at the next tax sale." | Opens a record in the Auctions ledger of that county. |
| T2 | "For that property, where did this information come from, and when was it last checked?" | Names the source, and the last-read date or "not refreshed recently". |
| T3 | "Is this property being auctioned, or can you buy it now without an auction?" | Answers correctly from the ledger and status, without guessing. |
| T4 | "Find a property in [county] that the government is holding and that you could apply to buy." | Opens a record in the Available ledger. |
| T5 | "How would you actually acquire it? Show me the official place or form." | Finds the acquisition steps and the official link or form, or correctly says "not yet verified". |
| T6 | "What don't we know about this property that you'd need to check yourself?" | Names at least two "Not published" / "Not available" / "Origin not recorded" items. |
| T7 | "Find a tax certificate in [county]. If you bought it, would you own the property?" | Answers no, citing the certificate section. |
| T8 | "Save this property, leave, and come back to it." | Finds it again from the watchlist or My Research. |
| T9 | "Write a note about what you still need to verify." | The note is saved and visible on return. |
| T10 | "On your phone: repeat T1 and T5." | Completes them on a phone-width screen. |

For each task, record:
- completed (Y/N), and the time in seconds;
- number of wrong turns;
- **misinterpretations**, for example calling an opening bid the price, calling a disappeared listing sold, or treating a certificate as ownership;
- broken or misleading links (URL plus what happened);
- any information the participant left the site to find (what, and where).

## Debrief (10 min)

1. "Which of these did you trust least, and why?"
2. "What would you have needed to make a bid or application decision without leaving the site?"
3. "Which parts would you pay for? Which wouldn't you?" Record the answer verbatim. Do not suggest prices.
4. "What do you use today instead, and what does it cost you?"
5. "What would make you come back next week?"

## Results sheet (one row per participant × task)

`participant_id, date, device, task, completed, seconds, wrong_turns, misinterpretation (verbatim), broken_link, left_site_for, notes`

## Analysis rules

- **Completion and time:** report the completion rate and the median time per task, with the count of participants (n). With n < 5, give the raw counts, never percentages.
- **Every misinterpretation is a product defect to triage**, whatever the completion rate.
- **Do not combine** "would pay" answers into a willingness-to-pay figure without a priced follow-up.
