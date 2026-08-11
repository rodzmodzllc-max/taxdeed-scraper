const { createClient } = require('@supabase/supabase-js');
const WebSocket = require('ws');
const puppeteer = require('puppeteer');

const supabaseUrl = process.env.SUPABASE_URL;
const supabaseKey = process.env.SUPABASE_SERVICE_KEY;

// Explicitly provide the ws transport to satisfy Supabase requirements
const supabase = createClient(supabaseUrl, supabaseKey, {
  auth: {
    persistSession: false,
    autoRefreshToken: false
  },
  realtime: {
    transport: WebSocket,
  }
});

async function runScraper() {
  console.log('Starting tax deed scraper...');
  
  let browser;
  try {
    browser = await puppeteer.launch({
      headless: true,
      args: ['--no-sandbox', '--disable-setuid-sandbox']
    });
    
    const page = await browser.newPage();
    console.log('Puppeteer launched successfully.');

    // Test database query using the Supabase client
    const { data, error } = await supabase.from('your_table_name').select('*').limit(1);
    
    if (error) {
      console.warn('Note: Table check warning (you can ignore if table does not exist yet):', error.message);
    } else {
      console.log('Supabase connected successfully:', data);
    }

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