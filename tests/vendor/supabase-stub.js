// Minimal fake of the @supabase/supabase-js client surface app.js touches,
// so the filters-panel wiring can be exercised in a real browser without a
// live Supabase project. Not shipped - test harness only.

// Phase 72: the RealAuction sale-event page for a county host and ISO sale
// date - the exact template harvest_all_counties.ps1 (FL) stores and
// harvest_realauction() (TX) fetches: AuctionDate is MM/DD/YYYY.
const txSaleUrl = (host, iso) => `https://${host}/index.cfm?zaction=AUCTION&zmethod=PREVIEW&AuctionDate=${iso.slice(5, 7)}/${iso.slice(8, 10)}/${iso.slice(0, 4)}`;

const FIXTURE_PROPERTIES = [
  // harvester_source added Phase 35 (regression coverage for the new
  // "Data source" provenance line) - a plausible FL harvester id, chosen
  // freely since assessedSourceLabel() only branches on harvester_source
  // for TX rows; on FL it's ignored entirely, so this can't affect any
  // pre-existing FL assertion.
  // Phase 72: url_auction_kind (migration 013) on every row that has a
  // url_auction, matching what the real writers store: FL deed rows carry
  // the RealAuction sale-date page ('sale'), LAFT rows the county list
  // ('county'), certificates LienHub's county-held list ('county'). p7/p8
  // exercise the two remaining kinds; p9 keeps a URL with NO kind (a row
  // written before migration 013) so the neutral fallback label is covered.
  { id: "p1", source: "auction", county: "Alachua", case_no: "A-1", parcel: "111", address: "1 Main St", owner_name: "Jane Doe", bid: 5000, assessed: 80000, market: 90000, value_year: 2025, year_built: 1958, living_area: 1840, lot_sqft: 16456, num_buildings: 1, land_value: 22000, last_sale_price: 41500, last_sale_year: 2011, legal_desc: "BEG 418 FT S AND 110 FT W OF INTER OF E AND W HALF SEC LI AND L AND N RR W 100 FT N 50 FT E 100 FT S 50 FT TO POB", status: "active", lien_level: "clean", lien_note: "", prop_type: "House", sale_date: futureDate(3), homestead: false, harvester_source: "fl_realauction_alachua", url_streetview: "https://x", url_appraiser: "https://x", url_zillow: "https://x", url_taxcoll: "https://x", url_auction: txSaleUrl("alachua.realtaxdeed.com", futureDate(3)), url_auction_kind: "sale", url_title: "https://x", updated_at: "2026-08-10T00:00:00Z" },
  { id: "p2", source: "auction", county: "Baker", case_no: "B-1", parcel: "222", address: "", owner_name: null, bid: 15000, assessed: 40000, market: 42000, status: "dropped", lien_level: "serious", lien_note: "lien", prop_type: "Vacant Lot", sale_date: futureDate(30), homestead: false, url_auction: "https://x", url_auction_kind: "sale", updated_at: "2026-08-10T00:00:00Z", gone_since: "2026-08-01T00:00:00Z" },
  // p3 also carries migration 017's OTC columns as the FL LAFT lifecycle
  // writes them (inventory_type, source_authority/source_id, list_url,
  // purchase_amount + purchase_amount_kind, last_seen_at).
  { id: "p3", source: "laft", county: "Bay", case_no: "C-1", parcel: "333", address: "3 Oak Ave", owner_name: "Bob", bid: 2000, assessed: 60000, market: 61000, value_year: 2024, land_value: 61000, lot_sqft: 43560, last_sale_price: 100, last_sale_year: 2007, status: "available", lien_level: "unscreened", lien_note: "", prop_type: "Condo", sale_date: null, homestead: true, url_auction: "https://x", url_auction_kind: "county", updated_at: "2026-08-11T00:00:00Z",
    inventory_type: "POST_SALE_FIXED_PRICE", source_authority: "GOVERNMENT_PLATFORM", source_id: "fl_laft_pioneer", list_url: "https://x", purchase_amount: 2000, purchase_amount_kind: "OPENING_BID", last_seen_at: "2026-08-11T00:00:00Z",
    // AVAILABLE commercialization (2026-09-30): the source's publication
    // decision (migration 022) and an FDOR acreage, so the Available filters
    // and the withholding path have real fields to read.
    publication_status: "APPROVED_GRANDFATHERED", acreage: 1.0,
    // Migration 023 projects the purchase-path columns as NULL on a row the
    // engine has not evaluated - the "not yet verified" state the decision
    // page and the provenance card must render honestly (p15 is the typed one).
    purchase_path_type: null, purchase_path_scope: null, purchase_path_evidence: null, purchase_path_observed_on: null,
    // Enrichment phase: the list-published fields scripts/laft_source_fields.py
    // carries (certificate number, migration 019's two dates) plus the
    // document/currentness columns the lifecycle writes. purchase_url stays
    // absent on purpose - no Florida county has a verified purchase link.
    document_url: "https://x/list.pdf", certificate_no: "2019-0042", escheatment_date: "2029-07-01", available_date: "2026-06-15",
    list_as_of: "2026-08-10", source_published_at: "2026-08-10T14:03:00Z",
    // Production-readiness (migration 021): the normalized status the
    // inventory-status writer sets from list presence, plus the per-field
    // (009) and per-row (017) provenance the RPC now projects.
    inventory_status: "available_otc", inventory_status_raw: null,
    inventory_status_basis: "LIST_PRESENCE: on the county's Lands Available list at the last read (F.S. 197.502(7))",
    inventory_status_observed_at: "2026-08-11T06:00:00Z",
    field_provenance: {
      legal_desc: { source: "county_list", source_id: "fl_laft_pioneer", recorded_at: "2026-08-11T06:00:00Z", list_as_of: "2026-08-10" },
      assessed: { source: "fdor_nal", recorded_at: "2026-08-12T10:00:00Z", matched_field: "PARCEL_ID" },
      acreage: { source: "fdor_nal", recorded_at: "2026-08-12T10:00:00Z", matched_field: "ALT_KEY" }
    },
    otc_provenance: { harvester: "fl_laft_pioneer", list_url: "https://x", retrieved_at: "2026-08-11T06:00:00Z", purchase_path_mode: "unknown",
      purchase_amount: "source column/field: OPENING_BID", list_as_of: "stated by the list document/filename",
      purchase_url: "no purchase path published by the source or verified in the registry - none invented",
      inventory_type: "harvester constant (F.S. 197.502(7) Lands Available list)",
      status_terminology: "active = on the county list this run; closed = absent from a COMPLETE/EMPTY harvest" },
    // Phase 66: photo_url '' is the pipeline's "checked, no Street View
    // coverage" sentinel (see CLAUDE.md "Property photos") - distinct from
    // NULL/absent (not checked yet), which every other row here has.
    photo_url: "" },
  // interest_rate was null here originally; set to a real figure so the
  // yield-desk math (accruedInterestEst/tdaEligibleText) has something to
  // compute against instead of only exercising its N/A branch. issued_date
  // is a fixed past date rather than an offset from "today" specifically
  // because the TDA-eligibility assertion depends on it landing more than
  // CERT_TDA_WAIT_YEARS (2) in the past - true today and for the life of
  // this fixture, unlike a rolling offset.
  // Three ledgers (2026-09-30): p4 carries parcel "111" - the same parcel as
  // auction row p1 - so the shared-property linkage ("same parcel in other
  // ledgers") has one real pair to render in both directions.
  { id: "p4", source: "certificate", county: "Alachua", case_no: "ACC-999", certificate_no: "CERT-42", tax_year: "2022", parcel: "111", bid: 1234.56, interest_rate: 18, issued_date: "2023-06-01", expiration_date: futureDate(20), url_auction: "https://lienhub.com/county/alachua/countyheld/certificates", url_auction_kind: "county", updated_at: "2026-08-12T00:00:00Z" },
  // Phase 67: p5 and p12 carry real-shaped coordinates (inside Charlotte and
  // Brevard respectively) so the map's pin/selection/imagery paths can be
  // exercised - every other row stays un-geocoded, which is the honest
  // production picture (~2% coverage).
  { id: "p5", source: "auction", county: "Charlotte", case_no: "D-1", parcel: "444", address: "500 Elm Way", owner_name: "Sam Lee", bid: 8000, assessed: 70000, market: 95000, status: "active", lien_level: "clean", lien_note: "", prop_type: "House", sale_date: futureDate(5), homestead: false, url_streetview: "https://x", url_appraiser: "https://x", url_auction: txSaleUrl("charlotte.realforeclose.com", futureDate(5)), url_auction_kind: "sale", updated_at: "2026-08-10T00:00:00Z", latitude: 26.9342, longitude: -82.0454 },
  { id: "p6", source: "auction", county: "Duval", case_no: "E-1", parcel: "555", address: "77 Pine Ct", owner_name: "Pat Kim", bid: 12000, assessed: 130000, market: 140000, status: "active", lien_level: "flag", lien_note: "code lien", prop_type: "Commercial", sale_date: futureDate(7), homestead: false, url_auction: "https://x", url_auction_kind: "sale", updated_at: "2026-08-10T00:00:00Z",
    // Phase 66: the one fixture row WITH a photo. A same-origin data: URI
    // (CSP allows data: in img-src) drawn as a plainly-labelled grey
    // placard, so the photo layout can be exercised and screenshotted
    // without a real Street View image - it is not a real property photo
    // and is labelled as such in the image itself.
    // Every stored image in production is USDA NAIP aerial imagery
    // (photo_source usda_naip), so the fixture mirrors that source - the
    // card must caption it as aerial imagery, never as Street View.
    photo_source: "usda_naip",
    photo_url: "data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='640' height='400'><rect width='100%' height='100%' fill='%2394a3b8'/><text x='50%' y='50%' dominant-baseline='middle' text-anchor='middle' font-family='sans-serif' font-size='30' fill='%23ffffff'>FIXTURE PHOTO</text></svg>" },
  { id: "p7", source: "auction", county: "Duval", case_no: "F-1", parcel: "666", address: "12 Searchable Blvd", owner_name: "Ana Ruiz", bid: 3000, assessed: 20000, market: 21000, status: "active", lien_level: "clean", lien_note: "", prop_type: "Vacant Lot", sale_date: futureDate(9), homestead: false, url_auction: "https://notices.collierclerk.com/notice/notice-of-application-for-tax-deed-26004/", url_auction_kind: "property", updated_at: "2026-08-10T00:00:00Z" },
  { id: "p8", source: "auction", county: "Escambia", case_no: "G-1", parcel: "777", address: "9 Bayview Dr", owner_name: "Lee Chan", bid: 6000, assessed: 55000, market: 60000, status: "active", lien_level: "clean", lien_note: "", prop_type: "House", sale_date: futureDate(11), homestead: false, url_auction: "https://www.escambiaclerk.com/tax-deed-sales", url_auction_kind: "info", updated_at: "2026-08-10T00:00:00Z" },
  { id: "p9", source: "auction", county: "Escambia", case_no: "H-1", parcel: "888", address: "21 Harbor Ln", owner_name: "Nia Frost", bid: 4500, assessed: 48000, market: 52000, status: "active", lien_level: "clean", lien_note: "", prop_type: "Condo", sale_date: futureDate(13), homestead: false, url_auction: "https://x", updated_at: "2026-08-10T00:00:00Z" },
  { id: "p10", source: "auction", county: "Marion", case_no: "I-1", parcel: "999", address: "3 Ridge Rd", owner_name: "Omar Diaz", bid: 7000, assessed: 65000, market: 72000, status: "active", lien_level: "unscreened", lien_note: "", prop_type: "House", sale_date: futureDate(15), homestead: false, url_auction: "https://x", url_auction_kind: "sale", updated_at: "2026-08-10T00:00:00Z" },
  { id: "p11", source: "auction", county: "Marion", case_no: "J-1", parcel: "1010", address: "88 Cedar Ct", owner_name: "Priya Shah", bid: 9000, assessed: 85000, market: 91000, status: "active", lien_level: "clean", lien_note: "", prop_type: "Vacant Lot", sale_date: futureDate(17), homestead: false, url_auction: "https://x", url_auction_kind: "sale", updated_at: "2026-08-10T00:00:00Z" },
  { id: "p12", source: "auction", county: "Brevard", case_no: "K-1", parcel: "1111", address: "42 Palm Ave", owner_name: "Kim Ng", bid: 11000, assessed: 100000, market: 118000, status: "active", lien_level: "clean", lien_note: "", prop_type: "House", sale_date: futureDate(2), homestead: false, url_auction: "https://x", url_auction_kind: "sale", updated_at: "2026-08-10T00:00:00Z", latitude: 28.3922, longitude: -80.6077 },
  // Past-due: sale date already came and went, but the scraper hasn't (yet)
  // re-visited the county site to flip status to dropped/sold/notfound - the
  // exact "still shows as active for a week after the auction" bug report.
  // Must NOT appear in the default ledger view even though status is "active".
  { id: "p13", source: "auction", county: "Alachua", case_no: "L-1", parcel: "1212", address: "6 Past Due Ln", owner_name: "Lin Cho", bid: 5000, assessed: 60000, market: 70000, status: "active", lien_level: "clean", lien_note: "", prop_type: "House", sale_date: futureDate(-6), homestead: false, url_auction: "https://x", url_auction_kind: "sale", updated_at: "2026-08-10T00:00:00Z" },
  // AVAILABLE commercialization (2026-09-30): an Available row whose SOURCE is
  // RESTRICTED (migration 022's publication_status, propagated from the
  // registry - here a source under legal review). The frontend must withhold
  // it from the list, the counts, the map and the export, and say so on the
  // Available ledger page ("1 record withheld"). Never rendered as inventory.
  { id: "p14", source: "laft", county: "Broward", case_no: "R-1", parcel: "777", address: "7 Restricted Rd", owner_name: "Withheld Source", bid: 3000, assessed: 40000, market: 41000, status: "available", lien_level: "unscreened", lien_note: "", prop_type: "Vacant", sale_date: null, homestead: false, url_auction: "https://x", url_auction_kind: "county", updated_at: "2026-08-11T00:00:00Z",
    inventory_type: "POST_SALE_FIXED_PRICE", source_authority: "GOVERNMENT_DIRECT", source_id: "fl_laft_broward_candidate", publication_status: "RESTRICTED" },
  // Available commercial release (2026-09-30, migration 023): an Available
  // row whose purchase path the engine established from evidence (a
  // source-level county instructions page, with its evidence and observed
  // date), with coordinates, a land use and a county value - so the typed
  // path, the decision page's "how / where / known" answers and the new
  // land-use / coordinates / value filters have one real row each way
  // (p3 stays untyped: "not yet verified"). No published amount on purpose.
  { id: "p15", source: "laft", county: "Citrus", case_no: "CI-7", parcel: "1515", address: "15 Manatee Ln", owner_name: "Lee Park", bid: 0, assessed: 25000, market: 26000, value_year: 2025, status: "available", lien_level: "unscreened", lien_note: "", prop_type: "Vacant Lot", sale_date: null, homestead: false, url_auction: "https://x", url_auction_kind: "county", updated_at: "2026-09-20T00:00:00Z",
    latitude: 28.8886, longitude: -82.4520, land_use: "Vacant residential", acreage: 0.3,
    inventory_type: "POST_SALE_FIXED_PRICE", source_authority: "GOVERNMENT_DIRECT", source_id: "fl_laft_html", list_url: "https://x/citrus-list",
    purchase_amount: null, purchase_amount_kind: "NOT_PUBLISHED", first_seen_at: "2026-07-01T06:00:00Z", last_seen_at: "2026-09-20T06:00:00Z", list_as_of: "2026-09-19",
    publication_status: "APPROVED_GRANDFATHERED",
    purchase_url: "https://www.citrusclerk.example.gov/lands-available/how-to-purchase", purchase_url_kind: "purchase_instructions",
    purchase_path_type: "county_instructions", purchase_path_scope: "source",
    purchase_path_evidence: "Clerk's 'How to purchase Lands Available' page names the application and payment steps (data/purchase_path_evidence.csv, observed 2026-09-18)",
    purchase_path_observed_on: "2026-09-18",
    inventory_status: "available_otc", inventory_status_raw: null,
    inventory_status_basis: "LIST_PRESENCE: on the county's Lands Available list at the last read (F.S. 197.502(7))",
    inventory_status_observed_at: "2026-09-20T06:00:00Z",
    otc_provenance: { harvester: "fl_laft_html", list_url: "https://x/citrus-list", retrieved_at: "2026-09-20T06:00:00Z", purchase_path_mode: "online_instructions",
      purchase_amount: "not published by the source", list_as_of: "stated by the list document/filename",
      purchase_url: "county_instructions (source-scope): Clerk's 'How to purchase Lands Available' page",
      inventory_type: "harvester constant (F.S. 197.502(7) Lands Available list)",
      status_terminology: "active = on the county list this run; closed = absent from a COMPLETE/EMPTY harvest",
      // Acquisition sprint: what the LAFT lifecycle writes from the verified
      // evidence record (scripts/purchase_path_engine.PurchasePath.provenance()) -
      // FIXTURE values on the fixture's own example.gov domain, not a real county's.
      purchase_evidence_url: "https://www.citrusclerk.example.gov/lands-available/how-to-purchase", purchase_evidence_type: "county_page",
      purchase_evidence_title: "How to purchase Lands Available (fixture)", purchase_path_observed_on: "2026-09-18",
      purchase_instructions: "Complete the application and pay at the Tax Deed office (fixture wording).",
      source_match: { identifier: "case_no", value: "CI-7", parcel: "1515", source: "https://x/citrus-list", read_at: "2026-09-20T06:00:00Z",
                      basis: "row read from the source list / document by the harvester; identity as the sync upserts it" },
      acquisition: { mode: "multi_step", channels: ["instructions", "email", "phone", "in_person"],
                     office: "Fixture County Clerk - Tax Deed Division (fixture)", address: "1 Example Ave, Inverness, FL 00000 (fixture)",
                     phone: "(000) 000-0000", email: "taxdeeds@example.gov", payment: "Certified funds (fixture)",
                     application_url: "https://www.citrusclerk.example.gov/lands-available/application.pdf",
                     steps: ["Download and complete the application (fixture)", "E-mail taxdeeds@example.gov with the case number (fixture)", "Pay in certified funds at 1 Example Ave (fixture)"],
                     evidence_url: "https://www.citrusclerk.example.gov/lands-available/how-to-purchase", observed_on: "2026-09-18" } } },
  // Phase 34: a TX row with no url_zillow/url_streetview and no
  // latitude/longitude - the exact shape (harvester-synced, no
  // hand-researched link, no geocode yet) that forces app.js's
  // fallbackZillowUrl()/fallbackStreetviewUrl() to build a search URL from
  // address+county+state. Regression coverage for the Phase 33 P1 finding:
  // those two functions used to hardcode "County, FL" for every property
  // regardless of state. `state: "TX"` is what makes this row TX instead of
  // the implicit-FL every other row above gets (see the rpc() filter below).
  // Phase 72: ptx1 is an LGBS auction row, and LGBS rows carry NO auction
  // link in production (the audit found no verified per-property or
  // per-sale LGBS URL anywhere) - so no url_auction here; the UI must say
  // "Auction link not published". tx_sale_status is LGBS's raw status.
  { id: "ptx1", source: "auction", state: "TX", county: "Harris", case_no: "TX-1", parcel: "TX999", address: "100 Longhorn Rd", owner_name: "Tex Owner", bid: 5000, assessed: 90000, market: 95000, status: "active", lien_level: "clean", lien_note: "", prop_type: "House", tx_category: "A1", sale_date: futureDate(4), homestead: false, harvester_source: "tx_lgbs", tx_sale_status: "Scheduled for Online Auction", updated_at: "2026-08-10T00:00:00Z" },
  // Phase 72 Texas shapes, each the exact form migration 013 / the Texas
  // sync produce (case_no = account number, parcel = cause number):
  //   ptx2  RealAuction, upcoming sale: the county sale-date page, kind 'sale'
  //   ptx3  LGBS struck-off (laft ledger), raw status kept, no link
  //   ptx4  RealAuction whose sale date has passed: link is not current
  //   ptx5  RealAuction with no URL (county host not on the verified roster)
  //   ptx6  LGBS "Available for Future Sale" (laft ledger), no link
  { id: "ptx2", source: "auction", state: "TX", county: "Nueces", case_no: "9377-0051-0100", parcel: "2021DCV-4034-H (5)", address: "4013 Tilden St, Corpus Christi, TX", bid: 21800, min_bid: 21800, assessed: 25000, status: "active", sale_date: futureDate(12), harvester_source: "tx_realauction", url_auction: txSaleUrl("nueces.texas.sheriffsaleauctions.com", futureDate(12)), url_auction_kind: "sale", updated_at: "2026-09-24T00:00:00Z" },
  // ptx3 / ptx6 carry migration 017's classification exactly as its backfill
  // derives it from tx_sale_status: STRUCK_OFF_HELD_IN_TRUST vs FUTURE_RESALE,
  // VENDOR_COUNSEL / tx_lgbs, no list/document/purchase URL (LGBS publishes
  // none), purchase_amount untouched (null - min_bid keeps its own meaning).
  { id: "ptx3", source: "laft", state: "TX", county: "Galveston", case_no: "129500040015000", parcel: "23-TX-0644", address: "VACANT LOT IN 6500 BLOCK OF OBRIEN ST, Hitchcock, TX 77563", bid: 4451.95, min_bid: 4451.95, status: "active", sale_date: null, harvester_source: "tx_lgbs", tx_sale_status: "Struck off to Jurisdiction", updated_at: "2026-09-23T00:00:00Z",
    inventory_status: "struck_off", inventory_status_raw: "Struck off to Jurisdiction", inventory_status_basis: "SOURCE_STATUS: the vendor's own sale status (LGBS)", inventory_status_observed_at: "2026-09-23T06:00:00Z",
    inventory_type: "STRUCK_OFF_HELD_IN_TRUST", source_authority: "VENDOR_COUNSEL", source_id: "tx_lgbs", list_url: null, document_url: null, purchase_url: null, purchase_amount: null, purchase_amount_kind: null },
  { id: "ptx4", source: "auction", state: "TX", county: "Llano", case_no: "R000020419", parcel: "23101 (6)", address: "LOT 6 SUNRISE BEACH, Llano, TX", bid: 3942.08, min_bid: 3942.08, status: "active", sale_date: futureDate(-3), harvester_source: "tx_realauction", url_auction: txSaleUrl("llano.texas.sheriffsaleauctions.com", futureDate(-3)), url_auction_kind: "sale", updated_at: "2026-09-24T00:00:00Z" },
  { id: "ptx5", source: "auction", state: "TX", county: "Atascosa", case_no: "17854", parcel: "20-11-0957-CVA (1)", address: "200 Oak St, Pleasanton, TX", bid: 1200, min_bid: 1200, status: "active", sale_date: futureDate(12), harvester_source: "tx_realauction", updated_at: "2026-09-24T00:00:00Z" },
  { id: "ptx6", source: "laft", state: "TX", county: "Liberty", case_no: "000016000361003", parcel: "21DC-TX-00185", address: "TRACT 3, Liberty, TX", bid: 900, min_bid: 900, status: "active", sale_date: null, harvester_source: "tx_lgbs", tx_sale_status: "Available for Future Sale", updated_at: "2026-09-23T00:00:00Z",
    inventory_type: "FUTURE_RESALE", source_authority: "VENDOR_COUNSEL", source_id: "tx_lgbs", list_url: null, document_url: null, purchase_url: null, purchase_amount: null, purchase_amount_kind: null }
];
// Brevard has a county_calendar row so the "Auction {date}" label test can
// cover the CALENDAR-lookup path, not just the per-property sale_date
// fallback every other county in this fixture exercises.
const CALENDAR_ROWS = [{ county: "Brevard", sale_date: futureDate(2) }];
function futureDate(days) {
  const d = new Date(); d.setDate(d.getDate() + days);
  return d.toISOString().slice(0, 10);
}

// ?profile= switches which approval-gate scenario the signed-in test user
// (u1) lands in, so all three app.js paths (approved/normal, pending, admin
// with a pending queue) are screenshot/assert-able without a real Supabase
// project:
//   (default)  approved=true,  is_admin=false - the pre-approval-gate tests
//   pending    approved=false, is_admin=false - shows #pendingGate
//   admin      approved=true,  is_admin=true  - shows the admin panel, with
//                                               one other account pending
//   notable    approved=true,  is_admin=false, profiles table absent - the
//              "migration not run yet" fallback (falls back to showApp())
const PROFILE_MODE = new URLSearchParams(location.search).get("profile") || "default";

const PROFILES_TABLE = PROFILE_MODE === "notable" ? null : [
  PROFILE_MODE === "pending"
    ? { id: "u1", email: "test@example.com", approved: false, is_admin: false, requested_at: "2026-08-10T00:00:00Z" }
    : { id: "u1", email: "test@example.com", approved: true, is_admin: PROFILE_MODE === "admin", requested_at: "2026-08-01T00:00:00Z" },
  ...(PROFILE_MODE === "admin" ? [
    { id: "u2", email: "newperson@example.com", approved: false, is_admin: false, requested_at: "2026-08-16T00:00:00Z" }
  ] : [])
];

