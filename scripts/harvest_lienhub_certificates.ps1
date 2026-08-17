$ErrorActionPreference = "Continue"
$ProgressPreference = "SilentlyContinue"

# LienHub "County-Held Liens" harvester - certificates the annual May auction
# didn't sell, now available for direct purchase year-round (the certificate
# equivalent of Lands Available for Taxes). Covers 32 of the 67 counties -
# by far the biggest single certificate-sale platform. County list is
# florida_certificate_sale_platforms.csv, filtered to Platform=LienHub.
#
# CONFIRMED LIVE 2026-08 via browser devtools against Alachua (234 rows) and
# Duval (138 rows) - this is not a guess. The results grid is a jQuery
# DataTables instance with serverSide:true, but LienHub does NOT use the
# plain "draw/start/length" POST convention the previous revision of this
# script guessed at (which is why that revision harvested 0 rows everywhere,
# confirmed via a live CI run). The real request shape:
#
#   POST <same page URL>
#   Content-Type: application/x-www-form-urlencoded
#   X-Requested-With: XMLHttpRequest
#   Body: datatables_ajax_data=<JSON-encoded DataTables params>&csrf_token=<token>
#
# Where the JSON payload is the standard DataTables server-side shape
# ({draw, columns[], order[], start, length, search, filters}), and:
#   - `filters` can be an empty object ({}) - confirmed live, returns the
#     full unfiltered set rather than erroring or defaulting to 0 rows.
#   - `csrf_token` comes from `<meta name="csrf_token" content="...">` on the
#     page itself, and must be paired with the session cookie set by the
#     initial GET (hence -SessionVariable below, not a stateless POST).
#   - `length: 2000` in one shot was enough for both confirmed counties
#     (234 and 138 rows respectively); the pagination loop below is a safety
#     net for any county with more than that, not something confirmed
#     necessary.
#   - The response's `data` array holds full row OBJECTS keyed by field name
#     (account_number, tax_year, certificate_number, issued_date,
#     expiration_date, purchase_amt, owner_name, owner_address,
#     property_address, legal_description, assessed_value, market_value,
#     use_code, certs_issued/redeemed/outstanding, rate, etc.) - richer than
#     the visible table columns, and NOT positional arrays, so the previous
#     revision's `$cols = @($d)` array-indexing approach was doubly wrong.
#
# Requires schema-v4-certificates.sql to have been run against Supabase once
# (adds certificate_no/tax_year/issued_date/expiration_date/interest_rate
# columns + 'certificate' to the source check constraint) - see repo root.
#
# CI-adapted: Invoke-WebRequest/-RestMethod with -SessionVariable (works
# cross-platform under pwsh on GitHub's runners) instead of a curl.exe cookie
# jar - no local machine involved.
#
# Output: harvest_certificates.json / .csv (kept separate from
# harvest_all.json - synced by sync-certificates-to-supabase.ps1, not
# sync-harvest-to-supabase.ps1).

$here = $PSScriptRoot
$ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
$registryPath = Join-Path $here "../data/florida_certificate_sale_platforms.csv"
$outDir = Join-Path $here "../out"
New-Item -ItemType Directory -Force -Path $outDir | Out-Null
$outJson = Join-Path $outDir "harvest_certificates.json"
$outCsv  = Join-Path $outDir "harvest_certificates.csv"

$counties = Import-Csv $registryPath | Where-Object { $_.Platform -eq 'LienHub' }
if (-not $counties) { Write-Host "No LienHub counties found in $registryPath"; exit }

function Get-Slug($county) {
    return ($county.ToLower() -replace '[^a-z]', '')   # "Indian River" -> "indianriver", "St. Lucie" -> "stlucie"
}

# The 15 fields LienHub's own front-end requests in `columns[].data` -
# confirmed live via browser devtools. The server appears to ignore this list
# for what it returns (response rows carry many more fields regardless), but
# still expects a plausible `columns` array to accept the request at all.
$columnNames = @(
    "account_number", "tax_year", "certificate_number", "issued_date",
    "expiration_date", "purchase_amt", "issued_date_year",
    "extended_data_advertised_number", "owner_name", "property_address",
    "legal_description", "assessed_value", "certs_issued", "certs_redeemed",
    "certs_outstanding"
)

