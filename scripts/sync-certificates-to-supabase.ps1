$ErrorActionPreference = "Stop"

# Pushes harvest_certificates.json (produced by
# harvest_lienhub_certificates.ps1) into the same `properties` table as the
# deed/LAFT sync, with source='certificate'.
#
# REQUIRES schema-v4-certificates.sql to have been run against Supabase once
# first (adds certificate_no/tax_year/issued_date/expiration_date/
# interest_rate columns + 'certificate' to the source check constraint - see
# repo root). If that hasn't been run yet, every upsert below will fail with
# a "column does not exist" or check-constraint error - that failure is
# contained to this one job and does not touch the deed/LAFT sync.
#
# Same safe-merge design as sync-harvest-to-supabase.ps1: only sends columns
# this harvester actually knows, so re-syncing never clobbers hand research.
#
# Run harvest_lienhub_certificates.ps1 first, then this.

$here = $PSScriptRoot
$jsonPath = Join-Path $here "../out/harvest_certificates.json"

$supabaseUrl = $env:SUPABASE_URL
$serviceRoleKey = $env:SUPABASE_SERVICE_KEY
if ([string]::IsNullOrWhiteSpace($supabaseUrl) -or [string]::IsNullOrWhiteSpace($serviceRoleKey)) {
throw "SUPABASE_URL / SUPABASE_SERVICE_KEY environment variables are not set - check the workflow's secrets."
}
if (-not (Test-Path $jsonPath)) {
Write-Output "No harvest_certificates.json - harvester found nothing this run. Nothing to sync."
exit 0
}

$harvest = Get-Content $jsonPath -Raw | ConvertFrom-Json
if (-not $harvest -or $harvest.Count -eq 0) { Write-Output "harvest_certificates.json is empty - nothing to sync."; exit 0 }

function ConvertTo-IsoDateFlexible($s) {
if ([string]::IsNullOrWhiteSpace($s)) { return $null }
$formats = @("MM/dd/yyyy", "yyyy-MM-dd", "M/d/yyyy")
foreach ($fmt in $formats) {
try { return ([datetime]::ParseExact($s.Trim(), $fmt, $null)).ToString("yyyy-MM-dd") } catch {}
}
try { return ([datetime]$s).ToString("yyyy-MM-dd") } catch {}
return $null
}

function ToNum($s) {
if ($null -eq $s -or [string]::IsNullOrWhiteSpace([string]$s)) { return $null }
$c = ([string]$s) -replace '[^0-9.]', ''
if ($c -match '^\d+(\.\d+)?$') { return [double]$c }
return $null
}

$rows = @()
$skipped = 0
foreach ($p in $harvest) {
if ([string]::IsNullOrWhiteSpace($p.case_no)) { $skipped++; continue }

# `address` and `bid` are both NOT NULL on the properties table with no
# DB default (same constraint the LAFT sync hit) - LienHub usually
# publishes a property_address, but fall back the same way LAFT does so
# a missing address never becomes a failed insert.
$addr = $p.address
if ([string]::IsNullOrWhiteSpace($addr)) { $addr = "Account $($p.case_no)" }

$bidVal = ToNum $p.bid
if ($null -eq $bidVal) { $bidVal = 0 }

$rows += [ordered]@{
source = "certificate"
county = $p.county
case_no = $p.case_no
certificate_no = $p.certificate_no
tax_year = $p.tax_year
issued_date = ConvertTo-IsoDateFlexible $p.issued_date
expiration_date = ConvertTo-IsoDateFlexible $p.expiration_date
bid = $bidVal
address = $addr
owner_name = if ([string]::IsNullOrWhiteSpace($p.owner_name)) { $null } else { $p.owner_name }
parcel = if ([string]::IsNullOrWhiteSpace($p.parcel)) { $null } else { $p.parcel }
assessed = ToNum $p.assessed
interest_rate = ToNum $p.interest_rate
url_auction = $p.url_auction
}
}

# De-duplicate on (county, case_no) - the same conflict target used by the
# upsert below (on_conflict=source,county,case_no). LienHub occasionally
# lists the same certificate more than once in a single county's export
# (e.g. a re-offered certificate, or a duplicate row in the source list).
# Postgres's `ON CONFLICT DO UPDATE` rejects a batch that would update the
# same row twice in one statement ("ON CONFLICT DO UPDATE command cannot
# affect row a second time"), which failed the entire sync job 100% of the
# time this bug was present - not just the duplicated rows. Keep the
# last-seen row per key (harvest order), matching the sync's own
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

if ($rows.Count -eq 0) { Write-Output "Every harvested row was missing case_no - nothing to sync."; exit 0 }
Write-Output "Prepared $($rows.Count) certificates ($skipped skipped for missing case_no)."

$headers = @{
"apikey" = $serviceRoleKey
"Authorization" = "Bearer $serviceRoleKey"
"Content-Type" = "application/json"
"Prefer" = "resolution=merge-duplicates,return=minimal"
}
# Preferred conflict target once 004_widen_unique_constraint_for_state.sql
# has been run (adds `state` to the unique key so FL/TX same-named counties
# can't collide on one upserted row - see that migration's header comment).
# Falls back to the old narrower target below if that migration hasn't run
# yet against this Supabase project - independent of, and checked before,
# the existing schema-v4-certificates.sql diagnostic below.
$endpoint = "$supabaseUrl/rest/v1/properties?on_conflict=state,source,county,case_no"
$fallbackEndpoint = "$supabaseUrl/rest/v1/properties?on_conflict=source,county,case_no"
$useFallback = $false

$batchSize = 40
$sent = 0
for ($i = 0; $i -lt $rows.Count; $i += $batchSize) {
$batch = $rows[$i..([math]::Min($i + $batchSize - 1, $rows.Count - 1))]
$json = $batch | ConvertTo-Json -Depth 5
if ($batch.Count -eq 1) { $json = "[$json]" }
$body = [System.Text.Encoding]::UTF8.GetBytes($json)
try {
if ($useFallback) {
Invoke-RestMethod -Uri $fallbackEndpoint -Method Post -Headers $headers -Body $body | Out-Null
} else {
try {
Invoke-RestMethod -Uri $endpoint -Method Post -Headers $headers -Body $body | Out-Null
} catch {
$detail = "$($_.ErrorDetails.Message) $($_.Exception.Message)"
if ($detail -match '42P10|no unique or exclusion constraint') {
Write-Warning "State-aware unique constraint not found yet (004_widen_unique_constraint_for_state.sql not run against production?) - falling back to the older (source, county, case_no) conflict target for the rest of this run."
$useFallback = $true
Invoke-RestMethod -Uri $fallbackEndpoint -Method Post -Headers $headers -Body $body | Out-Null
} else {
throw
}
}
}
$sent += $batch.Count
Write-Output " synced $sent / $($rows.Count)"
} catch {
Write-Output "SYNC FAILED on batch starting at row $i - most likely schema-v4-certificates.sql hasn't been run against this Supabase project yet."
Write-Output "Error: $($_.Exception.Message)"
throw
}
}

Write-Output "Done. $sent certificates upserted to Supabase."
Write-Output "Counties covered: $((($rows | ForEach-Object { $_.county }) | Select-Object -Unique).Count)"
