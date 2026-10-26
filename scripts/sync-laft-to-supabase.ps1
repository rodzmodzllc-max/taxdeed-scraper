$ErrorActionPreference = "Stop"

# --- Source permission gate (2026-10-12) ---------------------------------------
# Runs before any request or write. Fail closed: no Python, no governance
# package, or a missing / expired / denied record in data/source_permissions.csv
# stops this script with exit 3. scripts/source_permission_check.py is the CLI of
# harvesters/governance/permissions.py (the one permission decision).
$permPython = Get-Command python3 -ErrorAction SilentlyContinue
if (-not $permPython) { $permPython = Get-Command python -ErrorAction SilentlyContinue }
if (-not $permPython) {
    Write-Host "::error title=source_permission::Python not found - permission cannot be checked; stopping before any request"
    exit 3
}
& $permPython.Source (Join-Path $PSScriptRoot "source_permission_check.py") --source fl_laft_pdfs --source fl_laft_html --source fl_laft_realtdm --source fl_laft_pioneer --source fl_laft_orange --source fl_laft_stlucie --source fl_laft_osceola --source fl_laft_hillsborough --source fl_laft_leon --operation store --state FL --dataset lands_available
if (0 -ne $LASTEXITCODE) {
    Write-Host "::error title=source_permission::LAFT sync not permitted (see the decision above) - stopping before any request or write"
    exit 3
}
# --- end source permission gate ------------------------------------------------

