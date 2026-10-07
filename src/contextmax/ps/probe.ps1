<#
  probe.ps1: which optional Windows readers does this PC have? Prints one line of JSON.
  Word and Excel are started only long enough to know that they work.
#>
$ErrorActionPreference = 'SilentlyContinue'

function Test-Automation([string]$ProgId) {
    $instance = $null
    try { $instance = New-Object -ComObject $ProgId -ErrorAction Stop } catch { }
    if ($null -eq $instance) { return $false }
    try { $instance.Quit() } catch { }
    try { [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($instance) } catch { }
    return $true
}

$word = Test-Automation 'Word.Application'
$excel = Test-Automation 'Excel.Application'
$languages = @()
try {
    Add-Type -AssemblyName System.Runtime.WindowsRuntime
    $engineType = [Type]::GetType('Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType=WindowsRuntime', $true)
    $languages = @($engineType::AvailableRecognizerLanguages | ForEach-Object { $_.LanguageTag })
}
catch { }
[ordered]@{ word = $word; excel = $excel; ocr = $languages.Count -gt 0; ocr_languages = $languages } |
    ConvertTo-Json -Compress
