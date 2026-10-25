# Florida DOR Property Tax Oversight: written response on parcel data (2026-10-12)

Transcript of the reply TAXACQ received from the Florida Department of Revenue,
Property Tax Oversight. It is kept here as the written permission on file for
`fl_dor_pto_parcel_gis` and `fl_fdor_cadastral`
(`harvesters/governance/authorization.py`). Email addresses, telephone numbers,
the logo and DOR's standard e-mail footer are omitted. Nothing else is changed.

| Field | Value |
|---|---|
| From | Thomas (Tom) Canter, Systems Project Consultant, Property Tax Oversight, Florida Department of Revenue |
| To | TAXACQ (the product owner's mailbox) |
| Date | Mon, 12 Oct 2026 15:17:06 +0000 |
| Subject | TAXACQ + Florida parcel data: official-source referrals and permitted GIS use |
| Original | `.eml` file in the product owner's mailbox, supplied 2026-10-24; not committed (public repository) |
| SHA-256 of the original `.eml` | `64edaaab3860f1d5834f2eb7aff11ed21e5d598299ee55678e8ff9b14fe66722` |

## Body

> Good morning. Your inquiry was forwarded to me for response.
>
> Current and previous year (to 2005) GIS parcel shapefiles are published for
> download through the Property Tax Oversight's Data Portal here -
> https://floridarevenue.com/property/Pages/DataPortal_RequestAssessmentRollGISData.aspx
>
> Current year statewide parcel data are also available here -
> https://geodata.floridagio.gov/
>
> Responses to your questions are as follows -
>
> - May TAXACQ retain simplified parcel-boundary geometry derived from eligible
>   DOR-published county GIS files?
>   There are no restrictions placed on the data.
> - May we display those boundaries over aerial imagery in a commercial
>   research application?
>   Yes.
> - What attribution, disclaimers, refresh expectations, or other restrictions
>   should we follow?
>   These are at your discretion and professional courtesy. The data at both
>   locations are refreshed annually mid-August to early September.
> - Are there specific county-level permissions we must obtain separately?
>   There are no county-level permissions required. There is a read me PDF at
>   the Data Portal that addresses issues such as treatment of some condominium
>   properties.
>
> Let me know if you have further questions.

## How TAXACQ reads it (owner's decision, 2026-10-24)

- **County GIS parcel files on the Data Portal** (`fl_dor_pto_parcel_gis`): no
  restrictions placed on the data; boundaries may be retained and shown over
  aerial imagery; no county permissions needed.
- **"Current year statewide parcel data" at geodata.floridagio.gov**: the
  owner decided on 2026-10-24 that the response covers this dataset too.
  "There are no restrictions placed on the data" and "the data at both
  locations" name both places. TAXACQ reads that dataset as `fl_fdor_cadastral`,
  the `Florida_Statewide_Cadastral` FeatureServer (Florida GeoData item
  `efa909d6...`), for its parcel attributes and parcel centroid.
- **Not covered by this reading**: redistribution outside the app (exports, API,
  resale). It was not asked about and stays under review.
- **Attribution** is at TAXACQ's discretion. TAXACQ credits "Florida Department
  of Revenue, Property Tax Oversight" as a courtesy.
