<#
  word_text.ps1: let Microsoft Word read one .doc or .rtf file and save its text as UTF-8.

  One file per process, so the caller's timeout can stop a Word that hangs on a damaged or
  password-protected file without touching the rest of the build. The source is opened
  read-only, with macros disabled. Exit code 0: the text was written. Exit code 1: the reason
  is on stderr.
#>
param(
    [Parameter(Mandatory)][string]$Source,
    [Parameter(Mandatory)][string]$Target
)
$ErrorActionPreference = 'Stop'
$word = $null
$opened = $null
$problem = $null

try {
    $word = New-Object -ComObject Word.Application
    $word.Visible = $false
    $word.DisplayAlerts = 0                                    # wdAlertsNone: no message boxes
    try { $word.AutomationSecurity = 3 } catch { }             # msoAutomationSecurityForceDisable
    try { $word.Options.ConfirmConversions = $false } catch { }
    # Documents.Open(FileName, ConfirmConversions, ReadOnly, AddToRecentFiles, PasswordDocument).
    # The password is a placeholder that Word ignores for an unprotected file; it must stay within
    # Word's 15 characters, or every Open fails with 'Command failed'. A protected file waits on a
    # prompt nobody sees, and the caller's timeout ends it.
    $opened = $word.Documents.Open($Source, $false, $true, $false, 'unprotected')
    # Automatic list and heading numbers are not part of a document's text; written out as text
    # (in this read-only copy, which is never saved) they keep "3.1 Control loop" whole.
    try { $opened.ConvertNumbersToText() } catch { }
    $text = ([string]$opened.Content.Text) -replace "`r`n?", "`n"
    [IO.File]::WriteAllText($Target, $text, (New-Object Text.UTF8Encoding $false))
}
catch {
    $problem = $_
}
finally {
    if ($opened) { try { $opened.Close(0) } catch { } }        # 0 = wdDoNotSaveChanges
    if ($word) {
        try { $word.Quit(0) } catch { }
        try { [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($word) } catch { }
    }
}
if ($null -ne $problem) {
    [Console]::Error.WriteLine($problem.Exception.Message)
    exit 1
}
exit 0
