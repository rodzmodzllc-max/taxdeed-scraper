import { createClient } from '@supabase/supabase-js';
import ws from 'ws';

const supabaseUrl = process.env.SUPABASE_URL;
const supabaseKey = process.env.SUPABASE_SERVICE_KEY;

const supabase = createClient(supabaseUrl, supabaseKey, {
  auth: {
    persistSession: false,
    autoRefreshToken: false
  },
  realtime: {
    transport: ws,
  },
});

async function runScraper() {
  console.log('Starting tax deed scraper...');
  
  try {
    // Add your scraping and database insert logic here
    
    console.log('Scraper finished successfully.');
  } catch (error) {
    console.error('Error running tax deed scraper:', error);
    process.exit(1);
  }
}

runScraper();