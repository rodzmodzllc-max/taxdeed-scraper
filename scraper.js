const puppeteer = require('puppeteer');

let supabaseUrl = process.env.SUPABASE_URL;
const supabaseKey = process.env.SUPABASE_SERVICE_KEY;

// ---------------------------------------------------------------------------
// COUNTY CONFIG
// ---------------------------------------------------------------------------
// Verified live against miamidade.realtaxdeed.com and duval.realtaxdeed.com
// (same DOM structure confirmed on both — this is one shared RealAuction
// "RealTaxDeed" template, so one scraper function covers every county below).
//
// Subdomain convention is "countyname.realtaxdeed.com" (lowercase, no spaces).
// All 15 counties below have had their subdomain confirmed live (Aug 2026).
// Counties that only run Foreclosure sales (no Taxdeed) are left out.
const COUNTIES = [
  { state: 'FL', county: 'Miami-Dade',   subdomain: 'miamidade',   verified: true },
  { state: 'FL', county: 'Duval',        subdomain: 'duval',       verified: true },
  { state: 'FL', county: 'Alachua',      subdomain: 'alachua',     verified: true },
  { state: 'FL', county: 'Marion',       subdomain: 'marion',      verified: true },
  { state: 'FL', county: 'Orange',       subdomain: 'orange',      verified: true },
  { state: 'FL', county: 'Hillsborough', subdomain: 'hillsborough',verified: true },
  { state: 'FL', county: 'Broward',      subdomain: 'broward',     verified: true },
  { state: 'FL', county: 'Palm Beach',   subdomain: 'palmbeach',   verified: true },
  { state: 'FL', county: 'Pinellas',     subdomain: 'pinellas',    verified: true },
  { state: 'FL', county: 'Polk',         subdomain: 'polk',        verified: true },
  { state: 'FL', county: 'Lee',          subdomain: 'lee',         verified: true },
  { state: 'FL', county: 'Volusia',      subdomain: 'volusia',     verified: true },
  { state: 'FL', county: 'Seminole',     subdomain: 'seminole',    verified: true },
  { state: 'FL', county: 'Pasco',        subdomain: 'pasco',       verified: true },
  { state: 'FL', county: 'Sarasota',     subdomain: 'sarasota',    verified: true },
  // All 15 subdomains above confirmed live (each resolves to that county's
  // own splash page, not a 404 or wrong-county page) as of Aug 2026.
  // Add more counties here following the same convention:
  // <countyname>.realtaxdeed.com (lowercase, no spaces/hyphens) — but
  // verify each one before trusting it; the convention holds for these 15
  // but isn't guaranteed (e.g. multi-word counties could break the pattern).

  // Add more counties here as you verify their subdomains. Non-Florida
  // RealAuction states (AZ, CA, CO, ID, LA, NJ, NY, OH, PA, TX, WA) run
  // different products (RealForeclose / RealTDA) on different domains —
  // those need their own template and are NOT covered by this scraper yet.
];

const HOW_MANY_MONTHS_AHEAD = 2; // scan current month + this many future months

// ---------------------------------------------------------------------------
// PARSING HELPERS
// ---------------------------------------------------------------------------

function parseMoney(str) {
  if (!str) return null;
  const n = parseFloat(str.replace(/[^0-9.-]/g, ''));
  return Number.isFinite(n) ? n : null;
}

// ---------------------------------------------------------------------------
// SCRAPE ONE COUNTY'S CALENDAR TO FIND TAX DEED AUCTION DATES
// ---------------------------------------------------------------------------

