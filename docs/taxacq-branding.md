# TAXACQ: the customer-facing brand (2026-10-06)

**TAXACQ** is the product name customers see. Where a subtitle helps, it is
**Tax Acquisition Intelligence**. The product promise on the sign-in screen
is: *Find the property. Understand the record. Know how to acquire it.*

Only customer-facing text changed. The repository (`taxdeed-scraper`), the
Python packages, the modules, the database tables, the migration files, the
source identifiers, the URLs and the production domain
(`rodz-taxdeeds.pages.dev`) are unchanged. No redirect and no deployment
setting was touched.

Status of the name:
* TAXACQ has **not** been cleared as a trade name. That is still blocker 16 in
  `docs/legal/pre-sale-blockers.md`.
* No domain has been checked or claimed.

## Classification of every occurrence

The search covered "TaxDeed-Scraper", "taxdeed-scraper", "Tax Deed Scraper"
and the earlier interim name "Tax Acquisitions". Only category A was changed.

| Category | What | Files | Changed |
|---|---|---|---|
| **A. Customer-facing branding** | Page `<title>`; sign-in, pending-approval and plan screens (`<h1>`, tagline, split-screen mark); desktop masthead and phone top bar; About heading "Why …"; the iOS home-screen title meta | `public/index.html`, `tx.html`, `la.html`, the nine generated state pages | yes → TAXACQ |
| A | PWA manifest `name` / `short_name` | `public/manifest.webmanifest` | yes → "TAXACQ — Tax Acquisition Intelligence" / "TAXACQ" |
| A | The tab title app.js writes after sign-in, and the support e-mail subject | `public/app.js` | yes → "… · TAXACQ — <State>", "[TAXACQ] …" |
| A | Legal pages (title and the "… service" sentence) and the admin page | `terms.html`, `privacy.html`, `acceptable-use.html`, `source-disclaimer.html`, `admin.html` | yes, "Tax Acquisitions" → TAXACQ |
| A | Digest e-mail footer | `supabase/functions/send-digest/index.ts` | yes; source only, the edge function was **not** deployed |
| A | Deployed-shell check (what a signed-out visitor is served) | `scripts/check_deployed_branding.py` | the expected tagline is now "Tax Acquisition Intelligence"; the title and sign-in block must carry TAXACQ; the old name in visible text or meta content is reported |
| **B. Internal technical identifier** | Outbound `User-Agent: taxdeed-scraper/1.0 (+github…)` in harvesters and syncs; the `tdw-shell-*` cache prefix; `tdw_*` storage keys; CSS / design-language comments; `sw.js` version-history comment | `scripts/*.py`, `scripts/*.ps1`, `harvesters/acquisition/transport.py`, `public/sw.js`, `public/identity.css` (comment header only) | no |
| **C. Source / repository / deployment identifier** | Repository name and URLs; MapTiler key label `taxdeed-scraper-site`; the `rodz-taxdeeds.pages.dev` domain and its CORS allow-list in edge functions | `CLAUDE.md`, `config.js` comment, `supabase/functions/*` | no |
| **D. Test fixtures that use the technical name on purpose** | User-Agent assertion; branding-check fixtures showing the old name *is* reported; the "comments are not visible text" fixture | `tests/python/test_laft_lifecycle.py`, `tests/python/test_check_deployed_branding.py` | no (they test the rule) |
| Historical documentation | Dated sprint docs naming the identity at the time | `docs/identity-redesign.md`, `docs/ui-redesign.md`, `PHASE_4_SUMMARY.md`, … | no; `CLAUDE.md` gains a section saying the name is superseded |

Source and provenance labels are never rebranded. "Florida Department of
Revenue", county, parish and land-bank names, and every name in
`acquisition-evidence.json`, `source-inventory.json` and
`county-intelligence.json` stay as the source publishes them. A test pins
that none of those files contains "TAXACQ".

## Regression tests

* `tests/python/test_taxacq_branding.py` checks:
  * every state page's title, its three auth screens, masthead, top bar,
    tagline, promise and About heading;
  * that no customer page shows the repository name in visible text or
    accessible attributes (comments are not visible);
  * the manifest, the app.js title and support subject, and the digest
    footer;
  * that the root copies equal `public/`;
  * that source files are not rebranded;
  * that the technical identifiers (User-Agent, cache prefix, packages,
    production domain, repository URL) are unchanged.
* `tests/python/test_check_deployed_branding.py`: the deployed check reports
  the old name, a missing TAXACQ title and a missing tagline.
* `tests/run_test.mjs` `taxacqBrand` checks the signed-in app in a browser:
  * the tab title, rail and top-bar brand, and the subtitle;
  * no old name in `innerText`, the title, or any `aria-label` / `title` /
    `alt`;
  * "Why TAXACQ" in About.

  The existing title and login pins now expect TAXACQ.

`sw.js` → `tdw-shell-v107`, so returning visitors get the new shell.
