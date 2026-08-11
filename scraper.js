const puppeteer = require('puppeteer');

// Load environment variables
let supabaseUrl = process.env.SUPABASE_URL;
const supabaseKey = process.env.SUPABASE_SERVICE_KEY;

async function runScraper() {
  console.log('Starting tax deed scraper...');
  
  if (!supabaseUrl || !supabaseKey) {
    throw new Error('Missing SUPABASE_URL or SUPABASE_SERVICE_KEY environment variables in GitHub Secrets.');
  }

  // --- AUTOMATIC URL SANITIZATION ---
  // 1. Remove hidden spaces/newlines
  supabaseUrl = supabaseUrl.trim();
  
  // 2. Force https:// if missing
  if (!supabaseUrl.startsWith('http')) {
    supabaseUrl = `https://${supabaseUrl}`;
  }
  
  // 3. Remove trailing slash to prevent double slashes in the path
  if (supabaseUrl.endsWith('/')) {
    supabaseUrl = supabaseUrl.slice(0, -1);
  }

  // 4. Validate the fixed URL so it doesn't crash blindly later
  try {
    new URL(supabaseUrl);
  } catch (err) {
    throw new Error(`CRITICAL: Even after auto-formatting, the Supabase URL is invalid. Check the GitHub Secret. Masked length: ${supabaseUrl.length}`);
  }
  // -----------------------------------

  let browser;
  try {
    browser = await puppeteer.launch({
      headless: true,
      executablePath: process.env.PUPPETEER_EXECUTABLE_PATH || '/usr/bin/google-chrome-stable',
      args: ['--no-sandbox', '--disable-setuid-sandbox']
    });
    
    const page = await browser.newPage();
    console.log('Puppeteer launched successfully with system Chrome.');

    const tableName = 'tax_deeds';

    const scrapedData = {
      property_id: '12345',
      status: 'active'
    };

    console.log(`Sending data to: ***/rest/v1/${tableName}`);

    const response = await fetch(`${supabaseUrl}/rest/v1/${tableName}`, {
      method: 'POST',
      headers: {
        'apikey': supabaseKey,
        'Authorization': `Bearer ${supabaseKey}`,
        'Content-Type': 'application/json',
        'Prefer': 'return=representation'
      },
      body: JSON.stringify(scrapedData)
    });

    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(`Supabase REST error (${response.status}): ${errorText}`);
    }

    const result = await response.json();
    console.log('Successfully saved data to Supabase:', result);
    console.log('Scraper finished successfully.');

  } catch (error) {
    console.error('Error running tax deed scraper:', error);
    process.exit(1);
  } finally {
    if (browser) {
      await browser.close();
    }
  }
}

runScraper();