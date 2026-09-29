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
# Output: harvest_all.json (+ harvest_all.csv for eyeballing)

$here = $PSScriptRoot
$ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
$csv = Join-Path $here "../data/realauction_counties.csv"
$outDir = Join-Path $here "../out"
New-Item -ItemType Directory -Force -Path $outDir | Out-Null
$outJson = Join-Path $outDir "harvest_all.json"
$outCsv = Join-Path $outDir "harvest_all.csv"
# Phase 30B: per-county completeness record, same shape and purpose as
# harvest_lienhub_certificates.ps1's harvest_certificates_status.json -
# consumed by sync-harvest-to-supabase.ps1's stale-row closeout to decide
# which counties are safe to reconcile against. RealAuction's AJAX feed has
# no server-reported total to positively confirm pagination reached (unlike
# LienHub's recordsTotal), so COMPLETE here means "every transport-level
# request this county's harvest made actually succeeded" - never merely
# "the parsing loop didn't throw". See
# claude/phase-30b-deed-completeness-and-closed-gone-since.md.
$outStatus = Join-Path $outDir "harvest_all_status.json"
$tmpDir = [System.IO.Path]::GetTempPath()

# Get-Field / Get-Href / ToNum / Get-ParcelFields live in a dot-sourced file so
# tests/pwsh/realauction_fields.tests.ps1 can run them against captured blocks.
. (Join-Path $here "realauction_fields.ps1")

$counties = Import-Csv $csv
# A List + HashSet rather than a plain @() array, for two separate reasons -
# both of which were real, measured costs, not micro-optimisation:
#
#  1. `$all += $x` on a PowerShell array ALLOCATES A WHOLE NEW ARRAY and
#     copies every existing element, every single time. Appending n rows is
#     O(n^2) copying.
#  2. The dedupe below used to be `if ($all | Where-Object { $_._key -eq $key })`
#     - a full pipeline scan of every row harvested so far, run once per
#     property block seen. At the volume this harvest now runs at (~12,000
#     blocks seen to keep ~3,600 rows) that is ~20 MILLION comparisons,
#     versus ~12,000 hash probes for the same result - and it degrades
#     quadratically as more counties/inventory are added, so it gets worse
#     precisely as the project grows.
#
# A HashSet lookup is O(1) and List.Add() is amortised O(1), so both costs
# collapse to linear. Behaviour is otherwise identical: same rows, same
# order, same first-wins dedupe semantics.
$all = [System.Collections.Generic.List[object]]::new()
$seenKeys = [System.Collections.Generic.HashSet[string]]::new()
$countyStatus = @()
$ci = 0

