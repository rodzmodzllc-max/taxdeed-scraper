$ErrorActionPreference = "Continue"
$ProgressPreference = "SilentlyContinue"

# LienHub "County-Held Liens" harvester - certificates the annual May auction
# didn't sell, now available for direct purchase year-round (the certificate
# equivalent of Lands Available for Taxes). Covers 32 of the 67 counties -
# by far the biggest single certificate-sale platform. County list is
# florida_certificate_sale_platforms.csv, filtered to Platform=LienHub.
#
# *** EXPERIMENTAL - check the Action logs after the first few runs ***
# The results table is loaded via a JS grid (DataTables). This script tries
# the standard jQuery DataTables server-side POST convention, which is very
# common but not guaranteed to match LienHub's exact implementation. Falls
# back to just the first page (10 rows) per county via plain HTML parsing if
# the POST attempt fails, so a first run still gets you *something* even
# before that's confirmed correct.
#
# Requires schema-v4-certificates.sql to have been run against Supabase once
# (adds certificate_no/tax_year/issued_date/expiration_date/interest_rate
# columns + 'certificate' to the source check constraint) - see repo root.
#
# CI-adapted: paths resolved relative to this script's location, curl.exe ->
# curl, temp cookie jar via .NET's cross-platform temp path.
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
$tmpDir = [System.IO.Path]::GetTempPath()

$counties = Import-Csv $registryPath | Where-Object { $_.Platform -eq 'LienHub' }
if (-not $counties) { Write-Host "No LienHub counties found in $registryPath"; exit }

function Get-Slug($county) {
    return ($county.ToLower() -replace '[^a-z]', '')   # "Indian River" -> "indianriver", "St. Lucie" -> "stlucie"
}

$all = @()
$i = 0
foreach ($row in $counties) {
    $i++
    $slug = Get-Slug $row.County
    $base = "https://lienhub.com/county/$slug/countyheld/certificates"
    Write-Host ("[{0}/{1}] {2} ({3})" -f $i, $counties.Count, $row.County, $slug) -ForegroundColor Cyan

    $jar = Join-Path $tmpDir ("lh_" + $slug + ".txt")
    Remove-Item $jar -ErrorAction SilentlyContinue

    # Prime a session/cookies + grab the server-rendered first page as fallback.
    $html = & curl -s -c $jar -A $ua --max-time 20 $base 2>$null
    $html = $html -join "`n"
    if (-not $html -or $html -match '(?i)forbidden|access denied') {
        Write-Host "      couldn't load - skipping"
        continue
    }

    $gotViaApi = $false
    try {
        $postBody = "draw=1&start=0&length=2000&search%5Bvalue%5D=&search%5Bregex%5D=false"
        $resp = & curl -s -b $jar -c $jar -A $ua --max-time 25 `
            -H "Content-Type: application/x-www-form-urlencoded; charset=UTF-8" `
            -H "X-Requested-With: XMLHttpRequest" `
            -H "Referer: $base" `
            --data $postBody $base 2>$null
        $resp = $resp -join ""
        if ($resp -match '"data"\s*:\s*\[') {
            $json = $resp | ConvertFrom-Json
            if ($json.data -and $json.data.Count -gt 0) {
                $gotViaApi = $true
                foreach ($d in $json.data) {
                    # DataTables rows are usually arrays of column values, in the
                    # same left-to-right order as the visible table.
                    $cols = @($d)
                    $all += [pscustomobject]@{
                        source          = "certificate"
                        county          = $row.County
                        host            = "lienhub.com"
                        case_no         = ($cols[0] -replace '<[^>]+>','').Trim()
                        tax_year        = if ($cols.Count -gt 1) { $cols[1] } else { $null }
                        certificate_no  = if ($cols.Count -gt 2) { ($cols[2] -replace '<[^>]+>','').Trim() } else { $null }
                        issued_date     = if ($cols.Count -gt 3) { $cols[3] } else { $null }
                        expiration_date = if ($cols.Count -gt 4) { $cols[4] } else { $null }
                        bid             = if ($cols.Count -gt 5) { [double](($cols[5] -replace '[^0-9.]','')) } else { $null }
                        url_auction     = $base
                    }
                }
                Write-Host ("      {0} certificates (via API)" -f $json.data.Count) -ForegroundColor Green
            }
        }
    } catch { }

    if (-not $gotViaApi) {
        # Fallback: parse the ~10 rows already sitting in the initial page HTML.
        $rows = [regex]::Matches($html, '<tr[^>]*>\s*<td[^>]*>([^<]+)</td>\s*<td[^>]*>([^<]+)</td>\s*<td[^>]*>([^<]+)</td>\s*<td[^>]*>([^<]+)</td>\s*<td[^>]*>([^<]+)</td>\s*<td[^>]*>\$?([\d,\.]+)</td>')
        foreach ($m in $rows) {
            $all += [pscustomobject]@{
                source          = "certificate"
                county          = $row.County
                host            = "lienhub.com"
                case_no         = $m.Groups[1].Value.Trim()
                tax_year        = $m.Groups[2].Value.Trim()
                certificate_no  = $m.Groups[3].Value.Trim()
                issued_date     = $m.Groups[4].Value.Trim()
                expiration_date = $m.Groups[5].Value.Trim()
                bid             = [double]($m.Groups[6].Value -replace ',','')
                url_auction     = $base
            }
        }
        if ($rows.Count -gt 0) {
            Write-Host ("      {0} certificates (fallback: first page only, more likely exist)" -f $rows.Count) -ForegroundColor Yellow
        } else {
            Write-Host "      0 certificates found - parsing may need adjustment"
        }
    }
}

if ($all.Count -eq 0) { Write-Host "Nothing harvested - see the EXPERIMENTAL note at the top of this script."; exit }

$all | ConvertTo-Json -Depth 4 | Set-Content $outJson -Encoding utf8
$all | Export-Csv $outCsv -NoTypeInformation -Encoding utf8

Write-Host ""
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host ("Harvested {0} certificates across {1} counties" -f $all.Count, ($all.county | Select-Object -Unique).Count)
Write-Host "Saved: $outJson"
Write-Host "==================================================" -ForegroundColor Cyan
