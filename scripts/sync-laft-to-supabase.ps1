$ErrorActionPreference = "Stop"

# Pushes the Lands Available for Taxes harvest (harvest_laft.json, produced
# by harvest_laft_pdfs.py) into the same `properties` table the app reads
# from, tagged source='laft' - a distinct ledger from 'auction' and
# 'certificate', on_conflict(source,county,case_no) keeps them from
# colliding even when a LAFT case_no matches a former auction case_no for
# the same property.
#
# Same safe-merge design as sync-harvest-to-supabase.ps1: only ever sends
# the columns the harvester actually knows (county, case_no, parcel,
# address, bid, sale_date, url_auction). Anything hand-researched
# (owner_name, lien_level, notes, etc.) is left untouched on every re-sync.
#
# CI-adapted: reads SUPABASE_URL / SUPABASE_SERVICE_KEY from environment
# variables (GitHub Actions secrets).
#
# Run harvest_laft_pdfs.py first, then this.

$here     = $PSScriptRoot
$jsonPath = Join-Path $here "../out/harvest_laft.json"

$supabaseUrl = $env:SUPABASE_URL
$serviceRoleKey = $env:SUPABASE_SERVICE_KEY
if ([string]::IsNullOrWhiteSpace($supabaseUrl) -or [string]::IsNullOrWhiteSpace($serviceRoleKey)) {
    throw "SUPABASE_URL / SUPABASE_SERVICE_KEY environment variables are not set - check the workflow's secrets."
}
if (-not (Test-Path $jsonPath)) {
    throw "Missing $jsonPath - run harvest_laft_pdfs.py first."
}

$harvest = Get-Content $jsonPath -Raw | ConvertFrom-Json
if (-not $harvest -or $harvest.Count -eq 0) {
    Write-Output "harvest_laft.json is empty - no LAFT properties currently listed at any of the confirmed counties. Nothing to sync (not an error)."
    exit 0
}

function ConvertTo-IsoDate($s) {
    if ([string]::IsNullOrWhiteSpace($s)) { return $null }
    foreach ($fmt in @("MM/dd/yyyy", "M/d/yyyy", "yyyy-MM-dd")) {
        try { return ([datetime]::ParseExact($s, $fmt, $null)).ToString("yyyy-MM-dd") } catch {}
    }
    return $null
}
function ToNum($s) {
    if ([string]::IsNullOrWhiteSpace($s)) { return $null }
    $c = ($s -replace '[^0-9.]', '')
    if ($c -match '^\d+(\.\d+)?$') { return [double]$c }
    return $null
}

$rows = @()
$skipped = 0
foreach ($p in $harvest) {
    if ([string]::IsNullOrWhiteSpace($p.case_no) -and [string]::IsNullOrWhiteSpace($p.parcel)) {
        $skipped++
        continue
    }
    # `address` is NOT NULL on the properties table. Most LAFT PDFs don't
    # publish a street address at all (Marion's columns are just Sale #/Sale
    # date/Parcel #/Description - no address), so unlike the auction
    # harvester this can't skip rows that lack one. Instead, omit the key
    # entirely when blank rather than sending an explicit JSON null -
    # PostgREST then falls back to the column default, same as
    # sync-certificates-to-supabase.ps1 already does for every optional
    # column it doesn't send. Fall back to the legal description or parcel
    # ID so the property still shows *something* in the UI.
    $addr = $p.address
    if ([string]::IsNullOrWhiteSpace($addr)) { $addr = $p.legal_desc }
    if ([string]::IsNullOrWhiteSpace($addr) -and -not [string]::IsNullOrWhiteSpace($p.parcel)) { $addr = "Parcel $($p.parcel)" }
    if ([string]::IsNullOrWhiteSpace($addr) -and -not [string]::IsNullOrWhiteSpace($p.case_no)) { $addr = "Case $($p.case_no)" }
    if ([string]::IsNullOrWhiteSpace($addr)) { $addr = "Address not published - see county PDF" }

    $row = [ordered]@{
        source      = "laft"
        county      = $p.county
        case_no     = if ($p.case_no) { $p.case_no } else { $p.parcel }
        address     = $addr
        url_auction = $p.url_auction
    }
    # `bid` is also NOT NULL, and most LAFT PDFs simply don't publish a
    # price (confirmed on Marion - the same PDF that has no address column
    # also has no price column). `parcel`/`sale_date` aren't currently known
    # to be NOT NULL, but apply the same discipline to them too rather than
    # wait for the next county to hit the same class of bug: omit the key
    # entirely instead of sending an explicit JSON null whenever the
    # harvester didn't actually find a value, so PostgREST falls back to
    # each column's own default.
    $bidVal = ToNum $p.bid
    if ($null -ne $bidVal) { $row["bid"] = $bidVal }
    if (-not [string]::IsNullOrWhiteSpace($p.parcel)) { $row["parcel"] = $p.parcel }
    $saleDate = ConvertTo-IsoDate $p.sale_date
    if ($null -ne $saleDate) { $row["sale_date"] = $saleDate }

    $rows += $row
}

if ($rows.Count -eq 0) { Write-Output "Every harvested row was missing both case_no and parcel - nothing to sync."; exit 0 }
Write-Output "Prepared $($rows.Count) LAFT properties ($skipped skipped for missing case_no/parcel)."

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

Write-Output "Done. $sent LAFT properties upserted to Supabase (existing owner/lien research untouched)."
Write-Output "Counties covered: $((($rows | ForEach-Object { $_.county }) | Select-Object -Unique).Count)"
