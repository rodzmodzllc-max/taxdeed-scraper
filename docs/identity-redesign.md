# TaxDeed-Scraper identity redesign (2026-10-05)

TaxDeed-Scraper is public property acquisition intelligence. Its look should
be editorial and record-oriented: property, source, status, money and how to
acquire. It should not read as a generic dark SaaS dashboard. This change is
frontend only. Data semantics, harvesters, sources, the three-ledger
architecture and production configuration are unchanged.

## Design language (`public/identity.css`)

- **Loading:** loaded last on every app page (after `styles.css` and
  `explore.css`). It re-skins the existing markup; no id, class or data
  attribute changes meaning.
- **Palette:**
  - warm stone page `#F3EFE8`, near-white raised surface `#FFFDF9`, hairline
    `#D9D1C3`;
  - charcoal type `#24221F` and section rules;
  - burnt copper `#A4512A` as the brand accent.
- **Ledger colours:** sage `#4E6B54` (Available), rust `#A4512A` (Auctions),
  plum `#6B4A6E` (Liens & Certificates). Each one drives the existing
  `--led-*`, `--c-*` and `--lc` tokens, so buttons, focus rings, tabs, map
  markers and county shading follow the ledger.
- **What is gone:** no navy, no gradients as identity, no glow, no glass, no
  floating shadows.
- **Light is the product.** "Auto" no longer follows a dark operating system.
  Dark is an explicit choice in the account menu, in warm charcoal rather
  than navy.
- **Type:**
  - a serif display face (Source Serif 4, falling back to Georgia) for page,
    property and section titles;
  - IBM Plex Sans for reading;
  - IBM Plex Mono with tabular figures for every number;
  - compact uppercase eyebrows for labels.
- **Components:**
  - rectangular buttons (3px radius) and squared tags instead of pills;
  - sections separated by a 2px charcoal rule plus hairlines, not boxed cards.

## Layout

- **Desktop (≥1024px): a masthead, not a sidebar.** The old left rail is a
  two-row masthead:
  - row 1: brand plus utility links (Saved Searches, Watchlist, County
    Intelligence, About, Account);
  - row 2: product navigation (Home, Search, Available, Auctions,
    Liens & Certificates, Map), with the active entry underlined in its
    ledger colour.

  Below the masthead, the sticky command bar holds the search, the state
  selector and the account.
- **Markup:** the rail's buttons are now two lists, `.nav-primary` and
  `.nav-secondary`. They keep the same ids, data attributes and behaviour.
  "States & Counties" is labelled "County Intelligence"; it opens the state
  picker, which now carries the coverage explorer.
- **Phone / tablet:** compact header, search first, and a light bottom bar
  with the active item in copper. The bottom bar is hidden on the sign-in,
  pending and plan screens; it used to show there.
- **Home:** a workstation.
  - "Find property" serif headline and a large search bar;
  - the three products as a ruled band of destinations;
  - `#homeDesk`: Available now (editorial rows with amount, amount type,
    acquisition, source and last read), Upcoming auctions (a dated
    timeline), County intelligence (counties with their intelligence state),
    Saved (watchlist and saved searches);
  - Recent changes (newly observed) as a ruled list, then the operating view.
- **Property rows:** in a list at least 640px wide (a container query), a row
  reads image | identity, acquisition and facts | money and actions.
  - Certificates drop the image column: the instrument sits left, its
    figures right.
  - Below 640px the same blocks stack.
  - The DOM order is unchanged.
- **Auctions:** the ledger head carries an "Upcoming sales" timeline (date,
  county, sale, number of properties) built from the rows' own `sale_date`.
  An event filters the List to its county.
- **Property page:** a research sheet, 960px wide on desktop.
  - serif title and ruled sections;
  - **How to acquire** is the signature: a stone panel under a charcoal top
    rule, with an "Acquisition" eyebrow, a serif heading and the
    fourteen-item checklist as a ledger.
  - Source truth now sits with the source and provenance sections, after the
    map.
- **County dossier:** a research brief - "Tax sale intelligence" eyebrow,
  serif county title, ruled ledger sections with a ledger-coloured edge.
  Sources show readable names and publishers instead of raw ids.
- **Map:** neutral stone basemap (no blue sea), squared ledger pills, and
  markers in the ledger colour (charcoal for all ledgers).
- **Sign in / sign up:**
  - desktop: an editorial split - a drawn parcel plat (inline SVG, no image
    request, abstract linework) on charcoal, beside the sign-in sheet;
  - phone: brand, headline, then the form;
  - headline "Public Property Acquisition Intelligence", the supporting
    lines, and three plain points (search, track, save).

## Naming

The product name is **TaxDeed-Scraper** everywhere in the app:

- the sign-in brand;
- the static page title "TaxDeed-Scraper — Public Property Acquisition
  Intelligence";
- the signed-in tab title "<ledger> · TaxDeed-Scraper — <state>";
- the support e-mail subject.

`scripts/check_deployed_branding.py` now expects the new tagline. The legal
pages (`terms.html`, `privacy.html`, `acceptable-use.html`,
`source-disclaimer.html`) and `admin.html` still say "Tax Acquisitions".
Renaming the service in legal text is a decision for the owner and was not
made here.

## Not claimed

The Available header keeps its existing, accurate copy. The suggested
"currently available through verified acquisition paths" was not used,
because not every Available row has a verified path.

## Tests

- **`tests/run_test.mjs`, "Identity redesign" block:**
  - sign-in, sign-up, Home, the three ledgers and the county dossier at
    390, 430, 768, 1024, 1280, 1440 and 1920px;
  - no horizontal overflow;
  - the split visual only from 900px;
  - masthead on desktop, bottom bar below;
  - the Home workstation present;
  - no navy surface left.
- The existing viewport sweep (390–1920px, including 430px) still checks
  overflow and 44px touch targets.
- `desktopCertCardIsRow` now accepts a flex row or a grid with at least two
  columns.
- Pins updated for intended changes: titles, tagline, nav order, Home
  headline, detail section order.