// SaaS hardening (2026-09-29): Phase B event history for the fixture, read
// by the full property page. p1 has one scheduled event with two
// observations (an opening-bid change between them); p13 (past-due) has a
// completed event whose outcome is - as in production, always - 'unknown'.
const EVENT_ROWS = [
  { id: "ev1", property_id: "p1", scheduled_sale_date: futureDate(3), lifecycle: "scheduled", outcome: "unknown", opening_bid: 5000, first_seen_at: "2026-09-01T10:00:00Z", last_seen_at: "2026-09-28T10:00:00Z", source: "auction", harvester_source: "fl_realauction_alachua", event_url_kind: "sale" },
  { id: "ev2", property_id: "p13", case_no: "L-1", scheduled_sale_date: futureDate(-6), lifecycle: "completed", outcome: "unknown", opening_bid: 5000, first_seen_at: "2026-08-20T10:00:00Z", last_seen_at: "2026-09-20T10:00:00Z", source: "auction", harvester_source: "fl_realauction_alachua", event_url_kind: "sale" },
  { id: "ev3", property_id: "p13", scheduled_sale_date: futureDate(-40), lifecycle: "superseded", outcome: "unknown", opening_bid: 4800, first_seen_at: "2026-07-01T10:00:00Z", last_seen_at: "2026-08-10T10:00:00Z", source: "auction", harvester_source: "fl_realauction_alachua", event_url_kind: "sale" },
  // Production-readiness: an event whose result the SOURCE published (the
  // writer's outcome_for_source path) - shown with the source's own wording.
  { id: "ev4", property_id: "p10", scheduled_sale_date: futureDate(-20), lifecycle: "completed", outcome: "struck_off", outcome_raw: "Struck off to Jurisdiction", outcome_observed_at: "2026-09-20T10:00:00Z", opening_bid: 7000, first_seen_at: "2026-08-25T10:00:00Z", last_seen_at: "2026-09-20T10:00:00Z", source: "auction", harvester_source: "fl_realauction_alachua", event_url_kind: "sale" }
];
const OBSERVATION_ROWS = [
  { id: 1, event_id: "ev1", observed_at: "2026-09-01T10:00:00Z", feed: "county_auction_site", raw_status: "scheduled", lifecycle: "scheduled", outcome: "unknown", opening_bid: 4500 },
  { id: 2, event_id: "ev1", observed_at: "2026-09-28T10:00:00Z", feed: "county_auction_site", raw_status: "scheduled", lifecycle: "scheduled", outcome: "unknown", opening_bid: 5000 },
  { id: 3, event_id: "ev2", observed_at: "2026-08-20T10:00:00Z", feed: "county_auction_site", raw_status: "scheduled", lifecycle: "scheduled", outcome: "unknown", opening_bid: 5000 },
  { id: 4, event_id: "ev2", observed_at: "2026-09-20T10:00:00Z", feed: "county_auction_site", raw_status: null, lifecycle: "completed", outcome: "unknown", opening_bid: 5000 },
  { id: 5, event_id: "ev3", observed_at: "2026-07-01T10:00:00Z", feed: "county_auction_site", raw_status: "scheduled", lifecycle: "scheduled", outcome: "unknown", opening_bid: 4800 },
  { id: 6, event_id: "ev4", observed_at: "2026-09-20T10:00:00Z", feed: "api", raw_status: "Struck off to Jurisdiction", lifecycle: "completed", outcome: "struck_off", opening_bid: 7000 },
  // Auction-outcome evidence: the sale day's Closed or Canceled listing was
  // read (scripts/auction_outcomes.py) and printed no result line for p13's
  // item - "Outcome not published", never a guess.
  { id: 7, event_id: "ev2", observed_at: "2026-09-25T10:00:00Z", feed: "closed", raw_status: null, lifecycle: "completed", outcome: "unknown", opening_bid: null, evidence_url: "https://alachua.realtaxdeed.com/index.cfm?zaction=AUCTION&zmethod=PREVIEW&AuctionDate=09/24/2026" }
];
// Lifecycle history rows (migration 021's inventory_status_observations +
// 022/023's transition and result columns): p15 was observed, left the
// list, and came back - the append-only record the decision page shows.
// `?history=none` simulates the table not existing yet.
const HISTORY_MODE = new URLSearchParams(location.search).get("history") || "default";
const INVENTORY_HISTORY_ROWS = HISTORY_MODE === "none" ? null : [
  { id: 1, property_id: "p15", observed_at: "2026-07-01T06:00:00Z", source_id: "fl_laft_html", raw_status: null, inventory_status: "available_otc", basis: "LIST_PRESENCE: on the county's Lands Available list at the last read (F.S. 197.502(7))", transition: "newly_observed" },
  { id: 2, property_id: "p15", observed_at: "2026-08-15T06:00:00Z", source_id: "fl_laft_html", raw_status: null, inventory_status: "closed", basis: "LIST_PRESENCE: absent from the county's Lands Available list at a COMPLETE/EMPTY read; why is not published", transition: "removed" },
  { id: 3, property_id: "p15", observed_at: "2026-09-01T06:00:00Z", source_id: "fl_laft_html", raw_status: null, inventory_status: "available_otc", basis: "LIST_PRESENCE: on the county's Lands Available list at the last read (F.S. 197.502(7))", transition: "reactivated" }
];
// Admin publication reviews (migration 023's source_publication_reviews):
// one prior decision, appended to by the admin panel's form in the test.
// `?reviews=none` simulates the table not existing yet.
const REVIEWS_MODE = new URLSearchParams(location.search).get("reviews") || "default";
const REVIEW_ROWS = REVIEWS_MODE === "none" ? null : [
  { id: 1, state: "FL", source_id: "fl_laft_pioneer", publication_status: "APPROVED_GRANDFATHERED", restrictions: null, decision_note: "carried forward", evidence: "served to customers before the gate existed", decided_by: "u1", decided_at: "2026-09-29T10:00:00Z", next_review: "2027-03-01" }
];
// Dataset health rows (migration 016) - one healthy scheduled source, one
// INCOMPLETE, one FAILED, one manual Texas source, one stale. `?health=none`
// simulates the table not existing yet.
const HEALTH_MODE = new URLSearchParams(location.search).get("health") || "default";
const hoursAgo = h => new Date(Date.now() - h * 3600000).toISOString();
// Per-county freshness rows (county_source_registry + migration 021's
// columns). `?registry=none` simulates the columns not existing yet.
const REGISTRY_MODE = new URLSearchParams(location.search).get("registry") || "default";
const REGISTRY_ROWS = REGISTRY_MODE === "none" ? null : [
  { state: "FL", county: "Alachua", source_id: "fl_laft_realtdm", last_attempt_at: hoursAgo(2), last_attempt_status: "COMPLETE", last_success_at: hoursAgo(2), last_success_row_count: 14, consecutive_failures: 0, publication_status: "APPROVED_GRANDFATHERED", restrictions: null, governance_status: "APPROVED_GRANDFATHERED", verification_status: "PRODUCTION_VERIFIED" },
  { state: "FL", county: "Bay", source_id: "fl_laft_pioneer", last_attempt_at: hoursAgo(2), last_attempt_status: "FAILED", last_success_at: hoursAgo(74), last_success_row_count: 3, consecutive_failures: 3, last_error_category: "TRANSPORT_HTTP_403_BLOCKED", publication_status: "APPROVED_GRANDFATHERED", restrictions: null, governance_status: "APPROVED_GRANDFATHERED", verification_status: "PRODUCTION_VERIFIED" },
  { state: "FL", county: "Bradford", source_id: "fl_laft_pdfs", last_attempt_at: null, last_attempt_status: null, last_success_at: null, last_success_row_count: null, consecutive_failures: 0, publication_status: "APPROVED_GRANDFATHERED", restrictions: null, governance_status: "APPROVED_GRANDFATHERED", verification_status: "PRODUCTION_VERIFIED" },
  // Citrus (p15's county): a current, complete read of the HTML source.
  { state: "FL", county: "Citrus", source_id: "fl_laft_html", last_attempt_at: hoursAgo(3), last_attempt_status: "COMPLETE", last_success_at: hoursAgo(3), last_success_row_count: 6, consecutive_failures: 0, publication_status: "APPROVED_GRANDFATHERED", restrictions: null, governance_status: "APPROVED_GRANDFATHERED", verification_status: "PRODUCTION_VERIFIED" },
  // A RESTRICTED candidate (p14's source): the admin panel must show its reason.
  { state: "FL", county: "Broward", source_id: "fl_laft_broward_candidate", last_attempt_at: null, last_attempt_status: null, last_success_at: null, last_success_row_count: null, consecutive_failures: 0, publication_status: "RESTRICTED", restrictions: "terms of use under legal review", governance_status: "LEGAL_REVIEW_REQUIRED", verification_status: "CANDIDATE" },
  { state: "TX", county: "Galveston", source_id: "tx_lgbs", last_attempt_at: hoursAgo(30), last_attempt_status: "INCOMPLETE", last_success_at: hoursAgo(54), last_success_row_count: 120, consecutive_failures: 0, publication_status: "APPROVED_GRANDFATHERED", restrictions: null, governance_status: "APPROVED_GRANDFATHERED", verification_status: "PRODUCTION_VERIFIED" }
];
const SOURCE_HEALTH_ROWS = HEALTH_MODE === "none" ? null : [
  { source: "fl_deeds", label: "Florida deed auctions (county auction sites)", state: "FL", mode: "scheduled", cadence_hours: 12, last_attempt_at: hoursAgo(2), last_attempt_status: "SUCCESS", last_success_at: hoursAgo(2), last_run_id: "1001", row_count: 812, units_total: 46, units_complete: 46, units_incomplete: 0, incomplete_units: [], completeness: "COMPLETE", error: null },
  { source: "fl_certificates", label: "Florida county-held certificates (LienHub)", state: "FL", mode: "scheduled", cadence_hours: 24, last_attempt_at: hoursAgo(3), last_attempt_status: "INCOMPLETE", last_success_at: hoursAgo(3), last_run_id: "1002", row_count: 391, units_total: 32, units_complete: 30, units_incomplete: 2, incomplete_units: ["Baker", "Gulf"], completeness: "INCOMPLETE", error: "2 unit(s) INCOMPLETE: Baker, Gulf" },
  { source: "fl_laft", label: "Florida Lands Available for Taxes (county lists)", state: "FL", mode: "scheduled", cadence_hours: 24, last_attempt_at: hoursAgo(1), last_attempt_status: "FAILED", last_success_at: hoursAgo(25), last_run_id: "1003", row_count: 0, units_total: null, units_complete: null, units_incomplete: null, incomplete_units: [], completeness: "UNKNOWN", error: "sync step outcome: failure" },
  { source: "tx_sales", label: "Texas tax sales (LGBS + county sheriff-sale sites) - manual runs", state: "TX", mode: "manual", cadence_hours: null, last_attempt_at: hoursAgo(200), last_attempt_status: "INCOMPLETE", last_success_at: hoursAgo(200), last_run_id: "1004", row_count: 531, units_total: 2, units_complete: 1, units_incomplete: 1, incomplete_units: ["lgbs"], completeness: "INCOMPLETE", error: "1 unit(s) INCOMPLETE: lgbs" },
  { source: "db_backup", label: "Database backup export", state: "ALL", mode: "scheduled", cadence_hours: 24, last_attempt_at: hoursAgo(80), last_attempt_status: "SUCCESS", last_success_at: hoursAgo(80), last_run_id: "1005", row_count: 3000, units_total: 3, units_complete: 3, units_incomplete: 0, incomplete_units: [], completeness: "COMPLETE", error: null }
];

