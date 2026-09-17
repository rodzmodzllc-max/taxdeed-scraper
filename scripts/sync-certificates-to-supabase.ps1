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
# Phase 23B: after the upsert, reconciles certificates that dropped off a
# COMPLETE county's LienHub listing - see
# claude/phase-23a-certificate-reconciliation-design.md. This is
# deliberately NOT the same shape as sync-harvest-to-supabase.ps1's deed
# reconciliation (which has no per-county completeness gate at all): a
# certificate is only ever flipped to notfound if
# harvest_lienhub_certificates.ps1 positively marked that specific county
# COMPLETE this run (see that script's own header comment for exactly what
# "COMPLETE" requires). A county that failed, timed out, hit LienHub's
# documented WAF block, or returned a malformed/partial response is
# INCOMPLETE and is never reconciled - its existing active certificates are
# left exactly as they were, even though they're absent from this run's
# (partial) harvest output. Certificates have a documented, recurring
# partial-failure mode that the deed pipeline's whole-run "missing = gone"
# pattern would not handle safely, which is why this isn't a blind copy of
# that step.
#
# Run harvest_lienhub_certificates.ps1 first, then this.

$here = $PSScriptRoot
$jsonPath = Join-Path $here "../out/harvest_certificates.json"
$statusPath = Join-Path $here "../out/harvest_certificates_status.json"

$supabaseUrl = $env:SUPABASE_URL
$serviceRoleKey = $env:SUPABASE_SERVICE_KEY

# --------------------------------------------------------------------------
# Supabase's new `sb_secret_...` keys are REFUSED on any request whose
# User-Agent looks like a browser - their docs are explicit that the check
# "matches on the User-Agent header". PowerShell's Invoke-RestMethod sends a
# default UA that begins "Mozilla/5.0 ...  PowerShell/7.x", so Supabase reads
# every call in this script as coming from a browser and answers:
#
#   { "message": "Forbidden use of secret API key in browser",
#     "hint": "Secret API keys can only be used in a protected environment
#              and should never be used in a browser. ..." }
#
# That is what broke the whole pipeline on 2026-09-15: run #140 succeeded at
# 12:38, #141 failed at 13:10, and every deeds/certificate/LAFT sync since has
# failed the same way with no code change on our side. The legacy service_role
# JWT had no such check, so the breakage dates from the switch to a secret key,
# not from anything this repo did.
#
# Every Supabase call below therefore passes an explicit, honest,
# non-browser User-Agent. This is not evading a control - the control exists
# to stop secret keys being used from real browsers, and this is a CI job on a
# GitHub runner. Naming the tool plainly is what the header is for.
$SupabaseUserAgent = "taxdeed-scraper/1.0 (+https://github.com/rodzmodzllc-max/taxdeed-scraper; GitHub Actions)"
if ([string]::IsNullOrWhiteSpace($supabaseUrl) -or [string]::IsNullOrWhiteSpace($serviceRoleKey)) {
throw "SUPABASE_URL / SUPABASE_SERVICE_KEY environment variables are not set - check the workflow's secrets."
}

$headers = @{
"apikey" = $serviceRoleKey
"Authorization" = "Bearer $serviceRoleKey"
"Content-Type" = "application/json"
"Prefer" = "resolution=merge-duplicates,return=minimal"
}
$batchSize = 40

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

