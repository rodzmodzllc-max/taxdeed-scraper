// Research screen (screening-v1) - investor discovery on top of the complete
// source inventory. Pure functions, no DOM, no network: app.js imports it, and
// harvesters/screening/rules.py mirrors it line for line. The shared vectors in
// tests/python/fixtures/screening_cases.json pin both (pytest runs this file
// through node). Change the two together and bump SCREENING_VERSION.
//
// What this is NOT: a score, an estimate, a return, or a judgement that a
// property is bad. Every reason below cites a field the row already carries
// and the evidence that field comes from; a reason without evidence is never
// emitted, and missing data is reported as missing - never as a defect.
// Screening only decides what the List PROMOTES by default. Nothing is
// hidden permanently: "All inventory" and any search show every row, each
// labelled with why it was not promoted. Full rationale and the measured
// distributions behind each threshold: docs/investor-screening.md.

export const SCREENING_VERSION = "screening-v1";

// Thresholds. Each one is documented with the production measurement it
// rests on (docs/investor-screening.md section 3). PROVISIONAL thresholds
// only ever move a row to REVIEW - they never stop it being promoted.
export const SCREENING_DEFAULTS = Object.freeze({
  // Below 0.01 acre (about 435 sq ft, roughly 21 x 21 ft). Under the 1st
  // percentile of active FL auction parcels (0.015 ac, 2026-10-04). Applied
  // as LIMITED only when the source itself says the parcel is vacant land.
  tinyAcres: 0.01,
  // PROVISIONAL: under the 5th percentile of active FL auction parcels
  // (0.063 ac). REVIEW only - no zoning data exists to justify more.
  smallAcres: 0.05,
  // PROVISIONAL: a county/tax-roll value under $1,000 (4 of 945 valued
  // active FL auction rows). REVIEW only.
  lowValue: 1000,
  // The published opening / minimum bid or price meets or exceeds the
  // county's own value. A fact about two published numbers. REVIEW only.
  bidHighRatio: 1.0,
  // Informational: the bid is under 10% of the county value (common - an FL
  // opening bid is the delinquent taxes plus costs).
  bidLowRatio: 0.10
});

export const CLASSIFICATIONS = Object.freeze([
  "PRIORITY_REVIEW", "REVIEW", "LIMITED_OPPORTUNITY", "HIGH_RISK_REVIEW", "INSUFFICIENT_DATA"
]);
// What the List shows by default: rows with enough information and no
// evidence of a problem. The other three are one click away and counted.
export const DEFAULT_DISCOVERY = Object.freeze(["PRIORITY_REVIEW", "REVIEW"]);
// Ledgers the screen applies to. A tax certificate is a lien instrument, not
// a parcel offered for sale - it is not screened in v1 (NOT_SCREENED).
export const SCREENED_SOURCES = Object.freeze(["auction", "laft"]);

export const CLASSIFICATION_LABELS = Object.freeze({
  PRIORITY_REVIEW: "Research candidate",
  REVIEW: "Needs review",
  LIMITED_OPPORTUNITY: "Limited opportunity",
  HIGH_RISK_REVIEW: "High-risk review",
  INSUFFICIENT_DATA: "Insufficient data",
  NOT_SCREENED: "Not screened"
});

// severity: limited -> LIMITED_OPPORTUNITY, risk -> HIGH_RISK_REVIEW,
// review -> keeps a row out of PRIORITY_REVIEW only, info -> shown, no effect.
export const REASON_LABELS = Object.freeze({
  POSSIBLE_RIGHT_OF_WAY: "Possible right-of-way",
  DRAINAGE_INDICATOR: "Drainage / waste-land indicator",
  UTILITY_INDICATOR: "Utility indicator",
  COMMON_AREA_INDICATOR: "Common-area indicator",
  SUBMERGED_LAND_INDICATOR: "Submerged-land indicator",
  SUBSURFACE_RIGHTS_ONLY: "Subsurface rights only",
  POSSIBLE_EASEMENT: "Possible easement",
  STRIP_DESCRIPTION: "Described as a strip of land",
  NOT_A_BUILDING_SITE: "Described as not a building site",
  BUYER_ELIGIBILITY_RESTRICTED: "Buyer eligibility restricted",
  TINY_PARCEL: "Tiny parcel",
  SMALL_ACREAGE: "Small acreage",
  LOW_JUST_VALUE: "Low county value",
  OPENING_BID_HIGH_RELATIVE_TO_VALUE: "Bid at or above county value",
  OPENING_BID_LOW_RELATIVE_TO_VALUE: "Bid low relative to county value",
  PARCEL_MISSING: "Parcel number missing",
  ACREAGE_MISSING: "Acreage missing",
  VALUE_DATA_MISSING: "County value missing",
  PROPERTY_CLASS_UNKNOWN: "Property class unknown",
  INSUFFICIENT_DATA: "Insufficient data"
});

