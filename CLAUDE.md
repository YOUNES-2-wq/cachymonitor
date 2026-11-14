# CachyMonitor — notes pour Claude

Moniteur système gaming en **un seul fichier** (`cachymonitor.py`, Python + PySide6) pour
Linux et Windows 11. `IS_WINDOWS` aiguille chaque lecteur de capteurs ; interface, thèmes,
langues (dictionnaire `TRANSLATIONS`) et statistiques sont communs. `APP_VERSION` est la
seule source du numéro de version (le build Windows la lit).

## Avec qui on travaille
Younes (GitHub `YOUNES-2-wq`, AUR `younes-2`) : gamer, **pas développeur**. Toujours répondre
**en français**, expliquer simplement, demander avant les actions publiques.

## Distribution
- **AUR** `cachymonitor` (dépôt séparé `ssh://aur@aur.archlinux.org/cachymonitor.git`,
  PKGBUILD qui télécharge l'archive du tag GitHub) — en **1.4.4**.
- **winget** `YOUNES-2-wq.CachyMonitor` — en **1.5.0** (1.5.1 soumise) (manifestes dans
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
sous-processus et lit son CSV sur stdout. `WindowsGameReader` montre RivaTuner s'il
mesure en direct, sinon PresentMon. Plan complet de sortie d'Afterburner : 1.5.1
fréquence CPU + NVML, 1.6.0 priorité inversée, 1.7.0 LibreHardwareMonitor + PawnIO,
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

## Reste à faire
- Faux positifs antivirus : signalement Microsoft **envoyé le 03/10/2026** (WDSI, ID
  `86cddc4f-775c-4be8-9480-4b3c481ce8ca`), réponse attendue par e-mail. Quand elle arrive,
  relancer VirusTotal sur l'installateur.
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
