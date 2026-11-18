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
french.PawnIOGroup=Température et consommation CPU sans MSI Afterburner (processeurs AMD Ryzen) :
english.PawnIOGroup=CPU temperature and power without MSI Afterburner (AMD Ryzen processors):
french.PawnIOTask=Installer le pilote PawnIO (signé par Microsoft ; demande les droits administrateur). Ensuite, cocher la case PawnIO dans les Options de CachyMonitor.
english.PawnIOTask=Install the PawnIO driver (signed by Microsoft; asks for administrator rights). Then tick the PawnIO box in CachyMonitor's Options.
french.PawnIORun=Installation du pilote PawnIO...
english.PawnIORun=Installing the PawnIO driver...
french.PawnIOFailed=L'installation du pilote PawnIO a échoué (code %1). CachyMonitor fonctionne quand même, avec MSI Afterburner pour la température CPU. Vous pourrez installer PawnIO plus tard depuis pawnio.eu.
french.PawnIONotProgramFiles=Le pilote PawnIO n'a pas été installé : CachyMonitor n'est pas dans Program Files, et il n'utilise PawnIO que depuis ce dossier protégé. Réinstallez CachyMonitor dans Program Files pour vous en servir.
english.PawnIONotProgramFiles=The PawnIO driver was not installed: CachyMonitor is not in Program Files, and it only uses PawnIO from that protected folder. Reinstall CachyMonitor in Program Files to use it.
english.PawnIOFailed=The PawnIO driver could not be installed (code %1). CachyMonitor still works, with MSI Afterburner for the CPU temperature. You can install PawnIO later from pawnio.eu.

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
; Sans ce groupe, PresentMon (lancé sans élévation) se voit refuser les traces
; ETW de Windows : « access denied ». Le groupe est désigné par son SID, car son
; nom est traduit dans chaque langue de Windows. Pour annuler plus tard, dans un
; terminal administrateur :
;   Remove-LocalGroupMember -SID S-1-5-32-559 -Member <nom du compte>
Name: "perfgroup"; Description: "{cm:PerfGroupTask}"; GroupDescription: "{cm:PerfGroupGroup}"
; PawnIO (1.7.0) : proposé seulement sur un processeur AMD, pour une installation
; « pour tous les utilisateurs » (Program Files : l'appli refuse de se relancer en
; administrateur depuis un dossier modifiable sans droits), et s'il n'est pas déjà
; installé (par LibreHardwareMonitor, FanControl...). Décoché par défaut : c'est un
; pilote, on le choisit en connaissance de cause. Il faut ensuite cocher la case
; PawnIO dans les Options de l'appli. La désinstallation de CachyMonitor le laisse
; en place (d'autres logiciels s'en servent) ; il a sa propre entrée dans
; « Applications installées ».
Name: "pawnio"; Description: "{cm:PawnIOTask}"; GroupDescription: "{cm:PawnIOGroup}"; Check: PawnIOWanted; Flags: unchecked

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
; Module PawnIO pour Ryzen (lecture seule) et installateur officiel du pilote, vérifiés
; par build.ps1. L'installateur du pilote n'est extrait (dans {tmp}, effacé à la fin)
; que si la tâche « pawnio » est choisie : voir CurStepChanged.
Source: "..\..\build\pawnio\AMDFamily17.bin";            DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\build\pawnio\PawnIO-modules-LICENSE.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\build\pawnio\PawnIO_setup.exe";           DestDir: "{tmp}"; Flags: dontcopy

