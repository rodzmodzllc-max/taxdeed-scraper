# Coordinates for MI / PA / OK records without a point (2026-10-28)

Active records that kept no coordinates after both the authoritative parcel
geocoder (`scripts/geocode_authoritative.py`) and the Census address geocoder:
Wayne County MI (153, `mi_wayne_county_landbank`), Fayette County PA (80,
`pa_fayette_repository`) and Oklahoma County OK (27, `ok_oklahoma_county_owned`).
Each was measured live and read-only on 2026-10-28 against the county's own
layer, on the held identifiers themselves (counts only below; no identifier,
address or owner is recorded here).

The rule stays the factory's: one feature for the record's own identifier,
exactly as published, or nothing. A trimmed, padded or "nearby" identifier is
never used; AMBIGUOUS is never written; equal or stronger coordinates are never
replaced (`coordinates.should_replace`).

## Michigan - Wayne County: a county layer was missing (fixed)

**Cause.** 152 of the 153 records are out-county parcels (14-digit numbers for
Romulus, Redford Township, Inkster, Taylor, Huron Township, ...). The only
Wayne layer configured, the City of Detroit's `parcel_file_current`
(`mi_detroit_assessor_parcels`), covers Detroit only and is not a coordinate
source at all (`centroid=False`). The one Detroit-numbered record ("99999999."
form) had no coordinate layer either. Not a format problem.

**Source.** Wayne County's own GIS program publishes its county-wide parcel
layer on ArcGIS Online (organization "Wayne County", urlKey `wayne`):
`Parcels_AssessmentData` (layer `ParcelsFINAL5`, 812,735 polygons, public,
data edited 2026-10-26). `pnum` carries the parcel number exactly as the land
bank list publishes it, Detroit's trailing dot included (`pnum2` equals `pnum`
on every hit; `apn2` is blank). The county's own website answered this
sandbox with an Akamai 403, which was not worked around; the layer is a public
ArcGIS Online service. No licence or terms are published on the item.

**Measured (153 records).** 148 identifiers present; **146 exactly one
polygon (95%)**, 2 several different polygons (AMBIGUOUS, never written), 5
absent. Every hit carried a polygon.

**Fix.** `mi_wayne_county_parcels` in `harvesters/enrichment/sources.py`:
`pnum`, `exact`, `centroid=True`, `counties=("Wayne",)`, coordinates only
(`field_map={}`), batch 50, and `row_source_ids=("mi_wayne_county_landbank",)`
so the 30,500 Detroit Land Bank rows (which carry the land bank's own points)
are never swept. INTERIM fetch / enrich records (`INTERNAL_RISK_ACCEPTANCE`,
`excluded_from_paid_tier`, expiring 2027-04-12) in
`data/source_permissions.csv`; display is not recorded.

**Geocoder fix.** `geocode.plan_row()` now honours a layer's `row_source_ids`
(`ParcelSourceConfig.takes_row`) as the enrichment runner already did. Before,
a scoped layer could be asked for another source's row - e.g. the Harris CAD
layer (`tx_hcad_parcels`) for a Harris county-list row whose `case_no` is not
a CAD account.

## Pennsylvania - Fayette: no deterministic rule exists (unchanged)

**Cause.** None of the 80 identifiers is published on the county's parcel
layer (PASDA "Fayette County Parcels region 202602", 78,007 polygons) under
`TAXIDNUM` or `TAXSHORT` (digits-only form): 0 of 80. 74 are sub-accounts of a
base parcel (suffixes such as -51 ... -99, -NN-69 / -NN-99, -A0-0 / -B0-0 -
interests and units the county keeps on its roll but never draws as a
polygon); 40 of their 47 distinct base parcels are on the layer, but a base
parcel is another record and is never used. The 6 unsuffixed identifiers sit in
four map sections that have no polygon on the layer at all. The other PASDA
layers (parcel lines, address points) carry no parcel number. No official
Fayette County GIS service with these accounts was found (only third-party
copies).

**Result.** 0 of 80 can be matched deterministically; the configuration stays
`TAXIDNUM` / `exact`. These records stay without a point.

## Oklahoma - Oklahoma County: identifiers absent or stacked (unchanged)

**Cause.** Of the 27 county-owned records without a point, 23 PINs are not on
the county's public tax-parcel layer (`TaxParcelsPublics_view`) under `pin`,
`PARCELNB_1`, `mapnumber`, `accountno` or `parentaccount`, in the dashed or
digits-only form; 4 PINs return 2-7 different polygons each (AMBIGUOUS). The
same 27 failed for values, so the gap is the layer, not the format. The City
of Oklahoma City's Government Owned Properties layer (2023) holds 3 of them,
each with several polygons (AMBIGUOUS). The county organization's
"InternalParcelData view" mirrors the public layer (same 4 hits) and was not
configured.

**Result.** 0 of 27 can be matched deterministically; the configuration stays
`pin` / `exact`.

## Not done

No workflow was dispatched and nothing was written to production. The next
`job=geocode` run (owner-authorized) or the daily enrichment legs pick up the
Wayne layer.
