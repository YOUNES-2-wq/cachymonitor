# CachyMonitor — notes pour Claude

Moniteur système gaming (Python + PySide6) pour Linux et Windows 11. `IS_WINDOWS` aiguille
chaque lecteur de capteurs ; interface, thèmes, langues (dictionnaire `TRANSLATIONS`) et
statistiques sont communs. `APP_VERSION` (dans `cachymonitor.py`) est la seule source du
numéro de version (le build Windows la lit).

## Organisation du code (découpé le 2026-11-14, après la 1.5.1)
`cachymonitor.py` ne garde que le point d'entrée : `APP_VERSION`, `MainWindow`, `main()`.
Le reste vit dans le dossier `cachymon/` (aucune logique changée, lignes déplacées) :
`config` (constantes, `IS_WINDOWS`, `APP_ROOT`), `i18n` (TRANSLATIONS, `tr`), `theme`,
`sensors` (CPU, RAM, GPU), `controllers`, `winshm` (mémoire partagée Afterburner/RTSS),
`game` (statistiques + MangoHud), `mangohud_conf`, `game_windows` (RTSS, PresentMon),
`sampler`, `widgets`, `debug`.
Pièges : une globale réécrite (`global X`) doit rester dans le module qui la définit, et
`PRESENTMON_STATE` se lit par `presentmon_state()` (dans `game_windows`), jamais par
`from ... import PRESENTMON_STATE`.
Publié en **1.5.2** (Linux seulement : release GitHub non « latest », AUR ; pas d'installateur
Windows). Vérifié sous Windows le 2026-11-14 (ruff, tests, capteurs, exe PyInstaller) ;
première version Windows découpée = **1.6.0**, qui inverse aussi la priorité des FPS. **Lire `docs/NOTE-DECOUPAGE-1.5.2.md`**
(carte des modules, changements de comportement, liste de vérifications Windows, dont
`build.ps1` et PyInstaller).

## Contrôles avant une release
- `ruff check .` (réglages dans `pyproject.toml`) et `python -m pytest -q` : doivent passer.
  Les tests (`tests/`) couvrent les calculs purs (FPS, lows, batterie Sony, couleurs,
  traductions, lecture de log MangoHud) ; la CI GitHub (`.github/workflows/tests.yml`) les lance.
- `tests/conftest.py` isole le journal de débogage (fixture `journal_isole`) : aucun test
  n'écrit dans le vrai `%LOCALAPPDATA%\CachyMonitor\debug.log`.
- Option `--debug` (ou `CACHYMONITOR_DEBUG=1`) : écrit les erreurs normalement avalées dans
  `~/.cache/cachymonitor/debug.log` (Windows : `%LOCALAPPDATA%\CachyMonitor\debug.log`).
  À demander aux testeurs Radeon/Intel avec la sortie de `scripts/hw-report.sh`.

## Avec qui on travaille
Younes (GitHub `YOUNES-2-wq`, AUR `younes-2`) : gamer, **pas développeur**. Toujours répondre
**en français**, expliquer simplement, demander avant les actions publiques.

