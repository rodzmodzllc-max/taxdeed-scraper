const puppeteer = require('puppeteer');

const supabaseUrl = process.env.SUPABASE_URL;
const supabaseKey = process.env.SUPABASE_SERVICE_KEY;

async function runScraper() {
  console.log('Starting tax deed scraper...');
  
  if (!supabaseUrl || !supabaseKey) {
    throw new Error('Missing SUPABASE_URL or SUPABASE_SERVICE_KEY environment variables in GitHub Secrets.');
  }

  let browser;
  try {
    browser = await puppeteer.launch({
      headless: true,
      executablePath: process.env.PUPPETEER_EXECUTABLE_PATH || '/usr/bin/google-chrome-stable',
      args: ['--no-sandbox', '--disable-setuid-sandbox']
    });
    
    const page = await browser.newPage();
    console.log('Puppeteer launched successfully with system Chrome.');

    // Replace 'tax_deeds' with your actual Supabase table name
    const tableName = 'tax_deeds';

    const scrapedData = {
      property_id: '12345',
      status: 'active'
    };

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