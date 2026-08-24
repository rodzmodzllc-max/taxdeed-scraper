$ErrorActionPreference = "Stop"

# Nightly sanity check for the deed-auction harvest.
#
# Why this exists: harvest_all_counties.ps1 can run "successfully" (exit 0,
# no errors) while actually harvesting nothing useful - a county's HTML skin
# changes, a selector stops matching, the site starts blocking the runner's
# IP, etc. Nothing before this script would catch that class of failure:
# sync-harvest-to-supabase.ps1 happily upserts whatever it was given, even
# if that's "almost nothing", and the workflow still reports green. This is
# exactly the shape of bug that let the Hillsborough county-count
# mislabeling go unnoticed until a manual cross-check against the Clerk's
# site (see improvement-roadmap.md, "Reliability & monitoring").
#
# What it checks (best-effort, degrades to a warning rather than a hard
# failure wherever the underlying data's freshness/shape isn't guaranteed):
#
# 1. HARD CHECK - active-county coverage collapse. Counts how many distinct
# counties have at least one source=auction/status=active property whose
# updated_at falls within the last 26 hours (the job runs 2x/day on a
# ~12h cadence; 26h gives a safety margin for a slow run without
# widening so far it'd miss a real break). If that count drops below
# $MinFreshCounties, something broke broadly across many counties at
# once (a shared selector, a shared IP block, etc.) - fail the step.
# A single quiet county on a slow day should never trip this; a
# statewide scraper break should always trip it.
#
# 2. SOFT CHECK - county_calendar divergence. county_calendar is hand-
# maintained / sourced independently of harvest_all_counties.ps1 (no
# current script writes to it from the harvest pipeline), so it's
# treated as advisory, not ground truth: any county_calendar row whose
# sale_date is within the next 7 days but has zero matching active
# auction properties gets logged as a warning, not a failure. This is
# the "diverges from the calendar" signal the roadmap asked for, without
# hard-failing the whole job on a table this script can't independently
# verify is being kept current.
#
# Threshold is intentionally conservative (tuned to fail loudly on a broad
# break, not fuss over routine day-to-day count drift) - tighten
# $MinFreshCounties over time once you have a feel for the normal range.

$supabaseUrl = $env:SUPABASE_URL
$serviceRoleKey = $env:SUPABASE_SERVICE_KEY
if ([string]::IsNullOrWhiteSpace($supabaseUrl) -or [string]::IsNullOrWhiteSpace($serviceRoleKey)) {
    throw "SUPABASE_URL / SUPABASE_SERVICE_KEY environment variables are not set - check the workflow's secrets."
}

$MinFreshCounties = 15  # see header comment - deliberately conservative

$headers = @{
    "apikey"        = $serviceRoleKey
    "Authorization" = "Bearer $serviceRoleKey"
}

# ---- Hard check: how many counties have fresh active auction data? ----
$sinceIso = (Get-Date).ToUniversalTime().AddHours(-26).ToString("yyyy-MM-ddTHH:mm:ssZ")
$freshUrl = "$supabaseUrl/rest/v1/properties?source=eq.auction&status=eq.active&updated_at=gte.$sinceIso&select=county&limit=5000"
$freshRows = Invoke-RestMethod -Uri $freshUrl -Method Get -Headers $headers
$freshCounties = ($freshRows | ForEach-Object { $_.county } | Select-Object -Unique)
$freshCount = ($freshCounties | Measure-Object).Count

Write-Output "Counties with fresh (last 26h) active auction data: $freshCount"
if ($freshCount -gt 0) {
    Write-Output ("  " + (($freshCounties | Sort-Object) -join ", "))
}

# ---- Soft check: county_calendar divergence (advisory only) ----
try {
    $today = (Get-Date).ToString("yyyy-MM-dd")
    $weekOut = (Get-Date).AddDays(7).ToString("yyyy-MM-dd")
    $calUrl = "$supabaseUrl/rest/v1/county_calendar?sale_date=gte.$today&sale_date=lte.$weekOut&select=county,sale_date&limit=1000"
    $calRows = Invoke-RestMethod -Uri $calUrl -Method Get -Headers $headers

    $activeUrl = "$supabaseUrl/rest/v1/properties?source=eq.auction&status=eq.active&sale_date=gte.$today&sale_date=lte.$weekOut&select=county,sale_date&limit=5000"
    $activeRows = Invoke-RestMethod -Uri $activeUrl -Method Get -Headers $headers
    $activeKeys = [System.Collections.Generic.HashSet[string]]::new()
    foreach ($a in $activeRows) { $activeKeys.Add("$($a.county)|$($a.sale_date)") | Out-Null }

    $diverged = @()
    foreach ($c in $calRows) {
        $key = "$($c.county)|$($c.sale_date)"
        if (-not $activeKeys.Contains($key)) { $diverged += $key }
    }

    if ($diverged.Count -gt 0) {
        Write-Warning "county_calendar lists $($diverged.Count) county/date pair(s) in the next 7 days with no matching harvested active auction property (advisory - county_calendar isn't harvester-maintained, so this can reflect a stale calendar row as easily as a real scraper gap):"
        foreach ($d in $diverged) { Write-Warning "  $d" }
    } else {
        Write-Output "county_calendar cross-check: no divergence in the next 7 days."
    }
} catch {
    Write-Warning "county_calendar cross-check skipped (table may not exist or query failed): $($_.Exception.Message)"
}

# ---- Verdict ----
if ($freshCount -lt $MinFreshCounties) {
    throw "SANITY CHECK FAILED: only $freshCount counties have fresh active auction data in the last 26h (expected at least $MinFreshCounties). This usually means a broad scraper break (shared selector change, IP block, etc.) rather than normal day-to-day quiet counties - check the harvest step's own log above before assuming the data pipeline is fine."
}

Write-Output "Sanity check passed: $freshCount counties fresh (threshold: $MinFreshCounties)."
