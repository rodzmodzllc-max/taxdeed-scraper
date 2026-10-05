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
    // Acquisition-path sprint (2026-10-01): p3 carries a verified county-level
    // phone/e-mail process from a FIXTURE evidence page (the "complete" HOW TO
    // ACQUIRE state). The acquisition path is enrichment: the not-yet-verified
    // state is ptx6 (Liberty TX), which stays published.
    purchase_path_type: "phone_mail", purchase_path_scope: "source", purchase_path_observed_on: "2026-09-30",
    purchase_path_evidence: "Clerk's Lands Available page: call or e-mail the Tax Deed department for the current amount (fixture)",
    otc_provenance: { harvester: "fl_laft_pioneer", source_id: "fl_laft_pioneer", list_url: "https://x", retrieved_at: "2026-08-11T06:00:00Z", purchase_path_mode: "phone_mail",
      purchase_amount: "source column/field: OPENING_BID", list_as_of: "stated by the list document/filename",
      purchase_url: "phone_mail (source-scope): Clerk's Lands Available page (fixture)",
      status_terminology: "active = on the county list this run; closed = absent from a COMPLETE/EMPTY harvest",
      inventory_type: "harvester constant (F.S. 197.502(7) Lands Available list)",
      purchase_evidence_url: "https://www.bayclerk.example.gov/tax-deeds/lands-available", purchase_evidence_type: "county_page",
      purchase_evidence_title: "Lands Available for Taxes (fixture)", purchase_path_observed_on: "2026-09-30",
      source_match: { identifier: "case_no", value: "C-1", parcel: "333", source: "https://x/list.pdf", read_at: "2026-08-11T06:00:00Z",
                      basis: "row read from the source list / document by the harvester; identity as the sync upserts it" },
      acquisition: { mode: "phone", channels: ["email", "phone"], phone: "(850) 555-0100", email: "taxdeeds@bayclerk.example.gov",
                     office: "Clerk of Court - Tax Deed Department (fixture)", observed_on: "2026-09-30",
                     evidence_url: "https://www.bayclerk.example.gov/tax-deeds/lands-available",
                     steps: ["Call or e-mail the Tax Deed Department for the current purchase amount", "Pay the quoted amount at the Clerk's office"] } },
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
    inventory_type: "STRUCK_OFF_HELD_IN_TRUST", source_authority: "VENDOR_COUNSEL", source_id: "tx_lgbs", document_url: null, purchase_amount: null, purchase_amount_kind: null,
    // Acquisition-path sprint (2026-10-01): what scripts/apply_acquisition_paths.py
    // writes for a Texas row - the registry listing, the identity match and the
    // verified COUNTY-level process (FIXTURE page on an example.gov domain).
    list_url: "https://taxsales.lgbs.com/", purchase_url: "https://www.galveston.example.gov/sheriff-sale-information", purchase_url_kind: "purchase_instructions",
    purchase_path_type: "county_instructions", purchase_path_scope: "source", purchase_path_observed_on: "2026-10-01",
    purchase_path_evidence: "County Tax Assessor-Collector's Sheriff Sale Information page: struck-off property is re-offered at future Sheriff Sales (fixture)",
    otc_provenance: { source_id: "tx_lgbs", harvester: "tx_lgbs", list_url: "https://taxsales.lgbs.com/", purchase_path_mode: "online_instructions",
      purchase_evidence_url: "https://www.galveston.example.gov/sheriff-sale-information", purchase_evidence_type: "county_page",
      purchase_evidence_title: "Sheriff Sale Information (fixture)", purchase_path_observed_on: "2026-10-01",
      source_match: { identifier: "case_no", value: "129500040015000", parcel: "23-TX-0644", source: "https://taxsales.lgbs.com/", read_at: "2026-09-23",
                      basis: "row read from the source listing by the harvester (tx_lgbs); identity as the sync upserts it; last successful source read 2026-09-23" },
      acquisition: { mode: "multi_step", channels: ["instructions", "phone"], phone: "(409) 555-0101", office: "Tax Assessor-Collector (fixture)", observed_on: "2026-10-01",
                     evidence_url: "https://www.galveston.example.gov/sheriff-sale-information",
                     steps: ["Watch for the property on a future Sheriff's resale", "Submit the county's bid form with the deposit it names", "Bid at the Sheriff's sale"] } } },
  { id: "ptx4", source: "auction", state: "TX", county: "Llano", case_no: "R000020419", parcel: "23101 (6)", address: "LOT 6 SUNRISE BEACH, Llano, TX", bid: 3942.08, min_bid: 3942.08, status: "active", sale_date: futureDate(-3), harvester_source: "tx_realauction", url_auction: txSaleUrl("llano.texas.sheriffsaleauctions.com", futureDate(-3)), url_auction_kind: "sale", updated_at: "2026-09-24T00:00:00Z" },
  { id: "ptx5", source: "auction", state: "TX", county: "Atascosa", case_no: "17854", parcel: "20-11-0957-CVA (1)", address: "200 Oak St, Pleasanton, TX", bid: 1200, min_bid: 1200, status: "active", sale_date: futureDate(12), harvester_source: "tx_realauction", updated_at: "2026-09-24T00:00:00Z" },
  { id: "ptx6", source: "laft", state: "TX", county: "Liberty", case_no: "000016000361003", parcel: "21DC-TX-00185", address: "TRACT 3, Liberty, TX", bid: 900, min_bid: 900, status: "active", sale_date: null, harvester_source: "tx_lgbs", tx_sale_status: "Available for Future Sale", updated_at: "2026-09-23T00:00:00Z",
    // As scripts/lgbs_available_refresh.py writes it: a fill from a REVIEW_REQUIRED source.
    field_provenance: { legal_desc: { source: "vendor_listing", source_id: "tx_lgbs", field: "legal_description", governance: "REVIEW_REQUIRED",
      dataset: "taxsales.lgbs.com property_sales API", matched_on: "county + account number (case_no), exact", recorded_at: "2026-10-01T12:00:00Z" } },
    inventory_type: "FUTURE_RESALE", source_authority: "VENDOR_COUNSEL", source_id: "tx_lgbs", document_url: null, purchase_url: null, purchase_amount: null, purchase_amount_kind: null,
    // Acquisition-path sprint (2026-10-01): a Texas county with NO verified
    // acquisition record (Liberty) - exactly what scripts/apply_acquisition_paths.py
    // writes then: the registry listing and the identity match, no path. Still
    // published; its page reads "Acquisition path: Not yet verified".
    list_url: "https://taxsales.lgbs.com/",
    otc_provenance: { source_id: "tx_lgbs", list_url: "https://taxsales.lgbs.com/",
      source_match: { identifier: "case_no", value: "000016000361003", source: "https://taxsales.lgbs.com/", read_at: "2026-09-23" } } },
  // 2026-09-30 (state-expansion sprint): a Louisiana row in the shape
  // scripts/sync_state_inventory.py writes - East Baton Rouge's DATED
  // adjudicated-property list (list_as_of = the dataset's own rows-updated
  // date), no price, no purchase path. Values are SYNTHETIC.
  { id: "pla1", source: "laft", state: "LA", county: "East Baton Rouge", case_no: "012-3456-7", parcel: "012-3456-7", address: "10 FIXTURE AVE", bid: 0, status: "active", sale_date: null, lien_level: "unscreened", lien_note: "",
    harvester_source: "la_ebr_adjudicated", source_id: "la_ebr_adjudicated", source_authority: "GOVERNMENT_DIRECT", inventory_type: "ADJUDICATED_PROPERTY",
    list_url: "https://data.brla.gov/Housing-and-Development/Adjudicated-Property/a4h4-zi7e", document_url: "https://data.brla.gov/api/views/a4h4-zi7e/rows.csv?accessType=DOWNLOAD",
    url_auction: "https://data.brla.gov/Housing-and-Development/Adjudicated-Property/a4h4-zi7e", url_auction_kind: "county",
    purchase_url: null, purchase_amount: null, purchase_amount_kind: "NOT_PUBLISHED", list_as_of: "2024-02-27", source_published_at: "2024-02-27T18:54:28Z",
    assessed: 2500, market: 25000, tax_year: "2023", latitude: 30.4515, longitude: -91.1871, publication_status: "APPROVED", ledger_type: "buy", updated_at: "2026-09-30T12:00:00Z",
    purchase_path_type: "in_person", purchase_path_scope: "source", purchase_path_observed_on: "2026-10-01",
    purchase_path_evidence: "The Parish Attorney's office handles sales of adjudicated property (fixture)",
    otc_provenance: { source_id: "la_ebr_adjudicated", purchase_evidence_url: "https://www.brla.gov/Faq.aspx?QID=286", purchase_path_observed_on: "2026-10-01",
      source_match: { identifier: "case_no", value: "012-3456-7", source: "https://data.brla.gov/api/views/a4h4-zi7e/rows.csv?accessType=DOWNLOAD", read_at: "2026-10-01T08:50:04Z",
                      basis: "row read from the source list / document by the harvester; identity as the sync upserts it" },
      acquisition: { mode: "in_person", channels: ["in_person"], office: "Office of the Parish Attorney (fixture)", observed_on: "2026-10-01", evidence_url: "https://www.brla.gov/Faq.aspx?QID=286" } } },
  // 2026-10-01 (property-enrichment sprint): a second East Baton Rouge row in the
  // shape the LA lifecycle + enrichment write once the Parish Attorney's process
  // (data/purchase_path_evidence.csv) and the EBR Tax Parcel land value
  // (la_ebr_tax_parcels, Public Domain) apply. SYNTHETIC values.
  { id: "pla2", source: "laft", state: "LA", county: "East Baton Rouge", case_no: "012-3456-8", parcel: "012-3456-8", address: "12 FIXTURE AVE", bid: 0, status: "active", sale_date: null, lien_level: "unscreened", lien_note: "",
    harvester_source: "la_ebr_adjudicated", source_id: "la_ebr_adjudicated", source_authority: "GOVERNMENT_DIRECT", inventory_type: "ADJUDICATED_PROPERTY",
    list_url: "https://data.brla.gov/Housing-and-Development/Adjudicated-Property/a4h4-zi7e", url_auction: "https://data.brla.gov/Housing-and-Development/Adjudicated-Property/a4h4-zi7e", url_auction_kind: "county",
    purchase_url: "https://www.brla.gov/455/Adjudicated-Property", purchase_url_kind: "purchase_instructions", purchase_amount: null, purchase_amount_kind: "NOT_PUBLISHED", list_as_of: "2024-02-27",
    assessed: 2600, market: 26000, land_value: 9000, tax_year: "2023", latitude: 30.4521, longitude: -91.1875,
    purchase_path_type: "county_instructions", purchase_path_scope: "source", purchase_path_observed_on: "2026-10-01",
    purchase_path_evidence: "The Parish Attorney's Adjudicated Property page and FAQ say the Office of the Parish Attorney handles sales of adjudicated property",
    otc_provenance: { source_match: { identifier: "case_no", value: "012-3456-8", source: "https://data.brla.gov/api/views/a4h4-zi7e/rows.csv?accessType=DOWNLOAD", read_at: "2026-10-01T08:50:04Z",
                                      basis: "row read from the source list / document by the harvester; identity as the sync upserts it" },
      acquisition: { mode: "multi_step", channels: [], office: "Office of the Parish Attorney, City of Baton Rouge / Parish of East Baton Rouge",
      evidence_url: "https://www.brla.gov/Faq.aspx?QID=286", observed_on: "2026-10-01",
      steps: ["Confirm with the East Baton Rouge Parish Sheriff that the property remains adjudicated (properties are redeemed during the year)",
              "Request to purchase directly through the Office of the Parish Attorney, using its Request to Purchase form (see the Parish Attorney's Memorandum)"] } },
    field_provenance: { land_value: { source: "statewide_parcel", source_id: "la_ebr_tax_parcels", dataset: "Tax Parcel (data.brla.gov ei2c-krsr)", agency: "East Baton Rouge Parish Assessor (Open Data BR)",
      matched_id_field: "assessment_num", matched_row_column: "parcel", matched_parcel_id: "012-3456-8", recorded_at: "2026-10-01T12:00:00Z" } },
    publication_status: "APPROVED", ledger_type: "buy", updated_at: "2026-10-01T12:00:00Z" },
  // 2026-10-02 (collection vs customer publication): AVAILABLE rows from
  // sources still awaiting customer-publication review, in the shape the sync
  // now writes them (publication_status UNREVIEWED, the source's own program
  // wording in inventory_status_raw). Admins - and every user in
  // publicationMode "preview" - see them labelled; customers in the default
  // enforced mode do not. Values are SYNTHETIC.
  { id: "pmi_dlba1", source: "laft", state: "MI", county: "Wayne", case_no: "99000001.", parcel: "99000001.", address: "1 FIXTURE LOT ST", bid: 0, status: "active", sale_date: null, lien_level: "unscreened", lien_note: "",
    harvester_source: "mi_detroit_landbank_lots", source_id: "mi_detroit_landbank_lots", source_authority: "GOVERNMENT_DIRECT", inventory_type: "POST_SALE",
    list_url: "https://www.arcgis.com/home/item.html?id=848bc665295f4ca9b1e25068ffa88ab0", url_auction: "https://www.arcgis.com/home/item.html?id=848bc665295f4ca9b1e25068ffa88ab0", url_auction_kind: "county",
    purchase_amount: null, purchase_amount_kind: "NOT_PUBLISHED", inventory_status_raw: "Side Lot For Sale", latitude: 42.36, longitude: -83.08,
    last_seen_at: "2026-10-02T12:00:00Z", first_seen_at: "2026-10-02T12:00:00Z", publication_status: "UNREVIEWED", ledger_type: "buy", updated_at: "2026-10-02T12:00:00Z",
    otc_provenance: { source_id: "mi_detroit_landbank_lots", source_match: { identifier: "case_no", value: "99000001.", source: "https://services2.arcgis.com/qvkbeam7Wirps6zC/arcgis/rest/services/DLBA_Owned_Properties/FeatureServer/0", read_at: "2026-10-02T12:00:00Z", basis: "row read from the source list / document by the harvester; identity as the sync upserts it" } } },
  { id: "pmi_dlba2", source: "laft", state: "MI", county: "Wayne", case_no: "99000002.", parcel: "99000002.", address: "2 FIXTURE PROGRAM AVE", bid: 0, status: "active", sale_date: null, lien_level: "unscreened", lien_note: "",
    harvester_source: "mi_detroit_landbank_programs", source_id: "mi_detroit_landbank_programs", source_authority: "GOVERNMENT_DIRECT", inventory_type: "POST_SALE",
    list_url: "https://www.arcgis.com/home/item.html?id=e0c4f46a09b9405cb18837e66e85c622", url_auction: "https://www.arcgis.com/home/item.html?id=e0c4f46a09b9405cb18837e66e85c622", url_auction_kind: "county",
    purchase_amount: null, purchase_amount_kind: "NOT_PUBLISHED", inventory_status_raw: "Own It Now",
    last_seen_at: "2026-10-02T12:00:00Z", publication_status: "UNREVIEWED", ledger_type: "buy", updated_at: "2026-10-02T12:00:00Z" },
  // Detroit customer subset (2026-10-03): four SYNTHETIC rows with the DLBA's own
  // offered-structure status. By the subset rule (harvesters/otc/detroit_subset.py)
  // pmi_dlbs1/2 (99000102. / 99000105.) are IN the ~50% subset and pmi_dlbs3/4
  // (99000101. / 99000103.) are not; pmi_dlba1 (a Side Lot) and pmi_dlba2 (a program
  // record) carry no structure indicator.
  { id: "pmi_dlbs1", source: "laft", state: "MI", county: "Wayne", case_no: "99000102.", parcel: "99000102.", address: "102 FIXTURE HOUSE AVE", bid: 0, status: "active", sale_date: null, lien_level: "unscreened", lien_note: "",
    harvester_source: "mi_detroit_landbank_lots", source_id: "mi_detroit_landbank_lots", source_authority: "GOVERNMENT_DIRECT", inventory_type: "POST_SALE",
    list_url: "https://www.arcgis.com/home/item.html?id=848bc665295f4ca9b1e25068ffa88ab0", url_auction: "https://www.arcgis.com/home/item.html?id=848bc665295f4ca9b1e25068ffa88ab0", url_auction_kind: "county",
    purchase_amount: null, purchase_amount_kind: "NOT_PUBLISHED", inventory_status_raw: "Marketed Structure For Sale", latitude: 42.37, longitude: -83.1,
    last_seen_at: "2026-10-03T12:00:00Z", publication_status: "UNREVIEWED", ledger_type: "buy", updated_at: "2026-10-03T12:00:00Z" },
  { id: "pmi_dlbs2", source: "laft", state: "MI", county: "Wayne", case_no: "99000105.", parcel: "99000105.", address: "105 FIXTURE HOUSE AVE", bid: 0, status: "active", sale_date: null, lien_level: "unscreened", lien_note: "",
    harvester_source: "mi_detroit_landbank_lots", source_id: "mi_detroit_landbank_lots", source_authority: "GOVERNMENT_DIRECT", inventory_type: "POST_SALE",
    list_url: "https://www.arcgis.com/home/item.html?id=848bc665295f4ca9b1e25068ffa88ab0", url_auction: "https://www.arcgis.com/home/item.html?id=848bc665295f4ca9b1e25068ffa88ab0", url_auction_kind: "county",
    purchase_amount: null, purchase_amount_kind: "NOT_PUBLISHED", inventory_status_raw: "Marketed Structure For Sale", latitude: 42.38, longitude: -83.12,
    last_seen_at: "2026-10-03T12:00:00Z", publication_status: "UNREVIEWED", ledger_type: "buy", updated_at: "2026-10-03T12:00:00Z" },
  { id: "pmi_dlbs3", source: "laft", state: "MI", county: "Wayne", case_no: "99000101.", parcel: "99000101.", address: "101 FIXTURE HOUSE AVE", bid: 0, status: "active", sale_date: null, lien_level: "unscreened", lien_note: "",
    harvester_source: "mi_detroit_landbank_lots", source_id: "mi_detroit_landbank_lots", source_authority: "GOVERNMENT_DIRECT", inventory_type: "POST_SALE",
    list_url: "https://www.arcgis.com/home/item.html?id=848bc665295f4ca9b1e25068ffa88ab0", url_auction: "https://www.arcgis.com/home/item.html?id=848bc665295f4ca9b1e25068ffa88ab0", url_auction_kind: "county",
    purchase_amount: null, purchase_amount_kind: "NOT_PUBLISHED", inventory_status_raw: "Marketed Structure For Sale", latitude: 42.39, longitude: -83.05,
    last_seen_at: "2026-10-03T12:00:00Z", publication_status: "UNREVIEWED", ledger_type: "buy", updated_at: "2026-10-03T12:00:00Z" },
  { id: "pmi_dlbs4", source: "laft", state: "MI", county: "Wayne", case_no: "99000103.", parcel: "99000103.", address: "103 FIXTURE HOUSE AVE", bid: 0, status: "active", sale_date: null, lien_level: "unscreened", lien_note: "",
    harvester_source: "mi_detroit_landbank_lots", source_id: "mi_detroit_landbank_lots", source_authority: "GOVERNMENT_DIRECT", inventory_type: "POST_SALE",
    list_url: "https://www.arcgis.com/home/item.html?id=848bc665295f4ca9b1e25068ffa88ab0", url_auction: "https://www.arcgis.com/home/item.html?id=848bc665295f4ca9b1e25068ffa88ab0", url_auction_kind: "county",
    purchase_amount: null, purchase_amount_kind: "NOT_PUBLISHED", inventory_status_raw: "Marketed Structure For Sale", latitude: 42.35, longitude: -83.14,
    last_seen_at: "2026-10-03T12:00:00Z", publication_status: "UNREVIEWED", ledger_type: "buy", updated_at: "2026-10-03T12:00:00Z" },
  { id: "psc_horry1", source: "laft", state: "SC", county: "Horry", case_no: "99999999901", parcel: "99999999901", address: null, legal_desc: "FIXTURE LOT 9", bid: 1500, status: "active", sale_date: null, lien_level: "unscreened", lien_note: "",
    harvester_source: "sc_horry_forfeited_land", source_id: "sc_horry_forfeited_land", source_authority: "GOVERNMENT_DIRECT", inventory_type: "POST_SALE",
    list_url: "https://horrycountysc.gov/boards-and-commissions/forfeited-land-commission/", url_auction: "https://horrycountysc.gov/boards-and-commissions/forfeited-land-commission/", url_auction_kind: "county",
    purchase_url: "https://horrycountysc.gov/media/sinbmsz5/horrycountyflcguidelines.pdf", purchase_url_kind: "bid_form", purchase_amount: 1500, purchase_amount_kind: "OPENING_BID",
    // The typed path the engine writes after the 2026-10-03 fix: the county's one
    // FLC bid-form PDF is a SOURCE-level application download, never a
    // direct_property_url. No otc_provenance.acquisition on purpose: the
    // frontend's type-only fallback must also say "bid", never "online".
    purchase_path_type: "application_download", purchase_path_scope: "source", purchase_path_observed_on: "2026-10-02",
    purchase_path_evidence: "source-level bid_form page verified for this source (data/county_source_registry.csv, last_checked 2026-10-02)",
    last_seen_at: "2026-10-02T12:00:00Z", publication_status: "UNREVIEWED", ledger_type: "buy", updated_at: "2026-10-02T12:00:00Z" },
  // 2026-09-30 (six-state expansion): rows in the shapes scripts/harvest_expansion.py
  // + sync_state_inventory.py write. Values are SYNTHETIC.
  { id: "pmi1", source: "auction", state: "MI", county: "Eaton", case_no: "100-200-300-400-50", parcel: "100-200-300-400-50", address: "100 FIXTURE ST", bid: 4200, min_bid: 4200, status: "active", sale_date: null, lien_level: "unscreened", lien_note: "",
    harvester_source: "mi_eaton_treasurer_sale", source_id: "mi_eaton_treasurer_sale", source_authority: "GOVERNMENT_DIRECT",
    list_url: "https://www.arcgis.com/home/item.html?id=5b973732a9e84fdd94fa225f8160650d", url_auction: "https://www.arcgis.com/home/item.html?id=5b973732a9e84fdd94fa225f8160650d", url_auction_kind: "county",
    legal_desc: "FIXTURE LOT 1", acreage: 0.23, land_use: "Residential", assessed: 41200, taxable_value: 38100, publication_status: "APPROVED", ledger_type: "auctions", updated_at: "2026-09-30T12:00:00Z" },
  // Release visibility gate (2026-10-02): a York SC auction row in the shape the
  // expansion runner + purchase-path engine write - the county's published sale
  // process (in person, steps, office phone) at source scope. Values are SYNTHETIC.
  { id: "psc1", source: "auction", state: "SC", county: "York", case_no: "FIXTURE-SC-1", parcel: "0000000001", address: "1 FIXTURE LN", bid: 0, status: "active", sale_date: null, lien_level: "unscreened", lien_note: "",
    harvester_source: "sc_york_tax_sale", source_id: "sc_york_tax_sale", source_authority: "GOVERNMENT_DIRECT",
    list_url: "https://www.yorkcountysc.gov/216/Tax-Collection", url_auction: "https://www.yorkcountysc.gov/216/Tax-Collection", url_auction_kind: "county",
    purchase_path_type: "in_person", purchase_path_scope: "source", purchase_path_observed_on: "2026-10-01",
    purchase_path_evidence: "FIXTURE: the county fact sheet says the sale is held in person",
    otc_provenance: { purchase_evidence_url: "https://www.yorkcountysc.gov/DocumentCenter/View/5241/Tax-Sale-Fact-Sheet", purchase_evidence_title: "Tax Sale Fact Sheet and Disclaimer (York County, SC)",
      acquisition: { mode: "in_person", channels: ["in_person", "phone"], office: "York County Tax Collector", phone: "803-000-0000", observed_on: "2026-10-01",
        steps: ["FIXTURE: register as a bidder before the sale", "FIXTURE: bid in person at the published location"] } },
    publication_status: "APPROVED", ledger_type: "auctions", updated_at: "2026-10-01T12:00:00Z" },
  { id: "pco1", source: "certificate", state: "CO", county: "Morgan", case_no: "2023-00123", certificate_no: "2023-00123", parcel: "R012345", address: "1 FIXTURE RD", bid: 1234.56, status: "active", sale_date: null, lien_level: "unscreened", lien_note: "",
    harvester_source: "co_morgan_county_held_certificates", source_id: "co_morgan_county_held_certificates", source_authority: "GOVERNMENT_DIRECT",
    list_url: "https://morgancounty.colorado.gov/county-held-tax-lien-sale-certificates", url_auction: "https://morgancounty.colorado.gov/county-held-tax-lien-sale-certificates", url_auction_kind: "county",
    owner_name: "FIXTURE OWNER", legal_desc: "FIXTURE SUBD BLK 2", purchase_amount: 1234.56, purchase_amount_kind: "FIXED_PURCHASE_PRICE", list_as_of: "2026-10-31",
    market: 150000, taxable_value: 10500, acreage: 2.5, latitude: 40.255, longitude: -103.795,
    purchase_path_type: "quoted_amount", purchase_path_scope: "source", purchase_path_observed_on: "2026-09-30",
    purchase_path_evidence: "The Treasurer's county-held certificate page says the listed certificates may be purchased from Morgan County for the amount shown (data/purchase_path_evidence_expansion.csv, observed 2026-09-30)",
    otc_provenance: { acquisition: { mode: "multi_step", channels: [], office: "Morgan County Treasurer", evidence_url: "https://morgancounty.colorado.gov/county-held-tax-lien-sale-certificates", observed_on: "2026-09-30",
      steps: ["Review the county-held tax lien sale certificate list", "Purchase the certificate from the Morgan County Treasurer for the amount shown", "The amount shown is good to the date in the amount column's header"] } },
    field_provenance: { market: { source: "statewide_parcel", source_id: "co_oit_public_parcels", dataset: "Colorado Public Parcels (Colorado_Public_Parcel_Composite)", matched_id_field: "account", matched_parcel_id: "R012345", recorded_at: "2026-09-30T12:00:00Z" } },
    publication_status: "APPROVED", ledger_type: "lien", updated_at: "2026-09-30T12:00:00Z" },
  // 2026-10-01 (five-state sprint): a Douglas County CO county-held lien (CC BY-SA 4.0
  // open data) in the shape harvest_expansion.py + sync_state_inventory.py write. SYNTHETIC.
  { id: "pco2", source: "certificate", state: "CO", county: "Douglas", case_no: "2023-10001", certificate_no: "2023-10001", parcel: "R0000001", address: "Parcel R0000001", bid: 1234.56, status: "active", sale_date: null, issued_date: "2023-11-02", tax_year: "2022", lien_level: "unscreened", lien_note: "",
    harvester_source: "co_douglas_county_held_liens", source_id: "co_douglas_county_held_liens", source_authority: "GOVERNMENT_DIRECT",
    list_url: "https://www.arcgis.com/home/item.html?id=950fd2c3a9bf4e0e92fa4a64f1859fec", url_auction: "https://www.arcgis.com/home/item.html?id=950fd2c3a9bf4e0e92fa4a64f1859fec", url_auction_kind: "county",
    purchase_amount: 1234.56, purchase_amount_kind: "PUBLISHED_AMOUNT_KIND_UNSPECIFIED", last_seen_at: "2026-10-01T12:00:00Z",
    inventory_status: "certificate_listed", inventory_status_basis: "LIST_PRESENCE: on the county's list of certificates purchasable from the Treasurer at the last read",
    purchase_path_type: "application_download", purchase_path_scope: "source", purchase_path_observed_on: "2026-10-01",
    purchase_path_evidence: "Douglas County's 'Request for Assignment of County-Held Tax Lien' (data/purchase_path_evidence_expansion.csv, observed 2026-10-01)",
    otc_provenance: { adapter: "arcgis", acquisition: { mode: "multi_step", channels: ["application"], office: "Douglas County Treasurer", observed_on: "2026-10-01",
      evidence_url: "https://www.douglasco.gov/documents/request-for-assignment-of-county-held.pdf/", application_url: "https://www.douglasco.gov/documents/request-for-assignment-of-county-held.pdf/",
      steps: ["Complete the county's Request for Assignment of County-Held Tax Lien", "All county-held liens on the parcel must be redeemed if the assignment is granted", "Call the Douglas County Treasurer's office for the current payoff amount"] } },
    publication_status: "APPROVED", ledger_type: "lien", updated_at: "2026-10-01T12:00:00Z" },
  // 2026-10-04 (landing ledger): an auctions-only state's row - Albany WY's tax sale list
  // publishes no sale date for the list's rows, so it is visible in the live view.
  { id: "pwy1", source: "auction", state: "WY", county: "Albany", case_no: "R0099001", parcel: "99-00-001", address: "1 FIXTURE WY ST",
    bid: 0, status: "active", sale_date: null, lien_level: "unscreened", lien_note: "",
    harvester_source: "wy_albany_tax_sale", source_id: "wy_albany_tax_sale", source_authority: "GOVERNMENT_DIRECT",
    purchase_amount: 1500, purchase_amount_kind: "PUBLISHED_AMOUNT_KIND_UNSPECIFIED", last_seen_at: "2026-10-03T12:00:00Z",
    publication_status: "APPROVED", ledger_type: "auctions", updated_at: "2026-10-03T12:00:00Z" }
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

