; Installateur Windows de CachyMonitor (Inno Setup 6).
;
; Il empaquette l'exécutable autonome produit par PyInstaller : la personne qui
; installe n'a donc besoin ni de Python, ni de PySide6, ni de psutil.
;
; Fabrication : voir build.ps1, dans ce même dossier.

#define AppName        "CachyMonitor"
; La version vient de build.ps1, qui la lit dans APP_VERSION (cachymonitor.py) : une
; seule valeur fait foi pour le code, l'exécutable et l'installateur. La valeur de repli
; ne sert qu'à compiler ce script à la main, hors build.ps1.
#ifndef AppVersion
  #define AppVersion   "0.0.0-dev"
#endif
#define AppPublisher   "YOUNES-2-wq"
#define AppURL         "https://github.com/YOUNES-2-wq/cachymonitor"
#define AppExeName     "CachyMonitor.exe"

[Setup]
; Cet identifiant lie une version à la précédente : le garder identique d'une
; version à l'autre permet aux mises à jour de remplacer l'installation
; existante au lieu d'en créer une seconde en parallèle.
AppId={{61F32A52-2721-4AFB-8D69-CB8DF4E34FAD}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}/issues
AppUpdatesURL={#AppURL}/releases
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
LicenseFile=..\..\LICENSE
OutputDir=..\..\dist
OutputBaseFilename=CachyMonitor-Setup-{#AppVersion}
SetupIconFile=..\..\cachymonitor.ico
UninstallDisplayIcon={app}\{#AppExeName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; L'installation par défaut se fait dans le dossier de l'utilisateur, sans
; élévation. Celui qui préfère « Program Files » pour tous les comptes peut
; toujours le demander : Windows affiche alors l'invite d'administrateur.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
; L'exécutable est 64 bits (comme PySide6) : refuser les Windows 32 bits est
; plus honnête qu'installer quelque chose qui ne démarrera pas.
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0

[Languages]
Name: "french";  MessagesFile: "compiler:Languages\French.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\..\dist\{#AppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\README.md";          DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\LICENSE";            DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#AppName}";                 Filename: "{app}\{#AppExeName}"
Name: "{group}\{cm:UninstallProgram,{#AppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}";           Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent
