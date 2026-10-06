# My Research: research lists and customer workflow state (2026-10-06)

The watchlist answers "tell me when this changes". My Research answers a different question: "which properties am I working, and where am I with each?"

## What a customer can do

- **Save a property to a list.** Any property page's "My research" section can save the property to an existing list, or create a list and save into it in one step. Example list names: "October Florida Auction", "South Florida Available", "Due Diligence", "Watch".
- **Set their own research state** per saved property, as a select on the property page and in the list. The states are DISCOVERED, RESEARCHING, DUE_DILIGENCE, ACQUISITION_READY, PASSED and ACQUIRED.
- **Keep a private note** (up to 2,000 characters).
- **Use the My Research page** (`#/research`, the "My Research" entry in the navigation, or "In my research" on Home). It offers:
  - list tabs with counts;
  - create, rename and delete list;
  - a filter by research state;
  - one row per saved property.

  Each row shows the property (opens the property page), county (opens the County Intelligence page), ledger, official status, the customer's research state, saved date and list, upcoming sale date, acquisition-path status, due-diligence status (the next PR) and the note.

## Customer state is never government state

| | Where it comes from | Where it is written |
|---|---|---|
| Ledger (Available / Auctions / Liens & Certificates) | the source record | `properties` (unchanged) |
| Official / source status ("Available over the counter", "sale scheduled", a verified auction result) | the source record, `officialStatusText()` | `properties` / `auction_events` (unchanged) |
| Customer research state | the customer | `research_items.research_state` only |

- The two are always shown side by side and labelled separately: "Official status (from the source)" and "Your research state".
- `updateResearchItem()` refuses anything outside the six customer states before any request, so a value such as "SOLD" or "available" can never be written.
- Migration 029's CHECK enforces the same rule in the database.
- "ACQUIRED" is the customer's own record; it is never written to a property.

## Storage

**Migration 029** (`scripts/migrations/029_research_workspace.sql`) is written and tested. **It is not applied.**

- It adds two tables:
  - `research_lists`: id, user_id, name (1–80 characters), timestamps;
  - `research_items`: list, property (uuid → `properties.id`, cascade), research_state (CHECK of the six states), note (≤ 2,000 characters), `diligence` jsonb (the customer's own review notes, for due diligence), saved_at / state_changed_at / updated_at; unique (list, property).
- Each table has a PERMISSIVE own-row policy and a RESTRICTIVE `is_approved()` policy, both written as InitPlans (`(select …)`).
- Default grants are revoked first; only select / insert / update / delete are granted to `authenticated`.
- A trigger keeps an item in its owner's list and stamps `state_changed_at`.
- Limits: 50 lists and 2,000 saved properties per customer.
- `properties` is not touched.

**Until 029 is applied:**
- the app detects the missing tables (PGRST205) and keeps the same workspace in this browser (`localStorage`, per account);
- every surface says "Kept in this browser only";
- a read error other than "table missing" is shown as an error, never silently replaced by the browser copy.

## Tests

- **Python:** `tests/python/test_migration_029_research_workspace.py`.
  - Static: additive only, RLS pattern, grants, the vocabulary equals app.js.
  - Live, on a local PG16 scratch database, applied twice:
    - an owner creates, saves, moves state and is refused "SOLD";
    - duplicates are refused;
    - another customer, a pending account and anon see or write nothing;
    - nobody can add to another user's list;
    - deleting a list removes only its items.
- **Playwright** block "My Research":
  - server mode (stub tables) and browser-only mode (`?research=none`) across a reload;
  - a refused non-customer state;
  - the official status is unchanged and nothing is added to the property row;
  - list tabs, the state filter, remove, research row → county page;
  - no horizontal overflow at 390 / 430 / 768 / 1024 / 1440 / 1920.

`sw.js` → `tdw-shell-v100`.

## Verification pass (2026-10-06)

- **Status band.** The property page's status band (Ledger / Status / Last read)
  carries a fourth cell, **Your research**. It shows the customer's research
  state and lists, or "Not saved". It is marked with a dashed copper rule and
  labelled "(your label, not an official status)", so it never reads as, or
  replaces, the official status beside it. Tapping it jumps to the My research
  section.
- **Section order.** The full My research section now follows the property
  intelligence: How to acquire → Financial position → Overview / Decision /
  Inventory → Tax & Value / Property / History → **My research**. The cell at
  the top keeps it from being buried.
- **My Research page.**
  - A pipeline strip gives one count per research state, a count and never a
    score; a step filters the table.
  - The table's columns are grouped "From the records" (official status,
    upcoming sale, acquisition path, due diligence) and "Your workflow" (your
    state, saved, your note), with the second group shaded.
  - An empty workspace explains the four steps and links to Available and
    County Intelligence.
- **Home guide.** Step 2 names County Intelligence and step 4 ("Save & work
  it") names My Research and the due-diligence checklist, each with a link.