# --- Three-ledger contract (2026-10-14) ----------------------------------------
# The row contract (harvesters/ledgers/records.py) and the status-file reader
# (harvesters/ledgers/health.py) are applied through scripts/ledger_gate.py, the
# same rules the Python syncs apply - never a second copy of them here. Both
# helpers fail closed: a contract that cannot be checked writes nothing, and a
# status file that cannot be read closes nothing.
function Get-LedgerPython {
    $py = Get-Command python3 -ErrorAction SilentlyContinue
    if (-not $py) { $py = Get-Command python -ErrorAction SilentlyContinue }
    if (-not $py) { throw "Python not found - the ledger contract cannot be checked; nothing is written." }
    return $py.Source
}
function Select-LedgerRows([string]$Ledger, $Rows) {
    $all = @($Rows)
    if ($all.Count -eq 0) { return }
    $tmp = [System.IO.Path]::GetTempFileName()
    try {
        $json = $all | ConvertTo-Json -Depth 6
        if ($all.Count -eq 1) { $json = "[$json]" }
        [System.IO.File]::WriteAllText($tmp, $json, [System.Text.UTF8Encoding]::new($false))
        $out = & (Get-LedgerPython) (Join-Path $PSScriptRoot "ledger_gate.py") rows --ledger $Ledger --in $tmp
        if (0 -ne $LASTEXITCODE) { throw "ledger_gate.py could not check the $Ledger rows (exit $LASTEXITCODE) - nothing is written." }
        $verdict = ($out -join "`n") | ConvertFrom-Json
        $refused = [System.Collections.Generic.HashSet[int]]::new()
        foreach ($i in @($verdict.refused)) { $refused.Add([int]$i) | Out-Null }
        if ($refused.Count -gt 0) {
            Write-Warning "Ledger contract refused $($refused.Count) of $($all.Count) row(s) that do not belong to the $Ledger ledger - nothing is written for them."
        }
        for ($i = 0; $i -lt $all.Count; $i++) {
            if (-not $refused.Contains($i)) { $all[$i] }
        }
    } finally {
        Remove-Item $tmp -ErrorAction SilentlyContinue
    }
}
function Get-LedgerCloseableCounties([string]$Ledger, [string]$StatusPath) {
    $out = & (Get-LedgerPython) (Join-Path $PSScriptRoot "ledger_gate.py") closeable --ledger $Ledger --status $StatusPath
    if (0 -ne $LASTEXITCODE) { throw "ledger_gate.py could not read $StatusPath (exit $LASTEXITCODE)" }
    return @((($out -join "`n") | ConvertFrom-Json))
}
# --- end three-ledger contract -------------------------------------------------
# --- Stored-value guard (2026-10-26) -------------------------------------------
# PostgREST's bulk upsert needs one key set per batch, so a column the list did
# not publish is sent as null - and merge-duplicates used to write that null
# over the stored value (146 FL auction rows lost their FDOR tax-roll
# `assessed`). scripts/sync_value_guard.py reads the stored rows and puts the
# stored value back wherever a blank or placeholder would replace it, or where
# field_provenance names another source of equal or higher rank
# (scripts/field_provenance.py). Fail closed: if the stored rows cannot be
# read, nothing is written.
function Protect-StoredValues([string]$Source, $Rows) {
    $all = @($Rows)
    if ($all.Count -eq 0) { return }
    $in = [System.IO.Path]::GetTempFileName()
    $out = [System.IO.Path]::GetTempFileName()
    try {
        $json = $all | ConvertTo-Json -Depth 6
        if ($all.Count -eq 1) { $json = "[$json]" }
        [System.IO.File]::WriteAllText($in, $json, [System.Text.UTF8Encoding]::new($false))
        & (Get-LedgerPython) (Join-Path $PSScriptRoot "sync_value_guard.py") --source $Source --state FL --in $in --out $out
        if (0 -ne $LASTEXITCODE) { throw "sync_value_guard.py could not guard the $Source rows (exit $LASTEXITCODE) - nothing is written." }
        $guarded = @((Get-Content $out -Raw -Encoding utf8) | ConvertFrom-Json)
        if ($guarded.Count -ne $all.Count) { throw "sync_value_guard.py returned $($guarded.Count) of $($all.Count) rows - nothing is written." }
        $guarded
    } finally {
        Remove-Item $in, $out -ErrorAction SilentlyContinue
    }
}
# --- end stored-value guard ----------------------------------------------------


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
# - harvest_laft_leon.py: Leon County's lforms.leonclerk.com portal (added
#   2026-08-31) - a ninth distinct case: the page itself has no real HTML
#   table (an empty DataTables skeleton populated client-side via AJAX), so
#   unlike the other eight this harvester skips the rendered page entirely
#   and hits the JSON data file (listoflands.txt) it loads from directly.
#   Also removed from data/laft_html_sources.csv in the same round of
#   commits, since the static-HTML scan that file feeds can never find real
#   rows on that page.
# All nine write the same row shape to separate JSON files - this script
# merges them before syncing, so it's the only thing that needs to know all
# nine harvesters exist. Each optional file is guaranteed valid JSON when
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
    @{ Path = Join-Path $here "../out/harvest_laft_hillsborough.json"; Label = "Hillsborough County PAV (harvest_laft_hillsborough.json)" },
    @{ Path = Join-Path $here "../out/harvest_laft_leon.json"; Label = "Leon County (harvest_laft_leon.json)" }
)

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
    foreach ($fmt in @("MM/dd/yyyy", "M/d/yyyy", "MM-dd-yyyy", "M-d-yyyy", "yyyy-MM-dd")) {
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
        # `bid` keeps the legacy 0-means-not-published sentinel because the
        # column is NOT NULL with no default (see above). The honest amount
        # semantics - a nullable purchase_amount plus purchase_amount_kind
        # (NOT_PUBLISHED when the county published none) - are written by
        # scripts/laft_lifecycle.py once migration 017 exists; the app's
        # hasPublishedBid() reads that kind first and this sentinel second.
        bid         = $bidVal
        # `status` is pipeline state, never hand research (same reasoning as
        # sync-harvest-to-supabase.ps1's 2026-09-28 change): a row in this
        # run's harvest is on the county's list today, so it is 'active'
        # again even if scripts/laft_lifecycle.py closed it out earlier.
        # Migration 006's trigger clears gone_since when status leaves the
        # gone set. Nothing here ever writes 'closed' - only the lifecycle
        # script does, and only for a COMPLETE/EMPTY county.
        status      = "active"
        url_auction = $p.url_auction
        # Phase 72: every LAFT harvester (harvest_laft_*.py) sets url_auction
        # to the county's Lands Available list page or PDF - a COUNTY page
        # where the property can be found, never a per-property page - so
        # the kind is 'county' whenever a URL is present (migration 013).
        url_auction_kind = if ([string]::IsNullOrWhiteSpace($p.url_auction)) { $null } else { "county" }
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

# Every row must belong to the AVAILABLE ledger and pass its record contract
# (scripts/ledger_gate.py) before anything is written. This sync never closes
# a row; scripts/laft_lifecycle.py does that from the status file.
$rows = @(Select-LedgerRows "AVAILABLE" $rows)
if ($rows.Count -eq 0) { Write-Output "No row passed the AVAILABLE ledger contract - nothing to sync."; exit 0 }
Write-Output "Prepared $($rows.Count) LAFT properties ($skipped skipped for missing case_no/parcel)."
# A blank cell or an address / 0-bid placeholder never erases a stored value.
$rows = @(Protect-StoredValues "laft" $rows)

$headers = @{
    "apikey"        = $serviceRoleKey
    "Authorization" = "Bearer $serviceRoleKey"
    "Content-Type"  = "application/json"
    "Prefer"        = "resolution=merge-duplicates,return=minimal"
}
# Preferred conflict target once 004_widen_unique_constraint_for_state.sql
# has been run (adds `state` to the unique key so FL/TX same-named counties
# can't collide on one upserted row - see that migration's header comment).
# Falls back to the old narrower target below if that migration hasn't run
# yet against this Supabase project.
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

Write-Output "Done. $sent LAFT properties upserted to Supabase (existing owner/lien research untouched)."
Write-Output "Counties covered: $((($rows | ForEach-Object { $_.county }) | Select-Object -Unique).Count)"
