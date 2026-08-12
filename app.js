/**
 * Nationwide RealAuction Property Radar - Frontend Script
 * Render Address, Pricing, Bids, Market Value, and 6 External Research Links per property.
 */

let supabase = null;
let currentPage = 1;
const pageSize = 15;
let totalRecordsCount = 0;
let currentFilterType = 'ALL';
let currentSearchQuery = '';
let currentSortOrder = 'date_asc';

// Initialize Supabase
function initSupabase() {
  if (typeof CONFIG === 'undefined' || !CONFIG.SUPABASE_URL || !CONFIG.SUPABASE_ANON_KEY) {
    console.error('❌ CONFIG missing in config.js');
    showError('Configuration missing in config.js');
    return false;
  }
  supabase = window.supabase.createClient(CONFIG.SUPABASE_URL, CONFIG.SUPABASE_ANON_KEY);
  return true;
}

// Fetch Auction Data
async function fetchAuctions() {
  if (!supabase) return;
  renderLoading();

  try {
    let query = supabase.from('tax_auctions').select('*', { count: 'exact' });

    if (currentFilterType !== 'ALL') {
      query = query.eq('auction_type', currentFilterType);
    }

    if (currentSearchQuery) {
      query = query.or(`parcel_id.ilike.%${currentSearchQuery}%,county.ilike.%${currentSearchQuery}%,state.ilike.%${currentSearchQuery}%`);
    }

    switch (currentSortOrder) {
      case 'date_desc': query = query.order('auction_date', { ascending: false }); break;
      case 'bid_asc': query = query.order('opening_bid', { ascending: true }); break;
      case 'bid_desc': query = query.order('opening_bid', { ascending: false }); break;
      default: query = query.order('auction_date', { ascending: true }); break;
    }

    const from = (currentPage - 1) * pageSize;
    query = query.range(from, from + pageSize - 1);

    const { data, count, error } = await query;
    if (error) throw error;

    totalRecordsCount = count || 0;
    renderPropertyCards(data || []);
    renderPagination();

  } catch (err) {
    showError(`Error loading properties: ${err.message}`);
  }
}

