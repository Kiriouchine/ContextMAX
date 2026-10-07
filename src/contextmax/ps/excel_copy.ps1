<#
  excel_copy.ps1: let Microsoft Excel save one workbook as an .xlsx copy.

  Used for old .xls files, whose formulas no Python library reads, and for workbooks the
  Python reader rejects. Later only the copy's formulas are used; the values always come from
  the original file, so a recalculation here can never change an archived number. The source
  is opened read-only, without macros and without updating links.
  Exit code 0: the copy was written. Exit code 1: the reason is on stderr.
#>
param(
    [Parameter(Mandatory)][string]$Source,
    [Parameter(Mandatory)][string]$Target
)
$ErrorActionPreference = 'Stop'
$excel = $null
$workbook = $null
$problem = $null

try {
    $excel = New-Object -ComObject Excel.Application
    $excel.Visible = $false
    $excel.DisplayAlerts = $false
    $excel.AskToUpdateLinks = $false
    try { $excel.AutomationSecurity = 3 } catch { }            # msoAutomationSecurityForceDisable
    try { $excel.EnableEvents = $false } catch { }
    # Workbooks.Open(FileName, UpdateLinks, ReadOnly, Format, Password): links stay as they are, and
    # the placeholder password makes a protected workbook fail at once instead of asking for one.
    $workbook = $excel.Workbooks.Open($Source, 0, $true, [Type]::Missing, 'unprotected')
    if (Test-Path -LiteralPath $Target) { Remove-Item -LiteralPath $Target -Force }
    $workbook.SaveAs($Target, 51)                              # 51 = xlOpenXMLWorkbook, an .xlsx file
    $workbook.Close($false)
    $workbook = $null
}
catch {
    $problem = $_
}
finally {
    if ($workbook) { try { $workbook.Close($false) } catch { } }
    if ($excel) {
        try { $excel.Quit() } catch { }
        try { [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($excel) } catch { }
    }
}
if ($null -ne $problem) {
    [Console]::Error.WriteLine($problem.Exception.Message)
    exit 1
}
exit 0