## Distribution
- **AUR** `cachymonitor` (dépôt séparé `ssh://aur@aur.archlinux.org/cachymonitor.git`,
  PKGBUILD qui télécharge l'archive du tag GitHub) — en **1.5.2**.
- **winget** `YOUNES-2-wq.CachyMonitor` — en **1.6.0** (#480910 fusionnée) ; **1.7.0 soumise** : [#483266](https://github.com/microsoft/winget-pkgs/pull/483266), en attente (deux installateurs, `Scope: user` et `Scope: machine` avec `/ALLUSERS`) (manifestes dans
  `packaging/winget/manifests`, procédure dans `packaging/winget/README.md`).
- **Installateur Windows** : `packaging/windows/build.ps1` (PyInstaller en `--onedir`,
  puis Inno Setup). Le mode `--onefile` a été abandonné en 1.4.1 : son bootloader
  auto-extractible déclenchait des faux positifs antivirus heuristiques.
- La release GitHub v1.4.0 n'est volontairement **pas** marquée « latest » : elle n'a pas
  d'installateur Windows, et le README renvoie vers `releases/latest` pour le `.exe`.

## Matériel de test (le seul vérifié)
Ryzen 5 5600 + RTX 3060 ; CachyOS KDE Wayland et Windows 11 Pro 24H2 avec MSI Afterburner
+ RTSS. Manette : **DualSense (PS5)**, appairée en Bluetooth, câble USB-C possible.

## Manettes sous Windows (fait le 2026-10-02, 1.4.1)
La carte **MANETTE** fonctionne maintenant sur les deux OS. Sous Windows, deux sources :
XInput (`xinput1_4.dll`) pour les manettes Xbox, et HID brut (`setupapi` + `hid.dll`)
pour les manettes Sony, que Windows n'expose pas en XInput.

Trois pièges que seul le matériel a révélés, à ne pas réintroduire :
1. **Le bus ne se déduit pas du rapport.** En Bluetooth, la DualSense n'envoie d'elle-même
   qu'un rapport réduit portant le même identifiant `0x01` qu'en USB, et Windows complète
   toujours la lecture à la taille maximale déclarée : ni l'identifiant ni la longueur ne
   renseignent. Le chemin du périphérique, lui, est sans ambiguïté.
2. **En Bluetooth**, la batterie n'est que dans le rapport complet, qu'il faut *réclamer*
   (`HidD_GetInputReport` 0x31). Lire le rapport de calibration 0x05, l'astuce connue sur
   DualShock 4, ne fait PAS basculer la DualSense.
3. **En USB**, la manette refuse `GET_REPORT` (erreur 31) mais diffuse ses rapports en
   continu : lecture du flux en second recours, en asynchrone pour qu'une manette
   silencieuse ne fige pas le thread de mesure.

Vérifié sur la DualSense : Bluetooth 95 % en décharge, câble 100 % (la manette se déclare
pleine dès que son circuit de charge a fini, et le pilote Linux arrondit pareil).
`scripts/test_controllers.py` montre l'énumération, le rapport brut et le décodage.

**Non testé, faute de matériel** : DualShock 4, et les manettes Xbox via XInput. Le README
le dit explicitement — ne jamais le présenter comme testé.

## PresentMon sous Windows (1.5.0, 08/11/2026)
FPS sans Afterburner : `PresentMonGameReader` lance PresentMon 2.6.0 (Intel, MIT) en
sous-processus et lit son CSV sur stdout. `WindowsGameReader` montre PresentMon s'il
mesure en direct, sinon RivaTuner (ordre inversé en 1.6.0 ; 1.5.x : RivaTuner d'abord,
test `tests/test_priorite_windows.py`). Plan complet de sortie d'Afterburner : 1.5.1
fréquence CPU + NVML, 1.6.0 priorité inversée, 1.7.0 PawnIO (fait, voir plus bas),
2.0.0 retrait d'Afterburner — une étape par version, testée sur le PC de Younes.

Pièges vérifiés, à ne pas réintroduire :
1. **Afterburner ne publie « Framerate » que pour la fenêtre au premier plan** (FLT_MAX
   ou 0 sinon) : c'est pour ça que PresentMon prend le relais quand on clique ailleurs.
2. **Choix du jeu** : seulement la fenêtre au premier plan qui couvre tout son écran, hors
   `PRESENTMON_IGNORE`. Le mode de présentation « Hardware » ne suffit pas : un navigateur
   (Zen) y passe parfois et était pris pour un jeu.
3. **Lire le flux jusqu'au bout, même à l'arrêt** : un tuyau qu'on cesse de vider bloque
   PresentMon, qui ne quitte plus (5 s puis arrêt forcé).
4. stderr fusionné dans stdout (un seul tuyau, pas de blocage) ; images de plus d'une
   seconde écartées (jeu en pause, sinon fausse saccade).
5. Sans élévation, le compte doit être dans le groupe S-1-5-32-559 (case « perfgroup »
   de l'installateur), sinon « access denied ».
6. Tester à côté de l'appli installée : changer `PRESENTMON_SESSION`, sinon
   `--stop_existing_session` coupe la session de l'appli.

`build.ps1` télécharge PresentMon et vérifie SHA256 + signature Intel. Sur le PC de
Younes, `python` n'est que l'alias du Microsoft Store : le vrai est `py`. Avant le build :
`function global:python { & py @args }`.

## Fréquence CPU et NVML sous Windows (1.5.1, 14/11/2026)
- Fréquence CPU réelle sans Afterburner : `_PdhCpuFreq` lit le compteur PDH
  « % Processor Performance » (`PdhAddEnglishCounterW`, `PDH_FMT_NOCAP100`) multiplié
  par la fréquence de base. psutil ne donne que la base, figée. Afterburner en secours.
- GPU NVIDIA : NVML d'abord, chargé par chemin complet `System32\nvml.dll` (contre le
  détournement de DLL), `nvidia-smi` en secours. Premier appel ~1,3 s (init), puis ~0 ms.
- VRAM par `nvmlDeviceGetMemoryInfo_v2` (identique à nvidia-smi ; la v1 compte en plus
  la mémoire réservée par le pilote), repli v1. Touche aussi Linux et Flatpak.
- Validé sur le PC de Younes, avec et sans Afterburner. Seules la température et la
  conso CPU dépendent encore d'Afterburner (étape 1.7.0).

## Température et conso CPU par PawnIO (1.7.0, 17/11/2026)
- `cachymon/pawnio.py` : pilote PawnIO (namazso, signé Microsoft) + module officiel
  `AMDFamily17.bin` (PawnIO.Modules 0.2.11, LGPL 2.1). Lecture seule : Tctl par SMN
  0x59800, énergie paquet par MSR 0xC001029B (unité 0xC0010299). Mutex `Global\Access_PCI`
  partagé avec Afterburner/HWiNFO/LHM. Prioritaire sur Afterburner dans `WindowsCpuReader`.
- **Le pilote refuse tout process non élevé** (0x80070005). Choix de Younes : l'appli
  entière en admin. `cachymon/elevation.py` relance par ShellExecute « runas » avant Qt,
  seulement si TOUT est réuni (`should_elevate`) : case « Température CPU par PawnIO » des
  Options cochée (`pawnio_admin` dans QSettings, **décochée par défaut** : sinon tout
  possesseur de FanControl/LHM aurait l'UAC après une mise à jour winget), PawnIO + bon
  module + CPU AMD (`elevation_blocker()`, raison affichée en infobulle de la case grisée),
  exe dans **Program Files** (choix de Younes après la revue : depuis un dossier
  modifiable sans droits, un programme ordinaire pourrait remplacer un fichier et
  profiter du « Oui » à l'UAC ; pour la même raison, **jamais de relance depuis les
  sources**), compte admin à jeton restreint (`token_elevation_type()`, jamais sur un
  compte standard : la case est alors grisée avec la raison). Refus de l'UAC =
  comportement 1.6.0. `program_files()` et `elevation_blocker()` ne gardent en cache qu'une réponse définitive
  (registre du processeur, Program Files ou jeton illisibles = échec passager, réessayé :
  jamais gardé comme « pas un Ryzen » ni « driver introuvable »).
  `--elevated` empêche toute boucle ; `CACHYMONITOR_NO_ELEVATE=1` désactive.
- Code élevé : **jamais de variable d'environnement pour un chemin de sécurité** (un
  programme ordinaire peut les redéfinir dans HKCU\Environment). Program Files vient de
  HKLM (`program_files()`, ProgramFilesDir). DLL par chemin complet (InstallLocation, sinon
  Program Files\PawnIO), refusée hors de Program Files, dépendances limitées à son dossier
  + System32 (`winmode`). Module vérifié par SHA256 (`MODULE_AMD_SHA256`) avant l'UAC et
  avant chargement. Changer de version de modules = changer l'empreinte dans `pawnio.py`
  ET dans `build.ps1` (le build compare les deux et s'arrête s'ils divergent).
- Tctl : plage -49 °C par le bit RANGE_SEL **ou** les deux bits TJ_SEL (comme k10temp).
  Verrou `Global\Access_PCI` obligatoire (sinon PawnIO désactivé) ; verrou occupé ou
  lecture ratée = dernière valeur gardée 5 s ; au-delà, Afterburner prend le relais (mais
  pas les replis lents par PowerShell). Conso : même règle (seul le tout premier relevé,
  qui amorce le compteur d'énergie, vient d'Afterburner). Un échec de l'unité d'énergie
  ne coupe jamais la température. Un seul essai d'ouverture par session (voir « Échecs »).
- `CACHYMONITOR_DEBUG` ne passe pas l'UAC : `relaunch_command` le convertit en `--debug`.
- **Arguments de la ligne de commande** : la relance ne transmet que `--debug`
  (`relaunch_command`), et un process durci ne donne aucun argument à Qt
  (`qt_arguments()`) : Qt lit `-platformpluginpath`, `-plugin`... comme des chemins de
  DLL (revue finale du 17/11/2026 : n'importe quel programme pouvait lancer l'appli
  avec ces options et profiter du « Oui » à l'UAC). Tout nouvel argument transmis à la
  copie élevée doit être sur cette liste blanche.
- **Process durci** (`elevation.harden_environment()`, avant Qt, appelé seulement si
  `__name__ == "__main__"` : un import par les tests ne durcit rien) : s'applique si le
  process ouvrira PawnIO (`will_open_pawnio()` : copie relancée `--elevated` ET admin
  = `elevated_copy()`, ou admin lancé par l'utilisateur avec la case cochée, lue sans
  Qt par `pawnio.setting_in_registry()`, **et rien qui l'empêche** :
  `elevation_blocker()` exige aussi, pour l'exe, **le dossier exact où notre
  installateur l'a posé** (`pawnio.installed_here` : `InstallLocation` de la clé
  Uninstall de l'AppId dans HKLM, sous Program Files ; un sous-dossier de Program Files
  laissé modifiable par un autre logiciel ne suffit pas) ; les sources restent
  permises en admin, pour les tests). Admin lancé alors qu'une copie admin tourne
  (`DUPLICATE_ADMIN`, posé par `hold_admin_instance` si `ADMIN_MUTEX` existait déjà) :
  message « déjà lancé », compteur de plantages remis à 0, pas de seconde copie sur PawnIO. Puis `pawnio.mark_env_hardened()`. **PawnIO
  n'est ouvert que si `env_hardened()`** (condition de `_open`) : cocher la case en
  cours de session dans un admin non durci = « au prochain démarrage ». Un admin sans
  la case garde son environnement, comme en 1.6.0. **Exception** : une copie relancée
  (`elevated_copy()`) est toujours nettoyée et ne donne aucun argument à Qt, même si PawnIO
  est finalement refusé (registre illisible...) : elle tourne en administrateur ; seul le
  drapeau `env_hardened()` (condition d'ouverture de PawnIO) reste réservé à `will_open_pawnio()`.
  En administrateur, `find_presentmon()` ignore `CACHYMONITOR_PRESENTMON`.
  Raison : un process élevé hérite des variables de HKCU\Environment, modifiables par
  n'importe quel programme (QT_PLUGIN_PATH ferait charger une DLL en admin).
  `safe_environment()` = **liste blanche** : quelques textes inoffensifs (LANG,
  USERNAME, CACHYMONITOR_DEBUG..., et les réglages de taille d'affichage de Qt :
  QT_SCALE_FACTOR, QT_FONT_DPI...) ; **pas** les variables du lanceur PyInstaller
  (_PYI*, _MEI*). SystemRoot/windir, PATH (dossiers de Windows seulement), PSModulePath,
  ComSpec, USERPROFILE (via userenv, pas l'environnement), ProgramFiles, ProgramData,
  ALLUSERSPROFILE, CommonProgramFiles, ProgramFiles(x86) (lus dans HKLM,
  `_system_folders`) sont recalculés ; **pas** LOCALAPPDATA/APPDATA (dossiers de
  l'utilisateur, piégeables par un lien). TEMP = `Windows\SystemTemp` si on peut y
  écrire (`_writable_dir`), sinon `Windows\Temp`. QT_PLUGIN_PATH, QML2_IMPORT_PATH et
  `_MEIPASS` en tête du PATH (ce que pose le hook `pyi_rth_pyside6`) sont refaits depuis
  le dossier de l'appli. Le **dossier courant devient System32** (un programme lancé par
  son seul nom y est cherché avant le PATH). Vérifié le 17/11/2026 : l'exe ignore
  PYTHONPATH, et le lanceur de PyInstaller 6.22 (onedir) ignore _PYI_APPLICATION_HOME_DIR,
  _MEIPASS2, _PYI_ARCHIVE_FILE, _PYI_PARENT_PROCESS_LEVEL venus de l'extérieur (à
  revérifier si PyInstaller change de version majeure). Tout nouveau code qui lit une
  variable d'environnement doit en tenir compte.
- **Journal de débogage en admin** (tout admin, `debug.log_path`) : jamais de fichier
  (le dossier de l'utilisateur ne doit pas être écrit avec les droits administrateur) ;
  console s'il y en a une. L'exe n'en a pas : message au démarrage, `debug.unavailable()`.
  Sans admin : `%LOCALAPPDATA%`.
- **Plantage de la copie élevée** : `pawnio_relaunch_pending` (+1 avant chaque relance,
  remis à 0 par `confirm_elevated_start()` dès la première tentative d'ouverture de
  PawnIO jouée, sa première lecture comprise : `PAWNIO.tried()` dans `on_sample` ; ou à
  une fermeture normale, `aboutToQuit`, branché avant la fenêtre ; ou si la case est
  décochée avant). À `MAX_PENDING` = 2 : pas de nouvelle UAC, case décochée, message.
  Chaque confirmation retire **une** relance (une fois par process). Fin de session
  Windows (`commitDataRequest`) = pas un plantage non plus.
- **Une seule copie admin à la fois** : `ADMIN_MUTEX`, pris dès l'import par tout process
  durci (`hold_admin_instance()`) et gardé jusqu'à sa fermeture. Un lancement qui le voit
  (`_mutex_exists` : « accès refusé » = il existe, tenu par un process élevé) rend `BUSY`
  **avant** `should_elevate()` (ni seconde UAC, ni compteur touché) et `main()` affiche
  « déjà lancé ». Un double-clic pendant l'invite UAC peut en montrer une seconde ; la
  seconde copie élevée trouve le verrou pris (`DUPLICATE_ADMIN`) et se ferme avec le même
  message. Simplifié le 18/11/2026 : plus de `LAUNCHING_MUTEX`, de liste des process, de
  vérification de session ni d'élévation (les revues y trouvaient toujours des cas limites).
- **Liaisons ctypes de pawnio.py et elevation.py** : une seule par DLL, en cache, tous
  les types déclarés (bug n°3 ; les modules plus anciens, manettes, FPS, Afterburner,
  ont leurs propres liaisons). Elles vivent dans `cachymon/winapi.py` (aucune règle de
  sécurité, n'importe rien de l'appli) :
  `winapi.kernel32_api()` (verrous, dossiers système), `winapi.advapi32_api()`,
  `winapi.shell32_api()` (IsUserAnAdmin, ShellExecuteExW avec `winapi.ShellExecuteInfo`),
  `elevation._userenv_api()`.
  Seul appel à CreateMutexW : `winapi.create_mutex()` (`shared=True` pour
  `Global\Access_PCI` : accès complet à « Tout le monde », comme LibreHardwareMonitor,
  sinon créé en admin il fermerait l'accès aux autres outils). `winapi.hklm()` pour HKLM,
  `winapi.process_token()`, `winapi.cache_known` (garde une valeur lue, None = échec
  passager) et `winapi.cache_final` (la fonction rend `(valeur, définitive)` ;
  `elevation_blocker` l'utilise). Les règles (`is_admin`, `program_files`,
  `protected_folder`, `installed_here`...) restent dans `pawnio.py`. Les tests qui
  simulent ces liaisons patchent `winapi`, pas `pawnio`.
- **Échecs** (simplifié le 18/11/2026, choix de Younes) : **un seul essai d'ouverture par
  session**, aucun nouvel essai, aucun comptage sur plusieurs démarrages, aucune demande
  fenêtre/mesure (cocher ou décocher en cours de session prend effet au prochain
  lancement, la fenêtre le dit). Le pilote n'est touché que par le thread de mesure sous
  `_lock`. Une seule cause, `PawnIoCpu._failure`, posée par `_fail()` **avant** `_state`
  (la fenêtre lit les deux sans verrou) ; `failure_reason()` la rend quand l'ouverture a
  échoué. Durables (la case est décochée avec un message, `PAWNIO_FAILURE_MESSAGES`) :
  `UNSUPPORTED` (module refuse le processeur), `BAD_MODULE` (absent, illisible ou mauvaise
  empreinte), `MISSING_DRIVER` (PawnIOLib.dll introuvable), `DRIVER_REFUSED` (pawnio_load en
  erreur, DLL non chargeable ou sans une fonction : pilote trop ancien). Passagères
  (`PawnIoCpu.TRANSIENT` : la case reste, un message d'information, Afterburner reprend) :
  `PCI_BUSY` (verrou Global\Access_PCI d'un autre logiciel refusé) et `NO_RESPONSE`
  (exception à l'ouverture, pilote pas prêt). Registre du processeur muet : PawnIO
  simplement pas ouvert cette fois, sans message. `MainWindow._check_pawnio_started` juge
  une seule fois, après `PAWNIO.tried()`, et seulement dans un process durci ; la
  décision est testée sans Qt dans `tests/test_pawnio.py`. Message jamais dans `on_sample`
  (`QTimer.singleShot(0)` : boîte modale = relevés traités à rebours).
- **Case PawnIO des Options** : calculée (registre, empreinte du module, jeton) seulement
  Options ouvertes (`_pawnio_retext` ne pose que le texte tant que `options.isHidden()`),
  réévaluée à chaque ouverture. Jeton illisible (type 0) : raison neutre « impossible de
  vérifier », jamais « pas administrateur » ; `token_elevation_type()` et `cpu_is_ryzen()` ne
  gardent en cache qu'un résultat lu (décorateur `winapi.cache_known`, avec
  `cache_clear`). PawnIO n'est ouvert que si la case est cochée, en admin, durci,
  sur un Ryzen (AMD famille 17h à 1Ah, `ryzen_cpu()`, même règle dans le .iss).
- **PawnIO_setup refuse d'installer par-dessus une version existante** (« Please uninstall
  it first », lu dans le binaire 2.2.0 ; options : `-install -uninstall -silent
  -unrestricted -debuginfo`). Pilote trop ancien : message « le désinstaller dans les
  paramètres de Windows puis installer la dernière version depuis pawnio.eu ».
- Tester PawnIO depuis les sources : copier `AMDFamily17.bin` (et `PresentMon.exe`) à la
  racine du dépôt (gitignorés), puis lancer `pyw cachymonitor.py` depuis un **terminal
  administrateur** avec la case cochée (pas de relance automatique depuis les sources).
- Installateur : tâche « pawnio » décochée, seulement sur AMD, en installation « pour tous
  les utilisateurs », sans PawnIO déjà présent (même ancien : on ne désinstalle pas le
  pilote d'un autre logiciel). Installé dans `CurStepChanged(ssPostInstall)` ([Code],
  pas [Run]) : dossier vérifié (`AppInProgramFiles`, sinon message
  `PawnIONotProgramFiles`), `ExtractTemporaryFile` puis `PawnIO_setup.exe -install
  -silent` (2.2.0, SHA256 + signature namazso vérifiées par build.ps1) ; code de sortie
  (0, 3010, 1641 = succès) et présence de la DLL vérifiés, échec = message
  (`PawnIOFailed`, supprimable en silencieux). Fait aussi en silencieux si on le demande
  (`/TASKS=pawnio`). winget (silencieux) ne l'installe pas : README renvoie à
  `winget install namazso.PawnIO` et `--scope machine`.
- Bouton « À propos » dans les Options (1.7.0) : version, auteur, lien GitHub (non
  cliquable en mode admin, pour ne pas ouvrir le navigateur en admin), système, Python,
  Qt, mode admin.
- Validé sur le PC de Younes (build d'avant les revues 13 à 20) : identique à Afterburner
  (0,1 °C, ~1 W), avec et sans Afterburner, eFootball (anti-triche) OK. **Intel non pris
  en charge** (module IntelMSR jamais essayé, pas de matériel).

## Reste à faire
- Faux positifs antivirus : Windows Defender a retiré CachyMonitor de sa liste (confirmé par Younes le 2026-11-14). Le signalement WDSI est clos.
- La batterie des manettes Xbox attend une manette Xbox pour être vérifiée.

## Version Flathub (en cours, 04/10/2026)
**Règle de Flathub sur l'IA** (docs.flathub.org, "Generative AI policy", lue le 04/10/2026) :
le manifeste ne doit contenir **aucun contenu écrit ou assisté par IA** (la divulgation
n'y change rien) ; une IA ne doit ni ouvrir la PR de soumission ni écrire ses commits,
descriptions ou réponses de revue ; le code de l'appli généré par IA doit être déclaré,
avec son ampleur, et un relecteur peut refuser sans examen. **Claude n'écrit donc jamais
le manifeste, le `metainfo.xml` ni la PR** : Younes les écrit, Claude explique les champs
et relit ou débogue. Claude peut modifier le code de l'appli (à déclarer comme tel).

**Acquis** : identifiant `io.github.YOUNES_2_wq.CachyMonitor` (confirmé : `_` devient `-`
dans l'URL GitHub). Un Flatpak jetable (jamais à soumettre) a été construit avec le runtime
`org.kde.Platform` 6.11 et la base `io.qt.PySide.BaseApp` 6.11 ; construction par
`flatpak run org.flatpak.Builder --user --install --state-dir=...` (flatpak-builder n'est
pas installé en paquet, `--state-dir` doit être sur le même disque que le dossier de build).

**Résultats dans le sandbox**, vérifiés sur la RTX 3060 :
- GPU NVIDIA : `nvidia-smi` est absent, mais l'extension NVIDIA fournit `libnvidia-ml`.
  Corrigé en 04/10/2026 par une lecture NVML (ctypes) dans `cachymonitor.py`. OK.
- CPU, températures, manette (DualSense), `lspci` : OK. FPS : OK avec SuperTuxKart.
- `dmidecode` absent : la RAM (type, vitesse) restera à `—`, accepté.
- Logs MangoHud : le Goverlay de Younes écrit dans `~/.local/share/goverlay` ; le prototype
  a eu besoin de `--filesystem=xdg-data/goverlay:ro` (et `xdg-data/MangoHud:ro`).
  Le bouton "Activer le logging" écrit dans `~/.config/MangoHud` : bloqué par le sandbox,
  non testé. Un jeu Steam en Flatpak écrit ses logs dans `~/.var/app/com.valvesoftware.Steam/`.

**Reste à décider/faire** (par Younes) : quelles permissions demander (Flathub veut le
minimum et préfère les portails), écrire le manifeste, le `metainfo.xml` (captures dans
`docs/`, `content_rating` OARS, licence MIT, liste des versions), le `.desktop` et l'icône
renommés selon l'identifiant, tester avec `flatpak-builder-lint`, puis la PR sur
`github.com/flathub/flathub` (branche `new-pr`) ; revue humaine de quelques jours à
plusieurs semaines. Risque : refus à cause de la part d'IA. Prototype à désinstaller après :
`flatpak uninstall --user io.github.YOUNES_2_wq.CachyMonitor`.

## Plan de promotion (en pause, décidé le 04/10/2026)
Faites le 04/10/2026 : description GitHub anglaise + mots-clés ; README principal en
anglais (`README.fr.md` pour le français) ; toutes les releases passées en anglais seul
(Younes ne veut **qu'une langue** par release : l'anglais).
Reste, à reprendre après Flathub :
1. Post r/linux_gaming : appel aux testeurs Radeon/Intel, écrit en français pour sa
   relecture puis traduit. Dire ouvertement que l'appli est faite avec l'aide d'une IA.
2. r/cachyos + forum/Discord CachyOS, GamingOnLinux, r/pcgaming (Windows), fiche
   AlternativeTo (alternative à MSI Afterburner / MangoHud).
3. GIF ou vidéo de 30 s (jeu + CachyMonitor en double écran, batterie DualSense) en haut
   du README et dans les posts.
Point de départ chiffré (03/10/2026) : 97 téléchargements Windows, 3 étoiles, 12 visiteurs
uniques sur 14 jours, 0 vote AUR, aucune issue.

Pas d'emojis dans les textes rédigés pour Younes ou en son nom.
