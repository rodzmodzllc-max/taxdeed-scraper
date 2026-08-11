import 'dotenv/config';
import { createClient } from '@supabase/supabase-js';
import puppeteer from 'puppeteer-extra';
import StealthPlugin from 'puppeteer-extra-plugin-stealth';

puppeteer.use(StealthPlugin());

const { SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY } = process.env;

if (!SUPABASE_URL || !SUPABASE_SERVICE_ROLE_KEY) {
  console.error("❌ ERROR: SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY is missing in your .env file!");
  process.exit(1);
}

const supabase = createClient(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY);

// Updated RealAuction URLs for Florida Counties
const FLORIDA_COUNTIES = [
  { name: 'Miami-Dade', state: 'FL', baseUrl: 'https://miamidade.realforeclose.com' },
  { name: 'Orange', state: 'FL', baseUrl: 'https://orange.realforeclose.com' },
  { name: 'Broward', state: 'FL', baseUrl: 'https://broward.deedauction.net' },
  { name: 'Hillsborough', state: 'FL', baseUrl: 'https://hillsborough.realtaxdeed.com' },
  { name: 'Palm Beach', state: 'FL', baseUrl: 'https://palmbeach.realtaxdeed.com' },
  { name: 'Pinellas', state: 'FL', baseUrl: 'https://pinellas.realforeclose.com' },
  { name: 'Lee', state: 'FL', baseUrl: 'https://lee.realforeclose.com' },
  { name: 'Polk', state: 'FL', baseUrl: 'https://polk.realforeclose.com' },
  { name: 'Brevard', state: 'FL', baseUrl: 'https://brevard.realforeclose.com' },
  { name: 'Volusia', state: 'FL', baseUrl: 'https://volusia.realforeclose.com' },
  { name: 'Pasco', state: 'FL', baseUrl: 'https://pasco.realforeclose.com' },
  { name: 'Sarasota', state: 'FL', baseUrl: 'https://sarasota.realforeclose.com' },
  { name: 'Manatee', state: 'FL', baseUrl: 'https://manatee.realforeclose.com' },
  { name: 'Osceola', state: 'FL', baseUrl: 'https://osceola.realforeclose.com' },
  { name: 'Escambia', state: 'FL', baseUrl: 'https://escambia.realforeclose.com' },
  { name: 'Marion', state: 'FL', baseUrl: 'https://marion.realforeclose.com' },
  { name: 'St. Lucie', state: 'FL', baseUrl: 'https://stlucie.realforeclose.com' },
  { name: 'Collier', state: 'FL', baseUrl: 'https://collier.realforeclose.com' }
];

function parseCurrency(val) {
  if (!val) return 0;
  const cleaned = val.replace(/[^0-9.]/g, '');
  return parseFloat(cleaned) || 0;
}

async function startScraper() {
  console.log("🚀 Starting Florida Tax Deed Scraper...");

  const browser = await puppeteer.launch({
    headless: "new",
    args: [
      '--no-sandbox',
      '--disable-setuid-sandbox',
      '--disable-dev-shm-usage',
      '--window-size=1280,800'
    ]
  });

  let totalProcessed = 0;

  for (const county of FLORIDA_COUNTIES) {
    console.log(`\n🔍 Scraping ${county.name} County (${county.baseUrl})...`);
    
    const targetUrl = `${county.baseUrl}/index.cfm?zaction=AUCTION&zmethod=PREVIEW`;
    
    let page;
    try {
      page = await browser.newPage();
      await page.setViewport({ width: 1280, height: 800 });
      
      await page.goto(targetUrl, { waitUntil: 'networkidle2', timeout: 45000 });
      await new Promise(res => setTimeout(res, 2000));

      const scrapedData = await page.evaluate((countyName, stateCode, baseUrl) => {
        const items = [];
        const auctionCards = document.querySelectorAll('.area_auction, div[id^="area_auction"], .AUCTION_ITEM');

        auctionCards.forEach(card => {
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
          const realauctionUrl = linkEl ? linkEl.href : baseUrl;

          if (certNum || parcelId) {
            items.push({
              county: countyName,
              state: stateCode,
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
      }, county.name, county.state, county.baseUrl);

      console.log(`  └─ Found ${scrapedData.length} raw records in ${county.name} County.`);

      if (scrapedData.length > 0) {
        // 1. Format records
        const formattedRecords = scrapedData.map(item => ({
          county: item.county,
          certificate_number: item.certificate_number,
          parcel_id: item.parcel_id,
          auction_date: item.auction_date || new Date().toISOString().split('T')[0],
          opening_bid: parseCurrency(item.opening_bid),
          current_bid: parseCurrency(item.current_bid),
          status: item.status,
          property_address: item.property_address,
          realauction_url: item.realauction_url,
          updated_at: new Date().toISOString()
        }));

        // 2. DEDUPLICATE records in memory to avoid "ON CONFLICT DO UPDATE" errors
        const uniqueRecordsMap = new Map();
        formattedRecords.forEach(rec => {
          const key = `${rec.county}::${rec.certificate_number}`;
          uniqueRecordsMap.set(key, rec); // retains latest duplicate
        });
        const deduplicatedRecords = Array.from(uniqueRecordsMap.values());

        // 3. Upsert deduplicated batch into Supabase
        const { error } = await supabase
          .from('tax_deeds')
          .upsert(deduplicatedRecords, { onConflict: 'county,certificate_number' });

        if (error) {
          console.error(`  ❌ Supabase Upsert Error [${county.name}]:`, error.message);
        } else {
          console.log(`  ✅ Successfully upserted ${deduplicatedRecords.length} unique records into database.`);
          totalProcessed += deduplicatedRecords.length;
        }
      }

    } catch (err) {
      console.error(`  ⚠️ Skipped ${county.name} County due to error:`, err.message);
    } finally {
      if (page) await page.close();
    }
  }

  await browser.close();
  console.log(`\n🎉 Scraper finished! Total records processed/updated: ${totalProcessed}`);
}

startScraper().catch(err => {
  console.error("Fatal Scraper Crash:", err);
  process.exit(1);
});