async function getAuctionDates(page, subdomain, monthsAhead) {
  const dates = [];
  const now = new Date();

  for (let m = 0; m <= monthsAhead; m++) {
    const target = new Date(now.getFullYear(), now.getMonth() + m, 1);
    const mm = String(target.getMonth() + 1).padStart(2, '0');
    const yyyy = target.getFullYear();

    // Verified live: month navigation uses a ColdFusion timestamp literal,
    // not simple month/year query params (that was my first guess and it
    // silently did nothing — always double check calendar UI links directly).
    const selCalDate = `{ts '${yyyy}-${mm}-01 00:00:00'}`;
    const calUrl = `https://${subdomain}.realtaxdeed.com/index.cfm?zaction=user&zmethod=calendar&selCalDate=${encodeURIComponent(selCalDate)}`;
    await page.goto(calUrl, { waitUntil: 'networkidle2', timeout: 60000 });

    const monthDates = await page.evaluate(() => {
      const found = [];
      // Verified live: calendar days are NOT <td> cells — the whole
      // calendar renders inside one big <td>, and each day is a
      // `div.CALBOX`. Inside a day with an event, the day number is a
      // raw text node directly in the CALBOX (e.g. "6 Tax Deed0 / 9 TD..."),
      // followed by a `span.CALTEXT` holding the event details. My first
      // version queried `td` elements and tried to read the day number
      // from the box's first *element* child — which is that CALTEXT
      // span, not the day number — so extraction silently failed on every
      // county (0 dates found everywhere) despite the page itself loading
      // fine. Reading the box's own leading text instead fixes it.
      document.querySelectorAll('div.CALBOX').forEach(box => {
        if (/Tax Deed/i.test(box.textContent) && /\d+\s*\/\s*\d+\s*TD/i.test(box.textContent)) {
          const dayMatch = box.textContent.trim().match(/^\d+/)?.[0];
          if (dayMatch) found.push(dayMatch);
        }
      });
      // Diagnostic info so a future 0-results run tells us WHY from the
      // logs alone, instead of needing another manual investigation round:
      // if calboxCount is 0, the page didn't render the calendar as
      // expected (wrong content/layout/blocked); if calboxCount is high
      // but found stays empty, the extraction regex itself needs another
      // look.
      return { found, calboxCount: document.querySelectorAll('div.CALBOX').length, pageTitle: document.title };
    });

    if (monthDates.found.length === 0) {
      console.log(`    [debug] ${mm}/${yyyy}: 0 dates found, calboxCount=${monthDates.calboxCount}, pageTitle="${monthDates.pageTitle}"`);
    }

    monthDates.found.forEach(day => {
      dates.push(`${mm}/${String(day).padStart(2, '0')}/${yyyy}`);
    });
  }

  return dates;
}

// ---------------------------------------------------------------------------
// SCRAPE ALL PROPERTIES FOR ONE AUCTION DATE (WITH PAGINATION)
// ---------------------------------------------------------------------------

