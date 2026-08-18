# Fabrique l'installateur Windows de CachyMonitor.
#
#   1. PyInstaller empaquette cachymonitor.py, Python et Qt en un seul .exe
#   2. Inno Setup enrobe cet .exe dans un installateur classique
#
# Prérequis :
#   python -m pip install pyinstaller pyside6 psutil
#   winget install JRSoftware.InnoSetup
#
# Utilisation, depuis n'importe où :
#   powershell -ExecutionPolicy Bypass -File packaging\windows\build.ps1

$ErrorActionPreference = "Stop"

# La racine du dépôt, déduite de l'emplacement de ce script : le build ne dépend
# donc pas du dossier depuis lequel on le lance.
$root = (Resolve-Path "$PSScriptRoot\..\..").Path
$dist = Join-Path $root "dist"
$work = Join-Path $root "build"

Write-Host "== 1/2  Empaquetage de l'executable (PyInstaller)" -ForegroundColor Cyan
python -m PyInstaller --noconfirm --clean --onefile --windowed `
    --name CachyMonitor `
    --icon      (Join-Path $root "cachymonitor.ico") `
    --add-data  ((Join-Path $root "cachymonitor.ico") + ";.") `
    --add-data  ((Join-Path $root "cachymonitor.svg") + ";.") `
    --distpath  $dist `
    --workpath  $work `
    --specpath  $work `
    (Join-Path $root "cachymonitor.py")
if ($LASTEXITCODE -ne 0) { throw "PyInstaller a echoue" }

Write-Host "== 2/2  Fabrication de l'installateur (Inno Setup)" -ForegroundColor Cyan
# Inno Setup se pose soit dans Program Files, soit — quand winget l'installe pour
# le seul utilisateur courant — sous %LOCALAPPDATA%\Programs. On regarde aussi le
# PATH, au cas où il aurait été installé autrement.
$iscc = @(
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { $iscc = (Get-Command ISCC.exe -ErrorAction SilentlyContinue).Source }
if (-not $iscc) { throw "Inno Setup introuvable. Installe-le : winget install JRSoftware.InnoSetup" }
Write-Host "   ISCC : $iscc" -ForegroundColor DarkGray

& $iscc (Join-Path $PSScriptRoot "CachyMonitor.iss")
if ($LASTEXITCODE -ne 0) { throw "Inno Setup a echoue" }

Write-Host ""
Write-Host "Termine. Resultat dans $dist :" -ForegroundColor Green
Get-ChildItem $dist -Filter *.exe |
    Select-Object Name, @{ n = "Mo"; e = { [math]::Round($_.Length / 1MB, 1) } }
