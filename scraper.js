const puppeteer = require('puppeteer');

const supabaseUrl = process.env.SUPABASE_URL;
const supabaseKey = process.env.SUPABASE_SERVICE_KEY;

async function runScraper() {
  console.log('Starting tax deed scraper...');
  
  let browser;
  try {
    // Launch Puppeteer for GitHub Actions compatibility
    browser = await puppeteer.launch({
      headless: true,
      args: ['--no-sandbox', '--disable-setuid-sandbox']
    });
    
    const page = await browser.newPage();
    
    // Add your scraping navigation and data extraction logic here
    console.log('Puppeteer browser launched successfully.');

    // Example scraped payload to insert into Supabase via REST API
    const payload = {
      property_id: '12345',
      status: 'active'
    };

    // Send data to Supabase using native fetch (No SDK or WebSockets required)
    const response = await fetch(`${supabaseUrl}/rest/v1/tax_deeds`, {
      method: 'POST',
      headers: {
        'apikey': supabaseKey,
        'Authorization': `Bearer ${supabaseKey}`,
        'Content-Type': 'application/json',
        'Prefer': 'return=representation'
      },
      body: JSON.stringify(payload)
    });

    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(`Supabase REST error: ${response.status} - ${errorText}`);
    }

    const data = await response.json();
    console.log('Successfully saved data to Supabase:', data);
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