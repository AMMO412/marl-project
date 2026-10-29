param([string]$InputDoc,[string]$OutputPdf)
$ErrorActionPreference='Stop'
$scopeWord=New-Object -ComObject Word.Application
$scopeWord.Visible=$false
$scopeWord.DisplayAlerts=0
$scopeWord.AutomationSecurity=3
$scopeWordDoc=$null
try {
    $scopeWordDoc=$scopeWord.Documents.Open($InputDoc,$false,$true)
    $scopeWordDoc.Repaginate()
    $scopeWordDoc.Fields.Update() | Out-Null
    foreach($scopeWordSection in $scopeWordDoc.Sections) {
        $scopeWordSection.Footers.Item(1).Range.Fields.Update() | Out-Null
    }
    $scopeWordDoc.ExportAsFixedFormat($OutputPdf,17)
    Write-Output ('Pages: ' + $scopeWordDoc.ComputeStatistics(2))
} finally {
    if($null -ne $scopeWordDoc){$scopeWordDoc.Close(0)}
    $scopeWord.Quit()
    [System.Runtime.InteropServices.Marshal]::ReleaseComObject($scopeWord) | Out-Null
}