:countyLoop foreach ($c in $counties) {
    $ci++
    $hostName = $c.Host
    Write-Host ("[{0}/{1}] {2}" -f $ci, $counties.Count, $c.County) -ForegroundColor Cyan

    $jar = Join-Path $tmpDir ("ra_" + $c.County + ".txt")
    Remove-Item $jar -ErrorAction SilentlyContinue

    # Phase 30B: this county is COMPLETE unless a transport-level request
    # actually fails (curl exits non-zero, including --fail's non-2xx
    # detection). A page/date that legitimately has nothing left is a
    # content-level signal (no AITEM_ match, zero new blocks) and stays a
    # normal loop-exit, not a failure - completeness tracks REQUEST success,
    # not row count, exactly like harvest_lienhub_certificates.ps1's
    # transport-failure paths (GET-retry exhaustion, malformed response)
    # versus its content-level "confirmed empty" path.
    $countyOk = $true
    $countyFailReason = $null
    $countyRowsBefore = $all.Count

    # The calendar page defaults to showing ONLY the currently-displayed
    # month - confirmed live on Suwannee: the default page showed just
    # 08/06/2026 (already past), while the site's own "September >" link
    # revealed a fully-populated 09/03/2026 auction (2 pages of listings)
    # that the single-month fetch below would silently miss entirely,
    # exactly like the "no auction days" bug this same block used to have
    # for the quote-style mismatch. Realauction's own "next month" link
    # hits this same CALENDAR endpoint with a selCalDate={ts 'YYYY-MM-01
    # 00:00:00'} param, so walk the current month plus the next 2 that way
    # to catch anything scheduled up to ~3 months out, not just this month.
    $dates = @()
    for ($mOffset = 0; $mOffset -lt 3; $mOffset++) {
        $monthStart = (Get-Date).AddMonths($mOffset)
        $tsLiteral = "{{ts '{0:yyyy-MM}-01 00:00:00'}}" -f $monthStart
        $calUrl = "https://$hostName/index.cfm?zaction=user&zmethod=calendar&selCalDate=" + [uri]::EscapeDataString($tsLiteral)
        # --fail: makes curl report a non-2xx response as a real failure
        # (exit 22) instead of silently returning the error page's body as
        # if it were calendar HTML - purely an observational change (no
        # different headers, cadence, or retries) so this script can finally
        # tell "the county genuinely has nothing scheduled" apart from "the
        # request didn't work". See the completeness-tracking comment above.
        $cal = & curl -s --fail -c $jar -A $ua --max-time 20 $calUrl 2>$null
        if ($LASTEXITCODE -ne 0) {
            $countyOk = $false
            $countyFailReason = "calendar fetch failed for month offset $mOffset (curl exit $LASTEXITCODE)"
            break
        }
        # Quote style around dayid=... varies by county skin - most Realauction
        # sites emit dayid='MM/DD/YYYY' (single quotes), but at least Suwannee's
        # emits dayid="MM/DD/YYYY" (double quotes). The old single-quote-only
        # pattern silently matched zero dates on those counties, which then hit
        # the "no auction days" branch below and got skipped entirely even
        # though they had real, upcoming, fully-populated auctions - this is
        # exactly what happened to Suwannee. Match either quote character.
        $dates += [regex]::Matches(($cal -join "`n"), "CALSELT[^>]*dayid=['`"](\d{2}/\d{2}/\d{4})['`"]") |
            ForEach-Object { $_.Groups[1].Value }
    }
    $dates = $dates | Select-Object -Unique

    if (-not $countyOk) {
        Write-Host ("  INCOMPLETE: {0}" -f $countyFailReason) -ForegroundColor Red
        $countyStatus += [pscustomobject]@{
            county   = $c.County
            status   = "INCOMPLETE"
            rowCount = ($all.Count - $countyRowsBefore)
            reason   = $countyFailReason
        }
        continue countyLoop
    }
    if (-not $dates) {
        Write-Host "  no auction days" -ForegroundColor DarkGray
        $countyStatus += [pscustomobject]@{
            county   = $c.County
            status   = "COMPLETE"
            rowCount = 0
            reason   = "confirmed no scheduled auctions - calendar fetch succeeded across all 3 month windows"
        }
        continue countyLoop
    }

    :dateLoop foreach ($date in $dates) {
        & curl -s --fail -b $jar -c $jar -A $ua --max-time 20 `
            -H "Referer: https://$hostName/index.cfm?zaction=USER&zmethod=CALENDAR" `
            "https://$hostName/index.cfm?zaction=AUCTION&zmethod=PREVIEW&AuctionDate=$date" -o /dev/null 2>$null
        if ($LASTEXITCODE -ne 0) {
            $countyOk = $false
            $countyFailReason = "preview/referer warm-up fetch failed for $date (curl exit $LASTEXITCODE)"
            break dateLoop
        }

        $kept = 0; $seen = 0
        for ($page = 0; $page -lt 12; $page++) {
            $json = & curl -s --fail -b $jar -c $jar -A $ua --max-time 25 `
                -H "Accept: application/json, text/javascript, */*; q=0.01" `
                -H "X-Requested-With: XMLHttpRequest" `
                -H "Referer: https://$hostName/index.cfm?zaction=AUCTION&zmethod=PREVIEW&AuctionDate=$date" `
                "https://$hostName/index.cfm?zaction=AUCTION&Zmethod=UPDATE&FNC=LOAD&AREA=W&PageDir=$page&doR=1&bypassPage=1&test=1" 2>$null
            if ($LASTEXITCODE -ne 0) {
                $countyOk = $false
                $countyFailReason = "paginated fetch failed for $date page $page (curl exit $LASTEXITCODE)"
                break dateLoop
            }
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
                # HashSet.Add() returns $false if the key was already present,
                # so this is both the membership test and the insert in one
                # O(1) call - same first-wins semantics as the old scan.
                if (-not $seenKeys.Add($key)) { continue }
                $newOnPage++

                $bid = ToNum (Get-Field $b 'Opening Bid')

                $addrLine = Get-Field $b 'Property Address'
                # The city/state/zip sits in an unlabelled CAD_DTA right after the street
                $cityM = [regex]::Match($b, 'Property Address:[\s\S]{0,400}?CAD_DTA\\">[^@]*@[A-Z]CAD_LBL\\"[^>]*>\s*@[A-Z]CAD_DTA\\">([^@<]+)')
                $city = if ($cityM.Success) { ($cityM.Groups[1].Value -replace '\s+',' ').Trim() } else { "" }
                $addr = (($addrLine + ", " + $city) -replace '^,\s*','' -replace ',\s*$','').Trim()
                $pf = Get-ParcelFields $b

                $all.Add([pscustomobject]@{
                    # Use the CSV's County column as-is - it already matches the
                    # frontend's canonical spelling (e.g. "Miami-Dade", "St. Lucie").
                    # This used to run `-replace '-',' '` here, which silently
                    # turned "Miami-Dade" into "Miami Dade" on every sync. The
                    # frontend's county filter (state.counties, built from
                    # ALL_COUNTIES in app.js) only matches exact canonical
                    # spelling, so every Miami-Dade row synced under the mangled
                    # name was invisible in the app - see improvement-roadmap.md
                    # for the 2026-08-24 audit that caught this (33 stranded rows,
                    # backfilled once by hand; this fix stops it recurring).
                    county      = $c.County
                    host        = $hostName
                    sale_date   = $date
                    case        = $case
                    cert        = (Get-Field $b 'Certificate #')
                    bid         = $bid
                    assessed    = ToNum (Get-Field $b 'Assessed Value')
                    parcel      = $pf.parcel
                    appraiser   = $pf.appraiser
                    # Appraiser-side key some skins publish instead of a parcel
                    # number (Citrus, Hernando) - see Get-ParcelFields. Not a
                    # parcel, not synced; carried in the artifact as evidence.
                    alt_key     = $pf.alt_key
                    address     = $addr
                    auction_url = "https://$hostName/index.cfm?zaction=AUCTION&zmethod=PREVIEW&AuctionDate=$date"
                })
                $kept++
            }
            if ($newOnPage -eq 0) { break }
        }
        if ($kept -gt 0) { Write-Host ("  {0} {1} properties (of {2} seen)" -f $date, $kept, $seen) -ForegroundColor Green }
    }

    if ($countyOk) {
        $countyStatus += [pscustomobject]@{
            county   = $c.County
            status   = "COMPLETE"
            rowCount = ($all.Count - $countyRowsBefore)
            reason   = "calendar + pagination retrieval succeeded for every auction date found, no transport-level failure"
        }
    } else {
        Write-Host ("  INCOMPLETE: {0}" -f $countyFailReason) -ForegroundColor Red
        $countyStatus += [pscustomobject]@{
            county   = $c.County
            status   = "INCOMPLETE"
            rowCount = ($all.Count - $countyRowsBefore)
            reason   = $countyFailReason
        }
    }
}

