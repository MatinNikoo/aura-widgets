# Removes the source version of Aura: closes the widgets, turns off "open when my PC starts",
# and if you say yes, deletes your settings, logs and saved GIFs. The files in this folder stay.
$ErrorActionPreference = "SilentlyContinue"
$folder = Split-Path -Parent $PSScriptRoot

Write-Host "Closing any running Aura widgets..."
Get-CimInstance Win32_Process |
    Where-Object { $_.Name -match "^pythonw?\.exe$" -and $_.CommandLine -and $_.CommandLine.Contains($folder) } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force }

Write-Host "Turning off open when my PC starts..."
$run = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
(Get-Item $run).Property | Where-Object { $_ -match "^(AuraWidget|AuraClockWidget|AuraGifWidget|Aura_.*)$" } | ForEach-Object {
    Remove-ItemProperty -Path $run -Name $_
    Write-Host "  removed $_"
}

$answer = Read-Host "Also delete your Aura settings, logs and saved GIFs? (y/n)"
if ($answer -eq "y") {
    Remove-Item -Recurse -Force (Join-Path $env:APPDATA "Aura")
    Remove-Item -Recurse -Force "HKCU:\Software\Aura"
    Write-Host "Deleted."
} else {
    Write-Host "Kept them in $env:APPDATA\Aura"
}
Write-Host "Done. You can delete this folder now. The Python packages from install.bat are still installed."