$all = @()
$i = 0
foreach ($row in $counties) {
    $i++
    # Confirmed live 2026-08 across TWO CI runs. Run A (no delay at all):
    # 403 from 31/32 (only Nassau came through) in ~5s total - proved this is
    # a WAF/bot-block reacting to request velocity, not a request-format bug
    # (Nassau's 403-free run returned 10 real certificates via the identical
    # code path). Run B (3-7s jittered delay + single 15s-backoff retry):
    # 9/32 succeeded (1679 certificates total, incl. Lake/Orange/Santa
    # Rosa/Seminole/St. Lucie/Sumter, plus Lee/Pinellas legitimately empty) -
    # a real improvement over run A, and 8 of those 9 succeeded specifically
    # ON the retry (only Nassau succeeded on the very first attempt), proving
    # the backoff approach works when given enough runway. But 23/32 still
    # exhausted the single retry and 403'd anyway - one 15s backoff isn't
    # long enough most of the time. This revision adds a second retry with a
    # longer backoff (escalating 20s then 45s) and widens the base
    # inter-county delay, rather than changing approach again.
    if ($i -gt 1) { Start-Sleep -Seconds (Get-Random -Minimum 4 -Maximum 9) }
    $slug = Get-Slug $row.County
    $base = "https://lienhub.com/county/$slug/countyheld/certificates"
    Write-Host ("[{0}/{1}] {2} ({3})" -f $i, $counties.Count, $row.County, $slug) -ForegroundColor Cyan

    try {
        $getResp = $null
        $backoffs = @(20, 45)
        for ($attempt = 1; $attempt -le ($backoffs.Count + 1); $attempt++) {
            try {
                $getResp = Invoke-WebRequest -Uri $base -UserAgent $ua -TimeoutSec 25 -SessionVariable session -ErrorAction Stop
                break
            } catch {
                if ($attempt -le $backoffs.Count) {
                    $wait = $backoffs[$attempt - 1]
                    Write-Host ("      GET attempt {0} failed ({1}) - backing off {2}s and retrying" -f $attempt, $_.Exception.Message, $wait) -ForegroundColor Yellow
                    Start-Sleep -Seconds $wait
                } else {
                    throw
                }
            }
        }
        $html = $getResp.Content

        $metaTag = [regex]::Match($html, '<meta[^>]*name=["'']csrf_token["''][^>]*>')
        $csrf = $null
        if ($metaTag.Success) {
            $contentAttr = [regex]::Match($metaTag.Value, 'content=["'']([^"'']+)["'']')
            if ($contentAttr.Success) { $csrf = $contentAttr.Groups[1].Value }
        }
        if (-not $csrf) {
            Write-Host "      no csrf_token meta tag found - skipping (page structure may have changed)" -ForegroundColor Yellow
            continue
        }

        $start = 0
        $length = 2000
        $collected = @()
        $recordsTotal = $null
        do {
            $columns = $columnNames | ForEach-Object {
                [ordered]@{
                    data       = $_
                    name       = ""
                    searchable = $true
                    orderable  = $true
                    search     = [ordered]@{ value = ""; regex = $false }
                }
            }
            $payload = [ordered]@{
                draw    = 1
                columns = @($columns)
                order   = @(@{ column = 0; dir = "asc"; name = "" })
                start   = $start
                length  = $length
                search  = [ordered]@{ value = ""; regex = $false; fixed = @() }
                filters = @{}
            }
            $bodyJson = $payload | ConvertTo-Json -Depth 6 -Compress
            $bodyStr = "datatables_ajax_data=" + [uri]::EscapeDataString($bodyJson) + "&csrf_token=" + [uri]::EscapeDataString($csrf)

            $postResp = Invoke-RestMethod -Uri $base -Method Post -WebSession $session -UserAgent $ua -TimeoutSec 25 `
                -ContentType "application/x-www-form-urlencoded" `
                -Headers @{ "X-Requested-With" = "XMLHttpRequest" } `
                -Body $bodyStr -ErrorAction Stop

            if ($null -eq $recordsTotal) { $recordsTotal = [int]$postResp.recordsTotal }
            $gotCount = 0
            if ($postResp.data) {
                $pageRows = @($postResp.data)
                $collected += $pageRows
                $gotCount = $pageRows.Count
            }
            $start += $length
        } while ($collected.Count -lt $recordsTotal -and $gotCount -gt 0)

        if ($collected.Count -eq 0) {
            Write-Host "      0 certificates currently listed (not an error - counties empty out year-round)"
            continue
        }

        foreach ($d in $collected) {
            $addr = $d.property_address
            if ([string]::IsNullOrWhiteSpace($addr)) { $addr = $d.owner_address }
            if ([string]::IsNullOrWhiteSpace($addr) -and $d.account_number) { $addr = "Account $($d.account_number)" }
            if ([string]::IsNullOrWhiteSpace($addr)) { $addr = "Address not published - see LienHub listing" }

            $all += [pscustomobject]@{
                source          = "certificate"
                county          = $row.County
                host            = "lienhub.com"
                case_no         = $d.account_number
                certificate_no  = [string]$d.certificate_number
                tax_year        = [string]$d.tax_year
                issued_date     = $d.issued_date
                expiration_date = $d.expiration_date
                bid             = $d.purchase_amt
                owner_name      = $d.owner_name
                address         = $addr
                parcel          = $d.account_number
                assessed        = $d.assessed_value
                legal_desc      = $d.legal_description
                interest_rate   = $d.rate
                url_auction     = $base
            }
        }
        Write-Host ("      {0} certificates" -f $collected.Count) -ForegroundColor Green
    } catch {
        Write-Host ("      ERROR: {0}" -f $_.Exception.Message) -ForegroundColor Red
        continue
    }
}

if ($all.Count -eq 0) { Write-Host "Nothing harvested this run."; exit }

$all | ConvertTo-Json -Depth 4 | Set-Content $outJson -Encoding utf8
$all | Export-Csv $outCsv -NoTypeInformation -Encoding utf8

Write-Host ""
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host ("Harvested {0} certificates across {1} counties" -f $all.Count, ($all.county | Select-Object -Unique).Count)
Write-Host "Saved: $outJson"
Write-Host "==================================================" -ForegroundColor Cyan