class MockQuery {
  constructor(table) { this.table = table; this._op = "select"; this._filters = []; this._single = false; }
  select() { return this; }
  order() { return this; }
  eq(col, val) { this._filters.push([col, val]); return this; }
  in(col, vals) { this._filters.push([col, vals, "in"]); return this; }
  lt(col, val) { this._filters.push([col, val, "lt"]); return this; }
  range() { return this; }
  limit() { return this; }
  gte() { return this; }
  maybeSingle() { this._single = true; return this; }
  insert(row) { this._op = "insert"; this._row = row; return this; }
  update(patch) { this._op = "update"; this._row = patch; return this; }
  delete() { this._op = "delete"; return this; }
  upsert(row) { this._op = "upsert"; this._row = row; return this; }
  then(resolve) {
    let result = { data: [], error: null };
    if (this.table === "profiles" && STUB_AUTH) {
      // Row-level security: the signed-in user's own row only, values from the server table.
      const me = stubSessionUser();
      const own = me ? STUB_SERVER_USERS.filter(u => u.id === me.id && this._filters.every(([c, v]) => u[c] === v))
        .map(u => ({ id: u.id, email: u.email, approved: u.approved, is_admin: u.is_admin })) : [];
      result = { data: this._single ? (own[0] || null) : own, error: null };
    } else if (this.table === "profiles") {
      if (PROFILES_TABLE === null) {
        // Simulates schema-v6-approvals.sql not having been run yet.
        result = { data: null, error: { message: 'relation "public.profiles" does not exist', code: "42P01" } };
      } else {
        const matches = row => this._filters.every(([c, v]) => row[c] === v);
        if (this._op === "update") {
          PROFILES_TABLE.forEach(row => { if (matches(row)) Object.assign(row, this._row); });
          result = { data: null, error: null };
        } else {
          const rows = PROFILES_TABLE.filter(matches);
          result = { data: this._single ? (rows[0] || null) : rows, error: null };
        }
      }
    } else if (this._op === "insert" && this.table === "source_publication_reviews") {
      // Append-only, like the real table (RLS admits admins only).
      if (REVIEW_ROWS === null) result = { data: null, error: { message: "Could not find the table 'public.source_publication_reviews' in the schema cache", code: "PGRST205" } };
      else {
        const row = { id: REVIEW_ROWS.length + 1, decided_by: "u1", decided_at: new Date().toISOString(), ...this._row };
        REVIEW_ROWS.push(row);
        window.__stubReviewInserts = (window.__stubReviewInserts || []).concat([row]);
        result = { data: null, error: null };
      }
    } else if (this._op === "select") {
      const matches = row => this._filters.every(([c, v, kind]) => kind === "in" ? (v || []).includes(row[c]) : kind === "lt" ? String(row[c]) < String(v) : row[c] === v);
      if (this.table === "properties") result.data = FIXTURE_PROPERTIES;
      else if (this.table === "auction_events") result.data = EVENT_ROWS.filter(matches);
      else if (this.table === "auction_event_observations") result.data = OBSERVATION_ROWS.filter(matches);
      else if (this.table === "source_health") {
        result = SOURCE_HEALTH_ROWS === null
          ? { data: null, error: { message: "Could not find the table 'public.source_health' in the schema cache", code: "PGRST205" } }
          : { data: SOURCE_HEALTH_ROWS, error: null };
      }
      else if (this.table === "county_source_registry") {
        result = REGISTRY_ROWS === null
          ? { data: null, error: { message: "column county_source_registry.last_attempt_at does not exist", code: "42703" } }
          : { data: REGISTRY_ROWS, error: null };
      }
      else if (this.table === "inventory_status_observations") {
        result = INVENTORY_HISTORY_ROWS === null
          ? { data: null, error: { message: "Could not find the table 'public.inventory_status_observations' in the schema cache", code: "PGRST205" } }
          : { data: INVENTORY_HISTORY_ROWS.filter(matches), error: null };
      }
      else if (this.table === "source_publication_reviews") {
        result = REVIEW_ROWS === null
          ? { data: null, error: { message: "Could not find the table 'public.source_publication_reviews' in the schema cache", code: "PGRST205" } }
          : { data: REVIEW_ROWS.filter(matches).slice().sort((a, b) => (a.decided_at < b.decided_at ? 1 : -1)), error: null };
      }
      else if (this.table === "notes") result.data = [];
      else if (this.table === "favorites") result.data = [];
      else if (this.table === "hidden") result.data = [];
      else if (this.table === "county_calendar") result.data = CALENDAR_ROWS;
    }
    resolve(result);
    return Promise.resolve(result);
  }
}

