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
$statusPath = Join-Path $here "../out/harvest_all_status.json"

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
        # Phase 72: every writer of url_auction also writes what that URL
        # opens (migration 013). harvest_all_counties.ps1 stores the
        # RealAuction sale-date PREVIEW page (index.cfm?zaction=AUCTION&
        # zmethod=PREVIEW&AuctionDate=...) - a SALE-EVENT page, not a
        # per-property page - so that is 'sale'. Any other non-empty
        # auction_url a deed harvester ever produces is a county page
        # ('county'); an empty one stays null so the UI can say
        # "Auction link not published" rather than show a guess.
        url_auction_kind = if ([string]::IsNullOrWhiteSpace($p.auction_url)) { $null }
                           elseif ($p.auction_url -imatch 'zaction=auction&zmethod=preview&auctiondate=') { "sale" }
                           else { "county" }
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
# Preferred conflict target once 004_widen_unique_constraint_for_state.sql
# has been run (adds `state` to the unique key so FL/TX same-named counties,
# e.g. both have an Orange County, can't collide on one upserted row - see
# that migration's header comment). Falls back to the old narrower target
# below if that migration hasn't run yet against this Supabase project.
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
# Fix: for every FL auction-sourced property still marked 'active' whose sale
# date has already arrived, if its (county, case_no) isn't in what a COMPLETE
# county's harvest this run saw, it has left the Waiting feed - flip it to
# 'closed'. This can't distinguish Redeemed from Canceled from Sold (that
# needs scraping the Closed/Canceled section too, which nothing here does
# yet), but it's the difference between an accurate "closed" badge and a
# stale "active" one that's flat wrong days or weeks after the fact.
#
# Phase 30B: this closeout previously ran with no per-county completeness
# gate at all - it queried and could close out EVERY active,
# sale-date-passed auction property statewide, regardless of whether that
# county's harvest this run actually succeeded. A county whose harvest
# failed (network error, timeout, site change) would have every one of its
# still-genuinely-listed properties wrongly flipped to 'closed', for the
# exact same reason Phase 23B had to fix this for certificates - see
# claude/phase-30b-deed-completeness-and-closed-gone-since.md. A property is
# only ever closed out now if harvest_all_status.json (written by
# harvest_all_counties.ps1 / harvest_okaloosa_bid4assets.ps1) explicitly
# marks that specific county COMPLETE this run; the file's absence, or any
# parse failure, fails CLOSED (zero counties eligible), never open - same
# discipline as sync-certificates-to-supabase.ps1's reconciliation step.
#
# Phase 30B also adds `state=eq.FL` to the query below, which this closeout
# never had: Texas's own RealAuction harvest also writes source='auction'
# (harvesters/texas_harvester.py, source="auction"), and without a state
# filter this closeout was one FL sync run away from silently closing out
# any TX auction property whose sale_date passed, the moment one existed -
# confirmed live this phase that TX currently has 47 active auction rows
# and 0 with a passed sale_date yet, i.e. this had not yet fired by chance,
# not because it couldn't.
$completeCounties = [System.Collections.Generic.HashSet[string]]::new()
if (Test-Path $statusPath) {
    try {
        $countyStatusRaw = Get-Content $statusPath -Raw | ConvertFrom-Json
        foreach ($cs in @($countyStatusRaw)) {
            if ($cs.status -eq "COMPLETE") { $completeCounties.Add([string]$cs.county) | Out-Null }
        }
        Write-Output "Reconciliation-eligible (COMPLETE) counties this run: $($completeCounties.Count)"
    } catch {
        Write-Warning "harvest_all_status.json could not be parsed - skipping stale-property closeout entirely this run (fail closed): $($_.Exception.Message)"
        $completeCounties.Clear()
    }
} else {
    Write-Warning "No harvest_all_status.json found - skipping stale-property closeout entirely this run (fail closed: no county can be assumed complete without explicit confirmation)."
}

if ($completeCounties.Count -gt 0) {
    $today = (Get-Date).ToString("yyyy-MM-dd")
    # Harvested identity keys this run, scoped strictly per COMPLETE county -
    # matches sync-certificates-to-supabase.ps1's $harvestedKeysByCounty.
    $harvestedKeysByCounty = @{}
    foreach ($r in $rows) {
        if (-not $completeCounties.Contains([string]$r.county)) { continue }
        if (-not $harvestedKeysByCounty.ContainsKey($r.county)) {
            $harvestedKeysByCounty[$r.county] = [System.Collections.Generic.HashSet[string]]::new()
        }
        $harvestedKeysByCounty[$r.county].Add([string]$r.case_no) | Out-Null
    }

    $encodedCounties = ($completeCounties | ForEach-Object { [uri]::EscapeDataString($_) }) -join ","
    $activeUrl = "$supabaseUrl/rest/v1/properties?state=eq.FL&source=eq.auction&status=eq.active&sale_date=lte.$today&county=in.($encodedCounties)&select=id,county,case_no&limit=5000"
    $activeRows = Invoke-RestMethod -Uri $activeUrl -Method Get -Headers $headers -UserAgent $SupabaseUserAgent

    $staleIds = @()
    foreach ($ar in $activeRows) {
        # Defense in depth: re-check county membership even though the query
        # above already filters on it (matches the certificate reconciliation
        # step's own defensive re-check).
        if (-not $completeCounties.Contains([string]$ar.county)) { continue }
        $keysForCounty = $harvestedKeysByCounty[$ar.county]
        $stillListed = $keysForCounty -and $keysForCounty.Contains([string]$ar.case_no)
        if (-not $stillListed) { $staleIds += $ar.id }
    }

    if ($staleIds.Count -gt 0) {
        Write-Output "Closing out $($staleIds.Count) properties whose sale date passed and are no longer on a COMPLETE county's Waiting feed..."
        $patchHeaders = $headers.Clone()
        $patchHeaders["Prefer"] = "return=minimal"
        for ($i = 0; $i -lt $staleIds.Count; $i += $batchSize) {
            $idBatch = $staleIds[$i..([math]::Min($i + $batchSize - 1, $staleIds.Count - 1))]
            $patchUrl = "$supabaseUrl/rest/v1/properties?id=in.(" + ($idBatch -join ",") + ")"
            Invoke-RestMethod -Uri $patchUrl -Method Patch -Headers $patchHeaders -Body ([System.Text.Encoding]::UTF8.GetBytes('{"status":"closed"}')) -UserAgent $SupabaseUserAgent | Out-Null
        }
        Write-Output "Done closing out stale properties."
    } else {
        Write-Output "No stale active properties to close out in this run's COMPLETE counties."
    }
} else {
    Write-Output "Zero COMPLETE counties this run - stale-property closeout skipped entirely (nothing closed out)."
}
