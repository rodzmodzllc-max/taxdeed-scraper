$ErrorActionPreference = "Continue"

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
& $permPython.Source (Join-Path $PSScriptRoot "source_permission_check.py") --source fl_realauction --operation fetch --operation parse --state FL --dataset sale_calendar
if (0 -ne $LASTEXITCODE) {
    Write-Host "::error title=source_permission::fl_realauction sale-calendar harvest not permitted (see the decision above) - stopping before any request or write"
    exit 3
}
# --- end source permission gate ------------------------------------------------

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
# Test hooks (tests/python/test_fl_auction_paging.py runs this script against
# a local fake RealAuction server): an alternate county list and output
# folder. A loopback Host (127.0.0.1 / localhost) is read over plain http;
# every other host is https, as always.
if ($env:RA_COUNTIES_CSV) { $csv = $env:RA_COUNTIES_CSV }
if ($env:RA_OUT_DIR) { $outDir = $env:RA_OUT_DIR }
New-Item -ItemType Directory -Force -Path $outDir | Out-Null
$outJson = Join-Path $outDir "harvest_all.json"
$outCsv = Join-Path $outDir "harvest_all.csv"
# Phase 30B: per-county completeness record, same shape and purpose as
# harvest_lienhub_certificates.ps1's harvest_certificates_status.json -
# consumed by sync-harvest-to-supabase.ps1's stale-row closeout to decide
# which counties are safe to reconcile against. COMPLETE here means "every
# transport-level request this county's harvest made actually succeeded" AND
# (since 2026-10-26) "every page the sale-day page itself publishes ('page 1
# of N', from its status refresh) was read" - never merely "the parsing loop
# didn't throw". Each entry carries saleDays: per sale day the items read,
# pages read, the published page count and whether the day was read in full.
# See claude/phase-30b-deed-completeness-and-closed-gone-since.md.
$outStatus = Join-Path $outDir "harvest_all_status.json"
$tmpDir = [System.IO.Path]::GetTempPath()

