import ws from 'ws';

// Force global WebSocket support for Node < 22
if (!globalThis.WebSocket) {
  globalThis.WebSocket = ws;
}

import { createClient } from '@supabase/supabase-js';

const supabaseUrl = process.env.SUPABASE_URL;
const supabaseKey = process.env.SUPABASE_SERVICE_KEY;

const supabase = createClient(supabaseUrl, supabaseKey, {
  auth: {
    persistSession: false,
    autoRefreshToken: false
  }
});

async function runScraper() {
  console.log('Starting tax deed scraper...');
  
  try {
    // Your scraper and database logic here
    console.log('Scraper finished successfully.');
  } catch (error) {
    console.error('Error running tax deed scraper:', error);
    process.exit(1);
  }
}

runScraper();