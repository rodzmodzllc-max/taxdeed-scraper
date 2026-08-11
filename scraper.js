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

    const selCalDate = `{ts '${yyyy}-${mm}-01 00:00:00'}`;
    const calUrl = `https://${subdomain}.realtaxdeed.com/index.cfm?zaction=user&zmethod=calendar&selCalDate=${encodeURIComponent(selCalDate)}`;
    await page.goto(calUrl, { waitUntil: 'networkidle2', timeout: 60000 });

    const monthDates = await page.evaluate(() => {
      const found = [];
      document.querySelectorAll('td').forEach(td => {
        if (/Tax Deed/i.test(td.textContent) && /\d+\s*\/\s*\d+\s*TD/i.test(td.textContent)) {
          const dayMatch = td.querySelector(':scope > *:first-child')?.textContent?.trim()
            || td.textContent.trim().match(/^\d+/)?.[0];
          if (dayMatch) found.push(dayMatch.match(/\d+/)?.[0]);
        }
      });
      return found.filter(Boolean);
    });

    monthDates.forEach(day => {
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
          data[lastLabel] = (data[lastLabel] || '') + ', ' + val.textContent.trim();
        }
      });

      // Extra check for owner fields inside attributes or alternate labels
      const ownerEl = item.querySelector('.AD_DTA[data-lbl*="Owner"]');
      if (ownerEl) {
        data['Owner Name'] = ownerEl.textContent.trim();
      }

      const link = item.querySelector('a[href*="folio"], a[href*="parcel"], a');
      data.parcelLink = link ? link.getAttribute('href') : null;

      results.push(data);
    });
    return results;
  });

  async function paginateSection(nextImgIndex) {
    let stagnantRounds = 0;
    const MAX_ROUNDS = 40;

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
      await page.waitForTimeout(1300);

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

  await paginateSection(0); // "Running Auctions" section
  await paginateSection(2); // "Closed or Canceled" section

  return Array.from(allItems.values());
}

// ---------------------------------------------------------------------------
// MAP SCRAPED FIELDS -> SUPABASE ROW
// ---------------------------------------------------------------------------

function toDbRow(item, county) {
  const addressRaw = item['Property Address'] || '';
  const ownerRaw = item['Owner Name'] || item['Applicant'] || item['Owner'] || null;

  return {
    state: county.state,
    county: county.county,
    address: addressRaw,
    owner: ownerRaw?.trim() || 'Unknown', // Guaranteed non-null fallback
    opening_bid: parseMoney(item['Opening Bid']),
    assessed_value: parseMoney(item['Assessed Value']) ?? 0,
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
    const response = await fetch(`${supabaseUrl}/rest/v1/${tableName}?on_conflict=county,case_number`, {
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