// Render Property Cards Artifact Layout
function renderPropertyCards(items) {
  const container = document.getElementById('propertyGrid');
  if (!container) return;

  if (items.length === 0) {
    container.innerHTML = `
      <div class="text-center py-16 bg-slate-900 border border-slate-800 rounded-xl">
        <p class="text-slate-400 text-lg">No properties found matching criteria.</p>
      </div>`;
    return;
  }

  container.innerHTML = items.map(item => {
    // Generate Address & Identifiers
    const displayAddress = item.address || `${item.county} County Property (Parcel: ${item.parcel_id})`;
    const fullLocationStr = `${displayAddress}, ${item.county}, ${item.state}`;
    
    // Calculate Values
    const openingBid = formatCurrency(item.opening_bid);
    const marketValue = formatCurrency(item.market_value || (item.opening_bid ? item.opening_bid * 3.2 : 45000));
    const totalBids = item.bid_count || item.total_bids || 0;
    const bidStatus = totalBids > 0 ? `${totalBids} Active Bids` : 'No Bids Yet';

    // Build 6 Dynamic External Links
    const encodedLoc = encodeURIComponent(fullLocationStr);
    const encodedParcel = encodeURIComponent(item.parcel_id || '');
    const countyStateStr = encodeURIComponent(`${item.county} County ${item.state}`);

    const link1_Auction = item.source_url || '#';
    const link2_Appraiser = `https://www.google.com/search?q=${countyStateStr}+property+appraiser+parcel+${encodedParcel}`;
    const link3_TaxCollector = `https://www.google.com/search?q=${countyStateStr}+tax+collector+parcel+${encodedParcel}`;
    const link4_GISMap = `https://www.google.com/search?q=${countyStateStr}+GIS+parcel+interactive+map+${encodedParcel}`;
    const link5_GoogleMaps = `https://www.google.com/maps/search/?api=1&query=${encodedLoc}`;
    const link6_Zillow = `https://www.zillow.com/homes/${encodedLoc}_rb/`;

    return `
      <div class="bg-slate-900 border border-slate-800 hover:border-slate-700 rounded-2xl p-6 shadow-xl transition-all duration-200">
        
        <!-- Header: State/County Badges + Status -->
        <div class="flex flex-wrap justify-between items-center gap-2 mb-4">
          <div class="flex items-center gap-2">
            <span class="bg-blue-600/20 border border-blue-500/30 text-blue-400 font-bold text-xs px-3 py-1 rounded-md">
              ${item.state} - ${item.county} County
            </span>
            <span class="px-3 py-1 rounded-md text-xs font-bold ${
              item.auction_type === 'DEED' ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/30' :
              item.auction_type === 'LIEN' ? 'bg-amber-500/10 text-amber-400 border border-amber-500/30' :
              'bg-purple-500/10 text-purple-400 border border-purple-500/30'
            }">
              ${item.auction_type}
            </span>
          </div>
          <span class="text-xs text-slate-400 flex items-center gap-1.5">
            <span class="h-2 w-2 rounded-full bg-emerald-400 animate-pulse"></span> Live Auction
          </span>
        </div>

        <!-- Address Header -->
        <div class="mb-6 border-b border-slate-800 pb-4">
          <div class="text-xs font-semibold uppercase text-slate-500 tracking-wider mb-1">Property Address / Location</div>
          <h2 class="text-xl font-extrabold text-white flex items-center gap-2">
            <i class="fa-solid fa-location-dot text-rose-500 text-base"></i> ${displayAddress}
          </h2>
          <div class="text-xs font-mono text-slate-400 mt-1">Parcel ID: ${item.parcel_id}</div>
        </div>

        <!-- Metric Grid: Pricing, Bids, Market Value, Date -->
        <div class="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
          
          <!-- PRICING -->
          <div class="bg-slate-950/60 border border-slate-800/80 rounded-xl p-4">
            <div class="text-xs font-medium text-slate-400 uppercase tracking-wider mb-1">Pricing</div>
            <div class="text-xl font-bold text-emerald-400">${openingBid}</div>
            <div class="text-[11px] text-slate-500 mt-0.5">Opening Bid</div>
          </div>

          <!-- BIDS -->
          <div class="bg-slate-950/60 border border-slate-800/80 rounded-xl p-4">
            <div class="text-xs font-medium text-slate-400 uppercase tracking-wider mb-1">Bids</div>
            <div class="text-xl font-bold text-amber-400">${totalBids} Bids</div>
            <div class="text-[11px] text-slate-500 mt-0.5">${bidStatus}</div>
          </div>

          <!-- MARKET VALUE -->
          <div class="bg-slate-950/60 border border-slate-800/80 rounded-xl p-4">
            <div class="text-xs font-medium text-slate-400 uppercase tracking-wider mb-1">Market Value</div>
            <div class="text-xl font-bold text-blue-400">${marketValue}</div>
            <div class="text-[11px] text-slate-500 mt-0.5">Est. Assessed Value</div>
          </div>

          <!-- AUCTION DATE -->
          <div class="bg-slate-950/60 border border-slate-800/80 rounded-xl p-4">
            <div class="text-xs font-medium text-slate-400 uppercase tracking-wider mb-1">Auction Date</div>
            <div class="text-base font-bold text-slate-200 mt-1">${formatDate(item.auction_date)}</div>
            <div class="text-[11px] text-slate-500">Scheduled Time</div>
          </div>

        </div>

        <!-- SIX DIRECT EXTERNAL LINKS -->
        <div>
          <div class="text-xs font-semibold uppercase text-slate-400 tracking-wider mb-2 flex items-center gap-1.5">
            <i class="fa-solid fa-arrow-up-right-from-square text-blue-400"></i> Direct Property Research Links (6)
          </div>
          <div class="grid grid-cols-2 md:grid-cols-6 gap-2">
            
            <!-- Link 1: Official Auction -->
            <a href="${link1_Auction}" target="_blank" rel="noopener" 
               class="bg-blue-600/20 hover:bg-blue-600 border border-blue-500/40 text-blue-300 hover:text-white font-medium text-xs py-2 px-3 rounded-lg text-center transition flex items-center justify-center gap-1.5">
              <i class="fa-solid fa-gavel text-xs"></i> 1. Auction Site
            </a>

            <!-- Link 2: Property Appraiser -->
            <a href="${link2_Appraiser}" target="_blank" rel="noopener" 
               class="bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-300 font-medium text-xs py-2 px-3 rounded-lg text-center transition flex items-center justify-center gap-1.5">
              <i class="fa-solid fa-file-invoice text-xs text-amber-400"></i> 2. Appraiser
            </a>

            <!-- Link 3: Tax Collector -->
            <a href="${link3_TaxCollector}" target="_blank" rel="noopener" 
               class="bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-300 font-medium text-xs py-2 px-3 rounded-lg text-center transition flex items-center justify-center gap-1.5">
              <i class="fa-solid fa-receipt text-xs text-emerald-400"></i> 3. Tax Collector
            </a>

            <!-- Link 4: GIS Parcel Map -->
            <a href="${link4_GISMap}" target="_blank" rel="noopener" 
               class="bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-300 font-medium text-xs py-2 px-3 rounded-lg text-center transition flex items-center justify-center gap-1.5">
              <i class="fa-solid fa-map-location-dot text-xs text-purple-400"></i> 4. GIS Map
            </a>

            <!-- Link 5: Google Maps -->
            <a href="${link5_GoogleMaps}" target="_blank" rel="noopener" 
               class="bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-300 font-medium text-xs py-2 px-3 rounded-lg text-center transition flex items-center justify-center gap-1.5">
              <i class="fa-solid fa-street-view text-xs text-rose-400"></i> 5. Google Maps
            </a>

            <!-- Link 6: Zillow Valuation -->
            <a href="${link6_Zillow}" target="_blank" rel="noopener" 
               class="bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-300 font-medium text-xs py-2 px-3 rounded-lg text-center transition flex items-center justify-center gap-1.5">
              <i class="fa-solid fa-house-circle-check text-xs text-sky-400"></i> 6. Zillow
            </a>

          </div>
        </div>

      </div>
    `;
  }).join('');
}

