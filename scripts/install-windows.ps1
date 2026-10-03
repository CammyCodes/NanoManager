# Install NanoManager on Windows 10/11. Paste this into PowerShell:
#   irm https://raw.githubusercontent.com/CammyCodes/NanoManager/main/scripts/install-windows.ps1 | iex
# Downloads the latest release (it carries its own Python, nothing else to install), unpacks it to
# %LOCALAPPDATA%\Programs\NanoManager, adds Start menu + Desktop shortcuts and starts it.
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$url  = 'https://github.com/CammyCodes/NanoManager/releases/latest/download/NanoManager-windows.zip'
$dest = Join-Path $env:LOCALAPPDATA 'Programs\NanoManager'
$zip  = Join-Path $env:TEMP 'NanoManager-windows.zip'

Write-Host '- downloading NanoManager'
Invoke-WebRequest -Uri $url -OutFile $zip -UseBasicParsing
Get-Process -Name python -ErrorAction SilentlyContinue |
    Where-Object { $_.Path -like "$dest*" } | Stop-Process -Force -ErrorAction SilentlyContinue
if (Test-Path $dest) { Remove-Item $dest -Recurse -Force }
New-Item -ItemType Directory -Path $dest -Force | Out-Null
Write-Host '- unpacking'
Expand-Archive -Path $zip -DestinationPath $dest -Force
Remove-Item $zip -Force
Get-ChildItem $dest -Recurse -File | Unblock-File -ErrorAction SilentlyContinue

# Expand-Archive keeps the single top folder; flatten it
$inner = Join-Path $dest 'NanoManager'
if (Test-Path (Join-Path $inner 'python')) {
    Get-ChildItem $inner -Force | Move-Item -Destination $dest -Force
    Remove-Item $inner -Recurse -Force
}

$ws = New-Object -ComObject WScript.Shell
function New-Shortcut($path, $extra, $name) {
    $s = $ws.CreateShortcut($path)
    $s.TargetPath = Join-Path $dest 'python\python.exe'
    $s.Arguments  = "-X utf8 `"$(Join-Path $dest 'app\launcher.py')`" $extra"
    $s.WorkingDirectory = $dest
    $s.IconLocation = Join-Path $dest 'NanoManager.ico'
    $s.Description = $name
    $s.WindowStyle = 7   # minimized console
    $s.Save()
}
$menu = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs'
New-Shortcut (Join-Path $menu 'NanoManager.lnk') '' 'NanoManager'
New-Shortcut (Join-Path $menu 'NanoManager (phone access).lnk') '--share' 'NanoManager with phone access'
New-Shortcut (Join-Path ([Environment]::GetFolderPath('Desktop')) 'NanoManager.lnk') '' 'NanoManager'

Write-Host "- installed to $dest"
Write-Host '- starting NanoManager (first time: follow the pairing steps in its window)'
Start-Process -FilePath (Join-Path $dest 'python\python.exe') `
    -ArgumentList @('-X', 'utf8', (Join-Path $dest 'app\launcher.py')) -WorkingDirectory $dest -WindowStyle Minimized
