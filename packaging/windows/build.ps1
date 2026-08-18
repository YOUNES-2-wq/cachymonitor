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
$src  = Join-Path $root "cachymonitor.py"

# APP_VERSION dans cachymonitor.py est la seule source de verite : l'executable et
# l'installateur en heritent. Sans ca, les trois numeros divergent au premier oubli.
$version = (Select-String -Path $src -Pattern '^APP_VERSION\s*=\s*"([^"]+)"').Matches[0].Groups[1].Value
if (-not $version) { throw "APP_VERSION introuvable dans $src" }
Write-Host "== Version : $version" -ForegroundColor Yellow

# Metadonnees affichees par Windows dans Proprietes > Details. Le format attend
# quatre entiers, alors que APP_VERSION en compte trois : on complete par un zero.
$parts = @($version.Split('.') | ForEach-Object { [int]($_ -replace '\D.*$', '') })
while ($parts.Count -lt 4) { $parts += 0 }
$quad = $parts[0..3] -join ', '

New-Item -ItemType Directory -Force $work | Out-Null
$versionFile = Join-Path $work "version_info.txt"
@"
VSVersionInfo(
  ffi=FixedFileInfo(filevers=($quad), prodvers=($quad), mask=0x3f, flags=0x0,
                    OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName',      'YOUNES-2-wq'),
      StringStruct('FileDescription',  'CachyMonitor - moniteur systeme gaming'),
      StringStruct('FileVersion',      '$version'),
      StringStruct('InternalName',     'CachyMonitor'),
      StringStruct('LegalCopyright',   'MIT License - YOUNES-2-wq'),
      StringStruct('OriginalFilename', 'CachyMonitor.exe'),
      StringStruct('ProductName',      'CachyMonitor'),
      StringStruct('ProductVersion',   '$version')])]),
    VarFileInfo([VarStruct('Translation', [0x0409, 1200])])
  ]
)
"@ | Set-Content -Path $versionFile -Encoding UTF8

Write-Host "== 1/2  Empaquetage de l'executable (PyInstaller)" -ForegroundColor Cyan
python -m PyInstaller --noconfirm --clean --onefile --windowed `
    --name CachyMonitor `
    --icon         (Join-Path $root "cachymonitor.ico") `
    --version-file $versionFile `
    --add-data     ((Join-Path $root "cachymonitor.ico") + ";.") `
    --add-data     ((Join-Path $root "cachymonitor.svg") + ";.") `
    --distpath     $dist `
    --workpath     $work `
    --specpath     $work `
    $src
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

& $iscc "/DAppVersion=$version" (Join-Path $PSScriptRoot "CachyMonitor.iss")
if ($LASTEXITCODE -ne 0) { throw "Inno Setup a echoue" }

Write-Host ""
Write-Host "Termine. Resultat dans $dist :" -ForegroundColor Green
Get-ChildItem $dist -Filter *.exe |
    Select-Object Name, @{ n = "Mo"; e = { [math]::Round($_.Length / 1MB, 1) } }
