# Regression tests for scripts/realauction_fields.ps1 - no network.
#
# Fixtures are the first AITEM_ block of one live auction date per county,
# captured verbatim by scripts/probe_realauction_labels.py in Actions run
# 35402576827 on 2026-09-18 (JSON-escaped, exactly as the harvester sees
# them). Citrus and Hernando are the two counties whose 25 + 25 production
# rows carried parcel='' and no appraiser link; Alachua and Lee are the
# known-good controls that publish a real "Parcel ID".
#
# Dependency-free on purpose (no Pester): runs with plain `pwsh -File`.

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '../../scripts/realauction_fields.ps1')

$script:failures = 0
$script:passes = 0
function Assert-Equal($actual, $expected, $name) {
    if ("$actual" -ne "$expected") {
        Write-Host ("FAIL  {0}`n      expected: [{1}]`n      actual:   [{2}]" -f $name, $expected, $actual)
        $script:failures++
    } else {
        Write-Host ("ok    {0}" -f $name)
        $script:passes++
    }
}
$citrus = @'
1518765\" aria-label=\"Auction Details\" @C@E_ITEM PREVIEW\" aid=\"1518765\" rem=\"0\" isset=\"0\">@A@E_STATS\" tabindex=\"0\">@AASTAT_MSGA ASTAT_LBL\">@B@AASTAT_MSGB Astat_DATA\">@B@AASTAT_MSGC ASTAT_LBL\">@B @AASTAT_MSGD Astat_DATA\">@B@AASTAT_MSG_SOLDTO_Label ASTAT_LBL\">@B@AASTAT_MSG_SOLDTO_MSG Astat_DATA\">@B@B@A@E_DETAILS\"><@I @Cad_tab\" ><tbody>@Htabindex=\"0\" @CAD_LBL\" scope=\"row\">Auction Type:@F tabindex=\"0\" @CAD_DTA\">TAXDEED@G@Htabindex=\"0\" @CAD_LBL\" scope=\"row\" aria-label=\"Case Number\">Case #:@F tabindex=\"0\" @CAD_DTA\"> <a href=\"https://search.citrusclerk.org/TaxSmartWeb/Home/Details?id=12460\" onClick = \"return showExitPopup();\" target=\"_blank\">2026-0176TD</a> @G@Htabindex=\"0\" @CAD_LBL\" scope=\"row\">Certificate #:@F tabindex=\"0\"@CAD_DTA\">20-6043@G@Htabindex=\"0\" @CAD_LBL\" scope=\"row\">Opening Bid:@F tabindex=\"0\" @CAD_DTA\">$23,370.65@G@Htabindex=\"0\" @CAD_LBL\" scope=\"row\">Alternate Key:@F tabindex=\"0\" @CAD_DTA\"> <a href=\"http://www.citruspa.org/_Web/datalets/datalet.aspx?mode=profileall&UseSearch=no&pin=1028868&jur=19&LMparent=20\" onClick = \"return showExitPopup();\" target=\"_blank\">1028868</a> @G@Htabindex=\"0\" @CAD_LBL\" scope=\"row\">Property Address:@F tabindex=\"0\" @CAD_DTA\">9050 N RAINELLE AVE@G@H@CAD_LBL\" scope=\"row\">@F tabindex=\"0\" @CAD_DTA\">CRYSTAL RIVER, 34428@G@Htabindex=\"0\" @CAD_LBL\" scope=\"row\">Assessed Value:@F tabindex=\"0\" @CAD_DTA\">$10,352.00@G</tbody></@I>@B@B@A@E_ITEM_SPACER\">&nbsp;@B<div id=\"
'@
$hernando = @'
1519979\" aria-label=\"Auction Details\" @C@E_ITEM PREVIEW\" aid=\"1519979\" rem=\"0\" isset=\"0\">@A@E_STATS\" tabindex=\"0\">@AASTAT_MSGA ASTAT_LBL\">@B@AASTAT_MSGB Astat_DATA\">@B@AASTAT_MSGC ASTAT_LBL\">@B @AASTAT_MSGD Astat_DATA\">@B@AASTAT_MSG_SOLDTO_Label ASTAT_LBL\">@B@AASTAT_MSG_SOLDTO_MSG Astat_DATA\">@B@B@A@E_DETAILS\"><@I @Cad_tab\"><tbody>@Htabindex=\"0\" @CAD_LBL\" scope=\"row\">Auction Type:@F tabindex=\"0\" @CAD_DTA\">TAXDEED @G@Htabindex=\"0\" @CAD_LBL\" scope=\"row\" aria-label=\"Case Number\">Case #:@F @CAD_DTA\"> <a href=\"https://or.hernandoclerk.com/TaxSmart/Home/Details?id=\" onClick = \"return showExitPopup();\" target=\"_blank\">2026-081TD</a>@G@Htabindex=\"0\" @CAD_LBL\" scope=\"row\">Certificate #:@F tabindex=\"0\" @CAD_DTA\">22-0302500@G@Htabindex=\"0\" @CAD_LBL\" scope=\"row\">Opening Bid:@F tabindex=\"0\" @CAD_DTA\">$1,865.61@G@Htabindex=\"0\" @CAD_LBL\" scope=\"row\">Parcel Key:@F tabindex=\"0\" @CAD_DTA\"> <a href=\"https://propsearch.hernandocountypa-florida.us/parcel/00190947\" onClick = \"return showExitPopup();\" target=\"_blank\">00190947</a>@G@Htabindex=\"0\" @CAD_LBL\" scope=\"row\">Property Address:@F tabindex=\"0\" @CAD_DTA\">MOSS ST@G@H@CAD_LBL\" scope=\"row\">@F tabindex=\"0\" @CAD_DTA\">BROOKSVILLE, FL- 34604@G@Htabindex=\"0\" @CAD_LBL\" scope=\"row\">Assessed Value:@F tabindex=\"0\" @CAD_DTA\">$3,000.00@G</tbody></@I>@B@B@A@E_ITEM_SPACER\">&nbsp;@B<div id=\"
'@
$alachua = @'
1513937\" aria-label=\"Auction Details\" @C@E_ITEM PREVIEW\" aid=\"1513937\" rem=\"0\" isset=\"0\">@A@E_STATS\" tabindex=\"0\">@AASTAT_MSGA ASTAT_LBL\">@B@AASTAT_MSGB Astat_DATA\">@B@AASTAT_MSGC ASTAT_LBL\">@B @AASTAT_MSGD Astat_DATA\">@B@AASTAT_MSG_SOLDTO_Label ASTAT_LBL\">@B@AASTAT_MSG_SOLDTO_MSG Astat_DATA\">@B@B@A@E_DETAILS\"><@I @Cad_tab\"><tbody>@Htabindex=\"0\" @CAD_LBL\" scope=\"row\">Auction Type:@F tabindex=\"0\" @CAD_DTA\">TAXDEED @G@Htabindex=\"0\" @CAD_LBL\" scope=\"row\" aria-label=\"Case Number\">Case #:@F @CAD_DTA\"> TD 2026-024@G@Htabindex=\"0\" @CAD_LBL\" scope=\"row\">Certificate #:@F tabindex=\"0\" @CAD_DTA\">2024-477@G@Htabindex=\"0\" @CAD_LBL\" scope=\"row\">Opening Bid:@F tabindex=\"0\" @CAD_DTA\">$8,061.30@G@Htabindex=\"0\" @CAD_LBL\" scope=\"row\">Parcel ID:@F tabindex=\"0\" @CAD_DTA\"> <a href=\"https://qpublic.schneidercorp.com/Application.aspx?AppID=1081&LayerID=26490&PageTypeID=4&PageID=10770&Q=320373606&KeyValue=02684-000-000\" onClick = \"return showExitPopup();\" target=\"_blank\">02684-000-000</a>@G@Htabindex=\"0\" @CAD_LBL\" scope=\"row\">Property Address:@F tabindex=\"0\" @CAD_DTA\">UNASSIGNED LOCATION RE@G@Htabindex=\"0\" @CAD_LBL\" scope=\"row\">Assessed Value:@F tabindex=\"0\" @CAD_DTA\">$61,521.00@G</tbody></@I>@B@B@A@E_ITEM_SPACER\">&nbsp;@B<div id=\"
'@
$lee = @'
1512363\" aria-label=\"Auction Details\" @C@E_ITEM PREVIEW\" aid=\"1512363\" rem=\"0\" isset=\"0\">@A@E_STATS\" tabindex=\"0\">@AASTAT_MSGA ASTAT_LBL\">@B@AASTAT_MSGB Astat_DATA\">@B@AASTAT_MSGC ASTAT_LBL\">@B @AASTAT_MSGD Astat_DATA\">@B@AASTAT_MSG_SOLDTO_Label ASTAT_LBL\">@B@AASTAT_MSG_SOLDTO_MSG Astat_DATA\">@B@B@A@E_DETAILS\"><@I @Cad_tab\"><tbody>@Htabindex=\"0\" @CAD_LBL\" scope=\"row\">Auction Type:@F tabindex=\"0\" @CAD_DTA\">TAXDEED @G@Htabindex=\"0\" @CAD_LBL\" scope=\"row\" aria-label=\"Case Number\">Case #:@F @CAD_DTA\"> 2026000280@G@Htabindex=\"0\" @CAD_LBL\" scope=\"row\">Certificate #:@F tabindex=\"0\" @CAD_DTA\">24-01518@G@Htabindex=\"0\" @CAD_LBL\" scope=\"row\">Opening Bid:@F tabindex=\"0\" @CAD_DTA\">$5,505.03@G@Htabindex=\"0\" @CAD_LBL\" scope=\"row\">Parcel ID:@F tabindex=\"0\" @CAD_DTA\"> <a href=\"http://www.leepa.org/Scripts/PropertyQuery/PropertyQuery.aspx?STRAP=26-43-23-C3-02762.0130\" onClick = \"return showExitPopup();\" target=\"_blank\">26-43-23-C3-02762.0130</a>@G@Htabindex=\"0\" @CAD_LBL\" scope=\"row\">Property Address:@F tabindex=\"0\" @CAD_DTA\">2727 NW JUANITA PL@G@H@CAD_LBL\" scope=\"row\">@F tabindex=\"0\" @CAD_DTA\">CAPE CORAL, FL- 33993@G@Htabindex=\"0\" @CAD_LBL\" scope=\"row\">Assessed Value:@F tabindex=\"0\" @CAD_DTA\">$41,990.00@G</tbody></@I>@B@B@A@E_ITEM_SPACER\">&nbsp;@B<div id=\"
'@

