# First-run guide, touch targets and search while loading (2026-10-05)

Stacked on the saved-searches PR.

## First-run guide (Home)

`#homeGuide` is five short steps above the ledger cards. Every line comes
from this state's loaded data; nothing is a sample figure, score or
estimate.

1. **Find**: the number of active records and the counties they span.
   While the ledgers are still loading, the count is followed by "so far".
2. **Research**: what a property page holds (values, source, last read,
   per-field origin).
3. **Verify how to acquire**: "N of M available properties have a verified
   acquisition path; the rest say 'Not yet verified'", plus a reminder to
   confirm with the official source.
4. **Save**: the watchlist cap and how many are saved now.
5. **Track**: the number of saved searches for this state, and where
   changes show.

"Hide this guide" stores `tdw_home_guide_hidden_v1` per browser, and "How
this works" brings the guide back. The step buttons open the List (landing
ledger), the watchlist and the saved searches.

## Touch targets

At ≤768px, or on a coarse pointer, these controls are at least 44px tall
(`explore.css`, which loads last):

- the state selector and account button;
- the ledger tabs and "Map view";
- the Map page's search, county select and ledger pills;
- the guide's buttons and saved-search actions;
- "How to acquire" links.

Measured before the change: 28-37px, and 16px for the inline "Change
state" link.

## Viewport sweep (test)

Home, the FL and LA Lists, the Map page and a property page are each loaded
at 390, 768, 1024, 1280, 1440 and 1920px. The test checks two things:

- no horizontal page overflow at any width (strips that scroll inside their
  own container, such as the ledger tabs and summary chips, are by design);
- the controls above are at least 44px at 390px.

## Search while ledgers load

Global search runs over the records loaded so far: it is local, debounced
at 120ms, and makes no network request.

- While a ledger is still loading, the results say "Still loading some
  <state> records - results may grow". A miss reads "no match in the
  records loaded so far", never a final "no match".
- When a ledger failed to load, they say results may be incomplete.
- Open results refresh as background ledgers arrive.
