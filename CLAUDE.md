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
  PKGBUILD qui télécharge l'archive du tag GitHub) — en **1.4.2**.
- **winget** `YOUNES-2-wq.CachyMonitor` — en **1.4.1** (manifestes dans
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

## Reste à faire
- Faux positifs antivirus : signalement Microsoft **envoyé le 03/10/2026** (WDSI, ID
  `86cddc4f-775c-4be8-9480-4b3c481ce8ca`), réponse attendue par e-mail. Quand elle arrive,
  relancer VirusTotal sur l'installateur.
- La batterie des manettes Xbox attend une manette Xbox pour être vérifiée.
- `APP_VERSION` vaut encore `"1.4.1"` alors que le tag v1.4.2 existe : à monter à la
  prochaine version (et avant tout `metainfo.xml` Flathub, qui liste les versions).

## PROCHAINE SESSION (sur Linux) : version Flathub
Décidé le 04/10/2026 : Younes redémarre sur CachyOS pour attaquer Flathub, projet
ambitieux. Rien n'est commencé. Lui rappeler ce plan en ouvrant la session.

**Ce que Flathub demande** (à revérifier sur docs.flathub.org avant de commencer) :
1. Un identifiant d'app : `io.github.YOUNES_2_wq.CachyMonitor` (tiret du login remplacé
   par `_`, Flathub n'accepte pas `-` dans ce segment ; à confirmer).
2. Un manifeste Flatpak (`.yml`) : runtime `org.kde.Platform` 6.x, et PySide6 via la base
   `io.qt.PySide.BaseApp` (évite de compiler Qt). Python et psutil inutiles à ajouter sous
   Linux, à vérifier.
3. Un fichier AppStream `metainfo.xml` : description anglaise, captures (celles de
   `docs/`, en URL GitHub brutes), liste des versions, `content_rating` OARS, licence MIT.
4. Fichier `.desktop` et icône renommés selon l'identifiant ; l'icône SVG existe déjà.
5. Tester en local : `flatpak-builder --user --install`, puis `flatpak-builder-lint`.
6. Soumission : PR sur `github.com/flathub/flathub` (branche `new-pr`). Revue humaine,
   compter des jours à des semaines. Le dépôt Flathub de l'app est ensuite à entretenir.
7. **Politique IA** : vérifier ce que Flathub dit des applis écrites avec une IA avant
   d'investir du temps. Rester transparent, comme dans le README.

**Ce que le bac à sable (sandbox) va casser, capteur par capteur** — le gros du travail :
- `/proc/stat`, `/proc/meminfo`, `/sys` (hwmon, cpufreq, amdgpu, power_supply des
  manettes) : lisibles dans le sandbox, a priori OK, à tester.
- **`nvidia-smi`** : absent du runtime. Peut-être fourni par l'extension
  `org.freedesktop.Platform.GL.nvidia-*` ; sinon `flatpak-spawn --host` (demande
  `--talk-name=org.freedesktop.Flatpak`, permission que Flathub accepte mal), ou NVML
  via `libnvidia-ml.so`. Point le plus incertain.
- **Logs MangoHud** : `--filesystem=xdg-data/MangoHud:ro` pour les lire, et
  `xdg-config/MangoHud` en écriture pour le bouton « Activer le logging ». Attention :
  un jeu lancé via Steam en Flatpak écrit ses logs dans `~/.var/app/com.valvesoftware.Steam/`.
- **`lspci`** (nom du GPU) : absent ; lire `/sys/bus/pci` + `pci.ids`, ou embarquer pciutils.
- **`dmidecode`** (type/vitesse RAM) : demande root, impossible en Flatpak. Accepter `—`.
- Réglages (QSettings) : redirigés vers `~/.var/app/<id>/`, rien à faire.
- `IS_WINDOWS` intact : Flatpak ne concerne que Linux.

**Ordre conseillé** : construire le Flatpak en local et regarder ce qui affiche `—`, avant
d'écrire la moindre ligne pour Flathub.

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
