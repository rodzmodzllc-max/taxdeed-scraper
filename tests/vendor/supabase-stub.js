// Minimal fake of the @supabase/supabase-js client surface app.js touches,
// so the filters-panel wiring can be exercised in a real browser without a
// live Supabase project. Not shipped - test harness only.

const FIXTURE_PROPERTIES = [
  { id: "p1", source: "auction", county: "Alachua", case_no: "A-1", parcel: "111", address: "1 Main St", owner_name: "Jane Doe", bid: 5000, assessed: 80000, market: 90000, status: "active", lien_level: "clean", lien_note: "", prop_type: "House", sale_date: futureDate(3), homestead: false, url_streetview: "https://x", url_appraiser: "https://x", url_zillow: "https://x", url_taxcoll: "https://x", url_auction: "https://x", url_title: "https://x", updated_at: "2026-08-10T00:00:00Z" },
  { id: "p2", source: "auction", county: "Baker", case_no: "B-1", parcel: "222", address: "", owner_name: null, bid: 15000, assessed: 40000, market: 42000, status: "dropped", lien_level: "serious", lien_note: "lien", prop_type: "Vacant Lot", sale_date: futureDate(30), homestead: false, url_auction: "https://x", updated_at: "2026-08-10T00:00:00Z", gone_since: "2026-08-01T00:00:00Z" },
  { id: "p3", source: "laft", county: "Bay", case_no: "C-1", parcel: "333", address: "3 Oak Ave", owner_name: "Bob", bid: 2000, assessed: 60000, market: 61000, status: "available", lien_level: "unscreened", lien_note: "", prop_type: "Condo", sale_date: null, homestead: true, url_auction: "https://x", updated_at: "2026-08-11T00:00:00Z" },
  { id: "p4", source: "certificate", county: "Alachua", case_no: "ACC-999", certificate_no: "CERT-42", tax_year: "2022", bid: 1234.56, interest_rate: null, issued_date: "2023-06-01", expiration_date: futureDate(20), url_auction: "https://lienhub.com/county/alachua/countyheld/certificates", updated_at: "2026-08-12T00:00:00Z" },
  { id: "p5", source: "auction", county: "Charlotte", case_no: "D-1", parcel: "444", address: "500 Elm Way", owner_name: "Sam Lee", bid: 8000, assessed: 70000, market: 95000, status: "active", lien_level: "clean", lien_note: "", prop_type: "House", sale_date: futureDate(5), homestead: false, url_streetview: "https://x", url_appraiser: "https://x", url_auction: "https://x", updated_at: "2026-08-10T00:00:00Z" },
  { id: "p6", source: "auction", county: "Duval", case_no: "E-1", parcel: "555", address: "77 Pine Ct", owner_name: "Pat Kim", bid: 12000, assessed: 130000, market: 140000, status: "active", lien_level: "flag", lien_note: "code lien", prop_type: "Commercial", sale_date: futureDate(7), homestead: false, url_auction: "https://x", updated_at: "2026-08-10T00:00:00Z" },
  { id: "p7", source: "auction", county: "Duval", case_no: "F-1", parcel: "666", address: "12 Searchable Blvd", owner_name: "Ana Ruiz", bid: 3000, assessed: 20000, market: 21000, status: "active", lien_level: "clean", lien_note: "", prop_type: "Vacant Lot", sale_date: futureDate(9), homestead: false, url_auction: "https://x", updated_at: "2026-08-10T00:00:00Z" },
  { id: "p8", source: "auction", county: "Escambia", case_no: "G-1", parcel: "777", address: "9 Bayview Dr", owner_name: "Lee Chan", bid: 6000, assessed: 55000, market: 60000, status: "active", lien_level: "clean", lien_note: "", prop_type: "House", sale_date: futureDate(11), homestead: false, url_auction: "https://x", updated_at: "2026-08-10T00:00:00Z" },
  { id: "p9", source: "auction", county: "Escambia", case_no: "H-1", parcel: "888", address: "21 Harbor Ln", owner_name: "Nia Frost", bid: 4500, assessed: 48000, market: 52000, status: "active", lien_level: "clean", lien_note: "", prop_type: "Condo", sale_date: futureDate(13), homestead: false, url_auction: "https://x", updated_at: "2026-08-10T00:00:00Z" },
  { id: "p10", source: "auction", county: "Marion", case_no: "I-1", parcel: "999", address: "3 Ridge Rd", owner_name: "Omar Diaz", bid: 7000, assessed: 65000, market: 72000, status: "active", lien_level: "unscreened", lien_note: "", prop_type: "House", sale_date: futureDate(15), homestead: false, url_auction: "https://x", updated_at: "2026-08-10T00:00:00Z" },
  { id: "p11", source: "auction", county: "Marion", case_no: "J-1", parcel: "1010", address: "88 Cedar Ct", owner_name: "Priya Shah", bid: 9000, assessed: 85000, market: 91000, status: "active", lien_level: "clean", lien_note: "", prop_type: "Vacant Lot", sale_date: futureDate(17), homestead: false, url_auction: "https://x", updated_at: "2026-08-10T00:00:00Z" },
  { id: "p12", source: "auction", county: "Brevard", case_no: "K-1", parcel: "1111", address: "42 Palm Ave", owner_name: "Kim Ng", bid: 11000, assessed: 100000, market: 118000, status: "active", lien_level: "clean", lien_note: "", prop_type: "House", sale_date: futureDate(2), homestead: false, url_auction: "https://x", updated_at: "2026-08-10T00:00:00Z" },
  // Past-due: sale date already came and went, but the scraper hasn't (yet)
  // re-visited the county site to flip status to dropped/sold/notfound - the
  // exact "still shows as active for a week after the auction" bug report.
  // Must NOT appear in the default ledger view even though status is "active".
  { id: "p13", source: "auction", county: "Alachua", case_no: "L-1", parcel: "1212", address: "6 Past Due Ln", owner_name: "Lin Cho", bid: 5000, assessed: 60000, market: 70000, status: "active", lien_level: "clean", lien_note: "", prop_type: "House", sale_date: futureDate(-6), homestead: false, url_auction: "https://x", updated_at: "2026-08-10T00:00:00Z" }
];
// Brevard has a county_calendar row so the "Auction {date}" label test can
// cover the CALENDAR-lookup path, not just the per-property sale_date
// fallback every other county in this fixture exercises.
const CALENDAR_ROWS = [{ county: "Brevard", sale_date: futureDate(2) }];
function futureDate(days) {
  const d = new Date(); d.setDate(d.getDate() + days);
  return d.toISOString().slice(0, 10);
}

