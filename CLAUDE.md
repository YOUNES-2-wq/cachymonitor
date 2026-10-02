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
- **Installateur Windows** : `packaging/windows/build.ps1` (PyInstaller + Inno Setup).
- La release GitHub v1.4.0 n'est volontairement **pas** marquée « latest » : elle n'a pas
  d'installateur Windows, et le README renvoie vers `releases/latest` pour le `.exe`.

## Matériel de test (le seul vérifié)
Ryzen 5 5600 + RTX 3060 ; CachyOS KDE Wayland et Windows 11 Pro 24H2 avec MSI Afterburner
+ RTSS. Manette : **DualSense (PS5)**, appairée en Bluetooth, câble USB-C possible.

## Tâche en cours (2026-10-02) : la carte Manette sous Windows
La 1.4.0 a ajouté la carte **MANETTE** (modèle, câble USB ou Bluetooth, batterie en %,
⚡ en charge). `read_controllers()` ne marche que sous Linux (`/sys/class/input/js*` +
`power_supply`) et renvoie `[]` sous Windows. Chaque manette est un dict
`{"name", "bus": "usb"|"bluetooth"|None, "battery": int|None, "status": "charging"|…|None}` :
l'interface (`ControllerPanel`) n'a pas à changer.

À faire, sur une branche `manettes-windows` :
1. **Xbox via XInput** (`xinput1_4.dll` en ctypes, pas de nouvelle dépendance) :
   `XInputGetBatteryInformation` → type (filaire / sans fil) + 4 niveaux, à convertir
   comme `BATTERY_LEVELS`.
2. **DualSense / DualShock 4 via HID brut** (`hid.dll` + `setupapi.dll` en ctypes) :
   VID Sony `054C` (DualSense `0CE6`, Edge `0DF2`, DS4 `05C4`/`09CC`). Batterie et charge
   dans le rapport d'entrée ; la mise en page diffère entre USB et Bluetooth.
3. Un script `scripts/test_controllers.py` qui affiche ce que l'app lit, comme
   `test_afterburner.py` et `test_rtss.py`.
4. Tester sur la vraie DualSense (Bluetooth **et** câble), puis livrer une 1.4.x Windows :
   build, release marquée latest, mise à jour winget.

Ne jamais marquer « testé » ce qui n'a pas tourné sur du vrai matériel : le README
distingue soigneusement testé / écrit mais non testé.
