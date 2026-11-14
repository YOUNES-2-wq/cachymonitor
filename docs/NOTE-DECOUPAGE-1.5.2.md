# Note pour la session Windows : découpage du code (version 1.5.2, 2026-11-14)

Écrite par la session Linux à l'attention de la session Windows (et de tout Claude qui
reprend le projet). À lire AVANT de toucher à `cachymonitor.py` : il n'est plus le seul
fichier de code.

## En deux phrases
`cachymonitor.py` (4215 lignes en 1.5.1) a été découpé : il ne contient plus que la fenêtre
principale et le démarrage, le reste est dans le dossier `cachymon/`. Aucune logique n'a
été changée, les lignes ont seulement été déplacées (vérifié par comparaison des définitions
avant et après) ; le découpage n'a été testé que sous Linux, jamais sous Windows.

## Ce qui est publié
- Version **1.5.2**, tag `v1.5.2`, release GitHub **non marquée « latest »** : v1.5.1 reste
  la dernière version Windows, il n'y a pas d'installateur 1.5.2.
- AUR `cachymonitor` en 1.5.2 (le PKGBUILD copie maintenant `cachymon/*.py`).
- winget : pas touché, toujours 1.5.1.
- Le numéro **1.6.0 reste réservé** au plan Windows (priorité inversée PresentMon/Afterburner).
  La prochaine version Windows doit donc être 1.6.0, qui contiendra le découpage.

## Où est passé chaque morceau (fichiers dans `cachymon/`)
| Module | Contenu |
|---|---|
| `config.py` | `IS_WINDOWS`, `_NO_WINDOW`, `APP_ROOT`, toutes les constantes (HISTORY, WIN_POLL_MS, FPS_*, mémoire partagée...), `plausible_fps/temp`, `asset_dir`, `_num`, `_powershell`, `_as_bool`, `_read_first` |
| `i18n.py` | `TRANSLATIONS`, `tr`, `set_language`, `_system_language`, `LANG_*` |
| `theme.py` | `THEMES`, `col`, `set_palette`, `system_theme`, `_windows_light_theme`, `temp_role` |
| `winshm.py` | `_kernel32`, `_read_shared_memory`, `AfterburnerReader`, `AB` (mémoire partagée Afterburner) |
| `sensors.py` | CPU Linux et Windows (`LinuxCpuReader`, `WindowsCpuReader`, `_PdhCpuFreq`, LibreHardwareMonitor, WMI, ACPI), RAM, noms matériel, tous les GPU (`_gpu_nvidia`, NVML, `_gpu_amd`, `_gpu_intel`, `_gpu_afterburner`, `read_gpu`) |
| `controllers.py` | manettes : Linux (`/sys`), HID Sony, XInput, `read_controllers` |
| `game.py` | `game_stats`, `_percentile`, `MangoHudGameReader`, `bottleneck` |
| `mangohud_conf.py` | config MangoHud (`enable_mangohud_logging`, bouton HUD) et `no_game_text` |
| `game_windows.py` | `RtssGameReader`, `_GamePoller`, tout PresentMon (`PresentMonGameReader`, `find_presentmon`, `_foreground_fullscreen`...), `WindowsGameReader`, `make_game_reader` |
| `sampler.py` | thread `Sampler` |
| `widgets.py` | Sparkline, FrametimeGraph, jauges, `GamePanel`, `BatteryBar`, panneau manettes |
| `debug.py` | journal de debug (nouveau) |

Restent dans `cachymonitor.py` : `APP_VERSION`, `DropDownComboBox`, `MainWindow`,
`build_palette`, `build_style`, `main`. **`APP_VERSION` doit rester là** : `build.ps1` la lit
par une expression régulière sur ce fichier.