// ?authtest=1 forces the sign-in gate to show (no session) instead of
// auto-signing-in, so the sign-up/sign-in toggle can be screenshot-tested.
const FORCE_GATE = new URLSearchParams(location.search).get("authtest") === "1";

// ?stubauth=1 (2026-09-30, admin area): a stand-in for the SERVER side of
// Supabase Auth + row-level security, for the sign-in / role tests. The
// user table below lives only in this module's closure (a page cannot read
// or edit it - the way the real auth.users / public.profiles cannot be
// edited from the browser); signInWithPassword checks the password here,
// the session is an opaque id in sessionStorage (supabase-js keeps its
// signed token there too), and a profiles read returns only the signed-in
// user's own row with the server's is_admin. The passwords are FIXTURE
// values for these fake accounts - not any real credential.
const STUB_AUTH = new URLSearchParams(location.search).get("stubauth") === "1";
const STUB_SESSION_KEY = "stub-auth-session";
const STUB_SERVER_USERS = [
  { id: "n1", email: "normal@example.com", password: "fixture-normal-pass", approved: true, is_admin: false },
  { id: "a1", email: "admin@example.com", password: "fixture-admin-pass", approved: true, is_admin: true }
];
const stubListeners = [];
function stubSessionUser() {
  let id = null;
  try { id = sessionStorage.getItem(STUB_SESSION_KEY); } catch { id = null; }
  const u = STUB_SERVER_USERS.find(x => x.id === id);
  return u ? { id: u.id, email: u.email } : null;
}
function stubEmit(event, user) { stubListeners.forEach(cb => setTimeout(() => cb(event, user ? { user } : null), 0)); }

