const supabaseUrl = process.env.SUPABASE_URL;
const supabaseKey = process.env.SUPABASE_SERVICE_KEY;

async function runScraper() {
  console.log('Starting tax deed scraper...');
  
  try {
    // Example of inserting data into a table named 'tax_deeds' using standard fetch
    const response = await fetch(`${supabaseUrl}/rest/v1/tax_deeds`, {
      method: 'POST',
      headers: {
        'apikey': supabaseKey,
        'Authorization': `Bearer ${supabaseKey}`,
        'Content-Type': 'application/json',
        'Prefer': 'return=representation'
      },
      body: JSON.stringify({
        // Add your scraped data fields here
        property_id: '12345',
        status: 'active'
      })
    });

    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(`Supabase error: ${response.status} - ${errorText}`);
    }

    const data = await response.json();
    console.log('Successfully inserted data:', data);
    console.log('Scraper finished successfully.');
  } catch (error) {
    console.error('Error running tax deed scraper:', error);
    process.exit(1);
  }
}

runScraper();