## Changements de comportement (les seuls)
1. **`PRESENTMON_STATE`** : une globale réécrite en cours de route. Dans `game_windows.py`,
   elle est modifiée par `global PRESENTMON_STATE`. Pour la LIRE ailleurs, appeler
   `presentmon_state()` ; ne jamais faire `from .game_windows import PRESENTMON_STATE`
   (la valeur resterait figée à « absent »). `no_game_text()` (dans `mangohud_conf.py`)
   fait l'import dans la fonction, uniquement sous Windows.
   Même règle pour toute globale réécrite : elle reste dans le module qui la définit.
2. **Chemins** : `__file__` a changé de dossier. `APP_ROOT` (dans `config.py`) = dossier qui
   contient `cachymonitor.py`. `asset_dir()` et `find_presentmon()` s'en servent. Cas à
   vérifier sous Windows : l'exe PyInstaller (`sys.frozen`), où `asset_dir()` garde son
   chemin `_MEIPASS` habituel.
3. **`cachymonitor.py` ajoute son propre dossier au `sys.path`** en tête (pour que
   `cachymon/` soit trouvé même en mode isolé `python -I`).
4. **Option `--debug`** (ou variable `CACHYMONITOR_DEBUG=1`) : écrit les erreurs jusque-là
   avalées dans `~/.cache/cachymonitor/debug.log`, Windows : `%LOCALAPPDATA%\CachyMonitor\debug.log`.
   Sans l'option, rien ne change. Appels `debug_exc("...")` ajoutés dans les `except` de
   `sampler`, `controllers`, `sensors`, `winshm`, `game_windows` (le `TimeoutExpired` de
   l'arrêt de PresentMon n'est volontairement pas journalisé).

## À FAIRE sous Windows avant de publier la 1.6.0 (rien n'a été vérifié)
1. `git pull`, puis `python -m pip install ruff pytest` et lancer `ruff check .` et
   `python -m pytest -q` : ils doivent passer (58 tests).
2. Lancer l'appli depuis les sources (`python cachymonitor.py`) : jauges, FPS RivaTuner,
   PresentMon, fréquence CPU, GPU NVIDIA, manette DualSense.
3. **`packaging/windows/build.ps1`** : PyInstaller doit trouver le dossier `cachymon/`.
   Il est lancé sur `cachymonitor.py` sans `--paths` ni `--hidden-import` ; il devrait
   suivre les imports tout seul (y compris `from .game_windows import presentmon_state`,
   fait dans une fonction), mais ce n'est PAS vérifié. Si l'exe plante avec
   `ModuleNotFoundError: cachymon...`, ajouter `--paths $root` et `--hidden-import` pour
   les modules manquants (`cachymon.game_windows`, `cachymon.winshm`, `cachymon.controllers`...).
   Mettre aussi à jour les commentaires de `build.ps1` qui parlent d'un seul fichier.
4. Tester l'installateur construit sur une machine propre si possible, et lancer le
   scan VirusTotal : un exe qui change de structure peut refaire apparaître des alertes.
   (Windows Defender a retiré CachyMonitor de sa liste d'alertes le 2026-11-14.)
5. Si un lecteur est muet : relancer avec `--debug` et lire le journal.

## Nouveautés sans lien avec Windows
- `tests/` (58 tests purs), `pyproject.toml` (réglages ruff/pytest), CI GitHub
  `.github/workflows/tests.yml` (Ubuntu seulement : ne voit pas les bugs Windows).
- `scripts/hw-report.sh` réparé (il appelait une classe qui n'existait plus) ; il active le
  journal de debug et l'affiche. À demander aux testeurs Radeon/Intel.
- `scripts/test_controllers.py` adapté aux modules (il regroupe `config` et `controllers`).
- Le prototype Flatpak jetable est ignoré par git ; son install copie aussi `cachymon/`.

## Règle pour la suite
Un nouveau lecteur de capteur va dans le module de son thème (`sensors.py`,
`controllers.py`, `game_windows.py`), pas dans `cachymonitor.py`. Un nouveau test va dans
`tests/` s'il ne demande ni matériel ni écran.