# --- Citrus: "Alternate Key", no "Parcel ID" ----------------------------------
$pf = Get-ParcelFields $citrus
Assert-Equal $pf.parcel '' 'citrus: parcel stays empty (site publishes no parcel number)'
Assert-Equal $pf.alt_key '1028868' 'citrus: Alternate Key captured as alt_key'
Assert-Equal $pf.appraiser 'http://www.citruspa.org/_Web/datalets/datalet.aspx?mode=profileall&UseSearch=no&pin=1028868&jur=19&LMparent=20' 'citrus: appraiser deep-link from Alternate Key'
Assert-Equal (Get-Field $citrus 'Parcel ID') $null 'citrus: Parcel ID genuinely absent'
Assert-Equal (Get-Field $citrus 'Case #') '2026-0176TD' 'citrus: Case # (anchor text)'
Assert-Equal (Get-Field $citrus 'Certificate #') '20-6043' 'citrus: Certificate #'
Assert-Equal (ToNum (Get-Field $citrus 'Opening Bid')) 23370.65 'citrus: Opening Bid'
Assert-Equal (ToNum (Get-Field $citrus 'Assessed Value')) 10352 'citrus: Assessed Value'
Assert-Equal (Get-Field $citrus 'Property Address') '9050 N RAINELLE AVE' 'citrus: Property Address'