export function createClient() {
  return {
    auth: {
      async getSession() {
        if (STUB_AUTH) { const u = stubSessionUser(); return { data: { session: u ? { user: u } : null } }; }
        if (FORCE_GATE) return { data: { session: null } };
        return { data: { session: { user: { id: "u1", email: "test@example.com" } } } };
      },
      onAuthStateChange(cb) {
        if (STUB_AUTH) { stubListeners.push(cb); return { data: { subscription: { unsubscribe() {} } } }; }
        if (!FORCE_GATE) setTimeout(() => cb("SIGNED_IN", { user: { id: "u1", email: "test@example.com" } }), 0);
        // ?recovery=1: what supabase-js emits after a password-reset link
        // lands (detectSessionInUrl consumed the recovery token).
        if (!FORCE_GATE && new URLSearchParams(location.search).get("recovery") === "1") {
          setTimeout(() => cb("PASSWORD_RECOVERY", { user: { id: "u1", email: "test@example.com" } }), 10);
        }
        return { data: { subscription: { unsubscribe() {} } } };
      },
      async signInWithPassword(creds) {
        if (STUB_AUTH) {
          const u = STUB_SERVER_USERS.find(x => creds && x.email === creds.email && x.password === creds.password);
          if (!u) return { data: { user: null, session: null }, error: { message: "Invalid login credentials", status: 400 } };
          sessionStorage.setItem(STUB_SESSION_KEY, u.id);
          const user = { id: u.id, email: u.email };
          stubEmit("SIGNED_IN", user);
          return { data: { user, session: { user } }, error: null };
        }
        return { error: null };
      },
      async signUp({ email }) {
        // Simulate the "check your email" (no immediate session) outcome -
        // the more interesting UI path to verify, since the auto-confirmed
        // path just reuses the existing onAuthStateChange->showApp flow.
        if (email && email.includes("autoconfirm")) {
          return { data: { user: { id: "u2", email }, session: { user: { id: "u2", email } } }, error: null };
        }
        return { data: { user: { id: "u2", email }, session: null }, error: null };
      },
      async signOut() {
        if (STUB_AUTH) { try { sessionStorage.removeItem(STUB_SESSION_KEY); } catch { /* ignore */ } stubEmit("SIGNED_OUT", null); }
        return {};
      },
      // SaaS hardening: the two supported-pattern calls the account
      // lifecycle uses. ?resetfail=1 makes the reset request fail so the
      // error path is exercised too.
      async resetPasswordForEmail(email, opts) {
        window.__stubResetCalls = (window.__stubResetCalls || []).concat([{ email, redirectTo: opts && opts.redirectTo }]);
        if (new URLSearchParams(location.search).get("resetfail") === "1") return { data: null, error: { message: "stub: reset refused" } };
        return { data: {}, error: null };
      },
      async updateUser(attrs) {
        window.__stubUpdateUserCalls = (window.__stubUpdateUserCalls || []).concat([attrs]);
        return { data: { user: { id: "u1", email: "test@example.com", user_metadata: (attrs && attrs.data) || {} } }, error: null };
      }
    },
    from(table) { return new MockQuery(table); },
    // Added Phase 15 (Customer Surface Security Audit): app.js's
    // fetchProperties() has called sb.rpc("get_properties", {p_state})
    // as its unconditional, primary path since
    // 003_ledger_type_and_state_isolation.sql (2026-09-08), but this stub
    // had no `rpc` method at all - `sb.rpc` was `undefined`, so calling it
    // threw a synchronous TypeError inside fetchProperties()'s async body,
    // an unhandled rejection that silently starved every downstream
    // assertion in this suite of any property data (this went unnoticed
    // because nothing in run_test.mjs checks for it directly - see
    // docs/phase-15-customer-surface-security-audit.md). Only
    // get_properties() is implemented (the one RPC app.js actually calls);
    // any other function name mimics PostgREST's real "function not
    // found" shape (PGRST202) so app.js's own missingFn fallback-detection
    // logic can be exercised too if a future test needs it.
    async rpc(fnName, args) {
      // SaaS hardening: self-service account deletion (migration 015).
      // ?rpcmissing=1 mimics a deployment where 015 has not been applied.
      if (fnName === "delete_my_account") {
        window.__stubDeleteCalls = (window.__stubDeleteCalls || 0) + 1;
        if (new URLSearchParams(location.search).get("rpcmissing") === "1") {
          return { data: null, error: { message: "Could not find the function public.delete_my_account without parameters in the schema cache", code: "PGRST202" } };
        }
        return { data: null, error: null };
      }
      if (fnName === "get_properties") {
        const pState = args && args.p_state;
        // This suite mostly loads index.html (data-state="FL", see
        // PAGE_STATE in app.js) and FIXTURE_PROPERTIES has never carried an
        // explicit `state` field for its original rows - they're implicitly
        // FL (`p.state || "FL"` below), the same assumption the pre-RPC
        // `sb.from("properties").select("*")` fallback made for every one
        // of this file's existing DOM assertions. Filtering by state here
        // (rather than returning the whole array unfiltered) keeps every
        // pre-existing FL assertion in run_test.mjs byte-identical while
        // also correctly serving the one `state: "TX"` row (Phase 34,
        // fixture id "ptx1") to a real p_state:"TX" request, the way the
        // real get_properties() RPC's `where state = p_state` does.
        return { data: FIXTURE_PROPERTIES.filter(p => (p.state || "FL") === pState), error: null };
      }
      return { data: null, error: { message: `stub: unhandled rpc "${fnName}"`, code: "PGRST202" } };
    }
  };
}