async function scrapeAuctionDate(page, subdomain, dateStr) {
  const url = `https://${subdomain}.realtaxdeed.com/index.cfm?zaction=AUCTION&Zmethod=PREVIEW&AUCTIONDATE=${dateStr}`;
  await page.goto(url, { waitUntil: 'networkidle2', timeout: 60000 });

  const allItems = new Map(); // itemId -> data, dedup across pagination clicks

  // IMPORTANT (verified live against a real 185-property Duval auction):
  // The preview page has TWO independently-paginated sections, "Running
  // Auctions" and "Auctions Closed or Canceled", each with its own
  // "Next Page" image (both sections render a top AND bottom copy of their
  // button, so there are 4 `img[alt="Next Page"]` elements total: indices
  // 0/1 = Running Auctions, indices 2/3 = Closed or Canceled). Naively
  // clicking "the first visible Next Page image" only ever paginates the
  // first section and silently drops everything past page 1 of the second
  // section — on the 185-item test auction this lost 48 properties (only
  // 137/185 captured) until fixed to paginate both sections separately.
  const extractCurrentPageItems = () => page.evaluate(() => {
    const results = [];
    document.querySelectorAll('div.AUCTION_ITEM').forEach(item => {
      const data = { itemId: item.id };

      const statusEl = item.querySelector('.Astat_DATA');
      data.status = statusEl ? statusEl.textContent.trim() : null;

      const rows = item.querySelectorAll('table.ad_tab tr');
      let lastLabel = null;
      rows.forEach(r => {
        const lbl = r.querySelector('td.AD_LBL');
        const val = r.querySelector('td.AD_DTA');
        if (!val) return;
        const label = lbl ? lbl.textContent.trim().replace(':', '') : '';
        if (label) {
          data[label] = val.textContent.trim();
          lastLabel = label;
        } else if (lastLabel) {
          // Some counties (e.g. Duval) split the address across two rows:
          // "Property Address" -> street, then an unlabeled row -> city/zip
          data[lastLabel] = (data[lastLabel] || '') + ', ' + val.textContent.trim();
        }
      });

      const link = item.querySelector('a[href*="folio"], a[href*="parcel"], a');
      data.parcelLink = link ? link.getAttribute('href') : null;

      results.push(data);
    });
    return results;
  });

  async function paginateSection(nextImgIndex) {
    let stagnantRounds = 0;
    const MAX_ROUNDS = 40; // safety cap; real auctions have seen ~14 pages

    for (let round = 0; round < MAX_ROUNDS && stagnantRounds < 2; round++) {
      const pageItems = await extractCurrentPageItems();
      const before = allItems.size;
      pageItems.forEach(it => allItems.set(it.itemId, it));

      const clicked = await page.evaluate((idx) => {
        const nextImgs = Array.from(document.querySelectorAll('img[alt="Next Page"]'));
        const img = nextImgs[idx];
        if (!img) return false;
        const style = window.getComputedStyle(img);
        if (style.display === 'none' || style.visibility === 'hidden' || img.classList.contains('disabled')) {
          return false;
        }
        img.click();
        return true;
      }, nextImgIndex);

      if (!clicked) break;
      // page.waitForTimeout() was removed in recent Puppeteer versions
      // (confirmed live: "page.waitForTimeout is not a function" broke
      // every county's pagination in production). Plain setTimeout works
      // across all versions.
      await new Promise(resolve => setTimeout(resolve, 1300));

      const afterClickItems = await extractCurrentPageItems();
      const beforeClickSize = allItems.size;
      afterClickItems.forEach(it => allItems.set(it.itemId, it));
      if (allItems.size === beforeClickSize && allItems.size === before) {
        stagnantRounds++;
      } else {
        stagnantRounds = 0;
      }
    }
  }

  await paginateSection(0); // "Running Auctions" section (top Next Page button)
  await paginateSection(2); // "Closed or Canceled" section (top Next Page button)

  return Array.from(allItems.values());
}

// ---------------------------------------------------------------------------
// MAP SCRAPED FIELDS -> SUPABASE ROW
// ---------------------------------------------------------------------------

function toDbRow(item, county) {
  const addressRaw = item['Property Address'] || '';
  // addressRaw may look like "HOXIE DR, JACKSONVILLE, FL- 32257" or
  // "HOMESTEAD, FL- 33034" (single line). Just store it as one field —
  // splitting into street/city/zip reliably needs per-county rules.
  return {
    state: county.state,
    county: county.county,
    address: addressRaw,
    owner: null, // not present on the preview page; only on detail/bid pages
    opening_bid: parseMoney(item['Opening Bid']),
    assessed_value: parseMoney(item['Assessed Value']) ?? 0, // DB requires NOT NULL
    status: item.status || 'Unknown',
    is_active: /scheduled|active/i.test(item.status || ''),
    case_number: item['Case #'] || null,
    certificate_number: item['Certificate #'] || null,
    parcel_id: item['Parcel ID'] || null,
    parcel_link: item.parcelLink || null,
  };
}

// ---------------------------------------------------------------------------
// SUPABASE UPSERT (batched)
// ---------------------------------------------------------------------------

