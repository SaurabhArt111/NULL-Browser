# Creates "Null Browser" shortcuts (Desktop + Start menu) with the Null icon. Called by setup_and_run.bat; safe to run again.
#   -Python  pythonw.exe of the environment that has Qt (no console window)     -Browser  the "Null Browser" folder
#   -Exe     (instead of -Python) a built NullBrowser.exe
param([string]$Python = "", [string]$Browser, [string]$Exe = "")
$ErrorActionPreference = "Stop"
$icon = Join-Path $Browser "null_browser\assets\icon.ico"
$shell = New-Object -ComObject WScript.Shell
$folders = @([Environment]::GetFolderPath("Desktop"), [Environment]::GetFolderPath("Programs"))
foreach ($dir in $folders) {
    if (-not $dir -or -not (Test-Path $dir)) { continue }
    $lnk = $shell.CreateShortcut((Join-Path $dir "Null Browser.lnk"))
    if ($Exe) {
        $lnk.TargetPath = $Exe
        $lnk.WorkingDirectory = Split-Path $Exe
    } else {
        $lnk.TargetPath = $Python
        $lnk.Arguments = '"' + (Join-Path $Browser "main.py") + '"'
        $lnk.WorkingDirectory = $Browser
    }
    $lnk.IconLocation = $icon + ",0"
    $lnk.Description = "Null Browser"
    $lnk.Save()
}