# --- Hernando: "Parcel Key", no "Parcel ID" -----------------------------------
$pf = Get-ParcelFields $hernando
Assert-Equal $pf.parcel '' 'hernando: parcel stays empty (site publishes no parcel number)'
Assert-Equal $pf.alt_key '00190947' 'hernando: Parcel Key captured as alt_key, leading zeros kept'
Assert-Equal $pf.appraiser 'https://propsearch.hernandocountypa-florida.us/parcel/00190947' 'hernando: appraiser deep-link from Parcel Key'
Assert-Equal (Get-Field $hernando 'Parcel ID') $null 'hernando: Parcel ID genuinely absent'
Assert-Equal (Get-Field $hernando 'Case #') '2026-081TD' 'hernando: Case # (anchor text, no tabindex before CAD_DTA)'
Assert-Equal (ToNum (Get-Field $hernando 'Opening Bid')) 1865.61 'hernando: Opening Bid'
Assert-Equal (ToNum (Get-Field $hernando 'Assessed Value')) 3000 'hernando: Assessed Value'
Assert-Equal (Get-Field $hernando 'Property Address') 'MOSS ST' 'hernando: Property Address'

# --- Alachua: control, "Parcel ID" present ------------------------------------
$pf = Get-ParcelFields $alachua
Assert-Equal $pf.parcel '02684-000-000' 'alachua: Parcel ID unchanged'
Assert-Equal $pf.appraiser 'https://qpublic.schneidercorp.com/Application.aspx?AppID=1081&LayerID=26490&PageTypeID=4&PageID=10770&Q=320373606&KeyValue=02684-000-000' 'alachua: appraiser deep-link unchanged'
Assert-Equal $pf.alt_key $null 'alachua: no alt_key when a real Parcel ID exists'
Assert-Equal (Get-Field $alachua 'Case #') 'TD 2026-024' 'alachua: Case # (plain text)'
Assert-Equal (Get-Field $alachua 'Property Address') 'UNASSIGNED LOCATION RE' 'alachua: placeholder address passes through untouched'

