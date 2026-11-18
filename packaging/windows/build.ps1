# Fabrique l'installateur Windows de CachyMonitor.
#
#   1. PyInstaller empaquette cachymonitor.py, Python et Qt dans un dossier
#   2. Inno Setup enrobe ce dossier dans un installateur classique
#
# Le mode --onedir (un .exe et ses bibliothèques côte à côte) est préféré au
# mode --onefile (un .exe unique qui se décompresse dans un dossier temporaire
# à chaque lancement) pour deux raisons : le démarrage est immédiat, et surtout
# le bootloader auto-extractible de --onefile déclenchait des faux positifs
# heuristiques chez quatre antivirus sur soixante-dix. L'utilisateur ne voit
# aucune différence : tout reste enrobé dans l'installateur.
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

Write-Host "== 1/4  Empaquetage de l'executable (PyInstaller)" -ForegroundColor Cyan
# --noupx : si UPX arrive un jour dans le PATH, PyInstaller s'en servirait tout
# seul pour compresser les DLL, ce qui ramènerait les faux positifs antivirus.
python -m PyInstaller --noconfirm --clean --onedir --windowed --noupx `
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

# Télécharge un fichier tiers (sauf s'il est déjà là, intact) et refuse tout
# fichier dont l'empreinte SHA256 n'est pas celle attendue : seule la copie
# vérifiée peut partir dans l'installateur. Sert à PresentMon et à PawnIO.
function Get-VerifiedFile([string]$Url, [string]$File, [string]$Sha256) {
    if (-not (Test-Path $File) -or (Get-FileHash $File -Algorithm SHA256).Hash -ne $Sha256) {
        Invoke-WebRequest -Uri $Url -OutFile $File -UseBasicParsing
    }
    $hash = (Get-FileHash $File -Algorithm SHA256).Hash
    if ($hash -ne $Sha256) {
        Remove-Item $File -Force
        throw "Empreinte inattendue pour $(Split-Path $File -Leaf) ($hash) : fichier refuse"
    }
}

Write-Host "== 2/4  PresentMon (Intel, licence MIT)" -ForegroundColor Cyan
# PresentMon mesure les FPS sans Afterburner ni RivaTuner (source de secours
# depuis 1.5.0). On l'embarque tel que publié par Intel : version figée, et
# empreinte SHA256 vérifiée, pour qu'un fichier modifié ne parte jamais dans
# l'installateur. Cette empreinte est celle de la copie testée le 08/11/2026
# (signature Authenticode Intel valide, VirusTotal 0/71).
$pmVersion = "2.6.0"
$pmSha256  = "B2A706BC6AD475749E3B7E3409263AA1E6906D45BDCF993F6DBC0F660188F1AF"
$pmUrl     = "https://github.com/GameTechDev/PresentMon/releases/download/v$pmVersion/PresentMon-$pmVersion-x64.exe"
$pmLicUrl  = "https://raw.githubusercontent.com/GameTechDev/PresentMon/v$pmVersion/LICENSE.txt"
$pmDir     = Join-Path $work "presentmon"
$pmExe     = Join-Path $pmDir "PresentMon.exe"
New-Item -ItemType Directory -Force $pmDir | Out-Null
Get-VerifiedFile $pmUrl $pmExe $pmSha256
$sig = Get-AuthenticodeSignature $pmExe
if ($sig.Status -ne "Valid" -or $sig.SignerCertificate.Subject -notmatch "Intel Corporation") {
    throw "Signature de PresentMon invalide : $($sig.Status)"
}
Invoke-WebRequest -Uri $pmLicUrl -OutFile (Join-Path $pmDir "PresentMon-LICENSE.txt") -UseBasicParsing
Write-Host "   PresentMon $pmVersion : empreinte et signature Intel verifiees" -ForegroundColor DarkGray

Write-Host "== 3/4  PawnIO (namazso) : module AMD et installateur du pilote" -ForegroundColor Cyan
# Depuis 1.7.0, la température et la consommation CPU se lisent sans Afterburner
# par le pilote PawnIO (signé Microsoft), qui n'exécute que des modules signés.
# On embarque :
#   - le module AMDFamily17.bin (Ryzen), licence LGPL 2.1, non modifié ;
#   - l'installateur officiel du pilote, proposé par une case de l'installateur.
# Versions figées et empreintes vérifiées, comme PresentMon. Modules 0.2.11 et
# non 0.2.12, sortie le jour du test (17/11/2026) : trop récente.
$pwModVersion = "0.2.11"
$pwModSha256  = "43608CB89BC84247FEF1368A139013F7D043E17DB6D6C8DFC9B46BF0905A81F4"
$pwModUrl     = "https://github.com/namazso/PawnIO.Modules/releases/download/$pwModVersion/release_" + ($pwModVersion -replace '\.', '_') + ".zip"
$pwSetVersion = "2.2.0"
$pwSetSha256  = "1F519A22E47187F70A1379A48CA604981C4FCF694F4E65B734AAA74A9FBA3032"
$pwSetUrl     = "https://github.com/namazso/PawnIO.Setup/releases/download/$pwSetVersion/PawnIO_setup.exe"
$pwDir        = Join-Path $work "pawnio"
$pwZip        = Join-Path $pwDir "modules.zip"
$pwSetup      = Join-Path $pwDir "PawnIO_setup.exe"
New-Item -ItemType Directory -Force $pwDir | Out-Null
Get-VerifiedFile $pwModUrl $pwZip $pwModSha256
Get-VerifiedFile $pwSetUrl $pwSetup $pwSetSha256
$sig = Get-AuthenticodeSignature $pwSetup
if ($sig.Status -ne "Valid" -or $sig.SignerCertificate.Subject -notmatch "CN=namazso\.eu") {
    throw "Signature de PawnIO_setup.exe invalide : $($sig.Status)"
}
$pwExtract = Join-Path $pwDir "modules"
if (Test-Path $pwExtract) { Remove-Item $pwExtract -Recurse -Force }
Expand-Archive -Path $pwZip -DestinationPath $pwExtract
Copy-Item (Join-Path $pwExtract "AMDFamily17.bin") $pwDir -Force
# L'appli refuse tout module dont l'empreinte diffère de MODULE_AMD_SHA256
# (cachymon\pawnio.py) : si les deux ne concordent pas, le build s'arrête ici
# plutôt que de livrer une fonction morte.
$pyModMatch = Select-String -Path (Join-Path $root "cachymon\pawnio.py") `
    -Pattern '^MODULE_AMD_SHA256\s*=\s*"([0-9a-fA-F]{64})"'
if (-not $pyModMatch) { throw "MODULE_AMD_SHA256 introuvable dans cachymon\pawnio.py (format attendu : MODULE_AMD_SHA256 = `"<64 hex>`")" }
$pyModHash = $pyModMatch.Matches[0].Groups[1].Value
$binHash = (Get-FileHash (Join-Path $pwDir "AMDFamily17.bin") -Algorithm SHA256).Hash
if (-not $pyModHash -or $binHash -ne $pyModHash.ToUpper()) {
    throw "AMDFamily17.bin ($binHash) ne correspond pas a MODULE_AMD_SHA256 de pawnio.py ($pyModHash)"
}
Copy-Item (Join-Path $pwExtract "COPYING") (Join-Path $pwDir "PawnIO-modules-LICENSE.txt") -Force
Write-Host "   PawnIO $pwSetVersion + modules $pwModVersion : empreintes et signature verifiees" -ForegroundColor DarkGray

Write-Host "== 4/4  Fabrication de l'installateur (Inno Setup)" -ForegroundColor Cyan
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
