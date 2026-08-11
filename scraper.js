import { createClient } from '@supabase/supabase-js';

const supabaseUrl = process.env.SUPABASE_URL;
const supabaseKey = process.env.SUPABASE_SERVICE_KEY;

const supabase = createClient(supabaseUrl, supabaseKey);

async function runScraper() {
  console.log('Starting tax deed scraper...');
  
  try {
    // Add your scraper logic here
    console.log('Scraper finished successfully.');
  } catch (error) {
    console.error('Error running tax deed scraper:', error);
    process.exit(1);
  }
}

runScraper();