# Always written, even when every county failed - sync-harvest-to-supabase.ps1's
# stale-row closeout needs this file to positively know which counties, if
# any, are safe to reconcile against; its own absence must mean "reconcile
# nothing", never "assume everything succeeded" (same discipline as
# harvest_lienhub_certificates.ps1's harvest_certificates_status.json).
$countyStatus | ConvertTo-Json -Depth 3 | Set-Content $outStatus -Encoding utf8
$completeCount = @($countyStatus | Where-Object { $_.status -eq "COMPLETE" }).Count
$incompleteCount = @($countyStatus | Where-Object { $_.status -eq "INCOMPLETE" }).Count
Write-Host ("Completeness: {0} COMPLETE, {1} INCOMPLETE (of {2} counties attempted)" -f $completeCount, $incompleteCount, $countyStatus.Count)

# `_key` is no longer a property on these objects (the HashSet holds the dedupe
# keys instead), so there is nothing left to exclude here - the emitted JSON is
# byte-for-byte the same shape it always was.
$all | ConvertTo-Json -Depth 4 | Set-Content $outJson -Encoding utf8
$all | Select-Object county,sale_date,case,bid,assessed,parcel,address,appraiser,alt_key,auction_url |
    Export-Csv $outCsv -NoTypeInformation -Encoding utf8

Write-Host ""
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host ("Harvested {0} properties total (no bid filter)" -f $all.Count)
Write-Host ("Counties with matches: {0}" -f ($all.county | Select-Object -Unique).Count)
Write-Host ("With bid amount: {0}" -f ($all | Where-Object { $_.bid }).Count)
Write-Host ("With assessed value from the feed: {0}" -f ($all | Where-Object { $_.assessed }).Count)
Write-Host ("With parcel ID: {0}" -f ($all | Where-Object { $_.parcel }).Count)
Write-Host ("With appraiser deep-link: {0}" -f ($all | Where-Object { $_.appraiser }).Count)
Write-Host ("With appraiser key but no parcel ID published: {0}" -f ($all | Where-Object { $_.alt_key }).Count)
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "Saved: $outJson"