// Florida DOR property-use codes (Rule 12D-8.008, F.A.C.; FDOR NAL/SDF user
// guide), as stored in properties.dor_use_code by the FDOR enrichment. Each
// is the county property appraiser's own classification of the parcel.
const FL_DOR_FLAGS = {
  "09": ["COMMON_AREA_INDICATOR", "Residential common elements / areas"],
  "91": ["UTILITY_INDICATOR", "Utility, pipelines, canals, communication"],
  "93": ["SUBSURFACE_RIGHTS_ONLY", "Subsurface rights"],
  "94": ["POSSIBLE_RIGHT_OF_WAY", "Right-of-way, streets, roads, irrigation channel, ditch"],
  "95": ["SUBMERGED_LAND_INDICATOR", "Rivers and lakes, submerged lands"],
  "96": ["DRAINAGE_INDICATOR", "Sewage disposal, solid waste, borrow pits, drainage reservoirs, waste land, marsh, swamps"]
};
// DOR codes that name vacant land, and the ranges that name an improved
// use. 50-69 (agricultural) and 90-99 (miscellaneous) say neither.
const FL_DOR_VACANT = new Set(["00", "10", "40", "70", "80", "99"]);
const flDorImproved = c => { const n = Number(c); return !FL_DOR_VACANT.has(c) && ((n >= 1 && n <= 49) || (n >= 71 && n <= 89)); };

// Detroit Land Bank's own program wording (docs/available-publication-
// evidence.md): a Side Lot is sold only to the owner-occupant of the
// adjacent residential property.
const RESTRICTED_PROGRAMS = {
  mi_detroit_landbank_lots: { "Side Lot For Sale": "Detroit Land Bank side lot: sold only to the owner-occupant of the adjacent home" }
};
// Source program wording that states the property class (vacant lot vs a
// structure), for sources that publish no land-use column.
const PROGRAM_CLASS = {
  mi_detroit_landbank_lots: {
    "Neighborhood Lot For Sale": "vacant", "Side Lot For Sale": "vacant",
    "Oversized Lot For Sale": "vacant", "Marketed Lot For Sale": "vacant",
    "Marketed Structure For Sale": "improved"
  }
};

// Legal-description indicators - only wording that DESIGNATES the parcel as
// one of these things. A right-of-way or drainage canal named as a boundary
// ("ALG R/W", "NORTH OF THE DRAINAGE CANAL", "MEAS 50 FT ON INTERSTATE R/W")
// is not evidence about the parcel and is deliberately not matched; neither
// is a lot sold "& STRIP" (an addition to a lot). Measured against every
// matching production legal description on 2026-10-04 (docs/investor-
// screening.md section 4). A match counts only when no qualifier that
// excludes it from the parcel or grants it as an appurtenance sits in the
// same clause within the preceding 40 characters ("LESS R/W", "SUBJ TO
// EASEMENT", "TOGETHER WITH ... COMMON ELEMENTS", "LOTS 23 & 24 & STRIP").
// `lead`: the designation must open the description (first 40 characters)
// or stand in parentheses - a strip mentioned deep in a long description is
// usually a piece added to or taken from a lot.
const LEGAL_TEXT_FLAGS = [
  ["COMMON_AREA_INDICATOR", /COMMON (?:AREAS?|GROUNDS?|ELEMENTS?)\b/g, false],
  ["NOT_A_BUILDING_SITE", /\bNOT A BUILDING SITE\b|\bNON[- ]?BUILDABLE\b|\bUNBUILDABLE\b/g, false],
  ["DRAINAGE_INDICATOR", /\b(?:RETENTION|DETENTION) (?:POND|AREA|BASIN)\b|\bDRAINAGE (?:EASEMENT|R\/W|RIGHT[ -]OF[ -]WAY|SERVITUDE|AREA|TRACT|POND|RESERVE)\b|\bDRAINAGE\s*$/g, false],
  ["POSSIBLE_EASEMENT", /\b(?:DRAINAGE|UTILITY|ACCESS|INGRESS(?:\/| AND )EGRESS) EASEMENT\b|\bEASEMENT (?:ONLY|AREA|PARCEL|TRACT)\b/g, false],
  ["UTILITY_INDICATOR", /\b(?:LIFT|PUMP) STATION\b|\bWELL SITE\b|\bUTILITY (?:STRIP|PARCEL|TRACT|SITE)\b/g, false],
  ["POSSIBLE_RIGHT_OF_WAY", /\bABAN(?:DONED|D)?\.? (?:RR |RAILROAD )?(?:R\/W|RIGHT[ -]OF[ -]WAY)|(?:R\/W|RIGHT[ -]OF[ -]WAY) (?:ABANDONED|VACATED)\b|\bUNDEDICATED\b/g, false],
  ["STRIP_DESCRIPTION", /\bSTRIP\b/g, true]
];
const NEGATORS = /(?:\b(?:LESS|EX|EXC|EXCEPT|EXCEPTING|SUBJ|SUBJECT|TOGETHER|WITH|PLUS|INT|INTEREST|ALSO|AND|RESERVING)\b|&)/;

