<#
  ocr.ps1: read the page images (*.png) of one folder, in name order, with the text recognition
  built into Windows. Prints one line of JSON per page: {"page", "language", "width", "height", "angle", "lines"},
  each line [x, y, width, height, text] in pixels, or {"page", "language", "error"}.
  -Language picks the recognizer (a tag such as ru or en-GB); without it, the first language of the
  user's that Windows can read, else the first one installed.
#>
param([Parameter(Mandatory)][string]$Pages, [string]$Language = '')
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
Add-Type -AssemblyName System.Runtime.WindowsRuntime

# The Windows Runtime types used below, loaded by name and kept under their short name.
$runtimeTypes = @{}
foreach ($fullName in 'Windows.Storage.StorageFile', 'Windows.Storage.Streams.IRandomAccessStream',
                      'Windows.Graphics.Imaging.BitmapDecoder', 'Windows.Graphics.Imaging.SoftwareBitmap',
                      'Windows.Media.Ocr.OcrEngine', 'Windows.Media.Ocr.OcrResult', 'Windows.Globalization.Language') {
    $shortName = $fullName.Substring($fullName.LastIndexOf('.') + 1)
    $runtimeTypes[$shortName] = [Type]::GetType("$fullName, Windows.Foundation, ContentType=WindowsRuntime", $true)
}

# Windows Runtime calls finish later. The generic AsTask(IAsyncOperation<T>) wraps such a call in a
# .NET task to wait on; it is made concrete once per result type.
$asTask = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.IsGenericMethodDefinition -and
    (($_.GetParameters() | ForEach-Object { $_.ParameterType.Name }) -join ',') -eq 'IAsyncOperation`1'
} | Select-Object -First 1
$asTaskFor = @{}

function Wait-Result([object]$Operation, [type]$ResultType) {
    if (-not $asTaskFor.ContainsKey($ResultType)) {
        $asTaskFor[$ResultType] = $asTask.MakeGenericMethod($ResultType)
    }
    $task = $asTaskFor[$ResultType].Invoke($null, @($Operation))
    [void]$task.Wait(-1)
    $task.Result
}

$ocrEngine = $runtimeTypes.OcrEngine
if ($Language) {
    $engine = $ocrEngine::TryCreateFromLanguage($runtimeTypes.Language::new($Language))
} else {
    $engine = $ocrEngine::TryCreateFromUserProfileLanguages()
    if ($null -eq $engine) {     # none of the user's languages has recognition, but another language may
        $installed = @($ocrEngine::AvailableRecognizerLanguages)
        if ($installed.Count) { $engine = $ocrEngine::TryCreateFromLanguage($installed[0]) }
    }
}
if ($null -eq $engine) { throw "No Windows text recognition language is installed$(if ($Language) { " for $Language" })." }
$tag = $engine.RecognizerLanguage.LanguageTag

$images = Get-ChildItem -LiteralPath $Pages -Filter '*.png' -File | Sort-Object -Property Name
foreach ($image in $images) {
    try {
        $file = Wait-Result ($runtimeTypes.StorageFile::GetFileFromPathAsync($image.FullName)) $runtimeTypes.StorageFile
        $stream = Wait-Result ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) $runtimeTypes.IRandomAccessStream
        try {
            $decoder = Wait-Result ($runtimeTypes.BitmapDecoder::CreateAsync($stream)) $runtimeTypes.BitmapDecoder
            $bitmap = Wait-Result ($decoder.GetSoftwareBitmapAsync()) $runtimeTypes.SoftwareBitmap
            $recognized = Wait-Result ($engine.RecognizeAsync($bitmap)) $runtimeTypes.OcrResult
        }
        finally {
            $stream.Dispose()
        }
        # each line with its box: x, y, width, height in pixels (ContextMAX lays out rows and columns)
        $lines = @(foreach ($line in $recognized.Lines) {
            $boxes = @($line.Words | ForEach-Object { $_.BoundingRect })
            $left = ($boxes | ForEach-Object { $_.X } | Measure-Object -Minimum).Minimum
            $top = ($boxes | ForEach-Object { $_.Y } | Measure-Object -Minimum).Minimum
            $right = ($boxes | ForEach-Object { $_.X + $_.Width } | Measure-Object -Maximum).Maximum
            $bottom = ($boxes | ForEach-Object { $_.Y + $_.Height } | Measure-Object -Maximum).Maximum
            ,@([int]$left, [int]$top, [int]($right - $left), [int]($bottom - $top), $line.Text)
        })
        # angle: the slant of the text, in degrees clockwise (null when Windows finds none)
        [ordered]@{ page = $image.Name; language = $tag; width = $bitmap.PixelWidth; height = $bitmap.PixelHeight
                    angle = $recognized.TextAngle; lines = $lines } | ConvertTo-Json -Compress -Depth 4
    }
    catch {
        [ordered]@{ page = $image.Name; language = $tag; error = $_.Exception.Message } | ConvertTo-Json -Compress
    }
}
