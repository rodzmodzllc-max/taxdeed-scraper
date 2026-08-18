$ErrorActionPreference = "Stop"

# Pushes the statewide harvest (harvest_all.json, produced by
# harvest_all_counties.ps1 + harvest_okaloosa_bid4assets.ps1) into the same
# `properties` table the app reads from.
#
# Safe-merge design: this script only ever sends the columns the harvester
# actually knows (county, case_no, parcel, address, bid, assessed, sale_date,
# url_appraiser, url_auction). It deliberately OMITS owner_name, status,
# lien_level, lien_note, prop_type, homestead, url_streetview, url_zillow,
# url_taxcoll, url_title from the payload.
#
# Why that matters: Postgres upsert (INSERT ... ON CONFLICT DO UPDATE) only
# touches columns present in the request. Columns left out are never reset:
#   - Brand-new properties get the table defaults (status='active',
#     lien_level='unscreened', homestead=false) and null for the rest -
#     exactly like a property that hasn't been screened yet.
#   - Properties already hand-researched keep their owner_name / lien_level /
#     lien_note / notes untouched, even though this script re-syncs the same
#     case_no every run (bid/sale_date can drift as an auction date
#     approaches - those DO get refreshed).
#
# CI-adapted: reads SUPABASE_URL / SUPABASE_SERVICE_KEY from environment
# variables (GitHub Actions secrets) instead of a local sync-config.local.json
# file - there is no local machine involved anymore.
#
# Run harvest_all_counties.ps1 (+ harvest_okaloosa_bid4assets.ps1) first,
# then this.

$here     = $PSScriptRoot
$jsonPath = Join-Path $here "../out/harvest_all.json"

$supabaseUrl = $env:SUPABASE_URL
$serviceRoleKey = $env:SUPABASE_SERVICE_KEY
if ([string]::IsNullOrWhiteSpace($supabaseUrl) -or [string]::IsNullOrWhiteSpace($serviceRoleKey)) {
    throw "SUPABASE_URL / SUPABASE_SERVICE_KEY environment variables are not set - check the workflow's secrets."
}
if (-not (Test-Path $jsonPath)) {
    throw "Missing $jsonPath - run harvest_all_counties.ps1 first."
}

$harvest = Get-Content $jsonPath -Raw | ConvertFrom-Json
if (-not $harvest -or $harvest.Count -eq 0) { throw "harvest_all.json is empty - nothing to sync." }

function ConvertTo-IsoDate($s) {
    if ([string]::IsNullOrWhiteSpace($s)) { return $null }
    try { return ([datetime]::ParseExact($s, "MM/dd/yyyy", $null)).ToString("yyyy-MM-dd") }
    catch { return $null }
}

$rows = @()
$skipped = 0
foreach ($p in $harvest) {
    if ([string]::IsNullOrWhiteSpace($p.case) -or [string]::IsNullOrWhiteSpace($p.address)) {
        $skipped++
        continue
    }
    $rows += [ordered]@{
        source        = "auction"
        county        = $p.county
        case_no       = $p.case
        parcel        = $p.parcel
        address       = $p.address
        bid           = $p.bid
        assessed      = $p.assessed
        sale_date     = ConvertTo-IsoDate $p.sale_date
        url_appraiser = $p.appraiser
        url_auction   = $p.auction_url
    }
}

if ($rows.Count -eq 0) { throw "Every harvested row was missing case # or address - nothing to sync." }
Write-Output "Prepared $($rows.Count) properties ($skipped skipped for missing case/address)."

$headers = @{
    "apikey"        = $serviceRoleKey
    "Authorization" = "Bearer $serviceRoleKey"
    "Content-Type"  = "application/json"
    "Prefer"        = "resolution=merge-duplicates,return=minimal"
}
$endpoint = "$supabaseUrl/rest/v1/properties?on_conflict=source,county,case_no"

$batchSize = 40
$sent = 0
for ($i = 0; $i -lt $rows.Count; $i += $batchSize) {
    $batch = $rows[$i..([math]::Min($i + $batchSize - 1, $rows.Count - 1))]
    $json = $batch | ConvertTo-Json -Depth 5
    if ($batch.Count -eq 1) { $json = "[$json]" }
    Invoke-RestMethod -Uri $endpoint -Method Post -Headers $headers -Body ([System.Text.Encoding]::UTF8.GetBytes($json)) | Out-Null
    $sent += $batch.Count
    Write-Output "  synced $sent / $($rows.Count)"
}

Write-Output "Done. $sent properties upserted to Supabase (existing owner/lien research untouched)."
Write-Output "Counties covered: $((($rows | ForEach-Object { $_.county }) | Select-Object -Unique).Count)"

# ---- Close out properties that fell off the Waiting feed ----
# harvest_all_counties.ps1 only ever scrapes each date's "Auctions Waiting"
# list (RealForeclose's own term for it) - a property leaves that feed the
# moment it's redeemed, canceled, or actually sold at the table. Until now
# nothing here ever noticed: this script always omits `status` from the
# upsert payload (see header comment - that's deliberate, so hand-research
# isn't clobbered), so an existing 'active' row just sat there forever,
# even hours after the county's own site had already moved it to "Auctions
# Closed or Canceled". Confirmed live on Charlotte: the app kept showing
# "10/10 active" well after the county's site showed only 4 still waiting.
#
# Fix: for every auction-sourced property still marked 'active' whose sale
# date has already arrived, if its (county, case_no) isn't in what we just
# harvested, it has left the Waiting feed - flip it to 'closed'. This can't
# distinguish Redeemed from Canceled from Sold (that needs scraping the
# Closed/Canceled section too, which nothing here does yet), but it's the
# difference between an accurate "closed" badge and a stale "active" one
# that's flat wrong days or weeks after the fact.
$today = (Get-Date).ToString("yyyy-MM-dd")
$harvestedKeys = [System.Collections.Generic.HashSet[string]]::new()
foreach ($r in $rows) { $harvestedKeys.Add("$($r.county)|$($r.case_no)") | Out-Null }

$activeUrl = "$supabaseUrl/rest/v1/properties?source=eq.auction&status=eq.active&sale_date=lte.$today&select=id,county,case_no&limit=5000"
$activeRows = Invoke-RestMethod -Uri $activeUrl -Method Get -Headers $headers

$staleIds = @()
foreach ($ar in $activeRows) {
    if (-not $harvestedKeys.Contains("$($ar.county)|$($ar.case_no)")) { $staleIds += $ar.id }
}

if ($staleIds.Count -gt 0) {
    Write-Output "Closing out $($staleIds.Count) properties whose sale date passed and are no longer on the Waiting feed..."
    $patchHeaders = $headers.Clone()
    $patchHeaders["Prefer"] = "return=minimal"
    for ($i = 0; $i -lt $staleIds.Count; $i += $batchSize) {
        $idBatch = $staleIds[$i..([math]::Min($i + $batchSize - 1, $staleIds.Count - 1))]
        $patchUrl = "$supabaseUrl/rest/v1/properties?id=in.(" + ($idBatch -join ",") + ")"
        Invoke-RestMethod -Uri $patchUrl -Method Patch -Headers $patchHeaders -Body ([System.Text.Encoding]::UTF8.GetBytes('{"status":"closed"}')) | Out-Null
    }
    Write-Output "Done closing out stale properties."
} else {
    Write-Output "No stale active properties to close out."
}
