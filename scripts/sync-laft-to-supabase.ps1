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
# Run harvest_laft_pdfs.py (PDF-published counties) first, then this -
# that one's required. Five more harvesters cover other LAFT formats and
# are OPTIONAL (Test-Path guarded below) so this script still works
# standalone if any of them hasn't run yet:
# - harvest_laft_html.py: plain static-table counties (added 2026-08)
# - harvest_laft_realtdm.py: counties on the RealTDM case-management
#   platform (added 2026-08) - a shared multi-tenant search-portal system,
#   different vendor from both of the above
# - harvest_laft_pioneer.py: counties on the Pioneer/TaxSmartWeb platform
#   (added 2026-08) - a fourth distinct vendor, one domain per county
#   rather than a shared subdomain convention
# - harvest_laft_orange.py: Orange County's own Comptroller-run "TDSM"
#   search tool (added 2026-08-25) - a fifth distinct vendor/platform,
#   single-county (not CSV-driven, unlike the others) since no other
#   county has been found on this exact system
# - harvest_laft_stlucie.py: St. Lucie County's AcclaimWeb/TributeWeb
#   tax-deed search tool (added 2026-08-25) - a sixth distinct
#   vendor/platform, also single-county so far
# - harvest_laft_osceola.py: Osceola County's own NewVision Systems
#   search tool (added 2026-08-25) - a seventh distinct vendor/platform,
#   also single-county so far. Its ag-Grid results table required its own
#   scroll-and-collect virtualization handling (see that script's module
#   docstring) but writes the same row shape as every other harvester here.
# - harvest_laft_hillsborough.py: Hillsborough County's OnBase-based
#   Public Access View search tool (added 2026-08-25) - an eighth distinct
#   vendor/platform, also single-county so far. Requires a Case
#   Status='LANDS FOR SALE' filter (its default search just returns every
#   tax-deed case regardless of status) and a per-case dedupe across
#   duplicate document-type rows (see that script's module docstring) but
#   writes the same row shape as every other harvester here.
# All eight write the same row shape to separate JSON files - this script
# merges them before syncing, so it's the only thing that needs to know all
# eight harvesters exist. Each optional file is guaranteed valid JSON when
# present (every harvester always writes the file, even an empty `[]`, so a
# missing file really does mean "never ran" not "ran and found nothing").

$here = $PSScriptRoot
$jsonPath = Join-Path $here "../out/harvest_laft.json"
$optionalSources = @(
    @{ Path = Join-Path $here "../out/harvest_laft_html.json"; Label = "HTML-table counties (harvest_laft_html.json)" },
    @{ Path = Join-Path $here "../out/harvest_laft_realtdm.json"; Label = "RealTDM-platform counties (harvest_laft_realtdm.json)" },
    @{ Path = Join-Path $here "../out/harvest_laft_pioneer.json"; Label = "Pioneer/TaxSmartWeb-platform counties (harvest_laft_pioneer.json)" },
    @{ Path = Join-Path $here "../out/harvest_laft_orange.json"; Label = "Orange County TDSM (harvest_laft_orange.json)" },
    @{ Path = Join-Path $here "../out/harvest_laft_stlucie.json"; Label = "St. Lucie County AcclaimWeb (harvest_laft_stlucie.json)" },
    @{ Path = Join-Path $here "../out/harvest_laft_osceola.json"; Label = "Osceola County NewVision (harvest_laft_osceola.json)" },
    @{ Path = Join-Path $here "../out/harvest_laft_hillsborough.json"; Label = "Hillsborough County PAV (harvest_laft_hillsborough.json)" }
)

$supabaseUrl = $env:SUPABASE_URL
$serviceRoleKey = $env:SUPABASE_SERVICE_KEY
if ([string]::IsNullOrWhiteSpace($supabaseUrl) -or [string]::IsNullOrWhiteSpace($serviceRoleKey)) {
    throw "SUPABASE_URL / SUPABASE_SERVICE_KEY environment variables are not set - check the workflow's secrets."
}
if (-not (Test-Path $jsonPath)) {
    throw "Missing $jsonPath - run harvest_laft_pdfs.py first."
}

$harvest = @(Get-Content $jsonPath -Raw | ConvertFrom-Json)
foreach ($src in $optionalSources) {
    if (Test-Path $src.Path) {
        $extra = @(Get-Content $src.Path -Raw | ConvertFrom-Json)
        if ($extra.Count -gt 0) {
            Write-Output "Merging $($extra.Count) properties from $($src.Label)."
            $harvest = @($harvest) + @($extra)
        }
    } else {
        Write-Output "No $($src.Label) file found - skipping."
    }
}