function Get-Field($block, $label) {
    # Labels look like: @CAD_LBL\" scope=\"row\">Opening Bid:@F ... @CAD_DTA\">VALUE
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
# The tax certificate that opened the deed application. Most RealAuction
# county skins label it "Certificate #"; a county skin may word the label
# differently. (2026-10-26, Orange: 0 of 69 active rows carried a certificate
# number. The value-free label capture - fl-field-evidence run 40383361568 -
# showed Orange DOES use "Certificate #", on all 92 items read, but publishes
# the cell EMPTY; so Orange has no certificate number to read on this feed,
# and none is invented. Hillsborough and Lee use the same label, filled.)
# Labels are tried in order and
# the first one PRESENT with a value wins; "Certificate #" stays first, so a
# county that already read correctly reads exactly as before. The label must
# be the WHOLE label cell (anchored on the CAD_LBL cell's '>' and its ':'), so
# a shorter label never matches inside a longer one and a value is never read
# from another cell. Pinned by tests/python/test_fl_field_fixes.py, which runs
# this function under pwsh.
$CertLabels = @('Certificate #', 'Certificate Number', 'Certificate No.', 'Certificate No', 'Certificate',
                'Cert #', 'Cert. #', 'Cert Number', 'Cert No.', 'Cert No', 'Cert',
                'Tax Certificate #', 'Tax Certificate Number', 'Tax Certificate No.', 'Tax Certificate No', 'Tax Certificate',
                'Tax Cert #', 'Tax Cert', 'TC #', 'TC Number')
function Get-CertificateNumber($block) {
    foreach ($label in $CertLabels) {
        $pat = 'CAD_LBL\\"[^>]*>\s*' + [regex]::Escape($label) + '\s*:(?:@F|<)[\s\S]{0,200}?CAD_DTA\\">\s*([^@<]*(?:<a[^>]*>([^<]*)</a>)?[^@<]*)'
        $m = [regex]::Match($block, $pat, [System.Text.RegularExpressions.RegexOptions]::IgnoreCase)
        if (-not $m.Success) { continue }
        $v = if ($m.Groups[2].Success -and $m.Groups[2].Value) { $m.Groups[2].Value } else { $m.Groups[1].Value }
        $v = (($v -replace '<[^>]+>','') -replace '\\"','"' -replace '\s+',' ').Trim()
        if ($v) { return $v }
    }
    return $null
}
# Value-free label vocabulary of the items read (HARVEST_LABEL_REPORT=1, set
# only by the manual evidence job's realauction_labels scope): each CAD_LBL
# label text with every digit masked, counted per county. Never a cell value.
function Get-LabelTexts($block) {
    [regex]::Matches($block, 'CAD_LBL\\"[^>]*>\s*([^@<]{1,60})') | ForEach-Object {
        ((($_.Groups[1].Value -replace '\d','#') -replace '\s+',' ').Trim().TrimEnd(':')).Trim()
    } | Where-Object { $_ }
}
# The markup around one item's certificate cell with every digit masked and
# every text node's letters masked (tag and class names kept): the SHAPE of
# the cell, so a county whose label reads correctly but whose value does not
# can be diagnosed without printing a value.
function Get-CertSkeleton($block) {
    $i = $block.IndexOf('Certificate')
    if ($i -lt 0) { return $null }
    $frag = $block.Substring([Math]::Max(0, $i - 40), [Math]::Min(320, $block.Length - [Math]::Max(0, $i - 40)))
    $frag = $frag -replace '(href|src|onclick|id|value)=\\"[^\\]*', '$1=\"...'
    $frag = [regex]::Replace($frag, '>([^<@]+)', { param($m) '>' + ($m.Groups[1].Value -creplace '[A-Za-z]', 'a') })
    return ($frag -replace '\d', '#')
}
$LabelReport = ($env:HARVEST_LABEL_REPORT -eq "1")
$LabelCounts = @{}
$LabelSkeletons = @{}

function ToNum($s) {
    if (-not $s) { return $null }
    $c = ($s -replace '[^0-9.]','')
    if ($c -match '^\d+(\.\d+)?$') { return [double]$c }
    return $null
}

$counties = Import-Csv $csv
# HARVEST_COUNTIES (comma-separated) limits the read to those counties. Set
# only by the manual evidence job's value-free label capture, which runs with
# no database credential and syncs nothing; the scheduled harvest never sets it.
if (-not [string]::IsNullOrWhiteSpace($env:HARVEST_COUNTIES)) {
    $only = @($env:HARVEST_COUNTIES -split ',' | ForEach-Object { $_.Trim() } | Where-Object { $_ })
    $counties = @($counties | Where-Object { $only -contains $_.County })
}
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
    $baseUrl = if ($hostName -match '^(127\.0\.0\.1|localhost)(:\d+)?$') { "http://$hostName" } else { "https://$hostName" }
    $saleDays = [System.Collections.Generic.List[object]]::new()
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
        $calUrl = "$baseUrl/index.cfm?zaction=user&zmethod=calendar&selCalDate=" + [uri]::EscapeDataString($tsLiteral)
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
            -H "Referer: $baseUrl/index.cfm?zaction=USER&zmethod=CALENDAR" `
            "$baseUrl/index.cfm?zaction=AUCTION&zmethod=PREVIEW&AuctionDate=$date" -o /dev/null 2>$null
        if ($LASTEXITCODE -ne 0) {
            $countyOk = $false
            $countyFailReason = "preview/referer warm-up fetch failed for $date (curl exit $LASTEXITCODE)"
            break dateLoop
        }

        # Paging (fixed 2026-10-26). The Waiting list is served ten items per
        # page and the server keeps the current page in the session. The
        # first page is PageDir=0&doR=1&bypassPage=1 (what the page itself
        # sends on load); every NEXT page is PageDir=1&doR=0&bypassPage=0
        # (auction.js changePage -> loadArea(area, 1, 0, 0)). The harvester
        # used to send PageDir=N&doR=1&bypassPage=1 for every page, which the
        # server answers with page one again - so only the first ten items of
        # each sale day were ever read (deeds run 40200487211: 62 sale days at
        # "10 of 20 seen"). Measured: paging check run 40380815661.
        #
        # The page publishes its own page count ("page 1 of 5") in the status
        # refresh it calls with the ids of the items on screen
        # (FNC=UPDATE&ref=<rlist>, fields PW / WM). A sale day is read in full
        # only when every published page was read, each brought only items
        # not seen on an earlier page, and the item count reaches the
        # published page count's minimum. Anything else marks the county
        # INCOMPLETE (never silently partial) and is recorded per sale day in
        # the status file (saleDays), which the off-list close-out reads.
        $pageSize = 10
        $maxPages = 60
        $kept = 0; $seen = 0
        $dayItemIds = [System.Collections.Generic.HashSet[string]]::new()
        $publishedPages = $null
        $pagesRead = 0
        $dayShort = $null
        for ($page = 0; $page -lt $maxPages; $page++) {
            $pageQuery = if ($page -eq 0) { "PageDir=0&doR=1&bypassPage=1" } else { "PageDir=1&doR=0&bypassPage=0" }
            $json = & curl -s --fail -b $jar -c $jar -A $ua --max-time 25 `
                -H "Accept: application/json, text/javascript, */*; q=0.01" `
                -H "X-Requested-With: XMLHttpRequest" `
                -H "Referer: $baseUrl/index.cfm?zaction=AUCTION&zmethod=PREVIEW&AuctionDate=$date" `
                "$baseUrl/index.cfm?zaction=AUCTION&Zmethod=UPDATE&FNC=LOAD&AREA=W&$pageQuery&test=1" 2>$null
            if ($LASTEXITCODE -ne 0) {
                $countyOk = $false
                $countyFailReason = "paginated fetch failed for $date page $page (curl exit $LASTEXITCODE)"
                break dateLoop
            }
            $txt = $json -join ""
            if (-not $txt -or $txt -notmatch 'AITEM_') {
                if ($page -eq 0) { $publishedPages = 0 }
                break
            }

            $blocks = [regex]::Split($txt, 'AITEM_') | Select-Object -Skip 1
            if ($blocks.Count -eq 0) {
                if ($page -eq 0) { $publishedPages = 0 }
                break
            }
            # Item identity for paging only: the block's own AITEM_<id>.
            $newItems = 0
            foreach ($b in $blocks) {
                $idM = [regex]::Match($b, '^(\d+)')
                $itemKey = if ($idM.Success) { $idM.Groups[1].Value } else { "block:" + $b.GetHashCode() }
                if ($dayItemIds.Add($itemKey)) { $newItems++ }
            }
            if ($newItems -eq 0) {
                # The server handed back a page already read: the pager did
                # not move. Past the last published page this is expected
                # (it repeats the last page); before it, the day is short.
                break
            }
            $pagesRead++

            if ($page -eq 0) {
                # The page's own status refresh, for the ids it lists.
                $refM = [regex]::Match($txt, '"rlist"\s*:\s*"([0-9,]*)"')
                $ref = if ($refM.Success) { $refM.Groups[1].Value.Trim(',') } else { "" }
                if ($ref) {
                    $upd = & curl -s --fail -b $jar -c $jar -A $ua --max-time 25 `
                        -H "Accept: application/json, text/javascript, */*; q=0.01" `
                        -H "X-Requested-With: XMLHttpRequest" `
                        -H "Referer: $baseUrl/index.cfm?zaction=AUCTION&zmethod=PREVIEW&AuctionDate=$date" `
                        "$baseUrl/index.cfm?zaction=AUCTION&ZMETHOD=UPDATE&FNC=UPDATE&ref=$ref" 2>$null
                    if ($LASTEXITCODE -ne 0) {
                        $countyOk = $false
                        $countyFailReason = "page-count refresh failed for $date (curl exit $LASTEXITCODE)"
                        break dateLoop
                    }
                    $updTxt = $upd -join ""
                    $pwM = [regex]::Match($updTxt, '"PW"\s*:\s*"\s*page\s+(\d+)\s+of\s+(\d+)\s*"', 'IgnoreCase')
                    if ($pwM.Success) { $publishedPages = [int]$pwM.Groups[2].Value }
                }
            }

            foreach ($b in $blocks) {
                $seen++
                if ($LabelReport) {
                    if (-not $LabelCounts.ContainsKey($c.County)) { $LabelCounts[$c.County] = @{} }
                    foreach ($lt in @(Get-LabelTexts $b)) { $LabelCounts[$c.County][$lt] = 1 + [int]$LabelCounts[$c.County][$lt] }
                    $LabelCounts[$c.County]['(items)'] = 1 + [int]$LabelCounts[$c.County]['(items)']
                    if (-not (Get-CertificateNumber $b)) {
                        if (-not $LabelSkeletons.ContainsKey($c.County)) { $LabelSkeletons[$c.County] = @() }
                        if ($LabelSkeletons[$c.County].Count -lt 2) { $LabelSkeletons[$c.County] += (Get-CertSkeleton $b) }
                    }
                }
                $case = Get-Field $b 'Case #'
                if (-not $case) { continue }
                $case = ($case -replace '<[^>]+>','').Trim()
                $key = "$($c.County)|$case"
                # HashSet.Add() returns $false if the key was already present,
                # so this is both the membership test and the insert in one
                # O(1) call - same first-wins semantics as the old scan.
                if (-not $seenKeys.Add($key)) { continue }

                $bid = ToNum (Get-Field $b 'Opening Bid')

                $addrLine = Get-Field $b 'Property Address'
                # The city/state/zip sits in an unlabelled CAD_DTA right after the street
                $cityM = [regex]::Match($b, 'Property Address:[\s\S]{0,400}?CAD_DTA\\">[^@]*@[A-Z]CAD_LBL\\"[^>]*>\s*@[A-Z]CAD_DTA\\">([^@<]+)')
                $city = if ($cityM.Success) { ($cityM.Groups[1].Value -replace '\s+',' ').Trim() } else { "" }
                $addr = (($addrLine + ", " + $city) -replace '^,\s*','' -replace ',\s*$','').Trim()

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
                    cert        = (Get-CertificateNumber $b)
                    bid         = $bid
                    assessed    = ToNum (Get-Field $b 'Assessed Value')
                    parcel      = ((Get-Field $b 'Parcel ID') -replace '<[^>]+>','').Trim()
                    appraiser   = Get-Href $b 'Parcel ID'
                    address     = $addr
                    auction_url = "https://$hostName/index.cfm?zaction=AUCTION&zmethod=PREVIEW&AuctionDate=$date"
                })
                $kept++
            }
            if ($null -ne $publishedPages -and $pagesRead -ge $publishedPages) { break }
        }

        # Per-sale-day verdict. Read in full = the published page count is
        # known, every published page was read, and the items read reach that
        # page count's minimum ((pages - 1) * 10 + 1). A day with no items
        # (publishedPages 0) is read in full. Never silently partial.
        $itemsRead = $dayItemIds.Count
        if ($null -eq $publishedPages) {
            $dayShort = "page count not published"
        } elseif ($pagesRead -lt $publishedPages) {
            $dayShort = "read $pagesRead of $publishedPages pages"
        } elseif ($publishedPages -gt 0 -and $itemsRead -lt (($publishedPages - 1) * $pageSize + 1)) {
            $dayShort = "read $itemsRead items, fewer than $publishedPages pages hold"
        }
        $saleDays.Add([pscustomobject]@{
            sale_date       = $date
            read            = $itemsRead
            pages_read      = $pagesRead
            published_pages = $publishedPages
            complete        = ($null -eq $dayShort)
        })
        if ($null -ne $dayShort) {
            # Keep reading the county's other sale days (their rows are still
            # synced), but the county is not a complete read.
            $countyOk = $false
            if (-not $countyFailReason) { $countyFailReason = "sale day $date read short: $dayShort" }
            Write-Host ("  {0} READ SHORT: {1}" -f $date, $dayShort) -ForegroundColor Red
        }
        if ($kept -gt 0 -or $itemsRead -gt 0) {
            Write-Host ("  {0} {1} properties ({2} items on {3} of {4} page(s))" -f $date, $kept, $itemsRead, $pagesRead, $publishedPages) -ForegroundColor Green
        }
    }

    if ($countyOk) {
        $countyStatus += [pscustomobject]@{
            county   = $c.County
            status   = "COMPLETE"
            rowCount = ($all.Count - $countyRowsBefore)
            reason   = "calendar + pagination retrieval succeeded for every auction date found, every published page of every sale day read, no transport-level failure"
            saleDays = @($saleDays)
        }
    } else {
        Write-Host ("  INCOMPLETE: {0}" -f $countyFailReason) -ForegroundColor Red
        $countyStatus += [pscustomobject]@{
            county   = $c.County
            status   = "INCOMPLETE"
            rowCount = ($all.Count - $countyRowsBefore)
            reason   = $countyFailReason
            saleDays = @($saleDays)
        }
    }
}

# Always written, even when every county failed - sync-harvest-to-supabase.ps1's
# stale-row closeout needs this file to positively know which counties, if
# any, are safe to reconcile against; its own absence must mean "reconcile
# nothing", never "assume everything succeeded" (same discipline as
# harvest_lienhub_certificates.ps1's harvest_certificates_status.json).
$countyStatus | ConvertTo-Json -Depth 5 | Set-Content $outStatus -Encoding utf8
$completeCount = @($countyStatus | Where-Object { $_.status -eq "COMPLETE" }).Count
$incompleteCount = @($countyStatus | Where-Object { $_.status -eq "INCOMPLETE" }).Count
Write-Host ("Completeness: {0} COMPLETE, {1} INCOMPLETE (of {2} counties attempted)" -f $completeCount, $incompleteCount, $countyStatus.Count)

# `_key` is no longer a property on these objects (the HashSet holds the dedupe
# keys instead), so there is nothing left to exclude here - the emitted JSON is
# byte-for-byte the same shape it always was.
$all | ConvertTo-Json -Depth 4 | Set-Content $outJson -Encoding utf8
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
Write-Host ("With certificate number: {0}" -f ($all | Where-Object { $_.cert }).Count)
foreach ($cn in @($all.county | Select-Object -Unique)) {
    $cRows = @($all | Where-Object { $_.county -eq $cn })
    $cCert = @($cRows | Where-Object { $_.cert }).Count
    if ($cCert -lt $cRows.Count) { Write-Host ("  {0}: certificate number on {1} of {2} rows" -f $cn, $cCert, $cRows.Count) }
}
if ($LabelReport) {
    Write-Host "Label vocabulary per county (digits masked, never a value):"
    foreach ($cn in @($LabelCounts.Keys | Sort-Object)) {
        foreach ($lt in @($LabelCounts[$cn].Keys | Sort-Object)) { Write-Host ("  LABEL {0} | {1} | {2}" -f $cn, $lt, $LabelCounts[$cn][$lt]) }
    }
    foreach ($cn in @($LabelSkeletons.Keys | Sort-Object)) {
        foreach ($sk in $LabelSkeletons[$cn]) { Write-Host ("  CERT-CELL-SHAPE {0} | {1}" -f $cn, $sk) }
    }
}
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "Saved: $outJson"
