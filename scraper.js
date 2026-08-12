import 'dotenv/config';
import { createClient } from '@supabase/supabase-js';
import puppeteer from 'puppeteer-extra';
import StealthPlugin from 'puppeteer-extra-plugin-stealth';

puppeteer.use(StealthPlugin());

const { SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, SUPABASE_SERVICE_KEY } = process.env;
const serviceKey = SUPABASE_SERVICE_ROLE_KEY || SUPABASE_SERVICE_KEY;

if (!SUPABASE_URL || !serviceKey) {
  console.error("❌ ERROR: SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY is missing!");
  process.exit(1);
}

const supabase = createClient(SUPABASE_URL, serviceKey);

// ALL 67 FLORIDA COUNTIES
const ALL_FLORIDA_COUNTIES = [
  { name: 'Alachua', slug: 'alachua' },
  { name: 'Baker', slug: 'baker' },
  { name: 'Bay', slug: 'bay' },
  { name: 'Bradford', slug: 'bradford' },
  { name: 'Brevard', slug: 'brevard' },
  { name: 'Broward', slug: 'broward', customUrl: 'https://broward.deedauction.net' },
  { name: 'Calhoun', slug: 'calhoun' },
  { name: 'Charlotte', slug: 'charlotte' },
  { name: 'Citrus', slug: 'citrus' },
  { name: 'Clay', slug: 'clay' },
  { name: 'Collier', slug: 'collier' },
  { name: 'Columbia', slug: 'columbia' },
  { name: 'DeSoto', slug: 'desoto' },
  { name: 'Dixie', slug: 'dixie' },
  { name: 'Duval', slug: 'duval' },
  { name: 'Escambia', slug: 'escambia' },
  { name: 'Flagler', slug: 'flagler' },
  { name: 'Franklin', slug: 'franklin' },
  { name: 'Gadsden', slug: 'gadsden' },
  { name: 'Gilchrist', slug: 'gilchrist' },
  { name: 'Glades', slug: 'glades' },
  { name: 'Gulf', slug: 'gulf' },
  { name: 'Hamilton', slug: 'hamilton' },
  { name: 'Hardee', slug: 'hardee' },
  { name: 'Hendry', slug: 'hendry' },
  { name: 'Hernando', slug: 'hernando' },
  { name: 'Highlands', slug: 'highlands' },
  { name: 'Hillsborough', slug: 'hillsborough' },
  { name: 'Holmes', slug: 'holmes' },
  { name: 'Indian River', slug: 'indianriver' },
  { name: 'Jackson', slug: 'jackson' },
  { name: 'Jefferson', slug: 'jefferson' },
  { name: 'Lafayette', slug: 'lafayette' },
  { name: 'Lake', slug: 'lake' },
  { name: 'Lee', slug: 'lee' },
  { name: 'Leon', slug: 'leon' },
  { name: 'Levy', slug: 'levy' },
  { name: 'Liberty', slug: 'liberty' },
  { name: 'Madison', slug: 'madison' },
  { name: 'Manatee', slug: 'manatee' },
  { name: 'Marion', slug: 'marion' },
  { name: 'Martin', slug: 'martin' },
  { name: 'Miami-Dade', slug: 'miamidade' },
  { name: 'Monroe', slug: 'monroe' },
  { name: 'Nassau', slug: 'nassau' },
  { name: 'Okaloosa', slug: 'okaloosa' },
  { name: 'Okeechobee', slug: 'okeechobee' },
  { name: 'Orange', slug: 'orange' },
  { name: 'Osceola', slug: 'osceola' },
  { name: 'Palm Beach', slug: 'palmbeach' },
  { name: 'Pasco', slug: 'pasco' },
  { name: 'Pinellas', slug: 'pinellas' },
  { name: 'Polk', slug: 'polk' },
  { name: 'Putnam', slug: 'putnam' },
  { name: 'Santa Rosa', slug: 'santarosa' },
  { name: 'Sarasota', slug: 'sarasota' },
  { name: 'Seminole', slug: 'seminole' },
  { name: 'St. Johns', slug: 'stjohns' },
  { name: 'St. Lucie', slug: 'stlucie' },
  { name: 'Sumter', slug: 'sumter' },
  { name: 'Suwannee', slug: 'suwannee' },
  { name: 'Taylor', slug: 'taylor' },
  { name: 'Union', slug: 'union' },
  { name: 'Volusia', slug: 'volusia' },
  { name: 'Wakulla', slug: 'wakulla' },
  { name: 'Walton', slug: 'walton' },
  { name: 'Washington', slug: 'washington' }
];

function parseCurrency(val) {
  if (!val) return 0;
  const cleaned = val.replace(/[^0-9.]/g, '');
  return parseFloat(cleaned) || 0;
}