# --- Lee: control, dotted STRAP "Parcel ID" -----------------------------------
$pf = Get-ParcelFields $lee
Assert-Equal $pf.parcel '26-43-23-C3-02762.0130' 'lee: Parcel ID unchanged'
Assert-Equal $pf.appraiser 'http://www.leepa.org/Scripts/PropertyQuery/PropertyQuery.aspx?STRAP=26-43-23-C3-02762.0130' 'lee: appraiser deep-link unchanged'
Assert-Equal $pf.alt_key $null 'lee: no alt_key when a real Parcel ID exists'
Assert-Equal (Get-Field $lee 'Case #') '2026000280' 'lee: Case #'
Assert-Equal (ToNum (Get-Field $lee 'Opening Bid')) 5505.03 'lee: Opening Bid'

# --- Neither label at all ------------------------------------------------------
$pf = Get-ParcelFields 'Case #:@F @CAD_DTA\"> X@G@Htabindex=\"0\" @CAD_LBL\" scope=\"row\">Opening Bid:@F tabindex=\"0\" @CAD_DTA\">$1.00@G'
Assert-Equal $pf.parcel '' 'no label: parcel empty'
Assert-Equal $pf.appraiser $null 'no label: no appraiser link'
Assert-Equal $pf.alt_key $null 'no label: no alt_key'

Write-Host ""
Write-Host ("{0} passed, {1} failed" -f $script:passes, $script:failures)
if ($script:failures -gt 0) { exit 1 }
exit 0
