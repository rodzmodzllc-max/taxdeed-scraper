$ErrorActionPreference = "Stop"

# Sanity check for the LAFT harvest - catches a harvester silently
# returning 0 rows for a county that has previously produced real data,
# the same failure class sanity_check_deeds.ps1 catches for the deeds
# job (a selector/page change, IP block, etc. that leaves the harvest
# "succeeding" with nothing useful, while the job still reports green).
#
# Why this can't just check post-sync Supabase counts, unlike
# sanity_check_deeds.ps1's active-county-coverage check: sync-laft-to-
# supabase.ps1 is upsert-only (merge-duplicates) and never deletes stale
# rows, so a county's row count in `properties` never shrinks just
# because today's harvest found nothing - it only grows or holds steady.
# That means the signal has to come from comparing TODAY's raw harvest
# output (the out/harvest_laft_*.json files, before they're merged and
# synced) against what Supabase already has on file for that county, not
# from Supabase's post-sync state alone.
#
# Runs right after the harvest steps, before the sync - advisory only
# (Write-Warning, not throw), matching this project's own recurring
# "zero-results handling... worth re-confirming by hand" caveat already
# written into several single-county harvesters' own module docstrings
# (Orange, St. Lucie, Osceola, Leon). This formalizes that manual-recheck
# discipline into an automated, non-blocking check instead of relying on
# someone noticing a county quietly went to zero.
#
# Threshold ($MinPriorRows) is deliberately conservative - a single
# one-off listing that genuinely sold shouldn't trip this, only a county
# that's had a real, multi-row presence going quiet.

$supabaseUrl = $env:SUPABASE_URL
$serviceRoleKey = $env:SUPABASE_SERVICE_KEY
if ([string]::IsNullOrWhiteSpace($supabaseUrl) -or [string]::IsNullOrWhiteSpace($serviceRoleKey)) {
    throw "SUPABASE_URL / SUPABASE_SERVICE_KEY environment variables are not set - check the workflow's secrets."
}

$MinPriorRows = 2  # see header comment - deliberately conservative

$here = $PSScriptRoot

# Every harvest_laft_*.json file this job can produce, keyed only for
# Test-Path guarding below. Kept as its own list rather than re-parsing
# sync-laft-to-supabase.ps1's $optionalSources, since that script also
# merges the required harvest_laft.json PDF file in with everything else
# before this script would ever get a per-file breakdown.
$harvestFiles = @(
    Join-Path $here "../out/harvest_laft.json",
    Join-Path $here "../out/harvest_laft_html.json",
    Join-Path $here "../out/harvest_laft_realtdm.json",
    Join-Path $here "../out/harvest_laft_pioneer.json",
    Join-Path $here "../out/harvest_laft_orange.json",
    Join-Path $here "../out/harvest_laft_stlucie.json",
    Join-Path $here "../out/harvest_laft_osceola.json",
    Join-Path $here "../out/harvest_laft_hillsborough.json",
    Join-Path $here "../out/harvest_laft_leon.json"
)

# Today's per-county row counts across every harvester's fresh output.
$todayCounts = @{}
foreach ($f in $harvestFiles) {
    if (-not (Test-Path $f)) { continue }
    $rows = @(Get-Content $f -Raw | ConvertFrom-Json)
    foreach ($r in $rows) {
        if (-not $r.county) { continue }
        if (-not $todayCounts.ContainsKey($r.county)) { $todayCounts[$r.county] = 0 }
        $todayCounts[$r.county]++
    }
}

# What Supabase already has on file per county, as the "has this county
# historically had real data" baseline. Upsert-only sync means this never
# shrinks on its own, so a county showing up here with a healthy count is
# a reasonable proxy for "known-active", independent of today's run.
$headers = @{
    "apikey"        = $serviceRoleKey
    "Authorization" = "Bearer $serviceRoleKey"
}
$existingUrl = "$supabaseUrl/rest/v1/properties?source=eq.laft&select=county&limit=5000"
$existingRows = Invoke-RestMethod -Uri $existingUrl -Method Get -Headers $headers
$existingCounts = @{}
foreach ($r in $existingRows) {
    if (-not $r.county) { continue }
    if (-not $existingCounts.ContainsKey($r.county)) { $existingCounts[$r.county] = 0 }
    $existingCounts[$r.county]++
}

$anomalies = @()
foreach ($county in $existingCounts.Keys) {
    $had = $existingCounts[$county]
    $now = if ($todayCounts.ContainsKey($county)) { $todayCounts[$county] } else { 0 }
    if ($had -ge $MinPriorRows -and $now -eq 0) {
        $anomalies += "  $county - had $had row(s) on file, 0 in today's fresh harvest"
    }
}

if ($anomalies.Count -gt 0) {
    Write-Warning "LAFT anomaly check: $($anomalies.Count) county(ies) that previously had data produced 0 rows in today's harvest (this can be a real sold-out/cleared county, OR a broken selector/page change - worth a manual spot-check if this persists across multiple runs):"
    foreach ($a in $anomalies) { Write-Warning $a }
} else {
    Write-Output "LAFT anomaly check: no county with $MinPriorRows+ prior rows dropped to 0 in today's harvest."
}

Write-Output "Today's harvest, by county:"
foreach ($county in ($todayCounts.Keys | Sort-Object)) {
    Write-Output "  $county - $($todayCounts[$county]) row(s)"
}