# ---- Load and shape this run's harvested rows ----
# A missing or empty harvest_certificates.json is NOT treated as fatal: a
# run where every LienHub county is confirmed COMPLETE with zero results is
# a legitimate outcome (see the harvester's own header comment), and
# reconciliation below still needs to run in that case - it's the whole
# reason a previously-active certificate in a now-confirmed-empty county
# should be reconciled. Only "harvest ran, produced rows, but every single
# one was unusable" (missing case_no) is still treated as a hard failure,
# same as before this phase.
$rows = @()
if (Test-Path $jsonPath) {
$harvest = Get-Content $jsonPath -Raw | ConvertFrom-Json
if ($harvest -and $harvest.Count -gt 0) {
$skipped = 0
foreach ($p in @($harvest)) {
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

if ($rows.Count -eq 0) { throw "Every harvested row was missing case_no - nothing to sync." }
Write-Output "Prepared $($rows.Count) certificates ($skipped skipped for missing case_no)."
} else {
Write-Output "harvest_certificates.json is empty - nothing to upsert this run."
}
} else {
Write-Output "No harvest_certificates.json - harvester found nothing to upsert this run."
}

# ---- Upsert whatever was harvested (unconditional, always safe - this step
# only ever adds or refreshes rows, never removes data) ----
if ($rows.Count -gt 0) {
# Preferred conflict target once 004_widen_unique_constraint_for_state.sql
# has been run (adds `state` to the unique key so FL/TX same-named counties
# can't collide on one upserted row - see that migration's header comment).
# Falls back to the old narrower target below if that migration hasn't run
# yet against this Supabase project - independent of, and checked before,
# the existing schema-v4-certificates.sql diagnostic below.
$endpoint = "$supabaseUrl/rest/v1/properties?on_conflict=state,source,county,case_no"
$fallbackEndpoint = "$supabaseUrl/rest/v1/properties?on_conflict=source,county,case_no"
$useFallback = $false

$sent = 0
for ($i = 0; $i -lt $rows.Count; $i += $batchSize) {
$batch = $rows[$i..([math]::Min($i + $batchSize - 1, $rows.Count - 1))]
$json = $batch | ConvertTo-Json -Depth 5
if ($batch.Count -eq 1) { $json = "[$json]" }
$body = [System.Text.Encoding]::UTF8.GetBytes($json)
try {
if ($useFallback) {
Invoke-RestMethod -Uri $fallbackEndpoint -Method Post -Headers $headers -Body $body -UserAgent $SupabaseUserAgent | Out-Null
} else {
try {
Invoke-RestMethod -Uri $endpoint -Method Post -Headers $headers -Body $body -UserAgent $SupabaseUserAgent | Out-Null
} catch {
$detail = "$($_.ErrorDetails.Message) $($_.Exception.Message)"
if ($detail -match '42P10|no unique or exclusion constraint') {
Write-Warning "State-aware unique constraint not found yet (004_widen_unique_constraint_for_state.sql not run against production?) - falling back to the older (source, county, case_no) conflict target for the rest of this run."
$useFallback = $true
Invoke-RestMethod -Uri $fallbackEndpoint -Method Post -Headers $headers -Body $body -UserAgent $SupabaseUserAgent | Out-Null
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
} else {
Write-Output "Nothing to upsert this run."
}

# ---- Reconcile certificates absent from a COMPLETE county's harvest ----
# See the file header and claude/phase-23a-certificate-reconciliation-design.md.
# A county only participates if harvest_certificates_status.json explicitly
# marks it COMPLETE this run; the file's absence, or any parse failure,
# fails CLOSED (zero counties eligible), never open.
$completeCounties = [System.Collections.Generic.HashSet[string]]::new()
if (Test-Path $statusPath) {
try {
$countyStatusRaw = Get-Content $statusPath -Raw | ConvertFrom-Json
foreach ($cs in @($countyStatusRaw)) {
if ($cs.status -eq "COMPLETE") { $completeCounties.Add([string]$cs.county) | Out-Null }
}
Write-Output "Reconciliation-eligible (COMPLETE) counties this run: $($completeCounties.Count)"
} catch {
Write-Warning "harvest_certificates_status.json could not be parsed - skipping reconciliation entirely this run (fail closed): $($_.Exception.Message)"
$completeCounties.Clear()
}
} else {
Write-Output "No harvest_certificates_status.json found - skipping reconciliation entirely this run (fail closed: no county can be assumed complete without explicit confirmation)."
}

if ($completeCounties.Count -gt 0) {
# Harvested identity keys this run, scoped strictly per COMPLETE county -
# a case_no is only ever used to keep a row alive within its own county's
# reconciliation, matching the (state, source, county, case_no) identity
# the upsert itself already uses as its conflict target.
$harvestedKeysByCounty = @{}
foreach ($r in $rows) {
if (-not $completeCounties.Contains([string]$r.county)) { continue }
if (-not $harvestedKeysByCounty.ContainsKey($r.county)) {
$harvestedKeysByCounty[$r.county] = [System.Collections.Generic.HashSet[string]]::new()
}
$harvestedKeysByCounty[$r.county].Add([string]$r.case_no) | Out-Null
}

$encodedCounties = ($completeCounties | ForEach-Object { [uri]::EscapeDataString($_) }) -join ","
$activeUrl = "$supabaseUrl/rest/v1/properties?state=eq.FL&source=eq.certificate&status=eq.active&county=in.($encodedCounties)&select=id,county,case_no&limit=5000"
$activeRows = Invoke-RestMethod -Uri $activeUrl -Method Get -Headers $headers -UserAgent $SupabaseUserAgent

$staleIds = @()
foreach ($ar in $activeRows) {
# Defense in depth: re-check county membership even though the query
# above already filters on it, so a future query-shape change can't
# silently widen what gets reconciled without this check also changing.
if (-not $completeCounties.Contains([string]$ar.county)) { continue }
$keysForCounty = $harvestedKeysByCounty[$ar.county]
$stillListed = $keysForCounty -and $keysForCounty.Contains([string]$ar.case_no)
if (-not $stillListed) { $staleIds += $ar.id }
}

if ($staleIds.Count -gt 0) {
Write-Output "Marking $($staleIds.Count) certificate(s) notfound (absent from a COMPLETE county harvest this run)..."
$patchHeaders = $headers.Clone()
$patchHeaders["Prefer"] = "return=minimal"
# Only status is ever written here - every other field (owner_name,
# assessed, interest_rate, notes, favorites, hidden, etc.) is left exactly
# as it was, same discipline as the upsert step above.
# Phase 27: production `properties` has no `outcome` column (confirmed live
# via Phase 26's forensic audit - see claude/phase-26-production-schema-
# forensic-audit.md and claude/phase-27-certificate-reconciliation-schema-
# truth-redesign.md), so this PATCH writes status only. This isn't a loss of
# information: `gone_since` is already database-managed - a BEFORE UPDATE
# trigger (`properties_gone_since` -> `track_gone_since()`) stamps it the
# moment `status` transitions into ('dropped','sold','notfound') and clears
# it if a row ever transitions back out, with no `source` filter, so it
# fires identically for certificate rows without this script writing it.
# `outcome` was never more than a same-PATCH narrative annotation ("no
# longer listed") layered on top of that transition - LienHub's
# county-held-liens listing only ever exposes currently-available
# certificates, never a redemption/removal reason, so there was never a
# confirmed fact for it to record beyond what `status=notfound` (plus the
# trigger-stamped `gone_since`) already captures. Do not resurrect `outcome`
# or add a replacement narrative field here without a real production
# column to back it - see Phase 14D's independent finding that this field
# was deliberately deferred, not merely unimplemented.
$patchBody = [System.Text.Encoding]::UTF8.GetBytes('{"status":"notfound"}')
for ($i = 0; $i -lt $staleIds.Count; $i += $batchSize) {
$idBatch = $staleIds[$i..([math]::Min($i + $batchSize - 1, $staleIds.Count - 1))]
$patchUrl = "$supabaseUrl/rest/v1/properties?id=in.(" + ($idBatch -join ",") + ")"
Invoke-RestMethod -Uri $patchUrl -Method Patch -Headers $patchHeaders -Body $patchBody -UserAgent $SupabaseUserAgent | Out-Null
}
Write-Output "Done reconciling stale certificates."
} else {
Write-Output "No stale active certificates to reconcile in this run's COMPLETE counties."
}
} else {
Write-Output "Zero COMPLETE counties this run - reconciliation skipped entirely (nothing marked notfound)."
}
