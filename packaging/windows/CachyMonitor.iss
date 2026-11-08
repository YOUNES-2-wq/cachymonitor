; Installateur Windows de CachyMonitor (Inno Setup 6).
;
; Il empaquette le dossier autonome produit par PyInstaller (l'exécutable et ses
; bibliothèques) : la personne qui installe n'a donc besoin ni de Python, ni de
; PySide6, ni de psutil.
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

[CustomMessages]
french.PerfGroupGroup=Mesure des FPS sans MSI Afterburner :
english.PerfGroupGroup=FPS measurement without MSI Afterburner:
french.PerfGroupTask=Autoriser PresentMon (ajoute ton compte au groupe « Utilisateurs du journal de performances » ; demande les droits administrateur ; à prendre en compte après déconnexion)
english.PerfGroupTask=Allow PresentMon (adds your account to the "Performance Log Users" group; asks for administrator rights; takes effect after signing out)
french.PerfGroupRun=Autorisation de PresentMon...
english.PerfGroupRun=Allowing PresentMon...

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
; Sans ce groupe, PresentMon (lancé sans élévation) se voit refuser les traces
; ETW de Windows : « access denied ». Le groupe est désigné par son SID, car son
; nom est traduit dans chaque langue de Windows. Pour annuler plus tard, dans un
; terminal administrateur :
;   Remove-LocalGroupMember -SID S-1-5-32-559 -Member <nom du compte>
Name: "perfgroup"; Description: "{cm:PerfGroupTask}"; GroupDescription: "{cm:PerfGroupGroup}"

[Files]
; Tout le dossier produit par PyInstaller : l'exécutable, et ses bibliothèques
; dans le sous-dossier _internal.
Source: "..\..\dist\{#AppName}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\..\README.md";          DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\README.fr.md";       DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\LICENSE";            DestDir: "{app}"; Flags: ignoreversion
; PresentMon d'Intel, téléchargé et vérifié (empreinte + signature) par build.ps1.
Source: "..\..\build\presentmon\PresentMon.exe";         DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\build\presentmon\PresentMon-LICENSE.txt"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#AppName}";                 Filename: "{app}\{#AppExeName}"
Name: "{group}\{cm:UninstallProgram,{#AppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}";           Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
; « runas » fait apparaître l'invite administrateur de Windows pour cette seule
; commande : le reste de l'installation peut rester sans élévation. {username}
; est le compte qui lance l'installation. « Already a member » n'est pas une
; erreur, d'où le SilentlyContinue.
Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -Command ""Add-LocalGroupMember -SID 'S-1-5-32-559' -Member '{username}' -ErrorAction SilentlyContinue"""; Verb: runas; Flags: shellexec waituntilterminated runhidden; StatusMsg: "{cm:PerfGroupRun}"; Tasks: perfgroup
Filename: "{app}\{#AppExeName}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent
