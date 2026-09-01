import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

const cfg = window.TDW_CONFIG || {};
if (!cfg.supabaseUrl || cfg.supabaseUrl.includes("YOUR-PROJECT-REF")) {
  document.body.innerHTML = '<div style="padding:2rem;font-family:sans-serif">' +
    '<h2>Not configured</h2><p>Edit <code>config.js</code> with your Supabase project URL and publishable key, then redeploy.</p></div>';
  throw new Error("config.js not filled in");
}

// supabasePublishableKey replaces the old supabaseAnonKey - same client-side
// role (safe to expose, RLS still gates every table), new sb_publishable_...
// format instead of the legacy long-lived JWT anon token.
const sb = createClient(cfg.supabaseUrl, cfg.supabasePublishableKey, {
  auth: {
    storage: window.sessionStorage,
    persistSession: true,
    autoRefreshToken: true,
    detectSessionInUrl: false
  }
});

// Internal build reference only (deploy verification, support requests) -
// deliberately not surfaced anywhere in the UI. Showing a raw "v7 -
// 2026-08-19" build tag in the header read as an unfinished/dev-mode
// artifact to end users, so the eyebrow below no longer includes it.
const BUILD = "v7 - 2026-08-19";
const IDLE_MINUTES = 5;

const DOC_STAMP_RATE = 0.007;
const RECORDING_FEE = 30;
const QUIET_TITLE_EST = 3000;
const TOP_PICK_RATIO = 12;
const SOON_DAYS = 14;
// "My Bid List" is a small, deliberately-capped shortlist (separate from the
// unlimited ♥ Favorites) for the handful of properties someone's actually
// planning to show up and bid on - the cap forces prioritization instead of
// it turning into a second copy of the whole ledger.
const BID_LIST_MAX = 10;

const GONE_HOURS_DEFAULT = 24;
const GONE_HOURS_FLAGGED = 48;
// The sync pipeline runs on a PC, not a server - nothing guarantees it ran
// today. Past this many hours since the newest row's updated_at, the "Data
// updated" line switches from a plain timestamp to a warning, since a quiet
// ledger and a dead sync both look identical otherwise.
const STALE_DATA_HOURS = 36;
// "closed" = left the county's "Auctions Waiting" feed after its sale date
// arrived, without a fresh harvest row to explain why (redeemed, canceled,
// or actually sold at the table - sync-harvest-to-supabase.ps1 can't tell
// which, since it only ever diffs against what's still listed, not against
// the county's separate "Closed or Canceled" page). Still counts as gone
// so the active badge reflects reality instead of a stale "active" pill
// sitting there long after the county's own site moved on.
const GONE_STATUSES = ["dropped", "sold", "notfound", "closed"];
const isGone = p => GONE_STATUSES.includes(p.status);

const TYPE_ORDER = ["House", "Condo", "Townhome", "Mobile/Manuf.", "Vacant Lot", "Commercial", "Unknown"];
const LIEN_ORDER = ["clean", "flag", "serious", "unscreened"];
const LIEN_LABEL = { clean: "Clear", flag: "Flag", serious: "Serious", unscreened: "Unscreened" };
const STAGES = ["", "researched", "drove by", "called clerk", "bidding", "won", "passed"];

const COUNTY_INFO = {
  "Brevard":{fmt:"Online",note:"Deposit required in advance via the auction site."},
  "Indian River":{fmt:"Online",note:"Deposit required in advance via the auction site."},
  "Osceola":{fmt:"Online",note:"Deposit required in advance via the auction site."},
  "Seminole":{fmt:"Online",note:"Deposit required in advance via the auction site."},
  "Pasco":{fmt:"Online",note:"Deposit required in advance via the auction site."},
  "Polk":{fmt:"Online",note:"Deposit required in advance via the auction site."},
  "Lee":{fmt:"Online",note:"Deposit required in advance via the auction site."},
  "Charlotte":{fmt:"Shared site with foreclosure sales - confirm you are on a TAXDEED auction."},
  "Orange":{fmt:"Online",note:"Deposit required in advance via the auction site."},
  "Palm Beach":{fmt:"Three sale dates in play - check each property's own date."},
  "DeSoto":{fmt:"In person",note:"11:00am, DeSoto County Courthouse, 115 E Oak St, Arcadia. Register by 10:30am with 5% of your highest bid."},
  "Collier":{fmt:"In person",note:"1:00pm, Collier County Courthouse, 1st floor. Arrive 15 min early."},
  "Hendry":{fmt:"In person",note:"Not on Realauction - Clerk runs the sale from a PDF notice. (863) 675-5217."},
  "Hillsborough":{fmt:"Fixed price",note:"Lands Available parcels only - bought directly from the Clerk."},
  "Glades":{fmt:"In person",note:"No sale currently scheduled."}
};

// County-map coloring: "online" (blue) vs "in-person" (red) vs "fixed" (fixed-
// price/Lands-Available-only, amber). A county with NO entry here means its
// format hasn't been confirmed yet - it stays neutral gray on the map rather
// than guessing. This is deliberately separate from COUNTY_INFO above (which
// drives the free-text logistics note/pill) since COUNTY_INFO only covers 15
// hand-annotated counties, while this covers every county we've been able to
// confirm one way or the other.
//
// Sources: the 44 Realauction-platform counties below (realtaxdeed.com /
// realforeclose.com) are online by construction - that platform IS an online
// bidding site. Levy and Okaloosa are on other online platforms (TaxSmartWeb
// and Bid4Assets respectively) and are scraped by their own harvest scripts.
// The in-person counties were confirmed against each County Clerk's own tax
// deed sale page (courthouse address/time, no bidding platform mentioned).
//
// Known conflict, not silently resolved: Hendry has a registered Realauction
// host (hendry.realtaxdeed.com) but COUNTY_INFO's hand-researched note says
// "Not on Realauction - Clerk runs the sale from a PDF notice." We trust the
// more specific note here and mark Hendry in-person, but this needs a human
// to actually confirm with the Hendry Clerk's office (863-675-5217).
//
// Left unclassified (shown gray - "not yet confirmed"): Gadsden, Lafayette,
// Liberty, Union. Each county's Clerk site either didn't load, didn't state
// a format, or had no active sale listed at research time.
const COUNTY_FORMAT = {
  // --- Online (Realauction: realtaxdeed.com / realforeclose.com) ---
  "Alachua":"online","Baker":"online","Bay":"online","Brevard":"online",
  "Broward":"online","Calhoun":"online","Charlotte":"online","Citrus":"online",
  "Clay":"online","Duval":"online","Escambia":"online","Flagler":"online",
  "Gilchrist":"online","Gulf":"online","Hernando":"online","Highlands":"online",
  "Indian River":"online","Jackson":"online","Lake":"online","Lee":"online",
  "Leon":"online","Manatee":"online","Marion":"online","Martin":"online",
  "Miami-Dade":"online","Monroe":"online","Nassau":"online","Okeechobee":"online",
  "Orange":"online","Osceola":"online","Palm Beach":"online","Pasco":"online",
  "Pinellas":"online","Polk":"online","Putnam":"online","Santa Rosa":"online",
  "Sarasota":"online","Seminole":"online","St. Johns":"online","St. Lucie":"online",
  "Suwannee":"online","Volusia":"online","Walton":"online","Washington":"online",
  // --- Online (other platforms) ---
  "Levy":"online",     // TaxSmartWeb - "Levy County has chosen to conduct this tax sale via the Internet"
  "Okaloosa":"online", // Bid4Assets - handled by harvest_okaloosa_bid4assets.ps1
  // --- In person (courthouse sale, confirmed via Clerk site) ---
  "DeSoto":"in-person","Collier":"in-person","Hendry":"in-person","Glades":"in-person",
  "Bradford":"in-person","Columbia":"in-person","Dixie":"in-person","Franklin":"in-person",
  "Hamilton":"in-person","Hardee":"in-person","Holmes":"in-person","Jefferson":"in-person",
  "Madison":"in-person","Sumter":"in-person","Taylor":"in-person","Wakulla":"in-person",
  // --- Fixed price only (no competitive bidding) ---
  "Hillsborough":"fixed"
  // Gadsden, Lafayette, Liberty, Union: intentionally omitted - unconfirmed.
};

// Authoritative list of all 67 FL counties (exact spelling matches
// fl-counties.svg's data-county attributes). This is the "county universe"
// used to populate the filter chips/dropdown - deliberately independent of
// which counties currently have live scraped rows in `ALL`, so a county with
// zero properties right now still shows up (as "(0)") instead of silently
// disappearing from the picker.
const ALL_COUNTIES = [
  "Alachua", "Baker", "Bay", "Bradford", "Brevard", "Broward", "Calhoun", "Charlotte", "Citrus", "Clay", "Collier", "Columbia", "DeSoto", "Dixie", "Duval", "Escambia", "Flagler", "Franklin", "Gadsden", "Gilchrist", "Glades", "Gulf", "Hamilton", "Hardee", "Hendry", "Hernando", "Highlands", "Hillsborough", "Holmes", "Indian River", "Jackson", "Jefferson", "Lafayette", "Lake", "Lee", "Leon", "Levy", "Liberty", "Madison", "Manatee", "Marion", "Martin", "Miami-Dade", "Monroe", "Nassau", "Okaloosa", "Okeechobee", "Orange", "Osceola", "Palm Beach", "Pasco", "Pinellas", "Polk", "Putnam", "Santa Rosa", "Sarasota", "Seminole", "St. Johns", "St. Lucie", "Sumter", "Suwannee", "Taylor", "Union", "Volusia", "Wakulla", "Walton", "Washington"
];

// Reference links per county so a county with 0 scraped properties (or any
// property, really) can still be manually verified against the county's own
// official sites. Compiled via web research - Property Appraiser sites were
// individually confirmed; auction links use the county's Realauction/
// Bid4Assets host where one exists, falling back to the County Clerk's tax
// deed sale page for in-person counties. Tax Collector sites come from the
// same county-registry research used elsewhere in this project. If a link
// ever 404s, that's a site having moved, not a scraper bug - report it so
// this table can be corrected.
const COUNTY_LINKS = {
  "Alachua": { appraiser: "https://www.acpafl.org/", auction: "https://alachua.realtaxdeed.com", taxcoll: "https://www.alachuacollector.com/" },
  "Baker": { appraiser: "https://bakerpa.com/", auction: "https://baker.realtaxdeed.com", taxcoll: "https://mybakertc.com/" },
  "Bay": { appraiser: "https://baypa.net/", auction: "https://bay.realtaxdeed.com", taxcoll: "https://baycountyfltax.gov/" },
  "Bradford": { appraiser: "https://www.bradfordappraiser.com/", auction: "https://bradfordclerk.com/tax-deeds-and-foreclosure-sales/", taxcoll: "https://www.bradfordtaxcollector.com" },
  "Brevard": { appraiser: "https://www.bcpao.us/", auction: "https://brevard.realforeclose.com", taxcoll: "https://www.brevardtaxcollector.com" },
  "Broward": { appraiser: "https://bcpa.net/", auction: "https://broward.realtaxdeed.com", taxcoll: "https://www.broward.org/RecordsTaxesTreasury" },
  "Calhoun": { appraiser: "https://calhounpa.net/", auction: "https://calhoun.realforeclose.com", taxcoll: "https://www.calhouncountytaxcollector.com" },
  "Charlotte": { appraiser: "https://www.ccappraiser.com/", auction: "https://charlotte.realforeclose.com", taxcoll: "https://taxcollector.charlottecountyfl.gov/" },
  "Citrus": { appraiser: "https://www.citruspa.org/", auction: "https://citrus.realtaxdeed.com", taxcoll: "https://www.citrustc.us/" },
  "Clay": { appraiser: "https://www.ccpao.com/", auction: "https://clay.realtaxdeed.com", taxcoll: "https://www.claycountytax.com/" },
  "Collier": { appraiser: "https://www.collierappraiser.com/", auction: "https://app.collierclerk.com/LFOfficialRecords/Browse.aspx?dbid=0&startid=1600&repo=OFFICIALRECORDSPROD", taxcoll: "https://www.colliertax.com" },
  "Columbia": { appraiser: "https://columbia.floridapa.com/", auction: "https://columbiaclerk.com/clerk-services/tax-deeds/upcoming-tax-deed-sales/", taxcoll: "https://www.columbiataxcollector.com" },
  "DeSoto": { appraiser: "https://www.desotopa.com/", auction: "https://www.desotoclerk.com/public-sales/tax-deeds/", taxcoll: "https://www.desototaxcollector.com" },
  "Dixie": { appraiser: "https://www.qpublic.net/fl/dixie/", auction: "https://dixieclerk.com/departments-services/court-services/tax-deed-sales/", taxcoll: "https://dixietax.com/" },
  "Duval": { appraiser: "https://www.jacksonville.gov/departments/property-appraiser", auction: "https://duval.realtaxdeed.com", taxcoll: "https://www.duvaltax.com" },
  "Escambia": { appraiser: "https://www.escpa.org/", auction: "https://escambia.realtaxdeed.com", taxcoll: "https://www.escambiataxcollector.com" },
  "Flagler": { appraiser: "https://flaglerpa.com/", auction: "https://flagler.realtaxdeed.com", taxcoll: "https://www.flaglertax.gov/" },
  "Franklin": { appraiser: "https://franklincountypa.net/", auction: "https://www.taxcertsale.com/FranklinTaxSale/(S(gq5dmdvop2s3ej45323mbyiu))/Default.aspx", taxcoll: "https://franklintaxcollector.com" },
  "Gadsden": { appraiser: "https://gadsdenpa.com/", auction: "https://gadsdenfl.realtaxlien.com/", taxcoll: "https://www.gadsdentaxcollector.com" },
  "Gilchrist": { appraiser: "https://www.qpublic.net/fl/gilchrist/", auction: "https://gilchrist.realtaxdeed.com", taxcoll: "https://gilchristtax.com/" },
  "Glades": { appraiser: "https://qpublic.net/fl/glades/", auction: "https://gladesclerk.com/clerk-services/tax-deeds/", taxcoll: "https://gladestc.com/" },
  "Gulf": { appraiser: "https://gulfpa.com/", auction: "https://gulf.realtaxdeed.com", taxcoll: "https://www.gulftaxcollector.com" },
  "Hamilton": { appraiser: "https://hamiltonpa.com/", auction: "https://hamiltonclerk.com/tax-deeds/", taxcoll: "https://www.hamiltontaxcollector.com" },
  "Hardee": { appraiser: "https://hardeepa.com/", auction: "https://www.hardeeclerk.com/departments/tax-deeds/tax-deed-sales/", taxcoll: "https://hardeetaxcollector.com" },
  "Hendry": { appraiser: "https://hendryprop.com/", auction: "https://www.hendryclerk.org/tax-deeds/", taxcoll: "https://www.hendrycountytc.com/" },
  "Hernando": { appraiser: "https://hernandopa-fl.us/", auction: "https://hernando.realtaxdeed.com", taxcoll: "https://www.hernandocounty.us/tc" },
  "Highlands": { appraiser: "https://www.hcpao.org/", auction: "https://highlands.realtaxdeed.com", taxcoll: "https://www.hctaxcollector.com/" },
  "Hillsborough": { appraiser: "https://www.hcpafl.org/", auction: "https://hillsborough.realtaxdeed.com", taxcoll: "https://www.hillstax.org" },
  "Holmes": { appraiser: "https://www.qpublic.net/fl/holmes/", auction: "https://holmesclerk.com/courts/foreclosures-tax-deeds/tax-deeds/", taxcoll: "https://holmestax.com/" },
  "Indian River": { appraiser: "https://www.ircpa.org/", auction: "https://indian-river.realtaxdeed.com", taxcoll: "https://www.irctax.com" },
  "Jackson": { appraiser: "https://jacksonpa.com/", auction: "https://jackson.realtaxdeed.com", taxcoll: "https://jacksontc.com/" },
  "Jefferson": { appraiser: "https://jeffersonpa.net/", auction: "https://www.jeffersonclerk.com/clerk-services/property-sales/tax-deed-sales/", taxcoll: "https://jeffersontc.com/" },
  "Lafayette": { appraiser: "https://www.lafayettepa.com/", auction: "https://www.lafayetteclerk.com/tax-deeds/", taxcoll: "https://www.lafayettetc.com/" },
  "Lake": { appraiser: "https://www.lakecopropappr.com/", auction: "https://lake.realtaxdeed.com", taxcoll: "https://www.laketax.com" },
  "Lee": { appraiser: "https://www.leepa.org/", auction: "https://lee.realtaxdeed.com", taxcoll: "https://www.leetc.com" },
  "Leon": { appraiser: "https://www.leonpa.gov/", auction: "https://leon.realtaxdeed.com", taxcoll: "https://www.leontaxcollector.net" },
  "Levy": { appraiser: "https://www.qpublic.net/fl/levy/", auction: "https://online.levyclerk.com/TaxSmartWeb", taxcoll: "https://levytax.org/" },
  "Liberty": { appraiser: "https://libertypa.org/", auction: "https://libertyclerk.com/courts/tax-deeds/", taxcoll: "https://www.libertytaxcollector.com" },
  "Madison": { appraiser: "https://madisonpa.com/", auction: "https://www.madisonclerk.com/tax-deed-sales/", taxcoll: "https://madisontc.com/" },
  "Manatee": { appraiser: "https://www.manateepao.gov/", auction: "https://manatee.realforeclose.com", taxcoll: "https://www.taxcollector.com/" },
  "Marion": { appraiser: "https://www.pa.marion.fl.us/", auction: "https://marion.realtaxdeed.com", taxcoll: "https://www.mariontax.com" },
  "Martin": { appraiser: "https://www.pamartinfl.gov/", auction: "https://martin.realtaxdeed.com", taxcoll: "https://www.martintaxcollector.com" },
  "Miami-Dade": { appraiser: "https://www.miamidadepa.gov/", auction: "https://miami-dade.realtaxdeed.com", taxcoll: "https://www.mdctaxcollector.gov" },
  "Monroe": { appraiser: "https://www.mcpafl.org/", auction: "https://monroe.realtaxdeed.com", taxcoll: "https://www.monroetaxcollector.com" },
  "Nassau": { appraiser: "https://www.nassauflpa.com/", auction: "https://nassau.realtaxdeed.com", taxcoll: "https://www.nassautaxcollector.com" },
  "Okaloosa": { appraiser: "https://www.okaloosapa.com/", auction: "https://www.bid4assets.com/OkaloosaFLTax/listings", taxcoll: "https://www.okaloosatax.com" },
  "Okeechobee": { appraiser: "https://www.okeechobeepa.com/", auction: "https://okeechobee.realtaxdeed.com", taxcoll: "https://www.okeechobeetaxcollector.com" },
  "Orange": { appraiser: "https://ocpaweb.ocpafl.org/", auction: "https://orange.realtaxdeed.com", taxcoll: "https://www.octaxcol.com" },
  "Osceola": { appraiser: "https://www.property-appraiser.org/", auction: "https://osceola.realtaxdeed.com", taxcoll: "https://www.osceolataxcollector.org" },
  "Palm Beach": { appraiser: "https://www.pbcpao.gov/", auction: "https://palm-beach.realtaxdeed.com", taxcoll: "https://www.pbctax.gov/" },
  "Pasco": { appraiser: "https://pascopa.com/", auction: "https://pasco.realtaxdeed.com", taxcoll: "https://www.pascotaxes.com" },
  "Pinellas": { appraiser: "https://www.pcpao.gov/", auction: "https://pinellas.realtaxdeed.com", taxcoll: "https://www.pinellastaxcollector.gov" },
  "Polk": { appraiser: "https://www.polkflpa.gov/", auction: "https://polk.realtaxdeed.com", taxcoll: "https://www.polktaxes.com" },
  "Putnam": { appraiser: "https://pa.putnam-fl.com/", auction: "https://putnam.realtaxdeed.com", taxcoll: "https://putnamtax.com/" },
  "Santa Rosa": { appraiser: "https://srcpa.gov/", auction: "https://santa-rosa.realtaxdeed.com", taxcoll: "https://srctc.com/" },
  "Sarasota": { appraiser: "https://www.sc-pa.com/", auction: "https://sarasota.realtaxdeed.com", taxcoll: "https://www.sarasotataxcollector.gov/" },
  "Seminole": { appraiser: "https://www.scpafl.org/", auction: "https://seminole.realtaxdeed.com", taxcoll: "https://www.seminoletax.org" },
  "St. Johns": { appraiser: "https://www.sjcpa.gov/", auction: "https://saintjohns.realtaxdeed.com", taxcoll: "https://www.sjctax.us" },
  "St. Lucie": { appraiser: "https://www.paslc.gov/", auction: "https://st-lucie.realforeclose.com", taxcoll: "https://www.tcslc.com" },
  "Sumter": { appraiser: "https://www.sumterpa.com/", auction: "https://www.sumterclerk.com/public-records/tax-deeds/tax-deed-sales/", taxcoll: "https://www.sumtertaxcollector.com" },
  "Suwannee": { appraiser: "https://www.suwanneepa.com/", auction: "https://suwannee.realtaxdeed.com", taxcoll: "https://suwtax.com/" },
  "Taylor": { appraiser: "https://www.qpublic.net/fl/taylor/", auction: "https://taylorclerk.com/departments/tax-deeds/", taxcoll: "https://www.taylorcountytaxcollector.com" },
  "Union": { appraiser: "https://union.floridapa.com/", auction: "https://unionclerk.com/tax-deed-sales/", taxcoll: "https://unioncountytc.com/" },
  "Volusia": { appraiser: "https://vcpa.vcgov.org/", auction: "https://volusia.realtaxdeed.com", taxcoll: "https://www.volusiataxcollector.org" },
  "Wakulla": { appraiser: "https://mywakullapa.com/", auction: "https://wakullaclerk.org/official_records/tax_deed_sales.php", taxcoll: "https://wakullatax.com/" },
  "Walton": { appraiser: "https://waltonpa.com/", auction: "https://walton.realforeclose.com", taxcoll: "https://www.waltontaxcollector.com" },
  "Washington": { appraiser: "https://www.qpublic.net/fl/washington/", auction: "https://washington.realtaxdeed.com", taxcoll: "https://www.washingtoncountytaxcollector.com/" },
};

let ALL = [], CALENDAR = {}, NOTES = {}, FAVS = new Set(), HIDDEN = new Set(), ME = null, IS_ADMIN = false;
// BIDLIST is the membership set (fast "is this on the list" checks);
// BIDLIST_ORDER is the same ids in the order they were added, oldest first -
// the bid list modal reverses it to show the most recently added one on top.
let BIDLIST = new Set(), BIDLIST_ORDER = [];
// Ids someone tried to add while the list was already full, in the order
// they tried - not persisted (in-memory/this session only), auto-promoted
// into BIDLIST oldest-first the moment a slot frees up. See promoteNextPending().
let BID_LIST_PENDING = [];

const LEDGERS = {
  auction: { title: "Auctions & Bidding", sub: "Open to competitive bidding at a live county auction." },
  laft: { title: "Lands Available", sub: "Fixed price from Clerk." },
  certificate: { title: "Tax Certificates", sub: "County-held liens available for direct purchase - not property." }
};

const state = {
  bidMin: null, bidMax: null, assessedMin: null,
  sortBy: "county", sortSecondary: "", favoritesOnly: false, topPicksOnly: false, soonOnly: false,
  hideOldListings: false,
  includeQT: false, maxBidPct: 40,
  statusView: "all",
  ledger: "auction",
  search: "",
  // Counties the user has expanded via a county-group's <details> disclosure.
  // Re-applied on every render() since render() rebuilds #main from scratch.
  expandedCounties: new Set(),
  counties: new Set(), types: new Set(TYPE_ORDER), liens: new Set(LIEN_ORDER)
};

function goneExpired(p) {
  if (!isGone(p) || !p.gone_since) return false;
  const flagged = FAVS.has(p.id) || (NOTES[p.id] || []).some(n => n.body || n.stage);
  const hours = flagged ? GONE_HOURS_FLAGGED : GONE_HOURS_DEFAULT;
  return (Date.now() - Date.parse(p.gone_since)) > hours * 3600 * 1000;
}

// An auction whose sale date has already come and gone is no longer open for
// bidding, no matter what the scraper's last-seen `status` says - that only
// flips to dropped/sold/notfound once a re-scrape happens to notice, which
// can lag days behind the actual sale. A passed calendar date isn't
// ambiguous the way a scrape-detected removal can be, so this doesn't wait
// for a grace period the way goneExpired() does for favorited/noted rows.
// LAFT and certificates aren't tied to a single sale date, so they're exempt.
function isPastDue(p) {
  if (p.source !== "auction") return false;
  const d = daysUntil(p);
  return d !== null && d < 0;
}

const fmtMoney = n => "$" + Number(n).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const fmtShort = n => "$" + Math.round(Number(n)).toLocaleString("en-US");
const esc = s => String(s == null ? "" : s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

// Shared error toast for the write actions below (favorite, hide, restore,
// bid list, notes). These used to fail completely silently on a Supabase
// error - the button just re-enabled with zero indication anything went
// wrong. One small dismissable banner beats duplicating that logic five
// times, and beats a jarring native alert() (used for the admin-approval
// flow only, left as-is since that's a rarer, already-attention-grabbing
// action). Auto-hides; tap dismisses early.
let errToastTimer = null;
function showErrorToast(msg) {
  let el = document.getElementById("errToast");
  if (!el) {
    el = document.createElement("div");
    el.id = "errToast";
    el.className = "err-toast";
    el.addEventListener("click", hideErrorToast);
    document.body.appendChild(el);
  }
  el.textContent = msg;
  el.classList.add("show");
  clearTimeout(errToastTimer);
  errToastTimer = setTimeout(hideErrorToast, 5000);
}
function hideErrorToast() {
  const el = document.getElementById("errToast");
  if (el) el.classList.remove("show");
}

// Small icon-prefix for the quick-action reference links, shared by the
// compact card row and the roomier detail-modal buttons so the two stay
// visually consistent.
const LINK_ICON = {
  "Street View": "🛰", "Appraiser": "🏛", "Zillow": "🏠", "Tax Collector": "💰",
  "Auction": "🔨", "LAFT": "🔨", "Lands Available Listing": "🔨",
  "County Auction Site": "🔨", "County-Held Liens List": "📋", "Title Search": "📜",
  "Clerk of Courts": "⚖", "GIS Map": "🗺"
};
const linkIcon = label => LINK_ICON[label] ? `<span class="link-icon">${LINK_ICON[label]}</span>` : "";

// Small "ⓘ" tooltip affordance - keyboard-focusable (not hover-only) so it
// works on touch devices too. `tip` is plain text, escaped for the
// data-tip attribute the CSS ::after reads it from.
const infoTip = tip => `<i class="info-tip" tabindex="0" data-tip="${esc(tip)}">i</i>`;
const FEES_TIP = "Florida doc stamps (0.70/$100) + recording fee, plus half the assessed value on homesteaded parcels (FS 197.502(6)(c)). Added on top of whatever the actual winning bid turns out to be - estimated here using the opening bid, since the real winning bid isn't known in advance.";

// Properties synced from the statewide harvest pipeline (as opposed to the
// hand-researched watchlist) never get url_zillow / url_streetview from the
// sync script - the harvester doesn't collect them, so the column is left
// out of that upsert on purpose so it doesn't blank out a hand-researched
// link for the same property on a later re-sync. Build a best-effort search
// link from the address instead, client-side, only when the real one is
// missing - this never touches the database, so a hand-researched link
// (when one exists) always wins and is never at risk of being overwritten.
// Tax Collector / Title Search have no such generic URL - both are
// per-county lookups that need real research, so those stay blank until
// the data pipeline actually captures them.
function fallbackZillowUrl(p) {
  if (p.url_zillow) return p.url_zillow;
  // Zillow's own search doesn't take raw lat/long, only its address-search
  // form - so geocoding (see scripts/geocode_properties.py) can't sharpen
  // this one the way it does Street View below. Keep the address-search
  // fallback as-is.
  if (!p.address) return "";
  return `https://www.zillow.com/homes/${encodeURIComponent(p.address + ", " + p.county + " County, FL")}_rb/`;
}
function fallbackStreetviewUrl(p) {
  if (p.url_streetview) return p.url_streetview;
  // Prefer a direct coordinate link once geocode_properties.py has filled
  // these in (schema-v8-geocoding.sql) - lands on the actual parcel instead
  // of Google's best guess from an address search, which can miss on rural
  // routes, new subdivisions, or a scraped address with a typo.
  if (typeof p.latitude === "number" && typeof p.longitude === "number") {
    return `https://www.google.com/maps/search/?api=1&query=${p.latitude},${p.longitude}`;
  }
  if (!p.address) return "";
  return `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(p.address + ", " + p.county + " County, FL")}`;
}

function propType(p) {
  const s = (p.prop_type || "").toLowerCase();
  if (!s || s.includes("unknown")) return "Unknown";
  if (s.includes("vacant")) return "Vacant Lot";
  if (s.includes("mobile") || s.includes("manuf") || /\bmh\b/.test(s)) return "Mobile/Manuf.";
  if (s.includes("townhome")) return "Townhome";
  if (s.includes("condo")) return "Condo";
  if (s.includes("store") || s.includes("office") || s.includes("comm")) return "Commercial";
  if (s.includes("sfr") || s.includes("duplex") || /\d\s*\/\s*\d/.test(s)) return "House";
  return "Unknown";
}

const marketOf = p => Number(p.market || p.assessed || 0);

// A scraped opening bid of exactly 0 means the county hasn't posted the
// figure yet, not that the parcel is free. Rendering that as "$0.00" made
// every unpublished row read like a giveaway - the single most misleading
// thing on the card. Treat 0/null/undefined alike as "not published yet"
// and say so in words, in muted type, so it can't be mistaken for a price.
const hasPublishedBid = p => p.bid !== null && p.bid !== undefined && Number(p.bid) > 0;
const bidDisplay = p => (hasPublishedBid(p) ? fmtMoney(p.bid) : "Not published");

// Several counties dump the parcel number (or a bare "Parcel 12-34-56"
// placeholder) into the address column. That printed twice: once as the card
// title, then again in the "Parcel #" reference line directly underneath.
// Return "" when the address carries no real street information, so the card
// falls back to its proper parcel-lot title and drops the duplicate line.
//
// The denylist below is for the other failure mode, seen live on Escambia: a
// harvester picks up a COLUMN HEADER or an empty-field placeholder instead of
// a value, and the card ends up titled "Case Account". These are matched as
// whole strings only - a genuine street address that merely contains one of
// these words ("1200 Account Rd") still has its number and its suffix and is
// kept. Anything not on the list is trusted; guessing at "does this look like
// an address" would eventually throw away a real one.
const JUNK_ADDRESSES = new Set([
  "case account", "case", "account", "case number", "account number",
  "owner", "owner name", "owner of record", "last owner of record",
  "description", "address", "property address", "legal description",
  "parcel", "parcel number", "parcel id",
  "na", "n a", "none", "null", "unknown", "tbd", "not available",
  "no address", "no address available", "see legal", "-", "--"
]);

function realAddress(p) {
  const a = (p.address || "").trim();
  if (!a) return "";
  if (/^parcel\b/i.test(a)) return "";
  const squash = s => s.replace(/[^0-9a-z]/gi, "").toLowerCase();
  if (p.parcel && squash(a) === squash(p.parcel)) return "";
  // No letters at all means it's an identifier, not a street address.
  if (!/[a-z]/i.test(a)) return "";
  // Collapse punctuation and runs of whitespace before the denylist check, so
  // "Case / Account", "case  account" and "CASE ACCOUNT." all match.
  if (JUNK_ADDRESSES.has(a.replace(/[^0-9a-z]+/gi, " ").trim().toLowerCase())) return "";
  return a;
}

// The card title when there is no usable address. Falls back a second time
// when the parcel is missing too, rather than printing the literal string
// "Parcel #Unknown (Escambia County Lot)", which reads like a data error
// because it is one - it says nothing except that two fields are empty.
const hasParcel = p => !!(p.parcel && String(p.parcel).trim() &&
  !/^(unknown|n\/?a|none|null)$/i.test(String(p.parcel).trim()));
const lotTitle = p => (hasParcel(p)
  ? `Parcel #${esc(p.parcel)} (${esc(p.county)} County Lot)`
  : `${esc(p.county)} County Lot (parcel # not published)`);

const valueRatio = p => (Number(p.bid) > 0 ? marketOf(p) / Number(p.bid) : 0);
const isTopPick = p => p.lien_level === "clean" && valueRatio(p) >= TOP_PICK_RATIO;
const homesteadSurcharge = p => (p.homestead ? Number(p.assessed || 0) / 2 : 0);
function fees(p) {
  // Fee/add-on cost only - NOT a total acquisition cost. We don't know the
  // actual winning bid in advance (only the opening bid), so this shows
  // what gets layered on top of whatever bid wins, rather than pretending
  // the opening bid is the final price.
  const bid = Number(p.bid) || 0;
  const base = bid + homesteadSurcharge(p);
  const total = base + base * DOC_STAMP_RATE + RECORDING_FEE + (state.includeQT ? QUIET_TITLE_EST : 0);
  return total - bid;
}
const maxBid = p => marketOf(p) * (state.maxBidPct / 100);
function daysUntil(p) {
  if (!p.sale_date) return null;
  const [y, mo, da] = p.sale_date.split("-").map(Number); const d = Date.UTC(y, mo - 1, da);
  const t = new Date(); return Math.round((d - Date.UTC(t.getFullYear(), t.getMonth(), t.getDate())) / 86400000);
}

// Days since this property was last updated by the scraper
function daysSinceUpdate(p) {
  if (!p.updated_at) return 0;
  const d = new Date(p.updated_at);
  return Math.floor((Date.now() - d) / 86400000);
}

// Calculate freshness status for a group of properties (e.g., one county)
function getGroupFreshness(rows) {
  if (!rows || rows.length === 0) return { isStale: false, timestamp: null, hours: null };
  const newest = rows.reduce((a, p) => (p.updated_at && p.updated_at > a ? p.updated_at : a), "");
  if (!newest) return { isStale: false, timestamp: null, hours: null };
  const hours = (Date.now() - Date.parse(newest)) / 3600000;
  return {
    isStale: hours > STALE_DATA_HOURS,
    timestamp: newest,
    hours: Math.round(hours)
  };
}

function saleTime(p) {
  if (!p.sale_date) return Infinity;
  const t = Date.parse(p.sale_date);
  return isNaN(t) ? Infinity : t;
}
const countyNames = () => Array.from(new Set(ALL.map(p => p.county)));
const fmtDate = d => new Date(d + "T00:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
// Long form (weekday + full month) used only for the date-divider headers
// that separate auction groups by sale date - fmtDate's short form stays
// in the per-county meta line and everywhere else unchanged.
const fmtDateLong = d => new Date(d + "T00:00:00").toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric", year: "numeric" });

const gate = document.getElementById("authGate");
const app = document.getElementById("app");
const pendingGate = document.getElementById("pendingGate");
const authMsg = document.getElementById("authMsg");
const authLead = document.getElementById("authLead");
const authModeToggle = document.getElementById("authModeToggle");
const passwordConfirmEl = document.getElementById("passwordConfirm");
// Extra sign-up-only profile fields - same hidden/required toggle pattern as
// passwordConfirmEl above, driven by setAuthMode(). Only relevant to signup;
// signin never shows or requires them.
const firstNameEl = document.getElementById("firstName");
const lastNameEl = document.getElementById("lastName");
const companyEl = document.getElementById("company");
const addressEl = document.getElementById("address");
const phoneEl = document.getElementById("phone");
const SIGNUP_PROFILE_FIELDS = [firstNameEl, lastNameEl, companyEl, addressEl, phoneEl];

// "Sign in" is the default; the toggle flips this to a self-serve signup
// flow (sb.auth.signUp). NOTE: this only controls whether a Supabase Auth
// account can be created - it doesn't grant that account access to any
// data. Every table is still gated by Supabase Row Level Security, which
// this toggle has no say over.
let authMode = "signin";
function setAuthMode(mode) {
  authMode = mode;
  const signUp = mode === "signup";
  if (authLead) authLead.textContent = signUp ? "Create an account." : "Sign in to continue.";
  const btn = document.getElementById("signInBtn");
  if (btn) btn.textContent = signUp ? "Create account" : "Sign in";
  if (authModeToggle) authModeToggle.textContent = signUp ? "Already have an account? Sign in" : "Need an account? Create one";
  if (passwordConfirmEl) { passwordConfirmEl.hidden = !signUp; passwordConfirmEl.required = signUp; passwordConfirmEl.value = ""; }
  SIGNUP_PROFILE_FIELDS.forEach(el => { if (el) { el.hidden = !signUp; el.required = signUp; el.value = ""; } });
  const pw = document.getElementById("password");
  if (pw) pw.autocomplete = signUp ? "new-password" : "current-password";
  if (authMsg) { authMsg.className = "auth-msg"; authMsg.textContent = ""; }
}
if (authModeToggle) {
  authModeToggle.addEventListener("click", () => setAuthMode(authMode === "signin" ? "signup" : "signin"));
}

const authForm = document.getElementById("authForm");
if (authForm) {
  authForm.addEventListener("submit", async e => {
    e.preventDefault();
    const btn = document.getElementById("signInBtn");
    const email = document.getElementById("email").value.trim();
    const password = document.getElementById("password").value;

    if (authMode === "signup") {
      if (passwordConfirmEl && password !== passwordConfirmEl.value) {
        if (authMsg) { authMsg.className = "auth-msg err"; authMsg.textContent = "Passwords don't match."; }
        return;
      }
      const firstName = firstNameEl ? firstNameEl.value.trim() : "";
      const lastName = lastNameEl ? lastNameEl.value.trim() : "";
      const company = companyEl ? companyEl.value.trim() : "";
      const address = addressEl ? addressEl.value.trim() : "";
      const phone = phoneEl ? phoneEl.value.trim() : "";
      // All five are required - Company has no separate "skip" control, since
      // someone with no company enters "Independent" there instead.
      if (!firstName || !lastName || !company || !address || !phone) {
        if (authMsg) {
          authMsg.className = "auth-msg err";
          authMsg.textContent = "Please fill in all fields. No company? Enter \"Independent\".";
        }
        return;
      }
      if (btn) btn.disabled = true;
      if (authMsg) { authMsg.className = "auth-msg"; authMsg.textContent = "Creating account"; }
      const { data, error } = await sb.auth.signUp({
        email,
        password,
        options: { data: { first_name: firstName, last_name: lastName, company, address, phone } }
      });
      if (btn) btn.disabled = false;
      if (error) {
        if (authMsg) { authMsg.className = "auth-msg err"; authMsg.textContent = error.message; }
        return;
      }
      // Two outcomes depending on the project's email-confirmation setting:
      // a session comes back immediately (auto-confirmed - the
      // onAuthStateChange listener below takes it from here and shows the
      // app), or Supabase requires a confirmation click first and there's
      // no session yet - in that case, drop back to the sign-in view with
      // an explanatory message instead of silently doing nothing.
      if (!data.session) {
        // setAuthMode() clears authMsg as part of resetting the form, so the
        // confirmation message has to be set AFTER switching modes, not before.
        setAuthMode("signin");
        if (authMsg) {
          authMsg.className = "auth-msg";
          authMsg.textContent = "Account created — check your email to confirm it, then sign in.";
        }
      }
      return;
    }

    if (btn) btn.disabled = true;
    if (authMsg) {
      authMsg.className = "auth-msg";
      authMsg.textContent = "Signing in";
    }
    const { error } = await sb.auth.signInWithPassword({ email, password });
    if (btn) btn.disabled = false;
    if (error && authMsg) {
      authMsg.className = "auth-msg err";
      authMsg.textContent = error.message;
    }
  });
}

const signOutBtn = document.getElementById("signOutBtn");
if (signOutBtn) {
  signOutBtn.addEventListener("click", () => doSignOut(null));
}
const pendingSignOutBtn = document.getElementById("pendingSignOutBtn");
if (pendingSignOutBtn) {
  pendingSignOutBtn.addEventListener("click", () => doSignOut(null));
}

async function doSignOut(reason) {
  stopIdleWatch();
  if (reason) sessionStorage.setItem("tdw_signout_reason", reason);
  await sb.auth.signOut();
  location.reload();
}

function showPending() {
  stopIdleWatch();
  if (gate) gate.hidden = true;
  if (app) app.hidden = true;
  if (pendingGate) pendingGate.hidden = false;
}

// Gatekeeper between "signed in" and "sees the app": every account also
// needs an approved row in public.profiles (see schema-v6-approvals.sql).
// Self-serve sign-up creates the auth account instantly, but a DB trigger
// creates its profiles row with approved=false - actual ledger access stays
// blocked by RLS until the owner flips that to true (from the admin panel
// in showApp(), or directly in the Supabase table editor).
async function checkApprovalAndEnter(session) {
  ME = session.user;
  const { data: profile, error } = await sb.from("profiles").select("approved,is_admin").eq("id", ME.id).maybeSingle();
  if (error) {
    // Most likely schema-v6-approvals.sql hasn't been run against this
    // project yet (profiles table doesn't exist) - fall back to the
    // pre-approval-gate behavior instead of locking everyone out because of
    // a migration nobody's applied. Once the migration runs, this query
    // stops erroring and the gate takes effect on the next sign-in.
    IS_ADMIN = false;
    showApp();
    return;
  }
  IS_ADMIN = !!(profile && profile.is_admin);
  if (profile && profile.approved) showApp();
  else showPending();
}

let lastActivity = Date.now();
let tick = null;
function markActive() { lastActivity = Date.now(); }
function stopIdleWatch() { if (tick) { clearInterval(tick); tick = null; } }
function startIdleWatch() {
  stopIdleWatch();
  markActive();
  tick = setInterval(() => { if (!ME) return; if (Date.now() - lastActivity >= IDLE_MINUTES * 60 * 1000) doSignOut("idle"); }, 5000);
}

["mousemove", "mousedown", "keydown", "touchstart", "wheel", "scroll"].forEach(ev => window.addEventListener(ev, markActive, { passive: true, capture: true }));
document.addEventListener("visibilitychange", () => { if (!document.hidden) markActive(); });

sb.auth.onAuthStateChange((_e, session) => {
  if (session && session.user) { checkApprovalAndEnter(session); }
  else if (gate && app) { gate.hidden = false; app.hidden = true; if (pendingGate) pendingGate.hidden = true; }
});

(async () => {
  const { data } = await sb.auth.getSession();
  if (data.session) { checkApprovalAndEnter(data.session); }
  else if (gate) {
    gate.hidden = false;
    const why = sessionStorage.getItem("tdw_signout_reason");
    if (why === "idle" && authMsg) { authMsg.textContent = `Signed out after ${IDLE_MINUTES} minutes of inactivity.`; sessionStorage.removeItem("tdw_signout_reason"); }
  }
})();

// Animated card-shaped placeholders shown while the first Supabase fetch is
// in flight, instead of a bare "Loading" line. render() replaces #main's
// entire innerHTML once real data is in, so this needs no manual cleanup.
function renderSkeleton() {
  const main = document.getElementById("main");
  if (!main) return;
  const group = `
    <div class="skeleton-group">
      <div class="skel skel-title"></div>
      <div class="skel skel-line w40"></div>
      <div class="skel skel-line w80"></div>
      <div class="skel skel-line w60"></div>
      <div class="skel-grid">
        <div class="skel skel-box"></div><div class="skel skel-box"></div>
        <div class="skel skel-box"></div><div class="skel skel-box"></div>
      </div>
    </div>`;
  main.innerHTML = group.repeat(3);
}

async function showApp() {
  if (gate) gate.hidden = true;
  if (pendingGate) pendingGate.hidden = true;
  if (app) app.hidden = false;
  const genEl = document.getElementById("generatedAt");
  if (genEl) genEl.textContent = "Loading";
  renderSkeleton();
  await loadAll();
  state.counties = new Set(ALL_COUNTIES);
  buildAllChips();
  updateBadge();
  render();
  startIdleWatch();
  if (IS_ADMIN) refreshAdminApprovals();
}

// Admin-only: lists every account still waiting on approved=true (see
// schema-v6-approvals.sql) with a one-click Approve button. Only ever
// fetches anything for an admin account - profiles' RLS only lets a
// non-admin see their own row, so this silently returns nothing (not an
// error) for everyone else, but it's still gated behind IS_ADMIN so
// non-admins never even make the request.
async function refreshAdminApprovals() {
  const wrap = document.getElementById("adminApprovals");
  const list = document.getElementById("adminApprovalsList");
  if (!wrap || !list) return;
  const { data, error } = await sb.from("profiles").select("id,email,first_name,last_name,company,requested_at").eq("approved", false).order("requested_at");
  if (error || !data || !data.length) { wrap.hidden = true; list.innerHTML = ""; return; }
  wrap.hidden = false;
  list.innerHTML = data.map(p => {
    const name = [p.first_name, p.last_name].filter(Boolean).join(" ") || "Unknown";
    const company = p.company ? ` (${esc(p.company)})` : "";
    return `
    <span class="admin-approval-row" data-id="${esc(p.id)}">
      <span class="admin-approval-info">
        <span class="admin-approval-name">${esc(name)}${company}</span>
        <span class="admin-approval-email">${esc(p.email)}</span>
      </span>
      <span class="admin-approval-when">requested ${fmtDate((p.requested_at || "").slice(0, 10))}</span>
      <button class="mini-btn admin-approve-btn" type="button" data-id="${esc(p.id)}">✓ Approve</button>
    </span>`;
  }).join("");
  list.querySelectorAll(".admin-approve-btn").forEach(btn => {
    btn.addEventListener("click", async () => {
      btn.disabled = true;
      btn.textContent = "Approving…";
      const { error: updErr } = await sb.from("profiles")
        .update({ approved: true, approved_at: new Date().toISOString() })
        .eq("id", btn.dataset.id);
      if (updErr) { btn.disabled = false; btn.textContent = "✓ Approve"; alert("Couldn't approve: " + updErr.message); return; }
      refreshAdminApprovals();
    });
  });
}

async function loadAll() {
  const today = new Date().toISOString().slice(0, 10);
  const [props, notes, favs, hid, cal, bidlist] = await Promise.all([
    sb.from("properties").select("*").order("county").order("case_no"),
    sb.from("notes").select("*"),
    sb.from("favorites").select("property_id"),
    sb.from("hidden").select("property_id"),
    sb.from("county_calendar").select("county,sale_date").gte("sale_date", today).order("sale_date"),
    sb.from("bid_list").select("property_id").order("added_at")
  ]);
  if (props.error) {
    const genEl = document.getElementById("generatedAt");
    if (genEl) genEl.textContent = "Error: " + props.error.message;
    return;
  }
  ALL = props.data || [];
  NOTES = {}; (notes.data || []).forEach(n => { (NOTES[n.property_id] = NOTES[n.property_id] || []).push(n); });
  FAVS = new Set((favs.data || []).map(r => r.property_id));
  HIDDEN = new Set((hid.data || []).map(r => r.property_id));
  // Missing table (schema-v7-bidlist.sql not run yet) fails soft, same as
  // every other migration-gated feature here - the list just starts empty
  // instead of blocking sign-in.
  BIDLIST_ORDER = bidlist.error ? [] : (bidlist.data || []).map(r => r.property_id);
  BIDLIST = new Set(BIDLIST_ORDER);
  CALENDAR = {}; if (!cal.error) { (cal.data || []).forEach(r => { (CALENDAR[r.county] = CALENDAR[r.county] || []).push(r.sale_date); }); }
  const newest = ALL.reduce((a, p) => (p.updated_at > a ? p.updated_at : a), "");
  const genEl = document.getElementById("generatedAt");
  const eyeEl = document.getElementById("eyebrow");
  if (genEl) {
    const staleHours = newest ? (Date.now() - Date.parse(newest)) / 3600000 : null;
    const isStale = staleHours !== null && staleHours > STALE_DATA_HOURS;
    genEl.classList.toggle("stale", isStale);
    genEl.textContent = !newest ? "No data yet." :
      isStale ? "⚠ Data updated " + new Date(newest).toLocaleString() + " - sync may be behind" :
      "Data updated " + new Date(newest).toLocaleString();
  }
  if (eyeEl) eyeEl.textContent = "Field Ledger - " + countyNames().length + " Counties Tracked";
}

// County chips and the county map (below) both drive state.counties, so a
// click on either one has to keep the other in sync - route both through
// this single toggle instead of mutating the set in two places.
function toggleCounty(name) {
  if (state.counties.has(name)) state.counties.delete(name); else state.counties.add(name);
  const on = state.counties.has(name);
  document.querySelectorAll('#countyChips .chipx').forEach(c => {
    if (c.dataset.value !== name) return;
    c.classList.toggle("on", on);
    c.setAttribute("aria-pressed", on ? "true" : "false");
  });
  if (mapLoaded) document.querySelectorAll('#mapHost path[data-county]').forEach(p => { if (p.dataset.county === name) p.classList.toggle("sel", on); });
  syncCountyQuickSelect();
  updateBadge();
  render();
}

// Chips are <span>s, so nothing about them was reachable without a mouse:
// no tab stop, no Enter/Space activation, and a screen reader announced them
// as plain text with no on/off state. role/tabindex/aria-pressed plus a
// keydown handler make the whole filter panel operable from the keyboard
// without changing the markup the stylesheet targets.
function buildChips(id, values, set, labelFn, classFn) {
  const el = document.getElementById(id); if (!el) return; el.innerHTML = "";
  values.forEach(v => {
    const c = document.createElement("span");
    c.className = "chipx" + (set.has(v) ? " on" : "") + (classFn ? " " + classFn(v) : "");
    c.textContent = labelFn ? labelFn(v) : v; c.dataset.value = v;
    c.setAttribute("role", "button");
    c.setAttribute("tabindex", "0");
    c.setAttribute("aria-pressed", set.has(v) ? "true" : "false");
    const toggle = () => {
      if (id === "countyChips") { toggleCounty(v); return; }
      set.has(v) ? set.delete(v) : set.add(v);
      c.classList.toggle("on");
      c.setAttribute("aria-pressed", set.has(v) ? "true" : "false");
      updateBadge(); render();
    };
    c.addEventListener("click", toggle);
    c.addEventListener("keydown", e => {
      if (e.key !== "Enter" && e.key !== " " && e.key !== "Spacebar") return;
      e.preventDefault();   // stop Space from scrolling the panel
      toggle();
    });
    el.appendChild(c);
  });
}

// County chips carry a "(n)" count and sort busiest-first, so the picker
// itself answers "how many properties does this county have" instead of
// just being an alphabetical toggle list.
function countyCounts() {
  const m = new Map();
  ALL.forEach(p => m.set(p.county, (m.get(p.county) || 0) + 1));
  return m;
}
function countyNamesByCount() {
  const counts = countyCounts();
  // Sorts ALL 67 counties busiest-first (not just the ones with live rows),
  // so the picker always shows the full state - counties with 0 properties
  // sink to the bottom, alphabetically among themselves, instead of
  // disappearing.
  return ALL_COUNTIES.slice().sort((a, b) => (counts.get(b) || 0) - (counts.get(a) || 0) || a.localeCompare(b));
}
// The quick "Select County" dropdown is a single-pick shortcut over the same
// state.counties set the multi-select chips drive - picking one county here
// narrows to just that county; picking "All Counties" restores the full set.
// It can't represent an arbitrary multi-county selection made via the chips,
// so it just falls back to showing "All Counties" whenever the selection
// isn't exactly zero-or-one county.
function syncCountyQuickSelect() {
  const el = document.getElementById("countyQuick");
  if (!el) return;
  el.value = state.counties.size === 1 ? Array.from(state.counties)[0] : "ALL";
}
function buildAllChips() {
  const counts = countyCounts();
  const names = countyNamesByCount();
  buildChips("countyChips", names, state.counties, v => `${v} (${counts.get(v) || 0})`, v => (counts.get(v) ? "" : "chip-empty"));
  buildChips("typeChips", TYPE_ORDER, state.types);
  buildChips("lienChips", LIEN_ORDER, state.liens, v => LIEN_LABEL[v], v => "lien-" + v);
  const countyQuickEl = document.getElementById("countyQuick");
  if (countyQuickEl) {
    countyQuickEl.innerHTML = `<option value="ALL">All Counties</option>` +
      names.map(v => `<option value="${esc(v)}">${esc(v)} (${counts.get(v) || 0})</option>`).join("");
    syncCountyQuickSelect();
  }
  // "N of M selected" badges on the Advanced Filters dropdown summaries.
  const typeCountEl = document.getElementById("typeCount");
  if (typeCountEl) typeCountEl.textContent = `${state.types.size}/${TYPE_ORDER.length}`;
  const lienCountEl = document.getElementById("lienCount");
  if (lienCountEl) lienCountEl.textContent = `${state.liens.size}/${LIEN_ORDER.length}`;
  const countyCountEl = document.getElementById("countyCount");
  if (countyCountEl) countyCountEl.textContent = `${state.counties.size}/${names.length}`;
  buildCountyRefLinks(counts, names);
}

// Counties with 0 scraped properties still get a chip (see countyNamesByCount
// / ALL_COUNTIES above), but a chip alone doesn't let anyone actually verify
// anything about a county the scraper hasn't reached yet. This renders a
// direct-link row - Appraiser / Auction / Tax Collector - for every county
// currently at 0, reusing the same LINK_ICON glyphs used elsewhere so it
// reads as the same kind of control as the property-level reference links.
function buildCountyRefLinks(counts, names) {
  const wrap = document.getElementById("countyRefLinks");
  const list = document.getElementById("countyRefList");
  if (!wrap || !list) return;
  const empties = names.filter(v => !counts.get(v));
  if (!empties.length) { wrap.hidden = true; list.innerHTML = ""; return; }
  wrap.hidden = false;
  list.innerHTML = empties.map(v => {
    const links = COUNTY_LINKS[v];
    if (!links) return `<div class="county-ref-row"><span class="county-ref-name">${esc(v)}</span><span class="county-ref-none">no reference links on file</span></div>`;
    const item = (label, url) => url
      ? `<a href="${esc(url)}" target="_blank" rel="noopener">${linkIcon(label)}${label}</a>`
      : "";
    return `<div class="county-ref-row">
      <span class="county-ref-name">${esc(v)}</span>
      <span class="county-ref-links-row">
        ${item("Appraiser", links.appraiser)}
        ${item("Auction", links.auction)}
        ${item("Tax Collector", links.taxcoll)}
      </span>
    </div>`;
  }).join("");
}

function matchesSearch(p) {
  if (!state.search) return true;
  const q = state.search.toLowerCase();
  return (p.address || "").toLowerCase().includes(q) ||
    (p.parcel || "").toLowerCase().includes(q) ||
    (p.case_no || "").toLowerCase().includes(q);
}

function passes(p) {
  if (HIDDEN.has(p.id) || goneExpired(p)) return false;
  // Archive is a different mode, not a sub-filter of live/gone: it shows
  // ONLY past-due auctions (the record of what already closed, so notes/
  // stage on a property you won don't just vanish once the sale date
  // passes), while every other view excludes them outright. Keep this
  // check ahead of the live/gone branch below so the two modes can't leak
  // into each other.
  const archiving = state.statusView === "archive";
  if (archiving) { if (!isPastDue(p)) return false; }
  else if (isPastDue(p)) return false;
  if (!archiving) {
    if (state.statusView === "gone" && !isGone(p)) return false;
    if (state.statusView === "live" && isGone(p)) return false;
  }
  if (state.favoritesOnly && !FAVS.has(p.id)) return false;
  if (state.topPicksOnly && !isTopPick(p)) return false;
  if (state.soonOnly) { const d = daysUntil(p); if (d === null || d < 0 || d > SOON_DAYS) return false; }
  if (state.hideOldListings) { const d = daysSinceUpdate(p); if (d >= 7) return false; }
  if (!state.counties.has(p.county)) return false;
  if (!matchesSearch(p)) return false;
  // Certificates aren't screened for title and don't have a property type -
  // the type/lien chip filters only make sense for deed/LAFT rows.
  if (p.source !== "certificate" && (!state.types.has(propType(p)) || !state.liens.has(p.lien_level))) return false;
  if ((state.bidMin !== null && Number(p.bid) < state.bidMin) || (state.bidMax !== null && Number(p.bid) > state.bidMax)) return false;
  if (p.source !== "certificate" && state.assessedMin !== null && Number(p.assessed || 0) < state.assessedMin) return false;
  return true;
}

function noteHtml(p) {
  const rows = (NOTES[p.id] || []).slice().sort((a, b) => (a.updated_at < b.updated_at ? 1 : -1));
  const mine = ME ? rows.find(n => n.author_id === ME.id) : null;
  const others = ME ? rows.filter(n => n.author_id !== ME.id) : rows;
  const list = others.map(n => `<div class="note-item"><span class="note-author">${esc((n.author_email || "teammate").split("@")[0])}</span>${n.stage ? `<span class="note-stage-tag">${esc(n.stage)}</span>` : ""}<br>${esc(n.body || "")}</div>`).join("");
  return `
  <div class="notes-block">
    <div class="notes-head"><span>Team notes${rows.length ? " (" + rows.length + ")" : ""}</span></div>
    ${list}
    <div class="note-editor">
      <select data-role="stage" data-pid="${p.id}">${STAGES.map(s => `<option value="${s}"${mine && mine.stage === s ? " selected" : ""}>${s === "" ? " - stage - " : s}</option>`).join("")}</select>
      <textarea data-role="body" data-pid="${p.id}" rows="2" placeholder="Your note">${esc(mine ? mine.body : "")}</textarea>
      <button class="note-save" data-action="savenote" data-pid="${p.id}" type="button">Save note</button>
    </div>
  </div>`;
}

// Shared "add/remove bid list" toggle - distinct from the ♥ Favorite button:
// this one is capped at BID_LIST_MAX and meant for the short list of
// properties someone's actually planning to show up and bid on, rather than
// a general watch flag. `compact` renders the small icon-only version used
// on cards; the full labeled version is used in the detail modal.
//
// Three states, not two: on the list (⚑), queued (⏳ - list was full when
// they clicked, so this one is waiting and gets added automatically the
// moment a slot frees up, no need to come back and click again), or neither
// (⚐, click to add or queue).
function bidListBtnHtml(p, compact) {
  const on = BIDLIST.has(p.id);
  const pending = !on && BID_LIST_PENDING.includes(p.id);
  const icon = on ? "⚑" : pending ? "⏳" : "⚐";
  const label = on ? "On bid list — tap to remove"
    : pending ? "Bid list is full - queued, will be added automatically once a slot frees up (tap to cancel)"
    : `Add to bid list (max ${BID_LIST_MAX})`;
  const cls = on ? " on" : pending ? " pending" : "";
  if (compact) {
    return `<button class="icon-btn bid-btn${cls}" data-action="bidlist" data-pid="${p.id}" type="button" title="${esc(label)}">${icon}</button>`;
  }
  const fullLabel = on ? "⚑ On Bid List" : pending ? "⏳ Queued — adds automatically" : "⚐ Add to Bid List";
  return `<button class="icon-btn bid-btn${cls}" data-action="bidlist" data-pid="${p.id}" type="button" title="${esc(label)}">${fullLabel}</button>`;
}

function card(p, showCounty) {
  const el = document.createElement("div");
  const fav = FAVS.has(p.id), top = isTopPick(p);
  el.className = "prop-card" + (fav ? " favorited" : "") + (top ? " toppick" : "");
  const d = daysUntil(p);
  let cd = "";
  if (d !== null && d >= 0) { const cls = d <= 3 ? "urgent" : d <= SOON_DAYS ? "soon" : ""; cd = `<span class="countdown ${cls}">${d === 0 ? "TODAY" : d + "d"}</span>`; }
  else if (d !== null && d < 0) { cd = `<span class="countdown past">${-d}d ago</span>`; }
  const tag = showCounty ? `<div class="prop-county-tag">${esc(p.county)}${p.sale_date ? " - " + fmtDate(p.sale_date) : ""}</div>` : (p.sale_date ? `<div class="prop-county-tag">Sale ${new Date(p.sale_date + "T00:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric" })}</div>` : "");

  const street = realAddress(p);
  const hasAddress = !!street;
  const titleLine = hasAddress ? esc(street) : lotTitle(p);
  const bidPublished = hasPublishedBid(p);

  // Kept deliberately lean: header, parcel #, opening bid, and an estimated
  // value (real market value when we have it, otherwise the county's
  // assessed value as a stand-in - see marketOf()) are the only figures
  // that matter for a first glance. Everything else that used to live here -
  // the full title-status banner, owner/parcel copy buttons, notes - moved
  // to the full property page (openDetail/detailHtml), one click away via
  // the small link at the bottom. The county Tax Collector and Title
  // Search links, and the standalone Auction icon-link, moved there too -
  // the CTA button below already covers "go to the auction," so a second,
  // smaller Auction link right next to it was pure redundancy.
  //
  // Opening Bid + Est. Value are the two headline numbers - the whole pitch
  // of a tax deed/LAFT listing is "what will it cost me vs. what's it
  // worth" - so they get a 2-up grid instead of being crowded by a third
  // box; Parcel # moves to a quiet reference line right under the address.
  const marketVal = marketOf(p);
  const usingAssessed = !p.market && p.assessed;
  const isClosed = isGone(p);
  el.innerHTML = `
    ${isClosed ? `<div class="closed-banner">✓ Closed - ${esc(p.status)}</div>` : ""}
    ${top ? `<div class="toppick-banner">★ Top pick <span class="ratio-pill">${valueRatio(p).toFixed(1)}× market vs bid</span></div>` : ""}
    ${tag}
    <div class="prop-top">
      <div class="prop-address">${titleLine}</div>
      <div class="prop-top-actions">
        <button class="icon-btn heart-btn${fav ? " on" : ""}" data-action="fav" data-pid="${p.id}" type="button" title="Favorite">${fav ? "♥" : "♡"}</button>
        ${bidListBtnHtml(p, true)}
        <button class="icon-btn remove-btn" data-action="hide" data-pid="${p.id}" type="button" title="Hide">✕</button>
        ${cd}
        ${!isClosed ? `<span class="lien-pill ${esc(p.lien_level)}">${LIEN_LABEL[p.lien_level] || p.lien_level}</span>` : ""}
        <span class="pill ${esc(p.status)}">${esc(p.status)}</span>
      </div>
    </div>
    ${hasAddress && hasParcel(p) ? `<div class="prop-parcel-line">Parcel # ${esc(p.parcel)}</div>` : ""}
    <div class="card-stat-grid ${marketVal ? "card-stat-grid-2" : "card-stat-grid-1"}">
      <div class="card-stat card-stat-headline"><div class="card-stat-label">Opening Bid</div><div class="card-stat-val bid${bidPublished ? "" : " unpublished"}">${bidDisplay(p)}</div></div>
      ${marketVal ? `<div class="card-stat card-stat-headline"><div class="card-stat-label">${usingAssessed ? "Assessed Value" : "Est. Market"}</div><div class="card-stat-val market">${fmtShort(marketVal)}</div></div>` : ""}
    </div>
    <div class="prop-links">
      ${fallbackStreetviewUrl(p) ? `<a href="${esc(fallbackStreetviewUrl(p))}" target="_blank" rel="noopener">${linkIcon("Street View")}Street View</a>` : ''}
      ${p.url_appraiser ? `<a href="${esc(p.url_appraiser)}" target="_blank" rel="noopener">${linkIcon("Appraiser")}Appraiser</a>` : ''}
      ${fallbackZillowUrl(p) ? `<a href="${esc(fallbackZillowUrl(p))}" target="_blank" rel="noopener">${linkIcon("Zillow")}Zillow</a>` : ''}
    </div>
    ${p.url_auction ? `<a class="cta-btn" href="${esc(p.url_auction)}" target="_blank" rel="noopener">${p.source === "laft" ? "View Lands Available Listing" : "Bid on County Auction Site"}</a>` : ''}
    <button class="detail-btn" data-action="viewdetails" data-pid="${p.id}" type="button">View full property page →</button>`;
  return el;
}

const CERT_SOON_DAYS = 90;
function certDaysUntil(dateStr) {
  if (!dateStr) return null;
  const raw = new Date(dateStr + "T00:00:00"); const d = isNaN(raw) ? raw : Date.UTC(raw.getFullYear(), raw.getMonth(), raw.getDate());
  if (isNaN(d)) return null;
  const t = new Date(); return Math.round((d - Date.UTC(t.getFullYear(), t.getMonth(), t.getDate())) / 86400000);
}

// Certificates are liens, not property - no address/owner/assessed/lien
// screening the way deed and LAFT rows have, but they do have a redemption
// clock (expiration_date) that matters more than anything else on the card.
function certCard(p, showCounty) {
  const el = document.createElement("div");
  const fav = FAVS.has(p.id);
  el.className = "prop-card cert-card" + (fav ? " favorited" : "");
  const tag = showCounty ? `<div class="prop-county-tag">${esc(p.county)} County - Certificate</div>` : "";
  const expDays = certDaysUntil(p.expiration_date);
  let cd = "";
  if (expDays !== null && expDays >= 0) {
    const cls = expDays <= 30 ? "urgent" : expDays <= CERT_SOON_DAYS ? "soon" : "";
    cd = `<span class="countdown ${cls}">${expDays === 0 ? "TODAY" : expDays + "d to expire"}</span>`;
  }

  // Same lean-card treatment as card() above: header, the amount, the
  // account #, and the one date that actually drives a decision (expiration
  // - a redeemed-or-not clock, more decision-relevant on a cert than the
  // issue date or tax year). Interest rate, issued date, tax year, and the
  // account-# copy button moved to the full property page.
  el.innerHTML = `
    ${tag}
    <div class="prop-top">
      <div class="prop-address">Certificate #${esc(p.certificate_no || "Unknown")}</div>
      <div class="prop-top-actions">
        <button class="icon-btn heart-btn${fav ? " on" : ""}" data-action="fav" data-pid="${p.id}" type="button" title="Favorite">${fav ? "♥" : "♡"}</button>
        ${bidListBtnHtml(p, true)}
        <button class="icon-btn remove-btn" data-action="hide" data-pid="${p.id}" type="button" title="Hide">✕</button>
        ${cd}
      </div>
    </div>
    <div class="card-stat-grid">
      <div class="card-stat"><div class="card-stat-label">Amount</div><div class="card-stat-val bid${hasPublishedBid(p) ? "" : " unpublished"}">${bidDisplay(p)}</div></div>
      <div class="card-stat"><div class="card-stat-label">Account #</div><div class="card-stat-val">${esc(p.case_no || "Unknown")}</div></div>
      <div class="card-stat"><div class="card-stat-label">Expires</div><div class="card-stat-val">${p.expiration_date ? fmtDate(p.expiration_date) : "N/A"}</div></div>
    </div>
    ${p.url_auction ? `<a class="cta-btn" href="${esc(p.url_auction)}" target="_blank" rel="noopener">View on County-Held Liens List</a>` : ''}
    <button class="detail-btn" data-action="viewdetails" data-pid="${p.id}" type="button">View full property page →</button>`;
  return el;
}

// ==================== property detail modal ("full property page") ====================
// Same underlying data as the card, laid out roomier with big tappable link
// buttons instead of the compact 3-across grid - triggered by the card's
// "View Full Property Page" button (data-action="viewdetails").
function detailHtml(p) {
  const isCert = p.source === "certificate";
  const fav = FAVS.has(p.id);
  const links = [
    ["Street View", fallbackStreetviewUrl(p)],
    ["Appraiser", p.url_appraiser],
    ["Zillow", fallbackZillowUrl(p)],
    ["Tax Collector", p.url_taxcoll],
    [p.source === "laft" ? "Lands Available Listing" : (isCert ? "County-Held Liens List" : "County Auction Site"), p.url_auction],
    ["Title Search", p.url_title],
    // Populated per-property by the harvesters (url_clerk/url_gis), same as
    // url_title/url_taxcoll above - not filled in yet for most counties, so
    // these simply won't render until that scraper work lands (see the
    // .filter() below).
    ["Clerk of Courts", p.url_clerk],
    ["GIS Map", p.url_gis]
  ].filter(([, href]) => href);
  const detailStreet = isCert ? "" : realAddress(p);
  const title = isCert ? `Certificate #${esc(p.certificate_no || "Unknown")}` :
    (detailStreet ? esc(detailStreet) : lotTitle(p));
  const bidPublished = hasPublishedBid(p);

  const stats = [];
  if (!isCert) {
    stats.push(["Opening Bid", bidDisplay(p)]);
    stats.push(["Assessed Value", p.assessed ? fmtShort(p.assessed) : "N/A"]);
    stats.push(["Market Value", p.market ? fmtShort(p.market) : "N/A"]);
    if (bidPublished) {
      stats.push(["Fees", fmtShort(fees(p))]);
      stats.push(["Walk Away Above", fmtShort(maxBid(p))]);
      if (marketOf(p) > 0) {
        const spreadAmt = marketOf(p) - Number(p.bid);
        stats.push(["Potential Equity", `${spreadAmt >= 0 ? "+" : "-"}${fmtShort(Math.abs(spreadAmt))} (${valueRatio(p).toFixed(1)}×)`]);
      }
    }
  } else {
    stats.push(["Amount", bidDisplay(p)]);
    if (p.interest_rate) stats.push(["Interest Rate", p.interest_rate + "%"]);
    stats.push(["Tax Year", p.tax_year || "N/A"]);
    stats.push(["Issued", p.issued_date ? fmtDate(p.issued_date) : "N/A"]);
    stats.push(["Expires", p.expiration_date ? fmtDate(p.expiration_date) : "N/A"]);
  }

  return `
    <button class="detail-close" data-action="closedetail" type="button">✕</button>
    <div class="prop-county-tag">${esc(p.county)} County${isCert ? " · Certificate" : (p.source === "laft" ? " · Lands Available" : " · Auction")}</div>
    <h2 class="detail-address">${title}</h2>
    <div class="prop-top-actions" style="margin:.2rem 0 .5rem">
      <button class="icon-btn heart-btn${fav ? " on" : ""}" data-action="fav" data-pid="${p.id}" type="button">${fav ? "♥ Favorited" : "♡ Favorite"}</button>
      ${bidListBtnHtml(p, false)}
      ${!isCert ? `<span class="pill ${esc(p.status)}">${esc(p.status)}</span>` : ""}
    </div>
    ${!isCert ? `<div class="lien-banner ${esc(p.lien_level)}">
      <div class="lien-toprow"><span class="lien-label">Title: ${LIEN_LABEL[p.lien_level] || p.lien_level}</span><span class="type-badge">${esc(p.prop_type || "Type: Unknown")}</span></div>
      <span class="lien-text">${esc(p.lien_note || "")}</span>
    </div>` : ""}
    <div class="detail-grid">
      ${stats.map(([label, val]) => `<div class="detail-stat"><span class="detail-stat-label">${esc(label)}${label === "Fees" ? " " + infoTip(FEES_TIP) : ""}</span><span class="detail-stat-val">${esc(val)}</span></div>`).join("")}
    </div>
    <div class="copy-row">
      ${!isCert ? `<button class="copy-btn owner-tag${p.owner_name ? "" : " unknown"}" ${p.owner_name ? `data-action="copy" data-copy="${esc(p.owner_name)}"` : ""} type="button"><span class="copy-tag">Owner</span><span class="copy-val">${esc(p.owner_name || "Unknown")}</span></button>` : ""}
      <button class="copy-btn" data-action="copy" data-copy="${esc(p.parcel || p.case_no || "")}" type="button"><span class="copy-tag">${isCert ? "Account" : "Parcel"}</span><span class="copy-val">${esc(p.parcel || p.case_no || "Unknown")}</span></button>
    </div>
    <div class="detail-links">
      ${links.length ? links.map(([label, href]) => `<a href="${esc(href)}" target="_blank" rel="noopener">${linkIcon(label)}${esc(label)} →</a>`).join("") : `<span style="font-size:.78rem;color:var(--ink-soft)">No reference links harvested for this property yet.</span>`}
    </div>
    ${noteHtml(p)}`;
}

// Both the detail modal and the bid list modal are fixed-position overlays
// that can be open at the same time (viewing a property's full page from
// inside the bid list) - background scroll should stay locked as long as
// EITHER one is open, not just whichever closed most recently.
function syncBodyScrollLock() {
  const detailOpen = !document.getElementById("detailModal")?.hidden;
  const bidListOpen = !document.getElementById("bidListModal")?.hidden;
  const hiddenModalOpen = !document.getElementById("hiddenModal")?.hidden;
  document.body.style.overflow = (detailOpen || bidListOpen || hiddenModalOpen) ? "hidden" : "";
}

function openDetail(p) {
  const modal = document.getElementById("detailModal");
  const inner = document.getElementById("detailModalInner");
  if (!modal || !inner) return;
  // .prop-card so the existing fav/hide/copy/savenote click delegation
  // (which looks for `.closest('.prop-card')`) keeps working inside the modal.
  inner.className = "detail-modal-inner prop-card";
  inner.innerHTML = detailHtml(p);
  modal.hidden = false;
  syncBodyScrollLock();
}
function closeDetail() {
  const modal = document.getElementById("detailModal");
  if (!modal) return;
  modal.hidden = true;
  syncBodyScrollLock();
}
// After a fav toggle, if this property's detail modal happens to be open,
// rebuild it so the heart icon reflects the change instead of going stale.
function refreshOpenDetail(pid) {
  const modal = document.getElementById("detailModal");
  if (!modal || modal.hidden) return;
  const p = ALL.find(x => x.id === pid);
  if (p) openDetail(p);
}
const detailModalEl = document.getElementById("detailModal");
if (detailModalEl) detailModalEl.addEventListener("click", e => { if (e.target === detailModalEl) closeDetail(); });

// ==================== "My Bid List" modal ====================
// A small, separate overlay (same structural pattern as the detail modal)
// listing just the up-to-BID_LIST_MAX properties someone has added to their
// bid list, most-recently-added first. Reuses card()/certCard() so a bid
// list row looks and behaves exactly like it does in the main ledger -
// same fav/hide/notes/links - plus the bid-list toggle to remove it here.
function bidListRows() {
  // Most-recently-added first; silently drops any id no longer in ALL
  // (e.g. a property the sync pipeline has since removed).
  return BIDLIST_ORDER.slice().reverse()
    .map(id => ALL.find(p => p.id === id))
    .filter(Boolean);
}
// Short human label for a pending-queue row - doesn't need to match the
// card's title logic exactly, just be recognizable at a glance.
function shortPropLabel(p) {
  if (p.source === "certificate") return `Certificate #${esc(p.certificate_no || "Unknown")}`;
  if (p.address && p.address.trim()) return esc(p.address);
  return `Parcel #${esc(p.parcel || "Unknown")} (${esc(p.county)} County)`;
}
function renderBidListModal() {
  const inner = document.getElementById("bidListModalInner");
  if (!inner) return;
  const rows = bidListRows();
  const pendingRows = BID_LIST_PENDING.map(id => ALL.find(p => p.id === id)).filter(Boolean);
  const countLabel = `${BIDLIST.size}/${BID_LIST_MAX}`;
  const listHtml = rows.length
    ? ""
    : `<div class="empty-state">Your bid list is empty. Click ⚐ on any property to save it here — up to ${BID_LIST_MAX}.</div>`;
  const pendingHtml = pendingRows.length ? `
    <div class="bidlist-pending">
      <div class="bidlist-pending-head">⏳ Waiting for a slot (${pendingRows.length}) - added automatically, oldest first, as you remove items above</div>
      ${pendingRows.map(p => `<div class="bidlist-pending-row"><span>${shortPropLabel(p)}</span><button class="reset-btn" data-action="bidlist" data-pid="${p.id}" type="button">Cancel</button></div>`).join("")}
    </div>` : "";
  inner.innerHTML = `
    <button class="detail-close" data-action="closebidlist" type="button">✕</button>
    <h2 class="detail-address" style="margin-top:.1rem">⚑ My Bid List <span style="color:var(--ink-soft);font-weight:600">(${countLabel})</span></h2>
    <p class="mega-sub" style="margin:0 0 .8rem">The short list of properties you're actually planning to bid on — separate from ♡ Favorites, capped at ${BID_LIST_MAX} to keep it focused.</p>
    ${listHtml}
    <div class="prop-list flat" id="bidListRows"></div>
    ${pendingHtml}`;
  const listEl = document.getElementById("bidListRows");
  if (listEl) rows.forEach(p => listEl.appendChild(p.source === "certificate" ? certCard(p, true) : card(p, true)));
}
function openBidList() {
  const modal = document.getElementById("bidListModal");
  if (!modal) return;
  renderBidListModal();
  modal.hidden = false;
  syncBodyScrollLock();
}
function closeBidList() {
  const modal = document.getElementById("bidListModal");
  if (!modal) return;
  modal.hidden = true;
  syncBodyScrollLock();
}
// After adding/removing a bid list item (from anywhere - a ledger card, the
// detail modal, or the bid list modal itself), rebuild the modal in place if
// it's currently open so it never shows a stale list.
function refreshBidListModal() {
  const modal = document.getElementById("bidListModal");
  if (!modal || modal.hidden) return;
  renderBidListModal();
}
// Called right after a bid list removal frees up a slot - adds queued
// properties (oldest attempt first) until either the queue is empty or the
// list is full again, so "the bid list was full when I clicked" resolves
// itself instead of requiring a repeat click.
async function promoteNextPending() {
  while (BID_LIST_PENDING.length && BIDLIST.size < BID_LIST_MAX) {
    const nextId = BID_LIST_PENDING.shift();
    if (BIDLIST.has(nextId)) continue; // already added some other way - skip
    const { error } = await sb.from("bid_list").insert({ user_id: ME.id, property_id: nextId });
    if (!error) { BIDLIST.add(nextId); BIDLIST_ORDER.push(nextId); }
    // On error, just drop this one and keep working through the rest of the
    // queue rather than getting stuck on it.
  }
}
const bidListModalEl = document.getElementById("bidListModal");
if (bidListModalEl) bidListModalEl.addEventListener("click", e => { if (e.target === bidListModalEl) closeBidList(); });
const bidListToggleBtn = document.getElementById("bidListToggle");
if (bidListToggleBtn) bidListToggleBtn.addEventListener("click", () => openBidList());

// ==================== "Hidden Properties" modal ====================
// Hiding a property (the ✕ button) used to be one-way per item - the only
// way back was "Restore all", which blindly un-hides everything at once
// with no way to see what you'd get back first. This gives every hidden
// property its own row so a mis-click is recoverable individually, while
// properties that are no longer active (sale date already passed, or the
// county's own listing dropped it and stayed gone past the grace period in
// goneExpired()) are shown but can't be restored - bringing one of those
// back would just have it filtered right back out, or worse, look like a
// still-live listing when it isn't.
function isRecoverable(p) {
  return !goneExpired(p) && !isPastDue(p);
}
function hiddenRows() {
  // Silently drops any id no longer in ALL (e.g. a property the sync
  // pipeline has since removed outright) - same convention as bidListRows().
  return Array.from(HIDDEN).map(id => ALL.find(p => p.id === id)).filter(Boolean);
}
function hiddenRow(p) {
  const el = document.createElement("div");
  const active = isRecoverable(p);
  el.className = "hidden-row" + (active ? "" : " inactive");
  const countyLine = `${esc(p.county)} County` + (p.sale_date ? " · " + fmtDate(p.sale_date) : "");
  const inactiveReason = isPastDue(p) ? "Sale date already passed" : "No longer listed by the county";
  el.innerHTML = `
    <div class="hidden-row-info">
      <span class="hidden-row-label">${shortPropLabel(p)}</span>
      <span class="hidden-row-meta">${countyLine}</span>
      ${active ? "" : `<span class="hidden-row-inactive-tag">${inactiveReason} - can't be restored</span>`}
    </div>
    ${active
      ? `<button class="reset-btn" data-action="restore" data-pid="${p.id}" type="button">Restore</button>`
      : `<span class="hidden-row-unavailable">Not active</span>`}`;
  return el;
}
function renderHiddenModal() {
  const inner = document.getElementById("hiddenModalInner");
  if (!inner) return;
  const rows = hiddenRows();
  const activeCount = rows.filter(isRecoverable).length;
  const listHtml = rows.length
    ? ""
    : `<div class="empty-state">Nothing hidden right now. Tap ✕ on any property to hide it - hidden properties show up here so you can bring one back if you hid it by mistake.</div>`;
  inner.innerHTML = `
    <button class="detail-close" data-action="closehidden" type="button">✕</button>
    <h2 class="detail-address" style="margin-top:.1rem">Hidden Properties <span style="color:var(--ink-soft);font-weight:600">(${rows.length})</span></h2>
    <p class="mega-sub" style="margin:0 0 .8rem">Properties you've hidden with ✕. Still-active ones can be brought back below; ones no longer active (sale date passed, or the county dropped the listing) can't be.</p>
    ${listHtml}
    <div class="hidden-list" id="hiddenListRows"></div>
    ${activeCount ? `<button class="reset-btn" id="restoreAllActiveBtn" type="button" style="margin-top:.7rem">Restore all active (${activeCount})</button>` : ""}`;
  const listEl = document.getElementById("hiddenListRows");
  if (listEl) rows.forEach(p => listEl.appendChild(hiddenRow(p)));
  const restoreAllBtn = document.getElementById("restoreAllActiveBtn");
  if (restoreAllBtn) restoreAllBtn.addEventListener("click", restoreAllActive);
}
function openHiddenModal() {
  const modal = document.getElementById("hiddenModal");
  if (!modal) return;
  renderHiddenModal();
  modal.hidden = false;
  syncBodyScrollLock();
}
function closeHiddenModal() {
  const modal = document.getElementById("hiddenModal");
  if (!modal) return;
  modal.hidden = true;
  syncBodyScrollLock();
}
// After a restore (single or "restore all active"), rebuild the modal in
// place if it's currently open so it never shows a stale list - same
// convention as refreshBidListModal().
function refreshHiddenModal() {
  const modal = document.getElementById("hiddenModal");
  if (!modal || modal.hidden) return;
  renderHiddenModal();
}
// Bulk-restores only the still-active hidden properties, leaving no-longer-
// active ones hidden (there'd be no point un-hiding something that's just
// going to get filtered right back out by goneExpired()/isPastDue()).
async function restoreAllActive() {
  if (!ME) return;
  const activeIds = hiddenRows().filter(isRecoverable).map(p => p.id);
  if (!activeIds.length) return;
  const btn = document.getElementById("restoreAllActiveBtn");
  if (btn) btn.disabled = true;
  const { error } = await sb.from("hidden").delete().eq("user_id", ME.id).in("property_id", activeIds);
  if (!error) {
    activeIds.forEach(id => HIDDEN.delete(id));
    render();
    refreshHiddenModal();
  } else { if (btn) btn.disabled = false; showErrorToast("Couldn't restore: " + error.message); }
}
const hiddenModalEl = document.getElementById("hiddenModal");
if (hiddenModalEl) hiddenModalEl.addEventListener("click", e => { if (e.target === hiddenModalEl) closeHiddenModal(); });
const hiddenListBtn = document.getElementById("hiddenListBtn");
if (hiddenListBtn) hiddenListBtn.addEventListener("click", () => openHiddenModal());

// Escape closes whichever overlay is on top - the detail modal, if it's the
// one currently open over the bid list / hidden modals, otherwise whichever
// of those two is open.
document.addEventListener("keydown", e => {
  if (e.key !== "Escape") return;
  const detailModal = document.getElementById("detailModal");
  if (detailModal && !detailModal.hidden) { closeDetail(); return; }
  const hiddenModal = document.getElementById("hiddenModal");
  if (hiddenModal && !hiddenModal.hidden) { closeHiddenModal(); return; }
  closeBidList();
});

// Card-level actions: favorite, hide, copy-to-clipboard, save note. Nothing
// wired these up before, so the buttons on the card were dead clicks.
document.addEventListener("click", async e => {
  const btn = e.target.closest("[data-action]");
  if (!btn) return;
  const action = btn.dataset.action;
  const pid = btn.dataset.pid;

  if (action === "fav") {
    if (!ME || !pid) return;
    btn.disabled = true;
    if (FAVS.has(pid)) {
      const { error } = await sb.from("favorites").delete().eq("user_id", ME.id).eq("property_id", pid);
      if (!error) FAVS.delete(pid); else showErrorToast("Couldn't update favorite: " + error.message);
    } else {
      const { error } = await sb.from("favorites").insert({ user_id: ME.id, property_id: pid });
      if (!error) FAVS.add(pid); else showErrorToast("Couldn't update favorite: " + error.message);
    }
    render();
    refreshOpenDetail(pid);
    refreshBidListModal();
  } else if (action === "hide") {
    if (!ME || !pid) return;
    // Hide used to fire on a single click with no confirmation - easy to fat-
    // finger on a phone. There's no per-property undo (only "restore all" via
    // the hidden-count panel), so a mis-click meant re-finding the property
    // in the full ledger to bring it back. A confirm() dialog is the cheapest
    // fix that actually stops the accidental click before it does anything.
    const hiddenProp = ALL.find(x => x.id === pid);
    const label = hiddenProp && hiddenProp.address ? `"${hiddenProp.address}"` : "this property";
    if (!window.confirm(`Hide ${label}? It'll disappear from every view here. You can bring it back later from the hidden-properties panel.`)) return;
    btn.disabled = true;
    const { error } = await sb.from("hidden").insert({ user_id: ME.id, property_id: pid });
    if (!error) { HIDDEN.add(pid); render(); closeDetail(); refreshHiddenModal(); } else { btn.disabled = false; showErrorToast("Couldn't hide: " + error.message); }
  } else if (action === "restore") {
    if (!ME || !pid) return;
    btn.disabled = true;
    const { error } = await sb.from("hidden").delete().eq("user_id", ME.id).eq("property_id", pid);
    if (!error) { HIDDEN.delete(pid); render(); refreshHiddenModal(); } else { btn.disabled = false; showErrorToast("Couldn't restore: " + error.message); }
  } else if (action === "bidlist") {
    if (!ME || !pid) return;
    if (BIDLIST.has(pid)) {
      // Remove - then immediately try to promote the oldest queued property
      // into the slot that just opened up, so "full" is never a dead end.
      btn.disabled = true;
      const { error } = await sb.from("bid_list").delete().eq("user_id", ME.id).eq("property_id", pid);
      if (!error) {
        BIDLIST.delete(pid); BIDLIST_ORDER = BIDLIST_ORDER.filter(id => id !== pid);
        await promoteNextPending();
      } else { showErrorToast("Couldn't update bid list: " + error.message); }
    } else if (BID_LIST_PENDING.includes(pid)) {
      // Already queued - a second click cancels the queued attempt instead
      // of queueing it again.
      BID_LIST_PENDING = BID_LIST_PENDING.filter(id => id !== pid);
    } else if (BIDLIST.size >= BID_LIST_MAX) {
      // Full: queue it rather than just discarding the click. It gets added
      // automatically, in the order people tried, as slots free up.
      BID_LIST_PENDING.push(pid);
    } else {
      btn.disabled = true;
      const { error } = await sb.from("bid_list").insert({ user_id: ME.id, property_id: pid });
      if (error) {
        // Server-side backstop (schema-v7-bidlist.sql's trigger) tripped -
        // most likely two tabs racing to fill the last slot at once. Queue
        // it instead of failing outright, same as the client-side full case.
        // Any OTHER error (network blip, RLS denial, etc.) isn't expected
        // and silently dropping it would leave someone tapping ⚐ with no
        // idea whether it worked - surface those.
        if (/full|limit/i.test(error.message || "")) BID_LIST_PENDING.push(pid);
        else showErrorToast("Couldn't add to bid list: " + error.message);
      } else { BIDLIST.add(pid); BIDLIST_ORDER.push(pid); }
    }
    render();
    refreshOpenDetail(pid);
    refreshBidListModal();
  } else if (action === "viewdetails") {
    if (!pid) return;
    const p = ALL.find(x => x.id === pid);
    if (p) openDetail(p);
  } else if (action === "closedetail") {
    closeDetail();
  } else if (action === "closebidlist") {
    closeBidList();
  } else if (action === "closehidden") {
    closeHiddenModal();
  } else if (action === "copy") {
    const val = btn.dataset.copy;
    if (!val) return;
    try {
      await navigator.clipboard.writeText(val);
      btn.classList.add("copied");
      setTimeout(() => btn.classList.remove("copied"), 1200);
    } catch { /* clipboard permission denied - fail quietly */ }
  } else if (action === "savenote") {
    if (!ME || !pid) return;
    const cardEl = btn.closest(".prop-card");
    if (!cardEl) return;
    const stageEl = cardEl.querySelector(`[data-role="stage"][data-pid="${pid}"]`);
    const bodyEl = cardEl.querySelector(`[data-role="body"][data-pid="${pid}"]`);
    const stage = stageEl ? stageEl.value : "";
    const body = bodyEl ? bodyEl.value.trim() : "";
    btn.disabled = true;
    const { error } = await sb.from("notes").upsert(
      { property_id: pid, author_id: ME.id, author_email: ME.email, stage, body },
      { onConflict: "property_id,author_id" }
    );
    if (error) { btn.disabled = false; showErrorToast("Couldn't save note: " + error.message); return; }
    const rows = NOTES[pid] || (NOTES[pid] = []);
    const mine = rows.find(n => n.author_id === ME.id);
    const now = new Date().toISOString();
    if (mine) { mine.stage = stage; mine.body = body; mine.updated_at = now; }
    else rows.push({ property_id: pid, author_id: ME.id, author_email: ME.email, stage, body, updated_at: now });
    btn.textContent = "Saved ✓";
    btn.classList.add("saved");
    setTimeout(render, 700);
  }
});

// Three separate ledgers (Auctions, Lands Available, Certificates), one
// visible at a time via the tab bar - not one long page where Lands
// Available sat under 300+ auction cards and read as "not populated"
// because nobody scrolled that far to find it.
function render() {
  const bidListCountEl = document.getElementById("bidListCount");
  if (bidListCountEl) bidListCountEl.textContent = `${BIDLIST.size}/${BID_LIST_MAX}` + (BID_LIST_PENDING.length ? ` +${BID_LIST_PENDING.length}⏳` : "");

  const main = document.getElementById("main"); if (!main) return; main.innerHTML = "";
  if (!LEDGERS[state.ledger]) state.ledger = "auction";
  const activeLedger = state.ledger;
  const cfg = LEDGERS[activeLedger];
  const inLedger = p => p.source === activeLedger;
  const { shown } = section(main, cfg.title, cfg.sub, ALL.filter(inLedger), activeLedger);

  const tabCounts = { auction: 0, laft: 0, certificate: 0 };
  ALL.forEach(p => { if (p.source in tabCounts) tabCounts[p.source]++; });
  document.querySelectorAll("#ledgerTabs .ledger-tab").forEach(btn => {
    const src = btn.dataset.ledger;
    btn.classList.toggle("on", src === activeLedger);
    const countEl = document.getElementById("tabCount" + src[0].toUpperCase() + src.slice(1));
    if (countEl) countEl.textContent = tabCounts[src] || 0;
  });

  // Expand/Collapse-all button label reflects whether every county currently
  // in view is already expanded.
  const expandAllBtn = document.getElementById("expandAllBtn");
  if (expandAllBtn) {
    const keysInLedger = new Set(shown.map(p => groupKeyOf(activeLedger, p.county, p.sale_date)));
    const allOpen = keysInLedger.size > 0 && Array.from(keysInLedger).every(k => state.expandedCounties.has(k));
    expandAllBtn.textContent = allOpen ? "Collapse all" : "Expand all";
    expandAllBtn.dataset.mode = allOpen ? "collapse" : "expand";
  }

  const chipTotal = document.getElementById("chipTotal");
  if (chipTotal) chipTotal.textContent = shown.length;

  // Active/Gone/Archive counts ignore the current statusView (and are
  // scoped to the active ledger, same as Shown) so every chip stays
  // meaningful no matter which one is currently selected.
  const savedView = state.statusView;
  state.statusView = "live";
  const activeCount = ALL.filter(inLedger).filter(passes).length;
  state.statusView = "gone";
  const goneCount = ALL.filter(inLedger).filter(passes).length;
  state.statusView = "archive";
  const archiveCount = ALL.filter(inLedger).filter(passes).length;
  state.statusView = savedView;
  const chipActive = document.getElementById("chipActive");
  if (chipActive) chipActive.textContent = activeCount;
  const chipGone = document.getElementById("chipGone");
  if (chipGone) chipGone.textContent = goneCount;
  const chipArchive = document.getElementById("chipArchive");
  if (chipArchive) chipArchive.textContent = archiveCount;
  document.querySelectorAll(".summary-strip .chip[data-status]").forEach(c => c.classList.toggle("on", c.dataset.status === state.statusView));

  const hiddenListBtn = document.getElementById("hiddenListBtn");
  if (hiddenListBtn) hiddenListBtn.hidden = HIDDEN.size === 0;

  const hiddenCount = document.getElementById("hiddenCount");
  if (hiddenCount) hiddenCount.textContent = HIDDEN.size;

  // Hand the just-rendered rows to the explore map (explore.js) - see the
  // contract note at the top of that file. `shown` is the exact filtered +
  // sorted set this list just drew, so the map can't disagree with the list
  // about what's in view - there is deliberately no second copy of
  // passes()/sortRows() over there to drift out of sync with this one.
  // Stashing before dispatching matters: both files are type="module" so
  // this one runs first, and if a render ever lands before explore.js has
  // finished loading, an event-only handoff would be dropped silently and
  // the map would sit empty until the next filter change.
  const rendered = { rows: shown, ledger: activeLedger, openDetail };
  window.__tdwLastRender = rendered;
  window.dispatchEvent(new CustomEvent("tdw:rendered", { detail: rendered }));
}

// Both the primary "Sort" dropdown and the secondary "Then by" tiebreaker
// dropdown pick from this same set of comparators, so a comparator added
// here (or a bug fixed here) automatically applies to both.
const SORT_COMPARATORS = {
  dateAsc: (a, b) => saleTime(a) - saleTime(b),
  dateDesc: (a, b) => saleTime(b) - saleTime(a),
  bidAsc: (a, b) => Number(a.bid || 0) - Number(b.bid || 0),
  bidDesc: (a, b) => Number(b.bid || 0) - Number(a.bid || 0),
  assessedAsc: (a, b) => Number(a.assessed || 0) - Number(b.assessed || 0),
  assessedDesc: (a, b) => Number(b.assessed || 0) - Number(a.assessed || 0),
  spreadDesc: (a, b) => valueRatio(b) - valueRatio(a),
  address: (a, b) => (a.address || "").localeCompare(b.address || "")
};

function sortRows(rows) {
  const primary = SORT_COMPARATORS[state.sortBy];
  const secondary = SORT_COMPARATORS[state.sortSecondary];
  // "county" (default) has no comparator of its own and keeps the query's
  // own county/case_no order - if no tiebreaker is set either, there's
  // nothing to sort by, so skip the copy+sort entirely (matches the old
  // no-secondary-sort behavior exactly).
  if (!primary && !secondary) return rows;
  return rows.slice().sort((a, b) => {
    if (primary) {
      const r = primary(a, b);
      if (r !== 0) return r;
    }
    return secondary ? secondary(a, b) : 0;
  });
}

// ==================== county grouping ====================
// Each ledger is organized into one collapsible <details> group (name, a
// date/format line, and an "N/M active" count) instead of one long flat
// card list - the structure a county with 300+ properties needs to stay
// scannable, and the reason Lands Available used to read as "not populated"
// when it was buried under an unbroken run of auction cards.
//
// Auctions additionally split each county into one group PER SALE DATE
// (instead of one group for the whole county) - a county running four
// auctions this month is four separate accordion rows, each labeled with
// its own date and its own "N/M active" count for just that date's cases.
// Before this, every date's properties were rolled into a single group
// labeled with only the earliest date, so the badge silently summed every
// upcoming auction while the label implied just one (e.g. Hillsborough
// showing "55/55 active - Auction Aug 20" when Aug 20 itself only had 14
// cases and the other 41 belonged to three other August dates).

// groupKeyOf identifies a distinct county-group: for auctions that's
// county+date (so each sale date gets its own row); every other ledger
// still has exactly one group per county, same as before.
function groupKeyOf(ledgerKey, county, date) {
  return ledgerKey === "auction" ? `${county}||${date || "TBD"}` : county;
}

// Lands Available and certificates don't run on a single county-wide date,
// so they get a static descriptor instead of a real date.
function groupSecondaryLine(ledgerKey, date) {
  if (ledgerKey === "auction") return date ? `Auction ${fmtDate(date)}` : "Date not yet scheduled";
  if (ledgerKey === "laft") return "Lands Available - fixed price, available now";
  return "County-held certificates";
}

// COUNTY_INFO carries per-county logistics (online vs in-person, deposit
// rules, quirks) that only matters once you've drilled into a specific
// county's auction - shown inside the open <details>, not on every card.
// Most entries use fmt as a short category tag ("Online", "In person",
// "Fixed price") with the specifics in note - but a few (Charlotte, Palm
// Beach, Hendry) cram a whole freeform sentence into fmt with no note at
// all. Detect that shape so those don't render as a giant run-on pill.
const KNOWN_FMT_TAGS = new Set(["Online", "In person", "Fixed price"]);
function countyInfoBannerHtml(county) {
  const info = COUNTY_INFO[county];
  if (!info) return "";
  const isTag = KNOWN_FMT_TAGS.has(info.fmt);
  const pillText = isTag ? info.fmt : "Note";
  const pillClass = "fmt-pill" + (info.fmt === "In person" ? " inperson" : "");
  const bodyText = isTag ? (info.note || "") : (info.fmt + (info.note ? " " + info.note : ""));
  return `<div class="county-info"><span class="${pillClass}">${esc(pillText)}</span><span>${esc(bodyText)}</span></div>`;
}

// Groups sort soonest-sale-first within each county for auctions (so the
// most time-sensitive date is the first thing an investor sees), then by
// county name; other ledgers just sort alphabetically by county.
function groupSortKey(ledgerKey, county, date) {
  if (ledgerKey === "auction") return `${date || "9999-99-99"}|${county}`;
  return county;
}

// Returns { shown } - shown is the FULL filtered+sorted list (used for the
// Shown/Active/Gone counts, the Expand/Collapse-all button, and CSV export).
function section(container, title, sub, rows, kind) {
  const sec = document.createElement("section"); sec.className = "mega-section";
  sec.innerHTML = `<div class="mega-head"><h2>${title}</h2><p class="mega-sub">${sub}</p></div>`;
  const shown = sortRows(rows.filter(passes));
  if (!shown.length) {
    const e = document.createElement("div"); e.className = "empty-state";
    e.textContent = state.search ? `Nothing found for "${state.search}".` : "Nothing found.";
    sec.appendChild(e); container.appendChild(sec);
    return { shown };
  }

  // Per-group "N/M active" ignores the current statusView, same trick the
  // Active/Gone summary chips use, so the badge stays meaningful no matter
  // which status filter is selected. Archive is the one exception: forcing
  // "all" there would flip passes() out of archive mode entirely and zero
  // out every group's badge, so stay in "archive" rather than "all" when
  // that's the active view.
  const savedView = state.statusView;
  state.statusView = savedView === "archive" ? "archive" : "all";
  const allForCounts = rows.filter(passes);
  state.statusView = savedView;
  const totalsByGroup = new Map(), activeByGroup = new Map();
  allForCounts.forEach(p => {
    const k = groupKeyOf(kind, p.county, p.sale_date);
    totalsByGroup.set(k, (totalsByGroup.get(k) || 0) + 1);
    if (!isGone(p)) activeByGroup.set(k, (activeByGroup.get(k) || 0) + 1);
  });

  const groups = new Map();
  shown.forEach(p => {
    const k = groupKeyOf(kind, p.county, p.sale_date);
    if (!groups.has(k)) groups.set(k, { county: p.county, date: p.sale_date, rows: [] });
    groups.get(k).rows.push(p);
  });

  const orderedKeys = Array.from(groups.keys()).sort((ka, kb) => {
    const ga = groups.get(ka), gb = groups.get(kb);
    const sa = groupSortKey(kind, ga.county, ga.date), sb = groupSortKey(kind, gb.county, gb.date);
    if (sa !== sb) return sa < sb ? -1 : 1;
    return ga.county.localeCompare(gb.county);
  });

  const renderCard = kind === "certificate" ? certCard : card;
  // Auctions are grouped by county+date (see groupKeyOf above); a date
  // header inserted whenever the date changes turns a run of same-day
  // counties into one visually distinct cluster instead of every county
  // repeating its own small "Auction {date}" line with nothing higher-level
  // separating one sale date from the next.
  let lastDividerDate;
  const showDateDividers = kind === "auction";
  orderedKeys.forEach(key => {
    const { county, date, rows: countyRows } = groups.get(key);
    const total = totalsByGroup.get(key) ?? countyRows.length;
    const active = activeByGroup.get(key) ?? countyRows.length;

    if (showDateDividers && date !== lastDividerDate) {
      lastDividerDate = date;
      const divider = document.createElement("div");
      divider.className = "date-divider";
      divider.textContent = date ? fmtDateLong(date) : "Date not yet scheduled";
      sec.appendChild(divider);
    }

    // A search in progress auto-opens every group that has a match, so
    // results are visible immediately instead of hiding behind a collapse.
    const isOpen = !!state.search || state.expandedCounties.has(key);

    const det = document.createElement("details");
    det.className = "county-group";
    det.dataset.county = county;
    det.dataset.groupKey = key;
    if (isOpen) det.open = true;

    const summary = document.createElement("summary");
    summary.className = "county-head";
    const freshness = getGroupFreshness(countyRows);
    const freshnessBadge = freshness.timestamp ?
      `<span class="freshness-badge ${freshness.isStale ? 'stale' : 'fresh'}" title="Last synced ${new Date(freshness.timestamp).toLocaleString()}">
         ${freshness.isStale ? '⚠ Stale' : '✓ Fresh'} (${freshness.hours}h ago)
       </span>` : '';
    summary.innerHTML = `
      <div>
        <div class="county-name">${esc(county)}</div>
        <div class="county-meta">${esc(groupSecondaryLine(kind, date))}</div>
      </div>
      <div class="county-right">
        ${freshnessBadge}
        <span class="county-count">${active}/${total} active</span>
        <span class="county-chevron"></span>
      </div>`;
    det.appendChild(summary);

    if (kind === "auction") {
      const bannerHtml = countyInfoBannerHtml(county);
      if (bannerHtml) det.insertAdjacentHTML("beforeend", bannerHtml);
    }

    // Cards are built only for groups that are actually open. Every render
    // used to construct the full card DOM for all 67 counties even though
    // most sat inside a collapsed <details> nobody was looking at - thousands
    // of nodes per keystroke. A collapsed group now gets an empty .prop-list
    // and keeps its rows on the element; the "toggle" listener below fills it
    // in the first time the user opens it.
    const list = document.createElement("div"); list.className = "prop-list";
    if (isOpen) {
      countyRows.forEach(p => list.appendChild(renderCard(p, false)));
    } else {
      det._tdwRows = countyRows;
      det._tdwRenderCard = renderCard;
    }
    det.appendChild(list);

    sec.appendChild(det);
  });

  container.appendChild(sec);
  return { shown };
}

function updateBadge() {
  let n = 0;
  if (state.search) n++;
  if (state.bidMin || state.bidMax || state.assessedMin) n++;
  if (state.sortBy !== "county") n++;
  if (state.sortSecondary) n++;
  if (state.favoritesOnly || state.topPicksOnly || state.soonOnly || state.hideOldListings) n++;
  if (state.statusView !== "all") n++;
  if (state.maxBidPct !== 40) n++;
  if (state.counties.size !== ALL_COUNTIES.length) n++;
  if (state.types.size !== TYPE_ORDER.length) n++;
  if (state.liens.size !== LIEN_ORDER.length) n++;
  const b = document.getElementById("filtersBadge");
  if (b) { b.textContent = n; b.hidden = n === 0; }
}

// ==================== filters panel wiring ====================
// None of this existed before: the whole panel (toggle, inputs, sort,
// checkboxes, reset, status chips, hidden-restore, group buttons, theme,
// install, and the county map) rendered but did nothing on click/change.

let mapLoaded = false;

// ---- ledger tabs (Auctions / Lands Available / Certificates) ----
document.querySelectorAll("#ledgerTabs .ledger-tab[data-ledger]").forEach(btn => {
  btn.addEventListener("click", () => {
    if (state.ledger === btn.dataset.ledger) return;
    state.ledger = btn.dataset.ledger;
    render();
  });
});

// ---- quick controls: search, county dropdown, expand/collapse all, CSV export ----
const searchInputEl = document.getElementById("searchInput");
if (searchInputEl) {
  // Every keystroke used to trigger a full filter + sort + group + re-card of
  // the entire ledger, which on a phone showed up as the search box lagging
  // behind the typing. A short trailing debounce folds a burst of keystrokes
  // into one render. The value is read when the timer fires, not when it's
  // set, so a programmatic clear (Reset filters) can't be undone by a
  // still-pending keystroke.
  let searchTimer = null;
  searchInputEl.addEventListener("input", () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => {
      const v = searchInputEl.value.trim();
      if (v === state.search) return;
      state.search = v;
      updateBadge();
      render();
    }, 200);
  });
}

const countyQuickEl = document.getElementById("countyQuick");
if (countyQuickEl) countyQuickEl.addEventListener("change", () => {
  const v = countyQuickEl.value;
  state.counties = v === "ALL" ? new Set(ALL_COUNTIES) : new Set([v]);
  // Picking one specific county is a strong signal the user wants to see
  // straight into it, not just narrow the filter and leave it collapsed.
  // Auctions can have several date-groups for the same county, so expand
  // every one of them, not just a single "county" key.
  if (v !== "ALL") {
    const keys = new Set([v]);
    ALL.forEach(p => { if (p.county === v) keys.add(groupKeyOf(p.source, v, p.sale_date)); });
    keys.forEach(k => state.expandedCounties.add(k));
  }
  buildAllChips();
  if (mapLoaded) { refreshMapPaths(); if (zoomedCounty) zoomToState(); }
  updateBadge();
  render();
});

// County groups are native <details> - the browser handles the actual
// show/hide. We only need to mirror the open state into expandedCounties so
// a county the user expanded stays expanded across the next full re-render
// (every filter/search/sort change rebuilds #main from scratch). "toggle"
// doesn't bubble, so this listener has to run in the capture phase.
const mainEl = document.getElementById("main");
if (mainEl) mainEl.addEventListener("toggle", e => {
  const det = e.target;
  if (!det.classList || !det.classList.contains("county-group")) return;
  const key = det.dataset.groupKey || det.dataset.county;
  if (!key) return;
  if (det.open) state.expandedCounties.add(key); else state.expandedCounties.delete(key);

  // Hydrate a lazily-rendered group the first time it opens (see render()).
  if (det.open && det._tdwRows) {
    const list = det.querySelector(".prop-list");
    if (list && !list.children.length) {
      const frag = document.createDocumentFragment();
      det._tdwRows.forEach(p => frag.appendChild(det._tdwRenderCard(p, false)));
      list.appendChild(frag);
    }
    det._tdwRows = null;
    det._tdwRenderCard = null;
  }
}, true);

const expandAllBtn = document.getElementById("expandAllBtn");
if (expandAllBtn) expandAllBtn.addEventListener("click", () => {
  const inLedger = p => p.source === state.ledger;
  const keysInLedger = new Set(ALL.filter(inLedger).filter(passes).map(p => groupKeyOf(state.ledger, p.county, p.sale_date)));
  if (expandAllBtn.dataset.mode === "collapse") keysInLedger.forEach(k => state.expandedCounties.delete(k));
  else keysInLedger.forEach(k => state.expandedCounties.add(k));
  render();
});

// CSV export - everything currently matching the active ledger's filters
// (not just the visible page), so it's a complete export regardless of
// pagination.
const exportCsvBtn = document.getElementById("exportCsvBtn");
if (exportCsvBtn) exportCsvBtn.addEventListener("click", () => {
  const inLedger = p => p.source === state.ledger;
  const rows = sortRows(ALL.filter(inLedger).filter(passes));
  if (!rows.length) return;
  const cols = [
    ["County", p => p.county],
    ["Source", p => p.source],
    ["Address", p => p.address || ""],
    ["Parcel", p => p.parcel || ""],
    ["Case/Account #", p => p.case_no || ""],
    ["Owner", p => p.owner_name || ""],
    ["Status", p => p.status || ""],
    ["Property Type", p => p.prop_type || ""],
    ["Title Status", p => LIEN_LABEL[p.lien_level] || p.lien_level || ""],
    ["Opening Bid", p => p.bid ?? ""],
    ["Assessed Value", p => p.assessed ?? ""],
    ["Market Value", p => p.market ?? ""],
    ["Potential Equity ($)", p => (p.bid != null && marketOf(p) > 0) ? Math.round(marketOf(p) - Number(p.bid)) : ""],
    ["Potential Equity (x bid)", p => (Number(p.bid) > 0 && marketOf(p) > 0) ? valueRatio(p).toFixed(2) : ""],
    ["Fees", p => p.bid != null ? Math.round(fees(p)) : ""],
    ["Sale/Auction Date", p => p.sale_date || ""],
    ["Certificate #", p => p.certificate_no || ""],
    ["Tax Year", p => p.tax_year || ""],
    ["Issued Date", p => p.issued_date || ""],
    ["Expiration Date", p => p.expiration_date || ""],
    ["Interest Rate", p => p.interest_rate ?? ""],
    ["Street View", p => fallbackStreetviewUrl(p)],
    ["Appraiser", p => p.url_appraiser || ""],
    ["Zillow", p => fallbackZillowUrl(p)],
    ["Tax Collector", p => p.url_taxcoll || ""],
    ["Auction/LAFT Listing", p => p.url_auction || ""],
    ["Title Search", p => p.url_title || ""]
  ];
  const csvEscape = v => { const s = String(v ?? ""); return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s; };
  const lines = [cols.map(c => csvEscape(c[0])).join(",")];
  rows.forEach(p => lines.push(cols.map(c => csvEscape(c[1](p))).join(",")));
  const blob = new Blob([lines.join("\r\n")], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  const stamp = new Date().toISOString().slice(0, 10);
  a.href = url; a.download = `taxdeed-${state.ledger}-${stamp}.csv`;
  document.body.appendChild(a); a.click(); document.body.removeChild(a);
  URL.revokeObjectURL(url);
});

// ---- open/close ----
const filtersToggleBtn = document.getElementById("filtersToggle");
const filtersPanelEl = document.getElementById("filtersPanel");
if (filtersToggleBtn && filtersPanelEl) {
  filtersToggleBtn.addEventListener("click", () => {
    filtersPanelEl.classList.toggle("open");
    filtersToggleBtn.classList.toggle("open");
  });
}

// ---- range sliders for bid filtering ----
function bindBidRangeSliders() {
  const minSlider = document.getElementById("bidMin");
  const maxSlider = document.getElementById("bidMax");
  const minDisplay = document.getElementById("bidMinDisplay");
  const maxDisplay = document.getElementById("bidMaxDisplay");

  if (!minSlider || !maxSlider) return;

  function updateBidRange() {
    const min = Number(minSlider.value);
    const max = Number(maxSlider.value);

    if (min > max) {
      minSlider.value = max;
    }

    state.bidMin = min > 0 ? min : null;
    state.bidMax = max < 1000000 ? max : null;

    if (minDisplay) minDisplay.textContent = min > 0 ? fmtMoney(min) : "$0";
    if (maxDisplay) maxDisplay.textContent = max < 1000000 ? fmtMoney(max) : "Any";

    // Update CSS variables for slider track fill
    const percent1 = (min / 1000000) * 100;
    const percent2 = (max / 1000000) * 100;
    minSlider.style.setProperty("--value1", percent1 + "%");
    minSlider.style.setProperty("--value2", percent2 + "%");
    maxSlider.style.setProperty("--value1", percent1 + "%");
    maxSlider.style.setProperty("--value2", percent2 + "%");

    updateBadge();
    render();
  }

  minSlider.addEventListener("input", updateBidRange);
  maxSlider.addEventListener("input", updateBidRange);

  // Initialize display
  updateBidRange();
}
bindBidRangeSliders();

// ---- number inputs ----
function bindNumber(id, key, fallback) {
  const el = document.getElementById(id);
  if (!el) return;
  el.addEventListener("input", () => {
    const v = el.value.trim();
    state[key] = v === "" ? (fallback === undefined ? null : fallback) : Number(v);
    updateBadge();
    render();
  });
}
bindNumber("assessedMin", "assessedMin");
bindNumber("maxBidPct", "maxBidPct", 40);

// ---- sort ----
const sortByEl = document.getElementById("sortBy");
if (sortByEl) sortByEl.addEventListener("change", () => { state.sortBy = sortByEl.value; updateBadge(); render(); });
const sortSecondaryEl = document.getElementById("sortSecondary");
if (sortSecondaryEl) sortSecondaryEl.addEventListener("change", () => { state.sortSecondary = sortSecondaryEl.value; updateBadge(); render(); });

// ---- checkboxes ----
function bindCheckbox(id, key) {
  const el = document.getElementById(id);
  if (!el) return;
  el.addEventListener("change", () => { state[key] = el.checked; updateBadge(); render(); });
}
bindCheckbox("favOnly", "favoritesOnly");
bindCheckbox("topOnly", "topPicksOnly");
bindCheckbox("soonOnly", "soonOnly");
bindCheckbox("hideOldOnly", "hideOldListings");
bindCheckbox("qtToggle", "includeQT");

// ---- reset ----
const resetBtn = document.getElementById("resetBtn");
if (resetBtn) resetBtn.addEventListener("click", () => {
  state.bidMin = null; state.bidMax = null; state.assessedMin = null;
  state.sortBy = "county"; state.sortSecondary = ""; state.favoritesOnly = false; state.topPicksOnly = false;
  state.soonOnly = false; state.hideOldListings = false; state.includeQT = false; state.maxBidPct = 40;
  state.statusView = "all"; state.search = "";
  state.counties = new Set(ALL_COUNTIES); state.types = new Set(TYPE_ORDER); state.liens = new Set(LIEN_ORDER);
  state.expandedCounties.clear();

  const bidMinEl = document.getElementById("bidMin");
  const bidMaxEl = document.getElementById("bidMax");
  if (bidMinEl) { bidMinEl.value = "0"; bidMinEl.style.setProperty("--value1", "0%"); }
  if (bidMaxEl) { bidMaxEl.value = "1000000"; bidMaxEl.style.setProperty("--value2", "100%"); }
  const minDisplayEl = document.getElementById("bidMinDisplay");
  const maxDisplayEl = document.getElementById("bidMaxDisplay");
  if (minDisplayEl) minDisplayEl.textContent = "$0";
  if (maxDisplayEl) maxDisplayEl.textContent = "Any";
  const assessedMinEl = document.getElementById("assessedMin");
  if (assessedMinEl) assessedMinEl.value = "";
  const maxBidEl = document.getElementById("maxBidPct"); if (maxBidEl) maxBidEl.value = "40";
  const sortEl = document.getElementById("sortBy"); if (sortEl) sortEl.value = "county";
  const sortSecEl = document.getElementById("sortSecondary"); if (sortSecEl) sortSecEl.value = "";
  ["favOnly", "topOnly", "soonOnly", "hideOldOnly", "qtToggle"].forEach(id => { const el = document.getElementById(id); if (el) el.checked = false; });
  const searchEl = document.getElementById("searchInput"); if (searchEl) searchEl.value = "";

  buildAllChips();
  if (mapLoaded) { refreshMapPaths(); if (zoomedCounty) zoomToState(); }
  updateBadge();
  render();
});

// ---- status summary chips (Shown / Active / Gone) ----
document.querySelectorAll(".summary-strip .chip[data-status]").forEach(c => {
  c.addEventListener("click", () => { state.statusView = c.dataset.status; render(); });
});

// ---- hidden properties: view & restore ----
// The old blind "Restore all" button (no way to see what you'd get back, and
// no way to restore just one) has been replaced by hiddenListBtn opening the
// Hidden Properties modal - see the "Hidden Properties" modal section above
// for openHiddenModal/restoreAllActive/the per-item "restore" click action.

// ---- group all/none mini-buttons (types / liens / counties) ----
document.querySelectorAll(".mini-btn[data-group]").forEach(btn => {
  btn.addEventListener("click", () => {
    const group = btn.dataset.group, mode = btn.dataset.mode;
    const setRef = group === "types" ? state.types : group === "liens" ? state.liens : state.counties;
    const values = group === "types" ? TYPE_ORDER : group === "liens" ? LIEN_ORDER : ALL_COUNTIES;
    setRef.clear();
    if (mode === "all") values.forEach(v => setRef.add(v));
    buildAllChips();
    if (group === "counties" && mapLoaded) refreshMapPaths();
    updateBadge();
    render();
  });
});

// ---- Florida county map ----
const mapBtnEl = document.getElementById("mapBtn");
const mapWrapEl = document.getElementById("mapWrap");
const mapHostEl = document.getElementById("mapHost");
function refreshMapPaths() {
  if (!mapHostEl) return;
  const withData = new Set(countyNames());
  mapHostEl.querySelectorAll("path[data-county]").forEach(p => {
    const name = p.dataset.county;
    const fmt = COUNTY_FORMAT[name];
    const hasData = withData.has(name);
    p.classList.toggle("has-data", hasData);
    p.classList.toggle("sel", state.counties.has(name));
    // Color by confirmed auction format (independent of whether we currently
    // have any properties loaded for that county) - blue/red/amber cover every
    // county whose format we've confirmed; unconfirmed ones stay neutral gray.
    p.classList.toggle("fmt-online", fmt === "online");
    p.classList.toggle("fmt-inperson", fmt === "in-person");
    p.classList.toggle("fmt-fixed", fmt === "fixed");
    const fmtLabel = fmt === "online" ? "Online auction" : fmt === "in-person" ? "In-person auction" : fmt === "fixed" ? "Fixed price only" : "Format not yet confirmed";
    const countLabel = hasData ? " - currently tracking properties here" : " - no properties currently tracked";
    let titleEl = p.querySelector("title");
    if (!titleEl) { titleEl = document.createElementNS("http://www.w3.org/2000/svg", "title"); p.appendChild(titleEl); }
    titleEl.textContent = `${name}: ${fmtLabel}${countLabel}`;
  });
}
// Major Florida cities for map labels, shown only at the state-wide zoom
// level (see zoomToCounty()/zoomToState() below, which hide this group and
// swap in a single county-seat label instead). Coordinates are in the SVG's
// own user-space units (fl-counties.svg's viewBox is "0 0 1000 960") rather
// than percentages - percentage resolution on <text> x/y isn't guaranteed
// to track a changing viewBox the way plain numbers do, and this map now
// changes its viewBox on every zoom.
const FLORIDA_CITIES = [
  { name: "Miami", x: 880, y: 883.2, size: "large" },
  { name: "Tampa", x: 280, y: 624, size: "large" },
  { name: "Jacksonville", x: 680, y: 172.8, size: "large" },
  { name: "Orlando", x: 550, y: 480, size: "medium" },
  { name: "Fort Lauderdale", x: 850, y: 844.8, size: "medium" },
  { name: "Tallahassee", x: 320, y: 115.2, size: "small" },
  { name: "Saint Petersburg", x: 250, y: 672, size: "small" },
];

// County seat (or best-known primary city) for each of the 67 counties -
// used as the "then show cities" label once a tap zooms into a county (see
// zoomToCounty() below). Cross-checked 1:1 against ALL_COUNTIES so every
// county the filter/map knows about has a matching seat here.
const COUNTY_SEATS = {
  "Alachua": "Gainesville", "Baker": "Macclenny", "Bay": "Panama City",
  "Bradford": "Starke", "Brevard": "Titusville", "Broward": "Fort Lauderdale",
  "Calhoun": "Blountstown", "Charlotte": "Punta Gorda", "Citrus": "Inverness",
  "Clay": "Green Cove Springs", "Collier": "Naples", "Columbia": "Lake City",
  "DeSoto": "Arcadia", "Dixie": "Cross City", "Duval": "Jacksonville",
  "Escambia": "Pensacola", "Flagler": "Bunnell", "Franklin": "Apalachicola",
  "Gadsden": "Quincy", "Gilchrist": "Trenton", "Glades": "Moore Haven",
  "Gulf": "Port St. Joe", "Hamilton": "Jasper", "Hardee": "Wauchula",
  "Hendry": "LaBelle", "Hernando": "Brooksville", "Highlands": "Sebring",
  "Hillsborough": "Tampa", "Holmes": "Bonifay", "Indian River": "Vero Beach",
  "Jackson": "Marianna", "Jefferson": "Monticello", "Lafayette": "Mayo",
  "Lake": "Tavares", "Lee": "Fort Myers", "Leon": "Tallahassee",
  "Levy": "Bronson", "Liberty": "Bristol", "Madison": "Madison",
  "Manatee": "Bradenton", "Marion": "Ocala", "Martin": "Stuart",
  "Miami-Dade": "Miami", "Monroe": "Key West", "Nassau": "Fernandina Beach",
  "Okaloosa": "Crestview", "Okeechobee": "Okeechobee", "Orange": "Orlando",
  "Osceola": "Kissimmee", "Palm Beach": "West Palm Beach", "Pasco": "Dade City",
  "Pinellas": "Clearwater", "Polk": "Bartow", "Putnam": "Palatka",
  "Santa Rosa": "Milton", "Sarasota": "Sarasota", "Seminole": "Sanford",
  "St. Johns": "St. Augustine", "St. Lucie": "Fort Pierce", "Sumter": "Bushnell",
  "Suwannee": "Live Oak", "Taylor": "Perry", "Union": "Lake Butler",
  "Volusia": "DeLand", "Wakulla": "Crawfordville", "Walton": "DeFuniak Springs",
  "Washington": "Chipley"
};

// Populated once per map load from each county path's real getBBox() (see
// computeCountyCentroids()) rather than hand-placed coordinates - works for
// all 67 shapes without needing per-county tuning, at the cost of an
// occasional label that lands slightly off for a very non-convex county
// (Monroe's Keys chain being the main one) since a bounding-box center
// isn't always inside the polygon itself.
let countyCentroids = new Map();
let baseViewBox = null;
let zoomedCounty = null;

function computeCountyCentroids() {
  countyCentroids.clear();
  if (!mapHostEl) return;
  mapHostEl.querySelectorAll("path[data-county]").forEach(p => {
    try {
      const b = p.getBBox();
      countyCentroids.set(p.dataset.county, { cx: b.x + b.width / 2, cy: b.y + b.height / 2, bbox: b });
    } catch { /* not rendered yet (e.g. panel opened while hidden) - that
                 county just won't get a seat label until the next reopen */ }
  });
}

// Animates the SVG's viewBox attribute between two [x,y,w,h] arrays.
// viewBox isn't CSS-transitionable on its own, so this hand-rolls the tween
// with a plain rAF loop instead of pulling in an animation library for one
// effect.
function tweenViewBox(svg, from, to, duration = 320) {
  const start = (typeof performance !== "undefined" ? performance.now() : Date.now());
  function step(now) {
    const t = Math.min(1, (now - start) / duration);
    const eased = 1 - Math.pow(1 - t, 3);
    const cur = from.map((v, i) => v + (to[i] - v) * eased);
    svg.setAttribute("viewBox", cur.join(" "));
    if (t < 1) requestAnimationFrame(step);
  }
  requestAnimationFrame(step);
}

function currentViewBoxOf(svg) {
  const raw = svg.getAttribute("viewBox");
  return (raw ? raw.split(/\s+/).map(Number) : baseViewBox).slice();
}

// Renders (or clears) the single county-seat dot+label shown only while
// zoomed - see the comment on countyCentroids above for why this is
// centroid-based instead of a hand-placed coordinate per county.
function renderZoomSeatLabel(svg, name) {
  const ns = "http://www.w3.org/2000/svg";
  let g = svg.querySelector(".zoom-seat-label");
  if (!g) { g = document.createElementNS(ns, "g"); g.setAttribute("class", "zoom-seat-label"); svg.appendChild(g); }
  g.innerHTML = "";
  const c = countyCentroids.get(name);
  if (!c) return;
  const dot = document.createElementNS(ns, "circle");
  dot.setAttribute("cx", c.cx); dot.setAttribute("cy", c.cy); dot.setAttribute("r", 4);
  dot.setAttribute("class", "seat-dot");
  g.appendChild(dot);
  const seat = COUNTY_SEATS[name];
  if (seat) {
    const text = document.createElementNS(ns, "text");
    text.setAttribute("x", c.cx);
    text.setAttribute("y", c.cy - 12);
    text.setAttribute("class", "seat-label-text");
    text.textContent = seat;
    g.appendChild(text);
  }
}

// Zooms the map into one county, names it in the banner above the map, and
// swaps the state-wide city labels for that county's own seat label - the
// concrete fix for "the map filter needs to be clearer, you can't see the
// name": the name now only lives in an always-visible banner instead of an
// SVG <title> hover tooltip that a touch device would never trigger.
function zoomToCounty(name) {
  const svg = mapHostEl && mapHostEl.querySelector("svg");
  const path = mapHostEl && mapHostEl.querySelector(`path[data-county="${name}"]`);
  if (!svg || !path || !baseViewBox) return;
  const c = countyCentroids.get(name);
  const bbox = c ? c.bbox : path.getBBox();

  // Pad well beyond the county's own bbox so neighboring counties stay
  // partly visible for context, and give tiny counties (Union, Gilchrist)
  // a sane minimum window instead of an absurd pixel-tight crop.
  const pad = Math.max(bbox.width, bbox.height) * 0.6 + 40;
  let x = bbox.x - pad, y = bbox.y - pad;
  let w = bbox.width + pad * 2, h = bbox.height + pad * 2;

  // Keep the same aspect ratio as the full-state view so the panel never
  // looks squashed mid-zoom.
  const aspect = baseViewBox[2] / baseViewBox[3];
  if (w / h > aspect) { const nh = w / aspect; y -= (nh - h) / 2; h = nh; }
  else { const nw = h * aspect; x -= (nw - w) / 2; w = nw; }

  // Never zoom OUT past the full state, and never pan past its edges.
  w = Math.min(w, baseViewBox[2]); h = Math.min(h, baseViewBox[3]);
  x = Math.max(baseViewBox[0], Math.min(x, baseViewBox[0] + baseViewBox[2] - w));
  y = Math.max(baseViewBox[1], Math.min(y, baseViewBox[1] + baseViewBox[3] - h));

  tweenViewBox(svg, currentViewBoxOf(svg), [x, y, w, h]);
  zoomedCounty = name;

  const cityLabels = svg.querySelector(".city-labels");
  if (cityLabels) cityLabels.style.display = "none";
  renderZoomSeatLabel(svg, name);

  const banner = document.getElementById("mapZoomBanner");
  const nameEl = document.getElementById("mapZoomName");
  const hint = document.getElementById("mapHint");
  const seat = COUNTY_SEATS[name];
  if (nameEl) nameEl.textContent = name + " County" + (seat ? " · " + seat : "");
  if (banner) banner.hidden = false;
  if (hint) hint.hidden = true;
}

// Reverses zoomToCounty() - back to the full 67-county state view.
function zoomToState() {
  const svg = mapHostEl && mapHostEl.querySelector("svg");
  if (!svg || !baseViewBox) return;
  tweenViewBox(svg, currentViewBoxOf(svg), baseViewBox);
  zoomedCounty = null;

  const cityLabels = svg.querySelector(".city-labels");
  if (cityLabels) cityLabels.style.display = "";
  const seatG = svg.querySelector(".zoom-seat-label");
  if (seatG) seatG.innerHTML = "";

  const banner = document.getElementById("mapZoomBanner");
  const hint = document.getElementById("mapHint");
  if (banner) banner.hidden = true;
  if (hint) hint.hidden = false;
}

async function ensureMapLoaded() {
  if (mapLoaded || !mapHostEl) return;
  try {
    const res = await fetch("fl-counties.svg");
    mapHostEl.innerHTML = await res.text();

    // Add city labels as SVG text elements
    const svg = mapHostEl.querySelector("svg");
    if (svg) {
      baseViewBox = (svg.getAttribute("viewBox") || "0 0 1000 960").split(/\s+/).map(Number);
      const ns = "http://www.w3.org/2000/svg";
      const g = document.createElementNS(ns, "g");
      g.setAttribute("class", "city-labels");

      FLORIDA_CITIES.forEach(city => {
        const text = document.createElementNS(ns, "text");
        text.setAttribute("x", city.x);
        text.setAttribute("y", city.y);
        text.setAttribute("text-anchor", "middle");
        text.setAttribute("class", `city-label city-${city.size}`);
        text.setAttribute("data-city", city.name);
        text.textContent = city.name;
        g.appendChild(text);
      });

      svg.appendChild(g);
    }

    mapLoaded = true;
    refreshMapPaths();
    computeCountyCentroids();
    // Every county is clickable now, not just has-data ones (see the CSS
    // comment above #mapHost path) - a first tap on any county zooms in and
    // names it; a second tap on the SAME county while already zoomed toggles
    // the filter, and only then only if it actually has data to filter to.
    // Tapping a different county while zoomed just re-zooms to that one.
    mapHostEl.addEventListener("click", e => {
      const path = e.target.closest("path[data-county]");
      if (!path) return;
      const name = path.dataset.county;
      if (zoomedCounty === name) {
        if (path.classList.contains("has-data")) toggleCounty(name);
      } else {
        zoomToCounty(name);
      }
    });
  } catch { /* offline or fetch blocked - map picker just stays closed */ }
}
const mapZoomOutBtnEl = document.getElementById("mapZoomOutBtn");
if (mapZoomOutBtnEl) mapZoomOutBtnEl.addEventListener("click", () => zoomToState());

if (mapBtnEl && mapWrapEl) {
  mapBtnEl.addEventListener("click", async () => {
    mapWrapEl.hidden = !mapWrapEl.hidden;
    if (!mapWrapEl.hidden) {
      await ensureMapLoaded();
      refreshMapPaths();
      if (!countyCentroids.size) computeCountyCentroids();
    } else if (zoomedCounty) {
      // Closing the panel while zoomed - reset so reopening starts fresh
      // at the full-state view instead of picking up mid-zoom.
      zoomToState();
    }
  });
}

// ---- theme (auto -> light -> dark, persisted) ----
const THEME_KEY = "tdw_theme";
const THEME_CYCLE = ["auto", "light", "dark"];
const THEME_ICON = { auto: "☼", light: "☀", dark: "☾" };
const THEME_LABEL = { auto: "Auto", light: "Light", dark: "Dark" };
function applyTheme(mode) {
  if (mode === "light" || mode === "dark") document.documentElement.setAttribute("data-theme", mode);
  else document.documentElement.removeAttribute("data-theme");
  const icon = document.getElementById("themeIcon"); if (icon) icon.textContent = THEME_ICON[mode] || THEME_ICON.auto;
  const label = document.getElementById("themeLabel"); if (label) label.textContent = THEME_LABEL[mode] || THEME_LABEL.auto;
}
let themeMode = "auto";
try { themeMode = localStorage.getItem(THEME_KEY) || "auto"; } catch { /* private mode - fall back to auto */ }
applyTheme(themeMode);
const themeBtnEl = document.getElementById("themeBtn");
if (themeBtnEl) themeBtnEl.addEventListener("click", () => {
  themeMode = THEME_CYCLE[(THEME_CYCLE.indexOf(themeMode) + 1) % THEME_CYCLE.length];
  try { localStorage.setItem(THEME_KEY, themeMode); } catch { /* private mode - just won't persist */ }
  applyTheme(themeMode);
});

if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("sw.js").catch(() => {});
  });
}

// ---- install button ----
// installBtn exists in the HTML (starts hidden) but nothing ever showed it
// or handled a click - the captured beforeinstallprompt event just sat
// unused. Now it un-hides the button and the click actually triggers it.
let deferredInstallPrompt = null;
const installBtnEl = document.getElementById("installBtn");
window.addEventListener("beforeinstallprompt", e => {
  e.preventDefault();
  deferredInstallPrompt = e;
  if (installBtnEl) installBtnEl.hidden = false;
});
if (installBtnEl) installBtnEl.addEventListener("click", async () => {
  if (!deferredInstallPrompt) return;
  installBtnEl.hidden = true;
  deferredInstallPrompt.prompt();
  await deferredInstallPrompt.userChoice;
  deferredInstallPrompt = null;
});
window.addEventListener("appinstalled", () => {
  if (installBtnEl) installBtnEl.hidden = true;
  deferredInstallPrompt = null;
});
// ============ change password modal ============
// Reuses the .detail-modal shell pattern already used by detailModal/bidListModal.
// Flow: re-verify the current password via signInWithPassword() before calling
// sb.auth.updateUser() - a plain updateUser() alone would let anyone using an
// already-open signed-in session change the password without proving they
// know the existing one.
(function () {
  const openBtn = document.getElementById("changePasswordBtn");
  const modal = document.getElementById("changePasswordModal");
  const closeBtn = document.getElementById("changePasswordCloseBtn");
  const form = document.getElementById("changePasswordForm");
  const msgEl = document.getElementById("cpMsg");
  const submitBtn = document.getElementById("cpSubmitBtn");
  if (!openBtn || !modal || !form) return;

  function showMsg(text, isErr) {
    if (!msgEl) return;
    msgEl.textContent = text || "";
    msgEl.className = "auth-msg" + (isErr ? " err" : "");
  }

  function openModal() {
    form.reset();
    showMsg("", false);
    modal.hidden = false;
  }

  function closeModal() {
    modal.hidden = true;
    form.reset();
    showMsg("", false);
  }

  openBtn.addEventListener("click", openModal);
  if (closeBtn) closeBtn.addEventListener("click", closeModal);
  modal.addEventListener("click", (e) => {
    if (e.target === modal) closeModal();
  });

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (!ME || !ME.email) {
      showMsg("You must be signed in to change your password.", true);
      return;
    }
    const current = document.getElementById("cpCurrent").value;
    const next = document.getElementById("cpNew").value;
    const confirm = document.getElementById("cpConfirm").value;

    if (next.length < 6) {
      showMsg("New password must be at least 6 characters.", true);
      return;
    }
    if (next !== confirm) {
      showMsg("New password and confirmation do not match.", true);
      return;
    }

    if (submitBtn) submitBtn.disabled = true;
    showMsg("Verifying current password...", false);

    try {
      const { error: verifyErr } = await sb.auth.signInWithPassword({
        email: ME.email,
        password: current,
      });
      if (verifyErr) {
        showMsg("Current password is incorrect.", true);
        if (submitBtn) submitBtn.disabled = false;
        return;
      }

      showMsg("Updating password...", false);
      const { error: updateErr } = await sb.auth.updateUser({ password: next });
      if (updateErr) {
        showMsg(updateErr.message || "Could not update password.", true);
        if (submitBtn) submitBtn.disabled = false;
        return;
      }

      showMsg("Password updated successfully.", false);
      setTimeout(closeModal, 1500);
    } catch (err) {
      showMsg((err && err.message) || "Unexpected error updating password.", true);
    } finally {
      if (submitBtn) submitBtn.disabled = false;
    }
  });
})();