const num = v => (v === null || v === undefined || v === "" || !isFinite(Number(v))) ? null : Number(v);
const text = v => (v === null || v === undefined) ? "" : String(v).trim();

export function hasParcelId(p) {
  const v = text(p && p.parcel);
  return !!v && !/^(unknown|n\/?a|none|null)$/i.test(v);
}

// Acreage, the source's own figure when present, else derived from the lot
// square footage on the same tax roll. 0 is a no-data sentinel on FDOR.
export function acreageOf(p) {
  const a = num(p.acreage);
  if (a !== null && a > 0) return { acres: a, basis: "acreage" };
  const sq = num(p.lot_sqft);
  if (sq !== null && sq > 0) return { acres: sq / 43560, basis: "lot_sqft" };
  return { acres: null, basis: null };
}

// The county value: FL "just value" / the state's market figure, else the
// assessed figure the source publishes. Labelled by basis, never merged.
export function valueOf(p) {
  const m = num(p.market);
  if (m !== null && m > 0) return { value: m, basis: "market" };
  const a = num(p.assessed);
  if (a !== null && a > 0) return { value: a, basis: "assessed" };
  return { value: null, basis: null };
}

// The published opening / minimum bid or purchase price. An amount whose
// kind the source does not state is not an opening bid (amountWord() in
// app.js), and NOT_PUBLISHED is never an amount.
export function amountOf(p) {
  if (p.purchase_amount_kind === "NOT_PUBLISHED") return { amount: null, basis: null };
  if (p.purchase_amount_kind === "PUBLISHED_AMOUNT_KIND_UNSPECIFIED") return { amount: null, basis: null };
  const pa = num(p.purchase_amount);
  if (pa !== null && pa > 0) return { amount: pa, basis: "purchase_amount" };
  const mb = num(p.min_bid);
  if (mb !== null && mb > 0) return { amount: mb, basis: "min_bid" };
  const b = num(p.bid);
  if (b !== null && b > 0) return { amount: b, basis: "bid" };
  return { amount: null, basis: null };
}

function dorCode(p) {
  if (text(p.state || "FL") !== "FL") return "";
  const c = text(p.dor_use_code);
  return /^\d{1,2}$/.test(c) ? c.padStart(2, "0") : "";
}

// What the source says the property is: "vacant", "improved" or "" (unknown).
export function occupancyOf(p) {
  const prog = PROGRAM_CLASS[p.source_id];
  if (prog && prog[text(p.inventory_status_raw)]) return prog[text(p.inventory_status_raw)];
  if ((num(p.num_buildings) || 0) > 0 || (num(p.living_area) || 0) > 0 || (num(p.improvement_value) || 0) > 0 || (num(p.year_built) || 0) > 0) return "improved";
  const dor = dorCode(p);
  if (dor) return FL_DOR_VACANT.has(dor) ? "vacant" : flDorImproved(dor) ? "improved" : "";
  const lu = (text(p.land_use) + " " + text(p.prop_type)).toLowerCase();
  if (/\bvacant\b|\blot\b|\bland\b/.test(lu)) return "vacant";
  if (/\bbuilding\b|\bimproved\b|\bstructure\b|\bhouse\b|\bcondo\b|single family|residence/.test(lu)) return "improved";
  return "";
}