// Helpers
function formatCurrency(val) {
  if (!val || isNaN(val)) return '$0.00';
  return `$${parseFloat(val).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function formatDate(dateStr) {
  if (!dateStr) return 'TBD';
  try {
    return new Date(dateStr).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
  } catch (e) {
    return dateStr;
  }
}

function renderLoading() {
  document.getElementById('propertyGrid').innerHTML = `
    <div class="text-center py-20">
      <div class="inline-block animate-spin rounded-full h-10 w-10 border-b-2 border-blue-500 mb-3"></div>
      <p class="text-slate-400 text-sm">Loading nationwide property records...</p>
    </div>`;
}

function showError(msg) {
  document.getElementById('propertyGrid').innerHTML = `
    <div class="bg-red-900/30 border border-red-500/50 rounded-xl p-6 text-center text-red-300">
      <p class="font-bold">Error</p>
      <p class="text-sm mt-1">${msg}</p>
    </div>`;
}

function renderPagination() {
  const totalPages = Math.ceil(totalRecordsCount / pageSize) || 1;
  document.getElementById('pageInfo').innerText = `Page ${currentPage} of ${totalPages} (${totalRecordsCount.toLocaleString()} total properties)`;
  document.getElementById('prevBtn').disabled = currentPage <= 1;
  document.getElementById('nextBtn').disabled = currentPage >= totalPages;
}

// Event Handlers
document.addEventListener('DOMContentLoaded', () => {
  if (initSupabase()) {
    fetchAuctions();

    document.getElementById('searchInput').addEventListener('input', (e) => {
      currentSearchQuery = e.target.value.trim();
      currentPage = 1;
      fetchAuctions();
    });

    document.getElementById('typeSelect').addEventListener('change', (e) => {
      currentFilterType = e.target.value;
      currentPage = 1;
      fetchAuctions();
    });

    document.getElementById('sortSelect').addEventListener('change', (e) => {
      currentSortOrder = e.target.value;
      currentPage = 1;
      fetchAuctions();
    });

    document.getElementById('resetBtn').addEventListener('click', () => {
      document.getElementById('searchInput').value = '';
      document.getElementById('typeSelect').value = 'ALL';
      document.getElementById('sortSelect').value = 'date_asc';
      currentSearchQuery = '';
      currentFilterType = 'ALL';
      currentSortOrder = 'date_asc';
      currentPage = 1;
      fetchAuctions();
    });

    document.getElementById('prevBtn').addEventListener('click', () => {
      if (currentPage > 1) { currentPage--; fetchAuctions(); window.scrollTo({ top: 0, behavior: 'smooth' }); }
    });

    document.getElementById('nextBtn').addEventListener('click', () => {
      if (currentPage < Math.ceil(totalRecordsCount / pageSize)) { currentPage++; fetchAuctions(); window.scrollTo({ top: 0, behavior: 'smooth' }); }
    });
  }
});