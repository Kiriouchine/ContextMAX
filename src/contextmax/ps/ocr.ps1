<#
  ocr.ps1: read the page images (*.png) of one folder, in name order, with the text recognition
  built into Windows, and print the text of each page followed by an empty line.
  Nothing to install: Windows brings a recognition language with its display language.
#>
param([Parameter(Mandatory)][string]$Pages)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
Add-Type -AssemblyName System.Runtime.WindowsRuntime

# The Windows Runtime types used below, loaded by name and kept under their short name.
$runtimeTypes = @{}
foreach ($fullName in 'Windows.Storage.StorageFile', 'Windows.Storage.Streams.IRandomAccessStream',
                      'Windows.Graphics.Imaging.BitmapDecoder', 'Windows.Graphics.Imaging.SoftwareBitmap',
                      'Windows.Media.Ocr.OcrEngine', 'Windows.Media.Ocr.OcrResult') {
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

$engine = $runtimeTypes.OcrEngine::TryCreateFromUserProfileLanguages()
if ($null -eq $engine) { throw 'No Windows text recognition language is installed.' }

$images = Get-ChildItem -LiteralPath $Pages -Filter '*.png' -File | Sort-Object -Property Name
foreach ($image in $images) {
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
    $recognized.Text
    ''
}
