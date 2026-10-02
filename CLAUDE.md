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
  PKGBUILD qui télécharge l'archive du tag GitHub) — en **1.4.0**.
- **winget** `YOUNES-2-wq.CachyMonitor` — en **1.3.2** (manifestes dans
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
- Signaler les faux positifs antivirus à Microsoft une fois le nouvel installateur en
  ligne (`microsoft.com/en-us/wdsi/filesubmission`, profil « Software developer », en
  joignant l'URL du dépôt public). Avira ensuite, ce qui règle WithSecure du même coup.
- La batterie des manettes Xbox attend une manette Xbox pour être vérifiée.