// Scrape an individual county tab
async function scrapeCounty(browser, county) {
  const page = await browser.newPage();
  await page.setViewport({ width: 1280, height: 800 });

  // Domain fallback strategy
  const urlsToTry = county.customUrl 
    ? [county.customUrl]
    : [
        `https://${county.slug}.realtaxdeed.com`,
        `https://${county.slug}.realforeclose.com`
      ];

  let scrapedRecords = [];
  let successfulBaseUrl = '';

  for (const baseUrl of urlsToTry) {
    const targetUrl = `${baseUrl}/index.cfm?zaction=AUCTION&zmethod=PREVIEW`;
    try {
      const response = await page.goto(targetUrl, { waitUntil: 'networkidle2', timeout: 25000 });
      if (response && response.status() === 200) {
        successfulBaseUrl = baseUrl;
        await new Promise(res => setTimeout(res, 1500));

        scrapedRecords = await page.evaluate((countyName, bUrl) => {
          const items = [];
          const cards = document.querySelectorAll('.area_auction, div[id^="area_auction"], .AUCTION_ITEM');

          cards.forEach(card => {
            const text = card.innerText || '';

            const parcelMatch = text.match(/(?:Parcel|Parcel ID|STRAP|Pin|Tax ID)[\s#:]*([A-Z0-9-]{6,30})/i);
            const parcelId = parcelMatch ? parcelMatch[1].trim() : null;

            const certMatch = text.match(/(?:Tax Deed|Certificate|Case|Item)[\s#:]*([A-Z0-9-]{4,25})/i);
            const certNum = certMatch ? certMatch[1].trim() : (parcelId ? `CERT-${parcelId}` : null);

            const bidMatch = text.match(/(?:Opening Bid|Min Bid|Starting Bid)[\s:$]*([0-9,]+\.[0-9]{2})/i);
            const openingBid = bidMatch ? bidMatch[1] : '0';

            const addrMatch = text.match(/(?:Property Address|Location|Address)[\s:]*([^\n\r]+)/i);
            let propertyAddress = addrMatch ? addrMatch[1].trim() : '';
            if (!propertyAddress || propertyAddress.length < 5) {
              propertyAddress = `${countyName} County, FL`;
            }

            const dateMatch = text.match(/(?:Auction Date|Sale Date|Date)[\s:]*([0-9]{1,2}\/[0-9]{1,2}\/[0-9]{4})/i);
            let auctionDate = null;
            if (dateMatch) {
              const parts = dateMatch[1].split('/');
              if (parts.length === 3) {
                auctionDate = `${parts[2]}-${parts[0].padStart(2, '0')}-${parts[1].padStart(2, '0')}`;
              }
            }

            const linkEl = card.querySelector('a[href*="zaction=AUCTION"]');
            const realauctionUrl = linkEl ? linkEl.href : bUrl;

            if (certNum || parcelId) {
              items.push({
                county: countyName,
                state: 'FL',
                certificate_number: certNum || `PARCEL-${parcelId}`,
                parcel_id: parcelId,
                auction_date: auctionDate,
                opening_bid: openingBid,
                current_bid: openingBid,
                status: 'active',
                property_address: propertyAddress,
                realauction_url: realauctionUrl
              });
            }
          });

          return items;
        }, county.name, baseUrl);

        if (scrapedRecords.length > 0 || cardsExistOnPage(page)) {
          break; // Stop domain fallback if records were found
        }
      }
    } catch (e) {
      // Continue to fallback domain if first attempt fails
    }
  }

  await page.close();
  return { countyName: county.name, records: scrapedRecords };
}

async function cardsExistOnPage(page) {
  try {
    return await page.evaluate(() => document.querySelectorAll('.area_auction, div[id^="area_auction"]').length > 0);
  } catch {
    return false;
  }
}

// Run Main Batch Scraper
async function startFullStateScraper() {
  console.log("🚀 Launching Full 67-County Florida Tax Deed Scraper...");
  const startTime = Date.now();

  const browser = await puppeteer.launch({
    headless: "new",
    args: [
      '--no-sandbox',
      '--disable-setuid-sandbox',
      '--disable-dev-shm-usage',
      '--window-size=1280,800'
    ]
  });

  let totalUpserted = 0;
  const CONCURRENCY_LIMIT = 3; // 3 worker tabs running in parallel

  for (let i = 0; i < ALL_FLORIDA_COUNTIES.length; i += CONCURRENCY_LIMIT) {
    const chunk = ALL_FLORIDA_COUNTIES.slice(i, i + CONCURRENCY_LIMIT);
    console.log(`\n📦 Processing Batch ${Math.floor(i / CONCURRENCY_LIMIT) + 1}/${Math.ceil(ALL_FLORIDA_COUNTIES.length / CONCURRENCY_LIMIT)}: [${chunk.map(c => c.name).join(', ')}]`);

    const results = await Promise.all(chunk.map(c => scrapeCounty(browser, c)));

    for (const res of results) {
      if (res.records.length > 0) {
        const formatted = res.records.map(rec => ({
          county: rec.county,
          certificate_number: rec.certificate_number,
          parcel_id: rec.parcel_id,
          auction_date: rec.auction_date || new Date().toISOString().split('T')[0],
          opening_bid: parseCurrency(rec.opening_bid),
          current_bid: parseCurrency(rec.current_bid),
          status: rec.status,
          property_address: rec.property_address,
          realauction_url: rec.realauction_url,
          updated_at: new Date().toISOString()
        }));

        // Deduplicate in memory
        const dedupedMap = new Map();
        formatted.forEach(r => dedupedMap.set(`${r.county}::${r.certificate_number}`, r));
        const dedupedList = Array.from(dedupedMap.values());

        const { error } = await supabase
          .from('tax_deeds')
          .upsert(dedupedList, { onConflict: 'county,certificate_number' });

        if (error) {
          console.error(`  ❌ Supabase Upsert Error [${res.countyName}]:`, error.message);
        } else {
          console.log(`  ✅ ${res.countyName} County: Upserted ${dedupedList.length} unique records.`);
          totalUpserted += dedupedList.length;
        }
      } else {
        console.log(`  ℹ️ ${res.countyName} County: 0 active listings found.`);
      }
    }
  }

  await browser.close();
  const elapsed = ((Date.now() - startTime) / 1000).toFixed(1);
  console.log(`\n🎉 Full 67-County Sweep Completed in ${elapsed}s! Total records updated: ${totalUpserted}`);
}

startFullStateScraper().catch(err => {
  console.error("Fatal Statewide Scraper Crash:", err);
  process.exit(1);
});