async function upsertToSupabase(rows) {
  if (rows.length === 0) return;
  const tableName = 'properties';
  const BATCH_SIZE = 200;

  for (let i = 0; i < rows.length; i += BATCH_SIZE) {
    const batch = rows.slice(i, i + BATCH_SIZE);
    const response = await fetch(`${supabaseUrl}/rest/v1/${tableName}?on_conflict=case_number`, {
      method: 'POST',
      headers: {
        'apikey': supabaseKey,
        'Authorization': `Bearer ${supabaseKey}`,
        'Content-Type': 'application/json',
        'Prefer': 'resolution=merge-duplicates,return=minimal',
      },
      body: JSON.stringify(batch),
    });

    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(`Supabase REST error (${response.status}) on batch starting at ${i}: ${errorText}`);
    }
    console.log(`Upserted rows ${i + 1}-${i + batch.length} of ${rows.length}`);
  }
}

// ---------------------------------------------------------------------------
// MAIN
// ---------------------------------------------------------------------------

async function runScraper() {
  console.log('Starting tax deed scraper...');

  if (!supabaseUrl || !supabaseKey) {
    throw new Error('Missing SUPABASE_URL or SUPABASE_SERVICE_KEY environment variables in GitHub Secrets.');
  }
  supabaseUrl = supabaseUrl.trim();
  if (!supabaseUrl.startsWith('http')) supabaseUrl = `https://${supabaseUrl}`;
  if (supabaseUrl.endsWith('/')) supabaseUrl = supabaseUrl.slice(0, -1);

  let browser;
  try {
    browser = await puppeteer.launch({
      headless: true,
      executablePath: process.env.PUPPETEER_EXECUTABLE_PATH || '/usr/bin/google-chrome-stable',
      args: ['--no-sandbox', '--disable-setuid-sandbox'],
    });
    console.log('Puppeteer launched successfully.');

    const page = await browser.newPage();
    page.setDefaultNavigationTimeout(60000);

    // IMPORTANT: after fixing the div.CALBOX extraction bug (verified
    // correct live in a real browser — found exactly ["6","20"] for
    // Miami-Dade's August calendar), a real CI run STILL found 0 dates for
    // every county. The extraction logic itself is right; something about
    // Puppeteer's default headless environment gets different content than
    // a normal browser does. The two standard causes for this class of bug:
    // (1) Puppeteer's default UA includes "HeadlessChrome", which some
    //     legacy/WAF-protected sites detect and serve reduced content to;
    // (2) Puppeteer's default viewport (800x600) may trigger a different
    //     mobile-oriented layout than the desktop one we verified against.
    // This has NOT yet been confirmed live against this specific site in a
    // real headless run — if dates are still 0 after this, the cause is
    // something else and needs fresh investigation (e.g. capture a
    // screenshot or page.content() dump from inside the Action itself).
    await page.setUserAgent('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36');
    await page.setViewport({ width: 1440, height: 900 });

    const allRows = [];

    for (const county of COUNTIES) {
      try {
        console.log(`\n--- ${county.county}, ${county.state} (${county.subdomain}.realtaxdeed.com) ---`);
        const dates = await getAuctionDates(page, county.subdomain, HOW_MANY_MONTHS_AHEAD);
        console.log(`Found ${dates.length} tax deed auction date(s): ${dates.join(', ') || 'none'}`);

        for (const dateStr of dates) {
          console.log(`  Scraping auction ${dateStr}...`);
          const items = await scrapeAuctionDate(page, county.subdomain, dateStr);
          console.log(`  -> ${items.length} properties`);
          items.forEach(item => allRows.push(toDbRow(item, county)));
        }
      } catch (countyErr) {
        // One bad county should never kill the whole run.
        console.error(`Error scraping ${county.county}: ${countyErr.message}`);
      }
    }

    console.log(`\nTotal properties scraped: ${allRows.length}`);
    await upsertToSupabase(allRows);
    console.log('Successfully saved data to Supabase!');
  } catch (error) {
    console.error('Error running tax deed scraper:', error);
    process.exit(1);
  } finally {
    if (browser) await browser.close();
  }
}

runScraper();
