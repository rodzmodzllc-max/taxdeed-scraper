# Field extraction for RealAuction / RealTaxDeed AJAX listing blocks.
#
# Dot-sourced by harvest_all_counties.ps1 and exercised directly by
# tests/pwsh/realauction_fields.tests.ps1 against real blocks captured from
# the live sites, so a label change on a county skin is caught by a test
# rather than by rows quietly arriving with an empty parcel.
#
# Each block is the JSON-escaped HTML of one auction item, split on AITEM_ by
# the harvester. Labels look like:
#   @CAD_LBL\" scope=\"row\">Opening Bid:@F tabindex=\"0\" @CAD_DTA\">$1,234.00@G

function Get-Field($block, $label) {
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

# Labels under which some county skins publish the property appraiser's OWN
# key for the property instead of a parcel number. Confirmed live 2026-09-18
# (scripts/probe_realauction_labels.py, Actions run 35402576827):
#   Citrus   -> "Alternate Key" 1028868  linking to citruspa.org ...&pin=1028868
#   Hernando -> "Parcel Key"    00190947 linking to propsearch.hernandocountypa-florida.us/parcel/00190947
# Neither value is that county's parcel-number format (Citrus: "17E19S27 10000
# 005S", Hernando: "R27 222 19 1560 0000 0081"), so neither is ever written to
# `parcel`. The deep-link is real and becomes url_appraiser; the key itself is
# emitted as alt_key so the FDOR ALT_KEY probe can test whether it resolves to
# a PARCEL_ID - it is not synced to the database until that is established.
$script:AltKeyLabels = @('Alternate Key', 'Parcel Key')

function Get-ParcelFields($block) {
    $parcel = Get-Field $block 'Parcel ID'
    if ($parcel) {
        return [pscustomobject]@{
            parcel    = ($parcel -replace '<[^>]+>','').Trim()
            appraiser = Get-Href $block 'Parcel ID'
            alt_key   = $null
        }
    }
    foreach ($label in $script:AltKeyLabels) {
        $key = Get-Field $block $label
        if ($key) {
            return [pscustomobject]@{
                parcel    = ''
                appraiser = Get-Href $block $label
                alt_key   = ($key -replace '<[^>]+>','').Trim()
            }
        }
    }
    return [pscustomobject]@{ parcel = ''; appraiser = $null; alt_key = $null }
}
