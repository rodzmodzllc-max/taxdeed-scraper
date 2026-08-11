const puppeteer = require('puppeteer');

let supabaseUrl = process.env.SUPABASE_URL;
const supabaseKey = process.env.SUPABASE_SERVICE_KEY;

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
      args: ['--no-sandbox', '--disable-setuid-sandbox']
    });
    
    const page = await browser.newPage();
    console.log('Puppeteer launched successfully.');

    const tableName = 'properties';
    const scrapedData = {
      state: 'FL',
      county: 'Miami-Dade',
      address: '123 Test Street, Miami, FL',
      owner: 'John Doe'
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

    console.log('Successfully saved data to Supabase!');
  } catch (error) {
    console.error('Error running tax deed scraper:', error);
    process.exit(1);
  } finally {
    if (browser) await browser.close();
  }
}

runScraper();