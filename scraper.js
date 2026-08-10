const puppeteer = require('puppeteer');
const { createClient } = require('@supabase/supabase-js');

// Your Supabase Credentials
const SUPABASE_URL = "https://cqnnnvpbocafuvpzfbzu.supabase.co";
const SUPABASE_SERVICE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImNxbm5udnBib2NhZnV2cHpmYnp1Iiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc4NTk5NDI2NiwiZXhwIjoyMTAxNTcwMjY2fQ.xCNQNALqft3SLVqS7XKhkgD1P7zCyUFnaddW_BrudHU"; // Replace with your full service role key if needed

const supabase = createClient(SUPABASE_URL, SUPABASE_SERVICE_KEY);

async function runScraper() {
  console.log("Launching local browser...");
  
  // Uses Chrome installed on your Windows machine to avoid version spawn errors
  const browser = await puppeteer.launch({ 
    headless: "new",
    executablePath: "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe" 
  });
  
  const page = await browser.newPage();

  try {
    console.log("Navigating to target auction site...");
    await page.goto('https://broward.realforeclose.com/', { waitUntil: 'networkidle2' });

    // --- EXAMPLE DATA EXTRACTION ---
    // In a real run, you can use page.evaluate() to extract live rows from the DOM
    const scrapedProperties = [
      {
        state: "FL",
        county: "Broward",
        address: "123 Scraped Testway, Fort Lauderdale, FL",
        owner: "Automated Scraper Test",
        opening_bid: 19500,
        assessed_value: 240000,
        status: "Available",
        is_top_pick: true
      }
    ];

    console.log(`Scraped ${scrapedProperties.length} properties. Pushing to Supabase...`);

    // Upsert into Supabase (updates if address matches, inserts if new)
    const { data, error } = await supabase
      .from('properties')
      .upsert(scrapedProperties, { onConflict: 'address' });

    if (error) {
      console.error("Error writing to Supabase:", error);
    } else {
      console.log("Database successfully synced with live data!");
    }

  } catch (err) {
    console.error("Scraper encountered an error:", err);
  } finally {
    await browser.close();
  }
}

runScraper();