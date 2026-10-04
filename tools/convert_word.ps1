param([Parameter(Mandatory=$true)][string]$InputDocx,[Parameter(Mandatory=$true)][string]$OutputPdf)
$ErrorActionPreference = 'Stop'
$wordApp = $null
$wordDoc = $null
try {
    $wordApp = New-Object -ComObject Word.Application
    $wordApp.Visible = $false
    $wordApp.DisplayAlerts = 0
    $wordDoc = $wordApp.Documents.Open([System.IO.Path]::GetFullPath($InputDocx), $false, $true)
    $wordDoc.Repaginate()
    $wordDoc.ExportAsFixedFormat([System.IO.Path]::GetFullPath($OutputPdf), 17)
    Write-Output ('Microsoft Word ' + $wordApp.Version + '; PDF pages ' + $wordDoc.ComputeStatistics(2))
} finally {
    if ($wordDoc) { $wordDoc.Close(0) }
    if ($wordApp) { $wordApp.Quit() }
    if ($wordDoc) { [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($wordDoc) }
    if ($wordApp) { [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($wordApp) }
}