export function hasPropertyClass(p) {
  if (dorCode(p)) return true;
  if (text(p.land_use) || text(p.prop_type)) return true;
  const prog = PROGRAM_CLASS[p.source_id];
  return !!(prog && prog[text(p.inventory_status_raw)]);
}

function legalTextReasons(p) {
  const legal = text(p.legal_desc).toUpperCase();
  if (!legal) return [];
  const out = [];
  for (const [code, re, lead] of LEGAL_TEXT_FLAGS) {
    re.lastIndex = 0;
    let m;
    while ((m = re.exec(legal))) {
      if (lead && m.index >= 40 && !(legal[m.index - 1] === "(" && legal[m.index + m[0].length] === ")")) continue;
      const before = legal.slice(Math.max(0, m.index - 40), m.index);
      // Only the current clause: stop at the last sentence / clause break.
      const clause = before.split(/[.;,]/).pop();
      if (!NEGATORS.test(clause)) { out.push({ code, term: m[0] }); break; }
    }
  }
  return out;
}

function round(v, d) { const f = Math.pow(10, d); return Math.round(v * f) / f; }

// Screen one row. Returns a plain object, deterministic for a given row and
// options: { version, classification, promoted, reasons:[{code, severity,
// evidence}], metrics, geometry, access }.
export function screenProperty(p, opts) {
  const o = Object.assign({}, SCREENING_DEFAULTS, opts || {});
  const base = { version: SCREENING_VERSION, geometry: "GEOMETRY_NOT_AVAILABLE", access: "ACCESS_UNKNOWN" };
  if (!p || !SCREENED_SOURCES.includes(p.source)) {
    return Object.assign(base, { classification: "NOT_SCREENED", promoted: true, reasons: [], metrics: {} });
  }
  const reasons = [];
  const add = (code, severity, evidence) => {
    if (!reasons.some(r => r.code === code && r.severity === severity)) reasons.push({ code, severity, evidence });
  };

  const { acres, basis: acreBasis } = acreageOf(p);
  const { value, basis: valueBasis } = valueOf(p);
  const { amount, basis: amountBasis } = amountOf(p);
  const occupancy = occupancyOf(p);
  const dor = dorCode(p);

  // 1. Source classification evidence (LIMITED).
  if (dor && FL_DOR_FLAGS[dor]) add(FL_DOR_FLAGS[dor][0], "limited", `FL DOR use code ${dor} (${FL_DOR_FLAGS[dor][1]})`);
  const restricted = RESTRICTED_PROGRAMS[p.source_id] && RESTRICTED_PROGRAMS[p.source_id][text(p.inventory_status_raw)];
  if (restricted) add("BUYER_ELIGIBILITY_RESTRICTED", "limited", restricted);

  // 2. Size. Never on an improved property (a condo unit's land share is tiny
  // by design), and LIMITED only when the source says the parcel is vacant.
  if (acres !== null && occupancy !== "improved") {
    const acresTxt = `${round(acres, 4)} ac${acreBasis === "lot_sqft" ? " (from lot sq ft)" : ""}`;
    if (acres < o.tinyAcres) {
      add("TINY_PARCEL", occupancy === "vacant" ? "limited" : "review",
        `${acresTxt}, under ${o.tinyAcres} ac${occupancy === "vacant" ? "; vacant land per source" : "; vacancy not established"}`);
    } else if (acres < o.smallAcres) {
      add("SMALL_ACREAGE", "review", `${acresTxt}, under ${o.smallAcres} ac (provisional threshold)`);
    }
  }

  // 3. Legal-description wording (HIGH_RISK_REVIEW: text is weaker evidence
  // than the appraiser's own use code).
  legalTextReasons(p).forEach(r => add(r.code, "risk", `Legal description contains "${r.term}"`));

  // 4. Value and bid facts.
  if (value !== null && value < o.lowValue) add("LOW_JUST_VALUE", "review", `County value $${Math.round(value).toLocaleString("en-US")} under $${o.lowValue.toLocaleString("en-US")} (provisional threshold)`);
  const metrics = {
    acres: acres === null ? null : round(acres, 4), acresBasis: acreBasis,
    value, valueBasis, amount, amountBasis,
    bidToValue: null, valueToBid: null, valueSpread: null, pricePerAcre: null, valuePerAcre: null
  };
  if (value !== null && amount !== null) {
    metrics.bidToValue = round(amount / value, 4);
    metrics.valueToBid = round(value / amount, 2);
    metrics.valueSpread = round(value - amount, 2);
    if (amount / value >= o.bidHighRatio) add("OPENING_BID_HIGH_RELATIVE_TO_VALUE", "review", `Published amount is ${round(amount / value, 2)}x the county value`);
    else if (amount / value < o.bidLowRatio) add("OPENING_BID_LOW_RELATIVE_TO_VALUE", "info", `Published amount is ${round(amount / value * 100, 1)}% of the county value`);
  }
  if (acres !== null && acres > 0) {
    if (amount !== null) metrics.pricePerAcre = round(amount / acres, 2);
    if (value !== null) metrics.valuePerAcre = round(value / acres, 2);
  }

  // 5. Missing research fields (REVIEW). Missing is never a defect.
  const parcel = hasParcelId(p), cls = hasPropertyClass(p);
  if (!parcel) add("PARCEL_MISSING", "review", "No parcel number in the source row");
  if (acres === null) add("ACREAGE_MISSING", "review", "No acreage or lot size on file");
  if (value === null) add("VALUE_DATA_MISSING", "review", "No county / tax-roll value on file");
  if (!cls) add("PROPERTY_CLASS_UNKNOWN", "review", "No use code, land use or property type on file");

  let classification;
  if (reasons.some(r => r.severity === "limited")) classification = "LIMITED_OPPORTUNITY";
  else if (reasons.some(r => r.severity === "risk")) classification = "HIGH_RISK_REVIEW";
  else if (!parcel || (value === null && acres === null && !cls)) {
    classification = "INSUFFICIENT_DATA";
    add("INSUFFICIENT_DATA", "review", !parcel ? "No parcel number to research the property by" : "No value, size or property class on file");
  } else if (reasons.some(r => r.severity === "review")) classification = "REVIEW";
  else classification = "PRIORITY_REVIEW";

  return Object.assign(base, { classification, promoted: DEFAULT_DISCOVERY.includes(classification), reasons, metrics });
}

