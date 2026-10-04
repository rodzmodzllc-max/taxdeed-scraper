-- screening-v1 measurement (READ-ONLY). A SQL port of public/screening.js
-- used only to MEASURE how production inventory would classify; nothing is
-- written. The legal-description rules are ported with regexp_instr (PG 15+):
-- every occurrence of a designation pattern is checked for a negating
-- qualifier in the same clause within the preceding 40 characters, and the
-- `lead` patterns must open the description or stand in parentheses - the
-- same rule as public/screening.js. (ARE: \y is a word boundary.)
-- Scope: active rows (status active/available) of the screened ledgers.
with r as (
  select p.*,
    case when state = 'FL' and dor_use_code ~ '^\d{1,2}$' then lpad(dor_use_code, 2, '0') else '' end dor,
    case when acreage > 0 then acreage when lot_sqft > 0 then lot_sqft / 43560.0 end acres,
    case when market > 0 then market when assessed > 0 then assessed end val,
    case when purchase_amount_kind in ('NOT_PUBLISHED', 'PUBLISHED_AMOUNT_KIND_UNSPECIFIED') then null
         when purchase_amount > 0 then purchase_amount when min_bid > 0 then min_bid when bid > 0 then bid end amt,
    (nullif(trim(parcel), '') is not null and trim(parcel) !~* '^(unknown|n/?a|none|null)$') has_parcel
  from public.properties p
  where source in ('auction', 'laft') and status in ('active', 'available')
), o as (
  select r.*,
    case
      when source_id = 'mi_detroit_landbank_lots' and inventory_status_raw in ('Neighborhood Lot For Sale','Side Lot For Sale','Oversized Lot For Sale','Marketed Lot For Sale') then 'vacant'
      when source_id = 'mi_detroit_landbank_lots' and inventory_status_raw = 'Marketed Structure For Sale' then 'improved'
      when coalesce(num_buildings,0) > 0 or coalesce(living_area,0) > 0 or coalesce(improvement_value,0) > 0 or coalesce(year_built,0) > 0 then 'improved'
      when dor in ('00','10','40','70','80','99') then 'vacant'
      when dor <> '' and ((dor::int between 1 and 49) or (dor::int between 71 and 89)) then 'improved'
      when dor <> '' then ''
      when lower(coalesce(land_use,'') || ' ' || coalesce(prop_type,'')) ~ '\m(vacant|lot|land)\M' then 'vacant'
      when lower(coalesce(land_use,'') || ' ' || coalesce(prop_type,'')) ~ '(\m(building|improved|structure|house|condo)\M|single family|residence)' then 'improved'
      else '' end occ,
    (dor <> '' or nullif(trim(land_use),'') is not null or nullif(trim(prop_type),'') is not null
      or (source_id = 'mi_detroit_landbank_lots' and inventory_status_raw in ('Neighborhood Lot For Sale','Side Lot For Sale','Oversized Lot For Sale','Marketed Lot For Sale','Marketed Structure For Sale'))) has_class,
    case when upper(coalesce(legal_desc, '')) ~ '(COMMON|BUILD|DRAINAGE|RETENTION|DETENTION|EASEMENT|STATION|WELL SITE|UTILITY|ABAN|UNDEDICATED|STRIP)' then
    (select array_agg(distinct pat.code) from (values
        ('COMMON_AREA_INDICATOR', 'COMMON (?:AREAS?|GROUNDS?|ELEMENTS?)\y', false),
        ('NOT_A_BUILDING_SITE', '\yNOT A BUILDING SITE\y|\yNON[- ]?BUILDABLE\y|\yUNBUILDABLE\y', false),
        ('DRAINAGE_INDICATOR', '\y(?:RETENTION|DETENTION) (?:POND|AREA|BASIN)\y|\yDRAINAGE (?:EASEMENT|R/W|RIGHT[ -]OF[ -]WAY|SERVITUDE|AREA|TRACT|POND|RESERVE)\y|\yDRAINAGE\s*$', false),
        ('POSSIBLE_EASEMENT', '\y(?:DRAINAGE|UTILITY|ACCESS|INGRESS(?:/| AND )EGRESS) EASEMENT\y|\yEASEMENT (?:ONLY|AREA|PARCEL|TRACT)\y', false),
        ('UTILITY_INDICATOR', '\y(?:LIFT|PUMP) STATION\y|\yWELL SITE\y|\yUTILITY (?:STRIP|PARCEL|TRACT|SITE)\y', false),
        ('POSSIBLE_RIGHT_OF_WAY', '\yABAN(?:DONED|D)?\.? (?:RR |RAILROAD )?(?:R/W|RIGHT[ -]OF[ -]WAY)|(?:R/W|RIGHT[ -]OF[ -]WAY) (?:ABANDONED|VACATED)\y|\yUNDEDICATED\y', false),
        ('STRIP_DESCRIPTION', '\ySTRIP\y', true)
      ) pat(code, re, lead)
      cross join generate_series(1, 12) n
      cross join lateral (select upper(coalesce(r.legal_desc, '')) l) t
      cross join lateral (select regexp_instr(t.l, pat.re, 1, n) pos, regexp_instr(t.l, pat.re, 1, n, 1) epos) m
      where m.pos > 0
        and (not pat.lead or m.pos - 1 < 40 or (substr(t.l, m.pos - 1, 1) = '(' and substr(t.l, m.epos, 1) = ')'))
        and regexp_replace(substr(t.l, greatest(1, m.pos - 40), m.pos - greatest(1, m.pos - 40)), '^.*[.;,]', '')
            !~ '(?:\y(?:LESS|EX|EXC|EXCEPT|EXCEPTING|SUBJ|SUBJECT|TOGETHER|WITH|PLUS|INT|INTEREST|ALSO|AND|RESERVING)\y|&)'
    ) end legal_flags
  from r
), f as (
  select o.*,
    (dor in ('09','91','93','94','95','96')
      or (source_id = 'mi_detroit_landbank_lots' and inventory_status_raw = 'Side Lot For Sale')
      or (acres is not null and occ = 'vacant' and acres < 0.01)) lim,
    (acres is not null and occ <> 'improved' and acres < 0.01 and occ <> 'vacant') tiny_review,
    (acres is not null and occ <> 'improved' and acres >= 0.01 and acres < 0.05) small_review,
    (val is not null and val < 1000) low_value,
    (val is not null and amt is not null and amt / val >= 1.0) bid_high,
    (val is not null and amt is not null and amt / val < 0.10) bid_low
  from o
)
select f.*,
  case when lim then 'LIMITED_OPPORTUNITY'
       when legal_flags is not null then 'HIGH_RISK_REVIEW'
       when not has_parcel or (val is null and acres is null and not has_class) then 'INSUFFICIENT_DATA'
       when tiny_review or small_review or low_value or bid_high or acres is null or val is null or not has_class then 'REVIEW'
       else 'PRIORITY_REVIEW' end cls
from f