// Customer monitoring (migration 024): saved searches, alerts, preferences,
// server change events and analytics. `?monitor=none` simulates 024 not being
// applied (every table answers PGRST205), the production state until it is.
const MONITOR_MODE = new URLSearchParams(location.search).get("monitor") || "default";
const MONITOR_DB = MONITOR_MODE === "none" ? null : {
  saved_searches: [],
  alert_preferences: [],
  user_alerts: [
    { id: 11, user_id: "u1", kind: "watched_acquisition", property_id: "p15", saved_search_id: null, change_event_id: 101, title: "Acquisition path changed", detail: "Acquisition path: not on file → phone_mail", created_at: "2026-09-30T12:00:00Z", read_at: null },
    { id: 12, user_id: "u1", kind: "saved_search_new_match", property_id: "p3", saved_search_id: null, change_event_id: 102, title: "New match: Bay lots", detail: "Newly listed in Bay County", created_at: "2026-09-29T12:00:00Z", read_at: "2026-09-29T13:00:00Z" }
  ],
  property_change_events: [
    { id: 101, property_id: "p15", state: "FL", county: "Citrus", source: "laft", kind: "acquisition_path_changed", field: "purchase_path_type", old_value: null, new_value: "phone_mail", observed_at: "2026-09-30T12:00:00Z" },
    { id: 103, property_id: "p15", state: "FL", county: "Citrus", source: "laft", kind: "removed", field: "status", old_value: "active", new_value: "closed", observed_at: "2026-08-15T06:00:00Z" },
    { id: 102, property_id: "p3", state: "FL", county: "Bay", source: "laft", kind: "opening_bid_changed", field: "opening_bid", old_value: "1800", new_value: "2000", observed_at: "2026-09-29T12:00:00Z" }
  ],
  product_events: [],
  source_observation_runs: [
    { id: 1, state: "FL", source_id: "fl_laft_html", ledger: "laft", run_at: "2026-10-01T06:00:00Z", rows_observed: 120, rows_added: 3, rows_changed: 5, rows_closed: 2, rows_reactivated: 1 },
    { id: 2, state: "FL", source_id: "fl_laft_html", ledger: "laft", run_at: "2026-09-30T06:00:00Z", rows_observed: 119, rows_added: 0, rows_changed: 1, rows_closed: 0, rows_reactivated: 0 },
    { id: 3, state: "FL", source_id: "fl_realauction", ledger: "auction", run_at: "2026-10-01T10:00:00Z", rows_observed: 812, rows_added: 14, rows_changed: 40, rows_closed: 9, rows_reactivated: 0 }
  ]
};
const MONITOR_TABLES = new Set(["saved_searches", "alert_preferences", "user_alerts", "property_change_events", "product_events", "source_observation_runs"]);
function monitorQuery(q) {
  if (MONITOR_DB === null) return { data: null, error: { message: `Could not find the table 'public.${q.table}' in the schema cache`, code: "PGRST205" } };
  const rows = MONITOR_DB[q.table];
  const matches = row => q._filters.every(([c, v, kind]) => kind === "in" ? (v || []).includes(row[c]) : row[c] === v);
  if (q._op === "insert") {
    const row = Object.assign({ user_id: "u1", created_at: new Date().toISOString() }, q._row);
    rows.push(row);
    if (q.table === "product_events") window.__stubProductEvents = (window.__stubProductEvents || []).concat([row]);
    return { data: null, error: null };
  }
  if (q._op === "upsert") { rows.length = 0; rows.push(Object.assign({ user_id: "u1" }, q._row)); window.__stubPrefUpserts = (window.__stubPrefUpserts || 0) + 1; return { data: null, error: null }; }
  if (q._op === "update") {
    rows.filter(matches).forEach(r => Object.assign(r, q._row));
    if (q.table === "user_alerts") window.__stubAlertUpdates = (window.__stubAlertUpdates || 0) + 1;
    return { data: null, error: null };
  }
  if (q._op === "delete") { const keep = rows.filter(r => !matches(r)); rows.length = 0; rows.push(...keep); return { data: null, error: null }; }
  if (q.table === "product_events") return { data: [], error: null };
  const out = rows.filter(matches).map(r => Object.assign({}, r));
  if (q.table === "source_observation_runs") out.sort((a, b) => String(b.run_at).localeCompare(String(a.run_at)));
  if (q.table === "property_change_events" || q.table === "user_alerts") out.sort((a, b) => String(b.observed_at || b.created_at).localeCompare(String(a.observed_at || a.created_at)));
  return { data: q._single ? (out[0] || null) : out, error: null };
}