// The reasons that explain why a row is not promoted (or why it is REVIEW),
// most significant first - for one-line display.
const SEVERITY_ORDER = { limited: 0, risk: 1, review: 2, info: 3 };
export function keyReasons(result) {
  return (result.reasons || []).filter(r => r.severity !== "info")
    .slice().sort((a, b) => SEVERITY_ORDER[a.severity] - SEVERITY_ORDER[b.severity]);
}

// The investor's own buy box, applied ON TOP of the screen. Every criterion
// that reads a field the row does not carry fails closed for "require"
// options and for ranges ("no acreage on file" is not "at least 1 acre").
export const BUY_BOX_DEFAULTS = Object.freeze({
  minAcres: null, maxAcres: null, minValue: null, maxAmount: null, maxBidToValue: null,
  requireParcel: false, requireAcreage: false, requireValue: false, requireClass: false
});
export function passesBuyBox(p, result, box) {
  const b = Object.assign({}, BUY_BOX_DEFAULTS, box || {});
  const m = result.metrics || {};
  if (b.minAcres !== null && !(m.acres !== null && m.acres !== undefined && m.acres >= b.minAcres)) return false;
  if (b.maxAcres !== null && !(m.acres !== null && m.acres !== undefined && m.acres <= b.maxAcres)) return false;
  if (b.minValue !== null && !(m.value !== null && m.value !== undefined && m.value >= b.minValue)) return false;
  if (b.maxAmount !== null && !(m.amount !== null && m.amount !== undefined && m.amount <= b.maxAmount)) return false;
  if (b.maxBidToValue !== null && !(m.bidToValue !== null && m.bidToValue !== undefined && m.bidToValue <= b.maxBidToValue)) return false;
  if (b.requireParcel && !hasParcelId(p)) return false;
  if (b.requireAcreage && (m.acres === null || m.acres === undefined)) return false;
  if (b.requireValue && (m.value === null || m.value === undefined)) return false;
  if (b.requireClass && !hasPropertyClass(p)) return false;
  return true;
}
