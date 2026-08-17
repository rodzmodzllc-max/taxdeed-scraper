$ErrorActionPreference = "Continue"
$ProgressPreference = "SilentlyContinue"

# Harvest every scheduled tax deed auction property across all Realauction
# counties in Florida. The feed itself carries case #, certificate #, opening
# bid, parcel ID, an appraiser deep-link and the full address — and in some
# counties the assessed value too — so this gets most of the record without
# any per-property research.
#
# No bid filter: every scheduled property is captured, regardless of opening
# bid. Filter/sort in the app or in SQL, not here.
#
# CI-adapted (originally run by hand on a local PC - see git history for the
# path-hardcoded version). Paths are resolved relative to this script's own
# location so it runs the same on a GitHub Actions runner as anywhere else.
# curl.exe -> curl (Windows-only alias; ubuntu-latest ships plain curl).
#
# Output: harvest_all.json  (+ harvest_all.csv for eyeballing)

$here = $PSScriptRoot
$ua  = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
$csv = Join-Path $here "../data/realauction_counties.csv"
$outDir = Join-Path $here "../out"
New-Item -ItemType Directory -Force -Path $outDir | Out-Null
$outJson = Join-Path $outDir "harvest_all.json"
$outCsv  = Join-Path $outDir "harvest_all.csv"
$tmpDir = [System.IO.Path]::GetTempPath()

function Get-Field($block, $label) {
    # Labels look like:  @CAD_LBL\" scope=\"row\">Opening Bid:@F ... @CAD_DTA\">VALUE
    $pat = [regex]::Escape($label) + ':(?:@F|<)[\s\S]{0,200}?CAD_DTA\\">\s*([^@<]*(?:<a[^>]*>([^<]*)</a>)?[^@<]*)'
    $m = [regex]::Match($block, $pat)
    if (-not $m.Success) { return $null }
    $v = if ($m.Groups[2].Success -and $m.Groups[2].Value) { $m.Groups[2].Value } else { $m.Groups[1].Value }
    return ($v -replace '\\"','"' -replace '\s+',' ').Trim()
}
function Get-Href($block, $label) {
    $pat = [regex]::Escape($label) + ':[\s\S]{0,200}?href=\\"([^\\"]+)\\"'
    $m = [regex]::Match($block, $pat)
    if ($m.Success) { return ($m.Groups[1].Value -replace '&amp;','&') }
    return $null
}
function ToNum($s) {
    if (-not $s) { return $null }
    $c = ($s -replace '[^0-9.]','')
    if ($c -match '^\d+(\.\d+)?$') { return [double]$c }
    return $null
}

$counties = Import-Csv $csv
$all = @()
$ci = 0