class MockQuery {
  constructor(table) { this.table = table; this._op = "select"; this._filters = []; this._single = false; }
  select() { return this; }
  order() { return this; }
  eq(col, val) { this._filters.push([col, val]); return this; }
  in(col, vals) { this._filters.push([col, vals, "in"]); return this; }
  lt(col, val) { this._filters.push([col, val, "lt"]); return this; }
  range() { return this; }
  limit(n) { this._limit = n; return this; }
  // PostgREST or=(...) - only the customer publication filter the state
  // picker sends is understood (see the properties branch below).
  or(expr) { this._or = String(expr || ""); return this; }
  gte() { return this; }
  maybeSingle() { this._single = true; return this; }
  insert(row) { this._op = "insert"; this._row = row; return this; }
  update(patch) { this._op = "update"; this._row = patch; return this; }
  delete() { this._op = "delete"; return this; }
  upsert(row) { this._op = "upsert"; this._row = row; return this; }
  then(resolve) {
    let result = { data: [], error: null };
    if (MONITOR_TABLES.has(this.table)) {
      result = monitorQuery(this);
    } else if (this.table === "profiles" && STUB_AUTH) {
      // Row-level security, as the real policies: "profiles: read own row"
      // (SELECT, auth.uid() = id) and "profiles: admin full access" (ALL,
      // is_admin()). No INSERT/UPDATE policy exists for anyone else, so a
      // non-admin's update matches zero rows and changes nothing - the
      // same silent 200 PostgREST returns.
      const me = stubSessionUser();
      const users = stubUsers();
      const caller = me ? users.find(u => u.id === me.id) : null;
      const callerIsAdmin = !!(caller && caller.is_admin === true);
      const visible = users.filter(u => caller && (callerIsAdmin || u.id === caller.id));
      const matches = u => this._filters.every(([c, v]) => u[c] === v);
      if (this._op === "update") {
        const changed = callerIsAdmin ? visible.filter(matches) : [];
        changed.forEach(u => Object.assign(u, this._row));
        if (changed.length) stubSaveUsers(users);
        window.__stubProfileUpdates = (window.__stubProfileUpdates || []).concat([{ rows: changed.length }]);
        result = { data: null, error: null };
      } else {
        const rows = visible.filter(matches)
          .map(u => ({ id: u.id, email: u.email, approved: u.approved, is_admin: u.is_admin, requested_at: u.requested_at || null }));
        result = { data: this._single ? (rows[0] || null) : rows, error: null };
      }
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
    } else if (this.table === "bid_list" && BIDLIST_SEED) {
      // ?bidlist=<id>,<id>: one account's watchlist, the same rows whichever
      // state's page reads it (the table has no state column). Deletes are
      // counted so a test can prove a state switch never removes anything.
      if (this._op === "select") result = { data: BIDLIST_SEED.map(id => ({ property_id: id })), error: null };
      else if (this._op === "delete") window.__stubBidListDeletes = (window.__stubBidListDeletes || 0) + 1;
    } else if (this._op === "select") {
      const matches = row => this._filters.every(([c, v, kind]) => kind === "in" ? (v || []).includes(row[c]) : kind === "lt" ? String(row[c]) < String(v) : row[c] === v);
      if (this.table === "properties") {
        // The legacy unscoped fallback (no filters) still gets every row. A
        // filtered read - the state picker's "does this ledger have a row you
        // may see" probe - applies eq() on state (implicitly FL, as the RPC
        // does), source, the customer publication filter and the limit.
        // ?probefail=1 makes every probe fail, like a network error.
        if (!this._filters.length && !this._or) result.data = FIXTURE_PROPERTIES;
        else if (new URLSearchParams(location.search).get("probefail") === "1") result = { data: null, error: { message: "probe failed (stub)" } };
        else {
          window.__stubPropertyProbes = (window.__stubPropertyProbes || 0) + 1;
          let rows = FIXTURE_PROPERTIES.filter(r => this._filters.every(([c, v]) => (c === "state" ? (r.state || "FL") : r[c]) === v));
          if (/publication_status\.is\.null/.test(this._or || "")) rows = rows.filter(r => !r.publication_status || ["APPROVED", "APPROVED_GRANDFATHERED"].includes(r.publication_status));
          result.data = this._limit ? rows.slice(0, this._limit) : rows;
        }
      }
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

// ?bidlist=p1,ptx1 seeds the account's watchlist (see MockQuery.then).
const BIDLIST_SEED = (() => {
  const v = new URLSearchParams(location.search).get("bidlist");
  return v ? v.split(",").filter(Boolean) : null;
})();

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
//
// Sign-up (2026-09-30): signUp creates a new server user the way Supabase
// Auth + the handle_new_user trigger do - a profile with approved = false and
// is_admin = false, whatever metadata the caller sends. An admin (and only an
// admin) can read other users' rows and approve them. So that a sign-up in
// one tab is visible to the admin in another tab of the same browser context
// (the way one database serves every client), the user table is persisted
// under STUB_DB_KEY. That key stands for the server's database: the
// application never reads it, and the tamper checks never touch it.
// ?signupdisabled=1 makes signUp answer the way a project with "Allow new
// users to sign up" turned off does.
const STUB_AUTH = new URLSearchParams(location.search).get("stubauth") === "1";
const STUB_SIGNUP_DISABLED = new URLSearchParams(location.search).get("signupdisabled") === "1";
// ?emaillimit=1: Supabase's built-in e-mail sender is over its hourly limit -
// signUp / resend / resetPasswordForEmail answer 429 and nothing is created.
// ?unconfirmed=1: signInWithPassword answers "Email not confirmed".
const STUB_EMAIL_LIMIT = new URLSearchParams(location.search).get("emaillimit") === "1";
const STUB_UNCONFIRMED = new URLSearchParams(location.search).get("unconfirmed") === "1";
const STUB_RATE_ERR = { message: "email rate limit exceeded", status: 429, code: "over_email_send_rate_limit" };
const STUB_SESSION_KEY = "stub-auth-session";
const STUB_DB_KEY = "stub-server-db";
const STUB_SERVER_USERS = [
  { id: "n1", email: "normal@example.com", password: "fixture-normal-pass", approved: true, is_admin: false },
  { id: "a1", email: "admin@example.com", password: "fixture-admin-pass", approved: true, is_admin: true }
];
function stubUsers() {
  try { const saved = JSON.parse(localStorage.getItem(STUB_DB_KEY)); if (Array.isArray(saved)) return saved; } catch { /* seed below */ }
  return STUB_SERVER_USERS.map(u => ({ ...u }));
}
function stubSaveUsers(list) { try { localStorage.setItem(STUB_DB_KEY, JSON.stringify(list)); } catch { /* ignore */ } }
const stubListeners = [];
function stubSessionUser() {
  let id = null;
  try { id = sessionStorage.getItem(STUB_SESSION_KEY); } catch { id = null; }
  const u = stubUsers().find(x => x.id === id);
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
        if (STUB_AUTH && STUB_UNCONFIRMED) return { data: { user: null, session: null }, error: { message: "Email not confirmed", status: 400, code: "email_not_confirmed" } };
        if (STUB_AUTH) {
          const u = stubUsers().find(x => creds && x.email === creds.email && x.password === creds.password);
          if (!u) return { data: { user: null, session: null }, error: { message: "Invalid login credentials", status: 400 } };
          sessionStorage.setItem(STUB_SESSION_KEY, u.id);
          const user = { id: u.id, email: u.email };
          stubEmit("SIGNED_IN", user);
          return { data: { user, session: { user } }, error: null };
        }
        return { error: null };
      },
      async signUp(creds) {
        const email = creds && creds.email;
        if (STUB_AUTH) {
          if (STUB_SIGNUP_DISABLED) return { data: { user: null, session: null }, error: { message: "Signups not allowed for this instance", status: 422 } };
          if (STUB_EMAIL_LIMIT) return { data: { user: null, session: null }, error: STUB_RATE_ERR };
          const users = stubUsers();
          if (!email || !creds.password || users.some(x => x.email === email)) {
            return { data: { user: null, session: null }, error: { message: "User already registered", status: 422 } };
          }
          // handle_new_user(): (id, email) only - approved and is_admin take
          // the column defaults (false), never anything from the metadata.
          const created = { id: "s" + (users.length + 1), email, password: creds.password, approved: false, is_admin: false, requested_at: new Date().toISOString() };
          users.push(created);
          stubSaveUsers(users);
          sessionStorage.setItem(STUB_SESSION_KEY, created.id);
          const user = { id: created.id, email };
          stubEmit("SIGNED_IN", user);
          return { data: { user, session: { user } }, error: null };
        }
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
      async resend(args) {
        window.__stubResendCalls = (window.__stubResendCalls || []).concat([args]);
        if (STUB_EMAIL_LIMIT) return { data: null, error: STUB_RATE_ERR };
        return { data: {}, error: null };
      },
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
    // Edge Functions (2026-10-04): self-signup creates the account server-side,
    // already confirmed, with no e-mail. ?selfsignup=1 deploys it in the stub
    // (STUB_AUTH: a real stub server user, approved = false, no session -
    // the app then signs in); ?selfsignup=bad answers a validation refusal.
    // Without the flag the function is "not deployed" (404) and the app falls
    // back to auth.signUp, which is what every older sign-up check exercises.
    functions: {
      async invoke(name, opts) {
        // Paid beta: billing-checkout / billing-portal. ?billingfn=ok answers
        // with a same-document URL (the test reads window.__tdwBillingRedirects
        // - the page never leaves); ?billingfn=down answers 503 not configured.
        if (name === "billing-checkout" || name === "billing-portal") {
          const bf = new URLSearchParams(location.search).get("billingfn");
          window.__stubBillingCalls = (window.__stubBillingCalls || []).concat([{ name, fields: Object.keys((opts && opts.body) || {}).sort() }]);
          if (bf === "ok") return { data: { url: "#stub-stripe-" + (name === "billing-checkout" ? "checkout" : "portal") }, error: null };
          return { data: null, error: { name: "FunctionsHttpError", message: "Edge Function returned a non-2xx status code",
            context: { status: 503, json: async () => ({ error: "billing_not_configured", message: "Subscriptions are not open yet." }) } } };
        }
        const mode = new URLSearchParams(location.search).get("selfsignup");
        const body = (opts && opts.body) || {};
        window.__stubFnCalls = (window.__stubFnCalls || []).concat([{ name, email: body.email, fields: Object.keys(body).sort() }]);
        const res = (status, json) => ({ data: null, error: { name: "FunctionsHttpError", message: "Edge Function returned a non-2xx status code", context: { status, json: async () => json } } });
        if (name !== "self-signup" || !mode) return res(404, {});
        if (mode === "bad") return res(400, { error: "weak_password", message: "Please choose a password of at least 8 characters." });
        const users = stubUsers();
        if (users.some(x => x.email === body.email)) return res(409, { error: "already_registered", message: "An account with this email already exists. Choose “Already have an account? Sign in”, or “Forgot password?” to set a new password." });
        users.push({ id: "s" + (users.length + 1), email: body.email, password: body.password, approved: false, is_admin: false, requested_at: new Date().toISOString() });
        stubSaveUsers(users);
        return { data: { ok: true }, error: null };
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
      if (fnName === "product_usage_summary") {
        if (MONITOR_DB === null) return { data: null, error: { message: "Could not find the function public.product_usage_summary(p_days) in the schema cache", code: "PGRST202" } };
        const counts = {};
        MONITOR_DB.product_events.forEach(e => { counts[e.event] = (counts[e.event] || 0) + 1; });
        return { data: Object.entries(counts).map(([event, events]) => ({ event, events, users: 1, first_at: null, last_at: null })), error: null };
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
        // Customer-value sprint: mimic the real RPC's ledger filter, ORDER BY,
        // limit/offset AND PostgREST's max-rows cap (?maxrows=N, default
        // 1000) so the frontend's paging is exercised - a single call can
        // never return more than the cap, exactly as in production.
        const LEDGER_FOR_SOURCE = { auction: "auctions", laft: "buy", certificate: "lien" };
        const cap = Number(new URLSearchParams(location.search).get("maxrows")) || 1000;
        window.__stubGetPropertiesCalls = (window.__stubGetPropertiesCalls || 0) + 1;
        // ?emptystate=1: a registered state that currently has no rows at all.
        const EMPTY_STATE = new URLSearchParams(location.search).get("emptystate") === "1";
        // ?bigcounty=N (2026-10-02 scale regression): N SYNTHETIC Available rows in
        // Wayne MI, shaped like the Detroit Land Bank sync rows, every one
        // geocoded inside the county - the List and Map must page / cluster
        // them, never build N cards or N pins at once.
        const BIG = Number(new URLSearchParams(location.search).get("bigcounty")) || 0;
        if (BIG && !window.__stubBigRows) {
          let seed = 7;
          const rnd = () => { seed = (seed * 16807) % 2147483647; return seed / 2147483647; };
          window.__stubBigRows = Array.from({ length: BIG }, (_, i) => ({
            id: "pbig" + i, source: "laft", state: "MI", county: "Wayne", case_no: String(90000000 + i) + ".", parcel: String(90000000 + i) + ".",
            address: (100 + i) + " SYNTHETIC ST", bid: 0, status: "active", sale_date: null, lien_level: "unscreened", lien_note: "",
            harvester_source: "mi_detroit_landbank_lots", source_id: "mi_detroit_landbank_lots", source_authority: "GOVERNMENT_DIRECT", inventory_type: "POST_SALE",
            purchase_amount: null, purchase_amount_kind: "NOT_PUBLISHED", inventory_status_raw: "Side Lot For Sale",
            latitude: 42.30 + rnd() * 0.12, longitude: -83.20 + rnd() * 0.22, publication_status: "UNREVIEWED", ledger_type: "buy",
            last_seen_at: "2026-10-02T12:00:00Z", updated_at: "2026-10-02T12:00:00Z" }));
        }
        const rows = FIXTURE_PROPERTIES.concat(pState === "MI" && window.__stubBigRows ? window.__stubBigRows : [])
          .filter(p => !EMPTY_STATE && (p.state || "FL") === pState)
          .filter(p => !args.p_ledger_type || (p.ledger_type || LEDGER_FOR_SOURCE[p.source]) === args.p_ledger_type)
          .slice().sort((a, b) => String(a.county).localeCompare(String(b.county)) || String(a.case_no).localeCompare(String(b.case_no)))
          // ?stripacq=1 (2026-10-05): pla2 in the shape production's 3,500 East
          // Baton Rouge rows had after an adapter sync replaced otc_provenance
          // wholesale - the typed path columns stay, the acquisition record is gone.
          .map(p => new URLSearchParams(location.search).get("stripacq") === "1" && p.id === "pla2"
            ? { ...p, otc_provenance: { adapter: "la_ebr_adjudicated", identifier: "case_no", amount: null, coordinates: "published" } } : p);
        const offset = Number(args.p_offset) || 0, limit = Math.min(Number(args.p_limit) || 20000, cap);
        // Load-resilience fixtures (2026-10-04):
        //   ?failpage=<ledger>:<offset>[,...]   that page always fails (statement timeout)
        //   ?flakypage=<ledger>:<offset>:<n>     that page fails n times, then succeeds
        //   ?pagedelay=<ms>                      every page takes <ms>; peak concurrency is recorded
        const qs = new URLSearchParams(location.search);
        const key = `${args.p_ledger_type}:${offset}`;
        const calls = window.__stubPageCalls = window.__stubPageCalls || {};
        calls[key] = (calls[key] || 0) + 1;
        const delay = Number(qs.get("pagedelay")) || 0;
        if (delay) {
          window.__stubInflight = (window.__stubInflight || 0) + 1;
          window.__stubPeakInflight = Math.max(window.__stubPeakInflight || 0, window.__stubInflight);
          await new Promise(r => setTimeout(r, delay));
          window.__stubInflight--;
        }
        const timeout = { data: null, error: { message: "canceling statement due to statement timeout", code: "57014" } };
        //   window.__stubHealPages = true                   failpage stops failing (a later retry succeeds)
        if (!window.__stubHealPages && (qs.get("failpage") || "").split(",").includes(key)) return timeout;
        const flaky = (qs.get("flakypage") || "").split(",").map(x => x.split(":")).find(x => `${x[0]}:${x[1]}` === key);
        if (flaky && calls[key] <= Number(flaky[2] || 1)) return timeout;
        return { data: rows.slice(offset, offset + limit), error: null };
      }
      // Paid beta (migration 027). Without ?entitlement= the function is
      // "not deployed" (PGRST202) and the app keeps the approval-record path -
      // which is what every pre-existing check exercises.
      //   ?entitlement=tester|admin|customer|manual|cancelling|grace|inactive|payment_failed|cancelled|activating
      if (fnName === "my_entitlement") {
        const mode = new URLSearchParams(location.search).get("entitlement");
        if (!mode) return { data: null, error: { message: "Could not find the function public.my_entitlement without parameters in the schema cache", code: "PGRST202" } };
        const end = new Date(Date.now() + 20 * 86400000).toISOString();
        const sub = (state, status, extra) => ({ subscription_state: state, subscription_status: status, current_period_end: end, plan_key: "monthly", cancel_at_period_end: false, last_payment_status: "paid", ...(extra || {}) });
        window.__stubEntitlementCalls = (window.__stubEntitlementCalls || 0) + 1;
        const paid = { role: "customer", state: "active", access: true, scope: "approved", reason: "Paid subscription", ...sub("active", "active") };
        const table = {
          admin: { role: "admin", state: "admin_override", access: true, scope: "all", reason: "Administrator", subscription_state: null, subscription_status: null },
          tester: { role: "tester", state: "tester_beta", access: true, scope: "preview", reason: "Approved tester (beta) - no subscription needed", subscription_state: null, subscription_status: null },
          customer: paid,
          manual: { role: "customer", state: "manual_customer", access: true, scope: "approved", reason: "Customer access granted by an administrator", subscription_state: null, subscription_status: null },
          cancelling: { ...paid, state: "cancelling", ...sub("cancelling", "active", { cancel_at_period_end: true }) },
          grace: { ...paid, state: "payment_failed_grace", reason: "Payment failed - access continues during the 7-day grace period", ...sub("payment_failed_grace", "past_due", { last_payment_status: "failed" }) },
          inactive: { role: "inactive", state: "inactive", access: false, scope: "none", reason: "No approval and no active subscription", subscription_state: null, subscription_status: null },
          payment_failed: { role: "inactive", state: "payment_failed", access: false, scope: "none", reason: "Payment failed - the grace period has ended", ...sub("payment_failed", "past_due", { last_payment_status: "failed" }) },
          cancelled: { role: "inactive", state: "cancelled", access: false, scope: "none", reason: "Subscription cancelled", ...sub("cancelled", "canceled") }
        };
        // activating: the webhook has not landed for the first two reads.
        if (mode === "activating") return { data: window.__stubEntitlementCalls > 2 ? paid : table.inactive, error: null };
        return { data: table[mode] || table.inactive, error: null };
      }
      if (fnName === "admin_billing_overview") {
        if (!new URLSearchParams(location.search).get("entitlement")) return { data: null, error: { message: "Could not find the function public.admin_billing_overview without parameters in the schema cache", code: "PGRST202" } };
        return { data: [
          { email: "admin@example.com", role: "admin", state: "admin_override", access: true, reason: "Administrator", subscription_status: null },
          { email: "tester@example.com", role: "tester", state: "tester_beta", access: true, reason: "Approved tester (beta) - no subscription needed", subscription_status: null },
          { email: "paid@example.com", role: "customer", state: "active", access: true, reason: "Paid subscription", subscription_status: "active", stripe_subscription_id: "sub_FIXTURE1", current_period_end: "2026-11-05T00:00:00Z", cancel_at_period_end: false, last_payment_status: "paid" },
          { email: "late@example.com", role: "customer", state: "payment_failed_grace", access: true, reason: "Payment failed - access continues during the 7-day grace period", subscription_status: "past_due", stripe_subscription_id: "sub_FIXTURE2", current_period_end: "2026-10-03T00:00:00Z", last_payment_status: "failed", payment_failed_at: "2026-10-03T00:00:00Z" },
          { email: "pending@example.com", role: "inactive", state: "inactive", access: false, reason: "No approval and no active subscription", subscription_status: null }
        ], error: null };
      }
      return { data: null, error: { message: `stub: unhandled rpc "${fnName}"`, code: "PGRST202" } };
    }
  };
}