if (-not $harvest -or $harvest.Count -eq 0) {
    Write-Output "Both harvests are empty - no LAFT properties currently listed at any of the confirmed counties. Nothing to sync (not an error)."
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
    # `address` and `bid` are both NOT NULL on the properties table, and
    # neither has a database default - confirmed live: omitting `bid`
    # entirely (rather than sending an explicit null) still failed with the
    # same "violates not-null constraint" error, so the column really has no
    # DEFAULT clause to fall back to. That means both need a real value
    # computed here, not just "don't send null".
    #
    # Most LAFT PDFs don't publish a street address at all (Marion's columns
    # are just Sale #/Sale date/Parcel #/Description - no address) and often
    # don't publish a price either (same PDF, no price column) - unlike the
    # auction harvester this can't just skip rows that lack them. Fall back
    # to the legal description or parcel/case ID for address so the property
    # still shows *something* in the UI, and to 0 for bid so "no published
    # price" is visually obvious rather than silently wrong.
    $addr = $p.address
    if ([string]::IsNullOrWhiteSpace($addr)) { $addr = $p.legal_desc }
    if ([string]::IsNullOrWhiteSpace($addr) -and -not [string]::IsNullOrWhiteSpace($p.parcel)) { $addr = "Parcel $($p.parcel)" }
    if ([string]::IsNullOrWhiteSpace($addr) -and -not [string]::IsNullOrWhiteSpace($p.case_no)) { $addr = "Case $($p.case_no)" }
    if ([string]::IsNullOrWhiteSpace($addr)) { $addr = "Address not published - see county PDF" }

    $bidVal = ToNum $p.bid
    if ($null -eq $bidVal) { $bidVal = 0 }

    $row = [ordered]@{
        source      = "laft"
        county      = $p.county
        case_no     = if ($p.case_no) { $p.case_no } else { $p.parcel }
        address     = $addr
        bid         = $bidVal
        url_auction = $p.url_auction
    }
    # `parcel`/`sale_date` are nullable, but PostgREST's bulk-insert endpoint
    # requires every object in a batch to have the SAME set of keys - confirmed
    # live: mixing rows that omit `parcel`/`sale_date` (when a county's PDF
    # didn't publish them) with rows that include them fails the whole batch
    # with { "code": "PGRST102", "message": "All object keys must match" },
    # even though `parcel`/`sale_date` are individually nullable columns. So
    # every row must always carry the same key set - use $null explicitly
    # instead of conditionally omitting the key.
    $row["parcel"] = if (-not [string]::IsNullOrWhiteSpace($p.parcel)) { $p.parcel } else { $null }
    $row["sale_date"] = ConvertTo-IsoDate $p.sale_date

    $rows += $row
}

if ($rows.Count -eq 0) { Write-Output "Every harvested row was missing both case_no and parcel - nothing to sync."; exit 0 }

# De-duplicate on (county, case_no) - the same conflict target used by the
# upsert below (on_conflict=source,county,case_no). This is the same bug
# class that took down the certificates sync entirely (see
# sync-certificates-to-supabase.ps1's history): Postgres's
# `ON CONFLICT DO UPDATE` rejects a whole batch if any two rows in it share
# the same conflict-target key ("ON CONFLICT DO UPDATE command cannot
# affect row a second time"), not just the duplicated rows. LAFT merges
# eight independent harvesters' output before this point, so a collision
# is more plausible here than in any single-source sync: two harvesters
# could in principle both report the same physical property (e.g. if a
# county were ever added to more than one source CSV by mistake), or a
# single harvester's own case_no-from-parcel fallback could collide the
# same way Hendry's did before that was fixed at the harvest level. No
# such collision has been observed in production as of 2026-08-25 - this
# is a preventive fix, added so a future collision degrades gracefully
# (a few rows deduped) instead of failing the sync for all counties at
# once. Keeps the last-seen row per key, matching this script's own
# safe-merge/upsert semantics elsewhere.
$deduped = [ordered]@{}
foreach ($r in $rows) {
    $key = "$($r.county)|$($r.case_no)"
    $deduped[$key] = $r
}
$dupeCount = $rows.Count - $deduped.Count
$rows = @($deduped.Values)
if ($dupeCount -gt 0) {
    Write-Output "De-duplicated $dupeCount row(s) sharing a (county, case_no) key with another row in this harvest."
}

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
