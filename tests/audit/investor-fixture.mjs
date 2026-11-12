// Shared fixture for tests/audit/investor-ten.mjs (investor sprint, owner
// 2026-11-12): FL Available rows injected through the stub's
// window.__stubExtraRows, enough to fill a county grid. Every row is a
// labelled fixture: placeholder addresses, a fixture placard as the stored
// aerial, no real parcel.
export const COUNTIES = ['Alachua', 'Bay', 'Citrus', 'Marion', 'Orange'];
// Approximate county centres, only so a few rows carry coordinates.
const CENTRE = { Alachua: [29.67, -82.36], Bay: [30.23, -85.63], Citrus: [28.85, -82.47], Marion: [29.2, -82.06], Orange: [28.5, -81.3] };
const PLACARD = "data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='640' height='400'><rect width='100%' height='100%' fill='%2364748b'/><text x='50%' y='50%' dominant-baseline='middle' text-anchor='middle' font-family='sans-serif' font-size='26' fill='%23ffffff'>FIXTURE STORED AERIAL</text></svg>";
export const LEGAL = 'BEG 418 FT S AND 110 FT W OF INTER OF E AND W HALF SEC 12 TWP 2 S RNG 14 W';
export function investorRows() {
  const now = new Date().toISOString();
  const out = [];
  COUNTIES.forEach((county, c) => {
    for (let i = 0; i < 6; i++) {
      const id = `inv${c}-${i}`;
      const row = { id, source: 'laft', state: 'FL', county, case_no: `INV-${c}-${i}`, parcel: `${17920 + c * 10 + i}-000-000`,
        address: `${100 + i * 11} Fixture ${county} Rd`, bid: 1200 + i * 375, assessed: 30000 + i * 1000, market: 32000 + i * 2100, value_year: 2025,
        status: 'available', lien_level: 'unscreened', lien_note: '', sale_date: null, url_auction: 'https://x', url_auction_kind: 'county',
        inventory_type: 'POST_SALE_FIXED_PRICE', source_authority: 'GOVERNMENT_PLATFORM', source_id: 'fl_laft_pioneer', list_url: 'https://x',
        purchase_amount: 1200 + i * 375, purchase_amount_kind: 'OPENING_BID', publication_status: 'APPROVED_GRANDFATHERED', last_seen_at: now, updated_at: now };
      if (i === 1) row.address = LEGAL;                  // legal description in the address column
      if (i === 2) row.address = null;                   // no address published
      if (i === 3 || i === 4) { row.latitude = CENTRE[county][0] + i * 0.01; row.longitude = CENTRE[county][1] - i * 0.01; }
      if (i === 4) { row.photo_source = 'usda_naip'; row.photo_url = PLACARD; row.photo_captured_year = 2023; }
      out.push(row);
    }
  });
  return out;
}