class MockQuery {
  constructor(table) { this.table = table; this._op = "select"; }
  select() { return this; }
  order() { return this; }
  eq() { return this; }
  gte() { return this; }
  insert(row) { this._op = "insert"; this._row = row; return this; }
  delete() { this._op = "delete"; return this; }
  upsert(row) { this._op = "upsert"; this._row = row; return this; }
  then(resolve) {
    let result = { data: [], error: null };
    if (this._op === "select") {
      if (this.table === "properties") result.data = FIXTURE_PROPERTIES;
      else if (this.table === "notes") result.data = [];
      else if (this.table === "favorites") result.data = [];
      else if (this.table === "hidden") result.data = [];
      else if (this.table === "county_calendar") result.data = CALENDAR_ROWS;
    }
    resolve(result);
    return Promise.resolve(result);
  }
}

export function createClient() {
  return {
    auth: {
      async getSession() { return { data: { session: { user: { id: "u1", email: "test@example.com" } } } }; },
      onAuthStateChange(cb) { setTimeout(() => cb("SIGNED_IN", { user: { id: "u1", email: "test@example.com" } }), 0); return { data: { subscription: { unsubscribe() {} } } }; },
      async signInWithPassword() { return { error: null }; },
      async signOut() { return {}; }
    },
    from(table) { return new MockQuery(table); }
  };
}
