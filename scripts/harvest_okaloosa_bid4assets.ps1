$ErrorActionPreference = "Continue"
$ProgressPreference = "SilentlyContinue"

# Okaloosa is currently the only Florida county confirmed running its tax
# deed sales on Bid4Assets (checked the platform's own FL county directory -
# https://www.bid4assets.com/florida-tax-sales - on 2026-08-16; everyone else
# in realauction_counties.csv is on RealAuction). If Bid4Assets picks up more
# FL counties later, this script is the template to copy.
#
# Different platform than RealAuction: no AJAX JSON feed. The listings page
# and each property's detail page are plain server-rendered HTML, so a
# straight curl + tag-strip works. Unlike RealAuction, Bid4Assets shows the
# "Advertised Owner" right on the property page, so this fills owner_name -
# something the RealAuction harvest never gets you.
#
# NOTE: field extraction was built from a live browser session rather than
# raw HTML inspection - treat this as a first pass; check the Action logs
# after the first few automated runs to confirm fields are actually
# populating.
#
# CI-adapted: paths resolved relative to this script's location, curl.exe ->
# curl. Merges its results into harvest_all.json / harvest_all.csv (same
# output dir as harvest_all_counties.ps1 - run that one first), so the
# existing sync-harvest-to-supabase.ps1 picks up Okaloosa with no changes.

$here = $PSScriptRoot
$ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
$listingsBase = "https://www.bid4assets.com/OkaloosaFLTax/listings"
$county = "Okaloosa"
$outDir = Join-Path $here "../out"
New-Item -ItemType Directory -Force -Path $outDir | Out-Null
$outJson = Join-Path $outDir "harvest_all.json"
$outCsv  = Join-Path $outDir "harvest_all.csv"

function ConvertTo-FlatLines($html) {
    $t = $html -replace '(?is)<script.*?</script>', ''
    $t = $t -replace '(?is)<style.*?</style>', ''
    $t = $t -replace '(?i)<(br|/tr|/div|/li|/p|/dd|/dt|/td)\s*/?>', "`n"
    $t = $t -replace '<[^>]+>', "`n"
    $t = [System.Net.WebUtility]::HtmlDecode($t)
    return ($t -split "`n") | ForEach-Object { $_.Trim() } | Where-Object { $_ -ne "" }
}

# Finds a label whether it's "Label: value" on one line, or "Label" on its
# own line with the value as the very next non-empty line (both patterns
# show up across these government auction templates).
function Get-B4AValue($lines, $label) {
    for ($i = 0; $i -lt $lines.Count; $i++) {
        if ($lines[$i] -match ('^' + [regex]::Escape($label) + '\s*:?\s*(.+)$')) {
            $v = $matches[1].Trim()
            if ($v) { return $v }
            if ($i + 1 -lt $lines.Count) { return $lines[$i + 1] }
        }
    }
    return $null
}
function ToNum($s) {
    if (-not $s) { return $null }
    $c = ($s -replace '[^0-9.]', '')
    if ($c -match '^\d+(\.\d+)?$') { return [double]$c }
    return $null
}

# ---- 1. discover sale dates from the listings page's date dropdown ----
$listHtml = & curl -s -A $ua --max-time 20 $listingsBase 2>$null
$listHtml = $listHtml -join "`n"
$dates = [regex]::Matches($listHtml, '<option[^>]+value="(\d{8})"') |
         ForEach-Object { $_.Groups[1].Value } | Select-Object -Unique
$dates = $dates | Where-Object {
    try { [datetime]::ParseExact($_, "yyyyMMdd", $null) -ge (Get-Date).Date } catch { $false }
}
if (-not $dates) { Write-Host "No upcoming Okaloosa sale dates found."; exit }
Write-Host ("Found {0} upcoming sale date(s): {1}" -f $dates.Count, ($dates -join ", "))

# ---- 2. per date, list auction IDs ----
$ids = @()
foreach ($d in $dates) {
    $html = & curl -s -A $ua --max-time 20 "$listingsBase`?salesdate=$d" 2>$null
    $html = $html -join "`n"
    $pageIds = [regex]::Matches($html, 'href="/auction/(\d+)"') |
               ForEach-Object { $_.Groups[1].Value } | Select-Object -Unique
    Write-Host ("  {0}: {1} listing(s)" -f $d, $pageIds.Count)
    $ids += $pageIds
}
$ids = $ids | Select-Object -Unique

# ---- 3. per property detail page ----
$results = @()
$i = 0
foreach ($id in $ids) {
    $i++
    Write-Host ("[{0}/{1}] auction {2}" -f $i, $ids.Count, $id) -ForegroundColor Cyan
    $html = & curl -s -A $ua --max-time 20 "https://www.bid4assets.com/auction/index/$id" 2>$null
    $html = $html -join "`n"
    if (-not $html) { continue }
    $lines = ConvertTo-FlatLines $html

    # Title line looks like: "... > Auction Detail > (1299795) 908 TOKALON CT ..."
    $titleLine = $lines | Where-Object { $_ -match 'Auction Detail' } | Select-Object -First 1
    $addr = $null
    if ($titleLine -match '\(\d+\)\s*(.+)$') { $addr = $matches[1].Trim() }
    if (-not $addr) {
        $h = $lines | Where-Object { $_ -match ',\s*FL\s*\d{5}' } | Select-Object -First 1
        if ($h) { $addr = $h }
    }
    if ($addr -match '(?i)withdrawn') {
        Write-Host "      withdrawn - skipping"
        continue
    }

    $parcel   = Get-B4AValue $lines 'Parcel Number'
    $caseNo   = Get-B4AValue $lines 'Tax Deed Number'
    $cert     = Get-B4AValue $lines 'Certificate Number'
    $owner    = Get-B4AValue $lines 'Advertised Owner'
    $saleDate = Get-B4AValue $lines 'Sale Date'
    $bidTxt   = Get-B4AValue $lines 'Minimum Bid'
    if (-not $bidTxt) { $bidTxt = Get-B4AValue $lines 'Current BID' }
    $bid = ToNum $bidTxt

    if ($saleDate -match '^(\d{2})/(\d{2})/(\d{4})') {
        $saleDate = "$($matches[1])/$($matches[2])/$($matches[3])"
    }

    if (-not $caseNo) { $caseNo = "B4A-$id" }

    $results += [pscustomobject]@{
        _key        = "$county|$caseNo"
        county      = $county
        host        = "bid4assets.com"
        sale_date   = $saleDate
        case        = $caseNo
        cert        = $cert
        bid         = $bid
        assessed    = $null
        parcel      = $parcel
        appraiser   = $null
        address     = $addr
        auction_url = "https://www.bid4assets.com/auction/index/$id"
        owner       = $owner   # extra field the RealAuction feed never gives us
    }
    Write-Host ("      {0} | {1} | bid {2}" -f $caseNo, $addr, $bidTxt) -ForegroundColor Green
}

if ($results.Count -eq 0) { Write-Host "Nothing harvested."; exit }

# ---- 4. merge into harvest_all.json / .csv ----
$existing = @()
if (Test-Path $outJson) {
    $existing = @(Get-Content $outJson -Raw | ConvertFrom-Json)
}
$existingKeys = $existing | ForEach-Object { "$($_.county)|$($_.case)" }
$new = $results | Where-Object { $existingKeys -notcontains $_._key } | Select-Object * -ExcludeProperty _key
$merged = @($existing) + @($new)

$merged | ConvertTo-Json -Depth 4 | Set-Content $outJson -Encoding utf8
$merged | Select-Object county,sale_date,case,bid,assessed,parcel,address,appraiser,auction_url |
    Export-Csv $outCsv -NoTypeInformation -Encoding utf8

Write-Host ""
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host ("Okaloosa: {0} properties harvested, {1} new (merged into harvest_all.json)" -f $results.Count, $new.Count)
Write-Host ("harvest_all.json now has {0} properties total" -f $merged.Count)
Write-Host "==================================================" -ForegroundColor Cyan