[Icons]
Name: "{group}\{#AppName}";                 Filename: "{app}\{#AppExeName}"
Name: "{group}\{cm:UninstallProgram,{#AppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}";           Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
; « runas » fait apparaître l'invite administrateur de Windows pour cette seule
; commande : le reste de l'installation peut rester sans élévation. {username}
; est le compte qui lance l'installation. « Already a member » n'est pas une
; erreur, d'où le SilentlyContinue.
; skipifsilent (depuis la 1.5.1) : une installation silencieuse (winget, mise à jour
; automatique) ne doit jamais s'interrompre sur l'invite administrateur.
Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -Command ""Add-LocalGroupMember -SID 'S-1-5-32-559' -Member '{username}' -ErrorAction SilentlyContinue"""; Verb: runas; Flags: shellexec waituntilterminated runhidden skipifsilent; StatusMsg: "{cm:PerfGroupRun}"; Tasks: perfgroup
; Le pilote PawnIO n'est pas ici mais dans CurStepChanged ([Code]) : son code de
; sortie et sa présence après coup y sont vérifiés.
Filename: "{app}\{#AppExeName}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[Code]
// Même règle que l'appli (cachymon\pawnio.py, pawnio_dll) : PawnIO compte comme
// installé seulement si sa bibliothèque est sous Program Files, d'après son
// InstallLocation ou à l'emplacement par défaut. Sinon la case est proposée.
function PawnIOInstalled: Boolean;
var
  Loc, PF: String;
begin
  PF := AddBackslash(ExpandConstant('{commonpf64}'));
  Result := FileExists(PF + 'PawnIO\PawnIOLib.dll');
  if (not Result) and RegQueryStringValue(HKLM64,
      'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\PawnIO', 'InstallLocation', Loc) then
  begin
    // Chemin normalisé (« .. », barres obliques), comme abspath côté appli.
    Loc := AddBackslash(ExpandFileName(Loc));
    Result := (Pos(Lowercase(PF), Lowercase(Loc)) = 1) and FileExists(Loc + 'PawnIOLib.dll');
  end;
end;

// Même règle que l'appli (cachymon\pawnio.py, ryzen_cpu) : AMD de famille 17h à
// 1Ah (Ryzen), d'après « AMD64 Family 25 Model 33 Stepping 2 ».
function RyzenCpu: Boolean;
var
  Vendor, Ident, Digits: String;
  P, Family: Integer;
begin
  Result := False;
  if not RegQueryStringValue(HKLM64, 'HARDWARE\DESCRIPTION\System\CentralProcessor\0', 'VendorIdentifier', Vendor) then
    Exit;
  if (Vendor <> 'AuthenticAMD') or not RegQueryStringValue(HKLM64,
      'HARDWARE\DESCRIPTION\System\CentralProcessor\0', 'Identifier', Ident) then
    Exit;
  P := Pos('Family ', Ident);
  if P = 0 then
    Exit;
  Digits := '';
  // Borne testée à part : on ne lit jamais Ident[P] au-delà de la chaîne, même
  // si le « and » n'était pas évalué en court-circuit.
  for P := P + 7 to Length(Ident) do
  begin
    if (Ident[P] < '0') or (Ident[P] > '9') then
      Break;
    Digits := Digits + Ident[P];
  end;
  Family := StrToIntDef(Digits, 0);
  Result := (Family >= $17) and (Family <= $1A);
end;

// La case n'a de sens que si l'appli pourra s'en servir : installation pour tous
// les utilisateurs, Ryzen, et PawnIO pas encore là. Un PawnIO déjà installé, même
// ancien, n'est pas mis à jour : PawnIO_setup refuse d'installer par-dessus
// (« Please uninstall it first »), et désinstaller un pilote dont se servent
// peut-être FanControl ou LHM n'est pas à faire à leur place. L'appli, elle,
// conseille la mise à jour si le pilote refuse le module. Inno évalue ce Check des
// [Tasks] une seule fois, tôt : le dossier choisi ensuite est donc vérifié à
// part, au moment d'installer (AppInProgramFiles).
function PawnIOWanted: Boolean;
begin
  Result := IsAdminInstallMode and RyzenCpu and not PawnIOInstalled;
end;

// L'appli refuse le mode administrateur hors de Program Files (cachymon\pawnio.py,
// protected_folder) : installer le pilote pour un autre dossier ne servirait à
// rien. Évalué au moment d'installer, quand {app} est définitif.
function AppInProgramFiles: Boolean;
begin
  Result := Pos(Lowercase(AddBackslash(ExpandConstant('{commonpf64}'))),
                Lowercase(AddBackslash(ExpandFileName(ExpandConstant('{app}'))))) = 1;
end;

// Pilote PawnIO (tâche « pawnio ») : installé après les fichiers de l'appli, en
// mode silencieux (-silent : pas de fenêtre de PawnIO, même en installation
// silencieuse). Le résultat est vérifié (code de sortie, puis bibliothèque bien
// présente) : un échec est dit clairement au lieu d'une case grisée plus tard.
procedure CurStepChanged(CurStep: TSetupStep);
var
  Code: Integer;
begin
  if (CurStep <> ssPostInstall) or not WizardIsTaskSelected('pawnio') then
    Exit;
  if not AppInProgramFiles then
  begin
    // Case cochée mais dossier choisi hors de Program Files : on le dit.
    Log('PawnIO non installe : dossier hors de Program Files');
    SuppressibleMsgBox(CustomMessage('PawnIONotProgramFiles'), mbInformation, MB_OK, IDOK);
    Exit;
  end;
  WizardForm.StatusLabel.Caption := CustomMessage('PawnIORun');
  ExtractTemporaryFile('PawnIO_setup.exe');
  if not Exec(ExpandConstant('{tmp}\PawnIO_setup.exe'), '-install -silent', '', SW_HIDE,
              ewWaitUntilTerminated, Code) then
    Code := -1
  // 3010 / 1641 : installé, redémarrage demandé ou lancé (codes Windows de succès).
  else if (Code = 3010) or (Code = 1641) then
    Code := 0;
  if (Code = 0) and not PawnIOInstalled then
    Code := -2;
  if Code <> 0 then
  begin
    Log(Format('PawnIO_setup a echoue (code %d)', [Code]));
    SuppressibleMsgBox(FmtMessage(CustomMessage('PawnIOFailed'), [IntToStr(Code)]),
                       mbError, MB_OK, IDOK);
  end;
end;