foreach ($c in $counties) {
    $ci++
    $hostName = $c.Host
    Write-Host ("[{0}/{1}] {2}" -f $ci, $counties.Count, $c.County) -ForegroundColor Cyan

    $jar = Join-Path $tmpDir ("ra_" + $c.County + ".txt")
    Remove-Item $jar -ErrorAction SilentlyContinue

    $cal = & curl -s -c $jar -A $ua --max-time 20 "https://$hostName/index.cfm?zaction=USER&zmethod=CALENDAR" 2>$null
    # Quote style around dayid=... varies by county skin - most Realauction
    # sites emit dayid='MM/DD/YYYY' (single quotes), but at least Suwannee's
    # emits dayid="MM/DD/YYYY" (double quotes). The old single-quote-only
    # pattern silently matched zero dates on those counties, which then hit
    # the "no auction days" branch below and got skipped entirely even
    # though they had real, upcoming, fully-populated auctions - this is
    # exactly what happened to Suwannee. Match either quote character.
    $dates = [regex]::Matches(($cal -join "`n"), "CALSELT[^>]*dayid=['`"](\d{2}/\d{2}/\d{4})['`"]") |
             ForEach-Object { $_.Groups[1].Value } | Select-Object -Unique
    if (-not $dates) { Write-Host "      no auction days" -ForegroundColor DarkGray; continue }

    foreach ($date in $dates) {
        & curl -s -b $jar -c $jar -A $ua --max-time 20 `
            -H "Referer: https://$hostName/index.cfm?zaction=USER&zmethod=CALENDAR" `
            "https://$hostName/index.cfm?zaction=AUCTION&zmethod=PREVIEW&AuctionDate=$date" -o /dev/null 2>$null

        $kept = 0; $seen = 0
        for ($page = 0; $page -lt 12; $page++) {
            $json = & curl -s -b $jar -c $jar -A $ua --max-time 25 `
                -H "Accept: application/json, text/javascript, */*; q=0.01" `
                -H "X-Requested-With: XMLHttpRequest" `
                -H "Referer: https://$hostName/index.cfm?zaction=AUCTION&zmethod=PREVIEW&AuctionDate=$date" `
                "https://$hostName/index.cfm?zaction=AUCTION&Zmethod=UPDATE&FNC=LOAD&AREA=W&PageDir=$page&doR=1&bypassPage=1&test=1" 2>$null
            $txt = $json -join ""
            if (-not $txt -or $txt -notmatch 'AITEM_') { break }

            $blocks = [regex]::Split($txt, 'AITEM_') | Select-Object -Skip 1
            if ($blocks.Count -eq 0) { break }
            $newOnPage = 0

            foreach ($b in $blocks) {
                $seen++
                $case = Get-Field $b 'Case #'
                if (-not $case) { continue }
                $case = ($case -replace '<[^>]+>','').Trim()
                $key = "$($c.County)|$case"
                if ($all | Where-Object { $_._key -eq $key }) { continue }
                $newOnPage++

                $bid = ToNum (Get-Field $b 'Opening Bid')

                $addrLine = Get-Field $b 'Property Address'
                # The city/state/zip sits in an unlabelled CAD_DTA right after the street
                $cityM = [regex]::Match($b, 'Property Address:[\s\S]{0,400}?CAD_DTA\\">[^@]*@[A-Z]CAD_LBL\\"[^>]*>\s*@[A-Z]CAD_DTA\\">([^@<]+)')
                $city = if ($cityM.Success) { ($cityM.Groups[1].Value -replace '\s+',' ').Trim() } else { "" }
                $addr = (($addrLine + ", " + $city) -replace '^,\s*','' -replace ',\s*$','').Trim()

                $all += [pscustomobject]@{
                    _key       = $key
                    county     = $c.County -replace '-',' '
                    host       = $hostName
                    sale_date  = $date
                    case       = $case
                    cert       = (Get-Field $b 'Certificate #')
                    bid        = $bid
                    assessed   = ToNum (Get-Field $b 'Assessed Value')
                    parcel     = ((Get-Field $b 'Parcel ID') -replace '<[^>]+>','').Trim()
                    appraiser  = Get-Href $b 'Parcel ID'
                    address    = $addr
                    auction_url= "https://$hostName/index.cfm?zaction=AUCTION&zmethod=PREVIEW&AuctionDate=$date"
                }
                $kept++
            }
            if ($newOnPage -eq 0) { break }
        }
        if ($kept -gt 0) { Write-Host ("      {0}  {1} properties (of {2} seen)" -f $date, $kept, $seen) -ForegroundColor Green }
    }
}

$all | Select-Object * -ExcludeProperty _key | ConvertTo-Json -Depth 4 | Set-Content $outJson -Encoding utf8
$all | Select-Object county,sale_date,case,bid,assessed,parcel,address,appraiser,auction_url |
    Export-Csv $outCsv -NoTypeInformation -Encoding utf8

Write-Host ""
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host ("Harvested {0} properties total (no bid filter)" -f $all.Count)
Write-Host ("Counties with matches: {0}" -f ($all.county | Select-Object -Unique).Count)
Write-Host ("With bid amount: {0}" -f ($all | Where-Object { $_.bid }).Count)
Write-Host ("With assessed value from the feed: {0}" -f ($all | Where-Object { $_.assessed }).Count)
Write-Host ("With parcel ID: {0}" -f ($all | Where-Object { $_.parcel }).Count)
Write-Host ("With appraiser deep-link: {0}" -f ($all | Where-Object { $_.appraiser }).Count)
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "Saved: $outJson"
