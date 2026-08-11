const supabaseUrl = process.env.SUPABASE_URL;
const supabaseKey = process.env.SUPABASE_SERVICE_KEY;

async function runScraper() {
  console.log('Starting tax deed scraper...');
  
  try {
    // Example: Inserting data into Supabase using Node's built-in fetch
    // Replace 'your_table_name' with your actual table name
    const response = await fetch(`${supabaseUrl}/rest/v1/your_table_name`, {
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
      throw new Error(`Supabase REST error (${response.status}): ${errorText}`);
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